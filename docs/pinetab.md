# PineTab — the Lenovo Tab M9 as a Pine Box terminal

A record of turning a stock Lenovo Tab M9 into a dedicated Pine Box kiosk: what
the device is, what was found on it, what was built to manage it, and what has
deliberately not been done yet. Written as the work happened, on 2026-09-10.

The aim is a tablet that boots straight into Pine Box and is a limb of the
station — listen, work the deck, open every console, and play the air back
through a sampler — with no Google account, no Lenovo shell, and no home screen.

---

## 1. The device

| | |
| --- | --- |
| Model | Lenovo Tab M9, **TB310FU** (Wi-Fi, 4 GB / 64 GB) |
| Serial | `HA1Y7RCV` |
| Panel serial | `8SSP69A6PVC1MF1545L22CL` |
| SoC | MediaTek **MT6768** (`t6100a_wifi`), USB VID `0E8D` |
| Android | 13, SDK 33, build `TP1A.220624.014` |
| Shipped build | `TB310FU_USR_S000914_2601052017_mp1V969_ROW` |
| Partition layout | **A/B**, 2 slots, booted on slot `a`, dynamic `super` |
| Bootloader | `t6100a_wifi-4babc561b-20250515134948-20` |
| Warranty | expired 2025-08-13 — unlocking forfeits nothing that remained |

Two facts shape everything that follows. It is an **A/B device with a dynamic
super partition**, so any GSI has to be the arm64 A/B variant and images go to
the active slot. And its bootloader reports `max-download-size: 0x8000000`
(128 MB), while `super.img` is 6.28 GB — so that partition can only be written
in sparse chunks.

## 2. Getting the tablet to talk

The tablet was connected by USB with USB debugging enabled, and **nothing
happened**. `adb devices` was empty; not `unauthorized`, simply absent.

The cause was not the tablet. **There was no adb on the machine at all** — no
`platform-tools` in Program Files, the local SDK path, or Downloads. The
"Allow USB debugging?" dialog with its RSA fingerprint is raised *by an ADB
server asking the device for permission*. With no server, nothing ever asked,
so no prompt was ever shown. Installing Google's platform-tools (37.0.1,
extracted to `C:\_tools\platform-tools`) and running `adb devices` produced the
prompt immediately.

Worth keeping, because the symptom points the wrong way: **an empty device list
means Windows cannot see an ADB interface; `unauthorized` means it can, and is
waiting on a human.** They are different problems and only the second one is
about the tablet.

Windows enumerated the device twice under different product ids — `PID_201D` as
a composite (MTP + ADB) and `PID_201C` as a plain `Android ADB Interface`.
Windows already had drivers bound for both. A `Present: False` entry in
`Get-PnpDevice` is a *remembered* device, not a connected one; the live one is
found with `-PresentOnly`.

The RSA prompt then sat unaccepted for a while because **it does not render
while the screen is locked or while a system update is applying.** The transport
id changing (1 → 2) is the tell that the device re-enumerated across a reboot.

Once accepted:

```
HA1Y7RCV   device   product:TB310FU model:TB310FU device:TB310FU
```

## 3. The gate that mattered: OEM unlocking

The single biggest risk to the whole plan was that **OEM unlocking would be
greyed out**. Lenovo and MediaTek tablets frequently lock that toggle until the
device has been online for some time and sometimes until an account has signed
in — which is in direct tension with wanting no Google account on it. If it will
not move, the custom-ROM route is simply unavailable.

It moved:

```
sys.oem_unlock_allowed : 1        → allowed
ro.oem_unlock_supported: 1
ro.boot.flash.locked   : 1        → still locked, as expected
ro.boot.verifiedbootstate: green
```

Both lock signals are read, not just one, because a vendor that lies in one
sometimes tells the truth in the other.

## 4. The restore image

Unlocking erases the tablet. Before touching it, a verified way back had to
exist on disk — otherwise the exercise is a one-way door.

**Lenovo Rescue and Smart Assistant** (shipped as *Software Fix* v7.6.2.10) is
the official route, and it is keyed to the device: enter the serial and it
fetches the matching firmware, no tablet needed. It downloaded to
`C:\ProgramData\RSA\Download` — **not** `\LMSA` as most guides claim — and
brought SP Flash Tool along with it.

