/* #1183: THE MPC'S DISK, ON THE DESK.
 *
 * "Basically the Pine Box app needs the same feature set as what we have
 *  going on with the Pine Box tab. So it needs feature parity, so there's
 *  nothing left out."
 *
 * renderer/sampler.js:1368-1462 and renderer/sampler-kits.js:670-715 have
 * been calling usbState, usbPick, usbSend, usbList and usbRead on this
 * surface for as long as they have existed, and this surface answered none
 * of them. Both call sites guard with `typeof ... !== "function"` and say
 * "This terminal cannot reach a USB disk", so the operator got a polite
 * refusal on the desk and a working MPC door on the tablet.
 *
 * WHAT A "USB DEVICE" IS HERE, AND WHY THIS IS NOT THE TABLET'S ROAD.
 *
 * On the tablet these five are the Storage Access Framework: there is no
 * path to an OTG volume, so the operator points at a document tree once and
 * the app holds a persistable grant (gallery/UsbTarget.kt). None of that
 * exists on Windows and none of it is needed. An MPC put into USB disk mode
 * comes up as A DRIVE LETTER. Copying a folder onto it is exactly what the
 * operator would do by hand in Explorer, and plain fs does it.
 *
 * So this is a real road, not a pretend one: real volumes, a real folder
 * picker, real files copied to a real letter. The SHAPES are the tablet's
 * shapes, field for field, because sampler.js reads both.
 *
 * THE ONE PLACE THE TWO MACHINES HONESTLY DIFFER is `anyRemovable`.
 * Android's StorageManager states plainly whether a volume is removable and
 * whether it is mounted. Windows does not: Win32_LogicalDisk's DriveType
 * says 2 (removable) for a flash stick but 3 (local fixed) for any USB disk
 * whose firmware clears the removable-media bit - and an MPC Live's internal
 * SSD in disk mode is exactly that. Reporting DriveType alone would mean the
 * panel says "No USB disk is attached" with the MPC plugged in and lit,
 * which is the precise failure the tablet's own note warns about. So a
 * volume counts as removable here when DriveType is 2 OR when it sits on a
 * disk whose InterfaceType is USB, and both facts are reported in `volumes`
 * so the operator can see what the question actually returned.
 */
const fs = require("node:fs");
const path = require("node:path");
const { execFile } = require("node:child_process");

/* About a megabyte of file per answer, which is ~1.4 MB of base64. The same
 * number gallery/UsbBrowse.kt uses, and for the same reason: a bank of long
 * grabs is tens of megabytes and one answer that size is a stall.
 *
 * NOT a multiple of three, and that is correct HERE where it would be wrong
 * elsewhere. sampler-kits.js:696 decodes EACH chunk on its own and
 * concatenates the resulting bytes, so every chunk carries its own padding
 * and nothing is lost. The bug that made chunk size a multiple of three
 * elsewhere was a caller that concatenated the base64 and decoded once. */
const CHUNK = 1024 * 1024;

/* WHAT THE VOLUME SWEEP COSTS, AND WHY IT IS REMEMBERED FOR A MOMENT.
 *
 * The two CIM queries below take between half a second and two seconds on
 * this machine, and sampler.js:1373-1383 calls usbState, then usbPick, then
 * usbState again inside one click. Asking Windows the same question three
 * times in four seconds is three pauses the operator feels for no new
 * information. Six seconds is short enough that a disk plugged in while the
 * sheet is open is seen on the next click. */
const SWEEP_HOLD_MS = 6000;

/* A drive that is not there answers fast; a disconnected mapped network
 * letter can hang for thirty seconds. The sweep is on a click, so it is
 * given a hard ceiling and falls back to letter-probing rather than leaving
 * the operator looking at a button that does nothing. */
const SWEEP_MS = 8000;

/* The PowerShell that answers "what disks are there, and which of them
 * arrived over USB". One invocation, because two would be two startups.
 *
 * The USB set is built FIRST, by walking Win32_DiskDrive (where
 * InterfaceType lives) down through its partitions to the logical disks
 * (where the drive letter lives). There is no direct association between a
 * logical disk and its physical drive, which is why this is two hops and
 * not one. Anything that throws on the way is skipped: a disk that is being
 * removed mid-query must not cost the whole listing. */
