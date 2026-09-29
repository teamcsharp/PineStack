/* closex_cases.js - the popups the harness opens, with stubbed data.
 * {name, page: 'panel'|'shell', open: <js expression>, root: <css, optional>,
 *  pre: <js run first, optional>, settle: ms}
 * `ev()` (defined by PRE) is a fake event whose currentTarget is a real
 * button at (300, 300), for the builders that anchor to what was clicked. */
'use strict';

const EV = "window.ev = window.ev || function () { let b = document.getElementById('cxAnchor');"
  + " if (!b) { b = document.createElement('button'); b.id = 'cxAnchor'; b.textContent = 'anchor';"
  + " b.style.cssText = 'position:fixed;left:300px;top:300px;z-index:1'; document.body.appendChild(b); }"
  + " return {currentTarget: b, target: b, clientX: 300, clientY: 300, stopPropagation() {}, preventDefault() {}}; }";
const FAKE = (pathPart, obj) => "(() => { const f0 = window.__f0 || (window.__f0 = window.fetch);"
  + " window.fetch = (u, o) => String(u).includes(" + JSON.stringify(pathPart) + ") ? Promise.resolve(new Response("
  + JSON.stringify(JSON.stringify(obj)) + ", {headers: {'Content-Type': 'application/json'}})) : f0(u, o); })()";

const P = (name, open, extra) => Object.assign({name, page: 'panel', open, pre: EV}, extra || {});

