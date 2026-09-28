"""[s3-callend] How a call ends: the caller's wheel (RESOLVE1), the response chain, the
caller's rebuttal and WRAP CALL (WRAP1), planned at the end of the call's node tree.

The operator, 2026-09-28: "a resolution node with an RNG for setting up how a phone call
is wrapped up ... customers roll a wheel for how their call is ended. If the last segment
was selling a painting ... buys painting / wins painting due to raffle of being [RNG]
caller / is offered painting and they reject it / ... reject it by saying [RNG]
[speakerbox] / buys painting but decides to catch it on fire / ignores painting and says
they dont want it / buys painting but doesnt have enough money ... a response chain that
follows + a rebuttal from the caller before the call ends by somone one the station ending
the call in response to the customer "wrap call" roulette node".

Engine and runtime only (no app import): the painting wheel on and off, each of the seven
outcomes planning its chain, the raffle's caller number and the speakerbox rejection
recorded, the wrap's who and how rolled, the dead-line wheel, own streams (with the tables
switched off the call plans exactly the old draws), replay, the structure's validation, the
runtime's migration, the passage fetched, the mark on the call meta and the gallery effect
at air."""
import asyncio
import copy
import json
import re
import tempfile
import unittest

import system3
import system3_tables
import system3_runtime

from test_system3_runtime import FakeStation, ctx, settle
from fastapi import FastAPI
from fastapi.testclient import TestClient

PAINTING = {"image": "harbour_at_dawn_00275_.png", "title": "harbour at dawn",
            "desc": "a fishing boat under a violet sky with gulls", "price": 298,
            "terms": "first caller takes it", "kind": "gallery", "at": 1_800_000_000.0, "age": 120.0}
SEVEN = ("buys", "raffle", "rejects", "rejects_quote", "buys_burns", "ignores", "short")
OLD_ENDING = [
    {"id": "lands", "label": "The caller lands it", "place": "close", "seat": "C",
     "act": "{FIRST} LANDS IT. The caller says the last word of their own story here. This must be "
            "the SECOND TO LAST turn of the whole call.",
     "draws": [{"family": "ES"}]},
    {"id": "sign_off", "label": "Sign off", "place": "close", "seat": "A",
     "act": "SIGN OFF. The final turn is a host, and it must contain one of these words out loud: "
            "thanks, thank you, goodbye, goodnight, take care, appreciate.",
     "draws": [{"family": "ES"}]},
]


def call_inputs(painting=None, **over):
    call = {"name": "Dana Frost", "first": "Dana", "other": "Skip", "speakerbox": "The raccoon took the van."}
    if painting:
        call["painting"] = dict(painting)
    base = {"road": "caller", "seats": ["A", "B", "C"], "turns": 12, "at": 1_800_000_000.0,
            "names": {"A": "Dill", "B": "Skip", "C": "Dana"}, "roles": {"A": "dj", "B": "cohost", "C": "caller"},
            "subject": {"topic": "a raccoon in the van"}, "availability": {"call_passage": True},
            "call": call, "event_rolls": True}
    base.update(over)
    return base


def settings(seed):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def no_events(cfg):
    for t in cfg["tables"]:
        if t["family"] == "EVENT":
            for c in t["categories"]:
                c["odds"] = 0.0
    return cfg


def plan(seed, cfg=None, painting=None, **over):
    cfg = cfg if cfg is not None else no_events(system3.default_config())
    conv = system3.new_conversation(call_inputs(painting, **over), cfg, settings(seed), conversation_id="ce-" + seed)
    return system3.plan_call(conv, cfg, conv["inputs"])


def pinned(cfg, family, fixed=None, category=None):
    """The caller structure with the RESOLVE (or WRAP) draw pinned, as the Segments editor pins it."""
    cfg = copy.deepcopy(cfg)
    for leg in cfg["structures"]["caller"]["legs"]:
        for d in leg.get("draws") or []:
            if d.get("family") == family:
                if fixed:
                    d["fixed"] = fixed
                if category:
                    d["category"] = category
    return cfg


