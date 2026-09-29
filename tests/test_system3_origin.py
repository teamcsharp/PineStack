"""[s3-account] The origin ledger (system3_origin.py), pure: every aired item
gets ONE record - rolled (a System 3 node with its tables and dice), forced (a
named forced node: road + trigger, never dice) or rogue (the code path that
aired it, on the Untraced list) - kept 7 days in full, then compacted forever.
No app import; temp files only."""
import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

import system3_origin as so

NOW = 1790650000.0


def pack(v):
    return zlib.compress(json.dumps(v).encode("utf-8"))


def fake_system3(path):
    """A System 3 store with one conversation: a turn with an ES and an SFX
    decision, a round-level TOPIC roll, an SFX Guy observation and an INJECT."""
    db = sqlite3.connect(str(path))
    db.executescript("""CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
        seq INTEGER, kind TEXT NOT NULL, family TEXT, turn_id TEXT, at REAL NOT NULL, body BLOB NOT NULL);
        CREATE INDEX events_conv ON events(conversation_id, id);""")

    def dec(seq, fam, tid, label, dice, of=None):
        body = {"event_id": "c1:%04d" % seq, "family": fam, "turn_id": tid,
                "stages": [{"stage": "item", "selected": label, "selected_index": 2, "of": of or 5}],
                "rng": {"u": dice / 100.0, "dice": dice}, "selected": {"id": label, "label": label}}
        db.execute("INSERT INTO events(conversation_id,seq,kind,family,turn_id,at,body) VALUES(?,?,?,?,?,?,?)",
                   ("c1", seq, "decision", fam, tid, NOW, pack(body)))
    dec(1, "TOPIC", "", "RAISE", 12)
    dec(2, "ES", "c1:t00", "delight", 44)
    dec(3, "SFX", "c1:t00", "PLAY", 7)
    for fam, tid, body in (("SFXGUY", "c1:t00", {"family": "SFXGUY", "line": "We sold our innocence.", "kind": "quip",
                                                 "draws": [{"pool": "quip", "of": 40, "index": 3, "dice": 8,
                                                            "store": {"kind": "sfx guy quip shelf",
                                                                      "db": "sfxguy_quips/vl_x.json"}}]}),
                           ("INJECT", "", {"family": "INJECT", "by": "the dead-air rescue", "why": "silence 40 s",
                                           "line_id": "inj1"})):
        db.execute("INSERT INTO events(conversation_id,seq,kind,family,turn_id,at,body) VALUES(?,?,?,?,?,?,?)",
                   ("c1", None, "observation", fam, tid, NOW, pack(body)))
    db.commit()
    db.close()


def row(lid, **kw):
    out = {"id": lid, "ts": int(NOW), "air_at": NOW, "who": "dj", "kind": "call", "round": "banter",
           "text": "a line", "aired": "stream"}
    out.update(kw)
    return out


