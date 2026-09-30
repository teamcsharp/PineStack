"""[s3-lines] one observation whose `lines` is a count (the dead-air rescue's
INJECT card wrote "lines": 9) made /api/system3/line 500 for every line of its
conversation, so every Message-view card lost its rolodex."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _helper():
    src = (ROOT / "system3_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_s3_lines")
    ns = {}
    exec(compile(ast.Module([fn], []), "system3_runtime.py", "exec"), ns)
    return ns["_s3_lines"], src


class Lines(unittest.TestCase):
    def test_a_count_is_not_a_list_of_ids(self):
        lines, _ = _helper()
        self.assertEqual(lines({"lines": ["a", "b"]}), ["a", "b"])
        self.assertEqual(tuple(lines({"lines": 9})), ())
        self.assertEqual(tuple(lines({"lines": "9"})), ())
        self.assertEqual(tuple(lines({})), ())
        self.assertNotIn("x", lines({"family": "INJECT", "lines": 9}))

    def test_every_membership_reader_goes_through_it(self):
        _, src = _helper()
        self.assertNotIn('in (o.get("lines") or [])', src)
        self.assertGreaterEqual(src.count("_s3_lines(o)"), 3)

    def test_the_rescue_writes_a_count_under_its_own_name(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('extra={"road": kind, "line_count": len(said)})', app)
        self.assertNotIn('extra={"road": kind, "lines": len(said)})', app)


if __name__ == "__main__":
    unittest.main()
