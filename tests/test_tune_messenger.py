"""[tune-messenger] The listener door's Messenger road, without app.py.

What a listener's phone may be handed about a System 3 round - the dice, the
seats, the words of what is already on the air - and what it may never be
handed: a word of a turn not yet aired, a prompt, a sheet, a direction, a
setting, a seed, an operator note. The assertions run over the JSON the door
would send, not over the Python objects that built it."""
import asyncio
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import tune_messenger as tm

CID = "abcdef0123456789"
SECRETS = ("SHEET-SECRET", "PROMPT-SECRET", "SYSTEM-SECRET", "SEED-TEXT-SECRET", "TOPIC-SECRET",
           "DIRECTION-SECRET", "COMMAND-SECRET", "WHY-SECRET", "BLOCK-SECRET", "STATION-SECRET",
           "DIRECTIVE-SECRET", "CTS-DIRECTION-SECRET", "FAV-SECRET", "TEMPER-TEXT-SECRET",
           "INTENT-SECRET", "/samples/secret/path.mp4", "MATERIAL-SECRET", "NOTE-SECRET",
           "seed-0123456789abcdef", "cfg-hash-secret", "PASSAGE-SECRET", "EXCLUDED-SECRET")
UNAIRED = ("UNAIRED-TURN-ONE", "UNAIRED-TURN-TWO", "UNAIRED-LINE-ONE", "UNAIRED-SFXGUY-LINE",
           "UNAIRED-TURN-ZERO-LATER", "UNAIRED-MM-HMM")
ON0 = 1790581107000              # the first clip's moment on the station's air
NOW = ON0 + 1000                 # one second into it
FORBIDDEN_KEYS = {"prompt", "prompts", "plan", "sheet", "inputs", "settings", "seed", "config_hash",
                  "state_before", "state_after", "material", "excluded", "intent", "path", "text_prompt",
                  "system", "controls", "validation", "actual", "shadow_bindings", "draws_seed", "n",
                  "authority", "dims", "engine_hints", "cursor_before", "participants", "dynamics"}


def keys_of(value, out=None):
    out = set() if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(k)
            keys_of(v, out)
    elif isinstance(value, list):
        for v in value:
            keys_of(v, out)
    return out


def event(seq, family, turn="", stages=None, selected=None, meta=None, **extra):
    ev = {"schema": "system3.decision-event/1", "event_id": "%s:%04d" % (CID, seq), "seq": seq,
          "conversation_id": CID, "trace_id": "s3-" + CID, "turn_id": turn, "turn_index": 0 if turn else -1,
          "at": 1790581296.0, "family": family, "stages": stages or [], "selected": selected or {},
          "meta": meta or {}, "config_hash": "cfg-hash-secret",
          "rng": {"seed": "seed-0123456789abcdef", "n": 3, "label": family, "u": 0.4, "dice": 41, "sides": 100},
          "state_before": {"tension": 0.3, "note": "NOTE-SECRET"}, "state_after": {"tension": 0.4}}
    ev.update(extra)
    return ev


def item_stage(selected, labels, dice=64):
    return {"stage": "item", "selected": selected, "selected_index": 2, "of": len(labels), "total": 4.0,
            "draw": {"seed": "seed-0123456789abcdef", "n": 1, "label": "x", "u": 0.63, "dice": dice, "sides": 100},
            "candidates": [{"id": x, "label": x.title(), "base": 1.0, "weight": 1.0 + i, "p": 0.25,
                            "why": ["WHY-SECRET"]} for i, x in enumerate(labels)],
            "excluded": [{"id": "gone", "label": "EXCLUDED-SECRET", "why": "WHY-SECRET"}]}


