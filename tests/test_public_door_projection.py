"""[public-door] The listener door's cut of the station, without importing app.py.

tools/public_door_projection_patch.py. What is proved here, from the files as
they are on disk (app.py's text and the page inside it; system3_runtime.py
imported):

  * /api/dj through the door is an ALLOW list: exactly the keys the listener
    page reads (PAGE_READS - where each is read), leaves only, the chat's last
    rows as {id, ts, text, who}; no trace, prompt, persona, standing order,
    seed, config hash, model or setting survives it, lean or not;
  * every field the page reads is still there, with the value it had;
  * the page reads nothing else: the reader functions in RADIO_PAGE_HTML
    (sync, pineBuildWatch, pineReloadWatch, renderGallery, patter, patterKey,
    patterRow, s3Ask, paintMediaSession, retime) are scanned, and a new read
    fails here until it is allowed on purpose; car-diag.js, sfx-tv.js and
    tune-messenger.js do not fetch /api/dj at all;
  * /api/stream/state's door keys carry no listener, path or error;
  * /api/system3/public/lines carries no topic, CTS direction, FAV pick,
    speaker-box file or SFX intent word, while the desk's _compact() keeps
    them and the listener cut never shares the desk's cache.

Runs anywhere the repository is (python -m unittest
tests.test_public_door_projection); tests/test_public_door_projection_app.py is
the half that imports app (container only) and reuses the fixtures below.
PUBLIC_DOOR_ROOT points both at another tree (the scratch copy)."""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("PUBLIC_DOOR_ROOT") or Path(__file__).resolve().parent.parent)
APP_PY = ROOT / "app.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Markers planted where the station keeps what the door must never carry.
SECRETS = ("STANDING ORDERS FROM THE OPERATOR", "PERSONA-MARKER", "SYSTEM-PROMPT-MARKER",
           "SEED-MARKER", "CONFIG-HASH-MARKER", "QUERY-MARKER", "SCENARIO-MARKER",
           "ANALYSIS-MARKER", "WEATHER-MARKER", "MODEL-MARKER", "WORKER-ERROR-MARKER",
           "FLOW-MARKER", "PLAYBACK-MARKER", "VECTOR-MARKER", "UPCOMING-MARKER",
           "HISTORY-MARKER", "LAST-SAID-MARKER", "ACTIVITY-MARKER", "PULSE-MARKER",
           "LIBRARY-MARKER", "BOX-WHY-MARKER", "SELLING-MARKER", "RULE-MARKER",
           "REASON-MARKER", "MATCH-WHY-MARKER", "SOURCE-TEXT-MARKER", "/app/data/")
# Keys a listener's /api/dj answer may never hold, at any depth.
FORBIDDEN_KEYS = frozenset({"trace", "prompt", "persona", "cohost_persona", "system_prompt", "query",
                            "rule", "rule_id", "reason", "scenario", "model", "system3", "seed",
                            "config_hash", "analysis", "sfx_match_why", "source_text", "perf",
                            "dialogue_flow", "workers", "activity_log", "repair_log", "playback",
                            "vector_access", "admission", "stream_now", "last_said", "upcoming",
                            "history", "played", "box", "pulse", "library", "dj", "steward",
                            "comfy_doctor", "paper", "activity", "speaking_now", "selling_now",
                            "sfx_deleted", "airtime", "weather", "render", "written"})

# Where the listener page reads each field of /api/dj (RADIO_PAGE_HTML's
# inline script; nothing else public reads /api/dj).
PAGE_READS = {
    "build": "pineBuildWatch",
    "reload_at": "pineReloadWatch",
    "on": "sync (the dot, the title, the sub line, paintPaused)",
    "paused": "sync (the sub line, paintPaused, retime guard)",
    "elapsed": "sync (the clock, the progress bar)",
    "listeners": "sync (\"N listeners\")",
    "station": "sync (\"· <station>\")",
    "server_ms": "sync -> retime",
    "started_ms": "sync -> retime",
    "now.id": "sync (the sleeve), retime (the anchor key, the src)",
    "now.title": "sync, paintMediaSession",
    "now.artist": "sync, paintMediaSession",
    "now.art": "sync (the sleeve), paintMediaSession (artwork)",
    "now.seconds": "sync (the length, the bar) -> retime",
    "now.url": "sync (gate) -> retime (audio.src)",
    "gallery_now.images": "renderGallery",
    "chat[].id": "patterKey, s3Ask",
    "chat[].ts": "patterKey",
    "chat[].text": "patterKey, patterRow",
    "chat[].who": "patterRow",
}
READERS = ("sync", "pineBuildWatch", "pineReloadWatch", "renderGallery", "patter", "patterKey",
           "patterRow", "s3Ask", "paintMediaSession", "retime", "pollOnce")

