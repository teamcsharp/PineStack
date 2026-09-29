"""[pinestream] the operator's answers (2026-09-29), station + desk half:

1. RESTART COMES BACK OFF: PineLive.boot() clears stream_on (and writes it),
   keeping the source / fps / width / quality. A screen still pushing after
   the restart is answered keep:false by the switch itself.
3. SHARE LINKS ARE VEILED: every surface that shows a tune-in link or the
   list of them carries data-pine-private, which pinestream.js already treats
   as "Private screen" (no pixels leave the streamed screen):
     - app.py CONTROL_PANEL_HTML remotePanel() (#remoteModal): the tune-in
       link list, the mint row, the car link and its QR - the panel the
       PineTab runs and the desk's controlFrame webview shows;
     - desktop/renderer/index.html: the drawer's "Public broadcast" section
       (#pubLink) and the Pine Cam's picked-viewers list (#pineCamViewers).
   The shared views half (pinelive.js "Go LIVE" share sheet, desk + tablet)
   is edit_pinestream_bd_views.py. Key fields are password inputs and were
   already veiled by pinestream.js's own rule.
[pinestream-choose] pinestream.py: /api/pinestream/state?from=<screen>&awake=
   records each screen's check-in (the poll pinestream.js already makes), and
   status()["sources"] says whether each screen can stream now - the chooser
   names one that is asleep or closed.
[camgrey] pinelive.py: the Picture block also carries cam_state, cam_why and
   cam_seen_ago from the same pinelink_state() read (no new poll), for the
   greyed "PineCam to live" switch and its tooltip.
Also updates tests/test_pinestream.py.

    python edit_pinestream_bd_station.py --check|--apply <spark-agent root>
--apply runs py_compile and node --check on every inline script of
CONTROL_PANEL_HTML and RADIO_PAGE_HTML.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from patchlib import Edit, Insert, main  # noqa: E402

VEIL = "a tune-in link is on the screen"

EDITS = [
    Insert("pinelive.py", "PineStream always comes back OFF after a restart",
           "        try:\n            self.control = json.loads(self.control_path.read_text())\n",
           "        # [pinestream] PineStream always comes back OFF after a restart (the\n"
           "        # operator's rule, 2026-09-29): the source, rate, width and quality stay\n"
           "        # remembered; only the on-state resets, written so the file says what\n"
           "        # the station does. A screen still pushing is answered keep:false.\n"
           "        if self.settings.get(\"stream_on\"):\n"
           "            self.settings[\"stream_on\"] = False\n"
           "            try:\n"
           "                _atomic_write(self.settings_path, json.dumps(self.settings, indent=1))\n"
           "            except Exception:  # noqa: BLE001\n"
           "                pass\n"
           "            self.note(\"pinestream\", \"PineStream starts OFF after a restart - \"\n"
           "                      \"flip it on to stream again\")\n",
           where="before"),
    Insert("app.py", 'shade.setAttribute("data-pine-private"',
           '  shade.id = "remoteModal";\n',
           '  /* [pinestream-veil] tune-in links, the car link and its QR: PineStream shows\n'
           '   * "Private screen" while this is open (pinestream.js reads the attribute) */\n'
           '  shade.setAttribute("data-pine-private", "%s");\n' % VEIL),
    Edit("desktop/renderer/index.html", '<section data-pine-private="%s">\n        <h3>Public broadcast</h3>' % VEIL,
         "      <section>\n        <h3>Public broadcast</h3>\n",
         '      <!-- [pinestream-veil] the public link: PineStream shows "Private screen" while this is on the glass -->\n'
         '      <section data-pine-private="%s">\n        <h3>Public broadcast</h3>\n' % VEIL),
    Edit("desktop/renderer/index.html", 'class="pine-cam-viewers" data-pine-private=',
         '<div id="pineCamViewers" class="pine-cam-viewers"></div>',
         '<div id="pineCamViewers" class="pine-cam-viewers" data-pine-private="the list of tune-in links is on the screen"></div>'),
    Edit("tests/test_pinestream.py", "def test_a_restart_comes_back_off",
         "    def test_remembered_across_a_restart(self):\n"
         "        self.pl.set_settings({\"stream_on\": True, \"stream_source\": \"pineapp\"})\n"
         "        again = pinelive.PineLive(data_dir=Path(self._td.name))\n"
         "        again.boot()\n"
         "        self.assertTrue(again.settings[\"stream_on\"])\n"
         "        self.assertEqual(again.settings[\"stream_source\"], \"pineapp\")\n",
         "    def test_a_restart_comes_back_off(self):\n"
         "        \"\"\"The operator's rule: after any station restart stream_on is false until\n"
         "        he flips it again; the source, rate, width and quality are remembered, and\n"
         "        a screen still pushing is told keep:false.\"\"\"\n"
         "        self.pl.set_settings({\"stream_on\": True, \"stream_source\": \"pineapp\",\n"
         "                              \"stream_fps\": 3, \"stream_width\": 800, \"stream_quality\": 75})\n"
         "        again = pinelive.PineLive(data_dir=Path(self._td.name))\n"
         "        again.boot()\n"
         "        self.assertFalse(again.settings[\"stream_on\"])\n"
         "        self.assertEqual((again.settings[\"stream_source\"], again.settings[\"stream_fps\"],\n"
         "                          again.settings[\"stream_width\"], again.settings[\"stream_quality\"]),\n"
         "                         (\"pineapp\", 3, 800, 75))\n"
         "        import json\n"
         "        on_disk = json.loads(again.settings_path.read_text())\n"
         "        self.assertFalse(on_disk[\"stream_on\"])       # the file says what the station does\n"
         "        ps = pinestream.PineStream(settings=lambda: again.settings)\n"
         "        code, ans = ps.accept(\"pineapp\", JPEG)\n"
         "        self.assertFalse(ans[\"keep\"])                 # the desk still pushing is stopped\n"
         "        self.assertEqual(ps.frame(), (None, \"off\"))\n"
         "        third = pinelive.PineLive(data_dir=Path(self._td.name))\n"
         "        third.boot()                                  # a second restart: still off\n"
         "        self.assertFalse(third.settings[\"stream_on\"])\n"
         "\n"
         "    def test_on_after_a_restart_only_when_flipped(self):\n"
         "        again = pinelive.PineLive(data_dir=Path(self._td.name))\n"
         "        again.boot()\n"
         "        again.set_settings({\"stream_on\": True})\n"
         "        self.assertTrue(again.settings[\"stream_on\"])\n"),
    Insert("tests/test_pinestream.py", "class ShareLinksAreVeiled",
           "\n\nif __name__ == \"__main__\":\n    unittest.main()\n",
           "", where="before"),
]

# the test class goes in front of the main guard (an Insert whose text is set below)
EDITS[-1].text = (
    "\n\nclass ShareLinksAreVeiled(unittest.TestCase):\n"
    "    \"\"\"Every surface that shows a tune-in link carries data-pine-private, so\n"
    "    PineStream shows 'Private screen' while it is open (read, not run).\"\"\"\n"
    "\n"
    "    def test_the_panel_remote_modal(self):\n"
    "        src = (ROOT / \"app.py\").read_text(encoding=\"utf-8\")\n"
    "        i = src.index(\"async function remotePanel()\")\n"
    "        body = src[i:src.index(\"document.body.appendChild(shade);\", i)]\n"
    "        self.assertIn('shade.setAttribute(\"data-pine-private\"', body)\n"
    "        for bit in ('api(\"/api/share\")', 'api(\"/api/share/car\"'):     # the list and the car link live in it\n"
    "            j = src.index(bit, i)\n"
    "            self.assertLess(j, src.index(\"async function artistReadPanel()\", i))\n"
    "\n"
    "    def test_the_desk_drawer_and_the_cam_viewers(self):\n"
    "        html = (ROOT / \"desktop\" / \"renderer\" / \"index.html\").read_text(encoding=\"utf-8\")\n"
    "        self.assertIn('<section data-pine-private=\"a tune-in link is on the screen\">\\n        <h3>Public broadcast</h3>', html)\n"
    "        self.assertRegex(html, r'id=\"pineCamViewers\"[^>]*data-pine-private=')\n"
    "\n"
    "    def test_the_go_live_sheet_on_both_screens(self):\n"
    "        desk = (ROOT / \"desktop\" / \"renderer\" / \"pinelive.js\").read_text(encoding=\"utf-8\")\n"
    "        tab = (ROOT / \"app\" / \"src\" / \"main\" / \"assets\" / \"pine-views\" / \"pinelive.js\").read_text(encoding=\"utf-8\")\n"
    "        self.assertEqual(desk, tab)\n"
    "        i = desk.index(\"function openShareSheet()\")\n"
    "        self.assertIn(\"s.back.setAttribute('data-pine-private'\", desk[i:i + 400])\n"
    "\n"
    "    def test_the_agent_reads_the_attribute(self):\n"
    "        js = (ROOT / \"desktop\" / \"renderer\" / \"pinestream.js\").read_text(encoding=\"utf-8\")\n"
    "        self.assertIn(\"querySelectorAll('[data-pine-private]')\", js)\n"
)

PAY = HERE.parent / "payload"


def pay(name: str) -> str:
    return (PAY / name).read_text(encoding="utf-8").replace("\r\n", "\n")


EDITS += [
    # [pinestream-choose] the screens' check-ins, on the poll their agents already make
    Insert("pinestream.py", "CHECKIN_S = ",
           "VIEWER_S = 12.0          # a viewer who fetched within this is watching\n",
           "CHECKIN_S = 20.0         # [pinestream-choose] a screen whose agent asked within this is there\n"),
    Insert("pinestream.py", "def checkin(self, surface",
           "    def status(self) -> dict[str, Any]:\n",
           pay("bd_ps_methods.py.txt"), where="before"),
    Insert("pinestream.py", 'out["sources"] = self.sources()',
           '        out["watching"] = self.watching()\n',
           '        out["sources"] = self.sources()                  # [pinestream-choose]\n'),
    Edit("pinestream.py", 'PS.checkin(request.query_params.get("from"',
         "    async def pinestream_state_api(authorization: str | None = Header(default=None)) -> Any:\n"
         "        auth(authorization)\n",
         "    async def pinestream_state_api(request: Request,\n"
         "                                   authorization: str | None = Header(default=None)) -> Any:\n"
         "        auth(authorization)\n"
         "        # [pinestream-choose] the screen's agent says which it is and whether it is awake\n"
         '        PS.checkin(request.query_params.get("from", ""), request.query_params.get("awake", "1") != "0")\n'),
    # [camgrey] the camera's own words, from the read state() already makes
    Insert("pinelive.py", 'cam_state, cam_why = "", ""',
           "        cam_live = False\n",
           '        cam_state, cam_why = "", ""                       # [camgrey]\n'),
    Insert("pinelive.py", "self.cam_seen_at = time.time()",
           '            cam_live = bool(got.get("state") == "live" and got.get("fresh"))\n',
           '            cam_state = str(got.get("state") or "")          # [camgrey]\n'
           '            cam_why = str(got.get("why") or "")[:200]\n'
           '            if cam_live:\n'
           '                self.cam_seen_at = time.time()\n'),
    Insert("pinelive.py", '"cam_state": cam_state,',
           '                        "cam_live": cam_live,\n',
           '                        "cam_state": cam_state, "cam_why": cam_why,     # [camgrey]\n'
           '                        "cam_seen_ago": (round(time.time() - self.cam_seen_at, 1)\n'
           '                                         if getattr(self, "cam_seen_at", 0) else None),\n'),
    Insert("tests/test_pinestream.py", "class ChooserAndCamGrey",
           '\n\nif __name__ == "__main__":\n    unittest.main()\n',
           pay("bd_test_choose.py.txt").rstrip("\n") + "\n", where="before"),
]


def inline_scripts(src: str, name: str) -> list:
    i = src.index(name + ' = r"""')
    page = src[i:src.index('\n"""', i)]
    return [m.group(1) for m in re.finditer(r"<script(?:\s[^>]*)?>(.*?)</script>", page, re.S)
            if m.group(1).strip()]


def verify(root: Path):
    import py_compile
    for rel in ("app.py", "pinelive.py", "tests/test_pinestream.py"):
        try:
            py_compile.compile(str(root / rel), doraise=True)
        except Exception as err:  # noqa: BLE001
            return False, "py_compile %s: %s" % (rel, err)
    src = (root / "app.py").read_text(encoding="utf-8")
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
