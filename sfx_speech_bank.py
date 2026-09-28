"""Durable SFX-speaker takes. No model, renderer or playback dependency."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import stat as stat_module          # #1394
import threading
import time
import uuid

from response_bank import response_terms


# Ordinary reactions are source material for the same Crystal rewrite as
# other dialogue, never a shortcut that records ungraded stock phrases.
REACTION_SOURCES = (
    "I am listening. Keep talking.",
    "I heard what you said. Go ahead.",
    "That is a fair point. I hear you.",
    "Wait a minute. Say that again.",
    "Tell me more. I am still listening.",
    "You have my attention. Finish your thought.",
    "I understand your point. Keep going.",
    "Hold that thought. I want to hear the rest.",
)


class SfxSpeechBank:
    def __init__(self, path, media_dir, *, clock=time.time, capacity=512):
        self.path, self.media_dir = Path(path), Path(media_dir)
        self.clock, self.capacity = clock, capacity
        self.lock = threading.RLock()
        self._rows = None
        # #1394: name -> (ready, when). See media_ready.
        self._media_memo = {}
        # [s3-lists] the desk's hand on the bank - see desk_rows()
        self._desk_data = None

    def _load(self):
        if self._rows is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                data = {}
            # A damaged ledger must not silently discard its recordings.
            if not isinstance(data, dict):
                raise ValueError("Invalid SFX speech ledger")
            self._rows = {key: row for key, row in data.items() if isinstance(row, dict)}
        return self._rows

    def _save(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self.path)
        self._rows = rows

    def seed(self, voice, profile, sources):
        with self.lock:
            # #1243: a shallow ledger. Every row this adds is BRAND NEW,
            # and the existing rows are only read, so there was nothing
            # for the deep copy to protect - it simply copied 2 MB to
            # append to a dict. A _save that throws still leaves
            # self._rows untouched, because this dict is a different
            # object until _save adopts it.
            rows = dict(self._load())
            added = 0
            # [s3-lists] the desk's word on the sources: a line it removed is
            # never seeded again, a line it rewrote is seeded as the rewrite,
            # a line it switched off arrives off, and a line it added is a
            # source like any other. A source already standing under this
            # voice and profile (by its words, whatever its key) is not added
            # twice - an edited row keeps the key its old words were given.
            desk = self._desk()
            sources = list(sources) + [{"text": held.get("text"), "generic": held.get("generic", True)}
                                       for held in desk["added"].values()]
            standing = {_norm(row.get("text_plain")) for row in rows.values()
                        if row.get("voice") == voice and row.get("profile") == profile}
            for source in sources:
                text = self._desk_resolve(desk, str(source.get("text") or "").strip())
                if not voice or not text or len(text) > 400:
                    continue  # refuse oversized input; never clip its words
                if _norm(text) in desk["removed"] or _norm(text) in standing:
                    continue
                identity = hashlib.sha256((voice + "\0" + profile + "\0" + text).encode()).hexdigest()[:32]
                if identity in rows or len(rows) >= self.capacity:
                    continue
                rows[identity] = {"id": identity, "voice": voice, "profile": profile,
                    "who": "drop", "text_plain": text, "text": text,
                    "generic": bool(source.get("generic")), "at": self.clock(),
                    "state": "waiting", "attempts": 0, "retry_at": 0,
                    **({"off": True} if _norm(text) in desk["off"] else {})}
                standing.add(_norm(text))
                added += 1
            if added:
                self._save(rows)
            return added

    def rows(self, voice="", profile=None, deep=True):
        """#1243: `deep` is what the caller actually needs.

        due() hands rows to a loop that mutates them with top-level
        update()/pop() and puts them back, so a shallow copy per row
        protects the stored row exactly as well as a deep one. The
        status reader only reads scalars. Deep stays the default so no
        caller silently loses a copy it was relying on."""
        with self.lock:
            got = [row for row in self._load().values()
                   if (not voice or row.get("voice") == voice)
                   and (profile is None or row.get("profile") == profile)]
            return copy.deepcopy(got) if deep else [dict(r) for r in got]

    def put(self, row):
        with self.lock:
            # #1243: as #1236 did for pick and finish - the atomicity
            # comes from REPLACING one entry in a shallow ledger, not
            # from copying every row to change one of them.
            rows = dict(self._load())
            current = rows.get(row.get("id"))
            if not current:
                raise ValueError("Unknown SFX source")
            if any(row.get(key) != current.get(key) for key in ("voice", "profile", "text_plain", "who")):
                raise ValueError("SFX source ownership changed")
            updated = copy.deepcopy(row)
            # An async preparation completion cannot overwrite an ACK/lease.
            for key in ("reservation", "reserved_until", "last_played", "plays", "off"):   # [s3-lists] off
                if key in current:
                    updated[key] = current[key]
                else:
                    updated.pop(key, None)
            rows[row["id"]] = updated
            self._save(rows)

    def due(self, voice, profile):
        now = self.clock()
        # #1243: shallow - see rows(). The preparation loop only ever
        # assigns top-level keys on what this hands back.
        return sorted([row for row in self.rows(voice, profile, deep=False)
                       if row.get("state") != "suspended" and not row.get("off")   # [s3-lists]
                       and float(row.get("retry_at") or 0) <= now],
                      key=lambda row: (bool(row.get("clip")), int(row.get("attempts") or 0),
                                       float(row.get("last_attempt") or 0), row["at"]))

    MEDIA_MEMO_S = 20.0

    def media_ready(self, row):
        clip = row.get("clip") or {}
        name = str(clip.get("path") or "").split("?", 1)[0].rsplit("/", 1)[-1]
        try:
            seconds = float(clip.get("seconds") or 0)
            if not (name and name not in {".", ".."} and Path(name).name == name
                    and 0 < seconds <= 12):
                return False
            # #1394: ONE STAT PER NAME PER TWENTY SECONDS. This did is_file()
            # and then stat() - two disk round trips - for every row of the
            # bank on every pick and every eligibility sweep, on the event
            # loop, against a disk that also carries the pantry flusher's
            # 13.5 MB dumps and the clip book's commits. 141 rows, 282
            # stats, 7.4 s measured. A render file does not come and go
            # within twenty seconds; when it does appear, twenty seconds is
            # sooner than the next cadence window anyway.
            now = self.clock()
            held = self._media_memo.get(name)
            if held is not None and now - held[1] < self.MEDIA_MEMO_S:
                return held[0]
            try:
                st = (self.media_dir / name).stat()
                ok = bool(stat_module.S_ISREG(st.st_mode) and st.st_size > 0)
            except OSError:
                ok = False
            if len(self._media_memo) > 4096:
                self._media_memo.clear()
            self._media_memo[name] = (ok, now)
            return ok
        except (OSError, TypeError, ValueError):
            return False

    def eligible(self, context, voice, profile, validate, *, cooldown=180,
                 deep=True):
        """Read eligible takes with the same ownership/cooldown proof as pick."""
        with self.lock:
            now, terms = self.clock(), response_terms(context)
            def signature(row):
                return " ".join(str(row.get("text") or "").lower().split())
            unavailable = {signature(row) for row in self._load().values()
                if row.get("voice") == voice and
                (float(row.get("reserved_until") or 0) > now
                 or (row.get("last_played") and now - row["last_played"] < cooldown))}
            pool = []
            for row in self._load().values():
                if (row.get("voice") != voice or row.get("profile") != profile
                        or row.get("state") != "ready" or row.get("off")   # [s3-lists] switched off
                        or not self.media_ready(row)
                        or signature(row) in unavailable
                        or float(row.get("reserved_until") or 0) > now
                        or (row.get("last_played") and now - row["last_played"] < cooldown)):
                    continue
                overlap = len(terms & response_terms(row.get("text_plain", "")))
                if not overlap and not row.get("generic"):
                    continue
                try:
                    if not validate(row):
                        continue
                except Exception:
                    continue
                pool.append(copy.deepcopy(row) if deep else row)
            return pool

    def pick(self, context, voice, profile, validate, *, cooldown=180, lease_seconds=900,
             chooser=None):
        """Reserve a complete take; only a later audible ACK counts as heard.

        [s3-bank] `chooser`, when given, is the roulette: it is handed each
        eligible take as {text, overlap, plays, last_played} and answers the
        index it landed on (None: the bank's own ranking decides, as before)."""
        with self.lock:
            now, terms = self.clock(), response_terms(context)
            # #1236: pick reads three fields off each row to choose a
            # winner and never hands the pool out, so it does not pay to
            # deep-copy 33 rows of tint paperwork in order to sort them.
            pool = self.eligible(context, voice, profile, validate,
                                 cooldown=cooldown, deep=False)
            if not pool:
                return None
            picked = None
            if chooser is not None:
                try:
                    k = chooser([{"text": str(row.get("text") or ""),
                                  "overlap": len(terms & response_terms(row.get("text_plain", ""))),
                                  "plays": int(row.get("plays") or 0),
                                  "last_played": float(row.get("last_played") or 0)} for row in pool])
                    if k is not None and 0 <= int(k) < len(pool):
                        picked = pool[int(k)]
                except Exception:
                    picked = None
            if picked is None:
                picked = min(pool, key=lambda row: (-len(terms & response_terms(row.get("text_plain", ""))),
                                                    float(row.get("last_played") or 0), row["id"]))
            # #1236: a shallow ledger and ONE replaced row, not a deep
            # copy of 1.45 MB to write two fields. The atomicity the
            # deep copy bought is kept exactly: the stored row is
            # replaced rather than mutated, so a _save that throws
            # leaves self._rows holding the original, untouched.
            rows = dict(self._load())
            token = uuid.uuid4().hex
            rows[picked["id"]] = {**rows[picked["id"]],
                                  "reservation": token,
                                  "reserved_until": now + lease_seconds}
            self._save(rows)
            return {**copy.deepcopy(rows[picked["id"]]), "id": token, "entry_id": picked["id"]}

    def finish(self, token, *, heard):
        with self.lock:
            # #1236: as in pick - one row replaced in a shallow ledger,
            # which keeps the save atomic without copying the rest.
            held = self._load()
            for key, row in held.items():
                if row.get("reservation") != token:
                    continue
                fresh = {k: v for k, v in row.items()
                         if k not in ("reservation", "reserved_until")}
                if heard:
                    fresh.update(last_played=self.clock(),
                                 plays=int(row.get("plays") or 0) + 1)
                rows = dict(held)
                rows[key] = fresh
                self._save(rows)
                return True
            return False

    def restate(self, pick, update):
        """[rng-topics] Change every row `pick(row)` accepts with `update(row)`
        in ONE replaced ledger and ONE save - put() saves the whole ledger per
        row, which is 1.5-2 MB of JSON each time. Reservation and play fields
        are left as they are. Returns how many rows changed."""
        with self.lock:
            rows = dict(self._load())
            changed = 0
            for key, row in rows.items():
                if not pick(row):
                    continue
                fresh = dict(row)
                update(fresh)
                for held in ("reservation", "reserved_until", "last_played", "plays",
                             "voice", "profile", "text_plain", "who", "off"):   # [s3-lists] off
                    if held in row:
                        fresh[held] = row[held]
                rows[key] = fresh
                changed += 1
            if changed:
                self._save(rows)
            return changed

    def protected_files(self):
        return {str((row.get("clip") or {}).get("path") or "").split("?", 1)[0].rsplit("/", 1)[-1]
                for row in self.rows() if (row.get("clip") or {}).get("path")}

    # --- [s3-lists] THE DESK'S HAND ON THE BANK --------------------------------
    # "I need to be able to access that list of items in that database and be
    # able to edit them and remove them / add to it" (operator, 2026-09-28).
    #
    # The desk sees the bank as LINES, not takes: one line is every row whose
    # source words are the same (a take per voice and Crystal profile - "I
    # sold the tapes to Sawyer." is two rows, one under each profile it was
    # recorded for). A line's id is a digest of its words. Editing a line
    # rewrites every take of it and throws their recordings away (they are of
    # the old words), so the preparation loop records it again; removing it
    # deletes every take and leaves a tombstone so seed() never brings the
    # words back; switching it off keeps it, never picked or recorded.
    #
    # What the desk decided lives beside the ledger (<ledger>.desk.json):
    # {"removed": {norm: {text, at}}, "replaced": {norm: new words},
    #  "off": {norm: {text, at}}, "added": {norm: {text, generic, at}}} -
    # so a Crystal or voice change, which seeds every source again under new
    # keys, still honours it.
    DESK_KEYS = ("removed", "replaced", "off", "added")
    TAKE_KEYS = ("clip", "key", "engine", "seconds", "recorded_text", "recorded_voice",
                 "tint", "tint_ok", "tint_text_hash", "tint_progress", "review_cancel_pending",
                 "off_brief", "rested_from")

    def _desk_path(self):
        return self.path.with_name(self.path.stem + ".desk.json")

    def _desk(self):
        held = getattr(self, "_desk_data", None)
        if held is None:
            try:
                held = json.loads(self._desk_path().read_text(encoding="utf-8"))
            except FileNotFoundError:
                held = {}
            if not isinstance(held, dict):
                raise ValueError("Invalid SFX speech desk file")
            held = {key: dict(held.get(key) or {}) for key in self.DESK_KEYS}
            self._desk_data = held
        return held

    def _desk_save(self, desk):
        self._desk_path().parent.mkdir(parents=True, exist_ok=True)
        temporary = self._desk_path().with_suffix(".tmp")
        temporary.write_text(json.dumps(desk, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self._desk_path())
        self._desk_data = desk

    def _desk_commit(self, desk, rows):
        """Both files or neither: the desk first (small), then the ledger; a
        ledger that fails to save puts the desk back as it was."""
        before = copy.deepcopy(self._desk())
        self._desk_save(desk)
        if rows is None:
            return
        try:
            self._save(rows)
        except Exception:
            self._desk_save(before)
            raise

    @staticmethod
    def _desk_resolve(desk, text):
        """The words a source stands for now - a rewrite, followed to its end."""
        seen = set()
        while _norm(text) in desk["replaced"] and _norm(text) not in seen:
            seen.add(_norm(text))
            text = str(desk["replaced"][_norm(text)] or "").strip()
        return text

    @staticmethod
    def _desk_group(rows, line_id):
        return [key for key, row in rows.items() if line_key(row.get("text_plain")) == line_id]

    @staticmethod
    def _desk_added(desk, line_id):
        return next((n for n, held in desk["added"].items() if line_key(held.get("text")) == line_id), None)

    def desk_rows(self, voice="", profile="", *, now=None):
        """Every line in the bank, as the desk shows it: its words, whether it
        is on, its state for the voice and profile on air now, how often it
        was heard and when last. Lines the desk added that have no take yet
        are listed too (state "queued")."""
        with self.lock:
            now = self.clock() if now is None else now
            desk = self._desk()
            groups = {}
            for row in self._load().values():
                words = str(row.get("text_plain") or "").strip()
                if words:
                    groups.setdefault(line_key(words), []).append(row)
            out = []
            for line_id, takes in groups.items():
                current = [row for row in takes if row.get("voice") == voice and row.get("profile") == profile]
                lead = max(current or takes, key=lambda row: (row.get("state") == "ready", float(row.get("at") or 0)))
                off = any(row.get("off") for row in takes)
                states = {row.get("state") for row in current}
                state = ("off" if off else "ready" if "ready" in states else "waiting" if "waiting" in states
                         else "suspended" if "suspended" in states else "dormant")
                words = str(lead.get("text_plain") or "").strip()
                airs = str(lead.get("text") or "").strip()
                why = (str(lead.get("why") or "") if state in ("waiting", "suspended") else
                       "a take under another voice or Crystal profile only - never picked while that one is not on air"
                       if state == "dormant" else "")
                before_edit = sum(int(row.get("plays_before_edit") or 0) for row in takes)
                out.append({"id": line_id, "text": words, "on": not off, "state": state,
                            "airs_as": airs if airs and airs != words else "", "why": why,
                            "note": "heard %d times in its old words" % before_edit if before_edit else "",
                            "plays": sum(int(row.get("plays") or 0) for row in takes),
                            "last_played": max(float(row.get("last_played") or 0) for row in takes),
                            "takes": len(takes), "current": len(current),
                            "reserved": any(float(row.get("reserved_until") or 0) > now for row in takes),
                            "generic": bool(lead.get("generic")),
                            "origin": ("desk" if _norm(words) in desk["added"] else
                                       "desk edit" if any(row.get("desk_edited") for row in takes) else "station")})
            for norm_words, held in desk["added"].items():
                line_id = line_key(held.get("text"))
                if line_id in groups:
                    continue
                off = norm_words in desk["off"]
                out.append({"id": line_id, "text": str(held.get("text") or ""), "on": not off,
                            "state": "off" if off else "queued", "airs_as": "",
                            "why": "added on the desk - taken into the bank the next time the SFX Guy's "
                                   "preparation runs (the bank holds %d takes at most)" % self.capacity,
                            "plays": 0, "last_played": 0.0, "takes": 0, "current": 0, "reserved": False,
                            "generic": bool(held.get("generic", True)), "origin": "desk"})
            order = {"ready": 0, "waiting": 1, "queued": 1, "suspended": 2, "off": 3, "dormant": 4}
            out.sort(key=lambda r: (order.get(r["state"], 5), -r["plays"], r["text"].lower()))
            return out

    def desk_line(self, line_id, voice="", profile=""):
        return next((row for row in self.desk_rows(voice, profile) if row["id"] == line_id), None)

    @staticmethod
    def _desk_words(text):
        text = " ".join(str(text or "").split())
        if not text:
            raise ValueError("the line has no words")
        if len(text) > 400:
            raise ValueError("a banked line is one short interjection (400 characters at most)")
        return text

    def desk_add(self, text, voice="", profile="", *, generic=True):
        """A new line: a source like the station's own. Under the voice and
        profile given it is taken in at once, waiting to be recorded."""
        text = self._desk_words(text)
        with self.lock:
            rows = self._load()
            if self._desk_group(rows, line_key(text)) or self._desk_added(self._desk(), line_key(text)):
                raise ValueError("that line is already in the bank")
            desk = copy.deepcopy(self._desk())
            desk["removed"].pop(_norm(text), None)
            desk["replaced"].pop(_norm(text), None)
            desk["added"][_norm(text)] = {"text": text, "generic": bool(generic), "at": self.clock()}
            self._desk_commit(desk, None)
            if voice and profile:
                self.seed(voice, profile, [])
            return line_key(text)

    def desk_edit(self, line_id, text):
        """New words for a line: every take of it is rewritten and its
        recording thrown away - the preparation loop records it again. An
        in-flight preparation of the old words cannot write back over it
        (put() refuses a row whose source words changed)."""
        text = self._desk_words(text)
        with self.lock:
            rows = dict(self._load())
            keys = self._desk_group(rows, line_id)
            desk = copy.deepcopy(self._desk())
            added = self._desk_added(desk, line_id)
            if not keys and added is None:
                raise KeyError(line_id)
            old = str(rows[keys[0]].get("text_plain") or "") if keys else str(desk["added"][added]["text"])
            if old == text and all(rows[key].get("text") == text for key in keys):
                return line_id                                    # nothing to change
            new_id = line_key(text)
            if new_id != line_id and (self._desk_group(rows, new_id) or self._desk_added(desk, new_id)):
                raise ValueError("that line is already in the bank")
            for key in keys:
                row = rows[key]
                fresh = {k: v for k, v in row.items() if k not in self.TAKE_KEYS}
                fresh.update(text_plain=text, text=text, state="waiting", attempts=0, errors=0,
                             retry_at=0, desk_edited=self.clock(),
                             why="Rewritten on the desk - waiting to be recorded in the new words",
                             plays_before_edit=int(row.get("plays_before_edit") or 0) + int(row.get("plays") or 0))
                fresh.pop("plays", None)
                fresh.pop("last_played", None)
                fresh.setdefault("desk_source", old)
                rows[key] = fresh
            if _norm(old) != _norm(text):
                for held, target in list(desk["replaced"].items()):
                    if _norm(target) == _norm(old):
                        desk["replaced"][held] = text
                desk["replaced"][_norm(old)] = text
                desk["replaced"].pop(_norm(text), None)
                desk["removed"].pop(_norm(text), None)
                if _norm(old) in desk["off"]:
                    desk["off"][_norm(text)] = {**desk["off"].pop(_norm(old)), "text": text}
            if added is not None:
                held = desk["added"].pop(added)
                desk["added"][_norm(text)] = {**held, "text": text}
            self._desk_commit(desk, rows if keys else None)
            return new_id

    def desk_switch(self, line_id, on):
        """Off: kept, never picked and never recorded. On: back in the draw."""
        with self.lock:
            rows = dict(self._load())
            keys = self._desk_group(rows, line_id)
            desk = copy.deepcopy(self._desk())
            added = self._desk_added(desk, line_id)
            if not keys and added is None:
                raise KeyError(line_id)
            words = str(rows[keys[0]].get("text_plain") or "") if keys else str(desk["added"][added]["text"])
            for key in keys:
                fresh = dict(rows[key])
                if on:
                    fresh.pop("off", None)
                else:
                    fresh["off"] = True
                rows[key] = fresh
            if on:
                desk["off"].pop(_norm(words), None)
            else:
                desk["off"][_norm(words)] = {"text": words, "at": self.clock()}
            self._desk_commit(desk, rows if keys else None)
            return line_id

    def desk_remove(self, line_id):
        """Gone: every take of the line is deleted (its recordings are no
        longer protected), and its words are tombstoned against seed()."""
        with self.lock:
            rows = dict(self._load())
            keys = self._desk_group(rows, line_id)
            desk = copy.deepcopy(self._desk())
            added = self._desk_added(desk, line_id)
            if not keys and added is None:
                raise KeyError(line_id)
            words = str(rows[keys[0]].get("text_plain") or "") if keys else str(desk["added"][added]["text"])
            sources = {str(rows[key].get("desk_source") or "") for key in keys} - {""}
            for key in keys:
                rows.pop(key)
            if added is not None:
                desk["added"].pop(added)
            desk["off"].pop(_norm(words), None)
            for said in {words} | sources:
                desk["removed"][_norm(said)] = {"text": said, "at": self.clock()}
            self._desk_commit(desk, rows if keys else None)
            return len(keys)


def _norm(text):
    """[s3-lists] one line's words, however they are spaced or cased."""
    return " ".join(str(text or "").lower().split())


def line_key(text):
    """[s3-lists] a line's id on the desk: a digest of its words."""
    return hashlib.sha1(_norm(text).encode("utf-8")).hexdigest()[:16]
