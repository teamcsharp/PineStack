"""script_decision_tree.py - [rounds-tree] THE SEGMENT'S DECISION TREE.

"When I click this, I want a popup window showing me a vertical flowchart of
the decision tree for the entire flow that is scripted through consecutive
roulette per the System 3 vertical node table ... Show me every angle, twist
and turn the dialogue took, with the intermediate roulette rounds as diamonds
in between."                                          - the operator, 09-29

GET /api/script/segment/{segment_id}/decision-tree answers, for one scheduled
segment (the director's `occurrence`, e.g. "hour-1790672400000:hour-05"), the
rounds System 3 directed for it, top to bottom:

  - every round that went out in the segment (System 3's segment register:
    the script-ledger blocks it holds), in the script's order;
  - the round(s) written FOR it and not aired yet - the allocated script or
    each draft variant the Script view shows - found by their WORDS, because
    a draft can be moved to a later slot than the one it was prepared for.

Each round is a list of elements in the order the graph walked them:

  stage    a turn (Initiator, Reply A, Rebuttal, Answer B, Topic change...):
           speaker, words, its script row (block, ord, line id), its state
           (aired / on the script / written / planned / rejected), the die
           that picked the speaker, and its roll receipt (table > category >
           sub result, each with its die and odds).
  diamond  a roulette decision between stages - the graph's branch gates and
           chance gates: the node, the seed and draw, every face with its
           weight and probability, the one that landed, and the branches
           offered but not taken.

Nothing here is invented: every die, weight and seed is read from System 3's
own ledger (data/system3.sqlite3 decision events). A conversation without
graph events (an older engine) says "not recorded" instead of guessing.
READ ONLY: the handler never writes a store.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = "rounds-tree/1"
GATE_STAGES = ("branch", "chance")
WHO_STAGES = ("speaker", "initiator")
REJECTED_TURN = {"dropped", "withheld", "rejected", "cut", "failed", "withdrawn"}
REJECTED_CONV = {"withheld", "abandoned", "dropped", "failed", "rejected"}
EXIT_IDS = {"topic_change", "end", "exit", "close", "wrap"}
ROADS_OF = {"banter": ("banter",), "caller": ("caller", "banter_caller"),
            "manager": ("manager", "upstairs", "memo"), "ad": ("ad", "ad_spot"),
            "news": ("news",), "gallery": ("gallery",), "recap": ("recap",),
            "memo": ("memo",), "mixtape": ("mixtape",)}
MAX_ROUNDS = 24
FIXED_ROADS = {"caller", "banter_caller"}   # legs, not a graph (measured 09-29: 0 of 177 calls had GRAPH events)
NOT_RECORDED = "not recorded"


# --- small readers ---------------------------------------------------------------
def words(text: Any) -> str:
    """Words as two records can both be read: case, curly quotes, spacing."""
    s = str(text or "").replace("’", "'").replace("‘", "'").lower()
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", s).split())


def pretty_node(node: Any) -> str:
    s = str(node or "").strip()
    if not s:
        return ""
    parts = s.replace("-", "_").split("_")
    return " ".join(p.upper() if len(p) == 1 else p.capitalize() for p in parts if p)


def odds_text(p: Any) -> str:
    """0.5 -> '1:2', 0.333 -> '1:3', 0.6 -> '60%', 1.0 -> 'certain'."""
    try:
        p = float(p)
    except (TypeError, ValueError):
        return ""
    if p <= 0:
        return "0%"
    if p >= 0.999:
        return "certain"
    k = 1.0 / p
    if 2 <= round(k) <= 12 and abs(k - round(k)) < 0.04:
        return "1:%d" % round(k)
    return "%d%%" % round(p * 100)


def _num(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _pick(stage: dict[str, Any]) -> dict[str, Any] | None:
    """One stage of a draw: what landed, its die, odds and place among the faces."""
    if not isinstance(stage, dict):
        return None
    cands = [c for c in stage.get("candidates") or [] if isinstance(c, dict)]
    sel = stage.get("selected")
    draw = stage.get("draw") if isinstance(stage.get("draw"), dict) else {}
    idx = next((i for i, c in enumerate(cands) if str(c.get("id")) == str(sel)), None)
    c = cands[idx] if idx is not None else {}
    label = c.get("label") if c else None
    if label is None:
        label = sel if not isinstance(sel, (dict, list)) else json.dumps(sel)
    return {"stage": str(stage.get("stage") or ""), "id": None if sel is None else str(sel),
            "label": str(label if label is not None else ""),
            "dice": draw.get("dice"), "p": _num(c.get("p")) if c else None,
            "odds": odds_text(c.get("p")) if c else "",
            "index": (idx + 1) if idx is not None else None, "of": len(cands) or None,
            "fixed": bool(stage.get("fixed"))}


def receipt(ev: dict[str, Any]) -> dict[str, Any]:
    """A decision event as the roll tile reads it: table > category > sub result."""
    stages = [s for s in ev.get("stages") or [] if isinstance(s, dict)]
    by = {str(s.get("stage") or ""): s for s in stages}
    sel = ev.get("selected") if isinstance(ev.get("selected"), dict) else {}
    table = _pick(by["table"]) if "table" in by else None
    cat = _pick(by["category"]) if "category" in by else None
    sub = _pick(by["item"]) if "item" in by else None
    if not cat and not sub:
        # a one-stage draw (a gate, a dice hit, a speaker): its own stage is the result
        drawn = [s for s in stages if s.get("draw") or s.get("candidates")]
        if drawn:
            cat = _pick(drawn[0])
            sub = _pick(drawn[1]) if len(drawn) > 1 else None
    tname = str(sel.get("table") or (table or {}).get("id") or "")
    return {"family": str(ev.get("family") or ""), "event_id": str(ev.get("event_id") or ""),
            "table": tname, "table_label": (table or {}).get("label") or "",
            "table_roll": table if table and table.get("dice") is not None else None,
            "category": cat, "sub": sub,
            "label": str(sel.get("label") or (sub or cat or {}).get("label") or "")[:240],
            "text": str(sel.get("text") or "")[:300],
            "seed": str(((ev.get("rng") or {}) if isinstance(ev.get("rng"), dict) else {}).get("seed") or ""),
            "node": str((ev.get("meta") or {}).get("node") or "") if isinstance(ev.get("meta"), dict) else ""}


def diamond(ev: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    """A gate the graph rolled: every face with its weight, what landed, what did not."""
    stage = next((s for s in ev.get("stages") or [] if isinstance(s, dict)), {}) or {}
    meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
    node = str(meta.get("node") or "")
    kind = str(stage.get("stage") or "")
    draw = stage.get("draw") if isinstance(stage.get("draw"), dict) else (ev.get("rng") or {})
    sel = str(stage.get("selected") if stage.get("selected") is not None else "")
    faces = []
    for c in stage.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id"))
        faces.append({"id": cid, "label": str(c.get("label") or labels.get(cid) or pretty_node(cid)),
                      "weight": _num(c.get("weight")), "base": _num(c.get("base")), "p": _num(c.get("p")),
                      "odds": odds_text(c.get("p")), "taken": cid == sel,
                      "why": [str(w) for w in (c.get("why") or [])][:4]})
    taken = next((f for f in faces if f["taken"]), None)
    node_label = labels.get(node) or pretty_node(node)
    if kind == "chance":
        # an optional node: speak or skip. A skip leaves the node itself untaken.
        spoke = sel not in ("skip", "no", "pass", "false", "0")
        branches = [{"label": node_label, "node": node, "taken": spoke,
                     "p": (taken or {}).get("p") if spoke else next((f["p"] for f in faces if not f["taken"]), None)}]
    else:
        branches = [{"label": f["label"], "node": f["id"], "taken": f["taken"], "p": f["p"]} for f in faces]
    for b in branches:
        b["odds"] = odds_text(b.get("p"))
    exit_gate = (any(f["id"] in EXIT_IDS or "exit" in f["id"] for f in faces) or "exit" in node or "topic" in node)
    return {"type": "diamond", "event_id": str(ev.get("event_id") or ""), "seq": ev.get("seq"),
            "family": str(ev.get("family") or ""), "node": node, "node_label": node_label,
            "stage": kind, "kind": "exit" if exit_gate else kind,
            "table": "%s:%s" % (ev.get("family") or "GRAPH", node) if node else str(ev.get("family") or ""),
            "seed": str(draw.get("seed") or ""), "draw": str(draw.get("label") or ""), "n": draw.get("n"),
            "u": draw.get("u"), "dice": draw.get("dice"), "sides": draw.get("sides") or 100,
            "total": _num(stage.get("total")), "fixed": bool(stage.get("fixed")),
            "taken": ({"id": taken["id"], "label": taken["label"], "p": taken["p"], "odds": taken["odds"]}
                      if taken else ({"id": sel, "label": pretty_node(sel), "p": None, "odds": ""} if sel else None)),
            "odds": (taken or {}).get("odds") or "",
            "faces": faces, "branches": branches,
            "not_taken": [b["label"] for b in branches if not b["taken"]],
            "cycle": None}


def _state(turn: dict[str, Any], conv_status: str, lines: list[dict[str, Any]],
           aired: dict[str, dict[str, Any]]) -> tuple[str, str]:
    status = str(turn.get("status") or "")
    if any(ln.get("line_id") in aired for ln in lines):
        return "aired", "went out on air"
    if status in REJECTED_TURN:
        return "rejected", "the turn was %s" % status
    if conv_status in REJECTED_CONV:
        return "rejected", "the round was %s" % conv_status
    if lines:
        return "scripted", "on the script ledger (block %s, row %s), not heard yet" % (
            lines[0].get("block"), lines[0].get("ord"))
    if status in ("generated", "bound", "written") or str(turn.get("text") or "").strip():
        return "written", "written, not on the script yet"
    return "planned", "planned by the roll, never written"


def build_round(conv: dict[str, Any], aired: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """One System 3 conversation as a top-to-bottom chain of stages and diamonds."""
    aired = aired or {}
    ident = conv.get("identity") if isinstance(conv.get("identity"), dict) else {}
    events = sorted([e for e in conv.get("decision_events") or [] if isinstance(e, dict)],
                    key=lambda e: (e.get("seq") if isinstance(e.get("seq"), (int, float)) else 0))
    by_id = {str(e.get("event_id")): e for e in events}
    turns = sorted([t for t in conv.get("turns") or [] if isinstance(t, dict)],
                   key=lambda t: (t.get("index") if isinstance(t.get("index"), (int, float)) else 0))
    labels = {str(t.get("step") or ""): str(t.get("step_label") or "") for t in turns if t.get("step_label")}
    lines_of: dict[str, list[dict[str, Any]]] = {}
    for ln in conv.get("lines") or []:
        if isinstance(ln, dict) and ln.get("turn_id"):
            lines_of.setdefault(str(ln["turn_id"]), []).append(ln)
    conv_status = str(conv.get("status") or "")
    graph = [e for e in events if e.get("family") == "GRAPH"]
    gates, node_rolls = [], []
    for e in graph:
        st = next((s for s in e.get("stages") or [] if isinstance(s, dict)), {}) or {}
        (gates if st.get("stage") in GATE_STAGES else node_rolls).append(e)
    # a node's own rolls (who speaks, how it handles, its intonation, its topic)
    # belong to the turn standing on that node: the latest one at or before the draw
    attach: dict[str, list[dict[str, Any]]] = {}
    for e in node_rolls:
        node = str((e.get("meta") or {}).get("node") or "")
        at = e.get("turn_index") if isinstance(e.get("turn_index"), (int, float)) else 10 ** 6
        on = [t for t in turns if str(t.get("step") or "") == node]
        best = None
        for t in on:
            if (t.get("index") or 0) <= at:
                best = t
        best = best or (on[0] if on else None)
        if best is not None:
            attach.setdefault(str(best.get("turn_id")), []).append(e)
    # the round-level rolls (LENGTH, TOPIC, CARRY, INTERJECT, TEMPER ...)
    round_rolls, station = [], 0
    for e in events:
        fam = str(e.get("family") or "")
        if e.get("turn_id") or fam == "GRAPH" or (isinstance(e.get("turn_index"), int) and e["turn_index"] >= 0):
            continue
        if fam == "STATION":
            station += 1
            continue
        round_rolls.append(receipt(e))
    interject_ev = next((e for e in events if e.get("family") == "INTERJECT"), None)
    elements: list[dict[str, Any]] = []
    gi = 0
    interject_placed = False

    def stage_of(t: dict[str, Any]) -> dict[str, Any]:
        tid = str(t.get("turn_id") or "")
        lines = sorted(lines_of.get(tid, []), key=lambda x: (x.get("block") or 0, x.get("ord") or 0))
        state, why = _state(t, conv_status, lines, aired)
        who_roll, node_receipts = None, []
        for e in attach.get(tid, []):
            st = next((s for s in e.get("stages") or [] if isinstance(s, dict)), {}) or {}
            if st.get("stage") in WHO_STAGES and who_roll is None:
                p = _pick(st) or {}
                who_roll = dict(p, event_id=str(e.get("event_id") or ""), seed=str((st.get("draw") or {}).get("seed") or ""))
            else:
                node_receipts.append(receipt(e))
        rolls = []
        for d in t.get("decisions") or []:
            if not isinstance(d, dict):
                continue
            ev = by_id.get(str(d.get("event_id") or ""))
            if ev is not None:
                rolls.append(receipt(ev))
            else:
                rolls.append({"family": str(d.get("family") or ""), "event_id": str(d.get("event_id") or ""),
                              "table": str(d.get("table") or ""), "category": None, "sub": None,
                              "label": str(d.get("label") or ""), "text": "", "missing": NOT_RECORDED})
        for key in ("sfx", "sfxguy"):
            s = t.get(key)
            if isinstance(s, dict) and s.get("event_id") and str(s["event_id"]) in by_id:
                rolls.append(receipt(by_id[str(s["event_id"])]))
        first = lines[0] if lines else {}
        air = aired.get(str(first.get("line_id") or "")) if first else None
        return {"type": "stage", "turn_id": tid, "index": t.get("index"), "cycle": t.get("cycle"),
                "node": str(t.get("step") or ""), "label": str(t.get("step_label") or pretty_node(t.get("step"))),
                "phase": str(t.get("phase") or ""), "speaker": str(t.get("speaker") or ""),
                "name": str(t.get("name") or ""),
                "text": str(t.get("text") or first.get("text") or "")[:900],
                "status": str(t.get("status") or ""), "state": state, "why": why,
                "line": ({"line_id": first.get("line_id"), "block": first.get("block"), "ord": first.get("ord"),
                          "segment": first.get("segment"), "air_at": (air or {}).get("air_at"),
                          "line_ids": [x.get("line_id") for x in lines]} if first else None),
                "script_index": t.get("script_index"),
                "who_roll": who_roll, "rolls": rolls, "node_rolls": node_receipts,
                "emotion": str(t.get("emotion") or (t.get("performance") or {}).get("emotion") or "")}

    for t in turns:
        idx = t.get("index") if isinstance(t.get("index"), (int, float)) else 0
        while gi < len(gates) and isinstance(gates[gi].get("turn_index"), (int, float)) and gates[gi]["turn_index"] <= idx:
            d = diamond(gates[gi], labels)
            d["cycle"] = t.get("cycle")
            elements.append(d)
            gi += 1
        if (interject_ev is not None and not interject_placed and str(t.get("step") or "") == "interject"):
            d = diamond(interject_ev, labels)
            d.update({"kind": "chance", "node": "interject", "node_label": "Interjection",
                      "table": "INTERJECT", "cycle": t.get("cycle")})
            elements.append(d)
            interject_placed = True
        elements.append(stage_of(t))
    while gi < len(gates):
        elements.append(diamond(gates[gi], labels))
        gi += 1
    notes = []
    road = str(ident.get("road_kind") or "")
    if not graph and (conv.get("graph_structure") or road not in FIXED_ROADS):
        notes.append("the graph's gates are not recorded for this round (%s): the order is the plan's, "
                     "the diamonds are missing, never guessed" % (conv.get("engine") or "older engine"))
    elif not graph:
        notes.append("this road ran a fixed leg structure (%s): no roulette gate chose between its stages; "
                     "each stage's own rolls are shown" % (((conv.get("plan") or {}).get("structure") or road)
                                                           if isinstance(conv.get("plan"), dict) else road))
    if not events:
        notes.append("no decision events are recorded for this round")
    length = conv.get("length_roll") if isinstance(conv.get("length_roll"), dict) else {}
    counts: dict[str, int] = {}
    for el in elements:
        if el["type"] == "stage":
            counts[el["state"]] = counts.get(el["state"], 0) + 1
    return {"conversation_id": str(ident.get("conversation_id") or conv.get("id") or ""),
            "road": str(ident.get("road_kind") or ""), "mode": str(conv.get("mode") or ""),
            "status": conv_status, "created": conv.get("created"), "engine": str(conv.get("engine") or ""),
            "seed": str(conv.get("seed") or ""), "config_hash": str(conv.get("config_hash") or ""),
            "topic": str((conv.get("subject") or {}).get("topic") or "")[:240],
            "prepared_for": str(ident.get("system2_slot_id") or ""),
            "length": ({k: length.get(k) for k in ("turns", "lo", "hi", "rolled")} if length else None),
            "verdict": (conv.get("validation") or {}).get("verdict") if isinstance(conv.get("validation"), dict) else None,
            "recorded": {"graph": bool(graph), "events": len(events)},
            "round_rolls": round_rolls, "station_rolls": station,
            "elements": elements, "counts": counts, "notes": notes}


def match_score(texts: list[str], conv: dict[str, Any]) -> float:
    """How much of a written script is this conversation's words (0..1)."""
    want = [words(x) for x in texts if words(x)]
    have = [words(t.get("text")) for t in conv.get("turns") or [] if isinstance(t, dict) and words(t.get("text"))]
    if not want or not have:
        return 0.0
    hit = 0
    for w in want:
        if any(w == h or (len(w) >= 8 and (w in h or h in w)) for h in have):
            hit += 1
    return hit / float(len(want))


