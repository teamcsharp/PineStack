"""[s3-banks-roll] What the banks put on the air is the roulette's.

The operator's three decisions (2026-09-28): a banked round that has already
aired goes out again only on a desk roll (bank.reair), the replay is a roll
among the rested ones (bank.reair_pick) and is stamped "replay, first aired
<time>, airing N"; a gold run fires only on gold.run, every bar of the order is
a roll, only bars minted from System 3 turns fire and each airs stamped with
its source turn; a listening response is a roll per seam on the round's node,
its pick a roll among the eligible, stamped to the turn it answers. And the
re-air gate (reair_gate.py) is asked first: a round with copied turns, an echo
loop, a non_compliant verdict, the copy gate's flags or the sweep's mark never
goes out again, dice on or off, on any road - no roll is made for it.

The first two classes need only response_bank.py and system3_runtime.py; the
rest import app (run them in the container). Nothing here touches the
station's data dir: the dice are a System3Runtime on a temp store, and every
shelf, larder, bank and ledger read is patched."""
import asyncio
import json
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import response_bank
import system3
import system3_runtime
from test_system3_runtime import FakeStation, settle


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class Dice:
    """System 3's dice as the station installs them - live, on a temp store."""

    def __init__(self, mode="active"):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.station = FakeStation(self.tmp.name)
        self.rt = system3_runtime.System3Runtime(system3_runtime._Host(self.station))
        self.rt.settings = system3.normalise_settings({"mode": mode})
        self.rt.ready = True
        system3_runtime._S3_ROLLS.set(None)
        vars(system3_runtime._S3_LAST).clear()

    def door(self):
        rt = self.rt
        return {"system3_chance": rt.chance, "system3_pool": rt.pool, "system3_pick": rt.pick,
                "system3_roll": rt.roll, "system3_last_roll": rt.last_roll,
                "system3_dice_live": rt._dice_live, "system3_roll_to": rt.roll_to,
                "system3_turn_id_for": rt.turn_id_for, "_system3": lambda: rt}

    def rolls(self, key):
        return [r for r in self.rt.station_view() if r["key"] == key]

    def on_round(self, cid):
        """The STATION observations recorded on conversation `cid`."""
        settle()
        return [e for e in self.rt.store.events_after(0, 500, cid)["events"]
                if e.get("family") == "STATION" and e.get("kind") == "observation"]

    def odds(self, key, odds):
        """The desk's row for `key` (STATION1), at these odds."""
        config = self.rt.config
        st = self.rt._pool_table(config, "STATION1", _tables().STATION1)
        cat = next((c for c in st.setdefault("categories", []) if c.get("id") == key.split(".")[0]), None)
        if cat is None:
            cat = {"id": key.split(".")[0], "label": key, "weight": 1.0, "items": []}
            st["categories"].append(cat)
        cat["items"] = [i for i in cat.get("items") or [] if i.get("id") != key]
        cat["items"].append({"id": key, "label": key, "text": key, "odds": float(odds), "weight": 1.0})

    def pool(self, key, items):
        """The desk's POOLS1 category for `key`: [(text, weight, enabled)]."""
        config = self.rt.config
        pl = self.rt._pool_table(config, "POOLS1", _tables().POOLS1)
        pl.setdefault("categories", [])
        pl["categories"] = [c for c in pl["categories"] if c.get("id") != key]
        pl["categories"].append({"id": key, "label": key, "weight": 1.0, "items": [
            {"id": "o%d" % i, "label": t[:60], "text": t, "weight": w, "enabled": e}
            for i, (t, w, e) in enumerate(items)]})

    def close(self):
        settle()
        self.rt.store.close()
        self.tmp.cleanup()


def _tables():
    import system3_tables
    return system3_tables


