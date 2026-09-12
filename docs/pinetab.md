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

---

## 8. The audio, and the rule that shapes it

Everything in this section exists to satisfy one sentence from the operator:

> "My goal is to have the broadcast going to singularly the PineTab or the Pine
> Box or the Nabu device, the app instance or the application loaded on PC.
> Individually but never at the same time."

That is a stronger rule than the station's own model, and the gap is the whole
reason `desktop/pinetab-route.cjs` and `rail/AirOwners.kt` exist.

### Why the station cannot say it alone

Each stream routes to one of `box`, `here`, `both`, `off`, `nabu`
(app.py:93361). Two of the five break the rule by themselves:

| route | why it is not singular |
| --- | --- |
| `both` | the box **and** a page, by definition |
| `here` | **every** browser looking at the station |

`here` is the one that bites. The tablet, the Electron app and any web page open
on the PC are all "here" clients. Measured on the live station with all three
up, in the station's own words:

```
3 players are on this broadcast - if that is one machine,
they will be playing over each other. Give one of them the air.
```

That is what "I'm hearing a different broadcast coming out of the application
than out of the Pine Box tab" actually was: not two different shows, but **one
show played three times, a few hundred milliseconds apart**.

### The station already had the answer

`#1008` (app.py:25001) gives ONE listener the air; every other page gags itself
in `pineSoloGate` (app.py:154557), and an owner that stops polling releases it
after `AUDIO_OWNER_LIFE` (90 s), so this can never leave the house silent.

```
GET  /api/radio/listeners   the roster, plus audio_owner
POST /api/radio/solo        {"listener": id} | {"clear": true}
```

**It must not be reimplemented.** The terminal drives it; it does not replace
it. A destination is therefore two decisions made together — the route, and who
holds the air — and exclusivity falls out by construction: a route is a single
value, and when it is `here`, exactly one listener id is left unmuted.

### A listener id is not an identity

This is the trap that made "only the tablet" keep coming undone. The id is
minted fresh on every page load. Measured across three relaunches of the kiosk
app: `pbnvgdtefn`, then `pbq8gj5qvq`, then another. So the tablet would hold the
air until it reloaded, at which point the owner it named stopped polling, the
station released it after 90 s, and every page started sounding again.

Nothing durable is ever stored against a listener id. The durable statement is
the **destination**, kept in settings; the id is re-resolved from the roster
every time it is needed. Devices are identified two ways, both measured:

- the Electron app mints `desktop-<rand>` (`renderer.js` `desktopListenerId`), so
  it is self-identifying wherever it runs;
- everything else mints `pb<rand>` and is placed by **address** against the
  `terminals` table — which is why the tablet's row carries an `addr`.

A `terminals` row that pins a `listener` is never matched by address to anything
else. Two tabs on one machine share an address — the Electron app and a browser
window both sat on `10.89.1.13` — so an address alone cannot tell them apart.

### The half the desktop was missing

`renderer.js` read `window.__pineGagged` to decide whether another listener owned
the air, but **nothing in that file ever set it**. `pineSoloGate` sets it inside
the station page, which is a `<webview>` and therefore a different JS context, so
the shell's own players never learned they had been gagged and kept sounding.
`/api/radio/clock` already carries `audio_owner`, so the shell only had to ask
the same question about itself.

> Renderer changes need a **desktop relaunch** to take effect. A running app
> keeps the old `renderer.js` and will look exactly like an unfixed bug.

### The routing table

Beside the destination sits a table of devices in settings (`terminals`,
validated by `validate_terminals` in app.py), one row per device:

```
pinetab  play=true   music .8  voice 1    addr 10.89.1.154
desktop  play=false  music .6  voice .6   addr 10.89.1.13   fallback=true
```

Every client reads the same table and obeys its own row, which is what makes the
tablet's volume settable from the computer. The levels drive the panel's own desk
(`djGainMusic` / `djGainVoice`, read by `djLevels()` at app.py:149377) rather
than a second audio path, so the panel's existing GainNode machinery does the
work.

**The clamp is not cosmetic.** The voice slider defaults to 160%, and on the
tablet the DJs play through a plain `<audio>` element, whose volume setter throws
above 1.0:

```
IndexSizeError: The volume provided (1.6) is outside the range [0, 1]
```

