#!/usr/bin/env python3
"""
patch_env_unlock.py  -  Unlock an Amlogic (sabrina / S905X2/Y2/X3-class, Android
legacy-env lock) U-Boot environment image and apply a couple of dev-friendly
boot tweaks, fixing the CRC32 header(s) afterwards.

This targets devices whose bootloader reads the lock state from the `lock` env
variable via get_lock_data() (CONFIG_AML_ANTIROLLBACK *not* built), i.e. the
non-RPMB generation. It does NOT work on S905X4/Y4-class bootloaders that store
lock state in RPMB via SMC.

What it does (per 64 KiB env copy that contains a `lock` variable):
  1. lock          : flip unlock_ability=1, lock_state=0, lock_critical_state=0
  2. bootdelay     : set to N seconds (default 3) so you can break into the
                     u-boot console over UART. sabrina uses non-keyed autoboot
                     (abortboot_normal), so any of Enter/space/Ctrl+C stops it
                     during the window -- no magic stop-key env needed.
  3. upgrade_key   : remap the GPIOAO_10 button so a press drops into `fastboot`
                     (bootloader mode) instead of the USB recovery/burn path.
Each of 2/3 can be turned off; arbitrary extra vars can be set with --set.

Env layout assumed (matches these images):
  each 64 KiB (0x10000) copy =
    [0x0 : 0x4]      little-endian CRC32
    [0x4 : 0x10000]  NUL-separated "key=val" data (CRC is computed over this),
                     list ends at an empty entry, remainder zero-padded.
  Copy 0 at 0x0; optional redundant copy at 0x10000 (CRC done independently).

The 8-char `lock` value maps to Amlogic's LockData_t, one char per byte:
  [0] version_major  [1] version_minor  [2] unlock_ability
  [3] reserved1      [4] lock_state      [5] lock_critical_state
  [6] lock_bootloader[7] reserved2
Unlock = unlock_ability '1', lock_state '0', lock_critical_state '0'.
"""

import argparse
import binascii
import struct
import sys

ENV_COPY_SIZE = 0x10000            # 64 KiB per copy
CRC_LEN       = ENV_COPY_SIZE - 4  # 0xFFFC bytes, from +0x4 to +0x10000

# LockData_t char positions within the 8-char `lock` value
UNLOCK_ABILITY      = 2
LOCK_STATE          = 4
LOCK_CRITICAL_STATE = 5

# Button remap: GPIOAO_10 is the single physical button. Keep the gpio probe,
# swap the action from `recovery_from_udisk` (USB upgrade/"burn") to `fastboot`.
# storeargs has already run in `preboot` before upgrade_key, so bare `fastboot`
# is safe -- it's exactly how switch_bootmode enters fastboot on this build.
UPGRADE_KEY_FASTBOOT = (
    b"if gpio input GPIOAO_10; then echo GPIOAO_10 pressed;fastboot;fi;"
)


def parse_env(region):
    """Parse a CRC'd env region (the bytes after the 4-byte CRC) into an ordered
    list of (key, value) byte pairs. Stops at the empty-entry terminator."""
    entries = []
    i = 0
    while i < len(region):
        j = region.find(b"\x00", i)
        if j == -1 or j == i:      # no more / empty entry == end of list
            break
        k, _, v = region[i:j].partition(b"=")
        entries.append((k, v))
        i = j + 1
    return entries


def serialize_env(entries):
    """Rebuild the CRC region: each 'key=val' terminated by NUL, zero-padded to
    CRC_LEN. The first pad NUL doubles as the list's empty terminator."""
    blob = b"".join(k + b"=" + v + b"\x00" for k, v in entries)
    if len(blob) >= CRC_LEN:
        raise ValueError(f"env data ({len(blob)} bytes) does not fit in "
                         f"{CRC_LEN:#x} with room for the terminator")
    return blob + b"\x00" * (CRC_LEN - len(blob))


def set_var(entries, key, value, *, create=False):
    """Replace key's value in place (preserving order); append if absent and
    create=True. Returns (old_value_or_None)."""
    for idx, (k, v) in enumerate(entries):
        if k == key:
            entries[idx] = (k, value)
            return v
    if create:
        entries.append((key, value))
        return None
    return None


def unlock_lock_value(val):
    """Return the unlocked 8-digit lock value, validating the input."""
    if len(val) != 8 or not all(c in b"0123456789" for c in val):
        raise ValueError(f"lock value is not 8 digits: {bytes(val)!r}")
    v = bytearray(val)
    v[UNLOCK_ABILITY]      = ord("1")
    v[LOCK_STATE]          = ord("0")
    v[LOCK_CRITICAL_STATE] = ord("0")
    return bytes(v)


