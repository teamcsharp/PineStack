"""[s3-live-event] Station events in the System 3 window (frontend/system3.js).

  1. Controls: a "Station events" card - each registered event, its
     source, whether it is on right now and at which stage, and which
     tables carry its rows (status.events, from the runtime).
  2. Rolodex: an event card whose roll landed on a station-event row says
     so in as many words.

  python edit_mxlive_js.py [--check|--apply] path/to/frontend/system3.js

Marker-idempotent (marker: [s3-live-event]). --check: 0 ready, 2 applied,
1 anchors missing. Keeps LF endings. Run node --check afterwards; the
served import's ?v= is bumped by tools/mxlive_app_patch.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

EVENTS_CARD = (
    "    /* [s3-live-event] the station's activatable events: while one is on, its\n"
    "       rows join the wheels; off, they are invisible to the dice. */\n"
    "    const eventsCard = () => el('div', 's3-card', el('h2', {text: 'Station events'}),\n"
    "      el('p', {class: 's3-muted', text: 'An activatable event (MX Live) whose rows sit in the tables tagged "
    "with it (Tables tab: MXLIVE1, MXLIVECTS1, MXLIVETRACK1, MXLIVEID1, MXLIVEANGLE1, MXLIVECALL1). While the "
    "event is on, those rows are eligible in their wheels at their own weights; while it is off they are filtered "
    "out before any weight is computed, so no draw moves. A pinelive event follows the PineLive switch (the mic on "
    "the status bar); a roll that lands on one of its rows says so in the Rolodex.'}),\n"
    "      ((status && status.events) || []).length ? el('table', 's3-table',\n"
    "        el('thead', null, el('tr', null, ...['event', 'source', 'now', 'tables'].map(h => el('th', {text: h})))),\n"
    "        el('tbody', null, ...((status && status.events) || []).map(ev => el('tr', null,\n"
    "          el('td', null, el('b', {text: ev.name}), el('div', {class: 's3-muted', text: ev.id + (ev.what ? ' - ' + ev.what : '')})),\n"
    "          el('td', {text: ev.source}),\n"
    "          el('td', null, el('span', {class: 's3-pill ' + (ev.on ? 'active' : 'off'), text: ev.on ? (ev.stage || 'on') : 'off'})),\n"
    "          el('td', {class: 's3-muted', text: (ev.tables || []).join(', ') || 'no tables carry it'})))))\n"
    "        : para('No station events are registered.', 's3-muted'));\n")

EDITS: list[tuple[str, str, str, int]] = [
    ("controls-card-def",
     "    /* [s3-roads] every road that puts words on air, and what System 3 is for it now */\n"
     "    const roadsCard = () => el('div', 's3-card s3-roads', el('h2', {text: 'Roads'}),\n",
     EVENTS_CARD
     + "    /* [s3-roads] every road that puts words on air, and what System 3 is for it now */\n"
     "    const roadsCard = () => el('div', 's3-card s3-roads', el('h2', {text: 'Roads'}),\n", 1),

    ("controls-card-mount",
     "      roadsCard(),\n"
     "      versionsCard(),\n",
     "      eventsCard(),                                   /* [s3-live-event] */\n"
     "      roadsCard(),\n"
     "      versionsCard(),\n", 1),

    ("rolodex-badge",
     "    if (poster) card.append(el('img', {class: 's3-evposter', src: stationUrl(poster), alt: 'the clip it picked', loading: 'lazy',\n"
     "      decoding: 'async', onerror: e => { e.currentTarget.hidden = true; }}));\n",
     "    if (poster) card.append(el('img', {class: 's3-evposter', src: stationUrl(poster), alt: 'the clip it picked', loading: 'lazy',\n"
     "      decoding: 'async', onerror: e => { e.currentTarget.hidden = true; }}));\n"
     "    /* [s3-live-event] a roll that landed on a station event's row says so */\n"
     "    const evTag = (ev.meta || {}).event || (ev.selected || {}).event;\n"
     "    if (evTag) card.append(el('div', {class: 's3-muted', text: 'landed on a station-event row (' + evTag + ') "
     "- in the wheel only while that event is on'}));\n", 1),
]


def state_of(text: str, old: str, new: str, count: int) -> str:
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "frontend/system3.js")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text, "system3.js is expected LF-only"
    applied, missing = 0, []
    for name, old, new, count in EDITS:
        st = state_of(text, old, new, count)
        if st == "applied":
            applied += 1
        elif st != "ready":
            missing.append("%s (%s)" % (name, st))
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if applied == len(EDITS):
        print("already applied (%d edits)" % len(EDITS))
        return 2
    if not do_apply:
        print("ready: %d edits, %d already in" % (len(EDITS), applied))
        return 0
    for name, old, new, count in EDITS:
        if state_of(text, old, new, count) == "applied":
            continue
        text = text.replace(old, new)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
