"""[s3-turnchain] System 3's copy gate: every message answers the one before it,
and a copy never airs.

The engine's rules (system3.gate_*), the walk over three recorded rounds with
stub writers (no model is called: recorded writer output from
data/prompt_history.sqlite3 and data/system3.sqlite3, fixtures in
system3_turnchain_fixtures.json), Mode B's observe(), and the runtime's doors
on a real System3Runtime over a temp store (test_system3_runtime.FakeStation).
Nothing touches the station's data dir."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

import system3
import system3_runtime

FIX = json.loads((Path(__file__).resolve().parent / "system3_turnchain_fixtures.json").read_text(encoding="utf-8"))
ROUNDS = FIX["rounds"]
CALL_A, CALL_B, BANTER = "cc672e24cc5f452a", "1c0897fc96e84461", "ef39853f9fa54974"
SUBJECT = ("I just saw a man's cat drag someone into the sewer. That cat kidnapped somebody. It was a kid "
           "yesterday, a maleman the day before, and today it got someone else. What do I do about this?")


def turns_of(script, names=()):
    """The station's banter_turns, as far as the gate needs it (the booth's row-number cut included)."""
    s = str(script or "")
    for name, letter in sorted(names, key=lambda p: -len(p[0])):
        if name:
            s = re.sub(r"(^|\s)%s\s*:\s*" % re.escape(name), r"\g<1>%s: " % letter, s, flags=re.I)
    parts = re.split(r"(?:^|\s)([ABCDE])\s*:\s*", " " + s, flags=re.I)
    return [(parts[i].upper(), " ".join(re.sub(r"\s+\d{1,2}[.)]?\s*$", "", parts[i + 1].strip()).split()))
            for i in range(1, len(parts) - 1, 2)]


def conv_of(cid):
    return copy.deepcopy(ROUNDS[cid]["conv"])


def written(cid):
    rec = ROUNDS[cid]
    call = (rec["conv"].get("inputs") or {}).get("call") or {}
    turns = turns_of(rec["writer"], [(call.get("name") or "", "C")])
    return turns[:int((rec["conv"].get("validation") or {}).get("written") or len(turns))]


NOUNS = ("lantern", "gravel", "orchard", "saxophone", "ledger", "harbour", "velvet", "compass", "tinfoil",
         "radiator", "pelican", "marble", "chimney", "furnace", "violin", "parsnip", "trolley", "anchor",
         "biscuit", "meadow", "thimble", "cobbler", "glacier", "turnip", "walrus", "quarry", "bramble")


SYL = ("ka", "lo", "mi", "tru", "ven", "sa", "po", "dri", "zu", "fen", "gor", "ha", "jin", "ble", "qua",
       "rix", "tam", "wo", "yel", "nob")


def word(n, k):
    return SYL[(n * 7 + k * 3) % 20] + SYL[(n * 11 + k * 5 + 1) % 20] + SYL[(n * 13 + k + 2) % 20]


def fresh(n, seat):
    """A new line every time: six made-up words that no other n shares in order."""
    a, b, c, d = (word(n, k) for k in range(4))
    return "%s: The %s %s, and %s after %s %s." % (seat, a, NOUNS[n % len(NOUNS)], b, c, d)


def walk(conv, turns, writer, rewrites=system3.GATE_REWRITES, visits=system3.GATE_VISITS):
    run = system3.gate_open(conv, turns, None, rewrites=rewrites, visits=visits)
    asks = []
    while True:
        ask = system3.gate_next(conv, run)
        if not ask:
            break
        asks.append(dict(ask))
        said = writer(len(asks), ask, run)
        got = turns_of(said)
        system3.gate_take(conv, run, got[0][1] if got else said)
    return run, system3.gate_close(conv, run), asks


def fresh_writer(n, ask, run):
    return fresh(n, ask["seat"])


def stuck_writer(n, ask, run):
    return run["rows"][ask["at"]]["orig"]


def no_copies(test, conv, script):
    """No aired turn copies another, and none reads a source back off its door."""
    kept = turns_of(script)
    for i, (_m, t) in enumerate(kept):
        for j in range(i):
            test.assertEqual(system3.gate_copies(system3.gate_words(t), system3.gate_words(kept[j][1])), "",
                             "turn %d copies turn %d: %r / %r" % (i, j, t, kept[j][1]))


class Rules(unittest.TestCase):
    def w(self, s):
        return system3.gate_words(s)

    def test_what_is_a_copy_and_what_is_an_answer(self):
        c = system3.gate_copies
        self.assertEqual(c(self.w("You are talking about a man's cat; tell us more."),
                           self.w("You are talking about a man's cat; tell us more.")), "word for word")
        self.assertTrue(c(self.w("Yeah, I get that. Fine. Let's just move on then."),
                          self.w("Yeah, I get it. Whatever. Let's just move on then. 11")))
        self.assertTrue(c(self.w("Whoa, hold on a second there. You're talking about what? Where is the evidence "
                                 "for that claim, and how do you know that?"),
                          self.w("You're talking about what? Where is the evidence for that claim, and how do you "
                                 "know that?")))
        # an answer that picks a word up is not a copy; nor a repeated interjection
        self.assertEqual(c(self.w("Shave it? What do you mean by that?"), self.w("Shave it.")), "")
        self.assertEqual(c(self.w("I don't know."), self.w("I don't know what I'm doing")), "")
        self.assertEqual(c(self.w("Yeah."), self.w("Yeah.")), "")
        self.assertEqual(c(self.w("You said the cat dragged someone into the sewer - where?"),
                           self.w("I just saw a man's cat drag someone into the sewer.")), "")

    def test_a_row_number_left_on_the_end_is_not_a_difference(self):
        self.assertEqual(self.w("It's a joke, right? 10"), self.w("It's a joke, right?"))

    def test_the_subject_read_back_is_caught_a_mention_is_not(self):
        conv = conv_of(CALL_A)
        got = system3.gate_check(conv, 7, SUBJECT, [])
        self.assertEqual((got["rule"], got["what"]), ("subject", "the caller's subject"))
        self.assertIsNone(system3.gate_check(conv, 9, "I am trying to find out how to make people acknowledge the "
                                             "effect of this whole thing, but I just saw a man's cat drag someone "
                                             "into the sewer.", []))
        # the caller telling why they rang, where the call opens on it, is their subject stated -
        # the #1249 contract wants it said; in the middle of the call it is read back
        self.assertIsNone(system3.gate_check(conv, 3, SUBJECT, []))
        self.assertEqual(conv["turns"][3]["place"], "open")

    def test_a_passage_is_caught_off_its_door_and_allowed_on_it(self):
        conv = conv_of(CALL_B)
        got = system3.gate_check(conv, 9, "I don't know what i'm doing, I don't know what i'm doing come on come on.", [])
        self.assertEqual(got["rule"], "passage")          # a call's passage is in its own words, always
        banter = conv_of(BANTER)
        seed = banter["inputs"]["seed_text"]
        self.assertIsNone(system3.gate_check(banter, 0, seed, []), "the opening passage is turn 0's door")
        self.assertEqual(system3.gate_check(banter, 13, seed, [])["rule"], "passage")
        marked = next(t for t in banter["turns"] for sb in t.get("speakerbox") or []
                      if sb.get("mode") in ("PREPEND", "APPEND") and (sb.get("material") or {}).get("text"))
        text = next(sb["material"]["text"] for sb in marked["speakerbox"] if (sb.get("material") or {}).get("text"))
        if len(system3.gate_words(text)) >= system3.GATE_PASSAGE_RUN:
            self.assertIsNone(system3.gate_check(banter, marked["index"], "Well. " + text, []))

    def test_a_topic_row_is_said_in_their_own_words_unless_it_is_an_answer_line(self):
        conv = conv_of(BANTER)
        row = "You have to stop microwaving pets. The manager is going to catch you and he's going to fire you bro."
        self.assertEqual(system3.gate_check(conv, 5, row, [])["rule"], "topic")
        conv["turns"][5]["bank_topic"]["reply"] = "yes"          # "says these exact words, as written"
        conv["topic_plan"]["reply"] = "yes"
        self.assertIsNone(system3.gate_check(conv, 5, row, []))

    def test_empty_once_cleaned(self):
        conv = conv_of(CALL_A)
        self.assertEqual(system3.gate_check(conv, 7, "*laughs*", [], spoken="")["rule"], "empty")

    def test_the_map_follows_the_rows_in_order_not_the_looped_second_pass(self):
        conv = conv_of(CALL_A)
        m = system3.gate_map(conv, [x for x, _t in written(CALL_A)])
        self.assertEqual([m[i] for i in range(5)], [0, 1, 3, 4, 6])
        self.assertLess(m[14], 22)
        # align() paired the plan with the loop: greet at 15
        self.assertEqual(system3.align(conv, written(CALL_A))[2], 15)


class RecordedRounds(unittest.TestCase):
    def test_the_sewer_call_the_writer_answers_every_rewrite(self):
        conv = conv_of(CALL_A)
        run, out, asks = walk(conv, written(CALL_A), fresh_writer)
        c = out["counts"]
        self.assertEqual((c["caught"], c["rewritten"], c["trimmed"]), (4, 3, 22))
        self.assertEqual(out["held"], "")
        no_copies(self, conv, out["script"])
        seats = [m for m, _t in turns_of(out["script"])]
        self.assertEqual(seats[-2:], ["C", "A"], "the caller lands it, a host signs off")
        rewritten = {r["leg"] for r in run["rows"] if r["state"] == "rewritten"}
        self.assertEqual(rewritten, {"keeps_going", "lands", "sign_off"})
        g = conv["turn_gate"]
        self.assertEqual((g["caught"], g["rewritten"], g["dropped"], g["trimmed"]), (4, 3, 1, 22))
        self.assertLessEqual(g["visits"], system3.GATE_VISITS)

    def test_every_rewrite_prompt_carries_the_line_it_answers_and_its_dice(self):
        conv = conv_of(CALL_A)
        _run, _out, asks = walk(conv, written(CALL_A), fresh_writer)
        for ask in asks:
            t = conv["turns"][ask["turn"]]
            p = ask["prompt"]
            self.assertIn("THE LINE YOU ANSWER - ", p)
            self.assertIn("YOUR DICE FOR THIS LINE: answer ", p)
            self.assertIn("YOUR DRAFT REPEATED", p)
            self.assertTrue(p.rstrip().endswith("%s: <the words>" % t["speaker"]))
            for d in t["directions"]:
                if d["family"] in ("RS", "IRS", "FL"):
                    self.assertIn(d["text"], p, d)
            es = next(d for d in t["decisions"] if d["family"] == "ES")
            self.assertIn(es["label"], p)
        # the line it answers is the last line kept before it, word for word
        first = asks[0]
        self.assertEqual(first["turn"], 11)
        self.assertIn('Host just said: "You want people to acknowledge the effect of this, so who exactly did you see '
                      'doing the dragging', first["prompt"])

    def test_a_writer_that_keeps_copying_holds_a_call_and_airs_no_copy(self):
        for cid in (CALL_A, CALL_B):
            conv = conv_of(cid)
            _run, out, asks = walk(conv, written(cid), stuck_writer)
            self.assertIn("could not be written without copying", out["held"])
            self.assertTrue(all(a["attempt"] <= system3.GATE_REWRITES for a in asks))
            self.assertLessEqual(len(asks), system3.GATE_VISITS)
            no_copies(self, conv, out["script"])

    def test_the_passage_call(self):
        conv = conv_of(CALL_B)
        run, out, _asks = walk(conv, written(CALL_B), fresh_writer)
        self.assertEqual(out["held"], "")
        rules = {r["catch"]["rule"] for r in run["rows"] if r.get("catch")}
        self.assertLessEqual({"copy", "passage"}, rules)
        sign_off = next(r for r in run["rows"] if r["leg"] == "sign_off")
        self.assertEqual((sign_off["catch"]["rule"], sign_off["state"]), ("passage", "rewritten"))
        no_copies(self, conv, out["script"])

    def test_the_looping_banter_keeps_its_rhythm(self):
        conv = conv_of(BANTER)
        turns = written(BANTER)
        run, out, _asks = walk(conv, turns, fresh_writer)
        no_copies(self, conv, out["script"])
        seats = [m for m, _t in turns_of(out["script"])]
        self.assertTrue(all(a != b for a, b in zip(seats, seats[1:])), seats)
        self.assertGreaterEqual(out["counts"]["caught"], 10)
        self.assertEqual(out["held"], "", "banter has no protocol leg to lose")
        # the topics-board row and the passage read back are among the catches
        rules = {r["catch"]["rule"] for r in run["rows"] if r.get("catch")}
        self.assertLessEqual({"copy", "topic", "passage"}, rules)

    def test_a_live_round_is_not_rewritten_its_copies_are_dropped(self):
        conv = conv_of(BANTER)
        run, out, asks = walk(conv, written(BANTER), fresh_writer, rewrites=0, visits=0)
        self.assertEqual(asks, [])
        self.assertEqual(out["counts"]["rewritten"], 0)
        no_copies(self, conv, out["script"])
        why = {r["why"] for r in run["rows"] if r["state"] == "dropped" and r.get("catch")}
        self.assertTrue(any("not re-written" in w for w in why), why)

    def test_a_clean_round_passes_untouched(self):
        conv = conv_of(CALL_A)
        turns = [(t["speaker"], fresh(i, t["speaker"]).split(": ", 1)[1]) for i, t in enumerate(conv["turns"])]
        run, out, asks = walk(conv, turns, fresh_writer)
        self.assertEqual((out["changed"], out["counts"]["caught"], asks), (False, 0, []))
        self.assertEqual(turns_of(out["script"]), turns)

    def test_every_catch_rewrite_and_drop_is_an_event_on_its_node(self):
        conv = conv_of(CALL_A)
        run, out, _asks = walk(conv, written(CALL_A), fresh_writer)
        # gate_close appends the round's own summary; the walk's events were flushed
        # by whoever drove it - here nobody did, so they are all still on the run
        stages = [e["stage"] for e in run["events"]]
        self.assertEqual(stages.count("caught"), out["counts"]["caught"])
        self.assertEqual(stages.count("re-written"), out["counts"]["rewritten"])
        self.assertEqual(stages.count("trimmed"), out["counts"]["trimmed"])
        self.assertEqual(stages[-1], "gate")
        for e in run["events"]:
            if e.get("planned"):
                self.assertTrue(e["turn_id"].startswith(CALL_A + ":t"))
                self.assertIn("es", e["dice"])
        rw = next(e for e in run["events"] if e["stage"] == "re-written")
        self.assertIn("THE LINE YOU ANSWER", rw["prompt"])


class ModeB(unittest.TestCase):
    def test_observe_notes_a_copy_and_moves_the_state_the_same(self):
        a, b = conv_of(BANTER), conv_of(BANTER)
        for conv in (a, b):
            for t in conv["turns"]:
                t.pop("text", None)
            conv["observations"] = []
            system3.observe(conv, 0, "Nobody here remembers the orchard at all.")
        rec_a = system3.observe(a, 1, "Nobody here remembers the orchard at all.")
        rec_b = system3.observe(b, 1, "The orchard burned down the year the harbour froze.")
        self.assertEqual(rec_a["copy"]["rule"], "copy")
        self.assertNotIn("copy", rec_b)
        self.assertEqual(rec_a["delta"], system3.observe(copy.deepcopy(b), 1, "Nobody here remembers the orchard at all.")["delta"])

    def test_summary_carries_the_gate(self):
        conv = conv_of(CALL_A)
        conv.setdefault("identity", {}).setdefault("system2_slot_id", "")
        conv.setdefault("decision_events", [])
        self.assertIsNone(system3.summary(conv)["gate"])
        walk(conv, written(CALL_A), fresh_writer)
        g = system3.summary(conv)["gate"]
        self.assertEqual((g["caught"], g["rewritten"], g["dropped"]), (4, 3, 1))


class Runtime(unittest.TestCase):
    def setUp(self):
        from test_system3_runtime import FakeStation, settle
        self.settle = settle
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.rt = system3_runtime.System3Runtime(system3_runtime._Host(self.station))
        self.rt.settings = system3.normalise_settings({"mode": "active", "roads": ["banter", "caller"]})
        self.rt.ready = True
        self.addCleanup(lambda: (settle(), self.rt.store.close()))

    def handle(self, cid):
        conv = conv_of(cid)
        conv["identity"]["conversation_id"] = "t" + cid
        for t in conv["turns"]:
            t["turn_id"] = t["turn_id"].replace(cid, "t" + cid)
        return system3_runtime.Handle(self.rt, conv, system3.default_config(), True)

    def drive(self, h, writer, prepared=True):
        self.assertTrue(self.rt.turn_gate(h, written(h.conv["identity"]["conversation_id"][1:]), None, prepared))
        n = 0
        while True:
            ask = self.rt.turn_gate_next(h)
            if not ask:
                break
            n += 1
            said = writer(n, ask, h.gate)
            got = turns_of(said)
            self.rt.turn_gate_reply(h, got[0][1] if got else said)
        return self.rt.turn_gate_done(h)

    def events(self, conv):
        self.rt.persist(conv)
        self.settle()
        got = self.rt.store.conversation(conv["identity"]["conversation_id"]) or {}
        return [e for e in got.get("observations_air") or [] if e.get("family") == "GATE"]

    def test_the_doors_walk_record_and_count(self):
        h = self.handle(CALL_A)
        out = self.drive(h, fresh_writer)
        self.assertEqual((out["counts"]["caught"], out["counts"]["rewritten"], out["held"]), (4, 3, ""))
        self.assertIsNone(h.gate)
        evs = self.events(h.conv)
        stages = [e["stage"] for e in evs]
        self.assertEqual(stages.count("caught"), 4)
        self.assertEqual(stages.count("re-written"), 3)
        self.assertIn("gate", stages)
        on_node = [e for e in evs if e["stage"] == "caught" and e.get("turn_id")]
        self.assertTrue(all(e["turn_id"].startswith(h.id + ":t") for e in on_node))
        m = self.rt.status()["metrics"]
        self.assertEqual((m["gate_rounds"], m["gate_caught"], m["gate_rewritten"], m["gate_trimmed"]), (1, 4, 3, 22))
        self.assertEqual(m["gate_visits"], out["counts"]["visits"])
        row = [r for r in self.rt.store.conversations(limit=5) if r["conversation_id"] == h.id][0]
        self.assertEqual(row["gate"]["caught"], 4)

    def test_a_live_round_or_repair_off_is_never_rewritten(self):
        h = self.handle(BANTER)
        out = self.drive(h, fresh_writer, prepared=False)
        self.assertEqual((out["counts"]["visits"], out["counts"]["rewritten"]), (0, 0))
        self.rt.settings = dict(self.rt.settings, repair=False)
        h = self.handle(CALL_A)
        out = self.drive(h, fresh_writer, prepared=True)
        self.assertEqual(out["counts"]["visits"], 0)
        self.assertIn("could not be written", out["held"])

    def test_not_a_system3_round_nothing_to_walk(self):
        h = self.handle(CALL_A)
        h.active = False
        self.assertFalse(self.rt.turn_gate(h, written(CALL_A)))
        self.assertIsNone(self.rt.turn_gate_next(h))
        self.assertEqual(self.rt.turn_gate_done(h), {})

    def test_the_beat_chain_check(self):
        h = self.handle(BANTER)
        check = self.rt.beat_gate(h)
        made = [("A", ROUNDS[BANTER]["conv"]["turns"][0]["text"]), ("B", "Sounds like a mess, and a loud one.")]
        self.assertEqual(check(made, {"turn": 3, "seat": "A"}, "The orchard burned down the year the harbour froze."), "")
        got = check(made, {"turn": 3, "seat": "A"}, "Sounds like a mess, and a loud one.")
        self.assertIn("line (turn 2)", got)
        self.assertEqual(h.conv["turn_gate"]["in_chain"]["caught"], 1)
        self.assertTrue(check(made, {"turn": 6, "seat": "B"},
                              "You have to stop microwaving pets. The manager is going to catch you and he's going "
                              "to fire you bro."))
        evs = self.events(h.conv)
        self.assertEqual([e["stage"] for e in evs], ["caught in the beat chain"] * 2)
        self.assertEqual(self.rt.status()["metrics"]["gate_in_chain"], 2)
        h.active = False
        self.assertIsNone(self.rt.beat_gate(h))

    def test_the_microphone_check_and_its_node(self):
        copies = self.rt.line_copies
        said = ["Coming up next, the Stones.", "Lines are open at the station. Waiting on our first caller."]
        got = copies("Lines are open at the station. Waiting on our first caller.", said)
        self.assertEqual((got["of"], got["how"]), (1, "word for word"))
        self.assertIsNone(copies("We are waiting for a request from our caller. Checking the lines now.", said))
        self.assertIsNone(copies("", said))
        # a single-voice node refused at the microphone is marked dropped, with the why
        line = asyncio_run(self.rt.direct_line({"road": "open", "who": "dj", "dj": {"host_name": "Dill"},
                                                "context": "open the show"}))
        self.rt.line_gate(line, said[1], dict(got, why="it repeats the line Dill said 10 s ago", kind="open"))
        evs = self.events(line.conv)
        self.assertEqual((evs[-1]["stage"], evs[-1]["rule"], evs[-1]["turn_id"]),
                         ("dropped at the microphone", "copy", line.stamp["turn_id"]))
        self.assertEqual(line.conv["status"], "dropped")
        self.assertEqual(self.rt.status()["metrics"]["gate_air_dropped"], 1)
        self.rt.line_gate({"conversation_id": "nobody", "turn_id": ""}, "x", {})   # never raises
        self.rt.line_gate(None, "x", {})


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
