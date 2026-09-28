"""Editable, bounded conversation graphs for scheduled talk segments.

The graph is data, not a prompt template.  A seeded walk makes the same
segment occurrence receive the same dice results on repeated prompt reads.
"""

from __future__ import annotations

from typing import Any


TYPES = {"initiator", "reply", "rebuttal", "topic_change", "call", "decision", "end", "protocol"}
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