class Build(unittest.TestCase):
    def test_rolled_line_names_its_tables_and_dice(self):
        conv = {"exists": True, "any": 3,
                "turn": [{"event_id": "c1:0002", "family": "ES", "rng": {"dice": 44, "u": 0.44},
                          "selected": {"label": "delight"},
                          "stages": [{"selected": "ES1"}, {"selected": "delight", "selected_index": 3, "of": 9}]}],
                "round": [], "observations": []}
        rec = so.build(row("l1"), {"block": 7, "ord": 2, "sid": "s1"},
                       {"conversation_id": "c1", "turn_id": "c1:t00"}, conv)
        c = rec["compact"]
        self.assertEqual(c["verdict"], "rolled")
        self.assertEqual(c["script"]["block"], 7)
        self.assertEqual(c["system3"]["decisions"], ["c1:0002"])
        es = [t for t in rec["turn"]["compact"] if t.get("table") == "ES"][0]
        self.assertEqual((es["dice"], es["picked"], es["of"]), (44, "delight", 9))
        self.assertIn("ES1 > delight", es["path"])
        self.assertEqual(c["system3"]["turn_key"], "c1|c1:t00")
        self.assertEqual(rec["turn"]["full"]["decisions"][0]["event_id"], "c1:0002")   # kept once per turn

    def test_board_clip_rolled_by_its_own_dice_and_named_store(self):
        sfx = {"road": "book", "category": {"label": "vine", "dice": 37, "of": 34, "index": 13},
               "clip": {"label": "92 did you", "dice": 40, "of": 489, "index": 194}}
        rec = so.build(row("b1", who="board", kind="sfx", text="\U0001f50a 92 did you", sfx_roll=sfx,
                           sfx_dir="vine", sfx="abc123"))
        c = rec["compact"]
        self.assertEqual((c["road"], c["verdict"]), ("board clip", "rolled"))
        st = c["store"][0]
        self.assertEqual((st["kind"], st["folder"], st["pool"], st["index"], st["of"]),
                         ("sfx library", "vine", "book", 194, 489))
        self.assertEqual(st["file"], "92 did you")

    def test_gold_is_a_forced_node_with_its_gap_and_no_fake_dice(self):
        stamp = {"conversation_id": "g1", "turn_id": "g1:t03",
                 "gold": {"bar": "85d0", "label": "gold bar minted 14:51", "firing": 2,
                          "run": {"key": "gold.run", "dice": 63, "odds": 1.0},
                          "pick": {"key": "gold.pick", "dice": 27, "index": 1, "of": 4, "picked": "Drag..."}}}
        rec = so.build(row("g", kind="interject", round="gold"), None, stamp, {"exists": True, "any": 5},
                       {"gold_why": {"why": "exchange 4798c4e9 was pending", "at": NOW - 5}})
        c = rec["compact"]
        self.assertEqual((c["road"], c["verdict"]), ("gold", "forced"))
        self.assertIn("exchange 4798c4e9 was pending", c["forced"]["trigger"])
        self.assertEqual([s["kind"] for s in c["store"]][:1], ["gold bars"])
        # the real roll (which bar) is listed; the verdict is not dressed as a roll
        self.assertTrue(any(t["table"] == "gold.pick" for t in c["tables"]))
        inr = dict(stamp, gold=dict(stamp["gold"], run={"key": "gold.in_round", "dice": 3}))
        c2 = so.build(row("g2", kind="interject", round="gold"), None, inr, {})["compact"]
        self.assertIn("inside the round", c2["forced"]["trigger"])

    def test_emergency_pair_and_operator_taps_are_forced(self):
        c = so.build(row("e", kind="emergency_host", emergency=True,
                         emergency_reason="talk quiet 62 s"))["compact"]
        self.assertEqual((c["verdict"], c["forced"]["road"]), ("forced", "emergency_host"))
        self.assertIn("talk quiet 62 s", c["forced"]["trigger"])
        rep = so.build(row("r", replay=True, replay_of="abc"))["compact"]
        self.assertEqual((rep["road"], rep["verdict"], rep["of"]), ("operator replay", "forced", "abc"))
        sent = so.build(row("s", origin_path="ad_booth_row<gen_ads_broadcast<run"))["compact"]
        self.assertEqual((sent["verdict"], sent["forced"]["by"]), ("forced", "gen_ads_broadcast"))
        desk = so.build(row("d", who="board", kind="sfx", sfx_dir="the desk", aired="",
                            text="☎ the phone ringing"))["compact"]
        self.assertEqual((desk["verdict"], desk["forced"]["road"]), ("forced", "desk"))

    def test_rogue_names_its_code_path_and_producer(self):
        c = so.build(row("x", kind="ad", text="\U0001f4e3 the original painting",
                         origin_path="ad_booth_row<_air_produced_ad<run"))["compact"]
        self.assertEqual(c["verdict"], "rogue")
        self.assertEqual(c["rogue"]["producer"], "_air_produced_ad")
        self.assertEqual(c["rogue"]["path"], "ad_booth_row<_air_produced_ad<run")
        self.assertEqual(c["why"], "no System 3 stamp")

    def test_spin_roll_or_forced_note(self):
        rolled = so.build({"id": "rec:1", "kind": "record", "who": "deck", "aired": "published", "air_at": NOW,
                           "text": "Song - Band", "track_id": "t1",
                           "s3_spin": {"lane": "rotation", "deal": {"key": "records.deal", "dice": 12}}})["compact"]
        self.assertEqual((rolled["road"], rolled["verdict"]), ("record", "rolled"))
        live = so.build({"id": "rec:2", "kind": "record", "who": "deck", "aired": "published", "air_at": NOW,
                         "s3_spin": {"lane": "live", "forced": True, "why": "MX Live owns the air"}})["compact"]
        self.assertEqual((live["verdict"], live["forced"]["road"]), ("forced", "records: live"))

    def test_ad_line_names_the_product_store(self):
        c = so.build(row("a", round="ad"), None, {"conversation_id": "c9"}, {"exists": True, "any": 2},
                     {"ad_now": {"product": "The Harbour Oil", "at": NOW - 30}})["compact"]
        ad = [s for s in c["store"] if s["kind"] == "ad book"][0]
        self.assertEqual(ad["product"], "The Harbour Oil")

    def test_a_matched_clip_keeps_the_matchers_working(self):
        pick = {"at": NOW - 2, "road": "sting", "clip": "73 Her fury grew", "line": "she was furious at him",
                "line_source": "the line it follows", "why": "matched 'fury'", "score": 2.28, "cands": 64,
                "tied": 3, "eligible": 2, "removed": {"banned": 1, "just heard": 0},
                "words": {"line": ["fury"], "context": [], "senses": ["rage"], "folder": []},
                "candidates": [{"rowid": 9, "folder": "adamcurtis", "score": 2.28, "line": ["fury"]}]}
        rec = so.build(row("mc", who="board", kind="sfx", sfx="c255", text="73 Her fury grew",
                           sfx_dir="adamcurtis"), context={"match_picks": {"c255": pick}})
        m = [s for s in rec["compact"]["store"] if s["kind"] == "sfx matcher"][0]
        self.assertEqual((m["line"], m["why"], m["tied"], m["eligible"]),
                         ("she was furious at him", "matched 'fury'", 3, 2))
        self.assertEqual(m["removed"], {"banned": 1})
        self.assertEqual(m["words"], {"line": ["fury"], "senses": ["rage"]})
        self.assertEqual(rec["full"]["match"]["candidates"][0]["score"], 2.28)     # full: 7 days
        stale = so.build(row("mc2", who="board", kind="sfx", sfx="c255", air_at=NOW + 3600),
                         context={"match_picks": {"c255": pick}})
        self.assertFalse([s for s in stale["compact"]["store"] if s["kind"] == "sfx matcher"])

    def test_not_yet_aired_rows_are_not_items(self):
        self.assertFalse(so.eligible(row("p", aired="prepared")))
        self.assertFalse(so.eligible(row("c", kind="chat", aired="stream")))
        self.assertTrue(so.eligible(row("m", who="host", kind="call", aired="")))
        self.assertTrue(so.eligible(row("h", aired="", heard_ack_at=NOW)))


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        fake_system3(d / "system3.sqlite3")
        self.led = so.OriginLedger(d / "origin.sqlite3", d / "reports", d / "system3.sqlite3")

    def tearDown(self):
        self.led.close()
        self.tmp.cleanup()

    def test_nothing_is_opened_until_used(self):
        fresh = so.OriginLedger(Path(self.tmp.name) / "sub" / "o.sqlite3")
        self.assertFalse((Path(self.tmp.name) / "sub").exists())
        fresh.counts()
        self.assertTrue((Path(self.tmp.name) / "sub" / "o.sqlite3").exists())
        fresh.close()

    def test_tick_joins_ledger_and_system3_and_settles(self):
        self.led.ledger_note(41, NOW, "s1", "banter", {"id": "seg-1"},
                             [{"line_id": "l1", "turn": 0,
                               "system3": {"conversation_id": "c1", "turn_id": "c1:t00"}}])
        out = self.led.tick([row("l1"), row("q1", aired="prepared")], now=NOW + 1)
        self.assertEqual(out["written"], 1)
        rec = self.led.get("l1", full=True)
        self.assertEqual((rec["verdict"], rec["script"]["block"], rec["script"]["segment"]),
                         ("rolled", 41, "seg-1"))
        self.assertTrue(rec["settled"])
        self.assertEqual(sorted(rec["system3"]["decisions"]), ["c1:0002", "c1:0003"])
        self.assertEqual([d["table"] for d in rec["conversation_decisions"]], ["TOPIC"])
        self.assertEqual(sorted(d["table"] for d in rec["turn_decisions"]), ["ES", "SFX"])
        self.assertEqual(len(rec["full"]["turn"]["decisions"]), 2)
        self.assertEqual([o["family"] for o in rec["full"]["conversation"]["observations"]], ["INJECT"])
        self.assertIn("full", rec["retention"])
        ch = self.led.chain("l1")
        self.assertEqual(sorted(n.get("scope") for n in ch["nodes"] if n["node"] == "roll"),
                         ["round", "turn", "turn"])
        # a final record is not rebuilt again
        self.assertEqual(self.led.tick([row("l1")], now=NOW + 2)["seen"], 0)

    def test_rogue_waits_for_its_ledger_row_then_alarms(self):
        r = row("x1", origin_path="_dj_upstairs_page_floorless<run")
        self.led.tick([r], now=NOW + 5)
        self.assertEqual(self.led.untraced(NOW - 10)["count"], 0)       # not settled: may still be stamped
        self.led.tick([r], now=NOW + so.SETTLE_S + 20)
        got = self.led.untraced(NOW - 10)
        self.assertEqual(got["count"], 1)
        self.assertEqual(got["items"][0]["producer"], "_dj_upstairs_page_floorless")
        self.assertEqual(got["by_path"][0]["count"], 1)

    def test_a_late_stamp_rescues_a_row_before_it_settles(self):
        self.led.tick([row("x2")], now=NOW + 5)
        self.led.ledger_note(42, NOW, "", "", None, [{"line_id": "x2",
                             "system3": {"conversation_id": "c1", "turn_id": "c1:t00"}}])
        self.led.tick([row("x2")], now=NOW + 6)
        self.assertEqual(self.led.get("x2")["verdict"], "rolled")

    def test_sfx_guy_quip_names_its_shelf_and_injected_line_is_forced(self):
        guy = row("q", who="drop", kind="sfxguy", text="We sold our innocence.",
                  system3={"conversation_id": "c1", "turn_id": "c1:t00", "sfxguy": True})
        inj = row("inj1", system3={"conversation_id": "c1", "turn_id": ""})
        self.led.tick([guy, inj], now=NOW + so.SETTLE_S + 1)
        st = self.led.get("q")["store"][0]
        self.assertEqual((st["kind"], st["db"], st["of"]), ("sfx guy quip shelf", "sfxguy_quips/vl_x.json", 40))
        f = self.led.get("inj1")
        self.assertEqual((f["verdict"], f["forced"]["by"]), ("forced", "the dead-air rescue"))

    def test_a_welded_clip_is_part_of_its_line(self):
        gold = row("g1", kind="interject", round="gold",
                   system3={"conversation_id": "c1", "turn_id": "c1:t00", "gold": {"bar": "b"}})
        clip = row("g1-punct-1", who="board", kind="sfx", text="\U0001f50a 12 clip")
        self.led.tick([clip, gold], now=NOW + so.SETTLE_S + 1)       # the clip first in the ring
        c = self.led.get("g1-punct-1")
        self.assertEqual((c["verdict"], c["forced"]["road"]), ("forced", "gold"))
        self.assertIn("punctuates", c["forced"]["how"])

    def test_labels_link_to_the_road_they_announce(self):
        marker = row("m1", who="host", kind="call", aired="", text="On line 8,103: Bernice")
        self.led.tick([marker], now=NOW + 1)
        self.assertEqual(self.led.untraced(NOW - 10)["count"], 0)
        call = row("c1l", round="caller", air_at=NOW + 30,
                   system3={"conversation_id": "c1", "turn_id": "c1:t00"})
        self.led.tick([marker, call], now=NOW + 40)
        m = self.led.get("m1")
        self.assertEqual((m["verdict"], m["announces"]), ("rolled", "c1l"))
        self.assertEqual(m["store"][0]["kind"], "call line")
        # a listing written AFTER its spot links back to the spot's lines
        spot = row("sp1", round="ad", air_at=NOW + 100,
                   system3={"conversation_id": "c1", "turn_id": "c1:t00"})
        listing = row("li1", kind="ad", round="ad", air_at=NOW + 130,
                      text="\U0001f4e3 sponsor spot — OLLAMA", product="OLLAMA")
        self.led.tick([spot, listing], now=NOW + 140)
        li = self.led.get("li1")
        self.assertEqual((li["verdict"], li["announces"]), ("rolled", "sp1"))
        # a marker whose road never airs is an honest forced desk label
        lone = row("m2", who="host", kind="news", aired="", text="News break: x", air_at=NOW + 200)
        self.led.tick([lone], now=NOW + 200 + so.MARKER_LINK_S + 1)
        self.assertEqual((self.led.get("m2")["verdict"], self.led.get("m2")["forced"]["road"]),
                         ("forced", "desk label"))

    def test_side_items_and_chain(self):
        self.led.side_note({"id": "pol:1", "kind": "megaphone", "who": "outside", "aired": "published",
                            "text": "someone outside", "air_at": NOW,
                            "origin_forced": {"road": "operator", "trigger": "the megaphone", "by": "dj_police_outside"}})
        self.led.tick([], now=NOW + 1)
        ch = self.led.chain("pol:1")
        self.assertEqual(ch["verdict"], "forced")
        self.assertEqual([n["node"] for n in ch["nodes"]][:2], ["air", "road"])
        self.assertEqual(ch["nodes"][-1]["node"], "forced")
        self.assertIsNone(self.led.chain("nope"))

    def test_records_and_live_sets_have_an_origin_key(self):
        for item in ({"id": "rec:t1:100", "kind": "record", "who": "deck", "aired": "published", "air_at": 100.0,
                      "track_id": "t1", "s3_spin": {"lane": "rotation", "roll": {"key": "records.x", "dice": 5}}},
                     {"id": "rec:t1:900", "kind": "record", "who": "deck", "aired": "published", "air_at": 900.0,
                      "track_id": "t1", "s3_spin": {"lane": "request", "forced": True, "why": "a FIFO request"}},
                     {"id": "live:ev1:abc:500", "kind": "record", "who": "deck", "aired": "published",
                      "air_at": 500.0, "track_id": "abc", "event_id": "ev1",
                      "s3_spin": {"lane": "live", "forced": True, "why": "MX Live owns the air"}}):
            self.led.side_note(item)
        self.led.tick([], now=2000.0)
        self.assertEqual(self.led.find_record(track="t1")["line_id"], "rec:t1:900")        # the latest
        self.assertEqual(self.led.find_record(track="t1", at=150)["line_id"], "rec:t1:100")
        self.assertEqual(self.led.find_record(track="t1", at=150)["verdict"], "rolled")
        live = self.led.find_record(event="ev1")
        self.assertEqual((live["line_id"], live["verdict"]), ("live:ev1:abc:500", "forced"))
        self.assertIsNone(self.led.find_record(track="nope"))

    def test_seven_days_full_then_compacted_forever_and_daily_reports(self):
        old = NOW - 8 * 86400
        self.led.tick([row("old1", air_at=old, origin_path="x<y"),
                       row("old2", air_at=old + 60, kind="emergency_host")], now=old + 10 * 60)
        self.led.tick([row("new1", air_at=NOW, kind="emergency_host")], now=NOW + so.SETTLE_S + 1)
        self.assertIsNotNone(self.led.get("old1", full=True)["full"])
        out = self.led.housekeeping(now=NOW + 120)
        self.assertEqual(out["compacted"], 2)
        o = self.led.get("old1", full=True)
        self.assertIsNone(o["full"])
        self.assertIn("compacted", o["retention"])
        self.assertEqual((o["verdict"], o["rogue"]["path"]), ("rogue", "x<y"))    # ids and paths stay
        self.assertIsNotNone(self.led.get("new1", full=True)["full"])
        day = so.day_of(old)
        rep = self.led.report(day)
        self.assertEqual(rep["totals"]["items"], 2)
        self.assertEqual(rep["totals"]["traced_pct"], 50.0)
        self.assertEqual(rep["worst_untraced"][0]["producer"], "x")
        self.assertTrue((Path(self.tmp.name) / "reports" / (day + ".json")).exists())
        self.assertIn(day, [r["day"] for r in self.led.reports()])
        self.assertIsNone(self.led.report(so.day_of(NOW)))                         # today is not finished
        self.assertEqual(self.led.housekeeping(now=NOW + 120)["reports"], 0)          # kept, not remade

    def test_coverage_by_road(self):
        rep = so.coverage_report([("board clip", "rolled", 8), ("board clip", "rogue", 2),
                                  ("gold", "forced", 5)], [("dj_sting", "board clip", "no System 3 stamp", 2)],
                                 [("gold", "forced: gold", 5)], 0, 1)
        self.assertEqual(rep["totals"], {"items": 15, "rolled": 8, "forced": 5, "rogue": 2, "traced_pct": 86.67})
        self.assertEqual(rep["roads"][0]["road"], "board clip")                      # worst first
        self.assertEqual(rep["roads"][0]["traced_pct"], 80.0)


