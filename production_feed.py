"""[prod-feed] THE PAUSE, AS A FEED: what the backend is making for the cast.

"When the station is paused, I want a script scrolling a feed of the
generative production of banking on the backend. I want to see dice and
roulette animations and RNG results for the conversations and paths being
split showing dialogue winning over other dialogue. It should be detailed
and intricate showing how the orchestrator and backend is working on making
and storing dialogue for the cast. It is important that we dont make
dialogue that is not being used."                   - the operator, 2026-10-01

Nothing here decides anything. It READS four stores the station already
keeps and puts them in one time order:

  System 3's ledger (system3_store.events_after) - every weighted draw, each
      stage's candidates with their weights and probabilities, the random
      draw and the winner; and the observations: the copy gate, the repair
      and room rolls, rounds withheld, the station's dice doors (STATION).
  The production ring below - one row per step a banked round takes:
      written, emoted, recorded, banked, refused - noted by the banking code.
  The emotion engine (emotion_engine.state) - each line's ES block (tempo,
      pitch, range, energy, pause) and whether it was shaped by it.
  The pipeline ring (_RADIO["pipeline"]) - the orchestrator's own sentences.

and a header that answers the operator's last sentence: how much is banked,
how much of it has ever been heard, and what is being refused.

Rows come back already in the shape the script view's roll stage plays
(PineRollTag: {table, main: {dice, opts, hit, label, of}}), so the browser
animates exactly what was recorded and invents nothing.
"""
from __future__ import annotations

import collections
import itertools
import threading
import time
from typing import Any, Iterable

RING_KEPT = 600
OPTS_SHOWN = 10            # a reel shows the winner and the strongest losers
LOSERS_NAMED = 3
PIPELINE_KINDS = ("lookahead", "model", "voice", "system3", "crystal", "drop", "action", "perf")

_RING: collections.deque = collections.deque(maxlen=RING_KEPT)
_SEQ = itertools.count(1)
_LOCK = threading.Lock()

# The stages a banked round passes through, in order. The feed draws them as
# a track so the operator sees where each round has got to.
STAGES = ("rolled", "written", "tinted", "emoted", "recorded", "banked", "aired", "refused")


def note(stage: str, road: str = "", text: str = "", **extra: Any) -> None:
    """One step a banked round took. Called by the banking code; never raises."""
    try:
        row = {"n": next(_SEQ), "at": time.time(), "type": "stage", "stage": str(stage or ""),
               "road": str(road or ""), "text": str(text or "")[:600]}
        for k, v in extra.items():
            if v is not None:
                row[str(k)] = v
        with _LOCK:
            _RING.append(row)
    except Exception:  # noqa: BLE001
        pass


def ring_after(n: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    with _LOCK:
        rows = [dict(r) for r in _RING if int(r.get("n") or 0) > int(n or 0)]
    return rows[-max(1, int(limit)):]


# ------------------------------------------------------------ System 3's rolls

def _d100(draw: Any, total: Any = None) -> int | None:
    """The recorded draw as the d100 the roll stage shows. System 3's stream
    records {u, dice, sides} (system3.Stream.next); older rows a bare number."""
    try:
        if isinstance(draw, dict):
            if draw.get("dice") is not None:
                return int(draw["dice"])
            draw = draw.get("u")
        if draw is None:
            return None
        d = float(draw)
        t = float(total or 0)
        u = d / t if t > 0 and d > 1.0 else d
        if not 0.0 <= u <= 1.0:
            return None
        return max(1, min(100, int(u * 100) + 1))
    except (TypeError, ValueError):
        return None


def stage_row(family: str, stage: dict[str, Any]) -> dict[str, Any] | None:
    """One recorded stage -> one roll-stage row, plus the losers by name."""
    cands = [c for c in (stage.get("candidates") or []) if isinstance(c, dict)]
    if not cands:
        return None
    sel = stage.get("selected")
    winner = next((c for c in cands if c.get("id") == sel), None)
    ranked = sorted(cands, key=lambda c: -float(c.get("p") or 0))
    shown = ranked[:OPTS_SHOWN]
    if winner is not None and winner not in shown:
        shown = shown[:-1] + [winner]
    labels = [str(c.get("label") or c.get("id") or "?") for c in shown]
    hit = shown.index(winner) if winner in shown else -1
    losers = [{"label": str(c.get("label") or c.get("id")), "p": c.get("p")}
              for c in ranked if c is not winner][:LOSERS_NAMED]
    return {
        "table": "%s - %s" % (family, stage.get("stage") or "draw"),
        "main": {"dice": _d100(stage.get("draw"), stage.get("total")), "opts": labels,
                 "hit": max(0, hit), "label": labels[hit] if hit >= 0 else str(sel or ""),
                 "of": int(stage.get("of") or len(cands))},
        "winner": ({"label": str(winner.get("label") or winner.get("id")), "p": winner.get("p"),
                    "why": list(winner.get("why") or [])[:3]} if winner else None),
        "losers": losers,
        "excluded": len(stage.get("excluded") or []),
        "fixed": stage.get("stage") == "fixed",
    }


def _observation_say(ev: dict[str, Any]) -> str:
    for key in ("say", "why", "summary", "text", "label", "rule"):
        v = ev.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:300]
    return ""


