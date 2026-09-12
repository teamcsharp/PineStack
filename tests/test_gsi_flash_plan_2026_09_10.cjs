/* The flash plan, and walking it.
 *
 * A GSI flash fails most often not because the image is wrong but because a
 * step was run in the wrong MODE. `vbmeta` is a real partition and belongs
 * to the bootloader; `system` is a logical partition inside `super` and only
 * fastbootd can see it. Running either in the other place produces an error
 * that reads like a bad image, and sends the operator hunting the wrong
 * thing.
 *
 * So the plan is data, every step declares where it must run, and runPlan
 * refuses rather than letting fastboot fail confusingly.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {plan, planFor, requirement} = require('../desktop/gsi.cjs');
const {Terminal} = require('../desktop/terminal.cjs');

const PROPS = {
  'ro.treble.enabled': 'true',
  'ro.build.ab_update': 'true',
  'ro.product.cpu.abilist64': 'arm64-v8a',
  'ro.virtual_ab.enabled': 'true',
  'ro.boot.dynamic_partitions': 'true',
  'ro.board.platform': 'mt6768',
  'ro.boot.flash.locked': '0'
};
const REQ = requirement(PROPS);
const GSI = 'C:/_tools/pinebox-gsi/lineage-21.0-20260614-UNOFFICIAL-arm64_bvN.img';
const VBMETA = 'C:/firmware/image/vbmeta.img';

const bootloaderVars = (userspace) => [
  '(bootloader) unlocked: yes',
  '(bootloader) secure: no',
  '(bootloader) serialno: HA1Y7RCV',
  '(bootloader) slot-count: 2',
  '(bootloader) current-slot: a',
  '(bootloader) battery-soc-ok: yes',
  '(bootloader) is-userspace: ' + (userspace ? 'yes' : 'no')
].join('\n');

/* `mode` is a box so a step can change it, the way a real reboot does. */
function fixture({mode = {now: 'bootloader'}, fails = []} = {}) {
  const calls = [];
  const runFastboot = async (args) => {
    const line = args.join(' ');
    calls.push(line);
    if (args[0] === 'getvar') return bootloaderVars(mode.now === 'fastbootd');
    if (line === 'reboot fastboot') { mode.now = 'fastbootd'; return 'Rebooting into fastboot OKAY'; }
    if (line === 'reboot bootloader') { mode.now = 'bootloader'; return 'Rebooting into bootloader OKAY'; }
    if (fails.some((f) => line.includes(f))) return 'FAILED (remote: not enough space)';
    return 'OKAY [  1.0s]';
  };
  return {
    terminal: new Terminal({run: async () => '', runFastboot, now: () => 1789000000000}),
    calls, mode
  };
}

test('the plan puts every step in the mode that can actually do it', () => {
  const steps = plan(REQ, GSI, {stockVbmeta: VBMETA, deleteLogical: ['product_a']});
  const where = Object.fromEntries(steps.map((s) => [s.stage, s.where || '']));

  assert.equal(where['disable verified boot'], 'bootloader',
    'vbmeta is a real partition - the bootloader owns it');
  assert.equal(where['enter fastbootd'], 'bootloader');
  assert.equal(where['flash system'], 'fastbootd',
    'system is logical, inside super - only fastbootd can write it');
  /* userdata is PHYSICAL. fastbootd cannot see it; the bootloader can.
   * Getting this wrong once produced a wipe that reported success and
   * wiped nothing, leaving Play Services alive on a Google-free build. */
  assert.equal(where['wipe data'], 'bootloader');
  assert.equal(where['return to the bootloader'], 'fastbootd');

  /* Order matters as much as mode: AVB off before the image, fastbootd
   * before system, reboot last. */
  const order = steps.map((s) => s.stage);
  assert.ok(order.indexOf('disable verified boot') < order.indexOf('enter fastbootd'));
  assert.ok(order.indexOf('enter fastbootd') < order.indexOf('flash system'));
  assert.equal(order[order.length - 1], 'reboot');
});

