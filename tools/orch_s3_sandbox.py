"""[orch-s3] A sandbox station for the orchestrator's System 3 desk - and the
three proofs the operator asked for, end to end, on nothing live.

    PYTHONPATH=tests:. python3 tools/orch_s3_sandbox.py      (from a DRY tree)

Everything here is a temp directory: a real origin ledger (system3_origin's
OriginLedger on a temp sqlite), a real System 3 config (system3.default_config
behind a store that versions by hash the way System3Store does), real
line_story and sfx_display readers over temp stores, and the cupboard's doors
as recorders. It never imports app.py and never touches /app/data.

  1. an Untraced line  - identify (why #code), triage, the ask, the answer
  2. a rogue produced ad - the alarm, its legacy stock nominated, confirm, undo
  3. a cupboard item to shelve / retire, and a table edit - review, confirm, undo
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import orchestrator_s3 as os3  # noqa: E402
import system3  # noqa: E402
import system3_origin as so  # noqa: E402

T0 = time.time() - 1800.0


class FakeStore:
    """System3Store's config half: versions by hash, INSERT OR IGNORE."""

    def __init__(self, config: dict[str, Any]):
        self.bodies: dict[str, Any] = {}
        self.versions: list[dict[str, Any]] = []
        self.save_config(config, "sandbox start")

    def save_config(self, config: dict[str, Any], note: str = "") -> str:
        h = system3.config_hash(config)
        if h not in self.bodies:
            self.bodies[h] = copy.deepcopy(config)
            self.versions.append({"hash": h, "created": time.time(), "note": note})
        return h

    def config_by_hash(self, h: str) -> Any:
        return copy.deepcopy(self.bodies.get(h))

    def config_versions(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(reversed(self.versions))[:limit]


class FakeRuntime:
    def __init__(self) -> None:
        self.config = system3.default_config()
        self.settings = {"mode": "active", "roads": ["banter", "caller"]}
        self.store = FakeStore(self.config)
        self.logs: list[str] = []
        self.ready = True

    def log(self, text: str, extra: str = "") -> None:
        self.logs.append(text)


def _jl(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _rogue(led: Any, lid: str, at: float, road: str, producer: str, path: str, text: str) -> None:
    rec = {"schema": so.SCHEMA, "line_id": lid, "air_at": at, "road": road, "verdict": "rogue",
           "why": "no System 3 stamp", "kind": road, "who": "dj", "text": text, "producer": producer,
           "path": path, "rogue": {"path": path}}
    led.db.execute("INSERT INTO origin(line_id, air_at, day, road, verdict, kind, who, producer, why, settled, "
                   "compact, updated) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
                   (lid, at, so.day_of(at), road, "rogue", road, "dj", producer, rec["why"], so._pack(rec), at))


def build(root: Path) -> dict[str, Any]:
    """The sandbox station. Returns the namespace; `calls` records every door."""
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    calls: list[tuple[str, Any]] = []
    now = time.time()
    untraced = [("2e69c8deefb941acb499661390c6127a", "But what if it's important? Ashley, maybe it is."),
                ("47acbcbc52214dcaac53c1ce148beb9c", "Don't tell me another memo, you know."),
                ("cdb3ea55980644659c9693e048df8a70", "Another memo from upstairs, great.")]
    ads = [("a1d0000000000000000000000000beef", "Pine Mattress Barn - where sleep goes to retire."),
           ("a2d0000000000000000000000000beef", "Pine Mattress Barn, open till nine.")]
    led = so.OriginLedger(data / "system3_origin.sqlite3")
    for i, (lid, text) in enumerate(untraced):
        _rogue(led, lid, now - 600 + i, "interject", "page_recovery_chat_rows",
               "page_recovery_chat_rows<page_recovery_start<_radio_worker<run<run", text)
    for i, (lid, text) in enumerate(ads):
        _rogue(led, lid, now - 300 + i, "ad", "ad_break_legacy", "ad_break_legacy<ad_break<_radio_worker", text)
    led.db.commit()
    air = [{"id": lid, "ts": int(now - 600 + i), "air_at": now - 600 + i, "who": "dj", "kind": "interject",
            "text": text, "aired": "stream"} for i, (lid, text) in enumerate(untraced)]
    air += [{"id": lid, "ts": int(now - 300 + i), "air_at": now - 300 + i, "who": "dj", "kind": "ad",
             "text": text, "aired": "stream"} for i, (lid, text) in enumerate(ads)]
    _jl(data / "air_log.jsonl", air)

    shelf = {
        "ad": [{"id": "ad-legacy01", "text": "Pine Mattress Barn - the long read.", "aired": 0, "at": now - 9000},
               {"id": "ad-legacy02", "text": "Pine Mattress Barn - the short read.", "aired": 0, "at": now - 8000},
               {"id": "ad-s3stamp1", "text": "Rolled by System 3.", "aired": 0, "at": now - 100,
                "system3": {"conversation_id": "c0ffee", "mode": "active", "road": "ad"}}],
        "gallery": [{"id": "gallery-old001", "text": "A painting nobody finished recording.", "aired": 0,
                     "at": now - 4 * 86400, "part": True},
                    {"id": "gallery-ready1", "text": "A finished painting round.", "aired": 0, "at": now - 7300,
                     "system3": {"conversation_id": "beaded", "mode": "active", "road": "gallery"}}],
    }

    def cupboard_find(rid: str):
        for kind, rows in shelf.items():
            for r in rows:
                if r.get("id") == rid:
                    return kind, r
        return "", None

    def cupboard_why_row(kind: str, row: dict[str, Any]) -> dict[str, Any]:
        part = bool(row.get("part"))
        return {"id": row["id"], "kind": kind, "ready": not part, "blocked": part, "aired": row.get("aired"),
                "age": now - float(row.get("at") or now), "text": row.get("text"),
                "reasons": [{"code": "part_recorded" if part else "never_asked_for",
                             "say": "half its lines have no audio" if part else "finished; no road asked for it"}]}

    def bank_s3_of(row: Any) -> dict[str, Any]:
        s = row.get("system3") if isinstance(row, dict) else None
        return s if isinstance(s, dict) and s.get("conversation_id") and s.get("mode") == "active" else {}

    rec = lambda name: (lambda *a, **k: calls.append((name, a)) or True)  # noqa: E731

    async def pine_append(text: str) -> dict[str, Any]:
        calls.append(("pine_append", (text,)))
        return {"id": len(calls)}

    def fire_and_forget(coro: Any) -> None:
        try:
            asyncio.get_running_loop()
            asyncio.ensure_future(coro)
        except RuntimeError:
            asyncio.run(coro) if asyncio.iscoroutine(coro) else None

    asks: list[dict[str, Any]] = []

    def orch_raise(topic, why, urgency, questions):
        row = {"id": "ask%d" % len(asks), "topic": topic, "why": why, "urgency": urgency, "questions": questions}
        asks.append(row)
        return row

    rt = FakeRuntime()
    ns: dict[str, Any] = {
        "data_path": lambda *p: data.joinpath(*p),
        "AIR_LOG_PATH": data / "air_log.jsonl",
        "_ORIGIN_LEDGER": led,
        "_SYSTEM3_RUNTIME": rt,
        "_RADIO": {"on": True, "chat": []},
        "radio_paused": lambda: False,
        "_SHELF": shelf, "_LARDER": [],
        "shelf_rows": lambda k: shelf.setdefault(k, []),
        "cupboard_find": cupboard_find, "cupboard_why_row": cupboard_why_row, "bank_s3_of": bank_s3_of,
        "row_unaired": lambda r: not int(r.get("aired") or 0),
        "unheard_state": lambda: {"unheard": 4, "ready": 3},
        "retire_may": lambda kind, row, why="": calls.append(("retire_may", (kind, row["id"], why))) or False,
        "retire_decide": lambda ids, action, ext=None: calls.append(("retire_decide", (ids, action))) or {
            "say": "%s: %s" % (action, ",".join(ids))},
        "cupboard_finish_add": lambda kind, row, why="": calls.append(("cupboard_finish_add", (kind, row["id"]))) or {
            "ok": True, "say": "queued for the recording room"},
        "_pantry_save": rec("_pantry_save"),
        "sfx_mp4_only": lambda: True, "sfx_video_share": lambda: 100,
        "_MP4ONLY": {"refused": 4, "swapped": 1, "left_empty": 0, "quarantined": 0, "by_road": {}},
        "_SFX_QUARANTINED": {"q1", "q2", "q3"}, "_SFX_GONE_FOLDERS": set(),
        "_sfx_quarantine_path": lambda: data / "sfx_quarantine.jsonl", "_sfx_quarantine_load": lambda: None,
        "sfx_quarantine": lambda sid, why, path=None, by="": calls.append(("sfx_quarantine", (sid, why))) or True,
        "air_receivers_state": lambda: {"receivers": [
            {"id": "pinetab", "label": "PineTab", "sounding": True, "audible": True, "owns_air": True, "present": True},
            {"id": "desktop", "label": "This app", "sounding": False, "audible": False, "present": True}]},
        "_gap_log_read": lambda: [],
        "script_ledger_rows": lambda: [{"block": 9, "ord": 0, "at": time.time() - 60, "line_id": "abcd1234"}],
        "orch_raise": orch_raise, "_orch_recent": lambda topic, within=0: any(a["topic"] == topic for a in asks),
        "_opt": lambda face, does, note="": {"face": face, "does": does, "note": note},
        "pine_append": pine_append, "fire_and_forget": fire_and_forget,
    }
    try:
        import sfx_display
        ns["_SFX_DISPLAY_STORE"] = sfx_display.ReceiptStore(data / sfx_display.STORE_NAME)
    except Exception:  # noqa: BLE001
        pass
    ns["_calls"], ns["_asks"], ns["_rt"], ns["_ledger"] = calls, asks, rt, led
    ns["_desk"] = os3.Desk(ns, data / os3.LEDGER_NAME)
    return ns


def say(*a: Any) -> None:
    print(*a)


def cmd(desk: Any, text: str) -> tuple[bool, str, list[str]]:
    ok, s, lines = asyncio.run(desk.command(text))
    say("$ s3 %s\n  %s%s" % (text, s, "".join("\n    " + ln for ln in lines[:10])))
    return ok, s, lines


def decide_alone(desk: Any, ask: dict[str, Any]) -> str:
    """orch_decide_alone's rule: the FIRST option of each question, alone=True."""
    does = ask["questions"][0]["options"][0]["does"]
    verb, _, arg = does.partition(":")
    got = desk.verb(verb, arg, alone=True)
    say("  (nobody answered) station takes option 1 %s -> %s" % (does, got))
    return got


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        ns = build(Path(t))
        desk, calls, rt = ns["_desk"], ns["_calls"], ns["_rt"]
        say("=== the survey (his tick, on a worker thread in the station) ===")
        cmd(desk, "survey")

        say("\n=== PROOF 2 first, because it is the worst: a rogue produced ad ===")
        a1 = desk.ask()
        say("ASK raised: topic=%s urgency=%s\n  why: %s" % (a1["topic"], a1["urgency"], a1["why"][:400]))
        for o in a1["questions"][0]["options"]:
            say("  option: %-70s %s" % (o["face"][:70], o["does"]))
        decide_alone(desk, a1)
        say("  inbox filed: %d item(s)" % sum(1 for c in calls if c[0] == "pine_append"))
        again = desk.verb("s3file", a1["questions"][0]["options"][0]["does"].split(":")[1], alone=True)
        say("  filing again the same day -> %s" % again)
        rogue = next(f for f in desk.memo["value"]["findings"] if f["class"] == "rogue")
        for pid in rogue["proposals"]:
            p = desk.find_proposal(pid)
            say("  proposal %s: %s (station_may=%s)" % (pid, p["title"], p["station_may"]))
        pid = rogue["proposals"][0]
        say("  station alone confirms %s -> %s" % (pid, desk.verb("s3fix", pid, alone=True)))
        say("  retirement desk door called: %s" % [c for c in calls if c[0] == "retire_may"])
        say("  operator undoes it -> %s" % desk.undo(pid)["say"])
        rm = desk.propose_cupboard("ad-legacy02", "remove", by="orchestrator")
        say("  a REMOVE proposal %s, station alone -> %s" % (rm["id"], desk.verb("s3fix", rm["id"], alone=True)))

        say("\n=== PROOF 1: an Untraced line ===")
        a2 = desk.ask()
        say("ASK raised: topic=%s urgency=%s\n  why: %s" % (a2["topic"], a2["urgency"], a2["why"][:400]))
        for o in a2["questions"][0]["options"]:
            say("  option: %-70s %s" % (o["face"][:70], o["does"]))
        un = next(f for f in desk.memo["value"]["findings"] if f["class"] == "untraced")
        say("  identify:", un["identify"])
        cmd(desk, un["identify"][0])
        cmd(desk, "untraced")
        decide_alone(desk, a2)
        say("  the operator answers option 2 instead -> %s" % desk.verb("s3file", un["id"]))

        say("\n=== PROOF 3: a cupboard item to shelve / retire, and a table ===")
        cmd(desk, "cupboard")
        cmd(desk, "cupboard gallery")
        ok, s, _ = cmd(desk, "cupboard gallery-old001 finish")
        fin = s.split()[1].rstrip(":")
        say("  station alone -> %s" % desk.verb("s3fix", fin, alone=True))
        cmd(desk, "confirm %s" % fin)
        ok, s, _ = cmd(desk, "cupboard gallery-ready1 cue")
        cue = s.split()[1].rstrip(":")
        cmd(desk, "confirm %s" % cue)
        say("  cue_at on the row: %s" % bool(ns["_SHELF"]["gallery"][1].get("cue_at")))
        cmd(desk, "undo %s" % cue)
        say("  cue_at after undo: %s" % bool(ns["_SHELF"]["gallery"][1].get("cue_at")))
        ok, s, _ = cmd(desk, "cupboard gallery-old001 retire")
        ret = s.split()[1].rstrip(":")
        cmd(desk, "confirm %s" % ret)
        es = next(x for x in rt.config["tables"] if x.get("categories"))
        cat = es["categories"][0]
        key = "odds" if "odds" in cat else "weight"
        ok, s, lines = cmd(desk, "table %s set categories.%s.%s=%s" % (es["id"], cat["id"], key,
                                                                          round(float(cat.get(key) or 1) + 0.5, 2)))
        tp = s.split()[1]
        before = system3.config_hash(rt.config)
        say("  station alone -> %s" % desk.verb("s3fix", tp, alone=True))
        cmd(desk, "confirm %s" % tp)
        after = system3.config_hash(rt.config)
        cmd(desk, "undo %s" % tp)
        back = next(x for x in rt.config["tables"] if x["id"] == es["id"])
        say("  config %s -> %s -> undo; the category's %s is %s again (was %s)"
            % (before, after, key, back["categories"][0].get(key), cat.get(key)))
        cmd(desk, "tables")
        cmd(desk, "faculties")
        ns["_ledger"].close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