def scripts_of(entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The written scripts the Script view shows for an entry: the allocated
    performances (by candidate), else each draft variant."""
    script = (entry or {}).get("script") if isinstance((entry or {}).get("script"), dict) else {}
    out: list[dict[str, Any]] = []
    bound = [t for t in script.get("turns") or [] if isinstance(t, dict)]
    if bound:
        groups: dict[str, list[str]] = {}
        order: list[str] = []
        for t in bound:
            c = str(t.get("candidate") or script.get("candidate") or "allocated")
            if c not in groups:
                groups[c] = []
                order.append(c)
            groups[c].append(str(t.get("text") or ""))
        for c in order:
            out.append({"source": "allocated", "candidate": c, "selected": True, "texts": groups[c]})
        return out
    picked = str(script.get("selected_candidate") or "")
    variants = [v for v in script.get("draft_variants") or [] if isinstance(v, dict)]
    for i, v in enumerate(variants):
        out.append({"source": "draft", "candidate": str(v.get("id") or ""),
                    "selected": (str(v.get("id") or "") == picked) if picked else i == 0,
                    "texts": [str(t.get("text") or "") for t in v.get("turns") or [] if isinstance(t, dict)]})
    return out


def aired_lookup(origin_path: Path, line_ids: list[str]) -> dict[str, dict[str, Any]]:
    """line_id -> {air_at, verdict} from the origin ledger, read-only. {} when absent."""
    ids = [str(x) for x in line_ids if x]
    if not ids or not Path(origin_path).is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    db = sqlite3.connect("file:" + Path(origin_path).as_posix() + "?mode=ro", uri=True, timeout=5.0)
    try:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            for lid, at, verdict in db.execute("SELECT line_id, air_at, verdict FROM origin WHERE line_id IN (%s)"
                                               % ",".join("?" * len(chunk)), chunk):
                out[str(lid)] = {"air_at": at, "verdict": verdict}
    except sqlite3.Error:
        return out
    finally:
        db.close()
    return out


def heard_where(origin_path: Path, cids: list[str]) -> dict[str, tuple[float, float]]:
    """[tree-heard] conversation -> (first, last) moment a line of it was HEARD,
    from the origin ledger. Read only; {} when absent or the columns are not there."""
    ids = [str(x) for x in dict.fromkeys(cids or []) if x]
    if not ids or not Path(origin_path).is_file():
        return {}
    out: dict[str, tuple[float, float]] = {}
    db = sqlite3.connect("file:" + Path(origin_path).as_posix() + "?mode=ro", uri=True, timeout=5.0)
    try:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            for cid, lo, hi in db.execute("SELECT conversation_id, MIN(air_at), MAX(air_at) FROM origin "
                                          "WHERE conversation_id IN (%s) GROUP BY conversation_id"
                                          % ",".join("?" * len(chunk)), chunk):
                if lo is not None:
                    out[str(cid)] = (float(lo), float(hi))
    except sqlite3.Error:
        return {}
    finally:
        db.close()
    return out


def heard_in(origin_path: Path, start: float, ends: float) -> list[tuple[str, float, int]]:
    """[tree-heard] (conversation, first hearing, first block) of every conversation
    a line of which was HEARD in [start, ends), in the script's order. Read only."""
    if not (start and ends and ends > start) or not Path(origin_path).is_file():
        return []
    db = sqlite3.connect("file:" + Path(origin_path).as_posix() + "?mode=ro", uri=True, timeout=5.0)
    try:
        rows = db.execute("SELECT conversation_id, MIN(air_at), MIN(block) FROM origin WHERE air_at>=? AND "
                          "air_at<? AND conversation_id IS NOT NULL AND conversation_id!='' "
                          "GROUP BY conversation_id ORDER BY MIN(block), MIN(air_at)",
                          (float(start), float(ends))).fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()
    return [(str(c), float(a or 0), int(b or 0)) for c, a, b in rows]


def collect(store: Any, seg_id: str, entry: dict[str, Any] | None, origin_path: Path,
            now: float | None = None) -> dict[str, Any]:
    """Reader-thread work: find the segment's rounds, load them, build the tree."""
    now = float(now or time.time())
    rec = store.segment_record(seg_id) if hasattr(store, "segment_record") else None
    picked: list[tuple[str, dict[str, Any]]] = []   # (cid, how)
    seen: set[str] = set()
    for mine in ((rec or {}).get("conversations") or [])[:MAX_ROUNDS * 2]:
        cid = str(mine.get("conversation_id") or "")
        if cid and cid not in seen:
            seen.add(cid)
            picked.append((cid, {"source": "aired", "first_block": mine.get("first_block"),
                                 "blocks": mine.get("blocks") or []}))
    # [tree-heard] WENT OUT IN = HEARD IN. The register files a block under the
    # segment on air when it was WRITTEN, a median 51-85 s before it sounds; 30% of
    # heard lines (09-29) went out in the next entry. The entry's window decides.
    body_seg = (rec or {}).get("segment") if isinstance((rec or {}).get("segment"), dict) else {}
    try:
        w0 = float((entry or {}).get("start") or body_seg.get("start") or 0)
        w1 = float((entry or {}).get("deadline") or body_seg.get("ends") or 0)
    except (TypeError, ValueError):
        w0 = w1 = 0.0
    went_elsewhere: list[dict[str, Any]] = []
    if w0 and w1 > w0:
        spans = heard_where(origin_path, [cid for cid, _h in picked])
        keep = []
        for cid, how in picked:
            sp = spans.get(cid)
            if sp and not (sp[0] < w1 and sp[1] >= w0):
                went_elsewhere.append({"conversation_id": cid, "heard_from": sp[0], "heard_until": sp[1],
                                       "why": "written while this entry was on air; it went out %s it"
                                              % ("after" if sp[0] >= w1 else "before")})
                continue
            keep.append((cid, how))
        picked = keep
        for cid, first_at, first_block in heard_in(origin_path, w0, w1):
            if cid not in seen:
                seen.add(cid)
                picked.append((cid, {"source": "aired", "first_block": first_block, "blocks": [],
                                     "filed_elsewhere": True, "first_heard": first_at}))
        picked.sort(key=lambda p: (p[1].get("first_block") or 0))
    scripts = scripts_of(entry)
    unmatched = []
    if scripts:
        start = float((entry or {}).get("start") or now)
        pool: list[str] = []
        try:
            pool += [str(s.get("conversation_id") or "") for s in store.prepared_for(seg_id, start - 86400)]
        except Exception:  # noqa: BLE001
            pass
        kind = str((entry or {}).get("kind") or "")
        for road in ROADS_OF.get(kind, (kind,) if kind else ()):
            try:
                rows = store.conversations(80, road, 0.0, "")
            except Exception:  # noqa: BLE001
                rows = []
            pool += [str(r.get("conversation_id") or "") for r in rows
                     if float(r.get("created") or 0) >= min(start, now) - 6 * 3600]
        bodies: dict[str, dict[str, Any]] = {}
        for cid in dict.fromkeys(pool):
            if cid and len(bodies) < 90:
                try:
                    got = store.conversation(cid, with_events=False)
                except TypeError:
                    got = store.conversation(cid)
                if got:
                    bodies[cid] = got
        for sc in scripts:
            best, score = None, 0.0
            for cid, body in bodies.items():
                s = match_score(sc["texts"], body)
                if s > score:
                    best, score = cid, s
            if best and score >= 0.5:
                how = {"source": sc["source"], "candidate": sc["candidate"], "selected": sc["selected"],
                       "match": round(score, 3)}
                if best in seen:
                    for i, (cid, h) in enumerate(picked):
                        if cid == best:
                            picked[i] = (cid, dict(h, candidate=sc["candidate"], selected=sc["selected"],
                                                   match=round(score, 3)))
                else:
                    seen.add(best)
                    picked.append((best, how))
            else:
                unmatched.append({"candidate": sc["candidate"], "source": sc["source"],
                                  "why": "no System 3 conversation holds these words (best match %d%%)"
                                         % round(score * 100)})
    convs = []
    for cid, how in picked[:MAX_ROUNDS]:
        body = store.conversation(cid)
        if not body:
            convs.append((cid, how, None))
            continue
        convs.append((cid, how, body))
    line_ids = [str(ln.get("line_id")) for _c, _h, b in convs if b for ln in b.get("lines") or [] if ln.get("line_id")]
    aired = aired_lookup(origin_path, line_ids)
    rounds = []
    for cid, how, body in convs:
        if body is None:
            rounds.append({"conversation_id": cid, "gone": True, "elements": [],
                           "notes": ["past retention (System 3 keeps seven days)"], **how})
            continue
        r = build_round(body, aired)
        r.update(how)
        rounds.append(r)
    return {"rounds": rounds, "unmatched": unmatched, "registered": bool(rec),
            "segment": (rec or {}).get("segment") if rec else None,
            "more": max(0, len(picked) - MAX_ROUNDS),
            "went_elsewhere": went_elsewhere,  # [tree-heard]
            "window": [w0, w1] if w0 and w1 > w0 else None}


def entry_brief(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    orch = entry.get("orchestration") if isinstance(entry.get("orchestration"), dict) else {}
    return {k: entry.get(k) for k in ("ordinal", "kind", "label", "slot_id", "occurrence", "minutes",
                                      "start", "deadline", "state")} | {
        "say": orch.get("say"), "needs": orch.get("needs"), "status": orch.get("status")}


def install(app: Any, namespace: dict[str, Any]) -> Any:
    """Wire the read-only route. Returns the collect function (for tests)."""
    from fastapi import Header, HTTPException
    from fastapi.responses import Response

    data_path = namespace["data_path"]

    def _auth(authorization: Any) -> None:
        fn = namespace.get("require_read_auth")
        if callable(fn):
            fn(authorization)

    def _runtime() -> Any:
        got = namespace.get("_SYSTEM3_RUNTIME")
        return got() if callable(got) else got

    @app.get("/api/script/segment/{segment_id}/decision-tree")
    async def script_segment_decision_tree(segment_id: str, authorization: str | None = Header(default=None)):
        """[rounds-tree] One segment's rounds as the graph walked them: stages with
        their roll receipts and the roulette diamonds between them. Read only."""
        _auth(authorization)
        rt = _runtime()
        if rt is None or getattr(rt, "store", None) is None:
            raise HTTPException(503, "System 3 is not installed, so there is no roll to show")
        seg_id = str(segment_id or "").strip()
        entry = None
        room_of = namespace.get("director_room")
        if callable(room_of):
            for which in (0, 1):
                try:
                    room = await asyncio.wait_for(asyncio.to_thread(room_of, which), timeout=15.0)
                except Exception:  # noqa: BLE001
                    break
                entry = next((x for x in room.get("entries") or []
                              if str(x.get("occurrence") or "") == seg_id), None)
                if entry:
                    break
        origin = Path(data_path("system3_origin.sqlite3"))
        got = await rt.read(collect, rt.store, seg_id, entry, origin)
        if not entry and not got.get("registered"):
            raise HTTPException(404, "no segment %s: the director's room holds this hour and the next, and "
                                     "System 3's register keeps seven days" % seg_id)
        out = {"schema": SCHEMA, "segment_id": seg_id, "at": time.time(), "entry": entry_brief(entry),
               **got}
        body = json.dumps(out, default=str)
        return Response(content=body, media_type="application/json")

    return collect