_TEXT: list[str] = []


def app_text() -> str:
    if not _TEXT:
        _TEXT.append(APP_PY.read_bytes().decode("utf-8").replace("\r\n", "\n"))
    return _TEXT[0]


def load_projection() -> dict[str, Any]:
    """The door's allow lists and dj_state_public, exactly as app.py has them."""
    text = app_text()
    start = text.index("\n# --- [public-door] WHAT THE LISTENER DOOR MAY SEE OF THE STATE")
    end = text.index('\n@app.get("/api/dj")\n', start)
    lean = re.search(r"^DJ_LEAN_CHAT = (\d+)", text, re.M)
    ns: dict[str, Any] = {"Any": Any, "DJ_LEAN_CHAT": int(lean.group(1))}
    exec(compile(text[start:end], str(APP_PY), "exec"), ns)   # noqa: S102 - the file under test
    return ns


def page_script() -> str:
    text = app_text()
    i = text.index('\nRADIO_PAGE_HTML = r"""') + len('\nRADIO_PAGE_HTML = r"""')
    html = text[i:text.index('"""', i)]
    return "\n".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S))


def js_function(script: str, name: str) -> str:
    """The source of `function name(...) {...}` (braces balanced, strings and
    comments skipped well enough for this page)."""
    m = re.search(r"(?:async\s+)?function\s+%s\s*\(" % re.escape(name), script)
    if not m:
        raise AssertionError("the page has no function " + name)
    k, depth = m.end(), 1                  # past the parameters: `options = {}` is not the body
    while depth:
        depth += {"(": 1, ")": -1}.get(script[k], 0)
        k += 1
    i = script.index("{", k)
    depth, j, quote = 0, i, ""
    while j < len(script):
        c = script[j]
        if quote:
            if c == "\\":
                j += 2
                continue
            if c == quote:
                quote = ""
        elif script.startswith("//", j):
            j = script.index("\n", j)
            continue
        elif script.startswith("/*", j):
            j = script.index("*/", j) + 2
            continue
        elif c in "\"'`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return script[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced function " + name)