test('every step says why it exists, and which ones destroy something', () => {
  const steps = plan(REQ, GSI, {stockVbmeta: VBMETA});
  for (const step of steps) {
    assert.ok(step.why && step.why.length > 20, 'no reason given for ' + step.stage);
  }
  const destructive = steps.filter((s) => s.destructive).map((s) => s.stage);
  assert.deepEqual(destructive, ['disable verified boot', 'flash system', 'wipe data']);
  /* The wipe is last: a wipe before a flash that then fails empties the
   * tablet for nothing. */
  const order = steps.map((s) => s.stage);
  assert.ok(order.indexOf('flash system') < order.indexOf('wipe data'));
});

test('the vbmeta step disables verification, or the tablet will not boot a GSI', () => {
  const steps = plan(REQ, GSI, {stockVbmeta: VBMETA});
  const vb = steps.find((s) => s.stage === 'disable verified boot');
  assert.ok(vb.args.includes('--disable-verity'));
  assert.ok(vb.args.includes('--disable-verification'));
  assert.deepEqual(vb.args.slice(-3), ['flash', 'vbmeta', VBMETA]);

  /* Without a stock vbmeta to re-flash there is simply no such step. */
  assert.equal(plan(REQ, GSI, {}).some((s) => s.stage === 'disable verified boot'), false);
});

test('making room is optional - failing it is not a failed flash', () => {
  const steps = plan(REQ, GSI, {deleteLogical: ['product_a', 'system_ext_a']});
  const room = steps.filter((s) => s.stage.startsWith('make room'));
  assert.equal(room.length, 2);
  for (const step of room) assert.equal(step.optional, true);
});

test('the wipe can be left out, but it is on by default', () => {
  assert.ok(plan(REQ, GSI, {}).some((s) => s.stage === 'wipe data'));
  assert.equal(plan(REQ, GSI, {wipe: false}).some((s) => s.stage === 'wipe data'), false);
});

test('no plan is produced for an image that does not fit the tablet', () => {
  const bad = planFor(REQ, {exists: true, compressed: false, filesystem: 'ext4',
    file: 'lineage-arm64_avN.img', name: {parsed: true, arch: 'arm64',
      partitioning: 'a', gapps: false, superuser: false, vndklite: false}});
  assert.equal(bad.ok, false);
  assert.deepEqual(bad.steps, [], 'a refused image must not yield runnable steps');
  assert.match(bad.verdict.blockers.join(' '), /A-only/);

  const good = planFor(REQ, {exists: true, compressed: false, filesystem: 'ext4',
    file: GSI, name: {parsed: true, arch: 'arm64', partitioning: 'b',
      gapps: false, superuser: false, vndklite: false}}, {stockVbmeta: VBMETA});
  assert.equal(good.ok, true);
  assert.ok(good.steps.length >= 5);
});

test('a dry run reports the exact commands and touches nothing', async () => {
  const {terminal, calls} = fixture();
  const steps = plan(REQ, GSI, {stockVbmeta: VBMETA, deleteLogical: ['product_a']});
  const result = await terminal.runPlan(steps, {dryRun: true});
  assert.equal(result.ok, true);
  assert.equal(calls.length, 0, 'a dry run must not run fastboot at all');
  assert.match(result.steps[0].output, /--disable-verity .*flash vbmeta/);
  for (const step of result.steps) assert.equal(step.ran, false);
});

test('a fastbootd step is refused while the device is in the bootloader', async () => {
  const {terminal, calls} = fixture();
  const result = await terminal.runPlan([
    {stage: 'flash system', where: 'fastbootd', args: ['flash', 'system', GSI]}
  ]);
  assert.equal(result.ok, false);
  assert.match(result.steps[0].output, /needs fastbootd/);
  assert.equal(calls.filter((c) => c.startsWith('flash')).length, 0,
    'it must not attempt the flash in the wrong mode');
});

test('a bootloader step is refused while the device is in fastbootd', async () => {
  const {terminal} = fixture({mode: {now: 'fastbootd'}});
  const result = await terminal.runPlan([
    {stage: 'disable verified boot', where: 'bootloader',
      args: ['--disable-verity', 'flash', 'vbmeta', VBMETA]}
  ]);
  assert.equal(result.ok, false);
  assert.match(result.steps[0].output, /needs the bootloader/);
});

