"""[vcrfx] node --check every inline <script> of CONTROL_PANEL_HTML and RADIO_PAGE_HTML in an app.py."""
import re, subprocess, sys, tempfile, os
src = open(sys.argv[1], encoding="utf-8").read()
bad = 0
for name in ("CONTROL_PANEL_HTML", "RADIO_PAGE_HTML"):
    i = src.index(name + ' = r"""')
    j = src.index('\n"""', i)
    page = src[i:j]
    blocks = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", page, re.S)
    blocks = [b for b in blocks if b.strip()]
    for k, b in enumerate(blocks):
        fd, p = tempfile.mkstemp(suffix=".js"); os.write(fd, b.encode("utf-8")); os.close(fd)
        r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
        os.unlink(p)
        if r.returncode:
            bad += 1; print(name, "block", k, "FAILED", r.stderr[:600])
    print(name, len(blocks), "inline blocks checked")
sys.exit(1 if bad else 0)
