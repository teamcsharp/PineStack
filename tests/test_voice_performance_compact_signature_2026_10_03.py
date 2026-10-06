"""Exercise production voice-cache/performance functions without importing app."""
from __future__ import annotations

import ast
import copy
import json
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import patch

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
APP_SOURCE = APP_PATH.read_text(encoding="utf-8")
APP_TREE = ast.parse(APP_SOURCE)
FUNCTIONS = {
    "_voice_json_snapshot", "_voice_json_cached", "_voice_json", "voice_meta",
    "voice_signature", "voice_style", "_voice_performance_signature",
    "_compose_signature", "performance_vector",
}
ASSIGNMENTS = {"VOICE_ID_SHAPE", "EMOTION_DIMS", "_PERF_IDENTITY", "MACRO_STATES", "_MACRO_MULT"}
VID = "vl_11111111"
COMPONENT = "vl_22222222"

class Clock:
    def __init__(self): self.now = 100.0
    def time(self): return self.now

class FullAccessorBaseline(ast.NodeTransformer):
    """Reconstruct only the old accessor choices; performance math is unchanged."""
    def visit_Name(self, node):
        if node.id == "_voice_performance_signature":
            return ast.copy_location(ast.Name(id="voice_signature", ctx=node.ctx), node)
        return node

def namespace(root: Path, *, baseline=False):
    nodes = []
    for node in APP_TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            chosen = copy.deepcopy(node)
            if baseline and node.name in {"_compose_signature", "performance_vector"}:
                chosen = FullAccessorBaseline().visit(chosen)
            nodes.append(chosen)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id in ASSIGNMENTS for target in targets):
                nodes.append(copy.deepcopy(node))
    clock = Clock()
    settings = {"voice_speed": 1.02, "perf": True, "perf_strength": 0.75, "disfluency_rate": 0.22}
    scope = {"Any": Any, "Path": Path, "copy": copy, "json": json, "re": re,
             "time": clock, "VOICES_DIR": root, "_VOICE_JSON_MEMO": {},
             "_RADIO": {"speaker_macro": {}}, "dj_settings": lambda: settings,
             "ES_ROW_KEYS": ["name"], "_es_voice": SimpleNamespace(clean=lambda value: dict(value or {}))}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(APP_PATH), "exec"), scope)
    scope["speaker_state"] = lambda _who: {dim: 0.0 for dim in scope["EMOTION_DIMS"]}
    return scope, clock, settings

def signature(scale=1.0):
    return {
        "speaker": "sample", "pace": {"mean": 0.7, "spread": 0.2},
        "pitch": {"mobility": 0.8 * scale, "range": 0.4, "mean": 0.5},
        "rhythm": {"regularity": 0.6, "variation": 0.1},
        "pauses": {"duration": 0.4 * scale, "density": 0.3},
        "energy": {"dynamics": 0.7 * scale, "mean": 0.5},
        "articulation": {"precision": 0.8},
        "behavior": {"hesitation": 0.1, "filler": 0.12 * scale, "repetition": 0.2},
        "expressiveness": {"overall": 0.7},
        "raw": {"wpm": 175, "mean_pause_s": 0.4, "nested": {"notes": [1, 2]}},
        "extra": {"nested": [{"preserved": True}]},
        "timeline": [{"at": i / 10, "pitch": i % 7, "energy": i % 5} for i in range(4000)],
    }

def without_timeline(value): return {key: item for key, item in value.items() if key != "timeline"}

class VoicePerformanceCompactSignatureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pine-voice-compact-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.primary = signature()
        self.component = signature(0.6)
        self.style = {"components": {
            "energy": {"source": COMPONENT, "strength": 0.4},
            "pitch_mobility": {"source": COMPONENT, "strength": 0.7},
            "filler": {"source": COMPONENT, "strength": 0.5},
        }}
        for vid, value, style in [(VID, self.primary, self.style), (COMPONENT, self.component, {})]:
            directory = self.root / vid
            directory.mkdir()
            (directory / "signature.json").write_text(json.dumps(value), encoding="utf-8")
            (directory / "meta.json").write_text(json.dumps({"speed": 0.93, "pitch": 1.2}), encoding="utf-8")
            (directory / "style.json").write_text(json.dumps(style), encoding="utf-8")
        self.ns, self.clock, self.settings = namespace(self.root)

    def test_full_and_compact_accessors_own_all_returned_nested_values(self):
        compact = self.ns["_voice_performance_signature"](VID)
        full = self.ns["voice_signature"](VID)
        canonical = self.ns["_VOICE_JSON_MEMO"][(VID, "signature.json")][2]
        self.assertEqual(full, self.primary)
        self.assertEqual(compact, without_timeline(self.primary))
        self.assertIn("timeline", canonical)
        full["raw"]["nested"]["notes"].append(99)
        full["timeline"][0]["energy"] = 999
        compact["raw"]["nested"]["notes"].append(88)
        compact["extra"]["nested"][0]["preserved"] = False
        self.assertEqual(canonical, self.primary)
        self.assertEqual(self.ns["voice_signature"](VID), self.primary)
        self.assertEqual(self.ns["_voice_performance_signature"](VID), without_timeline(self.primary))

    def test_compact_hit_omits_timeline_before_any_deepcopy(self):
        class NeverCopyTimeline:
            def __deepcopy__(self, memo): raise AssertionError("timeline traversed")
        canonical = copy.deepcopy(self.primary)
        canonical["timeline"] = NeverCopyTimeline()
        self.ns["_VOICE_JSON_MEMO"][(VID, "signature.json")] = (self.clock.now, 123, canonical)
        self.assertEqual(self.ns["_voice_performance_signature"](VID), without_timeline(self.primary))
        with self.assertRaisesRegex(AssertionError, "timeline traversed"):
            self.ns["voice_signature"](VID)

    def test_five_second_freshness_and_mtime_version_invalidation_are_shared(self):
        old = self.ns["_voice_performance_signature"](VID)
        path = self.root / VID / "signature.json"
        before = path.stat().st_mtime_ns
        updated = copy.deepcopy(self.primary)
        updated["raw"]["wpm"] = 202
        updated["revision"] = 2
        path.write_text(json.dumps(updated), encoding="utf-8")
        os.utime(path, ns=(before + 10_000_000, before + 10_000_000))
        self.clock.now += 4.99
        self.assertEqual(self.ns["_voice_performance_signature"](VID), old)
        self.assertEqual(self.ns["voice_signature"](VID), self.primary)
        self.clock.now += 0.02
        self.assertEqual(self.ns["_voice_performance_signature"](VID), without_timeline(updated))
        self.assertEqual(self.ns["voice_signature"](VID), updated)

    def test_unchanged_mtime_reuses_canonical_object_after_freshness_window(self):
        self.ns["voice_signature"](VID)
        canonical = self.ns["_VOICE_JSON_MEMO"][(VID, "signature.json")][2]
        self.clock.now += 6
        with patch.object(Path, "read_text", side_effect=AssertionError("unchanged file reread")):
            compact = self.ns["_voice_performance_signature"](VID)
        self.assertIs(self.ns["_VOICE_JSON_MEMO"][(VID, "signature.json")][2], canonical)
        self.assertEqual(compact, without_timeline(self.primary))

    def test_component_blends_match_original_full_recursive_shape_without_timeline(self):
        baseline, _, _ = namespace(self.root, baseline=True)
        full = baseline["_compose_signature"](baseline["voice_signature"](VID), self.style)
        compact = self.ns["_compose_signature"](self.ns["_voice_performance_signature"](VID), self.style)
        self.assertEqual(compact, without_timeline(full))
        compact["raw"]["nested"]["notes"].append(123)
        self.assertEqual(self.ns["voice_signature"](VID), self.primary)
        self.assertEqual(self.ns["voice_signature"](COMPONENT), self.component)

    def test_component_lookup_does_not_copy_either_voice_timeline(self):
        class NeverCopyTimeline:
            def __deepcopy__(self, memo): raise AssertionError("component timeline traversed")
        for vid, signature_value in [(VID, self.primary), (COMPONENT, self.component)]:
            canonical = copy.deepcopy(signature_value)
            canonical["timeline"] = NeverCopyTimeline()
            self.ns["_VOICE_JSON_MEMO"][(vid, "signature.json")] = (self.clock.now, 123, canonical)
        compact = self.ns["_compose_signature"](self.ns["_voice_performance_signature"](VID), self.style)
        self.assertNotIn("timeline", compact)
        self.assertAlmostEqual(compact["energy"]["dynamics"], 0.7 + (0.42 - 0.7) * 0.4)

    def test_performance_vectors_match_full_accessor_baseline_with_components_macro_and_es(self):
        for macro, es in [("", None), ("angry", None), ("", {"tempo": 1.15, "range": 1.2, "energy": 0.1, "row": {"name": "sample"}})]:
            with self.subTest(macro=macro, es=es):
                baseline, _, _ = namespace(self.root, baseline=True)
                candidate, _, _ = namespace(self.root)
                for scope in [baseline, candidate]: scope["_RADIO"]["speaker_macro"]["dj"] = macro
                state = {"excitement": 0.4, "fatigue": 0.2, "confusion": 0.1,
                         "nervousness": 0.15, "irritation": 0.3, "amusement": 0.5}
                self.assertEqual(candidate["performance_vector"]("dj", VID, state=state, es=es),
                                 baseline["performance_vector"]("dj", VID, state=state, es=es))

    def test_missing_invalid_and_repaired_signature_follow_existing_cache_semantics(self):
        for invalid in ["", "../unsafe", "vl_bad"]:
            self.assertIsNone(self.ns["_voice_performance_signature"](invalid))
        missing = "vl_33333333"
        self.assertIsNone(self.ns["_voice_performance_signature"](missing))
        self.assertIsNone(self.ns["voice_signature"](missing))
        directory = self.root / missing
        directory.mkdir()
        (directory / "signature.json").write_text("{bad", encoding="utf-8")
        self.clock.now += 6
        self.assertIsNone(self.ns["_voice_performance_signature"](missing))
        (directory / "signature.json").write_text(json.dumps(self.primary), encoding="utf-8")
        self.clock.now += 6
        self.assertEqual(self.ns["_voice_performance_signature"](missing), without_timeline(self.primary))
        self.assertEqual(self.ns["voice_signature"](missing), self.primary)

    def test_default_snapshot_keeps_timeline_and_compact_keeps_every_other_branch(self):
        full = self.ns["_voice_json_snapshot"](self.primary)
        compact = self.ns["_voice_json_snapshot"](self.primary, omit_timeline=True)
        self.assertEqual(full, self.primary)
        self.assertEqual(compact, without_timeline(self.primary))
        self.assertEqual(self.ns["_voice_json_snapshot"](None, omit_timeline=True), None)
        self.assertEqual(self.ns["_voice_json_snapshot"]([1, {"timeline": [2]}], omit_timeline=True), [1, {"timeline": [2]}])

if __name__ == "__main__": unittest.main()