def conversation(mode="active"):
    t = [CID + ":t00", CID + ":t01", CID + ":t02"]
    turns = []
    for i, tid in enumerate(t):
        turns.append({
            "turn_id": tid, "index": i, "speaker": "AB"[i % 2], "name": ["Host", "Skip"][i % 2],
            "step": "s%d" % i, "step_label": ["Initial Statement", "Response A", "Initiator's Response"][i],
            "phase": "OPEN", "status": "generated", "estimated_seconds": 6.0, "script_index": i,
            "text": ["The words of turn zero, on the air now.", "UNAIRED-TURN-ONE and more.",
                     "UNAIRED-TURN-TWO and the rest."][i],
            "directions": [{"text": "DIRECTION-SECRET: argue with him"}],
            "decisions": [{"family": "ES", "event_id": "%s:%04d" % (CID, 10 + i * 10), "text": "COMMAND-SECRET"},
                          {"family": "CTS", "event_id": "%s:%04d" % (CID, 11 + i * 10)},
                          {"family": "DIRECTIVE", "event_id": "%s:%04d" % (CID, 12 + i * 10)}],
            "speakerbox": [{"event_id": "%s:%04d" % (CID, 13 + i * 10), "mode": "APPEND", "mark": "append",
                            "material": {"file": "koh4.md", "text": "PASSAGE-SECRET"}}],
            "sfx": {"play": True, "placement": "after", "intent": ["INTENT-SECRET"], "event_id": "%s:%04d" % (CID, 14 + i * 10)},
            "sfxguy": {"speak": True, "kind": "reaction", "order": ["reaction"], "event_id": "%s:%04d" % (CID, 15 + i * 10)},
            "performance": {"emotion": "outrage", "intensity": 0.52, "dims": {"irritation": 0.4},
                            "engine_hints": {"dsp": {"pace": True}}},
            "state_before": {"subject": {"topic": "TOPIC-SECRET"}}, "cursor_before": {"step": 0}})
    events = [
        event(1, "BLOCK", selected={"id": "KEEP", "label": "BLOCK-SECRET: The operator's standing orders: sent"}),
        event(2, "STATION", selected={"id": "14", "label": "STATION-SECRET"}),
        event(3, "TOPIC", stages=[{"stage": "dice", "selected": "NONE", "threshold": 60, "draw": {"u": 0.2, "dice": 21}}],
              selected={"id": "NONE", "label": "nothing off the board this round"}, meta={"rate": 0.4, "bank": "x"}),
        event(4, "TEMPER", stages=[item_stage("giddy", ["giddy", "tender", "dry"])],
              selected={"id": "giddy", "label": "Giddy", "text": "TEMPER-TEXT-SECRET", "seat": "A"}),
        event(5, "FAV", stages=[item_stage("fav_1", ["fav_1", "fav_2"])],
              selected={"id": "fav_1", "label": "FAV-SECRET a bit from the desk", "said_by": "Skip"}),
    ]
    for i, tid in enumerate(t):
        b = 10 + i * 10
        events += [
            event(b, "ES", tid, [item_stage("anger.outrage", ["anger.outrage", "anger.irritation", "joy.glee"])],
                  {"table": "ES1", "category": "anger", "category_label": "ANGER", "id": "anger.outrage",
                   "label": "outrage", "text": "COMMAND-SECRET", "index": 1, "of": 3, "intensity": 0.52}),
            event(b + 1, "CTS", tid, [], {"id": "OBLIGATED", "label": "CTS-DIRECTION-SECRET wonders aloud whether",
                                          "authority": "obligated"}, {"why": "WHY-SECRET"}),
            event(b + 2, "DIRECTIVE", tid, [], {"id": "D1", "label": "DIRECTIVE-SECRET"}),
            event(b + 3, "SPEAKERBOX", tid,
                  [{"stage": "dice", "selected": "PASS", "threshold": 51, "draw": {"u": 0.8, "dice": 81},
                    "rule": "a hit needs over the threshold"}],
                  {"id": "APPEND", "label": "append", "mark": "append"},
                  {"mark": "append", "rate": 0.49, "applies": True, "why": "WHY-SECRET", "insertion_point": 3}),
            event(b + 4, "SFX", tid, [{"stage": "dice", "selected": "PLAY", "threshold": 0.39, "draw": {"u": 0.2, "dice": 21},
                                       "why": ["WHY-SECRET"]}],
                  {"id": "PLAY", "label": "play after the line", "intent": ["INTENT-SECRET"]},
                  {"reason": "WHY-SECRET"}),
            event(b + 5, "SFXGUY", tid, [item_stage("reaction", ["reaction", "quip", "news"])],
                  {"id": "SPEAK", "kind": "reaction", "label": "pipes up: fires back at this very line"}),
        ]
    lines = [
        {"line_id": "line0000aired", "turn_id": t[0], "block": 10, "ord": 0, "sid": "s", "who": "dj",
         "text": "The words of turn zero,", "at": 1.0},
        {"line_id": "line0001board", "turn_id": None, "block": 10, "ord": 1, "sid": "s", "who": "board",
         "text": "\U0001F50A 68 Okay, see ya", "at": 1.0},
        {"line_id": "line0002aired", "turn_id": t[0], "block": 10, "ord": 2, "sid": "s", "who": "dj",
         "text": "on the air now.", "at": 1.0},
        # the second clip: the other seat's "Mm-hmm." the ledger linked to
        # turn zero, the rest of turn zero, then turn one and the SFX Guy
        {"line_id": "line0005mmhmm", "turn_id": t[0], "block": 11, "ord": 0, "sid": "s", "who": "cohost",
         "text": "UNAIRED-MM-HMM", "at": 1.0},
        {"line_id": "line0006later", "turn_id": t[0], "block": 11, "ord": 1, "sid": "s", "who": "dj",
         "text": "UNAIRED-TURN-ZERO-LATER", "at": 1.0},
        {"line_id": "line0003later", "turn_id": t[1], "block": 11, "ord": 2, "sid": "s", "who": "cohost",
         "text": "UNAIRED-LINE-ONE", "at": 1.0},
        {"line_id": "line0004guy", "turn_id": t[1], "block": 11, "ord": 3, "sid": "s", "who": "drop",
         "text": "UNAIRED-SFXGUY-LINE", "at": 1.0},
    ]
    observations = [
        {"family": "PROMPT", "kind": "observation", "stage": "writer", "text": "PROMPT-SECRET", "system": "SYSTEM-SECRET"},
        {"family": "COMMIT", "kind": "observation", "stage": "script-ledger", "block": 10,
         "media": {"line0001board": {"poster": "/api/sfx/poster/1bd9a68416e24e85?t=%s" % ("a" * 32),
                                     "sfx_roll": {"road": "book", "category": {"label": "vine", "dice": 48, "u": 0.47, "of": 38, "index": 18},
                                                  "clip": {"label": "68 Okay, see ya", "dice": 90, "u": 0.89, "of": 3, "index": 3},
                                                  "thumb": "/api/sfx/spec/1bd9a68416e24e85?t=x"}}}},
        {"family": "SPEAKERBOX", "kind": "observation", "stage": "door-outcome", "door": "full", "hit": True,
         "turns": 2, "file": "koh4.md", "why": "WHY-SECRET"},
        {"family": "SFX", "kind": "observation", "stage": "air", "turn_index": 0, "due": "cadence",
         "intent": ["INTENT-SECRET"],
         "played": [{"clip": "aae5399121fc2110-v4.wav", "sample_id": "f401f797d1e97b28", "seconds": 9.1,
                     "why": "matched 'hit'", "sfx_roll": {"clip": {"label": "95 So tell me more"}},
                     "poster": "/api/sfx/poster/f401f797d1e97b28?t=x"}],
         "sfx_guy": [{"text": "Say that again."}],
         "matcher": {"path": "/samples/secret/path.mp4", "cands": 64, "eligible": 4, "score": 2.3}},
        {"family": "SFXGUY", "kind": "observation", "stage": "line", "turn_index": 0, "planned": "reaction",
         "line": "Tell me more.", "how": "the bank's matcher chose the take", "draws": [], "fell_through": []},
    ]
    return {"schema": "system3.conversation/1", "engine": 2,
            "identity": {"conversation_id": CID, "trace_id": "s3-" + CID, "road_kind": "banter", "revision": 1,
                         "system2_slot_id": "hour-x", "script_digest": "d"},
            "mode": mode, "generation_mode": "turn", "seed": "seed-0123456789abcdef", "config_hash": "cfg-hash-secret",
            "settings": {"controls": {"disagreement": 0.8}, "note": "NOTE-SECRET"},
            "inputs": {"seed_text": "SEED-TEXT-SECRET", "availability": {"speakbox": True}},
            "created": 1790580000.0, "subject": {"topic": "TOPIC-SECRET", "keywords": ["x"]},
            "turns": turns, "plan": {"sheet": "SHEET-SECRET"}, "prompts": [{"text": "PROMPT-SECRET"}],
            "validation": {"verdict": "compliant", "note": "NOTE-SECRET"},
            "material": [{"decided_by": "x", "selected": {"file": "koh4.md", "text": "MATERIAL-SECRET"}}],
            "status": "generated", "decision_events": events, "observations_air": observations, "lines": lines}


