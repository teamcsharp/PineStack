"""Source-only sponsor supercuts, planned against the entire clip book.

No writer, speech synthesis, playback, or H3 regeneration is called here.
Every cut keeps its source ID, exact source window, role and selection evidence.
The vector keeper's existing semantic index is reused; a resumable census sync
makes every playable source available to that keeper, without claiming clips
with only filenames have been listened to. Plans enumerate the authoritative
book, including rows not yet represented in the semantic section.
"""
from __future__ import annotations

import asyncio
import copy
from contextlib import contextmanager
import hashlib
import heapq
import hmac
import itertools
import json
import math
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

class SourceAnalysisPending(RuntimeError):
    """Retained source evidence will resume on the next production visit."""


SCHEMA = "sfx.supercut/1"
RATE = 24000
ROLES = ("opening", "sell", "timely", "flair", "closing")
POOL = 180                       # retained AFTER every catalog row is scored
SYNC_BATCH = 4000
MAX_CUTS = 64
_WORD = re.compile(r"[a-z0-9']+")
_STOP = {"the", "a", "an", "and", "or", "for", "of", "to", "it", "is", "in", "on", "that", "this", "with", "from", "by", "be", "as", "we", "you", "your", "our"}
ROLE_WORDS = {
    "opening": "welcome hello hey listen attention everybody tonight presents ready introduce",
    "sell": "radio station music listen tune show broadcast fm song sounds amazing best love enjoy come listen",
    "timely": "tonight today now latest news happening right here time",
    "flair": "laugh cheer wow boom sound drum beat excited yes fantastic incredible applause party",
    "closing": "goodbye bye thanks thank listen tune radio station again see next goodbye goodnight",
}


def _text(value: Any, most: int = 4000) -> str:
    return " ".join(str(value or "").split())[:most]


def _number(value: Any, fallback: float = 0) -> float:
    try:
        got = float(value)
        return got if math.isfinite(got) else fallback
    except (TypeError, ValueError):
        return fallback


def _words(text: Any) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").lower()) if w not in _STOP}


def _identity(text: str, station: str) -> bool:
    wanted = re.sub(r"[^a-z0-9]", "", station.lower())
    heard = re.sub(r"[^a-z0-9]", "", str(text).lower())
    # ASR often omits 'FM'; the actual distinctive station name must be heard.
    short = wanted[:-2] if wanted.endswith("fm") else wanted
    if "pinebox" in wanted:
        return "pinebox" in heard
    return bool(len(short) >= 5 and short in heard)


def product_terms(cfg):
    """Meaningful product words; a station tag cannot sell an unrelated item."""
    item = _words(cfg.get('item'))
    station = _words(cfg.get('station'))
    if re.sub(r'[^a-z0-9]', '', str(cfg.get('item') or '').lower()) == re.sub(r'[^a-z0-9]', '', str(cfg.get('station') or '').lower()):
        return set()
    generic = {'radio','station','music','listen','tune','broadcast','fm','song','sounds',
        'pinebox','pine','box','best','great','amazing','premium','deluxe','limited','edition',
        'exclusive','new','special','super','ultimate','brand','product','sponsor'}
    return item - station - generic


def product_evidence(cfg, clips):
    wanted = product_terms(cfg)
    selected = [p for p in clips if p.get('role') == 'sell' and _words(p.get('said')) & wanted]
    normalized = lambda text: ' '.join(_WORD.findall(str(text or '').lower()))
    name = normalized(cfg.get('item'))
    return {'item':str(cfg.get('item') or ''), 'required_terms':sorted(wanted),
        'source_sids':[str(p.get('sid') or '') for p in selected],
        'spoken_matches':sorted(set().union(*(_words(p.get('said')) & wanted for p in selected))) if selected else [],
        'exact_product_named':bool(name and any(name in normalized(p.get('said')) for p in clips)),
        'verified':not wanted or bool(selected), 'basis':'station_pitch' if not wanted else 'recorded_product_words'}


def finite_weight(value):
    try:
        number=float(value)
        return number if math.isfinite(number) else 0.0
    except (TypeError,ValueError):
        return 0.0


def config(raw: Any = None) -> dict[str, Any]:
    got = raw if isinstance(raw, Mapping) else {}
    target = max(30.0, min(60.0, _number(got.get("target_seconds"), 45)))
    minimum = max(30.0, min(target, _number(got.get("min_seconds"), 30)))
    maximum = max(target, min(60.0, _number(got.get("max_seconds"), 60)))
    cleaned = {"station": _text(got.get("station") or got.get("stationname") or "Pine Box FM", 100),
            "sponsor": _text(got.get("sponsor") or "Pine Box FM", 140),
            "item": _text(got.get("item") or "Pine Box FM", 200),
            "target_seconds": target, "min_seconds": minimum, "max_seconds": maximum,
            "max_clip_seconds": max(0.8, min(6.0, _number(got.get("max_clip_seconds"), 3.6))),
            "context": _text(got.get("context"), 1200)}
    custom = got.get('custom')
    if isinstance(custom, Mapping) and re.fullmatch(r'scc-[a-f0-9]{24}', str(custom.get('id') or '')):
        cleaned['custom'] = {'id': str(custom['id']), 'words': str(custom.get('words') or '')[:12000],
            'max_seconds': max(.06, min(120., _number(custom.get('max_seconds'), 60.))),
            'accuracy': max(0., min(100., _number(custom.get('accuracy'), 100.)))}   # [cut-anyway] the dial rides the plan
    campaign = got.get('campaign')
    if isinstance(campaign, Mapping):
        cleaned['campaign'] = {key: str(campaign.get(key) or '')[:12000 if key in
            ('script','system_prompt','generation_prompt') else 500] for key in
            ('id','product','sponsor','script','system_prompt','generation_prompt',
             'hour','template_id','template_name','status','product_origin','product_source','creative_seed','occurrence')}
        cleaned['campaign']['generated_at'] = _number(campaign.get('generated_at'))
    return cleaned


def role_queries(cfg: Mapping[str, Any], prompt: str = "") -> dict[str, str]:
    item = str(cfg.get("item") or "")
    station = str(cfg.get("station") or "")
    context = str(cfg.get("context") or "")
    return {role: _text(" ".join((ROLE_WORDS[role], item if role == "sell" else "",
                                  station if role in ("sell", "closing") else "",
                                  context if role == "timely" else "",
                                  prompt if role == "sell" else "")), 2500)
            for role in ROLES}


@contextmanager
def _book_connection(path: Any):
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        yield con
    finally:
        con.close()


def _columns(con: sqlite3.Connection) -> set[str]:
    return {str(r[1]) for r in con.execute("pragma table_info(clips)")}


def census(book_path: Any, store: Any = None) -> dict[str, Any]:
    """Accurate coverage; metadata vectors and audio transcripts are separate."""
    with _book_connection(book_path) as con:
        columns = _columns(con)
        said = "coalesce(said,'')<>''" if "said" in columns else "0"
        listened = "said_at is not null" if "said_at" in columns else "0"
        seen = "coalesce(seen_desc,'')<>''" if "seen_desc" in columns else "0"
        counts = con.execute("select count(*),sum(playable=1),sum(playable=1 and " + said +
                             "),sum(playable=1 and " + listened + "),sum(playable=1 and " + seen + ") from clips").fetchone()
    vector = store.counts() if store is not None else {}
    total, playable, words, studied, vision = [int(v or 0) for v in counts]
    indexed = int(vector.get("clips") or 0)
    embedded = int(vector.get("clips_embedded") or 0)
    return {"catalog_total": total, "playable": playable, "transcripts": words,
            "audio_analyzed": studied, "audio_pending": max(0, playable - studied),
            "vision_described": vision, "metadata_indexed": indexed, "semantic_vectors": embedded,
            "metadata_pending": max(0, playable - indexed),
            "semantic_pending": max(0, playable - embedded),
            "scope": "all playable source rows; transcripts, filenames and existing semantic vectors",
            "analysis_complete": studied >= playable and embedded >= playable}


class _Scores:
    """Bounded numeric matrix plus source index; no per-source role dictionaries."""
    def __init__(self, keys, indexes, values):
        self.keys, self.indexes, self.values = keys, indexes, values
    def __len__(self):
        return len(self.indexes)
    def get(self, sid, default=None):
        ix = self.indexes.get(sid)
        if ix is None:
            return default
        return {k: float(self.values[ix][j]) for j, k in enumerate(self.keys)}


def _semantic(store: Any, vectors: Mapping[str, list[float]]) -> Any:
    """Cosine for EVERY embedded row, rather than a top-20 suggestion query."""
    if store is None or not vectors:
        return {}
    import sfx_vectors
    if callable(getattr(store, 'score_all', None)):
        return store.score_all(vectors)
    sids, matrix = store._load_matrix()
    if sfx_vectors._np is not None and sids:
        np = sfx_vectors._np
        keys = list(vectors)
        q = np.asarray([sfx_vectors.unit(vectors[k]) for k in keys], dtype=np.float32).T
        if q.shape[0] != matrix.shape[1]:
            return {}
        values = np.empty((len(sids), len(keys)), dtype=np.float32)
        # Chunk conversion avoids another full float32 copy of a large catalog.
        for start in range(0, len(sids), 4096):
            values[start:start+4096] = matrix[start:start + 4096].astype(np.float32) @ q
        return _Scores(keys, {sid: i for i, sid in enumerate(sids)}, values)
    if sids:
        return {sid: {k: sfx_vectors.dot(vec, sfx_vectors.unit(v)) for k, v in vectors.items()}
                for sid, vec in zip(sids, matrix)}
    return {}


