"""[s3-chain] app.py's prepared shelf: every line road's source airs only with
its complete System 3 exchange (>= 3 turns, >= 2 voices, one sid, every planned
turn, each row its own stamp), under one floor, or it WAITS on the shelf and the
keeper airs it whole. Imports app (run in the container). Nothing touches the
station's data dir or renders a voice: the shelf is a temp file, every take is a
temp file, every door that would speak is a recorder.

Cases (handoff step 4): a produced ad_spot with a 166-second fixed opener, two
produced spots at once (no interleave), a short station ID through the REAL
_dj_speak_floorless, a manager page, a pause mid-exchange (resumed), a writer
that returns stock replies (waits, then the keeper airs it whole), a road whose
graph is off (airs alone), and a round's chunk (names its own turn, no chapter).
"""
import ast
import asyncio
import importlib.util
import inspect
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app

ROOT = Path(app.__file__).resolve().parent
OPENER_AD = ("Pine Box paintings are on sale tonight: the harbour oil, the red barn, "
             "every canvas signed, ninety dollars, call the gallery line.")
SHEET = ("\n 1  A  - the spot plays as recorded. [Say it plainly.]\n"
         " 2  B  - Reacts to the line just aired. [Say it in discouragement, mildly. Write Skip's message "
         "with discouragement, reflecting the mood.]\n"
         " 3  D  - Answers the reaction before it. [Say it in skepticism. Write Third seat's message with "
         "skepticism, reflecting the mood.]\n"
         " 4  A  - Answers the replies to their opening point. [Say it in disbelief.]\n"
         " 5  B  - Lands it in one line and hands back to the show. [Say it in fascination.]\n")
GOOD = ["B: Ninety dollars for the harbour oil? That canvas is worth twice that, Dill.",
        "D: Twice that? The harbour oil has a crack in the corner, Skip, I saw the canvas.",
        "A: A crack is character, and the canvas is signed, so the harbour oil sells tonight.",
        "B: Then call the gallery line before the harbour oil is gone."]
STOCK = ["B: I don't know if that's right.",
         "D: Well, it is what it is, I suppose.",
         "A: So you're saying the painting is worth one hundred dollars.",
         "B: That's just how it is."]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeChapter:
    """The runtime's line_chapter contract (system3_runtime.line_chapter)."""

    def __init__(self):
        self.plans, self.states, self.n = {}, [], 0

    def plan(self, road="ad_spot", seats=("A", "B", "D", "A", "B"), chapter=True):
        self.n += 1
        cid = "%012dcafe" % self.n
        roles = {"A": "dj", "B": "cohost", "D": "third", "C": "manager"}
        names = {"A": "Dill", "B": "Skip", "D": "Sam", "C": "Marge"}
        self.plans[cid] = {"chapter": chapter, "road": road, "sheet": SHEET.replace(" 1  A", " 1  %s" % seats[0]),
                           "turns": len(seats), "seats": list(seats), "roles": roles, "names": names,
                           "turn_ids": ["%s:t%02d" % (cid, i) for i in range(len(seats))],
                           "seconds": [0.0] + [6.0] * (len(seats) - 1), "estimated_seconds": 30.0}
        return {"conversation_id": cid, "mode": "active", "turn_id": cid + ":t00", "road": road}

    def __call__(self, stamp, written=None):
        p = self.plans.get(str((stamp or {}).get("conversation_id") or ""))
        if p is None:
            return None
        if written is None:
            return dict(p) if p["chapter"] else {"chapter": False, "road": p["road"], "turns": p["turns"]}
        if not p["chapter"] or len(written) != p["turns"] or len({m for m, _s in written}) < 2:
            return None
        return [{"who": p["roles"][m], "name": p["names"][m], "text": s,
                 "stamp": dict(stamp, turn_id=p["turn_ids"][i], chapter_turn=i, chapter_of=p["turns"])}
                for i, (m, s) in enumerate(written)]

    def state(self, stamp, state, why="", extra=None):
        self.states.append((stamp.get("conversation_id"), state, why))


