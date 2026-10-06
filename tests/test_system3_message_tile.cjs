'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const tile = require('../desktop/renderer/system3-message-tile.js');

class Element {
  constructor(tag, cls, text) {
    this.tagName = tag.toUpperCase(); this.className = cls || '';
    this.children = []; this.parentNode = null; this.attrs = {};
    this._text = text == null ? '' : String(text);
    this.style = {setProperty(name, value) { this[name] = value; }};
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      add: (...names) => { this.className = [...new Set(this.className.split(/\s+/).filter(Boolean).concat(names))].join(' '); },
      remove: (...names) => { this.className = this.className.split(/\s+/).filter(name => !names.includes(name)).join(' '); },
      toggle: (name, on) => {
        const active = on === undefined ? !this.classList.contains(name) : !!on;
        this.classList[active ? 'add' : 'remove'](name); return active;
      }
    };
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] || null; }
  addEventListener(name, listener) {
    this.listeners ||= new Map();
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener); this.listeners.set(name, listeners);
  }
  removeEventListener(name, listener) {
    this.listeners?.set(name, (this.listeners.get(name) || []).filter(fn => fn !== listener));
  }
  dispatchEvent(event) {
    event.target ||= this;
    event.preventDefault ||= () => { event.defaultPrevented = true; };
    event.stopPropagation ||= () => {};
    (this.listeners?.get(event.type) || []).slice().forEach(fn => fn(event));
    return !event.defaultPrevented;
  }
  contains(other) { return this === other || this.children.some(child => child.contains(other)); }
  querySelectorAll(selector) {
    const cls = selector.replace(/^\./, '');
    return this.children.flatMap(child => (child.classList.contains(cls) ? [child] : []).concat(child.querySelectorAll(selector)));
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get firstChild() { return this.children[0] || null; }
}
const make = (tag, cls, text) => new Element(tag, cls, text);
const renderer = () => tile.createRenderer({make, familyColors: {ES: '#f88', RS: '#8af'}});
const reel = (dice, opts, hit, extra) => Object.assign({dice, opts, hit, label: opts[hit]}, extra);
const rows = () => [
  {fam: 'ES', table: 'ES1', tableLabel: 'Emotion Set 1',
    main: reel(80, ['JOY', 'INTEREST', 'ANGER'], 1, {weights: [1, 5, 1]}),
    sub: reel(95, ['certainty', 'uncertainty'], 1)},
  {fam: 'RS', table: 'RS1', main: reel(13, ['Agree', 'Opposite'], 1)}
];

test('the shared roulette lands category and indented subentry before advancing', () => {
  const r = renderer(), sheet = r.sheet({}, rows(), 6000);
  sheet.keep = true;
  const first = sheet.tables[0], next = sheet.tables[1];
  assert.equal(r.at(sheet, 0), '0:table');
  assert.equal(next.el.style.display, 'none');
  assert.equal(first.sub.el.style.display, 'none');
  assert.equal(r.at(sheet, first.dIn + first.dRej + 1), '0:cat-die');
  assert.equal(r.at(sheet, first.dIn + first.dRej + first.dDie + 1), '0:cat-spin');
  assert.equal(first.cat.die.textContent, '80');
  assert.equal(first.sub.el.style.display, 'none', 'subcategory waits until the category has landed');
  const subStart = first.dIn + first.dRej + first.dDie + first.dSpin + first.dPop + first.dRej2;
  assert.equal(r.at(sheet, subStart + 1), '0:sub-die');
  assert(first.sub.el.classList.contains('sp-rr-sub'), 'retains the Digital indentation');
  assert.equal(r.at(sheet, subStart + first.dDie2 + first.dSpin2 + 1), '0:sub-pop');
  assert.equal(first.sub.die.textContent, '95');
  assert.equal(first.cat.of.textContent, '2 of 3');
  assert.equal(first.sub.of.textContent, '2 of 2');
  assert.equal(r.at(sheet, next.at + 1), '1:table');
  assert(!first.el.classList.contains('folded'), 'the completed category retains its original reel presentation');
  assert.equal(first.el.style.display, '', 'completed rows remain above the active category');
  assert.equal(r.at(sheet, sheet.rolled), 'results');
  assert.equal(sheet.box.querySelectorAll('.sp-rr-sub').length, 1);
  assert.equal(sheet.box.querySelectorAll('.sp-rr-line').length, 0, 'landing creates no compact duplicate or summary');
  assert.equal(first.cat.die.textContent, '80');
  assert.equal(first.sub.die.textContent, '95');
  assert.equal(first.cat.list.children.at(-1).textContent, 'INTEREST');
  assert.equal(first.sub.list.children.at(-1).textContent, 'uncertainty');
  assert.equal(next.cat.list.children.at(-1).textContent, 'Opposite');
  assert.equal(first.cat.el.style.display, '');
  assert.equal(first.sub.el.style.display, '');
});

test('later rolls, results, and appended moment rows retain landed DOM and schedule', () => {
  const wired=[];
  const r=tile.createRenderer({make,wireEntry:(element,recorded,index,which)=>wired.push({element,recorded,index,which})});
  const sheet=r.sheet({},rows(),6000),first=sheet.tables[0];
  const nodes=[first.el,first.head,first.cat.el,first.cat.wheel,first.cat.die,first.cat.of,first.sub.el,first.sub.wheel];
  r.at(sheet,first.end);
  const schedule={at:first.at,end:first.end,dIn:first.dIn,dDie:first.dDie,dSpin:first.dSpin};
  const landed=nodes.map(element=>({children:[...element.children],text:element.textContent,style:{...element.style}}));
  for(const ms of [sheet.tables[1].at+1,sheet.tables[1].end,sheet.rolled,sheet.total+100]){
    r.at(sheet,ms);
    nodes.forEach((element,index)=>{
      assert.deepEqual(element.children,landed[index].children,'the original reel nodes remain in place');
      assert.equal(element.textContent,landed[index].text);
      assert.deepEqual({...element.style},landed[index].style,'finished formatting remains unchanged');
    });
  }
  const previousRows=sheet.rows,previousTables=[...sheet.tables],previousSchedule=sheet.tables.map(t=>[t.at,t.end]);
  const fresh={fam:'SFX',table:'book',main:reel(60,['sample A','sample B'],1)};
  const appendAt=sheet.total+500;
  r.append(sheet,[fresh],{appendAt},3000);
  assert.equal(sheet.rows,previousRows,'inspector adapters retain the same recorded-row collection');
  previousTables.forEach((table,index)=>assert.equal(sheet.tables[index],table));
  assert.deepEqual(sheet.tables.slice(0,2).map(t=>[t.at,t.end]),previousSchedule,'later data never retimes an already landed roll');
  assert.deepEqual({at:first.at,end:first.end,dIn:first.dIn,dDie:first.dDie,dSpin:first.dSpin},schedule);
  assert.equal(sheet.tables[2].at,appendAt,'late rows start at their actual append time');
  assert.equal(wired.at(-1).recorded,sheet.rows);assert.equal(wired.at(-1).index,2);
  r.at(sheet,appendAt+1);
  nodes.forEach((element,index)=>{
    assert.deepEqual(element.children,landed[index].children);
    assert.deepEqual({...element.style},landed[index].style);
  });
  r.results(sheet);r.results(sheet);
  assert.equal(sheet.box.querySelectorAll('.sp-rr-line').length,0);
  assert.equal(first.sub.el.getAttribute('data-state'),'landed');
});

test('reels retain real labels, weights, and counted large-pool results', () => {
  const r = renderer();
  const step = r.step(reel(60, ['Small', 'Large'], 1, {weights: [1, 9]}), false);
  const cells = step.list.children;
  assert.equal(cells.at(-1).textContent, 'Large');
  assert(Number.parseInt(cells.find(c => c.textContent === 'Large').style.height)
    > Number.parseInt(cells.find(c => c.textContent === 'Small').style.height));
  const counted = r.step({dice: 71, counted: true, label: '29 is high as', index: 12, of: 3309, opts: ['29 is high as'], hit: 0}, true);
  assert.equal(counted.landedOf, '12 of 3309');
  assert.equal(counted.list.children.at(-1).textContent, '29 is high as');
  assert(counted.list.children.length < 10, 'large pools use the station result without fabricating candidates');
});

