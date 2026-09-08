"""Saved-audio adapters for System2. No writer, voice engine or quality waiver.

Inventory/proof calls do filesystem work and belong in the inventory worker.
Delivery revalidates there too before borrowing the existing strict player.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import math
import threading
import time
import uuid
import wave
from pathlib import Path
from urllib.parse import urlsplit


class System2Media:
    def __init__(self, host):
        self.host = host
        self._proofs = {}
        self._lock = threading.RLock()

    def _path(self, clip):
        raw = str((clip or {}).get("path") or "")
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc or "\\" in raw:
            raise ValueError("audio must use a local media route")
        raw = parsed.path
        roots = (("/media/", Path(self.host.VOICE_MEDIA_DIR)),
                 ("/ads-audio/", Path(self.host.PRODUCED_ADS_DIR)))
        for prefix, root in roots:
            if raw.startswith(prefix):
                name = raw[len(prefix):]
                if not name or Path(name).name != name or name in (".", ".."):
                    raise ValueError("invalid media filename")
                path = root / name
            else:
                path = Path(raw)
                if not path.is_absolute() or path.parent != root:
                    continue
                name = path.name
            if path.resolve().parent != root.resolve():
                raise ValueError("media escapes its owned directory")
            return path, prefix + name
        raise ValueError("unsupported media route")

    @staticmethod
    def _stamp(path):
        stat = path.stat()
        if not path.is_file() or stat.st_size <= 0:
            raise ValueError("recording is empty or missing")
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def proof(self, clip):
        """Prove actual bytes and decoded duration; metadata is never evidence."""
        path, route = self._path(clip)
        before = self._stamp(path)
        key = (str(path), before)
        with self._lock:
            saved = self._proofs.get(key)
        if saved is None:
            digest = hashlib.sha256()
            with path.open("rb") as audio:
                for chunk in iter(lambda: audio.read(1024 * 1024), b""):
                    digest.update(chunk)
            try:
                with wave.open(str(path), "rb") as audio:
                    seconds = audio.getnframes() / audio.getframerate()
            except (wave.Error, EOFError):
                import mutagen
                try:
                    audio = mutagen.File(path)
                    seconds = float(getattr(getattr(audio, "info", None), "length", 0) or 0)
                except mutagen.MutagenError as exc:
                    raise ValueError("recording cannot be decoded") from exc
            if not math.isfinite(seconds) or seconds <= 0 or seconds > 3600:
                raise ValueError("recording has no valid measured duration")
            if self._stamp(path) != before:
                raise ValueError("recording changed during verification")
            saved = {"audio_hash": digest.hexdigest(), "seconds": seconds,
                     "bytes": before[2], "name": path.name, "local_path": str(path),
                     "path": route}
            with self._lock:
                self._proofs[key] = saved
                if len(self._proofs) > 12000:
                    for old in list(self._proofs)[:2000]:
                        self._proofs.pop(old, None)
        elif self._stamp(path) != before:
            raise ValueError("recording changed during verification")
        sig = self.host.media_sign(path.name)
        return {**saved, "sig": sig, "url": route + "?t=" + sig}

    def _pantry_take(self, row, who):
        h = self.host
        text, voice, key = (str(row.get(k) or "") for k in ("text", "voice", "key"))
        saved = h._PANTRY.get(key) or {}
        if (not text.strip() or not voice or not key
                or str(saved.get("text") or "") != text[:600]
                or str(saved.get("voice") or "") != voice[:64]
                or key not in {h.pantry_key(text, voice, engine)
                               for engine in ("piper", "xtts", "f5", "voxtral")}
                or h.is_binned(text) or h.station_name_scrub(text) != text):
            raise ValueError("saved text, voice and pantry key do not match")
        recorded_who = str(row.get("who") or saved.get("who") or who)
        if recorded_who not in ("dj", "cohost", "third", "caller", "caller2", "drop"):
            raise ValueError("recording has no known speaker")
        if saved.get("who") and str(saved["who"]) != recorded_who:
            raise ValueError("recorded speaker changed")
        clip = copy.deepcopy(saved.get("clip") or {})
        measured = self.proof(clip)
        clip.update({k: measured[k] for k in ("path", "sig", "seconds", "bytes")})
        return {"i": 0, "text": text, "who": recorded_who, "voice": voice,
                "key": key, "seconds": measured["seconds"], "clip": clip, **measured}

    def inventory_track_talk(self):
        """Distinct record-bound sides; an intro and outro are not one exchange."""
        out = []
        for track_id, parent in list(self.host._TRACK_TALK.items()):
            if not isinstance(parent, dict):
                continue
            for part in ("intro", "outro"):
                side = parent.get(part)
                if isinstance(side, dict):
                    out.append((f"track-talk:{track_id}:{part}", {
                        "track_id": str(track_id), "part": part,
                        "side": side, "track": copy.deepcopy(parent.get("track") or {}),
                        "parent": parent}))
        return out

    def resolve(self, kind, row):
        """Return an immutable performance snapshot plus its original owner."""
        h = self.host
        result = {"ready": False, "why": [], "kind": str(kind), "source_row": row,
                  "entry": {}, "takes": [], "media_kind": "round"}
        try:
            if not isinstance(row, dict):
                raise ValueError("missing source row")
            track_id, part = "", ""
            if kind == "track_talk":
                track_id, part = str(row.get("track_id") or ""), str(row.get("part") or "")
                parent = h._TRACK_TALK.get(track_id) or {}
                side = row.get("side")
                if (not track_id or part not in ("intro", "outro")
                        or parent.get(part) is not side or not h.track_talk_part_ready(side)):
                    raise ValueError("record-bound side is missing or not ready")
                row = side
                result.update(track_id=track_id, part=part, source_row=side,
                              source_parent=parent, inventory_row=result["source_row"])
                if h.dialogue_tint_required() and not (row.get("brief") or {}).get("ok"):
                    raise ValueError("record-bound wording has no passing final contract")
            elif not h.dialogue_row_ready(kind, row) or not h.dialogue_row_viable(kind, row):
                raise ValueError("source row does not meet the current readiness contract")
            entry = h.dialogue_entry(row)
            if entry is not None:
                takes = h._ready_round_takes(kind, row)
                if not takes:
                    raise ValueError("complete saved turn sequence is unavailable")
                takes = copy.deepcopy(takes)
                for take in takes:
                    measured = self.proof(take.get("clip") or {})
                    take.update(measured)
                    take["clip"].update({k: measured[k] for k in ("path", "sig", "seconds", "bytes")})
                entry = copy.deepcopy(entry)
            elif row.get("produced"):
                if kind != "ad":
                    raise ValueError("produced media is not an ad")
                ad = next((a for a in h.ad_list() if str(a.get("id") or "") == str(row["produced"])), None)
                if not ad:
                    raise ValueError("produced recording has no retained ad identity")
                text, voice, name = (str(ad.get(k) or "") for k in ("text", "voice", "audio"))
                if (not text.strip() or not voice or str(row.get("text") or "") != text
                        or row.get("audio") and str(row["audio"]) != name
                        or h.is_binned(text) or h.station_name_scrub(text) != text):
                    raise ValueError("produced recording has no exact retained transcript")
                measured = self.proof({"path": "/ads-audio/" + name})
                clip = {k: measured[k] for k in ("path", "sig", "seconds", "bytes")}
                takes = [{"i": 0, "text": text, "voice": voice, "who": "dj", "key": "",
                          "clip": clip, **measured}]
                entry = copy.deepcopy(row)
                entry["produced_ad"] = copy.deepcopy(ad)
                result["media_kind"] = "produced"
            else:
                if kind not in ("ad", "manager", "station_id", "track_talk"):
                    raise ValueError("unsupported single-line shelf road")
                who = "drop" if kind == "station_id" else "cohost" if part == "outro" else "dj"
                takes = [self._pantry_take(row, who)]
                entry = copy.deepcopy(row)
            if not entry.get("script"):
                marker = {"dj": "A", "cohost": "B", "third": "D", "drop": "D",
                          "caller": "C", "caller2": "E"}[takes[0]["who"]]
                entry["script"] = marker + ": " + takes[0]["text"]
            entry.update(prep_kind=str(kind), lines=len(takes), frozen=True)
            if track_id:
                entry.update(track_id=track_id, part=part,
                             track=copy.deepcopy(result["source_parent"].get("track") or {}))
            result.update(ready=True, entry=entry, takes=takes,
                          seconds=sum(t["seconds"] for t in takes))
        except (ValueError, TypeError, KeyError, OSError, AttributeError) as exc:
            result["why"] = [str(exc)]
        return result

    @staticmethod
    def signature(resolved):
        return [(t["i"], t["text"], t["voice"], t["who"], t["key"], t["audio_hash"])
                for t in resolved.get("takes") or []]

    def _current(self, resolved):
        row = resolved.get("inventory_row", resolved["source_row"])
        return self.resolve(resolved["kind"], row)

    async def deliver(self, resolved, on_handoff, can_handoff, entry_overrides=None):
        """Accepted handoff is distinct from the host's subsequent heard ACK."""
        h = self.host
        if not resolved.get("ready"):
            return False
        fresh = await asyncio.to_thread(self._current, resolved)
        if not fresh.get("ready") or self.signature(fresh) != self.signature(resolved):
            return False
        entry = copy.deepcopy(fresh["entry"])
        entry.update(copy.deepcopy(entry_overrides or {}))

        def allowed():
            if not h._RADIO.get("on") or h.radio_paused() or not can_handoff():
                return False
            if resolved["kind"] == "track_talk":
                position = entry.get("_system2_track_position") or {}
                return (str(position.get("track_id") or "") == fresh["track_id"]
                        and str(position.get("part") or "") == fresh["part"]
                        and str((h._RADIO.get("now") or {}).get("id") or "") == fresh["track_id"])
            return True

        if not allowed():
            return False
        if fresh["media_kind"] != "produced":
            return bool(await h._banter_air(entry, h._RADIO.get("now"),
                        ready_takes=fresh["takes"], on_handoff=on_handoff, can_handoff=allowed))
        return await self._deliver_produced(fresh, entry, on_handoff, allowed)

    async def _deliver_produced(self, resolved, entry, on_handoff, allowed):
        h = self.host
        owned = await h._floor_take("a System2 produced ad")
        try:
            # The file/contract can change while the floor is occupied.
            current = await asyncio.to_thread(self._current, resolved)
            if (not current.get("ready") or self.signature(current) != self.signature(resolved)
                    or not allowed()):
                return False
            take = current["takes"][0]
            now = time.time()
            route = str(h._RADIO.get("voice_to") or "box")
            to_box = route in ("box", "both")
            box_down = now < float(h._BOX_DOWN.get("until") or 0) or len(h._BOX_HOLD) >= 6
            to_page = h.page_carries_live(route, to_box, box_down)
            start = max(now + max(0, h.VOICE_BROADCAST_LEAD_MS / 1000),
                        float(h._PAGE_AIR_UNTIL[0] or 0) if to_page else 0)
            deadline = float((entry.get("_ready_slot") or {}).get("deadline") or 0)
            if deadline and start + take["seconds"] + 1 > deadline:
                return False
            rid = "system2-" + uuid.uuid4().hex
            row = {"id": rid, "text": take["text"], "remember_text": take["text"],
                   "voice": take["voice"], "who": "dj", "kind": "ad",
                   "from": 0.0, "until": take["seconds"], "aired": "held"}
            clip = {"url": take["url"], "text": take["text"], "voice": take["voice"],
                    "speech": True, "kind": "ad", "row_id": rid,
                    "stream": {"length": take["seconds"], "rows": [row]}, "ready_round": entry}
            delivery, played = "", False
            if to_page and allowed():
                delivery = h.page_feed_append(clip)
                if delivery:
                    row["aired"] = "published"
                    on_handoff()
            if to_box and (delivery or allowed()):
                # Own the attempted device submission at its start. Some HA
                # transports return only after playback; charging the complete
                # duration again on that return would reject already heard work.
                # This is no heard receipt. A known False result is released by
                # the runtime; ambiguous cancellation keeps its reservation.
                if not delivery:
                    on_handoff()
                played = bool(await h._play_on_box(take["path"], take["sig"]))
                if played:
                    receipt = dict(h._LAST_PLAYOUT)
                    # A shared meter for a different clip is not our proof.
                    audible = (receipt.get("key") == h._played_out_key(take["path"])
                               and receipt.get("ok") is True
                               and not receipt.get("interrupted")
                               and h._box_receipt_audible(receipt))
                    row["aired"] = "box" if audible else "muted"
                    if audible:
                        if rid not in h._PAGE_ACKED_LINES:
                            h._PAGE_ACKED_LINES.add(rid)
                            h.air_remember(take["text"], "dj", "ad")
                        h._ready_round_ack(entry)
            if delivery or played:
                h._RADIO.setdefault("chat", []).append(row)
                if delivery:
                    h.page_delivery_apply(row, delivery)
                return True
            return False
        finally:
            h._floor_drop(owned)
