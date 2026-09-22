"""word_cause_edits - what the cause graph changed, and how to put it back.

[#1386] The graph is an authoring surface: it lets the operator rewrite a
system prompt, re-weight a speakbox document, cut a passage, burn a gold
bar and ban a phrase, from inside the picture that showed him the cause.
Every one of those writes to a live station.

So every write is written down FIRST, with the value it is about to
replace, and the rail offers to put it back. That is the whole of this
module: app.py owns the stores, their locks and their HTTP doors, and this
owns the row, the inverse and the sentence - so both halves can be tested
off a temp directory with no station running.

TWO THINGS IT REFUSES TO PRETEND ABOUT.

`.bak-1241` is a FIRST-EDIT snapshot (app.py:120876 writes it only if it
does not already exist), not an undo. It is not consulted here and must
never be offered as one.

And some acts cannot be undone at all: a phrase ban retires prepared
rounds and burns gold bars as it goes, and lifting the ban restores
neither. Those rows carry `undoable: false` AND the reason, so the list
never grows a button that would lie about what it does.

Nothing here reads a file, a clock or a global.
"""
from __future__ import annotations

import json
from typing import Any

SCHEMA = 1

# Which endpoints can be walked backwards, and what walking backwards means.
# A door not in here is recorded and shown, but never offered a button.
INVERSE: dict[str, dict[str, Any]] = {
    "/api/speakbox/weight": {"method": "POST", "field": "weight",
                             "say": "put the document's weight back"},
    "/api/dj/dial": {"method": "POST", "field": "value",
                     "say": "put the dial back"},
    "/api/gold/burn": {"method": "POST", "to": "/api/gold/restore",
                       "say": "put the bar back in the bank"},
    "/api/gold/restore": {"method": "POST", "to": "/api/gold/burn",
                          "say": "burn it again"},
    "/api/prompt/cuts": {"method": "POST", "to": "/api/prompt/cuts/remove",
                         "say": "put the lines back into the prompt"},
    "/api/prompt/cuts/remove": {"method": "POST", "to": "/api/prompt/cuts",
                                "say": "cut them out again"},
    "/api/paperwork/field": {"method": "PUT", "field": "value",
                             "say": "put the words back as they were"},
}

# Acts that change more than the thing they name, and cannot be walked back.
NOT_UNDOABLE: dict[str, str] = {
    "/api/phrase/ban": (
        "a ban does three things at once - it blocks the phrase, retires "
        "every prepared round carrying it and burns the gold bars that "
        "have it. Lifting the ban unblocks the phrase and restores "
        "neither the rounds nor the bars, so this cannot be put back from "
        "here"),
}


def row(endpoint: str, *, was: Any = None, now: Any = None,
        key: str = "", word: str = "", node_id: str = "",
        node_type: str = "", method: str = "POST", at: float = 0.0,
        by: str = "the cause graph", say: str = "") -> dict[str, Any]:
    """One edit, as it goes into the ledger.

    Written BEFORE the store is called, so a write that then fails still
    leaves a record that it was attempted - which is the only way the
    operator can tell "I did not do that" from "it did not take"."""
    endpoint = str(endpoint or "")
    why = NOT_UNDOABLE.get(endpoint, "")
    return {
        "schema": SCHEMA,
        "at": float(at or 0.0),
        "word": str(word or "")[:80],
        "node_id": str(node_id or "")[:80],
        "node_type": str(node_type or "")[:32],
        "endpoint": endpoint[:120],
        "method": str(method or "POST").upper()[:8],
        "key": str(key or "")[:200],
        "was": _plain(was),
        "now": _plain(now),
        "by": str(by or "")[:40],
        "say": str(say or "")[:240],
        "undoable": (not why) and endpoint in INVERSE,
        "why_not": why,
        "undone": 0.0,
    }


def _plain(value: Any) -> Any:
    """Whatever it is, in something json.dumps will take. A ledger that
    cannot be written is not a ledger."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:4000]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)[:4000]


def undo_call(entry: dict[str, Any]) -> dict[str, Any] | None:
    """The call that puts this edit back, or None when there is not one.

    Returns {endpoint, method, body} - app.py makes the call, because
    app.py owns the doors."""
    if not isinstance(entry, dict):
        return None
    if entry.get("undone"):
        return None
    if not entry.get("undoable"):
        return None
    spec = INVERSE.get(str(entry.get("endpoint") or ""))
    if not spec:
        return None
    body: dict[str, Any] = {}
    key = str(entry.get("key") or "")
    endpoint = str(spec.get("to") or entry.get("endpoint") or "")
    # The two shapes: a door that takes a value back, and a door whose
    # opposite is a different door.
    if spec.get("field"):
        if key:
            body["key"] = key
        body[str(spec["field"])] = entry.get("was")
        # the doors that echo a `was` for optimistic concurrency get the
        # value we are replacing, which is what we last wrote.
        body["was"] = entry.get("now")
        if str(entry.get("endpoint")) == "/api/speakbox/weight":
            body = {"file": key, "weight": entry.get("was"),
                    "was": entry.get("now")}
        if str(entry.get("endpoint")) == "/api/paperwork/field":
            body = {"scope": str(entry.get("node_type") or ""), "key": key,
                    "value": entry.get("was"), "was": entry.get("now")}
    else:
        was = entry.get("was")
        body = was if isinstance(was, dict) else {"keys": [key] if key else []}
    return {"endpoint": endpoint,
            "method": str(spec.get("method") or "POST").upper(),
            "body": body,
            "say": str(spec.get("say") or "put it back")}


def listing(rows: list[dict[str, Any]], most: int = 20) -> list[dict[str, Any]]:
    """The last `most` edits, newest first, each saying honestly whether it
    can be put back."""
    out: list[dict[str, Any]] = []
    for entry in reversed([r for r in rows if isinstance(r, dict)]):
        got = dict(entry)
        got["can_undo"] = bool(undo_call(entry))
        if not got["can_undo"] and not got.get("why_not"):
            got["why_not"] = ("nothing here knows how to reverse that door"
                              if not entry.get("undone")
                              else "it has already been put back")
        out.append(got)
        if len(out) >= most:
            break
    return out


def find(rows: list[dict[str, Any]], at: float) -> int:
    """Which row is the one stamped `at`, or -1. Matched on the stamp
    because that is what the rail hands back, and two edits cannot share
    one."""
    for i, entry in enumerate(rows):
        if isinstance(entry, dict) and float(entry.get("at") or 0) == float(at):
            return i
    return -1
