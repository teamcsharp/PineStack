// Shared geometry and settings for the display and its desktop preview.
(function (root) {
  const timers = [30, 60, 300, 900];
  function corner(width = 320, height = 240) {
    const w = Math.floor(width / 5), h = Math.floor(height / 4);
    return {x: 0, y: 0, w, h, badge: {x: 4, y: 4, w: w - 8, h: h - 12}};
  }
  function cornerHit(x, y, width = 320, height = 240) {
    const box = corner(width, height);
    return x >= 0 && y >= 0 && x < box.w && y < box.h;
  }
  function timerLabel(seconds) { return seconds < 60 ? seconds + ' sec' : Math.round(seconds / 60) + ' min'; }
  function view(config = {}) {
    if (['dialogue', 'cupboard', 'gallery'].includes(config.mode)) return config.mode;
    if (config.paperStyle === 'tabloid') return 'tabloid';
    return config.chatOverlay === false ? 'newspaper' : 'paper';
  }
  function tiles(config = {}, width = 320, height = 240) {
    const sx = width / 320, sy = height / 240, selected = view(config);
    return [
      ['newspaper', 'Newspaper only', selected === 'newspaper', 'paper'],
      ['gallery', 'Pine gallery', selected === 'gallery', 'gallery'],
      ['paper', 'Paper + chat', selected === 'paper', 'chat'],
      ['tabloid', 'Tabloid', selected === 'tabloid', 'tabloid'],
      ['chat', 'Chat overlay', (!config.mode || config.mode === 'paper') && config.chatOverlay !== false, 'chat'],
      ['scroll', 'Auto-scroll', config.scrollEnabled !== false, 'scroll'],
      ['avatar', 'Quanta avatars', false, 'avatar'],
      ['saver', 'Screensaver', !!config.screensaverEnabled, 'moon'],
    ].map(([id, label, active, icon], i) => ({id, label, active, icon,
      x: (8 + (i % 2) * 156) * sx, y: (62 + Math.floor(i / 2) * 36) * sy,
      w: 148 * sx, h: 32 * sy}));
  }
  function hit(x, y, width, height, config) {
    if (cornerHit(x, y, width, height)) return 'swap';
    const tile = tiles(config, width, height).find(t => x >= t.x && x < t.x + t.w && y >= t.y && y < t.y + t.h);
    if (tile) return tile.id;
    if (y >= height * 210 / 240 && y < height * 236 / 240) return x < width * .66 ? 'timer' : 'close';
    if (y < height * 54 / 240 && x > width * .75) return 'close';
    return '';
  }
  function change(id, config = {}) {
    switch (id) {
      case 'chat': return {mode: 'paper', chatOverlay: config.mode && config.mode !== 'paper' ? true : config.chatOverlay === false, pausedCupboard: false};
      case 'newspaper': case 'paper': case 'tabloid': return {mode: 'paper', paperStyle: id === 'tabloid' ? 'tabloid' : 'broadsheet', chatOverlay: id === 'paper', pausedCupboard: false};
      case 'gallery': case 'dialogue': case 'cupboard': return {mode: id, pausedCupboard: false};
      case 'saver': return {screensaverEnabled: !config.screensaverEnabled};
      case 'scroll': return {scrollEnabled: config.scrollEnabled === false};
      case 'timer': return {screensaverSeconds: timers[(timers.indexOf(Number(config.screensaverSeconds) || 300) + 1) % timers.length]};
      default: return null;
    }
  }
  function cycle(config = {}) { return change(view(config) === 'newspaper' ? 'gallery' : 'newspaper', config); }
  function gesture(start, end, width = 320, height = 240) {
    if (!start || !end) return '';
    const dx = end.x - start.x, dy = end.y - start.y;
    if (Math.abs(dy) >= height * .12 && Math.abs(dy) > Math.abs(dx) * 1.35) {
      if (dy < 0) return 'up';
      if (start.y <= height * .22) return 'down';
    }
    return Math.hypot(dx, dy) <= Math.min(width, height) * .06 ? 'tap' : '';
  }
  const api = {tiles, hit, change, cycle, view, gesture, timerLabel, corner, cornerHit};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PineLcdControls = api;
})(typeof globalThis === 'undefined' ? this : globalThis);
