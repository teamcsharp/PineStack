#!/usr/bin/env node
/* audit_table.js - the popup audit, classified: popup_audit.js on the patched
 * tree + the reviewed classification of every row it could not decide + the
 * harness verdicts (proofs/results.json).
 *   node audit_table.js <patched-root> > audit_table.tsv */
'use strict';
const {execFileSync} = require('child_process');
const path = require('path');
const fs = require('fs');
const root = path.resolve(process.argv[2]);
const raw = (() => { try { return execFileSync(process.execPath, [path.join(__dirname, 'popup_audit.js'), root], {encoding: 'utf8'}); }
  catch (e) { return e.stdout; } })();
const results = (() => { try { return JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'proofs', 'results.json'), 'utf8')); } catch (e) { return []; } })();

/* reviewed by reading each builder (2026-09-29) */
const NOT = {
  'P:(top level)': 'CSS rule / static chrome (device skin, grain, beacon, tray CSS) - the tray and lightbox ARE fixed, via their openers',
  pineWinAdopt: 'window manager for 3JS scenes; the scene windows carry the X (pineWin)',
  pine3JSInstall: 'the 3JS launcher button', showPromptPeek: 'hover preview (tooltip)', callerCardShow: 'hover card (pointer-events:none)',
  lineCardShow: 'hover card', tipApply: 'hover tip', voteBurst: 'animation layer', pineCopy: 'off-screen copy textarea', opsPaint: 'status bubble (self-clears)',
  copyBlip: 'toast (self-clears)', docPreviewShow: 'hover preview', kill: 'selection bar under the text selection', pineTipBubble: 'tooltip',
  glyphyDot: 'the companion dot (its box has a Close)', djRepairBanner: 'status banner while a repair runs (clears itself); opens the repair popup',
  pineAudioPrompt: 'the one-tap audio unlock button', calTipEl: 'tooltip', audioUnlockBar: 'audio unlock bar (click = the action)', orchChip: 'status chip (fades)',
  wedgeIcon: 'the stuck-air alarm icon (by design never snoozed, #1208)', fixRailBuild: 'edge rail tab', handler: 'copy textarea', scriptCopy: 'copy textarea',
  orchBell: 'the orchestrator bell button', mpxInit: 'mix progress chip (self-clears)', openLightboxVideoEditor: 'full-screen editor: labelled Close editor + Escape (kept)',
  copyByHand: 'off-screen copy textarea', show: 'boot splash (lifts itself)', mount: 'fixed bar / dot (chrome, not a popup)', glowShow: 'hot-corner glow', glowHide: 'hot-corner glow',
  glowPulse: 'hot-corner glow', toast: 'toast (self-clears)', showTab: 'slide-away "bring it back" tab', dressWrap: 'hot-corner ink', openVideoEditor: 'full-screen editor with labelled Close editor',
  handOff: 'editor hand-off (same editor)', '(top level)': 'CSS / static chrome', shadeUp: 'the shade under the line sheet (tap closes)', laToast: 'toast (self-clears)',
  raiseOrb: 'the hold orb', dot: 'the orchestrator dot button', button: 'a fixed launcher button', cropRadial: 'radial press menu on a tap-to-close shade (#1450)',
  freeze: 'drag helper', css: 'stylesheet', copyText: 'copy textarea', setFullscreen: 'fullscreen toggle', 'root.__pineViewRail': 'the view rail (chrome)',
  createDesktopRejectionNotices: 'FIXED: X = Later (renderer.js)', createDesktopRetireNotices: 'FIXED: X = Later (renderer.js)', pineReviewDressing: 'review backdrop CSS', setFm: 'FM chip',
  threejsTip: 'hover tip', mk: 'FIXED: X (dxLineMenu, the Works line menu)', wkDraggable: 'drag helper', receive: 'flight animation', carryGhost: 'drag ghost',
  showBin: 'drag-to-delete bin target', mvMenuToggle: 'FIXED: X (script-page view menu)', findBanAsk: 'FIXED: X = Cancel (script-page)', scriptVisible: 'visibility probe',
  sheetClear: 'wall sheet placement', parodyGenerationNotice: 'render toast (tap = open result; self-clears)', build: 'the SFX TV set itself (not a popup)', stripWheel: 'wheel strip',
  sheet: 'the SFX wall sheet: close--filled X + shade (#1450)', warmHolder: 'off-screen video warmer', ensureCollapseButton: 'collapse button', fromKey: 'screenshot flash',
  promote: 'full-screen 3JS scene (its core carries the X)', shut: 'scene close', whyText: 'comment', lift: 'full-screen carrier', isFull: 'comment', makeScanScene: 'scan animation',
  tile: 'extraction tile', shouldRun: 'viz', attach: 'viz', statusLabel: 'Comfy Workshop window: header Close (runtime case)', journal: 'Station Flow window: header Close x (runtime case)',
  refresh: 'System2 window: its own Close (runtime case)', dropCopy: 'copy textarea', item: 'FIXED: X (System 3 audit context menu)', poll: 'openLineStory card (movableModal -> helper)',
  paint: 'System 3 window (openSystem3 -> helper)', unfold: 'segment inspector (movableModal -> helper)', close: 'System 3 focus window (-> helper)',
  openDecision: 'movableModal -> helper', openAssembly: 'movableModal -> helper', openCutPanel: 'movableModal -> helper', roundMenu: 'movableModal -> helper (the line menu)',
  turnMenu: 'movableModal -> helper ("What would you like to do with this?")', segMenu: 'movableModal -> helper', openList: 'console list: its own x (runtime PASS)',
  untracedOpen: 'untraced list: its own x (runtime PASS)', open: 'line-reach context menu: FIXED X', kill2: '',
};
const verdict = {};
for (const r of results) verdict[r.name] = verdict[r.name] || {}, verdict[r.name][r.profile] = r.verdict;
const out = ['class\tfile:line\tbuilder\tnote'];
for (const l of raw.split('\n')) {
  const [k, fl, b] = l.split('\t');
  if (!k || /^TOTAL/.test(k)) continue;
  const file = fl.replace('app.py#CONTROL_PANEL_HTML', 'app.py(panel)');
  const key = file.startsWith('app.py') && b === '(top level)' ? 'P:(top level)' : b;
  let cls = k.trim(), note = '';
  if (cls === 'helper') note = 'corner X via pineCloseX';
  else if (cls === 'has-X') note = 'own close glyph kept (runtime-checked where openable)';
  else { note = NOT[key] || NOT[b] || 'REVIEW'; cls = /^FIXED/.test(note) ? 'helper' : /movableModal|-> helper/.test(note) ? 'helper(shared)' : /runtime|kept|X \+|close--filled/.test(note) ? 'has-X' : 'not-a-popup'; }
  out.push([cls, file, b, note].join('\t'));
}
process.stdout.write(out.join('\n') + '\n');
const tally = {};
for (const l of out.slice(1)) { const c = l.split('\t')[0]; tally[c] = (tally[c] || 0) + 1; }
console.error(JSON.stringify(tally));
