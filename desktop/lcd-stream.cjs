// One persistent, identity-checked binary frame connection, with one draw ACK
// outstanding. No queued stale frames or retry of an ambiguously drawn frame.
const net = require('node:net');

class LcdStream {
  constructor({host, identity, port = 3233, connect = (options) => net.createConnection(options), timeout = 3000}) {
    this.host = new URL('http://' + host).hostname; this.identity = identity;
    this.port = port; this.createConnection = connect; this.timeout = timeout;
    this.socket = null; this.ready = null; this.pending = null; this.sequence = 0;
  }
  close() { this.socket?.destroy(); this.socket = null; this.ready = null;
    this.pending?.reject(new Error('LCD frame connection closed.')); this.pending = null; }
  open() {
    if (this.ready) return this.ready;
    const socket = this.socket = this.createConnection({host: this.host, port: this.port});
    socket.setNoDelay(true);
    let buffer = '', identified = false, resolveReady, rejectReady;
    this.ready = new Promise((resolve, reject) => {resolveReady = resolve; rejectReady = reject;});
    const fail = (error) => {
      clearTimeout(timer); rejectReady(error);
      if (this.socket !== socket) return;
      this.pending?.reject(error); this.pending = null;
      if (this.socket === socket) {this.socket = null; this.ready = null;}
      socket.destroy();
    };
    const timer = setTimeout(() => fail(new Error('LCD binary handshake timed out.')), this.timeout);
    socket.on('error', fail);
    socket.on('close', () => fail(new Error('LCD binary connection ended.')));
    socket.on('data', (chunk) => {
      buffer += chunk.toString('ascii');
      if (buffer.length > 4096) return fail(new Error('LCD binary response was oversized.'));
      let nl;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trim(); buffer = buffer.slice(nl + 1);
        if (!identified) {
          const match = line.match(/^PINEFRAME 2 id=([a-f0-9:]+) maxjpg=(\d+)$/i);
          if (!match || match[1].toLowerCase() !== this.identity.toLowerCase()) return fail(new Error('LCD binary identity did not match the verified display.'));
          this.maxJpeg = Math.min(24576, Number(match[2])); identified = true;
          clearTimeout(timer); resolveReady();
        } else if (this.pending) {
          const pending = this.pending;
          const seq = Number(line.match(/\bseq=(\d+)/)?.[1]);
          if (seq !== pending.sequence) return fail(new Error('LCD binary draw acknowledgment sequence did not match.'));
          this.pending = null; pending.resolve(line);
        }
      }
    });
    return this.ready;
  }
  async frame(jpeg) {
    await this.open();
    if (this.pending) throw new Error('LCD binary frame is already in flight.');
    if (!Buffer.isBuffer(jpeg) || jpeg.length > this.maxJpeg) throw new Error('LCD binary JPEG exceeds the advertised budget.');
    const sequence = this.sequence = (this.sequence + 1) >>> 0;
    const header = Buffer.alloc(12); header.write('PJF1'); header.writeUInt32BE(sequence, 4); header.writeUInt32BE(jpeg.length, 8);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {this.close(); reject(new Error('LCD binary draw acknowledgment timed out.'));}, this.timeout);
      this.pending = {sequence, resolve: (value) => {clearTimeout(timer); resolve(value);}, reject: (error) => {clearTimeout(timer); reject(error);}};
      this.socket.write(Buffer.concat([header, jpeg]));
    });
  }
}
module.exports = {LcdStream};
