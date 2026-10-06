"""[s3-flow-open] Dialogue flows; System 3 decides (2026-10-05).

Run from the repo root:  python3 -m unittest tests.test_flow_open_2026_10_05 -v
Pure: imports only the station's dependency-free modules and reads source text.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import flow_ledger  # noqa: E402
import manifest_store  # noqa: E402
import script_manifest as sm  # noqa: E402
import speech_gates  # noqa: E402


def _src(name: str) -> str:
    return (ROOT / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


class FlowLedgerTest(unittest.TestCase):
    def test_note_counts_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = flow_ledger.Ledger(Path(tmp) / "flow.jsonl", autoflush=False)
            led.note("final_handoff", "ValueError: rows must align", passed=True, road="caller",
                     text="Hello   there,\n caller.", ref="abc")
            led.note("final_handoff", "another", passed=True, road="banter")
            led.note("incomplete_conversation", "2 of 6 planned turns are bound", passed=False, road="news")
            counts = led.counts()
            self.assertEqual(counts["final_handoff"]["passed"], 2)
            self.assertEqual(counts["final_handoff"]["held"], 0)
            self.assertEqual(counts["incomplete_conversation"]["held"], 1)
            rows = led.recent(10)
            self.assertEqual([r["gate"] for r in rows],
                             ["incomplete_conversation", "final_handoff", "final_handoff"])   # newest first
            self.assertEqual(rows[-1]["text"], "Hello there, caller.")                       # whitespace folded
            self.assertEqual(len(led.recent(10, gate="final_handoff")), 2)
            self.assertEqual(len(led.recent(10, passed=False)), 1)
            self.assertEqual(led.recent(1)[0]["n"], 3)

    def test_flush_appends_jsonl_and_empties_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "flow.jsonl"
            led = flow_ledger.Ledger(path, autoflush=False)
            led.note("line_handoff", "why", road="station_id", text="This is the station.")
            self.assertEqual(led.flush(), 1)
            self.assertEqual(led.flush(), 0)
            led.note("line_handoff", "again")
            self.assertEqual(led.flush(), 1)
            lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["n"] for r in lines], [1, 2])
            self.assertTrue(all(r["passed"] is True for r in lines))

    def test_ring_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = flow_ledger.Ledger(Path(tmp) / "flow.jsonl", keep=10, autoflush=False)
            for i in range(40):
                led.note("g", str(i))
            self.assertEqual(len(led.recent(500)), 10)
            self.assertEqual(led.counts()["g"]["passed"], 40)      # the count is not the ring


class LazyPinsTest(unittest.TestCase):
    """_guard_overwrite must not read every manifest on the station to store a new take."""

    def _store(self, tmp):
        store = manifest_store.ManifestStore(Path(tmp) / "manifests")
        calls = {"n": 0}
        real = store.pins

        def counted(revision: str = ""):
            calls["n"] += 1
            return real(revision)

        store.pins = counted                # type: ignore[method-assign]
        return store, calls

    def test_new_record_does_not_read_the_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, calls = self._store(tmp)
            got = store._guard_overwrite("master", "take-1", "rev-1", {"take_id": "take-1", "a": 1})
            self.assertTrue(got["ok"])
            self.assertFalse(got.get("unchanged"))
            self.assertEqual(calls["n"], 0)

    def test_identical_rewrite_does_not_read_the_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, calls = self._store(tmp)
            record = {"take_id": "take-1", "kind": "master_recording", "a": 1}
            store._write_json(store.record_path("master", "rev-1", "take-1"), record)
            got = store._guard_overwrite("master", "take-1", "rev-1", dict(record))
            self.assertTrue(got["ok"])
            self.assertTrue(got.get("unchanged"))
            self.assertEqual(calls["n"], 0)

    def test_unpinnable_kind_does_not_read_the_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, calls = self._store(tmp)
            store._write_json(store.record_path("session", "rev-1", "s-1"), {"session_id": "s-1", "a": 1})
            got = store._guard_overwrite("session", "s-1", "rev-1", {"session_id": "s-1", "a": 2})
            self.assertTrue(got["ok"])
            self.assertEqual(calls["n"], 0)

    def test_a_different_record_over_a_pinned_take_is_still_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, calls = self._store(tmp)
            rev = "rev-1"
            store._write_json(store.record_path("master", rev, "take-1"), {"take_id": "take-1", "a": 1})
            store._write_json(store.record_path("cut", rev, "cut-1"), {"cut_id": "cut-1", "take_id": "take-1"})
            store._write_json(store.record_path("assembly", rev, "asm-1"),
                              {"assembly_id": "asm-1", "cue_map": [{"cut_id": "cut-1", "occurrence_id": "o1"}]})
            store._write_json(store.record_path("admission", rev, "adm-1"),
                              {"admission_id": "adm-1", "assembly_id": "asm-1", "revision": rev,
                               "state": "admitted", "playback_occurrence_id": "p1"})
            got = store._guard_overwrite("master", "take-1", rev, {"take_id": "take-1", "a": 2})
            self.assertFalse(got["ok"])
            self.assertEqual(calls["n"], 1)
            self.assertIn("pinned", " ".join(got["reasons"]))

    def test_same_answers_as_the_eager_guard(self):
        """The lazy guard and check_overwrite with the real pins agree on every case."""
        with tempfile.TemporaryDirectory() as tmp:
            store = manifest_store.ManifestStore(Path(tmp) / "manifests")
            rev = "rev-1"
            store._write_json(store.record_path("master", rev, "take-1"), {"take_id": "take-1", "a": 1})
            store._write_json(store.record_path("cut", rev, "cut-1"), {"cut_id": "cut-1", "take_id": "take-1"})
            store._write_json(store.record_path("assembly", rev, "asm-1"),
                              {"assembly_id": "asm-1", "cue_map": [{"cut_id": "cut-1", "occurrence_id": "o1"}]})
            store._write_json(store.record_path("admission", rev, "adm-1"),
                              {"admission_id": "adm-1", "assembly_id": "asm-1", "revision": rev,
                               "state": "admitted", "playback_occurrence_id": "p1"})
            cases = [("master", "take-1", {"take_id": "take-1", "a": 1}),
                     ("master", "take-1", {"take_id": "take-1", "a": 2}),
                     ("master", "take-9", {"take_id": "take-9"}),
                     ("cut", "cut-1", {"cut_id": "cut-1", "take_id": "take-2"}),
                     ("assembly", "asm-1", {"assembly_id": "asm-1", "cue_map": []}),
                     ("admission", "adm-1", {"admission_id": "adm-1", "state": "played"}),
                     ("session", "s-1", {"session_id": "s-1"})]
            pins = store.pins()
            for kind, ident, replacement in cases:
                eager = sm.check_overwrite(kind, ident, store.load(kind, rev, ident), replacement, pins)
                lazy = store._guard_overwrite(kind, ident, rev, replacement)
                self.assertEqual((eager["ok"], eager.get("unchanged")), (lazy["ok"], lazy.get("unchanged")),
                                 (kind, ident))


class SpeechGateTest(unittest.TestCase):
    def test_flow_gate_is_listed_and_switches_the_station(self):
        gate = speech_gates.gate("flow")
        self.assertIsNotNone(gate)
        param = gate["params"][0]
        self.assertEqual((param[0], param[3], param[4], param[5], param[6], param[7]),
                         ("open", "int", 1, 0, 1, "app.S3_FLOW_OPEN"))
        with tempfile.TemporaryDirectory() as tmp:
            speech_gates.load(Path(tmp) / "speech_gates.json")
            ns = {"S3_FLOW_OPEN": 1}
            speech_gates._STATE["boot"].pop("app.S3_FLOW_OPEN", None)
            missed = speech_gates.apply(ns)
            self.assertNotIn("app.S3_FLOW_OPEN", missed)
            self.assertEqual(ns["S3_FLOW_OPEN"], 1)
            speech_gates.change(ns, {"gate": "flow", "key": "open", "value": 0})
            self.assertEqual(ns["S3_FLOW_OPEN"], 0)
            saved = json.loads((Path(tmp) / "speech_gates.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["values"].get("flow.open"), 0)
            speech_gates.change(ns, {"gate": "flow", "reset": True})
            self.assertEqual(ns["S3_FLOW_OPEN"], 1)
            speech_gates._STATE["boot"].pop("app.S3_FLOW_OPEN", None)


class SourceContractTest(unittest.TestCase):
    """The wedges ask; they do not refuse. Read off the source the station runs."""

    @classmethod
    def setUpClass(cls):
        cls.app = _src("app.py")
        cls.rt = _src("system3_runtime.py")

    def _body(self, src: str, head: str, stop: str) -> str:
        start = src.index(head)
        return src[start:src.index(stop, start + len(head))]

    def test_a_refused_final_pass_does_not_queue_or_raise_while_flow_is_open(self):
        body = self._body(self.app, "async def _s3_handoff_entry(", "\ndef _s3_retire_handoff_candidate(")
        asked = body.index('s3_flow("final_handoff"')
        self.assertLess(asked, body.index("_dialogue_recovery_enqueue("))    # asked BEFORE anything is queued
        self.assertIn("return False", body[asked:body.index("_dialogue_recovery_enqueue(")])
        self.assertNotIn("except WritingDeferred", body)                      # a deferral is not a hold either

    def test_no_review_at_the_mouth_while_flow_is_open(self):
        body = self._body(self.app, "async def _banter_air(", "    if script_has_forgotten_line(")
        self.assertIn('entry.get("handoff_unavailable") and not s3_flow_is_open()', body)
        self.assertIn("and not s3_flow_is_open()):", body)

    def test_the_booth_asks_about_a_short_round(self):
        self.assertIn('"incomplete_conversation"', self.app)
        at = self.app.index("_s3_short and not s3_flow(")
        self.assertIn("incomplete conversation withheld after repair", self.app[at:at + 900])

    def test_readiness_predicates_do_not_roll(self):
        for head, stop in (("def s3_binding_withheld(", "\ndef dialogue_row_ready("),
                           ("def dialogue_row_ready(", "\ndef dialogue_row_viable("),
                           ("def dialogue_row_viable(", "\ndef ")):
            body = self._body(self.app, head, stop)
            self.assertIn("s3_flow_is_open()", body, head)
            self.assertNotIn("s3_flow(", body, head)          # per row per poll: a read, never a roll

    def test_finished_stock_is_not_pulled_back(self):
        body = self._body(self.app, "async def _s3_recover_larder_candidates(", "\ndef _s3_length_snapshot(")
        self.assertLess(body.index("if s3_flow_is_open():"), body.index("retired = 0"))

    def test_release_parks_what_it_cannot_bind_and_deletes_nothing(self):
        body = self._body(self.app, "async def dialogue_recovery_release(", "\nasync def flow_release_clock(")
        self.assertIn("DIALOGUE_RECOVERY_PARKED_PATH", body)
        self.assertIn("system3_flow_bind_entry", body)
        self.assertIn('entry.pop("dialogue_recovery_pending", None)', body)
        self.assertNotIn(".unlink(", body)

    def test_runtime_answers_at_once_without_rewrite_passes(self):
        body = self._body(self.rt, "    async def handoff_exchange(", "    # --- [s3-split] THE SPLIT NODE AT THE STATION'S DOORS")
        self.assertIn("recover=True)", body.split("\n", 2)[1] + body.split("\n", 2)[0])
        self.assertIn("if recovering and not recover:", body)
        gate = body.index("except ValueError as exc:")
        self.assertIn("if not recover:\n                    raise", body[gate:gate + 200])
        self.assertIn("kind, recover=recover)", body)
        self.assertIn('namespace["system3_flow_bind_entry"] = rt.flow_bind_entry', self.rt)

    def test_resolve_can_be_quiet(self):
        body = self._body(self.app, "async def pine_resolve(", "\n# --- #1079: the request book, served")
        self.assertIn('payload.get("speak") is not False', body)

    def test_gazette_paints_the_frame_it_opened(self):
        body = self._body(self.app, "async function paperShow(id) {", "\nasync function paperRefresh(")
        self.assertIn("const frame = paperFrame;", body)
        self.assertNotIn("paperFrame.onload", body)
        self.assertNotIn("paperFrame.srcdoc", body)
        self.assertEqual(body.count("paperFrame !== frame"), 3)


if __name__ == "__main__":
    unittest.main()
