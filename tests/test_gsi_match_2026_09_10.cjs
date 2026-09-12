/* Matching a GSI to the tablet.
 *
 * PROPS below is the real getprop output from HA1Y7RCV after unlocking on
 * 2026-09-10: Treble on, arm64, A/B, virtual A/B with dynamic partitions,
 * full VNDK (not lite), MT6768, verifiedbootstate orange.
 *
 * The point of these tests is that the FILENAME IS A CLAIM. A file called
 * arm64_bvN proves nothing; the bytes decide whether it is a filesystem
 * image, and the tablet's own properties decide whether the variant fits.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {inspect, match, requirement, describeName, filesystemOf} = require('../desktop/gsi.cjs');

const PROPS = {
  'ro.treble.enabled': 'true',
  'ro.build.ab_update': 'true',
  'ro.product.cpu.abilist64': 'arm64-v8a',
  'ro.vndk.version': '31',
  'ro.vndk.lite': '',
  'ro.virtual_ab.enabled': 'true',
  'ro.boot.dynamic_partitions': 'true',
  'ro.board.platform': 'mt6768',
  'ro.boot.verifiedbootstate': 'orange',
  'ro.boot.flash.locked': '0'
};

const NEWEST = 'lineage-21.0-20260614-UNOFFICIAL-arm64_bvN.img';

/* ext4 superblock magic lives at 0x438. */
function makeExt4(name, dir) {
  const file = path.join(dir, name);
  const body = Buffer.alloc(0x500, 0);
  body[0x438] = 0x53; body[0x439] = 0xef;
  fs.writeFileSync(file, body);
  return file;
}

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'pine-gsi-')); }

test('the tablet says what it needs, and it is read not guessed', () => {
  const req = requirement(PROPS);
  assert.equal(req.treble, true);
  assert.equal(req.arch, 'arm64');
  assert.equal(req.ab, true);
  assert.equal(req.virtualAb, true);
  assert.equal(req.dynamic, true);
  assert.equal(req.vndklite, false);
  assert.equal(req.platform, 'mt6768');
  assert.equal(req.unlocked, true);

  /* Still locked, by either signal. */
  assert.equal(requirement(Object.assign({}, PROPS,
    {'ro.boot.flash.locked': '1', 'ro.boot.verifiedbootstate': 'green'})).unlocked, false);
});

test('GSI filenames are decoded, including the newer gsi_ prefix', () => {
  const bvN = describeName(NEWEST);
  assert.equal(bvN.parsed, true);
  assert.equal(bvN.arch, 'arm64');
  assert.equal(bvN.partitioning, 'b');
  assert.equal(bvN.gapps, false);
  assert.equal(bvN.superuser, false);
  assert.equal(bvN.vndklite, false);

  const bvS = describeName('lineage-21.0-20250621-UNOFFICIAL-arm64_bvS.img.gz');
  assert.equal(bvS.superuser, true);
  assert.equal(bvS.compressed, true);

  const lite = describeName('lineage-21.0-20260614-UNOFFICIAL-arm64_bvN-vndklite.img.gz');
  assert.equal(lite.vndklite, true);

  const gapps = describeName('lineage-21.0-20260614-UNOFFICIAL-arm64_bgN-signed.img.gz');
  assert.equal(gapps.gapps, true);
  assert.equal(gapps.signed, true);

  /* The light tree drops the a/b letter entirely - unknown, not A-only. */
  const light = describeName('lineage-21.0-20260613-UNOFFICIAL-gsi_arm64_vN.img.gz');
  assert.equal(light.parsed, true);
  assert.equal(light.arch, 'arm64');
  assert.equal(light.partitioning, '');

  assert.equal(describeName('some-random-file.img').parsed, false);
});