def sign(sid):
    return "a" * 32


FIRST_CLIP = {"ts": ON0 - 7000, "broadcast_ms": ON0, "url": "/media/x.wav?t=y", "speech": True,
              "stream": {"length": 12.0, "rows": [
                  {"id": "line0000aired", "from": 0.0, "until": 4.0, "text": "The words of turn zero,"},
                  {"id": "line0001board", "from": 4.0, "until": 7.5, "text": "\U0001F50A 68 Okay, see ya"},
                  {"id": "line0002aired", "from": 7.5, "until": 12.0, "text": "on the air now."}]}}
# handed to the page feed already, but its moment on the air is a minute away
SECOND_CLIP = {"ts": ON0 + 2000, "broadcast_ms": ON0 + 60000, "url": "/media/z.wav?t=y", "speech": True,
               "stream": {"length": 14.0, "rows": [
                   {"id": "line0005mmhmm", "from": 0.0, "until": 1.0},
                   {"id": "line0006later", "from": 1.0, "until": 6.0},
                   {"id": "line0003later", "from": 6.0, "until": 12.0},
                   {"id": "line0004guy", "from": 12.0, "until": 14.0}]}}


def aired_first_block():
    """The first block handed to the page feed as one welded clip."""
    return tm.air_index([FIRST_CLIP])


