const assert = require('node:assert/strict');
const {test} = require('node:test');
const net = require('node:net');
const {LcdStream} = require('../desktop/lcd-stream.cjs');
const identity = 'dc:b4:d9:23:11:78';
async function withServer(handler, check, options = {}) {
  const sockets = new Set(), server = net.createServer((socket) => {sockets.add(socket);socket.on('error', () => {});handler(socket);});
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const stream = new LcdStream({host: '10.1.2.3', identity, ...options,
    connect: () => net.createConnection({host: '127.0.0.1', port: server.address().port})});
  try {await check(stream);} finally {stream.close();for (const s of sockets)s.destroy();await new Promise((r) => server.close(r));}
}
test('persistent binary stream frames exact bytes across fragmented acknowledgments', async () => {
  let connections = 0, frames = 0;
  await withServer((socket) => {
    connections++;socket.write('PINEFRAME 2 id=' + identity + ' maxjpg=24576\n');
    let body = Buffer.alloc(0);
    socket.on('data', (chunk) => {
      body = Buffer.concat([body, chunk]);
      if (body.length < 12) return;
      const size = body.readUInt32BE(8);if (body.length < size + 12)return;
      assert.equal(body.subarray(0, 4).toString(), 'PJF1');
      assert.deepEqual(body.subarray(12, 12 + size), Buffer.from([255,216,0,1,255,217]));
      const sequence = body.readUInt32BE(4);frames++;body = body.subarray(12 + size);
      socket.write('QACK img 320x240 seq=');setTimeout(() => socket.write(sequence + ' dec=100 via=stream\n'), 5);
    });
  }, async (stream) => {
    const jpeg = Buffer.from([255,216,0,1,255,217]);
    assert.match(await stream.frame(jpeg), /seq=1/);assert.match(await stream.frame(jpeg), /seq=2/);
    assert.equal(connections, 1);assert.equal(frames, 2);
  });
});
test('binary identity mismatch sends no image bytes', async () => {
  let bytes = 0;
  await withServer((socket) => {socket.on('data', (b) => bytes += b.length);socket.write('PINEFRAME 2 id=00:00:00:00:00:01 maxjpg=24576\n');},
    async (stream) => {await assert.rejects(stream.frame(Buffer.alloc(10)), /identity/);assert.equal(bytes, 0);});
});
test('wrong sequence and missing ACK never credit a draw', async () => {
  await withServer((socket) => {socket.write('PINEFRAME 2 id=' + identity + ' maxjpg=24576\n');socket.on('data', () => socket.write('QACK img 320x240 seq=999\n'));},
    async (stream) => assert.rejects(stream.frame(Buffer.alloc(10)), /sequence/));
  await withServer((socket) => socket.write('PINEFRAME 2 id=' + identity + ' maxjpg=24576\n'),
    async (stream) => assert.rejects(stream.frame(Buffer.alloc(10)), /closed|timed out/), {timeout: 80});
});
