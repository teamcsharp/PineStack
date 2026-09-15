"""Durable manifests on disk, and recovery from what survived.

The store beside `script_manifest.py`: one directory per script revision, an
atomic write for every record, an append-only event log for every state
transition and refusal, and a rebuild that reports what it could NOT recover
instead of quietly dropping it.

This module imports `script_manifest` and the standard library. Nothing else.
It never imports `app`, never touches a live runtime store, and writes only
under the root it was given. The root DEFAULTS to `data/manifests` and is a
constructor argument precisely so that tests pass a temporary directory.

--------------------------------------------------------------------------
LAYOUT
--------------------------------------------------------------------------

    <root>/events.jsonl                    every event, in order
    <root>/<revision>/script.json          the frozen script
    <root>/<revision>/events.jsonl         that revision's events
    <root>/<revision>/sessions/<session_id>.json
    <root>/<revision>/masters/<take_id>.json
    <root>/<revision>/cuts/<cut_id>.json
    <root>/<revision>/assemblies/<assembly_id>.json
    <root>/<revision>/admissions/<admission_id>.json

Every record file is written to a unique temporary name in its own directory
and then replaced into place, the way the station's existing stores do it
(`courier_write`, `ScriptReportStore._write` in app.py). An event line is
appended, flushed and fsynced; it is never rewritten.

An event is:

    {"seq": int, "at_ms": int, "kind": str, "revision": str, "subject": str,
     "state_from": str, "state_to": str, "ok": bool, "reasons": [str, ...],
     "detail": {...}}

--------------------------------------------------------------------------
PUBLIC SURFACE
--------------------------------------------------------------------------

Writes return the validator result shape of `script_manifest` - {"ok",
"refusals", "reasons", "reason", ...extras} - never a bare bool. A refused
write is itself recorded as an event.

  ManifestStore(root="data/manifests")
      .root -> Path

  put_script(script) -> result     extras {"path": str, "revision": str}
  put_session(session) -> result   extras {"path": str}
  put_master(master) -> result     extras {"path": str}
  put_cut(cut) -> result           extras {"path": str, "stored": bool}
      A cut whose state is "accepted" must validate or it is refused. A
      "pending" or "rejected" cut is stored anyway, with the reasons it is
      not acceptable recorded in the event log: that is the retake trail.
  put_assembly(assembly) -> result    extras {"path": str}
  put_admission(admission) -> result  extras {"path": str}

  load_script(revision) -> dict|None
  load(kind, revision, identifier) -> dict|None
      kind in ("session","master","cut","assembly","admission")
  records(kind, revision) -> {identifier: record}
      Unreadable files are skipped here and named by rebuild().
  list_revisions() -> [revision, ...]
  events(revision="", limit=0) -> [event, ...]
  pins(revision="") -> script_manifest.pin_index shape

  rebuild() -> result
      extras {"root", "revisions": {revision: {"script", "sessions",
      "masters", "cuts", "assemblies", "admissions"}}, "pins", "counts",
      "damaged": [{"path","code","reason"}], "events": int}
      `ok` is False when anything could not be recovered. The damage is
      reported; it is never dropped.

  resume_session(session_id, revision, *, read_audio=None, commit=True)
      -> result
      extras {"session": dict|None, "verified": [occurrence_id...],
              "dropped": [{"occurrence_id","cut_id","reason"}],
              "remaining": [occurrence_id...]}
      Rebuilds an interrupted session from the takes that still verify:
      each accepted cut must exist, validate against its master and the
      frozen script, and - when `read_audio(media_ref) -> bytes` is given -
      its master must still hash to its recorded audio. Everything else is
      returned as dropped work with a readable reason, and the resumed
      session (state "recording") is written unless commit=False.

  record_event(kind, *, revision="", subject="", state_from="", state_to="",
               ok=True, reasons=(), detail=None) -> dict
      Append one event. Returns the event written.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable, Mapping

import script_manifest as sm

DEFAULT_ROOT = "data/manifests"

SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z")

# kind -> (directory, id field, record kind)
KINDS: dict[str, tuple[str, str, str]] = {
    "session": ("sessions", "session_id", "performer_session"),
    "master": ("masters", "take_id", "master_recording"),
    "cut": ("cuts", "cut_id", "line_cut"),
    "assembly": ("assemblies", "assembly_id", "finished_conversation"),
    "admission": ("admissions", "admission_id", "broadcast_admission"),
}

EVENT_LOG = "events.jsonl"
SCRIPT_FILE = "script.json"


def _refuse(code: str, reason: str, **where: Any) -> dict:
    return {"code": str(code), "reason": str(reason),
            "where": {k: v for k, v in where.items() if v is not None}}


def _result(refusals: Iterable[dict] | None, **extra: Any) -> dict:
    rows = [r for r in (refusals or []) if r]
    out: dict[str, Any] = {"ok": not rows, "refusals": rows,
                           "reasons": [r["reason"] for r in rows],
                           "reason": rows[0]["reason"] if rows else ""}
    out.update(extra)
    return out


def _safe(name: Any, what: str) -> str:
    text = str(name or "")
    if not SAFE_NAME.fullmatch(text) or text in (".", ".."):
        raise ValueError("%s %r is not a usable file name" % (what, text))
    return text


class ManifestStore:
    """Durable manifests under one root directory. Thread-safe."""

    def __init__(self, root: str | Path = DEFAULT_ROOT):
        self.root = Path(root)
        self.lock = RLock()
        self._seq = 0
        self._seq_read = False

    # ------------------------------------------------------------------
    # paths
    # ------------------------------------------------------------------

    def revision_dir(self, revision: str) -> Path:
        return self.root / _safe(revision, "revision")

    def script_path(self, revision: str) -> Path:
        return self.revision_dir(revision) / SCRIPT_FILE

    def record_path(self, kind: str, revision: str, identifier: str) -> Path:
        if kind not in KINDS:
            raise ValueError("unknown manifest kind %r" % (kind,))
        folder, _, _ = KINDS[kind]
        return self.revision_dir(revision) / folder / (_safe(identifier, kind) + ".json")

    # ------------------------------------------------------------------
    # atomic write, append-only log
    # ------------------------------------------------------------------

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        """Temp file in the same directory, then replace. The house pattern."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False,
                                            allow_nan=False, indent=1,
                                            sort_keys=True),
                                 encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _append_line(path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                # A share that will not fsync still gets the write; the log
                # is append-only, so a torn tail is reported by rebuild().
                pass

    def _next_seq(self) -> int:
        if not self._seq_read:
            last = 0
            for row in self._read_log(self.root / EVENT_LOG)[0]:
                try:
                    last = max(last, int(row.get("seq") or 0))
                except (TypeError, ValueError):
                    continue
            self._seq = last
            self._seq_read = True
        self._seq += 1
        return self._seq

    def record_event(self, kind: str, *, revision: str = "", subject: str = "",
                     state_from: str = "", state_to: str = "", ok: bool = True,
                     reasons: Iterable[str] = (), detail: Mapping | None = None) -> dict:
        """Append one transition or refusal to the append-only log(s)."""
        with self.lock:
            event = {"seq": self._next_seq(), "at_ms": int(time.time() * 1000),
                     "kind": str(kind), "revision": str(revision or ""),
                     "subject": str(subject or ""), "state_from": str(state_from or ""),
                     "state_to": str(state_to or ""), "ok": bool(ok),
                     "reasons": [str(r) for r in (reasons or [])],
                     "detail": dict(detail or {})}
            line = json.dumps(event, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":"), sort_keys=True, default=str)
            self._append_line(self.root / EVENT_LOG, line)
            if revision:
                try:
                    self._append_line(self.revision_dir(revision) / EVENT_LOG, line)
                except ValueError:
                    pass
            return event

    @staticmethod
    def _read_log(path: Path) -> tuple[list[dict], list[dict]]:
        """(events, damage). A torn final line is damage, not a silent loss."""
        rows: list[dict] = []
        damage: list[dict] = []
        if not path.is_file():
            return rows, damage
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            return rows, [{"path": str(path), "code": "log_unreadable",
                           "reason": "the event log %s cannot be read: %s"
                                     % (path, err)}]
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as err:
                damage.append({"path": str(path), "code": "event_unreadable",
                               "reason": "line %d of %s is not valid JSON (%s); an "
                                         "interrupted write left a torn record"
                                         % (number, path.name, err)})
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                damage.append({"path": str(path), "code": "event_unreadable",
                               "reason": "line %d of %s is not an event object"
                                         % (number, path.name)})
        return rows, damage

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def list_revisions(self) -> list[str]:
        if not self.root.is_dir():
            return []
        out = []
        for child in sorted(self.root.iterdir()):
            if child.is_dir() and SAFE_NAME.fullmatch(child.name):
                out.append(child.name)
        return out

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def load_script(self, revision: str) -> dict | None:
        path = self.script_path(revision)
        if not path.is_file():
            return None
        try:
            row = self._read_json(path)
        except (OSError, ValueError):
            return None
        return row if isinstance(row, dict) else None

    def load(self, kind: str, revision: str, identifier: str) -> dict | None:
        path = self.record_path(kind, revision, identifier)
        if not path.is_file():
            return None
        try:
            row = self._read_json(path)
        except (OSError, ValueError):
            return None
        return row if isinstance(row, dict) else None

    def records(self, kind: str, revision: str) -> dict[str, dict]:
        """{identifier: record}. Unreadable files are named by rebuild()."""
        if kind not in KINDS:
            raise ValueError("unknown manifest kind %r" % (kind,))
        folder, field, _ = KINDS[kind]
        directory = self.revision_dir(revision) / folder
        out: dict[str, dict] = {}
        if not directory.is_dir():
            return out
        for path in sorted(directory.glob("*.json")):
            try:
                row = self._read_json(path)
            except (OSError, ValueError):
                continue
            if isinstance(row, dict) and row.get(field):
                out[str(row[field])] = row
        return out

    def events(self, revision: str = "", limit: int = 0) -> list[dict]:
        path = (self.revision_dir(revision) / EVENT_LOG) if revision \
            else (self.root / EVENT_LOG)
        rows, _ = self._read_log(path)
        rows.sort(key=lambda r: int(r.get("seq") or 0))
        return rows[-int(limit):] if limit else rows

    def pins(self, revision: str = "") -> dict:
        """What admitted broadcast occurrences are holding down, from disk."""
        revisions = [revision] if revision else self.list_revisions()
        admissions: list[dict] = []
        assemblies: dict[str, dict] = {}
        cuts: dict[str, dict] = {}
        for rev in revisions:
            admissions.extend(self.records("admission", rev).values())
            assemblies.update(self.records("assembly", rev))
            cuts.update(self.records("cut", rev))
        return sm.pin_index(admissions, assemblies, cuts)

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def _guard_overwrite(self, kind: str, identifier: str, revision: str,
                         replacement: Mapping) -> dict:
        existing = self.load_script(revision) if kind == "script" \
            else self.load(kind, revision, identifier)
        pins = self.pins()
        if kind == "script":
            pins = {"revisions": pins.get("revisions") or {}}
            return sm.check_overwrite("script", revision, existing, replacement, pins)
        return sm.check_overwrite(kind, identifier, existing, replacement, pins)

    def put_script(self, script: Mapping) -> dict:
        """Store a frozen script. A stored revision is immutable."""
        with self.lock:
            checked = sm.validate_frozen_script(script)
            if not checked["ok"]:
                self.record_event("script.refused", revision=str(dict(script).get("revision") or ""),
                                  subject=str(dict(script).get("revision") or ""),
                                  ok=False, reasons=checked["reasons"])
                return _result(checked["refusals"], path="")
            revision = str(dict(script)["revision"])
            guard = self._guard_overwrite("script", revision, revision, script)
            if not guard["ok"]:
                self.record_event("script.refused", revision=revision, subject=revision,
                                  ok=False, reasons=guard["reasons"])
                return _result(guard["refusals"], path="")
            if guard.get("unchanged"):
                return _result([], path=str(self.script_path(revision)),
                               revision=revision, stored=False)
            existing = self.load_script(revision)
            if existing is not None:
                reason = ("revision %s is already stored with different content; a "
                          "script change must create a new revision" % revision)
                self.record_event("script.refused", revision=revision, subject=revision,
                                  ok=False, reasons=[reason])
                return _result([_refuse("script_revision_frozen", reason)], path="")
            path = self.script_path(revision)
            self._write_json(path, dict(script))
            self.record_event("script.frozen", revision=revision, subject=revision,
                              state_to="frozen",
                              detail={"lines": len(dict(script).get("lines") or []),
                                      "conversation_id": dict(script).get("conversation_id")})
            return _result([], path=str(path), revision=revision, stored=True)

    def _known_script(self, record: Mapping, kind: str) -> tuple[dict | None, dict]:
        revision = str(dict(record).get("revision") or "")
        if not revision:
            return None, _refuse("record_no_revision",
                                 "this %s does not name a script revision" % kind)
        script = self.load_script(revision)
        if script is None:
            return None, _refuse(
                "unknown_revision",
                "no frozen script %s is stored, so this %s cannot be checked against "
                "the contract it claims" % (revision, kind))
        return script, {}

    def _put_record(self, kind: str, record: Mapping, checked: dict, *,
                    state_to: str = "", detail: Mapping | None = None,
                    store_anyway: bool = False) -> dict:
        folder, field, record_kind = KINDS[kind]
        row = dict(record)
        revision = str(row.get("revision") or "")
        identifier = str(row.get(field) or "")
        if row.get("kind") != record_kind:
            reason = "this record is a %r, not a %s" % (row.get("kind"), record_kind)
            self.record_event("%s.refused" % kind, revision=revision,
                              subject=identifier, ok=False, reasons=[reason])
            return _result([_refuse("record_wrong_kind", reason)], path="", stored=False)
        if not identifier:
            reason = "this %s has no %s" % (kind, field)
            self.record_event("%s.refused" % kind, revision=revision, ok=False,
                              reasons=[reason])
            return _result([_refuse("record_no_id", reason)], path="", stored=False)
        if not checked["ok"] and not store_anyway:
            self.record_event("%s.refused" % kind, revision=revision,
                              subject=identifier, ok=False, reasons=checked["reasons"],
                              detail=dict(detail or {}))
            return _result(checked["refusals"], path="", stored=False)
        guard = self._guard_overwrite(kind, identifier, revision, row)
        if not guard["ok"]:
            self.record_event("%s.refused" % kind, revision=revision,
                              subject=identifier, ok=False, reasons=guard["reasons"])
            return _result(guard["refusals"], path="", stored=False)
        path = self.record_path(kind, revision, identifier)
        if not guard.get("unchanged"):
            self._write_json(path, row)
        self.record_event("%s.stored" % kind, revision=revision, subject=identifier,
                          state_to=state_to or str(row.get("state") or ""),
                          ok=checked["ok"], reasons=checked["reasons"],
                          detail=dict(detail or {}))
        return _result(checked["refusals"] if not checked["ok"] else [],
                       path=str(path), stored=not guard.get("unchanged"),
                       kept=True)

    def put_session(self, session: Mapping) -> dict:
        """Store a performer session. Its contract must match the frozen cast."""
        with self.lock:
            script, missing = self._known_script(session, "session")
            if script is None:
                self.record_event("session.refused",
                                  subject=str(dict(session).get("session_id") or ""),
                                  ok=False, reasons=[missing["reason"]])
                return _result([missing], path="", stored=False)
            cuts = self.records("cut", str(dict(session).get("revision")))
            checked = sm.validate_session(session, script, cuts=cuts)
            return self._put_record("session", session, checked,
                                    detail={"accepted": checked.get("accepted"),
                                            "remaining": len(checked.get("remaining") or [])})

    def put_master(self, master: Mapping) -> dict:
        """Store a speaker master: hash, sample rate, frame count, media."""
        with self.lock:
            script, missing = self._known_script(master, "master")
            if script is None:
                self.record_event("master.refused",
                                  subject=str(dict(master).get("take_id") or ""),
                                  ok=False, reasons=[missing["reason"]])
                return _result([missing], path="", stored=False)
            session = self.load("session", str(dict(master).get("revision")),
                                str(dict(master).get("session_id") or "")) \
                if dict(master).get("session_id") else None
            checked = sm.validate_master(master, session=session, script=script)
            return self._put_record("master", master, checked,
                                    detail={"mode": dict(master).get("mode"),
                                            "seconds": checked.get("seconds")})

    def put_cut(self, cut: Mapping) -> dict:
        """Store a line cut.

        An accepted cut must validate. A pending or rejected cut is kept with
        its reasons in the log: that trail is what a retake is decided from.
        """
        with self.lock:
            script, missing = self._known_script_for_cut(cut)
            if script is None:
                self.record_event("cut.refused",
                                  subject=str(dict(cut).get("cut_id") or ""),
                                  ok=False, reasons=[missing["reason"]])
                return _result([missing], path="", stored=False)
            revision = str(script.get("revision"))
            row = dict(cut, revision=revision)
            master = self.load("master", revision, str(row.get("take_id") or ""))
            if master is None:
                reason = ("cut %s names take %s, which has no stored master"
                          % (row.get("cut_id"), row.get("take_id")))
                self.record_event("cut.refused", revision=revision,
                                  subject=str(row.get("cut_id") or ""), ok=False,
                                  reasons=[reason])
                return _result([_refuse("cut_master_missing", reason)], path="",
                               stored=False)
            checked = sm.validate_cut(row, master=master, script=script)
            accepted = row.get("state") == "accepted"
            got = self._put_record("cut", row, checked,
                                   store_anyway=not accepted,
                                   detail={"coverage": checked.get("coverage"),
                                           "state": row.get("state")})
            return got

    def _known_script_for_cut(self, cut: Mapping) -> tuple[dict | None, dict]:
        """A cut carries no revision of its own; find it by its occurrence."""
        row = dict(cut)
        revision = str(row.get("revision") or "")
        if revision:
            script = self.load_script(revision)
            if script is None:
                return None, _refuse("unknown_revision",
                                     "no frozen script %s is stored, so cut %s cannot "
                                     "be checked" % (revision, row.get("cut_id")))
            return script, {}
        occurrence = str(row.get("occurrence_id") or "")
        for candidate in self.list_revisions():
            script = self.load_script(candidate)
            if script and sm.script_line_by_occurrence(script, occurrence):
                return script, {}
        return None, _refuse(
            "unknown_revision",
            "cut %s claims occurrence %s, which belongs to no stored revision"
            % (row.get("cut_id"), occurrence))

    def put_assembly(self, assembly: Mapping) -> dict:
        """Store a finished conversation. It must be complete and in order."""
        with self.lock:
            script, missing = self._known_script(assembly, "assembly")
            if script is None:
                self.record_event("assembly.refused",
                                  subject=str(dict(assembly).get("assembly_id") or ""),
                                  ok=False, reasons=[missing["reason"]])
                return _result([missing], path="", stored=False)
            revision = str(dict(assembly).get("revision"))
            cuts = self.records("cut", revision)
            masters = self.records("master", revision)
            checked = sm.validate_assembly(assembly, script=script, cuts_by_id=cuts,
                                           masters=masters)
            return self._put_record("assembly", assembly, checked,
                                    detail={"cues": len(dict(assembly).get("cue_map") or []),
                                            "seconds": checked.get("seconds")})

    def put_admission(self, admission: Mapping) -> dict:
        """Admit a finished conversation to the reading order.

        Refused unless its assembly is a complete verified conversation whose
        audio and cue map still match what is being admitted.
        """
        with self.lock:
            script, missing = self._known_script(admission, "admission")
            if script is None:
                self.record_event("admission.refused",
                                  subject=str(dict(admission).get("admission_id") or ""),
                                  ok=False, reasons=[missing["reason"]])
                return _result([missing], path="", stored=False)
            revision = str(dict(admission).get("revision"))
            assembly = self.load("assembly", revision,
                                 str(dict(admission).get("assembly_id") or ""))
            if assembly is None:
                reason = ("admission %s commits assembly %s, which is not stored; no "
                          "incomplete conversation may be admitted"
                          % (dict(admission).get("admission_id"),
                             dict(admission).get("assembly_id")))
                self.record_event("admission.refused", revision=revision,
                                  subject=str(dict(admission).get("admission_id") or ""),
                                  ok=False, reasons=[reason])
                return _result([_refuse("admission_assembly_missing", reason)],
                               path="", stored=False)
            used = [str(r.get("playback_occurrence_id") or "")
                    for rev in self.list_revisions()
                    for r in self.records("admission", rev).values()
                    if r.get("admission_id") != dict(admission).get("admission_id")]
            checked = sm.validate_admission(
                admission, assembly=assembly, script=script,
                cuts_by_id=self.records("cut", revision),
                masters=self.records("master", revision),
                used_playback_occurrences=used)
            return self._put_record(
                "admission", admission, checked, state_to="admitted",
                detail={"playback_occurrence_id": dict(admission).get("playback_occurrence_id"),
                        "positions": checked.get("positions")})

    # ------------------------------------------------------------------
    # recovery
    # ------------------------------------------------------------------

    def rebuild(self) -> dict:
        """Rebuild the whole in-memory view from disk, and name the damage."""
        with self.lock:
            damaged: list[dict] = []
            view: dict[str, dict] = {}
            counts = {"revisions": 0, "sessions": 0, "masters": 0, "cuts": 0,
                      "assemblies": 0, "admissions": 0}
            log_rows, log_damage = self._read_log(self.root / EVENT_LOG)
            damaged.extend(log_damage)
            for revision in self.list_revisions():
                entry: dict[str, Any] = {"script": None, "sessions": {}, "masters": {},
                                         "cuts": {}, "assemblies": {}, "admissions": {}}
                script_path = self.script_path(revision)
                if not script_path.is_file():
                    damaged.append({
                        "path": str(script_path), "code": "script_missing",
                        "reason": "revision %s has a directory but no frozen script; "
                                  "its records cannot be checked against any contract"
                                  % revision})
                else:
                    try:
                        script = self._read_json(script_path)
                    except (OSError, ValueError) as err:
                        script = None
                        damaged.append({
                            "path": str(script_path), "code": "script_unreadable",
                            "reason": "the frozen script of revision %s cannot be read "
                                      "(%s)" % (revision, err)})
                    if isinstance(script, dict):
                        checked = sm.validate_frozen_script(script)
                        if not checked["ok"]:
                            damaged.append({
                                "path": str(script_path), "code": "script_invalid",
                                "reason": "the stored script of revision %s no longer "
                                          "validates: %s" % (revision, checked["reason"])})
                        entry["script"] = script
                        counts["revisions"] += 1
                    elif script is not None:
                        damaged.append({
                            "path": str(script_path), "code": "script_unreadable",
                            "reason": "the frozen script of revision %s is not an object"
                                      % revision})
                for kind, (folder, field, record_kind) in KINDS.items():
                    directory = self.revision_dir(revision) / folder
                    if not directory.is_dir():
                        continue
                    bucket = entry[folder]
                    for path in sorted(directory.glob("*.json")):
                        try:
                            row = self._read_json(path)
                        except (OSError, ValueError) as err:
                            damaged.append({
                                "path": str(path), "code": "record_unreadable",
                                "reason": "%s %s of revision %s cannot be read (%s); "
                                          "an interrupted write left it incomplete"
                                          % (kind, path.stem, revision, err)})
                            continue
                        if not isinstance(row, dict) or row.get("kind") != record_kind:
                            damaged.append({
                                "path": str(path), "code": "record_wrong_kind",
                                "reason": "%s is not a %s record" % (path.name, kind)})
                            continue
                        identifier = str(row.get(field) or "")
                        if identifier != path.stem:
                            damaged.append({
                                "path": str(path), "code": "record_id_mismatch",
                                "reason": "%s holds %s %r; the file name and the record "
                                          "disagree" % (path.name, field, identifier)})
                            continue
                        bucket[identifier] = row
                        counts[folder] += 1
                _, revision_damage = self._read_log(self.revision_dir(revision) / EVENT_LOG)
                damaged.extend(revision_damage)
                view[revision] = entry
            admissions = [r for e in view.values() for r in e["admissions"].values()]
            assemblies = {k: v for e in view.values() for k, v in e["assemblies"].items()}
            cuts = {k: v for e in view.values() for k, v in e["cuts"].items()}
            refusals = [_refuse(row["code"], row["reason"], path=row.get("path"))
                        for row in damaged]
            return _result(refusals, root=str(self.root), revisions=view,
                           pins=sm.pin_index(admissions, assemblies, cuts),
                           counts=counts, damaged=damaged, events=len(log_rows))

    def resume_session(self, session_id: str, revision: str, *,
                       read_audio: Callable[[str], bytes] | None = None,
                       commit: bool = True) -> dict:
        """Resume an interrupted session from the takes that still verify.

        `read_audio(media_ref) -> bytes` is optional; when given, every master
        behind an accepted take is re-hashed, so a changed or corrupt master
        drops its work instead of resuming on top of it.
        """
        with self.lock:
            script = self.load_script(revision)
            if script is None:
                reason = "no frozen script %s is stored" % revision
                return _result([_refuse("unknown_revision", reason)], session=None,
                               verified=[], dropped=[], remaining=[])
            session = self.load("session", revision, session_id)
            if session is None:
                reason = ("session %s of revision %s is not stored; there is nothing "
                          "to resume" % (session_id, revision))
                return _result([_refuse("unknown_session", reason)], session=None,
                               verified=[], dropped=[], remaining=[])
            if session.get("state") == "abandoned":
                reason = ("session %s was abandoned; resuming it would recover work "
                          "that was deliberately dropped" % session_id)
                return _result([_refuse("session_abandoned", reason)], session=session,
                               verified=[], dropped=[],
                               remaining=list(session.get("assignments") or []))
            cuts = self.records("cut", revision)
            masters = self.records("master", revision)
            verified: dict[str, str] = {}
            dropped: list[dict] = []
            hashed: dict[str, dict] = {}
            for occurrence, cut_id in dict(session.get("accepted") or {}).items():
                cut = cuts.get(str(cut_id))
                if cut is None:
                    dropped.append({"occurrence_id": occurrence, "cut_id": cut_id,
                                    "reason": "cut %s is not on disk; the take it "
                                              "accepted cannot be verified" % cut_id})
                    continue
                if cut.get("occurrence_id") != occurrence:
                    dropped.append({"occurrence_id": occurrence, "cut_id": cut_id,
                                    "reason": "cut %s is a cut of %s, not %s"
                                              % (cut_id, cut.get("occurrence_id"),
                                                 occurrence)})
                    continue
                if cut.get("state") != "accepted":
                    dropped.append({"occurrence_id": occurrence, "cut_id": cut_id,
                                    "reason": "cut %s is %r, not an accepted take"
                                              % (cut_id, cut.get("state"))})
                    continue
                master = masters.get(str(cut.get("take_id") or ""))
                if master is None:
                    dropped.append({"occurrence_id": occurrence, "cut_id": cut_id,
                                    "reason": "take %s has no stored master, so cut %s "
                                              "verifies against nothing"
                                              % (cut.get("take_id"), cut_id)})
                    continue
                checked = sm.validate_cut(cut, master=master, script=script)
                if not checked["ok"]:
                    dropped.append({"occurrence_id": occurrence, "cut_id": cut_id,
                                    "reason": checked["reason"]})
                    continue
                if read_audio is not None:
                    take_id = str(master.get("take_id"))
                    if take_id not in hashed:
                        try:
                            data = read_audio(str(master.get("media_ref") or ""))
                        except Exception as err:  # noqa: BLE001
                            hashed[take_id] = _result([_refuse(
                                "master_unreadable",
                                "the audio of take %s cannot be read (%s)"
                                % (take_id, err))], digest="")
                        else:
                            hashed[take_id] = sm.verify_master_bytes(master, data)
                    if not hashed[take_id]["ok"]:
                        dropped.append({"occurrence_id": occurrence, "cut_id": cut_id,
                                        "reason": hashed[take_id]["reason"]})
                        continue
                verified[occurrence] = str(cut_id)
            assignments = [str(a) for a in (session.get("assignments") or [])]
            remaining = [a for a in assignments if a not in verified]
            resumed = dict(session, accepted=verified,
                           state="complete" if not remaining else "recording",
                           updated_at=float(time.time()))
            if commit:
                stored = self._put_record(
                    "session", resumed, sm.validate_session(resumed, script, cuts=cuts),
                    state_to=str(resumed["state"]),
                    detail={"resumed_from": session.get("state"),
                            "verified": len(verified), "dropped": len(dropped)})
                if not stored["ok"]:
                    return _result(stored["refusals"], session=resumed,
                                   verified=sorted(verified), dropped=dropped,
                                   remaining=remaining)
            self.record_event("session.resumed", revision=revision, subject=session_id,
                              state_from=str(session.get("state") or ""),
                              state_to=str(resumed["state"]),
                              ok=not dropped,
                              reasons=[d["reason"] for d in dropped],
                              detail={"verified": len(verified),
                                      "remaining": len(remaining)})
            refusals = [_refuse("take_unverified", row["reason"],
                                occurrence_id=row.get("occurrence_id"),
                                cut_id=row.get("cut_id")) for row in dropped]
            return _result(refusals, session=resumed, verified=sorted(verified),
                           dropped=dropped, remaining=remaining)