test('the whole plan runs in order, crossing into fastbootd on the way', async () => {
  const {terminal, calls} = fixture();
  const steps = plan(REQ, GSI, {stockVbmeta: VBMETA});
  for (const step of steps) step.settle = 0;      /* no real waiting in a test */
  const seen = [];
  const result = await terminal.runPlan(steps, {onStep: (s) => {
    if (!s.starting) seen.push(s.stage);
  }});
  assert.equal(result.ok, true);
  assert.deepEqual(seen, ['disable verified boot', 'enter fastbootd',
    'flash system', 'return to the bootloader', 'wipe data', 'reboot']);
  assert.ok(calls.some((c) => c === 'reboot fastboot'));
  assert.ok(calls.some((c) => c === 'flash system ' + GSI));
});

test('FAILED in the output stops the plan even when fastboot exits zero', async () => {
  const {terminal, calls} = fixture({fails: ['flash system']});
  const steps = plan(REQ, GSI, {stockVbmeta: VBMETA});
  for (const step of steps) step.settle = 0;
  const result = await terminal.runPlan(steps);
  assert.equal(result.ok, false);
  const failed = result.steps[result.steps.length - 1];
  assert.equal(failed.stage, 'flash system');
  assert.equal(failed.ok, false);
  assert.match(failed.output, /FAILED/);
  /* And nothing after it ran - no wipe on a tablet with no system. */
  assert.equal(calls.includes('-w'), false,
    'data must never be wiped after the system flash failed');
});

test('an optional step that fails does not stop the plan', async () => {
  const {terminal} = fixture({fails: ['delete-logical-partition']});
  const steps = plan(REQ, GSI, {deleteLogical: ['product_a']});
  for (const step of steps) step.settle = 0;
  const result = await terminal.runPlan(steps);
  assert.equal(result.ok, true, 'making room is allowed to fail');
  const room = result.steps.find((s) => s.stage.startsWith('make room'));
  assert.equal(room.ok, false);
});

test('a step that succeeds while doing nothing is flagged, not passed silently', async () => {
  /* Verbatim from the real TB310FU flash on 2026-09-10: `fastboot -w` in
   * fastbootd answered this and finished in four milliseconds, having
   * wiped nothing at all - and was reported as a clean wipe. */
  const HOLLOW = 'wipe task partition not found: userdata\n'
    + 'wipe task partition not found: cache\n'
    + 'wipe task partition not found: metadata\n'
    + 'Finished. Total time: 0.004s';
  const runFastboot = async (args) =>
    args[0] === 'getvar' ? '(bootloader) is-userspace: yes' : HOLLOW;
  const terminal = new Terminal({run: async () => '', runFastboot});

  const result = await terminal.runPlan([{stage: 'wipe data', args: ['-w']}]);
  const step = result.steps[0];
  assert.equal(step.ok, true, 'fastboot did not fail, so the step did not fail');
  assert.ok(step.notes && step.notes.length, 'but it must not pass silently');
  assert.match(step.notes[0], /reported success but appears not to have done anything/);
  assert.match(step.notes[0], /partition not found/);
});

test('an ordinary success carries no such note', async () => {
  const runFastboot = async (args) =>
    args[0] === 'getvar' ? '(bootloader) is-userspace: yes'
      : 'Sending sparse system_a 1/10 OKAY [ 6.4s]\nWriting system_a OKAY';
  const terminal = new Terminal({run: async () => '', runFastboot});
  const result = await terminal.runPlan([{stage: 'flash system', args: ['flash', 'system', 'x.img']}]);
  assert.equal(result.steps[0].ok, true);
  assert.equal(result.steps[0].notes, undefined);
});

test('the sparse-format chatter of a real flash is not mistaken for a fault', async () => {
  /* fastboot prints this while sparsing a raw image; the flash succeeded. */
  const REAL = "Resizing 'system_a' OKAY [ 0.005s]\n"
    + 'Invalid sparse file format at header magic\n'
    + "Sending sparse 'system_a' 1/10 (262116 KB) OKAY [ 6.493s]\n"
    + "Writing 'system_a' OKAY [ 1.722s]";
  const runFastboot = async (args) =>
    args[0] === 'getvar' ? '(bootloader) is-userspace: yes' : REAL;
  const terminal = new Terminal({run: async () => '', runFastboot});
  const result = await terminal.runPlan([{stage: 'flash system', args: ['flash', 'system', 'x.img']}]);
  assert.equal(result.steps[0].ok, true, 'this is what a WORKING flash looks like');
  assert.equal(result.steps[0].notes, undefined);
});
