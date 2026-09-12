/* The restore-image gate.
 *
 * These tests exist because of one irreversible fact: `fastboot flashing
 * unlock` erases the tablet, and the only way back is a complete stock
 * package on disk beforehand. Every assertion here is a refusal that
 * stands between the operator and a tablet that will not boot.
 *
 * The scatter fixture is MediaTek's real shape - YAML, in a file named
 * .xml - as shipped for MT6769 devices like the TB310FU.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {inspect, restorability, parseScatter, manifestHash} = require('../desktop/firmware.cjs');

const SCATTER = `############################################################################################################
#  General Setting
############################################################################################################
- partition_index: SYS0
  partition_name: preloader
  file_name: preloader_tb310fu.bin
  is_download: true
  type: SV5_BL_BIN

- partition_index: SYS1
  partition_name: pgpt
  file_name: PGPT
  is_download: true
  type: NORMAL_ROM

- partition_index: SYS2
  partition_name: lk_a
  file_name: lk.img
  is_download: true
  type: NORMAL_ROM

- partition_index: SYS3
  partition_name: boot_a
  file_name: boot.img
  is_download: true
  type: NORMAL_ROM

- partition_index: SYS4
  partition_name: vbmeta_a
  file_name: vbmeta.img
  is_download: true
  type: NORMAL_ROM

- partition_index: SYS5
  partition_name: super
  file_name: super.img
  is_download: true
  type: NORMAL_ROM

- partition_index: SYS6
  partition_name: userdata
  file_name: NONE
  is_download: false
  type: NORMAL_ROM
`;

/* Real magic bytes, taken off the actual Lenovo TB310FU package. A fixture
 * full of the word "BOOT" would pass a filename check and tell us nothing
 * about whether the verifier can spot a corrupt download. */
const magic = (bytes, tail) =>
  Buffer.concat([Buffer.from(bytes), Buffer.from(tail || 'payload')]);

const FULL = {
  'MT6769_Android_scatter.xml': SCATTER,
  'preloader_tb310fu.bin': magic([0x4d, 0x4d, 0x4d, 0x01], 'FILE_INFO'),
  'PGPT': 'PGPT-TABLE',
  'lk.img': magic([0x88, 0x16, 0x88, 0x58], 'lk'),
  'boot.img': magic([0x41, 0x4e, 0x44, 0x52, 0x4f, 0x49, 0x44, 0x21]),
  'vbmeta.img': magic([0x41, 0x56, 0x42, 0x30]),
  'super.img': magic([0x3a, 0xff, 0x26, 0xed])
};

function makeDir(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-fw-'));
  for (const [name, body] of Object.entries(files)) {
    fs.writeFileSync(path.join(dir, name), body);
  }
  return dir;
}

function without(...names) {
  const copy = Object.assign({}, FULL);
  for (const name of names) delete copy[name];
  return copy;
}

test('a MediaTek scatter is read despite being YAML in an .xml file', () => {
  const parts = parseScatter(SCATTER);
  const names = parts.map((p) => p.partition);
  assert.ok(names.includes('preloader'));
  assert.ok(names.includes('super'));
  /* NONE means "nothing to write", not a missing file. */
  assert.ok(!names.includes('userdata'), 'a NONE entry is not a shipped file');
  const preloader = parts.find((p) => p.partition === 'preloader');
  assert.equal(preloader.file, 'preloader_tb310fu.bin');
  assert.equal(preloader.download, true);
});