COOLDOWN_HOURS = float(os.getenv("PINE_SUPERCUT_COOLDOWN_HOURS", "48"))   # [supercut-fresh] footage rests after a cut
FRESH_DAYS = float(os.getenv("PINE_SUPERCUT_FRESH_DAYS", "7"))            # [supercut-fresh] "actively explored" = studied this week
PLAYED_GAIN = 0.6                                                          # [supercut-fresh] a clip that has had play scores at this
FRESH_GAIN = 1.3                                                           # [supercut-fresh] a freshly studied clip scores at this


def scan_catalog(book_path: Any, store: Any, cfg: Mapping[str, Any], *, prompt: str = "",
                 vectors: Mapping[str, list[float]] | None = None, banned: set[str] | None = None,
                 weights: Mapping[str, float] | None = None, mp4_only: bool = False,
                 exclude: set[str] | None = None, extra_sources: list[dict[str, Any]] | None = None,
                 played: set[str] | None = None, fresh_days: float | None = None) -> dict[str, Any]:
    """Score each source, keeping only the best bounded set per dramatic role.

    The bounded result is NOT the scan boundary. Even a matching clip in the
    final row can win. Long clips without timed transcript evidence are not
    cut at guessed word offsets: this first template uses entire short clips.
    """
    started = time.time()
    blocked, excluded = set(banned or ()), set(exclude or ())
    controls = weights or {}
    queries = role_queries(cfg, prompt)
    terms = {k: _words(v) for k, v in queries.items()}
    context = _words(cfg.get("context"))
    semantic = _semantic(store, vectors or {})
    heaps: dict[str, list[Any]] = {k: [] for k in ROLES}
    identity: list[Any] = []
    need_identity: list[Any] = []
    scanned = eligible = 0
    rested = explored = 0                                                  # [supercut-fresh]
    played_set = set(played or ())
    fresh_since = time.time() - (FRESH_DAYS if fresh_days is None else float(fresh_days)) * 86400.0
    digest = hashlib.sha256()
    with _book_connection(book_path) as con:
        columns = _columns(con)
        wanted = [c for c in ("sid", "path", "name", "folder", "video", "seconds", "mtime", "said", "said_at", "seen_desc", "seen_desc_at") if c in columns]
        cursor = con.execute("select " + ",".join(wanted) + " from clips where playable=1 order by rowid")
        for row in itertools.chain(cursor, extra_sources or ()):
            scanned += 1
            d = dict(row)
            sid = str(d.get("sid") or hashlib.sha1(str(d.get("path")).encode()).hexdigest()[:16])
            digest.update((sid + ":" + str(d.get("mtime") or "") + "\n").encode())
            source_path = Path(str(d.get('path') or ''))
            # Finished station ads belong to review/reuse; never build recursive
            # montages from a prior Super Cut even if its future duration changes.
            if source_path.name.startswith('supercut-') or 'supercuts' in source_path.parts:
                continue
            length = _number(d.get("seconds"))
            weight = max(0, min(9, _number(controls.get(sid, 1), 1)))
            if sid in blocked or weight <= 0.05 or length < 0.45 or length > 6.0:
                continue
            # [supercut-fresh] footage a supercut used inside the cooldown rests - except a verified station
            # identity, which every cut needs for its tag. A resting row is counted, not scored.
            if sid in excluded and not _identity(_text(d.get("said"), 2000), str(cfg["station"])) \
                    and not _identity(str(d.get("name") or ""), str(cfg["station"])):
                rested += 1
                continue
            if mp4_only and (source_path.suffix.lower() != ".mp4" or not bool(d.get("video"))):
                continue
            said = _text(d.get("said"), 2000)
            is_identity = _identity(said, str(cfg["station"]))
            # A verified station tag may take up to six seconds; every other
            # cut obeys the operator's rapid-cut maximum.
            name_identity = _identity(str(d.get("name") or ""), str(cfg["station"]))
            if length > float(cfg["max_clip_seconds"]) and not (is_identity or name_identity):
                continue
            eligible += 1
            spoken, named = _words(said), _words(str(d.get("name")) + " " + str(d.get("seen_desc") or ""))
            candidate = {"sid": sid, "path": str(d.get("path") or ""), "name": _text(d.get("name"), 180),
                         "seconds": round(length, 6), "mtime": _number(d.get("mtime")),
                         "video": bool(d.get("video")), "said": said,
                         "transcript_scope": "entire_source" if said else "untranscribed",
                         "from_s": _number(d.get('source_from_s')), "until_s": _number(d.get('source_until_s'),round(length,6)),
                         "source_seconds": _number(d.get('source_seconds'),length),
                         "identity_verified": is_identity,
                         "weight": weight}
            if d.get('word_cut_verified'):
                candidate.update(word_cut_verified=True,source_audio_verified=True,
                    timing_basis=d.get('timing_basis'))
            if d.get("provenance"):
                candidate["provenance"] = d["provenance"]
                candidate["transcript_scope"] = d.get("transcript_scope") or "recorded_source_asr"
            if is_identity:
                _keep(identity, 4 + weight, candidate, 32)
            elif name_identity and not said and not re.search(r"(?:parity|verify|test|splice)", str(d.get("name") or ""), re.I):
                _keep(need_identity, weight - abs(length - 5.0) / 12.0, candidate, 20)
            if length > float(cfg["max_clip_seconds"]):
                if is_identity and "welcome" in spoken:
                    choice = dict(candidate, role="opening", score=8.0,
                                  why={"spoken_matches": ["welcome"], "verified_station_identity": cfg["station"]})
                    _keep(heaps["opening"], 8.0, choice, POOL)
                continue  # longer verified station tags only open or close
            similarities = semantic.get(sid) or {}
            # [supercut-fresh] never-played footage first, and what the SFX Guy studied this week before the rest
            fresh_gain = PLAYED_GAIN if sid in played_set else 1.0
            if max(_number(d.get("said_at")), _number(d.get("seen_desc_at"))) > fresh_since:
                fresh_gain *= FRESH_GAIN
                explored += 1
            for role in ROLES:
                word_hits = spoken & terms[role]
                name_hits = named & terms[role]
                lexical = min(3.0, len(word_hits) * 0.7 + len(name_hits) * 0.12)
                cosine = max(0.0, _number(similarities.get(role)))
                timely = len(spoken & context) * 2.0 if role == "timely" and context else 0.0
                if role == "sell":
                    direct = spoken & {"radio", "station", "music", "listen", "tune", "broadcast", "fm", "song", "sounds"}
                    lexical += len(direct) * 1.2 + (1.5 if direct else 0)
                    product_hits = spoken & product_terms(cfg)
                    lexical += len(product_hits) * 5.0
                # Semantic matches with no words remain visible, but cannot
                # pretend a filename or visual tag is something the audio says.
                score = (lexical + cosine * (0.7 if said else 0.25) + timely +
                         (0.15 if said else 0) + (0.1 if 0.8 <= length <= 2.8 else 0)) * math.sqrt(weight) * fresh_gain
                if score <= 0:
                    continue
                choice = dict(candidate, role=role, score=round(score, 6),
                              why={"spoken_matches": sorted(word_hits), "metadata_matches": sorted(name_hits),
                                   "semantic": round(cosine, 6), "timely_matches": sorted(spoken & context),
                                   "operator_weight": weight, "fresh_gain": round(fresh_gain, 3)})
                _keep(heaps[role], score, choice, POOL)
    return {"coverage": dict(census(book_path, store), catalog_scanned=scanned, rested_sources=rested, explored_recently=explored, played_known=len(played_set), recorded_station_sources=len(extra_sources or ()), catalog_digest=digest.hexdigest(), eligible_short_sources=eligible,
                             semantic_scored=len(semantic), scan_seconds=round(time.time() - started, 3)),
            "roles": {k: _rank(v) for k, v in heaps.items()}, "identities": _rank(identity),
            "identity_to_analyze": _rank(need_identity), "queries": queries, "prompt": _text(prompt, 4000)}


def _keep(heap: list[Any], score: float, row: dict[str, Any], most: int) -> None:
    item = (score, str(row["sid"]), row)
    if len(heap) < most:
        heapq.heappush(heap, item)
    elif item[:2] > heap[0][:2]:
        heapq.heapreplace(heap, item)


def _rank(heap: list[Any]) -> list[dict[str, Any]]:
    return [r for _score, _sid, r in sorted(heap, key=lambda h: h[:2], reverse=True)]