The throw aborted the routine that was setting it, so **the DJs were silent on
the tablet while music played**. The desktop never saw it because its GainNode
accepts boost. The setter is clamped for every element in the page, including
ones the code has never heard of.

Two rules that were **wrong in the first cut**, recorded so they are not
reintroduced:

- *"More than one device switched on is legitimate — the box and the tablet."*
  It is not. More than one is a fault, resolved by id order so the desktop and
  the tablet reach the same answer without talking to each other.
- *Reading the desk clamped.* That made 160% and 100% indistinguishable, so the
  table could never pull a boosted slider down — it always appeared to agree
  already. The desk is read **raw**.

### The 3.5 mm jack — the six roads, and the one that worked

> "It is tantamount that I get the audio working through the jack as well. That
> is one of the reasons I bought this unit. Typically I have the audio being
> piped into a major system."

Symptom: plugging an aux cable into the tablet did nothing; audio stayed on the
speaker. Measured end to end, with a cable in the socket:

| check | result |
| --- | --- |
| `/sys/class/switch/` | **empty** — no `h2w` node |
| `/dev/input/event0` `ACCDET` | `SW (0005): 0002*` — `SW_HEADPHONE_INSERT` **set** |
| `dumpsys input` Device 5 | `Switch Input Mapper: SwitchValues: 4` |
| `/vendor/etc/audio_policy_configuration.xml` | declares `AUDIO_DEVICE_OUT_WIRED_HEADSET` and `..._HEADPHONE` |
| `cmd overlay lookup android android:bool/config_useDevInputEventForAudioJack` | **`false`** |
| `dumpsys audio` | `mMainType=0x0` — the audio layer is unaware |

The kernel detects the plug, InputReader reports it, and the vendor policy has
somewhere to send it — and then the framework drops it on the floor.
InputManagerService's own bytecode says why:

```
iget-boolean v0, v6, InputManagerService.mUseDevInputEventForAudioJack
if-eqz v0, 0080                 <- false, so jump past everything
...
invoke-interface WiredAccessoryCallbacks.notifyWiredAccessoryChanged
```

**Five roads round it were tried and every one is dead.** They are recorded
because each looks plausible and each costs an afternoon:

1. **A platform-signed RRO flipping that boolean true.** It installs and it
   survives a reboot — and it still does not work, because a `/data` overlay is
   applied **after** IMS constructs. Measured: IMS at 15:12:43, the overlay at
   15:12:44. That is a hard ordering wall, not a bug with a fix.
2. **A fabricated overlay.** Wiped on every framework start.
3. **`cmd audio` / a vendor force-route property.** Neither exists on this build.
4. **`AudioTrack.setPreferredDevice`.** Needs the device to appear in
   `getDevices()`, which needs the framework to know about it. Circular.
5. **Forcing the codec by hand as root.** `HPL/HPR Mux` was set to Audio Playback
   and *held*, unopposed, for twenty seconds — and there was still nothing in the
   headphones. The vendor's own `audio_device.xml` explains it:
   `headphoneSpeaker_output` drives the **speaker** through the same headphone
   pins in LoudSPK mode, so the amplifier's power follows whichever path the HAL
   opened. **A mixer poke cannot open a path.**

### What actually worked: say it ourselves

The sixth road is to make the announcement the framework refuses to make —
`AudioManager.setWiredDeviceConnectionState`, the same call
`WiredAccessoryManager` would have made. It is `@SystemApi`, so it is reached by
reflection, and it is gated on `MODIFY_AUDIO_ROUTING`, which is
`signature|privileged`. **That is why the kiosk is signed with the platform key**
— see *Platform signing* below. `DUMP` comes along for the same reason, because
the terminal also has to *read* the switch and `getSwitchState` exists on neither
`InputManager` nor `InputManagerGlobal` on this Android 14 build. What does know
is the input service's own dump: `dumpsys input` prints `SwitchValues: 4` with a
cable in and `0` without, and bit 2 is `SW_HEADPHONE_INSERT`.

`audio/JackWatch.kt` polls that every two seconds — a question, not an event,
because there is no callback for a device the framework has decided not to track.
Verified through a full cycle:

```
cable out  ->  SwitchValues 0  ->  "the jack is out — audio back to the speaker"
               dumpsys audio: mMainType=0x0, headset port gone from the policy
cable in   ->  SwitchValues 1  ->  "the jack is in — audio handed to it"
```

### The announcement outlives the app

