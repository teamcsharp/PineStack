/* The restore image - is what we downloaded actually a way back?
 *
 * Unlocking the bootloader erases the tablet. The only thing standing
 * between "a Pine Box terminal" and "a brick with a Lenovo logo" is a
 * complete, verified stock firmware package sitting on disk BEFORE the
 * unlock. This module is the gate that says whether we have one.
 *
 * It answers three questions, in order of how much they matter:
 *   1. Is there a scatter file?             (without it SP Flash Tool is blind)
 *   2. Is every partition it asks for here? (a package missing `super` is
 *                                            not a restore, it is a hope)
 *   3. What is its hash?                    (so the thing we verified is
 *                                            provably the thing we flash)
 *
 * MediaTek scatter files are YAML with an .xml extension. They are parsed
 * leniently here on purpose: the aim is to find out what is MISSING, and a
 * strict parser that throws on an unexpected key would hide exactly that.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

/* Lose any of these and the tablet does not come back on its own.
 * `preloader` is the one that turns a soft brick into a BROM-only rescue. */
const CRITICAL = ['preloader', 'lk', 'lk_a', 'boot', 'boot_a', 'super', 'vbmeta', 'vbmeta_a'];

/* Files a scatter names but which are legitimately absent from a download:
 * the empty user partitions are formatted, never written. */
const NOT_SHIPPED = /^(userdata|cache|flashinfo|otp)$/i;

/* LMSA truncates extensions on the way out - the scatter arrives as
 * `MT6768_Android_scatter.t` and `.x`, not `.txt` and `.xml`. Measured on
 * the real TB310FU package, not guessed. */
function isScatter(name) {
  return /scatter.*\.(xml|txt|x|t)$/i.test(name);
}

/* What a partition image must BEGIN with to be that kind of image.
 *
 * This is the check that matters. A file called boot.img proves nothing;
 * a file starting with ANDROID! is an Android boot image. Verified against
 * the real Lenovo package for this device.
 */
const ANDROID_BOOT = [0x41, 0x4e, 0x44, 0x52, 0x4f, 0x49, 0x44, 0x21];    /* ANDROID!  */
const MTK_BLOB = [0x88, 0x16, 0x88, 0x58];
const MTK_PRELOADER = [0x4d, 0x4d, 0x4d];                                 /* MMM       */
const EMMC_BOOT = [0x45, 0x4d, 0x4d, 0x43, 0x5f, 0x42, 0x4f, 0x4f, 0x54]; /* EMMC_BOOT */

/* A rule may accept more than one signature, at more than one offset,
 * because one partition legitimately ships in several wrappings.
 *
 * The preloader is the case that proves it, and it cost a false alarm to
 * learn: preloader_raw.img and preloader_<board>.bin begin with MMM, while
 * preloader.img, preloader_emmc.img and preloader_ufs.img are the same
 * payload inside an EMMC_BOOT wrapper with MMM at 0x800. All five are
 * valid. Insisting on MMM at offset zero condemned three good files as a
 * corrupt download - on the real Lenovo package, first time out. */
const MAGIC = [
  {match: /^boot(-debug)?\.img$/i, name: 'Android boot',
    any: [{bytes: ANDROID_BOOT, at: 0}]},
  {match: /^vbmeta.*\.img$/i, name: 'AVB vbmeta',
    any: [{bytes: [0x41, 0x56, 0x42, 0x30], at: 0}]},
  /* super.img arrives as an Android SPARSE image; super_empty.img is raw
   * LP metadata ("gDla"), the empty partition table used when resetting
   * the dynamic partitions. Two formats, both legitimate, both here. */
  {match: /^super(_empty)?\.img$/i, name: 'dynamic super',
    any: [{bytes: [0x3a, 0xff, 0x26, 0xed], at: 0},
          {bytes: [0x67, 0x44, 0x6c, 0x61], at: 0}]},
  {match: /^dtbo\.img$/i, name: 'DTBO',
    any: [{bytes: [0xd7, 0xb7, 0xab, 0x1e], at: 0}]},
  {match: /^preloader.*\.(bin|img)$/i, name: 'MTK preloader',
    any: [{bytes: MTK_PRELOADER, at: 0},
          {bytes: EMMC_BOOT, at: 0},
          {bytes: MTK_PRELOADER, at: 0x800}]},
  {match: /^(lk|logo|md1img|scp|sspm|spmfw|gz|tee)\w*\.(img|bin)$/i,
    name: 'MTK bootloader blob', any: [{bytes: MTK_BLOB, at: 0}]}
];

