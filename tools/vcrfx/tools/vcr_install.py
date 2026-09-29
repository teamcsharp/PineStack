"""[vcrfx] puts pine-vcr.js (vcrfx/src/pine-vcr.js, beside this tools folder) at
<dest>: desktop/renderer/pine-vcr.js, and the kiosk's assets/pine-views/ and
assets/pine-sampler/ copies. LF, byte-identical to the source.

    python vcr_install.py --check <dest>   0 ready (absent or different), 2 identical
    python vcr_install.py --apply <dest>
TARGET: desktop/renderer/pine-vcr.js
"""
import os
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "pine-vcr.js")


def main(argv):
    if len(argv) != 2 or argv[0] not in ("--check", "--apply"):
        print("usage: --check|--apply <dest>")
        return 64
    mode, dest = argv
    with open(SRC, "rb") as fh:
        want = fh.read().replace(b"\r\n", b"\n")
    have = None
    if os.path.exists(dest):
        with open(dest, "rb") as fh:
            have = fh.read()
    if have == want:
        print("APPLIED already: %s" % dest)
        return 2
    if mode == "--check":
        print("READY: %s (%s)" % (dest, "absent" if have is None else "differs"))
        return 0
    d = os.path.dirname(os.path.abspath(dest))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".vcrfx-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(want)
    os.chmod(tmp, 0o644)
    os.replace(tmp, dest)
    print("APPLIED: %s" % dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
