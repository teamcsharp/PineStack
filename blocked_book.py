"""[blocked-book] Every blocked case on the station, in one book. 2026-10-06.

"At the top of The Works put a second tab that shows each and every blocked
listing ... an expandable tree that tells me what system did it, why it was
blocked, the rule causing the block, what section got it blocked, where the
gate that blocked it is located, and the System 3 roulette roll that caused the
rejection. Offer a button to sort by rule, time/date, segment, roulette roll,
node."

The station already writes every refusal down, in seven places and seven
shapes: the flow ledger (a wedge System 3 held), the no-repeat book's refusals,
the hand-over withdrawals, the recovery pen's parked drafts, the cupboard's
standing reasons per row, the dynamic segments' pending occurrences, the pantry
lifecycle's events, and System 3's own WITHHELD / ABANDONED observations. This
module reads them all and answers GET /api/blocked with one row shape:

    at, standing, system, rule, why, section, node, ref, text,
    gate {file, line, fn}, roll {conversation_id, turn_id, family, item, d100}

Nothing here decides anything; it is a reading of what the ledgers hold.
Gate locations come from a one-time scan of the station's source for the call
sites that write each ledger, mapped to the enclosing function.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

try:
    from fastapi import Header
except Exception:  # pragma: no cover - the unit tests do not need FastAPI
    Header = None  # type: ignore

MEMO_S = 20.0
TAIL_BYTES = 2 * 1024 * 1024

# the station's standing reason codes (cupboard_why_row) and the door that owns each
CUPBOARD_DOORS = {
    "no_slot": ("_ready_slot_window", "the in-turn door: the running order is on another entry"),
    "road_closed": ("_ready_shelf_row", "RESCUE_ROADS_OPEN: this road may not air out of turn"),
    "unrendered": ("dialogue_audio_ready", "written, not yet recorded"),
    "recast": ("cast_signature", "a seat the takes speak in has changed"),
    "clip_gone": ("pantry_get", "its audio left the pantry"),
    "not_ready": ("dialogue_row_ready", "the zero-work-to-air predicate says no"),
    "behind_others": ("dialogue_stock_items", "others of its kind are ahead in the queue"),
    "never_asked_for": ("unheard_stock_air", "finished radio nobody has asked for"),
    "withheld": ("s3_binding_withheld", "System 3 withholds the round"),
    "stale": ("_larder_current", "the writing contract moved (cast, crystal, plot act)"),
}

# the ledgers' writers, as call patterns in the source; the scan finds each site's function
GATE_PATTERNS = {
    "flow": re.compile(r's3_flow\(\s*"(?P<gate>[a-z_]+)"'),
    "no-repeat": re.compile(r'\bnorepeat_refuse\('),
    "handover": re.compile(r'\b_burst_withdraw\('),
    "recovery pen": re.compile(r'\bdialogue_recovery_park\w*\('),
    "system 3": re.compile(r'\bsystem3_withhold\b|\.withhold\('),
    "pantry lifecycle": re.compile(r'\blifecycle\.(note|admit_production|unavailable)\('),
    "dynamic segments": re.compile(r"SourceAnalysisPending\(|state='pending'|state=\"pending\"|'blocked'"),
}
DEF_RE = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class GateMap:
    """Where each ledger's gate lives: {system: [{gate, file, line, fn}]}, scanned once."""

    def __init__(self, files: list[Path]):
        self.files = [Path(f) for f in files]
        self.sites: dict[str, list[dict[str, Any]]] = {}
        self.at = 0.0
        self._lock = threading.Lock()

    def scan(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            if self.sites:
                return self.sites
            found: dict[str, list[dict[str, Any]]] = {k: [] for k in GATE_PATTERNS}
            for path in self.files:
                try:
                    lines = path.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
                except Exception:  # noqa: BLE001
                    continue
                owner = ""
                for i, line in enumerate(lines, 1):
                    m = DEF_RE.match(line)
                    if m:
                        owner = m.group(1)
                    for system, pat in GATE_PATTERNS.items():
                        hit = pat.search(line)
                        if not hit:
                            continue
                        if line.lstrip().startswith("#") or line.lstrip().startswith("def ") or line.lstrip().startswith("async def "):
                            continue
                        gate = hit.groupdict().get("gate") if hit.groupdict() else None
                        found[system].append({"gate": gate or "", "file": path.name, "line": i, "fn": owner})
            self.sites = found
            self.at = time.time()
            return found

    def locate(self, system: str, gate: str = "", prefer_fn: str = "") -> dict[str, Any]:
        sites = self.scan().get(system) or []
        if gate:
            for s in sites:
                if s.get("gate") == gate:
                    return dict(s)
        if prefer_fn:
            for s in sites:
                if s.get("fn") == prefer_fn:
                    return dict(s)
        return dict(sites[0]) if sites else {"gate": gate, "file": "", "line": 0, "fn": prefer_fn}


def _tail_jsonl(path: Path, most: int = 400) -> list[dict[str, Any]]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    try:
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in raw.splitlines()[-most:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _roll_of_entry(entry: Any) -> dict[str, Any]:
    """The System 3 roll a banked entry carries: its conversation and the first dice row."""
    if not isinstance(entry, dict):
        return {}
    s3 = entry.get("system3") if isinstance(entry.get("system3"), dict) else {}
    dice = entry.get("dice") if isinstance(entry.get("dice"), list) else []
    first = next((d for d in dice if isinstance(d, dict)), {})
    out = {"conversation_id": str(s3.get("conversation_id") or ""),
           "turn_id": str((first.get("s3") or {}).get("turn_id") or ""),
           "family": str(first.get("axis") or first.get("family") or ""),
           "item": str(first.get("id") or first.get("text") or "")[:80],
           "d100": first.get("roll")}
    return out if any(out.values()) else {}


class BlockedBook:
    def __init__(self, g: dict[str, Any]):
        self.g = g
        here = Path(g.get("__file__") or __file__).resolve().parent
        self.gates = GateMap([here / "app.py", here / "system3_runtime.py", here / "dynamic_segments_runtime.py",
                              here / "sfx_supercut.py", here / "pantry_lifecycle.py"])
        self.memo: dict[str, Any] = {"at": 0.0, "rows": [], "counts": {}}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- sources
    def _data(self, name: str) -> Path:
        fn = self.g.get("data_path")
        try:
            return Path(fn(name)) if callable(fn) else Path(self.g.get("DATA_DIR") or ".") / name
        except Exception:  # noqa: BLE001
            return Path(name)

    def _entry_by_ref(self, ref: str, kind: str = "") -> Any:
        """A banked row by its sid, for the roll it carries (best effort, read-only)."""
        if not ref:
            return None
        alt_sid = self.g.get("alt_sid")
        entry_of = self.g.get("dialogue_entry")
        piles: list[tuple[str, list[Any]]] = []
        shelf = self.g.get("_SHELF") or {}
        for k, rows in list(shelf.items()):
            if not kind or k == kind:
                piles.append((str(k), list(rows or [])))
        if not kind or kind == "banter":
            piles.append(("banter", list(self.g.get("_LARDER") or [])))
        for k, rows in piles:
            for row in rows[:600]:
                try:
                    sid = alt_sid(k, row) if callable(alt_sid) else str(row.get("sid") or "")
                except Exception:  # noqa: BLE001
                    sid = str(row.get("sid") or "") if isinstance(row, dict) else ""
                if sid and sid == ref:
                    e = entry_of(row) if callable(entry_of) else row
                    return e if isinstance(e, dict) else row
        return None

    def flow_rows(self, most: int) -> list[dict[str, Any]]:
        ledger = self.g.get("FLOW_LEDGER")
        if ledger is None or not hasattr(ledger, "recent"):
            return []
        out = []
        for r in ledger.recent(most, passed=False):
            gate = str(r.get("gate") or "")
            entry = self._entry_by_ref(str(r.get("ref") or ""), str(r.get("road") or ""))
            out.append({
                "at": float(r.get("at") or 0), "standing": False, "system": "flow",
                "rule": "flow." + gate, "why": str(r.get("why") or ""), "section": str(r.get("road") or ""),
                "node": str((entry or {}).get("road") or "") if isinstance(entry, dict) else "",
                "ref": str(r.get("ref") or ""), "text": str(r.get("text") or "")[:300],
                "gate": self.gates.locate("flow", gate), "roll": _roll_of_entry(entry),
                "n": r.get("n")})
        return out

    def norepeat_rows(self, most: int) -> list[dict[str, Any]]:
        hours = self.g.get("NOREPEAT_HOURS") or 24
        out = []
        for r in _tail_jsonl(self._data("norepeat_refusals.jsonl"), most):
            entry = self._entry_by_ref(str(r.get("ref") or ""), str(r.get("road") or ""))
            out.append({
                "at": float(r.get("at") or 0), "standing": False, "system": "no-repeat",
                "rule": "no repeat within %gh (%s)" % (float(hours), str(r.get("kind") or "line")),
                "why": str(r.get("why") or ""), "section": str(r.get("road") or ""),
                "node": str(r.get("stage") or ""), "ref": str(r.get("ref") or r.get("key") or ""),
                "text": str(r.get("text") or "")[:300],
                "gate": self.gates.locate("no-repeat", prefer_fn="norepeat_refuse"), "roll": _roll_of_entry(entry)})
        return out

    def withdrawn_rows(self, most: int) -> list[dict[str, Any]]:
        out = []
        for r in _tail_jsonl(self._data("withdrawn_rounds.jsonl"), most):
            why = str(r.get("why") or "")
            entry = self._entry_by_ref(str(r.get("sid") or ""), str(r.get("kind") or ""))
            out.append({
                "at": float(r.get("at") or 0), "standing": False, "system": "handover",
                "rule": "hand-over: " + (why.split(" - ")[0][:60] if why else "withdrawn"),
                "why": why, "section": str(r.get("kind") or ""), "node": "",
                "ref": str(r.get("sid") or ""), "text": "%s row(s), %s on the shelf" % (r.get("rows"), r.get("shelf")),
                "gate": self.gates.locate("handover", prefer_fn="_burst_withdraw"), "roll": _roll_of_entry(entry)})
        return out

    def parked_rows(self, most: int) -> list[dict[str, Any]]:
        out = []
        for r in _tail_jsonl(self._data("dialogue_recovery_parked.jsonl"), most):
            entry = r.get("entry") if isinstance(r.get("entry"), dict) else None
            out.append({
                "at": float(r.get("at") or 0), "standing": False, "system": "recovery pen",
                "rule": "parked: " + str(r.get("why") or "")[:60], "why": str(r.get("why") or ""),
                "section": str(r.get("kind") or ""), "node": "", "ref": str(r.get("id") or ""),
                "text": str((entry or {}).get("script") or "")[:300],
                "gate": self.gates.locate("recovery pen"), "roll": _roll_of_entry(entry)})
        return out

    def cupboard_rows(self, most: int) -> list[dict[str, Any]]:
        why_row = self.g.get("cupboard_why_row")
        if not callable(why_row):
            return []
        kinds = list(self.g.get("ROUND_SHELF_KINDS") or ("manager", "caller", "gallery", "news"))
        for extra in ("ad", "station_id", "track_talk", "sfx_supercut", "supercut_react"):
            if extra not in kinds:
                kinds.append(extra)
        shelf = self.g.get("_SHELF") or {}
        piles = [(k, list(shelf.get(k) or [])) for k in kinds] + [("banter", list(self.g.get("_LARDER") or []))]
        entry_of = self.g.get("dialogue_entry")
        out = []
        for kind, rows in piles:
            for row in rows:
                if len(out) >= most:
                    return out
                try:
                    w = why_row(kind, row)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(w, dict):
                    continue
                entry = entry_of(row) if callable(entry_of) else row
                for reason in (w.get("reasons") or []):
                    if not isinstance(reason, dict):
                        continue
                    code = str(reason.get("code") or "")
                    door = CUPBOARD_DOORS.get(code, ("cupboard_why_row", ""))
                    out.append({
                        "at": float((row.get("at") if isinstance(row, dict) else 0) or (entry or {}).get("at") or 0),
                        "standing": True, "system": "cupboard", "rule": code or "unknown",
                        "why": str(reason.get("say") or ""), "fix": str(reason.get("fix") or ""),
                        "section": kind, "node": str((entry or {}).get("road") or "") if isinstance(entry, dict) else "",
                        "ref": str(w.get("id") or ""), "text": str(w.get("text") or (entry or {}).get("script") or "")[:300],
                        "gate": {"file": "app.py", "line": 0, "fn": door[0], "note": door[1]},
                        "roll": _roll_of_entry(entry), "ready": bool(w.get("ready")), "blocked": bool(w.get("blocked"))})
        return out

    def dynamic_rows(self, most: int) -> list[dict[str, Any]]:
        rt = self.g.get("DYNAMIC_SEGMENTS_RUNTIME")
        if rt is None or not hasattr(rt, "status"):
            return []
        try:
            st = rt.status()
        except Exception:  # noqa: BLE001
            return []
        out = []
        seen = set()
        for p in (st.get("pending") or []):
            state = str(p.get("state") or "")
            if state in ("", "waiting", "ready"):
                continue
            occ = str(p.get("occurrence") or "")
            seen.add(occ)
            out.append({
                "at": float(p.get("due_at") or 0), "standing": True, "system": "dynamic segments",
                "rule": state, "why": str(p.get("why") or ""), "section": str(p.get("kind") or ""),
                "node": str(p.get("slot_id") or ""), "ref": occ, "text": "",
                "gate": self.gates.locate("dynamic segments"), "roll": {}})
        for occ, rec in (st.get("preparation") or {}).items():
            if not isinstance(rec, dict) or occ in seen:
                continue
            state = str(rec.get("state") or "")
            if state in ("", "waiting", "ready", "complete", "aired"):
                continue
            out.append({
                "at": float(rec.get("at") or 0), "standing": True, "system": "dynamic segments",
                "rule": state, "why": str(rec.get("why") or ""),
                "section": str(occ).split("-")[1] if "-" in str(occ) else "", "node": "",
                "ref": str(occ), "text": "", "gate": self.gates.locate("dynamic segments"), "roll": {}})
        return out[:most]

    def lifecycle_rows(self, most: int) -> list[dict[str, Any]]:
        lc = self.g.get("_PANTRY_LIFECYCLE")
        recent = getattr(lc, "recent", None)
        if not isinstance(recent, list):
            return []
        out = []
        for ev in list(recent)[-most:]:
            if not isinstance(ev, dict):
                continue
            action = str(ev.get("action") or "")
            if action in ("ready", "delivered", "admit", ""):
                continue
            out.append({
                "at": float(ev.get("at") or 0), "standing": False, "system": "pantry lifecycle",
                "rule": action, "why": str(ev.get("why") or ""), "section": str(ev.get("kind") or ""),
                "node": "", "ref": str(ev.get("id") or ""), "text": "",
                "gate": self.gates.locate("pantry lifecycle", prefer_fn="note"), "roll": {}})
        return out

    def system3_rows(self, most: int) -> list[dict[str, Any]]:
        rt_fn = self.g.get("_system3")
        try:
            rt = rt_fn() if callable(rt_fn) else None
        except Exception:  # noqa: BLE001
            rt = None
        store = getattr(rt, "store", None)
        if store is None or not hasattr(store, "events_after"):
            return []
        try:
            head = int(store.events_after(0, 1).get("head") or 0)
            got = store.events_after(max(0, head - 6000), 1000)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for ev in reversed(got.get("events") or []):
            if ev.get("kind") != "observation" or str(ev.get("family") or "") not in ("WITHHELD", "ABANDONED"):
                continue
            cid = str(ev.get("conversation_id") or "")
            body = ev.get("body") if isinstance(ev.get("body"), dict) else ev
            road, roll = "", {}
            try:
                conv = store.conversation(cid, with_events=True) if cid else None
            except Exception:  # noqa: BLE001
                conv = None
            if isinstance(conv, dict):
                road = str(((conv.get("identity") or {}).get("road_kind")) or "")
                decisions = [e for e in (conv.get("events") or []) if isinstance(e, dict) and e.get("kind") == "decision"]
                last = decisions[-1] if decisions else {}
                roll = {"conversation_id": cid, "turn_id": str(last.get("turn_id") or ""),
                        "family": str(last.get("family") or ""),
                        "item": str((last.get("body") or last).get("chosen") or (last.get("body") or last).get("item") or "")[:80],
                        "d100": (last.get("body") or last).get("d100") or (last.get("body") or last).get("roll"),
                        "decisions": len(decisions)}
            out.append({
                "at": float(ev.get("at") or 0), "standing": False, "system": "system 3",
                "rule": "%s at %s" % (str(ev.get("family") or "").lower(), str(body.get("stage") or "")),
                "why": str(body.get("why") or ""), "section": road, "node": str(ev.get("turn_id") or ""),
                "ref": cid, "text": "", "gate": self.gates.locate("system 3"), "roll": roll or {"conversation_id": cid}})
            if len(out) >= most:
                break
        return out

    # ---------------------------------------------------------------- the book
    def gather(self, limit: int = 400, standing: bool = True, history: bool = True) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            memo = self.memo
            if now - float(memo.get("at") or 0) < MEMO_S and memo.get("key") == (standing, history):
                return {"at": memo["at"], "rows": memo["rows"][:limit], "counts": memo["counts"],
                        "gates": self.gates.scan(), "memo": True}
        rows: list[dict[str, Any]] = []
        per = max(50, limit // 3)
        if history:
            for fn in (self.flow_rows, self.norepeat_rows, self.withdrawn_rows, self.parked_rows,
                       self.lifecycle_rows, self.system3_rows):
                try:
                    rows.extend(fn(per))
                except Exception as exc:  # noqa: BLE001
                    rows.append({"at": now, "standing": False, "system": "blocked book", "rule": "reader tripped",
                                 "why": "%s: %s" % (type(exc).__name__, str(exc)[:160]), "section": "", "node": "",
                                 "ref": "", "text": "", "gate": {}, "roll": {}})
        if standing:
            for fn in (self.cupboard_rows, self.dynamic_rows):
                try:
                    rows.extend(fn(limit))
                except Exception as exc:  # noqa: BLE001
                    rows.append({"at": now, "standing": True, "system": "blocked book", "rule": "reader tripped",
                                 "why": "%s: %s" % (type(exc).__name__, str(exc)[:160]), "section": "", "node": "",
                                 "ref": "", "text": "", "gate": {}, "roll": {}})
        for i, r in enumerate(rows):
            r["key"] = "%s|%s|%s|%s|%d" % (r.get("system"), r.get("rule"), r.get("ref"), int(r.get("at") or 0), i)
        rows.sort(key=lambda r: -float(r.get("at") or 0))
        counts: dict[str, dict[str, int]] = {"system": {}, "rule": {}, "section": {}}
        for r in rows:
            for k in counts:
                v = str(r.get(k) or "") or "-"
                counts[k][v] = counts[k].get(v, 0) + 1
        with self._lock:
            self.memo = {"at": now, "rows": rows, "counts": counts, "key": (standing, history)}
        return {"at": now, "rows": rows[:limit], "counts": counts, "gates": self.gates.scan(), "memo": False}


def install(app: Any, g: dict[str, Any]) -> BlockedBook:
    if g.get("BLOCKED_BOOK"):
        return g["BLOCKED_BOOK"]
    book = BlockedBook(g)
    g["BLOCKED_BOOK"] = book
    if app is None or Header is None:
        return book

    @app.get("/api/blocked")
    async def api_blocked(limit: int = 400, standing: int = 1, history: int = 1,
                          authorization: str | None = Header(default=None)) -> dict[str, Any]:
        """[blocked-book] Every blocked case the ledgers hold, one shape, newest first."""
        auth = g.get("require_read_auth")
        if callable(auth):
            auth(authorization)
        got = await asyncio.to_thread(book.gather, max(1, min(2000, int(limit))), bool(int(standing)), bool(int(history)))
        got["say"] = ("%d blocked case(s): %s" % (
            len(got["rows"]), ", ".join("%s %d" % (k, v) for k, v in sorted(got["counts"]["system"].items(), key=lambda kv: -kv[1]))))
        return got

    return book