def fam_events(conv, family, kind=None):
    return [e for e in conv["decision_events"] if e["family"] == family
            and (kind is None or (e.get("meta") or {}).get("kind") == kind)]


def legs(conv):
    return [t.get("leg") for t in conv["turns"]]


def draws_of(conv):
    """Every main-stream decision a call's turns carry: seat, family, item, and the ES intensity."""
    return [(t["speaker"], [(d.get("family"), d.get("item"), d.get("intensity")) for d in t["decisions"]
                            if d.get("family") not in system3_tables.CALLEND_FAMILIES]) for t in conv["turns"]]


class TableTests(unittest.TestCase):
    def test_the_tables_are_default_and_validate(self):
        ids = [t["id"] for t in system3_tables.default_tables()]
        self.assertIn("RESOLVE1", ids)
        self.assertIn("WRAP1", ids)
        for t in system3_tables.default_tables():
            if t["family"] in ("RESOLVE", "WRAP"):
                got = system3.validate_table(copy.deepcopy(t))
                self.assertEqual(got["family"], t["family"])
        paint = next(c for c in system3_tables.RESOLVE1["categories"] if c["id"] == "painting")
        self.assertEqual([i["id"] for i in paint["items"]], list(SEVEN), "exactly the operator's seven")
        self.assertEqual(paint["requires"], ["painting"])
        general = next(c for c in system3_tables.RESOLVE1["categories"] if c["id"] == "general")
        self.assertIn("painting", general["unless"])
        self.assertIn("prize", [i["id"] for i in general["items"]])

    def test_the_caller_structure_ends_on_the_five_legs_and_validates(self):
        st = system3_tables.default_structures()["caller"]
        self.assertEqual([leg["id"] for leg in st["legs"]][-5:],
                         ["resolution", "reaction", "response", "rebuttal", "wrap_call"])
        self.assertEqual(system3_tables.validate_structure("caller", st), [])
        bad = copy.deepcopy(st)
        bad["legs"][-1]["end"] = "nonsense"
        self.assertTrue(any("end must be one of" in p for p in system3_tables.validate_structure("caller", bad)))
        other = {"legs": [{"id": "x", "place": "close", "seat": "A", "draws": [{"family": "RESOLVE"}]}]}
        self.assertTrue(system3_tables.validate_structure("news", other), "the call's end families are the caller road's")


