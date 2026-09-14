# PineTab — the Lenovo Tab M9 as a Pine Box terminal

A record of turning a stock Lenovo Tab M9 into a dedicated Pine Box kiosk: what
the device is, what was found on it, what was built to manage it, and what has
deliberately not been done yet. Written as the work happened, on 2026-09-10.

The aim is a tablet that boots straight into Pine Box and is a limb of the
station — listen, work the deck, open every console, and play the air back
through a sampler — with no Google account, no Lenovo shell, and no home screen.


**Part I (§1-14)** is how a stock Lenovo Tab M9 was made ours. **Part II
(§15-22)** is the software that runs on it, how to build for it, and every
way it has been seen to fail. If you are picking this up cold and something
is broken, read §19 first.

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
after `AUDIO_OWNER_LIFE` (90 s).

That "stops polling" is doing more work than it looks, and it has been wrong
twice. `#1187` added the second release condition: a device whose row says
`play=false` may not keep, recover, or be given the air, because holding the
exclusive while refusing to sound silences everything. `#1332` added the
third, and it is the one that shows why "can never leave the house silent"
was too strong — a device can have `play=true`, poll perfectly, and still
acknowledge **nothing**. Measured: a freshly launched desktop held the air
that way while two tablets that had played 52 and 50 clips sat muted 75 and
74 times each, waiting for it. Polling is not consuming. An owner that holds
the air for `OWNER_DEAF_SECONDS` (75 s) having taken no clip at all now loses
it, and is refused re-entry for `OWNER_DEAF_REST` (300 s) — because without
that it simply claimed it back on the next poll and the house went quiet for
another seventy-five seconds, over and over.

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

## 12. DGX Terminal

"I want to be able to SSH into the Spark. I want to be able to access the
console. I want to be able to type in commands and be able to work through a
terminal in a separate app called DGX Terminal."

A third launcher activity in the same APK, following SparkActivity's shape:
its own label, its own taskAffinity, no HOME filter and no lock task. The
terminal is a thing you open, use and leave; the one screen that must never go
blank is the radio.

### No keys, and that is the whole point

Measured from the tablet before any of it was written:

    100.74.95.59:22   ->  SSH-2.0-Tailscale
    10.89.1.246:22    ->  SSH-2.0-OpenSSH_9.6p1

Tailscale SSH intercepts port 22 for tailnet peers, so the WireGuard tunnel
has already proved who the device is before an SSH packet is sent and the
server authorises on tailnet identity. No private key on the tablet, no
passphrase to type on a nine-inch screen, no `authorized_keys` to maintain,
and nothing to steal if the tablet is lost — revoking the device in the
Tailscale console revokes the shell with it.

The LAN address is deliberately NOT offered as a fallback here, although
everything else in this terminal falls back to it happily: sshd on `:22` would
demand a password, and putting a password box on a kiosk for a road nobody
asked to take is how credentials end up typed into the wrong thing. The app
reads the banner first and refuses anything that is not Tailscale answering.

`com.github.mwiede:jsch` rather than `com.jcraft:jsch` (last released 2018,
cannot negotiate with a 2024 OpenSSH) or sshj (drags in BouncyCastle at
several megabytes).

### Three bugs, and only the third was found by looking

Typing did nothing, and two plausible readings of that were shipped before
either was tested:

1. **the composing region** — a soft keyboard types into an underlined
   composing region and only commits at a space, so overriding `commitText`
   without `setComposingText` loses everything. This was real and is fixed:
   composing text is forwarded as it changes, with what has already gone out
   remembered so a correction rubs it out rather than sending the word twice.
2. **the input connection generally** — guessed at, not the cause.
3. **the actual cause**, found by adding one log point:

        onKeyDown 37 unicode=105 wired=true
        send failed: android.os.NetworkOnMainThreadException

   `send()` wrote to the socket straight from the key callback, which is the
   main thread, and Android forbids network I/O there. Worse than the refusal:
   the failed write left JSch's stream closed, so every keystroke after the
   first said "Already closed" — dead from the first letter with no sign why.

Writes now go through a **single-threaded** executor. Single on purpose:
keystrokes are ordered, and `ls` typed quickly must not arrive as `lsl`.
`resize()` goes the same way — it is also a network write, and it fires every
time the keyboard opens.

The lesson is the ordering: the log point cost one build and settled in
minutes what two readings of the symptom had got wrong.

### The keystroke logging was removed with the bug

While this was being chased every callback logged the character it received.
That would have written any password typed at that prompt into logcat, where
anything holding READ_LOGS can read it. A debugging aid that records what a
person types is a keylogger with good intentions. What is left logs only
whether the keyboard attached and whether the shell was wired.

### The emulator

`DgxScreen` is a character grid with enough VT100 to make `TERM=xterm`
honest — printable text, the control characters, cursor movement, the erase
family, scrolling regions and SGR colour, which covers ls, git, grep, tail -f,
python, nvidia-smi, docker and journalctl. Not the alternate screen buffer's
finer points, DEC line drawing or mouse reporting: vim and htop run and mostly
look right, and are not the reason it exists.

Plain arrays rather than a cell class: a 100x30 screen is 3,000 cells redrawn
on every frame of a `tail -f`, and this tablet has had an ANR from the console
before.

### Staying signed in

Two things were set on the tablet so the tunnel does not need re-establishing:

    dumpsys deviceidle whitelist +com.tailscale.ipn
    settings put global always_on_vpn_app com.tailscale.ipn
    settings put global always_on_vpn_lockdown 0

Lockdown is deliberately OFF. On it blocks all traffic whenever the tunnel is
down, which would break the LAN road and leave the kiosk dead at home during
any Tailscale hiccup.

**Still needs the admin console:** the tablet's node key expires on the
tailnet default. Machines → `trebledroid-vanilla` → Disable key expiry, or it
will ask to be signed in again when the key runs out.

## 13. What comes next

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

## 14. Things that cost time, recorded so they do not again

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

---

# Part II — the software on it, and how to work with it

Sections 1–14 are how a stock Lenovo Tab M9 was made ours. What follows is how
the thing that runs on it is built, how to build for it, and every way it has
been seen to fail. Written 2026-09-13, after a night that found most of §19 the
expensive way.

If you are an LLM handed this document with no other context: **§15 tells you
how to reach the tablet, §16 how the app is put together, §17 the hardware
surfaces, §19 the faults, §20 how to add something new.** Read §19 before you
conclude anything is broken.

---

## 15. Reaching it, day to day

```sh
export PATH="$PATH:/c/_tools/android-sdk/platform-tools"
adb connect 10.89.1.154:5555
D="-s 10.89.1.154:5555"        # ALWAYS use -s: USB and Wi-Fi are often both attached
```

`adb shell id` returns **uid 0** — this is a userdebug GSI and root is there when
you need it.

### The pid, and why your script will fail without this

`adb shell ps -A | grep pinebox` **returns nothing at random on this device**,
while the process is plainly running. It has cost hours across several nights.

```sh
P=$(adb $D shell "pidof com.pinebox.kiosk" | tr -d '\r\n ' | awk '{print $1}')
```

`pidof` can hand back **two** pids mid-restart — hence `awk '{print $1}'`. Loop
and retry rather than trusting a single attempt. The app's own log is a third
road: `adb $D logcat -d | grep "panel up in"` — field 3 is the pid.

### Looking inside the page

The panel is a WebView, so Chrome DevTools Protocol works over adb:

```sh
adb $D forward tcp:9600 localabstract:webview_devtools_remote_$P
curl -s http://127.0.0.1:9600/json          # -> webSocketDebuggerUrl
node cdp-ask.js "<ws url>" "<a JS expression>"
```

Three helpers exist and the difference matters:

| tool | when |
|---|---|
| `cdp-ask.js` | evaluate, print the result |
| `cdp-ask-long.js` | 45 s budget, awaits promises |
| `cdp-tap.js` | sets `userGesture: true` — **required to start audio or video** |

