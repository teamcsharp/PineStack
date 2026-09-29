#!/usr/bin/env python3
"""[msgroll] script-page.css: the roll sheet (sp-rr-*) and the results screen. Inserted before
[msgthumb]'s rules. Targets: desktop/renderer/script-page.css and
app/src/main/assets/pine-views/script-page.css, AFTER edit_msgthumb_css.py.

  python edit_msgroll_css.py --check <file>   exit 0 ready / 2 already applied / 1 missing (prints which)
  python edit_msgroll_css.py --apply <file>
Marker-idempotent; CRLF-aware (normalised to LF to match, written back as found);
all anchors must be present exactly once or nothing is written.
"""
import os
import sys
import tempfile

NEEDS = ["[msgthumb] THE CLIP'S PICTURE AND THE RECORD'S."]
EDITS = [('R1', 'before', "/* [msgthumb] THE CLIP'S PICTURE AND THE RECORD'S.", "/* [msgroll] THE ROLL, TABLE BY TABLE: the table rolls in, the category die and its\n   wheel, the indented sub-result die and its wheel, pop, next; the results screen\n   the Result tab flips any bubble back to. */\n.sp-rr { display: flex; flex-direction: column; gap: 4px; margin: 6px 0 2px; }\n.sp-rr-t { display: flex; flex-direction: column; gap: 3px; padding: 4px 6px; border-left: 3px solid var(--fam, #68ced9); border-radius: 6px; background: rgba(255, 255, 255, .03); }\n.sp-rr-t.arriving { transform: translateY(4px); }\n.sp-rr-head { display: flex; align-items: baseline; gap: 8px; font-size: 11px; letter-spacing: .05em; }\n.sp-rr-head b { color: var(--fam, #68ced9); }\n.sp-rr-head span { color: var(--sp-muted, #8fa0ad); letter-spacing: 0; }\n.sp-rr-step { display: flex; align-items: center; gap: 8px; min-width: 0; }\n.sp-rr-sub { margin-left: 18px; padding-left: 8px; border-left: 2px solid var(--fam, #68ced9); }\n.sp-rr-die {\n  flex: none; min-width: 32px; height: 24px; display: inline-grid; place-items: center; box-sizing: border-box;\n  border: 2px solid var(--fam, #68ced9); border-radius: 6px; font: 700 12px ui-monospace, Consolas, monospace; color: #fff; background: #0c1318;\n}\n.sp-rr-die.rolling { transform: rotate(-8deg); }\n.sp-rr-wheel {\n  position: relative; flex: 1; min-width: 90px; height: 24px; overflow: hidden; box-sizing: border-box;\n  border: 2px solid #4b5b67; border-radius: 6px; background: #0c1318;\n}\n.sp-rr-wheel::after { content: ''; position: absolute; left: 0; right: 0; top: 50%; height: 1px; background: rgba(255, 255, 255, .12); }\n.sp-rr-wheel.spinning { border-color: var(--fam, #68ced9); }\n.sp-rr-wheel.pop { transform: scale(1.06); border-color: #fff; box-shadow: 0 0 0 2px var(--fam, #68ced9); }\n.sp-rr-list { position: absolute; left: 0; right: 0; top: 0; will-change: transform; }\n.sp-rr-cell { display: block; padding: 0 8px; box-sizing: border-box; font-size: 12px; color: #b9c9d2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-bottom: 1px solid rgba(255, 255, 255, .05); }\n.sp-rr-cell.hit { color: #fff; font-weight: 700; }\n.sp-rr-of { flex: none; font-style: normal; font-size: 10.5px; color: var(--sp-muted, #8fa0ad); }\n.sp-rr-line { display: none; font-size: 11.5px; color: #cfe3ea; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }\n.sp-rr-t.folded { opacity: .65; }\n.sp-rr-t.folded .sp-rr-step, .sp-rr-t.folded .sp-rr-head { display: none !important; }\n.sp-rr-t.folded .sp-rr-line { display: block; }\n.sp-rr-line { align-items: baseline; gap: 6px; }\n.sp-rr-t.folded .sp-rr-line { display: flex; }\n.sp-rr-line b { color: var(--fam, #68ced9); font-size: 10.5px; letter-spacing: .05em; }\n.sp-rr-line i { font-style: normal; color: var(--sp-muted, #8fa0ad); }\n.sp-rr-ld { font: 700 10.5px ui-monospace, Consolas, monospace; color: #fff; border: 1px solid #4b5b67; border-radius: 4px; padding: 0 4px; }\n.sp-rr.results .sp-rr-t { opacity: 1; padding: 2px 6px; }\n.sp-mv-results .sp-mv-text, .sp-mv-results .sp-mv-media, .sp-mv-results .sp-mv-clipwhy, .sp-mv-results .sp-mv-load, .sp-mv-results .sp-mv-seed { display: none !important; }\n.sp-mv-past.sp-mv-results { opacity: 1; }\n.sp-mv-past.sp-mv-results .sp-mv-rolls { display: flex !important; }\n", '[msgroll] THE ROLL, TABLE BY TABLE')]


def state(text):
    done, ready, missing = [], [], []
    for name, kind, anchor, new, mark in EDITS:
        if mark in text:
            done.append(name)
        elif text.count(anchor) == 1:
            ready.append(name)
        else:
            missing.append('%s (anchor x%d)' % (name, text.count(anchor)))
    return done, ready, missing


def main(argv):
    apply = '--apply' in argv
    paths = [a for a in argv if not a.startswith('--')]
    if len(paths) != 1:
        print(__doc__)
        return 1
    path = paths[0]
    raw = open(path, 'rb').read().decode('utf-8')
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n') if crlf else raw
    for need in NEEDS:
        if need not in text:
            print('MISSING: needs %s applied first' % need)
            return 1
    done, ready, missing = state(text)
    if not ready and not missing:
        print('already applied (%s)' % ', '.join(done))
        return 2
    if missing:
        print('MISSING: ' + ', '.join(missing))
        return 1
    if done:
        print('PARTIAL: applied %s, ready %s - refusing' % (done, ready))
        return 1
    if not apply:
        print('ready: ' + ', '.join(ready))
        return 0
    for name, kind, anchor, new, mark in EDITS:
        assert text.count(anchor) == 1, name
        if kind == 'before':
            text = text.replace(anchor, new + anchor)
        elif kind == 'after':
            text = text.replace(anchor, anchor + new)
        else:
            text = text.replace(anchor, new)
        assert mark in text, name
    done, ready, missing = state(text)
    assert not ready and not missing, (ready, missing)
    out = text.replace('\n', '\r\n') if crlf else text
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix='.part')
    with os.fdopen(fd, 'wb') as fh:
        fh.write(out.encode('utf-8'))
    os.replace(tmp, path)
    print('APPLIED %d edits (%s)' % (len(EDITS), 'CRLF' if crlf else 'LF'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