# --- response_bank.py: the chooser --------------------------------------------------
class ResponseBankChooserTests(unittest.TestCase):
    def bank(self, texts=("Mm-hmm.", "I hear you.", "Go on.")):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        media = tmp / "media"
        media.mkdir()
        rows = {}
        for i, text in enumerate(texts):
            (media / ("r%d.wav" % i)).write_bytes(b"take")
            rows["k%d" % i] = {"voice": "v", "engine": "e", "text": text, "intent": "listening",
                               "clip": {"path": "/media/r%d.wav" % i}, "recorded_at": 1.0}
        (tmp / "bank.json").write_text(json.dumps(rows))
        return response_bank.ResponseBank(tmp / "bank.json", media)

    def test_the_pick_is_the_choosers_not_the_least_recently_used(self):
        bank = self.bank()
        seen = []
        got = bank.take("v", "e", "a long turn", chooser=lambda rows: (seen.append([r["text"] for r in rows]), 2)[1])
        self.assertEqual(got["text"], seen[0][2])
        self.assertEqual(len(seen[0]), 3, "every eligible response was on offer")

    def test_a_missed_seam_takes_nothing_and_rests_nothing(self):
        bank = self.bank()
        self.assertIsNone(bank.take("v", "e", "a long turn", chooser=lambda rows: -1))
        self.assertEqual(bank.last, {}, "a response that did not air is not rested")

    def test_a_response_heard_lately_waits_while_another_stands_by(self):
        bank = self.bank()
        bank.take("v", "e", "x", chooser=lambda rows: [r["text"] for r in rows].index("Go on."))
        offered = []
        bank.take("v", "e", "x", chooser=lambda rows: (offered.extend(r["text"] for r in rows), 0)[1])
        self.assertNotIn("Go on.", offered)
        self.assertEqual(sorted(offered), ["I hear you.", "Mm-hmm."])

    def test_without_a_chooser_the_bank_rotates_as_before(self):
        bank = self.bank()
        first = bank.take("v", "e", "x")
        second = bank.take("v", "e", "x")
        self.assertNotEqual(first["text"], second["text"])

    def test_the_seam_carries_the_rolls_line_and_node(self):
        playlist = [{"who": "dj", "chunk": "x" * 250, "turn_end": False},
                    {"who": "dj", "chunk": "y" * 50, "turn_end": True}]
        stamp = {"conversation_id": "c1", "turn_id": "c1:t00", "mode": "active"}
        out = response_bank.add_listening_responses(
            playlist, {"dj": "v1", "cohost": "v2"},
            lambda who, ctx, used: {"text": "Mm-hmm.", "clip": {"path": "/media/a.wav"},
                                    "line_id": "L1", "system3": stamp})
        added = [i for i in out if i.get("listening_response")]
        self.assertEqual(len(added), 1)
        self.assertEqual((added[0]["line_id"], added[0]["system3"]), ("L1", stamp))
        plain = response_bank.add_listening_responses(
            playlist, {"dj": "v1", "cohost": "v2"},
            lambda who, ctx, used: {"text": "Mm-hmm.", "clip": {"path": "/media/a.wav"}})
        self.assertNotIn("line_id", [i for i in plain if i.get("listening_response")][0])


# --- system3_runtime.py: a roll made at air lands on its round ----------------------
class RuntimeRollToTests(unittest.TestCase):
    def setUp(self):
        self.dice = Dice()
        self.addCleanup(self.dice.close)
        self.rt = self.dice.rt

    def test_a_roll_at_air_is_recorded_on_its_round_and_leaves_the_buffer(self):
        self.assertTrue(self.rt.chance("listen.seam", 1.0, "a seam"))
        self.assertEqual(len(system3_runtime._S3_ROLLS.get()["rolls"]), 1)
        got = self.rt.roll_to("listen.seam", "cid1", "cid1:t02", "a listening response at this seam")
        self.assertEqual((got["key"], got["hit"], got["recorded_on"]), ("listen.seam", True, "cid1"))
        self.assertIn("dice", got)
        self.assertEqual(system3_runtime._S3_ROLLS.get()["rolls"], [],
                         "the next plan must not absorb a roll that shaped this round")
        obs = self.dice.on_round("cid1")
        self.assertEqual(len(obs), 1)
        self.assertEqual((obs[0]["turn_id"], obs[0]["stage"], obs[0]["key"]),
                         ("cid1:t02", "a listening response at this seam", "listen.seam"))

    def test_no_fresh_roll_is_nothing(self):
        self.assertEqual(self.rt.roll_to("never.rolled", "cid1", "", "x"), {})

    def test_the_commit_keeps_a_lines_replay_gold_and_listening(self):
        rows = [{"line_id": "L1", "who": "dj", "text": "one",
                 "system3": {"conversation_id": "c1", "turn_id": "c1:t00",
                             "replay": {"label": "replay, first aired 07:14, airing 2"}}},
                {"line_id": "L2", "who": "cohost", "text": "Mm-hmm.",
                 "system3": {"conversation_id": "c1", "turn_id": "c1:t00",
                             "listening": {"label": "a listening response"}}}]
        self.rt.observe_ledger(7, "sid", rows, "banter")
        settle()
        commit = [e for e in self.rt.store.events_after(0, 100, "c1")["events"] if e.get("family") == "COMMIT"]
        self.assertEqual(len(commit), 1)
        media = commit[0]["media"]
        self.assertEqual(media["L1"]["replay"]["label"], "replay, first aired 07:14, airing 2")
        self.assertEqual(media["L2"]["listening"]["label"], "a listening response")
        conv = {"lines": [{"line_id": "L1"}, {"line_id": "L2"}], "observations_air": commit}
        system3_runtime.System3Runtime.line_media(conv)
        self.assertEqual(conv["lines"][0]["replay"]["label"], "replay, first aired 07:14, airing 2")

    def test_a_gold_bar_does_not_hand_its_old_round_on(self):
        conv = {"identity": {"conversation_id": "old", "road_kind": "banter"}, "turns": [{}, {}],
                "participants": [], "inputs": {"names": {}}, "subject": {}, "dynamics": {}, "tempers": {}}
        self.rt.recent["old"] = conv
        self.rt.observe_ledger(8, "s", [{"line_id": "G1", "who": "dj", "text": "a bar",
                                         "system3": {"conversation_id": "old", "turn_id": "old:t01",
                                                     "gold": {"label": "gold bar"}}}], "gold")
        settle()
        self.assertEqual(self.rt.carry, {}, "a bar replayed off an older round is not that round airing")
        self.rt.observe_ledger(9, "s", [{"line_id": "R1", "who": "dj", "text": "a round line",
                                         "system3": {"conversation_id": "old", "turn_id": "old:t01"}}], "banter")
        settle()
        self.assertEqual(self.rt.carry.get("from"), "old")


