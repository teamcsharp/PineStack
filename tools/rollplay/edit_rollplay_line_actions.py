#!/usr/bin/env python3
"""[rollplay] the dice in the hold menu header (line-actions.js)

Targets: desktop/renderer/line-actions.js and app/src/main/assets/pine-views/line-actions.js

  python edit_rollplay_line_actions.py --check <file> [<file> ...]   exit 0 ready / 2 applied / 1 anchor missing
  python edit_rollplay_line_actions.py --apply <file> [<file> ...]   idempotent; resumes a half-applied file

Marker-idempotent: an edit counts as APPLIED when its whole replacement is in
the file, READY when its anchor occurs exactly once. Line endings are kept
(a CRLF file stays CRLF, an LF file LF). The write is atomic, and a .js file
must pass `node --check` (when node is on PATH) before it replaces the old
one; a .json file must parse.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

EDITS = [('A1 the dice, left of the header icons: the roll again', "    var votes = make('div', 'la-votes');\n    /* [#1200] THE TRASH CAN", "    var votes = make('div', 'la-votes');\n    /* [rollplay] THE DICE, left of everything: the roll again, from the\n     * dice. The tile itself plays as the menu comes up (below). */\n    var rollDice = null, rollTag = null;\n    if (line.id && root.PineRollTag && typeof root.PineRollTag.mount === 'function') {\n      rollDice = make('button', 'la-vote la-roll');\n      rollDice.type = 'button';\n      rollDice.title = 'Replay how System 3 rolled this line';\n      rollDice.setAttribute('aria-label', rollDice.title);\n      rollDice.appendChild(icon('m:casino'));\n      /* ONE replay per press: press() acts on pointerup AND on the click that\n       * follows it; on a busy tablet that click can land after the de-dupe\n       * window and start a second roll. So a press is named by its\n       * pointerdown and acts once; a keyboard click (no pointer) acts too. */\n      var rollPress = 0, rollActed = -1;\n      rollDice.addEventListener('pointerdown', function () { rollPress += 1; });\n      press(rollDice, function (ev) {\n        var keyboard = ev && ev.type === 'click' && ev.detail === 0;\n        if (!rollTag || (!keyboard && rollActed === rollPress)) return;\n        rollActed = rollPress;\n        rollTag.replay();\n      });\n      votes.appendChild(rollDice);\n    }\n    /* [#1200] THE TRASH CAN"), ("A2 the roll tile in the quote's place, a clip's picture beside it", "    head.appendChild(make('p', 'la-vote-say', ''));\n    sheet.appendChild(head);\n", '    head.appendChild(make(\'p\', \'la-vote-say\', \'\'));\n    sheet.appendChild(head);\n    /* [rollplay] "If I tap and hold a message here and I bring up this\n     * window, then I want to see the RNG roulette animated message transition\n     * for that correspondence when this comes up ... with a 2 second hang\n     * after the RNG roulette before switching over to the typewriter effect\n     * message construction and icon rolodex" (the operator). The Message\n     * view\'s tile for this line (PineRollTag, script-page.js) plays in the\n     * quote\'s place - it types the same words - with how System 3 made it\n     * folded under it. A sound effect gets its picture beside it: drag to\n     * scrub, tap to hear it on a loop (PineRollTag.pip). The rows stay\n     * below and take a tap at any moment of the roll. */\n    if (rollDice) {\n      var band = make(\'div\', \'la-roll-band\' + (sfxRow ? \' la-clip-band\' : \'\'));\n      var slot = make(\'div\', \'la-roll-box\');\n      band.appendChild(slot);\n      sheet.appendChild(band);               /* under the header, not in it: the header is the drag handle */\n      try {\n        rollTag = root.PineRollTag.mount(slot, line, {autoplay: true, hold: 2000, compact: true, title: \'\', style: \'digital\'});\n        if (rollTag) head.classList.add(\'la-tiled\');\n        if (sfxRow && typeof root.PineRollTag.pip === \'function\') {\n          var pipSlot = make(\'div\', \'la-pip-box\');\n          band.appendChild(pipSlot);\n          root.PineRollTag.pip(pipSlot, {id: line.id, said: line.said, clip: true});\n        }\n      } catch (err) { band.remove(); head.classList.remove(\'la-tiled\'); }\n    }\n')]


def status(text):
    out = []
    for name, anchor, new in EDITS:
        if new.rstrip('\n') in text:
            out.append((name, 'applied'))
        elif anchor is None:
            out.append((name, 'ready'))
        else:
            n = text.count(anchor)
            out.append((name, 'ready' if n == 1 else 'missing (anchor x%d)' % n))
    return out


def verify(path, text):
    if path.endswith('.json'):
        json.loads(text)
        return ''
    if path.endswith('.py'):
        try:
            compile(text, path, 'exec')
        except SyntaxError as err:
            return 'SyntaxError: %s (line %s)' % (err.msg, err.lineno)
        return ''
    if path.endswith('.js') and shutil.which('node'):
        fd, tmp = tempfile.mkstemp(suffix='.js')
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)
        try:
            got = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
            return '' if got.returncode == 0 else (got.stderr or got.stdout)[-800:]
        finally:
            os.unlink(tmp)
    return ''


def one(path, apply):
    raw = open(path, 'rb').read().decode('utf-8')
    crlf = raw.count('\r\n') > raw.count('\n') // 2
    text = raw.replace('\r\n', '\n')
    st = status(text)
    for name, s in st:
        print('  %-60s %s' % (name, s))
    if any(s.startswith('missing') for _, s in st):
        print('%s: ANCHOR MISSING' % path)
        return 1
    if all(s == 'applied' for _, s in st):
        print('%s: already applied' % path)
        return 2
    if not apply:
        print('%s: ready' % path)
        return 0
    for name, anchor, new in EDITS:
        if new.rstrip('\n') in text:
            continue
        if anchor is None:
            text = text.rstrip('\n') + '\n' + new if text else new
            if not text.endswith('\n'):
                text += '\n'
        else:
            assert text.count(anchor) == 1, name
            text = text.replace(anchor, new, 1)
    assert all(s == 'applied' for _, s in status(text)), 'an edit did not land'
    bad = verify(path, text)
    if bad:
        print('%s: REFUSED - the result does not parse:\n%s' % (path, bad))
        return 1
    if crlf:
        text = text.replace('\n', '\r\n')
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.part')
    with os.fdopen(fd, 'wb') as fh:
        fh.write(text.encode('utf-8'))
    try:
        shutil.copymode(path, tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    print('%s: APPLIED (%s)' % (path, 'CRLF' if crlf else 'LF'))
    return 0


def main(argv):
    apply = '--apply' in argv
    paths = [a for a in argv if not a.startswith('--')]
    if not paths:
        print(__doc__)
        return 1
    rcs = [one(p, apply) for p in paths]
    return 1 if 1 in rcs else (0 if 0 in rcs else 2)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
