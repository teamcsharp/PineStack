/* The GSI - is this image the right shape for this tablet?
 *
 * A generic system image is flashed to the whole system partition of a
 * Treble device. Get the variant wrong and the tablet either refuses to
 * boot or boots without audio, which for a Pine Box terminal is the same
 * as not booting at all.
 *
 * Two jobs here, and they are separate on purpose:
 *
 *   requirement(props)  - reads what the TABLET needs, off its own
 *                         properties. No guessing from the model name.
 *   inspect(file)       - reads what an IMAGE actually is, off its bytes
 *                         and its filename.
 *   match(req, image)   - says whether the two agree, and refuses loudly
 *                         when they do not.
 *
 * The filename is treated as a claim, not as evidence. The bytes decide
 * whether it is a filesystem image at all.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

/* Andy Yan / phhusson naming: {arm|a64|arm64}_{a|b}{v|g}{N|S}, with an
 * optional -vndklite and -signed suffix. Newer trees also publish
 * gsi_arm64_vN, which drops the a/b letter entirely. */
const NAME_SHAPE = /(?:^|[-_])(arm64|a64|arm)_(?:(a|b))?(v|g)(N|S)(?:-(vndklite))?(?:-(signed))?/i;

function describeName(filename) {
  const base = path.basename(String(filename || ''));
  const match = NAME_SHAPE.exec(base);
  if (!match) return {parsed: false, file: base};
  return {
    parsed: true,
    file: base,
    arch: match[1].toLowerCase(),
    /* Absent means the build does not distinguish - treat as unknown
     * rather than as A-only, because guessing here costs a boot loop. */
    partitioning: match[2] ? match[2].toLowerCase() : '',
    gapps: match[3].toLowerCase() === 'g',
    superuser: match[4].toUpperCase() === 'S',
    vndklite: !!match[5],
    signed: !!match[6],
    compressed: /\.(gz|xz|zst)$/i.test(base)
  };
}

/* What THIS tablet requires, read from its own getprop output. */
function requirement(props = {}) {
  const abis = String(props['ro.product.cpu.abilist64'] || '');
  const lite = String(props['ro.vndk.lite'] || '').toLowerCase() === 'true';
  return {
    treble: String(props['ro.treble.enabled'] || '').toLowerCase() === 'true',
    arch: abis.includes('arm64') ? 'arm64' : abis ? 'unknown' : 'arm',
    ab: String(props['ro.build.ab_update'] || '').toLowerCase() === 'true',
    virtualAb: String(props['ro.virtual_ab.enabled'] || '').toLowerCase() === 'true',
    dynamic: String(props['ro.boot.dynamic_partitions'] || '').toLowerCase() === 'true',
    vndk: String(props['ro.vndk.version'] || ''),
    vndklite: lite,
    platform: String(props['ro.board.platform'] || ''),
    unlocked: String(props['ro.boot.flash.locked'] || '') === '0'
      || String(props['ro.boot.verifiedbootstate'] || '').toLowerCase() === 'orange'
  };
}

/* ext4 keeps its superblock magic at 0x438; EROFS keeps its at 0x400.
 * A GSI is one or the other - anything else is not a system image. */
const FS_MAGIC = [
  {name: 'ext4', at: 0x438, bytes: [0x53, 0xef]},
  {name: 'erofs', at: 0x400, bytes: [0xe2, 0xe1, 0xf5, 0xe0]}
];

function filesystemOf(file) {
  let fd;
  try {
    fd = fs.openSync(file, 'r');
    for (const candidate of FS_MAGIC) {
      const head = Buffer.alloc(candidate.bytes.length);
      const read = fs.readSync(fd, head, 0, head.length, candidate.at);
      if (read < head.length) continue;
      if (candidate.bytes.every((byte, i) => head[i] === byte)) return candidate.name;
    }
    return '';
  } catch (err) {
    return '';
  } finally {
    if (fd !== undefined) { try { fs.closeSync(fd); } catch (err) { /* closed */ } }
  }
}