# --- app.py -----------------------------------------------------------------------
class StationCase(unittest.TestCase):
    """app, patched away from the station's state, with System 3's dice live."""

    def setUp(self):
        import app
        self.app = app
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.logged = []
        self.real_reair_marks = app._reair_marks
        self.patch(pipeline_log=lambda kind, text, extra="": self.logged.append((kind, text)),
                   _BANK_REAIR_MISS={}, _S3_AIR_OWN={}, _RERUN_S3={},
                   _RERUN_S3_INDEX={"at": 0.0, "index": {}},
                   _REAIR_GATE_SAID={}, _reair_marks=lambda: {},
                   round_airings_now=lambda kind, row: int((row or {}).get("aired") or 0))

    def patch(self, **values):
        for name, value in values.items():
            self.stack.enter_context(mock.patch.object(self.app, name, value))

    def dice(self, mode="active"):
        dice = Dice(mode)
        self.addCleanup(dice.close)
        self.stack.enter_context(mock.patch.dict(self.app.__dict__, dice.door()))
        return dice

    def dice_off(self):
        self.stack.enter_context(mock.patch.dict(self.app.__dict__, {
            "system3_dice_live": lambda: False, "_system3": lambda: None}))


def _round(cid, aired=0, at=None, text="the words of it"):
    now = time.time()
    entry = {"script": "A: %s\nB: and the answer" % text, "system3": {
        "conversation_id": cid, "mode": "active", "turns": {"0": cid + ":t00", "1": cid + ":t01"}}}
    row = {"at": at or now - 600, "entry": entry, "key": ""}
    if aired:
        row.update(aired=aired, aired_at=now - 4 * 3600)
    return row


# ef39853f9fa54974 (2026-09-28): turns that copy each other, aired seven times in 17 h
BROKEN = """A: Buried inside of me lucky my dad's here get the damn truck son i need to take you home
B: Buried inside of me lucky my dad's here get the damn truck son i need to take you home
A: Whoa, hold on. You're trying to frame this like it's about what we saw or what the studio decided.
B: Exactly! It's a joke, right? I'm just saying it's a joke. No, apparently music is everything.
A: Whoa, hold on. You're trying to frame this like it's about what we saw or what the studio decided.
B: Exactly! It's a joke, right? I'm just saying it's a joke. No, apparently music is everything. 10"""


def _broken(cid, aired=1):
    row = _round(cid, aired)
    row["entry"]["script"] = BROKEN
    return row


class ReairGateTests(StationCase):
    """The gate comes before the roulette: a retired round is never rolled for."""

    def test_the_roulette_never_rolls_for_a_round_the_gate_retired(self):
        dice = self.dice()
        self.assertEqual(self.app.bank_reair_pick("gallery", [_broken("b1")]), (None, None))
        self.assertEqual(dice.rolls("bank.reair"), [], "no die is cast for a retired round")
        clean = _round("c1", 1)
        row, stamp = self.app.bank_reair_pick("gallery", [_broken("b2"), clean])
        self.assertIs(row, clean)
        self.assertEqual(stamp["pick"]["of"], 1, "only the round the gate let through was on the wheel")
        self.assertTrue(any("re-air gate" in t for _k, t in self.logged))

    def test_dice_off_the_gate_still_holds(self):
        self.dice_off()
        clean = _round("c1", 1)
        self.assertEqual(self.app.bank_reair_pick("gallery", [_broken("b1"), clean]), (clean, None))
        self.assertEqual(self.app.bank_reair_pick("gallery", [_broken("b1")]), (None, None))

    def test_a_non_compliant_verdict_and_a_sweep_mark_retire_a_round(self):
        self.dice_off()
        nc = _round("nc", 1)
        nc["entry"]["system3"]["verdict"] = "non_compliant"
        self.assertIn("non_compliant", self.app.bank_reair_refusal("gallery", nc))
        marked = _round("marked", 1)
        self.assertEqual(self.app.bank_reair_refusal("gallery", marked), "")
        self.patch(_reair_marks=lambda: {"cid:marked": {"why": "the sweep's mark"}})
        self.assertIn("the sweep's mark", self.app.bank_reair_refusal("gallery", marked))

    def test_the_gate_says_so_once_an_hour_per_round(self):
        self.dice_off()
        for _ in range(3):
            self.app.bank_reair_refusal("banter", _broken("once"))
        self.assertEqual(sum(1 for _k, t in self.logged if "re-air gate" in t), 1)

    def test_the_marks_file_is_read_again_when_it_changes(self):
        import reair_gate
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = tmp / "reair_ineligible.json"
        self.patch(REAIR_MARKS_PATH=path, _REAIR_MARKS={"at": 0.0, "mtime": -1.0, "marks": {}})
        real = self.real_reair_marks
        self.assertEqual(real(), {})
        reair_gate.save_marks(path, {"cid:x": {"why": "w"}})
        self.app._REAIR_MARKS["at"] = 0.0
        self.assertEqual(real(), {"cid:x": {"why": "w"}})


