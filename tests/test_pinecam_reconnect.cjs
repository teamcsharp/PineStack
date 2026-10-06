const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Exercise the actual view lifecycle and state poll with the UI/native
// boundaries stubbed. No radio, station or camera is changed by this test.
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/pine-cam.js'), 'utf8');
const lifecycle = source.slice(source.indexOf("  var VIEW_KEY ="), source.indexOf('  /* [vcrfx] THE BOX'));
const poll = source.slice(source.indexOf('  function look() {'), source.indexOf('  /* ------------------------------------------------- the sidebar row */'));
const saved = new Map();
const context = vm.createContext({
  root: {}, Promise, Date, JSON, setTimeout, setInterval: () => 1, clearInterval: () => {},
  localStorage: {getItem: k => saved.get(k), setItem: (k, v) => saved.set(k, v)},
  document: {getElementById: () => null},
  shown: false, bare: true, live: false, box: {hidden: true}, frameTimer: 0,
  FRAME_MS: 250, BARE_DEFAULT: true, nativeOn: false, boxRecFrom: 0,
  cropOn: false, tsInfo: null, toastWaitUntil: 0, polled: true, announceSeen: 0,
  recFrom: 0, answer: null, toasts: 0,
});
vm.runInContext(`
  function ask(){return Promise.resolve(answer)}
  function build(){} function setBare(v){bare=v}
  function vcrBox(v){box.hidden=!v}
  function paintFrame(){} function nativeStart(){} function nativeStop(){}
  function repaintPicture(){} function cropRadialClose(){} function cropDrawClose(){}
  function mjpegStop(){} function pathPaint(){} function showButton(){}
  function hideToast(){} function showToast(){toasts++}
  function paintRow(){} function paintBattery(){} function railTabs(){}
  ${lifecycle}\n${poll}
`, context);
async function read(answer) {
  context.answer = answer;
  vm.runInContext('look()', context);
  await new Promise(resolve => setTimeout(resolve, 15));
}
(async () => {
  await read({state: 'live', fresh: true});
  vm.runInContext('open(false)', context);
  const viewing = saved.get('pineCamView');
  await read({state: 'live', fresh: false});
  assert.equal(context.shown, false, 'stale footage is hidden');
  assert.equal(saved.get('pineCamView'), viewing, 'disconnect preserves viewing intent');
  const toasts = context.toasts;
  await read({state: 'joining', fresh: true});
  await read({state: 'live', fresh: true});
  assert.equal(context.shown, true, 'fresh live feed restores PiP');
  assert.equal(context.bare, false, 'header preference survives recovery');
  assert.equal(context.toasts, toasts, 'automatic recovery needs no second notification');
  await read({state: 'waiting', fresh: true});
  vm.runInContext('close()', context);
  await read({state: 'live', fresh: true});
  assert.equal(context.shown, false, 'explicit dismissal cancels restoration');
  vm.runInContext('open(); close({type:"click"})', context);
  assert.equal(JSON.parse(saved.get('pineCamView')).open, false, 'click event counts as explicit dismissal');
  vm.runInContext('open(false); close(true); viewRestored=false', context);
  await read({state: 'live', fresh: true});
  assert.equal(context.shown, true, 'saved viewing intent also restores after reload');
  console.log('PineCam reconnect: stale hide, automatic restore, header retention and explicit close passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
