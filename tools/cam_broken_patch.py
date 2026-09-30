"""[cam-broken] a recording that cannot be read says so, and offers nothing.

Before [cam-fmp4] a segment the link's restart cut short never got its index
(moov) and is unreadable for good; the Recordings tab listed them like any other
and Play/Export/H3 failed on them. The index sits at the head of a fragmented
segment and at the tail of a closed plain one: a file with neither is marked
`broken`. Read once per file (keyed by size and mtime).

Usage (ON THE HOST): python3 tools/cam_broken_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[cam-broken]"

HELPER_AT = '''def pinecam_recordings() -> dict[str, Any]:
'''
HELPER = '''_PINECAM_READABLE: dict[str, tuple[int, float, bool]] = {}


def _pinecam_readable(p: Path, st: Any) -> bool:
    """[cam-broken] a moov at the head (fragmented) or in the tail (closed plain)."""
    key = str(p)
    got = _PINECAM_READABLE.get(key)
    if got and got[0] == st.st_size and got[1] == st.st_mtime:
        return got[2]
    ok = False
    try:
        with p.open("rb") as fh:
            ok = b"moov" in fh.read(8192)
            if not ok and st.st_size > 8192:
                fh.seek(max(0, st.st_size - 2_000_000))
                ok = b"moov" in fh.read()
    except OSError:
        ok = False
    _PINECAM_READABLE[key] = (st.st_size, st.st_mtime, ok)
    if len(_PINECAM_READABLE) > 2000:
        _PINECAM_READABLE.pop(next(iter(_PINECAM_READABLE)))
    return ok


def pinecam_recordings() -> dict[str, Any]:
'''

APP = [
    (HELPER_AT, HELPER, 1),
    ('''        seg = bool(_PINECAM_SEGMENT.match(p.name))
        items.append({"name": p.name, "kind": "footage" if seg else "kept", "at": _pinecam_at(p),
                      "bytes": st.st_size, "url": "/api/pinelink/clip/" + p.name,
                      "writing": bool(seg and p.name == newest_seg and now - st.st_mtime < 30),
                      "host_path": share_path_of(p)})
''', '''        seg = bool(_PINECAM_SEGMENT.match(p.name))
        writing = bool(seg and p.name == newest_seg and now - st.st_mtime < 30)
        items.append({"name": p.name, "kind": "footage" if seg else "kept", "at": _pinecam_at(p),
                      "bytes": st.st_size, "url": "/api/pinelink/clip/" + p.name,
                      "writing": writing, "host_path": share_path_of(p),
                      "broken": (not writing) and not _pinecam_readable(p, st)})      # [cam-broken]
''', 1),
]

JS_PATHS = ['/desktop/renderer/pine-cam.js', '/app/src/main/assets/pine-views/pine-cam.js']
JS = [
    ('''    var row = cfgMake('div', 'pcc-rec' + (x.writing ? ' writing' : ''));
    row.draggable = !x.writing;
    row.title = x.writing ? x.name + ' - still being written; it can be used once it closes'
      : x.name + ' - drag it onto the folder above to copy it to PineBoxRecordings';
''', '''    var off = !!(x.writing || x.broken);      /* [cam-broken] */
    var row = cfgMake('div', 'pcc-rec' + (off ? ' writing' : ''));
    row.draggable = !off;
    row.title = x.broken ? x.name + ' - unreadable: the link restarted while it was being written, before recordings were made crash-proof'
      : x.writing ? x.name + ' - still being written; it can be used once it closes'
        : x.name + ' - drag it onto the folder above to copy it to PineBoxRecordings';
''', 1),
    ('''    if (!x.writing) {
      var src = base() + '/api/pinecam/thumb/' + encodeURIComponent(x.name);
''', '''    if (!off) {
      var src = base() + '/api/pinecam/thumb/' + encodeURIComponent(x.name);
''', 1),
    ('''      + (x.writing ? ' - recording now' : '')));
''', '''      + (x.writing ? ' - recording now' : x.broken ? ' - unreadable (cut short by a restart)' : '')));
''', 1),
    ('''    [play, exp, h3].forEach(function (b) { b.disabled = !!x.writing; btns.appendChild(b); });
''', '''    [play, exp, h3].forEach(function (b) { b.disabled = off; btns.appendChild(b); });
''', 1),
]


def patch(path, edits, mode, py):
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for old, new, n in edits:
        got = out.count(old)
        assert got == n, "%s: %r found %d, want %d" % (path, old[:60], got, n)
        out = out.replace(old, new)
    if py:
        ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/%s.bak-cam-broken" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    mode = sys.argv[1]
    patch(ROOT + "/app.py", APP, mode, True)
    for p in JS_PATHS:
        patch(ROOT + p, JS, mode, False)