class BankReairPickTests(StationCase):
    def test_dice_off_the_first_replay_as_before(self):
        self.dice_off()
        rows = [_round("c1", 1), _round("c2", 1)]
        self.assertEqual(self.app.bank_reair_pick("gallery", rows), (rows[0], None))

    def test_the_desk_lets_one_out_and_it_is_stamped_a_replay(self):
        dice = self.dice()
        rows = [_round("c1", 1), _round("c2", 2)]
        row, stamp = self.app.bank_reair_pick("gallery", rows, "the gallery cupboard")
        self.assertIn(row, rows)
        self.assertEqual(len(dice.rolls("bank.reair")), 1)
        self.assertEqual(len(dice.rolls("bank.reair_pick")), 1)
        self.assertEqual(stamp["airing"], int(row["aired"]) + 1)
        self.assertTrue(stamp["label"].startswith("replay, first aired "), stamp["label"])
        self.assertTrue(stamp["label"].endswith("airing %d" % (int(row["aired"]) + 1)))
        self.assertEqual(stamp["chance"]["key"], "bank.reair")
        self.assertEqual(stamp["pick"]["of"], 2)
        if int(row["aired"]) == 1:
            self.assertEqual(row["first_aired_at"], row["aired_at"],
                             "one airing before: that airing was the first")
        cid = row["entry"]["system3"]["conversation_id"]
        keys = sorted(o["key"] for o in dice.on_round(cid))
        self.assertEqual(keys, ["bank.reair", "bank.reair_pick"], "both rolls land on the round let out")

    def test_the_desk_can_keep_the_replays_off_and_the_answer_rests(self):
        dice = self.dice()
        dice.odds("bank.reair", 0.0)
        rows = [_round("c1", 1)]
        self.assertEqual(self.app.bank_reair_pick("news", rows), (None, None))
        self.assertEqual(self.app.bank_reair_pick("news", rows), (None, None))
        self.assertEqual(len(dice.rolls("bank.reair")), 1, "one decision per window, not one per pass")
        self.assertTrue(any("bank.reair" in t for _k, t in self.logged))

    def test_a_class_switched_off_on_the_desk_is_never_picked(self):
        dice = self.dice()
        classes = self.app.BANK_REAIR_CLASSES
        dice.pool("bank.reair_pick", [(classes[0], 1.0, False), (classes[1], 1.0, True), (classes[2], 1.0, True)])
        once, twice = _round("c1", 1), _round("c2", 2)
        for _ in range(4):
            self.app._BANK_REAIR_MISS.clear()
            row, _stamp = self.app.bank_reair_pick("gallery", [once, twice])
            self.assertIs(row, twice)
        self.app._BANK_REAIR_MISS.clear()
        self.assertEqual(self.app.bank_reair_pick("gallery", [once]), (None, None))