test('rejected candidates go grey before the recorded roll and failed result', () => {
  const r = renderer();
  const row = {fam: 'RS', table: 'RS1',
    main: reel(13, ['Agree', 'Opposite'], 1, {rej: [{label: 'Repeat', why: 'already used'}]}),
    failed: {why: 'no eligible response'}};
  const sheet = r.sheet({}, [row], 3000), t = sheet.tables[0];
  assert.equal(r.at(sheet, t.dIn + 1), '0:cat-rej');
  assert(t.cat.rej[0].classList.contains('pop'));
  assert.equal(t.cat.rej[0].getAttribute('aria-disabled'), 'true');
  r.at(sheet, t.dIn + t.dRej + 1);
  assert(t.cat.rej[0].classList.contains('gone'));
  r.at(sheet, sheet.rolled);
  assert(t.el.classList.contains('sp-rr-failed'));
  assert.equal(t.el.title, 'no eligible response');
  assert.match(t.head.textContent, /1 rejected/);
  assert(!t.cat.die.classList.contains('rolling'));
  assert(!t.cat.wheel.classList.contains('spinning'));
});

test('scheduled buildup ends at the station time', () => {
  const sheet = renderer().sheet({buildFit: {ms: 7000, from: 0}}, rows(), 6000);
  assert(Math.abs(sheet.total - 7000) < 1e-6);
  assert(Math.abs(sheet.tables[1].at - sheet.tables[0].end - tile.BUILD.between) < 1e-6);
});

test('typing follows audio progress smoothly without erasing prior characters', () => {
  assert.equal(tile.typeCount(20, .1, 100), 20);
  const first = tile.typeCount(0, .8, 100);
  assert(first > 0 && first < 80);
  let count = first;
  for (let frame = 0; frame < 25; frame++) count = tile.typeCount(count, 1, 100);
  assert.equal(count, 100);
});

test('desktop and PineTab load one shared roulette renderer before the feed', () => {
  const root = path.resolve(__dirname, '..');
  for (const name of ['system3-message-tile.js', 'system3-message-tile.css']) {
    assert.equal(fs.readFileSync(path.join(root, 'app/src/main/assets/pine-views', name), 'utf8'),
      fs.readFileSync(path.join(root, 'desktop/renderer', name), 'utf8'), name + ' must be synchronized');
  }
  const html = fs.readFileSync(path.join(root, 'desktop/renderer/index.html'), 'utf8');
  assert(html.indexOf('src="./system3-message-tile.js"') < html.indexOf('src="./script-page.js"'));
  const page = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8');
  assert.match(page, /PineSystem3MessageTile\.createRenderer/);
  assert.match(page, /function mvRrSheet[^]*?return mvTileRenderer\.sheet\(/);
  assert.match(page, /function mvRrStepAt[^]*?return mvTileRenderer\.stepAt\(/);
});

Element.prototype.append = function (...children) { children.forEach(child => this.appendChild(child)); };
Element.prototype.remove = function () {
  if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this);
  this.parentNode = null;
};
Element.prototype.replaceChildren = function (...children) { this.children.forEach(child => { child.parentNode = null; }); this.children = []; this.append(...children); };
Element.prototype.getBoundingClientRect = function () { return {top:0,bottom:100,left:0,right:400,width:400,height:100}; };
Object.defineProperty(Element.prototype, 'isConnected', {get() { return !!this.connected || !!this.parentNode?.isConnected; }});

function mounted(options, load, clock, onLayout, setup) {
  let nextId = 0, frameTime = 1000;
  const frames = new Map();
  const view = {requestAnimationFrame(fn) { frames.set(++nextId, fn); return nextId; },
    cancelAnimationFrame(id) { frames.delete(id); }, matchMedia() { return {matches:false}; }};
  const doc = {defaultView:view, hidden:false, addEventListener() {}, removeEventListener() {}};
  const host = new Element('main'); host.connected = true; host.ownerDocument = doc;
  const localMake = (tag, cls, text) => { const element = make(tag, cls, text); element.dataset = {}; return element; };
  setup?.({view,doc,host,make:localMake});
  const instance = tile.mount(host, {make:localMake,window:view,options,load,clock,onLayout});
  const beat = (id, text = 'x') => ({now:{id,text,from:0,until:1},station:{stream_now:{at:1000}}});
  const step = (ms = 100) => { frameTime += ms; const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(fn => fn(frameTime)); };
  return {instance,host,beat,step,frames,view,doc};
}
const flush = async () => { for (let microtask = 0; microtask < 8; microtask++) await Promise.resolve(); };

test('the reusable mount holds, fades, and bounds completed history', async t => {
  let wall = 1001000;
  t.mock.method(Date, 'now', () => wall);
  const world = mounted({}, async () => ({rows:[]}), () => wall);
  world.instance.receive(world.beat('hold'));await flush();world.step();
  assert.equal(world.instance.state().phase,'done');
  wall += 100000;world.step();
  assert.equal(world.instance.state().visible,true,'hold survives until another on-air message');
  assert.equal(world.instance.state().raf,false,'held completed tile has no idle animation loop');
  world.instance.configure({mode:'fade',fadeDelay:1});
  wall += 900;world.step();assert.equal(world.instance.state().visible,true);
  wall += 700;world.step();assert.equal(world.instance.state().visible,false,'fade obeys the configured delay');
  world.instance.configure({mode:'history'});
  for(let n=0;n<16;n++){world.instance.receive(world.beat('history-'+n));await flush();world.step();}
  assert.equal(world.host.querySelectorAll('.pip-system3-message').length,12,'history has a bounded total of twelve message tiles');
  assert.equal(world.instance.state().history,11);
  world.instance.configure({mode:'hold'});
  assert.equal(world.host.querySelectorAll('.pip-system3-message').length,1,'returning to hold clears previous message history');
  world.instance.visible(false);assert.equal(world.instance.state().raf,false);
  world.instance.dispose();assert.equal(world.host.children.length,0);
});

test('a newer message discards stale asynchronous roulette data', async () => {
  const pending = new Map();
  const world = mounted({}, row => new Promise(resolve => pending.set(row.id, resolve)), () => 1001000);
  world.instance.receive(world.beat('old'));await flush();
  world.instance.receive(world.beat('new'));await flush();
  pending.get('new')({rows:[]});await flush();world.step();
  assert.equal(world.instance.state().current,'new');
  pending.get('old')({rows:rows()});await flush();world.step();
  assert.equal(world.instance.state().rows,0,'obsolete loader cannot attach its recorded roulette to the current message');
  assert.equal(world.host.querySelectorAll('.pip-system3-message').length,1);
  assert.equal(world.instance.state().typed,1);
  world.instance.dispose();assert.equal(world.frames.size,0);
});



test('mount typing uses the same steady rate across clip durations and playback clock jumps', async () => {
  const text='A constant typewriter rate stays independent of audio duration. '.repeat(20);
  const worlds=[];
  for(const duration of [.1,120,null]){
    let wall=1000000;
    const world=mounted({},async()=>({rows:[]}),()=>wall);
    const beat=world.beat('steady-'+duration,text);
    if(duration==null)beat.station={};else beat.now.until=duration;
    world.instance.receive(beat);await flush();world.step();
    assert.equal(world.instance.state().typed,1,'the first character appears immediately');
    for(let n=0;n<5;n++)world.step();
    const halfway=world.instance.state().typed;
    assert(halfway>=30&&halfway<=31,'500 ms reveals approximately 30 characters at the base rate');
    wall=9000000;
    world.instance.receive({...beat,station:duration==null?{}:{stream_now:{at:1000}}});
    assert.equal(world.instance.state().typed,halfway,'jumping playback cannot reveal extra text');
    for(let n=0;n<5;n++)world.step();
    worlds.push({world,typed:world.instance.state().typed,halfway});
  }
  assert.equal(new Set(worlds.map(item=>item.halfway)).size,1);
  assert.equal(new Set(worlds.map(item=>item.typed)).size,1,'equal local elapsed time yields equal prefixes for every clip');
  assert(worlds[0].typed>=60&&worlds[0].typed<=61,'one second reveals approximately 60 characters');
  worlds.forEach(({world,typed})=>{
    assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,text.slice(0,typed));
    world.instance.dispose();
  });
});

test('typing speed scales a constant character rate without depending on reply length', async () => {
  const counts=[];
  for(const [typingSpeed,length] of [[1,300],[1,1200],[2,1200]]){
    const world=mounted({typingSpeed},async()=>({rows:[]}),()=>1001000);
    world.instance.receive(world.beat('speed-'+typingSpeed+'-'+length,'x'.repeat(length)));await flush();world.step();
    for(let n=0;n<10;n++)world.step();
    counts.push(world.instance.state().typed);world.instance.dispose();
  }
  assert.equal(counts[0],counts[1],'shorter and longer replies share the same characters-per-second rate');
  assert(counts[0]>=60&&counts[0]<=61);
  assert(counts[2]>=120&&counts[2]<=121,'typingSpeed 2 doubles the base rate');
});

