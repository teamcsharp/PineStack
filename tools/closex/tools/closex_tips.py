#!/usr/bin/env python3
"""closex_tips - every icon-only button says what it does on hover.

    python closex_tips.py --check <repo-root>
    python closex_tips.py --apply <repo-root>

"I don't know which icon to click because there's no tool tips on hover for
them." Each row is a button whose face is only a glyph (a cross, a bin, an
arrow, a triangle): one line after it is made gives it a title (the hover
tooltip) and, if it had none, the same words as its aria-label. The rows are
tips_audit.js's findings; tips_audit.js is the test that none are left.

Popup X's that pine-closex.js replaced are not here: the old button steps
aside and the corner X carries its own title.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from closex_patchlib import Insert, Replace, main  # noqa: E402

R = "desktop/renderer/"
MIRROR = "app/src/main/assets/pine-views/"


def T(file, scope, anchor, v, words, within=300):
    key = scope.split('(')[0].split()[-1] if scope.lstrip().startswith(("function", "async")) else scope.strip()[:18]
    marker = f"closex:tip:{Path(file).name}:{key}:{v}:{words[:12]}"
    js = (f'{v}.title = "{words}"; if (!{v}.getAttribute("aria-label")) '
          f'{v}.setAttribute("aria-label", "{words}");')
    ind = anchor[: len(anchor) - len(anchor.lstrip())]
    return Insert(file, marker, anchor, f"{ind}{js}  // [{marker}]", where="after", scope=scope, within=within)


P = "app.py"
ROWS = [
    (P, "async function scriptsOpen() {", '  const refresh = el("button", "", "↻");', "refresh", "Refresh the list"),
    (P, "  oneShot.forEach((n) => {", '    const drop = el("button", "", "✕");', "drop", "Retire this note"),
    (P, "async function sfxDirPopup(sfxId) {", '    const play = el("button", "", "▶");', "play", "Play this sample"),
    (P, "async function produce(air) {", '  const del = el("button", "", "🗑");', "del", "Delete this spot"),
    (P, "function trackPanel(slot, at2) {", '  const x2 = el("button", "", "\\u2715");', "x2", "Close"),
    (P, "function promptPanel(slot, at2) {", '  const x2 = el("button", "", "\\u2715");', "x2", "Close"),
    (P, "async function plotList() {", '  const del = el("button", "", "🗑");', "del", "Delete this plot"),
    (P, "async function renderUpstairs() {", '  const bin = el("button", "danger", "🗑");', "bin", "Delete this page"),
    (P, "async function calOpen() {", '  const prev = el("button", "", "◀");', "prev", "Previous"),
    (P, "async function calOpen() {", '  const next = el("button", "", "▶");', "next", "Next"),
    (P, "function calRenderSide() {", '  const pv = el("button", "", "⏮");', "pv", "Previous in the queue"),
    (P, "function calRenderSide() {", '  const nx = el("button", "", "⏭");', "nx", "Next in the queue"),
    (P, "async function djCallersPanel() {", '      const drop = el("button", "danger", "✕");', "drop", "Delete this caller"),
    (P, "async function mindReader(name) {", '  const x = el("button", "", "✕");', "x", "Close"),
    (P, "async function backlogRefresh() {", '  const play = el("button", "bl-play", "▶");', "play", "Play"),
    (P, "function threeSheetOpen() {", '  x.textContent = "×";', "x", "Close"),
    (P, "async function sfxStatsOpen() {", '  const play = el("button", "", "▶");', "play", "Play this sample"),
    (P, "function studioSimulacrumWizard(host) {", '  const drop = el("button", "", "✕");', "drop", "Remove this component"),
    (P, "async function libOpenDoc(slug, page) {", '  const prev = el("button", "", "◀");', "prev", "Previous page"),
    (P, "async function libOpenDoc(slug, page) {", '  const next = el("button", "", "▶");', "next", "Next page"),
    (P, "async function pipeOpen(ev) {", '  shut.textContent = "\\u2715";', "shut", "Close"),
    (R + "hot-corners.js", "  function sheet(title, cls, opts) {", "    var x = make('button', 'hc-x', '×');", "x", "Close"),
    (R + "renderer.js", '    pop = mk("div", "triage-pop");', '    const x = mk("button", "tri-x", "✕");', "x", "Close"),
    (R + "renderer.js", '    pop = mk("div", "works-pop");', '    const x = mk("button", "wk-x", "✕");', "x", "Close"),
    (R + "renderer.js", "function schedTilePopup() {", '  const x = mk("button", "", "✕");', "x", "Close"),
    (R + "renderer.js", "function pantryRow(r) {", '  const tri = mk("button", "", "\\u25b8");', "tri", "Show or hide the details"),
    (R + "renderer.js", "async function dxLineTranscript(item) {", '  const x = mk("button", "wk-x", "✕");', "x", "Close"),
    (R + "renderer.js", "function wkPurgePop(anchor) {", '  const x = mk("button", "wk-x", "✕");', "x", "Close"),
    (R + "renderer.js", "function wkTakeText(take) {", '  const x = mk("button", "wk-x", "✕");', "x", "Close"),
    (R + "renderer.js", "function wkRoadPop(road, anchor) {", '  const x = mk("button", "wk-x", "✕");', "x", "Close"),
    (R + "renderer.js", "function worksSchedule(anchorPop) {", '  const x = mk("button", "wk-x", "✕");', "x", "Close"),
    (R + "renderer.js", "function worksSchedule(anchorPop) {", '  const prev = mk("button", "", "‹");', "prev", "Previous"),
    (R + "renderer.js", "function worksSchedule(anchorPop) {", '  const next = mk("button", "", "›");', "next", "Next"),
    (R + "renderer.js", "function trackPick(slot) {", '  const cx = mk("button", "wk-x", "\\u2715");', "cx", "Close"),
    (R + "renderer.js", "function promptDesk(slot, i, opts) {", '  const cx = mk("button", "wk-x", "\\u2715");', "cx", "Close"),
    (R + "renderer.js", "function detail(slot, i) {", '  const cx = mk("button", "wk-x", "✕");', "cx", "Close"),
    (R + "sampler-face.js", "  function openPicker() {", "    var shut = make('button', 'pb-skins-x', '×');", "shut", "Close"),
    (R + "sampler-grab.js", "  function open(options) {", "    var shut = make('button', 'sg-x', '×');", "shut", "Close"),
    (R + "sampler.js", "  async function openKits() {", '    shut.textContent = "\\u00d7";', "shut", "Close"),
    (R + "sampler.js", "  async function showDisk(path) {", '    shut.textContent = "\\u00d7";', "shut", "Close"),
    (R + "script-flow.js", "function chunk(into, spec) {", "  twist.textContent = '\\u25b8';", "twist", "Show or hide this part"),
    (R + "script-flow.js", "function chunk(into, spec) {", "  cut.textContent = '\\u00d7';", "cut", "Remove this part"),
    (R + "script-page.js", "  function folderOpen() {", "    var x = make('button', 'sp-find-x', '\\u00d7');", "x", "Close"),
    (R + "script-page.js", "  function folderRow(f, depth, hasKids) {", "    var check = make('button', 'sp-folder-check', '');", "check",
     "Pin the clips to this folder for a few hours (press again to unpin)"),
    (R + "script-page.js", "  function sheetShell(id, cls, title) {", "    var x = make('button', 'sp-find-x', '\\u00d7');", "x", "Close"),
    (R + "script-page.js", "  function segExportToast(title) {", "    var x = make('button', 'sp-segexp-x', '\\u00d7');", "x", "Close"),
    (R + "script-page.js", "  function findOpen(q) {", "    var x = make('button', 'sp-find-x', '\\u00d7');", "x", "Close"),
    (R + "script-page.js", "  function mixerOpen() {", "    var shut = make('button', 'sp-mix-shut', '\\u2715');", "shut", "Close"),
    (R + "script-page.js", "  function openLine(item, node) {", "    var close = make('button', 'sp-detail-close', '✕');", "close", "Close"),
    (R + "slideshow.js", "  function openSheet(which, row) {", "    var close = el('button', 'sl-sheet-close', '✕');", "close", "Close"),
]

PATCHES = []
for file, scope, anchor, v, words in ROWS:
    PATCHES.append(T(file, scope, anchor, v, words))
    if file.startswith(R):
        PATCHES.append(T(MIRROR + file[len(R):], scope, anchor, v, words))

# markup buttons
PATCHES += [
    Replace(R + "index.html", "closex:tip:reload-aria",
            '<button id="reloadFrameBtn" title="Reload current panel">R</button>',
            '<button id="reloadFrameBtn" title="Reload current panel" aria-label="Reload current panel" data-closex="closex:tip:reload-aria">R</button>'),
    Replace(R + "renderer.js", "closex:tip:renderer.js:range-x",
            "+ \"<button data-x='\" + n + \"'>✕</button></div>\").join(\"\")",
            "+ \"<button data-x='\" + n + \"' title='Remove this range' aria-label='Remove this range'>✕</button></div>\").join(\"\") /* [closex:tip:renderer.js:range-x] */"),
    Replace(R + "video-editor.html", "closex:tip:ve-play",
            '<button id="play" class="play" disabled aria-label="Play selection">',
            '<button id="play" class="play" disabled aria-label="Play selection" title="Play selection" data-closex="closex:tip:ve-play">'),
    Replace(R + "video-editor.html", "closex:tip:ve-in",
            'class="trim-handle in" aria-label="Trim start" role=',
            'class="trim-handle in" aria-label="Trim start" title="Trim start (drag)" data-closex="closex:tip:ve-in" role='),
    Replace(R + "video-editor.html", "closex:tip:ve-out",
            'class="trim-handle out" aria-label="Trim end" role=',
            'class="trim-handle out" aria-label="Trim end" title="Trim end (drag)" data-closex="closex:tip:ve-out" role='),
    Replace(R + "video-editor.html", "closex:tip:ve-split-in",
            'aria-label="Piece in point" aria-valuemin=',
            'aria-label="Piece in point" title="Piece in point (drag)" data-closex="closex:tip:ve-split-in" aria-valuemin='),
    Replace(R + "video-editor.html", "closex:tip:ve-split-out",
            'aria-label="Piece out point" aria-valuemin=',
            'aria-label="Piece out point" title="Piece out point (drag)" data-closex="closex:tip:ve-split-out" aria-valuemin='),
]

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0] if args else ".").resolve()
    PATCHES = [p for p in PATCHES if not p.file.startswith(MIRROR) or (root / p.file).exists()]
    sys.exit(main(PATCHES))