class Harness(unittest.TestCase):
    """Stand-ins for the station around the shelf; subclasses add the road."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "media").mkdir()
        self.chapter = FakeChapter()
        self.replies = list(GOOD)
        self.aired = []          # (who, text, sid, turn_id) in air order
        self.floor = {"held": 0, "takes": 0}
        self.radio = {"on": True, "voice_to": "here", "reply_to": "here", "chat": [], "now": None}
        self.renders = 0
        self.heard = set()           # line ids with a heard receipt
        self.repair_ok = True        # the repair writer answers properly
        self.prompts = []
        patches = {
            "system3_line_chapter": self.chapter, "system3_line_chapter_state": self.chapter.state,
            "system3_direct_line": self.direct, "_banter_beats": self.beats,
            "_s3_split_render": self.render, "s3_chapter_shelf_path": lambda: self.dir / "shelf.json",
            "VOICE_MEDIA_DIR": self.dir / "media", "pipeline_log": lambda *a, **k: None,
            "_ready_slot_window": lambda kind: None, "segment_overrun": lambda d, r="": 45.0,
            "radio_paused": lambda: False, "_RADIO": self.radio, "line_forgotten": lambda t: False,
            "_system2_repeat_rows_async": mock.AsyncMock(return_value=True),
            "session_voices": mock.AsyncMock(return_value={"dj": "v-dj", "cohost": "v-co", "third": "v-3"}),
            "configured_radio_voice": lambda who, v="": v or who, "dj_settings": lambda: {},
            "_floor_take": self.take, "_floor_drop": self.drop, "_floor_lend": self.lend,
            "_clip_seconds_async": mock.AsyncMock(return_value=0.0), "_RENDER_BACKLOG": [],
            "render_backlog_save": lambda: None, "_RECENT_SPOKEN": [],
            "_S3_CHAPTER_SHELF": {}, "_S3_CHAPTER_STATE": {"loaded": True, "task": None},
            "_s3_active": lambda: True, "ask_model": self.ask, "_PAGE_ACKED_LINES": self.heard,
        }
        for name, value in patches.items():
            p = mock.patch.object(app, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        self.lock = None

    # -- stand-ins --------------------------------------------------------
    async def direct(self, road="interject", **kw):
        stamp = self.chapter.plan(road=road, seats=(("C", "A", "B", "D", "A") if road == "upstairs"
                                                    else ("A", "B", "D", "A", "B")))
        return mock.Mock(active=True, stamp=stamp)

    async def beats(self, context, sheet, lines, seats, seed_text="", verbatim_seed=False, **kw):
        self.assertTrue(verbatim_seed)
        self.assertIn("TIME: the replies together run about", context)
        rows = [r.split(":", 1) for r in self.replies[:lines - 1]]
        body = ["%s:%s" % (seats[i + 1], t) for i, (_m, t) in enumerate(rows)]
        return "\n".join(["%s: %s" % (seats[0], " ".join(seed_text.split()))] + body)

    async def ask(self, prompt, **kw):
        """The writer's repair visit: one line per listed turn."""
        self.prompts.append(prompt)
        rows = re.findall(r"(?m)^(\d+)  ([ABCD])  - ", prompt.split("WRITE ONLY THESE NEXT TURNS:")[-1])
        pool = GOOD if self.repair_ok else STOCK
        return "\n".join("%s:%s" % (seat, pool[(int(n) - 2) % len(pool)].split(":", 1)[1]) for n, seat in rows)

    async def render(self, text, who, voice):
        self.renders += 1
        name = "take%03d.wav" % self.renders
        (self.dir / "media" / name).write_bytes(b"RIFF")
        return {"path": "/media/" + name, "sig": "s", "seconds": 6.0}

    async def take(self, label=""):
        if self.lock is None:
            self.lock = asyncio.Lock()
        cur = asyncio.current_task()
        if getattr(self, "_owner", None) is cur:
            return False
        await self.lock.acquire()
        self._owner = cur
        self.floor["takes"] += 1
        return True

    def drop(self, owned):
        if owned:
            self._owner = None
            self.lock.release()

    async def lend(self, label, work):
        return await work

    async def speak(self, kind, track=None, **kw):
        """The microphone for chapter rows (and page parts)."""
        await asyncio.sleep(0)
        st = kw.get("system3") or {}
        self.aired.append((kw.get("who"), kw.get("line"), kw.get("sid"), st.get("turn_id"),
                           st.get("chapter_turn"), bool(kw.get("clip"))))
        lid = "L%03d" % len(self.aired)
        self.radio["chat"].append({"id": lid, "who": kw.get("who"), "text": kw.get("line")})
        self.heard.add(lid)                      # the listener hears it at once, unless a test says not
        return kw.get("line") or ""