def both_blocks():
    return tm.air_index([FIRST_CLIP, SECOND_CLIP])


class Trimming(unittest.TestCase):
    def setUp(self):
        self.trimmed = tm.trim_conversation(conversation(), both_blocks(), {}, {}, sign, now_ms=NOW)
        self.blob = json.dumps(self.trimmed, ensure_ascii=False)
        self.turns = {t["turn_id"]: t for t in self.trimmed["turns"]}

    def test_no_word_of_a_turn_not_yet_on_the_air(self):
        for word in UNAIRED:
            self.assertNotIn(word, self.blob, "%s reached the listener before its clip aired" % word)
        self.assertEqual(self.turns[CID + ":t00"]["text"], "The words of turn zero,",
                         "the message on the air carries its words")
        self.assertEqual(self.turns[CID + ":t00.1"]["text"], "on the air now.")
        for tid in (CID + ":t00.2", CID + ":t00.3", CID + ":t01", CID + ":t02"):
            self.assertNotIn("text", self.turns[tid], tid)
        lines = {line["line_id"]: line for line in self.trimmed["lines"]}
        self.assertIn("text", lines["line0000aired"])
        self.assertNotIn("text", lines["line0003later"])
        self.assertNotIn("text", lines["line0004guy"], "the SFX Guy's own row waits for its own air")
        self.assertEqual(lines["line0001board"]["text"], "\U0001F50A 68 Okay, see ya", "a sting is its clip's name")

    def test_handed_over_is_not_yet_on_the_air(self):
        """The second clip was handed to the feed a minute before its moment:
        its words wait for the moment (RELEASE_LEAD_MS early), not the hand-over."""
        early = tm.trim_conversation(conversation(), both_blocks(), {}, {}, sign,
                                     now_ms=ON0 + 60000 - tm.RELEASE_LEAD_MS - 1000)
        self.assertNotIn("UNAIRED-LINE-ONE", json.dumps(early))
        due = tm.trim_conversation(conversation(), both_blocks(), {}, {}, sign,
                                   now_ms=ON0 + 60000 - tm.RELEASE_LEAD_MS + 1000)
        turns = {t["turn_id"]: t for t in due["turns"]}
        self.assertEqual(turns[CID + ":t01"]["text"], "UNAIRED-LINE-ONE")
        self.assertEqual(turns[CID + ":t00.3"]["text"], "UNAIRED-TURN-ZERO-LATER")
        self.assertNotIn("text", turns[CID + ":t02"], "a turn the ledger has not reached has no words")

    def test_each_run_on_the_air_is_its_own_message(self):
        order = [t["turn_id"] for t in self.trimmed["turns"]]
        self.assertEqual(order, [CID + ":t00", CID + ":t00.1", CID + ":t00.2", CID + ":t00.3", CID + ":t01", CID + ":t02"],
                         "the ledger's order: a sting splits a turn, the other seat's line is its own, the unwritten turn last")
        mm = self.turns[CID + ":t00.2"]
        self.assertEqual((mm["speaker"], mm["name"], mm["step_label"]), ("B", "Skip", "interjects"))
        self.assertEqual(self.turns[CID + ":t00.1"]["step_label"], "continues")
        self.assertEqual(self.turns[CID + ":t00"]["step_label"], "Initial Statement")
        for tid in (CID + ":t00.1", CID + ":t00.2", CID + ":t00.3"):
            self.assertEqual(self.turns[tid]["decisions"], [], "the dice ride the turn's first message only")
            self.assertIsNone(self.turns[tid]["script_index"])
        lines = {line["line_id"]: line for line in self.trimmed["lines"]}
        self.assertEqual(lines["line0002aired"]["turn_id"], CID + ":t00.1")
        self.assertEqual(lines["line0005mmhmm"]["turn_id"], CID + ":t00.2")
        self.assertEqual(lines["line0003later"]["turn_id"], CID + ":t01")
        dropped = conversation()
        dropped["turns"][2]["status"] = "dropped"
        got = tm.trim_conversation(dropped, both_blocks(), {}, {}, sign, now_ms=NOW)
        self.assertNotIn(CID + ":t02", [t["turn_id"] for t in got["turns"]], "a dropped turn never airs")

    def test_no_prompt_sheet_setting_seed_or_note(self):
        for secret in SECRETS:
            self.assertNotIn(secret, self.blob, "%s reached the listener" % secret)
        found = keys_of(self.trimmed) & FORBIDDEN_KEYS
        self.assertEqual(found, set(), "operator fields in the listener payload")
        self.assertEqual(self.trimmed["subject"], {})
        for t in self.trimmed["turns"]:
            self.assertEqual(t["directions"], [])
            self.assertEqual(t["speakerbox"], [], "no passage to open on the listener page")

    def test_only_listener_families(self):
        fams = {e["family"] for e in self.trimmed["decision_events"]}
        self.assertTrue({"ES", "SPEAKERBOX", "SFX", "SFXGUY", "CTS", "TOPIC", "TEMPER", "FAV"} <= fams)
        self.assertFalse(fams & {"BLOCK", "STATION", "DIRECTIVE", "PROMPT"})
        obs = {o["family"] for o in self.trimmed["observations_air"]}
        self.assertEqual(obs, {"SFX", "SFXGUY"})
        ids = {e["event_id"] for e in self.trimmed["decision_events"]}
        for t in self.trimmed["turns"]:
            for d in t["decisions"]:
                self.assertIn(d["event_id"], ids, "a turn points only at dice it carries")
            if "." not in t["turn_id"].split(":")[1]:
                self.assertIn("SPEAKERBOX", {d["family"] for d in t["decisions"]}, "the speaker-box die rides the turn")

    def test_the_dice_chips_survive(self):
        es = next(e for e in self.trimmed["decision_events"] if e["family"] == "ES")
        self.assertEqual(es["selected"]["label"], "outrage")
        self.assertEqual(es["selected"]["category_label"], "ANGER")
        item = next(s for s in es["stages"] if s["stage"] == "item")
        self.assertEqual(item["draw"], {"dice": 64, "u": 0.63})
        self.assertEqual([c["label"] for c in item["candidates"]], ["Anger.Outrage", "Anger.Irritation", "Joy.Glee"])
        self.assertTrue(all(set(c) == {"id", "label", "p"} for c in item["candidates"]), "labels and shares only")
        cts = next(e for e in self.trimmed["decision_events"] if e["family"] == "CTS")
        self.assertEqual(cts["selected"]["label"], "the step as planned", "an obligated CTS is the writer's direction")
        fav = next(e for e in self.trimmed["decision_events"] if e["family"] == "FAV")
        self.assertEqual(fav["selected"]["label"], "a favourite")
        self.assertFalse(any("candidates" in s for s in fav["stages"]))
        sb = next(e for e in self.trimmed["decision_events"] if e["family"] == "SPEAKERBOX")
        self.assertEqual(sb["meta"], {"mark": "append", "applies": True, "rate": 0.49})
        dice = sb["stages"][0]
        self.assertEqual((dice["threshold"], dice["draw"]["dice"]), (51, 81))

    def test_board_line_poster_and_rolls(self):
        board = next(line for line in self.trimmed["lines"] if line["line_id"] == "line0001board")
        self.assertEqual(board["poster"], "/api/system3/public/poster/1bd9a68416e24e85?t=" + "a" * 32)
        self.assertEqual(board["sfx_roll"]["clip"], {"label": "68 Okay, see ya", "dice": 90, "of": 3, "index": 3})
        self.assertNotIn("thumb", json.dumps(board))
        self.assertEqual(tm.public_poster("/api/sfx/poster/1bd9a68416e24e85?t=" + "b" * 32, sign), "",
                         "a signature that is not the station's own is dropped")
        self.assertEqual(tm.public_poster("/etc/passwd", sign), "")

    def test_air_state_and_timing(self):
        air = self.trimmed["public_air"]
        self.assertEqual(air["line0000aired"]["on"], 1790581107000)
        self.assertEqual(air["line0002aired"]["on"], 1790581114500)
        self.assertEqual(air["line0002aired"]["seconds"], 4.5)
        self.assertTrue(air["line0000aired"]["published"])
        # handed over, a minute from its moment: the page learns WHEN (so a
        # phone behind live can find it), not what
        self.assertEqual(air["line0003later"]["on"], ON0 + 60000 + 6000)
        self.assertNotIn("text", next(x for x in self.trimmed["lines"] if x["line_id"] == "line0003later"))
        self.assertNotIn("line0003later", tm.trim_conversation(conversation(), aired_first_block(), {}, {}, sign,
                                                               now_ms=NOW)["public_air"])
        withdrawn = tm.chat_index([{"id": "line0003later", "aired": "withdrawn", "text": "UNAIRED-LINE-ONE"}], ("published",))
        again = tm.trim_conversation(conversation(), aired_first_block(), withdrawn, {}, sign, now_ms=ON0 + 90000)
        self.assertEqual(again["public_air"]["line0003later"]["aired"], "withdrawn")
        self.assertNotIn("UNAIRED-LINE-ONE", json.dumps(again), "a withdrawn line never aired: no words")

    def test_chat_publication_releases_the_turn(self):
        # the ring no longer remembers it; the booth says it was published: history
        chat = tm.chat_index([{"id": "line0003later", "aired": "published", "who": "cohost"}], ("published", "stream"))
        got = tm.trim_conversation(conversation(), {}, chat, {}, sign, now_ms=NOW)
        turns = {t["turn_id"]: t for t in got["turns"]}
        self.assertEqual(turns[CID + ":t01"]["text"], "UNAIRED-LINE-ONE", "a message's words are its lines' own")
        self.assertNotIn("UNAIRED-TURN-ONE", json.dumps(got), "never the writer's whole turn")
        self.assertNotIn("text", turns[CID + ":t00"], "nothing of turn zero was handed over in this telling")
        heard = tm.chat_index([{"id": "line0000aired", "aired": "prepared", "heard_ack_at": 5.0}], (),
                              heard_at=lambda row: float(row.get("heard_ack_at") or 0))
        self.assertEqual(heard["line0000aired"]["state"], "published")

    def test_shadow_simulation_and_preview_rounds_are_not_a_listeners(self):
        for mode in ("shadow", "simulation", "preview", None):
            self.assertIsNone(tm.trim_conversation(conversation(mode), aired_first_block(), {}, {}, sign, now_ms=NOW))
        self.assertIsNone(tm.trim_conversation({"mode": "active"}, {}, {}, {}, sign))

    def test_a_published_line_the_ledger_has_not_filed_yet(self):
        conv = conversation()
        conv["lines"] = [x for x in conv["lines"] if x["line_id"] != "line0000aired"]
        stamps = {"line0000aired": {"conversation_id": CID, "turn_id": CID + ":t00"}}
        chat = tm.chat_index([{"id": "line0000aired", "aired": "published", "who": "dj", "text": "The words"}], ("published",))
        got = tm.trim_conversation(conv, aired_first_block(), chat, stamps, sign, now_ms=NOW)
        row = next(x for x in got["lines"] if x["line_id"] == "line0000aired")
        self.assertEqual((row["turn_id"], row["who"], row["text"]), (CID + ":t00", "dj", "The words"))


