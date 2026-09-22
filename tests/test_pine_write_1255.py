"""#1255 — prove the guard refuses the write that erases the inbox.

Lifts pine_write / pine_read_or_raise / _pine_render / _PINE_BLOCK_RE out of
the patched app.py and drives them against a real file, with no station.

    python test_pine_write_1255.py <patched app.py>
"""
import pathlib
import re
import sys
import tempfile
import time
from typing import Any


def lift(src: str) -> dict:
    """Execute just the pieces this guard needs, nothing else from app.py."""
    ns: dict[str, Any] = {"Any": Any, "re": re, "time": time,
                          "pathlib": pathlib, "print": print}
    want = ("_PINE_BLOCK_RE = ", "_PINE_READ_FAILED: dict[str, Any] = ",
            "def _pine_render(", "def pine_read_or_raise(", "def pine_write(")
    for name in want:
        i = src.find(name)
        assert i >= 0, "could not find %r in the patched file" % name
        if name.endswith("= "):
            # a statement, possibly spanning lines: read until the
            # parentheses balance rather than to the first newline
            depth, j = 0, i
            while j < len(src):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                elif src[j] == "\n" and depth == 0:
                    break
                j += 1
            chunk = src[i:j + 1]
        else:
            # to the next top-level def/comment block
            j = src.find("\n\n\ndef ", i)
            k = src.find("\n\n\n# ", i)
            j = min(x for x in (j, k, len(src)) if x > 0)
            chunk = src[i:j]
        exec(compile(chunk, "<lifted>", "exec"), ns)
    return ns


def main() -> int:
    src = pathlib.Path(sys.argv[1]).read_bytes().decode("utf-8")
    ns = lift(src)
    fails = []

    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "pine_requests.md"
        ns["PINE_REQUESTS_PATH"] = path

        rows = [{"id": 900 + n, "when": "2026-09-22 00:0%d" % n,
                 "status": "open", "text": "request number %d" % n}
                for n in range(4)]
        path.write_text(ns["_pine_render"](rows), encoding="utf-8")
        start = path.read_text(encoding="utf-8")

        def check(name, got, want):
            if got != want:
                fails.append("%s: got %r want %r" % (name, got, want))
            print("%-58s %s" % (name, "ok" if got == want else "FAIL"))

        # 1. the fault this exists for: a failed read became an empty list
        check("an empty write over a full book is REFUSED",
              ns["pine_write"]([], "a read that failed"), False)
        check("  ...and the book on disk is untouched",
              path.read_text(encoding="utf-8"), start)

        # 2. dropping rows nobody named is refused even when not empty
        check("dropping two unnamed rows is REFUSED",
              ns["pine_write"](rows[:2], "half a book"), False)
        check("  ...and the book on disk is untouched",
              path.read_text(encoding="utf-8"), start)

        # 3. the legitimate shrink: the caller names what it took out
        check("taking out a NAMED request is allowed",
              ns["pine_write"]([r for r in rows if r["id"] != 902],
                               "resolving", dropping=902), True)
        check("  ...and that request is gone",
              "#902" in path.read_text(encoding="utf-8"), False)
        check("  ...and the other three are still there",
              all("#%d" % i in path.read_text(encoding="utf-8")
                  for i in (900, 901, 903)), True)

        # 4. the last request out leaves a header-only book, legitimately
        left = [r for r in rows if r["id"] not in (902, 900, 901)]
        ns["pine_write"]([r for r in rows if r["id"] not in (902, 900)],
                         "resolving", dropping=900)
        ns["pine_write"](left, "resolving", dropping=901)
        check("emptying the book one NAMED request at a time is allowed",
              [r["id"] for r in ns["pine_read_or_raise"]()], [903])

        # 5. adding is never blocked
        rows2 = ns["pine_read_or_raise"]()
        rows2.insert(0, {"id": 999, "when": "now", "status": "open",
                         "text": "a new one"})
        check("filing a new request is allowed",
              ns["pine_write"](rows2, "filing"), True)

        # 6. a backup of the previous bytes exists
        check("the previous book was kept beside it",
              path.with_suffix(".prev.md").exists(), True)

        # 7. an unreadable book refuses the write rather than overwriting it
        path.write_bytes(b"\xff\xfe not utf-8 at all \xff")
        check("an UNREADABLE book refuses the write",
              ns["pine_write"](rows, "after a bad read"), False)
        check("  ...and the unreadable bytes are left alone",
              path.read_bytes()[:2], b"\xff\xfe")

    print()
    print("FAILURES: %d" % len(fails))
    for f in fails:
        print(" ", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
