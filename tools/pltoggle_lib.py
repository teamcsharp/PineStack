"""[pltoggle] shared patch machinery: marker-idempotent, CRLF-aware.

Each edit is (name, anchor, replacement, done). `done` is a string only the
replacement carries: present = applied. Otherwise the anchor must occur
exactly once = ready. --check exits 0 ready, 2 applied, 1 anchors missing.
--apply is idempotent and writes atomically, keeping the file's newlines.
"""
import os
import sys


def _read(path):
    raw = open(path, "rb").read()
    text = raw.decode("utf-8")
    crlf = "\r\n" in text
    return text.replace("\r\n", "\n"), crlf


def _write(path, text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    tmp = path + ".pltoggle.part"
    with open(tmp, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)


def status(text, edits):
    rows = []
    for name, anchor, new, done in edits:
        if done in text:
            rows.append((name, "applied"))
        elif text.count(anchor) == 1:
            rows.append((name, "ready"))
        else:
            rows.append((name, "missing (anchor x%d)" % text.count(anchor)))
    return rows


def main(edits_for, argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = "--check"
    if argv and argv[0] in ("--check", "--apply"):
        mode = argv.pop(0)
    if not argv:
        print("usage: %s [--check|--apply] FILE [FILE ...]" % os.path.basename(sys.argv[0]))
        return 1
    codes = []
    for path in argv:
        text, crlf = _read(path)
        edits = edits_for(path)
        rows = status(text, edits)
        missing = [n for n, s in rows if s.startswith("missing")]
        applied = [n for n, s in rows if s == "applied"]
        for n, s in rows:
            print("  %-28s %s" % (n, s))
        if missing:
            print("%s: ANCHORS MISSING: %s" % (path, ", ".join(missing)))
            codes.append(1)
            continue
        if mode == "--check":
            code = 2 if len(applied) == len(rows) else 0
            print("%s: %s" % (path, "APPLIED" if code == 2 else "READY"))
            codes.append(code)
            continue
        codes.append(0)
        for name, anchor, new, done in edits:
            if done in text:
                continue
            assert text.count(anchor) == 1, name
            text = text.replace(anchor, new, 1)
            assert done in text, name
        for n, s in status(text, edits):
            assert s == "applied", (n, s)
        _write(path, text, crlf)
        print("%s: APPLIED (%s)" % (path, "CRLF" if crlf else "LF"))
    if 1 in codes:
        return 1
    if mode == "--check" and codes and all(c == 2 for c in codes):
        return 2
    return 0
