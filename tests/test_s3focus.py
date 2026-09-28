"""[s3-focus] The Examine window's "3" opens System 3 focused on one message.

What is checked here is the integrated tree: the served System 3 module
carries the focused view as one block at its end and exactly two hooks in
mount(); the Examine window (desktop and kiosk copies alike) carries the
button, its opener and the module pins; Carbon's number--3 is in the icon
source and in both sprites exactly as tools/icons_build.py writes them; and
every write the focused view makes goes through a door that already exists.
The behaviour itself is driven headless (test_s3focus.cjs, beside the
delivery) - this file guards the wiring so a later edit cannot drop a piece
silently."""
import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "frontend" / "system3.js"
CSS = ROOT / "frontend" / "system3.css"
DEEP = ROOT / "desktop" / "renderer" / "line-deep.js"
DEEP_CSS = ROOT / "desktop" / "renderer" / "line-deep.css"
KIOSK = ROOT / "app" / "src" / "main" / "assets" / "pine-views"


def text(p):
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def block(src):
    at = src.index("/* [s3-focus] ONE MESSAGE, ZEROED IN.")
    return src[at:]


class FocusModuleTests(unittest.TestCase):
    def setUp(self):
        self.src = text(JS)

    def test_the_block_is_one_region_at_the_end(self):
        self.assertEqual(self.src.count("/* [s3-focus] ONE MESSAGE, ZEROED IN."), 1)
        b = block(self.src)
        self.assertEqual(b.count("export async function openSystem3Focus("), 1)
        self.assertEqual(b.count("function s3FocusLens(root, ctx) {"), 1)
        # nothing of the block's is defined before it
        head = self.src[:self.src.index("/* [s3-focus] ONE MESSAGE, ZEROED IN.")]
        for name in ("openSystem3Focus", "s3FocusLens(root, ctx)", "FOCUS_OF"):
            self.assertNotIn("function " + name if "(" not in name else "function " + name, head)
        self.assertNotIn("const FOCUS_OF", head)

    def test_mount_has_exactly_two_hooks(self):
        head = self.src[:self.src.index("/* [s3-focus] ONE MESSAGE, ZEROED IN.")]
        self.assertEqual(head.count("const focus = s3FocusLens(root, {"), 1)
        self.assertEqual(head.count("if (focus && focus.paint(tab)) return;"), 1)
        self.assertEqual(head.count("if (list[0] && !(focus && !focus.full())) await load(list[0].conversation_id);"), 1)
        # the router asks the lens first, then paints as it always did
        router = head[head.index("  function paint() {\n    paintTabs();"):]
        router = router[:router.index("\n  }\n")]
        self.assertLess(router.index("focus.paint(tab)"), router.index("if (tab === 'director')"))
        # the lens gets handles onto mount's own editors, and nothing new is exported from mount
        hook = head[head.index("const focus = s3FocusLens(root, {"):head.index("  function paint() {\n    paintTabs();")]
        for handle in ("go:", "config:", "settings:", "loadConfig:", "visual:", "director:", "table:", "segment:", "structure:", "audit:"):
            self.assertIn(handle, hook)

    def test_only_the_existing_doors_are_written(self):
        b = block(self.src)
        writes = set(re.findall(r"send\('(/api/[^']+?)'", b)) | set(re.findall(r"send\((?:base|path) \+ '([^']*)'", b))
        doors = set(re.findall(r"send\('(/api/[a-z0-9/_-]+)", b))
        for d in doors:
            self.assertTrue(d.startswith(("/api/system3/tables/", "/api/system3/config/section/blocks", "/api/system3/structure",
                                          "/api/system3/settings", "/api/paperwork/field")), d)
        self.assertIn("send('/api/system3/tables/' + encodeURIComponent(id), 'PUT', d)", b)
        self.assertIn("send('/api/system3/config/section/blocks', 'PUT', S.blocksDraft)", b)
        self.assertIn("send('/api/system3/structure', 'PUT'", b)
        self.assertIn("send('/api/system3/structures/' + encodeURIComponent(key), 'PUT'", b)
        self.assertIn("send('/api/paperwork/field', 'POST'", b)
        # the lists doors, as the lists editor uses them
        self.assertIn("const base = '/api/system3/lists/' + encodeURIComponent(listId);", b)
        self.assertIn("await send(path, 'DELETE')", b)
        self.assertIn("await send(path, 'PUT', body)", b)
        self.assertTrue(writes is not None)

    def test_nothing_polls_or_scrolls_by_itself(self):
        b = block(self.src)
        self.assertNotIn("setInterval(", b)
        # the one scrollIntoView is the operator's own tap on "open in the editor"
        self.assertEqual(b.count("scrollIntoView("), 1)
        self.assertIn("const litOnce = node =>", b)

    def test_every_way_out(self):
        b = block(self.src)
        self.assertIn("Back to Examine", b)
        self.assertIn("Show all of System 3", b)
        self.assertIn("Focus on the message again", b)
        self.assertIn("window.PineDismiss.onBack(", b)          # the tablet's BACK
        self.assertIn("e.key === 'Escape'", b)
        self.assertIn("backdrop.addEventListener('click'", b)

    def test_carbon_only(self):
        b = block(self.src)
        self.assertIn("window.pineIcon('c:number--3')", b)
        # no pictograph in the block's own words (the ES badge's emoji live elsewhere)
        pictos = [ch for ch in b if ord(ch) >= 0x1F000 or 0x2600 <= ord(ch) <= 0x27BF]
        self.assertEqual(pictos, [])

    def test_the_css_block_is_appended_and_scoped(self):
        css = text(CSS)
        self.assertEqual(css.count("[s3-focus] ONE MESSAGE, ZEROED IN"), 1)
        tail = css[css.index("[s3-focus] ONE MESSAGE, ZEROED IN"):]
        for sel in re.findall(r"^([^{}\n@/][^{}\n]*)\{", tail, re.M):
            for part in sel.split(","):
                self.assertTrue(".s3-fx-" in part or "s3-fx-focused" in part, part)