**The trap:** the kiosk injects its view code with `evaluateJavascript`, so
**injected JS never enters the DOM**. Searching
`document.documentElement.innerHTML` for a function you just shipped finds
nothing, and you will wrongly conclude the deploy failed — this has happened
twice. **CSS does** land in the DOM, so a stylesheet rule is a reliable "did my
build arrive" probe. Better: call the function and see if it answers.

### Screen frozen, nothing responds

Check the **notification shade first**. It takes focus and covers everything and
is indistinguishable from a hung kiosk:

```sh
adb $D shell "cmd statusbar collapse"
adb $D shell "dumpsys window | grep mCurrentFocus"      # names what actually has it
```

Lock-task pinning is a separate thing (`dumpsys activity activities | grep
mLockTaskModeState`) and is usually **NONE** — see §16.6.

---

## 16. How the app is built

### 16.1 One Activity, one WebView, injected views

`MainActivity` owns a WebView that loads the station's panel. Everything that
makes it *the Pine Box* is **injected at document start** from the APK's own
assets — the station serves the panel, the tablet supplies the views:

| bundle | file | carries |
|---|---|---|
| Boot | `bridge/BootAssets.kt` | the logo and splash, before anything else |
| Views | `bridge/ViewAssets.kt` | `assets/pine-views/*` — Script, Listen, Music, Presentation, the rail, the meters, the CRT set, the deaf-watch |
| Sampler | `bridge/SamplerAssets.kt` | `assets/pine-sampler/*` — its own page, its own copies |

**Order is not cosmetic.** `SCRIPTS` is evaluated in list order: models first,
then the views that read them, `rail.js` last because it looks for the globals
the others define. Wrong position, silent `undefined`.

**A file on one surface is not on the other.** The sampler page is a separate
bundle with its own copy of shared files. `sfx-tv.js` lived only in the desktop
shell for weeks, which is why the video window never appeared on the tablet —
the operator was tapping a button whose window did not exist there. A shared
view goes in **both** lists and **both** asset directories.

### 16.2 The bridge — `window.pineDesktop`

`bridge/PineDesktopBridge.kt` plus the shim `assets/pine-bridge.js`. The shim
hangs **one function per method** off `window.pineDesktop`:

```js
await pineDesktop.get('/api/dj')                 // the station, via the APP's HTTP client
await pineDesktop.post('/api/sfx/fill', {road:'video'})
await pineDesktop.jack({on:true})                // hand audio to the cable
await pineDesktop.wallpaper({now:true})
await pineDesktop.revive({now:true, why:'…'})    // restart the terminal
```

**A new bridge method needs THREE edits. Missing the third is the usual bug:**

1. the name in the method set in `PineDesktopBridge.kt` — dispatch
2. a `"name" -> { … }` branch in the `when` — behaviour
3. **`name: promised("name")` in `assets/pine-bridge.js`** — exposure

Skip (3) and `pineDesktop.yourMethod` is `undefined`, with no error anywhere.
(Measured: added `revive` to the dispatch set, rebuilt, and it was still
undefined on the page until the shim line went in.)

**The bridge does not use the WebView's network.** It goes through the app's own
HTTP client. This is the single most important fact for debugging this tablet —
see §19.1 — and the reason anything that must not fail belongs on the bridge.

### 16.3 `PineNet` — the request interceptor

`net/PineNet.kt`, hooked from `PanelClient.shouldInterceptRequest`. It owns two
prefixes and returns `null` for everything else:

- `/vendor/*` — served straight from APK assets (three.js and friends)
- `/api/generations/image/*` — fetched by the **app's** HTTP client, cached on disk

Why: the panel draws ~180 full-size 1024×1024 PNGs as thumbnails, which
saturates an HTTP/1.1 connection pool and starves everything behind it —
measured with `/vendor/three.min.js` still unanswered after three minutes.

Consequence to remember: **images keep loading when the WebView's network is
dead**, because they never touch it. That asymmetry is the diagnostic in §19.1.

### 16.4 `LoopDoor` — the loopback proxy, and why the origin is 127.0.0.1

`net/LoopDoor.kt` runs a proxy on `127.0.0.1:8096`, and the panel is loaded from
**there**, not from `10.89.1.246:8096`. It forwards raw bytes upstream.

This is not an optimisation, it is the only road that worked. `sampler-air.js`
wants an **AudioWorklet** for the broadcast tap, because the fallback
`ScriptProcessorNode` runs on the main thread and *loses* 17–23 % of buffers,
85 ms at a time, whenever the panel is laying out (§8 has the rest).
`BaseAudioContext.audioWorklet` is gated on `isSecureContext`, and the panel is
plain http.

Three roads were tried:

- **a certificate** — none obtainable for a LAN address that is also reached on
  a tailnet
- **a command-line flag** — the flag file *is* read on this device (proved with
  `--force-device-scale-factor`), but
  `--unsafely-treat-insecure-origin-as-secure` never reached the renderer, and
  it would need every road's origin listed
- **loopback** — potentially trustworthy *by spec*, no certificate, no flag,
  and it stays http so the panel's own cleartext media is not blocked as mixed
  content

Measured: a page on `127.0.0.1` reports `isSecureContext: true` with a live
`audioWorklet`; the same page on `10.89.1.246` reports `false` and `undefined`.

**So `location.origin` is `http://127.0.0.1:8096` and that is correct.** Do not
"fix" it. If you see a fetch to 127.0.0.1 failing, the door is not the first
suspect — read §19.1.

### 16.5 Provisioning itself — `KeyDiscovery`

The station embeds its key in every page it serves (`const SERVER_KEY = "…"`),
so a terminal on the LAN provisions itself with one unauthenticated `GET /`
rather than being told a secret by hand. The regex must stay identical to
Electron's `discoverAgentKey`.

### 16.6 What makes it a kiosk

Three separate mechanisms, and confusing them is how a "kiosk" ends up with a
Recents button:

1. **HOME** — declared in the manifest, made sticky with
   `addPersistentPreferredActivity`. Decides where every boot and every
   back-out-of-everything lands.
2. **LOCK TASK** — `startLockTask()`. Without device owner this is only screen
   pinning: a toast, and Back+Recents together lets you out. Usually reports
   `mLockTaskModeState=NONE`.
3. **IMMERSIVE** — whether the bars are drawn. Cosmetic, and the one that keeps
   needing re-applying, because the system restores the bars on every focus
   change.

---

## 17. The hardware surfaces

