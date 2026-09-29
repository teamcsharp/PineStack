#!/usr/bin/env python3
"""closex_verify - after --apply: node --check every JS the wave touches,
the panel's inline <script> blocks (extracted from CONTROL_PANEL_HTML), and
that each kiosk mirror still equals its desktop/renderer canonical.

    python closex_verify.py <repo-root> [file ...]
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
extra = sys.argv[2:]
fail = 0


def node_check(path: Path, label: str) -> None:
    global fail
    r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    ok = r.returncode == 0
    fail += 0 if ok else 1
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else "\n" + r.stderr[-1500:]))


src = (root / "app.py").read_text(encoding="utf-8").replace("\r\n", "\n")
a = src.index('CONTROL_PANEL_HTML = r"""') + len('CONTROL_PANEL_HTML = r"""')
b = src.index('\n"""', a)
panel = src[a:b]
blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", panel, flags=re.S)
with tempfile.TemporaryDirectory() as tmp:
    for i, body in enumerate(blocks):
        if not body.strip():
            continue
        p = Path(tmp) / f"panel_{i}.js"
        p.write_text(body, encoding="utf-8")
        node_check(p, f"app.py CONTROL_PANEL_HTML <script> #{i} ({len(body)} chars)")

for rel in ["desktop/renderer/pine-closex.js", "desktop/renderer/pine-dismiss.js"] + extra:
    p = root / rel
    if p.suffix == ".js":
        node_check(p, rel)

mirror = root / "app/src/main/assets/pine-views"
if mirror.is_dir():
    for m in sorted(mirror.iterdir()):
        c = root / "desktop/renderer" / m.name
        if c.is_file() and m.suffix in (".js", ".css") and m.read_bytes() != c.read_bytes():
            print("MIRROR-DIFFERS " + m.name)
print("VERIFY", "FAILED" if fail else "PASSED")
sys.exit(1 if fail else 0)