def compose(scan: Mapping[str, Any], cfg: Mapping[str, Any], occurrence: str = "", *, roulette: Any = None) -> dict[str, Any]:
    """Opening, sales beats, current-context reactions, stinger flair, closing."""
    import random
    rng = random.Random(hashlib.sha256(str(occurrence).encode()).hexdigest())
    used: set[str] = set()
    paths: set[str] = set()
    phrases: set[str] = set()
    picks: list[dict[str, Any]] = []
    roles = scan.get("roles") or {}
    warnings: list[str] = []
    identities = list(scan.get("identities") or [])
    if not identities:
        return {"ok": False, "why": "No source clip has a verified spoken station identifier yet.",
                "coverage": scan.get("coverage"), "needs": ["station_identity"],
                "identity_candidates": list(scan.get("identity_to_analyze") or [])[:8]}
    # Rotate near-equivalent source tags and hooks while keeping the occurrence
    # stable when a panel poll or the recording room asks for the same segment.
    tag_pool = identities[:min(8, len(identities))]
    tag_pick = roulette("closing", tag_pool) if callable(roulette) else rng.randrange(len(tag_pool))
    tag = dict(tag_pool[max(0, min(len(tag_pool)-1, int(tag_pick)))], role="closing", score=4.0,
               why={"verified_station_identity": str(cfg["station"])})
    used.add(tag["sid"])
    paths.add(tag["path"])
    phrases.add(" ".join(sorted(_words(tag.get("said")))))
    budget = float(cfg["target_seconds"]) - float(tag["seconds"])

    def choose(role: str, remain: float, final: bool = False) -> dict[str, Any] | None:
        available = [r for r in roles.get(role, ()) if r["sid"] not in used and r["path"] not in paths
                     and float(r["seconds"]) <= remain + (0.45 if final else 0)
                     and (not r.get("said") or " ".join(sorted(_words(r["said"]))) not in phrases)]
        if not available:
            return None
        # Source-text evidence is required for selling or introducing; a mood
        # score alone must not be offered as a spoken sales claim.
        if role in ("opening", "sell", "timely"):
            wordy = [r for r in available if r.get("said") and (r.get("why") or {}).get("spoken_matches")]
            if wordy:
                available = wordy
            elif role != "timely":
                return None
            if role == 'sell' and product_terms(cfg):
                available = [r for r in available if _words(r.get('said')) & product_terms(cfg)]
                if not available:
                    return None
        if final:
            row = min(available, key=lambda r: (abs(float(r["seconds"]) - remain), -float(r["score"])))
        else:
            top = available[:min(6, len(available))]
            if callable(roulette):
                selected = int(roulette(role, top))
                row = top[max(0, min(len(top)-1, selected))]
            else:
                row = rng.choices(top, weights=[max(0.01, float(r["score"])) for r in top], k=1)[0]
        used.add(row["sid"])
        paths.add(row["path"])
        if row.get("said"):
            phrases.add(" ".join(sorted(_words(row["said"]))))
        return dict(row, role=role)

    opening = choose("opening", budget)
    if opening is None:
        return {"ok": False, "why": "No verified spoken opening hook is available.",
                "coverage": scan.get("coverage"), "needs": ["opening"]}
    picks.append(opening)
    budget -= float(opening["seconds"])
    sequence = ["sell", "sell", "timely", "sell", "flair", "sell", "timely", "sell", "flair"]
    ix = 0
    while budget > 0.45 and len(picks) < MAX_CUTS - 1:
        role = sequence[ix % len(sequence)]
        ix += 1
        got = choose(role, budget, final=budget < 3.8)
        if got is None:
            got = choose("sell", budget, final=budget < 3.8) or choose("flair", budget, final=budget < 3.8)
        if got is None:
            break
        picks.append(got)
        budget -= float(got["seconds"])
    picks.append(tag)
    total = sum(float(r["seconds"]) for r in picks)
    if not any(r["role"] == "sell" for r in picks):
        return {"ok": False, "why": "The catalog has no verified spoken selling beats for this item.",
                "coverage": scan.get("coverage"), "needs": ["sell"]}
    product_proof = product_evidence(cfg, picks)
    if not product_proof['verified']:
        return {'ok':False,'why':'The catalog has no recorded product-selling evidence for this item.',
            'coverage':scan.get('coverage'),'needs':['product_source'],'product_evidence':product_proof}
    if cfg.get("context") and not any((r.get("why") or {}).get("timely_matches") for r in picks):
        warnings.append("No transcript matches the current topic; timely flair is generic.")
    if not (float(cfg["min_seconds"]) <= total <= float(cfg["max_seconds"])) or abs(total - float(cfg["target_seconds"])) > 1.0:
        return {"ok": False, "why": "The source cuts do not cover the requested duration without padding or repetition.",
                "seconds": round(total, 6), "coverage": scan.get("coverage"), "needs": ["duration"]}
    cursor = 0.0
    for p in picks:
        p["at"] = round(cursor, 6)
        cursor += float(p["seconds"])
    digest = hashlib.sha256(json.dumps([occurrence, cfg, [(p["sid"], p["from_s"], p["until_s"]) for p in picks]], sort_keys=True).encode()).hexdigest()[:24]
    return {"ok": True, "id": "sc-" + digest, "schema": SCHEMA, "occurrence": occurrence,
            "source_only": True, "complete": True, "config": dict(cfg), "clips": picks,
            "source_count": len(picks), "seconds": round(total, 6), "created_at": time.time(),
            "coverage": scan.get("coverage"), "queries": scan.get("queries"), "warnings": warnings,
            "product_evidence": product_proof,
            "prompt": _text(scan.get("prompt"), 4000),
            "structure": {"opening": True, "sell": True, "timely": any(p["role"] == "timely" for p in picks),
                          "flair": any(p["role"] == "flair" for p in picks), "closing": True,
                          "station_identity_verified": True}}