test('completed short text cannot bank roulette time to reveal a later correction instantly', async () => {
  const world=mounted({},async()=>({rows:rows()}),()=>1001000);
  const beat=world.beat('no-typing-bank','Hi');
  world.instance.receive(beat);await flush();
  for(let n=0;n<25;n++)world.step();
  assert.equal(world.instance.state().phase,'roll');assert.equal(world.instance.state().typed,2);
  const longer='A corrected longer reply keeps the same typewriter pace. '.repeat(8);
  world.instance.receive({...beat,now:{...beat.now,text:longer}});
  assert.equal(world.instance.state().typed,2,'correction preserves the visible character count');
  world.step();
  const revealed=world.instance.state().typed;
  assert(revealed>2&&revealed<=9,'only one fresh frame of typing is added after the correction');
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,longer.slice(0,revealed));
  world.instance.dispose();
});


test('async initial data and repeated fresh rolls do not interrupt the steady typing clock', async () => {
  const text='Typing retains its constant pace as new recorded events arrive. '.repeat(20);
  let answer,resolveInitial;
  const changing=mounted({},()=>answer?Promise.resolve({rows:answer}):new Promise(resolve=>resolveInitial=resolve),()=>1001000);
  const control=mounted({},async()=>({rows:rows()}),()=>1001000);
  const beat=changing.beat('continuous-data',text);
  changing.instance.receive(beat);control.instance.receive(control.beat('steady-control',text));await flush();
  changing.step();control.step();
  assert.equal(changing.instance.state().phase,'loading');
  for(let tick=0;tick<10;tick++){
    if(tick===0){answer=rows();resolveInitial({rows:answer});}
    else{
      answer=answer.concat({fam:'SFX',table:'Fresh '+tick,event:'fresh-'+tick,main:reel(60,['other','clip '+tick],1)});
      changing.instance.receive({...beat,now:{...beat.now,event_id:'update-'+tick}});
    }
    await flush();changing.step();control.step();
    assert.equal(changing.instance.state().typed,control.instance.state().typed,
      'recorded data delivery at tick '+tick+' does not discard elapsed typing time');
  }
  assert.equal(changing.instance.state().typed,tile.TYPING_CPS,'one second still reveals 60 characters');
  assert.equal(changing.instance.state().rows,11);
  assert.equal(changing.host.querySelectorAll('.pip-system3-words')[0].textContent,text.slice(0,tile.TYPING_CPS));
  changing.instance.dispose();control.instance.dispose();
});

test('late rolls and a longer correction wake a stopped card without banking idle time', async () => {
  let answer=rows();
  const world=mounted({},async()=>({rows:answer}),()=>1001000);
  const beat=world.beat('stopped-correction','Hi');
  world.instance.receive(beat);await flush();
  for(let n=0;n<60&&world.instance.state().phase!=='done';n++)world.step();
  assert.equal(world.instance.state().phase,'done');assert.equal(world.instance.state().raf,false);
  world.step(30000);
  answer=answer.concat({fam:'SFX',table:'Late clip',event:'late-stopped',main:reel(71,['other','late'],1)});
  const longer='A longer corrected reply wakes with the normal typewriter pace. '.repeat(10);
  world.instance.receive({...beat,now:{...beat.now,text:longer,event_id:'late-correction'}});await flush();world.step();
  assert.equal(world.instance.state().typed,2,'the first wake frame does not add stopped wall time to typing');
  assert.equal(world.instance.state().phase,'roll');
  assert.match(world.instance.state().rollNow,/^2:/,'the newly appended reel starts unfolding');
  world.step();
  assert(world.instance.state().typed>2&&world.instance.state().typed<=9,'the next 100 ms reveals only the normal six characters');
  world.instance.dispose();
});

test('every message has a live typewriter header above its running roulette rows', async () => {
  let wall=1000200;
  const world=mounted({mode:'history'},async()=>({rows:rows()}),()=>wall);
  const text='The reply starts typing above its recorded roulette results. '.repeat(3);
  const first=world.beat('header-first',text);first.now.until=4;
  world.instance.receive(first);
  const article=world.host.querySelectorAll('.pip-system3-message')[0];
  const words=article.querySelectorAll('.pip-system3-words')[0];
  const rolls=article.querySelectorAll('.pip-system3-rolls')[0];
  assert.equal(article.firstChild,words,'the message text is the first item in each entry');
  assert.equal(article.children[1],rolls,'roulette results appear below the header');
  assert.equal(words.hidden,false);
  assert.equal(words.textContent,text.slice(0,1),'the first character appears before recorded rolls finish loading');
  assert.equal(world.instance.state().phase,'loading');
  await flush();world.step();
  wall=1000400;world.step();
  for(let n=0;n<10&&!article.querySelectorAll('.sp-rr-wheel').some(wheel=>wheel.classList.contains('spinning'));n++)world.step();
  assert.equal(world.instance.state().phase,'roll');
  assert.notEqual(world.instance.state().rollNow,'results');
  assert(article.querySelectorAll('.sp-rr-wheel').some(wheel=>wheel.classList.contains('spinning')),
    'the header advances while the rolodex is still spinning');
  assert(words.textContent.length>1,'typing continues while the roulette spins');
  assert.equal(words.textContent,text.slice(0,world.instance.state().typed));
  wall=1004000;world.step();
  for(let n=0;n<60&&world.instance.state().phase!=='done';n++)world.step();
  assert.equal(world.instance.state().phase,'done');
  const next=world.beat('header-next','Another reply has its own typewriter header.');next.now.until=4;next.station.stream_now.at=1004;
  wall=1004200;world.instance.receive(next);await flush();world.step();
  const entries=world.host.querySelectorAll('.pip-system3-message');
  assert.equal(entries.length,2);
  entries.forEach(entry=>{
    assert.equal(entry.firstChild,entry.querySelectorAll('.pip-system3-words')[0]);
    assert.equal(entry.children[1],entry.querySelectorAll('.pip-system3-rolls')[0]);
  });
  assert.equal(entries[0],article,'completed history retains its original header and reels');
  assert.equal(words.textContent,text);
  world.instance.dispose();
});


test('late recorded data unfolds each reel even after playback has finished', async () => {
  let wall=1000000,resolve;
  const world=mounted({},()=>new Promise(done=>resolve=done),()=>wall);
  const text='A short reply finishes while its recorded results are loading.';
  world.instance.receive(world.beat('late-roulette',text));await flush();world.step();
  wall=1001000;
  for(let n=0;n<30&&world.instance.state().typed<text.length;n++)world.step();
  assert.equal(world.instance.state().phase,'loading');
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,text);
  resolve({rows:rows()});await flush();world.step();
  assert.equal(world.instance.state().phase,'roll','finished audio does not skip newly loaded roulette animation');
  assert.equal(world.instance.state().rollNow,'0:table','newly loaded reels start at their first row');
  assert.equal(world.host.querySelectorAll('.sp-rr-t')[1].style.display,'none','the subsequent row waits its turn');
  const stages=new Set([world.instance.state().rollNow]);
  for(let n=0;n<80&&world.instance.state().phase!=='done';n++){world.step();stages.add(world.instance.state().rollNow);}
  for(const stage of ['0:cat-die','0:cat-spin','0:sub-die','0:sub-spin','1:cat-die','1:cat-spin'])
    assert(stages.has(stage),'late data retains the visible '+stage+' stage');
  assert.equal(world.instance.state().phase,'done');
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,text);
  world.instance.dispose();
});

test('a one-second on-air clip does not fast-forward typing or the active rolodex', async () => {
  let wall=1000000;
  const world=mounted({},async()=>({rows:rows()}),()=>wall);
  const text='A one-second reply';
  world.instance.receive(world.beat('short-roulette',text));await flush();world.step();
  wall=1001000;world.step();
  assert(world.instance.state().typed>1&&world.instance.state().typed<text.length,'audio finishing does not fast-forward text');
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,text.slice(0,world.instance.state().typed));
  assert.equal(world.instance.state().phase,'roll','the short clip cannot complete the independent roulette timeline');
  assert.notEqual(world.instance.state().rollNow,'results');
  assert.equal(world.host.querySelectorAll('.sp-rr-sub')[0].style.display,'none','the subentry waits for its category to unfold');
  assert.equal(world.host.querySelectorAll('.sp-rr-t')[1].style.display,'none');
  const stages=new Set();
  for(let n=0;n<80&&world.instance.state().phase!=='done';n++){world.step();stages.add(world.instance.state().rollNow);}
  for(const stage of ['0:cat-spin','0:sub-spin','1:cat-spin'])
    assert(stages.has(stage),'short clips preserve the visible '+stage+' stage');
  assert.equal(world.instance.state().phase,'done');
  assert.equal(world.instance.state().rollNow,'results');
  world.instance.dispose();
});