const CASES = [
  /* the operator's screenshot */
  P('booth', 'boothOpen()', {root: '#boothModal', settle: 1200}),
  /* the size in the operator's screenshot: the narrowest the booth goes */
  P('boothNarrow', 'boothOpen()', {root: '#boothModal', settle: 1200,
    pre: EV + "; localStorage.setItem('boothBox', JSON.stringify({left: 40, top: 150, width: 360, height: 560}))"}),
  /* popups that had no X and got one through their builder */
  P('crystalDetail', "crystalDetailOpen('x')", {root: '#crystalModal'}),
  P('trackCard', 'trackCard(1)', {root: '#trackModal'}),
  P('usbConsole', 'usbConsole()'),
  P('pineDoctor', 'pineDoctor()'),
  P('speakboxEdit', "speakboxEdit('a', 'b')", {root: '#speakboxModal'}),
  P('stationPanel', 'djStationPanel()', {root: '#djStationModal'}),
  P('voiceTest', 'voiceTestOpen()', {root: '#voiceTestModal'}),
  P('sfxDir', "sfxDirPopup('x')", {root: '#sfxDirModal'}),
  P('plot', 'plotOpen()', {root: '#plotModal'}),
  P('voiceDesk', 'voiceDeskOpen()', {root: '#voiceDeskModal', settle: 1500}),
  P('studioEngineAB', "studioEngineAB('n', {takes: []})"),
  P('guest', 'djGuestPanel()', {root: '#djGuestOv'}),
  P('rhetDoc', "rhetVecDoc('f')", {root: '#rhetVecOv'}),
  P('rhetWord', "rhetWordDetail('w')", {root: '#rhetDetail'}),
  P('wedgeCard', 'wedgeToast()', {pre: EV + ';' + FAKE('/api/broadcast/health', {stuck: true, say: 'the air is stuck'})
    + '; wedgeSnooze = 0; if (typeof wedgeCardHide === "function") wedgeCardHide()'}),
  P('themeMenu', 'themeMenu(ev())', {root: '#themeMenu'}),
  P('sayMenu', 'djSayMenu(ev())', {root: '#djSayMenu'}),
  P('hawkMenu', "artHawkMenu(ev(), 'n')", {root: '#artHawkMenu'}),
  P('calMenu', 'calMenu(ev(), 0, 0)', {root: '#calMenu'}),
  P('crystalDelMenu', 'crystalDeleteMenu({slug: "x", name: "x"}, 300, 300)', {root: '#crystalDelMenu'}),
  P('engineMenu', 'djHostEngineMenu(ev())', {root: '#djHostEngineMenu'}),
  P('tray', 'toggleTray()', {root: '#trayPanel'}),
  P('lightbox', "showLightbox('x.png')", {root: '#lightbox'}),
  /* the popups that already carried an X: is it in the corner, can it be hit */
  P('adArchive', 'adArchivePopup()'), P('adStudio', 'adStudioOpen()'), P('artistRead', 'artistReadPanel()'),
  P('cal', 'calOpen()'), P('callRec', 'callRecordings()'), P('cookies', 'studioCookies()'),
  P('banter', 'djBanterPanel()'), P('callers', 'djCallersPanel()'), P('graph', 'djGraphPanel()', {settle: 1500}),
  P('mind', 'mindOpen()', {settle: 1500}), P('prompts', 'djPromptManage()'), P('repair', 'djRepairPopup()'),
  P('topics', 'djTopicsPanel()'), P('docLock', 'docLockPanel()'), P('hangup', 'hangupRules()'),
  P('mixtape', 'mixtapeLibrary()'), P('pineInit', 'pineboxInitialize()'), P('pineStatus', 'pineboxStatus()'),
  P('remote', 'remotePanel()'), P('ring', 'phoneRingStudio()'), P('sfxStats', 'sfxStatsOpen()'),
  P('themeDoc', 'themeDocPick()'), P('crystal', 'crystalOpen()', {settle: 1500}),
  P('chunk', 'chunkOpen()'), P('slot', 'slotOpen()'), P('orch', 'orchOpen()'), P('pipe', 'pipeOpen(ev())'),
  P('gpuAdvisor', 'djGpuAdvisor()'), P('storage', 'storagePanel(ev().currentTarget)'),
  P('schedule', 'schedulePanel(ev().currentTarget)'), P('comfyDoctor', 'comfyDoctorPanel()'),
  P('cupboard', 'cupboardPanel()'), P('converseHist', 'djConverseHistory()'), P('talkPopup', 'djTalkPopup()'),
  P('cloud', 'cloudPopupOpen()'), P('backlog', 'backlogOpen()'), P('glass', 'glassOpen()'),
  P('mindTopology', 'mindTopologyOpen()', {settle: 1500}), P('orchLogic', 'orchLogicPanel()'),
  P('orchPlexus', 'orchPlexusOpen()', {settle: 1500}), P('paper', 'paperOpen()'), P('phone', 'phonePanel()'),
  P('mediaSettings', 'pineMediaSettings()'), P('rapAssembly', 'rapAssemblyPanel()'), P('screenplay', 'screenplayOpen()'),
  P('sfxDesk', 'sfxDeskPanel()'), P('sfxInspect', "sfxInspect('x')"), P('sparkQueue', 'sparkQueuePopup(ev())'),
  P('staging', 'stagingDesk()'), P('steward', 'stewardPanel()'), P('wedgeConsole', 'wedgeConsoleOpen()'),
  P('winamp', 'winampOpen()'), P('opsTray', 'opsTray()'), P('callerCases', 'callerCases()'),
  P('callerDossier', "callerDossier('x')"), P('artHawkPanel', "artHawkPanel(['x'])"), P('gazHour', 'gazHourOpen(1)'),
  P('pbModal', 'openModal()', {root: '#pbModal'}), P('deskPanel', 'deskPanel(ev().currentTarget)'),
  P('pathsPanel', 'djPathsPanel(ev().currentTarget)'), P('tailPanel', 'djTailPanel(ev().currentTarget)'),
  P('roomPanel', 'roomPanel(ev().currentTarget)'), P('provenance', "djProvenanceShow({text: 'x', id: 1}, ev())"),
  P('artFullscreen', "artFullscreen('x')"), P('visionDesk', "visionPromptDesk({text: 'x'}, ev().currentTarget, () => {})"),
  P('boothDossier', "boothAnalysisDossier({text: 'x', name: 'Dill'})"), P('paperBell', "paperBellRing('p1', 'Headline')"),
  P('gpuWin', 'djGpuAdvisor()', {root: '#djGpuWin'}),
  /* the other frontend windows the panel imports */
  P('comfyWorkshop', 'comfyWorkshopOpen()', {settle: 2000}), P('system2', 'system2Open()', {settle: 2000}),
  P('wordCause', "wordCauseOpen('pine')", {settle: 2000}), P('stationFlow', 'stationFlowOpen()', {settle: 2000}),
  /* System 3 (frontend/system3.js), imported by the panel the way it does */
  P('s3window', 'system3Open()', {settle: 2500}),
  P('s3focus', "import('/system3/system3.js').then((m) => m.openSystem3Focus({request: async () => ({}), lineId: 'l1'}))", {settle: 1800}),
  P('s3roll', "import('/system3/system3.js').then((m) => m.openRoll({request: async () => ({}), conversationId: 'c1'}))", {settle: 1800}),
  P('s3lineStory', "import('/system3/system3.js').then((m) => m.openLineStory({request: async () => ({}), lineId: 'l1'}))", {settle: 1800}),
  P('s3segInspector', "import('/system3/system3.js').then((m) => m.openSegmentInspector({request: async () => ({}), segment: 's1'}))", {settle: 1800}),
];
const S3CSS = "if (!document.getElementById('system3Style')) { const l = document.createElement('link'); l.id = 'system3Style'; l.rel = 'stylesheet'; l.href = '/system3/system3.css'; document.head.append(l); }";
for (const c of CASES) if (/^s3/.test(c.name)) c.pre = EV + ';' + S3CSS;
CASES.find((c) => c.name === 'wedgeCard').root = 'body > div[style*="z-index: 195"]';