test('a complete package is accepted and hashed', () => {
  const dir = makeDir(FULL);
  const report = inspect(dir);
  assert.equal(report.found, true);
  assert.equal(report.scatter.name, 'MT6769_Android_scatter.xml');
  assert.deepEqual(report.missing, []);
  assert.ok(report.partitions.length >= 6);
  assert.ok(report.manifest.length === 64, 'a package hash is recorded');
  for (const file of report.files) assert.equal(file.sha256.length, 64);

  const verdict = restorability(report, {device: 'TB310FU'});
  assert.equal(verdict.ok, true);
  assert.deepEqual(verdict.blockers, []);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('the package hash is about content, not about where it sits', () => {
  const a = makeDir(FULL);
  const b = makeDir(FULL);
  assert.equal(inspect(a).manifest, inspect(b).manifest);

  const c = makeDir(Object.assign({}, FULL,
    {'boot.img': magic([0x41, 0x4e, 0x44, 0x52, 0x4f, 0x49, 0x44, 0x21], 'DIFFERENT')}));
  assert.notEqual(inspect(a).manifest, inspect(c).manifest,
    'a changed partition must change the hash');
  for (const dir of [a, b, c]) fs.rmSync(dir, {recursive: true, force: true});
});

test('no scatter means it is not a restore image, whatever else is there', () => {
  const dir = makeDir(without('MT6769_Android_scatter.xml'));
  const report = inspect(dir);
  assert.equal(report.found, true);
  assert.equal(report.scatter, null);
  const verdict = restorability(report);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers[0], /No scatter file/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a package the scatter says is incomplete is refused', () => {
  const dir = makeDir(without('super.img'));
  const report = inspect(dir);
  assert.equal(report.missing.length, 1);
  assert.equal(report.missing[0].file, 'super.img');
  const verdict = restorability(report);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /super\.img/);
  assert.match(verdict.blockers.join(' '), /not a way back/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a missing preloader is called out by name - it is the BROM lifeline', () => {
  const dir = makeDir(without('preloader_tb310fu.bin'));
  const verdict = restorability(inspect(dir));
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /Critical partitions are absent.*preloader/s);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('A/B spellings count - lk_a satisfies lk, and only both missing fails', () => {
  const dir = makeDir(FULL);
  const verdict = restorability(inspect(dir));
  assert.equal(verdict.ok, true,
    'lk_a / boot_a / vbmeta_a must satisfy the lk / boot / vbmeta requirement');
  fs.rmSync(dir, {recursive: true, force: true});
});

test('firmware for the wrong model is a warning the operator must see', () => {
  const dir = makeDir(FULL);
  const report = inspect(dir);
  const verdict = restorability(report, {device: 'TB350FU'});
  assert.equal(verdict.ok, true, 'it is still a complete package');
  assert.match(verdict.warnings.join(' '), /TB350FU/);
  assert.match(verdict.warnings.join(' '), /firmware for THIS model/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('an absent or empty folder is reported plainly, not as a crash', () => {
  const missing = inspect(path.join(os.tmpdir(), 'pine-fw-does-not-exist-xyz'));
  assert.equal(missing.found, false);
  assert.match(missing.notes.join(' '), /does not exist/);
  assert.equal(restorability(missing).ok, false);

  const empty = makeDir({});
  const report = inspect(empty);
  assert.equal(report.found, false);
  assert.match(report.notes.join(' '), /empty/);
  fs.rmSync(empty, {recursive: true, force: true});
});

test('an unhashed inspection warns that it cannot be proved later', () => {
  const dir = makeDir(FULL);
  const report = inspect(dir, {hashFiles: false});
  const verdict = restorability(report);
  assert.equal(verdict.ok, true);
  assert.match(verdict.warnings.join(' '), /cannot be proved later/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('manifestHash ignores ordering', () => {
  const one = manifestHash([{name: 'b.img', sha256: 'bb'}, {name: 'a.img', sha256: 'aa'}]);
  const two = manifestHash([{name: 'a.img', sha256: 'aa'}, {name: 'b.img', sha256: 'bb'}]);
  assert.equal(one, two);
});

/* ---------------------------------------------------------------------
 * What the real Lenovo package turned out to be.
 *
 * LMSA ships the TB310FU firmware with the scatter ENCRYPTED and its
 * extension truncated to .t / .x, while every partition image beside it is
 * ordinary plaintext. None of this was guessed - it was read off the
 * genuine 6.6 GB download for serial HA1Y7RCV.
 * ------------------------------------------------------------------- */

const {scatterIsReadable, isScatter} = require('../desktop/firmware.cjs');

test('LMSA truncated scatter extensions are still recognised as scatters', () => {
  assert.equal(isScatter('MT6768_Android_scatter.t'), true);
  assert.equal(isScatter('MT6768_Android_scatter.x'), true);
  assert.equal(isScatter('MT6769_Android_scatter.xml'), true);
  assert.equal(isScatter('super.img'), false);
});

test('an encrypted scatter is told apart from a readable one', () => {
  assert.equal(scatterIsReadable(SCATTER), true);
  /* The real file's opening bytes. */
  assert.equal(scatterIsReadable(
    Buffer.from([0xe9, 0x7c, 0xfb, 0x81, 0x01, 0x78, 0x82, 0xd5,
      0x8a, 0xd4, 0x59, 0x9e]).toString('latin1')), false);
  assert.equal(scatterIsReadable(''), false);
});

test('an encrypted scatter still leaves a restore path, and says which', () => {
  const files = Object.assign({}, FULL);
  delete files['MT6769_Android_scatter.xml'];
  files['MT6768_Android_scatter.t'] = Buffer.from(
    [0xe9, 0x7c, 0xfb, 0x81, 0x01, 0x78, 0x82, 0xd5, 0x8a, 0xd4, 0x59, 0x9e]);
  const dir = makeDir(files);

  const report = inspect(dir);
  assert.equal(report.scatter.readable, false);
  assert.match(report.notes.join(' '), /encrypted, as Lenovo ships it/);
  /* The images are still found, verified and hashed without the map. */
  assert.ok(report.images.length >= 4);
  assert.ok(report.images.every((i) => i.magicOk));
  assert.equal(report.manifest.length, 64);

  const verdict = restorability(report, {device: 'TB310FU'});
  assert.equal(verdict.ok, true, 'plain verified images are still a way back');
  assert.match(verdict.warnings.join(' '), /SP Flash Tool cannot use/);
  assert.match(verdict.warnings.join(' '), /LMSA/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a file that is not the image it claims to be blocks everything', () => {
  const dir = makeDir(Object.assign({}, FULL, {'boot.img': 'this is not a boot image'}));
  const report = inspect(dir);
  const boot = report.images.find((i) => i.name === 'boot.img');
  assert.equal(boot.magicOk, false);
  const verdict = restorability(report);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /not the images they claim to be.*boot\.img/s);
  assert.match(verdict.blockers.join(' '), /download is corrupt/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('an encrypted-scatter package missing super is still refused', () => {
  const files = Object.assign({}, FULL);
  delete files['MT6769_Android_scatter.xml'];
  delete files['super.img'];
  files['MT6768_Android_scatter.t'] = Buffer.from([0xe9, 0x7c, 0xfb, 0x81, 0x8a, 0xd4, 0x59, 0x9e]);
  const verdict = restorability(inspect(makeDir(files)));
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /Critical images are absent.*super/s);
});

test('every MTK preloader wrapping counts, raw and EMMC_BOOT alike', () => {
  const {magicFor, checkMagic} = require('../desktop/firmware.cjs');
  const rule = magicFor('preloader.img');
  assert.equal(rule.name, 'MTK preloader');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-pre-'));
  const raw = path.join(dir, 'preloader_raw.img');
  fs.writeFileSync(raw, Buffer.concat([Buffer.from([0x4d, 0x4d, 0x4d, 0x01]), Buffer.from('FILE_INFO')]));
  assert.equal(checkMagic(raw, rule), true, 'raw MMM preloader');

  /* EMMC_BOOT header, then the real MMM payload at 0x800 - exactly how
   * Lenovo ships preloader.img / _emmc / _ufs for the TB310FU. */
  const wrapped = path.join(dir, 'preloader_emmc.img');
  const body = Buffer.alloc(0x800 + 16, 0xff);
  Buffer.from('EMMC_BOOT\0').copy(body, 0);
  Buffer.from([0x4d, 0x4d, 0x4d, 0x01]).copy(body, 0x800);
  fs.writeFileSync(wrapped, body);
  assert.equal(checkMagic(wrapped, rule), true, 'EMMC_BOOT-wrapped preloader');

  const junk = path.join(dir, 'preloader_bad.img');
  fs.writeFileSync(junk, Buffer.alloc(0x900, 0x00));
  assert.equal(checkMagic(junk, rule), false, 'an all-zero file is still refused');
  fs.rmSync(dir, {recursive: true, force: true});
});
