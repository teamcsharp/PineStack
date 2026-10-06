"""[flowchart] EVERY CONVERSATION AS A CONDITIONAL FLOWCHART, BY ITS HEX KEY.

"I want a decision tree flow chart that's able to be viewed for any and every
conversation, seeing how information was stored, how it was banked, how it was
recalled, how it was scheduled, how the dice rolled, how the roulette went for
each and every item in the flow of a conversation. I want these conversations
to be tracked with hex keys that I'm able to use in order to follow around and
have trouble shot and diagnosed and analyzed by you if we need to run a report
on the back end."                                    - the operator, 2026-10-01

Read-only. A conversation is keyed by System 3's own id (16 hex); any of its
lines' codes (the 8-hex [msgid] code, or a longer line id) finds it too.
build_flow() turns the stored conversation into an ordered graph:

  start      the conversation: its road, structure, topic, seed
  decision   one recorded draw (a diamond): its family, the d100, every
             candidate with its odds, the winner and the losers - the
             branches not taken are drawn beside it
  turn       a planned turn (a box): the seat, the leg, what the running
             order asked for, and - once it aired - the words and the code
  gate       what happened to it after: the copy gate, a repair, a withhold
  step       its life outside the plan: written, recorded, banked, produced,
             aired (the production ring and the lines' own air times)
  end

report_text() says the same graph as plain lines, for a diagnosis.
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable

SCHEMA = "flow.chart/1"
HEX = re.compile(r"^#?([0-9a-f]{6,32})$")
LOSERS_SHOWN = 4


def _p(v: Any) -> float | None:
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _d100(draw: Any) -> int | None:
    if isinstance(draw, dict):
        if draw.get("dice") is not None:
            try:
                return int(draw["dice"])
            except (TypeError, ValueError):
                return None
        draw = draw.get("u")
    try:
        u = float(draw)
    except (TypeError, ValueError):
        return None
    return max(1, min(100, int(u * 100) + 1)) if 0.0 <= u <= 1.0 else None


def decision_node(ev: dict[str, Any]) -> dict[str, Any] | None:
    stages = [s for s in ev.get("stages") or [] if isinstance(s, dict)]
    if not stages:
        return None
    path, dice = [], None
    for s in stages:
        sel = s.get("selected")
        win = next((c for c in s.get("candidates") or [] if c.get("id") == sel), None)
        path.append(str((win or {}).get("label") or sel or "?"))
        d = _d100(s.get("draw"))
        dice = d if d is not None else dice
    # the winner and the beaten are read off the deepest stage that HAD a choice: an ES roll
    # ends on its intensity, a number, with nothing to beat
    last = next((st for st in reversed(stages)
                 if len([c for c in st.get("candidates") or [] if isinstance(c, dict)]) > 1), stages[-1])
    cands = [c for c in last.get("candidates") or [] if isinstance(c, dict)]
    sel = last.get("selected")
    winner = next((c for c in cands if c.get("id") == sel), None)
    losers = sorted((c for c in cands if c is not winner), key=lambda c: -(_p(c.get("p")) or 0))
    meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
    return {
        "id": "d:%s" % (ev.get("event_id") or ev.get("cursor") or id(ev)),
        "type": "decision", "family": str(ev.get("family") or ""), "seq": ev.get("seq"),
        "at": ev.get("at"), "turn_index": ev.get("turn_index"), "turn_id": str(ev.get("turn_id") or ""),
        "label": "%s: %s" % (ev.get("family") or "roll", path[-1] if path else "?"),
        "path": path, "dice": dice, "of": int(last.get("of") or len(cands) or 0),
        "fixed": last.get("stage") == "fixed" or meta.get("authority") == "fixed",
        "odds": meta.get("odds"),
        "winner": ({"label": str(winner.get("label") or winner.get("id")), "p": _p(winner.get("p")),
                    "why": [str(w) for w in (winner.get("why") or [])][:3]} if winner else None),
        "losers": [{"label": str(c.get("label") or c.get("id")), "p": _p(c.get("p"))} for c in losers],
        "more": 0,
        "excluded": len(last.get("excluded") or []),
        "stages": stages, "selected": ev.get("selected"), "properties": meta,
        "state_before": ev.get("state_before"), "state_after": ev.get("state_after"),
        "previous_revision": bool(meta.get("prior_revision")),
        "kind": str(meta.get("kind") or last.get("stage") or ""),
        "source_turn": str(meta.get("source_turn") or meta.get("target_turn_id") or ""),
        "turn_credit": int(meta.get("turn_credit") or 0),
    }


def _obs_text(ev: dict[str, Any]) -> str:
    for k in ("say", "why", "summary", "text", "rule", "label"):
        v = ev.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:300]
    return ""


def build_flow(conv: dict[str, Any], steps: Iterable[dict[str, Any]] = (), now_turn_id: str = "") -> dict[str, Any]:
    """The conversation as nodes in order and the edges between them."""
    ident = conv.get("identity") if isinstance(conv.get("identity"), dict) else {}
    cid = str(ident.get("conversation_id") or conv.get("conversation_id") or "")
    inputs = conv.get("inputs") if isinstance(conv.get("inputs"), dict) else {}
    road = str(inputs.get("road") or conv.get("road") or "banter")
    turns = sorted([t for t in conv.get("turns") or [] if isinstance(t, dict)], key=lambda t: int(t.get("index") or 0))
    names = inputs.get("names") if isinstance(inputs.get("names"), dict) else {}
    lines_by_turn: dict[str, list[dict[str, Any]]] = {}
    for ln in conv.get("lines") or []:
        if isinstance(ln, dict) and ln.get("turn_id"):
            lines_by_turn.setdefault(str(ln["turn_id"]), []).append(ln)
    decisions = [d for d in (decision_node(e) for e in conv.get("decision_events") or [] if isinstance(e, dict)
                            and not (e.get("meta") or {}).get("superseded_by_revision")) if d]
    decisions.sort(key=lambda d: (d.get("seq") if isinstance(d.get("seq"), int) else 10 ** 6, float(d.get("at") or 0)))
    by_turn: dict[int, list[dict[str, Any]]] = {}
    planning: list[dict[str, Any]] = []
    for d in decisions:
        ti = d.get("turn_index")
        if isinstance(ti, int) and ti >= 0:
            by_turn.setdefault(ti, []).append(d)
        else:
            planning.append(d)
    obs_by_turn: dict[str, list[dict[str, Any]]] = {}
    loose_obs: list[dict[str, Any]] = []
    for ev in conv.get("observations_air") or conv.get("observations") or []:
        if not isinstance(ev, dict):
            continue
        node = {"id": "g:%s" % (ev.get("cursor") or ev.get("event_id") or id(ev)), "type": "gate",
                "label": str(ev.get("family") or "note").lower(), "text": _obs_text(ev), "at": ev.get("at")}
        if ev.get("turn_id"):
            obs_by_turn.setdefault(str(ev["turn_id"]), []).append(node)
        else:
            loose_obs.append(node)
    timing = conv.get("timing") if isinstance(conv.get("timing"), dict) else {}
    nodes: list[dict[str, Any]] = [{
        "id": "start:%s" % cid, "type": "start", "label": "Conversation #%s" % cid,
        "road": road, "topic": str((inputs.get("subject") or {}).get("topic") or "")[:200]
        if isinstance(inputs.get("subject"), dict) else "",
        "structure": str((conv.get("road_structure") or conv.get("call_structure") or {}).get("id") or "")
        if isinstance(conv.get("road_structure") or conv.get("call_structure"), dict) else "",
        "properties": {**{k: conv.get(k) for k in ("call_diversity", "rewrite_request") if conv.get(k)}, "call_material": inputs.get("call") or {}}, "seed": str(conv.get("seed") or ""), "turns": len(turns),
        "budget": timing.get("turn_budget"), "at": ident.get("created_at") or conv.get("created_at")}]
    nodes += planning
    aired_any = False
    for t in turns:
        i = int(t.get("index") or 0)
        nodes += by_turn.get(i, [])
        tid = str(t.get("turn_id") or "")
        said = lines_by_turn.get(tid) or []
        aired = [ln for ln in said if ln.get("at")]
        aired_any = aired_any or bool(aired)
        seat = str(t.get("speaker") or "")
        perf = t.get("performance") if isinstance(t.get("performance"), dict) else {}
        nodes.append({
            "id": "t:%s" % (tid or i), "type": "turn", "index": i, "turn_id": tid, "seat": seat,
            "who": str(names.get(seat) or seat), "leg": str(t.get("leg") or ""), "place": str(t.get("place") or ""),
            "reply_to": t.get("reply_to"), "turn_credit": int(t.get("turn_credit") or 0),
            "inner_reply": bool(t.get("inner_reply")), "cast_reaction": bool(t.get("cast_reaction")),
            "returns_to_topic": str(t.get("graph_node") or "").startswith("__return_"),
            "properties": {k: t.get(k) for k in ("diversity", "decisions", "performance") if t.get(k)}, "asked": str(t.get("protocol") or ""),
            "feeling": ("%s %s" % (perf.get("emotion") or "", perf.get("intensity") or "")).strip(),
            "said": " ".join(str(ln.get("text") or "") for ln in said)[:600],
            "codes": [str(ln.get("line_id") or "") for ln in said if ln.get("line_id")],
            "aired_at": min((float(ln["at"]) for ln in aired), default=None),
            "now": bool(now_turn_id and tid == now_turn_id)})
        nodes += obs_by_turn.get(tid, [])
    nodes += loose_obs
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        nodes.append({"id": "s:%s" % s.get("n", id(s)), "type": "step", "label": str(s.get("stage") or "step"),
                      "text": str(s.get("text") or "")[:300], "at": s.get("at"),
                      "facts": {k: s.get(k) for k in ("seconds", "made", "lines", "shelf", "outcome", "caller")
                                if s.get(k) not in (None, "")}})
    nodes.append({"id": "end:%s" % cid, "type": "end",
                  "label": "aired" if aired_any else "planned - not aired yet"})
    edges = []
    for a, b in zip(nodes, nodes[1:]):
        label = ""
        if a["type"] == "decision" and a.get("winner"):
            p = a["winner"].get("p")
            label = "%s%s" % (a["winner"]["label"][:40], " (%d%%)" % round(p * 100) if p is not None else "")
        edges.append({"from": a["id"], "to": b["id"], "label": label})
    reply_edges = [{"from": "t:" + t["reply_to"]["turn_id"], "to": "t:" + t["turn_id"],
                    "kind": "reply", "label": "reacts" if t.get("cast_reaction") else "answers",
                    "turn_credit": int(t.get("turn_credit") or 0)} for t in turns if t.get("reply_to")]
    return {"schema": SCHEMA, "key": cid, "revision": ident.get("revision", 1), "road": road, "nodes": nodes, "edges": edges,
            "reply_edges": reply_edges,
            "counts": {"decisions": len(decisions), "turns": len(turns),
                       "turn_credits": sum(int(t.get("turn_credit") or 0) for t in turns),
                       "cast_reactions": sum(bool(t.get("cast_reaction")) for t in turns),
                       "aired": sum(1 for n in nodes if n["type"] == "turn" and n.get("aired_at")),
                       "candidates_lost": sum(len(d.get("losers") or []) + int(d.get("more") or 0) for d in decisions)},
            "now_turn": now_turn_id, "at": time.time()}


def report_text(flow: dict[str, Any]) -> str:
    """The graph as plain lines - what a diagnosis reads."""
    out = ["FLOW %s  road=%s  %s" % (flow.get("key"), flow.get("road"),
                                       ", ".join("%s=%s" % kv for kv in (flow.get("counts") or {}).items()))]
    for n in flow.get("nodes") or []:
        t = n.get("type")
        if t == "start":
            out.append("START  %s  structure=%s seed=%s budget=%s topic=%s" % (
                n.get("label"), n.get("structure"), n.get("seed"), n.get("budget"), n.get("topic")))
        elif t == "decision":
            w = n.get("winner") or {}
            out.append("  ◆ %-10s d100=%-4s %s  -> %s (%s)%s  beat: %s" % (
                n.get("family"), n.get("dice") if n.get("dice") is not None else "-", " › ".join(n.get("path") or []),
                w.get("label"), w.get("p"), "  [pinned]" if n.get("fixed") else "",
                ", ".join("%s (%s)" % (x["label"], x["p"]) for x in n.get("losers") or []) or "-"))
        elif t == "turn":
            out.append("■ %2s %-6s %-14s %s%s" % (
                n.get("index"), n.get("seat"), n.get("leg"),
                ("SAID: " + n["said"][:160]) if n.get("said") else ("ASKED: " + n.get("asked", "")[:160]),
                ("  codes=" + ",".join(c[:8] for c in n.get("codes") or [])) if n.get("codes") else ""))
            target = n.get("reply_to")
            if target:
                out.append("    %s %s (turn %s)%s" % (
                    "CAST REACTION ->" if n.get("cast_reaction") else "RETURN TO TOPIC ->" if n.get("returns_to_topic") else "REPLY ->",
                    target.get("name") or target.get("speaker"), int(target.get("index", 0)) + 1,
                    "  +%s turn restored" % n["turn_credit"] if n.get("turn_credit") else ""))
        elif t == "gate":
            out.append("    ↳ %s: %s" % (n.get("label"), n.get("text")))
        elif t == "step":
            out.append("  ● %s %s %s" % (n.get("label"), n.get("facts") or "", (n.get("text") or "")[:120]))
        elif t == "end":
            out.append("END  %s" % n.get("label"))
    return "\n".join(out)


def install(app: Any, ns: dict[str, Any]) -> None:
    import asyncio
    import json as _json

    from fastapi import Header, HTTPException
    from fastapi.responses import PlainTextResponse

    def runtime() -> Any:
        get = ns.get("_SYSTEM3_RUNTIME")
        rt = get() if callable(get) else None
        if rt is None:
            raise HTTPException(503, "System 3 is not running")
        return rt

    def ring_steps(cid: str) -> list[dict[str, Any]]:
        feed = ns.get("_production_feed")
        try:
            return [r for r in feed.ring_after(0, 600) if str(r.get("conversation") or "") == cid] if feed else []
        except Exception:  # noqa: BLE001
            return []

    async def load(rt: Any, cid: str) -> dict[str, Any] | None:
        got = await rt.read(rt.store.conversation, cid)
        if not got:
            live = rt.recent.get(cid)
            if live:
                got = _json.loads(_json.dumps(live, default=str))
        return got

    async def resolve(rt: Any, key: str) -> tuple[str, str]:
        """(conversation id, the turn a line code names) for any hex key."""
        m = HEX.match(str(key or "").strip().lower())
        if not m:
            raise HTTPException(400, "a flowchart key is hex: a conversation's 16 or a line's code")
        key = m.group(1)
        if await load(rt, key):
            return key, ""
        link = await rt.read(rt.store.line, key)
        if not link:
            held = ns.get("_S3_LINE_BY_ID")
            stamp = held.get(key) if isinstance(held, dict) else None
            if isinstance(stamp, dict):
                link = stamp
        if not link:
            why = ns.get("line_story_resolve")
            if callable(why):
                try:
                    full = why(key)
                    if full:
                        link = await rt.read(rt.store.line, full)
                except Exception:  # noqa: BLE001
                    link = None
        if link and link.get("conversation_id"):
            return str(link["conversation_id"]), str(link.get("turn_id") or "")
        raise HTTPException(404, "no conversation or line %s (System 3 keeps seven days)" % key)

    async def flow_for(cid: str, now_tid: str = "") -> dict[str, Any]:
        rt = runtime()
        conv = await load(rt, cid)
        if not conv:
            raise HTTPException(404, "no conversation %s" % cid)
        return await asyncio.to_thread(build_flow, conv, ring_steps(cid), now_tid)

    @app.get("/api/flow/now")
    async def flow_now(authorization: str | None = Header(default=None)):
        """[flowchart] the conversation on air, with the turn going out now."""
        ns["require_read_auth"](authorization)
        rt = runtime()
        now = await rt.now()
        s3 = now.get("system3") if isinstance(now.get("system3"), dict) else None
        if not s3 or not s3.get("conversation_id"):
            return {"live": False, "line": now.get("line"), "why": "the line on air was not made by a System 3 node"
                    if now.get("line") else "nothing is on air"}
        flow = await flow_for(str(s3["conversation_id"]), str(s3.get("turn_id") or ""))
        return {"live": True, "line": now.get("line"), "flow": flow}

    @app.get("/api/flow/recent")
    async def flow_recent(limit: int = 30, road: str = "", authorization: str | None = Header(default=None)):
        ns["require_read_auth"](authorization)
        rt = runtime()
        got = await rt.read(rt.store.conversations, max(1, min(100, int(limit))), str(road or ""))
        return {"conversations": got}

    @app.get("/api/flow/{key}")
    async def flow_key(key: str, text: bool = False, authorization: str | None = Header(default=None)):
        """[flowchart] a conversation by its hex key, or by any of its lines' codes.
        ?text=1 is the report a diagnosis reads."""
        ns["require_read_auth"](authorization)
        rt = runtime()
        cid, tid = await resolve(rt, key)
        flow = await flow_for(cid, tid)
        if text:
            return PlainTextResponse(report_text(flow))
        return flow
