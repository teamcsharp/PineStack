# -*- coding: utf-8 -*-
"""#1177: the two roads the running order cannot ask for, executed.

app.py is never imported here - it is 9.8 MB and needs the whole station.
What IS executed is the exact source text the patch inserts, in a
namespace holding stand-ins for the handful of app.py globals it touches,
so the switch and the two gates are tested as code rather than as a
description of code, and a typo in the patch fails here rather than on
air.

The patch script lives outside the repository on purpose: the station is
broadcasting and every app.py change is applied by hand. Point
SPARK_EVENT_ROADS_PATCH at it, or leave it where the agent wrote it;
without it these tests skip and say so.
"""
import ast
import hashlib
import importlib.util
import io
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

CANDIDATES = [
    os.getenv("SPARK_EVENT_ROADS_PATCH", ""),
    str(Path(tempfile.gettempdir()) / "claude" / "patch_1177_event_roads.py"),
    r"C:\Users\EHMECK~1\AppData\Local\Temp\claude"
    r"\--10-89-1-246-ehm-eckx-pinevoice-stack-spark-agent"
    r"\4c062de1-24db-4acb-9996-7567ccd60535\scratchpad\1177"
    r"\patch_1177_event_roads.py",
]


def find_patch():
    for name in CANDIDATES:
        if name and Path(name).is_file():
            return Path(name)
    return None


PATCH = find_patch()