test('fallback typing continues during asynchronous loading and roulette animation', async () => {
  let resolve;
  const world=mounted({followPlayback:false},()=>new Promise(done=>resolve=done),()=>1000000);
  const text='The header keeps typing while recorded System 3 results arrive and roll. '.repeat(4);
  world.instance.receive(world.beat('header-fallback',text));await flush();
  const article=world.host.querySelectorAll('.pip-system3-message')[0];
  const words=article.querySelectorAll('.pip-system3-words')[0];
  assert.equal(article.firstChild,words);
  assert.equal(words.hidden,false,'the typewriter is visible while decisions are loading');
  for(let n=0;n<4;n++)world.step(100);
  const prefix=words.textContent;
  assert(prefix.length>0&&prefix.length<text.length,'typing starts without a playback clock or loaded decisions');
  assert.equal(world.instance.state().phase,'loading');
  resolve({rows:rows()});await flush();
  assert.equal(words.textContent,prefix,'loading results preserves the text already shown');
  let spinning=false;
  for(let n=0;n<20&&!spinning;n++){
    world.step(100);
    spinning=article.querySelectorAll('.sp-rr-wheel').some(wheel=>wheel.classList.contains('spinning'));
  }
  assert(spinning,'recorded roulettes animate concurrently with typing');
  assert.equal(world.instance.state().phase,'roll');
  assert.equal(article.firstChild,words,'roulette animation retains the same header element');
  assert(words.textContent.startsWith(prefix));
  assert(words.textContent.length>prefix.length,'typing advances while the reels are active');
  world.instance.dispose();
});



test('a tall typewriter header follows its own pane during pending loads without moving roulettes', async () => {
  let wall=1000500;
  const world=mounted({},()=>new Promise(()=>{}),()=>wall);
  const text='The long header stays readable while recorded rolls are still loading. '.repeat(24);
  world.instance.receive(world.beat('header-loading-scroll',text));await flush();
  const stage=world.instance.element,words=world.host.querySelectorAll('.pip-system3-words')[0],rolls=world.host.querySelectorAll('.pip-system3-rolls')[0];
  stage.scrollHeight=900;stage.clientHeight=100;stage.scrollTop=19;
  words.scrollHeight=300;words.clientHeight=100;words.scrollTop=0;
  rolls.scrollTop=37;
  wall=1000600;world.step();
  assert.equal(world.instance.state().phase,'loading');
  assert.equal(words.scrollTop,200,'the word pane follows newly typed lines while decisions are pending');
  assert.equal(stage.scrollTop,19,'typing leaves the outer history position fixed');
  assert.equal(rolls.scrollTop,37,'typing leaves the roulette pane position fixed');
  world.step();
  assert.equal(words.scrollTop,200,'the word pane remains settled on the next frame');
  wall=1000800;words.scrollHeight=420;world.step();
  assert.equal(words.scrollTop,320,'additional typed lines continue following within the word pane');
  world.step();
  assert.equal(words.scrollTop,320,'following the growing header does not alternate scroll positions');
  assert.equal(stage.scrollTop,19);assert.equal(rolls.scrollTop,37);
  assert.equal(world.instance.state().phase,'loading');
  world.instance.dispose();
});

test('roulette following scrolls its own pane without moving the reply header', async () => {
  let wall=1000500;
  const world=mounted({},async()=>({rows:rows()}),()=>wall);
  world.instance.receive(world.beat('isolated-rolls','A reply types in its own fixed header. '.repeat(4)));await flush();
  const stage=world.instance.element,words=world.host.querySelectorAll('.pip-system3-words')[0],rolls=world.host.querySelectorAll('.pip-system3-rolls')[0];
  const first=world.host.querySelectorAll('.sp-rr-t')[0];
  stage.scrollTop=19;
  words.scrollHeight=40;words.clientHeight=40;words.scrollTop=0;
  rolls.scrollHeight=700;rolls.clientHeight=60;rolls.scrollTop=0;
  rolls.getBoundingClientRect=()=>({top:40,bottom:100,left:0,right:400,width:400,height:60});
  first.getBoundingClientRect=()=>({top:150-rolls.scrollTop,bottom:200-rolls.scrollTop,left:0,right:400,width:400,height:50});
  world.step();
  assert(rolls.scrollTop>0,'the active roulette is brought into its own viewport');
  assert.equal(stage.scrollTop,19,'roulette following does not scroll the message stage');
  assert.equal(words.scrollTop,0,'roulette following does not scroll the header');
  const rollScroll=rolls.scrollTop,prefix=words.textContent;
  wall=1000600;world.step();
  assert(words.textContent.length>prefix.length,'typing continues while the roulette pane follows its row');
  assert.equal(rolls.scrollTop,rollScroll,'the landed viewport does not oscillate on another frame');
  assert.equal(stage.scrollTop,19);assert.equal(words.scrollTop,0);
  world.instance.dispose();
});

test('finishing the typewriter header keeps unfinished roulettes alive', async () => {
  const world=mounted({followPlayback:false,typingSpeed:4,rollSpeed:.25},async()=>({rows:rows()}),()=>1000000);
  world.instance.receive(world.beat('header-fast','Hi'));await flush();
  for(let n=0;n<10;n++)world.step(100);
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,'Hi');
  assert.equal(world.instance.state().typed,2);
  assert.equal(world.instance.state().phase,'roll','a finished header does not finish an active reel timeline');
  assert.equal(world.instance.state().raf,true,'remaining roulette animation keeps receiving frames');
  assert.notEqual(world.instance.state().rollNow,'results');
  for(let n=0;n<200&&world.instance.state().phase!=='done';n++)world.step(100);
  assert.equal(world.instance.state().phase,'done');
  assert.equal(world.instance.state().rollNow,'results');
  assert.equal(world.instance.state().raf,false,'the completed entry stops its animation loop');
  world.instance.dispose();
});

test('mounted tile keeps the exact category and subcategory elements through typing', async () => {
  let wall=1000500;
  const world=mounted({},async()=>({rows:rows()}),()=>wall);
  world.instance.receive(world.beat('persistent','A message header stays above the same recorded roulettes. '.repeat(12)));
  await flush();world.step(100);
  const table=world.host.querySelectorAll('.sp-rr-t')[0];
  const cat=table.querySelectorAll('.sp-rr-cat')[0],sub=table.querySelectorAll('.sp-rr-sub')[0];
  const wheel=cat.querySelectorAll('.sp-rr-wheel')[0],subwheel=sub.querySelectorAll('.sp-rr-wheel')[0];
  for(let n=0;n<70&&world.instance.state().phase!=='typing';n++)world.step(100);
  assert.equal(world.instance.state().phase,'typing');
  const prefix=world.host.querySelectorAll('.pip-system3-words')[0].textContent;
  assert(prefix.length>0);
  assert.equal(world.host.querySelectorAll('.sp-rr-t')[0],table);
  assert.equal(world.host.querySelectorAll('.sp-rr-cat')[0],cat);
  assert.equal(world.host.querySelectorAll('.sp-rr-sub')[0],sub);
  assert.equal(cat.querySelectorAll('.sp-rr-wheel')[0],wheel);
  assert.equal(sub.querySelectorAll('.sp-rr-wheel')[0],subwheel);
  assert.equal(world.host.querySelectorAll('.sp-rr-line').length,0);
  assert.equal(cat.style.display,'');assert.equal(sub.style.display,'');
  wall=1001000;
  for(let n=0;n<120&&world.instance.state().phase!=='done';n++)world.step(100);
  assert.equal(world.instance.state().phase,'done');
  assert(world.host.querySelectorAll('.pip-system3-words')[0].textContent.startsWith(prefix));
  assert.equal(world.host.querySelectorAll('.sp-rr-t')[0],table);
  assert.equal(cat.querySelectorAll('.sp-rr-wheel')[0],wheel);
  world.instance.dispose();
});

