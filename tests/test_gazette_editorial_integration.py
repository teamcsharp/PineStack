"""Exercise actual Gazette press hooks without starting station services."""
import ast
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import random
import re
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import gazette_editorial
import gazette_prompt

_SOURCE = None


def app_function(name, namespace):
    """Compile actual app function source, avoiding import-time station services."""
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    start = re.search(r"(?m)^(?:async )?def " + re.escape(name) + r"\(", _SOURCE)
    if start is None:
        raise AssertionError(f"app.py has no {name} integration")
    following = re.search(r"(?m)^(?:async )?def ", _SOURCE[start.end():])
    end = start.end() + following.start() if following else len(_SOURCE)
    span = _SOURCE[start.start():end]
    decorator = re.search(r"(?m)^@", span)
    if decorator:
        span = span[:decorator.start()]
    node = next(n for n in ast.parse(span).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    namespace.setdefault("Any", object)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
    return node, namespace[name]


class GazettePressIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_topics_history_emotion_speakerbox_reach_one_cached_edition(self):
        topic = {"id": "water", "text": "The water bills keep rising."}
        seed = {"file": "civic.md", "mind": "main", "text": "Someone always gets the comfy seat.", "hash": "receipt"}
        previous = {"fictional": True, "arc": {"id": "water-arc", "stage": 1}}
        plans = [{"topic": topic, "rolls": [{"key": "fresh"}, {"key": "stale"}], "source_seed": seed}]
        sampler = [{"desk": "Gazette Roulette", "temperature": 0.9, "seed": 500000001}]
        stories = [{"slug": "city-news", "body": "Civic fiction.", "meta": {"editorial": {"topic": topic}, "copy_origin": "writer"}}]
        planner = mock.Mock(return_value=plans)
        generator = mock.AsyncMock(return_value=stories)
        writer, budget = mock.AsyncMock(), mock.Mock(return_value=20)
        seeds, used = mock.AsyncMock(return_value=[seed]), mock.Mock()
        ns = {"asyncio": asyncio, "time": SimpleNamespace(time=lambda: 1000), "PAPER_EDITORIAL_STORIES": 6, "MACRO_STATES": {"furious": {}, "smug": {}},
              "read_bombshells": mock.Mock(return_value=[topic]), "paper_latest_id": lambda: "previous",
              "paper_edition_read": mock.Mock(return_value={"articles": [{"meta": {"editorial": previous}}, {"meta": {"headline": "Air facts"}}]}),
              "gazette_editorial": SimpleNamespace(plan=planner, generate=generator, eligible_topics=lambda topics, m: topics),
              "s3_weighted": mock.Mock(), "paper_seeds": seeds, "paper_write": writer,
              "paper_press_left": budget, "paper_seeds_used": used, "_PAPER_PRESS": {"editorial_sampler": sampler},
              "system3_last_roll": lambda key: {"at": 1000 if key == "fresh" else 999, "dice": "fixture", "u": 0.25},
              "_paper_say": mock.Mock()}
        _, run = app_function("paper_editorial_stories", ns)
        material = {"station": "Pine Box FM", "host": "Tony", "cohost": "Skip", "calls": [{"name": "Nell"}]}
        self.assertIs(await run(material), stories)
        self.assertIs(await run(material), stories)
        planner.assert_called_once()
        args, kwargs = planner.call_args
        self.assertEqual(args[:2], ([topic], material))
        self.assertIs(args[2], ns["s3_weighted"])
        self.assertEqual(kwargs["previous"], [previous])
        self.assertEqual(kwargs["emotions"], ["furious", "smug"])
        self.assertEqual(kwargs["most"], 6)
        self.assertEqual(kwargs["seeds"], [seed])
        generator.assert_awaited_once_with(plans, writer, budget)
        seeds.assert_awaited_once()
        used.assert_called_once_with([seed])
        self.assertEqual(stories[0]["meta"]["editorial"]["sampler"], sampler)
        self.assertEqual(plans[0]["rolls"][0]["rng"], {"dice": "fixture", "u": 0.25})
        self.assertNotIn("rng", plans[0]["rolls"][1])

    async def test_disabled_editorial_does_not_draw_topics_or_spend_writer_calls(self):
        topics = mock.Mock()
        ns = {"PAPER_EDITORIAL_STORIES": 0, "read_bombshells": topics}
        _, run = app_function("paper_editorial_stories", ns)
        self.assertEqual(await run({}), [])
        topics.assert_not_called()

    async def test_empty_topic_bank_does_not_create_a_fake_draw(self):
        seeds, picker, planner = mock.AsyncMock(), mock.Mock(), mock.Mock()
        ns = {"asyncio": asyncio, "PAPER_EDITORIAL_STORIES": 6,
              "read_bombshells": lambda: [], "paper_latest_id": lambda: "",
              "gazette_editorial": SimpleNamespace(eligible_topics=lambda topics, m: [], plan=planner),
              "paper_seeds": seeds, "s3_weighted": picker, "_paper_say": mock.Mock()}
        _, run = app_function("paper_editorial_stories", ns)
        material = {}
        self.assertEqual(await run(material), [])
        self.assertEqual(await run(material), [])
        self.assertEqual(material["editorial_status"], "no eligible topics")
        seeds.assert_not_awaited()
        picker.assert_not_called()
        planner.assert_not_called()
    async def test_both_editorial_writer_passes_have_single_json_contract(self):
        response = [{"index": 0, "headline": "Mayor defends the hidden camera remark", "body": "The fictional city council argued over the water bills."}]
        answer = "<think>private scratchpad</think>\n" + json.dumps(response)
        for desk in ("Gazette Roulette", "Gazette Roulette Coherence"):
            with self.subTest(desk=desk):
                writer = mock.AsyncMock(return_value={"message": {"content": answer}})
                ns = {"asyncio": asyncio, "time": time, "random": random, "re": re,
                      "load_settings": lambda: {"model": "writer"}, "PAPER_MODEL": "writer", "PAPER_WRITER_MAX": 12,
                      "_PAPER_PRESS": {"writer_calls": 0}, "paper_press_left": lambda reserve=False: 30,
                      "_paper_say": mock.Mock(), "plotline_paper_clause": lambda: "", "gazette_editorial": gazette_editorial,
                      "call_ollama": writer, "model_ctx": lambda: 8192,
                      "s3_weighted": mock.Mock(return_value=2), "s3_roll": mock.Mock(return_value=0.25)}
                _, run = app_function("_paper_write_inner", ns)
                result = await run(desk, "Expand the topic into civic fiction.", "Exact source material.", (250, 900))
                self.assertEqual(json.loads(result["body"]), response)
                self.assertEqual(writer.call_args.kwargs["result_schema"], {
                    "type": "array", "minItems": 1, "maxItems": 6,
                    "items": {"type": "object", "additionalProperties": False,
                              "required": ["index", "headline", "body"],
                              "properties": {
                                  "index": {"type": "integer", "minimum": 0, "maximum": 5},
                                  "headline": {"type": "string"}, "body": {"type": "string"}}}})
                messages = writer.call_args.kwargs["messages"]
                self.assertEqual(messages[0]["content"], gazette_editorial.system_prompt())
                self.assertNotIn("HEADLINE: <", messages[0]["content"])
                self.assertIn("fiction", messages[0]["content"].lower())
                self.assertIn("No invented dialogue is a recorded call or broadcast", messages[0]["content"])
                self.assertIn("Exact source material.", messages[1]["content"])
                self.assertEqual(ns["_PAPER_PRESS"]["writer_calls"], 1)
                self.assertEqual(writer.call_args.kwargs["temperature"], 0.9)
                self.assertEqual(writer.call_args.kwargs["seed"], 500000001)
                self.assertEqual(ns["_PAPER_PRESS"]["editorial_sampler"], [{"desk": desk, "temperature": 0.9, "seed": 500000001}])
                self.assertEqual(ns["s3_weighted"].call_args.args[0], "gazette.editorial.writer.temperature")
                self.assertEqual(ns["s3_roll"].call_args.args[0], "gazette.editorial.writer.seed")

    async def test_editorial_writer_obeys_existing_press_budget(self):
        writer = mock.AsyncMock()
        ns = {"load_settings": lambda: {"model": "writer"}, "PAPER_MODEL": "writer", "PAPER_WRITER_MAX": 4,
              "_PAPER_PRESS": {"writer_calls": 2}, "paper_press_left": lambda reserve=False: 30,
              "_paper_say": mock.Mock(), "call_ollama": writer}
        _, run = app_function("_paper_write_inner", ns)
        self.assertEqual(await run("Gazette Roulette", "brief", "topic"), {})
        writer.assert_not_awaited()
        self.assertEqual(ns["_PAPER_PRESS"]["writer_refused"], 1)

    async def test_press_editorial_precedes_city_copy_after_budget_reset(self):
        for offline in (False, True):
            with self.subTest(offline=offline):
                events = []
                story = {"slug": "city-news", "meta": {"headline": "Civic topic", "editorial": {"fictional": True}}, "body": "A city story."}
                material = {"station": "Pine Box FM", "records": [{"title": "Record"}], "calls": [], "ads": [],
                            "wire": [], "memos": [], "said": {}, "offline": offline}

                async def editorial(m):
                    events.append("editorial")
                    self.assertEqual(m["broadcast"], not offline)
                    return [story]

                def city(m):
                    events.append("city")

                ns = {"asyncio": asyncio, "time": time, "_PAPER_LOCK": threading.Lock(), "_PAPER": {}, "_PAPER_PRESS": {},
                      "paper_window": lambda kind: (1000, 2000, "edition"), "_paper_masthead_seed": lambda: None,
                      "_paper_say": lambda *args: None, "_paper_hour_words": lambda at: "one",
                      "paper_material": mock.AsyncMock(return_value=material), "paper_press_reset": lambda: events.append("reset"),
                      "paper_gallery_subjects": lambda m: [], "system_stats": lambda: "", "paper_editorial_stories": editorial,
                      "paper_story_empty": lambda s: "", "_desk_city": city}
                for name in ("records", "adverts", "hour", "sports", "engineering", "device", "dgx", "weather", "banked"):
                    ns["_desk_" + name] = lambda *args: None
                node, _ = app_function("paper_print", ns)
                node = copy.deepcopy(node)
                press_try = next(n for n in node.body if isinstance(n, ast.Try))
                # Execute the real press through its legacy city desk, stopping
                # before export and publication services unrelated to this hook.
                stop = next(i for i, statement in enumerate(press_try.body)
                            if any(isinstance(n, ast.Name) and n.id == "_desk_city" for n in ast.walk(statement)))
                press_try.body = press_try.body[:stop + 1] + [ast.Return(value=ast.Name(id="stories", ctx=ast.Load()))]
                press_try.handlers, press_try.orelse, press_try.finalbody = [], [], [ast.Pass()]
                ast.fix_missing_locations(node)
                exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), ns)
                self.assertEqual(await ns["paper_print"]("test", "hourly"), [story])
                self.assertEqual(events, ["reset", "editorial", "city"])



class GazetteTintIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        topics = [{"id": "water", "text": "water permits reserved for friends"}]
        material = {"station": "Pine Box FM", "host": "Jules", "cohost": "Ada",
                    "calls": [{"name": "Ruth Caller"}]}

        def first_available(key, labels, weights, description):
            return next(index for index, weight in enumerate(weights) if weight > 0)

        self.plans = gazette_editorial.plan(topics, material, first_available)

    def tint_namespace(self, writer):
        ns = {"asyncio": asyncio, "time": time, "re": re, "hashlib": hashlib,
              "gazette_editorial": gazette_editorial, "TINT_TURN_FLOOR": 24,
              "crystal_coverage_target": lambda: 100,
              "paper_tint_caps": lambda: (10, 20, 1000), "paper_tint_left": lambda: 30,
              "crystal_tint_two_pass": lambda: True, "crystal_active": lambda: True,
              "tint_should_stop": lambda: "", "tint_fast_model": lambda: "tint-fixture",
              "WritingDeferred": type("WritingDeferred", (RuntimeError,), {}),
              "crystal_line": writer, "tint_output_ready": mock.Mock(return_value=True),
              "_PAPER_PRESS": {"started": 1000}, "_TINT_OUTPUT_READY": {},
              "_paper_tint_why": mock.Mock(), "_tint_flow": mock.Mock()}
        for name in ("paper_tint_units", "paper_tint_plan", "_paper_city_tint_target",
                     "_paper_tint_store", "paper_tint_story", "paper_tint_cut"):
            app_function(name, ns)
        return ns

    async def test_editorial_tint_rejects_invalid_assembled_rewrites_before_accepted_stamp(self):
        story = gazette_editorial.fallback(self.plans[-1])
        original = story["body"]
        self.assertEqual(gazette_editorial.validate_story(story), [])
        writer = mock.AsyncMock(return_value=(
            "The moon turns silver over streets where sleepy neighbours wait beside the gate."))
        ns = self.tint_namespace(writer)
        store = mock.Mock(wraps=ns["_paper_tint_store"])
        ns["_paper_tint_store"] = store
        report = ns["paper_tint_plan"](story)

        self.assertFalse(await ns["paper_tint_story"](story, "test the rolled case"))
        self.assertEqual(story["body"], original)
        self.assertFalse(story["meta"]["tinted"])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["changed"], 0)
        self.assertEqual(report["attempted"], 2)
        self.assertFalse(any(row["ok"] for row in report["paragraphs"]))
        self.assertTrue(all(row["output_hash"] == "" for row in report["paragraphs"]))
        self.assertIn("rolled official reaction omitted", report["paragraphs"][-1]["faults"])
        self.assertNotIn("tinted_paras", ns["_PAPER_PRESS"])
        self.assertNotIn("tinted_stories", ns["_PAPER_PRESS"])
        store.assert_not_called()
        self.assertEqual(ns["tint_output_ready"].call_count, 2)
        self.assertEqual(writer.await_count, 2)
        self.assertTrue(all(call.args[1] == "failed" for call in ns["_tint_flow"].call_args_list))
        self.assertEqual(gazette_editorial.validate_story(story), [])

    async def test_valid_editorial_tint_keeps_case_and_records_accepted_rewrites(self):
        story = gazette_editorial.fallback(self.plans[-1])
        original = story["body"]

        async def rewrite(source, why, room, **kwargs):
            return source + " The Gazette keeps the original receipts on file."

        ns = self.tint_namespace(mock.AsyncMock(side_effect=rewrite))
        report = ns["paper_tint_plan"](story)
        self.assertTrue(await ns["paper_tint_story"](story, "test the rolled case"))
        self.assertNotEqual(story["body"], original)
        self.assertEqual(gazette_editorial.validate_story(story), [])
        self.assertTrue(story["meta"]["tinted"])
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["changed"], 2)
        self.assertTrue(all(row["ok"] and row["output_hash"] for row in report["paragraphs"]))
        self.assertEqual(ns["_PAPER_PRESS"]["tinted_paras"], 2)
        self.assertEqual(ns["_PAPER_PRESS"]["tinted_stories"], 1)

    def test_editorial_cut_preserves_each_sections_rolled_case_and_tint_records(self):
        ns = self.tint_namespace(mock.AsyncMock())
        for plan in self.plans:
            with self.subTest(section=plan["section"]):
                story = gazette_editorial.fallback(plan)
                original_body = story["body"]
                original_headline = story["meta"]["headline"]
                original_receipt = copy.deepcopy(story["meta"]["editorial"])
                self.assertEqual(gazette_editorial.validate_story(story), [])
                report = ns["paper_tint_plan"](story)
                report["changed"] = 1
                report["paragraphs"] = [
                    {"key": "body:0", "ok": True, "output_hash": "accepted-first"},
                    {"key": "body:1", "ok": False, "output_hash": ""}]
                original_records = copy.deepcopy(report["paragraphs"])

                self.assertEqual(ns["paper_tint_cut"](story), 0)
                self.assertTrue(report["cut_refused"])
                self.assertEqual(story["body"], original_body)
                self.assertEqual(story["meta"]["headline"], original_headline)
                self.assertEqual(story["meta"]["editorial"], original_receipt)
                self.assertEqual(report["paragraphs"], original_records)
                self.assertEqual(report["required"], 2)
                self.assertNotIn("cut", report)
                self.assertEqual(gazette_editorial.validate_story(story), [])

    def test_legacy_tint_cut_still_cuts_and_rekeys_body_and_classifieds(self):
        ns = self.tint_namespace(mock.AsyncMock())
        paragraphs = ["The original opening remains at the top of the newspaper story.",
                      "This ordinary paragraph was refused by the tint writer and should be cut.",
                      "This accepted paragraph keeps its place after the refused paragraph is cut."]
        rows = [{"body": "A refused classified notice offering an old bicycle for sale."},
                {"body": "An accepted classified notice seeks a neighbour with a spare wheel."}]
        story = {"slug": "legacy-city", "body": "\n\n".join(paragraphs),
                 "meta": {"headline": "The city's ordinary news story", "classifieds": copy.deepcopy(rows)}}
        report = ns["paper_tint_plan"](story)
        report["changed"] = 2
        report["paragraphs"] = [
            {"key": "body:0", "ok": False}, {"key": "body:1", "ok": False},
            {"key": "body:2", "ok": True, "output_hash": "accepted-body"},
            {"key": "classified:0", "ok": False},
            {"key": "classified:1", "ok": True, "output_hash": "accepted-notice"}]

        self.assertEqual(ns["paper_tint_cut"](story), 2)
        self.assertEqual(story["body"], "\n\n".join((paragraphs[0], paragraphs[2])))
        self.assertEqual(story["meta"]["classifieds"], [rows[1]])
        self.assertEqual(report["paragraphs"], [
            {"key": "body:0", "ok": False},
            {"key": "body:1", "ok": True, "output_hash": "accepted-body"},
            {"key": "classified:0", "ok": True, "output_hash": "accepted-notice"}])
        self.assertEqual(report["cut"], 2)
        self.assertEqual(report["eligible"], 3)
        self.assertEqual(report["required"], 3)
        self.assertNotIn("cut_refused", report)