const SWEEP_PS = [
  "$usb=@{};",
  "try{Get-CimInstance Win32_DiskDrive -ErrorAction Stop|",
  "Where-Object{$_.InterfaceType -eq 'USB'}|ForEach-Object{",
  "try{Get-CimAssociatedInstance -InputObject $_ -ResultClassName Win32_DiskPartition -ErrorAction Stop|",
  "ForEach-Object{try{Get-CimAssociatedInstance -InputObject $_ -ResultClassName Win32_LogicalDisk -ErrorAction Stop|",
  "ForEach-Object{$usb[$_.DeviceID]=$true}}catch{}}}catch{}}}catch{};",
  "Get-CimInstance Win32_LogicalDisk|ForEach-Object{[pscustomobject]@{",
  "id=$_.DeviceID;type=[int]$_.DriveType;label=$_.VolumeName;",
  "size=[int64]$_.Size;free=[int64]$_.FreeSpace;usb=[bool]$usb[$_.DeviceID]}}|",
  "ConvertTo-Json -Compress"
].join("");

class UsbDisk {
  /**
   * @param read  () => config object - where the chosen disk is remembered
   * @param write (patch) => config - the same store the rest of the desk uses
   * @param downloads () => the folder the kit exporter wrote into, which is
   *        what usbSend copies FROM. Passed in rather than computed here so
   *        this module never has to know about Electron's app object.
   *
   * THEY ARE HELD UNDER DIFFERENT NAMES THAN THEY ARRIVE UNDER, and that is
   * not tidiness. Written as `this.read = read` the config getter lands on
   * the instance and SHADOWS the prototype's own read() - the one that hands
   * back a chunk of a file - so usbRead answered with the config object
   * instead of bytes. Caught by running it: read() came back as
   * {usbDisk, usbDiskName} and sampler-kits.js:698 would have thrown on
   * atob(undefined) for every sample on the card.
   */
  constructor({ read, write, downloads }) {
    this.config = read;
    this.save = write;
    this.downloads = downloads;
    this.sweptAt = 0;
    this.swept = null;
  }

  /* ---------------------------------------------------------- the volumes */

  /**
   * Every volume Windows can see, with the two facts that matter.
   *
   * Shape per row matches UsbTarget.volumes as closely as the two systems
   * allow: {name, removable, primary, state, path}. `state` is "mounted"
   * for anything that answered, because a letter that answers IS mounted -
   * there is no Android MEDIA_UNMOUNTED equivalent to report.
   */
  async volumes() {
    const now = Date.now();
    if (this.swept && now - this.sweptAt < SWEEP_HOLD_MS) return this.swept;
    let rows = null;
    if (process.platform === "win32") {
      rows = await this.sweepWindows();
    }
    if (!rows) rows = this.sweepLetters();
    this.swept = rows;
    this.sweptAt = Date.now();
    return rows;
  }

  sweepWindows() {
    return new Promise((settle) => {
      let done = false;
      const give = (value) => { if (!done) { done = true; settle(value); } };
      const timer = setTimeout(() => give(null), SWEEP_MS);
      try {
        execFile("powershell.exe",
          ["-NoProfile", "-NonInteractive", "-Command", SWEEP_PS],
          { windowsHide: true, timeout: SWEEP_MS, maxBuffer: 1024 * 1024 },
          (error, stdout) => {
            clearTimeout(timer);
            if (error) { give(null); return; }
            try {
              const said = JSON.parse(String(stdout || "").trim() || "null");
              /* ConvertTo-Json hands back a bare object when there is
               * exactly one volume, and an array when there is more than
               * one. A machine with a single C: is not a rare case. */
              const list = said == null ? [] : (Array.isArray(said) ? said : [said]);
              give(list.map((row) => this.dressVolume(row)));
            } catch (err) { give(null); }
          });
      } catch (err) { clearTimeout(timer); give(null); }
    });
  }

  dressVolume(row) {
    const id = String((row && row.id) || "");
    const type = Number((row && row.type) || 0);
    const usb = !!(row && row.usb);
    const label = String((row && row.label) || "");
    const system = String(process.env.SystemDrive || "C:").toUpperCase();
    return {
      /* What the operator sees on the picker and in the note: "PINEBOX (E:)"
       * when the volume is labelled, the bare letter when it is not. */
      name: label ? label + " (" + id + ")" : id,
      path: id + "\\",
      /* DriveType 2 is Windows saying "removable media". `usb` is the
       * InterfaceType walk. Either one is enough - see the note at the head
       * of this file for the MPC Live SSD that reports neither removable
       * media nor a floppy but is unmistakably the thing plugged in. */
      removable: type === 2 || usb,
      usb,
      driveType: type,
      /* The Windows drive, which is never the MPC. Reported the way
       * UsbTarget reports the tablet's own storage: listed and marked, so
       * the operator knows the question was asked rather than skipped. */
      primary: id.toUpperCase() === system,
      state: "mounted",
      bytes: Number((row && row.size) || 0),
      free: Number((row && row.free) || 0)
    };
  }