This one cost a working jack twice, and it is not obvious.

The announcement lives in the **framework**, not in the app. It survives the app
being killed, force-stopped, crashed or reinstalled, because **none of those run
`stop()`**. A fresh `JackWatch` that assumed `announced = false` then read
`SwitchValues 0`, decided the two already agreed, and said nothing — leaving the
tablet routed to a headset that was not plugged in:

```
dumpsys audio          mMainType=0x1                      (MAIN_HEADSET)
media.audio_policy     "Wired Headset" Port 278 available
dumpsys input          SwitchValues: 0                    (no cable)
```

And unplugging could never fix it, because unplugging is exactly the transition
it believed had already happened. `announced` is therefore a `Boolean?` — `null`
until we have spoken in this process — so the **first** reading is always
announced, whatever it says. One redundant binder call at startup, against a
terminal silently routed to nothing.

**The general rule:** any state pushed into a system service must be reconciled
on startup, never assumed.

### Platform signing, and why the deploy is one script

The jack needs `MODIFY_AUDIO_ROUTING` and `DUMP`. Both are
`signature|privileged`, so they are granted only to a build signed with the same
key as the framework — here the AOSP platform test key, SHA-256
`c8a2e9bc…92ab8`, whose framework certificate hashCode is `b4addb29`
(`dumpsys package android`).

**Gradle cannot produce that APK.** `assembleDebug` always signs with the debug
key (`4c7dcfcf`), so the platform signature is a separate step afterwards — and
the moment anyone runs the two obvious commands:

```
gradle assembleDebug && adb install -r app-debug.apk
```

the tablet is quietly back on a debug-signed build, both permissions read
`granted=false`, and the jack stops following the cable. **The app still launches
and looks entirely normal.** There is no symptom except the audio, which is why
this happened twice before it was caught.

So `deploy.sh` welds build → zipalign → platform-sign → **verify** → install, and
refuses to install an APK that is not platform-signed. Two things it checks, not
one: that the APK's signer is the platform key by full SHA-256, *and* that the
tablet's framework is still `b4addb29`, so reflashing with a differently signed
GSI is noticed here rather than discovered later as a dead jack.

> A guard that fails to read its input and then passes is worse than no guard.
> The first version of that check parsed the framework hash into an empty string
> and then matched everything against it.

A signature change cannot be installed over the top, so the script uninstalls
first when it has to — and **re-grants `RECORD_AUDIO` afterwards**, because an
uninstall takes the runtime grants with it and the talk dot is silently useless
without it: it records, gets zeros, and the station transcribes nothing. There is
no permission prompt to fall back on in a kiosk that owns HOME.

### The microphone, and a measurement that was wrong

The terminal has **no speech recognizer of its own** — `cmd package
query-services -a android.speech.RecognitionService` returns *"No services
found"* on this GApps-less GSI. So `audio/MicCapture.kt` records 16 kHz mono
here and the **station** hears it, through `/api/listen/transcribe` to
wyoming-whisper.

Two things worth keeping:

- **`VOICE_RECOGNITION` is dead on this device.** Measured against `MIC`:
  0.0004 against 0.63. My first sweep found them equivalent — it was taken in a
  silent room, so it was comparing two noise floors. A level comparison is
  meaningless without a signal.
- **Wyoming sends the transcript in the `data_length` blob, not inline.** Reading
  the header only gives an empty transcript and a 504 further up. This fix went
  missing once and had to be applied twice, because `app.py` is edited from more
  than one session.

### The wallpaper is the gallery

> "Constantly every five minutes be replacing the wallpaper with the latest image
> being hawked by the Pine Box gallery on the station. I want the lock screen and
> the home screen to always have images from the Pine Box Gallery as they are
> being chosen by the station and being sold."

`gallery/WallpaperWatch.kt`, every five minutes, onto `FLAG_SYSTEM` **and**
`FLAG_LOCK` — set in two calls rather than one, because a build can refuse the
keyguard alone and a single combined call that throws would leave both unchanged.

Which picture, and in what order:

1. **`selling_now`** — the station's own single answer to "what art is being sold
   right now" (#900, app.py ~45587). It folds the three roads that sell things —
   the sales floor `hawking_now`, the ad break `ad_now`, and the gallery press —
   into one dict carrying a bare gallery filename, and it rides on `/api/dj`.