def load_patch():
    spec = importlib.util.spec_from_file_location("patch_1177", str(PATCH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = load_patch() if PATCH else None
skip_no_patch = unittest.skipIf(
    P is None, "patch script not found; set SPARK_EVENT_ROADS_PATCH")


# --------------------------------------------------------------------
# A namespace with the few app.py globals the inserted code really uses.
# --------------------------------------------------------------------
class Clock(object):
    """A hand-wound time.time(), so memoisation is testable without sleeps."""

    def __init__(self, at=1000.0):
        self.at = at

    def time(self):
        return self.at


class Booth(object):
    """Stand-ins for the station globals, with a record of what was logged."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.clock = Clock()
        self.logged = []
        self.track_talk_full_says = True
        self.shelf_full_says = True
        self.track_talk_full_raises = False
        self.shelf_full_raises = False
        self.shelf_asked = []

    def data_path(self, *parts):
        return self.tmp.joinpath(*parts)

    def pipeline_log(self, kind, text, extra=""):
        self.logged.append((kind, text))

    def track_talk_full(self):
        if self.track_talk_full_raises:
            raise RuntimeError("the lookahead was unreadable")
        return self.track_talk_full_says

    def shelf_full(self, kind):
        self.shelf_asked.append(kind)
        if self.shelf_full_raises:
            raise RuntimeError("the shelf was unreadable")
        return self.shelf_full_says


def make_namespace(booth):
    ns = {
        "Any": Any,
        "time": booth.clock,
        "data_path": booth.data_path,
        "pipeline_log": booth.pipeline_log,
        "track_talk_full": booth.track_talk_full,
        "shelf_full": booth.shelf_full,
    }
    exec(compile(P.A_BLOCK.decode("utf-8"), "<A_BLOCK>", "exec"), ns)
    return ns


class SwitchBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="evtroads-")
        self.booth = Booth(self.tmp)
        self.ns = make_namespace(self.booth)
        self.switch = Path(self.tmp) / "event_roads_prepare"

    def write(self, text):
        self.switch.write_text(text, encoding="utf-8")

    def ask(self):
        return self.ns["event_roads_prepare"]()

    def tick(self, by=10.0):
        self.booth.clock.at += by


@skip_no_patch
class TestTheSwitchDefaultsOff(SwitchBase):
    """Off is the station exactly as it runs now, and off is the default."""

    def test_missing_file_is_off(self):
        self.assertFalse(self.switch.exists())
        self.assertFalse(self.ask())

    def test_empty_file_is_off(self):
        self.write("")
        self.assertFalse(self.ask())

    def test_a_directory_where_the_file_should_be_is_off(self):
        self.switch.mkdir()
        self.assertFalse(self.ask())

    def test_junk_is_off(self):
        for junk in ("yes", "1", "true", "enabled", "ON PLEASE", "o n"):
            self.tick()
            self.write(junk)
            self.assertFalse(self.ask(), junk)

    def test_the_word_on_is_on(self):
        for word in ("on", "ON", " on ", "on\n", "\tOn\r\n"):
            self.tick()
            self.write(word)
            self.assertTrue(self.ask(), repr(word))

    def test_off_after_on_goes_back_off(self):
        self.write("on")
        self.assertTrue(self.ask())
        self.tick()
        self.write("off")
        self.assertFalse(self.ask())


@skip_no_patch
class TestTheSwitchIsCheapAndQuiet(SwitchBase):
    """A share read per road per pass is a share read per road per pass."""

    def test_memoised_inside_the_window(self):
        self.assertFalse(self.ask())
        self.write("on")
        self.booth.clock.at += P and 0.0 or 0.0      # no time has passed
        self.assertFalse(self.ask(), "re-read inside the memo window")

    def test_re_read_after_the_window(self):
        self.assertFalse(self.ask())
        self.write("on")
        self.tick(self.ns["EVENT_ROADS_SWITCH_EVERY"] + 0.1)
        self.assertTrue(self.ask())

    def test_logs_only_when_it_changes(self):
        self.assertFalse(self.ask())
        self.assertEqual([], self.booth.logged, "first read logged")
        for _ in range(4):
            self.tick()
            self.assertFalse(self.ask())
        self.assertEqual([], self.booth.logged, "still-off logged a line")
        self.tick()
        self.write("on")
        self.assertTrue(self.ask())
        self.assertEqual(1, len(self.booth.logged))
        self.assertEqual("lookahead", self.booth.logged[0][0])
        self.assertIn("#1177", self.booth.logged[0][1])
        self.tick()
        self.assertTrue(self.ask())
        self.assertEqual(1, len(self.booth.logged), "no change, but logged")

    def test_a_broken_log_never_breaks_the_switch(self):
        def boom(*a, **k):
            raise RuntimeError("the log is gone")
        self.ns["pipeline_log"] = boom
        self.assertFalse(self.ask())
        self.tick()
        self.write("on")
        self.assertTrue(self.ask())


@skip_no_patch
class TestWhatAnEventRoadWants(SwitchBase):
    """The very predicates prep_plan tests two lines below the door."""

    def wants(self, kind):
        return self.ns["event_road_wants"](kind)

    def test_the_two_roads_are_the_two_roads(self):
        self.assertEqual(("station_id", "track_talk"),
                         self.ns["EVENT_DRIVEN_ROADS"])

    def test_track_talk_wants_when_its_lookahead_is_not_full(self):
        self.booth.track_talk_full_says = False
        self.assertTrue(self.wants("track_talk"))
        self.booth.track_talk_full_says = True
        self.assertFalse(self.wants("track_talk"))

    def test_station_id_wants_when_its_shelf_is_not_full(self):
        self.booth.shelf_full_says = False
        self.assertTrue(self.wants("station_id"))
        self.assertEqual(["station_id"], self.booth.shelf_asked)
        self.booth.shelf_full_says = True
        self.assertFalse(self.wants("station_id"))

    def test_no_other_road_is_touched(self):
        self.booth.shelf_full_says = False
        self.booth.track_talk_full_says = False
        for kind in ("caller", "manager", "gallery", "news", "ad",
                     "banter", "recap", "record", "", None):
            self.assertFalse(self.wants(kind), repr(kind))

    def test_a_raising_predicate_builds_nothing(self):
        self.booth.track_talk_full_raises = True
        self.booth.shelf_full_raises = True
        self.assertFalse(self.wants("track_talk"))
        self.assertFalse(self.wants("station_id"))


# --------------------------------------------------------------------
# The two gates, lifted out of the patch and run as code.
# --------------------------------------------------------------------
def build_gate(fragment, head, tail):
    """Wrap an inserted fragment in the smallest function that runs it."""
    body = textwrap.indent(textwrap.dedent(fragment.decode("utf-8")), "    ")
    return head + body + tail


PLAN_GATE_HEAD = "def gate(kind, _needs_script, _can_finish_here):\n"
PLAN_GATE_TAIL = ("        return 'refused'\n"
                  "    return 'on the board'\n")

DOOR_GATE_HEAD = "def door(kind, _new_script, _assigned_unready):\n"
DOOR_GATE_TAIL = "    return True\n"


@skip_no_patch
class TestThePlannersGate(unittest.TestCase):
    """prep_plan: the road must reach the board at all."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="evtplan-")
        self.booth = Booth(self.tmp)
        self.ns = make_namespace(self.booth)
        self.ns["story_bank_short"] = lambda: False
        src = build_gate(P.B_NEW, PLAN_GATE_HEAD, PLAN_GATE_TAIL)
        exec(compile(src, "<B_NEW>", "exec"), self.ns)
        self.gate = self.ns["gate"]
        self.switch = Path(self.tmp) / "event_roads_prepare"

    def on(self):
        self.switch.write_text("on", encoding="utf-8")
        self.booth.clock.at += 10.0

    def test_switch_off_changes_nothing_for_the_two_roads(self):
        self.booth.track_talk_full_says = False
        self.booth.shelf_full_says = False
        for kind in ("station_id", "track_talk"):
            self.assertEqual("refused", self.gate(kind, False, False), kind)

    def test_switch_off_changes_nothing_for_any_other_road(self):
        for kind in ("caller", "manager", "gallery", "news", "ad"):
            self.assertEqual("refused", self.gate(kind, False, False), kind)
            self.assertEqual("on the board", self.gate(kind, True, False),
                             kind)

    def test_switch_on_puts_a_wanting_road_on_the_board(self):
        self.on()
        self.booth.track_talk_full_says = False
        self.booth.shelf_full_says = False
        for kind in ("station_id", "track_talk"):
            self.assertEqual("on the board", self.gate(kind, False, False),
                             kind)

    def test_switch_on_still_respects_the_ceilings(self):
        self.on()
        self.booth.track_talk_full_says = True
        self.booth.shelf_full_says = True
        for kind in ("station_id", "track_talk"):
            self.assertEqual("refused", self.gate(kind, False, False), kind)

    def test_switch_on_does_not_widen_any_other_road(self):
        self.on()
        self.booth.track_talk_full_says = False
        self.booth.shelf_full_says = False
        for kind in ("caller", "manager", "gallery", "news", "ad", "banter"):
            self.assertEqual("refused", self.gate(kind, False, False), kind)

    def test_the_1033_caller_floor_is_untouched(self):
        self.ns["story_bank_short"] = lambda: True
        self.assertEqual("on the board", self.gate("caller", False, False))

    def test_a_road_that_can_finish_here_is_untouched(self):
        self.assertEqual("on the board", self.gate("ad", False, True))


@skip_no_patch
class TestTheProducersDoor(unittest.TestCase):
    """_prep_one_work: the road must survive the pass that chose it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="evtdoor-")
        self.booth = Booth(self.tmp)
        self.ns = make_namespace(self.booth)
        self.noted = []
        self.ns["prep_note"] = lambda k, s, **m: self.noted.append((k, s))
        src = build_gate(P.C_NEW, DOOR_GATE_HEAD, DOOR_GATE_TAIL)
        exec(compile(src, "<C_NEW>", "exec"), self.ns)
        self.door = self.ns["door"]
        self.switch = Path(self.tmp) / "event_roads_prepare"

    def on(self):
        self.switch.write_text("on", encoding="utf-8")
        self.booth.clock.at += 10.0

    def test_switch_off_refuses_exactly_as_before(self):
        self.booth.track_talk_full_says = False
        self.booth.shelf_full_says = False
        for kind in ("station_id", "track_talk", "caller", "ad"):
            self.assertFalse(self.door(kind, False, set()), kind)
        self.assertEqual({"four-hour obligations assigned"},
                         {s for _k, s in self.noted})

    def test_switch_on_lets_a_wanting_road_through(self):
        self.on()
        self.booth.track_talk_full_says = False
        self.booth.shelf_full_says = False
        for kind in ("station_id", "track_talk"):
            self.assertTrue(self.door(kind, False, set()), kind)
        self.assertEqual([], self.noted)

    def test_switch_on_still_refuses_a_full_road(self):
        self.on()
        self.booth.track_talk_full_says = True
        self.booth.shelf_full_says = True
        for kind in ("station_id", "track_talk"):
            self.assertFalse(self.door(kind, False, set()), kind)

    def test_an_existing_obligation_still_walks_straight_through(self):
        for kind in ("caller", "manager", "station_id", "track_talk"):
            self.assertTrue(self.door(kind, True, set()), kind)

    def test_the_track_talk_finish_bypass_is_untouched(self):
        self.assertTrue(self.door("track_talk", False, {"a-sid"}))
        self.assertEqual([], self.noted)


# --------------------------------------------------------------------
# The patch script itself.
# --------------------------------------------------------------------
SYNTHETIC = ""

if P:
    SYNTHETIC = (
        "import time\n"
        "from typing import Any\n"
        "\n"
        "\n"
        "def data_path(*parts):\n"
        "    return None\n"
        "\n"
        "\n"
        + P.A_ANCHOR.decode("utf-8")
        # The same nesting app.py has: def / try / for kind in order / try,
        # so the anchor sits at the indent it really sits at.
        + "    try:\n"
        + "        order = []\n"
        + "        for kind in order:\n"
        + "            try:\n"
        + "                _needs_script = False\n"
        + "                _can_finish_here = False\n"
        + P.B_ANCHOR.decode("utf-8")
        + "                    continue\n"
        + "            except Exception:\n"
        + "                continue\n"
        + "    except Exception:\n"
        + "        pass\n"
        + "    return {}\n"
        + "\n"
        + "\n"
        + "async def _prep_one_work(kind):\n"
        + "    try:\n"
        + "        _new_script = False\n"
        + "        _assigned_unready = set()\n"
        + P.C_ANCHOR.decode("utf-8")
        + "    except Exception:\n"
        + "        return False\n"
        + "    return True\n"
    )


@skip_no_patch
class TestThePatchScript(unittest.TestCase):
    """Idempotent, byte-IO, LF-only, and it refuses rather than guesses."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="evtpatch-"))
        self.target = self.tmp / "app.py"
        self.target.write_bytes(SYNTHETIC.encode("utf-8"))
        self.original = self.target.read_bytes()

    def sha(self, data):
        return hashlib.sha1(data).hexdigest()

    def test_the_synthetic_file_holds_each_anchor_exactly_once(self):
        for _n, _m, anchor, _new in P.STAGES:
            self.assertEqual(1, self.original.count(anchor))

    def test_clean_file_reports_appliable(self):
        applied, missing, _rows = P.plan(self.original)
        self.assertEqual(0, applied)
        self.assertEqual(3, missing)

    def test_apply_then_check_reports_fully_applied(self):
        out = P.apply_all(self.original)
        applied, missing, _rows = P.plan(out)
        self.assertEqual(3, applied)
        self.assertEqual(0, missing)

    def test_the_result_compiles(self):
        self.assertEqual("", P.compiles(P.apply_all(self.original)))

    def test_applying_twice_changes_nothing(self):
        once = P.apply_all(self.original)
        twice = P.apply_all(once)
        self.assertEqual(self.sha(once), self.sha(twice))

    def test_a_half_applied_file_is_finished_not_skipped(self):
        """The marker of one stage must never mask the other two."""
        full = P.apply_all(self.original)
        for at in range(len(P.STAGES)):
            part = self.original
            for name, _mark, anchor, new in P.STAGES[:at + 1]:
                part = part.replace(anchor, new, 1)
            self.assertEqual(self.sha(full), self.sha(P.apply_all(part)),
                             "stopped after stage %d" % (at + 1))

    def test_revert_is_byte_exact(self):
        out = P.apply_all(self.original)
        self.assertNotEqual(self.sha(self.original), self.sha(out))
        self.assertEqual(self.sha(self.original), self.sha(P.revert_all(out)))

    def test_revert_of_a_clean_file_is_a_no_op(self):
        self.assertEqual(self.sha(self.original),
                         self.sha(P.revert_all(self.original)))

    def test_a_missing_anchor_refuses(self):
        with self.assertRaises(SystemExit):
            P.apply_all(b"nothing in here resembles app.py\n")

    def test_a_duplicated_anchor_refuses(self):
        doubled = self.original + P.B_ANCHOR
        with self.assertRaises(SystemExit):
            P.apply_all(doubled)

    def test_crlf_is_refused_outright(self):
        crlf = self.tmp / "crlf.py"
        crlf.write_bytes(self.original.replace(b"\n", b"\r\n"))
        with self.assertRaises(SystemExit):
            P.read(crlf)

    def test_the_patch_writes_no_carriage_returns(self):
        self.assertEqual(0, P.apply_all(self.original).count(b"\r"))

    def test_a_non_compiling_result_is_never_written(self):
        broken = self.tmp / "broken.py"
        broken.write_bytes(self.original + b"def (:\n")
        before = broken.read_bytes()
        out = P.apply_all(before)
        self.assertNotEqual("", P.compiles(out))
        self.assertEqual(before, broken.read_bytes())

    def test_each_stage_marker_is_unique_to_its_stage(self):
        out = P.apply_all(self.original)
        for _name, mark, _anchor, _new in P.STAGES:
            self.assertEqual(1, out.count(mark), mark)


# --------------------------------------------------------------------
# The fix must not contradict something the station says is by design.
# --------------------------------------------------------------------
APP_PY = Path(__file__).resolve().parent.parent / "app.py"


_APP_CONSTS = {}


def _app_lines():
    """app.py is 9.8 MB and a full ast.parse of it costs 72 seconds on this
    box - measured. These constants are plain top-level literals, so the
    statement is lifted out by hand and only THAT is parsed."""
    if "\n" not in _APP_CONSTS:
        _APP_CONSTS["\n"] = io.open(
            str(APP_PY), encoding="utf-8", errors="replace").read().split("\n")
    return _APP_CONSTS["\n"]


def const_from_app(name):
    if name in _APP_CONSTS:
        return _APP_CONSTS[name]
    lines = _app_lines()
    head = name + " = "
    for at, line in enumerate(lines):
        if not line.startswith(head):
            continue
        # Grow the statement a line at a time until it is a whole literal.
        for end in range(at + 1, min(at + 200, len(lines)) + 1):
            chunk = "\n".join(lines[at:end])
            try:
                node = ast.parse(chunk).body[0]
                _APP_CONSTS[name] = ast.literal_eval(node.value)
                return _APP_CONSTS[name]
            except Exception:
                continue
    raise AssertionError("no literal constant %s in app.py" % name)


@unittest.skipIf(not APP_PY.is_file(), "app.py not beside the tests")
class TestNeitherRoadIsLiveByDesign(unittest.TestCase):
    """If either road were deliberately live-only, this fix would be wrong."""

    def test_neither_is_in_cannot_prepare(self):
        cannot = const_from_app("CANNOT_PREPARE")
        self.assertNotIn("station_id", cannot)
        self.assertNotIn("track_talk", cannot)

    def test_neither_is_on_the_short_horizon(self):
        short = const_from_app("PREP_SHORT_HORIZON")
        self.assertNotIn("station_id", short)
        self.assertNotIn("track_talk", short)

    def test_both_are_roads_the_preparer_knows_how_to_write(self):
        self.assertIn("station_id", const_from_app("ALT_PREP_KINDS"))
        self.assertIn("track_talk", const_from_app("ALT_PREP_KINDS"))

    def test_both_are_on_the_board_the_operator_watches(self):
        board = const_from_app("PREP_BOARD_KINDS")
        self.assertIn("station_id", board)
        self.assertIn("track_talk", board)

    def test_the_sheet_cannot_name_a_station_id_at_all(self):
        """The evidence, frozen: station_id has no schedule kind behind it."""
        self.assertNotIn("station_id", const_from_app("SCHED_PREP_KIND"))


if __name__ == "__main__":
    unittest.main()