  /**
   * WHEN POWERSHELL WILL NOT ANSWER.
   *
   * Execution policy, a locked-down machine, a PATH without powershell.exe,
   * or simply a sweep that ran past its ceiling. Probing letters with stat
   * still finds every volume; what it cannot find out is which of them is
   * USB.
   *
   * So in this fallback every non-system letter is marked removable. That is
   * deliberately generous and it is the safe direction: the worst it causes
   * is the folder picker opening when the MPC is not plugged in, and the
   * operator closes it. The other direction - "No USB disk is attached" with
   * the MPC sitting there lit - is the one that makes a feature feel broken,
   * and nothing here is allowed to say that on a guess.
   */
  sweepLetters() {
    const out = [];
    const system = String(process.env.SystemDrive || "C:").toUpperCase();
    for (let code = 67; code <= 90; code += 1) {          /* C: through Z: */
      const id = String.fromCharCode(code) + ":";
      let there = false;
      try { there = fs.statSync(id + "\\").isDirectory(); } catch (err) { there = false; }
      if (!there) continue;
      const primary = id === system;
      out.push({ name: id, path: id + "\\", removable: !primary, usb: false,
        driveType: 0, primary, state: "mounted", bytes: 0, free: 0 });
    }
    return out;
  }

  /* ----------------------------------------------------- the chosen disk */

  /**
   * Where the kit goes, or "" when nothing has been pointed at.
   *
   * CHECKED, NOT ASSUMED, exactly as UsbTarget.target re-checks its
   * persisted grant: a drive letter is remembered across restarts and the
   * card behind it can be unplugged, reformatted, or handed a different
   * letter. A write into a letter that is no longer there is an ENOENT the
   * operator cannot act on; "no disk has been chosen" is something he can.
   */
  chosen() {
    const cfg = this.config() || {};
    const where = String(cfg.usbDisk || "");
    if (!where) return "";
    try { return fs.statSync(where).isDirectory() ? where : ""; }
    catch (err) { return ""; }
  }

  chosenName() {
    const cfg = this.config() || {};
    if (!this.chosen()) return "";
    return String(cfg.usbDiskName || cfg.usbDisk || "");
  }

  remember(where, name) {
    this.save({ usbDisk: String(where || ""), usbDiskName: String(name || "") });
  }

  /**
   * usbState - sampler.js:1373 and :1445.
   *
   * {ok, chosen, name, canHost, anyRemovable, volumes} - PineDesktopBridge.kt
   * "usbState". sampler.js reads `chosen`, `anyRemovable`, `canHost` and
   * `name`; the rest is reported because seeing it is how a "nothing
   * happened" is told apart from a question that was never asked.
   *
   * `canHost` is always true. The tablet asks the package manager for
   * FEATURE_USB_HOST because a tablet may genuinely not have it - a GSI
   * without the feature was measured. A Windows PC with a USB port is a USB
   * host by construction, and sampler.js:1449 prints "This tablet cannot act
   * as a USB host" on false, which is not a sentence this surface should
   * ever show.
   */
  async state() {
    const volumes = await this.volumes();
    const chosen = this.chosen();
    return {
      ok: true,
      chosen: !!chosen,
      name: this.chosenName(),
      canHost: true,
      anyRemovable: volumes.some((row) => row.removable && !row.primary),
      volumes
    };
  }

  /**
   * usbPick - sampler.js:1381 and :1460.
   *
   * {ok, name, detail}. The tablet opens ACTION_OPEN_DOCUMENT_TREE; the desk
   * opens a folder dialog, which reaches any letter and needs no grant. The
   * dialog itself is passed in, because this module must not require
   * electron - that is what keeps it testable from node.
   *
   * @param ask async ({defaultPath}) => "" | the folder chosen
   */
  async pick(ask) {
    const volumes = await this.volumes();
    /* Opened ON the likeliest disk rather than on nothing: the first
     * removable volume that is not the Windows drive. The operator can still
     * walk anywhere from there. */
    const first = volumes.find((row) => row.removable && !row.primary);
    let where = "";
    try { where = String((await ask({ defaultPath: first ? first.path : "" })) || ""); }
    catch (error) {
      return { ok: false, name: this.chosenName(),
        detail: String(error && error.message ? error.message : error) };
    }
    if (!where) {
      return { ok: false, name: this.chosenName(), detail: "nothing was chosen" };
    }
    /* Named after the volume it sits on where one matches, so the note in
     * sampler.js:1396 says "Copying to PINEBOX (E:)" and not a raw path. */
    const on = volumes.find((row) => where.toUpperCase()
      .startsWith(String(row.path || "").toUpperCase()));
    this.remember(where, on ? on.name : where);
    return { ok: true, name: this.chosenName(), detail: "" };
  }

