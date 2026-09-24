"""Focused provenance checks for the image-analysis dossier."""

import ast
import hashlib
import time
import unittest
import uuid
from pathlib import Path
from typing import Any


class ImageAnalysisIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).parents[1].joinpath("app.py").read_text(
            encoding="utf-8")
        wanted = {
            "_analysis_text_match", "image_analysis_identity",
            "image_analysis_ready", "gallery_pending_set",
            "gallery_pending_analysis_ids",
        }
        tree = ast.parse(source)
        selected = [node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name in wanted]
        if {node.name for node in selected} != wanted:
            raise AssertionError("Image-analysis helper extraction is incomplete")
        cls.code = compile(ast.Module(body=selected, type_ignores=[]),
                           "app.py:image-analysis", "exec")

    def setUp(self):
        self.radio = {"chat": []}
        self.pending = {}
        self.ns = {
            "Any": Any, "hashlib": hashlib, "time": time, "uuid": uuid,
            "_RADIO": self.radio, "_GALLERY_PENDING": self.pending,
            "RADIO_CHAT_KEEP": 240,
            "_gallery_words": lambda value: set(str(value).lower().split()),
        }
        exec(self.code, self.ns)

    def test_bounded_preparation_copy_matches_full_vision_response(self):
        full = ("A cyan figure stands under a damaged station clock while "
                "amber reflections cross the wet floor. " * 14)
        self.assertTrue(self.ns["_analysis_text_match"](full[:600], full))
        self.assertFalse(self.ns["_analysis_text_match"](
            "A different reading with unrelated objects and lighting. " * 4,
            full))

    def test_analysis_id_flows_into_the_pending_gallery_lines(self):
        desc = ("A violet portrait leans into a hard green light while the "
                "background dissolves into scratched concrete. " * 8)
        ready = self.ns["image_analysis_ready"]
        first = ready("portrait.png", desc, model="vision-one", ms=420)
        self.assertEqual(len(first), 6)
        self.assertEqual(len(self.radio["chat"]), 1)
        self.assertEqual(ready("portrait.png", desc), first,
                         "the same completed pass must retain one identity")
        self.assertEqual(len(self.radio["chat"]), 1)

        self.ns["gallery_pending_set"](["portrait.png"], [desc[:600]])
        self.assertEqual(self.pending["analysis_ids"], [first])
        self.assertEqual(
            self.ns["gallery_pending_analysis_ids"](["portrait.png"]),
            [first])


if __name__ == "__main__":
    unittest.main()