class ToolAndChecks(unittest.TestCase):
    def test_both_tools_are_applied(self):
        for name, target in (("system3_exchange_chain_patch", "app.py"),
                             ("system3_exchange_chain2_patch", "app.py"),
                             ("system3_chain_runtime_patch", "system3_runtime.py")):
            mod = load_tool(name)
            text = (ROOT / target).read_text(encoding="utf-8")
            applied, missing = mod.check(text)
            self.assertEqual(missing, [], name)
            self.assertEqual(applied, len(mod.plan(text)), name)

    def test_the_live_failures_are_not_answers(self):
        work = ("Reacts to the line just aired. [Say it in discouragement, mildly. Write Skip's message "
                "with discouragement, reflecting the mood.]")
        # 4798c4e9 t01, as aired 2026-09-29 01:31:18
        self.assertIn("direction", app._s3_chapter_reply_fault(
            ["This one, right here on the station."],
            "No, bro, that isn't gonna work. Skip's message with discouragement, reflecting the mood.", work))
        # 129b7bfa t01/t04: stock frames
        self.assertIn("stock", app._s3_chapter_reply_fault([OPENER_AD], "I don't know if that's right.", work))
        self.assertIn("stock", app._s3_chapter_reply_fault([OPENER_AD], "That's just how it is.", ""))
        # 2026-09-29 03:00-03:40 shelf rejections, re-judged
        act = ("Reacts to the line just aired. [Say it in discouragement, mildly; while doing it, tells them "
               "flatly that no, bro, that isn't gonna work. Write Skip's message with discouragement, "
               "reflecting the mood.]")
        self.assertEqual(app._s3_chapter_reply_fault([OPENER_AD], "No, bro, that isn't gonna work.", act), "")
        self.assertEqual(app._s3_chapter_reply_fault([OPENER_AD], "Are you sure about that?", work), "")
        self.assertIn("direction", app._s3_chapter_reply_fault(
            [OPENER_AD], "Well, it is fixed source material, Dill, it airs exactly as recorded.", work))
        self.assertIn("too short", app._s3_chapter_reply_fault([OPENER_AD], "Right, there.", work))
        self.assertIn("stock", app._s3_chapter_reply_fault(
            [OPENER_AD], "Oh, well, I suppose it is what it is, just some noise in the booth.", work))
        self.assertEqual(app._s3_chapter_reply_fault(
            [OPENER_AD], "Skip, you would sell your own grandmother for less.", work, ["Skip"]), "")
        self.assertIn("answers nothing", app._s3_chapter_reply_fault(
            [OPENER_AD], "My uncle keeps pigeons on the roof of the old cinema downtown all summer.", work))
        self.assertEqual(app._s3_chapter_reply_fault(
            [OPENER_AD], "Ninety dollars for the harbour oil? That canvas is worth twice that.", work), "")