  /* ---------------------------------------------------------- reading it */

  /**
   * A path under the chosen disk, or "" when it tries to leave.
   *
   * The page hands these back from its own listings, so in ordinary use they
   * are already safe - but a page is not a trust boundary, and ".." in a
   * relative path is how a folder listing becomes a read of C:\Users. The
   * tablet cannot have this bug: SAF walks findFile child by child and there
   * is no parent to name. Here it has to be checked.
   */
  under(root, rel) {
    const parts = String(rel || "").split(/[\\/]+/).filter(Boolean);
    for (const part of parts) if (part === "." || part === "..") return "";
    const full = path.resolve(root, ...parts);
    const base = path.resolve(root);
    if (full !== base && !full.startsWith(base.endsWith(path.sep) ? base : base + path.sep)) {
      return "";
    }
    return full;
  }

  /**
   * usbList - sampler-kits.js:678, painted by sampler.js:1506-1552.
   *
   * {ok, path, name, folders, files} or {ok:false, path, detail} -
   * UsbBrowse.list. Each row is {name, dir, bytes, at}; a folder that holds
   * an .xpm also carries {program}. Folders first, then files, each sorted
   * by name folded to lower case, because that is the order sampler.js
   * paints and it does no sorting of its own.
   */
  list(rel) {
    const out = { path: String(rel || "") };
    const root = this.chosen();
    if (!root) {
      return Object.assign(out, { ok: false, detail: "no disk has been chosen yet" });
    }
    const here = this.under(root, rel);
    if (!here) {
      return Object.assign(out, { ok: false,
        detail: "there is nothing at that path on the disk" });
    }
    let stat = null;
    try { stat = fs.statSync(here); } catch (err) { stat = null; }
    if (!stat) {
      return Object.assign(out, { ok: false,
        detail: "there is nothing at that path on the disk" });
    }
    if (!stat.isDirectory()) {
      return Object.assign(out, { ok: false, detail: "that is a file, not a folder" });
    }
    let kids = [];
    try { kids = fs.readdirSync(here, { withFileTypes: true }); }
    catch (error) {
      return Object.assign(out, { ok: false,
        detail: "that folder would not open: "
          + String(error && error.message ? error.message : error) });
    }
    kids.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    const folders = [];
    const files = [];
    for (const kid of kids) {
      let size = 0;
      let at = 0;
      try {
        const info = fs.statSync(path.join(here, kid.name));
        size = info.isDirectory() ? 0 : info.size;
        at = Math.round(info.mtimeMs);
      } catch (err) { /* a file that vanished mid-listing is still a row */ }
      const row = { name: kid.name, dir: kid.isDirectory(), bytes: size, at };
      if (row.dir) folders.push(row); else files.push(row);
    }
    /* A FOLDER THAT IS A KIT SAYS SO - the same one fact UsbBrowse answers
     * here rather than making the page open every folder to find out which
     * of them are kits. An MPC card has a handful of kits among hundreds of
     * samples and sampler.js:1379 labels them from this field alone. */
    for (const row of folders) {
      try {
        const inner = fs.readdirSync(path.join(here, row.name));
        const program = inner.find((name) => /\.xpm$/i.test(name));
        if (program) row.program = program;
      } catch (err) { /* unreadable: not a kit as far as anyone can tell */ }
    }
    return Object.assign(out, { ok: true, folders, files,
      name: path.basename(here) || String(rel || "") });
  }

