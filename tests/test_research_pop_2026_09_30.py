"""[research-pop] the top five, what became of each, and the operator's word per site."""
import ast
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app.py").read_text(encoding="utf-8")


def _fns():
    keep = [n for n in ast.parse(SRC).body
            if (isinstance(n, ast.FunctionDef) and n.name in ("s3_research_domain", "s3_research_judge"))
            or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                                                   ("S3_RESEARCH_SHOWN", "S3_RESEARCH_HANDED") for t in n.targets))]
    ns = {"re": re, "Any": Any}
    exec(compile(ast.Module(keep, []), "app.py", "exec"), ns)
    return ns


NS = _fns()
ROWS = [{"title": "t%d" % i, "url": "https://www.site%d.com/x" % i, "snippet": "said %d" % i} for i in range(1, 8)]


class Judge(unittest.TestCase):
    def test_five_shown_three_handed(self):
        rows, lines = NS["s3_research_judge"](ROWS, {})
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["verdict"] for r in rows], ["used", "used", "used", "spare", "spare"])
        self.assertEqual(lines, ["said 1", "said 2", "said 3"])
        self.assertEqual(rows[0]["domain"], "site1.com")

    def test_the_operators_word_holds(self):
        rows, lines = NS["s3_research_judge"](ROWS, {"site1.com": "never", "site6.com": "prefer"})
        self.assertEqual(rows[0]["domain"], "site6.com")               # preferred comes first
        self.assertEqual(rows[0]["verdict"], "used")
        never = [r for r in rows if r["domain"] == "site1.com"][0]
        self.assertEqual(never["verdict"], "refused")
        self.assertNotIn("said 1", lines)

    def test_the_rebuttal_row_needs_research(self):
        tables = (ROOT / "system3_tables.py").read_text(encoding="utf-8")
        at = tables.index('"id": "llm_rebuttal"')
        self.assertIn('"requires": ["research"]', tables[at:at + 300])
        self.assertIn('"key": str(got.get("key") or "")', (ROOT / "system3.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
