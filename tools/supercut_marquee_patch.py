#!/usr/bin/env python3
"""[supercut-marquee] Every saved supercut scrolls along the top of the Supercut studio. 2026-10-06.

"At the top of the Supercut studio I want a scrolling marquee of all the Supercut ads
that have been made so far where I'm able to tap on one and select which one I want to
view and be able to reuse the prompt for creating additional ones."

The studio (desktop/renderer/supercut-review.js, mirrored to the tablet's pine-views)
listed the archive only as a paged grid at the bottom. Now a marquee sits under the
studio's title: every archived supercut (newest first, the first hundred), as cards
that drift left on their own and loop seamlessly (the row is laid twice), pause while
the pointer is over them or for a few seconds after a touch, wheel or tap, and scroll
by hand on the tablet. Tapping a card selects it and opens it in "Selected supercut"
(the player, the written script, Add to reusable ads); its "Reuse prompt" button
fetches the full row and puts the product and the script into the custom editor,
which opens and scrolls into view, with a status line saying so. The marquee reloads
with the library's Refresh and stops its animation when the studio is disposed.
Both copies of the two files.

Usage:  supercut_marquee_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        supercut_marquee_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

MARQUEE_OLD = '''    panel.appendChild(intro);
'''
MARQUEE_NEW = '''    panel.appendChild(intro);
    /* [supercut-marquee] every saved supercut, newest first, drifting along the top of the studio: tap one to
       view it below, or take its prompt into the editor to make another */
    var marquee = make('div', 'psc-marquee'); marquee.setAttribute('aria-label', 'Saved supercuts'); panel.appendChild(marquee);
    var marqueeTrack = make('div', 'psc-marquee-track'); marquee.appendChild(marqueeTrack);
    var marqueeNote = make('span', 'psc-marquee-note', ''); marquee.appendChild(marqueeNote);
    var marqueeRows = [], marqueeHold = 0, marqueeRaf = 0, marqueeLast = 0, marqueeSelected = '';
    function marqueeCard(row) {
      var card = make('div', 'psc-marquee-card'); card.dataset.id = row.id;
      var view = make('button', 'psc-marquee-view'); view.type = 'button'; view.setAttribute('aria-label', 'View ' + (row.product || row.title || 'supercut'));
      var when = new Date(Number(row.created_at || 0) * 1000);
      view.append(make('b', '', row.product || row.title || 'Supercut'),
        make('span', '', Number(row.seconds || 0).toFixed(1) + 's' + (row.kind === 'video' ? ' video' : ' audio') + ' - ' + when.toLocaleDateString([], {month: 'numeric', day: 'numeric'}) + ' ' + when.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})));
      view.addEventListener('click', function () { marqueeSelected = row.id; marqueeMark(); marqueeHold = Date.now() + 12000; loadArchive(row.id); });
      card.appendChild(view);
      var reuse = make('button', 'psc-marquee-reuse', 'Reuse prompt'); reuse.type = 'button'; reuse.title = 'Put this supercut\\'s product and script into the editor to make another';
      reuse.addEventListener('click', function (ev) {
        ev.stopPropagation(); marqueeHold = Date.now() + 12000;
        get('/api/sfx/supercut/archive/' + encodeURIComponent(row.id)).then(function (full) {
          if (dead) return; recallPrompt(full);
          say('The prompt of "' + (full.product || full.title || 'this supercut') + '" is in the editor - change what you like and make another.');
          try { editor.open = true; editor.scrollIntoView({behavior: 'smooth', block: 'start'}); } catch (e) { /* no scroll here */ }
        }).catch(function (e) { say(e.message || e); });
      });
      card.appendChild(reuse);
      return card;
    }
    function marqueeMark() { Array.prototype.forEach.call(marqueeTrack.children, function (c) { c.classList.toggle('selected', c.dataset.id === marqueeSelected); }); }
    function marqueeStep(now) {
      marqueeRaf = root.requestAnimationFrame(marqueeStep);
      var dt = Math.min(0.1, (now - (marqueeLast || now)) / 1000); marqueeLast = now;
      if (Date.now() < marqueeHold || marquee.matches(':hover') || !marqueeRows.length) return;
      var half = marqueeTrack.scrollWidth / 2; if (half <= marqueeTrack.clientWidth) return;
      marqueeTrack.scrollLeft += 28 * dt; if (marqueeTrack.scrollLeft >= half) marqueeTrack.scrollLeft -= half;
    }
    function loadMarquee() {
      return get('/api/sfx/supercut/archive?summary=true&limit=100&offset=0').then(function (got) {
        if (dead) return; marqueeRows = got.rows || []; marqueeTrack.replaceChildren();
        marqueeNote.textContent = marqueeRows.length ? String(got.total || marqueeRows.length) + ' supercuts made so far - tap one to view it, or reuse its prompt' : 'No supercuts made yet - the first one lands here';
        marqueeRows.forEach(function (row) { marqueeTrack.appendChild(marqueeCard(row)); });
        if (marqueeRows.length > 2) marqueeRows.forEach(function (row) { marqueeTrack.appendChild(marqueeCard(row)); });   /* laid twice, so the loop is seamless */
        marqueeMark(); if (!marqueeRaf) marqueeRaf = root.requestAnimationFrame(marqueeStep);
      }).catch(function (e) { if (!dead) marqueeNote.textContent = 'The saved supercuts could not be read: ' + (e.message || e); });
    }
    ['pointerdown', 'touchstart', 'wheel', 'focusin'].forEach(function (ev) { marqueeTrack.addEventListener(ev, function () { marqueeHold = Date.now() + 8000; }, {passive: true}); });
    loadMarquee();
'''

REFRESH_OLD = '''    button(libraryBar, 'Refresh', function (b) { run(b, function () { archiveOffset = 0; return loadLibrary(); }); });
'''
REFRESH_NEW = '''    button(libraryBar, 'Refresh', function (b) { run(b, function () { archiveOffset = 0; return Promise.all([loadLibrary(), loadMarquee()]); }); });   /* [supercut-marquee] */
'''

DISPOSE_OLD = '''      dispose: function () { dead = true; root.clearInterval(pollTimer); stop(audio); panel.remove(); }};
'''
DISPOSE_NEW = '''      dispose: function () { dead = true; root.clearInterval(pollTimer); if (marqueeRaf) root.cancelAnimationFrame(marqueeRaf); stop(audio); panel.remove(); }};   /* [supercut-marquee] */
'''

CSS_OLD = '''video.psc-audio{aspect-ratio:16/9;max-height:50vh;object-fit:contain;background:#000;}
'''
CSS_NEW = '''video.psc-audio{aspect-ratio:16/9;max-height:50vh;object-fit:contain;background:#000;}

/* [supercut-marquee] every saved supercut along the top of the studio */
.psc-marquee{display:flex;flex-direction:column;gap:4px;min-width:0}
.psc-marquee-track{display:flex;gap:8px;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;padding:2px 2px 6px;-webkit-overflow-scrolling:touch}
.psc-marquee-track::-webkit-scrollbar{display:none}
.psc-marquee-card{flex:0 0 auto;display:flex;flex-direction:column;gap:5px;width:188px;padding:8px 10px;border:1px solid #3b5862;border-radius:6px;background:linear-gradient(180deg,#19303a,#101d24)}
.psc-marquee-card.selected{border-color:#8de1ed;box-shadow:0 0 0 1px #8de1ed inset}
.psc-marquee-view{all:unset;cursor:pointer;display:flex;flex-direction:column;gap:3px;min-width:0;color:#e6f2f4}
.psc-marquee-view:focus-visible{outline:1px solid #8de1ed;outline-offset:2px}
.psc-marquee-view b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#8de1ed}
.psc-marquee-view span{font-size:11px;color:#9eb8c2}
.psc-marquee-reuse{align-self:flex-start;padding:4px 8px;border:1px solid #45616b;border-radius:4px;background:#20353e;color:#e6f2f4;font:12px system-ui;cursor:pointer}
.psc-marquee-reuse:hover{border-color:#8de1ed}
.psc-marquee-note{font-size:12px;color:#9eb8c2}
body.pine-pip .psc-marquee-card{width:150px}
'''

JS_EDITS = [
    ("the marquee under the title", MARQUEE_OLD, MARQUEE_NEW, 1),
    ("Refresh reloads it", REFRESH_OLD, REFRESH_NEW, 1),
    ("dispose stops it", DISPOSE_OLD, DISPOSE_NEW, 1),
]
CSS_EDITS = [("the marquee's style", CSS_OLD, CSS_NEW, 1)]

EDITS = {
    "desktop/renderer/supercut-review.js": JS_EDITS,
    "desktop/renderer/supercut-review.css": CSS_EDITS,
    "app/src/main/assets/pine-views/supercut-review.js": JS_EDITS,
    "app/src/main/assets/pine-views/supercut-review.css": CSS_EDITS,
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
                print("%-72s applied" % (name[-28:] + ": " + label)[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % (name[-28:] + ": " + label)[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % ((name[-28:] + ": " + label)[:72], n, want))
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
        tmp = path.with_suffix(path.suffix + ".marquee.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