function magicFor(name) {
  return MAGIC.find((entry) => entry.match.test(name)) || null;
}

function checkMagic(file, expect) {
  let fd;
  try {
    fd = fs.openSync(file, 'r');
    for (const signature of expect.any) {
      const head = Buffer.alloc(signature.bytes.length);
      const read = fs.readSync(fd, head, 0, head.length, signature.at || 0);
      if (read < head.length) continue;
      if (signature.bytes.every((byte, i) => head[i] === byte)) return true;
    }
    return false;
  } catch (err) {
    return false;
  } finally {
    if (fd !== undefined) { try { fs.closeSync(fd); } catch (err) { /* closed */ } }
  }
}

/* Is this text a scatter we can actually read, or ciphertext?
 *
 * Lenovo encrypts the scatter in LMSA packages, so the map is unreadable
 * even though every image beside it is plain. That is a fact about the
 * package, not a fault in it - and it must not be reported as corruption. */
function scatterIsReadable(text) {
  const sample = String(text || '').slice(0, 2048);
  if (!sample) return false;
  if (/partition_name\s*:|<partition_name>/i.test(sample)) return true;
  let printable = 0;
  for (let i = 0; i < sample.length; i += 1) {
    const code = sample.charCodeAt(i);
    if (code === 9 || code === 10 || code === 13 || (code >= 32 && code < 127)) printable += 1;
  }
  return (printable / sample.length) > 0.85;
}

/* Walk a firmware folder. Bounded depth: an LMSA download is a couple of
 * levels, and a runaway recursion over a whole drive is not a diagnostic. */
function walk(dir, depth = 0, out = []) {
  if (depth > 4) return out;
  let entries;
  try { entries = fs.readdirSync(dir, {withFileTypes: true}); }
  catch (err) { return out; }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, depth + 1, out);
    else if (entry.isFile()) {
      let size = 0;
      try { size = fs.statSync(full).size; } catch (err) { size = 0; }
      out.push({name: entry.name, path: full, size});
    }
  }
  return out;
}

/* Pull partition_name / file_name / is_download triples out of a scatter,
 * whether it is written as MTK's YAML or as real XML. */
function parseScatter(text) {
  const parts = [];
  let current = null;
  const push = () => {
    if (current && (current.partition || current.file)) parts.push(current);
    current = null;
  };
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    if (/^-\s*partition_index\s*:/i.test(line)) { push(); current = {}; continue; }
    if (/^<partition>/i.test(line)) { push(); current = {}; continue; }
    if (/^<\/partition>/i.test(line)) { push(); continue; }
    if (!current) current = {};

    let match = /^partition_name\s*:\s*(\S+)/i.exec(line)
      || /<partition_name>([^<]*)<\/partition_name>/i.exec(line);
    if (match) { current.partition = match[1].trim(); continue; }

    match = /^file_name\s*:\s*(\S+)/i.exec(line)
      || /<file_name>([^<]*)<\/file_name>/i.exec(line);
    if (match) { current.file = match[1].trim(); continue; }

    match = /^is_download\s*:\s*(\S+)/i.exec(line)
      || /<is_download>([^<]*)<\/is_download>/i.exec(line);
    if (match) { current.download = /true|1|yes/i.test(match[1]); continue; }
  }
  push();
  /* NONE is the scatter's own way of saying "nothing to write here". */
  return parts.filter((p) => p.partition
    && (!p.file || !/^none$/i.test(p.file)));
}