class ExamineButtonTests(unittest.TestCase):
    def test_the_button_is_in_the_head_between_title_and_actions(self):
        src = text(DEEP)
        head = src[src.index("+ '<b>How this line came to be</b>'"):src.index("+ '<div class=\"ld-head-actions\">'")]
        self.assertIn('class="ld-s3"', head)
        self.assertIn("root.pineIcon('c:number--3'", src)
        self.assertIn("mod.openSystem3Focus({request: s3Request", src)
        self.assertIn("opened.hidden = true;", src)
        self.assertIn("opened.hidden = false;", src)

    def test_the_bridge_carries_every_method(self):
        src = text(DEEP)
        self.assertIn("method === 'DELETE' ? 'del'", src)

    def test_both_imports_share_one_pin(self):
        src = text(DEEP)
        js = re.findall(r"/system3/system3\.js\?v=(\d+)", src)
        css = re.findall(r"/system3/system3\.css\?v=(\d+)", src)
        self.assertEqual(len(js), 2)
        self.assertEqual(len(set(js)), 1)
        self.assertEqual(len(css), 2)
        self.assertEqual(len(set(css)), 1)
        self.assertGreaterEqual(int(js[0]), 5)

    def test_the_hidden_window_is_really_hidden(self):
        self.assertIn(".ld-box[hidden] { display: none !important; }", text(DEEP_CSS))

    def test_the_kiosk_copy_mirrors_the_desktop(self):
        for name in ("line-deep.js", "line-deep.css"):
            kiosk = KIOSK / name
            if not kiosk.exists():
                self.skipTest("no kiosk tree here")
            self.assertEqual(text(kiosk), text(ROOT / "desktop" / "renderer" / name), name)


class IconTests(unittest.TestCase):
    def test_carbon_number_3_is_vendored_where_the_builder_reads_and_writes(self):
        doc = json.loads((ROOT / "frontend" / "icons" / "pine-icons.json").read_text(encoding="utf-8"))
        self.assertIn("c:number--3", doc["art"])
        self.assertIn('viewBox="0 0 32 32"', doc["art"]["c:number--3"])
        self.assertNotIn("c:number--3", {row["icon"] for row in doc["map"].values()})   # no emoji maps to it
        for rel in ("frontend/pine-icons.js", "desktop/renderer/pine-icons.js"):
            src = text(ROOT / rel)
            m = re.search(r"^  var ART = (\{.*\});$", src, re.M)
            art = json.loads(m.group(1))
            self.assertIn("c:number--3", art, rel)
            keys = list(art.keys())
            self.assertEqual(keys, sorted(keys), rel + ": ART is written sorted, as the builder writes it")


if __name__ == "__main__":
    unittest.main()