2. **The newest still in the gallery**, when nothing is on the block — which is
   most of the time, since `selling_now` is `None` between spots. Without this
   the tablet would revert to a black rectangle, which is not "always have images
   from the Pine Box Gallery".

Two traps in that fallback. `/api/generations?limit=N` is **newest-first**
(`read_generations` slices the tail and reverses), and it serves `.mp4`/`.webm`
alongside stills — so anything wanting a *picture* must filter by extension.

It reads `StationFeed.snapshot()` when that is fresh and only fetches `/api/dj`
itself when nothing is collecting the feed. That is the single-poller rule, and
it is also correctness: the snapshot goes stale the moment no view is attached,
which on a locked tablet is most of the time, so trusting it outright would hang
whatever was selling when the screen was last unlocked, forever. It runs from the
Application rather than the Activity for the same reason — started from the
activity it would stop at the moment it starts mattering.

Renders are several thousand pixels square and the screen is not, so the bitmap
is decoded at `inSampleSize` and then **centre-cropped to the screen's shape**.
Left to itself the wallpaper service letterboxes or stretches it.

### Wireless adb does not survive a reboot

`adb tcpip 5555` is a runtime mode, not a setting. After a reboot the tablet
pings but refuses adb, and **rebooting it is how remote access gets lost**. Two
recoveries:

- **Wireless debugging** (Android 11+): `adb mdns services` lists both
  `_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp` with their ports, so only
  the six-digit pairing code has to come off the tablet's screen. This is how
  access was recovered without a cable.
- **USB**, then `adb tcpip 5555` again.

Either way, make it permanent once you are back in:

```
adb shell setprop persist.adb.tcp.port 5555
```

Verified: after the next reboot, 5555 came back on its own.

Note that `adb root` **restarts adbd and changes the TLS port**, so a wireless
session must re-discover by mDNS afterwards. Reconnecting by the mDNS service
name rather than the old `ip:port` is the reliable form.

## 9. Making the panel fit a 9-inch screen

"It is still scaled too big... the application is still very cramped even on
mobile... I need to be able to spread the UI out."

Two complaints that pull opposite ways, so the page was surveyed over the
devtools socket in landscape before anything was changed:

```
viewport            1000 x 598 CSS px   (dpr 1.25, 1340x800 physical)
controls on screen  112, of which 94 under 32px tall, median 30
text on screen      123 elements at 9-11px
flex rows           60, of which 22 have neighbours under 6px apart
```

**The type was never too big — most of it was tiny.** What was too big was the
scale: at 1000 CSS px across a 1340 px panel everything renders at 1.34x, so the
furniture ate a 598 px-tall viewport and the content was squeezed into what was
left. Height is the scarce axis in landscape, and nothing was being spent on it.

The fix is `TARGET_CSS_WIDTH` 1000 → **1150**, paid for by a WebView
`minimumFontSize = 12`: the layout gains 15% while the smallest text ends up
*larger* in real pixels than it was. Measured after:

| | before | after |
| --- | --- | --- |
| viewport | 1000 × 598 | **1154 × 690** |
| text under 12 px | 123 elements | **0** |
| rows with <6 px gaps | 22 of 60 | **3 of 21** |
| clipped overflow | 4 | **0** |

> **Keep `tablet.css`'s breakpoint above `TARGET_CSS_WIDTH`.** It was
> `max-width: 1100px` while the target was 1000; raising the target without
> moving the query would leave it not matching and **every tablet rule silently
> off** — which looks exactly like the stylesheet having no effect rather than
> like a bug. It is now 1250.

### Square pads

"The point of the sampler's pads is that they are square pads that I tap on."

The grid was 4×4 of `1fr` stretched across whatever box it was handed — and that
box is square in neither orientation, so pads came out wide in landscape and tall
in portrait. A 4×4 of rectangles is a spreadsheet.

`.pb-padwrap` is a **size container**, so `min(100%, 100cqh)` inside it is "the
smaller of this box's two sides" — the largest square that fits. Four equal
columns and rows with equal gaps in both axes then give square cells with no
per-pad rule. Measured in the real WebView:

| viewport | pad | ratio |
| --- | --- | --- |
| 1066 × 1786 | 189 × 189 | 1.0000 |
| 1154 × 690 | 251 × 251 | 1.0000 |
| 1150 × 1924 | 208 × 208 | 1.0001 |
| 1000 × 1834 | 172 × 172 | 1.0000 |