def chat_row(i: int, **extra: Any) -> dict[str, Any]:
    """A booth row as the ring holds one (the keys measured on the live
    station, 2026-09-28), secrets planted where the booth keeps them."""
    row = {
        "id": "%032x" % (0xabc000 + i), "ts": 1790590000 + i, "seq": i,
        "who": ("dj", "cohost", "board", "caller", "host", "analysis")[i % 6],
        "name": ("Host", "Skip", "Booth", "Zeppo", "", "Analysis")[i % 6],
        "kind": ("banter", "call", "sfx", "call", "call", "image_analysis")[i % 6],
        "text": "line %d as it aired" % i, "aired": "stream", "air_at": 1790590010.5 + i,
        "air_at_by": "stream", "voice": "vl_a5cc23e4", "engine": "xtts", "ms": 812,
        "round": "r-%d" % (i // 4), "turn": i % 4, "turns": 4, "media": "/media/%032x.wav?t=%s" % (i, "a" * 32),
        "clip_media": "/media/x.wav", "clip_sig": "b" * 32, "clip_from": 0.0, "clip_until": 4.2, "clip_tail": 0.3,
        "delivery_id": "d%05d" % i, "page_id": "p%d" % i, "page_audio": True, "page_delivery": "ended",
        "admission_occurrence": None, "heard_ack_at": 0, "heard_ack_by": "",
        "sfx": "%016x" % i, "sfx_dir": "samples/SFX", "sfx_sample_id": 44, "sfx_video_id": "", "sfx_video_seconds": 0,
        "sfx_match_why": "MATCH-WHY-MARKER: keyword 'chicken' in /samples/grabbed",
        "sfx_roll": {"dice": 42}, "fx": {"reverb": 0.2}, "repeat": False, "sid": "s%d" % i, "sig": "c" * 32,
        "poster": "/api/sfx/poster/%016x?t=%s" % (i, "d" * 32), "url": "/media/x.wav", "video": False,
        "image": "", "images": [], "image_analysis_ids": [],
        "analysis": {"text": "ANALYSIS-MARKER a painting of a pine"},
        "model": "MODEL-MARKER gemma4:e2b", "query": "QUERY-MARKER chicken tendo", "rule": "RULE-MARKER #843",
        "rule_id": "r843", "reason": "REASON-MARKER the round ran long", "scenario": "SCENARIO-MARKER the sewer",
        "source": "booth", "source_text": "SOURCE-TEXT-MARKER", "macro": "", "perf": {"emotion": "irritation"},
        "system3": {"conversation_id": "bed6c5244428435f", "mode": "active", "turn_id": "bed6c5244428435f:t00",
                    "road": "upstairs", "seed": "SEED-MARKER d82683e7", "config_hash": "CONFIG-HASH-MARKER 2861"},
        "trace": {"queued_at": 1790590000.2, "chars": 87, "kind": "banter", "burst": 3,
                  "weather": "WEATHER-MARKER rain over the funnel",
                  "render": {"voice": "vl_a5cc23e4", "engine": "xtts"},
                  "written": {"prompt": "SYSTEM-PROMPT-MARKER You are Skip, PERSONA-MARKER the co-host. "
                                        "STANDING ORDERS FROM THE OPERATOR: never name the owner.",
                              "model": "MODEL-MARKER"}},
    }
    row.update(extra)
    return row


def full_state(rows: int = 240) -> dict[str, Any]:
    """dj_state() as the station builds it (61 keys, measured 2026-09-28),
    with the house's secrets planted where the house keeps them."""
    return {
        "station": "itunes", "playing": True, "paused": False, "dj": True, "overlap": 35, "tip_delay_ms": 3000,
        "elapsed": 61.4, "server_ms": 1790593749613, "started_ms": 1790593688213, "queued": 7,
        "build": 1790579681228, "reload_at": 0, "kiosk_kick": 0.0,
        "now": {"id": "14474ac25ff6b218", "title": "Wondering (Dirtyphonics Remix)", "artist": "Does It Offend You, Yeah?",
                "album": "UKF Dubstep 2011", "ext": ".m4a", "seconds": 283.6, "station": "itunes",
                "mtime": 1652135085, "size": 10449947,
                "url": "/music/14474ac25ff6b218?t=1650efe5edab6c5fa63e7c3a8f95726e",
                "art": "/music/14474ac25ff6b218/art?t=1650efe5edab6c5fa63e7c3a8f95726e"},
        "coming": None, "on": True,
        "comfy_doctor": {"running": False, "started": 0.0, "verdict": ""},
        "steward": {"running": False, "started": 0.0, "verdict": "WORKER-ERROR-MARKER"},
        "paper": {"running": False, "started": 0.0, "latest": "2026-09-08-16", "headline": "x", "verdict": ""},
        "station_name": "Chicken Tendo Little Pine Box FM",
        "dj_names": {"host": "Host", "cohost": "Skip", "third": "", "guest": "", "sfx": "The SFX Guy"},
        "remaining": 222.2,
        "upcoming": [{"id": "u1", "title": "UPCOMING-MARKER", "url": "/music/u1?t=x", "art": "/music/u1/art?t=x"}],
        "requests": 0, "music_to": "here", "voice_to": "box", "voice_device": "nabu",
        "nabu_music_level": 0.4, "nabu_voice_level": 0.5, "nabu_reply_level": 0.5, "reply_to": "box",
        "box_talk": True, "monitor": False,
        "gallery_now": {"images": ["PineBox_00232_.png", "PineBox_00233_.png"]},
        "ad_now": None,
        "selling_now": {"kind": "gallery", "why": "SELLING-MARKER the pair have it up", "image": "PineBox_00232_.png"},
        "sfx_deleted": [{"id": "a3864f66667f14bc", "name": "146 clip", "at": 1790252242.4, "lines": []}],
        "box": {"off": True, "down": False, "held": 0, "floor": "a booth round", "floor_for": 207,
                "why": "BOX-WHY-MARKER voice output is routed to 'here'", "overridden": None},
        "pulse": "PULSE-MARKER 1 stall(s) in the last 10 min - mostly _row_clip_keys",
        "library": "LIBRARY-MARKER 9624 KB/s off the share",
        "activity": {"stage": "voicing", "detail": "xtts", "text": "ACTIVITY-MARKER", "speaker": "Caller"},
        "activity_log": [{"stage": "writing", "detail": "SYSTEM-PROMPT-MARKER"}],
        "output": "here", "listeners": 4,
        "history": [{"id": "h1", "title": "HISTORY-MARKER"}],
        "played": [{"id": "h1", "title": "HISTORY-MARKER"}],
        "last_said": {"text": "LAST-SAID-MARKER"},
        "speaking": True,
        "speaking_now": {"id": "86a5", "who": "board", "text": "\U0001f50a 2109", "aired": "airing"},
        "talk_next_in": None,
        "dialogue_flow": {"why": "FLOW-MARKER the writer is behind"},
        "workers": {"workers": [{"name": "ad", "last_error": "WORKER-ERROR-MARKER"}]},
        "model": "MODEL-MARKER gemma4:e2b",
        "chat": [chat_row(i) for i in range(rows)],
        "stream_now": {"at": 1.0, "length": 9.0, "rows": [{"id": "x", "text": "t"}]},
        "admission": {"available": False, "occurrences": [], "mode": "off", "why": "switched off"},
        "vector_access": [{"query": "VECTOR-MARKER", "at": 1.0}],
        "repairing": None, "repair_log": [{"what": "WORKER-ERROR-MARKER"}],
        "airtime": {"delivered": 0.9},
        "playback": {"listeners": {"x": {"ua": "PLAYBACK-MARKER", "addr": "/app/data/"}}},
    }


def walk_keys(value: Any, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            out.append(path + "." + str(k))
            out.extend(walk_keys(v, path + "." + str(k)))
    elif isinstance(value, list):
        for v in value:
            out.extend(walk_keys(v, path + "[]"))
    return out


def read_path(state: dict[str, Any], path: str) -> list[Any]:
    """The values at a PAGE_READS path ("chat[].id" -> one per row)."""
    if path.startswith("chat[]."):
        key = path[len("chat[]."):]
        return [row[key] for row in state["chat"]]
    head, _, tail = path.partition(".")
    got = state[head]
    return [got[tail]] if tail else [got]


class TheStateCut(unittest.TestCase):
    """dj_state_public: the allow list, and only the allow list."""

    @classmethod
    def setUpClass(cls):
        cls.ns = load_projection()
        cls.cut = staticmethod(cls.ns["dj_state_public"])

    def test_it_answers_with_the_allow_list_and_nothing_else(self):
        out = self.cut(full_state())
        self.assertEqual(set(out), set(self.ns["DJ_PUBLIC_KEYS"]) | {"now", "gallery_now", "chat"})
        self.assertEqual(set(out["now"]), set(self.ns["DJ_PUBLIC_NOW"]))
        self.assertEqual(out["gallery_now"], {"images": ["PineBox_00232_.png", "PineBox_00233_.png"]})
        for row in out["chat"]:
            self.assertEqual(set(row), set(self.ns["DJ_PUBLIC_CHAT"]))

    def test_no_secret_survives_it(self):
        state = full_state()
        self.assertTrue(all(s in json.dumps(state) for s in SECRETS), "the fixture plants every marker")
        blob = json.dumps(self.cut(state), ensure_ascii=False)
        for secret in SECRETS:
            self.assertNotIn(secret, blob)
        keys = {p.rsplit(".", 1)[-1] for p in walk_keys(self.cut(state))}
        self.assertFalse(keys & FORBIDDEN_KEYS, keys & FORBIDDEN_KEYS)

    def test_every_field_the_page_reads_is_there_with_its_value(self):
        state = full_state()
        out = self.cut(state)
        tail = dict(state, chat=state["chat"][-self.ns["DJ_LEAN_CHAT"]:])
        for path, where in PAGE_READS.items():
            self.assertEqual(read_path(out, path), read_path(tail, path), "%s (read in %s)" % (path, where))

    def test_the_chat_is_the_last_rows_in_order(self):
        state = full_state()
        out = self.cut(state)
        n = self.ns["DJ_LEAN_CHAT"]
        self.assertEqual(n, 20)
        self.assertEqual([r["id"] for r in out["chat"]], [r["id"] for r in state["chat"][-n:]])
        self.assertEqual(self.cut(full_state(rows=3))["chat"], [
            {k: r[k] for k in ("id", "ts", "text", "who")} for r in full_state(rows=3)["chat"]])

    def test_a_structure_under_an_allowed_name_stays_in_the_house(self):
        state = full_state()
        state["now"]["title"] = {"prompt": "SYSTEM-PROMPT-MARKER"}
        state["listeners"] = ["PLAYBACK-MARKER"]
        state["chat"][-1]["text"] = {"trace": "SYSTEM-PROMPT-MARKER"}
        state["gallery_now"] = {"images": ["a.png", {"x": "SELLING-MARKER"}, ""]}
        out = self.cut(state)
        self.assertIsNone(out["now"]["title"])
        self.assertIsNone(out["listeners"])
        self.assertIsNone(out["chat"][-1]["text"])
        self.assertEqual(out["gallery_now"], {"images": ["a.png"]})
        self.assertNotIn("MARKER", json.dumps(out))

    def test_off_air_and_nothing_hanging(self):
        state = full_state(rows=0)
        state.update(now=None, gallery_now=None, on=False)
        out = self.cut(state)
        self.assertIsNone(out["now"])
        self.assertIsNone(out["gallery_now"])
        self.assertEqual(out["chat"], [])
        self.assertIs(out["on"], False)
        self.assertEqual(self.cut({}), {"now": None, "gallery_now": None, "chat": []})

    def test_the_cut_is_small(self):
        full = len(json.dumps(full_state()))
        cut = len(json.dumps(self.cut(full_state())))
        self.assertLess(cut * 20, full, (cut, full))

    def test_the_stream_state_keys_name_no_listener(self):
        keys = set(self.ns["STREAM_PUBLIC_KEYS"])
        self.assertFalse(keys & {"hls_listeners", "listener_rows", "recent_sessions", "hls", "rates"})
        self.assertTrue({"running", "listeners"} <= keys)


class ThePageReadsNothingElse(unittest.TestCase):
    """RADIO_PAGE_HTML is the only public reader of /api/dj; a new read on it
    fails here until the door allows it on purpose."""

    @classmethod
    def setUpClass(cls):
        cls.ns = load_projection()
        cls.script = page_script()
        cls.src = {name: js_function(cls.script, name) for name in READERS}

    def test_one_fetch_and_four_readers(self):
        fetches = re.findall(r"""api\(\s*["'`]/api/dj(?:[?"'`])""", self.script)
        self.assertEqual(len(fetches), 1, fetches)
        poll = self.src["pollOnce"]
        self.assertIn('await api("/api/dj?lean=1&listener=" + ME)', poll)
        self.assertEqual(sorted(re.findall(r"(\w+)\(state\)", poll)),
                         ["paintMediaSession", "patter", "renderGallery", "sync"])

    def test_every_state_read_is_allowed(self):
        top = set(self.ns["DJ_PUBLIC_KEYS"]) | {"now", "gallery_now", "chat"}
        seen = set()
        for name, body in self.src.items():
            for key in re.findall(r"\(state \|\| \{\}\)\.(\w+)|\bstate\.(\w+)|state && state\.(\w+)", body):
                seen |= {k for k in key if k}
        self.assertTrue(seen, "the scan found the reads")
        self.assertEqual(seen - top, set(), "read by the page, not on the door's allow list")
        self.assertEqual({p.split(".")[0].split("[")[0] for p in PAGE_READS}, seen,
                         "PAGE_READS names every top-level read")

    def test_every_now_read_is_allowed(self):
        now = set()
        for name in ("sync", "retime", "paintMediaSession"):
            now |= set(re.findall(r"\bnow\.(\w+)", self.src[name]))
        self.assertEqual(now - set(self.ns["DJ_PUBLIC_NOW"]), set())
        self.assertEqual(now, {p.split(".", 1)[1] for p in PAGE_READS if p.startswith("now.")})

    def test_every_row_read_is_allowed(self):
        rows = set()
        for name in ("patter", "patterKey", "patterRow"):
            rows |= set(re.findall(r"\bline\.(\w+)", self.src[name]))
        rows |= set(re.findall(r"\br\.(\w+)", self.src["s3Ask"].split(".then(")[0]))
        self.assertEqual(rows - set(self.ns["DJ_PUBLIC_CHAT"]), set())
        self.assertEqual(rows, {p.split(".", 1)[1] for p in PAGE_READS if p.startswith("chat[].")})
        gallery = set(re.findall(r"state\.gallery_now\.(\w+)", self.src["renderGallery"]))
        self.assertEqual(gallery, {"images"})

    def test_the_other_public_modules_never_fetch_the_state(self):
        for rel in ("frontend/car-diag.js", "desktop/renderer/sfx-tv.js", "frontend/tune-messenger.js"):
            path = ROOT / rel
            if not path.is_file():
                self.skipTest(rel + " is not in this tree")
            body = path.read_text(encoding="utf-8")
            self.assertEqual(re.findall(r"""/api/dj(?=[?"'`])""", body), [], rel)


class TheListenerFeedCut(unittest.TestCase):
    """/api/system3/public/lines: the dice and the turn's shape, never the
    road's prompt, the running order's direction, the operator's favourites,
    the speaker box's files or the SFX intent words."""

    @classmethod
    def setUpClass(cls):
        import system3_runtime
        cls.mod = system3_runtime

    def runtime(self, conv):
        rt = object.__new__(self.mod.System3Runtime)
        rt.store = FakeStore({conv["identity"]["conversation_id"]: conv})
        return rt

    def test_the_listener_cut(self):
        conv = conversation()
        cut = self.runtime(conv)._listener_compact(copy.deepcopy(conv))
        blob = json.dumps(cut)
        for secret in S3_SECRETS:
            self.assertNotIn(secret, blob)
        self.assertNotIn("topic", cut)
        t0 = cut["turns"]["c0ffee01:t00"]
        rolls = {r["family"]: r for r in t0["rolls"]}
        self.assertEqual(set(rolls), {"CTS", "ES", "FAV", "SPEAKERBOX", "SFX"})   # DIRECTIVE dropped
        self.assertEqual(rolls["CTS"]["label"], "the step as planned")
        self.assertEqual(rolls["CTS"]["reel"], [])
        self.assertEqual(rolls["FAV"]["label"], "a favourite")
        self.assertEqual(rolls["FAV"]["reel"], [])
        self.assertEqual(rolls["FAV"]["dice"], 7)
        self.assertEqual((rolls["ES"]["label"], rolls["ES"]["dice"], rolls["ES"]["reel"]),
                         ("anger", 42, ["joy", "anger"]))
        self.assertEqual(rolls["SPEAKERBOX"]["rule"], "hit when the d100 lands above 32 (68% slider)")
        self.assertEqual(t0["speakerbox"], [{"mode": "APPEND"}])
        self.assertEqual(t0["sfx"], {"play": True, "placement": "after"})
        self.assertEqual((t0["name"], t0["step"], t0["phase"]), ("Host", "The lead", "OPEN"))
        t1 = cut["turns"]["c0ffee01:t01"]
        self.assertEqual([r["label"] for r in t1["rolls"] if r["family"] == "FAV"], ["no favourite this time"])

    def test_the_desk_keeps_its_reading(self):
        conv = conversation()
        desk = self.runtime(conv)._compact(copy.deepcopy(conv))
        self.assertIn("ROAD-PROMPT-MARKER", desk["topic"])
        rolls = {r["family"]: r for r in desk["turns"]["c0ffee01:t00"]["rolls"]}
        self.assertIn("OPERATOR-FAVOURITE-MARKER", rolls["FAV"]["label"])
        self.assertIn("DIRECTION-MARKER", rolls["CTS"]["label"])
        self.assertIn("DIRECTIVE", rolls)

    def test_public_lines_answers_from_its_own_cut_and_cache(self):
        conv = conversation()
        rt = self.runtime(conv)
        rt._compact_cached("c0ffee01")                   # the desk warms ITS cache first
        self.assertIn("c0ffee01", rt.__dict__["_public_cache"])
        got = rt.public_lines(["line00000000", "line00000001", "notalinexx"])
        self.assertEqual([g["system3"] for g in got], [True, True, False])
        blob = json.dumps(got)
        for secret in S3_SECRETS:
            self.assertNotIn(secret, blob)
        self.assertTrue(all("topic" not in g for g in got))
        self.assertEqual(got[0]["turn"]["rolls"][0]["label"], "the step as planned")
        self.assertIn("c0ffee01", rt.__dict__["_listener_cache"])
        # ...and the desk's entry is still the desk's
        self.assertIn("ROAD-PROMPT-MARKER", rt.__dict__["_public_cache"]["c0ffee01"][1]["topic"])


def html_literal(name: str) -> str:
    text = app_text()
    i = text.index('\n%s = r"""' % name) + len('\n%s = r"""' % name)
    return text[i:text.index('"""', i)]


class TheLinkThatRanOut(unittest.TestCase):
    """2026-09-28: a remote listener "can't hear" - his link had expired, and
    the page said nothing. One sentence everywhere; the page asks the station
    when any road refuses it; a notice before; the panel marks what ran out."""

    @classmethod
    def setUpClass(cls):
        cls.ns = load_projection()
        cls.script = page_script()

    def test_one_sentence_wherever_a_listener_meets_it(self):
        say = self.ns["LINK_GONE_SAY"]
        self.assertEqual(say, "This link has expired - ask the station for a new one.")
        page = re.search(r'var LINK_GONE_SAY = "([^"]+)";', self.script)
        self.assertEqual(page.group(1), say, "the tune page says what /tune/ says")
        html = self.ns["LINK_GONE_HTML"]
        self.assertEqual(html.count(say), 1)
        self.assertTrue(html.lstrip().startswith("<!doctype html>"))
        for leak in ("__SAY__", "detail", "revoked", "token", "<script", "http"):
            self.assertNotIn(leak, html, leak)
        self.assertNotIn("{", html.split("<body>", 1)[1], "no data in the body")

    def test_every_road_that_refuses_the_link_asks_the_station(self):
        api = js_function(self.script, "api")
        self.assertIn("if (linkGone) throw new Error(LINK_GONE_SAY);", api.split("let url = path;")[0])
        self.assertRegex(api, r"response\.status === 401 \|\| response\.status === 403\)\s*"
                              r"&& String\(path\)\.indexOf\(\"/api/pinelink/\"\) !== 0\) linkSuspect\(path\);")
        probe = js_function(self.script, "streamProbe")
        self.assertIn('if (r.status === 401 || r.status === 403) linkSuspect("stream");', probe)
        suspect = js_function(self.script, "linkSuspect")
        self.assertIn('fetch("/api/listen/link?t=" + encodeURIComponent(KEY)', suspect)
        self.assertIn("< 15000", suspect)
        self.assertIn("linkGoneShow(why)", suspect)
        gone = js_function(self.script, "linkGoneShow")
        self.assertIn("if (playing) tune();", gone)
        self.assertIn("box.textContent = LINK_GONE_SAY;", gone)

    def test_the_notice_reads_the_pass_itself(self):
        exp = js_function(self.script, "linkExpiresMs")
        self.assertIn(r"/^(\d{9,11})\./", exp)
        notice = js_function(self.script, "linkNotice")
        self.assertIn("LINK_WARN_DAYS * 86400000", notice)
        self.assertEqual(re.search(r"var LINK_WARN_DAYS = (\d+);", self.script).group(1), "3")

    def test_the_panel_marks_the_links_that_ran_out(self):
        panel = html_literal("CONTROL_PANEL_HTML")
        start = panel.index("async function remotePanel() {")
        body = panel[start:panel.index("\nasync function ", start + 10)]
        draw = body[body.index("const drawLinks = async () => {"):body.index("await drawLinks();")]
        self.assertIn("(got.expired || []).forEach((l) => {", draw)
        self.assertIn('el("span", "", "EXPIRED")', draw)
        self.assertIn('line.dataset.expired = "1";', draw)
        self.assertIn("text-decoration:line-through", draw)
        self.assertIn('api("/api/share/revoke"', draw.split("(got.expired || [])")[1])


S3_SECRETS = ("ROAD-PROMPT-MARKER", "DIRECTION-MARKER", "OPERATOR-FAVOURITE-MARKER",
              "OTHER-FAVOURITE-MARKER", "DIRECTIVE-MARKER", "secret_material.md", "MATERIAL-MARKER",
              "intentmarker")


def conversation() -> dict[str, Any]:
    """A System 3 round with every kind of decision a listener must not read."""
    cid = "c0ffee01"
    events = [
        {"event_id": "e-cts", "family": "CTS", "turn_id": cid + ":t00", "rng": {"dice": 12},
         "selected": {"id": "row7", "label": "DIRECTION-MARKER Coming back off that spot, one of you WONDERS ALOUD"},
         "stages": []},
        {"event_id": "e-es", "family": "ES", "turn_id": cid + ":t00",
         "selected": {"id": "anger", "label": "anger", "category_label": "ANGER", "table": "ES1", "intensity": 0.7},
         "stages": [{"stage": "item", "candidates": [{"id": "joy", "label": "joy"}, {"id": "anger", "label": "anger"}],
                     "selected_index": 2, "of": 2, "draw": {"dice": 42}}]},
        {"event_id": "e-fav", "family": "FAV", "turn_id": cid + ":t00",
         "selected": {"id": "fav3", "label": "OPERATOR-FAVOURITE-MARKER a GTA chase", "table": "FAV1",
                      "category_label": "OPERATOR-FAVOURITE-MARKER"},
         "stages": [{"stage": "dice", "draw": {"dice": 7}, "rule": "a favourite when d100 <= 20", "selected": "PICK"},
                    {"stage": "item", "candidates": [{"id": "fav1", "label": "OTHER-FAVOURITE-MARKER"},
                                                     {"id": "fav3", "label": "OPERATOR-FAVOURITE-MARKER a GTA chase"}],
                     "selected_index": 2, "of": 2}]},
        {"event_id": "e-dir", "family": "DIRECTIVE", "turn_id": cid + ":t00",
         "selected": {"id": "d1", "label": "DIRECTIVE-MARKER keep it clean"}, "stages": []},
        {"event_id": "e-sb", "family": "SPEAKERBOX", "turn_id": cid + ":t00",
         "selected": {"id": "append", "label": "append"},
         "stages": [{"stage": "dice", "draw": {"dice": 60}, "selected": "HIT",
                     "rule": "hit when the d100 lands above 32 (68% slider)"}]},
        {"event_id": "e-sfx", "family": "SFX", "turn_id": cid + ":t00",
         "selected": {"id": "play", "label": "play after the line"},
         "stages": [{"stage": "dice", "draw": {"dice": 30}, "selected": "PLAY", "rule": "a clip when u < 0.65"}]},
        {"event_id": "e-fav0", "family": "FAV", "turn_id": cid + ":t01",
         "selected": {"id": "NONE", "label": "no favourite this time"},
         "stages": [{"stage": "dice", "draw": {"dice": 88}, "selected": "MISS"}]},
    ]
    turns = [
        {"turn_id": cid + ":t00", "index": 0, "speaker": "A", "name": "Host", "step_label": "The lead",
         "phase": "OPEN", "performance": {"emotion": "anger", "intensity": 0.7, "pace": 1.1, "pause_style": "clipped"},
         "decisions": [{"event_id": "e-cts"}, {"event_id": "e-es"}, {"event_id": "e-fav"}, {"event_id": "e-dir"}],
         "speakerbox": [{"mode": "APPEND", "event_id": "e-sb",
                         "material": {"file": "secret_material.md", "passage": "MATERIAL-MARKER"}}],
         "sfx": {"play": True, "placement": "after", "intent": ["intentmarker", "outrage"], "event_id": "e-sfx"}},
        {"turn_id": cid + ":t01", "index": 1, "speaker": "B", "name": "Skip", "step_label": "Reacts to the lead",
         "phase": "DEVELOP", "performance": {"emotion": "joy"}, "decisions": [{"event_id": "e-fav0"}],
         "speakerbox": [], "sfx": {"play": False, "placement": None, "intent": ["intentmarker"]}},
    ]
    return {"identity": {"conversation_id": cid, "road_kind": "news"}, "mode": "active", "status": "bound",
            "subject": {"topic": "ROAD-PROMPT-MARKER A news moment between records, like a late-night podcast",
                        "category": "news", "keywords": ["pine"]},
            "turns": turns, "decision_events": events,
            "lines": [{"line_id": "line0000000%d" % i, "turn_id": turns[i]["turn_id"], "text": "w"} for i in range(2)]}


class FakeStore:
    def __init__(self, convs):
        self.convs = convs

    def conversation(self, cid, with_events=True):
        got = self.convs.get(cid)
        return copy.deepcopy(got) if got else None

    def line(self, lid):
        for conv in self.convs.values():
            for ln in conv.get("lines") or []:
                if ln["line_id"] == lid:
                    return {"conversation_id": conv["identity"]["conversation_id"], "turn_id": ln["turn_id"],
                            "line_id": lid}
        return None


if __name__ == "__main__":
    unittest.main()
