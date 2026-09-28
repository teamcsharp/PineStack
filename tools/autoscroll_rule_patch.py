"""[autoscroll-rule] Nothing moves a scroller the operator is not following.

"do not move the page for me as far as scrolling it unless I am already
looking at the latest message. If I'm looking at the latest message, then
move to the next message in line when that message comes in, just like it
would with an instant message. But if I'm scrolling around the page looking
at different elements, then don't move the page that I'm already looking at
... And that's just in the program in general."  - the operator, 2026-09-28

The panel (CONTROL_PANEL_HTML) loads the one shared rule,
desktop/renderer/pine-stick.js, from /spark/asset/pine-stick.js (added to
_SPARK_ASSETS here), and every panel scroller that followed on its own now
goes through it: it moves only for a reader at its latest end who is not
examining something there; a reader elsewhere keeps the row they are on,
and a jump button counts what arrived. Where the panel used scrollIntoView
for a live row (the deck, the booth's live line, the Gazette shelf chip) it
now scrolls that one box only - scrollIntoView also moved the page.

Sites in CONTROL_PANEL_HTML: the music deck, boothLog, the booth transcript,
usbLog, the booth log (djTalkRender / djTalkScroll / djTalkMarkLive),
djRenderChat, the ad studio's "locate", the pipeline graph feed, the glass
(pipeline log), the wedge / fix / ComfyUI-doctor / steward consoles, the
Gazette's air log, shelf chip, maker's console and new-edition swap, the
studio console, the #1041 console's jump button, the manuals' chat rails,
and pvAnchor.

RADIO_PAGE_HTML (/radio, the desktop's radio webview, and /tune/<token>):
its plain feed (#patter) follows only a listener at its end who has no line
open, holds the line they are reading while old lines leave the top, and
counts what came on the jump button. The page loads /icons/pine-icons.js
and /spark/asset/pine-stick.js for that; the public door (:8097) gets
"/spark/asset/pine-stick.js" on _PUBLIC_GET, named exactly like sfx-tv.js
(/icons/ is already a public prefix). The tune Messenger's own follow is
System 3's (frontend/system3.js) and is not touched here.

Needs desktop/renderer/pine-stick.js on the host (the route serves it from
/app/desktop/renderer). Without it every site degrades to NOT scrolling.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only, and keeps the file's mode. ON THE HOST. Every edit writes
the [autoscroll-rule] marker.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('spark-asset-pine-stick',
     '    "wall-transition.js": "application/javascript; charset=utf-8",\n    "pinebox.png": "image/png",\n',
     '    "wall-transition.js": "application/javascript; charset=utf-8",\n    # [autoscroll-rule] the one scroll rule: the panel - and the tablet\'s\n    # views, which run inside it - load the desktop\'s own file from here.\n    "pine-stick.js": "application/javascript; charset=utf-8",\n    "pinebox.png": "image/png",\n', 1),
    ('panel-loads-pine-stick',
     '<script src="/icons/pine-icons.js"></script>\n<script src="/spark/asset/wall-transition.js"></script>\n',
     '<script src="/icons/pine-icons.js"></script>\n<script src="/spark/asset/wall-transition.js"></script>\n<!-- [autoscroll-rule] one rule for every scroller that follows: it moves only\n     for a reader at its latest end who is not examining something there. -->\n<script src="/spark/asset/pine-stick.js"></script>\n', 1),
    ('deck-watch',
     'let deckSignature = "";\n',
     '/* [autoscroll-rule] the deck scrolled off the record on air by hand = held\n   there; back on it = centred on it again as the tracks advance. */\nfunction deckWatch(host) {\n  if (host.__deckWatch) return;\n  host.__deckWatch = true;\n  host.addEventListener("scroll", () => {\n    const on = host.querySelector("[data-deck-now]");\n    if (!on) return;\n    const lip = host.getBoundingClientRect(), seat = on.getBoundingClientRect();\n    host.__deckHeld = !(seat.right > lip.left + 4 && seat.left < lip.right - 4);\n  }, {passive: true});\n}\n\nlet deckSignature = "";\n', 1),
    ('deck-follow',
     '    host.appendChild(tile);\n    // Keep the current track in view as the deck advances.\n    setTimeout(() => {\n      tile.scrollIntoView({block: "nearest", inline: "center"});\n    }, 60);\n',
     '    tile.setAttribute("data-deck-now", "1");\n    host.appendChild(tile);\n    // Keep the current track in view as the deck advances.\n    /* [autoscroll-rule] ...inside the deck only: scrollIntoView also moved\n       the page to the deck on every track change, wherever the operator was\n       reading. And only while they have not scrolled the deck off it. */\n    deckWatch(host);\n    setTimeout(() => {\n      if (host.__deckHeld || !tile.isConnected) return;\n      const lip = host.getBoundingClientRect(), seat = tile.getBoundingClientRect();\n      if (!(lip.width > 0 && seat.width > 0)) return;\n      const left = Math.max(0, host.scrollLeft\n        + (seat.left + seat.width / 2) - (lip.left + lip.width / 2));\n      if (Math.abs(left - host.scrollLeft) < 1) return;\n      try { host.scrollTo({left: left, behavior: "instant"}); }\n      catch (e) { host.scrollLeft = left; }\n    }, 60);\n', 1),
    ('booth-chat',
     '  const line = document.createElement("div");\n  line.textContent = text;\n  log.appendChild(line);\n  log.scrollTop = log.scrollHeight;\n}\n',
     '  /* [autoscroll-rule] the booth chat follows only a reader at its end */\n  const stick = window.pineStick ? window.pineStick(log, {edge: "bottom"}) : null;\n  const line = document.createElement("div");\n  line.textContent = text;\n  log.appendChild(line);\n  if (stick) stick.follow();\n}\n', 1),
    ('booth-transcript-hold',
     '    if (tr) {\n      tr.innerHTML = "";\n',
     '    if (tr) {\n      /* [autoscroll-rule] rebuilt every 4 s: its end is followed only by a\n         reader at it; one scrolled back keeps the line they were on */\n      const trStick = window.pineStick ? window.pineStick(tr, {edge: "bottom"}) : null;\n      const trHold = trStick ? trStick.anchor() : null;\n      const trLast = tr.lastElementChild ? tr.lastElementChild.textContent : "";\n      tr.innerHTML = "";\n', 1),
    ('booth-transcript-put',
     '        tr.appendChild(rowEl);\n      });\n      tr.scrollTop = tr.scrollHeight;\n    }\n',
     '        tr.appendChild(rowEl);\n      });\n      if (trStick) trStick.restore(trHold, !!trLast   // [autoscroll-rule]\n        && (tr.lastElementChild ? tr.lastElementChild.textContent : "") !== trLast);\n    }\n', 1),
    ('usb-console',
     '  // Only follow the tail if you are already at it.\n  const near = out.scrollHeight - out.scrollTop - out.clientHeight < 60;\n  while (out.childElementCount > 900) out.removeChild(out.firstChild);\n  if (near) out.scrollTop = out.scrollHeight;\n}\n',
     '  // Only follow the tail if you are already at it.\n  /* [autoscroll-rule] ...and are not examining a line in it; what arrives\n     otherwise is counted on the jump button. */\n  const stick = window.pineStick ? window.pineStick(out, {edge: "bottom", slack: 60}) : null;\n  const near = out.scrollHeight - out.scrollTop - out.clientHeight < 60;\n  while (out.childElementCount > 900) out.removeChild(out.firstChild);\n  if (stick) stick.follow();\n  else if (near) out.scrollTop = out.scrollHeight;\n}\n', 1),
    ('talk-hold',
     '  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;\n',
     '  /* [autoscroll-rule] the booth follows its end only for a reader at it who\n   * is not examining a row (text selected, a finger down, a line being\n   * edited); one reading back keeps the row they are on - measured on the\n   * row, so the #745 trim and a row replaced above them cannot slide it. */\n  const talkStick = window.pineStick\n    ? window.pineStick(log, {edge: "bottom", slack: 40, key: "data-eid", button: false}) : null;\n  const talkHold = talkStick ? talkStick.anchor() : null;\n  const atBottom = talkStick ? talkStick.following()\n    : log.scrollHeight - log.scrollTop - log.clientHeight < 40;\n', 1),
    ('talk-repaint-put',
     '    djTalkRepaint();\n    djTalkScroll(log, atBottom, keepTop);\n    return;\n',
     '    djTalkRepaint();\n    djTalkScroll(log, atBottom, keepTop, talkHold);   // [autoscroll-rule]\n    return;\n', 1),
    ('talk-paint-put',
     '  djTalkTrim(log);\n  djTalkMarkLatest();\n  djTalkScroll(log, atBottom, keepTop);\n',
     '  djTalkTrim(log);\n  djTalkMarkLatest();\n  djTalkScroll(log, atBottom, keepTop, talkHold);   // [autoscroll-rule]\n', 1),
    ('talk-scroll-sig',
     'function djTalkScroll(log, atBottom, keepTop) {\n',
     'function djTalkScroll(log, atBottom, keepTop, hold) {   // [autoscroll-rule]\n', 1),
    ('talk-scroll-restore',
     '  log.scrollTop = atBottom ? log.scrollHeight : keepTop;\n}\n',
     '  /* [autoscroll-rule] the row the reader was on, put back where it was -\n     or the end, for a reader who was following and still is */\n  if (hold && window.pineStick) { window.pineStick(log).restore(hold, false); return; }\n  log.scrollTop = atBottom ? log.scrollHeight : keepTop;\n}\n', 1),
    ('talk-live-in-log',
     '  if (found && !log._userScrolled) {\n    try { found.scrollIntoView({block: "nearest"}); } catch (e) {}\n  }\n',
     '  /* [autoscroll-rule] inside the log only - scrollIntoView also moved every\n     scroller above it, the page included, wherever the operator was - and\n     not while they are examining a row in it. */\n  if (found && !log._userScrolled && window.pineStick\n      && !window.pineStick(log, {edge: "bottom", slack: 40, key: "data-eid", button: false}).examining()) {\n    try {\n      const lip = log.getBoundingClientRect(), seat = found.getBoundingClientRect();\n      if (seat.height > 0 && lip.height > 0) {\n        if (seat.top < lip.top) log.scrollTop += seat.top - lip.top;\n        else if (seat.bottom > lip.bottom) {\n          log.scrollTop += Math.min(seat.bottom - lip.bottom, seat.top - lip.top);\n        }\n      }\n    } catch (e) {}\n  }\n', 1),
    ('dj-chat-hold',
     '  if (!host || document.getElementById("djChat").style.display === "none") return;\n  host.textContent = "";\n',
     '  if (!host || document.getElementById("djChat").style.display === "none") return;\n  /* [autoscroll-rule] rebuilt every poll: its end is followed only by a\n     reader at it; one scrolled back keeps the line they were on */\n  const chatStick = window.pineStick ? window.pineStick(host, {edge: "bottom"}) : null;\n  const chatHold = chatStick ? chatStick.anchor() : null;\n  const chatLast = host.lastElementChild ? host.lastElementChild.textContent : "";\n  host.textContent = "";\n', 1),
    ('dj-chat-put',
     '    host.appendChild(row);\n  });\n  host.scrollTop = host.scrollHeight;\n}\n',
     '    host.appendChild(row);\n  });\n  if (chatStick) chatStick.restore(chatHold, !!chatLast   // [autoscroll-rule]\n    && (host.lastElementChild ? host.lastElementChild.textContent : "") !== chatLast);\n}\n', 1),
    ('adstudio-locate-once',
     '          window.adStudioFocus = line.ad_id;\n          try { adStudioOpen(); } catch (e) {}\n',
     '          window.adStudioFocus = line.ad_id;\n          window.adStudioReveal = line.ad_id;   // [autoscroll-rule] one jump, for this click\n          try { adStudioOpen(); } catch (e) {}\n', 1),
    ('adstudio-reveal-once',
     '        if (window.adStudioFocus && a.id === window.adStudioFocus) {\n          setTimeout(() => {\n',
     '        /* [autoscroll-rule] the "locate" jump is ONE jump, for the click\n           that asked for it: the highlight stays, but a later refresh of\n           this list no longer drags the studio back to that ad. */\n        if (window.adStudioFocus && a.id === window.adStudioFocus\n            && window.adStudioReveal === a.id) {\n          window.adStudioReveal = "";\n          setTimeout(() => {\n', 1),
    ('graph-feed-hold',
     '  function drawFeed(g) {\n    const rows = [];\n',
     '  function drawFeed(g) {\n    /* [autoscroll-rule] the end follows only a reader at it */\n    const feedStick = window.pineStick ? window.pineStick(feed, {edge: "bottom"}) : null;\n    const feedCount = feed.children.length;\n    const rows = [];\n', 1),
    ('graph-feed-follow',
     '      feed.appendChild(line);\n    });\n    feed.scrollTop = feed.scrollHeight;\n  }\n',
     '      feed.appendChild(line);\n    });\n    if (feedStick && feed.children.length !== feedCount) feedStick.follow();   // [autoscroll-rule]\n  }\n', 1),
    ('glass-hold',
     '      const top = feed.scrollTop < 40;\n',
     '      /* [autoscroll-rule] newest at the top: a reader there sees the beat\n         arrive - unless examining a row (an opened payload, a selection, a\n         finger down); anyone else keeps the row they are on. */\n      const glassStick = window.pineStick ? window.pineStick(feed, {edge: "top", slack: 40,\n        examining: () => !!feed.querySelector("pre")}) : null;\n      const glassHold = glassStick && events.length ? glassStick.anchor() : null;\n      const top = feed.scrollTop < 40;\n', 1),
    ('glass-put',
     '      while (feed.children.length > 320) feed.removeChild(feed.lastChild);\n      if (top) feed.scrollTop = 0;\n',
     '      while (feed.children.length > 320) feed.removeChild(feed.lastChild);\n      if (glassHold) glassStick.restore(glassHold, true);   // [autoscroll-rule]\n      else if (top && !glassStick) feed.scrollTop = 0;\n', 1),
    ('wedge-hold',
     '  if (!term) return;\n  term.textContent = wedgeLines.length\n',
     '  if (!term) return;\n  /* [autoscroll-rule] the tail follows only a reader at it */\n  const termStick = window.pineStick ? window.pineStick(term, {edge: "bottom"}) : null;\n  const termWas = term.textContent;\n  term.textContent = wedgeLines.length\n', 1),
    ('wedge-follow',
     '  term.scrollTop = term.scrollHeight;\n}\n',
     '  if (termStick && term.textContent !== termWas) termStick.follow();   // [autoscroll-rule]\n}\n', 1),
    ('fix-say',
     'function fixSay(line) {\n  fixLines.push(String(line));\n  if (fixLines.length > 300) fixLines = fixLines.slice(-300);\n  const term = fixDrawer && fixDrawer.querySelector(".pb-fix-term");\n  if (term) {\n    term.textContent = fixLines.join("\\n");\n    term.scrollTop = term.scrollHeight;\n  }\n}\n',
     'function fixSay(line) {\n  fixLines.push(String(line));\n  const term = fixDrawer && fixDrawer.querySelector(".pb-fix-term");\n  /* [autoscroll-rule] followed, and trimmed, only while the reader is at the\n     tail: one scrolled back keeps every line where it was */\n  const termStick = term && window.pineStick ? window.pineStick(term, {edge: "bottom"}) : null;\n  if (fixLines.length > 300 && (!termStick || termStick.following())) {\n    fixLines = fixLines.slice(-300);\n  }\n  if (term) {\n    term.textContent = fixLines.join("\\n");\n    if (termStick) termStick.follow();\n  }\n}\n', 1),
    ('comfy-doctor-term',
     '    term.textContent = steps.length\n      ? steps.map((s) => stamp(s.at) + "  " + s.line).join("\\n")\n        + (d.running ? "\\n▋" : "")\n      : "no run yet — press Run, or just ask the box what\'s going on "\n        + "with ComfyUI.";\n    term.scrollTop = term.scrollHeight;\n',
     '    /* [autoscroll-rule] the tail follows only a reader at it */\n    const termStick = window.pineStick ? window.pineStick(term, {edge: "bottom"}) : null;\n    term.textContent = steps.length\n      ? steps.map((s) => stamp(s.at) + "  " + s.line).join("\\n")\n        + (d.running ? "\\n▋" : "")\n      : "no run yet — press Run, or just ask the box what\'s going on "\n        + "with ComfyUI.";\n    if (termStick) termStick.follow();\n', 1),
    ('steward-term',
     '    term.textContent = steps.length\n      ? steps.map((s) => stamp(s.at) + "  " + s.line).join("\\n")\n        + (d.running ? "\\n▋" : "")\n      : "no run yet — press Check, or just ask the box how the "\n        + "services are doing.";\n    term.scrollTop = term.scrollHeight;\n',
     '    /* [autoscroll-rule] the tail follows only a reader at it */\n    const termStick = window.pineStick ? window.pineStick(term, {edge: "bottom"}) : null;\n    term.textContent = steps.length\n      ? steps.map((s) => stamp(s.at) + "  " + s.line).join("\\n")\n        + (d.running ? "\\n▋" : "")\n      : "no run yet — press Check, or just ask the box how the "\n        + "services are doing.";\n    if (termStick) termStick.follow();\n', 1),
    ('paper-script-hold',
     '  body.innerHTML = "";\n  if (!showing) {\n',
     '  /* [autoscroll-rule] re-read every 12 s while live: the air log follows\n     its end only for a reader at it; one reading back keeps their line */\n  const scrStick = window.pineStick ? window.pineStick(body, {edge: "bottom"}) : null;\n  const scrHold = scrStick && quiet ? scrStick.anchor() : null;\n  body.innerHTML = "";\n  if (!showing) {\n', 1),
    ('paper-script-put',
     '  if (!paperScriptHour) body.scrollTop = body.scrollHeight;\n}\n',
     '  if (scrHold) scrStick.restore(scrHold, false);   // [autoscroll-rule]\n  else if (!paperScriptHour) body.scrollTop = body.scrollHeight;\n}\n', 1),
    ('paper-chip-shelf-only',
     '    if (chip && chip.scrollIntoView) chip.scrollIntoView({inline: "nearest", block: "nearest"});\n',
     '    /* [autoscroll-rule] along the shelf only: scrollIntoView also moved\n       every scroller above it, the page included */\n    if (chip && paperShelf) {\n      const lip = paperShelf.getBoundingClientRect(), seat = chip.getBoundingClientRect();\n      if (seat.left < lip.left) paperShelf.scrollLeft += seat.left - lip.left;\n      else if (seat.right > lip.right) paperShelf.scrollLeft += seat.right - lip.right;\n    }\n', 1),
    ('paper-console-stick',
     'function paperPaintConsole(d) {\n  if (!paperConsole) return;\n',
     'function paperPaintConsole(d) {\n  if (!paperConsole) return;\n  /* [autoscroll-rule] the maker\'s last lines follow only a reader at them */\n  const pcStick = window.pineStick\n    ? window.pineStick(paperConsole, {edge: "bottom", button: false}) : null;\n', 1),
    ('paper-console-running',
     '    paperConsole.textContent = steps.slice(-8).map((s) => stamp(s.at) + "  " + s.line).join("\\n") + "\\n▋";\n    paperConsole.scrollTop = paperConsole.scrollHeight;\n',
     '    paperConsole.textContent = steps.slice(-8).map((s) => stamp(s.at) + "  " + s.line).join("\\n") + "\\n▋";\n    if (pcStick) pcStick.follow();   // [autoscroll-rule]\n', 1),
    ('paper-console-done',
     '      + (d.verdict ? "\\n— " + d.verdict : "");\n    paperConsole.scrollTop = paperConsole.scrollHeight;\n',
     '      + (d.verdict ? "\\n— " + d.verdict : "");\n    if (pcStick) pcStick.follow();   // [autoscroll-rule]\n', 1),
    ('paper-reading-down',
     'async function paperPoll() {\n  if (!paperBox) return;\n',
     '/* [autoscroll-rule] a reader who has started down the edition on screen. */\nfunction paperReadingDown() {\n  try {\n    const w = paperFrame && paperFrame.contentWindow;\n    const doc = w && w.document;\n    const top = doc && doc.scrollingElement ? doc.scrollingElement.scrollTop\n      : (w ? w.scrollY : 0);\n    return top > 40;\n  } catch (e) { return false; }\n}\n\nasync function paperPoll() {\n  if (!paperBox) return;\n', 1),
    ('paper-new-edition-waits',
     '    if (wasLatest && !d.running && paperList[0] && paperList[0].id !== paperCur) {\n',
     '    /* [autoscroll-rule] a new edition replaces the page only for a reader\n       who has not started down the one on screen; otherwise it waits on the\n       shelf, where its chip already is, until they choose it. */\n    if (wasLatest && !d.running && paperList[0] && paperList[0].id !== paperCur\n        && !paperReadingDown()) {\n', 1),
    ('studio-console',
     '  body.innerHTML = html;\n  const log = body.lastChild;\n  if (log) log.scrollTop = log.scrollHeight;\n}\n',
     '  /* [autoscroll-rule] the log is rebuilt with the body: its place is\n     carried across - the tail for a reader at it, their line otherwise */\n  const oldLog = body.lastChild && body.lastChild.nodeType === 1 ? body.lastChild : null;\n  const logHold = oldLog && window.pineStick\n    ? window.pineStick.hold(oldLog, {edge: "bottom"}) : null;\n  body.innerHTML = html;\n  const log = body.lastChild;\n  if (log && logHold) window.pineStick.put(log, logHold, {edge: "bottom"}, false);\n  else if (log && !oldLog) log.scrollTop = log.scrollHeight;\n}\n', 1),
    ('console-jump-fn',
     'function trimAndScrollConsole(feed) {\n',
     '/* [autoscroll-rule] the console\'s way back to its tail is the shared jump\n   button - which also lifts the hold a hand put on the feed - not a timer. */\nfunction consoleJump(feed) {\n  if (!feed || !window.pineStick) return null;\n  return window.pineStick(feed, {edge: "bottom", slack: 24,\n    onJump: () => { consoleStuck = true; consoleTouched = 0; }});\n}\n\nfunction trimAndScrollConsole(feed) {\n', 1),
    ('console-note',
     '      while (feed.children.length > 400) feed.removeChild(feed.firstChild);\n      return;\n    }\n',
     '      while (feed.children.length > 400) feed.removeChild(feed.firstChild);\n      const jump = consoleJump(feed);   // [autoscroll-rule]\n      if (jump) jump.note(1);\n      return;\n    }\n', 1),
    ('rail-log-stick',
     'function buildChatRail(getDoc, getPage) {\n  const rail = el("div", "pv-chat");\n  const log = el("div", "pv-chat-log");\n',
     'function buildChatRail(getDoc, getPage) {\n  const rail = el("div", "pv-chat");\n  const log = el("div", "pv-chat-log");\n  /* [autoscroll-rule] made with the log, so it knows where the reader is */\n  const logStick = window.pineStick ? window.pineStick(log, {edge: "bottom"}) : null;\n', 1),
    ('rail-answer',
     '    pvChatBusy = false;\n    log.scrollTop = log.scrollHeight;\n  }\n',
     '    pvChatBusy = false;\n    /* [autoscroll-rule] the answer lands seconds after the question: it is\n       followed only by a reader still at the end of the conversation */\n    if (logStick) logStick.follow();\n  }\n', 1),
    ('popup-log-stick',
     '  chat.style.cssText = "flex:0 0 190px;border-left:0;border-top:1px solid var(--border)";\n  const log = el("div", "pv-chat-log");\n',
     '  chat.style.cssText = "flex:0 0 190px;border-left:0;border-top:1px solid var(--border)";\n  const log = el("div", "pv-chat-log");\n  /* [autoscroll-rule] made with the log, so it knows where the reader is */\n  const logStick = window.pineStick ? window.pineStick(log, {edge: "bottom"}) : null;\n', 1),
    ('popup-answer',
     '    wait.textContent = res.answer || "(no answer)";\n    log.scrollTop = log.scrollHeight;\n    renderSide(res);\n',
     '    wait.textContent = res.answer || "(no answer)";\n    if (logStick) logStick.follow();   /* [autoscroll-rule] as in buildChatRail */\n    renderSide(res);\n', 1),
    ('pv-anchor',
     'function pvAnchor(scroller, add) {\n  let was = 0, top = 0, ok = false;\n',
     'function pvAnchor(scroller, add) {\n  /* [autoscroll-rule] the rows land at the top of a list INSIDE this\n   * scroller; adding their height whenever it was not at its top pushed the\n   * reader\'s line up by that much whenever the list sat below it. The place\n   * is now measured on what is under the eye and put back there. */\n  const pvStick = scroller && window.pineStick\n    ? window.pineStick(scroller, {edge: "top", slack: 0, button: false}) : null;\n  if (pvStick) {\n    try { pvStick.keep(add, false); } catch (e) { /* one bad row must not stop the rest */ }\n    return;\n  }\n  let was = 0, top = 0, ok = false;\n', 1),
    ('tune-public-door',
     '               "/spark/asset/slideshow.css",   # #1415,\n',
     '               "/spark/asset/slideshow.css",   # #1415,\n               # [autoscroll-rule] the one scroll rule the tune page\'s\n               # feed follows by - public client code, named exactly.\n               "/spark/asset/pine-stick.js",\n', 1),
    ('tune-loads-pine-stick',
     '<link rel="stylesheet" href="/spark/asset/slideshow.css">\n<script src="/spark/asset/sfx-tv.js"></script>\n',
     '<link rel="stylesheet" href="/spark/asset/slideshow.css">\n<script src="/spark/asset/sfx-tv.js"></script>\n<!-- [autoscroll-rule] the feed follows only a reader at its end; its way\n     back is a Carbon jump button (pine-icons.js draws the icon). -->\n<script src="/icons/pine-icons.js"></script>\n<script src="/spark/asset/pine-stick.js"></script>\n', 1),
    ('tune-patter-wrap',
     '/* #1472c: "if a message is tapped by a listener, then animate the Rolodex\n',
     '/* [autoscroll-rule] THE FEED FOLLOWS ONLY A READER AT ITS END. patter()\n   keeps a listener at the end of the feed when they are near it; this adds\n   the rest of the one rule (desktop/renderer/pine-stick.js): a listener with\n   a line open (tapped, replaying), words selected or a finger down is\n   examining it and nothing moves; one reading back keeps the line they are\n   on while the oldest lines leave the top; what arrives meanwhile is counted\n   on the jump button. It wraps patter() from outside, because patter() is\n   System 3\'s own text (tools/system3_patch_app.py). No helper, no change. */\npatter = (function (plain) {\n  return function (state) {\n    const host = document.getElementById("patter");\n    const stick = host && window.pineStick ? window.pineStick(host, {edge: "bottom", slack: 48,\n      key: "data-key", examining: () => !!host.querySelector(\'[aria-expanded="true"]\')}) : null;\n    if (!stick) return plain(state);\n    const hold = stick.anchor();\n    const had = new Set(Array.from(host.children, (n) => n.dataset.key));\n    try { return plain(state); }\n    finally {\n      stick.restore(hold, Array.from(host.children).filter((n) => !had.has(n.dataset.key)).length);\n    }\n  };\n})(patter);\n\n/* #1472c: "if a message is tapped by a listener, then animate the Rolodex\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