function wholeMomentLoader(feed, answers) {
  const source=fs.readFileSync(path.join(__dirname,'../desktop/renderer/script-page.js'),'utf8').replace(/\r\n/g,'\n');
  const names=['mvTileData','mvHistItem','mvBaseLid','mvMomentKeys','mvMomentRows','mvRowKey','mvMerge'];
  const grab=name=>{
    const start=source.indexOf('  function '+name+'(');assert(start>=0,name);
    const lineEnd=source.indexOf('\n',start);
    const line=source.slice(start,lineEnd);
    if(line.includes(' }'))return line;
    const end=source.indexOf('\n  }\n',start);assert(end>start,name+' closes');
    return source.slice(start,end+5);
  };
  return new Function('root','mvAsk','mvMomentList','MV_MATES','mvPlain',names.map(grab).join('\n')+'\nreturn mvTileData;')(
    {PineStationFeed:{rows:()=>feed}},item=>Promise.resolve(answers[item.lid]),()=>[],3,x=>String(x||''));
}

test('whole-moment loader includes parent and stings in Digital order without duplicates or foreign turns', async () => {
  const rolled=(event,table,dice)=>({event,fam:table,table,main:{dice,label:table}});
  const emotion=rolled('es','ES1',80),clip1=rolled('p1','book',60),clip2=rolled('p2','SFX',8),guy=rolled('guy','SFXGUY',41);
  const answers={
    L:{cid:'C',tid:'T',rows:[emotion],answered:true},
    'L-punct-1':{rows:[clip1],answered:true},
    'L-punct-2':{rows:[clip2],answered:true},
    G:{cid:'C',tid:'T',rows:[emotion,guy],answered:true},
    foreign:{cid:'OTHER',tid:'T',rows:[rolled('bad','OTHER',99)],answered:true},
    U:{cid:'C',tid:'OTHER',rows:[rolled('neighbor','NEIGHBOR',1)],answered:true}
  };
  const feed=['foreign','L','L-punct-1','L-punct-2','G','U'].map(id=>({id,text:id}));
  const load=wholeMomentLoader(feed,answers);
  const parent=await load(feed[1],{rows:feed});
  const punctuation=await load(feed[3],{rows:feed});
  assert.deepEqual(parent.rows.map(r=>r.event),['es','p1','p2','guy']);
  assert.deepEqual(punctuation.rows.map(r=>r.event),['es','p1','p2','guy'],'a currently on-air sting keeps the parent first');
  assert.equal(punctuation.rows.filter(r=>r.event==='es').length,1);
  assert(!punctuation.rows.some(r=>r.event==='bad'||r.event==='neighbor'));
  const distant=[feed[1],{id:'music',music:true},feed[5],feed[5],feed[3],feed[2],feed[4]];
  const distantLoad=wholeMomentLoader(distant,answers);
  assert.deepEqual((await distantLoad(distant[4],{rows:distant})).rows.map(r=>r.event),['es','p1','p2','guy'],
    'an inline sting finds its base parent even beyond the adjacent window');
});

test('same on-air ID accepts corrected equal-length and shorter message text', async () => {
  const world=mounted({},async()=>({rows:[]}),()=>1001000);
  world.instance.receive(world.beat('corrected','abcdef'));await flush();
  for(let n=0;n<10;n++)world.step();
  assert.equal(world.instance.state().phase,'done');
  world.instance.receive(world.beat('corrected','ZYXWVU'));
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,'ZYXWVU');
  world.instance.receive(world.beat('corrected','Hi'));
  world.step();
  assert.equal(world.instance.state().typed,2);
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,'Hi');
  assert.equal(world.host.querySelectorAll('.pip-system3-message').length,1);
  world.instance.dispose();
});


test('intrinsic layout notifications measure growing contents behind a capped viewport', async () => {
  const layouts=[];
  const world=mounted({},async()=>({rows:[]}),()=>1001000,info=>layouts.push(info));
  const stage=world.instance.element;
  stage.offsetWidth=200;stage.scrollWidth=200;stage.offsetHeight=120;stage.scrollHeight=900;
  world.instance.receive(world.beat('measured'));await flush();world.step();world.step();
  assert.equal(world.instance.measure().width,200);
  assert.equal(world.instance.measure().height,900,'measurement includes full scrollable content beyond the viewport');
  assert.equal(layouts.at(-1).height,900);
  assert.equal(layouts.at(-1).current,'measured');
  assert.equal(layouts.at(-1).item,world.host.querySelectorAll('.pip-system3-message')[0]);
  const before=layouts.length;world.instance.requestLayout();world.step();
  assert.equal(layouts.length,before,'unchanged geometry does not trigger repeated host resizing');
  stage.offsetHeight=120;stage.scrollHeight=120;world.instance.requestLayout();world.step();
  assert.equal(layouts.at(-1).height,120,'host receives shorter intrinsic content immediately');
  world.instance.dispose();assert.equal(world.frames.size,0,'disposal cancels layout and animation callbacks');
});

test('Digital late moment joins keep the original sheet and typed prefix', t => {
  let wall=10000;t.mock.method(Date,'now',()=>wall);
  const source=fs.readFileSync(path.join(__dirname,'../desktop/renderer/script-page.js'),'utf8').replace(/\r\n/g,'\n');
  const start=source.indexOf('  function mvTurnJoin('),end=source.indexOf('\n  }\n',start);
  assert(start>=0&&end>start);
  const r=renderer(),sheet=r.sheet({},rows(),6000);r.at(sheet,sheet.total);
  const host={item:{kind:'speech',lid:'L'},style:'digital',sheet,data:{rows:rows()},node:make('section'),rolls:make('div'),all:make('div'),text:make('span','','The prefix already typed'),typed:24,phase:'air'};
  host.node.connected=true;host.rolls.appendChild(sheet.box);
  const before=[...sheet.tables],beforeNodes=[...sheet.box.children],callbacks=[];
  const child=id=>({item:{kind:'clip',lid:id},node:make('section'),all:make('div')});
  const mv={cur:null};
  const env={mv,root:{requestAnimationFrame:fn=>callbacks.push(fn)},mvRowKey:r=>r.event||r.table,mvStatic:()=>make('button'),make,
    mvPlan:(cur,data)=>cur.data=data,mvRrSheet:r.sheet,mvRrAppend:r.append,mvRrAt:r.at,mvRrResults:r.results,mvRrReserve:r.reserve,feedDiceOpen(){}};
  const join=new Function(...Object.keys(env),source.slice(start,end+5)+'\nreturn mvTurnJoin;')(...Object.values(env));
  const moment={rows:host.data.rows.slice()},a=child('L-p1'),b=child('L-p2');
  join(host,a,{rows:[{fam:'SFX',table:'book',event:'p1',main:reel(60,['other','sample A'],1)}]},moment);
  assert.equal(host.sheet,sheet);before.forEach((table,index)=>assert.equal(sheet.tables[index],table));
  assert.deepEqual(sheet.box.children.slice(0,beforeNodes.length),beforeNodes);
  assert.equal(host.text.textContent,'The prefix already typed');assert.equal(host.typed,24);
  assert.equal(callbacks.length,1);
  wall+=100;
  join(host,b,{rows:[{fam:'SFX',table:'clip',event:'p2',main:reel(71,['other','sample B'],1)}]},moment);
  assert.equal(host.sheet,sheet);assert.equal(sheet.tables.length,4);
  assert.equal(host.text.textContent,'The prefix already typed');
  const pending=callbacks.length;callbacks[0]();
  assert.equal(callbacks.length,pending,'a replaced append clock cannot schedule another frame');
  wall+=100000;callbacks[1]();
  assert.equal(host.joinRollingSheet,null);
  assert.equal(sheet.now,'results');assert.equal(host.text.textContent,'The prefix already typed');
  assert.equal(sheet.box.querySelectorAll('.sp-rr-line').length,0);
});