Permissions held (manifest): `CAMERA`, `RECORD_AUDIO`, `MODIFY_AUDIO_ROUTING`,
`MODIFY_AUDIO_SETTINGS`, `CAPTURE_AUDIO_OUTPUT`, `CAPTURE_VIDEO_OUTPUT`,
`CAPTURE_SECURE_VIDEO_OUTPUT`, `DUMP`, `SET_WALLPAPER`, `WAKE_LOCK`,
`RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE*`, `POST_NOTIFICATIONS`,
`INTERNET`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE`.

Several of those are **signature-level** and only exist because the app is
platform-signed (§637 and §18).

| surface | file | the shape of it |
|---|---|---|
| The jack | `audio/JackWatch.kt` | announces the cable to the framework, because this GSI never notices it (§8 and §19.4) |
| Output routing | `audio/OutputRoute.kt` | where the sound goes |
| The mix | `audio/AirTap.kt` | the broadcast captured natively, off the page — the ScriptProcessor version lost 85 ms at a time |
| The ear | `audio/MicCapture.kt` | native capture; a level comparison in a silent room compares noise floors (§14) |
| The sampler engine | `audio/NativeAudio.kt` + `app/src/main/cpp/` | oboe. **Not written by this project.** A build with no engine still installs and the panel's own HTML5 audio carries the show |
| Focus | `audio/MediaFocus.kt` | give the speaker back when something else is in front |
| Camera | `camera/PineCameraService.kt` | **no preview and no Activity** — Camera2 renders into an `ImageReader`, so looking through the camera never takes the terminal off the air |
| Screen | `replay/ScreenReplay.kt` | a `VirtualDisplay` mirrors the real screen into an encoder, held in a rolling ring, extractable through the app |
| Power | `power/PowerWatch.kt` | how long the radio has left, computed rather than guessed — Android only answers `computeChargeTimeRemaining` while charging |
| USB | `gallery/UsbBrowse.kt`, `UsbTarget.kt` | browse and write a stick |
| Wallpaper | `gallery/WallpaperWatch.kt` | the gallery on the home screen and keyguard (§19.2) |
| DGX terminal | `terminal/Dgx*.kt` | ssh to the workstation, no keys stored (§12) |
| Rail | `rail/*` | the side rail, quick jumps, who owns the air |

### The one rule that governs the audio graph

`window.audioScope(el)` memoises **one analyser per element** and adopts
`window.pineAudioCtx`. An element may have exactly **one**
`createMediaElementSource`; a second **throws** and takes the audio with it.

So anything wanting levels **borrows**, never builds. `sampler-air.js` states
this; `pine-meters.js` had to learn it — it called `createMediaElementSource`
itself, threw every time, caught, returned `null` for ever, and the player's
spectrum was blank while the code drawing it ran perfectly. Measured cure:
ink 0 → 4033 on the music meter, 0 → 2569 on the voice meter.

Pads **duck the broadcast** (`PineAir.duck('pad')`, released when nothing is
sounding and no pad is held). If everything reports "playing" and you hear
nothing, check `PineAir.duckState()` before anything else.

---

## 18. Deploying

```sh
cd /c/_tools/pinebox-android/PineBoxKiosk
export JAVA_HOME=C:/_tools/jdk17 ANDROID_HOME=C:/_tools/android-sdk \
       GRADLE_USER_HOME=C:/_tools/_gradlehome
./deploy.sh
```

**Always `deploy.sh`. Never `gradle assembleDebug` + `adb install`.** Gradle
signs with the debug key every time, so a plain install silently reverts the
platform signature and takes `MODIFY_AUDIO_ROUTING` and `DUMP` with it — and the
headphone jack stops working with no error. `deploy.sh` re-signs with
`keys/platform.pk8` / `platform.x509.pem`, refuses to install anything that is
not platform-signed, and prints the proof:

```
android.permission.MODIFY_AUDIO_ROUTING: granted=true
android.permission.DUMP: granted=true
```

If either says `false`, stop. Also: an uninstall takes **runtime** grants with
it, and `RECORD_AUDIO` does not come back on its own — the mic then records
silence rather than failing, which reads as "it did not hear me".

**`deploy.sh` leaves the app stopped.** Start it yourself:

```sh
adb $D shell "am start -n com.pinebox.kiosk/.MainActivity"
```

**A view change still needs a rebuild.** The views live inside the APK, so
copying a `.js` onto the station changes the desktop shell only. Copy to all the
places that need it:

```
…/spark-agent/desktop/renderer/<file>                     # the shell
…/PineBoxKiosk/app/src/main/assets/pine-views/<file>      # the tablet's panel
…/PineBoxKiosk/app/src/main/assets/pine-sampler/<file>    # the tablet's sampler
```

---

## 19. Failure modes, with their cures

### 19.0 The panel's script does not parse — the one every meter misses

**Symptom (2026-09-14, 52 minutes):** the station is on, a record is
playing, the voice ring holds dozens of clips, a listener is registered and
even *holds the air* — and `broadcast/health` says *"Nobody has heard the
DJs say anything for N minutes. The station is on and something is sounding,
so this is not a dead broadcast — the dialogue is not reaching the air."*
LOOK, DEVICES and RELEASE all report nothing wrong.

**Cause:** one JavaScript `SyntaxError` in the control panel's inline script
(served line 36838 of `/`). A rewrite over `app.py` had turned eight
`font: "…"` entries into `font: PineIcons, "…, PineIcons"` and eaten the
trailing comma. A SyntaxError kills the **entire** script block: `pollDJ`,
`djVoicePoll`, the music player — none of it ever existed. The heartbeat
that kept the roster looking alive was the Electron top page's, not the
panel's. `ast.parse` proves `app.py`; it proves nothing about the JavaScript
inside its string templates.

**Signature:**

```
webview   Runtime.exceptionThrown  SyntaxError: Unexpected identifier …
          Object.keys(window).filter(k => /^dj|^poll/.test(k))  -> []
          musicPlayer src=""   sayAudio src=""     (music silent too — the tell)
station   heard_seconds_ago=null  clips_waiting=0  "0 clip(s) handed over"
```

**Check, in one line, after any template edit** (node is on the DGX host):

```sh
K=$(docker exec spark-agent printenv SPARK_AGENT_API_KEY)
curl -s -H "Authorization: Bearer $K" http://127.0.0.1:8096/ -o /tmp/p.html
S=$(grep -n "<script>" /tmp/p.html | head -1 | cut -d: -f1)
E=$(grep -n "</script>" /tmp/p.html | tail -1 | cut -d: -f1)
awk -v s=$((S+1)) -v e=$((E-1)) 'NR>=s && NR<=e' /tmp/p.html > /tmp/p.js && node --check /tmp/p.js
```

**Cure:** fix the line, restart, and then **reload the open pages** — a
station restart does not reload a webview that is already showing the broken
page. On the desktop, `Page.reload` over `--remote-debugging-port`; on the
tablet, the TERMINAL rung.

**And the second half:** once the panel lived again the desktop still played
nothing, because its out-loud switch (`settings.terminals.desktop.play`) was
OFF while the tablet's was ON and the tablet was not polling. The DEVICES
rung refuses that case on purpose (it acts only when *every* switch is off).
`POST /api/broadcast/fix/terminals` prints the switches; round-trip
`GET`→`PUT /api/settings` to turn one on.

### 19.1 The WebView goes deaf — the one that will fool you

**Symptom:** the panel looks completely alive — feed updating, views painting —
and there is **no audio at all**.

**Why it looks alive:** the feed and every API call go through the bridge
(§16.2), which is the app's HTTP client. Images load for the same reason
(§16.3). What has died is **Chromium's own network stack**, and with it every
`fetch`, every `<audio>` and every `<video>` — the only three things the
broadcast needs.

**Signature:**

```
musicPlayer        net=2 ready=0        stuck loading, never plays
djVoiceAudio0/1    src="" or ready=0
djVoiceSeen        stuck  (seen 51 minutes behind)
fetch('/api/…')     TypeError: Failed to fetch in 40–100 ms
                   — a PRISTINE fetch from a fresh <iframe> fails too,
                     so it is not a page-level override
images             still 200 in ~500 ms       <-- the tell
```

**Ruled out, each measured. Do not spend a night on these again:** no proxy
(`settings get global http_proxy` null, Wi-Fi `Proxy settings: NONE`);
Tailscale up but `ip route get 10.89.1.246 uid 10212` goes straight out
`wlan0`; `mediaPlaybackRequiresUserGesture` already false; nothing ducked, all
elements volume 1 and unmuted; `LoopDoor` healthy (two requests on one
connection, 200 each in 0.02 s, keep-alive reused).

**The cure is a fresh process:**

```sh
adb $D shell "am force-stop com.pinebox.kiosk"; sleep 4
adb $D shell "am start -n com.pinebox.kiosk/.MainActivity"
```

Measured: `fetch` went from `TypeError` to `200 in 442 ms` on the instant, and
audio returned. **A WebView reload will not do it** — the network service lives
in the app process, so the same dead stack is handed to the new page.

**The self-heal** is `deaf-watch.js` (a view) + `net/Revive.kt` (the app). It
does **not** watch the audio: "no sound for a while" cannot tell deafness from a
quiet show, and this station has real quiet stretches. It compares the two
roads — *the bridge answers and a plain fetch does not* — which is a pattern no
amount of genuine dead air can produce. Three consecutive strikes, a 25 s probe
budget, and any round where the bridge itself was slow is thrown away.

Two things it had to learn, both measured on this device:

- `setExactAndAllowWhileIdle` is **refused**: *"Package com.pinebox.kiosk, uid
  10212 lost permission to set exact alarms"*. Use `setAndAllowWhileIdle`.
- **The relaunch delay must be ~2.5 s, not 900 ms.** At 900 ms the app came back
  and the panel **never loaded** — no `panel up in` line at all, `listeners=0` —
  because the launch landed inside a process that was still dying, while
  Android was also restarting the foreground activity itself. Two launches
  fighting.
- The rest period lives **on disk**, not in a field: a field is reborn with the
  process, so a terminal that came back still deaf would revive for ever. It
  gives up after three in thirty minutes, because a restart loop is worse than a
  silent screen — you can at least read a silent screen.

**Watch for:** if the probe budget is shorter than the station's worst
event-loop stall, this watch will restart a perfectly healthy tablet. It did
exactly that at an 8 s budget against a station that stalls 10–15 s.

### 19.2 The wallpaper relaunches the Activity

Hanging gallery art makes systemui regenerate the Material You overlays, which
raises `CONFIG_ASSETS_PATHS` (`0x80000000`) — a config change with **no name in
the `android:configChanges` flag set**, so it cannot be declared away and the
Activity is **relaunched**. Measured: seven times in thirty-three minutes, on
exactly `WallpaperWatch.EVERY_MS` (5 min), each taking the operator's scroll
position and folds with it.

Cure: still choose a piece every round, but **hang it only when no view is on
the glass** — `reading` set in `onResume`, `released()` from `onPause`. That is
faithful to `PineApp`'s own note: *"the wallpaper's whole point is to be right
when the app is NOT the thing on screen."* Verified: zero relaunches after.

### 19.3 JS timers freeze; rAF does not

The WebView **suspends JS timers** while `requestAnimationFrame` keeps firing.
Anything that must keep moving — a mark, a meter, a countdown — rides rAF, not
`setInterval`. No web-side cure can reach the timer that would fix it, because
that cure would itself be a timer.

### 19.4 Audio going to a jack with nothing in it

The announcement **outlives the app** (§8), so a stale one routes the broadcast
into an empty socket. `dumpsys audio | grep Devices:` shows `headset(4)` —
which on this tablet is usually **correct**, because a cable runs to a larger
system. Confirm with the operator before "restoring" the speaker.

```js
await pineDesktop.jack()                // report
await pineDesktop.jack({on:false})      // hand it back
```

### 19.5 The connection pool, and leaked media elements

A WebView allows roughly **six connections per origin**, and the panel holds
several long-lived polls. Anything that leaks a loading `<video>` eats a slot
permanently — measured: two orphaned videos at `net=2`, after which **87 fetches
were outstanding and not one completed in 25 s**, including `/api/pulse`.

If you build a floating player, tear it down **by class over the document**, not
through the module's own references. Under rapid cutting the references have
moved on and the old node is left attached, still loading. Removing a `<video>`
does **not** stop it: clear `src` and call `load()` first, then remove the node.

### 19.6 Floating above the views

Every view is `display:none` the moment another tab is chosen and three of them
are separate documents, so anything that must float mounts at **body level**.
Then it has to out-rank the view layer:

```
the kiosk floats every injected view at   z-index 2147483000
the sampler's own overlays                2147483030+
the hold sheets                           2147483046
the lock screen                           2147483050
```

A picture-in-picture belongs around **2147483020** — above the views, below the
things meant to cover it.

Measured before this was understood: the video window was built, playing and
**completely buried**, with `elementFromPoint` at its own centre returning a
script line.

**#1322 — and the same number applies in the shell.** This used to lift the
kiosk only, told apart by `location.protocol`, on the reasoning that 900 was
right in the Electron renderer because that shell's own chrome is at 1000. That
reasoning has not held: the shell now carries the same high bands the kiosk
does — `view-chrome` at 2147483200, the hold sheets at 2147483046, the trace
console at 2147483004, the SC pop-up at 2147483010, the panel's own 3JS windows
at 2147483020 — and its Agent tab is a `<webview>` with a compositing layer of
its own. A set at 900 behind any of those is this same fault on the other
surface, with nothing on screen to say so. **Both surfaces lift.** The 900 in
`sfx-tv.css` is now only the fallback for a surface where an inline style is
refused; `tests/test_sfx_tv_2026_09_12.cjs` asserts the lifted number in a
world with no `location` at all, which is the shell's case.

### 19.7 Stale ANRs

`/data/anr` keeps old traces. **Check the date** before blaming one for
something happening now.

---

### 19.8 The script highlight, and which document the audio is in

The SCRIPT view places its live mark by matching a position against each
row's `from`/`until` window. Those windows are offsets into one welded
file, so the position has to be the DJ voice element's `currentTime` — the
same coordinate — and not a clock estimate. Measured over 308 samples, the
clock estimate was behind the sound in **81.3%** of them, off by more than
three seconds in 58.5%, median −2.99 s; 29.8% of its moves were skips and
20.5% were backward.

It looked for that element with `document.querySelectorAll('audio')`. On
**this tablet that works**, because the panel *is* the document and
`djVoiceAudio0/1` are in it. On the **desktop it never worked at all**: the
SCRIPT view runs in the Electron chrome, whose document holds exactly one
`<audio>` (`desktopRadioPlayer`), while the panel runs inside
`<webview id="radioFrame">` — a separate DOM the chrome cannot reach. So the
scan returned `null` *every* time, not sometimes, and the view silently ran
on the estimator that three tickets had been written to replace.

The tell is that it is **not intermittent**. A timing bug wanders; this one
was a clean 0%. When a renderer feature works on the tablet and never on the
desktop, ask which document it is running in before you measure anything
else.

The cure is a bridge: `webview-preload.js` posts `{id, t, file, duration}`
every 250 ms, `renderer.js` stamps it on arrival, and `window.pinePlayhead()`
returns `null` once the reading is older than 1200 ms.

> **Stale must mean absent.** A bridge that keeps handing back its last value
> pins the mark to one line and *looks* like it is working. That is strictly
> worse than no bridge, because falling back to the clock at least keeps
> moving. The same rule as §19.1: the failure that imitates health is the
> expensive one.

The tablet needs no bridge — it has the elements — but it shares the rest of
the chain, so a script that will not follow on the tablet is a real fault and
not this one.

**The order comes from a ledger, not a clock.** `data/script_ledger.jsonl` is
written *before* a round is audible, keyed `(block, ord)`, assigned once and
never rewritten. The screenplay applies it last, after the older corrective
passes, so what you read is the order the round was written in — including
the SFX guy, who sits where he was rolled in rather than being placed
afterwards by a timestamp. **Everything that has been heard now carries a
`block`/`ord`** (#1339, below), so the absence of one is no longer the
signal it used to be — the element's `scripted` flag is. `true` means the
booth wrote that line down before it was audible; `false` means the station
reached for it and the ledger caught it once it had aired.

**And it reads downwards.** The first cut of that merge gave every row of a
block ONE sort time — the block's earliest — and put unledgered events after
it by their own clock. That keeps a conversation together and it is wrong,
because a block is not an instant: anything that happened *during* a round
sorted to the far side of it. Measured on the live hour: **15 backward pairs
in 365, worst 93.3 s**, and every single one the same shape — `dialogue (in a
block) → action (unledgered)`. A sting thirty seconds into a round was drawn
after the round ended, so the stamps read 08:14:53, 08:14:56, … 08:16:26,
then 08:14:53 again.

So a block carries no single time. Each row keeps its own, and the written
order is held by making those times **monotone** across the block: walking in
`ord`, each row sits at `max(its own stamp, the previous one + a hair)`.
Where the clock agrees with the script nothing moves at all; where `air_at`
was rewritten backwards the row is nudged just far enough to stay behind the
line it followed. Everything then sorts on one axis, so an interjection lands
where it actually interrupted.

After: **0 backward pairs in 558 elements**, 0 order inversions inside a
block, 23 of 23 SFX guy rows still inside their conversation, and 47
unledgered events now sitting *inside* a block — which is the point, because
that is where they happened.

> A script is read downwards. Holding a conversation together is worth
> nothing if it throws the reader up and down the page to do it.

**And one conversation at a time.** Making each row monotone fixed the
reader being thrown backwards and left a second fault standing: blocks
whose time spans *overlap* got shuffled into each other. Measured on the
live hour — 14 of 37 neighbouring blocks overlapped, and the rendered
order came out `55 56 56 55 56 55 57 56 57 56 57`: three conversations
shredded together a line at a time. Every stamp ascends, so it passes the
downwards test, and it is still unreadable.

Only one thing can be on the air at once, so overlapping blocks are a
stamping artefact rather than a fact about the broadcast. They are laid
out one after another — blocks in the order they started, and a block
that would begin before the previous one finished is pushed just past it.
The monotone walk then runs across the whole document instead of
restarting per block, so a conversation is contiguous *and* the page
reads downwards.

Where that correction moved a row, the element carries `air_at` with the
stamp it arrived with. Its presence is the signal: this row is not where
its own clock said it was. Final state on the live hour — **0 backward
pairs, 0 blocks re-entered, 0 order inversions, 38 of 38 SFX rows inside
their conversation**.

**And half the spoken lines had no place in it at all.** The ledger is
written from the booth, and the booth is not where half the air comes from.
Measured on one live hour: **194 of 399 dialogue rows carried no
`(block, ord)`** — 151 gold bars, 33 of the SFX guy's quips, 9 adverts — and
every one of them had aired. They are minted by the fill and rescue roads
and appended straight to the ring, so `script_ledger_commit` never saw them,
and the screenplay had nothing to order them by but raw `air_at`.

That is what "the script jumps around" actually was. Dropped into a ledgered
conversation they push its own turns apart: conversation b90 opened at
element 14 with turn 0, and its turn 2 did not appear until element 39 —
**24 elements of other material between two consecutive turns.**

They cannot be written down before they are audible, because nothing knows
they are coming. So they are written the moment they have been **heard** —
one block each, in air order, by `script_ledger_catch_up`, called from
`airlog_keeper`, whose own docstring calls it *"the one hook that catches all
twenty-five ring append sites"*. Patching the roads one at a time would have
missed the next one somebody adds. A one-row block is contiguous by
construction, so it can never split anything. They carry **`scripted:
false`**, because a reader is entitled to know which lines were planned and
which the station reached for. After: **100% of dialogue rows placed** over
the last three minutes, block runs reading `b126/0..5` and
`b166/0,2,3,4,6,7,9,10,11,13`, with the stings landing exactly in the `ord`
gaps they punctuate (#1339).

> **The metric said it was fine.** Three counters watched that document and
> all three read clean for fifteen minutes while it was wrong. "0 backward
> pairs" was true *by construction* — #1336b rewrites every element's stamp
> ascending **after** the sort, so nothing downstream can measure backwards;
> the check was reading its own output. The other two ranged only over rows
> **the ledger knew**, and every row it knew was in perfect order — the
> fault lived entirely in the rows they could not see. Dumping the actual
> sequence and reading it is what found it. A meter built out of the thing
> it measures cannot fail, and a meter that cannot fail is not evidence.

**And it must not re-sort an hour it knows nothing about.** The whole merge
was gated on `if _ord:` — and `_ord` is the entire 48-hour ledger, not the
hour being composed. So it was true on every compose, including hours that
predate the ledger, and it re-keyed every row on raw `air_at` with the list
position only a third tiebreak. But #1259, #1265 and #1299 express their
results **as positions in that list**: re-sorting on `air_at` throws all
three away. Those hours quietly reverted to the combed `air_at` order that
those passes exist to repair — and then the monotone sweep painted clean
ascending stamps over the top, so they measured perfect. The gate is now the
hour actually having ledger rows; an hour the ledger does not cover is left
exactly as the repair passes built it, which is how it read before #1330
(#1337).

**What the action lines say.** A record entry reads *"A record is spinning:"*
while that record is on the deck and *"A record drops:"* once it has
finished, and carries a `playing` flag the panel tints from. Before that the
two read identically, so a record that began forty seconds ago looked exactly
like one that finished an hour ago — which is what made a script that had
simply not caught up with a track change look like one that had skipped it.
The entry is never queued ahead: `_music_log_append` writes the row when the
record *starts*, so an entry here always describes a record already turning.
The lag it was hiding is the composition cache (20 s) plus the client's own
rest (20 s).

---

## 20. Building something new for this tablet

1. Write the view as a plain IIFE hanging one global off `window`
   (`window.PineYourThing = {…}`). No modules, no bundler — files are
   concatenated and evaluated in order.
2. Put it in `assets/pine-views/` **and** name it in `ViewAssets.SCRIPTS` at the
   right point in the order; a `.css` goes in `STYLES` the same way.
3. If it must also live on the sampler page, repeat for `pine-sampler/` and
   `SamplerAssets`.
4. Talk to the station through **`pineDesktop`**, not `fetch` — the bridge
   survives §19.1 and `fetch` does not.
5. New native capability? **Three edits** (§16.2), and remember the shim.
6. Anything that must not stop when the screen is idle rides **rAF** (§19.3).
7. Floating? Body level, and mind the z-index bands (§19.6).
8. Media? One owner of the audio graph — **borrow** the analyser (§17).
9. Deploy with `./deploy.sh`, then `am start`, then verify by **calling** your
   code over CDP — never by grepping the DOM for it (§15).

---

## 21. Quick reference

```sh
D="-s 10.89.1.154:5555"

# alive?
adb $D shell "pidof com.pinebox.kiosk"
adb $D shell "dumpsys window | grep mCurrentFocus"

# the cure for §19.1
adb $D shell "am force-stop com.pinebox.kiosk"; sleep 4
adb $D shell "am start -n com.pinebox.kiosk/.MainActivity"

# the app's own voice
adb $D logcat -d | grep -E "PineKioskActivity|PineRevive|PineWallpaper"

# audio routing
adb $D shell "dumpsys audio | grep -iE 'Devices:|Current:'"

# is the tablet actually hearing the station?  listeners>0 means it is polling
curl -s http://10.89.1.246:8096/api/dj | python -c "import sys,json;d=json.load(sys.stdin);print('listeners',d['listeners'],'|',d['dialogue_flow']['why_quiet']['why'])"

# screen covered by nothing you can see
adb $D shell "cmd statusbar collapse"
```

---

## 22. The standing rules

- **`deploy.sh`, always.** Platform signing is what makes the jack and the
  routing work, and a plain install silently takes them away.
- **The bridge outlives the WebView's network.** Anything that must not fail
  goes on the bridge.
- **One owner of the audio graph.** Borrow the analyser; never build a second
  source on an element.
- **Measure on the device.** Every number in Part II came off this tablet, and
  several contradicted a reasonable guess.
- **A meter that can only ever print one answer is not a meter.** Two separate
  nights were lost to checks that could not fail — a highlight measured against
  the arithmetic it was testing, and a "0 nodes rebuilt" reading taken during
  the one condition that cannot produce the fault.
- **Ruling something out is worth writing down.** Half of §19.1 is a list of
  things that were *not* the cause, and that list is what makes the next
  occurrence a ten-minute job instead of a night.

---

## 23. Getting the broadcast back

The `⟳` tab on the left edge of the panel (or a 24 px swipe from that edge)
opens **Reinitialise**. One button. It is the thing to press when the room
has gone quiet and you do not yet know why.

It exists because the fault is almost never where it looks. A wedge presents
as silence whether the cause is a shut pause door, a page that gagged itself,
a dead voice engine, a deadlocked floor or a stalling event loop — and the
first four of those survive a restart, which is the reflex it is there to
replace.

### What one tap does

Every rung re-checks and **stops the moment sound comes back**, so a healthy
station pays for almost none of this.

| # | Rung | What it reaches |
|---|---|---|
| 0 | IDENTIFY | Reads every page's own acknowledgments, names the one fault, runs its cure, checks, escalates once |
| 1 | ON AIR | Lifts a pause. Only if one is set |
| 2 | RELIEVE | Stands the writing and recording rooms down so the loop can serve the air |
| 3 | UNGAG | Local: drops this page's own hold, bumps the voice epoch, restarts the player |
| 4 | FLOOR | Takes the floor back from a hold that has gone silent |
| 5 | FLUSH | Advances the feed epoch — every page abandons the clip it cannot start |
| 6 | DRAIN | Sends out audio that already exists: the clips held on the box's shelf, and the lines that could not be rendered when they were written |
| 7 | STOCK | Takes the longest-unheard finished round off the cupboard shelf and airs it out of turn; replays the last segment if the cupboard refuses |
| 8 | DEVICES | Reads every device's out-loud switch; turns them on only if **every** one is off |
| 9 | RELEASE | Releases the audio exclusive so every player may sound |
| 10 | PAGES | Asks **every** page in the house to reload, not just this one |
| 11 | TERMINAL | Force-stops and relaunches **the tablet's kiosk** — the one cure a page reload cannot be |
|   | *listens for eight seconds* | |
| 12 | STREAM | The public door on :8097 and the mp3 mixer behind `/stream.mp3` — probed for real, and the mixer revived |
| 13 | ENGINES | F5, the voice-director and XTTS's reload — the engines the services table does not cover |
| 14 | DEEP | The whole repair tree: engines, the box, routing, the writer's lifeboat, the deaf-device reboot |
| 15 | SERVICES | Steward census — restarts xtts, ollama, comfy, a sick container; warms the music library |
| 16 | RELOAD | Reloads this page, and resumes the ladder afterwards |
| 17 | DISK | Runs the bounded retention sweep and names what is over its cap. Deletes nothing the rules would not have |
| 18 | RESTART | Restarts the station process. About twenty seconds of silence |

### Five of those rungs were unreachable before #1331

Worth knowing, because each one was a night:

- **RELIEVE** was missing although the station's own `AIR_LADDER` puts it
  *first*, with the note: *"the only rung that touches a congested loop —
  every other one assumes the clip never arrived, and a stalling loop
  delivers it late instead."*
- **PAGES** was a `location.reload()` of the operator's own tab. The wedged
  listener is frequently a *different* tablet, and it was never touched.
- **DEEP** and **SERVICES** were never called at all, so a dead voice engine
  got "cured" by restarting the station around it, indefinitely.
- **DEVICES** was nobody's job at all. `play` is the per-device out-loud
  switch, and a terminal with `play=false` that nevertheless claims the air
  gags every other page for a device that then plays nothing — measured at
  #1187: *"the desktop panel re-claimed the air every few seconds while its
  own row read play=false, so the tablet was gagged and the house heard
  nothing."* Releasing the exclusive does not help, because the same page
  re-claims it. The rung acts only when **every** switch is off, which is
  silence by construction and nothing anybody configures on purpose; a
  device deliberately set quiet is left alone.
- **FLOOR** (`_floor_break`) had exactly one caller — the silence branch of
  `dead_air_watch`, which needs 20 s of quiet *and* nothing speaking *and* the
  station unpaused before it will even look. There was no operator path to it.
  It is the cure for the deadlock that put the station off the air for six
  minutes with 134 finished rounds sitting on the shelf.

RELEASE had a fifth, quieter problem, and it took three goes to kill.

It read `health.gagged`, and `/api/broadcast/health` never returned that key.
In JavaScript a missing key is `undefined`, so the condition collapsed to
`!health.holding_the_air` — it fired only when *nobody* held the air, which is
the one case where releasing does nothing, and was skipped whenever a page
really was holding the exclusive and gagging the others. The rung written for
that fault had never once run.

Adding the key was not enough. `page_wedge_state`'s `gagged` means the page
holding the air **stopped polling**; the live fault was the opposite — an
owner polling happily while muting the whole house. So the rung was still
skipped, through 317 seconds of silence, with `gagged=False` and triangulate
saying `gagged` on every poll. Two genuinely different faults wearing one
word. They are reported separately now: `gagged` keeps its meaning and
`solo_gagged` carries triangulate's.

Then the gate went altogether. There is nothing left to gate on — every
branch above returns the moment sound is heard, so the ladder only *arrives*
at RELEASE when nothing is being heard, and releasing is right at that point
whatever the reason. The old else-branch said "the air is held by a page that
is answering — left alone", and a page that is ANSWERING is not a page that
is being HEARD. That distinction is the entire reason this endpoint exists.

> Three diagnostics in a row, each one fixed and each one still lying. The
> fix is never done until it has been watched against the real fault.

### And five more after it (#1338)

That audit asked which cures the operator had no button for. The next one
asked a different question — which *rooms* the ladder never walks into at
all. Five:

- **DRAIN** (6). Two shelves hold finished renders that only their own
  timers drain: the box's hold queue and the render backlog. A starved air
  can be silent standing next to speech that is already on disk. It belongs
  beside FLUSH — FLUSH throws away what the page cannot start, DRAIN puts
  back what the station already made — and it is cheap, because that audio
  exists.
- **STOCK** (7). `unheard_stock_air(force=True)` drops the seven-minute
  interval and the floor test (#1313) and puts the longest-unheard finished
  round on the air out of turn (#1260). Its only callers were watchdog
  timers. If the cupboard refuses it says why, and falls back to replaying
  the last segment.
- **STREAM** (12). Everything above that line is about the speakers in this
  house. The public door on :8097 and the mp3 mixer behind `/stream.mp3`
  are how the broadcast *leaves* it, and neither had a rung: the door is an
  unsupervised startup task, and the mixer's own `running` flag is set true
  before its thread has made a single frame and stays true after that thread
  is dead. The rung deliberately ignores that flag and samples the frame
  counter instead, then revives the mixer.
- **ENGINES** (13). The steward's table is xtts, ollama and comfyui. F5
  carries the clones whenever XTTS is offloaded, and the voice-director is
  the middleman every engine handle goes through — when *it* is the
  casualty, restarting the station around it changes nothing. The director
  is bounced **only when it does not answer**, because a healthy one holds
  every engine loaded behind it. Before DEEP, because a deep ladder asking
  a dead director is asking nobody.
- **DISK** (17). A box with no room left writes nothing — no render, no
  larder, no log — and that fault survives a restart. It presses the
  bounded retention sweep and **names** what is big and what is over its
  cap. It deliberately **refuses** the three purge routes that require
  areas to be named by hand: those take named areas on purpose, and a
  ladder guessing a cutoff is exactly the slip that guard exists to stop.

All five were exercised against the live station.

**A rung that can block past the client's timeout silently kills every rung
after it.** STOCK waits for the line to actually reach the air — a render
*and* a playout — and from the console it ran past **120 s**, at which point
the caller gave up. On a ladder that is not one slow step: the run ends
there, and DEVICES, RELEASE, PAGES, TERMINAL and everything below them
never happen, with nothing in the transcript saying so. It is bounded to
**25 s** now, and the wait was never the work — the round is queued either
way and the page starts it at its next poll — so the honest thing is to
stop waiting and say so (#1340).

And say it in words. The handler's broad `except Exception` sat **above**
the narrow `except asyncio.TimeoutError`, and a `TimeoutError` *is* an
`Exception`, so the narrow clause could never run — and a `TimeoutError`
carries no message, so the transcript read *"the cupboard raised: "* with
nothing after the colon (#1340b). An empty reason is worse than no line at
all: it tells the operator something went wrong and refuses to say what.

### The rung that exists because of §19.1

For a long time the ladder's entire client-side vocabulary was `fixUngag()`
— this tab only — and a page reload. Against the fault documented in §19.1
that is nothing: the WebView's network service lives in the app process, so
a reload hands the new page **the same dead stack**. Two of the rungs were
therefore no-ops on this tablet, and both printed as successes.

`9 TERMINAL` is the cure §19.1 already names. The station has no adb and no
reach into the tablet; the desktop app has both. So the station *stamps*
`kiosk_kick` onto the state the desktop is already polling, and the desktop
runs `am force-stop` then `am start` — the same shape as `reload_pages`,
which is how a flag on the far side of a process boundary gets reached at
all.

It acts only on a **new** stamp, so a station restart — which re-sends the
last value — cannot put the tablet into a restart loop.

> Everything before this could reload a client. Nothing could restart one.

### And it could not reach its own rung eleven

`reload_pages` stamps `_RADIO["reload_at"]`; every open page sees it on the
next poll and reloads 0.8–4.8 s later — **including the operator's own**. The
run was sitting in the eight-second wait with no resume mark written, so
`fixResume` found nothing and it simply ended. Everything below it — STREAM,
ENGINES, DEEP, SERVICES, RELOAD, DISK and RESTART — never ran, and the
transcript's last line read *"10 PAGES asked every page in the house to
reload itself"*, which looks exactly like success.

That is why the deep repair had to be run by hand against a live wedge: the
button could not reach its own rung 11. The mark is now written **before**
the reload is asked for.

Two more from the same audit. **ON AIR never touched the switch** —
triangulate returns `off_air → onair` when `_RADIO["on"]` is false, and the
step only ever looked at `radio_paused()`, so the one cure named for a
switched-off station changed nothing. And **DEVICES now runs before
RELEASE**, because for the `#1187` fault they are cause and symptom:
releasing first hands the exclusive to a second device whose switch is also
off, so the "sound is back" check could never pass.

> **A cure the operator cannot reach during the fault it cures is not a cure
> the station has.** Four of these existed as working code for months.

### Reaching past the button

Every rung is also a step you can run alone, which is what to do when you
already know the answer:

```sh
B=http://10.89.1.246:8096
K=$(curl -s $B/ | grep -o 'SERVER_KEY = "[^"]*"' | cut -d'"' -f2)

curl -s $B/api/broadcast/health          | jq .   # is anyone hearing it
curl -s $B/api/broadcast/console         | jq .   # the whole step table + log
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/look
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/terminals
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/floor
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/drain
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/stock
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/stream
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/engines
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/steward
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/deep
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/disk
```

`look`, `speed` and `triangulate` change nothing and are always safe.

**The tune-in page has no rail.** `RADIO_PAGE_HTML` carries no Reinitialise
drawer — a listener there has `retime()` and the one-way unpause and nothing
else. If the tablet is on the tune page rather than the panel, the button you
want is not on the screen you are looking at.

**The Electron shell has a second, separate one-tap.** `panicRecover()` in
`renderer.js` walks `/api/service/restart` → `/api/pinebox/initialize` →
`/api/pinebox/recover`. It does not touch `/api/broadcast/*`, and Reinitialise
does not touch `/api/pinebox/*`. Two buttons, two disjoint trees; if one has
not helped, the other is not a repeat.

## 24. The Pine Cam

A 4K Wi-Fi body camera (`H88_…`, an access point at `192.168.1.254`). It is
held by the **spare USB radio** on the DGX (`wlx984827b6b478`, an RTL8821AU),
never by the station's own (`wlP9s9`, which carries `10.89.1.246` and the
broadcast); `tools/pinelink.py` refuses to run at all unless the station's
radio still holds that address, and the camera's NetworkManager profile is
pinned to the spare interface at priority −10 so it cannot be brought up on
the wrong one. One ffmpeg pulls the RTSP stream and writes two things with
`-c copy`: five-minute recordings under `data/pinelink/clips/` and an HLS
playlist, plus a `frame.jpg` four times a second. That JPEG is what every
surface shows — Chromium plays no HLS without a library this project does
not vendor, and the tablet's WebView is the same engine.

### On the tablet

The tablet has no glass bar to hang a camera button in, so `pine-cam.js`
builds its own: a small pulsing **CAM** flag on the right edge, above the
view rail, that appears only while the link is live and goes when the camera
does. Tap it for the picture-in-picture box — draggable, remembers where you
left it, closes itself if the link drops rather than freezing on the last
frame. (Before #1358 the file answered `undefined` for the station's address
off the desktop and looked for a button that only the Electron chrome has,
so on this tablet it did nothing at all.)

### On the desktop

The **Pine Cam** row in the sidebar reads like the tablet's row: what it is,
whether it is reachable, what it is costing. It is always listed, because a
device that only appears when it is working cannot tell you it is not. The
tools icon beside the fold is the whole ladder from one press: ask the
doctor, press the cure it names, wait for the link, open the picture — or
say plainly that the camera itself is not on the air, because then the next
move is a button on the camera. Under the fold: Look, Troubleshoot, **Reset
radio**, Snapshot, Record, the on-air preference, and the viewer picker.

Record is a **cut, not a capture**: the link is recording continuously
anyway, so the button marks a moment, marks another, and the station cuts
that span out of what is already on disk (`POST /api/pinelink/cut`). Nothing
is missed at the head while a stream opens, stopping is instant, and the
camera is never asked for a second client — these access-point cameras
commonly refuse one. Save As goes through the Electron shell; a page cannot
save a file where you want it.

### Who may see it

Three positions, not a switch: **nobody**, **picked**, **anyone with a
link**. "Picked" is a tick beside each tune-in link on the Share panel, and
the tick is stored *on the link* (`shares.json`), so revoking the link
revokes the camera and no orphan permission is left pointing at nobody. The
tune-in page asks `GET /api/pinelink/mine?t=<token>` — which answers for
that token and lists no one else — and draws the same JPEG in a corner box.
Every branch was measured against the running station: ticked 200, unticked
403, forged tag 403, mode off 403, no token on `:8097` 403. That last one was
a hole this work opened and closed on the same day; see `docs/extending.md`
§6.1.

### When it will not join

The troubleshooter names the fault and the cure, and asks the questions in
the order that matters:

1. **Is the kernel still accepting neighbours?** On 2026-09-14 the camera was
   on, the radio associated, and authentication timed out three tries
   running while every reading said "healthy". The ARP table held 1,019
   entries against a ceiling of 1,024 — five Docker bridges holding ~250
   each — and a kernel that cannot record a new neighbour cannot finish an
   ARP exchange with a device it has just met. `tools/99-pine-neigh.conf`
   raises the ceiling (1024/4096/8192) and lets the collector run; the
   table went from 1,019 to 23 the moment it did.
2. **Does the radio see anything at all?** After refused associations this
   chipset stops scanning entirely — admin-UP, no carrier, zero networks
   with no error. `ip link` down/up does not clear it. **Reset radio** does:
   an unbind/re-bind on the USB bus, through the host bridge
   (`pinelink-kick.path`), because there is no `systemctl` inside the
   container and the old Connect button could never have worked.
3. **Is the camera on the air?** If the radio sees other networks and not
   the camera's, the camera has slept its Wi-Fi to save battery or is out of
   its ten-metre reach. Press the camera's Wi-Fi button; bring it closer.

## 25. The clip doctor and the clip book

### The day the station played no clips

`/samples` inside the container held **zero files** while the same path on
the host held 44 entries and 32,367 video clips. The share had not gone
away; the container's bind had. On the host `/home/ehm_eckx/samples` was
`dev=122` (the CIFS filesystem); inside, `/samples` was `dev=66306` — the
host's root disk. The container was looking at the empty directory
*underneath* the mount.

A Docker bind is resolved when the container is **created** and is
`rprivate`, so a share mounted on the host afterwards never propagates in.
`docker compose restart` does not recreate the container — restarting, the
obvious move and the ladder's last rung, could never have fixed this. Only
`docker compose up -d --force-recreate spark-agent` does. Every reader in
the station answered "no samples", which is indistinguishable from an empty
library, so nothing could see it. `GET /api/sfx/doctor` now prints the tell
first: the device id of `SFX_ROOT` against the station's own data directory.

### The book (#1362)

Four earlier attempts at "the video button must be instant" were all a memo
in RAM in front of the same share walk, so every restart put the button back
at *still warming* for as long as the walk took — and the walk was dying
silently behind an `except Exception: pass`. `data/sfx_clips.db` is a SQLite
book of every clip: path, length, playable. An indexer thread writes it,
commits **per folder**, and starts at boot; a tap is one indexed read on a
reader connection of its own, on an executor of its own, and never touches
the share. Measured with the indexer still walking: `/healthz` 5–22 ms, the
tap 11–25 ms on eleven of twelve; after a restart the book already held
20,724 playable video clips before any walk began.

Two things only measuring found: a random-rowid pick returned the **same
clip four times in ten** (rows are written a folder at a time, so the first
clip after each run of audio wins — it is `COUNT`+`OFFSET` now, uniform);
and the length lookup keyed the ledger by `path:mtime`, a stat on CIFS —
the book hands the length over with the path.

### The popup

A miss on the video button used to print *"still warming — tap again"* for
four different faults, only one of which tapping again cures. It opens the
**clip doctor** instead: the station's verdict, the steps, the counts, and
four thumb-sized buttons — **Rebuild** (every clip cache cleared and the
library read again), **Ping the server** (is the share answering, and how
fast — a slow answer is as much the diagnosis as a failed one), **Query the
folders** (what is actually in each named clip folder), **Try a clip**. The
cure the doctor named gets the accent. One file serves both surfaces:
`clip-doctor.js` uses bare paths where the page is served by the station and
the bridge where the document is `file://`.

### The dead air was not the script

The operator's model was that the hour has holes because the scripts are not
dense enough. `GET /api/deadair` reads the gap ledger and says which of two
*opposite* faults an hour was — a famine (write more) or a stall (take the
named function off the loop). Over 24 hours: **93% of all dead air was a
blocked event loop**, and the record named the blockers. The largest single
one was the sample pool's `publish` callback re-filtering the whole
accumulated list through `sfx_id()` twice per path on every emit, on the
loop, ~2,500 times per walk, once a minute (#1370). The next were the
learning desks writing SQLite synchronously from inside the tint pass
(#1371). `air_first()` now reads the pulse sentinel and stands the desks
down the moment the loop is late rather than after twelve seconds of
silence (#1372). The census carries the numbers; the note
`docs/notes/the-bind-underneath-the-mount.md` carries the day.

## 26. The SCRIPT view's two new controls, and every report's telemetry

**The loop button** beside the video button (#1385) puts the SFX guy into
endless video: clips one after another, chosen at random from the whole
collection, until you press it again. It is a *held* setting on the station
(`/api/sfx/video/mode`, #1366), so it survives a restart and this view
coming and going; turning it off takes effect at the end of the clip on the
tube rather than cutting it. Lit red while it runs. His picture dial
(`sfx_video_share`, default 67) is what decides the mp4:mp3 mix the rest of
the time — two mp4s for every mp3, as asked in #1100.

**The search box** in the same bar (#1385, for #1110): type a word, press
Enter, and the station answers with every time it was said on the air in
the last two days and — the part that was actually asked for — *why*. The
verdict is one of four shapes, each with a different cure: **REPEATS** (a
few lines re-aired over and over; the repetition desk, not a prompt),
**ONE ROAD** (one writing road leans on it; look at what that road is
written from), **ONE VOICE** (a persona or a seat's prompt), or **SPREAD**
(the word is simply common in what the station writes; the crystal's
banned-words list is the lever). Under it: the counts by road and voice,
the most-repeated lines with their tallies, and the airings newest first.
`GET /api/said/search?q=` is the road; the box only draws what it says.

**Every report now carries the station's own account of the moment**
(#1379, for #1094/#1095/#1098). A request filed from the Pine Chat panel —
on the tablet, the desktop or a phone — gets a `### Station at the time`
block appended before its attachments: what is playing, what is being said,
the last five lines, the script position (block/ord), the listeners and
each device's out-loud switch, the loop's pulse, the last hour's dead air
with its verdict, the ladder's LOOK, the tablet's state and the learning
desk. Repeats still fold into the request they repeat, because the gist
stops at the marker. The point is the one #1095 made: *"the station is
playing on the tablet, yet the application is saying it's unable to locate
the tablet"* — the report now arrives with the evidence that would have
settled it.

## 27. The endless set is a playlist, and the desktop's tube lights itself

**Clip after clip (#1395).** The loop button's first cut rang *one* clip, a
second before the one on the tube ran out, and drew it from the memo pool.
Measured on the desktop with the mode lit and "the room is quiet" on the
strip, three things made that gap-ridden: the sets poll `/api/dj/video`
every 2.5 s, so a clip rung one second early was seen up to 1.5 s *after*
the tube went dark; a set discards a clip more than 8 s late, and this
station's loop stalled for 8 s often enough that a stall at the wrong
moment dropped the clip and the tube stayed dark for the whole length of
the one that never played; and the memo pool is empty for minutes after
every restart while the clip book (#1362) already holds tens of thousands
of playable clips. Now the station keeps a short playlist rung *ahead*
from the book: each clip is stamped with a start after the previous one's
end, three deep and about twenty seconds ahead. The sets hold the next clip
before they need it and light each on its own timer ("early is not late"),
so a stall of a few seconds on the station changes nothing on the screen.
`/api/sfx/video/mode` says how far ahead it is — `queued` (clips the sets
hold), `ahead_s`, `book` (48,103 playable video clips today), `rung` (total
since boot). Measured: three different clips on the tablet in twelve
seconds with no black between them; on the desktop the tube's `currentTime`
went 2.5 → 7.5 s across a five-second probe at readyState 4. The picture
door's own rule still holds — no lead, no reservation, no claim on the air —
so an endless set cannot mortgage the show.

**The desktop's tube (#1399).** On the desktop the set lives in the *shell*,
not the panel webview, so it floats over every view — and it used to wait
for the shell to mount it. After a reload the shell never did: `PineSfxTv`
was there, the tube was not, and the loop button lit a set nobody could
see. `sfx-tv.js` now mounts itself when it loads in the desktop shell (base
URL from the station setting, `http://127.0.0.1:8096` as the fallback) and
on any http(s) page with `baseUrl ''`; inside the kiosk the bridge still
mounts it with the tablet's base. Verified over CDP: `.sfx-tv` present with
a playing `<video>` thirteen minutes after a reload. (Numbered #1399 — the
continuity agent's #1397 in `app.py` is a different thing.)

**Pictures are not a stuck queue (#1405).** The reinitialise ladder's LOOK
and the wedge detector counted every delivery the page had *received* and
not *started* as "handed over and not started". With the playlist rung
ahead that read *19 waiting, the head 690 s old* on a station that was
audibly playing — past `PAGE_WEDGE_WAITING` (4), which is to say the ladder
could have cured a fault that did not exist. `page_delivery_waits()` now
excludes picture-only rows and any clip whose `broadcast_ms` is still to
come, and every counter — the wedge state, the LOOK line, the ladder's rung
and the oldest-waiting list — reads through it.