class PlanTests(unittest.TestCase):
    def test_the_painting_wheel_only_when_the_last_segment_sold_one(self):
        with_p = plan("p1", painting=PAINTING)
        ev = fam_events(with_p, "RESOLVE", "outcome")[0]
        self.assertEqual(ev["selected"]["category"], "painting")
        cat = next(s for s in ev["stages"] if s["stage"] == "category")
        self.assertIn("painting wheel stands", json.dumps(cat["excluded"]))
        self.assertIn(ev["selected"]["id"], SEVEN)
        without = plan("p1")
        ev = fam_events(without, "RESOLVE", "outcome")[0]
        self.assertEqual(ev["selected"]["category"], "general")
        cat = next(s for s in ev["stages"] if s["stage"] == "category")
        self.assertIn("did not sell a painting", json.dumps(cat["excluded"]))
        self.assertNotIn("painting", ((without.get("callend") or {}).get("resolve") or {}))

    def test_each_of_the_seven_outcomes_plans_its_chain(self):
        base = no_events(system3.default_config())
        for outcome in SEVEN:
            with self.subTest(outcome=outcome):
                conv = plan("seven-" + outcome, pinned(base, "RESOLVE", outcome), painting=PAINTING)
                ce = conv["callend"]
                self.assertEqual(ce["resolve"]["id"], outcome)
                ev = next(e for e in fam_events(conv, "RESOLVE", "outcome"))
                self.assertEqual(ev["meta"]["authority"], "fixed")
                ls = legs(conv)
                self.assertEqual(ls[-1], "wrap_call")
                self.assertEqual(ls[-2], "rebuttal")
                i = ls.index("resolution")
                self.assertEqual(ls[i + 1], "reaction")
                chain = ls[i + 2:-2]
                self.assertTrue(chain and set(chain) == {"response"} and len(chain) <= 2, chain)
                t = conv["turns"]
                self.assertEqual(t[i + 1]["speaker"], "C", "the caller plays it out")
                self.assertEqual(t[-2]["speaker"], "C", "the rebuttal is the caller's, second to last")
                self.assertIn(t[-1]["speaker"], ("A", "B"), "someone on the station wraps it")
                self.assertNotEqual(t[i]["speaker"], t[i - 1]["speaker"], "nobody speaks twice in a row")
                for a, b in zip(t, t[1:]):
                    self.assertNotEqual(a["speaker"], b["speaker"])
                sheet = system3.render_call_sheet(conv)
                self.assertIn("THE RESOLUTION", sheet)
                self.assertIn("GETS THE LAST WORD", sheet)
                self.assertIn("WRAP CALL", sheet)
                self.assertIn("harbour at dawn", sheet)
                self.assertEqual(ce["resolve"]["effect"],
                                 {"buys": "sold", "raffle": "awarded", "buys_burns": "burnt"}.get(outcome, "unsold"))
                self.assertEqual(ce["resolve"]["painting"]["image"], PAINTING["image"])
                self.assertTrue(any(d["family"] == "RESOLVE" for d in t[i]["decisions"]))
                self.assertTrue(any(d["family"] == "WRAP" for d in t[-1]["decisions"]))
                mark = system3.callend_mark(conv)
                self.assertTrue(mark["planned"] and mark["wrap"]["planned"])
                self.assertEqual(mark["end_turns"], len(t) - i)
                self.assertTrue(mark["says"])
        # the prices and the words the writer is told
        buys = plan("seven-buys", pinned(base, "RESOLVE", "buys"), painting=PAINTING)
        self.assertIn("298 dollars", system3.render_call_sheet(buys))
        burns = plan("burn", pinned(base, "RESOLVE", "buys_burns"), painting=PAINTING)
        self.assertIn("setting it on fire", system3.render_call_sheet(burns))

    def test_the_raffle_rolls_the_caller_number(self):
        conv = plan("raffle", pinned(no_events(system3.default_config()), "RESOLVE", "raffle"), painting=PAINTING)
        ev = fam_events(conv, "RESOLVE", "raffle")
        self.assertEqual(len(ev), 1)
        n = conv["callend"]["resolve"]["number"]
        self.assertTrue(2 <= n <= 99)
        self.assertEqual(ev[0]["selected"]["id"], str(n))
        self.assertIsNotNone(ev[0]["rng"])
        self.assertIn("caller number %d" % n, system3.render_call_sheet(conv))
        again = plan("raffle", pinned(no_events(system3.default_config()), "RESOLVE", "raffle"), painting=PAINTING)
        self.assertEqual(again["callend"]["resolve"]["number"], n, "replayable")

    def test_the_speakerbox_rejection_asks_for_a_passage_on_the_callers_turn(self):
        conv = plan("quote", pinned(no_events(system3.default_config()), "RESOLVE", "rejects_quote"), painting=PAINTING)
        reaction = next(t for t in conv["turns"] if t.get("leg") == "reaction")
        reqs = [r for r in conv["material_requests"] if r.get("callend")]
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["turn_id"], reaction["turn_id"])
        self.assertEqual(reqs[0]["mode"], "APPEND")
        sb = [x for x in reaction["speakerbox"] if x.get("mark") == "callend"]
        self.assertEqual(len(sb), 1)
        ev = next(e for e in conv["decision_events"] if e["event_id"] == sb[0]["event_id"])
        self.assertEqual(ev["family"], "SPEAKERBOX")
        self.assertEqual(ev["turn_id"], reaction["turn_id"])
        # unresolved, the row says so; resolved, the passage is said word for word
        self.assertIn("No passage came back", system3.render_call_sheet(conv))
        sb[0]["material"] = {"file": "43d.md", "text": "I want to eat. Someone got eaten."}
        self.assertIn('"I want to eat. Someone got eaten."', system3.render_call_sheet(conv))

    def test_the_prize_comes_off_the_stations_own_list(self):
        cfg = pinned(no_events(system3.default_config()), "RESOLVE", "prize")
        conv = plan("prize", cfg)
        prize = conv["callend"]["resolve"]["prize"]
        self.assertIn(prize, system3_tables.CALL_PRIZES)
        ev = fam_events(conv, "RESOLVE", "prize")[0]
        self.assertIn("not on the desk yet", ev["meta"]["why"])
        # once the desk has the list (POOLS1 call.prizes), its rows and weights govern
        pools = next(t for t in cfg["tables"] if t["id"] == "POOLS1")
        pools["categories"].append({"id": "call.prizes", "label": "prizes", "weight": 1.0, "items": [
            {"id": "o0", "label": "a mug", "text": "a Pine Box mug", "weight": 1.0}]})
        conv = plan("prize", cfg)
        self.assertEqual(conv["callend"]["resolve"]["prize"], "a Pine Box mug")
        self.assertIn("a Pine Box mug", system3.render_call_sheet(conv))

    def test_the_wrap_rolls_who_and_how(self):
        conv = plan("wrap-1", painting=PAINTING)
        how = fam_events(conv, "WRAP", "how")
        who = fam_events(conv, "WRAP", "who")
        self.assertEqual(len(how), 1)
        self.assertEqual(len(who), 1)
        st = next(s for s in who[0]["stages"] if s["stage"] == "who")
        seats = {c["id"] for c in st["candidates"]}
        self.assertTrue(seats <= {"A", "B"}, seats)
        excl = {x["id"]: x["why"] for x in st["excluded"]}
        self.assertIn("S", excl)
        self.assertIn("Sam", excl["S"])
        self.assertEqual(conv["turns"][-1]["speaker"], conv["callend"]["wrap"]["seat"])
        self.assertEqual(how[0]["turn_id"], conv["turns"][-1]["turn_id"])

    def test_a_wrap_tied_to_an_outcome_comes_up_only_after_it(self):
        base = no_events(system3.default_config())
        fire = plan("tie", pinned(base, "RESOLVE", "buys_burns"), painting=PAINTING)
        item = next(s for s in fam_events(fire, "WRAP", "how")[0]["stages"] if s["stage"] == "item")
        self.assertIn("enjoy_the_ashes", [c["id"] for c in item["candidates"]] + [x["id"] for x in item["excluded"]])
        if fire["callend"]["wrap"]["category"] == "ends":
            self.assertIn("enjoy_the_ashes", [c["id"] for c in item["candidates"]])
        no = plan("tie", pinned(base, "RESOLVE", "rejects"), painting=PAINTING)
        item = next(s for s in fam_events(no, "WRAP", "how")[0]["stages"] if s["stage"] == "item")
        why = {x["id"]: x["why"] for x in item["excluded"]}
        self.assertIn("only after tag:fire", why.get("enjoy_the_ashes", ""))
        self.assertIn("offer_stands", [c["id"] for c in item["candidates"]])
        pinned_wrap = plan("tie", pinned(pinned(base, "RESOLVE", "buys_burns"), "WRAP", "enjoy_the_ashes"),
                           painting=PAINTING)
        self.assertIn("enjoy the ashes", system3.render_call_sheet(pinned_wrap))

    def test_a_call_cut_short_gets_the_dead_line_wrap(self):
        cfg = system3.default_config()
        for t in cfg["tables"]:
            if t["id"] == "CALLEVENT1":
                for c in t["categories"]:
                    c["odds"] = 1.0 if c["id"] == "pulled_away" else 0.0
        conv = plan("dead", cfg, painting=PAINTING, turns=16)
        self.assertIsNotNone(conv.get("event_end"))
        self.assertEqual(conv["callend"]["wrap"]["category"], "dead_line")
        self.assertTrue(conv["callend"]["wrap"]["dead_line"])
        self.assertEqual(conv["turns"][-1]["leg"], "wrap_call")
        at = conv["callend"]["at"]
        if at.get("reaction") is None or at["reaction"] >= conv["event_end"]:
            self.assertTrue(conv["callend"]["resolve"]["cut"])
            self.assertTrue(system3.callend_mark(conv)["resolve"]["cut"])

    def test_own_streams_with_the_tables_off_the_call_is_the_old_call(self):
        old = no_events(system3.default_config())
        old["structures"]["caller"]["legs"] = old["structures"]["caller"]["legs"][:-5] + copy.deepcopy(OLD_ENDING)
        old["tables"] = [t for t in old["tables"] if t["family"] not in ("RESOLVE", "WRAP")]
        off = no_events(system3.default_config())
        off["tables"] = [t for t in off["tables"] if t["family"] not in ("RESOLVE", "WRAP")]
        for seed in ("s1", "s2", "s3", "s4"):
            a, b = plan(seed, old), plan(seed, off)
            self.assertEqual(draws_of(a), draws_of(b), seed)
            self.assertEqual([t["speaker"] for t in a["turns"]], [t["speaker"] for t in b["turns"]])
            self.assertEqual(legs(b)[-2:], ["rebuttal", "wrap_call"])
            self.assertIn("thanks, thank you, goodbye", b["turns"][-1]["protocol"], "a spoken sign-off")
            self.assertIsNone(system3.callend_mark(b))
        # and with events rolling, the happenings land where they did
        ev_old, ev_off = copy.deepcopy(old), copy.deepcopy(off)
        for cfg in (ev_old, ev_off):
            for t in cfg["tables"]:
                if t["id"] == "CALLEVENT1":
                    for c in t["categories"]:
                        c["odds"] = 0.6
        a, b = plan("ev", ev_old, turns=16), plan("ev", ev_off, turns=16)
        self.assertEqual([(e["family"], (e.get("selected") or {}).get("id"), e.get("turn_index"))
                          for e in a["decision_events"] if e["family"] == "EVENT"],
                         [(e["family"], (e.get("selected") or {}).get("id"), e.get("turn_index"))
                          for e in b["decision_events"] if e["family"] == "EVENT"])

    def test_with_the_tables_on_the_opening_draws_do_not_move(self):
        old = no_events(system3.default_config())
        old["structures"]["caller"]["legs"] = old["structures"]["caller"]["legs"][:-5] + copy.deepcopy(OLD_ENDING)
        new = no_events(system3.default_config())
        a, b = plan("open", old), plan("open", new)
        self.assertEqual(draws_of(a)[:7], draws_of(b)[:7], "the open legs roll exactly what they rolled")

    def test_replay_reproduces_a_planned_end(self):
        cfg = system3.default_config()
        conv = plan("replay", cfg, painting=PAINTING, turns=14)
        stored = json.loads(json.dumps(conv, default=str))
        got = system3.replay(stored, cfg)
        self.assertTrue(got["ok"], got.get("why"))

    def test_the_ending_shelf_words_give_way_on_the_sheet(self):
        conv = plan("tail", painting=PAINTING)
        sheet = system3.render_call_sheet(conv)
        self.assertIn("exactly as the running order rolled it", sheet)
        self.assertNotIn("the spoken sign-off on the last turn", sheet)

    def test_the_caller_plays_it_out_in_a_feeling_the_outcome_leans(self):
        conv = plan("feel", pinned(no_events(system3.default_config()), "RESOLVE", "raffle"), painting=PAINTING)
        reaction = next(t for t in conv["turns"] if t.get("leg") == "reaction")
        ev = next(e for e in conv["decision_events"] if e["family"] == "ES" and e["turn_id"] == reaction["turn_id"])
        cats = {c["id"]: c["weight"] for c in next(s for s in ev["stages"] if s["stage"] == "category")["candidates"]}
        self.assertEqual(max(cats, key=cats.get), "joy", cats)          # x3 on joy: winning it leans it
        plain = plan("feel", pinned(no_events(system3.default_config()), "RESOLVE", "rejects"), painting=PAINTING)
        reaction = next(t for t in plain["turns"] if t.get("leg") == "reaction")
        ev = next(e for e in plain["decision_events"] if e["family"] == "ES" and e["turn_id"] == reaction["turn_id"])
        items = [c for s in ev["stages"] if s["stage"] == "item" for c in s["candidates"]]
        self.assertFalse(any("what happens on this turn" in w for c in items for w in c["why"]),
                         "an outcome with no emotions leans nothing")


