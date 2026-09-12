"""The Library (#1158) — the shelf the station reads and remembers.

Documents dropped into a watched folder are picked up on their own, read into
pages, cut into overlapping chunks, embedded through the local embedder and
kept where a question can find them again. Nothing is clicked and nothing is
restarted: `ingest_clock` notices the file and the answer starts citing it.

Everything the app must hand over is injected by `configure` — the embedder,
the data directory, the page ranker, and a "is the show busy" flag — so this
module imports nothing from app.py and can be exercised on its own.

Two halves worth knowing apart:

  the shelf     index.json + <slug>/doc.json + <slug>/pages/*.html
  the memory    vec/<slug>.npy  (float32, one unit row per chunk)
                vec/<slug>.jsonl (the same rows' text and page, in order)

The vectors are PER DOCUMENT and they are .npy, deliberately. The DJs' one
big vectors.json grew to 625 MB and parsing it for a chunk COUNT froze the
event loop 11.4 s (#1156) — the C json decoder holds the GIL, so a thread
does not help. np.load(mmap_mode="r") is instant, a deleted document is one
file removed, and a restart mid-ingest resumes at the last finished book.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from collections import OrderedDict
from threading import RLock
from typing import Any, Callable, Iterable

import library_extract as extract

# --- what the app hands over -----------------------------------------------

_DATA: Path = Path("data/library")
_EMBED: Callable[[list[str]], Any] | None = None
_BUSY: Callable[[], bool] = lambda: False
_PAGE_SCORE: Callable[[dict[str, Any], list[str]], float] | None = None
_REFERENCE: list[str] = []            # folders whose documents may OPEN the shelf
_TOPIC_WORDS: Callable[[str], list[str]] | None = None
_LOG: Callable[[str], None] = lambda line: None

# --- dials ------------------------------------------------------------------

CHUNK_CHARS = 900          # about a screenful; nomic handles it comfortably
CHUNK_OVERLAP = 150        # a fact that straddles a boundary stays findable
CHUNK_MIN = 60             # shorter than this and there is nothing to match
EMBED_BATCH = 32
PER_DOC_CHUNKS = 6000
VEC_MAX = 300000           # the whole shelf, all folders together
# Measured twice against the real shelf, and the second measurement is the
# one that matters. On eight manuals a cosine floor was enough. Once the 321
# speakbox transcripts joined them, it stopped working: a shelf that holds
# hundreds of hours of people talking is plausibly "about" anything.
#
#   question the shelf answers   cosine 0.63-0.76   word score 4.3-9.8
#   question it must leave alone cosine 0.53-0.65   word score 0.0-2.0
#
# The cosines OVERLAP. The word scores do not, and the reason is not an
# accident: somebody asking a manual a question uses the manual's own words -
# the control names, the model numbers, the menus. Somebody asking about the
# capital of France does not. So the shelf opens on the LETTERS, and the
# meaning is what ranks the passages once it is open.
SEARCH_FLOOR = 0.52        # the topic still has to fit...
WORD_FLOOR = 3.0           # ...and the question must use the document's words
KEEP_FLOOR = 0.42          # once open, neighbours this good ride along
WORD_KEEP = 2.0
WORD_STRONG = 8.0          # an exact hit ("EP-133 fader") needs less topic
WORD_COSINE = 0.45
# Being documentation is worth about half a rank when the passages are
# ordered: the shelf opened on a manual, so a manual should lead the
# answer even when a transcript happens to repeat the question's words.
REFERENCE_BONUS = 0.5
IDLE_SECONDS = 120         # how often the shelf is re-read
BUSY_SLEEP = 2.5           # between batches while the show is talking
EASY_SLEEP = 0.15          # between batches while it is not
RRF_K = 60.0               # reciprocal-rank fusion constant
WORD_DOCS = 12             # documents the lexical half will open

SHARD_CACHE = 150          # documents whose chunk text is held in memory

_LOCK = RLock()
_INDEX: dict[str, Any] | None = None
# slug -> (stamp, matrix, rows), least-recently-used first. The matrices are
# memory-mapped and cost almost nothing; the row TEXT is what adds up, and on
# a shelf of three hundred transcripts it would grow without a bound. This box
# has been taken down by memory pressure before (#1156), so it is capped.
_SHARDS: "OrderedDict[str, Any]" = OrderedDict()   # slug -> (stamp, rows)
_MATS: dict[str, Any] = {}            # slug -> (stamp, mmap matrix)
_DF_CACHE: dict[str, Any] = {}        # derived, keyed by which docs are ready
_VOCAB_CACHE: dict[str, Any] = {}
_WORK: dict[str, Any] = {             # what the console tails
    "running": False, "doc": "", "phase": "", "done": 0, "total": 0,
    "started": 0.0, "finished": 0.0, "last": "", "pass": 0, "burst": False,
}
_BURST = False
_WAKE: asyncio.Event | None = None


def configure(*, data_dir: Path | str, embed: Callable[[list[str]], Any],
              busy: Callable[[], bool] | None = None,
              page_score: Callable[[dict[str, Any], list[str]], float] | None = None,
              topic_words: Callable[[str], list[str]] | None = None,
              reference: list[str] | None = None,
              log: Callable[[str], None] | None = None) -> None:
    """Wire the shelf to the app. Safe to call again on a settings change."""
    global _DATA, _EMBED, _BUSY, _PAGE_SCORE, _TOPIC_WORDS, _LOG, _REFERENCE
    _DATA = Path(data_dir)
    _EMBED = embed
    _BUSY = busy or (lambda: False)
    _PAGE_SCORE = page_score
    _TOPIC_WORDS = topic_words
    _REFERENCE = [str(f).rstrip("/") for f in (reference or []) if str(f or "")]
    _LOG = log or (lambda line: None)
    try:
        (_DATA / "vec").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


# --- the index --------------------------------------------------------------


def index_path() -> Path:
    return _DATA / "index.json"


def doc_dir(slug: str) -> Path:
    return _DATA / slug


def shard_paths(slug: str) -> tuple[Path, Path]:
    return _DATA / "vec" / f"{slug}.npy", _DATA / "vec" / f"{slug}.jsonl"


def vocab_path(slug: str) -> Path:
    return doc_dir(slug) / "vocab.json"


def slug_for(path: Path | str) -> str:
    """A stable, boring folder name for a document. The source path is what
    identifies it, so two books with the same title on different shelves do
    not collide."""
    path = Path(path)
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:48]
    # sha1, not hash(): PYTHONHASHSEED is random per process, so builtin
    # hash would hand the same document a new folder on every restart.
    tail = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    return f"{stem or 'doc'}-{tail}"


def _read_index() -> dict[str, Any]:
    try:
        raw = index_path().read_text(encoding="utf-8")
        got = json.loads(raw)
        if isinstance(got, dict) and isinstance(got.get("docs"), dict):
            return got
    except (OSError, ValueError):
        pass
    return {"docs": {}, "built": 0.0, "model": ""}


def index() -> dict[str, Any]:
    global _INDEX
    with _LOCK:
        if _INDEX is None:
            _INDEX = _read_index()
        return _INDEX


def _write_index() -> None:
    with _LOCK:
        held = json.dumps(index(), indent=1, default=str)
    try:
        path = index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(held, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def docs() -> list[dict[str, Any]]:
    """Every row on the shelf: documentation first, then newest read first.

    The console is a manuals console. Three hundred transcripts sorted above
    the eight manuals is a list nobody can use."""
    rows = list(index().get("docs", {}).values())
    rows.sort(key=lambda r: (not is_reference(str(r.get("slug") or "")),
                             r.get("state") != "ready",
                             -float(r.get("at") or 0)))
    return rows


def doc_row(slug: str) -> dict[str, Any] | None:
    return index().get("docs", {}).get(slug)


def doc_pages(slug: str) -> dict[str, Any] | None:
    """The read document. Small enough to parse on demand (a 543-page manual
    is about 1 MB); the vectors are what is kept out of json."""
    try:
        return json.loads((doc_dir(slug) / "doc.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- chunking ---------------------------------------------------------------


def page_chunks(text: str) -> list[str]:
    """One page cut into overlapping runs. Paragraph boundaries first, then
    sentences, then a hard cut — a wall of text still gets chunked."""
    text = " \n".join(text.split("\n"))
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        if len(para) <= CHUNK_CHARS:
            units.append(para)
            continue
        for sentence in re.split(r"(?<=[.!?:;])\s+", para):
            sentence = sentence.strip()
            while len(sentence) > CHUNK_CHARS:
                units.append(sentence[:CHUNK_CHARS - CHUNK_OVERLAP])
                sentence = sentence[CHUNK_CHARS - 2 * CHUNK_OVERLAP:]
            if sentence:
                units.append(sentence)

    out: list[str] = []
    buf = ""
    for unit in units:
        if buf and len(buf) + len(unit) + 1 > CHUNK_CHARS:
            out.append(buf)
            # Carry the tail of the chunk just closed into the next one, so a
            # fact that straddles the boundary is still whole somewhere. Only
            # when it FITS: prepending it unconditionally let a chunk run to
            # CHUNK_CHARS + CHUNK_OVERLAP, which is not what the dial says.
            tail = buf[-CHUNK_OVERLAP:] if CHUNK_OVERLAP else ""
            buf = ((tail + " " + unit).strip()
                   if tail and len(tail) + len(unit) + 1 <= CHUNK_CHARS
                   else unit)
        else:
            buf = f"{buf} {unit}".strip()
    if buf:
        out.append(buf)
    return [c for c in out if len(c) >= CHUNK_MIN] or (
        [units[0]] if units and len(units[0]) >= 12 else [])


def doc_chunks(doc: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    """Every chunk of a read document, carrying where it came from so an
    answer can cite a page instead of waving at the book."""
    rows: list[dict[str, Any]] = []
    title = str(doc.get("title") or "")
    for page in doc.get("pages") or []:
        heading = str(page.get("heading") or "")
        n = int(page.get("n") or 0)
        for body in page_chunks(str(page.get("text") or "")):
            # The heading rides along in the embedded text: "press shift" in
            # a chunk headed "step components" should not read the same as
            # the identical words under "mixer".
            lead = f"{title} — {heading}: " if heading else f"{title}: "
            rows.append({"slug": slug, "page": n, "heading": heading,
                         "text": body, "embed": (lead + body)[:2000]})
            if len(rows) >= PER_DOC_CHUNKS:
                return rows
    return rows


# --- the vector shards ------------------------------------------------------


def _numpy():
    import numpy as np           # noqa: PLC0415 - already a dependency
    return np


def shard_write(slug: str, rows: list[dict[str, Any]],
                vecs: list[list[float]]) -> int:
    """Write one document's memory. Both files or neither."""
    np = _numpy()
    keep = [(r, v) for r, v in zip(rows, vecs) if v]
    npy, jsl = shard_paths(slug)
    npy.parent.mkdir(parents=True, exist_ok=True)
    if not keep:
        shard_forget(slug)
        return 0
    mat = np.asarray([v for _r, v in keep], dtype=np.float32)
    tmp_n = npy.with_suffix(".npy.tmp")
    tmp_j = jsl.with_suffix(".jsonl.tmp")
    with open(tmp_n, "wb") as fh:
        np.save(fh, mat)
    with open(tmp_j, "w", encoding="utf-8") as fh:
        for r, _v in keep:
            fh.write(json.dumps({"page": r["page"], "heading": r["heading"],
                                 "text": r["text"]}) + "\n")
    tmp_n.replace(npy)
    tmp_j.replace(jsl)
    with _LOCK:
        _SHARDS.pop(slug, None)
        _MATS.pop(slug, None)
    return len(keep)


