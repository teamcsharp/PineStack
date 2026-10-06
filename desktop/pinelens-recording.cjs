'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const mux = require('./clip-mux.cjs');

class LensRecording {
  constructor({seconds = 600, bytes = 256 * 1024 * 1024} = {}) {
    this.hold = seconds; this.limit = bytes; this.rows = []; this.bytes = 0;
    this.dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-lens-ring-'));
  }
  add(frame, at = Date.now()) {
    if (this.rows.length && at - this.rows.at(-1).at < 250) return;
    const data = Buffer.from(frame.jpeg, 'base64');
    const file = path.join(this.dir, frame.id + '.jpg');
    fs.writeFileSync(file, data);
    this.rows.push({file, at, bytes: data.length}); this.bytes += data.length;
    while (this.rows.length && (at - this.rows[0].at > this.hold * 1000 || this.bytes > this.limit)) {
      const row = this.rows.shift(); this.bytes -= row.bytes; fs.rmSync(row.file, {force: true});
    }
  }
  state() {
    return {seconds: this.rows.length > 1 ? (this.rows.at(-1).at - this.rows[0].at) / 1000 : 0,
      capacity: this.hold, bytes: this.bytes};
  }
  async export(seconds, folder, ffmpeg) {
    const end = this.rows.at(-1)?.at;
    if (!end || Date.now() - end > 5000) throw new Error('Pine Lens recording is not currently active');
    const floor = end - seconds * 1000;
    const rows = this.rows.filter(r => r.at >= floor);
    if (rows.length < 2) throw new Error('Pine Lens has not recorded enough history yet');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-lens-export-'));
    try {
      // Copy the snapshot before awaiting encoding so ring eviction cannot remove it.
      rows.forEach((r, i) => fs.copyFileSync(r.file, path.join(dir, i + '.jpg')));
      const held = (end - rows[0].at) / 1000;
      const lines = rows.flatMap((r, i) => ["file '" + i + ".jpg'",
        'duration ' + (i + 1 < rows.length ? (rows[i + 1].at - r.at) / 1000 : .25)]);
      lines.push("file '" + (rows.length - 1) + ".jpg'");
      fs.writeFileSync(path.join(dir, 'frames.txt'), lines.join('\n'));
      fs.mkdirSync(folder, {recursive: true});
      const out = path.join(folder, 'pinelens-' + Date.now() + '.mp4');
      await mux.run(mux.findFfmpeg(ffmpeg).path, ['-hide_banner', '-nostdin', '-y', '-f', 'concat',
        '-safe', '0', '-i', path.join(dir, 'frames.txt'), '-t', String(held),
        '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
        '-r', '30', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart', out], 600000);
      return {path: out, seconds: held, asked: seconds, partial: held < seconds - .3};
    } finally { fs.rmSync(dir, {recursive: true, force: true}); }
  }
  close() { fs.rmSync(this.dir, {recursive: true, force: true}); }
}
module.exports = {LensRecording};