function gzipped(file) {
  let fd;
  try {
    fd = fs.openSync(file, 'r');
    const head = Buffer.alloc(2);
    if (fs.readSync(fd, head, 0, 2, 0) < 2) return false;
    return head[0] === 0x1f && head[1] === 0x8b;
  } catch (err) {
    return false;
  } finally {
    if (fd !== undefined) { try { fs.closeSync(fd); } catch (err) { /* closed */ } }
  }
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

function inspect(file, {hash = true} = {}) {
  const out = {file, exists: false, bytes: 0, name: describeName(file),
    compressed: false, filesystem: '', sha256: '', notes: []};
  if (!file || !fs.existsSync(file)) {
    out.notes.push('That file is not there.');
    return out;
  }
  out.exists = true;
  try { out.bytes = fs.statSync(file).size; } catch (err) { out.bytes = 0; }

  if (out.bytes < 64) {
    /* A few bytes usually means a download that was refused - a bot-block
     * page, not an image. Say that, rather than "corrupt". */
    out.notes.push('This file is ' + out.bytes + ' bytes. That is a failed '
      + 'download, most likely a rejection page rather than an image.');
    return out;
  }

  out.compressed = gzipped(file) || /\.(gz|xz|zst)$/i.test(file);
  if (out.compressed) {
    out.notes.push('Still compressed. Decompress it before flashing - '
      + 'fastboot needs the raw .img.');
    if (hash) out.sha256 = sha256(file);
    return out;
  }

  out.filesystem = filesystemOf(file);
  if (!out.filesystem) {
    out.notes.push('This is not an ext4 or EROFS filesystem image, so it is '
      + 'not a GSI whatever it is called.');
  }
  if (hash) out.sha256 = sha256(file);
  return out;
}

/* Does this image suit this tablet? Blockers stop the flash. */
function match(req, image) {
  const blockers = [];
  const warnings = [];

  if (!req || !req.treble) {
    blockers.push('This tablet does not report Treble support, so no GSI '
      + 'will run on it.');
  }
  if (req && !req.unlocked) {
    blockers.push('The bootloader is still locked - unlock before flashing.');
  }
  if (!image || !image.exists) {
    blockers.push('No GSI image found.');
    return {ok: false, blockers, warnings};
  }
  if (image.compressed) {
    blockers.push('The image is still compressed. Decompress it first.');
  } else if (!image.filesystem) {
    blockers.push('That file is not a filesystem image - it cannot be a GSI.');
  }

  const claim = image.name;
  if (!claim.parsed) {
    warnings.push('The filename does not follow the usual GSI naming, so its '
      + 'variant cannot be checked. Be sure it is arm64, A/B and vanilla.');
  } else {
    if (req && req.arch === 'arm64' && claim.arch === 'arm') {
      blockers.push('This is a 32-bit image and the tablet is arm64.');
    }
    if (req && req.ab && claim.partitioning === 'a') {
      blockers.push('This is an A-only image and the tablet is an A/B device.');
    }
    if (req && req.ab && !claim.partitioning) {
      warnings.push('The filename does not state A/B. This tablet is A/B - '
        + 'make sure the build is too.');
    }
    if (claim.gapps) {
      warnings.push('This build carries GApps. The plan is a Google-free '
        + 'terminal, so a vanilla build is wanted instead.');
    }
    if (req && claim.vndklite && !req.vndklite) {
      warnings.push('This is a vndklite build but the tablet is not vndklite. '
        + 'The full build is usually the right one.');
    }
    if (req && !claim.vndklite && req.vndklite) {
      blockers.push('This tablet needs a vndklite build and this is not one.');
    }
  }

  if (req && req.virtualAb) {
    warnings.push('Virtual A/B with dynamic partitions: the system image goes '
      + 'through fastbootd, not the bootloader.');
  }
  return {ok: !blockers.length, blockers, warnings};
}

/* The flash, as an ordered list of steps rather than a run of awaits.
 *
 * Written as data so it can be read before it is run, shown to the operator
 * with the reason for each step, and tested without a tablet. Every step
 * says WHERE it must happen, because getting that wrong is the single most
 * common way a GSI flash fails in a way that looks like a bad image:
 *
 *   - `vbmeta` is a real partition, so it is written from the BOOTLOADER.
 *   - `system` is a logical partition inside `super`, so it can only be
 *     written from FASTBOOTD. The bootloader cannot see it at all.
 */
function plan(req, image, {stockVbmeta, deleteLogical, wipe = true} = {}) {
  const steps = [];

  if (stockVbmeta) {
    /* A GSI is not signed by the vendor. Left on, Android Verified Boot
     * refuses to hand off to it and the tablet loops. The stock vbmeta is
     * re-flashed with verification disabled rather than an empty one, so
     * the partition still holds something the bootloader understands. */
    steps.push({
      stage: 'disable verified boot',
      where: 'bootloader',
      args: ['--disable-verity', '--disable-verification', 'flash', 'vbmeta', stockVbmeta],
      why: 'A GSI carries no vendor signature, so AVB has to be turned off or '
        + 'the tablet will refuse to boot it.',
      destructive: true
    });
  }

  steps.push({
    stage: 'enter fastbootd',
    where: 'bootloader',
    args: ['reboot', 'fastboot'],
    settle: 15000,
    why: 'system lives inside the dynamic super partition, and only fastbootd '
      + 'can write that.'
  });

  for (const name of deleteLogical || []) {
    steps.push({
      stage: 'make room by removing ' + name,
      where: 'fastbootd',
      args: ['delete-logical-partition', name],
      optional: true,
      why: 'super may not have room for a system image larger than the one it '
        + 'replaces. Failing here is fine if the room was already there.'
    });
  }

  steps.push({
    stage: 'flash system',
    where: 'fastbootd',
    args: ['flash', 'system', image],
    why: 'The GSI replaces the vendor system image inside super. This is the '
      + 'step that makes it a LineageOS tablet, and the point of no return '
      + 'for the shipped software.',
    destructive: true
  });

  if (wipe) {
    /* MEASURED ON THE REAL TB310FU, 2026-09-10.
     *
     * `fastboot -w` was first placed here in fastbootd, and answered
     * "wipe task partition not found: userdata / cache / metadata" in four
     * milliseconds - reporting a clean wipe having wiped nothing. The
     * tablet then booted LineageOS with Lenovo's old /data intact, Play
     * Services and all.
     *
     * The reason: on a virtual A/B device fastbootd exposes the LOGICAL
     * partitions inside super, and `userdata` is not one of them - it is a
     * physical partition the BOOTLOADER owns. So the wipe has to happen
     * back in the bootloader, which means returning there after the system
     * image is written.
     *
     * It stays last on purpose: a wipe that runs before a flash that then
     * fails leaves an empty tablet for no reason. */
    steps.push({
      stage: 'return to the bootloader',
      where: 'fastbootd',
      args: ['reboot', 'bootloader'],
      settle: 15000,
      why: 'userdata is a physical partition, so fastbootd cannot see it to '
        + 'wipe it. Only the bootloader can.'
    });
    steps.push({
      stage: 'wipe data',
      where: 'bootloader',
      args: ['-w'],
      why: 'the existing userdata is encrypted with keys the new system does '
        + 'not have, and carries the old vendor apps with it.',
      destructive: true
    });
  }

  steps.push({stage: 'reboot', args: ['reboot'],
    why: 'first boot after a GSI flash takes several minutes.'});
  return steps;
}

/* The plan, plus the refusal to produce one for an image that does not fit
 * this tablet. Callers should check `ok` rather than reading `steps` blind. */
function planFor(req, image, options = {}) {
  const verdict = match(req, image);
  return {
    ok: verdict.ok,
    verdict,
    steps: verdict.ok ? plan(req, image.file, options) : []
  };
}

module.exports = {
  inspect, match, requirement, describeName, filesystemOf, gzipped, sha256,
  plan, planFor, NAME_SHAPE, FS_MAGIC
};
