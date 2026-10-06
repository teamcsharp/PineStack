"""[llm-command] 2026-10-06: the command book from a fake host.

    python3 -m unittest tests/test_llm_commands_2026_10_06.py

The host is app.py's globals in miniature: one cheap parser per name of the
chain, in the shapes the real ones return (bool, dict, str), a fake
orch_command_run, and a data_path into a temp folder. The route tests run when
FastAPI's TestClient is importable (it is in the station container) and are
skipped elsewhere.
"""
import asyncio
import json
import re
import tempfile
import time
import unittest
from pathlib import Path

import llm_commands


def fake_host(tmp):
    g = {"data_path": lambda n: tmp / n}
    g["parse_show_doctor"] = lambda t: bool(re.search(r"where are the djs", t, re.I))
    g["parse_what_happened"] = lambda t: bool(re.search(r"what happened", t, re.I))
    g["parse_export_command"] = lambda t: {"seconds": 300, "kind": "talk"} if "export" in t.lower() else None
    g["parse_directive"] = lambda t: ({"text": t, "road": "ad", "move": "less", "shape": "standing"}
                                      if t.lower().startswith("from now on") else None)
    g["te_manual_intent"] = lambda t: None
    g["is_memory_command"] = lambda t: t[9:] if t.lower().startswith("remember ") else None
    g["is_system_query"] = lambda t: "ram" in t.lower()
    g["parse_service_command"] = lambda t: "comfyui" if "restart comfy" in t.lower() else ""
    g["parse_broadcast_command"] = lambda t: {"music": "nabu"} if "broadcast to the nabu" in t.lower() else None
    g["parse_paper_command"] = lambda t: "print" if "print the paper" in t.lower() else ""
    g["is_services_query"] = lambda t: "services" in t.lower()
    g["is_comfy_status_query"] = lambda t: "comfy" in t.lower()      # also true for "restart comfy": the chain decides
    g["is_weather_query"] = lambda t: "weather" in t.lower()
    g["is_song_query"] = lambda t: False
    g["is_te_query"] = lambda t: False
    g["is_library_query"] = lambda t: False
    g["is_tv_query"] = lambda t: "episode" in t.lower()
    g["is_game_query"] = lambda t: "cheat" in t.lower()
    g["is_research_query"] = lambda t: "datasheet" in t.lower()
    g["orch_verbs"] = lambda: ("drive", "noop", "thin")
    g["BROADCAST_STEPS"] = [{"key": "look"}, {"key": "repair"}]

    async def orch_command_run(text):
        return {"ok": not text.startswith("bogus"), "say": "ran " + text, "lines": ["the dial moved"], "text": text}
    g["orch_command_run"] = orch_command_run
    return g


def chain(g, text):
    """What generate_answer does with the chain: ask in order, the first truthy one owns the turn."""
    for name in llm_commands.CHAIN:
        if g[name](text):
            return name
    return ""


class CommandBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.g = fake_host(self.tmp)
        self.book = llm_commands.install(None, self.g)

    def test_every_parser_of_the_chain_has_a_row(self):
        named = {"is_weather_query", "is_game_query", "is_research_query", "is_tv_query", "te_manual_intent",
                 "is_library_query", "is_te_query", "is_system_query", "is_comfy_status_query", "is_song_query",
                 "parse_directive", "is_memory_command", "parse_what_happened", "parse_broadcast_command",
                 "is_services_query", "parse_service_command", "parse_export_command", "parse_paper_command",
                 "parse_show_doctor"}
        ids = {b["id"] for b in llm_commands.BUILTINS}
        self.assertEqual(ids, named)
        self.assertEqual(set(llm_commands.CHAIN), named)
        self.assertEqual(len(llm_commands.CHAIN), len(set(llm_commands.CHAIN)))
        for b in llm_commands.BUILTINS:
            self.assertTrue(3 <= len(b["examples"]) <= 6, (b["id"], len(b["examples"])))
            self.assertTrue(b["does"] and b["name"], b["id"])
        orch = {o["id"] for o in llm_commands.ORCHESTRATOR}
        for want in ("help", "more", "less", "ease", "drop", "policy", "run", "hear", "retire", "why",
                     "why-code", "s3", "s3-propose", "s3-confirm"):
            self.assertIn("orch:" + want, orch)
        rows = self.book.rows()
        self.assertEqual(len(rows), len(llm_commands.BUILTINS) + len(llm_commands.ORCHESTRATOR))
        # the chain order is on every built-in row, and the live policy verbs and rungs are read off g
        self.assertEqual([r["id"] for r in rows if r["kind"] == "builtin"], list(llm_commands.CHAIN))
        policy = [r for r in rows if r["id"] == "orch:policy"][0]
        self.assertIn("drive, noop, thin", policy["does"])
        run = [r for r in rows if r["id"] == "orch:run"][0]
        self.assertIn("look, repair", run["does"])

    def test_watch_wraps_every_parser_and_keeps_its_answer(self):
        for name in llm_commands.CHAIN:
            self.assertTrue(getattr(self.g[name], "_llm_watch", False), name)
        self.assertEqual(self.g["parse_export_command"]("export the tape"), {"seconds": 300, "kind": "talk"})
        self.assertEqual(self.g["parse_service_command"]("restart comfy"), "comfyui")
        self.assertIs(self.g["is_weather_query"]("weather"), True)
        self.assertIsNone(self.g["parse_export_command"]("hello"))
        self.assertEqual(self.g["parse_service_command"]("hello"), "")

    def test_one_hit_per_utterance_the_first_in_chain_order(self):
        said = "restart comfy please"
        self.assertEqual(chain(self.g, said), "parse_service_command")
        # the chain stopped there; had it gone on, the comfy status parser also says yes - same text, same turn
        self.assertTrue(self.g["is_comfy_status_query"](said))
        self.assertEqual(self.book.count_of("parse_service_command")["count"], 1)
        self.assertEqual(self.book.count_of("is_comfy_status_query")["count"], 0)
        self.assertEqual(self.book.count_of("parse_service_command")["last_text"], said)
        # a different sentence is a different turn
        self.assertEqual(chain(self.g, "is comfy running"), "is_comfy_status_query")
        self.assertEqual(self.book.count_of("is_comfy_status_query")["count"], 1)
        # and the same sentence again after the window counts again
        self.book._last["at"] -= llm_commands.HIT_WINDOW_S + 1
        chain(self.g, "is comfy running")
        self.assertEqual(self.book.count_of("is_comfy_status_query")["count"], 2)
        # nothing truthy, nothing counted
        self.assertEqual(chain(self.g, "tell me a story"), "")
        self.assertEqual(self.book.summary()["hits"], 3)

    def test_a_switched_off_builtin_answers_falsy_in_its_own_shape_and_is_not_counted(self):
        self.book.note("parse_export_command", enabled=False)
        self.book.note("parse_service_command", enabled=False)
        self.book.note("is_weather_query", enabled=False)
        self.assertIsNone(self.g["parse_export_command"]("export the last five minutes"))
        self.assertEqual(self.g["parse_service_command"]("restart comfy"), "")
        self.assertIs(self.g["is_weather_query"]("weather"), False)
        self.assertEqual(self.book.count_of("parse_export_command")["count"], 0)
        row = self.book.row("parse_export_command")
        self.assertFalse(row["enabled"])
        # with export off, "restart comfy" now reaches the comfy status question - the chain moves on
        self.assertEqual(chain(self.g, "restart comfy"), "is_comfy_status_query")
        self.book.note("parse_export_command", enabled=True)
        self.assertEqual(self.g["parse_export_command"]("export it"), {"seconds": 300, "kind": "talk"})

    def test_the_orchestrator_line_is_counted_by_verb(self):
        run = self.g["orch_command_run"]
        self.assertTrue(getattr(run, "_llm_watch", False))
        got = asyncio.run(run("more banter"))
        self.assertEqual(got["say"], "ran more banter")
        asyncio.run(run("drive:banter"))
        asyncio.run(run("why #a1b2c3"))
        asyncio.run(run("why news"))
        asyncio.run(run("s3 confirm p1"))
        asyncio.run(run("s3 table T1 set x=1"))
        asyncio.run(run("run look"))
        asyncio.run(run("bogus verb"))
        asyncio.run(run("nonsense here"))
        counts = {k: v["count"] for k, v in self.book.counts.items()}
        self.assertEqual(counts, {"orch:more": 1, "orch:policy": 1, "orch:why-code": 1, "orch:why": 1,
                                  "orch:s3-confirm": 1, "orch:s3-propose": 1, "orch:run": 1})

    def test_custom_commands_rewrite_reply_and_run_the_orchestrator(self):
        self.book.custom_upsert({"name": "Cut me a tape", "triggers": ["cut me a tape", "/^tape (it|that)$/"],
                                 "does": {"as": "export the last five minutes"}, "notes": "the quick cut"})
        self.book.custom_upsert({"name": "Who are you", "triggers": ["who are you"],
                                 "does": {"say": "I am the Pine Box."}})
        self.book.custom_upsert({"name": "More jokes", "triggers": ["more jokes", "play * on the box"],
                                 "does": {"orchestrator": "more banter"}})
        self.book.custom_upsert({"name": "Sleeping", "triggers": ["goodnight"], "does": {"say": "zzz"}, "enabled": False})
        # the lead and the pleasantries do not matter; the sentence must be the sentence
        text, cmd = self.book.rewrite("Hey Pine Box, cut me a tape please.")
        self.assertEqual(text, "export the last five minutes")
        self.assertEqual(cmd["id"], "custom:cut-me-a-tape")
        self.assertEqual(self.book.rewrite("tape that")[0], "export the last five minutes")
        self.assertEqual(self.book.rewrite("cut me a tape and then some")[0], "cut me a tape and then some")
        self.assertEqual(self.book.rewrite("who are you"), ("who are you", None))     # a say, not an as
        self.assertEqual(self.book.fixed_reply("who are you?"), "I am the Pine Box.")
        self.assertEqual(self.book.fixed_reply("cut me a tape"), "")
        self.assertEqual(self.book.orchestrator_line("more jokes"), "more banter")
        self.assertEqual(self.book.orchestrator_line("play the heat theme on the box"), "more banter")
        self.assertEqual(self.book.orchestrator_line("who are you"), "")
        self.assertEqual(self.book.fixed_reply("goodnight"), "")                      # switched off
        # each matched custom counted once per sentence
        self.assertEqual(self.book.count_of("custom:cut-me-a-tape")["count"], 2)
        self.assertEqual(self.book.count_of("custom:who-are-you")["count"], 1)
        self.assertEqual(self.book.count_of("custom:more-jokes")["count"], 2)
        rows = [r for r in self.book.rows() if r["kind"] == "custom"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["examples"], ["cut me a tape", "/^tape (it|that)$/"])
        self.assertEqual(rows[0]["how"], "as")
        self.assertIn("export the last five minutes", rows[0]["does"])
        # module-level doors reach the installed book
        self.assertEqual(llm_commands.fixed_reply("who are you"), "I am the Pine Box.")
        self.assertEqual(llm_commands.rewrite("cut me a tape")[0], "export the last five minutes")
        self.assertEqual(llm_commands.orchestrator_line("more jokes"), "more banter")

    def test_a_custom_command_is_refused_when_it_is_not_one(self):
        with self.assertRaises(llm_commands.BookError):
            self.book.custom_upsert({"triggers": ["x"], "does": {"say": "y"}})
        with self.assertRaises(llm_commands.BookError):
            self.book.custom_upsert({"name": "n", "triggers": [], "does": {"say": "y"}})
        with self.assertRaises(llm_commands.BookError):
            self.book.custom_upsert({"name": "n", "triggers": ["/(/"], "does": {"say": "y"}})
        with self.assertRaises(llm_commands.BookError):
            self.book.custom_upsert({"name": "n", "triggers": ["x"], "does": {"say": "y", "as": "z"}})
        with self.assertRaises(llm_commands.BookError):
            self.book.custom_upsert({"name": "n", "triggers": ["x"], "does": {}})
        with self.assertRaises(llm_commands.BookError):
            self.book.note("no-such-command", notes="x")
        self.assertEqual(self.book.custom, [])

    def test_upsert_edits_by_id_and_delete_forgets(self):
        row = self.book.custom_upsert({"name": "Tape", "triggers": ["tape"], "does": {"say": "a"}})
        again = self.book.custom_upsert({"id": row["id"], "name": "Tape two", "triggers": ["tape", "tapes"],
                                         "does": {"say": "b"}})
        self.assertEqual(again["id"], row["id"])
        self.assertEqual(len(self.book.custom), 1)
        self.assertEqual(self.book.fixed_reply("tapes"), "b")
        other = self.book.custom_upsert({"name": "Tape two", "triggers": ["t"], "does": {"say": "c"}})
        self.assertNotEqual(other["id"], row["id"])         # a new command, a numbered id
        self.assertTrue(self.book.custom_delete(row["id"]))
        self.assertFalse(self.book.custom_delete(row["id"]))
        self.assertEqual(self.book.fixed_reply("tapes"), "")
        self.assertEqual([c["id"] for c in self.book.custom], [other["id"]])

    def test_the_book_persists_and_comes_back(self):
        chain(self.g, "restart comfy")
        self.book.note("parse_export_command", notes="the quick cut", enabled=False)
        self.book.custom_upsert({"name": "Cut me a tape", "triggers": ["cut me a tape"],
                                 "does": {"as": "export the last five minutes"}})
        path = self.book.save()
        self.assertEqual(path, self.tmp / "llm_commands.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["counts"]["parse_service_command"]["count"], 1)
        self.assertEqual(data["notes"]["parse_export_command"], "the quick cut")
        self.assertEqual(data["disabled"], ["parse_export_command"])
        self.assertEqual(data["custom"][0]["id"], "custom:cut-me-a-tape")
        again = llm_commands.CommandBook(fake_host(self.tmp))
        self.assertEqual(again.count_of("parse_service_command")["count"], 1)
        self.assertEqual(again.row("parse_export_command")["notes"], "the quick cut")
        self.assertFalse(again.row("parse_export_command")["enabled"])
        # (a dry run: a hit on this second book would schedule its own write of the same file and race the first)
        self.assertEqual(again.try_text("cut me a tape")["rewritten"], "export the last five minutes")
        # a hit writes the file by itself, a moment later (the write is deferred SAVE_DELAY_S, off the loop)
        chain(self.g, "what's the weather")
        deadline = time.time() + llm_commands.SAVE_DELAY_S + 4.0
        data = {}
        while time.time() < deadline:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if "is_weather_query" in (data.get("counts") or {}):
                break
            time.sleep(0.1)
        self.assertEqual(data["counts"]["is_weather_query"]["count"], 1)

    def test_try_is_a_dry_run(self):
        self.book.custom_upsert({"name": "Cut me a tape", "triggers": ["cut me a tape"],
                                 "does": {"as": "export the last five minutes"}})
        self.book.custom_upsert({"name": "Who are you", "triggers": ["who are you"], "does": {"say": "me"}})
        self.book.custom_upsert({"name": "Jokes", "triggers": ["more jokes"], "does": {"orchestrator": "more banter"}})
        got = self.book.try_text("restart comfy")
        self.assertEqual(got["builtin"], "parse_service_command")
        self.assertEqual(got["also"], ["parse_service_command", "is_comfy_status_query"])
        self.assertIn("Restart a service", got["say"])
        got = self.book.try_text("cut me a tape")
        self.assertEqual(got["custom"]["id"], "custom:cut-me-a-tape")
        self.assertEqual(got["rewritten"], "export the last five minutes")
        self.assertEqual(got["builtin"], "parse_export_command")
        got = self.book.try_text("who are you")
        self.assertEqual(got["custom"]["how"], "say")
        self.assertEqual(got["builtin"], "")
        got = self.book.try_text("more jokes")
        self.assertEqual(got["orchestrator"], "more banter")
        self.assertIn("orch:more", got["say"])
        got = self.book.try_text("tell me a story")
        self.assertIn("chat model", got["say"])
        self.book.note("parse_export_command", enabled=False)
        got = self.book.try_text("export the tape")
        self.assertEqual(got["skipped"], ["parse_export_command"])
        self.assertIn("switched off", got["say"])
        self.assertEqual(self.book.summary()["hits"], 0)

    def test_the_say_counts_the_book(self):
        say = self.book.summary()["say"]
        self.assertIn("%d commands on the book" % (len(llm_commands.BUILTINS) + len(llm_commands.ORCHESTRATOR)), say)
        self.assertIn("19 built-in", say)
        chain(self.g, "restart comfy")
        self.assertIn("most used: Restart a service 1", self.book.summary()["say"])

    def test_the_doors_pass_through_when_no_book_is_installed(self):
        keep = llm_commands._BOOK
        try:
            llm_commands._BOOK = None
            self.assertEqual(llm_commands.rewrite("x"), ("x", None))
            self.assertEqual(llm_commands.fixed_reply("x"), "")
            self.assertEqual(llm_commands.orchestrator_line("x"), "")
        finally:
            llm_commands._BOOK = keep

    def test_install_is_idempotent_and_watch_does_not_double_wrap(self):
        again = llm_commands.install(None, self.g)
        self.assertIs(again, self.book)
        fn = self.g["parse_export_command"]
        llm_commands.watch(self.g)
        self.assertIs(self.g["parse_export_command"], fn)


try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except Exception:  # noqa: BLE001
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_FASTAPI, "FastAPI's TestClient is not importable here")
class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.g = fake_host(self.tmp)
        self.auth = []
        self.g["require_auth"] = lambda a: self.auth.append(("write", a))
        self.g["require_read_auth"] = lambda a: self.auth.append(("read", a))
        self.app = FastAPI()
        self.book = llm_commands.install(self.app, self.g)
        self.client = TestClient(self.app)

    def test_the_routes(self):
        got = self.client.get("/api/llm-commands", headers={"Authorization": "Bearer k"}).json()
        self.assertEqual(len(got["rows"]), len(llm_commands.BUILTINS) + len(llm_commands.ORCHESTRATOR))
        self.assertIn("commands on the book", got["say"])
        self.assertEqual(self.auth[-1], ("read", "Bearer k"))
        r = self.client.put("/api/llm-commands/custom", json={"name": "Cut me a tape", "triggers": ["cut me a tape"],
                                                                 "does": {"as": "export the last five minutes"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["row"]["id"], "custom:cut-me-a-tape")
        self.assertEqual(self.auth[-1][0], "write")
        r = self.client.post("/api/llm-commands/custom", json={"name": "Jokes", "triggers": ["more jokes"],
                                                                  "does": {"orchestrator": "more banter"}})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.put("/api/llm-commands/custom", json={"name": "bad", "triggers": ["/(/"], "does": {"say": "x"}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("does not compile", r.json()["detail"])
        r = self.client.post("/api/llm-commands/try", json={"text": "cut me a tape"})
        self.assertEqual(r.json()["builtin"], "parse_export_command")
        self.assertEqual(r.json()["rewritten"], "export the last five minutes")
        r = self.client.put("/api/llm-commands/note/parse_export_command", json={"notes": "the quick cut", "enabled": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["row"]["notes"], "the quick cut")
        self.assertFalse(r.json()["row"]["enabled"])
        r = self.client.post("/api/llm-commands/note/custom:jokes", json={"notes": "n"})
        self.assertEqual(r.json()["row"]["notes"], "n")
        r = self.client.put("/api/llm-commands/note/nope", json={"notes": "n"})
        self.assertEqual(r.status_code, 404)
        r = self.client.delete("/api/llm-commands/custom/custom:jokes")
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/api/llm-commands/custom/custom:cut-me-a-tape/delete")
        self.assertEqual(r.status_code, 200)
        r = self.client.delete("/api/llm-commands/custom/custom:jokes")
        self.assertEqual(r.status_code, 404)
        got = self.client.get("/api/llm-commands").json()
        self.assertEqual([r["id"] for r in got["rows"] if r["kind"] == "custom"], [])
        self.assertEqual(got["hits"], 0)          # try counted nothing


if __name__ == "__main__":
    unittest.main()