class GazettePublishedIntegration(unittest.TestCase):
    def test_editorial_receipts_round_trip_in_actual_frontmatter(self):
        ns = {"json": json, "re": re}
        for name in ("_fm_scalar", "_fm_dump", "_fm_split_list", "_fm_unquote", "_fm_load"):
            app_function(name, ns)
        receipt = {"schema": "gazette.editorial/1", "fictional": True,
                   "topic": {"id": "water", "text": "Bills, pipes: and an official's excuse"},
                   "cast": {"official": {"name": "Mayor Vera Brass", "role": "mayor"}},
                   "arc": {"id": "water-arc", "stage": 2, "response": "double down"},
                   "rolls": [{"key": "gazette.editorial.topic", "chosen": "water", "labels": ["water", "music"]}],
                   "source_seed": {"file": "civic.md", "text": "She said, \"Keep the receipts.\""},
                   "media": {"image_prompt": "Mayor confronts the hidden camera", "video_prompt": "A smug reaction"}}
        media = {"status": "queued", "image": {"file": "city-water.png", "prompt_id": "comfy-123"},
                 "video": {"status": "pending", "job_id": "h3-city-water", "reaction": "double down"}}
        meta = {"headline": "The mayor keeps defending her water bills", "section": "news", "editorial": receipt, "media": media}
        loaded, body, error = ns["_fm_load"](ns["_fm_dump"](meta) + "\nCivic fiction remains in the story.")
        self.assertEqual(error, "")
        self.assertEqual(loaded["editorial"], receipt)
        self.assertEqual(loaded["media"], media)
        self.assertIn("Civic fiction", body)

    def test_media_attachment_rejects_stale_story_and_persists_ready_receipts(self):
        ns = {"json": json, "re": re, "Path": Path, "_PAPER_LOCK": threading.Lock(), "_PAPER": {}}
        for name in ("_fm_scalar", "_fm_dump", "_fm_split_list", "_fm_unquote", "_fm_load", "_paper_media_attach_disk"):
            app_function(name, ns)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "articles").mkdir()
            ns["paper_edition_dir"] = lambda edition_id: directory
            path = directory / "articles" / "city-water.md"
            editorial = {"id": "current-water-case", "fictional": True, "topic": {"id": "water", "text": "Water bills"}}
            body = "The mayor defended the fictional water bill while residents compared receipts."
            path.write_text(ns["_fm_dump"]({"headline": "Water bill dispute", "editorial": editorial}) + "\n" + body, encoding="utf-8")
            summary = directory / "edition.json"
            summary.write_text(json.dumps({"id": "edition", "at": 1000}), encoding="utf-8")
            cache_names = ("edition.html", "edition.broadsheet.html", "edition.tabloid.html", "edition.broadsheet.pdf", "edition.tabloid.pdf")
            for name in cache_names:
                (directory / name).write_bytes(b"old export")
            receipt = {"editorial_id": "current-water-case", "status": "ready",
                       "image": {"status": "ready", "file": "mayor.png", "url": "/api/image/mayor.png", "prompt_id": "comfy-123"},
                       "video": {"status": "ready", "file": "mayor.mp4", "url": "/api/workshop/generation/mayor.mp4", "job_id": "h3-123"}}
            attach = ns["_paper_media_attach_disk"]
            stale = dict(receipt, editorial_id="previous-water-case")
            original = path.read_text(encoding="utf-8")
            self.assertFalse(attach("edition", path.name, "image", receipt["image"]["url"], stale))
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertTrue(all((directory / name).exists() for name in cache_names))
            self.assertTrue(attach("edition", path.name, "image", receipt["image"]["url"], receipt))
            meta, loaded_body, error = ns["_fm_load"](path.read_text(encoding="utf-8"))
            self.assertEqual(error, "")
            self.assertEqual(meta["editorial"], editorial)
            self.assertEqual(meta["media"], receipt)
            self.assertEqual(loaded_body, body)
            published = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(published["media_revision"], 1)
            self.assertEqual(published["media"]["image"], "ready")
            self.assertEqual(published["media"]["video"], "ready")
            self.assertEqual(ns["_PAPER"]["media_status"], "ready")
            self.assertTrue(all(not (directory / name).exists() for name in cache_names))
            for name in cache_names:
                (directory / name).write_bytes(b"fresh export")
            self.assertFalse(attach("edition", path.name, "image", receipt["image"]["url"], receipt))
            self.assertEqual(json.loads(summary.read_text(encoding="utf-8"))["media_revision"], 1)
            self.assertTrue(all((directory / name).exists() for name in cache_names))
    def test_gazette_token_marks_fiction_and_draws_section_then_article(self):
        edition = {"id": "printed", "articles": [{"file": "city-water.md",
                   "meta": {"section": "wire", "headline": "Mayor defends a city favour", "editorial": {"fictional": True}},
                   "body": "The fictional mayor defended the disputed water contract."}]}
        picks = []
        def weighted(key, labels, weights, label):
            picks.append(key)
            return 0
        result = gazette_prompt.draw(gazette_prompt.articles(edition), weighted)
        self.assertEqual(picks, ["gazette.section", "gazette.article"])
        self.assertIn("fictional Pinebox city satire", result["prompt"])
        self.assertIn("disputed water contract", result["prompt"])

    def test_html_cache_rejects_old_render_written_after_new_media_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            summary = directory / "edition.json"
            summary.write_text(json.dumps({"id": "edition", "media_revision": 0}), encoding="utf-8")
            def read(edition_id):
                return json.loads(summary.read_text(encoding="utf-8"))
            def render(ed, style):
                if ed["media_revision"] == 0:
                    summary.write_text(json.dumps({"id": "edition", "media_revision": 1}), encoding="utf-8")
                return (f'<!--PAPER_RENDER_VERSION=77 style={style} media_revision={ed["media_revision"]}-->'
                        f'<article>revision={ed["media_revision"]}</article>')
            renderer = mock.Mock(side_effect=render)
            ns = {"Path": Path, "json": json, "PAPER_RENDER_VERSION": 77, "_paper_style": lambda style: style,
                  "paper_edition_dir": lambda edition_id: directory, "paper_edition_read": read, "paper_render_html": renderer}
            _, run = app_function("paper_html_for", ns)
            self.assertIn("revision=0", run("edition", "tabloid"))
            self.assertIn("revision=1", run("edition", "tabloid"))
            self.assertIn("revision=1", run("edition", "tabloid"))
            self.assertEqual(renderer.call_count, 2)

    def test_pdf_cache_rejects_old_render_written_after_new_media_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            summary = directory / "edition.json"
            summary.write_text(json.dumps({"id": "edition", "media_revision": 0}), encoding="utf-8")
            def read(edition_id):
                return json.loads(summary.read_text(encoding="utf-8"))
            def render(ed, style, base):
                if ed["media_revision"] == 0:
                    summary.write_text(json.dumps({"id": "edition", "media_revision": 1}), encoding="utf-8")
                return f'pdf revision={ed["media_revision"]}'.encode()
            renderer = mock.Mock(side_effect=render)
            ns = {"Path": Path, "json": json, "PAPER_PDF_VERSION": 55, "_paper_style": lambda style: style,
                  "paper_edition_dir": lambda edition_id: directory, "paper_edition_read": read, "paper_pdf": renderer}
            app_function("paper_pdf_path", ns)
            _, run = app_function("paper_pdf_for", ns)
            self.assertEqual(run("edition", "tabloid"), b"pdf revision=0")
            self.assertEqual(run("edition", "tabloid"), b"pdf revision=1")
            self.assertEqual(run("edition", "tabloid"), b"pdf revision=1")
            self.assertEqual(renderer.call_count, 2)
            self.assertEqual((directory / "edition.tabloid.pdf.v").read_text().strip(), "55:1")
    def test_city_fiction_uses_system3_in_later_station_discussion(self):
        receipt = {"fictional": True, "kind": "fictional_city", "topic": {"id": "water", "text": "Water bills"}}
        edition = {"id": "edition", "at": 1000, "articles": [
            {"file": "mayor.md", "meta": {"headline": "Mayor defends the water bills", "section": "news", "editorial": receipt},
             "body": "Mayor Vera Brass defended the city's water bills while residents demanded the hidden camera transcript."},
            {"file": "letter.md", "meta": {"headline": "A letter to the water department", "section": "letters", "editorial": receipt},
             "body": "Nell wrote to the fictional water department and copied the station hosts into the correspondence."},
            {"file": "record.md", "meta": {"headline": "An actual record played", "section": "music"},
             "body": "The broadcast log records a song that played during the previous hour at the station."}]}
        picks = []

        def weighted(key, labels, weights, label):
            picks.append((key, list(labels)))
            return 0

        now = SimpleNamespace(time=lambda: 2000)
        ns = {"time": now, "_PAPER_DISCUSSION_LOCK": threading.Lock(), "_PAPER_DISCUSSION": {},
              "paper_latest_id": lambda: "edition", "paper_edition_read": lambda eid: edition,
              "_paper_md_plain": lambda text: text, "s3_weighted": weighted, "gazette_prompt": gazette_prompt,
              "_tint_flow": mock.Mock(), "pipeline_log": mock.Mock()}
        _, run = app_function("paper_discussion_context", ns)
        first = run()
        self.assertTrue(first.get("articles"))
        self.assertTrue(any("section" in key for key, _ in picks))
        self.assertTrue(any("article" in key for key, _ in picks))
        self.assertIn("fiction", first["prompt"].lower())
        self.assertEqual(first["articles"][0].get("editorial"), receipt)
        second = run()
        self.assertTrue(set(r["file"] for r in first["articles"]).isdisjoint(r["file"] for r in second["articles"]))
        self.assertEqual(run(), {})
        now.time = lambda: 1000 + 7 * 3600
        self.assertEqual(run(), {})


if __name__ == "__main__":
    unittest.main()