test('one shared parser retains recorded stage numbers, counted pools, and rejection metadata', () => {
  const emotion={event_id:'emotion',family:'ES',selected:{table:'ES1',label:'uncertainty',material:{book:'B'},prompt_row:'row',prompt:'words',in_prompt:true},stages:[
    {stage:'table',selected:'ES1',candidates:[{id:'ES1',label:'Emotion Set 1'}]},
    {stage:'category',selected:'interest',draw:{dice:80},candidates:[{id:'joy',label:'JOY',weight:1},{id:'interest',label:'INTEREST',weight:3}],excluded:[{id:'anger',label:'ANGER',why:'already used'}]},
    {stage:'item',selected:'uncertain',draw:{dice:95},candidates:[{id:'certain',label:'certainty'},{id:'uncertain',label:'uncertainty'}]},
    {stage:'rule',verdicts:[{id:'old',label:'old reaction',eligible:false,why:'repeat'}]}
  ]};
  const response={event_id:'response',family:'RS',selected:{table:'RS1',label:'Opposite'},stages:[{stage:'item',selected:'opposite',draw:{dice:13},candidates:[{id:'agree',label:'Agree'},{id:'opposite',label:'Opposite'}]}]};
  const result=tile.decisionRows([response,{family:'RULE',selected:{id:'forced'},stages:[]},emotion]);
  assert.deepEqual(result.map(row=>row.event),['emotion','response']);
  assert.equal(result[0].tableLabel,'Emotion Set 1');
  assert.deepEqual(result[0].main.opts,['JOY','INTEREST']);assert.deepEqual(result[0].main.weights,[1,3]);
  assert.equal(result[0].main.dice,80);assert.equal(result[0].main.hit,1);
  assert.equal(result[0].sub.dice,95);assert.equal(result[0].sub.label,'uncertainty');
  assert.deepEqual(result[0].main.rej,[{label:'ANGER',why:'rejected: already used'}]);
  assert.deepEqual(result[0].vrej,[{label:'old reaction',why:'not eligible: repeat'}]);
  assert.deepEqual(result[0].material,{book:'B'});assert.deepEqual(result[0].prompt,{words:'words',row:'row',used:true});
  const counted=tile.countedRow('SFX','book',{dice:60,label:'dachamp',index:41,of:100},{dice:1,label:'01 Ladies and',index:27,of:3309},
    {event:'clip',match:{score:.9,removed:{recent:2},candidates:[{folder:'other',score:.2}]},prompt:{words:'used'}});
  assert.equal(counted.main.counted,true);assert.equal(counted.main.index,41);assert.equal(counted.main.of,100);
  assert.equal(counted.sub.index,27);assert.equal(counted.sub.of,3309);
  assert.deepEqual(counted.sub.opts,['01 Ladies and'],'counted pool does not fabricate unavailable candidates');
  assert.match(counted.sub.rej[0].why,/recent/);assert.match(counted.sub.rej[1].why,/lost: scored 0.20/);
  assert.equal(counted.event,'clip');assert.equal(counted.prompt.words,'used');
  assert.match(tile.decisionRow({family:'SFX',selected:{id:'PASS',label:'no clip'},stages:[{stage:'dice',threshold:.4,draw:{dice:8},selected:'PASS'}]}).failed.why,/no clip.*rolled 8/);
});

test('explicit replay resets timing state while reusing every original reel node', () => {
  const r=renderer(),sheet=r.sheet({},rows(),6000);r.at(sheet,sheet.total);
  const tables=[...sheet.tables],children=[...sheet.box.children],rowData=sheet.rows;
  const steps=tables.flatMap(t=>[t.cat,t.sub].filter(Boolean)),nodes=steps.map(step=>[step.el,step.wheel,step.list,step.die,step.of]);
  const schedule=tables.map(table=>[table.at,table.end,table.dSpin]);
  r.reset(sheet);
  assert.equal(sheet.rows,rowData);assert.equal(sheet.elapsed,0);assert.equal(sheet.now,'');
  assert.deepEqual(sheet.box.children,children);assert.deepEqual(tables.map(table=>[table.at,table.end,table.dSpin]),schedule);
  steps.forEach((step,index)=>{
    assert.deepEqual([step.el,step.wheel,step.list,step.die,step.of],nodes[index]);
    assert.equal(step.die.textContent,'#');assert.equal(step.el.style.display,'none');
    assert.equal(step.of.style.visibility,'hidden');assert.equal(step.list.style.transform,'');
  });
  assert.equal(r.at(sheet,tables[0].dIn+1),'0:cat-die');
  r.at(sheet,sheet.total);
  tables.forEach((table,index)=>assert.equal(sheet.tables[index],table));
  assert.equal(sheet.box.querySelectorAll('.sp-rr-line').length,0);
});

test('same on-air message appends late material without rebuilding rows, polling clock ticks, or accepting stale refreshes', async () => {
  let wall=1000500,calls=0,pending;
  const initial=rows();
  const world=mounted({},row=>{
    calls++;
    if(calls===1)return Promise.resolve({rows:initial});
    if(row.id==='next')return Promise.resolve({rows:[]});
    return new Promise(resolve=>pending=resolve);
  },()=>wall);
  const text='A typed header stays above completed rows while new moment material arrives. '.repeat(8);
  const base={...world.beat('L',text),rows:[{id:'L'}]};
  world.instance.receive(base);await flush();
  for(let n=0;n<80&&world.instance.state().phase!=='typing';n++)world.step(100);
  world.step(100);
  const prefix=world.host.querySelectorAll('.pip-system3-words')[0].textContent,original=world.host.querySelectorAll('.sp-rr-t').slice();
  assert(prefix.length>0);
  world.instance.receive({...base,station:{stream_now:{at:1000},paused:false}});await flush();
  assert.equal(calls,1,'stream clocks and ordinary status updates do not reload recorded decisions');
  const fresh={fam:'SFX',table:'book',event:'clip',main:reel(60,['other','sample'],1)};
  const roster={...base,rows:[{id:'L'},{id:'L-punct-1',sfx_roll:{category:{dice:60}}}]};
  world.instance.receive(roster);await flush();assert.equal(calls,2);
  // More material arriving during the first read is coalesced into the next read.
  const newest={...roster,rows:roster.rows.concat({id:'L-punct-2',sfx_roll:{clip:{dice:71}}})};
  world.instance.receive(newest);await flush();assert.equal(calls,2);
  pending({rows:initial.concat(fresh,fresh)});await flush();
  assert.equal(world.instance.state().rows,3,'duplicate rows from the refreshed answer append once');
  assert.equal(world.instance.state().phase,'roll');
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,prefix);
  original.forEach((element,index)=>assert.equal(world.host.querySelectorAll('.sp-rr-t')[index],element));
  assert.equal(calls,3,'a changing roster during the read triggers one follow-up snapshot');
  const stale=pending;
  world.instance.receive(world.beat('next','x'));await flush();world.step();
  stale({rows:initial.concat(fresh,{fam:'SFX',table:'late',main:reel(71,['late'],0)})});await flush();world.step();
  assert.equal(world.instance.state().current,'next');assert.equal(world.instance.state().rows,0);
  assert.equal(world.host.querySelectorAll('.pip-system3-message').length,1);
  world.instance.dispose();
});

test('hover hold retains the message and its playback timeline, then resumes the latest message', async () => {
  let wall=1001000;const loaded=[];
  const world=mounted({},async row=>{loaded.push(row.id);return {rows:rows()};},()=>wall);
  const first=world.beat('hover-a','abcdefghijklmnopqrstuvwxyz'.repeat(12));first.now.until=4;
  world.instance.receive(first);await flush();
  for(let n=0;n<80&&world.instance.state().phase!=='typing';n++)world.step(100);
  assert.equal(world.instance.state().phase,'typing');
  const original=world.host.querySelectorAll('.pip-system3-message')[0];
  const reels=world.host.querySelectorAll('.sp-rr-t');
  world.instance.hold(true);
  const next=world.beat('hover-b','next'),latest=world.beat('hover-c','latest');
  next.station.stream_now.at=2000;latest.station.stream_now.at=3000;
  world.instance.receive(next);world.instance.receive(latest);await flush();
  const heldTyped=world.instance.state().typed;
  wall=1002000;world.step();world.step();
  assert.equal(world.instance.state().current,'hover-a');assert.equal(world.instance.state().held,true);
  assert.equal(world.instance.state().playbackFraction,.5,'new broadcast anchors do not retime the held message');
  assert(world.instance.state().typed>heldTyped,'steady typing continues on the held message');
  assert.equal(world.host.querySelectorAll('.pip-system3-message')[0],original);
  reels.forEach((node,index)=>assert.equal(world.host.querySelectorAll('.sp-rr-t')[index],node));
  assert(!loaded.includes('hover-b')&&!loaded.includes('hover-c'),'replacement messages are not loaded while held');
  world.instance.hold(false);
  assert.equal(world.instance.state().current,'hover-c','mouse exit resumes the latest on-air ID immediately');
  await flush();assert(loaded.includes('hover-c'));assert(!loaded.includes('hover-b'));
  assert.equal(world.instance.state().held,false);
  world.instance.dispose();assert.equal(world.frames.size,0);
});