class ShelfTakeTests(StationCase):
    def shelf(self, rows, kind="gallery"):
        self.patch(shelf_rows=lambda k: rows, dialogue_row_ready=lambda k, r: True,
                   shelf_cast_stale=lambda r: False, _larder_current=lambda e: True,
                   pantry_get=lambda key: {"path": "x.wav"}, resort_keys=lambda k: set(),
                   alt_took=lambda k, r: None, repeat_safe=lambda k, r: True,
                   stock_expires_at=lambda k, r: 0.0, stock_used_by=lambda: "test",
                   shelf_rest_now=lambda: 3 * 3600.0, row_innings=lambda k, r: 3,
                   gold_locked=lambda k, r: False, row_is_rhymed=lambda k, r: False,
                   resort_may_drop=lambda *a, **k: False, airings_ghost_last=lambda k, o: list(o),
                   _SHELF={kind: rows})
        return rows

    def test_a_first_airing_anywhere_on_the_shelf_goes_before_a_replay(self):
        dice = self.dice()
        fresh = _round("c-new")
        self.shelf([_round("c-old", 1), fresh])
        self.assertIs(self.app.shelf_take("gallery"), fresh)
        self.assertEqual(dice.rolls("bank.reair"), [], "a first airing is never rolled")

    def test_a_replay_is_the_roulettes_and_rides_its_entry(self):
        dice = self.dice()
        old = _round("c-old", 1)
        rows = self.shelf([old])
        got = self.app.shelf_take("gallery")
        self.assertIs(got, old)
        self.assertEqual(len(dice.rolls("bank.reair")), 1)
        self.assertEqual(got["entry"]["_s3_replay"]["airing"], 2)
        self.assertEqual(got["aired"], 2, "the take itself counted the airing, as before")
        self.assertEqual(rows[-1], old, "kept at the back of the shelf, as before")

    def test_a_refused_replay_stays_on_the_shelf_untouched(self):
        dice = self.dice()
        dice.odds("bank.reair", 0.0)
        old = _round("c-old", 1)
        rows = self.shelf([old])
        self.assertIsNone(self.app.shelf_take("gallery"))
        self.assertEqual((rows, old["aired"]), ([old], 1))
        self.assertNotIn("_s3_replay", old["entry"])

    def test_a_peek_names_the_first_replay_without_rolling(self):
        dice = self.dice()
        old = _round("c-old", 1)
        self.shelf([old])
        self.assertIs(self.app.shelf_take("gallery", peek=True), old)
        out = []
        self.app.shelf_take("gallery", peek=True, reair_out=out)
        self.assertEqual(out, [old])
        self.assertEqual(dice.rolls("bank.reair"), [])

    def test_the_gate_skips_a_retired_replay_on_the_walk_dice_on_or_off(self):
        self.dice_off()
        broken, clean = _broken("b1"), _round("c1", 1)
        self.shelf([broken, clean])
        self.assertIs(self.app.shelf_take("gallery", peek=True), clean)
        self.assertIs(self.app.shelf_take("gallery"), clean)
        self.assertEqual(broken["aired"], 1, "the retired round was not taken")

    def test_a_first_airing_is_not_the_gates_question(self):
        self.dice()
        fresh = _broken("b-new", aired=0)
        self.shelf([fresh])
        self.assertIs(self.app.shelf_take("gallery"), fresh,
                      "the copy gate at the turn guards a first airing; this gate is the re-air's")

    def test_a_single_line_replay_carries_it_on_its_own_node(self):
        self.dice()
        line = {"at": time.time() - 600, "text": "Pine Box FM.", "aired": 1, "aired_at": time.time() - 5 * 3600,
                "system3": {"conversation_id": "id1", "mode": "active", "turn_id": "id1:t00"}}
        self.shelf([line], "station_id")
        got = self.app.shelf_take("station_id")
        self.assertEqual(got["system3"]["replay"]["airing"], 2)
        self.assertEqual(got["system3"]["turn_id"], "id1:t00")


class LarderGateTests(StationCase):
    def larder(self, entries):
        self.patch(_LARDER=entries, dialogue_row_ready=lambda k, e: True, _larder_current=lambda e: True,
                   larder_fresh=lambda: 3 * 3600.0, shelf_repeat_ready=lambda k, e: bool(e.get("aired_at")),
                   shelf_is_repeat=lambda k, e: bool(e.get("aired_at")))
        return entries

    def entry(self, cid, aired=0):
        e = dict(_round(cid, aired)["entry"], at=time.time() - 600)
        if aired:
            e.update(aired=aired, aired_at=time.time() - 4 * 3600)
        return e

    def test_a_first_airing_stands_without_a_roll(self):
        dice = self.dice()
        self.larder([self.entry("a"), self.entry("b", 1)])
        self.assertEqual(self.app.larder_reair_gate(0), (0, None))
        self.assertEqual(dice.rolls("bank.reair"), [])

    def test_a_replay_yields_to_a_first_airing_behind_it(self):
        dice = self.dice()
        self.larder([self.entry("b", 1), self.entry("a")])
        self.assertEqual(self.app.larder_reair_gate(0), (1, None))
        self.assertEqual(dice.rolls("bank.reair"), [])

    def test_dice_off_a_retired_replay_is_passed_over_for_the_next_the_serve_could_take(self):
        self.dice_off()
        broken = dict(self.entry("b", 1), script=BROKEN)
        clean = self.entry("c", 2)
        self.larder([broken, clean])
        self.assertEqual(self.app.larder_reair_gate(0), (1, None))
        self.larder([broken])
        self.assertEqual(self.app.larder_reair_gate(0), (-1, None))

    def test_dice_on_a_retired_replay_is_never_rolled_for(self):
        dice = self.dice()
        broken = dict(self.entry("b", 1), script=BROKEN)
        self.larder([broken])
        self.assertEqual(self.app.larder_reair_gate(0), (-1, None))
        self.assertEqual(dice.rolls("bank.reair"), [])

    def test_only_replays_the_roulette_decides(self):
        dice = self.dice()
        self.larder([self.entry("b", 1), self.entry("c", 2)])
        at, stamp = self.app.larder_reair_gate(0)
        self.assertIn(at, (0, 1))
        self.assertEqual(stamp["road"], "banter")
        dice.odds("bank.reair", 0.0)
        self.app._BANK_REAIR_MISS.clear()
        self.assertEqual(self.app.larder_reair_gate(0), (-1, None))


