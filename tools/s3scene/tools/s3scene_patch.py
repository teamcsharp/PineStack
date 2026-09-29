#!/usr/bin/env python3
"""[s3-scene-nav] The Sys3 scene: navigable (orbit / pan / pinch / wheel / double-tap
frame) and inspectable (tap -> inspector sidebar with confirm + undo edits).

    python3 s3scene_patch.py --check <repo>    exit 0 ready, 2 already applied, 1 anchors missing
    python3 s3scene_patch.py --apply <repo>    idempotent; CRLF kept per file; atomic write

Targets (repo = spark-agent root):
  frontend/system3.js                           paintSys3 + sys3Scene replaced (one span, base-hashed)
  frontend/system3.css                          the [s3-scene-nav] block appended
  desktop/renderer/hot-corners.js               'pine-gestures' joins OWNED (a corner swipe never starts on the scene)
  app/src/main/assets/pine-views/hot-corners.js the same, on the kiosk mirror
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'src')
MARK = '[s3-scene-nav]'

JS_START = '  async function paintSys3() {\n'
JS_END = '\n  /* ---------------- controls ---'
HC_OLD = 'var OWNED = /(^|\\s)(pine-view-tab|'
HC_NEW = 'var OWNED = /(^|\\s)(pine-gestures|pine-view-tab|'


def _read(path):
    with open(path, 'rb') as f:
        raw = f.read().decode('utf-8')
    crlf = '\r\n' in raw
    return raw.replace('\r\n', '\n'), crlf


def _write(path, text, crlf):
    data = (text.replace('\n', '\r\n') if crlf else text).encode('utf-8')
    tmp = path + '.s3scene.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def _src(name):
    with open(os.path.join(SRC, name), 'rb') as f:
        return f.read().decode('utf-8').replace('\r\n', '\n')


def span_sha(text):
    a = text.find(JS_START)
    b = text.find(JS_END, a)
    return hashlib.sha1(text[a:b].encode('utf-8')).hexdigest() if a >= 0 and b > a else ''


BASE_SPAN = '2935c0ad87bd9f49bb4323f5b25ecaee3141db50'   # sha1 of the paintSys3..controls span at bb00ac9


def plan(repo):
    """[(path, state, new_text_or_None, crlf, why)] state: ready | applied | missing"""
    out = []
    p = os.path.join(repo, 'frontend', 'system3.js')
    t, crlf = _read(p)
    if MARK in t and 'function sys3Scene(THREE, canvas, nowNode, host)' in t:
        out.append((p, 'applied', None, crlf, ''))
    elif t.count(JS_START) != 1 or t.count(JS_END) != 1:
        out.append((p, 'missing', None, crlf, 'paintSys3 / controls anchors: %d / %d' % (t.count(JS_START), t.count(JS_END))))
    elif span_sha(t) != BASE_SPAN:
        out.append((p, 'missing', None, crlf, 'the paintSys3..sys3Scene span changed since bb00ac9 (sha1 %s) - re-anchor' % span_sha(t)))
    else:
        a = t.find(JS_START)
        b = t.find(JS_END, a)
        out.append((p, 'ready', t[:a] + _src('sys3_block.js').rstrip('\n') + '\n' + t[b:], crlf, ''))
    p = os.path.join(repo, 'frontend', 'system3.css')
    t, crlf = _read(p)
    if MARK in t:
        out.append((p, 'applied', None, crlf, ''))
    else:
        out.append((p, 'ready', t.rstrip('\n') + '\n' + _src('sys3_block.css'), crlf, ''))
    for rel in ('desktop/renderer/hot-corners.js', 'app/src/main/assets/pine-views/hot-corners.js'):
        p = os.path.join(repo, *rel.split('/'))
        if not os.path.exists(p):
            out.append((p, 'missing', None, False, 'no such file'))
            continue
        t, crlf = _read(p)
        if HC_NEW in t:
            out.append((p, 'applied', None, crlf, ''))
        elif t.count(HC_OLD) != 1:
            out.append((p, 'missing', None, crlf, 'OWNED anchor count %d' % t.count(HC_OLD)))
        else:
            out.append((p, 'ready', t.replace(HC_OLD, HC_NEW), crlf, ''))
    return out


def main(argv):
    if len(argv) != 3 or argv[1] not in ('--check', '--apply'):
        print(__doc__)
        return 1
    repo = argv[2]
    rows = plan(repo)
    for p, state, _, _, why in rows:
        print('%-8s %s %s' % (state, os.path.relpath(p, repo), why))
    if any(r[1] == 'missing' for r in rows):
        return 1
    if argv[1] == '--check':
        return 2 if all(r[1] == 'applied' for r in rows) else 0
    for p, state, text, crlf, _ in rows:
        if state == 'ready':
            _write(p, text, crlf)
    again = plan(repo)
    ok = all(r[1] == 'applied' for r in again)
    print('APPLIED' if ok else 'NOT APPLIED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
