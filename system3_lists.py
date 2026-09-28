"""[s3-lists] Every list that feeds the air is a table on System 3's desk.

Operator (2026-09-28), pointing at the empty space under POOL in the Tables
tab: "the system that made the 'I sold the tapes to Sawyer.'. I need to be
able to access that list of items in that database and be able to edit them
and remove them / add to it. Any list to do with conversation or the
roulette needs to be listed here as an editable table."

This is the machinery only - no station imports, so it is tested on its
own. app.py registers each list against the store that owns it (its own
load, save and lock) and serves the doors:

    GET    /api/system3/lists                       the registry, with counts
    GET    /api/system3/lists/{id}?offset=&limit=&q=&state=
    POST   /api/system3/lists/{id}/rows             add
    PUT    /api/system3/lists/{id}/rows/{row_id}    edit and/or switch
    DELETE /api/system3/lists/{id}/rows/{row_id}    remove

A list is {id, label, family, what, schema, rows(), add?, edit?, switch?,
remove?}. `rows()` answers every row as a dict with at least "id" and
"text"; the facts the desk shows are optional: "on", "state", "plays",
"last_played", "why", "note". A handler it does not have is a door that
answers 405 - the UI draws only the controls a list can take.

Every write is written down BEFORE the store is called (who, when, which
list, which row, what was asked), and a failure is written after it - the
same rule as the word-cause doors: a write that then fails still leaves a
record that it was attempted, which is the only way to tell "I did not do
that" from "it did not take".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable

FAMILIES = ("BANK", "LIST")
MAX_LIMIT = 500


class ListError(Exception):
    """A door's refusal: an HTTP status and the reason, in words."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def norm(text: Any) -> str:
    """One line's words, however they are spaced or cased."""
    return " ".join(str(text or "").lower().split())


def text_id(text: Any) -> str:
    """A row's id when a list keeps bare words: a digest of the words."""
    return hashlib.sha1(norm(text).encode("utf-8")).hexdigest()[:16]


def clean_words(text: Any, most: int = 400) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        raise ListError(400, "the row has no words")
    if len(text) > most:
        raise ListError(400, "%d characters at most" % most)
    return text


