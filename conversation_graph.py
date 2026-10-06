"""Editable, bounded conversation graphs for scheduled talk segments.

The graph is data, not a prompt template.  A seeded walk makes the same
segment occurrence receive the same dice results on repeated prompt reads.
"""

from __future__ import annotations

from typing import Any
import system3_reply


TYPES = {"initiator", "reply", "rebuttal", "topic_change", "call", "decision", "end", "protocol", "book_reader"}
DEFAULT_MOODS = [
    "takes the point seriously", "feels challenged by the argument",
    "reconsiders part of their position", "pushes back on the premise",
    "finds common ground", "thinks the reply missed the point",
]
DEFAULT_INTONATIONS = ["measured", "bright", "dry", "urgent", "reflective", "playful"]


def _text(value: Any, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _number(value: Any, default: float, low: float, high: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if result != result or result in (float("inf"), float("-inf")):
        result = default
    return round(max(low, min(high, result)), 3)


def normalize(raw: Any) -> dict[str, Any]:
    """Reject broken links and bound all operator supplied graph data."""
    source = raw if isinstance(raw, dict) else {}
    def items(value: Any, limit: int) -> list[Any]:
        return value[:limit] if isinstance(value, list) else []

    nodes, seen = [], set()
    for index, item in enumerate(items(source.get("nodes"), 64)):
        if not isinstance(item, dict):
            continue
        kind = _text(item.get("type"), 32).lower()
        if kind not in TYPES:
            continue
        ident = _text(item.get("id"), 64) or f"node-{index + 1}"
        if ident in seen:
            continue
        seen.add(ident)
        nodes.append({
            "id": ident, "type": kind,
            "label": _text(item.get("label"), 80) or kind.replace("_", " ").title(),
            "speaker": _text(item.get("speaker"), 60),
            **({"readers": [r for r in items(item.get("readers") or ["host", "cohost", "third"], 6)
                            if r in ("host", "cohost", "third", "sfx", "manager", "caller")],
                "routing": _text(item.get("routing"), 20) if item.get("routing") in ("single", "sequential", "roulette") else "sequential",
                "weights": {r: _number((item.get("weights") or {}).get(r), 1, 0, 100)
                            for r in ("host", "cohost", "third", "sfx", "manager", "caller")}}
               if kind == "book_reader" else {}),
            "protocol_road": _text(item.get("protocol_road"), 40),
            "respond_to": _text(item.get("respond_to"), 64),
            "topic": _text(item.get("topic"), 200),
            "prompt": _text(item.get("prompt"), 600),
            "draws": [{"family": draw["family"],
                       "tables": [_text(table, 60) for table in items(draw.get("tables"), 12) if _text(table, 60)],
                       "closes": bool(draw.get("closes", False))}
                      for draw in items(item.get("draws"), 8)
                      if isinstance(draw, dict) and draw.get("family") in
                      ("CTS", "ES", "RS", "IRS", "FL")],
            "speakerbox": [mark for mark in items(item.get("speakerbox"), 2)
                           if mark in ("prepend", "append")],
            # [nodeplan] a nested call chain's shape: the RESOLVE wheel rolls at
            # "open", its words land at "close" (plan_graph). The keys exist only
            # when set, so a graph without them normalizes byte-identically to
            # the engine before these fields (the enabled-graph hash stands).
            **({"call_leg": _text(item.get("call_leg"), 8).lower()}
               if _text(item.get("call_leg"), 8).lower() in ("open", "middle", "close") else {}),
            # [s3-split] the SPLIT switch rides the node (conditional keys: an
            # untouched graph still normalizes byte-identically)
            **({"splits": True} if item.get("splits") in (True, 1) else {}),
            **({"max_splits": int(_number(item.get("max_splits"), 0, 0, 12))}
               if item.get("max_splits") not in (None, "", 0, False) else {}),
            # [nodeplan] [s3-booth] a rebuttal that takes on ONE answer: the
            # roulette over the chain's repliers, a spicier answer weighed up
            **({"target": "rolled"} if _text(item.get("target"), 8).lower() == "rolled" else {}),
            "seconds": _number(item.get("seconds"), 12, 0, 300),
            "chance": _number(item.get("chance"), 1, 0, 1),
            "moods": [_text(x, 60) for x in items(item.get("moods") or DEFAULT_MOODS, 12)
                      if _text(x, 60)],
            "intonations": [_text(x, 60) for x in items(item.get("intonations") or DEFAULT_INTONATIONS, 12)
                            if _text(x, 60)],
            "x": _number(item.get("x"), 0, -2000, 2000),
            "y": _number(item.get("y"), index * 90, -2000, 2000),
        })
    ids = {node["id"] for node in nodes}
    edges = []
    for item in items(source.get("edges"), 128):
        if not isinstance(item, dict):
            continue
        origin, target = _text(item.get("from"), 64), _text(item.get("to"), 64)
        if origin not in ids or target not in ids:
            continue
        edges.append({"from": origin, "to": target,
                      "weight": _number(item.get("weight"), 1, 0, 100),
                      "label": _text(item.get("label"), 60)})
    start = _text(source.get("start"), 64)
    if start not in ids:
        start = next((node["id"] for node in nodes if node["type"] == "initiator"),
                     nodes[0]["id"] if nodes else "")
    return {"nodes": nodes, "edges": edges, "start": start,
            "reply_roulette": system3_reply.normalize(source.get("reply_roulette")),
            "enabled": bool(source.get("enabled", False)),
            "topic_options": [_text(x, 120) for x in items(source.get("topic_options"), 30)
                              if _text(x, 120)],
            "max_steps": int(_number(source.get("max_steps"), 48, 1, 120))}


def default_graph(topic: str = "") -> dict[str, Any]:
    """The initiator/reply/rebuttal/topic loop described by the operator."""
    rows = [
        ("start", "initiator", 0, 0, 18, 1),
        ("reply_gate", "decision", 0, 60, 0, 1),
        ("reply_a", "reply", -100, 110, 16, 1),
        ("reply_b", "reply", 100, 220, 16, 1),
        ("call_gate", "decision", 0, 330, 0, 1),
        ("call", "call", -230, 440, 35, 1),
        ("call_reply", "reply", -250, 520, 16, 1),
        ("call_followup", "call", -250, 600, 20, 1),
        ("call_return", "reply", -250, 680, 16, 1),
        ("expand_one", "decision", 80, 440, 0, 1),
        ("reply_c", "reply", -170, 550, 16, 1),
        ("expand_two", "decision", -80, 660, 0, 1),
        ("reply_d", "reply", -190, 770, 16, 1),
        ("rebuttal", "rebuttal", 100, 790, 20, 1),
        ("answer_a", "reply", 80, 900, 14, .5),
        ("answer_b", "reply", 80, 1010, 14, .5),
        ("topic_change", "topic_change", 80, 1120, 10, 1),
        ("end", "end", 230, 1230, 8, 1),
    ]
    draws = {"initiator": [{"family": "CTS"}, {"family": "ES"}],
             "reply": [{"family": "ES"}, {"family": "RS"}],
             "rebuttal": [{"family": "ES"}, {"family": "IRS"}],
             "topic_change": [{"family": "ES"}, {"family": "FL"}],
             "call": [{"family": "ES"}, {"family": "RS"}],
             "end": [{"family": "ES"}, {"family": "FL", "closes": True}]}
    nodes = [{"id": ident, "type": kind, "label": ident.replace("_", " ").title(),
              "x": x, "y": y, "seconds": sec, "chance": chance,
              "draws": draws.get(kind, []),
              "topic": topic if ident == "start" else ""} for ident, kind, x, y, sec, chance in rows]
    for node in nodes:
        if node["id"] == "start":
            node["speakerbox"] = ["prepend"]
            # [s3-split] the chapter's opening-monologue node ships with the
            # SPLIT switch on, exactly like the cycle's `initial` step after
            # the split defaults - so add_split_defaults has nothing to tick
            # on a config built from these defaults
            node["splits"] = True
        if node["id"] == "end":
            node["speakerbox"] = ["append"]
        if node["id"] in ("answer_a", "answer_b"):
            node["respond_to"] = "reply_" + node["id"][-1]
        if node["id"] == "call_reply":
            node["prompt"] = "Answer the caller's actual point and show they heard the current discussion."
        if node["id"] == "call_followup":
            node["prompt"] = "Respond to the station's answer with a follow-up rooted in the topic."
        if node["id"] == "call_return":
            node["prompt"] = "Answer the caller's follow-up and hand the discussion back to the cast."
    links = [
        ("start", "reply_gate", 1), ("reply_gate", "reply_a", .85),
        ("reply_gate", "topic_change", .15), ("reply_a", "reply_b", 1),
        ("reply_b", "call_gate", 1), ("call_gate", "call", .12),
        ("call_gate", "expand_one", .88), ("call", "call_reply", 1),
        ("call_reply", "call_followup", 1), ("call_followup", "call_return", 1),
        ("call_return", "expand_one", 1),
        ("expand_one", "reply_c", .5), ("expand_one", "rebuttal", .5),
        ("reply_c", "expand_two", 1), ("expand_two", "reply_d", .5),
        ("expand_two", "rebuttal", .5), ("reply_d", "rebuttal", 1),
        ("rebuttal", "answer_a", 1), ("answer_a", "answer_b", 1),
        ("answer_b", "topic_change", 1), ("topic_change", "start", .7),
        ("topic_change", "end", .3),
    ]
    return normalize({"enabled": False, "nodes": nodes, "edges": [
        {"from": a, "to": b, "weight": weight} for a, b, weight in links],
        "start": "start", "max_steps": 48})


def protocol_graph(road: str) -> dict[str, Any]:
    """A macro node for a road whose internal protocol already owns its turns."""
    return normalize({"enabled": True, "start": "protocol", "nodes": [{"id": "protocol", "type": "protocol",
                      "label": str(road).replace("_", " ").title() + " protocol",
                      "protocol_road": road, "seconds": 60, "chance": 1}], "edges": []})


def validate(raw: Any) -> list[str]:
    """Report path mistakes before an edited graph becomes live config."""
    graph = normalize(raw)
    nodes = graph["nodes"]
    if not nodes:
        return []  # An empty graph leaves the established road structure in charge.
    if any(node["type"] == "protocol" for node in nodes):
        if len(nodes) != 1 or graph["edges"]:
            return ["a protocol wraps its existing internal nodes as one graph node"]
        return []
    ids = {node["id"] for node in nodes}
    if not any(node["type"] == "end" for node in nodes):
        return ["add an end node so the segment can close"]
    reply_ids = {node["id"] for node in nodes if node["type"] == "reply"}
    bad_references = [node["label"] for node in nodes
                      if node["respond_to"] and node["respond_to"] not in reply_ids]
    if bad_references:
        return ["reply source must name a reply node: " + ", ".join(bad_references[:5])]
    outgoing = {ident: [] for ident in ids}
    for edge in graph["edges"]:
        if edge["weight"] > 0:
            outgoing[edge["from"]].append(edge["to"])
    seen, pending = set(), [graph["start"]]
    while pending:
        ident = pending.pop()
        if ident in seen:
            continue
        seen.add(ident)
        pending.extend(outgoing.get(ident, []))
    problems = []
    if not any(node["type"] == "end" and node["id"] in seen for node in nodes):
        problems.append("the start node cannot reach an end node")
    unreachable = [node["label"] for node in nodes if node["id"] not in seen]
    if unreachable:
        problems.append("unreachable nodes: " + ", ".join(unreachable[:5]))
    dead = [node["label"] for node in nodes if node["type"] != "end" and not outgoing[node["id"]]]
    if dead:
        problems.append("nodes without an outgoing flow: " + ", ".join(dead[:5]))
    return problems


def road_graph(road, structure=None):
    """[nodeplan] The talk chapter derived from a road's current structure.

    Every segment is a variant of the operator's node graph (nodeplan.md):
    the road's own opening act is the initiator statement (a single-voice
    road keeps its door seat, its act and its LINE draw over the handed-in
    candidates), the studio's replies are raffled per the chain dice, the
    50% expansion is rolled twice, the initiator rebuts the chain, each
    replier gets the 1:2 answer to the rebuttal, and the 1:3 exit diamond
    either pads with another chapter (topic change - on a specific segment
    a chance-gated roll on changing the discussion points) or lands the
    segment on the road's own closing act. Returned DISABLED: the road's
    existing planner stays in charge until the operator turns it on."""
    road = str(road or "").partition("~")[0]
    st = structure if isinstance(structure, dict) else {}
    legs = [x for x in st.get("legs") or [] if isinstance(x, dict)]
    opening = [x for x in legs if x.get("place") == "open"]
    middle = [x for x in legs if x.get("place") == "middle"]
    closing = [x for x in legs if x.get("place") == "close"]
    line_road = not opening and not middle
    lead = opening[0] if opening else (legs[0] if legs else {})
    mid = middle[0] if middle else {}
    close = closing[-1] if closing else {}

    def act(leg, fallback):
        return " ".join(str(leg.get("act") or fallback).split())[:600]

    open_prompt = act(lead, "Opens this chapter with a concrete point.")
    reply_prompt = act(mid, "")
    if line_road:
        # No one-line segments: the studio answers the line as its own chapter.
        rows = [
            ("start", "initiator", open_prompt, 10, 1, ""),
            ("reply_a", "reply", "Reacts to the line just aired: a real reaction in their own voice.", 8, 1, ""),
            ("more_gate", "decision", "", 0, 1, ""),
            ("reply_b", "reply", "Answers the reaction before it and keeps the exchange alive.", 8, 1, ""),
            ("rebuttal", "rebuttal", "", 10, 1, ""),
            ("answer_a", "reply", "", 7, .5, "reply_a"),
            ("answer_b", "reply", "", 7, .5, "reply_b"),
            ("end", "end", "Lands it in one line and hands back to the show.", 6, 1, ""),
        ]
        links = [("start", "reply_a", 1), ("reply_a", "more_gate", 1),
                 ("more_gate", "reply_b", .6), ("more_gate", "rebuttal", .4),
                 ("reply_b", "rebuttal", 1), ("rebuttal", "answer_a", 1),
                 ("answer_a", "answer_b", 1), ("answer_b", "end", 1)]
    else:
        rows = [
            ("start", "initiator", open_prompt, 14, 1, ""),
            ("reply_gate", "decision", "", 0, 1, ""),
            ("reply_a", "reply", reply_prompt, 12, 1, ""),
            ("reply_b", "reply", reply_prompt, 12, 1, ""),
            ("call_gate", "decision", "", 0, 1, ""),
            ("call", "call", "", 30, 1, ""),
            ("call_reply", "reply", "Answers the caller's actual point and shows they heard this discussion.",
             12, 1, ""),
            ("call_close", "call", "Comes back on the answer and lets the cast take the discussion home.",
             16, 1, ""),
            ("expand_one", "decision", "", 0, 1, ""),
            ("reply_c", "reply", reply_prompt, 12, 1, ""),
            ("expand_two", "decision", "", 0, 1, ""),
            ("reply_d", "reply", reply_prompt, 12, 1, ""),
            ("rebuttal", "rebuttal", "", 14, 1, ""),
            ("answer_a", "reply", "", 10, .5, "reply_a"),
            ("answer_b", "reply", "", 10, .5, "reply_b"),
            ("answer_c", "reply", "", 10, .5, "reply_c"),
            ("answer_d", "reply", "", 10, .5, "reply_d"),
            ("exit_gate", "decision", "", 0, 1, ""),
            ("topic_change", "topic_change", "", 8, .5, ""),
            ("end", "end", act(close, "Closes the segment with an amiable ending."), 8, 1, ""),
        ]
        links = [("start", "reply_gate", 1),
                 ("reply_gate", "reply_a", .85), ("reply_gate", "exit_gate", .15),
                 ("reply_a", "reply_b", 1), ("reply_b", "call_gate", 1),
                 ("call_gate", "call", .12), ("call_gate", "expand_one", .88),
                 ("call", "call_reply", 1), ("call_reply", "call_close", 1),
                 ("call_close", "expand_one", 1),
                 ("expand_one", "reply_c", .5), ("expand_one", "rebuttal", .5),
                 ("reply_c", "expand_two", 1),
                 ("expand_two", "reply_d", .5), ("expand_two", "rebuttal", .5),
                 ("reply_d", "rebuttal", 1),
                 ("rebuttal", "answer_a", 1), ("answer_a", "answer_b", 1),
                 ("answer_b", "answer_c", 1), ("answer_c", "answer_d", 1),
                 ("answer_d", "exit_gate", 1),
                 ("exit_gate", "topic_change", .67), ("exit_gate", "end", .33),
                 ("topic_change", "start", 1)]
    draws = {"initiator": ([{"family": "ES"}] if line_road else [{"family": "CTS"}, {"family": "ES"}]),
             "reply": [{"family": "ES"}, {"family": "RS"}],
             "rebuttal": [{"family": "ES"}, {"family": "IRS"}],
             "topic_change": [{"family": "ES"}, {"family": "FL"}],
             "call": [{"family": "ES"}, {"family": "RS"}],
             "end": [{"family": "ES"}, {"family": "FL", "closes": True}]}
    nodes = []
    for index, (ident, kind, prompt, seconds, chance, respond_to) in enumerate(rows):
        node = {"id": ident, "type": kind, "label": ident.replace("_", " ").title(),
                "prompt": prompt, "seconds": seconds, "chance": chance,
                "respond_to": respond_to, "draws": draws.get(kind, []),
                "x": (-140 if kind in ("reply", "call") else 60), "y": index * 100}
        if kind == "initiator":
            if line_road:
                # the road's own voice opens: the door seat wins at plan time
                node["protocol_road"] = road
                node["speaker"] = str(lead.get("seat") or "")
            else:
                node["speakerbox"] = ["prepend"]
            if lead.get("splits") in (True, 1):
                # [s3-split] the chapter keeps the road's split switch
                node["splits"] = True
                if lead.get("max_splits"):
                    node["max_splits"] = lead.get("max_splits")
        if ident == "call":
            node["call_leg"] = "open"
        if ident == "call_close":
            node["call_leg"] = "close"
        if kind == "rebuttal":
            # [s3-booth] the lead comes back on ONE answer: rolled, spice-weighed
            node["target"] = "rolled"
        if kind == "end" and not line_road:
            node["speakerbox"] = ["append"]
        nodes.append(node)
    return normalize({"enabled": False, "nodes": nodes,
                      "edges": [{"from": a, "to": b, "weight": w} for a, b, w in links],
                      "start": "start", "max_steps": 48})