def shard_forget(slug: str) -> None:
    for path in shard_paths(slug):
        try:
            path.unlink()
        except OSError:
            pass
    with _LOCK:
        _SHARDS.pop(slug, None)
        _MATS.pop(slug, None)


def shard_matrix(slug: str) -> Any:
    """Just the vectors, memory-mapped. Costs almost nothing to open, which
    is the point: ranking touches EVERY document on the shelf, so it must not
    also parse every document's text to do it."""
    npy, _jsl = shard_paths(slug)
    try:
        stamp = npy.stat().st_mtime_ns
    except OSError:
        return None
    with _LOCK:
        held = _MATS.get(slug)
        if held and held[0] == stamp:
            return held[1]
    try:
        mat = _numpy().load(npy, mmap_mode="r")
    except (OSError, ValueError):
        return None
    with _LOCK:
        _MATS[slug] = (stamp, mat)
    return mat


def shard_rows(slug: str) -> list[dict[str, Any]] | None:
    """The chunk text beside those vectors. Parsed only for a document that
    actually produced a hit, and held under an LRU - this is the part that
    adds up to hundreds of MB across a shelf of transcripts."""
    _npy, jsl = shard_paths(slug)
    try:
        stamp = (jsl.stat().st_mtime_ns, jsl.stat().st_size)
    except OSError:
        return None
    with _LOCK:
        held = _SHARDS.get(slug)
        if held and held[0] == stamp:
            _SHARDS.move_to_end(slug)
            return held[1]
    try:
        rows = [json.loads(line) for line in
                jsl.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return None
    with _LOCK:
        _SHARDS[slug] = (stamp, rows)
        _SHARDS.move_to_end(slug)
        while len(_SHARDS) > SHARD_CACHE:
            _SHARDS.popitem(last=False)
    return rows


def shard_load(slug: str) -> tuple[Any, list[dict[str, Any]]] | None:
    """(matrix, rows) for one document, both halves, in step."""
    mat = shard_matrix(slug)
    if mat is None:
        return None
    rows = shard_rows(slug)
    if rows is None or len(rows) != mat.shape[0]:
        # The two files disagree: half a write, or a hand-edited shard. Trust
        # neither and let the next pass rebuild the document.
        return None
    return mat, rows


def vocab_write(slug: str, doc: dict[str, Any]) -> int:
    """Every distinct word in the document. A few hundred KB across the whole
    shelf, and it is what lets the shelf tell a question it can answer from a
    question that merely uses words every manual happens to contain."""
    seen: set[str] = set()
    for page in doc.get("pages") or []:
        for word in re.findall(r"[a-z0-9][a-z0-9\-]{2,}",
                               str(page.get("text") or "").lower()):
            seen.add(word)
            if len(seen) >= 20000:
                break
    try:
        vocab_path(slug).parent.mkdir(parents=True, exist_ok=True)
        vocab_path(slug).write_text(json.dumps(sorted(seen)), encoding="utf-8")
    except OSError:
        return 0
    return len(seen)


def _vocab_sets() -> dict[str, set[str]]:
    """Per-document word sets: what makes the lexical half cheap.

    Loaded INCREMENTALLY. Keying the whole thing on "which documents are
    ready" meant that during a bulk ingest - when that set changes every
    couple of minutes - every search re-read every vocabulary on the shelf.
    """
    ready = {slug for slug, row in index().get("docs", {}).items()
             if row.get("state") == "ready"}
    with _LOCK:
        held: dict[str, set[str]] = _VOCAB_CACHE.setdefault("words", {})
        missing = [slug for slug in ready if slug not in held]
        for slug in list(held):
            if slug not in ready:
                held.pop(slug, None)
    for slug in missing:
        try:
            words = set(json.loads(
                vocab_path(slug).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            words = set()
        with _LOCK:
            held[slug] = words
    with _LOCK:
        return dict(held)


def _document_frequency() -> tuple[dict[str, int], int]:
    """word -> how many ready documents contain it. Recounted only when the
    set of ready documents actually changes; the vocabularies underneath it
    are loaded incrementally."""
    vocabs = _vocab_sets()
    key = tuple(sorted(vocabs))
    with _LOCK:
        held = _DF_CACHE.get("held")
        if held and held[0] == key:
            return held[1], len(key)
    counts: dict[str, int] = {}
    for words in vocabs.values():
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    with _LOCK:
        _DF_CACHE["held"] = (key, counts, len(key))
    return counts, len(key)


def shelf_question(query: str) -> bool:
    """Is this a question the shelf could plausibly be about?

    The measured failure it exists to stop: "play some music" and "what time
    is it" both scored above 0.6 against the MPC Bible, because a book about
    music production really is about music and really does discuss time. The
    test that separates them is not similarity, it is SPECIFICITY - does the
    question use a word that only some of the shelf knows?
    """
    words = _words(query)
    if not words:
        return False
    if len(words) >= 3:
        return True
    counts, ready = _document_frequency()
    if not ready:
        return bool(words)
    common = max(1, ready // 2)
    return any(counts.get(word, 0) <= common for word in words)


# Words that name a KIND of document rather than a particular one. Two
# titles sharing only these are not the same book.
_TITLE_GENERIC = {"guide", "guidebook", "manual", "user", "users", "owner",
                  "owners", "reference", "book", "the", "and", "for", "with",
                  "edition", "version", "revision", "rev", "vol", "volume",
                  "pdf", "epub", "cheat", "sheet", "docs", "documentation",
                  "final", "draft", "copy", "new", "old", "full"}


def _title_marks(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9\-]{1,}", str(title or "").lower())
    return {w for w in words if w not in _TITLE_GENERIC and len(w) > 2}


def named_document(text: str) -> str:
    """The slug of a document the question NAMES, or "".

    Its whole reason to exist: "what does the MPC Bible say about chopping"
    was answered out of the gear corpus, because "MPC" is a device alias
    there - so the book the operator asked for by name never got a look. Two
    distinctive words of a title have to line up, so "chop it on the MPC"
    still belongs to the gear manuals and only "the MPC Bible" comes here.
    """
    said = set(re.findall(r"[a-z0-9][a-z0-9\-]{1,}", str(text or "").lower()))
    if len(said) < 2:
        return ""
    counts, ready = _document_frequency()
    common = max(1, ready // 2) if ready else 1
    best, score = "", 0
    for slug, row in index().get("docs", {}).items():
        if row.get("state") != "ready":
            continue
        marks = _title_marks(row.get("title") or "") | _title_marks(
            str(row.get("name") or "").rsplit(".", 1)[0])
        hit = marks & said
        if len(hit) >= 2 and len(hit) > score:
            best, score = slug, len(hit)
        elif len(marks) == 1 and len(hit) == 1 and score < 1:
            # A title whose whole distinctive vocabulary is one word - "the
            # CyDrums manual" - is named by that word alone. Only when the
            # word is genuinely that document's: a shelf holding "Music.md"
            # must not answer every question that says "music".
            word = next(iter(hit))
            if len(word) >= 4 and counts.get(word, 0) <= common:
                best, score = slug, 1
    return best


def is_reference(slug: str) -> bool:
    """Is this document DOCUMENTATION, or is it a record of somebody talking?

    It decides which documents are allowed to open the shelf, and it is not a
    hack - it is the difference between the two corpora on it. A manual is
    written to be consulted. A transcript is a record of speech, and a shelf
    holding hundreds of hours of speech is plausibly "about" any conversational
    question you can ask it: measured, "write me a poem about rain" and "sing
    me a song about the sea" beat "what are keygroup programs" on every score
    there is, purely on the transcripts. So a transcript can SUPPORT an answer
    and can be searched directly, but it may not decide that an ordinary
    question was a documentation question.
    """
    if not _REFERENCE:
        return True                    # nothing declared: the whole shelf is
    folder = str((doc_row(slug) or {}).get("folder") or "").rstrip("/")
    return any(folder == ref or folder.startswith(ref + "/")
               for ref in _REFERENCE)


def chunk_total() -> int:
    return sum(int(r.get("chunks") or 0) for r in index().get("docs", {}).values())


# --- reading the shelf ------------------------------------------------------


def scan(folders: Iterable[str | Path]) -> dict[str, dict[str, Any]]:
    """What is on the watched shelves right now: source path -> stat.

    Sync and wrapped by the caller in a thread — a folder can be a CIFS mount
    over Wi-Fi and `iterdir` on a sleeping NAS is not fast (#1156).
    """
    found: dict[str, dict[str, Any]] = {}
    for folder in folders:
        if not str(folder or "").strip():
            continue
        for path in extract.scan_folder(folder):
            try:
                st = path.stat()
            except OSError:
                continue
            found[str(path)] = {"path": str(path), "size": int(st.st_size),
                                "mtime": int(st.st_mtime),
                                "folder": str(folder),
                                "name": path.name}
    return found


# #1255: how long a FAILED read waits before it is tried again. A
# skipped one is never retried at all - see below.
RETRY_FAILED_REST = 3600.0


def _fresh(row: dict[str, Any], seen: dict[str, Any]) -> bool:
    """Is this row settled for the file on disk right now?

    #1255: it used to accept only `ready`, so a SKIPPED document came
    back in `todo` on every single pass and was unzipped, parsed and
    skipped again for ever - a subprocess-and-parse loop with no rest
    in it. Measured on the live station: the same archive read
    continuously for hours, /healthz at a p90 of eleven to twenty
    seconds, and the host watchdog restarting the container seven times
    an hour. ingest_one's own docstring names that exact cost.

    A `skipped` verdict is a fact about the CONTENT - "every document
    inside is already on the shelf" - and re-reading the same bytes
    cannot change it, so the row is settled until size or mtime moves,
    which the two tests below already watch.

    `failed` may be transient, so it is retried, but on a clock rather
    than on every pass. `queued` is left alone: the embedder being cold
    is meant to be picked up next time."""
    if (int(row.get("size") or -1) != seen["size"]
            or int(row.get("mtime") or -1) != seen["mtime"]):
        return False                     # the file itself changed
    state = str(row.get("state") or "")
    if state in ("ready", "skipped"):
        return True
    if state == "failed":
        return time.time() - float(row.get("at") or 0) < RETRY_FAILED_REST
    return False


def plan(folders: Iterable[str | Path]) -> dict[str, Any]:
    """Reconcile the shelf with the index: what to read, what to forget."""
    seen = scan(folders)
    with _LOCK:
        held = index()["docs"]
        by_path = {r.get("path"): (slug, r) for slug, r in held.items()}
        todo: list[str] = []
        for path, stat in seen.items():
            slug, row = by_path.get(path, ("", None))
            if row is None:
                slug = slug_for(path)
                row = {"slug": slug, "path": path, "name": stat["name"],
                       "folder": stat["folder"],
                       "title": extract.nice_title(path),
                       "kind": extract.doc_kind(path), "state": "queued",
                       "size": stat["size"], "mtime": stat["mtime"],
                       "pages": 0, "chunks": 0, "chars": 0, "at": 0.0,
                       "note": "", "sha": ""}
                held[slug] = row
                todo.append(slug)
                continue
            if not _fresh(row, stat):
                row.update({"size": stat["size"], "mtime": stat["mtime"],
                            "state": "queued", "note": ""})
                todo.append(slug)
        gone = [slug for slug, row in held.items()
                if row.get("path") not in seen]
    return {"todo": todo, "gone": gone, "seen": len(seen)}


def forget(slug: str) -> None:
    """Take a document off the shelf entirely."""
    shard_forget(slug)
    folder = doc_dir(slug)
    try:
        for path in sorted(folder.rglob("*"), reverse=True):
            try:
                path.unlink() if path.is_file() else path.rmdir()
            except OSError:
                pass
        folder.rmdir()
    except OSError:
        pass
    try:
        vocab_path(slug).unlink()
    except OSError:
        pass
    with _LOCK:
        index()["docs"].pop(slug, None)
        _DF_CACHE.clear()
        _VOCAB_CACHE.get("words", {}).pop(slug, None)


# --- ingest -----------------------------------------------------------------


def _note(slug: str, phase: str, line: str = "") -> None:
    row = doc_row(slug) or {}
    with _LOCK:
        _WORK["doc"] = row.get("title") or slug
        _WORK["phase"] = phase
        if line:
            _WORK["last"] = line
    if line:
        _LOG(line)


async def ingest_one(slug: str) -> dict[str, Any]:
    """Read one document, chunk it, embed it, and put it on the shelf.

    Every heavy step is on a thread: extraction is subprocess-and-parse work
    that would otherwise hold the loop long enough for the host watchdog to
    restart the container (24 s).
    """
    row = doc_row(slug)
    if row is None:
        return {"slug": slug, "state": "gone"}
    path = Path(row.get("path") or "")
    row["state"] = "reading"
    _note(slug, "reading", f"reading {row.get('name')}")

    skip = {str(r.get("sha") or "") for s, r in index()["docs"].items()
            if s != slug and r.get("sha") and r.get("state") == "ready"}
    out = doc_dir(slug)
    try:
        got = await asyncio.to_thread(extract.read_document, path, out, skip)
        sha = await asyncio.to_thread(extract.file_sha, path)
    except extract.ExtractError as exc:
        row.update({"state": "skipped", "note": str(exc), "at": time.time()})
        shard_forget(slug)
        _note(slug, "", f"{row.get('name')}: {exc}")
        await asyncio.to_thread(_write_index)
        return row
    except Exception as exc:  # noqa: BLE001 - one bad book, not a dead shelf
        row.update({"state": "failed", "note": f"{type(exc).__name__}: {exc}",
                    "at": time.time()})
        _note(slug, "", f"{row.get('name')} failed: {exc}")
        await asyncio.to_thread(_write_index)
        return row

    doc = {"slug": slug, "title": got["title"], "kind": got["kind"],
           "path": str(path), "pages": got["pages"], "figures": got["figures"],
           "reader": got.get("reader", ""), "built": time.time()}
    try:
        out.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            (out / "doc.json").write_text,
            json.dumps(doc, default=str), "utf-8")
    except OSError as exc:
        row.update({"state": "failed", "note": f"could not be saved: {exc}"})
        await asyncio.to_thread(_write_index)
        return row

    await asyncio.to_thread(vocab_write, slug, doc)
    rows = doc_chunks(doc, slug)
    row.update({"state": "embedding", "title": got["title"],
                "kind": got["kind"], "sha": sha, "figures": got["figures"],
                "pages": len(doc["pages"]), "chars": got["chars"],
                "thin": bool(got.get("thin")), "reader": got.get("reader", ""),
                "chunks": 0, "note": ""})
    _note(slug, "embedding",
          f"{row['title']}: {row['pages']} pages, {len(rows)} chunks to learn")

    vecs: list[list[float]] = []
    for i in range(0, len(rows), EMBED_BATCH):
        batch = rows[i:i + EMBED_BATCH]
        got_vecs = await _EMBED([r["embed"] for r in batch]) if _EMBED else []
        if len(got_vecs) != len(batch):
            # The embedder is cold or over its lane. Keep what we have, mark
            # the book unfinished, and let the next pass pick it up again.
            row.update({"state": "queued",
                        "note": "the embedder did not answer; will retry"})
            _note(slug, "", f"{row['title']}: embedder cold, will retry")
            await asyncio.to_thread(_write_index)
            return row
        vecs.extend(got_vecs)
        with _LOCK:
            _WORK["done"] = i + len(batch)
            _WORK["total"] = len(rows)
        # The box runs one Ollama lane, shared with the show. Give it back
        # between batches, and give it back for longer while a line is being
        # written or rendered (#1158).
        await asyncio.sleep(BUSY_SLEEP if (not _BURST and _busy()) else EASY_SLEEP)

    kept = await asyncio.to_thread(shard_write, slug, rows, vecs)
    row.update({"state": "ready", "chunks": kept, "at": time.time()})
    _note(slug, "", f"{row['title']}: {kept} chunks on the shelf")
    await asyncio.to_thread(_write_index)
    return row


def _busy() -> bool:
    try:
        return bool(_BUSY())
    except Exception:  # noqa: BLE001
        return False


async def ingest_pass(folders: Iterable[str | Path],
                      burst: bool = False) -> dict[str, Any]:
    """One reconciliation of the shelf. Returns what it did."""
    global _BURST
    folders = list(folders)
    todo_plan = await asyncio.to_thread(plan, folders)
    for slug in todo_plan["gone"]:
        forget(slug)
    if todo_plan["gone"]:
        _LOG(f"{len(todo_plan['gone'])} taken off the shelf")

    over = chunk_total() > VEC_MAX
    read = 0
    with _LOCK:
        _WORK.update({"running": bool(todo_plan["todo"]), "burst": bool(burst),
                      "started": time.time(), "pass": _WORK.get("pass", 0) + 1,
                      "done": 0, "total": 0})
    _BURST = bool(burst)
    try:
        for slug in todo_plan["todo"]:
            if over:
                row = doc_row(slug)
                if row is not None:
                    row.update({"state": "skipped",
                                "note": "the shelf is full "
                                        f"({chunk_total()} chunks)"})
                continue
            await ingest_one(slug)
            read += 1
            over = chunk_total() > VEC_MAX
    finally:
        _BURST = False
        with _LOCK:
            _WORK.update({"running": False, "doc": "", "phase": "",
                          "finished": time.time()})
        await asyncio.to_thread(_write_index)
    if todo_plan["gone"] or read:
        await asyncio.to_thread(_write_index)
    return {"read": read, "forgotten": len(todo_plan["gone"]),
            "seen": todo_plan["seen"], "chunks": chunk_total()}


def wake() -> None:
    """Ask the clock to come round now rather than at its next turn."""
    global _BURST
    _BURST = True
    if _WAKE is not None:
        try:
            _WAKE.set()
        except RuntimeError:
            pass


async def ingest_clock(folders: Callable[[], list[str]],
                       enabled: Callable[[], bool] | None = None) -> None:
    """The background service (#1158).

    Deliberately NOT tied to the show: a document dropped in while the radio
    is off must still be assimilated, because that is exactly when somebody
    is sitting there asking questions about it.
    """
    global _WAKE
    _WAKE = asyncio.Event()
    await asyncio.sleep(8)              # let the app finish standing up
    while True:
        try:
            if enabled is None or enabled():
                await ingest_pass(folders(), burst=_BURST)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the shelf must never be fatal
            _LOG(f"the shelf stumbled: {type(exc).__name__}: {exc}")
        try:
            _WAKE.clear()
            await asyncio.wait_for(_WAKE.wait(), timeout=IDLE_SECONDS)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            raise


# --- recall -----------------------------------------------------------------


def _words(query: str) -> list[str]:
    if _TOPIC_WORDS is not None:
        try:
            got = [w for w in _TOPIC_WORDS(query) if len(w) > 2]
            if got:
                return got[:12]
        except Exception:  # noqa: BLE001
            pass
    # Only genuine function words. Nothing that MEANS something on a manual
    # page ("play", "show", "set", "hold", "step", "time") belongs here -
    # they are controls, not noise. This list is the fallback; the app
    # injects the station's own topic_words, which knows more.
    stop = {"the", "and", "for", "how", "what", "with", "does", "did", "you",
            "your", "can", "was", "are", "this", "that", "from", "when",
            "where", "why", "who", "its", "his", "her", "not", "but", "all",
            "any", "say", "says", "tell", "about", "into", "onto", "there",
            "some", "each", "every", "other", "such", "than", "then", "them",
            "they", "these", "those", "been", "have", "has", "had", "will",
            "would", "could", "should", "must", "may", "might", "very",
            "much", "many", "most", "also", "only", "even", "still", "again",
            "once", "here", "now", "just", "please", "want", "need", "let",
            "like", "know", "think", "really", "actually", "something",
            "anything", "everything", "across", "over", "under", "while"}
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", query.lower())
            if w not in stop][:12]


def _vector_rows(q: Any, want: int,
                 only: set[str] | None = None) -> list[dict[str, Any]]:
    np = _numpy()
    picks: list[tuple[float, str, int]] = []
    for row in index().get("docs", {}).values():
        if row.get("state") != "ready" or not row.get("chunks"):
            continue
        slug = row["slug"]
        if only is not None and slug not in only:
            continue
        mat = shard_matrix(slug)
        if mat is None:
            continue
        try:
            scores = np.asarray(mat) @ q
        except ValueError:
            continue            # the embedder changed dimension under us
        for i in np.argsort(-scores)[:want]:
            picks.append((float(scores[int(i)]), slug, int(i)))
    picks.sort(key=lambda p: -p[0])

    out: list[dict[str, Any]] = []
    for score, slug, i in picks[:max(want * 4, 24)]:
        rows = shard_rows(slug)         # only now is any text parsed
        if rows is None or i >= len(rows):
            continue
        row = index()["docs"][slug]
        out.append({"slug": slug, "title": row.get("title") or slug,
                    "page": rows[i].get("page"),
                    "heading": rows[i].get("heading") or "",
                    "text": rows[i].get("text") or "",
                    "cosine": score})
    return out


def _word_rows(query: str, want: int,
               only: set[str] | None = None) -> list[dict[str, Any]]:
    """The lexical half. A model number, a key combination or a menu name is
    matched by the letters, not by the meaning - and that is most of what
    somebody asks a manual.

    It scores the CHUNKS, not the pages: they are already in memory beside
    the vectors, so a search reads no document files at all. Scoring pages
    meant opening every doc.json on the shelf on every single query, which
    was fine for nine manuals and ruinous at three hundred documents.
    """
    words = _words(query)
    if not words or _PAGE_SCORE is None:
        return []
    wanted = set(words)
    vocabs = _vocab_sets()
    ranked: list[tuple[int, str]] = []
    for slug, row in index().get("docs", {}).items():
        if row.get("state") != "ready" or not row.get("chunks"):
            continue
        if only is not None and slug not in only:
            continue
        vocab = vocabs.get(slug)
        overlap = len(wanted & vocab) if vocab else 1
        if not overlap:
            continue          # this document has never used any of the words
        ranked.append((overlap, slug))
    ranked.sort(key=lambda pair: -pair[0])

    out: list[dict[str, Any]] = []
    for _overlap, slug in ranked[:WORD_DOCS]:
        rows = shard_rows(slug)
        if rows is None:
            continue
        row = index()["docs"][slug]
        best: list[tuple[float, dict[str, Any]]] = []
        for chunk in rows:
            try:
                score = float(_PAGE_SCORE(chunk, words))
            except Exception:  # noqa: BLE001
                score = 0.0
            if score > 0:
                best.append((score, chunk))
        best.sort(key=lambda pair: -pair[0])
        for score, chunk in best[:want]:
            out.append({"slug": slug,
                        "title": row.get("title") or slug,
                        "page": int(chunk.get("page") or 0),
                        "heading": chunk.get("heading") or "",
                        "text": chunk.get("text") or "",
                        "words": score})
    out.sort(key=lambda r: -r["words"])
    return out


async def search(query: str, k: int = 6, per_doc: int = 2,
                 gate: bool = True) -> list[dict[str, Any]]:
    """The k passages most likely to answer `query`, best first.

    Hybrid on purpose. The vectors find the passage that MEANS the right
    thing; the words find the passage that SAYS "shift + step". Merged by
    reciprocal-rank fusion so neither half can drown the other, and capped
    per document so one thick manual cannot fill the answer on its own.

    Two phases, and the reason is cost. Only documentation may open the shelf
    (see is_reference), so the first phase reads ONLY documentation and asks
    whether this was a question for the shelf at all. Most questions are not,
    and they stop there having touched eight manuals rather than three hundred
    and thirty documents. The rest of the shelf is read only once a real
    documentation question has already opened it, so that the records which
    touch on the same subject can ride along.
    """
    query = " ".join(str(query or "").split())[:600]
    if not query or not index().get("docs"):
        return []
    # `gate` is on for the chat road and off for the console's search box:
    # somebody typing into the shelf's own search means it.
    if gate and not await asyncio.to_thread(shelf_question, query):
        return []

    ready = [slug for slug, row in index().get("docs", {}).items()
             if row.get("state") == "ready" and row.get("chunks")]
    named = named_document(query)
    opening = {slug for slug in ready if is_reference(slug) or slug == named}
    rest = {slug for slug in ready if slug not in opening}

    q = None
    if _EMBED is not None:
        qv = await _EMBED([query])
        if qv:
            np = _numpy()
            q = np.asarray(qv[0], dtype=np.float32)

    merged: dict[tuple[str, int], dict[str, Any]] = {}

    def fold(rows: list[dict[str, Any]], field: str) -> None:
        """Reciprocal-rank fusion. One contribution per key PER LIST - the
        best rank it reached - never one per row.

        Summing every rank a key occupied scored documents on how many CHUNKS
        they had rather than on how well they matched: a 44-chapter EPUB whose
        every chapter is one "page" folds twenty-five chunks into a single key
        and collected twenty-five contributions for them. Measured, that put a
        transcript matching a question at cosine 0.39 above the manual that
        matched the same question at 0.90.
        """
        seen: set[tuple[str, int]] = set()
        for rank, row in enumerate(rows):
            key = (row["slug"], int(row.get("page") or 0))
            held = merged.get(key)
            if held is None:
                held = dict(row)
                held["score"] = 0.0
                merged[key] = held
            elif len(row.get("text") or "") > len(held.get("text") or ""):
                held["text"] = row["text"]
            # keep the strongest evidence this key showed on this road
            if float(row.get(field, 0.0) or 0) >= float(held.get(field, 0.0) or 0):
                held[field] = row.get(field, 0.0)
            if key in seen:
                continue
            seen.add(key)
            held["score"] = float(held["score"]) + 1.0 / (RRF_K + rank + 1)

    async def read(slugs: set[str]) -> None:
        if not slugs:
            return
        if q is not None:
            fold(await asyncio.to_thread(_vector_rows, q, max(k, 8), slugs),
                 "cosine")
        fold(await asyncio.to_thread(_word_rows, query, max(k, 8), slugs),
             "words")

    await read(opening)

    # Is the shelf open at all? A page the vectors merely tolerated and the
    # words barely touched is not an answer, it is the nearest thing on a
    # shelf that had nothing.
    top_cos = max((float(r.get("cosine") or 0) for r in merged.values()),
                  default=0.0)
    top_words = max((float(r.get("words") or 0) for r in merged.values()),
                    default=0.0)
    fits = top_cos >= SEARCH_FLOOR and top_words >= WORD_FLOOR
    exact = top_words >= WORD_STRONG and top_cos >= WORD_COSINE
    if gate and not (fits or exact):
        return []

    await read(rest)

    for row in merged.values():
        if is_reference(row["slug"]) or row["slug"] == named:
            row["score"] = float(row["score"]) + REFERENCE_BONUS / (RRF_K + 1)
            row["reference"] = True
    rows = sorted(merged.values(), key=lambda r: -r["score"])
    rows = [r for r in rows
            if float(r.get("cosine") or 0) >= KEEP_FLOOR
            or float(r.get("words") or 0) >= WORD_KEEP]

    out: list[dict[str, Any]] = []
    per: dict[str, int] = {}
    for row in rows:
        if per.get(row["slug"], 0) >= per_doc:
            continue
        per[row["slug"]] = per.get(row["slug"], 0) + 1
        row["why"] = ("both" if row.get("cosine") and row.get("words")
                      else ("meaning" if row.get("cosine") else "words"))
        out.append(row)
        if len(out) >= k:
            break
    return out


def best_cosine(rows: list[dict[str, Any]]) -> float:
    return max((float(r.get("cosine") or 0) for r in rows), default=0.0)


def page_word(kind: str, plural: bool = False) -> str:
    """What to call a numbered piece of this document out loud. An epub has
    chapters, not pages, and citing "page 23" of a 44-page book that is 700
    pages long in print reads as a mistake."""
    word = "chapter" if str(kind or "") in {"epub", "zip"} else "page"
    return word + "s" if plural else word


# --- what the console reads -------------------------------------------------


def stats() -> dict[str, Any]:
    rows = docs()
    states: dict[str, int] = {}
    for row in rows:
        states[str(row.get("state") or "?")] = states.get(
            str(row.get("state") or "?"), 0) + 1
    with _LOCK:
        work = dict(_WORK)
    return {"documents": len(rows), "chunks": chunk_total(),
            "pages": sum(int(r.get("pages") or 0) for r in rows),
            "ready": states.get("ready", 0), "states": states,
            "capacity": VEC_MAX, "work": work,
            "folders_seen": sorted({str(r.get("folder") or "") for r in rows}),
            "at": time.time()}


def section(slug: str, page_n: int, question: str = "",
            budget: int = 9000) -> str:
    """The text the doc chat reads: the named page and its neighbours, so an
    answer has the run-up and the follow-through, not one orphan page."""
    doc = doc_pages(slug)
    if not doc:
        return ""
    pages = doc.get("pages") or []
    if not pages:
        return ""
    words = _words(question) if question else []
    chosen: list[dict[str, Any]] = []
    if words and _PAGE_SCORE is not None:
        scored = []
        for page in pages:
            try:
                score = float(_PAGE_SCORE(page, words))
            except Exception:  # noqa: BLE001
                score = 0.0
            if score > 0:
                scored.append((score, page))
        scored.sort(key=lambda pair: -pair[0])
        chosen = [page for _s, page in scored[:6]]
    here = next((p for p in pages if int(p.get("n") or 0) == int(page_n)), None)
    if here is not None:
        near = [p for p in pages
                if abs(int(p.get("n") or 0) - int(page_n)) <= 1]
        for page in [here] + near:
            if page not in chosen:
                chosen.append(page)
    if not chosen:
        chosen = pages[:3]
    chosen.sort(key=lambda p: int(p.get("n") or 0))
    blocks: list[str] = []
    left = int(budget)
    for page in chosen:
        body = " ".join(str(page.get("text") or "").split())
        if not body:
            continue
        body = body[:max(400, left // max(1, len(chosen)))]
        label = f"page {page.get('n')}"
        if page.get("heading"):
            label += f" - {page.get('heading')}"
        blocks.append(f"[{label}]\n{body}")
        left -= len(body)
        if left <= 0:
            break
    return "\n\n".join(blocks)


__all__ = ["configure", "docs", "doc_row", "doc_pages", "doc_dir", "forget",
           "index", "ingest_clock", "ingest_one", "ingest_pass", "page_chunks",
           "doc_chunks", "plan", "scan", "search", "section", "shard_load",
           "shard_write", "slug_for", "stats", "wake", "chunk_total",
           "best_cosine", "page_word", "shelf_question", "vocab_write",
           "is_reference",
           "named_document",
           "VEC_MAX", "SEARCH_FLOOR"]