class Air(unittest.TestCase):
    def test_air_index_rows_and_single_lines(self):
        got = tm.air_index([
            {"ts": 1000, "broadcast_ms": 8000, "stream": {"rows": [{"id": "a", "from": 0, "until": 2.5},
                                                                   {"id": "b", "from": 2.5, "until": 6}]}},
            {"ts": 20000, "row_id": "c", "seconds": 3.2},
            {"ts": 30000, "row_id": "d", "text": "x" * 70},
            {"ts": 40000, "video": True, "row_id": "e"},
            "not a clip"], lead_ms=7000)
        self.assertEqual(got["a"], {"on": 8000, "len": 2.5, "clip_on": 8000})
        self.assertEqual(got["b"], {"on": 10500, "len": 3.5, "clip_on": 8000})
        self.assertEqual(got["c"], {"on": 27000, "len": 3.2, "clip_on": 27000})
        self.assertEqual(got["d"]["len"], 5.0)
        self.assertNotIn("e", got, "a picture is not a line")


class FakeStore:
    def __init__(self, convs):
        self.convs = convs
        self.reads = 0

    def conversation(self, cid):
        self.reads += 1
        got = self.convs.get(cid)
        return json.loads(json.dumps(got)) if got else None

    def conversations(self, limit=16):
        return [{"conversation_id": c["identity"]["conversation_id"], "mode": c["mode"], "status": c["status"],
                 "road": c["identity"]["road_kind"], "created": c["created"], "topic": "TOPIC-SECRET"}
                for c in sorted(self.convs.values(), key=lambda c: -c["created"])][:limit]

    def line(self, lid):
        for c in self.convs.values():
            for x in c["lines"]:
                if x["line_id"] == lid:
                    return {"conversation_id": c["identity"]["conversation_id"], "line_id": lid}
        return None


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Cache(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(NOW / 1000.0)
        other = conversation()
        other["identity"] = dict(other["identity"], conversation_id="fedcba9876543210")
        other["created"] = 1790581000.0
        other["lines"] = []
        self.store = FakeStore({CID: conversation(), "fedcba9876543210": other})
        self.door = tm.PublicMessenger(clock=self.clock)
        self.air = aired_first_block()

    def build(self):
        self.door.build(self.store, self.air, {}, {}, sign)

    def test_many_listeners_one_build(self):
        self.build()
        self.assertEqual(self.store.reads, 2)
        for _ in range(200):
            body, _h = self.door.answer("")
            self.assertIn(b'"conv":', body)
        self.assertEqual(self.store.reads, 2, "answering never touches the store")
        self.assertFalse(self.door.stale())
        self.clock.t += tm.TTL_AIRING + 0.1
        self.assertTrue(self.door.stale())
        self.build()
        self.assertEqual(self.store.reads, 3, "the round on the air is read again; the other waits its TTL")
        self.clock.t += tm.TTL_OTHER
        self.build()
        self.assertEqual(self.store.reads, 5)

    def test_single_flight(self):
        async def run(fn, *args):
            await asyncio.sleep(0.01)
            return fn(*args)

        async def many():
            await asyncio.gather(*[self.door.refresh(run, self.store, self.air, {}, {}, sign) for _ in range(25)])
        asyncio.run(many())
        self.assertEqual(self.store.reads, 2, "twenty-five listeners at once cost one build")

    def test_order_airing_first_and_no_summary_leak(self):
        self.build()
        order = [o["conversation_id"] for o in self.door.order]
        self.assertEqual(order[0], CID, "the round the air is on leads")
        self.assertIn("fedcba9876543210", order)
        body, _h = self.door.answer("")
        self.assertNotIn(b"TOPIC-SECRET", body, "the store's summary rows never pass through")

    def test_have_answers_a_stub(self):
        self.build()
        first = json.loads(self.door.answer("")[0])
        rev = first["convs"][CID]["rev"]
        second = json.loads(self.door.answer("%s:%s" % (CID, rev))[0])
        self.assertEqual(second["convs"][CID], {"rev": rev}, "a round the page holds comes back as its revision")
        self.assertIn("conv", second["convs"]["fedcba9876543210"])
        stale = json.loads(self.door.answer("%s:%s" % (CID, "0" * 12))[0])
        self.assertIn("conv", stale["convs"][CID])
        self.assertEqual(tm.parse_have("bad cid!:zz,%s:%s,x:y" % (CID, rev)), {CID: rev})

    def test_a_round_that_moves_gets_a_new_revision(self):
        self.build()
        rev = json.loads(self.door.answer("")[0])["convs"][CID]["rev"]
        seq = self.door.seq
        self.clock.t += tm.TTL_AIRING + 0.1
        self.build()
        self.assertEqual(json.loads(self.door.answer("")[0])["convs"][CID]["rev"], rev, "nothing moved: same rev")
        self.assertEqual(self.door.seq, seq)
        self.air = dict(self.air, line0003later={"on": NOW + 2000, "len": 3.0, "clip_on": NOW + 2000})
        self.clock.t += tm.TTL_AIRING + 0.1
        self.build()
        after = json.loads(self.door.answer("")[0])
        self.assertNotEqual(after["convs"][CID]["rev"], rev, "a line handed over is news")
        self.assertGreater(self.door.seq, seq)
        turns = {t["turn_id"]: t for t in after["convs"][CID]["conv"]["turns"]}
        self.assertIn("text", turns[CID + ":t01"])

    def test_gzip_and_off(self):
        self.build()
        body, headers = self.door.answer("", gzip_ok=True)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        self.assertIn(CID, json.loads(gzip.decompress(body))["convs"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        off = json.loads(self.door.answer("", off=True)[0])
        self.assertEqual((off["off"], off["order"], off["convs"]), (True, [], {}))


class Files(unittest.TestCase):
    def test_etag_304_and_gzip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "system3.js"
            p.write_text("export const x = 1;\n" * 400, encoding="utf-8")
            files = tm.StaticFiles({"system3.js": p})
            status, body, headers = files.respond("system3.js", "", gzip_ok=True)
            self.assertEqual((status, headers["Content-Encoding"]), (200, "gzip"))
            self.assertEqual(gzip.decompress(body), p.read_bytes())
            status, body, _h = files.respond("system3.js", headers["ETag"], gzip_ok=True)
            self.assertEqual((status, body), (304, b""))
            status, plain, headers = files.respond("system3.js", "", gzip_ok=False)
            self.assertEqual((status, plain), (200, p.read_bytes()))
            self.assertNotIn("Content-Encoding", headers)
            self.assertEqual(files.respond("app.py")[0], 404)
            self.assertEqual(files.respond("../app.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
