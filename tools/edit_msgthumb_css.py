#!/usr/bin/env python3
"""[msgthumb] script-page.css: the clip's thumbnail / looping video box, the transparent LED meter,
the record's album art and its in-bubble transparent visualizer row (overrides [msgviz]'s absolute
black box). Appended after [msgviz]'s rule.

Targets: desktop/renderer/script-page.css and app/src/main/assets/pine-views/script-page.css.

  python edit_msgthumb_css.py --check <file>   exit 0 ready / 2 already applied / 1 missing (prints which)
  python edit_msgthumb_css.py --apply <file>
Marker-idempotent; CRLF-aware (normalised to LF to match, written back as found);
all anchors must be present exactly once or nothing is written.
"""
import os
import sys
import tempfile

NEEDS = []
EDITS = [('C1', 'after', '.sp-mv-viz { position: absolute; right: 14px; top: 8px; width: 138px; height: 40px; border-radius: 6px; background: #05080b; }\n', "/* [msgthumb] THE CLIP'S PICTURE AND THE RECORD'S. An MP4: its thumbnail, then\n   the clip itself muted and looping, in the bubble. An MP3: the LED meter on\n   the bubble itself - no box, no black. The record: album art at the left,\n   inside the bubble; its visualizer a transparent row under the title,\n   inside the bubble's content box (no longer an absolute black box). */\n.sp-mv-media.is-video { height: 132px; }\n.sp-mv-media.is-probe { height: 44px; background: transparent; border-color: transparent; }\n.sp-mv-media.is-audio { height: 44px; background: transparent; border-color: transparent; border-radius: 0; overflow: hidden; }\n.sp-mv-media .sp-mv-led { position: absolute; inset: 0; width: 100%; height: 100%; display: block; background: transparent; }\n.sp-mv-past .sp-mv-media.is-video { height: 72px; }\n.sp-mv-past .sp-mv-media.is-audio { height: 22px; opacity: .8; }\n/* a short pane: the thumbnail / video as a tile at the bubble's left, beside the roll */\n.sp-mv-bubble.sp-mv-side { min-width: min(440px, 100%); padding-left: 178px; min-height: 108px; }\n.sp-mv-side > .sp-mv-media.is-video, .sp-mv-side > .sp-mv-media.is-probe {\n  position: absolute; left: 10px; top: 10px; bottom: 10px; width: 158px; height: auto; margin: 0; border-radius: 12px;\n}\n.sp-mv-side > .sp-mv-media.is-audio { height: 30px; }\n.sp-mv-past .sp-mv-bubble.sp-mv-side { padding-left: 96px; min-height: 58px; }\n.sp-mv-past .sp-mv-side > .sp-mv-media.is-video { width: 76px; height: auto; }\n.sp-mv-has-viz .sp-mv-bubble { padding-right: 13px; }\n.sp-mv-vizrow { position: relative; display: block; width: 100%; height: 40px; margin-top: 6px; overflow: hidden; background: transparent; }\n.sp-mv-vizrow .sp-mv-viz { position: static; display: block; width: 100%; height: 100%; border-radius: 0; background: transparent; }\n.sp-mv-past .sp-mv-vizrow { height: 22px; opacity: .8; }\n.sp-mv-has-art .sp-mv-bubble { padding-left: 88px; min-height: 88px; }\n.sp-mv-art { position: absolute; left: 12px; top: 12px; width: 64px; height: 64px; object-fit: cover; border-radius: 10px; background: #0c1318; }\n.sp-mv-past .sp-mv-art { left: 10px; top: 8px; width: 34px; height: 34px; border-radius: 7px; }\n.sp-mv-past.sp-mv-has-art .sp-mv-bubble { padding-left: 54px; min-height: 50px; }\n", '[msgthumb] THE CLIP')]


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