  /**
   * usbRead - sampler-kits.js:696, in a loop until `eof`.
   *
   * {ok, path, offset, bytes, size, eof, base64} - UsbBrowse.read. `bytes`
   * is how many bytes THIS chunk carries, `size` is the whole file, and the
   * caller advances by the decoded length rather than by a promised chunk
   * size, so a short read is not a lost read.
   */
  read(rel, offset, want) {
    const out = { path: String(rel || ""), offset: Math.max(0, Number(offset) || 0) };
    const root = this.chosen();
    if (!root) {
      return Object.assign(out, { ok: false, detail: "no disk has been chosen yet" });
    }
    const file = this.under(root, rel);
    if (!file) {
      return Object.assign(out, { ok: false, detail: "no such file on the disk" });
    }
    let stat = null;
    try { stat = fs.statSync(file); } catch (err) { stat = null; }
    if (!stat) {
      return Object.assign(out, { ok: false, detail: "no such file on the disk" });
    }
    if (stat.isDirectory()) {
      return Object.assign(out, { ok: false, detail: "that is a folder, not a file" });
    }
    const size = stat.size;
    if (out.offset > size) {
      return Object.assign(out, { ok: false, detail: "that file is shorter than that" });
    }
    const take = Math.min(Math.max(1, Number(want) || CHUNK), CHUNK);
    let handle = null;
    try {
      handle = fs.openSync(file, "r");
      const buffer = Buffer.alloc(take);
      const got = fs.readSync(handle, buffer, 0, take, out.offset);
      return Object.assign(out, {
        ok: true,
        bytes: got,
        size,
        eof: out.offset + got >= size,
        base64: buffer.subarray(0, got).toString("base64")
      });
    } catch (error) {
      return Object.assign(out, { ok: false,
        detail: String(error && error.message ? error.message : error) });
    } finally {
      if (handle !== null) { try { fs.closeSync(handle); } catch (err) { /* gone */ } }
    }
  }

  /* ---------------------------------------------------------- writing it */

  /**
   * usbSend - sampler.js:1397.
   *
   * {ok, files, bytes, where, detail} - UsbTarget.sendFolder. The kit has
   * already been built and verified on local storage by exportMpc, so this
   * COPIES rather than rebuilding: building it twice is two chances for the
   * two copies to differ.
   *
   * FLAT, files only, exactly as sendFolder is. An MPC program names its
   * samples with no path, so a kit is one folder deep by construction, and
   * recursing would carry things the MPC has no use for.
   *
   * An existing folder of the same name is replaced FILE BY FILE rather than
   * deleted first. A half-deleted kit on a card the operator is about to
   * unplug is worse than a mixed one.
   */
  send(opts) {
    const asked = String((opts && opts.folder) || "");
    const into = String((opts && opts.into) || "")
      || asked.split(/[\\/]+/).filter(Boolean).pop() || "";
    const root = this.chosen();
    if (!root) {
      return { ok: false, files: 0, bytes: 0, where: "",
        detail: "no MPC disk has been chosen yet" };
    }
    if (!into) {
      return { ok: false, files: 0, bytes: 0, where: "",
        detail: "no kit folder was named" };
    }
    const from = this.under(this.downloads(), asked);
    if (!from) {
      return { ok: false, files: 0, bytes: 0, where: "",
        detail: "that is not a folder this app wrote" };
    }
    let there = false;
    try { there = fs.statSync(from).isDirectory(); } catch (err) { there = false; }
    if (!there) {
      return { ok: false, files: 0, bytes: 0, where: "",
        detail: "there is no kit at " + from };
    }
    const target = this.under(root, into);
    if (!target) {
      return { ok: false, files: 0, bytes: 0, where: "",
        detail: "that is not a folder on the chosen disk" };
    }
    try { fs.mkdirSync(target, { recursive: true }); }
    catch (error) {
      return { ok: false, files: 0, bytes: 0, where: target,
        detail: "could not make a folder on that disk: "
          + String(error && error.message ? error.message : error) };
    }
    let names = [];
    try { names = fs.readdirSync(from).sort(); } catch (err) { names = []; }
    let files = 0;
    let bytes = 0;
    for (const name of names) {
      const source = path.join(from, name);
      let info = null;
      try { info = fs.statSync(source); } catch (err) { info = null; }
      if (!info || !info.isFile()) continue;
      try {
        fs.copyFileSync(source, path.join(target, name));
      } catch (error) {
        return { ok: false, files, bytes, where: target,
          detail: "writing " + name + " failed: "
            + String(error && error.message ? error.message : error) };
      }
      files += 1;
      bytes += info.size;
    }
    if (!files) {
      return { ok: false, files: 0, bytes: 0, where: target,
        detail: "there was nothing in that kit to copy" };
    }
    /* A path a person can act on. The tablet has to reconstruct a readable
     * name from a content:// tree because SAF does not promise a real path
     * exists; here the real path IS the answer, and sampler.js:1399 prints
     * it straight into "Sent 17 files to ...". */
    return { ok: true, files, bytes, where: target, detail: "" };
  }
}

module.exports = { UsbDisk, CHUNK };
