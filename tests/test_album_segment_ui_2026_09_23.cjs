const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const renderer = path.join(__dirname, '..', 'desktop', 'renderer');
const album = fs.readFileSync(path.join(renderer, 'album-popup.js'), 'utf8');
const script = fs.readFileSync(path.join(renderer, 'script-page.js'), 'utf8');
const deep = fs.readFileSync(path.join(renderer, 'line-deep.js'), 'utf8');
const css = fs.readFileSync(path.join(renderer, 'script-page.css'), 'utf8');

test('the playing sleeve opens the canonical album and track desk', () => {
  assert.match(script, /PineAlbum\.open\(playerTrack\)/);
  assert.match(album, /\/api\/music\/album\?track_id=/);
  assert.match(album, /className = 'pa-player'/);
  assert.match(album, /data-pine-drag/);
  assert.match(css, /\.pa-box/);
});

test('album tracks expose DJ files, analysis, transcription and queue actions', () => {
  assert.match(album, /\/api\/music\/track\//);
  assert.match(album, /\/api\/music\/notes\//);
  assert.match(album, /\/api\/music\/track\/read/);
  assert.match(album, /\/api\/dj\/request/);
  assert.match(album, /\/api\/dj\/queue\/move/);
  assert.match(album, /Schedule \/ requeue/);
  assert.match(album, /Top of queue/);
});

test('the album desk has smart search, rich now-playing facts and a real meter', () => {
  assert.match(album, /\/api\/music\/search\?q=/);
  assert.match(album, /Search artist, album, or song/);
  assert.match(album, /pa-countdown/);
  assert.match(album, /TIME LEFT/);
  assert.match(album, /reading = meters\.read/);
  assert.match(album, /make\('canvas', 'pa-visual'\)/);
  assert.match(album, /requestAnimationFrame\(draw\)/);
  assert.match(css, /\.pa-art \{ width: 104px; height: 104px/);
});

test('the compact script player is an editable transport with adjacent votes', () => {
  assert.match(script, /PineVote\.mount\(voteSeat/);
  assert.match(script, /id="spVotes"/);
  assert.match(script, /id="spArtist"/);
  assert.match(script, /id="spAlbum"/);
  assert.match(script, /p\.currentTime = \(Number\(seek\.value\) \/ 1000\) \* p\.duration/);
  assert.match(css, /\.sp-votes \.pv-votes \{ flex-direction: row/);
  assert.match(css, /\.sp-seek[\s\S]*height: 30px/);
});

test('the active segment strip opens a complete schedule navigator', () => {
  assert.match(script, /function activeSegment\(row\)/);
  assert.match(script, /function scheduledNow\(\)/);
  assert.match(script, /--sp-segment-run/);
  assert.match(script, /paintOrchestratorMonitor/);
  assert.match(script, /PineConsoleTrace\.open\(item\)/);
  assert.match(script, /tab\('Hour', 'hour'\)/);
  assert.match(script, /tab\('Day', 'day'\)/);
  assert.match(script, /tab\('Week', 'week'\)/);
  assert.match(script, /tab\('Month', 'month'\)/);
  assert.match(script, /\/api\/schedule\/slots/);
  assert.match(script, /\/api\/dj\/segments\/interject/);
  assert.match(script, /segInspectOpen\(ident\)/);
  assert.match(script, /segPromptOpen\(ident\)/);
  assert.match(script, /segExportRun\(ident, 'welded'\)/);
});

test('each calendar segment expands into three conversation readers and editable provenance', () => {
  assert.match(script, /\['Chat', 'chat'\], \['Transcript', 'transcript'\], \['Screenplay', 'screenplay'\]/);
  assert.match(script, /function itinConversation\(entry, sheet, refresh\)/);
  assert.match(script, /script\.draft_turns/);
  assert.match(script, /\/api\/director\/segment\//);
  assert.match(script, /\/api\/pantry\/commission/);
  assert.match(script, /Prompt and scheduling setup/);
  assert.match(css, /\.sp-itin-conversation-body\[data-view="transcript"\]/);
  assert.match(css, /\.sp-itin-conversation-body\[data-view="screenplay"\]/);
  assert.match(css, /\.sp-itin-turn-table/);
  assert.match(script, /function itinConversationTurns\(entry, variant\)/);
  assert.match(script, /var aired = \(entry && entry\.aired\) \|\| \[\]/);
  assert.match(script, /The SFX Guy - stinger/);
  assert.match(script, /Inspect full provenance/);
  assert.match(script, /\/api\/slideshow\?limit=200/);
  assert.match(script, /\/api\/sfx\/video\/profiles\?limit=12/);
  assert.match(script, /video\.muted = true/);
  assert.match(script, /classList\.add\('has-picture'\)/);
  assert.match(css, /\.sp-itin-avatar img/);
  assert.match(css, /\.sp-itin-message-bubble/);
});

test('draft variants can be compared, selected, corrected and traced', () => {
  assert.match(script, /script\.draft_variants/);
  assert.match(script, /\/winner'/);
  assert.match(script, /Select winner/);
  assert.match(script, /Off topic/);
  assert.match(script, /Does not make sense/);
  assert.match(script, /Refer to previous text/);
  assert.match(script, /Discuss this instead/);
  assert.match(script, /\/feedback'/);
  assert.match(script, /function itinTurnFlow\(canvas\)/);
  assert.match(script, /new THREE\.WebGLRenderer/);
  assert.match(css, /\.sp-itin-flow-canvas/);
});

test('the on-air calendar opens and scrolls to the current segment', () => {
  assert.match(script, /sheet\.revealLive = true/);
  assert.match(script, /function itineraryRevealLive\(list\)/);
  assert.match(script, /live\.__pineOpen\(true\)/);
  assert.match(script, /scrollIntoView\(\{block: 'center', behavior: 'smooth'\}\)/);
});

test('feed activity opens details and voicing rows show their actual line', () => {
  assert.match(script, /function feedDetailOpen\(row\)/);
  assert.match(script, /Voice Rendering/);
  assert.match(script, /sp-msg-marquee-track/);
  assert.match(script, /data-dialogue-text/);
  assert.match(css, /@keyframes sp-feed-voice-crawl/);
  assert.match(css, /\.sp-feed-detail-box/);
});

test('feed rows identify their subject, operation, purpose, and orchestrator', () => {
  assert.match(script, /function feedAvatar\(row\)/);
  assert.match(script, /function feedOperation\(row\)/);
  assert.match(script, /function feedPurpose\(row\)/);
  assert.match(script, /function feedOrchestrated\(row\)/);
  assert.match(script, /sp-msg-orchestrator/);
  assert.match(script, /Object\.assign\(\{\}, subject \|\| \{\}, ev\)/);
  assert.match(css, /grid-template-columns: 36px minmax\(112px, \.82fr\) minmax\(0, 1\.55fr\)/);
  assert.match(css, /\.sp-msg-avatar img, \.sp-msg-avatar video/);
  assert.match(css, /--sp-feed-crawl/);
});

test('the live message strip follows the interpolated line and keeps dialogue readable', () => {
  assert.match(script, /speakingNow = \(payload && payload\.now\)/);
  assert.match(script, /function sayingSource\(row, node\)/);
  assert.match(script, /PineStationFeed && root\.PineStationFeed\.now/);
  assert.match(script, /function sayingCrawl\(into, words, seconds\)/);
  assert.match(script, /sayingBox\.dataset\.spoken/);
  assert.match(css, /\.sp-saying-text \{/);
  assert.match(css, /overflow: auto;/);
});

test('the forward script includes draft conversations and every prepared line opens', () => {
  assert.match(script, /boundTurns\.length \? boundTurns : \(sc\.draft_turns \|\| \[\]\)/);
  assert.match(script, /DRAFT READY/);
  assert.match(script, /planLine\.pineItem/);
  assert.match(script, /openLine\(this\.pineItem \|\| \{\}, this\)/);
  assert.match(css, /\.sp-el\.sp-plandraft/);
});

test('the screenplay is a chronological expandable segment outline', () => {
  assert.match(script, /function screenplayOrder\(before, current\)/);
  assert.match(script, /function dressScene\(node, item\)/);
  assert.match(script, /Pine Box FM \/ The Booth/);
  assert.match(script, /sp-segment-time/);
  assert.match(script, /sp-segment-name/);
  assert.match(script, /sp-segment-past/);
  assert.match(script, /node\.setAttribute\('aria-expanded', shut \? 'false' : 'true'\)/);
  assert.match(css, /grid-template-columns: minmax\(58px, 76px\) minmax\(0, 1fr\)/);
});

test('music and DJ spectra share one scale and write the unified final level', () => {
  const app = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
  const levels = fs.readFileSync(path.join(renderer, 'pine-levels.js'), 'utf8');
  assert.match(css, /\.sp-spectrum, \.sp-voicemeter \{ height: 22px; \}/);
  assert.match(script, /levelDrag\(el\('spSpectrum'\), 'music'\)/);
  assert.match(script, /levelDrag\(el\('spVoice'\), 'voice'\)/);
  assert.match(app, /const automaticDuck = unified \? 0 : level\.duck/);
  assert.match(levels, /This is the final[\s\S]*listener gain/);
});

test('all dialogue uses one viewport-bounded hold action sheet', () => {
  const actions = fs.readFileSync(path.join(renderer, 'line-actions.js'), 'utf8');
  const actionCss = fs.readFileSync(path.join(renderer, 'line-actions.css'), 'utf8');
  assert.match(actions, /\[data-dialogue-id\]/);
  assert.match(actions, /\.sp-itin-message/);
  assert.match(actions, /document\.addEventListener\('contextmenu'/);
  assert.match(actionCss, /calc\(100dvh - 24px\)/);
  assert.match(actionCss, /\.la-list[\s\S]*overflow-y: auto/);
});

test('the boot scene starts as diagonal depth-filled streaks and never rotates a plane', () => {
  const boot = fs.readFileSync(path.join(renderer, 'boot-splash.js'), 'utf8');
  assert.match(boot, /var streakPos = new Float32Array/);
  assert.match(boot, /vx: \(4\.8/);
  assert.match(boot, /vy: -\(3\.2/);
  assert.match(boot, /var breathe = Math\.sin/);
  assert.doesNotMatch(boot, /group\.rotation/);
});

test('calendar conversations wrap completely inside the sheet', () => {
  assert.match(css, /flex: 0 0 calc\(100% - 52px\)/);
  assert.match(css, /\.sp-itin-list[\s\S]*overflow-x: hidden/);
  assert.match(css, /\.sp-itin-row[\s\S]*overflow-x: hidden/);
  assert.match(css, /grid-template-columns: minmax\(72px, 120px\) minmax\(0, 1fr\)/);
  assert.match(css, /\.sp-itin-conversation-tools[\s\S]*flex-wrap: wrap/);
  assert.match(css, /\.sp-itin-conversation-body[\s\S]*max-height: none; overflow: visible/);
  assert.match(css, /\.sp-itin-message-text[\s\S]*overflow-wrap: anywhere; word-break: break-word/);
  assert.match(css, /\.sp-itin-setup[\s\S]*max-width: 100%[\s\S]*white-space: pre-wrap/);
});

test('the on-air strip cannot be hidden by control feedback and follows lean playout', () => {
  assert.match(script, /\(!shown \|\| !shown\.id\) && sayUntil/);
  assert.match(script, /\/api\/playout\?limit=1&lean=1/);
  assert.match(script, /the station playout controller names this exact sounding line/);
  assert.match(script, /PLAYOUT_MS = 800/);
});

test('line provenance options are a stable editable table', () => {
  assert.match(deep, /make\('table', 'ld-admin-table'\)/);
  assert.match(deep, /\['Status', 'Option', 'Current value', 'Governs and evidence'\]/);
  assert.match(deep, /meta\.scope/);
  assert.match(deep, /editable\(full/);
});
