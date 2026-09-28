"""[autoscroll-rule] The one scroll rule reaches every page that follows.

"do not move the page for me as far as scrolling it unless I am already
looking at the latest message ... And that's just in the program in
general."  - the operator, 2026-09-28

Run in the container after tools/autoscroll_rule_patch.py, with
desktop/renderer/pine-stick.js in the tree beside app.py:

  the tool reads "applied" on this app.py (every anchored site rewritten);
  /spark/asset/pine-stick.js serves the desktop's own file, as JavaScript,
  revalidated on every load;
  the panel loads it after the icon sprite and before its own script;
  the tune page (/radio and /tune/<token>) loads the sprite and it before its
  script, and wraps patter() after System 3's block rather than inside it;
  the public door lets exactly that file through, and not its neighbours;
  the helper itself never polls and never resumes on a timer;
  the desktop window loads it before renderer.js;
  both served pages' inline scripts parse (when node is on this machine).

Nothing here touches the station's data dir, settings or network."""
import asyncio
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app

REPO = Path(app.__file__).resolve().parent
STICK = REPO / "desktop" / "renderer" / "pine-stick.js"
TOOL = REPO / "tools" / "autoscroll_rule_patch.py"


def first_inline_script(html):
    m = re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    return m.start() if m else -1


class TheTool(unittest.TestCase):
    def test_every_site_is_rewritten_on_this_app_py(self):
        run = subprocess.run([sys.executable, str(TOOL), app.__file__],
                             capture_output=True, text=True, timeout=300)
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
        self.assertIn("already applied", run.stdout)

    def test_every_site_carries_the_marker(self):
        self.assertGreaterEqual(app.CONTROL_PANEL_HTML.count("[autoscroll-rule]"), 30)
        self.assertGreaterEqual(app.RADIO_PAGE_HTML.count("[autoscroll-rule]"), 2)


class TheAsset(unittest.TestCase):
    def test_the_route_serves_the_desktop_file(self):
        self.assertTrue(STICK.is_file(), STICK)
        self.assertTrue(app._SPARK_ASSETS["pine-stick.js"].startswith("application/javascript"))
        with mock.patch.object(app, "_SPARK_ASSET_DIR", STICK.parent):
            got = asyncio.run(app.spark_asset("pine-stick.js"))
        self.assertEqual(got.body, STICK.read_bytes())
        self.assertTrue(got.media_type.startswith("application/javascript"))
        self.assertEqual(got.headers.get("cache-control"), "no-cache")

    def test_the_helper_never_polls_and_never_resumes_on_a_timer(self):
        js = STICK.read_text(encoding="utf-8")
        self.assertNotIn("setInterval", js)
        # the only timer is requestAnimationFrame's fallback, one frame long
        self.assertEqual(sorted(set(re.findall(r"setTimeout\(([^)]*)\)", js))), ["fn, 16"])
        self.assertIn("root.pineStick = pineStick", js)
        self.assertIn("pineStick.version = VERSION", js)
        for method in ("follow", "reveal", "keep", "anchor", "restore", "jump", "examining"):
            self.assertIn("Stick.prototype.%s = function" % method, js)

    def test_its_button_is_carbon_never_emoji(self):
        js = STICK.read_text(encoding="utf-8")
        self.assertIn("root.pineIcon(st.opts.icon || 'c:arrow--up')", js)
        pictographs = [c for c in js if 0x1F000 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF]
        self.assertEqual(pictographs, [])


class ThePages(unittest.TestCase):
    def test_the_panel_loads_it_after_the_sprite_and_before_its_script(self):
        html = app.CONTROL_PANEL_HTML
        sprite = html.index('<script src="/icons/pine-icons.js"></script>')
        stick = html.index('<script src="/spark/asset/pine-stick.js"></script>')
        self.assertLess(sprite, stick)
        self.assertLess(stick, first_inline_script(html))

    def test_the_tune_page_loads_both_before_its_script(self):
        html = app.RADIO_PAGE_HTML
        sprite = html.index('<script src="/icons/pine-icons.js"></script>')
        stick = html.index('<script src="/spark/asset/pine-stick.js"></script>')
        self.assertLess(sprite, stick)
        self.assertLess(stick, first_inline_script(html))

    def test_the_tune_feed_is_wrapped_outside_system3s_block(self):
        html = app.RADIO_PAGE_HTML
        declared = html.index("function patter(state) {")
        toggle = html.index("function s3Toggle(row) {")
        wrapped = html.index("patter = (function (plain) {")
        self.assertLess(declared, toggle)
        self.assertLess(toggle, wrapped)            # after the stored block, not in it
        self.assertLess(wrapped, html.index("</script>", wrapped))
        # System 3's own text is untouched: patter() still decides "near" itself
        self.assertIn("  if (near) host.scrollTop = host.scrollHeight;\n  s3Ask(rows);\n}\n", html)

    def test_the_desktop_window_loads_it_before_renderer_js(self):
        page = (REPO / "desktop" / "renderer" / "index.html").read_text(encoding="utf-8")
        self.assertLess(page.index('<script src="./pine-icons.js"></script>'),
                        page.index('<script src="./pine-stick.js"></script>'))
        self.assertLess(page.index('<script src="./pine-stick.js"></script>'),
                        page.index('src="./renderer.js"'))


class ThePublicDoor(unittest.TestCase):
    def test_exactly_that_file_goes_through(self):
        self.assertTrue(app._public_allows("GET", "/spark/asset/pine-stick.js"))
        self.assertTrue(app._public_allows("HEAD", "/spark/asset/pine-stick.js"))
        self.assertFalse(app._public_allows("POST", "/spark/asset/pine-stick.js"))
        # named exactly: the asset route's other files stay behind the door
        self.assertFalse(app._public_allows("GET", "/spark/asset/spark-overlays.js"))
        self.assertFalse(app._public_allows("GET", "/spark/asset/pine-stick.js.map"))
        # and the sprite the tune page now loads was already public
        self.assertTrue(app._public_allows("GET", "/icons/pine-icons.js"))


@unittest.skipUnless(shutil.which("node"), "node is not on this machine")
class TheServedPagesParse(unittest.TestCase):
    def test_every_inline_script_parses(self):
        for name in ("CONTROL_PANEL_HTML", "RADIO_PAGE_HTML"):
            html = getattr(app, name)
            for ph in ("__SERVER_KEY__", "__AWAY__", "__ROAD__", "__BUILD__"):
                html = html.replace(ph, "0")
            blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
            self.assertTrue(blocks, name)
            for i, js in enumerate(blocks):
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                                 encoding="utf-8") as fh:
                    fh.write(js)
                try:
                    run = subprocess.run(["node", "--check", fh.name],
                                         capture_output=True, text=True, timeout=300)
                finally:
                    Path(fh.name).unlink()
                self.assertEqual(run.returncode, 0, "%s script %d: %s" % (name, i, run.stderr[:600]))


if __name__ == "__main__":
    unittest.main()
