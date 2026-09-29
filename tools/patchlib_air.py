"""Tiny marker-idempotent, CRLF-aware anchor patcher for the airplayers build.

Each edit is (marker, anchor, text, mode, count):
  mode "before"  inserts `text` immediately before every one of `count` anchors
  mode "after"   inserts `text` immediately after them
  mode "replace" replaces them with `text` (which must NOT contain the anchor)
An edit counts as APPLIED when its marker is in the file (marker must be
unique to the inserted text). --check exits 0 ready, 2 all applied, 1 missing.
"""
import os
import sys
import tempfile


def _nl(raw):
    return "\r\n" if "\r\n" in raw[:200000] else "\n"


def run(target_rel, edits, argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ("--check", "--apply"):
        print("usage: --check|--apply <repo root>")
        return 64
    mode, root = argv
    path = os.path.join(root, target_rel)
    with open(path, "r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    nl = _nl(raw)
    text = raw.replace("\r\n", "\n") if nl == "\r\n" else raw
    missing, applied, ready = [], [], []
    for marker, anchor, new, how, count in edits:
        if new.find(anchor) >= 0 and how == "replace":
            raise SystemExit("edit %s: replacement contains its own anchor" % marker)
        if marker in text:
            applied.append(marker)
        elif text.count(anchor) == count:
            ready.append(marker)
        else:
            missing.append("%s (anchor seen %d, want %d)" % (marker, text.count(anchor), count))
    if missing:
        print("%s: MISSING %s" % (target_rel, "; ".join(missing)))
        return 1
    if mode == "--check":
        if not ready:
            print("%s: APPLIED (%d edits)" % (target_rel, len(applied)))
            return 2
        print("%s: READY %s (applied already: %s)" % (target_rel, ready, applied))
        return 0
    for marker, anchor, new, how, count in edits:
        if marker in text:
            continue
        if how == "before":
            text = text.replace(anchor, new + anchor)
        elif how == "after":
            text = text.replace(anchor, anchor + new)
        else:
            text = text.replace(anchor, new)
        if marker not in text:
            raise SystemExit("edit %s: marker not present after apply" % marker)
    out = text.replace("\n", "\r\n") if nl == "\r\n" else text
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".air-")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, path)
    print("%s: APPLIED %d edit(s)%s" % (target_rel, len(ready), " (CRLF kept)" if nl == "\r\n" else ""))
    return 0
