#!/usr/bin/env python3
"""[seg-names] THE SCRIPT'S ROUND CARDS CARRY THE OPERATOR'S SEGMENT NAMES - the page.

"these should be named after the segment names I assigned to the station."

A scene heading (a round card) from /api/screenplay now carries `slot`:
{label, id, entry, how} when its round names the running-order entry it
filled (seg_names_app_patch.py), {none, why} when its round is known to have
none. The card's title becomes the entry's own name ("Painting selling"),
the old road title drops to the small line under it ("Studio Banter ·
Pine Box FM"); a round with no entry keeps its road title with a quiet
"(no slot)". A heading whose round is not written down yet reads as before.

Anchors (kept away from the line popup's tab row and the base bar):
  script-page.js  SCENE_NAMES/sceneName/dressScene  (~15346-15400)
                  linearAgainNode's derived item + print (~15772-15775)
                  the server-row print (~15866-15869)
  script-page.css appended at the end

Usage: seg_names_script_page_patch.py --check|--apply DIR [DIR ...]
  DIR holds script-page.js and script-page.css (desktop/renderer and the
  kiosk mirror app/src/main/assets/pine-views). --check exits 0 ready,
  2 applied, 1 anchors missing. CRLF-aware: each file keeps its newlines.
"""
from __future__ import annotations

import os
import sys
import tempfile

MARK = "[seg-names]"

JS_EDITS = [
    ("helpers",
     '''  function dressScene(node, item) {
''',
     '''  /* [seg-names] THE ENTRY THE ROUND FILLED, BY THE OPERATOR'S OWN NAME.
     "these should be named after the segment names I assigned to the
     station." The server names it from the round's own link (reserved,
     shelved, on its entry, banked for) - never from the clock. */
  function sceneSlot(item) {
    var slot = item && item.slot;
    if (!slot || typeof slot !== 'object') return {};
    return slot;
  }

  function sceneSlotKey(item) {
    var slot = sceneSlot(item);
    return slot.label ? 'L' + slot.label : (slot.none ? 'none' : '');
  }

  var SLOT_HOW = {
    stacked: 'reserved for this entry',
    shelf: 'aired from the shelf inside this entry',
    'on its entry': 'aired while this entry was on',
    banked: 'written for this entry'
  };

  function dressScene(node, item) {
'''),
    ("title",
     '''    words.appendChild(make('b', 'sp-segment-name', sceneName(item)));
    words.appendChild(make('small', 'sp-segment-place', 'Pine Box FM / The Booth'));
''',
     '''    var slot = sceneSlot(item);                               /* [seg-names] */
    var road = sceneName(item);
    var title = make('b', 'sp-segment-name', slot.label || road);
    if (slot.label) {
      title.title = slot.label + ' - the hour entry this round filled ('
        + (SLOT_HOW[slot.how] || slot.how || 'linked') + ')';
    } else if (slot.none) {
      title.appendChild(make('span', 'sp-segment-noslot', '(no slot)'));
      title.title = 'No hour entry: ' + String(slot.why || 'nothing links this round to one');
    }
    node.dataset.slot = slot.label ? String(slot.entry || slot.id || '') : (slot.none ? 'none' : '');
    words.appendChild(title);
    words.appendChild(make('small', 'sp-segment-place',
      slot.label ? road + ' \\u00b7 Pine Box FM' : 'Pine Box FM / The Booth'));
'''),
    ("derived",
     '''      stands: String(was.stands || was.seg || ''), derived: true};
    var print = item.text + SEP + String(item.at);
''',
     '''      stands: String(was.stands || was.seg || ''), derived: true,
      slot: was.slot};                                            /* [seg-names] */
    var print = item.text + SEP + String(item.at) + SEP + sceneSlotKey(item);
'''),
    ("print",
     '''        + SEP + (item.deleted ? 'D' : '');                        /* [#1200] */
''',
     '''        + SEP + (item.deleted ? 'D' : '')                         /* [#1200] */
        + SEP + sceneSlotKey(item);                               /* [seg-names] */
'''),
]

CSS_ADD = '''
/* [seg-names] a round with no hour entry keeps its road title, quietly marked */
.sp-segment-noslot {
  margin-left: 6px;
  color: #70828f;
  font-weight: 400;
  font-size: 10px;
}
'''


def load(path):
    raw = open(path, "rb").read().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def save(path, text, crlf):
    out = text.replace("\n", "\r\n") if crlf else text
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)))
    with os.fdopen(fd, "wb") as fh:
        fh.write(out.encode("utf-8"))
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, path)


def js_state(text):
    applied, missing = [], []
    for name, old, new in JS_EDITS:
        if new in text:
            applied.append(name)
        elif text.count(old) != 1:
            missing.append("%s (anchor x%d)" % (name, text.count(old)))
    return applied, missing


def one_dir(mode, root):
    js = os.path.join(root, "script-page.js")
    css = os.path.join(root, "script-page.css")
    jtext, jcrlf = load(js)
    ctext, ccrlf = load(css)
    applied, missing = js_state(jtext)
    css_in = ".sp-segment-noslot {" in ctext
    done = len(applied) == len(JS_EDITS) and css_in
    if mode == "--check":
        if done:
            print("APPLIED", root)
            return 2
        if missing:
            print("MISSING", root, "; ".join(missing))
            return 1
        print("READY", root)
        return 0
    if done:
        print("already applied", root)
        return 0
    if missing:
        print("MISSING", root, "; ".join(missing))
        return 1
    for name, old, new in JS_EDITS:
        if name not in applied:
            jtext = jtext.replace(old, new, 1)
    assert len(js_state(jtext)[0]) == len(JS_EDITS)
    save(js, jtext, jcrlf)
    if not css_in:
        ctext = ctext if ctext.endswith("\n") else ctext + "\n"
        save(css, ctext + CSS_ADD, ccrlf)
    print("applied", MARK, root)
    return 0


def main(argv):
    if len(argv) < 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    codes = [one_dir(argv[1], d) for d in argv[2:]]
    if any(c == 1 for c in codes):
        return 1
    if argv[1] == "--check" and all(c == 2 for c in codes):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