What arrived: `TB310FU_S000915_260703_ROW`, a 3.4 GB archive expanding to
**6.5 GB across 21 partition images**. Note it is a *newer* build than the
`S000914_260105_ROW` on the device; same model, official Lenovo, so restoring
moves the tablet forward a build rather than back.

### The scatter is encrypted

The MediaTek scatter file — the map SP Flash Tool needs — is **ciphertext**, and
its extension is truncated on the way out of LMSA:

```
image/MT6768_Android_scatter.t     21,328 bytes   e97c fb81 0178 82d5 ...
image/MT6768_Android_scatter.x     35,808 bytes   dde3 7578 08bd cba7 ...
image/efuse_t6100a_wifi.x           2,560 bytes   9358 9364 928f b2a2 ...
```

This is how Lenovo ships it, not a corrupt download. The consequence is real
though: **SP Flash Tool cannot use this package as it stands**, which also means
the BROM rescue path is not available from it. The tool LMSA helpfully
downloaded alongside the firmware is, for this package, inert.

### The images themselves are plain

Every actual partition image is ordinary and verifiable:

| File | First bytes | Verdict |
| --- | --- | --- |
| `boot.img` | `ANDROID!` | Android boot image |
| `vbmeta.img`, `_system`, `_vendor` | `AVB0` | AVB metadata |
| `super.img` (6.28 GB) | `3aff26ed` | Android **sparse** image |
| `super_empty.img` | `gDla` | raw **LP metadata** |
| `dtbo.img` | `d7b7ab1e` | DTBO |
| `preloader_raw.img`, `preloader_t6100a_wifi.bin` | `MMM…FILE_INFO` | raw MTK preloader |
| `preloader.img`, `_emmc`, `_ufs` | `EMMC_BOOT` … `MMM` at `0x800` | wrapped MTK preloader |
| `lk`, `logo`, `tee`, `gz`, `scp`, `sspm`, `spmfw`, `md1img` | `88168858` | MTK bootloader blobs |

So the restore path survives: **LMSA Rescue** (primary — it decrypts internally),
or **`fastboot flash`** of these verified images once unlocked. Keep LMSA
installed; it is the way back.

Package manifest hash, over every image name and digest:

```
d390ca9892572566d8ed8ddeec9e4ef5cf561145dafd55791c4172ce3d8d5d9b
```

Full record in [terminal-m9-firmware-2026-09-10.json](terminal-m9-firmware-2026-09-10.json),
device survey in [terminal-m9-snapshot-2026-09-10.json](terminal-m9-snapshot-2026-09-10.json)
(229 packages installed, **93 of them Google** — the ones a GApps-free GSI removes).

### Two false alarms worth keeping

The verifier flagged good files twice, and both corrections are now rules with
tests behind them:

1. **Three preloaders "corrupt".** They were not. `preloader.img`, `_emmc` and
   `_ufs` are the same payload inside an `EMMC_BOOT` wrapper with the real `MMM`
   header at offset `0x800`; only `preloader_raw` and `preloader_<board>.bin`
   start with `MMM` at zero. Insisting on offset zero condemned three valid
   files.
2. **`super_empty.img` "corrupt".** Also not. `super.img` is a sparse image and
   `super_empty.img` is raw LP metadata — two formats, both legitimate, and the
   rule only knew the first.

A verifier that cries corruption over a good download is worse than none,
because it burns the operator's trust exactly when it matters.

## 5. Drivers — less than expected

The widely repeated advice is that MediaTek devices need the **USB VCOM driver**
or `fastboot` hangs at *waiting for device*. On this machine that turned out not
to apply: Windows had already bound `Android ADB Interface` to
`USB\VID_0E8D&PID_201C`, and `fastboot devices` answered immediately after
`adb reboot bootloader`:

```
HA1Y7RCV    fastboot
```

Google's official USB driver package (rev 13) was downloaded and inspected —
it contains **zero** `VID_0E8D` entries, only Google's own — so it would not
have bound anyway, and was not needed.