def patch_copy(data, base, extra_sets, bootdelay, button_fastboot, verbose=True):
    """Patch one 64 KiB copy. Returns the new CRC, or None if this copy has no
    'lock=' variable (i.e. it's padding, not a real env copy)."""
    entries = parse_env(bytes(data[base + 4: base + ENV_COPY_SIZE]))
    if not any(k == b"lock" for k, _ in entries):
        return None

    changes = []

    old_lock = dict(entries).get(b"lock")
    new_lock = unlock_lock_value(old_lock)
    set_var(entries, b"lock", new_lock)
    changes.append(f"lock {old_lock.decode()} -> {new_lock.decode()}")

    if bootdelay is not None:
        bd = str(bootdelay).encode()
        old = set_var(entries, b"bootdelay", bd, create=True)
        changes.append(f"bootdelay {None if old is None else old.decode()} -> {bd.decode()}")

    if button_fastboot:
        old = set_var(entries, b"upgrade_key", UPGRADE_KEY_FASTBOOT, create=True)
        changes.append("upgrade_key -> button boots to fastboot"
                       + ("" if old is not None else " (created)"))

    for k, v in extra_sets:
        old = set_var(entries, k, v, create=True)
        changes.append(f"{k.decode()} {'(new)' if old is None else '->'} {v.decode()}")

    region = serialize_env(entries)
    data[base + 4: base + ENV_COPY_SIZE] = region
    crc = binascii.crc32(region) & 0xFFFFFFFF
    data[base:base + 4] = struct.pack("<I", crc)

    if verbose:
        print(f"  copy @ {base:#08x}: {len(entries)} vars, CRC32 = {crc:08X}"
              f"  (header {' '.join('%02X' % b for b in data[base:base+4])})")
        for c in changes:
            print(f"      - {c}")
    return crc


def parse_set_arg(s):
    if "=" not in s:
        raise argparse.ArgumentTypeError(f"--set needs KEY=VALUE, got {s!r}")
    k, _, v = s.partition("=")
    if not k:
        raise argparse.ArgumentTypeError("--set key is empty")
    return (k.encode(), v.encode())


def main():
    ap = argparse.ArgumentParser(
        description="Patch Amlogic U-Boot env: unlock bootloader + boot tweaks.")
    ap.add_argument("image", help="env image file")
    ap.add_argument("-o", "--output", help="write to this file instead of in place")
    ap.add_argument("--copies", type=int, default=0,
                    help="number of 64KiB copies to patch (default: all present)")
    ap.add_argument("--bootdelay", type=int, default=3, metavar="SECS",
                    help="set bootdelay for the UART console break (default: 3)")
    ap.add_argument("--no-bootdelay", action="store_true",
                    help="leave bootdelay untouched")
    ap.add_argument("--keep-button", action="store_true",
                    help="leave upgrade_key (the GPIOAO_10 button) untouched")
    ap.add_argument("--unlock-only", action="store_true",
                    help="only patch the lock bits; leave bootdelay and the "
                         "button (upgrade_key) untouched (same as "
                         "--no-bootdelay --keep-button)")
    ap.add_argument("--set", action="append", type=parse_set_arg, default=[],
                    metavar="KEY=VALUE", dest="sets",
                    help="set an arbitrary env var (repeatable; creates if absent)")
    ap.add_argument("--no-backup", action="store_true",
                    help="do not write a .bak when patching in place")
    args = ap.parse_args()

    bootdelay = None if (args.no_bootdelay or args.unlock_only) else args.bootdelay
    button_fastboot = not (args.keep_button or args.unlock_only)

    with open(args.image, "rb") as f:
        data = bytearray(f.read())

    if len(data) < ENV_COPY_SIZE:
        sys.exit(f"error: image is {len(data)} bytes, smaller than one {ENV_COPY_SIZE:#x} copy")

    slots = len(data) // ENV_COPY_SIZE
    print(f"image: {args.image} ({len(data)} bytes, room for {slots} x {ENV_COPY_SIZE:#x} copies)")

    # The real env copies are the leading, contiguous slots that contain a
    # 'lock=' variable; the rest of a larger partition is just padding. With
    # --copies N we force exactly N leading slots instead of auto-detecting.
    bases = []
    for i in range(slots):
        base = i * ENV_COPY_SIZE
        if args.copies:
            if i >= args.copies:
                break
        elif not any(k == b"lock" for k, _ in
                     parse_env(bytes(data[base + 4: base + ENV_COPY_SIZE]))):
            break
        bases.append(base)

    patched = 0
    for base in bases:
        if patch_copy(data, base, args.sets, bootdelay, button_fastboot) is not None:
            patched += 1
        else:
            sys.exit(f"error: copy @ {base:#x} has no 'lock=' variable (reduce --copies)")

    if patched == 0:
        sys.exit("error: no 'lock=' variable found - is this really the env partition?")

    # verify the copies we patched
    for base in bases:
        stored = struct.unpack("<I", data[base:base + 4])[0]
        calc = binascii.crc32(bytes(data[base + 4: base + ENV_COPY_SIZE])) & 0xFFFFFFFF
        if stored != calc:
            sys.exit(f"error: CRC verify failed for copy @ {base:#x}")

    out = args.output or args.image
    if not args.output and not args.no_backup:
        with open(args.image + ".bak", "wb") as f:
            f.write(open(args.image, "rb").read())
        print(f"backup: {args.image}.bak")
    with open(out, "wb") as f:
        f.write(data)
    print(f"wrote:  {out}  ({patched} copy/copies patched, all CRCs verified)")


if __name__ == "__main__":
    main()
