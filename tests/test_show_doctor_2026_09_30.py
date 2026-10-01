"""[show-doctor] the operator's words reach the troubleshooting tree; other talk does not."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app.py").read_text(encoding="utf-8")


def _parse():
    keep = [n for n in ast.parse(SRC).body
            if (isinstance(n, ast.FunctionDef) and n.name in ("parse_show_doctor", "parse_what_happened"))
            or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("_SHOW_DOCTOR_RX", "_HAPPENED_RX")
                                                  for t in n.targets))]
    ns = {"re": re}
    exec(compile(ast.Module(keep, []), "app.py", "exec"), ns)
    return ns


NS = _parse()
DOC = NS["parse_show_doctor"]


class Words(unittest.TestCase):
    def test_the_operators_own_questions(self):
        for said in ("Where are the DJs?", "I'm not hearing any DJs", "I can't hear the DJs on the station",
                     "what happened to the show", "what happened to the broadcast on the tablet",
                     "why am I not hearing the hosts", "fix the show", "the DJs are quiet",
                     "there's no dialogue", "I'm still not hearing the DJs on the station"):
            self.assertTrue(DOC(said), said)

    def test_other_talk_is_left_alone(self):
        for said in ("do any DJs like jazz", "play something by the DJ Shadow", "what happened to the script",
                     "export the last five minutes of the pine tab", "where is the remote"):
            self.assertFalse(DOC(said), said)

    def test_it_runs_before_the_script_report(self):
        self.assertLess(SRC.index("    if parse_show_doctor(user_text):"), SRC.index("    if parse_what_happened(user_text):"))
        self.assertTrue(NS["parse_what_happened"]("what happened to the script"))


if __name__ == "__main__":
    unittest.main()
