"""Built-in dramatic frames migrate into an operator-owned approach book."""
import ast
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from threading import RLock


SOURCE = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def approach_source():
    names = {"DIALOGUE_APPROACHES", "_approach_seed", "_approach_write",
             "approach_rules"}
    nodes = []
    for node in TREE.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
                nodes.append(node)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id in names:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
    return compile(ast.Module(body=nodes, type_ignores=[]),
                   "app.py:approaches", "exec")


class DialogueApproachTests(unittest.TestCase):
    def namespace(self, path):
        ns = {"Path": Path, "hashlib": hashlib, "json": json, "time": time,
              "Any": object, "APPROACHES_PATH": path,
              "_APPROACH_LOCK": RLock()}
        exec(approach_source(), ns)
        return ns

    def test_new_scenario_types_join_an_existing_book_without_resetting_it(self):
        with tempfile.TemporaryDirectory(prefix="approaches-") as directory:
            path = Path(directory) / "approaches.json"
            custom = {"id": "mine", "text": "MY CUSTOM FRAME", "weight": 9,
                      "enabled": False, "uses": 12, "last": 99}
            path.write_text(json.dumps([custom]), encoding="utf-8")
            ns = self.namespace(path)
            rows = ns["approach_rules"]()
            mine = next(row for row in rows if row["id"] == "mine")
            self.assertEqual(mine, custom)
            text = "\n".join(str(row.get("text") or "") for row in rows)
            self.assertIn("STUDIO PRANK", text)
            self.assertIn("TALK INTIMATELY", text)
            self.assertIn("CHANGE THEIR MIND", text)
            self.assertTrue(all(row.get("id") for row in rows))

    def test_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="approaches-") as directory:
            path = Path(directory) / "approaches.json"
            ns = self.namespace(path)
            first = ns["approach_rules"]()
            second = ns["approach_rules"]()
            self.assertEqual(len(first), len(second))
            self.assertEqual(len({row["id"] for row in second}), len(second))


if __name__ == "__main__":
    unittest.main()