class CupboardDoorTests(StationCase):
    """_ready_shelf_air: every road through the cupboard's door."""

    def door(self, plain, first=None, replays=None):
        asked = []
        calls = []

        def row_of(kind, rescue=False, pick=None, reair_out=None):
            calls.append((pick, reair_out is not None))
            if reair_out is not None:
                reair_out.extend(replays or [])
                return first
            return pick if pick is not None else plain
        self.patch(_ready_shelf_row=row_of,
                   _ready_round_takes=lambda kind, row: (asked.append(row), [])[1],
                   _READY_SHELF_WHY={"at": 0.0, "kind": "", "why": ""})
        return asked, calls

    def test_the_operators_play_now_is_never_rolled_but_the_gate_refuses_a_retired_round(self):
        dice = self.dice()
        clean = _round("c1", 1)
        asked, _calls = self.door(clean)
        self.assertEqual(run(self.app._ready_shelf_air("gallery", None, rescue=True, pick=clean, named=True)), [])
        self.assertIs(asked[0], clean, "went on to its takes")
        self.assertEqual(dice.rolls("bank.reair"), [])
        broken = _broken("b1")
        asked, _calls = self.door(broken)
        self.assertEqual(run(self.app._ready_shelf_air("gallery", None, rescue=True, pick=broken, named=True)), [])
        self.assertEqual(asked, [], "refused before its takes")
        self.assertIn("re-air gate", self.app._READY_SHELF_WHY["why"])

    def test_a_round_another_road_named_rolls_on_its_own(self):
        dice = self.dice()
        dice.odds("bank.reair", 0.0)
        row = _round("c1", 1)
        asked, _calls = self.door(row)
        self.assertEqual(run(self.app._ready_shelf_air("gallery", None, rescue=True, pick=row)), [])
        self.assertEqual(asked, [])
        self.assertEqual(len(dice.rolls("bank.reair")), 1)

    def test_a_refused_replay_gives_way_to_the_first_airing_the_plot_passed_over(self):
        dice = self.dice()
        dice.odds("bank.reair", 0.0)
        replay, first = _round("in-plot", 1), _round("first-airing", 0)
        asked, calls = self.door(replay, first=first, replays=[replay])
        self.assertEqual(run(self.app._ready_shelf_air("gallery", None, rescue=True)), [])
        self.assertIs(asked[0], first, "heard for the first time: the bank's job, no roll")
        self.assertEqual(calls, [(None, False), (None, True)])

    def test_a_replay_the_roulette_lets_out_goes_with_its_stamp(self):
        self.dice()
        replay = _round("in-plot", 1)
        asked, _calls = self.door(replay, first=None, replays=[replay])
        run(self.app._ready_shelf_air("gallery", None, rescue=True))
        self.assertIs(asked[0], replay)

    def test_nothing_first_and_the_replays_refused_is_a_named_refusal(self):
        dice = self.dice()
        dice.odds("bank.reair", 0.0)
        replay = _round("r", 1)
        asked, _calls = self.door(replay, first=None, replays=[replay])
        self.assertEqual(run(self.app._ready_shelf_air("gallery", None, rescue=True)), [])
        self.assertEqual(asked, [])
        self.assertIn("bank.reair", self.app._READY_SHELF_WHY["why"])


