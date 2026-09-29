#!/usr/bin/env python3
"""[rollplay] How System 3 made this, at the top of Dialogue repeat diagnostics

Targets: desktop/renderer/line-repeat.js and app/src/main/assets/pine-views/line-repeat.js

  python edit_rollplay_line_repeat.py --check <file> [<file> ...]   exit 0 ready / 2 applied / 1 anchor missing
  python edit_rollplay_line_repeat.py --apply <file> [<file> ...]   idempotent; resumes a half-applied file

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

EDITS = [('R1 How System 3 made this, at the top of the diagnostics', '  function paint(body, line, report, current) {\n    body.replaceChildren();\n', '  function paint(body, line, report, current) {\n    body.replaceChildren();\n    /* [rollplay] "At the top of dialogue repeat diagnostics show the roulette\n       roles that resulted in this": the Message view tile, replayable, with\n       the rolls, the databases and the lists under it (script-page.js). */\n    if (root.PineRollTag && typeof root.PineRollTag.mount === \'function\') {\n      var roll = make(\'section\', \'lr-section lr-roll\');\n      body.appendChild(roll);\n      try {\n        root.PineRollTag.mount(roll, {id: report.line_id || line.id, said: report.text || line.said}, {autoplay: true});\n      } catch (err) { roll.remove(); }\n    }\n')]


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
