#!/usr/bin/env python3
"""closex_renderer - desktop/renderer popups (the desk shell and, through
pine-views, the tablet): the corner X, through each popup's own builder and
its own close road.

    python closex_renderer.py --check <repo-root>
    python closex_renderer.py --apply <repo-root>

Every patch is written once for desktop/renderer/<file> and repeated for the
kiosk mirror app/src/main/assets/pine-views/<file> when that copy exists, so
the two stay identical (deploy.sh syncs pine-views FROM desktop/renderer;
pine-sampler/sfx-tv.js is re-copied by deploy.sh itself).

Where a popup already had a small close in its header, the corner X presses
that one (its road, unchanged) and the old one steps aside (display:none, not
removed - callers may still hold it). Where the old close sits at the foot of
a list ("Close" after the choices), it stays.

Parallel builders: talk-dot.js (base-bar disk icon / file manager) and the
staged wave's ad-viewer.js are touched here by ONE line each, anchored on a
single line.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from closex_patchlib import Insert, Replace, main  # noqa: E402

R = "desktop/renderer/"
MIRRORS = ["app/src/main/assets/pine-views/"]


def X(fname, marker, scope, anchor, text, where="after", within=200):
    out = []
    for base in [R] + MIRRORS:
        out.append(Insert(base + fname, f"closex:{marker}", anchor,
                          text.rstrip() + f"  // [closex:{marker}]",
                          where=where, scope=scope, within=within))
    return out


def G(popup, close, old=None, label="Close", extra=""):
    """the one line: X on `popup`, calling `close`; `old` steps aside"""
    tail = f" {old}.style.display = 'none';" if old else ""
    opts = "{label: '%s'%s}" % (label, extra)
    return f"if (window.pineCloseX) {{ window.pineCloseX({popup}, {close}, {opts});{tail} }}"


SPEC = [
    ("pine-segments.js", "pseg-topic", "  function topicWindow() {", "    x.addEventListener('click', topicShut);",
     "    " + G("node", "function () { x.click(); }", "x", "Close the topics")),
    ("pine-segments.js", "pseg-plot", "  function plotWindow(parsed) {", "    x.addEventListener('click', function () { shut(); });",
     "    " + G("node", "function () { x.click(); }", "x", "Close the plot")),
    ("line-actions.js", "line-actions", "  function open(line) {", "    document.body.appendChild(sheet);",
     "    " + G("sheet", "function () { close(); }", None, "Close"), "after", 140),
    ("ad-viewer.js", "ad-viewer", None, "    veil.appendChild(box); document.body.appendChild(veil);",
     "    " + G("box", "function () { close(); }", None, "Close the ad viewer")),
    ("album-popup.js", "album", None, "    shut.addEventListener('click', close);",
     "    " + G("box", "function () { close(); }", "shut", "Close the album")),
    ("clip-doctor.js", "clip-doctor", "  function build() {", "    bar.appendChild(x);",
     "    " + G("box", "function () { x.click(); }", "x", "Close the clip doctor")),
    ("three-full.js", "three-chooser", "  function chooser() {", "    document.body.appendChild(mine);",
     "    " + G("mine", "function () { if (sheet === mine) { mine.remove(); sheet = null; } }", None, "Close the 3JS list")),
    ("talk-dot.js", "report-pad", "  function reportOpen(heard, image, dictateNow, firstLine) {", "    document.body.appendChild(pad);",
     "    " + G("pad", "function () { padClose(); }", None, "Close the report", ", reserve: 'top'"), "after", 130),
    ("talk-dot.js", "mic-menu", "  async function micMenu() {", "    document.body.appendChild(box);",
     "    " + G("box", "function () { closeMicMenu(); }", None, "Close the microphones", ", reserve: 'top'")),
    ("view-chrome.js", "view-sheet", "  function sheet() {", "    document.body.appendChild(box);",
     "    " + G("box", "function () { box.remove(); }", None, "Close the menu", ", reserve: 'top'")),
    ("orchestrator-glass.js", "orch-glass", "  function build() {", "    head.appendChild(shut);",
     "    " + G("node", "function () { shut.click(); }", "shut", "Close the orchestrator"), "after", 60),
    ("pine-levels.js", "levels", "  function open() {", "    shut.addEventListener('click', close);",
     "    " + G("node", "function () { close(); }", "shut", "Close the levels")),
    ("video-editor.js", "ve-escape", "  function showEscape(", "    box.appendChild(card); document.body.appendChild(box);",
     "    " + G("card", "function () { escapeClose(); }", None, "Close")),
    ("presentation.js", "pv-popup", None, '    frame.querySelector("[data-close]").onclick = closePopup;',
     "    " + G("frame", "closePopup", 'frame.querySelector("[data-close]")', "Close")),
    ("lcd.js", "lcd-panel", None,
     "    const close = node('button', 'Close'); close.onclick = () => { shade.remove(); panel = null; syncStationFeed(); };",
     "    " + G("card", "() => close.click()", "close", "Close the LCD panel")),
    ("listen.js", "listen-desk", None, '      root.PineDismiss.watch(desk, () => open(false), [() => el("plDeskBtn")]);',
     "      " + G("desk", "() => open(false)", None, "Close the levels", ", reserve: 'top'")),
    ("script-page.js", "sp-ban-ask", "  function findBanAsk(back, pane, q) {",
     "    no.addEventListener('click', function () { wrap.remove(); });",
     "    " + G("sheet", "function () { wrap.remove(); }", None, "Cancel (close)"), "after", 60),
    ("script-page.js", "sp-view-menu", "  function mvMenuToggle(flip, ev) {", "    mv.menu = menu;",
     "    " + G("menu", "function () { mvMenuClose(); }", None, "Close the menu", ", reserve: 'top'"), "after", 40),
    ("line-reach.js", "reach-menu", "  function open(atX, atY, row) {", "    document.body.appendChild(menu);",
     "    " + G("menu", "function () { shut(); }", None, "Close the menu", ", reserve: 'top'"), "after", 60),
    ("sfx-tv.js", "sfx-ask", "  function ask(screen) {", "    askWrap = wrap;",
     "    " + G("wrap", "function () { askDrop(); }", None, "Close", ", reserve: 'top'"), "after", 90),
    ("sfx-tv.js", "sfx-parody-result", "  function parodyResultOpen(generation, url) {",
     "    shade.addEventListener('click', function (ev) { if (ev.target === shade) shade.remove(); });",
     "    " + G("box", "function () { close.click(); }", "close", "Close"), "after", 80),
    ("sfx-tv.js", "sfx-parody", "  function parodyOpen(seed, keepSurfaceDown) {",
     "    shade.appendChild(box); document.body.appendChild(shade); parodyWrap = shade;",
     "    " + G("box", "function () { parodyClose(); }", "close", "Close the stinger maker"), "after", 140),
    ("sfx-tv.js", "sfx-delete", "  function deleteConfirm(clip) {", "    document.body.appendChild(shade); deleteWrap = shade;",
     "    " + G("box", "function () { deleteConfirmClose(true); }", None, "Keep it (close)")),
    ("sfx-tv.js", "sfx-editor", "  function editorWindow(path, say, clip, after) {", "    document.body.appendChild(box);",
     "    " + G("box", "function () { editorClose(); }", None, "Close the editor")),
    ("sfx-tv.js", "sfx-endless", "  function endlessSheet() {", "    document.body.appendChild(box);",
     "    " + G("box", "function () { endlessSheet(); }", None, "Close", ", reserve: 'top'"), "after", 300),
]

PATCHES = []
for row in SPEC:
    fname, marker, scope, anchor, text = row[:5]
    where = row[5] if len(row) > 5 else "after"
    within = row[6] if len(row) > 6 else 200
    PATCHES += X(fname, marker, scope, anchor, text, where, within)

# renderer.js is the desk shell only (no kiosk mirror)
PATCHES += [
    Insert(R + "renderer.js", "closex:wk-round-edit", "  document.body.appendChild(d);",
           "  " + G("d", "() => shut.click()", None, "Cancel the edit") + "  // [closex:wk-round-edit]",
           scope="function wkRoundEdit(r) {", within=60),
    Insert(R + "renderer.js", "closex:call-in", "  box.appendChild(shut);",
           "  " + G("box", "() => shut.click()", "shut", "Close the call-in") + "  // [closex:call-in]",
           scope="function callInPanel() {", within=40),
    Insert(R + "renderer.js", "closex:dx-line-menu", "  document.body.appendChild(menu);",
           "  " + G("menu", "close", None, "Close the menu", ", reserve: 'top'") + "  // [closex:dx-line-menu]",
           scope="function dxLineMenu(ev, item) {", within=100),
    # the two notice cards that stay up until answered: their X is their own "Later"
    Insert(R + "renderer.js", "closex:reject-notice",
           "  review.onclick = () => open(newest); badge.onclick = () => open(null); later.onclick = snooze;",
           "  " + G("card", "() => later.click()", None, "Not now", ", reserve: 'top'") + "  // [closex:reject-notice]",
           scope="function createDesktopRejectionNotices(", within=80),
    Insert(R + "renderer.js", "closex:retire-notice", "  later.onclick = dismiss;",
           "  " + G("card", "() => later.click()", None, "Not now", ", reserve: 'top'") + "  // [closex:retire-notice]",
           scope="function createDesktopRetireNotices(", within=40),
]

# prompt-history: its <dialog> popups (the H3 prompt viewer's inspect and
# randomization sheets) - one road, pop(), plus the randomization one.
for base in [R] + MIRRORS:
    PATCHES.append(Replace(base + "prompt-history.js", "closex:ph-pop",
                           "panel.appendChild(popup); popup.showModal(); return popup;",
                           "panel.appendChild(popup); popup.showModal(); "
                           "if (window.pineCloseX) { window.pineCloseX(popup, function () { popup.close(); }, {label: 'Close inspection'}); "
                           "var phOld = popup.querySelector('.ph-inspect-close'); if (phOld) phOld.style.display = 'none'; } "
                           "/* [closex:ph-pop] */ return popup;"))
    PATCHES.append(Replace(base + "prompt-history.js", "closex:ph-random",
                           "popup.addEventListener('close', function () { popup.remove(); }); panel.appendChild(popup); popup.showModal();\n",
                           "popup.addEventListener('close', function () { popup.remove(); }); panel.appendChild(popup); popup.showModal();"
                           " if (window.pineCloseX) window.pineCloseX(popup, function () { popup.close(); }, {label: 'Close randomization'}); /* [closex:ph-random] */\n"))

# keep only the mirror patches whose file exists in the tree being patched
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0] if args else ".").resolve()
    PATCHES = [p for p in PATCHES if not any(p.file.startswith(m) for m in MIRRORS) or (root / p.file).exists()]
    sys.exit(main(PATCHES))