### CHOP was never a mode

"I am stuck in chop mode. I need the ability to exit chop mode."

There was no chop mode. CHOP is one destructive press that writes sixteen slices
of the selected pad across the whole bank, over whatever was there — but it sat
in the row of toggles wearing the same button as POLY and GATE, so it *read* as a
state, and with every pad relabelled `[3/16]` and no way back, that is exactly
what it became.

Both halves were needed: the bank is snapshotted first — **bytes, not just
labels**, because the chop overwrites the other pads' records and a layout-only
undo would restore fifteen names in front of the wrong audio — and the button now
says what it will do next, CHOP then UNCHOP. One-shot actions (TAP, CHOP, STOP)
are drawn dashed so they never again look like a light that could be left on.

---

## 10. What has been put on it since

* **The slideshow** — [slideshow-tablet.md](slideshow-tablet.md). `~/bin/media-slideshow`,
  the Spark's own 25,000-line PySide6 glass, ported to the **SLIDES** tab:
  the same `/comfy-output` folder, the same `favorites.md`, the same twenty
  transitions, and the SC stack's console folded into one poll because
  eleven subprocesses cannot run here.
* **The overlays** — same document, `#1241`. The readouts are the product:
  the render ComfyUI is working on and its prompt, the per-core CPU, the
  NVIDIA section, the OpenWebUI rolodex with its resident models. One module
  that also runs standalone at `/spark`, and that stops polling the moment
  nobody is looking at it.

* **The headphone jack** — working, after five dead roads. See
  *The 3.5 mm jack* above. The terminal makes the wired-device announcement the
  GSI's framework refuses to make, which is why it is platform-signed.

* **The gallery as wallpaper** — `gallery/WallpaperWatch.kt` hangs whatever the
  station is selling on the home screen and the keyguard every five minutes.

* **The microphone** — recorded here, transcribed by the station, because this
  GSI ships no speech recognizer at all.

---

## 11. Off the LAN: the tailnet road

"I want to be able to connect the tablet up to my phone through 3G or the
localized network and be able to connect and interact with the radio and be
able to start it, have it broadcast to me and be able to download samples to
the sampler."

**The station and the DGX Spark are the same machine.** Worth stating plainly,
because the ask named them separately: `lilspark` is aarch64 with an NVIDIA
GB10 and carries `~/oww-train`. One host, one Tailscale node, no subnet router
and no second hop to arrange.

| | |
| --- | --- |
| tailnet | `tail1fec29.ts.net`, account masterxeon1001@ |
| the box | `lilspark` — `100.74.95.59`, MagicDNS `lilspark.tail1fec29.ts.net` |
| also on it | `iphone184` (the phone), and this desktop, offline since ~89 days |
| Tailscale SSH | enabled 2026-09-12 (`tailscale set --ssh=true`) |
| sshd host keys | ED25519 `SHA256:uDi74jxpAQMe49eTEkTJy+oaokvfcVI6U1x7EVQyzlE` |
| | RSA `SHA256:bxWiwv8E4GMpk3Ejwh+vaAEIoEU0iKTsszjwehC8THU` |

### Three roads, and the terminal picks

`net/Reach.kt` holds an ordered list and uses the first that answers:

    http://10.89.1.246:8096            the LAN, at home
    http://100.74.95.59:8096           the tailnet, from anywhere
    http://lilspark.tail1fec29.ts.net  the same, by MagicDNS name

The LAN goes first because Tailscale will happily carry traffic between two
machines on the same switch and it is a longer path through a userspace TUN —
and the panel is one very large document. The address goes before the name
because `100.74.95.59` needs no resolver, while MagicDNS needs the tablet to
be accepting Tailscale's DNS, which is a setting inside their app and
therefore not something the terminal can promise.

The road is chosen by `StationClient.reachable()`, which the offline banner
already calls on its own retry — so a tablet carried out of the house
re-chooses with no second timer and no "the network changed" listener.

### Two things that will bite

**The network policy fails closed.** `res/xml/network_security_config.xml`
permits cleartext per host BY NAME. A road added to Reach and not to that file
is refused before a packet leaves, and nothing in the failure says so. Both
tailnet hosts are named there now.

