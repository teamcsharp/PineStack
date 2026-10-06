const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
const start = source.indexOf("ipcMain.handle('camera:pip'");
const end = source.indexOf('\n});', start) + 4;
let handler, pending, delayStart = false, closed = 0, started = [];
const webContents = {};
const context = {
  win: { webContents }, camera: null, cameraWindow: null, pipCameraActive: false, pipCameraGeneration: 0, pipCameraQueue: Promise.resolve(),
  ipcMain: { handle: (_name, fn) => (handler = fn) },
  startTabletCamera: async facing => {
    started.push(facing); if (delayStart) await new Promise(resolve => { pending = resolve; });
    context.camera = { close: async () => { closed++; } };
    return { ok: true, facing, stream: '/camera.mjpg' };
  }
};
vm.runInNewContext(source.slice(start, end), context);
const event = { sender: webContents };
(async () => {
  await assert.rejects(handler({ sender: {} }, { facing: 'front' }), /Pine desktop/);
  const front = await handler(event, { facing: 'front' }); assert.equal(front.facing, 'front');
  const rear = await handler(event, { facing: 'rear' }); assert.equal(rear.facing, 'rear');
  await handler(event, { off: true }); assert.equal(context.camera, null); assert.equal(closed, 1);
  delayStart = true;
  const opening = handler(event, { facing: 'front' }); await new Promise(resolve => setImmediate(resolve));
  const stopping = handler(event, { off: true }); pending();
  assert.equal((await opening).ok, false); await stopping;
  assert.equal(context.camera, null); assert.equal(closed, 2, 'late camera start cannot leak after PiP is turned off');
  delayStart = false;
  context.cameraWindow = { isDestroyed: () => false };
  await handler(event, { facing: 'rear' }); await handler(event, { off: true });
  assert.equal(closed, 2, 'standalone camera window keeps its shared stream when PiP stops');
  assert.ok(started.includes('front') && started.includes('rear'));
  console.log('PiP cameras: front/rear selection, caller guards, stop during startup and shared window lifecycle passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
