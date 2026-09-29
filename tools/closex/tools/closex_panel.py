#!/usr/bin/env python3
"""closex_panel - the station panel (app.py CONTROL_PANEL_HTML): serve
pine-closex.js, load it, and give every popup that had no X its corner X.

    python closex_panel.py --check <repo-root>
    python closex_panel.py --apply <repo-root>

Each popup is fixed in its own builder, calling its own close road. The
anchor is the builder's signature (unique) plus one line inside it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from closex_patchlib import Insert, Replace, main  # noqa: E402

F = "app.py"


def x_before(marker, scope, anchor, popup, close, label, extra=""):
    """pineCloseX(popup, close) on its own line before `anchor` in `scope`."""
    opts = '{label: "%s"%s}' % (label, extra)
    return Insert(F, marker, anchor,
                  f"  if (window.pineCloseX) window.pineCloseX({popup}, {close}, {opts});  // [{marker}]",
                  where="before", scope=scope)


def x_after(marker, scope, anchor, popup, close, label, extra=""):
    opts = '{label: "%s"%s}' % (label, extra)
    return Insert(F, marker, anchor,
                  f"  if (window.pineCloseX) window.pineCloseX({popup}, {close}, {opts});  // [{marker}]",
                  where="after", scope=scope)


CARD = "  shade.appendChild(card);"

PATCHES = [
    # -- the helper: served from desktop/renderer like pine-stick.js, loaded by the panel
    Insert(F, "closex:asset", '    "pine-stick.js": "application/javascript; charset=utf-8",',
           '    # [closex:asset] every popup\'s corner X - one control, one look\n'
           '    "pine-closex.js": "application/javascript; charset=utf-8",'),
    Insert(F, "closex:script", '<script src="/spark/asset/wall-transition.js"></script>',
           '<!-- [closex:script] the corner X every popup carries (pineCloseX) -->\n'
           '<script src="/spark/asset/pine-closex.js"></script>', where="before"),

    # -- THE BOOTH: the operator's screenshot. Its Close was the last button in
    #    a bar that does not wrap, inside a window that clips.
    Insert(F, "closex:booth-bar", '    + "gap:8px;align-items:center;padding:10px 14px;z-index:2;"',
           '    + "flex-wrap:wrap;padding-right:56px;"   // [closex:booth-bar] wrap, never clip; clear of the X',
           scope="async function boothOpen() {"),
    Insert(F, "closex:booth-tips", '  next.onclick = () => djCall("next");',
           '  // [closex:booth-tips] every icon button says what it does\n'
           '  [[prev, "Previous track"], [next, "Next track"],\n'
           '   [banterBtn, "Have the DJs banter now"], [adBtn, "Play an ad now"],\n'
           '   [grow, "Fill the screen / restore"], [pop, "Pop out into a floating window"]]\n'
           '    .forEach(([b, say]) => { b.title = b.title || say; b.setAttribute("aria-label", say); });',
           scope="async function boothOpen() {"),
    Replace(F, "closex:booth",
            '  const shut = el("button", "danger", "✕ Close");\n'
            '  shut.onclick = boothClose;\n'
            '  [title, onAir, prev, next, banterBtn, adBtn, viewBtn, grow, pop, shut]\n'
            '    .forEach((n) => bar.appendChild(n));\n',
            '  // [closex:booth] The way out is the corner X (pine-closex.js), not the\n'
            '  // last button in a bar that clips: at 620 px "Ad" was already cut and\n'
            '  // Close had slid off the edge - the booth could not be closed at all.\n'
            '  [title, onAir, prev, next, banterBtn, adBtn, viewBtn, grow, pop]\n'
            '    .forEach((n) => bar.appendChild(n));\n'
            '  if (window.pineCloseX) {\n'
            '    window.pineCloseX(shade, boothClose, {label: "Close the booth"});\n'
            '  } else {\n'
            '    const shut = el("button", "danger", "✕ Close");\n'
            '    shut.onclick = boothClose;\n'
            '    bar.appendChild(shut);\n'
            '  }\n',
            scope="async function boothOpen() {"),
    Insert(F, "closex:booth-reqtip", '  reqBtn.onclick = () => boothSend(true);',
           '  reqBtn.title = "Request a song by name";   // [closex:booth-reqtip]\n'
           '  sendBtn.title = "Say it to the DJ";',
           scope="async function boothOpen() {"),

    # -- shade + card modals whose only way out was a Close at the bottom, or none
    x_before("closex:crystal-detail", "async function crystalDetailOpen(slug) {", CARD,
             "card", "crystalDetailClose", "Close the crystal"),
    x_before("closex:track-card", "async function trackCard(id) {", CARD,
             "card", "trackClose", "Close the track card"),
    x_before("closex:usb-console", "function usbConsole() {", CARD,
             "card", "() => shut.click()", "Close the USB console"),
    x_before("closex:pine-doctor", "async function pineDoctor() {", CARD,
             "card", "() => shade.remove()", "Close the diagnosis"),
    x_before("closex:speakbox-edit", "async function speakboxEdit(name, passage) {", CARD,
             "card", "shutAll", "Close the speaker box"),
    x_before("closex:station-panel", "async function djStationPanel() {", CARD,
             "card", "() => shade.remove()", "Close the station settings"),
    x_before("closex:voice-test", "async function voiceTestOpen() {", CARD,
             "card", "voiceTestClose", "Close the voice test"),
    x_before("closex:sfx-dir", "async function sfxDirPopup(sfxId) {", CARD,
             "card", "() => shade.remove()", "Close the sample folder"),
    x_before("closex:plot", "async function plotOpen() {", CARD,
             "card", "() => shade.remove()", "Close the plots"),
    x_before("closex:voice-desk-wait", "async function voiceDeskOpen() {", "  document.body.appendChild(wait);",
             "waitCard", "() => wait.remove()", "Close the voice desk"),
    x_before("closex:voice-desk", "async function voiceDeskOpen() {", CARD,
             "card", "() => shade.remove()", "Close the voice desk"),
    x_before("closex:studio-ab", "async function studioEngineAB(name, got) {", "  document.body.appendChild(box);",
             "box", "() => shut.click()", "Close the engine comparison"),
    x_before("closex:guest", "async function djGuestPanel() {", "  ov.appendChild(card);",
             "card", "() => ov.remove()", "Close the studio guest"),
    x_before("closex:rhet-doc", "async function rhetVecDoc(file) {", "ov.appendChild(card); document.body.appendChild(ov);",
             "card", "() => ov.remove()", "Close the document"),
    x_before("closex:rhet-word", "async function rhetWordDetail(word) {", "  ov.appendChild(card);",
             "card", "() => ov.remove()", "Close the word"),

    # -- found by the harness: a Close only at the foot (or a row's delete cross
    #    that the static audit mistook for one), nothing in the corner
    Insert(F, "closex:ad-studio", CARD,
           '  if (window.pineCloseX) window.pineCloseX(card, () => shade.remove(), {label: "Close the Ad studio"});  // [closex:ad-studio]',
           where="before", scope="async function adStudioOpen() {", within=460),
    Insert(F, "closex:banter", CARD,
           '  if (window.pineCloseX) window.pineCloseX(card, () => shut.click(), {label: "Close the banter desk"});  // [closex:banter]',
           where="before", scope="async function djBanterPanel() {", within=420),
    Insert(F, "closex:callers", CARD,
           '  if (window.pineCloseX) window.pineCloseX(card, () => shut.click(), {label: "Close the callers"});  // [closex:callers]',
           where="before", scope="async function djCallersPanel() {", within=480),
    Insert(F, "closex:topics", CARD,
           '  if (window.pineCloseX) window.pineCloseX(card, () => shut.click(), {label: "Close the topics"});  // [closex:topics]',
           where="before", scope="function djTopicsPanel() {", within=330),
    x_before("closex:sfx-stats", "async function sfxStatsOpen() {", CARD,
             "card", "() => shade.remove()", "Close the SFX statistics"),
    x_before("closex:theme-doc", "async function themeDocPick() {", CARD,
             "card", "close", "Close the document picker"),
    x_after("closex:paths", "function djPathsPanel(anchor) {", "  document.body.appendChild(pop);",
            "pop", "() => pop.remove()", "Close the paths"),
    x_after("closex:room", "function roomPanel(anchor) {", "  document.body.appendChild(pop);",
            "pop", "() => pop.remove()", "Close the room"),

    # -- hand-rolled X's the generator could not read (appended in a row of
    #    several): the corner X calls the old one's handler, the old one goes
    *[Insert(F, f"closex:legacy2:{fn}", anchor,
             f"{ind}if (window.pineCloseX) {{ window.pineCloseX({pop}, () => {v}.click()); {v}.remove(); }}  // [closex:legacy2:{fn}]",
             where="after", scope=sig, within=within)
      for fn, sig, anchor, pop, v, ind, within in [
          ("storagePanel", "function storagePanel(anchor) {",
           "    head.appendChild(title); head.appendChild(again); head.appendChild(shut);", "pop", "shut", "    ", 60),
          ("schedulePanel", "function schedulePanel(anchor) {",
           "    head.appendChild(title); head.appendChild(again); head.appendChild(shut);", "pop", "shut", "    ", 70),
          ("comfyDoctorPanel", "async function comfyDoctorPanel() {",
           "  head.appendChild(run); head.appendChild(deep); head.appendChild(x);", "box", "x", "  ", 60),
          ("stewardPanel", "async function stewardPanel() {",
           "  head.appendChild(check); head.appendChild(fix); head.appendChild(x);", "box", "x", "  ", 60),
          ("opsTray", "function opsTray() {", "  head.appendChild(x);", "box", "x", "  ", 40),
          ("djTailPanel", "function djTailPanel(anchor) {",
           "  row.appendChild(go); row.appendChild(close);", "pop", "close", "  ", 200),
          ("paperBellRing", "function paperBellRing(id, headline) {",
           "  card.appendChild(mark); card.appendChild(words); card.appendChild(shut);", "card", "shut", "  ", 60),
          ("artFullscreen", "async function artFullscreen(name) {",
           "  top.appendChild(title); top.appendChild(shut);", "card", "shut", "  ", 60),
          ("visionPromptDesk", "function visionPromptDesk(line, anchor, onResult) {",
           "    head.appendChild(title); head.appendChild(shut);", "pop", "shut", "    ", 60),
          ("boothAnalysisDossier", "function boothAnalysisDossier(line) {",
           "  head.appendChild(t); head.appendChild(x);", "pop", "x", "  ", 40),
          ("djGpuAdvisor", "async function djGpuAdvisor() {", "  win.appendChild(shut);", "win", "shut", "  ", 60),
      ]],

    Insert(F, "closex:cloud", "  head.appendChild(x);",
           '  if (window.pineCloseX) {   // [closex:cloud] close, never toggle: a cloud that never mounted must still go\n'
           '    window.pineCloseX(box, () => { if (cloud) toggleCloud(); else cloudPopupClose(); }, {label: "Close the word cloud"});\n'
           '    x.remove();\n'
           '  }',
           scope="function cloudPopupOpen() {", within=30),
    Insert(F, "closex:mind-topology", "  card.appendChild(bar); shade.appendChild(card); document.body.appendChild(shade);",
           '  if (window.pineCloseX) { window.pineCloseX(card, () => closeBtn.click(), {label: "Close the Mind Topology"}); closeBtn.style.display = "none"; }  // [closex:mind-topology]',
           scope="async function mindTopologyOpen() {", within=30),

    # -- persistent notices: their X is their own "later"
    x_before("closex:wedge-card", "async function wedgeToast() {", "  wedgeCard = card;",
             "card", "() => later.click()", "Not now (ask again in ten minutes)", ', reserve: "top"'),
    x_before("closex:orch-card", "async function orchToast() {", "  orchCard = card;",
             "card", "() => later.click()", "Not now (ask again in ten minutes)", ', reserve: "top"'),

    # -- menus: they close on a tap away too, the X is the one you can see
    x_after("closex:theme-menu", "function themeMenu(event) {", "  document.body.appendChild(menu);",
            "menu", "themeMenuClose", "Close the menu", ', reserve: "top"'),
    x_after("closex:say-menu", "function djSayMenu(event) {", "  document.body.appendChild(menu);",
            "menu", "djSayMenuClose", "Close the menu", ', reserve: "top"'),
    x_after("closex:hawk-menu", "function artHawkMenu(event, name) {", "  document.body.appendChild(menu);",
            "menu", "artHawkClose", "Close the menu", ', reserve: "top"'),
    x_after("closex:cal-menu", "function calMenu(e, sec, epochSecs) {", "  document.body.appendChild(m);",
            "m", "() => m.remove()", "Close the menu", ', reserve: "top"'),
    x_after("closex:crystal-del-menu", "function crystalDeleteMenu(row, x, y) {", "  document.body.appendChild(m);",
            "m", "closeMenu", "Close the menu", ', reserve: "top"'),
    x_after("closex:engine-menu", "function djHostEngineMenu(event) {", "  document.body.appendChild(box);",
            "box", '() => { box.remove(); document.removeEventListener("pointerdown", away, true); }',
            "Close the engine menu", ', reserve: "top"'),

    # -- static markup: the lightbox card and the Recent pop-ups tray
    Insert(F, "closex:lightbox", "function closeLightbox(event) {",
           '// [closex:lightbox] the lightbox card\'s corner X - static markup, so it is\n'
           '// wired once the page is parsed; closeLightbox() with no event closes it.\n'
           '(function closexLightbox() {\n'
           '  const wire = () => {\n'
           '    const card = document.querySelector("#lightbox .lb-card");\n'
           '    if (card && window.pineCloseX) window.pineCloseX(card, () => closeLightbox(),\n'
           '      {label: "Close the lightbox", sticky: true});\n'
           '  };\n'
           '  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);\n'
           '  else wire();\n'
           '})();', where="before"),
    Insert(F, "closex:tray", '  panel.style.display = showing ? "none" : "block";',
           '  if (!showing && window.pineCloseX) {   // [closex:tray] the tray\'s corner X\n'
           '    window.pineCloseX(panel, () => { if (panel.style.display !== "none") toggleTray(); },\n'
           '      {label: "Close recent pop-ups", reserve: "top"});\n'
           '  }',
           scope="function toggleTray() {"),
]

if __name__ == "__main__":
    sys.exit(main(PATCHES))
