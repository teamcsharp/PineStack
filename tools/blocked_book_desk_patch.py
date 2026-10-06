#!/usr/bin/env python3
"""[blocked-book] The Works gets its second tab on the desk. 2026-10-06.

desktop/renderer/renderer.js: initWorksPopup.open() grows a tab strip - "the
rooms" (the flow as it was) and "blocked N" - and a second pane where
PineBlockedBook (desktop/renderer/blocked-book.js) mounts; the close button
stops the book's clock. desktop/renderer/index.html loads the module and its
stylesheet beside the Gazette view's.

Usage:  blocked_book_desk_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        blocked_book_desk_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

TABS_OLD = '''    pop.appendChild(head);
    pop.appendChild(mk("div", "wk-sub",
      "Every round is written, banked, recorded and stacked before it "
      + "goes out. This is where each one is right now."));
'''
TABS_NEW = '''    pop.appendChild(head);
    /* [blocked-book] THE SECOND TAB. "At the top of The Works put a 2nd tab that
     * shows each and every blocked listing" - the rooms as they were, and the
     * blocked book (blocked-book.js over GET /api/blocked) beside them. */
    const tabs = mk("div", "wk-tabs");
    const tabRooms = mk("button", "wk-tab on", "the rooms");
    const tabBlocked = mk("button", "wk-tab", "blocked");
    const wkBadge = mk("span", "wk-badge", "");
    tabBlocked.appendChild(wkBadge);
    tabs.appendChild(tabRooms);
    tabs.appendChild(tabBlocked);
    pop.appendChild(tabs);
    pop.appendChild(mk("div", "wk-sub",
      "Every round is written, banked, recorded and stacked before it "
      + "goes out. This is where each one is right now."));
'''

BODY_OLD = '''    const body = mk("div", "wk-flow-wrap");
    pop.appendChild(body);
    document.body.appendChild(pop);
'''
BODY_NEW = '''    const body = mk("div", "wk-flow-wrap");
    pop.appendChild(body);
    /* [blocked-book] the second pane, mounted on first look and kept */
    const bookHost = mk("div", "wk-flow-wrap wk-book");
    bookHost.style.display = "none";
    pop.appendChild(bookHost);
    const showTab = (which) => {
      const rooms = which !== "blocked";
      tabRooms.classList.toggle("on", rooms);
      tabBlocked.classList.toggle("on", !rooms);
      body.style.display = rooms ? "" : "none";
      bookHost.style.display = rooms ? "none" : "";
      if (!rooms && !pop.wkBook && window.PineBlockedBook) {
        pop.wkBook = window.PineBlockedBook.mount(bookHost, {
          get: (p) => api.get(p), always: true,
          openRound: () => { try { if (typeof window.pineShow3JS === "function") window.pineShow3JS("sys3"); } catch (e) { /* no window here */ } },
        });
      }
      try { localStorage.setItem("wkTab", rooms ? "rooms" : "blocked"); } catch (e) { /* no storage */ }
    };
    tabRooms.onclick = () => showTab("rooms");
    tabBlocked.onclick = () => showTab("blocked");
    const wkBadgeTick = () => api.get("/api/blocked?limit=1&standing=1&history=1").then((b) => {
      const sys = (b && b.counts && b.counts.system) || {};
      const n = Object.keys(sys).reduce((a, k) => a + (Number(sys[k]) || 0), 0);
      wkBadge.textContent = n ? String(n) : "";
      tabBlocked.title = b && b.say ? b.say : "every blocked case the ledgers hold";
    }).catch(() => {});
    wkBadgeTick();
    pop.wkBadgePoll = setInterval(wkBadgeTick, 15000);
    try { if (localStorage.getItem("wkTab") === "blocked") showTab("blocked"); } catch (e) { /* no storage */ }
    document.body.appendChild(pop);
'''

CLOSE_OLD = '''      try { if (pop.wkBriefPoll) clearInterval(pop.wkBriefPoll); } catch (e) {}
      close();
'''
CLOSE_NEW = '''      try { if (pop.wkBriefPoll) clearInterval(pop.wkBriefPoll); } catch (e) {}
      try { if (pop.wkBadgePoll) clearInterval(pop.wkBadgePoll); if (pop.wkBook) pop.wkBook.close(); } catch (e) { /* [blocked-book] */ }
      close();
'''

CSS_OLD = '''  <link rel="stylesheet" href="./gazette-view.css">
'''
CSS_NEW = '''  <link rel="stylesheet" href="./gazette-view.css">
  <link rel="stylesheet" href="./blocked-book.css">  <!-- [blocked-book] -->
'''

JS_OLD = '''  <script src="./gazette-view.js"></script>
'''
JS_NEW = '''  <script src="./gazette-view.js"></script>
  <script src="./blocked-book.js"></script>  <!-- [blocked-book] the second tab of The Works -->
'''

EDITS = {
    "desktop/renderer/renderer.js": [
        ("The Works grows a tab strip", TABS_OLD, TABS_NEW, 1),
        ("...and a second pane for the blocked book", BODY_OLD, BODY_NEW, 1),
        ("...whose clock stops with the window", CLOSE_OLD, CLOSE_NEW, 1),
    ],
    "desktop/renderer/index.html": [
        ("the book's stylesheet loads with the Gazette's", CSS_OLD, CSS_NEW, 1),
        ("the book's module loads with the Gazette view", JS_OLD, JS_NEW, 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".bbook.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