VCOM is only required for **SP Flash Tool / BROM** work, which the encrypted
scatter has ruled out for this package. If a BROM rescue is ever needed, the
right tool is [bkerler/mtkclient](https://github.com/bkerler/mtkclient) with
UsbDk — open source and auditable. Note that `mtkclient.com` is **not** the
official project, and the driver zips on ad-supported mirror sites are a genuine
malware vector for something that installs an unsigned kernel driver.

## 5b. Off the cable

The tablet is reachable over Wi-Fi and can be found, connected to and updated
from the app with no USB at all.

```
10.89.1.154:5555 -> TrebleDroid vanilla running 21.0-20260614-UNOFFICIAL-arm64_bvN
```

Discovery asks **mDNS** first (`adb mdns services`) and falls back to a bounded
sweep of only the private subnets this machine is actually on — the same
restraint the LCD's own discovery shows, because a scan that wanders off the
local network is a nuisance rather than a feature.

Three things measured here that no amount of reading would have produced:

1. **The advertisement has two shapes.** A tablet switched on with `adb tcpip`
   publishes the bare `adb-HA1Y7RCV`; one paired for wireless debugging adds a
   random suffix, `adb-HA1Y7RCV-vWmDCe`. A pattern that assumed the suffix
   returned a **blank serial** for the real tablet.
2. **`adb tcpip` restarts adbd.** The very next shell command lands while the
   daemon is gone, so reading the address immediately reported *"no Wi-Fi
   address yet"* for a tablet that plainly had one. It now retries.
3. **Two transports make adb ambiguous.** Once the tablet is on both the cable
   and the network, adb has two transports for one device and answers
   *"error: more than one device/emulator"* to any untargeted command. Every
   wireless call now targets the cabled serial explicitly, and "more than one
   device" is treated as a failure rather than a success.

Also: adb has been observed handing back `0.0.0.0` as a service address once a
TCP transport already existed. That is not somewhere anything can connect, so
non-routable addresses are dropped rather than offered as targets.

One honest limitation: `adb tcpip` does **not** survive a reboot on a build that
does not persist it, and this GSI does not. Reconnecting after a restart needs
the cable once — the app says so rather than leaving it to be discovered.

## 6. What was built

The provisioning logic lives in the Pine Box desktop, modelled on the existing
CYD LCD firmware manager ([pine-box-lcd.md](pine-box-lcd.md)) and reusing its
discipline: identify by something the device cannot change, record what you find
with a hash and a timestamp, refuse anything that does not match, verify after
acting rather than trusting the tool's own success message.

**[`desktop/terminal.cjs`](../desktop/terminal.cjs)** — device discovery and the
bootloader.

- `devices()` / `identify()` — parses `adb devices -l`, then a single batched
  `getprop` and `dumpsys battery`. It will not shell into a tablet that has not
  accepted the RSA prompt.
- `readiness()` — the survey gate: not connected, not authorized, OEM unlocking
  off or unsupported, battery below 50%.
- `snapshot()` — props, packages, features and global settings, hashed. Its own
  `caveat` field states plainly that it is **not a restorable image**.
- `bootloader()` — parses `fastboot getvar all` into a typed state.
- `unlockReadiness()` — the last gate before erasure.
- `unlock()` — runs `flashing unlock` only past that gate, then **re-reads the
  bootloader to prove it worked** rather than believing `OKAY`.

**[`desktop/firmware.cjs`](../desktop/firmware.cjs)** — the restore-image gate.
Finds the scatter (including LMSA's truncated `.t`/`.x`), tells ciphertext from
a readable map, verifies every image by **magic bytes at possibly several
offsets**, SHA-256s each file and folds them into one package manifest, and
refuses a package missing `preloader`, `lk`, `boot`, `vbmeta` or `super`.

**[`desktop/gsi.cjs`](../desktop/gsi.cjs)** — matching an image to the tablet.
It keeps three things apart that are easy to conflate: what the **tablet
requires** (read from its own properties), what an **image actually is** (ext4
magic at `0x438`, EROFS at `0x400` — the filename is a claim, not evidence), and
whether the two **agree**. It refuses A-only on an A/B device, 32-bit on arm64,
a vndklite mismatch, a locked bootloader, or a still-compressed file — and it
names a failed download as a rejection page rather than calling it corrupt.

**[`desktop/terminal-host.cjs`](../desktop/terminal-host.cjs)** — the wiring.
It owns the only thing the modules above deliberately do not: where `adb` and
`fastboot` live, and how to run them. Its `survey()` answers the whole screen in
one round trip — what is plugged in, whether it is fit to touch, whether there is
a way back, and whether the image on hand is the right one.

**[`desktop/renderer/terminal.js`](../desktop/renderer/terminal.js)** — the
Terminal panel, reachable from the rail. It reads as a checklist of refusals, in
the same words the modules use, so a blockage is visible before anything is
pressed rather than discovered from a failure. Blockers and warnings are never
merged: one stops the work and the other does not, and blurring them teaches an
operator to skim both. The unlock control makes you type the confirmation out and
stays disabled until a verified restore image exists — and the main process
checks all of it again regardless of what the page believes.

Both take their shell runners by injection, so every path — including the ones
that would wipe a tablet — is tested without hardware.

### The refusals, in one place

`unlock()` will not run unless **all** of these hold:

- the bootloader actually says whether it is locked (silence is never taken as unlocked)
- it is the real bootloader, not fastbootd
- the bootloader's own `battery-soc-ok` is `yes`
- the serial matches the tablet that was surveyed
- a **verified restore image** exists
- the caller passes the exact string `ERASE THIS TABLET`

Tests, all without a tablet attached:
[test_terminal_provisioner](../tests/test_terminal_provisioner_2026_09_10.cjs) (14),
[test_terminal_unlock](../tests/test_terminal_unlock_2026_09_10.cjs) (14),
[test_terminal_host](../tests/test_terminal_host_2026_09_10.cjs) (6),
[test_firmware_restore](../tests/test_firmware_restore_2026_09_10.cjs) (17),
[test_gsi_match](../tests/test_gsi_match_2026_09_10.cjs) (14).

## 7. State as of this writing

| Gate | Status |
| --- | --- |
| Tablet identified and authorized | done — `HA1Y7RCV` |
| OEM unlocking available | **allowed** |
| Device survey captured and hashed | done |
| Verified restore image on disk | done — 6.5 GB, 21 images, 0 bad |
| fastboot reachable | done — no extra drivers needed |
| Bootloader | **unlocked** |
| GSI flashed | **LineageOS 21, Android 14** — `21.0-20260614-UNOFFICIAL-arm64_bvN` |
| Hardware acceptance | **passed** — audio, mic, Wi-Fi, touch, sensors |
| Google packages | **93 → 6** (Play Services gone) |
| Reaches the station | yes — HTTP 200 from `10.89.1.246:8096` |
| Kiosk APK, launcher, lock task | not started |

### The unlock

Run through the app's own code path, not by hand. It verified the restore image
was still on disk, surveyed the tablet, rebooted to the bootloader, and only then
issued `flashing unlock`. The tablet asked for confirmation on its own screen;
fastboot waited **62.5 s** for it.

```
before:  unlocked: false   secure: true
after:   unlocked: true    secure: false
```

The result was **re-read from the bootloader rather than taken from fastboot's
`OKAY`**, and confirmed again from Android afterwards:
`ro.boot.flash.locked = 0`, `ro.boot.verifiedbootstate = orange`. Every boot now
shows an orange "bootloader unlocked" warning; that is permanent and not a fault.

Userdata was erased, as expected. Developer options and USB debugging had to be
re-enabled afterwards, and the RSA prompt reappeared with a fresh fingerprint.

### The flash

Run as a plan rather than a run of commands, each step declaring the mode it
needs. The GSI: 2.37 GB ext4, `sha256 644722fc8c8a8b594187218c6dcacabe02ca77e9e17dd0e1a7f18a373028d27c`.

```
1 [bootloader] disable verified boot   flash vbmeta --disable-verity --disable-verification
2 [bootloader] enter fastbootd         reboot fastboot            (20.3s)
3 [fastbootd ] flash system            resized system_a, 10 sparse chunks
4 [bootloader] wipe data               mkfs.f2fs over 49,500 MB
5 [any       ] reboot
```

It booted in about 40 seconds to `ro.lineage.version 21.0-20260614-UNOFFICIAL-arm64_bvN`,
Android 14 / SDK 34. Being a **userdebug** build, ADB is enabled and authorized
out of the box, which removes the re-enable dance after every wipe.

Afterwards: all hardware features present, audio routed to `speaker(2)`, **ten
vendor `soundfx` libraries loaded** — the MediaTek audio HAL survives the GSI,
which was the single risk that could have killed the whole project — and the
tablet answered `HTTP 200` from the Pine Box agent at `10.89.1.246:8096`.

### The wipe that wiped nothing

Worth recording, because it was silent and it mattered.

`fastboot -w` was first placed in **fastbootd**, where it answered:

```
wipe task partition not found: userdata
wipe task partition not found: cache
wipe task partition not found: metadata
Finished. Total time: 0.004s
```

Four milliseconds, exit zero, reported as a clean wipe — and the tablet then
booted LineageOS with Lenovo's `/data` intact, **Play Services and all**. A
Google-free build with Google Play Services alive on it.

The cause is a real distinction: **fastbootd exposes the LOGICAL partitions
inside `super`, and `userdata` is not one of them.** It is a physical partition
the bootloader owns. Moving the wipe back to the bootloader — after the system
flash, so a failed flash never empties the tablet for nothing — produced what a
real wipe looks like:

```
F2FS-tools: mkfs.f2fs ... total sectors = 101377984 (49500 MB)
```

Google packages went 93 → 6, and the six that remain are AOSP framework
resource overlays on the vendor partition (networkstack, wifi resources,
cellbroadcast UI), not Google services.

Two lessons are now code. The plan puts `wipe data` in `bootloader`, with a test
asserting that mode specifically. And `runPlan` flags a **hollow success** — a
command that exits clean while saying "partition not found", "No such file" or
"Command not supported" — as a note on the step, without failing it. A step that
quietly did not happen is worse than one that failed loudly.

### What the tablet says it needs

Read from the device itself after unlocking, never guessed from the model:

```
ro.treble.enabled          true
ro.build.ab_update         true          -> A/B
ro.product.cpu.abilist64   arm64-v8a     -> arm64
ro.vndk.lite               (empty)       -> full VNDK, not lite
ro.virtual_ab.enabled      true          -> super goes through fastbootd
ro.boot.dynamic_partitions true
ro.board.platform          mt6768
```

So the image wanted is **arm64 · A/B · vanilla · full VNDK**.

### On root

Root was chosen, but neither current build publishes a superuser variant —
`bvS` exists only in the June 2025 image, a year behind. Rather than give up a
year of MediaTek fixes on the subsystem that decides whether this project works
at all, the plan is the **newest TrebleDroid base plus Magisk**, patching the
boot image separately. Magisk is better maintained than PHH Superuser, and the
stock `boot.img` needed to patch is already on disk from the Lenovo package.

## 8. What comes next

1. **Unlock** — through the app, past the gate above, with the tablet confirming
   on its own screen.
2. **Flash a LineageOS 21 arm64 A/B GSI**, no GApps, with
   `fastboot --disable-verity --disable-verification flash vbmeta vbmeta.img`.
   `fastbootd` is where a driver problem would actually appear, since it
   enumerates differently from the bootloader.
3. **Hardware acceptance** — speakers, microphone, the 3.5 mm jack, Wi-Fi,
   sleep/wake, volume keys, rotation. This is a **gate, not a report**: if audio
   out, mic in, or the jack fail on the GSI, the sampler premise is dead and the
   stock-Android route has to be reconsidered.
4. **The kiosk app** — `PineDesktopBridge` so the Windows renderer runs in an
   Android WebView, HOME launcher, lock task, boot receiver, foreground audio,
   and the native Oboe sampler engine.
5. **Wireless from then on** — terminal configuration held on the agent and
   polled by the tablet, so every install on the network shares one master
   configuration, as the station already does for its other settings.

## 9. Things that cost time, recorded so they do not again

- No adb on the machine means **no RSA prompt ever appears**. The empty device
  list is the symptom; the missing tool is the cause.
- The RSA dialog does not render on a locked screen or during a system update.
- `Get-PnpDevice` without `-PresentOnly` shows remembered devices; `Present:
  False` is not a fault.
- LMSA downloads to `C:\ProgramData\RSA\Download`, and **deletes the archive
  after extracting it**.
- Lenovo's support site blocks scripted requests outright (403 to plain fetches,
  HEAD requests and browser user-agents alike), so LMSA must be fetched by hand.
- MTK scatter files are YAML wearing an `.xml` extension — and in an LMSA
  package, encrypted YAML wearing a truncated extension.
- A partition image can legitimately ship in more than one wrapping. Verify by
  magic bytes, allow several, and check more than one offset.
