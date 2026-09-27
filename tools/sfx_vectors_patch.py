"""Wire the SFX Guy's vector section into app.py: one guarded install line
after System 3's (docs/SFX_vector_reuse.md). --check exits 0 ready / 2
applied / 1 missing; --apply writes LF atomically. ON THE HOST."""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("install",
     'except Exception as _system3_exc:  # noqa: BLE001\n'
     '    _SYSTEM3_RUNTIME = None\n'
     '    print("system3 did not install: %s: %s" % (type(_system3_exc).__name__, _system3_exc))\n',
     'except Exception as _system3_exc:  # noqa: BLE001\n'
     '    _SYSTEM3_RUNTIME = None\n'
     '    print("system3 did not install: %s: %s" % (type(_system3_exc).__name__, _system3_exc))\n'
     '# [sfx-vectors] the SFX Guy\'s vector section (docs/SFX_vector_reuse.md): clips\n'
     '# and his dialogue indexed by lexical, semantic and anchored facets, kept by\n'
     '# his own keeper, queryable by outside applications, backed up as one file.\n'
     'try:\n'
     '    from sfx_vectors_runtime import install as install_sfx_vectors\n'
     '    _SFX_VECTORS_RUNTIME = install_sfx_vectors(app, globals())\n'
     'except Exception as _sfxv_exc:  # noqa: BLE001\n'
     '    _SFX_VECTORS_RUNTIME = None\n'
     '    print("sfx vectors did not install: %s: %s" % (type(_sfxv_exc).__name__, _sfxv_exc))\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if applied == len(plan(text)):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in plan(text):
        if state_of(text, old, new, count) == "applied":
            continue
        text = text.replace(old, new)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if "--apply" in argv:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if applied == len(plan(text)):
        print("already applied")
        return 2
    print("ready")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
