#!/usr/bin/env python3
"""[rollplay] the rolls stay expanded; the result types underneath (script-page.js, on wave AS)

Every PineRollTag home and the Result pin loop. Targets: desktop/renderer/script-page.js and app/src/main/assets/pine-views/script-page.js (applies on top of wave AS 81ce2fd).

  python edit_rollkeep_script_page.py --check <file> [<file> ...]   exit 0 ready / 2 applied / 1 anchor missing
  python edit_rollkeep_script_page.py --apply <file> [<file> ...]   idempotent; resumes a half-applied file

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

EDITS = [("K1 at the message, a kept roll stays in view (like a clip's)", "        if (item.kind === 'clip') { /* [msgthumb] a clip keeps its roll in view, over its picture */ }\n", "        if (item.kind === 'clip' || cur.keepRolls) { /* [msgthumb] a clip keeps its roll in view; [rollkeep] so does a tile */ }\n"), ('K2 ... as its results, expanded and indented', "        if (cur.sheet && item.kind === 'clip') mvRrResults(cur.sheet);   /* [msgroll] a clip keeps its roll in view */\n", "        if (cur.sheet && (item.kind === 'clip' || cur.keepRolls)) mvRrResults(cur.sheet);   /* [msgroll] [rollkeep] the roll stays */\n"), ('K3 the Result tab, flipped back, keeps a kept roll in view', "      if (cur.item.kind === 'clip') { /* a clip's roll stays in view [msgthumb] */ }\n", "      if (cur.item.kind === 'clip' || cur.keepRolls) { /* a clip's roll stays in view [msgthumb] [rollkeep] */ }\n"), ('K4 while it rolls out, every finished table stays in view', '        var keep = i === sheet.tables.length - 1 || !(sheet.tables[i + 2] && (skip || ms >= sheet.tables[i + 2].at));\n', '        var keep = sheet.keep || i === sheet.tables.length - 1 || !(sheet.tables[i + 2] && (skip || ms >= sheet.tables[i + 2].at));   /* [rollkeep] */\n'), ('K5 a tile keeps its rolls', '    cur.skip = false;                        /* asked for: it rolls, whatever the motion setting */\n    cur.fit = 3;\n', "    cur.skip = false;                        /* asked for: it rolls, whatever the motion setting */\n    cur.fit = 3;\n    rtKeep(cur);                             /* [rollkeep] the rolls stay; the result types under them */\n    st.clipText = '';\n"), ("K6 a clip's result types too, and the tile waits for it", "    rtOffAir(function () { mvFrameItem(cur, now); });\n    if (cur.phase === 'air' && (cur.item.kind !== 'speech' || cur.typed >= cur.item.text.length)) {\n      root.cancelAnimationFrame(st.raf);\n", "    rtOffAir(function () { mvFrameItem(cur, now); });\n    var clipTyped = rtClipType(st, cur, now);   /* [rollkeep] */\n    if (cur.phase === 'air' && (cur.item.kind !== 'speech' ? clipTyped : cur.typed >= cur.item.text.length)) {\n      root.cancelAnimationFrame(st.raf);\n"), ('K7 the helpers', '  function rtFrame(st, gen) {\n', '  /* [rollkeep] "whenever this expands, I want to see it reflected expanded\n     for each section on the rollout. I like that indented look. I want to see\n     that roll out. And stay after rollout. Then the result typewriters\n     underneath so I can see how it built and also what the result is." (the\n     operator, 2026-09-29). In every PineRollTag home and in the Result pin\n     loop the rolls stay: each finished table keeps its two-level indented\n     rows in view as the next one rolls, nothing folds away or is replaced,\n     and after the hang the result types UNDER them - the spoken line, or for\n     a clip its name and the line it answered. */\n  function rtKeep(cur) {\n    cur.keepRolls = true;\n    if (cur.sheet) { cur.sheet.keep = true; cur.sheet.box.classList.add(\'sp-rr-keep\'); }\n  }\n  function rtClipResult(item) {\n    var ci = mvClipInfo(item);\n    var name = String(ci.name || item.text || \'\').trim();\n    var m = item.match || null;\n    var line = String((m && m.line) || (item.row && (item.row.match_line || item.row.sfx_line)) || \'\').trim();\n    return line && line !== name ? name + \'\\n“\' + line + \'”\' : name;\n  }\n  /* a clip\'s result, typed like the spoken line (mvFrameItem sets a clip\'s\n     title whole): true once it is all there */\n  function rtClipType(st, cur, now) {\n    if (cur.item.kind !== \'clip\') return true;\n    if (cur.phase !== \'air\') return false;\n    if (!st.clipText) { st.clipText = rtClipResult(cur.item); st.clipAt = now; }\n    var all = st.clipText;\n    var n = Math.min(all.length, Math.floor((now - st.clipAt) / 38));\n    var shown = all.slice(0, n);\n    if (cur.text.textContent !== shown) cur.text.textContent = shown;\n    cur.text.classList.add(\'sp-mv-title\');\n    cur.text.classList.toggle(\'typing\', n < all.length);\n    var w = (all.length ? n / all.length * 100 : 100).toFixed(1) + \'%\';\n    if (cur.fill.style.width !== w) cur.fill.style.width = w;\n    return n >= all.length;\n  }\n  function rtFrame(st, gen) {\n'), ('K8 the pin loop keeps its rolls too', '    rtOffAir(function () { mvPlan(cur, cur.data); });\n    cur.skip = false;\n    if (cur.sheet) {\n', "    rtOffAir(function () { mvPlan(cur, cur.data); });\n    cur.skip = false;\n    rtKeep(cur);                              /* [rollkeep] */\n    P.clipText = '';\n    if (cur.sheet) {\n"), ("K9 ... and types a clip's result", "      rtOffAir(function () { mvFrameItem(cur, now); });\n      if (cur.phase === 'air' && (cur.item.kind !== 'speech' || cur.typed >= cur.item.text.length)) {\n        P.doneAt = now;\n", "      rtOffAir(function () { mvFrameItem(cur, now); });\n      var pinTyped = rtClipType(P, cur, now);   /* [rollkeep] */\n      if (cur.phase === 'air' && (cur.item.kind !== 'speech' ? pinTyped : cur.typed >= cur.item.text.length)) {\n        P.doneAt = now;\n"), ('K10 unpinned, the bubble lets its rolls go as before', "    if (cur.plan) cur.skip = true;\n    if (cur !== mv.cur) cur.node.classList.add('sp-mv-past');\n", "    if (cur.plan) cur.skip = true;\n    cur.keepRolls = false;                     /* [rollkeep] */\n    if (cur.sheet) { cur.sheet.keep = false; cur.sheet.box.classList.remove('sp-rr-keep'); }\n    if (cur !== mv.cur) cur.node.classList.add('sp-mv-past');\n")]


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
