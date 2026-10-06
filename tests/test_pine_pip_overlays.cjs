// Controlled clocks exercise the actual overlay functions without Electron.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/pine-pip.js'), 'utf8');
let now = 0, serial = 0, saved, position;
const timers = new Map();
class Element {
  constructor(tag, cls = '') { this.tagName = tag; this.className = cls; this.children = []; this.dataset = {}; this.style = { setProperty(k,v) { this[k] = v; } }; this.events = {}; this.offsetWidth = 200; this.offsetHeight = 120; this.offsetLeft = 10; this.offsetTop = 20; const classes = new Set(); this.classList = { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) }; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); }
  replaceChildren(...children) { this.children = children; this.textContent = ''; }
  setAttribute() {}
  removeAttribute(key) { delete this[key]; }
  addEventListener(type, fn) { this.events[type] = fn; }
  scrollIntoView() {}
  setPointerCapture() {}
  hasPointerCapture() { return false; }
  querySelector(selector) { const matches = n => selector.startsWith('.') ? n.className.split(' ').includes(selector.slice(1)) : n.tagName === selector; for (const child of this.children) { if (matches(child)) return child; const nested = child.querySelector(selector); if (nested) return nested; } return null; }
}
const node = (tag, cls, text) => { const e = new Element(tag,cls); if (text != null) e.textContent = text; return e; };
const root = { addEventListener() {}, matchMedia: () => ({matches:false}), crypto:{getRandomValues: a => {a[0] = 5;}}, desktopMusicUrl: s => 'http://fixture' + s };
const context = vm.createContext({ node, root, innerWidth:440, innerHeight:330, setTimeout: (fn,ms) => { timers.set(++serial,{fn,at:now+ms}); return serial; }, clearTimeout: id => timers.delete(id), say() {}, api: () => ({pipUpdate: value => {saved = value; return Promise.resolve();}}) });
vm.runInContext(`let painting, paintingKey='', paintingTimer, slateTimers=[], slateDrag; const widgets={}; const overlay=node('div'); let currentLine='one', liveSpeaker='Host'; let state={active:true,ui:true,widgets:{roulette:true},roulettePosition:{x:.04,y:.18}}; let station={}; let lastPayload={now:{id:'one',name:'Host',text:'Spoken line'}};` + source.slice(source.indexOf('  function clearSlate()'),source.indexOf('  function cameraWanted()')) + source.slice(source.indexOf('  function safeImage('),source.indexOf('  function updateCast()')), context);
const run = code => vm.runInContext(code,context);
function advance(ms) { const end=now+ms; while (true) { const next=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0]; if (!next) break; now=next[1].at; timers.delete(next[0]); next[1].fn(); } now=end; }
run('buildSlate();buildPainting();');
run(`assembleSlate({decisions:[{family:'TOPIC',selected:{label:'Final topic'},stages:[{stage:'category',selected:'a',draw:{u:.4},candidates:[{id:'a',label:'Arts'},{id:'b',label:'News'}]},{stage:'item',selected:'p',draw:{dice:64},candidates:[{id:'p',label:'Painting'}]}]}]},'one');`);
advance(0); assert.equal(run("widgets.roulette.querySelector('.pip-slate-rolls').children.length"),1);
assert.match(run("widgets.roulette.querySelector('.pip-slate-rolls').children[0].children[1].textContent"),/u 0.4000.*Arts/,'stage winner and actual RNG are preserved');
assert.equal(run("widgets.roulette.querySelector('.pip-slate-line').textContent"),'');
advance(650); assert.equal(run("widgets.roulette.querySelector('.pip-slate-rolls').children.length"),2);
advance(650); assert.equal(run("widgets.roulette.querySelector('.pip-slate-line').textContent"),'Spoken line');
run("assembleSlate({decisions:[{stages:[{stage:'item',draw:{dice:10},selected:'x'}]}]},'one');currentLine='two';clearSlate();");advance(2000);
assert.equal(run("widgets.roulette.querySelector('.pip-slate-line').textContent"),'','changing line cancels stale assembly');
run("placeSlate({x:1,y:1})");assert.equal(run('widgets.roulette.style.left'),'240px');assert.equal(run('widgets.roulette.style.top'),'210px');
run("widgets.roulette.querySelector('.pip-slate-move').events.keydown({key:'ArrowRight',preventDefault(){}})");assert.ok(saved.roulettePosition.x>0,'position saved through PiP preferences');
run("station={selling_now:{image:'art.png',title:'Active art',at:1}};updatePainting();painting.querySelector('img').onload();");
assert.equal(run('painting.dataset.seconds'),10);assert.equal(run("painting.classList.contains('show')"),true);
assert.equal(run("painting.querySelector('img').src"),'http://fixture/api/generations/image/art.png');
advance(9999);assert.equal(run("painting.classList.contains('show')"),true);advance(1);assert.equal(run("painting.classList.contains('show')"),false);
run('updatePainting()');assert.equal(timers.size,0,'same sale never restarts timed thumbnail');
run("station={};updatePainting()");assert.equal(run('paintingKey'),'');
run("station={gallery_now:{images:['gallery.png']}};updatePainting()");assert.match(run("painting.querySelector('img').src"),/gallery.png$/);
console.log('PiP overlays: sequential recorded stages, line assembly/cancellation, bounds/persistence, painting selection and timed dismissal passed');