function sha256(file) {
  const hash = crypto.createHash('sha256');
  const fd = fs.openSync(file, 'r');
  try {
    const buffer = Buffer.alloc(1024 * 1024);
    let read;
    while ((read = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
      hash.update(buffer.subarray(0, read));
    }
  } finally { fs.closeSync(fd); }
  return hash.digest('hex');
}

/* One hash over the whole package: every shipped file's name and digest,
 * folded together in sorted order. Two folders with the same manifest hash
 * hold the same firmware, whatever they are called or wherever they sit. */
function manifestHash(files) {
  const rows = files.slice()
    .map((f) => f.name.toLowerCase() + ':' + f.sha256)
    .sort();
  return crypto.createHash('sha256').update(rows.join('\n')).digest('hex');
}

function inspect(dir, {hashFiles = true} = {}) {
  const report = {
    dir, at: Date.now(), found: false, scatter: null,
    partitions: [], missing: [], files: [], images: [], bytes: 0,
    manifest: '', notes: []
  };
  if (!dir || !fs.existsSync(dir)) {
    report.notes.push('That folder does not exist.');
    return report;
  }
  const all = walk(dir);
  if (!all.length) {
    report.notes.push('That folder is empty.');
    return report;
  }
  report.found = true;
  report.bytes = all.reduce((sum, f) => sum + f.size, 0);

  const scatter = all.find((f) => isScatter(f.name));
  if (!scatter) {
    report.notes.push('No scatter file here. SP Flash Tool cannot restore a '
      + 'MediaTek device without one, so this is not yet a restore image.');
    report.files = all.map((f) => ({name: f.name, size: f.size}));
    return report;
  }
  report.scatter = {name: scatter.name, path: scatter.path, size: scatter.size};

  /* Every image gets its magic bytes checked, whether or not the scatter is
   * readable. This is the load-bearing verification: it proves the files
   * ARE what their names claim, which a filename listing never can. */
  for (const file of all) {
    const expect = magicFor(file.name);
    if (!expect) continue;
    report.images.push({
      name: file.name, size: file.size, kind: expect.name,
      magicOk: checkMagic(file.path, expect)
    });
  }

  let text = '';
  try { text = fs.readFileSync(scatter.path, 'latin1'); }
  catch (err) { report.notes.push('The scatter file could not be read.'); return report; }

  report.scatter.readable = scatterIsReadable(text);
  if (!report.scatter.readable) {
    /* Not damage - Lenovo ships it this way. Say so plainly, because
     * "the scatter is unreadable" otherwise reads as a broken download. */
    report.notes.push('The scatter file is encrypted, as Lenovo ships it. '
      + 'SP Flash Tool cannot read it directly, so restore either through '
      + 'LMSA itself, or by flashing the images with fastboot - they are '
      + 'plain, and their magic bytes are checked below.');
    report.files = all
      .filter((f) => magicFor(f.name))
      .map((f) => {
        const row = {name: f.name, size: f.size};
        if (hashFiles) { try { row.sha256 = sha256(f.path); } catch (err) { row.sha256 = ''; } }
        return row;
      });
    if (hashFiles) report.manifest = manifestHash(report.files.filter((f) => f.sha256));
    return report;
  }

  const byName = new Map(all.map((f) => [f.name.toLowerCase(), f]));
  const shipped = [];
  for (const part of parseScatter(text)) {
    const file = part.file ? byName.get(part.file.toLowerCase()) : null;
    const entry = {
      partition: part.partition,
      file: part.file || '',
      download: part.download !== false,
      present: !!file,
      size: file ? file.size : 0
    };
    report.partitions.push(entry);
    if (file) shipped.push(file);
    else if (entry.file && entry.download && !NOT_SHIPPED.test(part.partition)) {
      report.missing.push(entry);
    }
  }

  const unique = [...new Map(shipped.map((f) => [f.path, f])).values()];
  report.files = unique.map((f) => {
    const row = {name: f.name, size: f.size};
    if (hashFiles) { try { row.sha256 = sha256(f.path); } catch (err) { row.sha256 = ''; } }
    return row;
  });
  if (hashFiles) report.manifest = manifestHash(report.files.filter((f) => f.sha256));
  return report;
}

/* Whether this package may be treated as a restore path. Deliberately
 * strict: a half-package that looks plausible is more dangerous than an
 * obviously absent one, because it buys false confidence right before the
 * one irreversible step. */
function restorability(report, identity) {
  const blockers = [];
  const warnings = [];

  if (!report || !report.found) {
    blockers.push('No firmware package found.');
    return {ok: false, blockers, warnings};
  }
  if (!report.scatter) {
    blockers.push('No scatter file, so SP Flash Tool has no map of the '
      + 'device. This is not a restore image.');
    return {ok: false, blockers, warnings};
  }
  /* A corrupt image is worse than an absent one: it flashes, and then the
   * tablet does not come back. Check this before anything else. */
  const bad = report.images.filter((image) => !image.magicOk);
  if (bad.length) {
    blockers.push('These files are not the images they claim to be: '
      + bad.map((image) => image.name).join(', ')
      + '. The download is corrupt - fetch it again.');
  }

  /* Lenovo encrypts the scatter, so the partition table cannot be read.
   * The images beside it are plain and individually verified, so this is
   * still a restore path - through LMSA, or by fastboot - but SP Flash
   * Tool's BROM rescue is NOT available with this package as it stands. */
  if (report.scatter.readable === false) {
    const kinds = new Set(report.images.filter((i) => i.magicOk).map((i) => i.kind));
    const need = [
      ['Android boot', 'boot'],
      ['AVB vbmeta', 'vbmeta'],
      ['dynamic super', 'super'],
      ['MTK preloader', 'preloader']
    ];
    const absent = need.filter(([kind]) => !kinds.has(kind)).map(([, label]) => label);
    if (absent.length) {
      blockers.push('Critical images are absent or unverifiable: '
        + absent.join(', ') + '.');
    }
    warnings.push('The scatter is encrypted, so SP Flash Tool cannot use '
      + 'this package directly. Restore through LMSA, or flash the verified '
      + 'images with fastboot. Keep LMSA installed - it is the way back.');
    return {ok: !blockers.length, blockers, warnings};
  }

  if (!report.partitions.length) {
    blockers.push('The scatter file named no partitions - it is probably '
      + 'truncated or not a scatter at all.');
    return {ok: false, blockers, warnings};
  }
  if (report.missing.length) {
    blockers.push('The scatter asks for ' + report.missing.length
      + ' file(s) that are not here: '
      + report.missing.slice(0, 6).map((m) => m.file).join(', ')
      + (report.missing.length > 6 ? ' and more' : '')
      + '. An incomplete package is not a way back.');
  }

  const have = new Set(report.partitions.filter((p) => p.present)
    .map((p) => p.partition.toLowerCase()));
  const absent = CRITICAL.filter((name) => !have.has(name));
  /* lk/lk_a, boot/boot_a and vbmeta/vbmeta_a are the same partition under
   * two naming schemes, so only complain when BOTH spellings are missing. */
  const pairMissing = (a, b) => absent.includes(a) && absent.includes(b);
  const reallyMissing = [];
  if (!have.has('preloader')) reallyMissing.push('preloader');
  if (pairMissing('lk', 'lk_a')) reallyMissing.push('lk');
  if (pairMissing('boot', 'boot_a')) reallyMissing.push('boot');
  if (pairMissing('vbmeta', 'vbmeta_a')) reallyMissing.push('vbmeta');
  if (!have.has('super')) reallyMissing.push('super');
  if (reallyMissing.length) {
    blockers.push('Critical partitions are absent: ' + reallyMissing.join(', ')
      + '. Without these the tablet cannot be put back to stock.');
  }

  if (!report.manifest) {
    warnings.push('The package was not hashed, so it cannot be proved later '
      + 'that this is the same firmware that gets flashed.');
  }
  if (identity && identity.device) {
    const wanted = identity.device.toLowerCase();
    const names = report.files.map((f) => f.name.toLowerCase()).join(' ')
      + ' ' + (report.scatter.name || '').toLowerCase();
    if (!names.includes(wanted)) {
      warnings.push('Nothing in this package mentions "' + identity.device
        + '". Check it is firmware for THIS model before relying on it.');
    }
  }
  return {ok: !blockers.length, blockers, warnings};
}

module.exports = {
  inspect, restorability, parseScatter, manifestHash, sha256,
  isScatter, checkMagic, magicFor, scatterIsReadable, CRITICAL, MAGIC
};