test('hover hold protects a completed message from fade and clears when hidden', async t => {
  let wall=1001000;t.mock.method(Date,'now',()=>wall);
  const world=mounted({mode:'fade',fadeDelay:1},async()=>({rows:[]}),()=>wall);
  world.instance.receive(world.beat('hover-fade'));await flush();world.step();
  world.instance.hold(true);wall+=100000;world.step();
  assert.equal(world.instance.state().visible,true,'the hovered result remains visible beyond the fade timeout');
  assert.equal(world.instance.state().raf,false,'a completed held result does not need an idle frame loop');
  world.instance.receive(world.beat('queued'));await flush();
  assert.equal(world.instance.state().current,'hover-fade');
  world.instance.visible(false);assert.equal(world.instance.state().held,false);
  world.instance.visible(true);await flush();
  assert.equal(world.instance.state().current,'queued','reopening does not retain an old hover lock');
  world.instance.dispose();
});

test('hover hold lets the current async load finish and discards it after release', async () => {
  const pending=new Map();
  const world=mounted({},row=>new Promise(resolve=>pending.set(row.id,resolve)),()=>1001000);
  world.instance.receive(world.beat('loading-held'));await flush();world.instance.hold(true);
  const queued=world.beat('loading-next');queued.rows=[queued.now];world.instance.receive(queued);await flush();
  assert.equal(world.instance.state().current,'loading-held');assert(!pending.has('loading-next'));
  pending.get('loading-held')({rows:rows()});await flush();
  assert.equal(world.instance.state().rows,2);assert.equal(world.instance.state().phase,'roll');
  const stale=pending.get('loading-held');world.instance.hold(false);await flush();
  pending.get('loading-next')({rows:[]});await flush();stale({rows:rows()});await flush();
  assert.equal(world.instance.state().current,'loading-next');assert.equal(world.instance.state().rows,0);
  world.instance.dispose();
});

