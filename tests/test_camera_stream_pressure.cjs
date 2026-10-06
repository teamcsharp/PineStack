const {test} = require('node:test');
const assert = require('node:assert/strict');
const {CameraGlass} = require('../desktop/tablet-mirror.cjs');

test('camera frames survive partial reads and embedded JPEG thumbnails', () => {
  const camera = new CameraGlass({});
  const jpeg = Buffer.from([255,216,1,255,216,2,255,217,3,255,217]);
  const size = Buffer.alloc(4); size.writeUInt32BE(jpeg.length);
  const packet = Buffer.concat([size,jpeg]);
  camera.chew(packet.subarray(0,7));
  assert.equal(camera.frames,0);
  camera.chew(packet.subarray(7));
  assert.equal(camera.frames,1);
  assert.deepEqual(camera.latest,jpeg);
});

test('a slow camera viewer receives no additional stale frames', () => {
  const camera = new CameraGlass({}); let writes=0;
  const viewer={writableNeedDrain:true,write(){writes++;}};
  camera.watchers.add(viewer);
  for(let i=0;i<100;i++)camera.push(viewer,Buffer.alloc(1000));
  assert.equal(writes,0);
  viewer.writableNeedDrain=false;
  camera.push(viewer,Buffer.from('newest frame'));
  assert.equal(writes,5);
});

test('a whole frame finishes even if backpressure begins in its header', () => {
  const camera = new CameraGlass({}); const writes=[];
  const viewer={writableNeedDrain:false,write(part){writes.push(part);this.writableNeedDrain=true;return false;}};
  const jpeg=Buffer.from('frame'); camera.push(viewer,jpeg);
  assert.equal(writes.length,5); assert.equal(writes[3],jpeg);
  camera.push(viewer,Buffer.from('obsolete next frame'));
  assert.equal(writes.length,5);
});