**A probe must confirm the STATION, not merely an answer.** `answers()` first
accepted `200..499`, inherited from the old reachable() where the question was
"is the station I already know about up?". As a road chooser that is wrong,
and the first test proved it: pointed at `:8099` — the restart bridge — the
terminal announced "station on the LAN" and loaded the panel from a service
whose whole vocabulary is `{"error": "GET /status or POST /restart/<name>"}`.
It now requires 200 and a body saying `"status"` and `ok`. The case that
matters is a captive portal: exactly what sits between this tablet and the
internet on somebody else's wifi, and it answers everything.

Measured after the fix: pointed at the decoy it logged
`station over the tailnet` and loaded from the second road; pointed at the
real config it logged `station on the LAN`, panel up in 3.5s.

### Why remote listening needs no station change

The served panel contains **no absolute `http://10.89.1.246:` references at
all**, and the feed hands out media as relative paths (`/sfx/<id>?t=<sig>`, and
`media` as a bare filename). Everything therefore resolves against whatever
origin the page was loaded from: load the panel from the tailnet address and
the audio, the API and the sampler's clip cuts all follow it. Nothing on the
station had to learn about Tailscale.

### ConfigStore wrote an explicit key list

`tailnetUrl` and `tailnetName` are settings rather than constants, so a tailnet
address can move without a new build — but `ConfigStore` writes a named list of
keys and they were not on it, so `writeConfig` appeared to work and read back
the compiled-in default. `recordingFolder` was missing from that same list and
had been since it was added, so "download it to the local recording folder"
had never survived a restart. All three are stored now.

### What still needs a human

Tailscale 1.102.4 is installed on the tablet (`tailscale-android-universal`,
SHA-256 verified against Tailscale's published checksum, signature verified).
Two things cannot be done for the operator and should not be:

1. **The VPN consent dialog** — `com.android.vpndialogs.ConfirmDialog`. Android
   is asking the person, not the tool.
2. **The sign-in** — the tailnet is an account.

There is a browser on this GSI (`org.lineageos.jelly`), so the login flow can
complete on the tablet itself. Until both are done the second and third roads
cannot answer, and the terminal simply stays on the LAN — which is the correct
behaviour when it is at home anyway.

## 12. What comes next

1. **Unlock** — through the app, past the gate above, with the tablet confirming
   on its own screen.
2. **Flash a LineageOS 21 arm64 A/B GSI**, no GApps, with
   `fastboot --disable-verity --disable-verification flash vbmeta vbmeta.img`.
   `fastbootd` is where a driver problem would actually appear, since it
   enumerates differently from the bootloader.
3. ~~**Hardware acceptance**~~ — **walked, and passed.** Speakers, microphone
   and the 3.5 mm jack all work on the GSI; the jack needed the terminal to
   announce the cable itself, and the mic needed the station to do the
   listening. The sampler premise stands.
4. **The kiosk app** — `PineDesktopBridge` so the Windows renderer runs in an
   Android WebView, HOME launcher, lock task, boot receiver, foreground audio,
   and the native Oboe sampler engine.
5. **Wireless from then on** — terminal configuration held on the agent and
   polled by the tablet, so every install on the network shares one master
   configuration, as the station already does for its other settings.

---

## 13. Things that cost time, recorded so they do not again

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
- **A platform signature is not sticky.** Gradle signs with the debug key every
  time, so any plain `assembleDebug` + `install -r` silently reverts the tablet
  and takes `MODIFY_AUDIO_ROUTING` and `DUMP` with it. Deploy with `deploy.sh`,
  which refuses to install anything that is not platform-signed.
- **An uninstall takes the runtime grants with it.** A signature change forces
  one, and `RECORD_AUDIO` does not come back on its own — the mic then records
  silence rather than failing, which reads as "it did not hear me".
- **State pushed into a system service outlives the app that pushed it.** The
  wired-device announcement survived kills and reinstalls, so a watch that
  assumed its own default fought a route it had itself set in a previous life.
  Reconcile on startup; never assume.
- **A level comparison in a silent room compares noise floors.** `MIC` and
  `VOICE_RECOGNITION` measured identical until there was something to hear, and
  then differed by three orders of magnitude.
- **The platform keys must not live in a scratch directory.** They did, and the
  directory was temporary. They belong beside the project that needs them.
- **`[hidden]` is a UA type-level rule**, so any class-level `display` out-ranks
  it. That is the whole of the "I still cannot close this overlay" bug.