test('web Messenger, desktop tools, and Android ship identical shared tile assets', () => {
  const workspace=path.resolve(__dirname,'..');
  for(const name of ['system3-message-tile.js','system3-message-tile.css']){
    const canonical=fs.readFileSync(path.join(workspace,'desktop/renderer',name));
    for(const dir of ['frontend','desktop/station-tools','app/src/main/assets/pine-views']){
      assert(fs.readFileSync(path.join(workspace,dir,name)).equals(canonical),dir+'/'+name+' must carry the canonical renderer');
    }
  }
  for(const name of ['system3.js','system3.css']){
    assert(fs.readFileSync(path.join(workspace,'desktop/station-tools',name)).equals(fs.readFileSync(path.join(workspace,'frontend',name))),name+' desktop tool bundle must match web Messenger');
  }
  const messenger=fs.readFileSync(path.join(workspace,'frontend/system3.js'),'utf8');
  assert.match(messenger,/import ['"]\.\/system3-message-tile\.js['"]/);
  assert.match(fs.readFileSync(path.join(workspace,'frontend/system3.css'),'utf8'),/@import ['"]\.\/system3-message-tile\.css['"]/);
});

const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
const pointer = (host, type) => host.dispatchEvent({type, pointerType:'mouse', clientX:25, clientY:25});
const pastRow = (id, text = id) => ({id, text, from:0, until:1, lcdStatus:'Played'});
const reviewSnapshot = host => descendants(host).map(element => ({
  element, children:[...element.children], text:element._text, style:{...element.style}, hidden:element.hidden
}));
function assertReviewUnchanged(host, saved) {
  const current=descendants(host);
  // Navigation metadata may change as fresh messages arrive; the selected article stays fixed.
  const articles=saved.filter(item=>item.element.classList.contains('pip-system3-message')).map(item=>item.element);
  for(const item of saved){
    if(!articles.some(article=>article.contains(item.element)))continue;
    assert(current.includes(item.element),'reviewing never rebuilds the selected message elements');
    assert.deepEqual(item.element.children,item.children);
    assert.equal(item.element._text,item.text,'incoming corrections cannot rewrite words under the reader');
    assert.deepEqual({...item.element.style},item.style);
    assert.equal(item.element.hidden,item.hidden);
  }
}

test('review arrows browse earlier recorded messages and expose both navigation boundaries', async () => {
  const loaded=[];
  const world=mounted({},async row=>{loaded.push(row.id);return {rows:rows()};},()=>1001000);
  const a=pastRow('review-a','First recorded reply'),b=pastRow('review-b','Second recorded reply');
  const live={...pastRow('review-live','Latest reply'),lcdStatus:'Playing'};
  const future={...pastRow('review-future'),lcdStatus:'Upcoming'};
  world.instance.receive({now:live,rows:[a,{...pastRow('music'),music:true},b,live,future],station:{stream_now:{at:1000}}});
  await flush();
  assert.equal(world.instance.state().navigation.total,3,'music and upcoming replies are outside review history');
  assert.equal(world.instance.state().navigation.canPrevious,true);
  assert.equal(world.instance.state().navigation.canNext,false);
  const buttons=descendants(world.host).filter(element=>element.tagName==='BUTTON');
  const previous=buttons.find(button=>/previous/i.test(button.getAttribute('aria-label')||''));
  const next=buttons.find(button=>/next/i.test(button.getAttribute('aria-label')||''));
  assert(previous&&next,'both arrows have accessible names');
  assert.equal(previous.disabled,false);assert.equal(next.disabled,true);
  previous.dispatchEvent({type:'click'});await flush();
  assert.equal(world.instance.state().current,'review-b');
  assert.equal(world.instance.state().reviewing,true);
  assert.equal(world.instance.state().phase,'done','historical replies settle immediately for reading');
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,b.text);
  assert.equal(world.host.querySelectorAll('.sp-rr-t').length,2);
  assert.equal(world.host.querySelectorAll('.sp-rr-die')[0].textContent,'80');
  world.instance.previous();await flush();
  assert.equal(world.instance.state().current,'review-a');
  assert.equal(world.instance.state().navigation.canPrevious,false);
  assert.equal(previous.disabled,true);assert.equal(next.disabled,false);
  world.instance.previous();await flush();assert.equal(world.instance.state().current,'review-a');
  next.dispatchEvent({type:'click'});await flush();assert.equal(world.instance.state().current,'review-b');
  world.instance.next();await flush();assert.equal(world.instance.state().current,'review-live');
  assert.equal(world.instance.state().navigation.canNext,false);
  world.instance.next();assert.equal(world.instance.state().current,'review-live');
  assert(!loaded.includes('music')&&!loaded.includes('review-future'));
  world.instance.dispose();assert.equal(world.frames.size,0);
});

test('review keeps selected words, roulette elements and scroll position fixed until pointer exit', async () => {
  const loaded=[];let wall=1001000;
  const world=mounted({},async row=>{loaded.push(row.id);return {rows:rows()};},()=>wall);
  const a=pastRow('pin-a','A previous message that must remain readable. '.repeat(8));
  const b={...pastRow('pin-b','Latest before review'),lcdStatus:'Playing'};
  world.instance.receive({now:b,rows:[a,b],station:{stream_now:{at:1000}}});await flush();
  pointer(world.host,'pointerenter');world.instance.previous();await flush();world.step();
  assert.equal(world.instance.state().current,'pin-a');assert.equal(world.instance.state().reviewing,true);
  const stage=world.instance.element;stage.scrollHeight=900;stage.clientHeight=120;stage.scrollTop=137;
  const saved=reviewSnapshot(world.host),typed=world.instance.state().typed;
  const corrected={...a,text:'An incoming correction should not replace the words being reviewed.',sfx_roll:{category:{dice:60}}};
  const c={...pastRow('pin-c','New reply arriving during review'),lcdStatus:'Playing'};
  world.instance.receive({now:c,rows:[corrected,b,c],station:{stream_now:{at:2000}}});await flush();
  wall+=10000;for(let n=0;n<20;n++)world.step(100);
  assert.equal(world.instance.state().current,'pin-a');assert.equal(world.instance.state().typed,typed);
  assert.equal(stage.scrollTop,137,'automatic scrolling cannot move the historical reply');
  assertReviewUnchanged(world.host,saved);
  assert(!loaded.includes('pin-c'),'new live replies wait until review ends');
  pointer(world.host,'pointerleave');await flush();
  assert.equal(world.instance.state().current,'pin-c','mouse exit resumes the most recent received reply');
  assert.equal(world.instance.state().reviewing,false);assert.equal(world.instance.state().held,false);
  assert(loaded.includes('pin-c'));
  world.instance.dispose();
});

test('a missing historical load settles once without replay and stale live data cannot replace it', async () => {
  const pending=new Map();
  const world=mounted({},row=>new Promise(resolve=>pending.set(row.id,resolve)),()=>1001000);
  const a=pastRow('async-history','The whole historical reply is immediately readable.');
  const live={...pastRow('async-live','Live reply'),lcdStatus:'Playing'};
  world.instance.receive({now:live,rows:[a,live],station:{stream_now:{at:1000}}});await flush();
  world.instance.previous();await flush();
  assert.equal(world.instance.state().current,'async-history');assert.equal(world.instance.state().phase,'loading');
  const c={...pastRow('async-new','New live reply'),lcdStatus:'Playing'};
  world.instance.receive({now:c,rows:[a,live,c],station:{stream_now:{at:2000}}});
  pending.get('async-history')({rows:rows()});await flush();world.step();
  assert.equal(world.instance.state().phase,'done');assert.equal(world.instance.state().typed,a.text.length);
  const saved=reviewSnapshot(world.host);
  pending.get('async-live')({rows:[{fam:'SFX',table:'stale',main:reel(71,['Stale live result'],0)}]});
  await flush();for(let n=0;n<12;n++)world.step(100);
  assert.equal(world.instance.state().current,'async-history');assert.equal(world.instance.state().rows,2);
  assert.equal(world.instance.state().raf,false,'historical reading has no animation loop');
  assertReviewUnchanged(world.host,saved);
  pointer(world.host,'pointerleave');await flush();assert.equal(world.instance.state().current,'async-new');
  world.instance.dispose();assert.equal(world.frames.size,0);
});

test('navigation roster stays bounded while preserving a selected old message through pruning', async () => {
  const world=mounted({},async()=>({rows:[]}),()=>1001000);
  const recorded=Array.from({length:160},(_,index)=>pastRow('bounded-'+index));
  recorded.at(-1).lcdStatus='Playing';
  world.instance.receive({now:recorded.at(-1),rows:recorded,station:{stream_now:{at:1000}}});await flush();
  assert.equal(world.instance.state().navigation.total,100);
  assert.equal(world.instance.state().navigation.index,99);
  for(let index=0;index<99;index++)world.instance.previous();
  await flush();assert.equal(world.instance.state().current,'bounded-60');
  assert.equal(world.instance.state().navigation.canPrevious,false);
  const pinned=world.host.querySelectorAll('.pip-system3-message')[0];
  const newer=Array.from({length:160},(_,index)=>pastRow('bounded-'+(index+160)));newer.at(-1).lcdStatus='Playing';
  world.instance.receive({now:newer.at(-1),rows:newer,station:{stream_now:{at:2000}}});await flush();
  assert.equal(world.instance.state().current,'bounded-60','pruning never ejects the reply being read');
  assert.equal(world.host.querySelectorAll('.pip-system3-message')[0],pinned);
  assert.equal(world.instance.state().navigation.total,100);
  pointer(world.host,'pointerleave');await flush();
  assert.equal(world.instance.state().current,'bounded-319');assert.equal(world.instance.state().reviewing,false);
  assert.equal(world.instance.state().navigation.canNext,false);
  world.instance.dispose();
});
test('revisiting a reviewed reply preserves its exact elements and reading scroll position', async () => {
  const loads=new Map();
  const world=mounted({},async row=>{loads.set(row.id,(loads.get(row.id)||0)+1);return {rows:rows()};},()=>1001000);
  const a=pastRow('return-a','Earlier reply'),b=pastRow('return-b','The long reply being read. '.repeat(12));
  const live={...pastRow('return-live','Current reply'),lcdStatus:'Playing'};
  world.instance.receive({now:live,rows:[a,b,live],station:{stream_now:{at:1000}}});await flush();
  world.instance.previous();await flush();
  const article=world.host.querySelectorAll('.pip-system3-message')[0],reels=article.querySelectorAll('.sp-rr-t');
  const words=article.querySelectorAll('.pip-system3-words')[0],rolls=article.querySelectorAll('.pip-system3-rolls')[0];
  words.scrollTop=61;rolls.scrollTop=79;
  world.instance.element.scrollHeight=900;world.instance.element.clientHeight=120;world.instance.element.scrollTop=137;
  world.instance.previous();await flush();assert.equal(world.instance.state().current,'return-a');
  world.instance.next();await flush();assert.equal(world.instance.state().current,'return-b');
  assert.equal(world.host.querySelectorAll('.pip-system3-message')[0],article,'back/forward reuses the reviewed message');
  reels.forEach((reel,index)=>assert.equal(article.querySelectorAll('.sp-rr-t')[index],reel));
  assert.equal(world.instance.element.scrollTop,137,'back/forward restores where the reader had scrolled');
  assert.equal(words.scrollTop,61,'back/forward restores the independent reply reading position');
  assert.equal(rolls.scrollTop,79,'back/forward restores the independent roulette reading position');
  assert.equal(loads.get('return-b'),1,'visiting a recorded reply again does not reload its settled data');
  world.instance.dispose();
});
test('returning to a message whose first load is unfinished starts a fresh request and rejects stale data', async () => {
  const requests=new Map();
  const world=mounted({},row=>new Promise(resolve=>{
    const attempts=requests.get(row.id)||[];attempts.push(resolve);requests.set(row.id,attempts);
  }),()=>1001000);
  const older=pastRow('unfinished-old','Earlier reply');
  const live={...pastRow('unfinished-live','The current reply being loaded'),lcdStatus:'Playing'};
  world.instance.receive({now:live,rows:[older,live],station:{stream_now:{at:1000}}});await flush();
  assert.equal(requests.get('unfinished-live').length,1);
  world.instance.previous();await flush();assert.equal(requests.get('unfinished-old').length,1);
  world.instance.next();await flush();
  assert.equal(world.instance.state().current,'unfinished-live');
  assert.equal(requests.get('unfinished-live').length,2,'unfinished cards cannot restore an abandoned loading promise');
  const stale={fam:'SFX',table:'stale',main:reel(71,['Stale result'],0)};
  requests.get('unfinished-live')[0]({rows:[stale]});
  requests.get('unfinished-old')[0]({rows:[stale]});
  await flush();world.step();
  assert.equal(world.instance.state().phase,'loading');
  assert.equal(world.instance.state().rows,0,'original requests cannot populate a replacement card');
  assert.equal(world.instance.state().typed,0);
  requests.get('unfinished-live')[1]({rows:rows()});await flush();world.step();
  assert.equal(world.instance.state().phase,'done');
  assert.equal(world.instance.state().rows,2);
  assert.equal(world.host.querySelectorAll('.pip-system3-words')[0].textContent,live.text);
  assert.equal(world.host.querySelectorAll('.sp-rr-die')[0].textContent,'80');
  world.instance.dispose();assert.equal(world.frames.size,0);
});

test('an open roulette inspector retains the reviewed reply after mouse exit until the inspector closes', async () => {
  let popup=null,observer;
  const outside=new Element('div');
  const loaded=[];
  const world=mounted({},async row=>{loaded.push(row.id);return {rows:rows()};},()=>1001000,undefined,({view,doc})=>{
    doc.body=new Element('body');
    doc.getElementById=id=>id==='spRrPop'?popup:null;
    doc.elementFromPoint=()=>outside;
    view.MutationObserver=class {
      constructor(callback) { this.callback=callback;observer=this; }
      observe() { this.observing=true; }
      disconnect() { this.observing=false; }
      fire() { this.callback(); }
    };
  });
  const older=pastRow('inspector-old','The reply being inspected'),live={...pastRow('inspector-live'),lcdStatus:'Playing'};
  world.instance.receive({now:live,rows:[older,live],station:{stream_now:{at:1000}}});await flush();
  pointer(world.host,'pointerenter');world.instance.previous();await flush();
  popup=new Element('aside');
  world.host.querySelectorAll('.sp-rr-cat')[0].dispatchEvent({type:'click'});
  assert.equal(world.instance.state().inspecting,true);
  assert.equal(popup.__system3MessageOwner,world.instance.element);
  const saved=reviewSnapshot(world.host);
  const newest={...pastRow('inspector-newest','The newest reply'),lcdStatus:'Playing'};
  world.instance.receive({now:newest,rows:[older,live,newest],station:{stream_now:{at:2000}}});
  pointer(world.host,'pointerleave');await flush();world.step();
  assert.equal(world.instance.state().current,'inspector-old','mouse exit waits for the owned inspector');
  assert.equal(world.instance.state().reviewing,true);assert.equal(world.instance.state().held,true);
  assertReviewUnchanged(world.host,saved);
  assert(!loaded.includes('inspector-newest'));
  popup=null;observer.fire();await flush();
  assert.equal(world.instance.state().current,'inspector-newest','closing the inspector resumes the latest reply outside the tile');
  assert.equal(world.instance.state().reviewing,false);assert.equal(world.instance.state().held,false);
  assert.equal(world.instance.state().inspecting,false);
  world.instance.dispose();assert.equal(observer.observing,false);
});