class RuntimeTests(unittest.TestCase):
    def boot(self, gallery=None):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.effects, self.context = [], []
        self.station.update(
            system3_painting_on_offer=lambda within=1200.0: dict(gallery or {}),
            system3_gallery_outcome=lambda effect, painting, cid="": (
                self.effects.append((effect, painting.get("image"), cid)) or {"applied": True}),
            call_line_context=lambda **kw: self.context.append(kw))
        app = FastAPI()
        system3_runtime.install(app, self.station)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.rt = self.station["_system3"]()
        self.addCleanup(self.rt.store.close)
        self.addCleanup(settle)
        r = self.client.post("/api/system3/settings", json={"mode": "active_selected_roads",
                                                             "roads": ["banter", "caller"], "test_seed": "ce-rt"},
                             headers={"Authorization": "Bearer k"})
        self.assertEqual(r.status_code, 200, r.text)
        return self.rt

    def run_(self, coro):
        return asyncio.new_event_loop().run_until_complete(coro)

    def call(self, **over):
        meta = {"topic": "a cat in the sewer", "speakerbox_text": "The cat kidnapped somebody."}
        return self.run_(self.station["system3_direct_banter"](**ctx(
            caller_name="Monk Brennan", lines=12, seats=["A", "B", "C"], call_meta=meta,
            call_sheet=" 1  A  - ANSWER THE RINGING LINE.", **over))), meta

    def test_a_call_carries_its_rolled_end_to_the_station(self):
        self.boot(gallery=PAINTING)
        h, meta = self.call(bank=False)
        self.assertIsNotNone(h)
        self.assertTrue(h.active)
        mark = meta.get("callend")
        self.assertTrue(mark and mark["planned"], meta)
        self.assertEqual(mark["resolve"]["category"], "painting")
        self.assertEqual(mark["resolve"]["painting"]["image"], PAINTING["image"])
        self.assertTrue(mark["wrap"]["planned"])
        self.assertIn("WRAP CALL", h.sheet)
        self.assertEqual(h.conv["turns"][-1]["leg"], "wrap_call")
        self.assertTrue(any("callend" in kw for kw in self.context), "the live call's record is told")

    def test_a_banked_call_keeps_the_mark_and_leaves_the_live_line_alone(self):
        self.boot()
        h, meta = self.call(bank=True)
        self.assertTrue(meta["callend"]["planned"])
        self.assertEqual(meta["callend"]["resolve"]["category"], "general")
        self.assertFalse(self.context, "a banked call never writes into whatever call is live")

    def test_the_rejection_passage_is_fetched_through_the_station(self):
        rt = self.boot(gallery=PAINTING)
        cfg = copy.deepcopy(rt.config)
        for leg in cfg["structures"]["caller"]["legs"]:
            for d in leg.get("draws") or []:
                if d.get("family") == "RESOLVE":
                    d["fixed"] = "rejects_quote"
        rt.config = cfg
        h, meta = self.call(bank=True)
        reaction = next(t for t in h.conv["turns"] if t.get("leg") == "reaction")
        sb = next(x for x in reaction["speakerbox"] if x.get("mark") == "callend")
        self.assertEqual(sb["material"]["file"], "43d.md")
        self.assertIn("Someone got eaten.", h.sheet)
        self.assertEqual(self.station.quote_calls, 1, "only the rejection's passage is fetched")
        self.assertTrue(meta["callend"]["resolve"]["speakerbox"])

    def test_the_outcome_acts_on_the_gallery_once_at_air(self):
        rt = self.boot(gallery=PAINTING)
        cfg = copy.deepcopy(rt.config)
        for leg in cfg["structures"]["caller"]["legs"]:
            for d in leg.get("draws") or []:
                if d.get("family") == "RESOLVE":
                    d["fixed"] = "buys_burns"
        rt.config = cfg
        h, _meta = self.call(bank=True)
        settle()
        rows = [{"line_id": "L%d" % i, "who": "dj", "text": "words " * 12,
                 "system3": {"conversation_id": h.id, "turn_id": t["turn_id"]}}
                for i, t in enumerate(h.conv["turns"])]
        rt.observe_ledger(7, "sid-1", rows, "caller")
        settle()
        rt.observe_ledger(8, "sid-1", rows, "caller")
        settle()
        self.assertEqual(self.effects, [("burnt", PAINTING["image"], h.id)])
        conv = rt.store.conversation(h.id)
        self.assertTrue(any(o.get("family") == "CALLEND" for o in conv["observations_air"]))

    def test_an_old_stored_structure_gains_the_end_legs_once(self):
        rt = self.boot()
        cfg = copy.deepcopy(rt.config)
        cfg["structures"]["caller"]["legs"] = cfg["structures"]["caller"]["legs"][:-5] + copy.deepcopy(OLD_ENDING)
        cfg["defaults_added"] = [x for x in cfg.get("defaults_added") or [] if x != rt.CALLEND_MARK]
        rt.config = cfg
        note = rt.add_missing_call_legs()
        self.assertTrue(note)
        self.assertEqual([leg["id"] for leg in rt.config["structures"]["caller"]["legs"]][-5:],
                         ["resolution", "reaction", "response", "rebuttal", "wrap_call"])
        self.assertIn(rt.CALLEND_MARK, rt.config["defaults_added"])
        self.assertEqual(system3.config_hash(rt.store.config()), system3.config_hash(rt.config))
        # removed by the operator afterwards: they stay removed
        cfg = copy.deepcopy(rt.config)
        cfg["structures"]["caller"]["legs"] = cfg["structures"]["caller"]["legs"][:-5] + copy.deepcopy(OLD_ENDING)
        rt.config = cfg
        self.assertEqual(rt.add_missing_call_legs(), "")
        # a structure the operator reshaped is left as it is
        cfg = copy.deepcopy(rt.config)
        cfg["defaults_added"] = [x for x in cfg["defaults_added"] if x != rt.CALLEND_MARK]
        cfg["structures"]["caller"]["legs"] = cfg["structures"]["caller"]["legs"][:-1]
        rt.config = cfg
        self.assertEqual(rt.add_missing_call_legs(), "")
        self.assertEqual(rt.config["structures"]["caller"]["legs"][-1]["id"], "lands")

    def test_the_tables_reach_a_stored_config_that_predates_them(self):
        rt = self.boot()
        cfg = copy.deepcopy(rt.config)
        cfg["tables"] = [t for t in cfg["tables"] if t["family"] not in ("RESOLVE", "WRAP")]
        cfg["defaults_added"] = [x for x in cfg.get("defaults_added") or [] if x not in ("RESOLVE1", "WRAP1")]
        rt.config = cfg
        self.assertEqual(sorted(rt.add_missing_default_tables()), ["RESOLVE1", "WRAP1"])

    def test_the_wiring_is_in_the_desk(self):
        from pathlib import Path
        root = Path(system3.__file__).resolve().parent
        js = (root / "frontend" / "system3.js").read_text(encoding="utf-8")
        for words in ("FAM.RESOLVE", "FAM.WRAP", "RESOLVE: [\"Resolution - the caller's wheel (RESOLVE1)\"",
                      "WRAP: ['Wrap call (WRAP1)'", "callendTableFields", "callendItemFields",
                      "'RESOLVE', 'WRAP'"):
            self.assertIn(words, js)
        self.assertRegex(js, r"const TABLE_FAMILIES = \[[^\]]*'RESOLVE', 'WRAP'")


if __name__ == "__main__":
    unittest.main()