def render_source_plan(plan: Mapping[str, Any], output: Any, executable: str, *,
                       banned: set[str] | None = None, weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    """All source cuts must decode; never publish an incomplete advertising cut."""
    if not plan.get("ok") or not plan.get("source_only") or not plan.get("complete"):
        raise ValueError("Only a complete source-only plan can be rendered")
    cfg = config(plan.get("config"))
    clips = list(plan.get("clips") or [])
    custom = cfg.get('custom') or {}
    if custom:
        from sfx_supercut_custom import tokens
        exact = _number(custom.get('accuracy'), 100.) >= 100.     # [cut-anyway] the request's own dial; 100 is word for word
        if exact and not all(p.get('word_cut_verified') and p.get('source_audio_verified') for p in clips):
            raise ValueError('Every custom word cut needs verified trimmed source audio')
        if exact and tokens(' '.join(p.get('said') or '' for p in clips)) != tokens(custom.get('words')):
            raise ValueError('The custom audio differs from the exact requested words')
    proof = product_evidence(cfg, clips)
    if not custom and not proof['verified']:
        raise ValueError('The source-only montage has no recorded selling evidence for this product')
    if not (1 if custom else 3) <= len(clips) <= MAX_CUTS:
        raise ValueError("The supercut needs a bounded opening, sales beats and closing")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pcm = bytearray()
    cues: list[dict[str, Any]] = []
    held = set(banned or ())
    controls = weights or {}
    with tempfile.TemporaryDirectory(prefix="pine-supercut-") as tmp:
        for ix, p in enumerate(clips):
            sid, source = str(p.get("sid") or ""), Path(str(p.get("path") or ""))
            if sid in held or _number(controls.get(sid, 1), 1) <= 0.05:
                raise ValueError("A planned source is disabled: " + sid)
            start, end = _number(p.get("from_s")), _number(p.get("until_s"))
            if start < 0 or not (.06 if custom else .45) <= end - start <= 6.0 or end > _number(p.get("source_seconds"),_number(p.get("seconds"))) + 0.02:
                raise ValueError("Invalid exact source window: " + sid)
            stat = source.stat()
            if p.get("mtime") and abs(stat.st_mtime - _number(p["mtime"])) > 0.01:
                raise ValueError("A source changed after the plan was composed: " + sid)
            cut = Path(tmp) / (str(ix) + ".wav")
            subprocess.run([str(executable), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", f"{start:.6f}", "-t", f"{end-start:.6f}", "-i", str(source), "-vn",
                            "-af", "loudnorm=I=-18:TP=-1.5:LRA=7", "-ac", "1", "-ar", str(RATE),
                            "-sample_fmt", "s16", "-f", "wav", str(cut)],
                           capture_output=True, timeout=30, check=True)
            with wave.open(str(cut), "rb") as handle:
                raw = handle.readframes(handle.getnframes())
            if not any(raw):
                raise ValueError("A source window is digital silence: " + sid)
            actual = len(raw) / 2 / RATE
            if actual < (.05 if custom else .4) or abs(actual - (end - start)) > 0.12:
                raise ValueError("A source did not decode to its planned window: " + sid)
            at = len(pcm) / 2 / RATE
            pcm.extend(raw)
            cues.append({**dict(p), "at": round(at, 6), "until": round(at + actual, 6),
                         "body_seconds": round(actual, 6), "source_from": start, "source_until": end})
        duration = len(pcm) / 2 / RATE
        if (custom and not .06 <= duration <= custom["max_seconds"]) or (not custom and (not cfg["min_seconds"] <= duration <= cfg["max_seconds"] or abs(duration - cfg["target_seconds"]) > 1.0)):
            raise ValueError("The measured supercut does not cover the requested duration")
        if not custom and not _identity(str(clips[-1].get("said") or ""), cfg["station"]):
            raise ValueError("The closing source no longer supplies a verified station identifier")
        temporary = output.with_name(output.name + ".tmp.wav")
        with wave.open(str(temporary), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(RATE)
            handle.writeframes(bytes(pcm))
        temporary.replace(output)
    result = {"ok": True, "clip": output.name, "key": output.name, "path": str(output),
              "seconds": round(duration, 6), "body_seconds": round(duration, 6), "body_frames": len(pcm) // 2,
              "engine": "sfx_supercut", "sample_rate": RATE, "source_plan": dict(plan), "cues": cues,
              "source_only": True, "complete": True,
              "recorded_text": " / ".join(p.get("said") or ("[source audio: " + p.get("name", "") + "]") for p in clips)}
    result["source_plan"].update(seconds=result["seconds"], cues=cues, rendered_at=time.time(), clip=output.name)
    return result


class _CatalogIndex:
    """Worker-owned read snapshot; never shares the vector keeper's connection."""
    def __init__(self, store):
        self.con = sqlite3.connect(Path(store.db_path).resolve().as_uri()+"?mode=ro", uri=True)
        self.manifest = copy.deepcopy(store.manifest)
        self._matrix = None
        self._matrix_n = -1

    def counts(self):
        # The census needs source/vector coverage, not full facet/dialogue tallies.
        return {'clips':int(self.con.execute('select count(*) from clips').fetchone()[0]),
                'clips_embedded':int(self.con.execute('select count(*) from clip_vec').fetchone()[0])}

    def score_all(self, vectors):
        """Score every indexed vector with bounded batches, without a second matrix."""
        import sfx_vectors
        keys = list(vectors)
        dims = int(self.manifest.get('dims') or sfx_vectors.DIMS)
        if any(len(vectors[key])!=dims for key in keys):
            return {}
        query = [sfx_vectors.unit(vectors[key]) for key in keys]
        np = sfx_vectors._np
        q = np.asarray(query, dtype=np.float32).T if np is not None else query
        indexes, batches = {}, []
        cursor = self.con.execute('select sid, vec from clip_vec')
        while rows:=cursor.fetchmany(4096):
            offset = len(indexes)
            for i,(sid,_) in enumerate(rows):
                indexes[sid] = offset+i
            if np is not None:
                matrix = np.frombuffer(b''.join(blob for _,blob in rows), dtype=np.float32).reshape(len(rows),dims)
                batches.append(matrix @ q)
            else:
                batches.extend([[sfx_vectors.dot(sfx_vectors.unpack(blob),v) for v in query] for _,blob in rows])
        values = np.concatenate(batches, axis=0) if np is not None and batches else batches
        return _Scores(keys, indexes, values)


class SupercutRuntime:
    def __init__(self, host: dict[str, Any]):
        self.host = host
        base = host.get("DATA_DIR") or "data"
        self.root = Path(base) / "sfx_supercuts"
        self.root.mkdir(parents=True, exist_ok=True)
        from sfx_supercut_archive import SupercutArchive
        self.archive = SupercutArchive(host)
        self.archive_task: asyncio.Task | None = None
        self.progress_path = self.root / "census.json"
        self.progress = {"rowid": 0, "seen": 0, "complete": False, "at": 0.0, "why": ""}
        try:
            self.progress.update(json.loads(self.progress_path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.lock = asyncio.Lock()
        self.plan_lock = asyncio.Lock()
        self.source_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='supercut-source')
        self.catalog_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='supercut-catalog')
        self.catalog_future = None
        self.catalog_results = {}
        self.catalog_index = None
        self.catalog_analysis = {'state':'idle'}
        self.source_future = None
        self.source_results = {}
        self.analysis = {'state':'idle'}
        self.coverage_snapshot = {}
        self.census_future = None
        self.bootstrap_ready = {}
        self._scan_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.memo_path = self.root / "occurrences.json"
        self.station_sources_path = self.root / "recorded_station_sources.json"
        self.h3_sources_path = self.root / 'generated_h3_sources.json'
        try:
            self.h3_sources = json.loads(self.h3_sources_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.h3_sources = {}
        try:
            self.station_sources = json.loads(self.station_sources_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.station_sources = {}
        try:
            self.memo = json.loads(self.memo_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.memo = {}
        self.task: asyncio.Task | None = None

    def vectors(self):
        get = self.host.get("_sfx_vectors")
        rt = get() if callable(get) else None
        if rt is None:
            raise RuntimeError("The SFX vector keeper is unavailable")
        return rt

    def controls(self) -> tuple[set[str], dict[str, float], bool]:
        bans, weights, only = self.host.get("sfx_bans"), self.host.get("sfx_weights"), self.host.get("sfx_mp4_only")
        return (set(bans() or ()) if callable(bans) else set(),
                dict(weights() or {}) if callable(weights) else {}, True)

    def sync_batch(self, store: Any) -> dict[str, Any]:
        """Resumable keyset full census, not updates sorted before new rows."""
        with _book_connection(self.host["SFX_DB_PATH"]) as con:
            columns = _columns(con)
            wanted = [c for c in ("path", "sid", "name", "folder", "video", "seconds", "said", "seen_desc", "mtime") if c in columns]
            rows = con.execute("select rowid as source_rowid," + ",".join(wanted) +
                               " from clips where playable=1 and rowid>? order by rowid limit ?",
                               (int(self.progress["rowid"]), SYNC_BATCH)).fetchall()
        if rows:
            store.upsert_clips([dict(r, sid=str(r["sid"] or hashlib.sha1(str(r["path"]).encode()).hexdigest()[:16])) for r in rows])
            self.progress.update(rowid=int(rows[-1]["source_rowid"]), seen=int(self.progress["seen"]) + len(rows),
                                 complete=False, at=time.time(), why="")
        else:
            self.progress.update(complete=True, at=time.time(), why="")
        temporary = self.progress_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.progress), encoding="utf-8")
        temporary.replace(self.progress_path)
        return dict(self.progress)

    def catalog_read(self, function):
        store = self.vectors().store
        if self.catalog_index is None:
            self.catalog_index = _CatalogIndex(store) if hasattr(store, 'db_path') else store
        return function(self.catalog_index)

    async def bounded_catalog(self, label, function, *, timeout=30.0):   # [supercut-budget] was 6 s
        """Retain one complete scan across visits, releasing the station producer."""
        saved = self.catalog_future
        if saved is not None and saved[1].done():
            previous_label, future = saved
            try:
                self.catalog_results[previous_label] = future.result()
            except Exception as exc:
                self.catalog_results[previous_label] = exc
            self.catalog_future = None
            self.catalog_analysis.update(state='complete', completed_at=time.time())
            while len(self.catalog_results)>4:
                self.catalog_results.pop(next(iter(self.catalog_results)))
        if label in self.catalog_results:
            value = self.catalog_results.pop(label)
            if isinstance(value, Exception):
                raise value
            return value
        if self.catalog_future is not None:
            raise SourceAnalysisPending('The complete source catalog scan is still running; preparation will resume its retained result')
        future = asyncio.get_running_loop().run_in_executor(self.catalog_pool, lambda:self.catalog_read(function))
        self.catalog_future = (label, future)
        self.catalog_analysis.update(state='scanning', operation=label, started_at=time.time())
        try:
            value = await asyncio.wait_for(asyncio.shield(future), timeout=max(.05,timeout))
        except asyncio.TimeoutError as exc:
            reason='Complete catalog scan exceeded its production wait budget'
            if self.catalog_future is not None and self.catalog_future[1] is future:
                self.catalog_analysis.update(state='pending', why=reason, at=time.time())
            raise SourceAnalysisPending(reason) from exc
        except Exception:
            if self.catalog_future is not None and self.catalog_future[1] is future:
                self.catalog_future = None
                self.catalog_analysis.update(state='failed', at=time.time())
            raise
        if self.catalog_future is not None and self.catalog_future[1] is future:
            self.catalog_future = None
            self.catalog_analysis.update(state='complete', completed_at=time.time())
        return value

    async def status(self) -> dict[str, Any]:
        rt = self.vectors()
        if self.census_future is None or self.census_future.done():
            if self.census_future is not None:
                try:
                    self.coverage_snapshot = self.census_future.result()
                except Exception:
                    pass
            self.census_future = asyncio.create_task(self.bounded_catalog('coverage', lambda store:census(self.host['SFX_DB_PATH'],store), timeout=1.0))
        try:
            self.coverage_snapshot = await asyncio.wait_for(asyncio.shield(self.census_future), timeout=1.0)
        except (asyncio.TimeoutError, SourceAnalysisPending):
            pass
        return {'ok':True, 'schema':SCHEMA, 'config':config(), 'full_catalog_sync':dict(self.progress),
                'coverage':dict(self.coverage_snapshot), 'coverage_pending':not bool(self.coverage_snapshot) or self.catalog_future is not None,
                'catalog_scan':dict(self.catalog_analysis),
                'source_analysis':dict(self.analysis), 'speech':dict(self.host.get('_SFX_SPEECH') or {}),
                'archive_migration':dict(self.archive.migration),
                'say':'Every playable row is scored when composing; untranscribed audio remains pending analysis.'}

    async def bounded_source(self, label, function, *args, timeout=45.0):   # [supercut-budget] was 6 s
        saved = self.source_future
        if saved is not None and saved[1].done():
            previous_label, future = saved
            try:
                self.source_results[previous_label] = future.result()
            except Exception as exc:
                self.source_results[previous_label] = exc
            self.source_future = None
            while len(self.source_results)>64:
                self.source_results.pop(next(iter(self.source_results)))
        if label in self.source_results:
            value = self.source_results.pop(label)
            if isinstance(value, Exception):
                raise value
            return value
        if self.source_future is not None:
            raise SourceAnalysisPending('The one source-analysis worker is still completing its previous bounded request')
        future = asyncio.get_running_loop().run_in_executor(self.source_pool, lambda:function(*args))
        self.source_future = (label,future)
        self.analysis.update(state='analyzing',operation=label,started_at=time.time())
        try:
            value = await asyncio.wait_for(asyncio.shield(future),timeout=max(.05,timeout))
        except asyncio.TimeoutError as exc:
            self.analysis.update(state='pending',why='Source request exceeded its production time budget',at=time.time())
            raise SourceAnalysisPending(self.analysis['why']) from exc
        if self.source_future is not None and self.source_future[1] is future:
            self.source_future = None
        return value

    _cooled_cache: tuple[float, set[str]] = (0.0, set())

    def cooled(self, hours: float | None = None) -> set[str]:
        """[supercut-fresh] Every source sid a supercut used inside the cooldown: the archive's
        cues and the saved plans' clips (rendered or only composed). Cached a minute."""
        hours = COOLDOWN_HOURS if hours is None else float(hours)
        now = time.time()
        at, cached = self._cooled_cache
        if hours == COOLDOWN_HOURS and now - at < 60.0:
            return set(cached)
        since = now - hours * 3600.0
        out: set[str] = set()
        try:
            with self.archive.connection() as con:
                for row in con.execute("select metadata from archive where created_at >= ?", (since,)):
                    try:
                        meta = json.loads(row["metadata"])
                    except ValueError:
                        continue
                    cues = list(meta.get("cues") or []) + list((meta.get("source_plan") or {}).get("clips") or [])
                    for cue in cues:
                        if isinstance(cue, dict) and cue.get("sid"):
                            out.add(str(cue["sid"]))
        except Exception:  # noqa: BLE001
            pass
        for path in self.root.glob("sc-*.json"):
            try:
                stamp = path.stat().st_mtime
                if stamp < since:
                    continue
                plan = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if _number(plan.get("rendered_at"), stamp) < since:
                continue
            for clip in plan.get("clips") or []:
                if isinstance(clip, dict) and clip.get("sid"):
                    out.add(str(clip["sid"]))
        if hours == COOLDOWN_HOURS:
            self._cooled_cache = (now, set(out))
        return out

    def played_sids(self) -> set[str]:
        """[supercut-fresh] Every clip the endless set has put on the air (its durable deck)."""
        try:
            loader = self.host.get("_sfx_video_played_load")
            if callable(loader):
                loader()
            return set(str(k) for k in (self.host.get("_SFX_VIDEO_PLAYED") or {}).keys())
        except Exception:  # noqa: BLE001
            return set()

    def fresh_note(self) -> str:
        """[supercut-fresh] The footage rule in one sentence, with live counts, for the writer's brief."""
        try:
            resting = len(self.cooled())
        except Exception:  # noqa: BLE001
            resting = 0
        return ("Footage rule: every clip a supercut used rests %d hours (%d clip(s) resting now); build this one "
                "from clips that have never had play on the station (%d have), and prefer the ones the SFX Guy "
                "studied this week - push further into the unexplored library rather than returning to the "
                "same footage." % (int(COOLDOWN_HOURS), resting, len(self.played_sids())))

    def remember(self, key, plan):
        self.memo[key] = plan['id']
        while len(self.memo)>240:
            self.memo.pop(next(iter(self.memo)))
        tmp = self.memo_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(self.memo),encoding='utf-8')
        tmp.replace(self.memo_path)

    async def _verify_identity(self, candidates: list[dict[str, Any]], station: str, *, deadline=None) -> bool:
        transcriber = self.host.get("clip_speech")
        call = getattr(transcriber, "transcribe_file", None)
        writer, guard = self.host.get("sfx_db"), self.host.get("_SFX_DB_LOCK")
        if not callable(call) or not callable(writer) or guard is None:
            return False
        deadline = deadline or time.monotonic()+60.0
        for candidate in candidates[:6]:
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise SourceAnalysisPending('Station identity analysis reached its 60-second source budget')
            said = await self.bounded_source('identity:'+str(candidate['sid']),
                lambda path:call(path,timeout=min(6.0,remaining)),candidate['path'],timeout=min(6.0,remaining))
            if not said:
                continue
            def save():
                db = writer()
                with guard:
                    db.execute("update clips set said=?,said_at=? where sid=?", (_text(said, 600), time.time(), candidate["sid"]))
                    db.commit()
            await asyncio.to_thread(save)
            if _identity(str(said), station):
                return True
        return False

    async def generated_h3_sources(self, *, prompt='', analyze=False, deadline=None, max_seconds=180.):
        source = self.host.get('supercut_h3_sources')
        if not callable(source):
            return []
        value = await self.bounded_catalog('completed-h3-sources', lambda _store: source())
        from sfx_supercut_custom import recursive
        rows = [dict(row) for row in value or [] if isinstance(row, Mapping) and not recursive(row)
            and .06 <= _number(row.get('seconds')) <= 180.]
        transcriber = getattr(self.host.get('clip_speech'), 'transcribe_file', None)
        wanted = _words(prompt)
        rows.sort(key=lambda row: (-len(_words(str(row.get('candidate_text') or '') + ' ' + str(row.get('name') or '')) & wanted),
            -_number(row.get('mtime')), str(row.get('sid') or '')))
        deadline = deadline or time.monotonic()+60.
        changed = 0
        for row in rows:
            row['source_seconds'] = _number(row.get('seconds'))
            key = str(row.get('sid') or row['path']) + ':' + str(row.get('mtime'))
            cached = self.h3_sources.get(key)
            if not cached and not row.get('said') and analyze and callable(transcriber) and changed < 3:
                remaining = deadline-time.monotonic()
                if remaining <= .05:
                    raise SourceAnalysisPending('Generated H3 source analysis reached its 60 second visit budget')
                said = await self.bounded_source('h3-asr:'+key, lambda path: transcriber(path, timeout=min(6.,remaining)),
                    row['path'], timeout=min(6.,remaining))
                cached = {'said': _text(said, 3000), 'at': time.time()}
                self.h3_sources[key] = cached
                changed += 1
                temporary = self.h3_sources_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(self.h3_sources,ensure_ascii=False),encoding='utf-8')
                temporary.replace(self.h3_sources_path)
            if cached:
                row.update(said=cached['said'],said_at=cached['at'],transcript_scope='current_h3_source_asr')
                # clip_speech's PCM reader covers at most the initial 30 s.
                # Word windows must not extrapolate that evidence to later audio.
                row['seconds'] = min(_number(row['seconds']),30.)
                if row['source_seconds'] > 30:
                    row['transcript_scope'] = 'current_h3_first_30_seconds_asr'
            row.setdefault('provenance',{})['transcript_basis'] = 'actual_asr' if row.get('said') else 'not_yet_transcribed'
        if max_seconds <= 6.:
            excerpts = []
            from sfx_supercut_custom import audition, tokens, windows
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
            crop_visits = 0
            for row in rows:
                if row['seconds'] <= max_seconds:
                    excerpts.append(row)
                    continue
                heard = tokens(row.get('said'))
                if not heard or not analyze or not callable(transcriber):
                    continue
                key = str(row.get('sid') or row['path']) + ':' + str(row.get('mtime'))
                excerpt_key = key + ':excerpt:' + hashlib.sha256(str(prompt).encode()).hexdigest()[:16]
                cached_excerpt = self.h3_sources.get(excerpt_key)
                if cached_excerpt is not None:
                    if cached_excerpt.get('seconds'):
                        excerpts.append(copy.deepcopy(cached_excerpt))
                    continue
                if crop_visits >= 3:
                    continue
                crop_visits += 1
                count = min(6,len(heard))
                offsets = sorted(range(max(1,len(heard)-count+1)), key=lambda at:
                    (-len(set(heard[at:at+count]) & wanted),at))[:2]
                found = False
                for offset in offsets:
                    for start,end,basis in windows(row,offset,count):
                        if end-start > max_seconds or end-start < .45:
                            continue
                        stamp = key+':'+str(offset)+':'+str(start)+':'+str(end)
                        remaining = deadline-time.monotonic()
                        if remaining <= .05:
                            raise SourceAnalysisPending('Generated H3 cut verification reached its 60 second visit budget')
                        try:
                            proof = await self.bounded_source('h3-window:'+stamp,audition,row,start,end,transcriber,
                                executable,timeout=min(6.,remaining))
                        except (OSError,ValueError,subprocess.SubprocessError,wave.Error):
                            continue
                        if tokens(proof['said']) != heard[offset:offset+count]:
                            continue
                        excerpt = {**row,**proof,'seconds':end-start,'source_from_s':start,'source_until_s':end,
                            'transcript_scope':'current_h3_trimmed_window_asr','timing_basis':basis}
                        excerpts.append(excerpt)
                        self.h3_sources[excerpt_key] = copy.deepcopy(excerpt)
                        temporary = self.h3_sources_path.with_suffix('.tmp')
                        temporary.write_text(json.dumps(self.h3_sources,ensure_ascii=False),encoding='utf-8')
                        temporary.replace(self.h3_sources_path)
                        found=True;break
                    if found:break
                if not found:
                    self.h3_sources[excerpt_key] = {'why':'No exact ASR verified short word window', 'at':time.time()}
            return excerpts
        return rows

    async def plan(self, raw: Any = None, *, prompt: str = "", occurrence: str = "", verify: bool = False) -> dict[str, Any]:
        async with self.plan_lock:
            return await self._plan(raw, prompt=prompt, occurrence=occurrence, verify=verify)

    async def _plan(self, raw: Any = None, *, prompt: str = "", occurrence: str = "", verify: bool = False) -> dict[str, Any]:
        cfg = config(raw)
        memo_key = hashlib.sha256(json.dumps([cfg, prompt, occurrence], sort_keys=True).encode()).hexdigest()
        if occurrence and self.memo.get(memo_key):
            try:
                retained = await asyncio.to_thread(self.load, str(self.memo[memo_key]))
                if retained.get('analysis_state') == 'pending':
                    retained = await self.seal(retained)
                    await asyncio.to_thread(self.save,retained)
                return retained
            except (OSError, ValueError):
                pass
        rt = self.vectors()
        bans, weights, only = self.controls()
        queries = role_queries(cfg, prompt)
        source_deadline=time.monotonic()+60.0
        extra_sources = await self.recorded_station_sources(cfg, analyze=verify, deadline=source_deadline)
        extra_sources += await self.generated_h3_sources(prompt=str(cfg['item'])+' '+prompt, analyze=verify, deadline=source_deadline, max_seconds=6.)
        source_remaining = max(0.0, source_deadline-time.monotonic())
        cooled = set() if cfg.get('custom') else await asyncio.to_thread(self.cooled)        # [supercut-fresh]
        played = set() if cfg.get('custom') else await asyncio.to_thread(self.played_sids)   # [supercut-fresh]
        scan_key = hashlib.sha256(json.dumps([cfg, prompt, sorted(bans), weights, only, sorted(cooled), len(played)], sort_keys=True).encode()).hexdigest()
        cached = self._scan_cache.get(scan_key)
        vectors = {}
        if cached and time.time() - cached[0] < 120:
            scan = cached[1]
        else:
            if not rt.desk_busy():
                try:
                    embedded = await asyncio.wait_for(rt.embed(list(queries.values())), timeout=4.0)
                except asyncio.TimeoutError:
                    embedded = []  # query embeddings are optional when the station owns the model
                vectors = {k: v for k, v in zip(queries, embedded) if v}
            scan = await self.bounded_catalog('scan:'+scan_key, lambda store:scan_catalog(self.host["SFX_DB_PATH"], store, cfg, prompt=prompt,
                                                    vectors=vectors, banned=bans, weights=weights, mp4_only=only, extra_sources=extra_sources, exclude=cooled, played=played))
            if len(self._scan_cache) >= 8:
                self._scan_cache.pop(next(iter(self._scan_cache)))
            self._scan_cache[scan_key] = (time.time(), scan)
        source_deadline=time.monotonic()+source_remaining
        if verify and not scan["identities"] and scan["identity_to_analyze"]:
            await self._verify_identity(scan["identity_to_analyze"], str(cfg["station"]),deadline=source_deadline)
            source_remaining=max(0.0,source_deadline-time.monotonic())
            scan = await self.bounded_catalog('verified-scan:'+scan_key, lambda store:scan_catalog(self.host["SFX_DB_PATH"], store, cfg, prompt=prompt,
                                                     vectors=vectors, banned=bans, weights=weights, mp4_only=only, extra_sources=extra_sources, exclude=cooled, played=played))
            self._scan_cache[scan_key] = (time.time(), scan)
            source_deadline=time.monotonic()+source_remaining
        roll_records: list[dict[str, Any]] = []
        roll = self.host.get("s3_weighted")
        def roulette(role, candidates):
            if not callable(roll):
                return 0
            labels = [str(c.get("name") or c["sid"])[:130] + " [" + c["sid"] + "]" for c in candidates]
            weights = [max(0.01, float(c.get("score") or c.get("weight") or 1)) for c in candidates]
            key = "segment.sfx_supercut." + role
            selected = int(roll(key, labels, weights, "which source clip supplies the " + role + " of this source-only station supercut"))
            roll_records.append({"key": key, "role": role, "candidates": len(candidates), "picked": candidates[selected]["sid"],
                                 "catalog_scanned": scan["coverage"]["catalog_scanned"]})
            return selected
        result = compose(scan, cfg, occurrence, roulette=roulette if callable(roll) else None)
        freshness = {"cooldown_hours": COOLDOWN_HOURS, "resting": len(cooled), "played_known": len(played),
                     "rested_sources": int((scan.get("coverage") or {}).get("rested_sources") or 0),
                     "explored_recently": int((scan.get("coverage") or {}).get("explored_recently") or 0),
                     "relaxed": False}
        if not result.get("ok") and cooled:
            # [supercut-fresh] never nothing: a cut that only the resting footage can make is made from it, and says so
            relaxed = await self.bounded_catalog('relaxed-scan:'+scan_key, lambda store:scan_catalog(self.host["SFX_DB_PATH"], store, cfg, prompt=prompt,
                                                     vectors=vectors, banned=bans, weights=weights, mp4_only=only, extra_sources=extra_sources, played=played))
            again = compose(relaxed, cfg, occurrence, roulette=roulette if callable(roll) else None)
            if again.get("ok"):
                result, scan = again, relaxed
                freshness["relaxed"] = True
        result["freshness"] = freshness
        if result.get("ok"):
            if cfg.get('campaign'):
                result['campaign'] = copy.deepcopy(cfg['campaign'])
                result['generated_script'] = str(cfg['campaign'].get('script') or '')
            result['rolls'] = roll_records
            result.update(analysis_state='pending',complete=False)
            await asyncio.to_thread(self.save,result)
            if occurrence:
                await asyncio.to_thread(self.remember,memo_key,result)
            result = await self.seal(result,deadline=source_deadline)
            await asyncio.to_thread(self.save,result)
        return result

    async def recorded_station_sources(self, cfg: Mapping[str, Any], *, analyze: bool = False, deadline=None) -> list[dict[str, Any]]:
        """Borrow original recorded station IDs, without taking their reservations.

        These stay in a separate source overlay and are not added to the normal
        SFX rotation. Existing source metadata retains the pantry address and
        original engine, while ASR verifies the actual file when first borrowed.
        """
        pantry = self.host.get("_PANTRY")
        if not isinstance(pantry, dict):
            try:
                pantry = json.loads((Path(self.host.get("DATA_DIR") or "data") / "pantry.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pantry = {}
        media = Path(self.host.get("VOICE_MEDIA_DIR") or Path(self.host.get("DATA_DIR") or "data") / "voice_media").resolve()
        transcriber = getattr(self.host.get("clip_speech"), "transcribe_file", None)
        rows = []
        analyzed = 0
        eligible = [(k, v) for k, v in list(pantry.items()) if isinstance(v, dict) and v.get("kind") == "station_id"
                    and _identity(str(v.get("text") or ""), str(cfg["station"]))]
        eligible.sort(key=lambda kv: ("welcome" not in str(kv[1].get("text") or "").lower(), str(kv[0])))
        deadline=deadline or time.monotonic()+60.0
        for key, row in eligible[:40]:
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise SourceAnalysisPending('Recorded station source analysis reached its 60-second source budget')
            name = str((row.get("clip") or {}).get("path") or "").split("?")[0].rsplit("/", 1)[-1]
            if not re.fullmatch(r"[a-f0-9]{32}\.wav", name):
                continue
            source = media / name
            try:
                stat = await self.bounded_source('station-stat:'+name+':'+str(time.monotonic_ns()),
                    source.stat,timeout=min(6.0,remaining))
                def duration():
                    with wave.open(str(source), "rb") as wav:
                        return wav.getnframes()/wav.getframerate()
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    raise SourceAnalysisPending('Recorded station source analysis reached its 60-second source budget')
                seconds = await self.bounded_source('station-duration:'+name+':'+str(stat.st_mtime_ns),
                    duration,timeout=min(6.0,remaining))
            except (OSError, wave.Error):
                continue
            if not 0.45 <= seconds <= 6.0:
                continue
            cache_key = name + ":" + str(stat.st_mtime_ns)
            cached = self.station_sources.get(cache_key)
            if not cached and analyze and callable(transcriber) and analyzed < 4:
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    raise SourceAnalysisPending('Recorded station source analysis reached its 60-second source budget')
                said = await self.bounded_source('station-asr:'+cache_key,
                    lambda path:transcriber(path,timeout=min(6.0,remaining)),str(source),timeout=min(6.0,remaining))
                analyzed += 1
                cached = {"said": _text(said, 600), "at": time.time()}
                self.station_sources[cache_key] = cached
            if not cached or not _identity(str(cached.get("said") or ""), str(cfg["station"])):
                continue
            sid = hashlib.sha1(str(source).encode()).hexdigest()[:16]
            rows.append({"sid": sid, "path": str(source), "name": _text(row.get("text"), 180),
                         "folder": "recorded station IDs", "video": 0, "seconds": seconds,
                         "mtime": stat.st_mtime, "said": cached["said"], "said_at": cached["at"],
                         "transcript_scope": "current_recorded_station_source_asr",
                         "provenance": {"catalog": "station_id pantry", "pantry_key": str(key),
                                        "original_media_key": name, "original_engine": (row.get("clip") or {}).get("engine"),
                                        "original_text": _text(row.get("text"), 1200), "existing_audio_only": True}})
        if analyzed:
            def save_sources():
                tmp = self.station_sources_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(self.station_sources), encoding="utf-8")
                tmp.replace(self.station_sources_path)
            await asyncio.to_thread(save_sources)
        return rows

    async def seal(self, plan: dict[str, Any], *, deadline=None) -> dict[str, Any]:
        """Stat selected sources only, and refresh stale audio descriptions.

        Some grabbed files are shortened after the catalog scan. A cached
        transcript of the former longer file must not be labelled as the
        current cut's words. ASR refresh stays bounded to the chosen montage.
        """
        try:
            transcriber = getattr(self.host.get("clip_speech"), "transcribe_file", None)
            writer, guard = self.host.get("sfx_db"), self.host.get("_SFX_DB_LOCK")
            refreshed = pending = 0
            deadline = deadline or time.monotonic()+60.0
            for p in plan["clips"]:
                remaining = deadline-time.monotonic()
                if remaining<=0:
                    raise SourceAnalysisPending('The selected-source analysis visit reached its 16-second budget')
                stat = await self.bounded_source('stat:'+p['sid']+':'+str(time.monotonic_ns()),
                    Path(p['path']).stat,timeout=min(6.0,remaining))
                p.setdefault("catalog_mtime",p.get("mtime"))
                p["mtime"], p["bytes"] = stat.st_mtime, stat.st_size
                if (abs(stat.st_mtime-_number(p['catalog_mtime']))<=.01
                        or p.get('analysis_verified_mtime')==stat.st_mtime) and not p.get('source_analysis_pending'):
                    continue
                p["source_changed_since_catalog"] = True
                p["source_transcript"] = p.get("said") or ""
                if callable(transcriber) and refreshed < 24:
                    p['source_analysis_pending']=True
                    def transcribe_current():
                        return transcriber(p['path'],timeout=6.0)
                    said = await self.bounded_source('asr:'+p['sid']+':'+str(stat.st_mtime_ns),
                        transcribe_current,timeout=min(6.0,max(.05,deadline-time.monotonic())))
                    p['source_analysis_pending']=False
                    p['analysis_verified_mtime']=stat.st_mtime
                    refreshed += 1
                    p["said"] = _text(said, 600)
                    p["transcript_scope"] = "current_entire_source_asr" if said else "current_source_untranscribed"
                    if callable(writer) and guard is not None:
                        def update_source():
                            db = writer()
                            with guard:
                                db.execute("update clips set said=?,said_at=?,mtime=?,bytes=? where sid=?",
                                           (p["said"], time.time() if p["said"] else None, stat.st_mtime, stat.st_size, p["sid"]))
                                db.commit()
                        await asyncio.to_thread(update_source)
                else:
                    p["said"] = ""
                    p["transcript_scope"] = "changed_source_pending_asr"
                    pending += 1
            if not _identity(str(plan["clips"][-1].get("said") or ""), str(plan["config"]["station"])):
                raise ValueError("The current closing source has no verified spoken station identity")
            queries = role_queries(plan["config"], str(plan.get("prompt") or ""))
            for p in plan["clips"][1:-1]:
                role = str(p.get("role") or "flair")
                spoken = _words(p.get("said"))
                matches = spoken & _words(queries.get(role, ""))
                p.setdefault("why", {})["current_spoken_matches"] = sorted(matches)
                if role in ("sell", "timely") and not matches:
                    p["planned_role"] = role
                    p["role"] = "flair"
                    p["why"]["role_adjusted_after_source_analysis"] = True
            plan["structure"]["sell"] = any(p["role"] == "sell" for p in plan["clips"])
            plan["structure"]["timely"] = any(p["role"] == "timely" for p in plan["clips"])
            if not plan["structure"]["sell"]:
                raise ValueError("Refreshed source audio supplies no spoken sales beat; another source plan is needed")
            plan['product_evidence'] = product_evidence(plan['config'], plan['clips'])
            if not plan['product_evidence']['verified']:
                raise SourceAnalysisPending('Recorded product-selling source evidence is still unavailable for this item')
            plan["source_analysis"] = {"refreshed_selected_sources": refreshed, "changed_sources_pending_asr": pending,
                                        "description_basis": "machine transcripts; every playback cut is the original source audio"}
            if pending:
                plan.setdefault("warnings", []).append(str(pending) + " changed source descriptions await ASR; no spoken text is inferred from those descriptions.")
            plan.update(analysis_state='complete',complete=True)
            self.analysis.update(state='complete',plan_id=plan['id'],at=time.time())
            return plan

        except SourceAnalysisPending as exc:
            plan.update(analysis_state='pending',complete=False)
            plan['source_analysis']={'state':'pending','why':str(exc),'at':time.time(),
                'verified_selected_sources':sum(bool(p.get('analysis_verified_mtime')) for p in plan['clips']),
                'selected_sources':len(plan['clips'])}
            self.analysis.update(plan['source_analysis'],plan_id=plan['id'])
            await asyncio.to_thread(self.save,plan)
            raise

    def save(self, plan: Mapping[str, Any]) -> None:
        pid = str(plan["id"])
        if not re.fullmatch(r"sc-[a-f0-9]{24}", pid):
            raise ValueError("Invalid supercut plan ID")
        path = self.root / (pid + ".json")
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(path)

    def load(self, pid: str) -> dict[str, Any]:
        if not re.fullmatch(r"sc-[a-f0-9]{24}", pid):
            raise ValueError("Invalid supercut plan ID")
        return json.loads((self.root / (pid + ".json")).read_text(encoding="utf-8"))

    async def render(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        async with self.lock:
            import imageio_ffmpeg
            from sfx_supercut_video import require_mp4_sources, render_video
            require_mp4_sources(plan)
            media = Path(self.host.get("VOICE_MEDIA_DIR") or self.root)
            filename = hashlib.sha256((str(plan["id"]) + SCHEMA).encode()).hexdigest()[:32] + ".wav"
            output = media / filename
            bans, weights, _only = self.controls()
            result = await asyncio.to_thread(render_source_plan, plan, output, imageio_ffmpeg.get_ffmpeg_exe(),
                                             banned=bans, weights=weights)
            video = await asyncio.to_thread(render_video, plan, result, output.with_suffix(".mp4"), imageio_ffmpeg.get_ffmpeg_exe())
            result.update(video)
            result["source_plan"].update(video=video["video"], video_sha256=video["video_sha256"], video_source_only=True)
            await asyncio.to_thread(self.save, result["source_plan"])
            sign = self.host.get("media_sign")
            if callable(sign):
                signature = str(sign(filename))
                result["media"] = {"path": "/media/" + filename, "sig": signature, "seconds": result["seconds"]}
                result["url"] = "/media/" + filename + "?sig=" + signature
            result["audio"] = filename
            result["product"] = str((plan.get("config") or {}).get("item") or "Pine Box FM")
            result["text"] = result["recorded_text"]
            result['campaign'] = copy.deepcopy(plan.get('campaign') or (plan.get('config') or {}).get('campaign') or {})
            result['generated_script'] = str(plan.get('generated_script') or result['campaign'].get('script') or '')
            result['archive'] = await asyncio.to_thread(self.archive.record, result)
            result['archive_id'] = result['archive']['id']
            return result

    def verify_bootstrap(self, pid, expected_hash, occurrence, requested):
        plan = self.load(pid)
        if not plan.get('source_only') or not plan.get('complete') or not plan.get('clip'):
            raise ValueError('Bootstrap needs an already rendered complete source-only plan')
        original = config(plan.get('config'))
        wanted = config(requested)
        if (not _identity(original['station'],wanted['station'])
                or re.sub(r'[^a-z0-9]','',original['sponsor'].lower())!=re.sub(r'[^a-z0-9]','',wanted['sponsor'].lower())
                or re.sub(r'[^a-z0-9]','',original['item'].lower())!=re.sub(r'[^a-z0-9]','',wanted['item'].lower())
                or abs(original['target_seconds']-wanted['target_seconds'])>.01):
            raise ValueError('The existing audio does not match this station, item and duration')
        required = ('opening','sell','closing','station_identity_verified')
        if not all((plan.get('structure') or {}).get(key) for key in required):
            raise ValueError('Bootstrap lacks the verified source-only station/sales structure')
        clips = plan.get('clips') or []
        cues = plan.get('cues') or []
        if not clips or len(clips)!=len(cues) or not _identity(str(clips[-1].get('said') or ''),wanted['station']):
            raise ValueError('The closing source and measured montage cues do not verify the station identity')
        bans,weights,only = self.controls()
        for clip,cue in zip(clips,cues):
            sid = str(clip.get('sid') or '')
            if not sid or sid in bans or finite_weight(weights.get(sid,1))<=.05:
                raise ValueError('A bootstrap source is now banned or disabled')
            if only and not clip.get('video') and not (clip.get('provenance') or {}).get('existing_audio_only'):
                raise ValueError('A bootstrap source no longer meets the current video policy')
            if cue.get('sid')!=sid or Path(clip['path']).stat().st_mtime!=clip.get('mtime'):
                raise ValueError('An original bootstrap source changed since its verified recording')
        name = str(plan['clip'])
        if not re.fullmatch(r'[a-f0-9]{32}\.wav',name):
            raise ValueError('Bootstrap media must be a native station WAV')
        path = Path(self.host['VOICE_MEDIA_DIR'])/name
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if not re.fullmatch(r'[a-f0-9]{64}',str(expected_hash)) or digest!=expected_hash:
            raise ValueError('The native promo hash changed since the authorized verification')
        with wave.open(str(path),'rb') as audio:
            frames,rate,channels,width=audio.getnframes(),audio.getframerate(),audio.getnchannels(),audio.getsampwidth()
            if channels!=1 or width!=2 or not any(audio.readframes(frames)):
                raise ValueError('Bootstrap WAV is empty or has an unexpected audio format')
        seconds=frames/rate
        if (abs(seconds-_number(plan.get('seconds')))>.002 or not 30<=seconds<=60
                or abs(seconds-wanted['target_seconds'])>1.0
                or abs(_number(cues[-1].get('until'))-seconds)>.002):
            raise ValueError('Actual bootstrap PCM frames do not match its original measured source cues')
        source_plan=copy.deepcopy(plan)
        source_plan.update(occurrence=occurrence,bootstrap_from_occurrence=plan.get('occurrence'),
            bootstrap_media_sha256=digest,bootstrap_verified_at=time.time())
        media={'path':'/media/'+name,'sig':self.host['media_sign'](name),'seconds':seconds}
        return {'ok':True,'clip':name,'key':name,'audio':name,'path':str(path),
            'seconds':seconds,'body_seconds':seconds,'body_frames':frames,'sample_rate':rate,
            'source_plan':source_plan,'source_only':True,'complete':True,'engine':'sfx_supercut',
            'cues':copy.deepcopy(cues),'recorded_text':' / '.join(str(c.get('said') or '') for c in cues),
            'product':wanted['item'],'media':media,'url':media['path']+'?sig='+media['sig'],
            'bootstrap_media_sha256':digest}

    async def bootstrap(self,pid,expected_hash):
        import segment_prompts
        import dynamic_segments
        adapter=self.host.get('DYNAMIC_SEGMENTS_SYSTEM2')
        dynamic=self.host.get('DYNAMIC_SEGMENTS_RUNTIME')
        if adapter is None or dynamic is None or not adapter.runtime.enabled:
            raise ValueError('Bootstrap uses the active native System2 dynamic preparation contract')
        slots=sorted((slot for hour in adapter.runtime._plans for slot in hour.get('slots',[])
            if slot.get('dynamic_kind')=='sfx_supercut' and slot['start']>time.time()),key=lambda slot:slot['start'])
        if not slots:
            raise ValueError('There is no future scheduled supercut to bootstrap')
        due=adapter.due(slots[0])
        occurrence=dynamic.occurrence(due)
        key=segment_prompts.memo_key('sfx_supercut',due['slot_id'],occurrence)
        words=await asyncio.to_thread(segment_prompts.govern,'sfx_supercut',dynamic_segments.SFX_SUPERCUT['text'],key)
        chosen=segment_prompts.occurrence_view('sfx_supercut',key) or {}
        requested=dict(chosen.get('config') or dynamic_segments.SFX_SUPERCUT['config'])
        settings=self.host['dj_settings']()
        requested['station']=settings.get('station_name') or 'Pine Box FM'
        # One explicit bounded proof visit. This endpoint never starts playback.
        prepared=await asyncio.wait_for(asyncio.to_thread(self.verify_bootstrap,pid,expected_hash,occurrence,requested),16)
        self.bootstrap_ready[occurrence]={'prepared':prepared,'requested':config(requested),
            'prompt_hash':hashlib.sha256(words.encode()).hexdigest()}
        row=await dynamic.prepare_supercut(due)
        if not row:
            raise SourceAnalysisPending('The native scheduled producer still owns this occurrence; retry the explicit bootstrap after it yields')
        adapter.runtime._last_refresh=0
        return {'ok':True,'occurrence':occurrence,'slot_id':slots[0]['id'],'clip':prepared['clip'],
            'seconds':prepared['seconds'],'body_frames':prepared['body_frames'],
            'sample_rate':prepared['sample_rate'],'source_only':True,'coverage':row['coverage'],
            'source_plan':prepared['source_plan']['id'],'media_sha256':prepared['bootstrap_media_sha256'],
            'media':prepared['media'],'autoplay':False}

    async def prepare(self, slot: Any = None, prompt: str = "", occurrence: str = "") -> dict[str, Any]:
        got = dict(slot) if isinstance(slot, Mapping) else {}
        raw = dict(got.get("dynamic_config") or got.get("config") or got.get("template_config") or {})
        for key in ("station", "sponsor", "item", "context", "target_seconds", "min_seconds", "max_seconds"):
            # System2 target_seconds describes the wall allocation. A chosen
            # dynamic preset owns the source-audio body duration and controls.
            if key in got and key not in raw:
                raw[key] = got[key]
        settings = self.host.get("dj_settings")
        if callable(settings):
            raw.setdefault("station", (settings() or {}).get("station_name"))
        raw.setdefault("context", str((self.host.get("_RADIO") or {}).get("topic") or ""))
        occurrence = occurrence or str(got.get("occurrence") or got.get("id") or int(time.time() // 3600))
        approved=self.bootstrap_ready.get(occurrence)
        if approved:
            current=config(raw)
            expected=approved['requested']
            if (all(current[field]==expected[field] for field in ('station','sponsor','item','target_seconds'))
                    and hashlib.sha256(prompt.encode()).hexdigest()==approved['prompt_hash']):
                return copy.deepcopy(approved['prepared'])
        plan = await self.plan(raw, prompt=prompt, occurrence=occurrence, verify=True)
        return await self.render(plan) if plan.get("ok") else plan

    async def keeper(self):
        while True:
            try:
                rt = self.vectors()
                # The station's active writer has priority over an index census.
                # No transcription or embedding is added by this census itself.
                if not rt.desk_busy():
                    await rt.run(self.sync_batch, rt.store)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.progress["why"] = str(exc)[:240]
            await asyncio.sleep(15 if not self.progress.get("complete") else 300)


def install(app: Any, host: dict[str, Any]) -> SupercutRuntime:
    from fastapi import Header, HTTPException, Request
    globals()["Request"] = Request
    runtime = SupercutRuntime(host)
    host["sfx_supercut_prepare"] = runtime.prepare
    host["_sfx_supercut_runtime"] = runtime
    host["supercut_fresh_note"] = runtime.fresh_note             # [supercut-fresh] the rule, for the writer's brief
    import sfx_supercut_custom
    sfx_supercut_custom.install(app, host, runtime)

    async def body(request):
        got = await request.json()
        return got if isinstance(got, dict) else {}

    @app.get("/api/sfx/supercut/status")
    async def status(authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        return await runtime.status()

    @app.post('/api/sfx/supercut/bootstrap')
    async def bootstrap(request:Request,authorization:str|None=Header(default=None)):
        host['require_auth'](authorization)
        body=await request.json()
        try:
            return await runtime.bootstrap(str(body.get('plan_id') or ''),str(body.get('media_sha256') or ''))
        except (SourceAnalysisPending,asyncio.TimeoutError) as exc:
            raise HTTPException(409,str(exc) or 'Bootstrap source verification exceeded its time budget') from exc
        except (OSError,ValueError) as exc:
            raise HTTPException(409,str(exc)) from exc

    @app.post("/api/sfx/supercut/plan")
    async def plan(request: Request, authorization: str | None = Header(default=None)):
        host["require_auth"](authorization)
        got = await body(request)
        return await runtime.plan(got.get("config") or got, prompt=_text(got.get("prompt")),
                                  occurrence=_text(got.get("occurrence"), 200), verify=bool(got.get("analyze_sources")))

    @app.get("/api/sfx/supercut/plans/{pid}")
    async def get_plan(pid: str, authorization: str | None = Header(default=None)):
        host["require_read_auth"](authorization)
        try:
            return await asyncio.to_thread(runtime.load, pid)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/sfx/supercut/render")
    async def render(request: Request, authorization: str | None = Header(default=None)):
        host["require_auth"](authorization)
        got = await body(request)
        try:
            planned = await asyncio.to_thread(runtime.load, str(got.get("plan_id") or ""))
            return await runtime.render(planned)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/api/sfx/supercut/archive')
    async def archive_list(limit: int = 24, offset: int = 0, q: str = '', summary: bool = False, authorization: str | None = Header(default=None)):
        host['require_read_auth'](authorization)
        return await asyncio.to_thread(runtime.archive.list, limit=limit, offset=offset, query=q, summary=summary)

    @app.get('/api/sfx/supercut/archive/{identifier}')
    async def archive_detail(identifier: str, authorization: str | None = Header(default=None)):
        host['require_read_auth'](authorization)
        try:
            return await asyncio.to_thread(runtime.archive.detail, identifier)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get('/api/sfx/supercut/archive/{identifier}/audio')
    async def archive_audio(identifier: str, request: Request, authorization: str | None = Header(default=None)):
        from fastapi.responses import FileResponse
        sign = host.get('media_sign')
        signature = str(sign(identifier)) if callable(sign) else ''
        if not (signature and hmac.compare_digest(str(request.query_params.get('t') or ''), signature)):
            host['require_read_auth'](authorization)
        try:
            path = await asyncio.to_thread(runtime.archive.audio, identifier)
            return FileResponse(path, media_type='audio/wav', headers={'X-Content-Type-Options': 'nosniff'})
        except (OSError, ValueError, wave.Error) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get('/api/sfx/supercut/archive/{identifier}/video')
    async def archive_video(identifier: str, request: Request, authorization: str | None = Header(default=None)):
        from fastapi.responses import FileResponse
        sign = host.get('media_sign')
        signature = str(sign(identifier)) if callable(sign) else ''
        if not (signature and hmac.compare_digest(str(request.query_params.get('t') or ''), signature)):
            host['require_read_auth'](authorization)
        try:
            path = await asyncio.to_thread(runtime.archive.video, identifier)
            return FileResponse(path, media_type='video/mp4', headers={'X-Content-Type-Options': 'nosniff'})
        except (OSError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post('/api/sfx/supercut/archive/{identifier}/reuse')
    async def archive_reuse(identifier: str, authorization: str | None = Header(default=None)):
        host['require_auth'](authorization)
        try:
            return await asyncio.to_thread(runtime.archive.reuse, identifier)
        except (OSError, ValueError, wave.Error) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.on_event("startup")
    async def start():
        runtime.task = asyncio.create_task(runtime.keeper())
        runtime.archive_task = asyncio.create_task(asyncio.to_thread(runtime.archive.migrate, runtime.root,
            Path(host.get('VOICE_MEDIA_DIR') or runtime.root)), name='supercut-archive-migration')

    @app.on_event("shutdown")
    async def stop():
        if runtime.task:
            runtime.task.cancel()
            try:
                await runtime.task
            except asyncio.CancelledError:
                pass
        if runtime.archive_task:
            await asyncio.shield(runtime.archive_task)
        runtime.source_pool.shutdown(wait=False, cancel_futures=True)
        runtime.catalog_pool.shutdown(wait=False, cancel_futures=True)
    return runtime