test('the right image for this tablet is accepted', () => {
  const dir = tmp();
  const image = inspect(makeExt4(NEWEST, dir));
  assert.equal(image.exists, true);
  assert.equal(image.compressed, false);
  assert.equal(image.filesystem, 'ext4');
  assert.equal(image.sha256.length, 64);

  const verdict = match(requirement(PROPS), image);
  assert.equal(verdict.ok, true);
  assert.deepEqual(verdict.blockers, []);
  /* Virtual A/B must always be called out - it changes where it is flashed. */
  assert.match(verdict.warnings.join(' '), /fastbootd, not the bootloader/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a still-compressed image is refused before it wastes a flash', () => {
  const dir = tmp();
  const file = path.join(dir, NEWEST + '.gz');
  fs.writeFileSync(file, Buffer.concat([Buffer.from([0x1f, 0x8b]), Buffer.alloc(200)]));
  const image = inspect(file);
  assert.equal(image.compressed, true);
  assert.match(image.notes.join(' '), /Decompress it before flashing/);
  const verdict = match(requirement(PROPS), image);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /still compressed/i);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a rejected download is named as such, not called corrupt', () => {
  const dir = tmp();
  const file = path.join(dir, NEWEST);
  fs.writeFileSync(file, '\n');            /* the 2-byte SourceForge 403 body */
  const image = inspect(file);
  assert.equal(image.bytes, 1);
  assert.match(image.notes.join(' '), /failed download/);
  assert.match(image.notes.join(' '), /rejection page/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a file that is not a filesystem image cannot be a GSI', () => {
  const dir = tmp();
  const file = path.join(dir, NEWEST);
  fs.writeFileSync(file, Buffer.alloc(0x500, 0x41));   /* no magic anywhere */
  const image = inspect(file);
  assert.equal(image.filesystem, '');
  const verdict = match(requirement(PROPS), image);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /not a filesystem image/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('EROFS is a filesystem image too', () => {
  const dir = tmp();
  const file = path.join(dir, NEWEST);
  const body = Buffer.alloc(0x500, 0);
  Buffer.from([0xe2, 0xe1, 0xf5, 0xe0]).copy(body, 0x400);
  fs.writeFileSync(file, body);
  assert.equal(filesystemOf(file), 'erofs');
  assert.equal(match(requirement(PROPS), inspect(file)).ok, true);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('an A-only image on an A/B tablet is refused outright', () => {
  const dir = tmp();
  const image = inspect(makeExt4('lineage-21.0-UNOFFICIAL-arm64_avN.img', dir));
  const verdict = match(requirement(PROPS), image);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /A-only image and the tablet is an A\/B/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a 32-bit image on an arm64 tablet is refused outright', () => {
  const dir = tmp();
  const image = inspect(makeExt4('lineage-21.0-UNOFFICIAL-arm_bvN.img', dir));
  const verdict = match(requirement(PROPS), image);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /32-bit image/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a GApps build warns, because the whole point is a Google-free terminal', () => {
  const dir = tmp();
  const image = inspect(makeExt4('lineage-21.0-UNOFFICIAL-arm64_bgN-signed.img', dir));
  const verdict = match(requirement(PROPS), image);
  assert.equal(verdict.ok, true, 'it would still boot');
  assert.match(verdict.warnings.join(' '), /carries GApps/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('vndklite is checked both ways round', () => {
  const dir = tmp();
  const lite = inspect(makeExt4('lineage-21.0-UNOFFICIAL-arm64_bvN-vndklite.img', dir));
  /* This tablet is NOT vndklite, so a lite build is a warning. */
  assert.match(match(requirement(PROPS), lite).warnings.join(' '), /vndklite build but the tablet is not/);

  /* A tablet that IS vndklite must not be given the full build. */
  const liteTablet = requirement(Object.assign({}, PROPS, {'ro.vndk.lite': 'true'}));
  const full = inspect(makeExt4('lineage-21.0-UNOFFICIAL-arm64_bvN.img', dir));
  const verdict = match(liteTablet, full);
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /needs a vndklite build/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a locked bootloader blocks flashing regardless of the image', () => {
  const dir = tmp();
  const locked = requirement(Object.assign({}, PROPS,
    {'ro.boot.flash.locked': '1', 'ro.boot.verifiedbootstate': 'green'}));
  const verdict = match(locked, inspect(makeExt4(NEWEST, dir)));
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers.join(' '), /still locked/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a non-Treble tablet is refused before anything else happens', () => {
  const dir = tmp();
  const noTreble = requirement(Object.assign({}, PROPS, {'ro.treble.enabled': 'false'}));
  const verdict = match(noTreble, inspect(makeExt4(NEWEST, dir)));
  assert.equal(verdict.ok, false);
  assert.match(verdict.blockers[0], /does not report Treble/);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('a missing image is reported plainly', () => {
  const image = inspect(path.join(os.tmpdir(), 'pine-gsi-nope-xyz.img'));
  assert.equal(image.exists, false);
  assert.match(image.notes.join(' '), /not there/);
  assert.equal(match(requirement(PROPS), image).ok, false);
});
