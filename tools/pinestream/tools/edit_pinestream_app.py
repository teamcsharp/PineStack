"""[pinestream] app.py: import + install pinestream.py, open its two viewer
routes (and pine-closex.js) on the public listener door, carry a `pinestream`
block on the tune page's existing /api/pinelink/mine poll, and give
RADIO_PAGE_HTML the PiP window (CSS + its own <script> block + the one-line
hand-off inside the Pine Cam's ask()).

    python edit_pinestream_app.py --check|--apply <spark-agent root>

--apply also extracts every inline <script> of CONTROL_PANEL_HTML and
RADIO_PAGE_HTML and runs `node --check` on each (node must be on PATH).
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from patchlib import Edit, Insert, main  # noqa: E402

T = "app.py"
PAY = HERE.parent / "payload"


def payload(name: str) -> str:
    return (PAY / name).read_text(encoding="utf-8").replace("\r\n", "\n")


PIP_JS = payload("tune_pip.js")
PIP_CSS = payload("tune_pip.css")
assert '"""' not in PIP_JS and '"""' not in PIP_CSS
assert not re.search(r"__[A-Z_]+__", PIP_JS + PIP_CSS)

EDITS = [
    Insert(T, "import pinestream  ",
           "import pinelive                         # [pinelive] MX Live: the event, its roads, its doors\n",
           "import pinestream                       # [pinestream] the PineTab / Pine app screen as a PiP for listeners\n"),
    Insert(T, "pinestream.install(app, globals())",
           "pinelive.install(app, globals())\n",
           "pinestream.install(app, globals())      # [pinestream] /api/pinestream/*: one frame in memory, no encoder\n"
           "# [pinestream] the viewers' two routes check the tune-in token themselves\n"
           "# (frame.jpg refuses a tokenless request on the door, like the camera's);\n"
           "# pine-closex.js draws the PiP's corner X.\n"
           "_PUBLIC_GET |= {\"/api/pinestream/mine\", \"/api/pinestream/frame.jpg\",\n"
           "                \"/spark/asset/pine-closex.js\"}\n"),
    Insert(T, '"pinestream": pinestream.mine_for(',
           '            "switch": _vcr_switch(t),                       # [vcrfx]\n',
           '            "pinestream": pinestream.mine_for(               # [pinestream] rides this poll\n'
           '                t, request.headers.get("x-pinebox-public") == "1"),\n'),
    Insert(T, '<script src="/spark/asset/pine-closex.js"></script><!-- [pinestream]',
           '<script src="/spark/asset/pine-stick.js"></script>\n<style>\n  :root { color-scheme: dark; }\n'
           '  * { box-sizing: border-box; }\n  body {\n    margin: 0; min-height: 100vh; display: flex; align-items: center;\n',
           '<script src="/spark/asset/pine-closex.js"></script><!-- [pinestream] the PiP\'s corner X -->\n',
           where="before"),
    Insert(T, ".pinestream {",
           "    .pinecam { right: 8px; bottom: 8px; width: min(240px, 62vw); }\n  }\n",
           PIP_CSS),
    Insert(T, "window.PineStreamTune = {",
           "<!-- #1471: one tap in the car captures what the phone, the player and\n",
           PIP_JS, where="before"),
    Insert(T, "window.PineStreamTune.news(got",
           '      var got = await api("/api/pinelink/mine");\n',
           '      try { if (window.PineStreamTune) window.PineStreamTune.news(got && got.pinestream); }   /* [pinestream] */\n'
           '      catch (e) { /* PineStream never breaks the camera */ }\n'),
]


def inline_scripts(src: str, name: str) -> list[str]:
    i = src.index(name + ' = r"""')
    j = src.index('\n"""', i)
    page = src[i:j]
    return [m.group(1) for m in re.finditer(r"<script(?:\s[^>]*)?>(.*?)</script>", page, re.S)
            if m.group(1).strip()]


def verify(root: Path):
    import py_compile
    try:
        py_compile.compile(str(root / T), doraise=True)
    except Exception as err:  # noqa: BLE001
        return False, "py_compile: %s" % err
    src = (root / T).read_text(encoding="utf-8")
    said = []
    for name in ("CONTROL_PANEL_HTML", "RADIO_PAGE_HTML"):
        for k, js in enumerate(inline_scripts(src, name)):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
                f.write(js)
            got = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
            Path(f.name).unlink()
            if got.returncode != 0:
                return False, "node --check %s script %d: %s" % (name, k, got.stderr[-600:])
            said.append("%s#%d" % (name, k))
    return True, "py_compile ok; node --check ok on " + ", ".join(said)


if __name__ == "__main__":
    sys.exit(main(EDITS, after_apply=verify))
