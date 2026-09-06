"""Persistent listener performances and their Speakerbox source catalogue."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path


PHRASES = (
    ("Mm-hmm.", "listening"), ("I hear you.", "listening"),
    ("Yeah.", "listening"), ("Go on.", "listening"),
    ("Hmm.", "listening"), ("I'm listening.", "listening"),
    ("I understand.", "listening"), ("Oh wow.", "surprise"),
)

_STOP = set("a an and are as at be been but by can could did do does for from had has have how i if in into is it its just like may me more most my no not of on one or our out say so some than that the their them then there these they this those to too us very was we were what when where which who why will with would you your about after again also being even much really something thing think know way want hear tell sounds sound".split())
# Timing, quantity and conversational scaffolding are not topics. Without
# this distinction, "people ... now" selected a question about fires, and
# "long ... take" selected an unrelated question about muffin quantities.
_STOP.update("all any anybody anyone anything around away back basis behind both come coming day days done down each else enough equal every everyone everything feel find first get getting give go going good got happen happened happening here last later let little long look looking lot make making many might need new next now okay once other others own part people person persons place point put real right same seem several short since still stuff sure take taking talk talking tell through time times today together tomorrow turn use used usual well work working yes yesterday yet amount amounts bit bits kind kinds number numbers over under during until across watch watching try trying prove perfect minute minutes hour hours second seconds week weeks month months year years fuck fucking shit damn".split())
_NUMBER_WORDS = set("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion".split())


def response_terms(text):
    terms = set()
    for raw in re.findall(r"[a-z][a-z'-]{2,}", str(text).lower()):
        word = raw.removesuffix("'s").strip("'")
        if word in _STOP or all(part in _NUMBER_WORDS for part in word.split("-")):
            continue
        word = word[:-1] if word.endswith("s") and not word.endswith("ss") else word
        if word and word not in _STOP and word not in _NUMBER_WORDS:
            terms.add(word)
    return terms


def source_response(row, source):
    """Deterministic brief/grounding checks; rejected drafts cost no recording."""
    if not isinstance(row, dict) or not isinstance(source, dict):
        return None
    text = " ".join(str(row.get("text") or "").split())
    if (not 2 <= len(text.split()) <= 14 or len(text) > 110
            or re.search(r"https?://|[\d\[\]{}]", text)
            or any(all(part in _NUMBER_WORDS for part in word.removesuffix("s").split("-"))
                   for word in re.findall(r"[a-z]+(?:-[a-z]+)*", text.lower()))
            or not re.match(r"^(?:What|How|Why|Where|When|Could|Would|Do|Does|Is|Are|Can|Tell|Say|Help|That sounds|Sounds like|I wonder|I'm curious)\b", text, re.I)
            or not text.endswith(("?", "."))
            or re.search(r"\b(?:I|we) (?:saw|met|visited|remember|was|were|did)\b|\b(?:my|our)\b", text, re.I)):
        return None
    supplied = row.get("keywords") or []
    if not isinstance(supplied, list):
        return None
    grounding = response_terms(source.get("text", ""))
    if any(match.start() > 0 and not (response_terms(match.group()) & grounding)
           for match in re.finditer(r"\b[A-Z][A-Za-z]{1,}\b", text)):
        return None                     # never introduce a new named participant
    # Both the response itself and its matching terms must connect to this
    # exact source. Invented tags cannot route an unrelated prepared remark.
    anchors = response_terms(text) & grounding
    keywords = (response_terms(" ".join(map(str, supplied))) & grounding) | anchors
    if not anchors:
        return None
    excerpt = str(source.get("text") or "")[:700]
    provenance = {key: str(source.get(key) or "")[:240]
                  for key in ("file", "mind", "id")}
    provenance.update(text=excerpt, sampled_at=time.time(),
                      hash=hashlib.sha256(excerpt.encode()).hexdigest()[:20])
    return {"text": text, "intent": "topic", "keywords": sorted(keywords)[:20],
            "anchors": sorted(anchors), "source": provenance}


def _validated_source_row(row):
    """Recheck old drafts/takes against today's routing rules without
    rewriting their source evidence or deleting the preserved recording."""
    if not isinstance(row, dict) or not isinstance(row.get("source"), dict):
        return None
    source = row["source"]
    checked = source_response(row, source)
    if checked is None:
        return None
    if source.get("hash") and source["hash"] != checked["source"]["hash"]:
        return None
    checked["source"] = dict(source)
    return {**row, **checked}


class ResponseBank:
    def __init__(self, path: Path, media_dir: Path, target=64):
        self.path, self.media_dir = Path(path), Path(media_dir)
        self.catalog_path = self.path.with_suffix(".catalog.json")
        self.retry_path = self.path.with_suffix(".retries.json")
        self.retired_path = self.path.with_suffix(".retired.json")
        self.target = max(16, min(256, int(target)))
        self.lock = threading.RLock()
        self.rows = None
        self.drafts = None
        self.retries = None
        self.retirements = None
        self.last = {}

    def _load(self):
        if self.rows is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.rows = {key: row for key, row in data.items()
                             if isinstance(row, dict) and isinstance(row.get("clip"), dict)
                             and isinstance(row.get("text"), str)
                             and isinstance(row.get("recorded_at", 0), (int, float))} \
                    if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self.rows = {}
        return self.rows

    @staticmethod
    def key(voice, engine, text, crystal=""):
        # #1064: a crystal's version of a response is its own recording.
        return hashlib.sha256(
            (f"{voice}\0{engine}\0{text}" + (f"\0{crystal}" if crystal else ""))
            .encode()).hexdigest()[:24]

    def _exists(self, row):
        name = str((row.get("clip") or {}).get("path") or "").rsplit("/", 1)[-1].split("?")[0]
        return bool(re.fullmatch(r"[\w.-]+", name) and
                    (self.media_dir / name).is_file())

    @staticmethod
    def _retirement_key(text):
        normalized = " ".join(str(text or "").split()).casefold()
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _retired_load(self):
        if self.retirements is None:
            try:
                data = json.loads(self.retired_path.read_text(encoding="utf-8"))
                self.retirements = {key: row for key, row in data.items()
                                    if isinstance(row, dict)
                                    and isinstance(row.get("text"), str)} \
                    if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self.retirements = {}
        return self.retirements

    def retired(self):
        with self.lock:
            return [dict(row) for row in self._retired_load().values()]

    def _is_retired(self, text):
        return self._retirement_key(text) in self._retired_load()

    def retire(self, text, reason):
        """Persist one review decision for every voice, preserving all takes.

        A full review ledger refuses additional entries rather than reviving
        an earlier rejected response by dropping its retirement record.
        """
        body = " ".join(str(text or "").split())
        if not body:
            return False
        with self.lock:
            key = self._retirement_key(body)
            decisions = dict(self._retired_load())
            if key not in decisions and len(decisions) >= 4096:
                raise ValueError("The retired response ledger is full")
            decisions[key] = {"text": body[:512], "reason": str(reason or "")[:512],
                              "at": time.time()}
            self.retired_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.retired_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(decisions, ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(self.retired_path)
            self.retirements = decisions
            return True

    def ready(self, voice, engine, crystal=""):
        """#1064: with a crystal named, only rows rapped through it; with
        none, only plain rows. A plain take never serves under a crystal."""
        with self.lock:
            ready = []
            for row in self._load().values():
                if (row.get("voice") != voice or row.get("engine") != engine
                        or str(row.get("crystal") or "") != str(crystal or "")
                        or self._is_retired(row.get("text"))
                        or not self._exists(row)):
                    continue
                usable = (_validated_source_row(row)
                          if row.get("source") or row.get("intent") == "topic"
                          else dict(row))
                if usable is not None:
                    ready.append(usable)
            return ready

    def missing(self, voice, engine, crystal=""):
        return [(row["text"], row["intent"])
                for row in self.missing_entries(voice, engine, crystal=crystal)]

    def catalog(self):
        with self.lock:
            if self.drafts is None:
                try:
                    data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
                    self.drafts = [row for row in data if isinstance(row, dict)
                                   and isinstance(row.get("text"), str)
                                   and isinstance(row.get("source"), dict)
                                   and isinstance(row.get("keywords"), list)] if isinstance(data, list) else []
                except (OSError, ValueError):
                    self.drafts = []
            return [checked for row in self.drafts
                    if not self._is_retired(row.get("text"))
                    and (checked := _validated_source_row(row)) is not None]

    def stage(self, entries):
        with self.lock:
            drafts = self.catalog()
            present = {r["text"].casefold() for r in drafts}
            added = 0
            for row in entries:
                row = _validated_source_row(row)
                if row is None or self._is_retired(row.get("text")):
                    continue
                # #1064: the cap is per crystal - a full plain catalogue
                # does not stop the crystal's own from being drafted.
                same = [r for r in drafts
                        if str(r.get("crystal") or "") == str(row.get("crystal") or "")]
                if len(same) >= self.target - len(PHRASES):
                    continue
                if row["text"].casefold() in present:
                    continue
                drafts.append(dict(row))
                present.add(row["text"].casefold())
                added += 1
            if added:
                self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.catalog_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(drafts, ensure_ascii=False, indent=1), encoding="utf-8")
                temporary.replace(self.catalog_path)
                self.drafts = drafts
            return added

    def _retry_load(self):
        if self.retries is None:
            try:
                data = json.loads(self.retry_path.read_text(encoding="utf-8"))
                self.retries = {key: row for key, row in data.items()
                                if isinstance(row, dict)
                                and isinstance(row.get("attempts"), int)
                                and isinstance(row.get("retry_after"), (int, float))} if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self.retries = {}
        return self.retries

    def _retry_save(self):
        retries = self._retry_load()
        for key in sorted(retries, key=lambda k: retries[k].get("at", 0))[:-4096]:
            del retries[key]
        self.retry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.retry_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(retries, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(self.retry_path)

    def retry_state(self, voice, engine, text, crystal=""):
        with self.lock:
            return dict(self._retry_load().get(self.key(voice, engine, text, crystal)) or {})

    def reject(self, voice, engine, text, clip, pantry_key=""):
        """At most three unsuitable takes, then an explicit operator reset."""
        with self.lock:
            retries = self._retry_load()
            key = self.key(voice, engine, text)
            attempts = min(3, int((retries.get(key) or {}).get("attempts") or 0) + 1)
            row = {"voice": voice, "engine": engine, "text": text,
                   "attempts": attempts, "at": time.time(),
                   "retry_after": time.time() + (30 if attempts == 1 else 120),
                   "suspended": attempts >= 3, "path": str(clip.get("path") or ""),
                   "pantry_key": str(pantry_key), "seconds": clip.get("seconds"),
                   "reason": "Take was outside the 0–6 second response brief"}
            retries[key] = row
            self._retry_save()
            return dict(row)

    def reset_retries(self, voices):
        """Give explicitly requested current casts one new bounded retry budget."""
        with self.lock:
            reset = 0
            for row in self._retry_load().values():
                if (row.get("voice"), row.get("engine")) in voices:
                    row.update(attempts=0, retry_after=0, suspended=False)
                    reset += 1
            if reset:
                self._retry_save()
            return reset

    def missing_entries(self, voice, engine, available_only=False, crystal=""):
        crystal = str(crystal or "")
        present = {row["text"] for row in self.ready(voice, engine, crystal)}
        # #1064: the fixed acknowledgments are plain by nature; under a
        # crystal only rows rapped through it are candidates.
        candidates = ([] if crystal else
                      [{"text": text, "intent": intent} for text, intent in PHRASES])
        candidates.extend([r for r in self.catalog()
                           if str(r.get("crystal") or "") == crystal
                           ][:max(0, self.target - len(PHRASES))])
        missing = [row for row in candidates if row["text"] not in present
                   and not self._is_retired(row["text"])]
        if available_only:
            missing = [row for row in missing if not (
                (retry := self.retry_state(voice, engine, row["text"], crystal)).get("suspended")
                or float(retry.get("retry_after") or 0) > time.time())]
        return missing

    def put(self, voice, engine, text, intent, clip, metadata=None):
        row = {"voice": voice, "engine": engine, "text": text, "intent": intent,
               "clip": dict(clip), "recorded_at": time.time()}
        if metadata is None:
            metadata = next((entry for entry in self.catalog()
                             if entry["text"] == text), {})
        if metadata:
            row.update({key: metadata[key]
                        for key in ("source", "keywords", "anchors", "said", "crystal")
                        if key in metadata})
        if row.get("source") or row.get("intent") == "topic":
            row = _validated_source_row(row)
            if row is None:
                return False
        if not self._exists(row):
            return False
        with self.lock:
            if self._is_retired(text):
                return False
            rows = self._load()
            rows[self.key(voice, engine, text, str(row.get("crystal") or ""))] = row
            # Multiple casts can each retain a substantial recorded repertoire.
            for key in sorted(rows, key=lambda k: rows[k].get("recorded_at", 0))[:-4096]:
                del rows[key]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(self.path)
            if self._retry_load().pop(self.key(voice, engine, text, str(row.get("crystal") or "")), None):
                self._retry_save()
        return True

    def take(self, voice, engine, context="", excluded=(), crystal=""):
        with self.lock:
            surprise = bool(re.search(r"\b(?:unbelievable|surprised|amazing|incredible)\b", context, re.I))
            terms = response_terms(context)
            available = [r for r in self.ready(voice, engine, crystal) if r["text"] not in excluded]
            topical = []
            for row in available:
                keywords = set(row.get("keywords") or [])
                overlap = terms & keywords
                # Match two concrete response anchors when it has two, so
                # mentioning a woman alone cannot select a question about her
                # toes. A question with one specific topic (muffin, fire) can
                # use that anchor; conversational filler never supplies one.
                anchors = set(row.get("anchors") or [])
                if (row.get("intent") == "topic" and overlap
                        and len(terms & anchors) >= min(2, len(anchors))
                        and anchors):
                    topical.append((len(overlap) / max(2, len(keywords)), row))
            fresh = [(score, row) for score, row in topical if time.monotonic()
                     - self.last.get(self.key(voice, engine, row["text"]), -1e12) > 180]
            rows = [row for score, row in sorted(fresh, key=lambda pair: -pair[0])]
            if not rows:
                rows = [r for r in available if r.get("intent") == "listening"
                        or (r.get("intent") == "surprise" and surprise)]
            if not rows:
                return None
            chosen = min(rows, key=lambda r: self.last.get(self.key(voice, engine, r["text"]), 0))
            self.last[self.key(voice, engine, chosen["text"])] = time.monotonic()
            return chosen

    def protected_files(self):
        with self.lock:
            return {str(row.get("clip", {}).get("path") or "").rsplit("/", 1)[-1].split("?")[0]
                    for row in self._load().values()}

    def status(self, voices):
        return {who: {"voice": voice, "engine": engine,
                      "ready": len(self.ready(voice, engine)), "target": self.target,
                      "source_ready": sum(bool(row.get("source")) for row in self.ready(voice, engine)),
                      "source_drafts": len(self.catalog()),
                      "awaiting_recording": len(self.missing_entries(voice, engine)),
                      "eligible_now": len(self.missing_entries(voice, engine, available_only=True)),
                      "rejected_takes": [dict(row) for row in self._retry_load().values()
                                         if row.get("voice") == voice and row.get("engine") == engine]}
                for who, (voice, engine) in voices.items() if voice}


def add_listening_responses(playlist, voices, choose, away="", max_responses=3):
    """Keep original turns intact; add only recorded responses at chunk seams.

    A real next-speaker turn already answers the speaker. Responses bridge a
    continuing long turn or acknowledge a lone monologue, never replace it.
    """
    result, used = [], set()
    previous, chars, inserted = "", 0, 0
    for index, item in enumerate(playlist):
        who = item["who"]
        chars = chars + len(item.get("chunk", "")) if who == previous else len(item.get("chunk", ""))
        previous = who
        result.append(item)
        following = playlist[index + 1] if index + 1 < len(playlist) else None
        continues = following is not None and following["who"] == who
        listener = "cohost" if who == "dj" else "dj"
        if (chars < 240 or inserted >= max_responses or listener == away
                or not voices.get(listener) or (following and not continues)):
            continue
        try:
            response = choose(listener, str(item.get("chunk") or ""), used)
        except Exception:
            # Optional listening texture must never cost a real spoken turn.
            response = None
        if not response:
            continue
        text = str(response.get("said") or response["text"])
        result.append({"who": listener, "chunk": text, "turn_text": text,
                       "turn_end": True, "big": False, "vec": {},
                       "response_clip": dict(response["clip"]), "listening_response": True,
                       "continuation_response": continues and not item.get("turn_end")})
        used.add(response["text"])
        chars, inserted = 0, inserted + 1
    return result