/* ------------------------------------------------------ the shell page */
const LINE = "{id: 'l1', line_id: 'l1', text: 'Hello there, this is the line.', said: 'Hello there', name: 'Dill', speaker: 'A', block: 1, turn: 1, at: Date.now() / 1000}";
/* the boot splash waits for a station the stub never answers as: lift it */
const UNSPLASH = "document.querySelectorAll('.pine-splash, #rebuildOverlay').forEach((n) => n.remove())";
const S = (name, open, extra) => Object.assign({name, page: 'shell', open, pre: EV + ';' + UNSPLASH}, extra || {});
CASES.push(
  S('levels', "(window.PineLevels ? 0 : new Promise((r) => { const s = document.createElement('script'); s.src = '/r/pine-levels.js'; s.onload = r; document.head.append(s); })).then(() => PineLevels.open())", {root: '.plv-sheet'}),
  S('segTopics', 'PineSegments.topicWindow()', {root: '.pseg-topic-sheet'}),
  S('segPlot', "PineSegments.plotWindow({title: 'Plot', acts: ['one', 'two'], filename: 'x.md'})", {root: '.pseg-sheet'}),
  S('orchGlass', 'PineOrchGlass.open()', {settle: 1200}),
  S('lineActions', 'PineLineActions.open(' + LINE + ')', {root: '.la-sheet'}),
  S('lineDeep', 'PineLineDeep.open(' + LINE + ')', {root: '.ld-box', settle: 1200}),
  S('lineRepeat', 'PineLineRepeat.open(' + LINE + ')'),
  S('adViewer', 'PineAdViewer.open()', {settle: 1200}),
  S('adGallery', 'PineAdViewer.openGallery()', {settle: 1200}),
  S('promptHistory', 'PinePromptHistory.toggle()', {settle: 1200}),
  S('pinelive', 'PineLive.open()', {settle: 1200}),
  S('voiceActor', 'PineVoiceActor.open()', {settle: 1200}),
  S('voiceExtract', 'Promise.resolve(PineVoiceActor.open()).then(() => PineVoiceActor.openExtraction())', {settle: 1500}),
  S('album', "PineAlbum.open({title: 'Song', artist: 'Artist', album: 'Album'})", {settle: 1200}),
  S('changelog', 'PineChangeLog.open()', {settle: 1200}),
  S('consoleTrace', "PineConsoleTrace.open({text: 'x', kind: 'x', at: Date.now() / 1000})", {root: '.ct-box'}),
  S('clipDoctor', "PineClipDoctor.open('no clip')", {settle: 1200}),
  S('threeChooser', 'PineThreeFull.chooser()', {settle: 1200}),
  S('consoleList', 'PineConsoleLine.open()', {root: '#pineConsoleList'}),
  S('untraced', 'PineConsoleLine.untraced()', {root: '#pineUntracedList'}),
  S('viewMenu', 'PineViewChrome.openMenu()'),
  S('reportPad', "PineReport.open('', 'a note')", {root: '#pineReportPad'}),
  S('trackPick', 'trackPick()'), S('promptDesk', 'promptDesk()'),
  S('wkVersionRead', "wkVersionRead({id: 1}, 'a', 'label', 'text')"), S('wkRoundEdit', 'wkRoundEdit({id: 1, lines: []})'),
  S('wkReviewPopup', "wkReviewPopup('round', '1')"), S('segCell', 'segCellOpen()'), S('callIn', 'callInPanel()'),
);

/* The Electron preload bridge (window.pineDesktop), stubbed: every member is
 * a callable that resolves {} and has members of its own. */
const SHELL_STUB = "(function(){ const mk = () => new Proxy(function(){}, {"
  + " get: (t, k) => k === 'then' ? undefined : (k === Symbol.toPrimitive ? () => '' : mk()),"
  + " apply: () => Promise.resolve({}) }); window.pineDesktop = mk(); })();";
const SHELL_CSS = [], SHELL_SCRIPTS = [];

module.exports = {CASES, SHELL_CSS, SHELL_SCRIPTS, SHELL_STUB};
