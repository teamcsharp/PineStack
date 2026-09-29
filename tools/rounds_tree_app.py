#!/usr/bin/env python3
"""[rounds-tree] app.py: install script_decision_tree (GET /api/script/segment/{id}/decision-tree).

Usage: python3 tools/rounds_tree_app.py --check|--apply [--root REPO]
Exit: 0 ready, 2 already applied / applied, 1 anchor missing. CRLF-aware, marker-idempotent.
Needs the new file script_decision_tree.py at the repo root."""

import argparse
import os
import sys
import tempfile
from pathlib import Path


def _eol(text):
    crlf = text.count("\r\n")
    return "\r\n" if crlf and crlf * 2 >= text.count("\n") else "\n"


def _variants(s):
    lf = s.replace("\r\n", "\n")
    return [lf, lf.replace("\n", "\r\n")]


def _read(p):
    with open(str(p), encoding="utf-8", newline="") as fh:
        return fh.read()


def state_of(text, edit):
    """'applied' | 'ready' | 'missing' | 'ambiguous'"""
    if any(v in text for v in _variants(edit["marker"])):
        return "applied"
    hits = [text.count(v) for v in _variants(edit["anchor"])]
    if max(hits) == 0:
        return "missing"
    if max(hits) > 1:
        return "ambiguous"
    return "ready"


def apply_edit(text, edit):
    eol = _eol(text)
    anchor = next(v for v in _variants(edit["anchor"]) if text.count(v) == 1)
    body = edit["insert"].replace("\r\n", "\n").replace("\n", eol)
    if edit["where"] == "before":
        return text.replace(anchor, body + anchor, 1)
    return text.replace(anchor, anchor + body, 1)


def write_atomic(path, text):
    path = Path(path)
    mode = path.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".rtree-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def run(targets, edits_for, argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="exit 0 ready, 2 already applied, 1 anchor missing")
    g.add_argument("--apply", action="store_true", help="apply (idempotent); exit 2 when applied")
    ap.add_argument("--root", default=".", help="the spark-agent repo root")
    ap.add_argument("--kiosk", default="", help="also the kiosk project's pine-views/script-page.js")
    ap.add_argument("--only-kiosk", action="store_true", help="only the --kiosk file")
    a = ap.parse_args(argv)
    paths = targets(a)
    states = {}
    for path in paths:
        p = Path(path)
        if not p.is_file():
            print("MISSING FILE %s" % p)
            return 1
        text = _read(p)
        for e in edits_for(p):
            st = state_of(text, e)
            states[(str(p), e["name"])] = st
            print("%-9s %s :: %s" % (st.upper(), p, e["name"]))
    if any(s in ("missing", "ambiguous") for s in states.values()):
        print("anchor missing/ambiguous - nothing written")
        return 1
    if args_all_applied(states):
        print("already applied")
        return 2
    if a.check:
        return 0
    for path in paths:
        p = Path(path)
        text = _read(p)
        new = text
        for e in edits_for(p):
            if state_of(new, e) == "ready":
                new = apply_edit(new, e)
        for e in edits_for(p):
            if state_of(new, e) != "applied":
                print("FAILED to verify %s :: %s" % (p, e["name"]))
                return 1
        if new != text:
            write_atomic(p, new)
            print("APPLIED   %s" % p)
    return 2


def args_all_applied(states):
    return bool(states) and all(s == "applied" for s in states.values())


EDITS = [
    {'name': 'install the decision-tree route after the SFX display receipts',
     'anchor': '    print("the SFX display receipts did not install: %s: %s" % (type(_sfxd_exc).__name__, _sfxd_exc))\n',
     'where': 'after',
     'marker': 'import script_decision_tree as _rounds_tree',
     'insert': '# [rounds-tree] THE SEGMENT\'S DECISION TREE (script_decision_tree.py): a\n# segment\'s rounds as System 3\'s graph walked them - the stages with their\n# roll receipts and the roulette diamonds between them - for the Script\n# view\'s status block. GET /api/script/segment/{id}/decision-tree, read only.\ntry:\n    import script_decision_tree as _rounds_tree\n    _ROUNDS_TREE = _rounds_tree.install(app, globals())\nexcept Exception as _rtree_exc:  # noqa: BLE001\n    _ROUNDS_TREE = None\n    print("the decision tree did not install: %s: %s" % (type(_rtree_exc).__name__, _rtree_exc))\n'},
]


def edits_for(path):
    return EDITS


def targets(a):
    return [Path(a.root) / 'app.py']


if __name__ == "__main__":
    sys.exit(run(targets, edits_for))