class GoldTests(StationCase):
    def media(self):
        return Path(self.enterContext(tempfile.TemporaryDirectory()))

    def bank(self, bars, media=None):
        self.patch(_GOLD={"loaded": True, "rows": bars}, _gold_save=lambda: None,
                   VOICE_MEDIA_DIR=media or self.media(),
                   repeat_window=lambda: 0.0, rap_rhyme_evidence=lambda t: {"ok": True})

    def bar(self, key, src=True, fired=0, take=True, media=None):
        b = {"key": key, "who": "dj", "text": "bar " + key, "path": key + ".wav", "seconds": 5.0,
             "at": time.time() - 7200, "fired": fired, "last": 0.0}
        if src:
            b["source"] = {"conversation_id": "src-" + key, "turn_id": "src-%s:t00" % key}
        if take and media is not None:
            (media / (key + ".wav")).write_bytes(b"take")
        return b

    def test_a_bar_is_minted_with_its_system3_turn(self):
        self.bank([])
        src = {"conversation_id": "c9", "turn_id": "c9:t03", "mode": "active"}
        self.assertTrue(self.app.gold_note("dj", "a rhymed bar that aired", "/media/x.wav", 4.0, source=src))
        row = self.app._gold_rows()[-1]
        self.assertEqual(row["source"]["turn_id"], "c9:t03")
        self.app.gold_note("dj", "a rhymed bar that aired", "/media/y.wav", 4.0,
                           source={"conversation_id": "c10", "turn_id": "c10:t01"})
        self.assertEqual(len(self.app._gold_rows()), 1)
        self.assertEqual(self.app._gold_rows()[0]["source"]["conversation_id"], "c10")

    def test_only_system3_bars_fire_and_the_order_is_rolled(self):
        dice = self.dice()
        media = self.media()
        legacy = self.bar("legacy", src=False, media=media)
        gone = self.bar("gone", take=False, media=media)
        kept = self.bar("kept", media=media)
        self.bank([legacy, gone, kept], media)
        self.assertEqual(self.app.gold_source(legacy), {})
        # the first roll lands on the bar whose take is gone; the next is one more roll
        seen = []
        real = self.app._S3Dice.pick

        def pick(self_, label, cands):
            seen.append(list(cands))
            return cands.index("bar gone") if "bar gone" in cands else real(self_, label, cands)
        with mock.patch.object(self.app._S3Dice, "pick", pick):
            got = self.app.gold_pick()
        self.assertIs(got, kept, "the legacy bar never fires; the bar whose take is gone costs one more roll")
        self.assertEqual(seen, [["bar gone", "bar kept"], ["bar kept"]])
        self.assertEqual(len(dice.rolls("gold.pick")), 1, "the second roll is System 3's")

    def test_the_run_is_the_desks_and_each_bar_is_its_source_turns_node(self):
        dice = self.dice()
        media = self.media()
        bar = self.bar("one", media=media)
        self.bank([bar], media)
        self.patch(radio_paused=lambda: False, _RADIO={"on": True},
                   _PAGE_AIR_UNTIL=[0.0], media_sign=lambda n: "sig")
        said = []

        async def floor(kind, track, **kw):
            said.append(kw)
            return "said"
        self.patch(_dj_speak_floorless=floor)
        self.assertEqual(run(self.app.gold_fill_gap("a hole", floorless=True, ahead=4.0)), "bar")
        stamp = said[0]["system3"]
        self.assertEqual((stamp["conversation_id"], stamp["turn_id"], stamp["mode"]),
                         ("src-one", "src-one:t00", "active"))
        self.assertEqual(stamp["gold"]["run"]["key"], "gold.run")
        self.assertEqual(stamp["gold"]["pick"]["key"], "gold.pick")
        keys = sorted(o["key"] for o in dice.on_round("src-one"))
        self.assertEqual(keys, ["gold.pick", "gold.run"])

    def test_a_refused_run_lays_nothing(self):
        dice = self.dice()
        dice.odds("gold.run", 0.0)
        media = self.media()
        self.bank([self.bar("one", media=media)], media)
        self.patch(radio_paused=lambda: False, _RADIO={"on": True},
                   _PAGE_AIR_UNTIL=[0.0], media_sign=lambda n: "sig")
        called = []

        async def floor(kind, track, **kw):
            called.append(kw)
            return "said"
        self.patch(_dj_speak_floorless=floor)
        self.assertEqual(run(self.app.gold_fill_gap("a hole", floorless=True, ahead=4.0)), "")
        self.assertEqual(called, [])
        self.assertEqual(len(dice.rolls("gold.run")), 1)
        self.assertEqual(run(self.app.gold_fill_gap("a hole", floorless=True, ahead=4.0)), "")
        self.assertEqual(len(dice.rolls("gold.run")), 1, "the refusal rests the road")


class ListeningSeamTests(StationCase):
    META = {"script": "A: the long turn about the fire at the warehouse tonight\nB: answer",
            "system3": {"conversation_id": "r1", "mode": "active", "turns": {"0": "r1:t00", "1": "r1:t01"}}}

    def responses(self):
        take = mock.Mock(side_effect=lambda voice, engine, context, used, crystal="", chooser=None: (
            None if chooser is not None and chooser([{"text": "Mm-hmm."}, {"text": "Go on."}]) < 0
            else {"text": "Go on.", "clip": {"path": "/media/g.wav"}}))
        self.patch(_RESPONSES=mock.Mock(take=take), voice_engine_for=lambda v: "e",
                   continuity_crystal=lambda: "")
        return take

    def test_dice_off_the_bank_takes_as_before(self):
        self.dice_off()
        take = self.responses()
        got = self.app.listening_seam_take("cohost", "the long turn", set(), {"cohost": "v"}, self.META)
        self.assertEqual(got["text"], "Go on.")
        self.assertNotIn("chooser", take.call_args.kwargs)

    def test_a_missed_seam_airs_nothing_and_is_on_the_round(self):
        dice = self.dice()
        dice.odds("listen.seam", 0.0)
        self.responses()
        self.assertIsNone(self.app.listening_seam_take(
            "cohost", "the long turn about the fire at the warehouse tonight", set(), {"cohost": "v"}, self.META))
        obs = dice.on_round("r1")
        self.assertEqual([(o["key"], o["hit"], o["turn_id"]) for o in obs], [("listen.seam", False, "r1:t00")])

    def test_a_response_is_rolled_and_stamped_to_the_turn_it_answers(self):
        dice = self.dice()
        self.responses()
        got = self.app.listening_seam_take(
            "cohost", "the long turn about the fire at the warehouse tonight", set(), {"cohost": "v"}, self.META)
        stamp = got["system3"]
        self.assertEqual((stamp["conversation_id"], stamp["turn_id"]), ("r1", "r1:t00"))
        self.assertEqual(stamp["listening"]["seam"]["key"], "listen.seam")
        self.assertEqual(stamp["listening"]["pick"]["key"], "listen.pick")
        self.assertEqual(self.app._S3_AIR_OWN[got["line_id"]], stamp)
        self.assertEqual(sorted(o["key"] for o in dice.on_round("r1")), ["listen.pick", "listen.seam"])