class ListRegistry:
    def __init__(self, edits_path: Any, *, clock: Callable[[], float] = time.time) -> None:
        self.edits_path = Path(edits_path)
        self.clock = clock
        self.lists: dict[str, dict[str, Any]] = {}
        self._edits_lock = threading.RLock()

    # --- the registry ---------------------------------------------------------
    def register(self, spec: dict[str, Any]) -> dict[str, Any]:
        lid = str(spec.get("id") or "").strip()
        if not lid or "/" in lid:
            raise ValueError("a list needs an id without a slash")
        if spec.get("family") not in FAMILIES:
            raise ValueError("family is one of %s" % ", ".join(FAMILIES))
        if not callable(spec.get("rows")):
            raise ValueError("a list needs rows()")
        for door in ("add", "edit", "switch", "remove", "count"):
            if spec.get(door) is not None and not callable(spec.get(door)):
                raise ValueError("%s must be callable" % door)
        self.lists[lid] = dict(spec, id=lid)
        return self.lists[lid]

    def spec(self, lid: str) -> dict[str, Any]:
        got = self.lists.get(str(lid))
        if got is None:
            raise ListError(404, "no list %s" % lid)
        return got

    def meta(self, spec: dict[str, Any], count: Any = None) -> dict[str, Any]:
        return {"id": spec["id"], "label": spec.get("label") or spec["id"], "family": spec["family"],
                "what": spec.get("what") or "", "schema": spec.get("schema") or [
                    {"key": "text", "kind": "text", "label": "the words"}],
                "store": spec.get("store") or "", "count": count,
                "can": {door: spec.get(door) is not None for door in ("add", "edit", "switch", "remove")}}

    def catalog(self) -> list[dict[str, Any]]:
        out = []
        for spec in self.lists.values():
            try:
                count = spec["count"]() if spec.get("count") else len(spec["rows"]())
            except Exception as exc:  # noqa: BLE001 - one broken store must not blank the others
                count, spec_error = None, "%s: %s" % (type(exc).__name__, exc)
            else:
                spec_error = ""
            got = self.meta(spec, count)
            if spec_error:
                got["error"] = spec_error
            out.append(got)
        return out

    # --- reading --------------------------------------------------------------
    def page(self, lid: str, *, offset: int = 0, limit: int = 50, q: str = "",
             state: str = "") -> dict[str, Any]:
        spec = self.spec(lid)
        rows = [dict(r) for r in spec["rows"]()]
        want = norm(q)
        if want:
            rows = [r for r in rows if want in norm(" ".join(str(r.get(k) or "") for k in
                                                             ("text", "airs_as", "note", "id")))]
        states: dict[str, int] = {}          # what the search found, before the state filter
        for r in rows:
            key = str(r.get("state") or ("on" if r.get("on", True) is not False else "off"))
            states[key] = states.get(key, 0) + 1
        if state:
            rows = [r for r in rows if (str(r.get("state") or "") == state
                                        or (state == "on" and r.get("on", True) is not False)
                                        or (state == "off" and r.get("on", True) is False))]
        total = len(rows)
        offset = max(0, int(offset or 0))
        limit = max(1, min(MAX_LIMIT, int(limit or 50)))
        return {"list": self.meta(spec, total if not (want or state) else None), "total": total,
                "offset": offset, "limit": limit, "states": states,
                "rows": rows[offset:offset + limit], "edits": self.edits(lid, 12)}

    def row(self, lid: str, row_id: str) -> dict[str, Any] | None:
        return next((dict(r) for r in self.spec(lid)["rows"]() if str(r.get("id")) == str(row_id)), None)

    # --- writing --------------------------------------------------------------
    def _door(self, spec: dict[str, Any], door: str) -> Callable[..., Any]:
        fn = spec.get(door)
        if fn is None:
            raise ListError(405, "%s cannot be %s from the desk" % (spec.get("label") or spec["id"], {
                "add": "added to", "edit": "edited", "switch": "switched", "remove": "removed from"}[door]))
        return fn

    def _run(self, lid: str, op: str, row_id: str, asked: dict[str, Any], who: dict[str, Any],
             call: Callable[[], Any]) -> Any:
        before = self.row(lid, row_id) if row_id else None
        if row_id and before is None:
            raise ListError(404, "no row %s in %s" % (row_id, lid))
        at = self.note({"list": lid, "op": op, "row": row_id, "asked": asked, "who": who,
                        "before": _brief(before)})
        try:
            return call()
        except ListError as exc:
            self.note({"at": at, "list": lid, "failed": str(exc)})
            raise
        except KeyError as exc:
            self.note({"at": at, "list": lid, "failed": "no such row"})
            raise ListError(404, "no row %s in %s" % (row_id or exc, lid)) from exc
        except ValueError as exc:
            self.note({"at": at, "list": lid, "failed": str(exc)})
            raise ListError(400, str(exc)) from exc
        except OSError as exc:
            self.note({"at": at, "list": lid, "failed": "%s: %s" % (type(exc).__name__, exc)})
            raise ListError(503, "the store could not be written: %s" % exc) from exc
        except Exception as exc:
            self.note({"at": at, "list": lid, "failed": "%s: %s" % (type(exc).__name__, exc)})
            raise

    def add(self, lid: str, body: dict[str, Any], who: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = self.spec(lid)
        fn = self._door(spec, "add")
        body = dict(body or {})
        new_id = self._run(lid, "add", "", body, who or {}, lambda: fn(body))
        return {"ok": True, "id": new_id, "row": self.row(lid, new_id) if new_id else None}

    def edit(self, lid: str, row_id: str, body: dict[str, Any], who: dict[str, Any] | None = None) -> dict[str, Any]:
        """One PUT may carry new words, the on/off switch, or both: the words
        first (they may move the row to a new id), the switch after."""
        spec = self.spec(lid)
        body = dict(body or {})
        fields = {k: v for k, v in body.items() if k != "on"}
        if not fields and "on" not in body:
            raise ListError(400, "nothing to change")
        edit_fn = self._door(spec, "edit") if fields else None
        switch_fn = self._door(spec, "switch") if "on" in body else None
        current = row_id
        if edit_fn is not None:
            current = self._run(lid, "edit", row_id, fields, who or {},
                                lambda: edit_fn(row_id, fields)) or row_id
        if switch_fn is not None:
            on = bool(body["on"])
            current = self._run(lid, "switch", current, {"on": on}, who or {},
                                lambda: switch_fn(current, on)) or current
        return {"ok": True, "id": current, "was": row_id, "row": self.row(lid, current)}

    def remove(self, lid: str, row_id: str, who: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = self.spec(lid)
        fn = self._door(spec, "remove")
        got = self._run(lid, "remove", row_id, {}, who or {}, lambda: fn(row_id))
        return {"ok": True, "removed": row_id, "detail": got}

    # --- the record of desk edits --------------------------------------------
    def note(self, row: dict[str, Any]) -> float:
        at = float(row.get("at") or self.clock())
        line = dict(row, at=at)
        try:
            with self._edits_lock:
                self.edits_path.parent.mkdir(parents=True, exist_ok=True)
                with self.edits_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
        return at

    def edits(self, lid: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """The newest desk edits (of one list), each marked with its failure
        if it did not take."""
        out: list[dict[str, Any]] = []
        failed: dict[float, str] = {}
        try:
            with self.edits_path.open(encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    try:
                        got = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(got, dict) or (lid and got.get("list") != lid):
                        continue
                    if "failed" in got:
                        failed[float(got.get("at") or 0)] = str(got["failed"])
                    else:
                        out.append(got)
        except OSError:
            return []
        out = out[-max(1, int(limit)):]
        for got in out:
            if float(got.get("at") or 0) in failed:
                got["failed"] = failed[float(got["at"])]
        return list(reversed(out))


def _brief(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {k: row.get(k) for k in ("id", "text", "on", "state") if k in row}


def who_of(host: str = "", agent: str = "") -> dict[str, Any]:
    """Who is at the desk, the way #1029 names who moved the broadcast."""
    agent = str(agent or "")
    return {"addr": str(host or "?"), "what": ("the desktop app" if "Electron" in agent
                                               else "a browser tab" if agent else "something unnamed"),
            "agent": agent[:120]}