def s3_items(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """System 3's recorded events as feed items."""
    out: list[dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        family = str(ev.get("family") or "")
        meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
        base = {"at": float(ev.get("at") or 0), "cursor": ev.get("cursor"), "family": family,
                "conversation": str(ev.get("conversation_id") or ""),
                "turn": ev.get("turn_index"), "road": str(meta.get("road") or ev.get("road") or ""),
                "speaker": str(meta.get("speaker") or ev.get("speaker") or "")}
        if ev.get("kind") == "decision" or ev.get("stages"):
            rows = [r for r in (stage_row(family, s) for s in (ev.get("stages") or [])
                                if isinstance(s, dict)) if r]
            if not rows:
                continue
            last = rows[-1]
            out.append(dict(base, type="roll", rows=rows,
                            title="%s rolled %s" % (family, (last.get("winner") or {}).get("label") or "?"),
                            winner=last.get("winner"), losers=last.get("losers")))
            continue
        if family == "STATION":
            # a dice door (system3_runtime._record_roll): a chance carries
            # `hit` and its odds, a pick its candidates, a roll only `u`
            if "hit" in ev:
                opts, picked = ["no", "yes"], ("yes" if ev.get("hit") else "no")
                title = "%s - %s at %s%%" % (ev.get("label") or ev.get("key") or "a chance", picked,
                                             int(round(float(ev.get("odds") or 0) * 100)))
            elif ev.get("candidates"):
                opts = [str(c) for c in ev.get("candidates") or []][:OPTS_SHOWN]
                picked = str(ev.get("picked") or "")
                title = "%s - picked %s of %s" % (ev.get("label") or ev.get("key") or "a pick",
                                                  ev.get("index"), ev.get("of"))
            else:
                picked = "lands at %.2f" % float(ev.get("u") or 0)
                opts = [picked]
                title = "%s - %s" % (ev.get("label") or ev.get("key") or "a roll", picked)
            if picked not in opts:
                opts.append(picked)
            losers = [{"label": o} for o in opts if o != picked][:LOSERS_NAMED] if ev.get("candidates") else []
            row = {"table": "dice door - %s" % (ev.get("label") or ev.get("key") or "roll"),
                   "main": {"dice": ev.get("dice"), "opts": opts, "hit": opts.index(picked),
                            "label": picked, "of": int(ev.get("of") or len(opts))}}
            out.append(dict(base, type="roll", rows=[row], title=title,
                            winner={"label": picked}, losers=losers, why=str(ev.get("why") or "")[:200]))
            continue
        out.append(dict(base, type="gate", title=family.lower(), text=_observation_say(ev)))
    return out


# ------------------------------------------------------------ the other stores

def emotion_items(tasks: Iterable[dict[str, Any]], since: float) -> list[dict[str, Any]]:
    out = []
    for t in tasks or []:
        if not isinstance(t, dict) or float(t.get("at") or 0) <= since:
            continue
        out.append({"at": float(t.get("at") or 0), "type": "emote", "speaker": str(t.get("speaker") or ""),
                    "text": str(t.get("text") or "")[:300], "es": t.get("es") or {},
                    "shaped": bool(t.get("shaped_by_es")), "state": str(t.get("state") or ""),
                    "engine": str(t.get("engine") or ""), "voice": str(t.get("voice") or "")})
    return out


def pipeline_items(rows: Iterable[dict[str, Any]], since_ms: float) -> list[dict[str, Any]]:
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or str(r.get("kind") or "") not in PIPELINE_KINDS:
            continue
        ts = float(r.get("ts") or 0)
        if ts <= since_ms:
            continue
        out.append({"at": ts / 1000.0, "ts": ts, "type": "note", "kind": str(r.get("kind")),
                    "text": str(r.get("text") or "")[:240]})
    return out


def merge(*groups: Iterable[dict[str, Any]], limit: int = 120) -> list[dict[str, Any]]:
    rows = [r for g in groups for r in (g or [])]
    rows.sort(key=lambda r: float(r.get("at") or 0))
    return rows[-max(1, int(limit)):]


# ------------------------------------------------------------ the route

def install(app: Any, ns: dict[str, Any]) -> None:
    from fastapi import Header

    def get(name: str) -> Any:
        return ns.get(name)

    def s3_store() -> Any:
        rt_get = get("_SYSTEM3_RUNTIME")
        rt = rt_get() if callable(rt_get) else None
        return getattr(rt, "store", None) if rt is not None else None

    def header() -> dict[str, Any]:
        out: dict[str, Any] = {"paused": False}
        try:
            out["paused"] = bool(get("radio_paused")())
        except Exception:  # noqa: BLE001
            pass
        try:
            u = get("unheard_state")() or {}
            out["bank"] = {"unheard": u.get("unheard"), "ready": u.get("ready"),
                           "overdue": u.get("overdue"), "oldest_s": u.get("oldest"),
                           "roads": [{k: r.get(k) for k in ("kind", "label", "rows", "unheard", "ready")}
                                     for r in (u.get("roads") or []) if isinstance(r, dict)],
                           "call_endings": u.get("call_endings"), "bank_ahead": u.get("bank_ahead"),
                           "refusals": (u.get("sweep") or {}).get("blocked") or {},
                           "aired_by_rescue": (u.get("sweep") or {}).get("aired")}
        except Exception:  # noqa: BLE001
            pass
        try:
            needs = get("hour_needs_now")() or {}
            out["needs"] = {k: {"owed": round(float(v.get("owed") or 0)), "held": round(float(v.get("held") or 0))}
                            for k, v in needs.items()}
        except Exception:  # noqa: BLE001
            pass
        return out

    def build(s3: int, n: int, t: float, limit: int) -> dict[str, Any]:
        now = time.time()
        store = s3_store()
        s3_rows: list[dict[str, Any]] = []
        s3_next = int(s3 or 0)
        if store is not None:
            try:
                if s3_next <= 0:
                    head = int(store.events_after(10 ** 12, 1).get("head") or 0)
                    s3_next = max(0, head - 60)            # the first look: the recent rolls only
                got = store.events_after(s3_next, 200)
                s3_rows = s3_items(got.get("events") or [])
                s3_next = int(got.get("cursor") or s3_next)
            except Exception:  # noqa: BLE001
                s3_rows = []
        since_t = float(t or 0) or (now - 600.0)
        emo: list[dict[str, Any]] = []
        try:
            emo = emotion_items((get("_emotion").state(80) or {}).get("tasks") or [], since_t)
        except Exception:  # noqa: BLE001
            emo = []
        pipe: list[dict[str, Any]] = []
        try:
            pipe = pipeline_items(list((get("_RADIO") or {}).get("pipeline") or []), since_t * 1000.0)
        except Exception:  # noqa: BLE001
            pipe = []
        ring = ring_after(n, 200)
        if not n:
            ring = [r for r in ring if float(r.get("at") or 0) > since_t]
        items = merge(s3_rows, ring, emo, pipe, limit=limit)
        return {"at": now, "items": items, "header": header(),
                "cursor": {"s3": s3_next, "n": max([int(r.get("n") or 0) for r in ring] + [int(n or 0)]),
                           "t": max([float(r.get("at") or 0) for r in emo + pipe] + [since_t])}}

    @app.get("/api/production/feed")
    async def production_feed_api(s3: int = 0, n: int = 0, t: float = 0.0, limit: int = 120,
                                  authorization: str | None = Header(default=None)):
        """[prod-feed] everything the backend made since the cursor, in order."""
        get("require_read_auth")(authorization)
        import asyncio
        return await asyncio.to_thread(build, s3, n, t, max(1, min(400, int(limit))))