class AirRowsTests(StationCase):
    def test_own_nodes_and_the_replay_ride_the_rounds_ledger_rows(self):
        self.app._S3_AIR_OWN["L-seam"] = {"conversation_id": "r1", "turn_id": "r1:t00", "listening": {"x": 1}}
        rep = {"at": time.time(), "label": "replay, first aired 07:14, airing 2"}
        rows = [{"line_id": "L1", "who": "dj", "system3": {"conversation_id": "r1", "turn_id": "r1:t00"}},
                {"line_id": "L-seam", "who": "cohost", "dice": {"s3": {"turn_id": "r1:t05"}},
                 "system3": {"conversation_id": "r1", "turn_id": ""}},
                {"line_id": "B1", "who": "board", "system3": {"conversation_id": "r1", "turn_id": ""}},
                {"line_id": "S1", "who": "drop", "system3": {"conversation_id": "r1", "turn_id": "r1:t00"}}]
        self.app._s3_air_rows(rows, {"_s3_replay": rep})
        self.assertEqual(rows[0]["system3"]["replay"]["label"], rep["label"])
        self.assertEqual(rows[1]["system3"]["listening"], {"x": 1})
        self.assertNotIn("dice", rows[1], "a turn's dice by position are not the response's")
        self.assertNotIn("replay", rows[2]["system3"])
        self.assertNotIn("replay", rows[3]["system3"])

    def test_a_stale_replay_is_not_carried(self):
        rows = [{"line_id": "L1", "who": "dj", "system3": {"conversation_id": "r1", "turn_id": "r1:t00"}}]
        self.app._s3_air_rows(rows, {"_s3_replay": {"at": time.time() - 7200, "label": "old"}})
        self.assertNotIn("replay", rows[0]["system3"])


class RerunAndContinuityTests(StationCase):
    def test_a_finished_call_finds_its_system3_round_by_its_words(self):
        at = time.time() - 8 * 3600
        ledger = [{"at": at - 7200, "text": "The request line is ringing, you're live, go ahead.",
                   "system3": {"conversation_id": "call0", "turn_id": "call0:t00"}},
                  {"at": at, "text": "The request line is ringing, you're live, go ahead.",
                   "system3": {"conversation_id": "call1", "turn_id": "call1:t00"}},
                  {"at": at + 1, "text": "Hi, this is Salta, calling about the cat in the sewer.",
                   "system3": {"conversation_id": "call1", "turn_id": "call1:t01"}},
                  {"at": at + 2, "text": "Salta, good to have you. What made you call?",
                   "system3": {"conversation_id": "call1", "turn_id": "call1:t02"}}]
        self.patch(script_ledger_rows=lambda: list(ledger))
        row = {"id": "abc", "ts": at + 600, "transcript": [{"text": r["text"]} for r in ledger[1:]]}
        got = self.app.rerun_s3_source(row)
        self.assertEqual(got["conversation_id"], "call1")
        self.assertEqual(got["turns"][self.app._rerun_norm(ledger[1]["text"])], "call1:t00",
                         "the stock greeting belongs to every call; the call's own round wins the vote")
        self.assertEqual(self.app.rerun_row_s3(dict(got, replay={"label": "r"}), {"text": ledger[2]["text"]})["turn_id"],
                         "call1:t01")
        self.assertEqual(self.app.rerun_s3_source({"id": "zzz", "ts": at,
                                                   "transcript": [{"text": "nothing anybody said on air"}]}), {})

    def test_the_emergency_hosts_pair_is_a_roll_and_a_line_draw(self):
        dice = self.dice()
        pairs = (("first line of pair one", "second line of pair one"),
                 ("first line of pair two", "second line of pair two"))
        handle = mock.Mock(active=True, choice=1, stamp={"conversation_id": "n1", "mode": "active",
                                                         "turn_id": "n1:t00", "road": "interject"})

        async def direct(**ctx):
            self.assertEqual(len(ctx["candidates"]), 2)
            return handle
        self.patch(CONTINUITY_PAIRS=pairs, continuity_pick=lambda who, voice, text: {"who": who, "text": text},
                   _CONTINUITY_STATE={}, dj_settings=lambda: {})
        self.stack.enter_context(mock.patch.dict(self.app.__dict__, {
            "system3_direct_line": direct, "system3_bind_line": lambda h, t: None}))
        picks, resting, stamp = run(self.app.continuity_roulette({"dj": "v", "cohost": "w"}, {}))
        self.assertEqual([p["text"] for p in picks], list(pairs[1]))
        self.assertEqual((resting, stamp["conversation_id"]), (0, "n1"))
        self.assertEqual(stamp["replay"]["pick"], {"kind": "line", "index": 2, "of": 2})
        self.assertEqual(len(dice.rolls("bank.reair")), 1)
        dice.odds("bank.reair", 0.0)
        self.app._BANK_REAIR_MISS.clear()
        self.assertEqual(run(self.app.continuity_roulette({"dj": "v", "cohost": "w"}, {})), ([], 0, None))


if __name__ == "__main__":
    unittest.main()
