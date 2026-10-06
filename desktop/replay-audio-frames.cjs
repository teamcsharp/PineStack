'use strict';
// Capture only frames hosted inside this Pine window, never system loopback.
class ReplayAudioFrames {
  constructor({ getWindow, getPanel, onChanged }) {
    this.getWindow = getWindow; this.getPanel = getPanel; this.onChanged = onChanged;
    this.guests = new Map(); this.revision = 0;
  }
  usable(contents) {
    try {
      if (!contents || contents.isDestroyed()) return null;
      const url = contents.getURL();
      return url && !/^about:blank(?:$|[?#])/.test(url) ? contents.mainFrame : null;
    } catch (_) { return null; }
  }
  frame(target) {
    try {
      if (target === 'shell') {
        const host = this.getWindow();
        return host && !host.isDestroyed() ? host.webContents.mainFrame : null;
      }
      if (target === 'panel') return this.getPanel();
      const match = /^guest:(\d+)$/.exec(String(target));
      return match ? this.usable(this.guests.get(Number(match[1]))) : null;
    } catch (_) { return null; }
  }
  targets() {
    const targets = this.frame('shell') ? ['shell'] : [];
    const panel = this.frame('panel');
    if (panel) targets.push('panel');
    for (const [id, guest] of this.guests) {
      const frame = this.usable(guest);
      if (frame && frame !== panel) targets.push('guest:' + id);
    }
    return targets;
  }
  changed() {
    this.revision++;
    this.onChanged?.({ targets: this.targets(), revision: this.revision });
  }
  track(contents) {
    if (this.guests.has(contents.id)) return;
    this.guests.set(contents.id, contents);
    contents.on('did-finish-load', () => this.changed());
    contents.on('did-navigate', () => this.changed());
    contents.once('destroyed', () => { this.guests.delete(contents.id); this.changed(); });
    this.changed();
  }
}
module.exports = { ReplayAudioFrames };
