/* [supercut-gallery] the studio's tiles are the videos: both copies identical, the source parses, the parts are there. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const DESK = path.join(ROOT, 'desktop', 'renderer');
const TAB = path.join(ROOT, 'app', 'src', 'main', 'assets', 'pine-views');
const ASCII_ONLY = new RegExp('^[\\x00-\\x7f]*$');

function block(src, from, to) {
  const start = src.indexOf(from), end = src.indexOf(to, start);
  assert.ok(start > 0 && end > start, 'the block from ' + JSON.stringify(from) + ' is there');
  return src.slice(start, end);
}

test('[supercut-gallery] the studio parses, the tablet copy is the desk copy, and the new blocks are ASCII', () => {
  for (const name of ['supercut-review.js', 'supercut-review.css']) {
    const desk = fs.readFileSync(path.join(DESK, name), 'utf8');
    assert.equal(desk, fs.readFileSync(path.join(TAB, name), 'utf8'), name + ' is mirrored');
  }
  const src = fs.readFileSync(path.join(DESK, 'supercut-review.js'), 'utf8');
  new vm.Script(src, { filename: 'supercut-review.js' });
  assert.match(block(src, 'function marqueeCard(row)', 'function marqueeStep(now)'), ASCII_ONLY, 'the tile and the player add nothing outside ASCII');
  const css = fs.readFileSync(path.join(DESK, 'supercut-review.css'), 'utf8');
  assert.match(block(css, '/* [supercut-gallery]', 'audio.psc-player-video'), ASCII_ONLY, 'the stylesheet block is ASCII');
});

test('[supercut-gallery] a tile is its poster frame with a play mark, and a tap plays the supercut', () => {
  const src = fs.readFileSync(path.join(DESK, 'supercut-review.js'), 'utf8');
  const card = block(src, 'function marqueeCard(row)', 'function closePlayer()');
  for (const part of ["'psc-marquee-frame'", "'psc-marquee-poster'", 'poster.src = url(row.poster_url)', "pineIcon('c:play--filled')", "mark.textContent = 'Play'",
    "view.title = 'Play this supercut'", 'playArchive(row.id); loadArchive(row.id);', "frame.classList.add('no-poster')"]) {
    assert.ok(card.includes(part), 'the tile has ' + part);
  }
  assert.ok(!card.includes("'View ' +"), 'the tile no longer says View');
  assert.ok(src.includes("' supercuts made so far - tap one to play it, or reuse its prompt'"), 'the note says play');
});

test('[supercut-gallery] the player sits under the marquee, plays at once, and has its own way out', () => {
  const src = fs.readFileSync(path.join(DESK, 'supercut-review.js'), 'utf8');
  const player = block(src, 'function closePlayer()', 'function marqueeMark()');
  for (const part of ['function openPlayer(full)', 'function playArchive(id)', "make(full.video_url ? 'video' : 'audio', 'psc-player-video')",
    'playerVideo.controls = true', 'playerVideo.autoplay = true', 'marquee.parentNode.insertBefore(player, marquee.nextSibling)',
    "x.title = 'Close the player'", "x.setAttribute('aria-label', 'Close the player')", "root.pineCloseX(player, closePlayer, {label: 'Close the player'})",
    "ev.key === 'Escape' && player", 'audio only, this cut has no video']) {
    assert.ok(player.includes(part), 'the player has ' + part);
  }
  assert.ok(src.includes('stop(audio); closePlayer(); panel.remove();'), 'disposing the studio stops the player');
  const css = fs.readFileSync(path.join(DESK, 'supercut-review.css'), 'utf8');
  for (const part of ['.psc-marquee-frame{', '.psc-marquee-poster{', '.psc-marquee-play{', '.psc-player{', '.psc-player-close{', '.psc-player-video{', 'audio.psc-player-video{']) {
    assert.ok(css.includes(part), 'the stylesheet has ' + part);
  }
});
