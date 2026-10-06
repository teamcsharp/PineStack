/* [supercut-marquee] the studio's marquee: both copies identical, the source parses, the parts are there. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const DESK = path.join(ROOT, 'desktop', 'renderer');
const TAB = path.join(ROOT, 'app', 'src', 'main', 'assets', 'pine-views');
const ASCII_ONLY = new RegExp('^[\\x00-\\x7f]*$');

test('[supercut-marquee] the studio parses, and the tablet copy is the desk copy', () => {
  for (const name of ['supercut-review.js', 'supercut-review.css']) {
    const desk = fs.readFileSync(path.join(DESK, name), 'utf8');
    assert.equal(desk, fs.readFileSync(path.join(TAB, name), 'utf8'), name + ' is mirrored');
  }
  const src = fs.readFileSync(path.join(DESK, 'supercut-review.js'), 'utf8');
  new vm.Script(src, { filename: 'supercut-review.js' });
  const start = src.indexOf('var marquee = make'), end = src.indexOf('loadMarquee();', start);
  assert.ok(start > 0 && end > start, 'the marquee block is there');
  assert.match(src.slice(start, end), ASCII_ONLY, 'the marquee adds nothing outside ASCII');
  for (const part of ['psc-marquee-track', 'function loadMarquee()', 'function marqueeCard(row)', "'Reuse prompt'", 'recallPrompt(full)', 'loadArchive(row.id)',
    'limit=100&offset=0', 'cancelAnimationFrame(marqueeRaf)', 'Promise.all([loadLibrary(), loadMarquee()])']) {
    assert.ok(src.includes(part), 'the studio has ' + part);
  }
  const css = fs.readFileSync(path.join(DESK, 'supercut-review.css'), 'utf8');
  for (const part of ['.psc-marquee-track{', '.psc-marquee-card.selected{', '.psc-marquee-reuse{', 'body.pine-pip .psc-marquee-card{']) assert.ok(css.includes(part), 'the style has ' + part);
});

test('[supercut-marquee] the marquee loops by laying the row twice and pauses for a hand on it', () => {
  const src = fs.readFileSync(path.join(DESK, 'supercut-review.js'), 'utf8');
  assert.ok(src.includes('if (marqueeRows.length > 2) marqueeRows.forEach'), 'a second copy only when there is something to loop');
  assert.ok(src.includes("marquee.matches(':hover')"), 'a pointer over it pauses it');
  assert.ok(src.includes("['pointerdown', 'touchstart', 'wheel', 'focusin']"), 'a touch, a wheel or focus holds it');
  assert.ok(src.includes('marqueeTrack.scrollLeft -= half'), 'the loop wraps at the halfway point');
});
