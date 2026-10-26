# sabrina-unlock-v2: (New!) Bootloader unlock for the Chromecast with Google TV

An exploit chain intended to allow one to run a custom OS/unsigned code on the Chromecast with Google TV (CCwGTV).

This uses [GhostLock](https://nvd.nist.gov/vuln/detail/cve-2026-43499) to attain root access, then patches the `env partition`, and uses a creative method to avoid Rescue Party wiping the device and resetting the `env` partition.

# Standard Disclaimer

You are solely responsible for any potential damage(s) caused to your device by this exploit.

# Requirements

- Chromecast With Google TV (sabrina) running `UTTC.250917.004` (Security Patch Level: 2025-10-01)
- A USB-C to C cable - USB-A to C will not work, it cannot provide sufficient power to boot the device to Android
- A PC running some flavor of 64-bit GNU Linux with `python3` installed
- `adb`, `fastboot`, & `mke2fs` installed from the [SDK Platform tools](https://developer.android.com/studio/releases/platform-tools)

# FAQ

Can I flash LineageOS once I do this?

- **NO**
  **Important Note:** Do **not** try to flash LineageOS 22.2 build on the device in this state! You _will_ brick.
  LineageOS 22.2 `sabrina` builds is designed for the older Android 12 bootloader, and as such flashes the matching bootloader.

  Anti-Rollback (ARB) **will brick your device** if you flash LineageOS 22.2 builds.

  We are actively working on LineageOS 24.0 utilizing the Android 14 bootloader and Linux 5.15, but it is not ready yet - no ETA either.

Does unlocking the bootloader void my warranty on this device?

- Probably, assume so. Or just flash stock and lock your bootloader before RMA. The exploit itself leaves no traces.

Does unlocking the bootloader break DRM in any way?

- Nope, just like unlocking a Pixel device officially.

Can I OTA afterwards?

- NO - It will relock your bootloader, and if you've made any modifications, brick you pretty hard. If you manage to do this, re-running the exploit won't be possible either, as OTA's both relock the bootloader and set a burn-mode password.

Can I use stock?

- Yes, but avoid taking any OTA served by the `SetupWraith` application, or block Google's OTA servers via your router's DNS.

Can I go back to stock after installing custom OS's?

- Yeah, totally, here's a full "[OTA Image](https://android.googleapis.com/packages/ota-api/package/0d0a14a015085ddff485765a28559bcd858d3018.zip)" You can install this via the stock recovery. The patch level of this build is `2025-10-01`.

Can I relock the bootloader?

- Sure, just make sure you're not modified when you do.

I've run the exploit 10 times and it isn't working yet!

- Swap USB ports/cables, and keep trying, for some people it takes only one attempt, for others it takes several attempts.

# Content
* /images/: Contains helpful images and dumps from the device
  * boot.img - The stock `UTTC.250917.004` boot image for recovery or rooting via Magisk
  * bootloader.img - The stock `UTTC.250917.004` bootloader image for recovery/research
  * recovery.img - The stock `UTTC.250917.004` recovery image for recovery or reflashing stock images via full OTA
  * env.img.bak - One of my broken devices `env` image in case someone destroys/loses theirs - it has some identifiers like MAC, Serial Number, etc. but I don't care as the board associated to it is broken
* /scripts/: Scripts used to create the images in this repo and that will be flashed to the device by `unlock.sh`
* /unlock.sh: Bash script to bootloader unlock CCwGTV 4K (sabrina) devices

# Guide
1. Unplug the CCwGTV 4K from everything
2. Clone/Download this repo locally, and change your shell's directory to it
4. Connect your CCwGTV 4K to your host Linux machine via a USB-C to C cable and let it boot fully
5. Enable Developer Options by opening the Settings app, navigating to "System" -> "About", then slicking "Android TV OS Build" 7 times. Then navigate back to "System" and into "Developer Options", where you will toggle "USB Debugging" on, and then accept the prompt that appears onscreen selecting the "Always allow" checkbox
6. Execute the **unlock.sh** script on your host and follow the instructions it provides.

# Notices
This exploit chain modifies the content of the `env` partition to unlock the bootloader and make recovery of the device easier. Therefore, it would be ill advised to do any of the following:
- Modify contents of the `env` partition
- Don't OTA! Each OTA relocks the device's bootloader upon install. Additionally, the February update enforces a password to interact with Amlogic's burn-mode, which effectively mitigates this exploit, as we can't interact with the device while it's in burn-mode.

# Explanation

See the whitepaper on my blog [here](https://oddsolutions.github.io/Chromecast-with-Google-TV-4K-Secure-Boot-Bypass-v2/).

# Credits
- Nolen Johnson (npjohnson), Jan Altensen (Stricted), and Ray Volpe (Functioner): Theorizing, developing, and chaining together these vulnerabilities into an exploit chain.
- [k-o-n-t-o-r](https://github.com/k-o-n-t-o-r) (and Claude) for their awesome sabrina-tailored [GhostLock implementation](https://github.com/k-o-n-t-o-r/ghostlock-sabrina).
- BigEmpty @ XDA - The pointer on the dual environments contained in the `env` image, as well as confirming CRC calculation methods
- P0werpl @ XDA - Pointing me at the GhostLock implementation and testing the patching method
- Brian Light - Whitepaper QA/Review

# Special Thanks
- My product security consulting team at [LevelBlue](https://www.levelblue.com/) - So proud of the amazing team we're building, and the amazing team members

# Contribute to FOSS development on this device
- U-Boot: [sabrina-uboot](https://github.com/npjohnson/android_external_u-boot)
- Android: [android_device_google_sabrina](https://github.com/LineageOS/android_device_google_sabrina)
- GNU/Linux: [sabrina-linux](https://github.com/frederic/sabrina-linux)