class Install(unittest.TestCase):
    def test_install_wires_hooks_and_routes_without_opening_anything(self):
        try:
            import importlib
            importlib.import_module("fastapi")
        except ImportError:
            self.skipTest("fastapi not installed")

        class FakeApp:
            def __init__(self):
                self.routes = {}

            def get(self, path, **_kw):
                def deco(fn):
                    self.routes[path] = fn
                    return fn
                return deco
        with tempfile.TemporaryDirectory() as d:
            ns = {"data_path": lambda n: Path(d) / n, "require_read_auth": lambda a: None,
                  "_RADIO": {"ad_now": {}}, "_S3_LINE_BY_ID": {}, "_ORIGIN_GOLD_WHY": {"why": "", "at": 0}}
            app = FakeApp()
            led = so.install(app, ns)
            self.assertFalse((Path(d) / "system3_origin.sqlite3").exists())
            for hook in ("origin_keeper_tick", "origin_housekeeping", "origin_ledger_note",
                         "origin_side_note", "origin_lookup"):
                self.assertTrue(callable(ns[hook]), hook)
            self.assertEqual(sorted(app.routes), ["/api/system3/coverage", "/api/system3/origin-of",
                                                  "/api/system3/origin/{line_id}",
                                                  "/api/system3/untraced", "/system3-coverage"])
            ns["origin_keeper_tick"]([row("z1", kind="emergency_host")])
            self.assertEqual(led.get("z1")["verdict"], "forced")
            ns["origin_ledger_note"](1, NOW, "", "", None, [{"line_id": None}])   # never raises
            page = __import__("asyncio").run(app.routes["/system3-coverage"]())
            self.assertIn(b"System 3 coverage", page.body)
            self.assertNotIn(b"__SERVER_KEY__", page.body)
            led.close()


if __name__ == "__main__":
    unittest.main()
