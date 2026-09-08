"""Durable SFX-speaker takes. No model, renderer or playback dependency."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
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
            rows = copy.deepcopy(self._load())
            added = 0
            for source in sources:
                text = str(source.get("text") or "").strip()
                if not voice or not text or len(text) > 400:
                    continue  # refuse oversized input; never clip its words
                identity = hashlib.sha256((voice + "\0" + profile + "\0" + text).encode()).hexdigest()[:32]
                if identity in rows or len(rows) >= self.capacity:
                    continue
                rows[identity] = {"id": identity, "voice": voice, "profile": profile,
                    "who": "drop", "text_plain": text, "text": text,
                    "generic": bool(source.get("generic")), "at": self.clock(),
                    "state": "waiting", "attempts": 0, "retry_at": 0}
                added += 1
            if added:
                self._save(rows)
            return added

    def rows(self, voice="", profile=None):
        with self.lock:
            return copy.deepcopy([row for row in self._load().values()
                if (not voice or row.get("voice") == voice)
                and (profile is None or row.get("profile") == profile)])

    def put(self, row):
        with self.lock:
            rows = copy.deepcopy(self._load())
            current = rows.get(row.get("id"))
            if not current:
                raise ValueError("Unknown SFX source")
            if any(row.get(key) != current.get(key) for key in ("voice", "profile", "text_plain", "who")):
                raise ValueError("SFX source ownership changed")
            updated = copy.deepcopy(row)
            # An async preparation completion cannot overwrite an ACK/lease.
            for key in ("reservation", "reserved_until", "last_played", "plays"):
                if key in current:
                    updated[key] = current[key]
                else:
                    updated.pop(key, None)
            rows[row["id"]] = updated
            self._save(rows)

    def due(self, voice, profile):
        now = self.clock()
        return sorted([row for row in self.rows(voice, profile)
                       if row.get("state") != "suspended"
                       and float(row.get("retry_at") or 0) <= now],
                      key=lambda row: (bool(row.get("clip")), int(row.get("attempts") or 0),
                                       float(row.get("last_attempt") or 0), row["at"]))

    def media_ready(self, row):
        clip = row.get("clip") or {}
        name = str(clip.get("path") or "").split("?", 1)[0].rsplit("/", 1)[-1]
        try:
            seconds = float(clip.get("seconds") or 0)
            return bool(name and name not in {".", ".."} and Path(name).name == name
                        and 0 < seconds <= 12 and (self.media_dir / name).is_file()
                        and (self.media_dir / name).stat().st_size > 0)
        except (OSError, TypeError, ValueError):
            return False

    def eligible(self, context, voice, profile, validate, *, cooldown=180):
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
                        or row.get("state") != "ready" or not self.media_ready(row)
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
                pool.append(copy.deepcopy(row))
            return pool

    def pick(self, context, voice, profile, validate, *, cooldown=180, lease_seconds=900):
        """Reserve a complete take; only a later audible ACK counts as heard."""
        with self.lock:
            now, terms = self.clock(), response_terms(context)
            pool = self.eligible(context, voice, profile, validate, cooldown=cooldown)
            if not pool:
                return None
            picked = min(pool, key=lambda row: (-len(terms & response_terms(row.get("text_plain", ""))),
                                                float(row.get("last_played") or 0), row["id"]))
            rows = copy.deepcopy(self._load())
            token = uuid.uuid4().hex
            rows[picked["id"]].update(reservation=token, reserved_until=now + lease_seconds)
            self._save(rows)
            return {**copy.deepcopy(rows[picked["id"]]), "id": token, "entry_id": picked["id"]}

    def finish(self, token, *, heard):
        with self.lock:
            rows = copy.deepcopy(self._load())
            for row in rows.values():
                if row.get("reservation") != token:
                    continue
                row.pop("reservation", None)
                row.pop("reserved_until", None)
                if heard:
                    row.update(last_played=self.clock(), plays=int(row.get("plays") or 0) + 1)
                self._save(rows)
                return True
            return False

    def protected_files(self):
        return {str((row.get("clip") or {}).get("path") or "").split("?", 1)[0].rsplit("/", 1)[-1]
                for row in self.rows() if (row.get("clip") or {}).get("path")}
