/* [llm-command] The LLM command popup: parses, exports its global, has its X, ASCII only (2026-10-06).
   node --test tests/test_llm_commands_ui_2026_10_06.cjs
   Finds the files in the repo (desktop/renderer, and the tablet copy under pine-views) or, before
   integration, beside this test under ../modules. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '..');
function find(name) {
  const places = [path.join(ROOT, 'desktop', 'renderer', name), path.join(ROOT, 'modules', name), path.join(__dirname, '..', 'modules', name)];
  return places.filter(p => fs.existsSync(p));
}
const JS = find('llm-commands.js');
const CSS = find('llm-commands.css');
const TABLET = [path.join(ROOT, 'app', 'src', 'main', 'assets', 'pine-views', 'llm-commands.js')].filter(p => fs.existsSync(p));

test('the popup script and its stylesheet exist', () => {
  assert.ok(JS.length, 'llm-commands.js');
  assert.ok(CSS.length, 'llm-commands.css');
});

for (const file of JS) {
  const src = fs.readFileSync(file, 'utf8');
  const short = path.relative(ROOT, file);
  test(short + ': parses as a plain script', () => {
    assert.doesNotThrow(() => new vm.Script(src, {filename: file}));
  });
  test(short + ': ASCII only - no emoji, no typographic quotes or arrows', () => {
    const bad = src.match(/[^\x00-\x7f]/g);
    assert.equal(bad, null, 'non-ASCII: ' + JSON.stringify(bad && bad.slice(0, 8)));
  });
  test(short + ': defines window.PineLlmCommands with open, close and mount, and touches no DOM at load', () => {
    const ctx = {console, setTimeout, clearTimeout, setInterval, clearInterval};
    ctx.window = ctx;
    ctx.document = new Proxy({}, {get(_, key) { throw new Error('the script touched document.' + String(key) + ' at load'); }});
    vm.createContext(ctx);
    new vm.Script(src, {filename: file}).runInContext(ctx);
    const api = ctx.PineLlmCommands;
    assert.ok(api, 'PineLlmCommands');
    for (const fn of ['open', 'close', 'mount']) assert.equal(typeof api[fn], 'function', fn);
  });
  test(short + ': the PiP tools catalog would discover it (a Pine* global assigned an object with open)', () => {
    assert.match(src, /root\.PineLlmCommands\s*=\s*\{open:\s*open,\s*close:\s*close,\s*mount:\s*mount/);
    const acornPath = path.join(ROOT, 'desktop', 'vendor', 'acorn.cjs');
    if (!fs.existsSync(acornPath)) return;
    const acorn = require(acornPath);
    assert.doesNotThrow(() => acorn.parse(src, {ecmaVersion: 'latest', sourceType: 'script', allowReturnOutsideFunction: true}));
  });
  test(short + ': every popup has an X in its corner, with a tooltip', () => {
    assert.match(src, /pineCloseX\(box,\s*close,\s*\{label:\s*'Close the LLM command book'\}\)/, 'the shared X');
    assert.match(src, /x\.title = 'Close the LLM command book'/, 'the fallback X has a tooltip');
    assert.match(src, /x\.setAttribute\('aria-label', 'Close the LLM command book'\)/, 'and a name');
    assert.match(src, /b\.title = title \|\| label/, 'icon-less buttons carry tooltips');
  });
  test(short + ': no auto-scroll takeover', () => {
    assert.doesNotMatch(src, /scrollIntoView|\.scrollTo\(|\.scroll\(/);
    assert.match(src, /wrap\.scrollTop = top/, 'a repaint puts the scroll back where it was');
  });
  test(short + ': talks to the station through the portable request (bridge, else fetch with the key)', () => {
    assert.match(src, /root\.pineDesktop/);
    assert.match(src, /headers\.Authorization = 'Bearer ' \+ key/);
    assert.match(src, /\/api\/llm-commands\/try/);
    assert.match(src, /\/api\/llm-commands\/custom/);
    assert.match(src, /\/api\/llm-commands\/note\//);
  });
}

for (const file of CSS) {
  const css = fs.readFileSync(file, 'utf8');
  const short = path.relative(ROOT, file);
  test(short + ': ASCII only, dark palette, works at phone width', () => {
    assert.equal(css.match(/[^\x00-\x7f]/g), null);
    assert.match(css, /\.lc-back\s*\{\s*position: fixed; inset: 0;/);
    assert.match(css, /@media \(max-width: 700px\)/);
    assert.match(css, /\.lc-table td::before \{ content: attr\(data-label\)/);
  });
}

test('the tablet copy, when present, is identical to the desk copy', () => {
  if (!TABLET.length || !JS.length) return;
  assert.equal(fs.readFileSync(TABLET[0], 'utf8'), fs.readFileSync(JS[0], 'utf8'));
});