class ProducedSpot(Harness):
    """ad_spot: the 166-second case (2026-09-28 7:52 PM Sponsor's Copy)."""

    def setUp(self):
        super().setUp()
        (self.dir / "ads").mkdir()
        (self.dir / "ads" / "spot1.mp3").write_bytes(b"ID3")
        (self.dir / "ads" / "spot2.mp3").write_bytes(b"ID3")
        (self.dir / "ads" / "spot3.mp3").write_bytes(b"ID3")
        self.published = []
        inner = app._air_produced_ad_floorless
        names = {n.id for n in ast.walk(ast.parse(inspect.getsource(inner))) if isinstance(n, ast.Name)}
        keep = {"_s3_source_chapter", "_s3_chapter_floor", "_s3_chapter_air_rest", "_s3_chapter_opener_missed",
                "_s3_active", "_clip_seconds_async", "media_sign", "pipeline_log", "copy"}
        for name in names - keep:
            value = getattr(app, name, None)
            if inspect.isfunction(value):
                cls = mock.AsyncMock if inspect.iscoroutinefunction(value) else mock.Mock
                p = mock.patch.object(app, name, cls(return_value=""))
                p.start()
                self.addCleanup(p.stop)
        for name, value in {"PRODUCED_ADS_DIR": self.dir / "ads", "_PAGE_ACKED_LINES": self.heard,
                            "_PAGE_DELIVERIES": {}, "_BOX_DOWN": {}, "_BOX_HOLD": [],
                            "_dj_speak_floorless": self.speak,
                            "_clip_seconds_async": mock.AsyncMock(return_value=166.0)}.items():
            p = mock.patch.object(app, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        app.ad_booth_row.side_effect = lambda label, product, **kw: {"id": "row-" + str(kw.get("audio")), "text": label}
        app.page_carries_live.return_value = True
        app.admission_admit_line.return_value = "occ"

        def publish(clip):
            self.aired.append(("dj", clip.get("text"), None, None, None, True))
            self.published.append(clip)
            return "d%d" % len(self.published)
        app.page_feed_append.side_effect = publish

    def spot(self, n=1):
        return {"id": "ad%d" % n, "audio": "spot%d.mp3" % n, "product": "paintings %d" % n, "text": OPENER_AD}

    def test_the_166_second_spot_airs_with_its_whole_exchange(self):
        ok = asyncio.run(app._air_produced_ad(self.spot()))
        self.assertTrue(ok)
        self.assertEqual(self.aired[0][1], "\U0001f4e3 paintings 1")          # the spot, as recorded
        replies = self.aired[1:]
        self.assertEqual(len(replies), 4)
        entry = app._S3_CHAPTER_SHELF["ad:ad1"]
        self.assertEqual(entry["state"], "aired")
        self.assertEqual([r[4] for r in replies], [1, 2, 3, 4])                # every planned reply
        self.assertEqual({r[2] for r in replies}, {entry["sid"]})              # one sid
        self.assertTrue(all(r[5] for r in replies))                            # takes made before air
        self.assertEqual(len({r[3] for r in replies}), 4)                      # each its own stamp
        self.assertEqual({r[0] for r in replies}, {"cohost", "third", "dj"})
        self.assertAlmostEqual(entry["seconds"], 166.0 + 4 * 6.0)              # the whole, measured
        self.assertEqual(self.floor["takes"], 1)                               # one floor, spot to last reply
        self.assertIsNone(getattr(self, "_owner", None))

    def test_two_spots_at_once_never_interleave(self):
        async def both():
            return await asyncio.gather(app._air_produced_ad(self.spot(1)), app._air_produced_ad(self.spot(2)))
        self.assertEqual(asyncio.run(both()), [True, True])
        heads = [i for i, r in enumerate(self.aired) if str(r[1]).startswith("\U0001f4e3")]
        self.assertEqual(heads, [0, 5])                  # spot, its 4 replies, spot, its 4 replies
        self.assertEqual(len({r[2] for r in self.aired[1:5]}), 1)
        self.assertEqual(len({r[2] for r in self.aired[6:10]}), 1)
        self.assertNotEqual(self.aired[1][2], self.aired[6][2])

    def test_a_writer_that_does_not_answer_makes_it_wait_then_the_keeper_airs_it_whole(self):
        self.replies = list(STOCK)
        self.repair_ok = False
        self.assertFalse(asyncio.run(app._air_produced_ad(self.spot())))
        self.assertEqual(self.aired, [])                                       # nothing aired, not dropped
        entry = app._S3_CHAPTER_SHELF["ad:ad1"]
        self.assertEqual(entry["state"], "pending")
        self.assertIn("stock frame", entry["why"])
        self.assertIn("YOUR LAST DRAFT FAILED: turn 2 is a stock frame", self.prompts[0])   # told why
        saved = json.loads((self.dir / "shelf.json").read_text())
        self.assertEqual(saved["ad:ad1"]["state"], "pending")                   # durable
        self.replies = list(GOOD)
        self.repair_ok = True
        entry["next_try"] = 0
        asyncio.run(app._s3_chapter_keep_once())                                # the keeper writes it
        self.assertEqual(entry["state"], "prepared")
        asyncio.run(app._s3_chapter_keep_once())                                # and airs it through its road
        self.assertEqual(entry["state"], "aired")
        self.assertEqual(len(self.aired), 5)
        self.assertTrue(any(s[1] == "pending" for s in self.chapter.states))

    def test_only_the_failing_turn_is_written_again_and_told_why(self):
        self.replies = [GOOD[0], STOCK[1], GOOD[2], GOOD[3]]
        self.assertTrue(asyncio.run(app._air_produced_ad(self.spot())))
        self.assertEqual(len(self.prompts), 1)                                  # one repair visit
        self.assertIn("YOUR LAST DRAFT FAILED: turn 3 is a stock frame", self.prompts[0])
        written = self.prompts[0].split("WRITE ONLY THESE NEXT TURNS:")[1]
        self.assertNotIn("\n2  B", written)                                     # turn 2 was kept, not rewritten
        self.assertIn(GOOD[0].split(":", 1)[1].strip(), self.prompts[0])        # ...and handed on as said
        self.assertEqual(self.aired[1][1], GOOD[0].split(":", 1)[1].strip())
        self.assertEqual(len(self.aired), 5)

    def test_a_full_writers_lane_is_a_short_wait_not_an_attempt(self):
        async def full(*a, **k):
            raise app.WritingDeferred("full")
        with mock.patch.object(app, "_banter_beats", full):
            self.assertFalse(asyncio.run(app._air_produced_ad(self.spot())))
        entry = app._S3_CHAPTER_SHELF["ad:ad1"]
        self.assertEqual((entry["state"], entry["attempts"], entry["lane_waits"]), ("pending", 0, 1))
        self.assertLessEqual(entry["next_try"] - app.time.time(), app.S3_CHAPTER_LANE_RETRY + 1)
        self.assertEqual(app.S3_CHAPTER_BACKOFF[-1], 120.0)

    def test_published_is_not_aired_until_every_reply_is_heard(self):
        real = self.speak

        async def speak(kind, track=None, **kw):
            got = await real(kind, track, **kw)
            if (kw.get("system3") or {}).get("chapter_turn") == 4:
                self.heard.discard(self.radio["chat"][-1]["id"])                 # still queued on the page
            return got
        with mock.patch.object(app, "_dj_speak_floorless", speak):
            self.assertTrue(asyncio.run(app._air_produced_ad(self.spot())))
        entry = app._S3_CHAPTER_SHELF["ad:ad1"]
        self.assertEqual(entry["state"], "published")                          # handed over, not heard
        asyncio.run(app._s3_chapter_keep_once())
        self.assertEqual(entry["state"], "published")
        self.heard.add(entry["line_ids"]["4"])                                  # the listener reaches it
        asyncio.run(app._s3_chapter_keep_once())
        self.assertEqual(entry["state"], "aired")
        # one that is never heard is recorded as such, never called aired
        e2 = app._s3_chapter_new("ad:y", stamp=self.chapter.plan(), opening="y", kind="ad")
        e2.update(state="published", published_at=app.time.time() - app.S3_CHAPTER_HEARD_WAIT - 1,
                  line_ids={"1": "nope"})
        asyncio.run(app._s3_chapter_keep_once())
        self.assertEqual(e2["state"], "unheard")
        self.assertIn("1", e2["why"])

    def test_one_waiting_exchange_per_road_a_newer_source_is_superseded_and_recorded(self):
        self.replies = list(STOCK)
        self.repair_ok = False
        self.assertFalse(asyncio.run(app._air_produced_ad(self.spot(1))))
        self.assertFalse(asyncio.run(app._air_produced_ad(self.spot(2))))
        first, second = app._S3_CHAPTER_SHELF["ad:ad1"], app._S3_CHAPTER_SHELF["ad:ad2"]
        self.assertEqual((first["state"], second["state"]), ("pending", "superseded"))
        self.assertEqual(second["superseded_by"], "ad:ad1")
        # an earlier one that has failed three times gives way instead
        first["attempts"] = 3
        self.assertFalse(asyncio.run(app._air_produced_ad(self.spot(3))))
        self.assertEqual(first["state"], "expired")
        self.assertEqual(app._S3_CHAPTER_SHELF["ad:ad3"]["state"], "pending")

    def test_an_exchange_longer_than_its_entry_waits_for_room_then_airs_and_says_so(self):
        now = app.time.time()
        with mock.patch.object(app, "_ready_slot_window",
                               lambda kind: {"kind": kind, "deadline": now + 100.0}):
            self.assertFalse(asyncio.run(app._air_produced_ad(self.spot())))
            entry = app._S3_CHAPTER_SHELF["ad:ad1"]
            self.assertEqual(entry["state"], "prepared")
            self.assertIn("waits for room", entry["why"])
            self.assertEqual(self.aired, [])
            entry["fit_since"] = now - app.S3_CHAPTER_FIT_WAIT - 1
            self.assertTrue(asyncio.run(app._air_produced_ad(self.spot())))
        self.assertGreater(entry["overrun"], 0)
        self.assertEqual(len(self.aired), 5)

    def test_a_road_with_its_graph_off_airs_the_spot_alone(self):
        orig = self.chapter.plan
        self.chapter.plan = lambda road="ad_spot", seats=("A",), chapter=True: orig(road, ("A", "B", "D"), False)
        self.assertTrue(asyncio.run(app._air_produced_ad(self.spot())))
        self.assertEqual(len(self.aired), 1)

    def test_a_pause_leaves_the_rest_owed_and_the_keeper_resumes_it(self):
        paused = {"on": False}
        real = self.speak

        async def speak(kind, track=None, **kw):
            got = await real(kind, track, **kw)
            if (kw.get("system3") or {}).get("chapter_turn") == 2:
                paused["on"] = True
            return got
        with mock.patch.object(app, "_dj_speak_floorless", speak), \
                mock.patch.object(app, "radio_paused", lambda: paused["on"]):
            asyncio.run(app._air_produced_ad(self.spot()))
            entry = app._S3_CHAPTER_SHELF["ad:ad1"]
            self.assertEqual(entry["state"], "partial")
            self.assertEqual(entry["done"], 3)
            paused["on"] = False
            entry["next_air"] = 0
            asyncio.run(app._s3_chapter_keep_once())
        self.assertEqual(entry["state"], "aired")
        self.assertEqual([r[4] for r in self.aired[1:]], [1, 2, 3, 4])          # nothing twice, in order

    def test_the_shelf_survives_a_restart_mid_air(self):
        e = app._s3_chapter_new("ad:x", stamp=self.chapter.plan(), opening="x", kind="ad")
        e.update(state="airing", done=2)
        app._s3_chapter_save()
        with mock.patch.object(app, "_S3_CHAPTER_SHELF", {}), \
                mock.patch.object(app, "_S3_CHAPTER_STATE", {"loaded": False, "task": None}):
            got = app._s3_chapter_shelf()["ad:x"]
        self.assertEqual(got["state"], "partial")


class MusicBedSpot(Harness):
    def setUp(self):
        super().setUp()
        inner = app._dj_music_ad_floorless
        names = {n.id for n in ast.walk(ast.parse(inspect.getsource(inner))) if isinstance(n, ast.Name)}
        keep = {"_s3_source_chapter", "_s3_chapter_floor", "_s3_chapter_air_rest", "_s3_active",
                "pipeline_log", "ad_booth_row", "hashlib", "session_voices"}
        for name in names - keep:
            value = getattr(app, name, None)
            if inspect.isfunction(value):
                cls = mock.AsyncMock if inspect.iscoroutinefunction(value) else mock.Mock
                p = mock.patch.object(app, name, cls(return_value=""))
                p.start()
                self.addCleanup(p.stop)
        p = mock.patch.object(app, "_dj_speak_floorless", self.speak)
        p.start()
        self.addCleanup(p.stop)
        (self.dir / "media" / "bed.wav").write_bytes(b"RIFF")
        app.ad_write_fresh.return_value = {"text": OPENER_AD}
        app.spoken_text.side_effect = lambda t: t
        app.voice_generate.return_value = {"path": "/media/bed.wav", "sig": "s", "seconds": 30.0}
        app._music_bed_track.return_value = None
        app.page_carries_live.return_value = True
        app.ad_save.return_value = {"id": "m1"}
        app.page_feed_append.side_effect = lambda clip: self.aired.append(
            ("dj", clip.get("text"), None, None, None, True)) or "d1"

    def test_the_bedded_spot_opens_its_chapter_and_its_row_is_turn_zero(self):
        got = asyncio.run(app.dj_music_ad("paintings"))
        self.assertEqual(got["ad"], OPENER_AD)
        self.assertEqual(len(self.aired), 5)
        entry = next(e for k, e in app._S3_CHAPTER_SHELF.items() if k.startswith("bed:"))
        self.assertEqual(entry["state"], "aired")
        row = next(r for r in self.radio["chat"] if r.get("kind") == "ad")
        self.assertEqual(row["sid"], entry["sid"])
        self.assertEqual(row["system3"]["turn_id"], entry["rows"][0]["stamp"]["turn_id"])
        self.assertEqual({r[2] for r in self.aired[1:]}, {entry["sid"]})
        self.assertEqual(self.floor["takes"], 1)


class ManagerPage(Harness):
    def setUp(self):
        super().setUp()
        (self.dir / "up").mkdir()
        (self.dir / "up" / "p1.mp3").write_bytes(b"ID3")
        inner = app._dj_upstairs_page_floorless
        names = {n.id for n in ast.walk(ast.parse(inspect.getsource(inner))) if isinstance(n, ast.Name)}
        keep = {"_s3_source_chapter", "_s3_chapter_floor", "_s3_chapter_air_rest", "_s3_active",
                "_clip_seconds_async", "media_sign", "pipeline_log", "_s3_split_speak"}
        for name in names - keep:
            value = getattr(app, name, None)
            if inspect.isfunction(value):
                cls = mock.AsyncMock if inspect.iscoroutinefunction(value) else mock.Mock
                p = mock.patch.object(app, name, cls(return_value=""))
                p.start()
                self.addCleanup(p.stop)
        for name, value in {"UPSTAIRS_AUDIO_DIR": self.dir / "up", "_dj_speak_floorless": self.speak,
                            "UPSTAIRS_AUDIO_SHAPE": mock.Mock(fullmatch=mock.Mock(return_value=True)),
                            "_clip_seconds_async": mock.AsyncMock(return_value=21.0)}.items():
            p = mock.patch.object(app, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        app.manager_call_name.return_value = "Marge"
        app.upstairs_page_backlogged.return_value = False
        app.admission_admit_line.return_value = "occ"
        app.page_feed_append.side_effect = lambda clip: (self.aired.append(
            ("manager", clip.get("text"), None, None, None, True)) or "d1")
        self.replies = ["A: Marge wants the boombox gone? The boombox stays, Marge.",
                        "B: The boombox stays until Marge sends a memo about the boombox, Dill.",
                        "D: A memo about the boombox is how Marge wins, Skip.",
                        "A: Then Marge can have the boombox when she comes down for it."]
        self.page = {"id": "p1", "audio": "p1.mp3", "text": "The boombox in the booth goes by Friday.",
                     "gripe": "the boombox", "split": {"whole": "The boombox in the booth goes by Friday. "
                                                                "Friday means Friday.",
                                                       "parts": [{"part": 2, "of": 2, "who": "cohost", "name": "Skip",
                                                                  "text": "Friday means Friday.",
                                                                  "stamp": {"conversation_id": "old", "turn_id": "old:t00",
                                                                            "split": {"part": 2, "of": 2}}}]}}

    def test_the_page_is_answered_by_its_chapter_not_a_second_conversation(self):
        self.assertTrue(asyncio.run(app.dj_upstairs_page(dict(self.page))))
        app.dj_banter.assert_not_called()
        self.assertEqual(self.aired[0][0], "manager")
        rest = self.aired[1:]
        self.assertEqual(rest[0][1], "Friday means Friday.")                   # the split part reads on
        self.assertEqual(len(rest), 5)
        entry = app._S3_CHAPTER_SHELF["page:p1"]
        self.assertEqual({r[2] for r in rest}, {entry["sid"]})
        cid = entry["stamp"]["conversation_id"]
        self.assertTrue(rest[0][3].startswith(cid + ":t00"))                   # the part is t00's own
        self.assertEqual([r[4] for r in rest[1:]], [1, 2, 3, 4])
        self.assertEqual(self.floor["takes"], 1)

    def test_a_page_whose_exchange_is_not_ready_waits_unaired(self):
        self.replies = list(STOCK)
        self.assertFalse(asyncio.run(app.dj_upstairs_page(dict(self.page))))
        self.assertEqual(self.aired, [])
        app.dj_banter.assert_not_called()
        self.assertEqual(app._S3_CHAPTER_SHELF["page:p1"]["state"], "pending")


class RealMicrophone(Harness):
    """A short station ID through the REAL _dj_speak_floorless (the
    test_system2_repeat_host pattern: every other helper it names is a stand-in)."""

    def setUp(self):
        super().setUp()
        original = app._dj_speak_floorless
        names = {n.id for n in ast.walk(ast.parse(inspect.getsource(original))) if isinstance(n, ast.Name)}
        keep = {"_dj_speak_floorless", "_s3_line_chapter_admit", "_s3_chapter_forget_recent",
                "_s3_active", "radio_paused", "line_forgotten", "_system2_repeat_rows_async",
                "session_voices", "configured_radio_voice", "dj_settings", "_floor_lend",
                "pipeline_log", "_box_receipt_heard", "_box_receipt_audible", "_played_out_key"}
        for name in names - keep:
            value = getattr(app, name, None)
            if inspect.isfunction(value):
                cls = mock.AsyncMock if inspect.iscoroutinefunction(value) else mock.Mock
                p = mock.patch.object(app, name, cls(return_value=""))
                p.start()
                self.addCleanup(p.stop)
        for name, value in {"_system2": None, "_LAST_PLAYOUT": {}, "_BOX_DOWN": {}, "_BOX_HOLD": [],
                            "_PAGE_ACKED_LINES": set(), "_SPEAKING": [0], "_SILENT_HOLD_STREAK": [0],
                            "_PAGE_AIR_UNTIL": [0], "_SPEAK_LAST": {}, "_SPEAKING_NOW": {},
                            "_DIALOGUE_AT": [0]}.items():
            p = mock.patch.object(app, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        self.radio["voice_to"] = "box"
        app.spoken_text.side_effect = lambda text: text
        app.station_name_scrub.side_effect = lambda text: text
        app.performance_vector.return_value = {}
        app.voice_engine_for.return_value = "piper"
        app.box_talk_ok.return_value = True
        app.page_carries_live.return_value = False
        app.load_settings.return_value = {}
        app._s3_said_copy.return_value = False
        app.satellite_busy.return_value = True               # the box is "answering someone"
        self.played = []

        async def play(path, sig, **kw):
            self.played.append(path)
            return "transport accepted"
        app._play_on_box.side_effect = play
        self.replies = ["B: Pine Box FM, you say? At four in the morning Pine Box FM is all we have, Dill.",
                        "D: All we have is plenty, Skip, Pine Box FM never sleeps.",
                        "A: Never sleeps and never stops, that is Pine Box FM."]

    def test_a_station_id_airs_with_its_exchange_in_order(self):
        stamp = self.chapter.plan(road="station_id", seats=("A", "B", "D", "A"))
        said = asyncio.run(app.dj_speak("station_id", None, line="This is Pine Box FM.", who="dj",
                                        system3=stamp, sting=False))
        self.assertEqual(said, "This is Pine Box FM.")
        entry = app._S3_CHAPTER_SHELF["conv:" + stamp["conversation_id"]]
        self.assertIn(entry["state"], ("published", "aired"))                  # aired once heard
        self.assertEqual(entry["done"], 4)
        self.assertEqual(len(self.played), 4)                   # opener + 3 replies, all on the box
        self.assertEqual(self.played, [c["path"] for c in entry["clips"]])   # the made takes, in order
        app.box_hold.assert_not_called()                        # a busy box never shelves a chapter row
        self.assertEqual(app._S3_CHAPTER_ROW.get(), "")

    def test_a_rounds_chunk_names_its_turn_and_plans_no_chapter(self):
        stamp = self.chapter.plan(road="banter", seats=("A", "B", "A"), chapter=False)
        stamp["turn_id"] = stamp["conversation_id"] + ":t01"
        app.satellite_busy.return_value = False
        (self.dir / "media" / "chunk.wav").write_bytes(b"RIFF")
        said = asyncio.run(app.dj_speak("interject", None, line="A chunk of a round.", who="cohost",
                                        system3=stamp, checked=True,
                                        clip={"path": "/media/chunk.wav", "sig": "s", "seconds": 2.0}))
        self.assertEqual(said, "A chunk of a round.")
        self.assertEqual(app._S3_CHAPTER_SHELF, {})
        self.assertEqual(len(self.played), 1)

    def test_the_chunk_stamp_reads_the_rounds_own_turn(self):
        meta = {"system3": {"conversation_id": "r1", "mode": "active", "turns": {"0": "r1:t00"}}}
        with mock.patch.object(app, "system3_turn_id_for", lambda m, text, who: "r1:t00", create=True):
            self.assertEqual(app._s3_chunk_stamp(meta, "words", "dj"),
                             {"conversation_id": "r1", "mode": "active", "turn_id": "r1:t00"})
        self.assertIsNone(app._s3_chunk_stamp({}, "words", "dj"))


if __name__ == "__main__":
    unittest.main()
