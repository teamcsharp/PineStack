"""The SFX Guy's vector section, wired to the station (docs/SFX_vector_reuse.md).

sfx_vectors.py is the section and knows nothing of the station. This module
is what the station adds: the keeper that maintains it (the SFX Guy
"maintaining, refining, expanding on, scanning, analyzing and cultivating"),
and the doors outside applications come through.

    keeper, every 30 s, on its own worker thread and never the loop:
      1. scan  - new and changed rows of the clip book (data/sfx_clips.db:
                 path, name, transcript, thumbnail tags) into the section
      2. air   - what he played (data/sfx_history.jsonl) -> aired counts
      3. speak - his dialogue: the speech bank's recorded takes and the quip
                 shelves, each tied to its audio path
      4. embed - anchors, then clips (aired first, then the wordy ones), then
                 dialogue, through the station's own embedder
                 (_embed_texts, nomic-embed-text on Ollama) - ONLY while the
                 writing desk is idle (_OLLAMA_GATE unlocked): he never takes
                 the model from a round being written
      5. tag   - embedded clips against the facet anchors (pure arithmetic)

    doors (read key for reads, the admin key for writes):
      GET  /api/sfx/vectors/status            counts, backlog, last tick
      GET  /api/sfx/vectors/manifest          schema, embed model, roots, counts
      GET  /api/sfx/vectors/facets            the categorisation (anchors per facet)
      PUT  /api/sfx/vectors/facets/{facet}    replace a facet's anchors; clips are re-tagged
      GET  /api/sfx/vectors/query?q=&facets=&video=&k=&max_seconds=
                                              recommendations with paths and why
      GET  /api/sfx/vectors/clip/{sid}        one clip, its tags and its dialogue
      POST /api/sfx/vectors/backup {label?}   one compressed tarball (+ the crystals)
      GET  /api/sfx/vectors/backups           the tarballs on hand
      GET  /api/sfx/vectors/backup/{name}     download one
      POST /api/sfx/vectors/restore {file, roots?, into?}
                                              unpack a backup beside the live section

Every hook is guarded: an install that fails leaves the station exactly as
it was, and the keeper's faults are counted on the status, never raised
into the air.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import sfx_vectors

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sfx-vectors")
TICK = 30.0
EMBED_BATCH = 48
EMBED_BATCHES_PER_TICK = 4
TAG_PER_TICK = 3000
SYNC_PER_TICK = 4000


class _Host:
    def __init__(self, namespace):
        object.__setattr__(self, "namespace", namespace)

    def __getattr__(self, name):
        try:
            return self.namespace[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def get(self, name, default=None):
        return self.namespace.get(name, default)


class SfxVectorRuntime:
    def __init__(self, host):
        self.host = host
        data = host.data_path
        voice = host.get("VOICE_MEDIA_DIR")
        roots = {"samples": "/samples", "comfy": "/comfy-output", "made": str(data("sfx")),
                 "voice": str(voice) if voice else str(data("voice_media")), "app": "/app"}
        self.store = sfx_vectors.Store(data("sfx_vectors"), roots=roots,
                                       embed_model=str(host.get("EMBED_MODEL") or sfx_vectors.EMBED_MODEL))
        self.backups = Path(data("sfx_vectors_backups"))
        self.lock = threading.Lock()
        self.metrics = {"ticks": 0, "failures": 0, "last_failure": "", "last_tick": 0.0, "tick_ms": 0.0,
                        "synced": 0, "aired_noted": 0, "dialogue_synced": 0, "embedded_clips": 0,
                        "embedded_dialogue": 0, "embedded_anchors": 0, "tagged": 0, "embed_skipped_busy": 0,
                        "queries": 0, "backups": 0, "started": time.time()}
        self.progress = {"book_rowid": 0, "book_since": 0.0, "history_offset": 0, "dialogue_at": 0.0}
        self._progress_path = self.store.root / "keeper.json"
        try:
            if self._progress_path.is_file():
                self.progress.update(json.loads(self._progress_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass

    # -- plumbing ----------------------------------------------------------------
    def fail(self, where, exc):
        with self.lock:
            self.metrics["failures"] += 1
            self.metrics["last_failure"] = "%s: %s: %s" % (where, type(exc).__name__, str(exc)[:200])
        try:
            self.host.pipeline_log("sfx", "the SFX Guy's vector keeper stumbled at %s" % where,
                                   extra="%s: %s" % (type(exc).__name__, exc))
        except Exception:  # noqa: BLE001
            pass

    async def run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(_POOL, lambda: fn(*args))

    def _save_progress(self):
        try:
            tmp = self._progress_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.progress), encoding="utf-8")
            tmp.replace(self._progress_path)
        except Exception:  # noqa: BLE001
            pass

    def desk_busy(self) -> bool:
        """The writing desk holds the model: the keeper embeds nothing."""
        gate = self.host.get("_OLLAMA_GATE")
        try:
            return bool(gate is not None and gate.locked())
        except Exception:  # noqa: BLE001
            return False

    async def embed(self, texts):
        fn = self.host.get("_embed_texts")
        if fn is None or not texts:
            return []
        try:
            got = await fn(list(texts))
            return list(got or [])
        except Exception as exc:  # noqa: BLE001
            self.fail("embed", exc)
            return []

    # -- the keeper's steps (worker thread) ----------------------------------------------
    def sync_clips(self) -> int:
        book = self.host.get("SFX_DB_PATH")
        if not book or not Path(str(book)).is_file():
            return 0
        con = sqlite3.connect("file:%s?mode=ro" % str(book), uri=True, check_same_thread=False)
        try:
            since = float(self.progress.get("book_since") or 0)
            rows = con.execute("""select rowid, path, sid, name, folder, video, seconds, said, seen_desc, mtime
                                  from clips where playable=1 and (rowid > ? or coalesce(said_at,0) > ? or coalesce(seen_desc_at,0) > ?)
                                  order by rowid limit ?""",
                               (int(self.progress.get("book_rowid") or 0), since, since, SYNC_PER_TICK)).fetchall()
        finally:
            con.close()
        if not rows:
            return 0
        got = self.store.upsert_clips([{"sid": r[2] or hashlib.sha1(str(r[1]).encode("utf-8")).hexdigest()[:16],
                                        "path": r[1], "name": r[3], "folder": r[4], "video": r[5], "seconds": r[6],
                                        "said": r[7], "seen_desc": r[8], "mtime": r[9]} for r in rows])
        self.progress["book_rowid"] = max(int(self.progress.get("book_rowid") or 0), max(int(r[0]) for r in rows))
        if len(rows) < SYNC_PER_TICK:
            self.progress["book_since"] = time.time() - 5.0
        self._save_progress()
        return got

    def sync_history(self) -> int:
        path = self.host.get("SFX_HISTORY_ARCHIVE_PATH")
        if not path or not Path(str(path)).is_file():
            return 0
        p = Path(str(path))
        size = p.stat().st_size
        offset = int(self.progress.get("history_offset") or 0)
        if size < offset:
            offset = 0
        if size == offset:
            return 0
        pairs = []
        with p.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read(2_000_000)
            lines = chunk.split(b"\n")
            complete = lines[:-1] if not chunk.endswith(b"\n") else lines
            consumed = sum(len(x) + 1 for x in complete)
            for raw in complete:
                try:
                    d = json.loads(raw.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                sid = str(d.get("id") or "")
                if sid:
                    pairs.append((sid, float(d.get("ts") or 0)))
        self.progress["history_offset"] = offset + consumed
        self._save_progress()
        return self.store.note_aired(pairs) if pairs else 0

    def sync_dialogue(self) -> int:
        rows = []
        bank = self.host.get("SFXGUY_SPEECH_PATH") or self.host.data_path("sfxguy_speech.json")
        voice_dir = self.host.get("VOICE_MEDIA_DIR")
        try:
            book = json.loads(Path(str(bank)).read_text(encoding="utf-8")) if Path(str(bank)).is_file() else {}
        except Exception:  # noqa: BLE001
            book = {}
        items = book.values() if isinstance(book, dict) else (book if isinstance(book, list) else [])
        for r in items:
            if not isinstance(r, dict) or not r.get("text"):
                continue
            clip = r.get("clip") if isinstance(r.get("clip"), dict) else {}
            media = str(clip.get("path") or "")
            path = ""
            if media and voice_dir:
                path = str(Path(str(voice_dir)) / media.rsplit("/", 1)[-1])
            rows.append({"id": "take:" + str(r.get("id") or r.get("key") or hashlib.sha1(str(r["text"]).encode()).hexdigest()[:16]),
                         "kind": "take", "who": r.get("who") or "drop", "voice": r.get("voice") or "",
                         "text": r.get("text"), "about": r.get("about") or r.get("context") or "",
                         "path": path, "at": r.get("at") or 0})
        quips = self.host.get("sfxguy_quips")
        if callable(quips):
            try:
                for q in quips() or []:
                    rows.append({"id": "quip:" + hashlib.sha1(str(q).encode("utf-8")).hexdigest()[:16], "kind": "quip",
                                 "who": "drop", "text": str(q), "at": 0})
            except Exception:  # noqa: BLE001
                pass
        if not rows:
            return 0
        return self.store.upsert_dialogue(rows)

    # -- the keeper ----------------------------------------------------------------------
    async def tick(self):
        started = time.perf_counter()
        try:
            n = await self.run(self.sync_clips)
            a = await self.run(self.sync_history)
            d = await self.run(self.sync_dialogue) if time.time() - float(self.progress.get("dialogue_at") or 0) > 600 else 0
            if d:
                self.progress["dialogue_at"] = time.time()
            with self.lock:
                self.metrics["synced"] += n
                self.metrics["aired_noted"] += a
                self.metrics["dialogue_synced"] += d
            if self.desk_busy():
                with self.lock:
                    self.metrics["embed_skipped_busy"] += 1
            else:
                todo = await self.run(self.store.anchors_to_embed)
                if todo:
                    vecs = await self.embed([t[2] for t in todo])
                    if vecs:
                        k = await self.run(self.store.put_anchor_vectors, todo, vecs)
                        with self.lock:
                            self.metrics["embedded_anchors"] += k
                for _ in range(EMBED_BATCHES_PER_TICK):
                    if self.desk_busy():
                        break
                    batch = await self.run(self.store.clips_to_embed, EMBED_BATCH)
                    if not batch:
                        break
                    vecs = await self.embed([self.store.clip_text(r) for r in batch])
                    if not vecs:
                        break
                    k = await self.run(self.store.put_clip_vectors, [r["sid"] for r in batch], vecs)
                    with self.lock:
                        self.metrics["embedded_clips"] += k
                    await asyncio.sleep(0)
                dbatch = await self.run(self.store.dialogue_to_embed, EMBED_BATCH)
                if dbatch and not self.desk_busy():
                    vecs = await self.embed([(r["text"] + (" | " + r["about"] if r.get("about") else "")) for r in dbatch])
                    if vecs:
                        k = await self.run(self.store.put_dialogue_vectors, [r["id"] for r in dbatch], vecs)
                        with self.lock:
                            self.metrics["embedded_dialogue"] += k
            t = await self.run(self.store.tag_clips, TAG_PER_TICK)
            with self.lock:
                self.metrics["tagged"] += t
                self.metrics["ticks"] += 1
                self.metrics["last_tick"] = time.time()
                self.metrics["tick_ms"] = round((time.perf_counter() - started) * 1000, 1)
        except Exception as exc:  # noqa: BLE001
            self.fail("tick", exc)

    # -- backups ---------------------------------------------------------------------------
    def crystal_files(self) -> dict[str, bytes]:
        """The crystals as the station's own export road writes them (one
        JSON per crystal: every chunk, its vector, its votes, the tint)."""
        out: dict[str, bytes] = {}
        crystals_read = self.host.get("crystals_read")
        load = self.host.get("_load_vectors")
        mind_id = self.host.get("mind_id")
        votes_read = self.host.get("votes_read")
        chunk_key = self.host.get("chunk_key")
        if not (callable(crystals_read) and callable(load) and callable(mind_id)):
            return out
        try:
            crystals = crystals_read() or {}
            votes = votes_read() if callable(votes_read) else {}
        except Exception as exc:  # noqa: BLE001
            self.fail("crystals", exc)
            return out
        for cid, c in crystals.items():
            chunks = []
            for rid in c.get("minds") or []:
                try:
                    store = load(mind_id(rid))
                except Exception:  # noqa: BLE001
                    continue
                for ch in store.get("chunks") or []:
                    key = chunk_key(ch.get("file"), ch.get("text")) if callable(chunk_key) else ""
                    chunks.append({"mind": rid, "file": ch.get("file"), "text": ch.get("text"), "vec": ch.get("vec"),
                                   "votes": (votes.get(key) if key else None) or {}})
            body = {"crystal": cid, "name": c.get("name"), "tint": c.get("tint"), "minds": c.get("minds"),
                    "embed_model": self.store.manifest.get("embed_model"), "exported": int(time.time()), "chunks": chunks}
            out["crystals/%s.json" % str(cid).replace("/", "_")] = json.dumps(body).encode("utf-8")
        return out

    def backup(self, label="backup", with_crystals=True) -> dict[str, Any]:
        extra = self.crystal_files() if with_crystals else {}
        out = self.store.backup(self.backups, label=label, extra_files=extra)
        with self.lock:
            self.metrics["backups"] += 1
        return {"file": out.name, "bytes": out.stat().st_size, "crystals": len(extra), "dir": str(self.backups)}

    def backups_list(self) -> list[dict[str, Any]]:
        if not self.backups.is_dir():
            return []
        rows = []
        for p in sorted(self.backups.glob("sfx_vectors-*.tar.gz")):
            st = p.stat()
            rows.append({"file": p.name, "bytes": st.st_size, "at": st.st_mtime,
                         "label": p.name.split("-")[1] if p.name.count("-") >= 2 else ""})
        return rows

    def status(self) -> dict[str, Any]:
        with self.lock:
            m = dict(self.metrics)
        return {"section": str(self.store.root), "backups_dir": str(self.backups), "manifest": self.store.manifest,
                "counts": self.store.counts(), "progress": dict(self.progress), "metrics": m,
                "desk_busy": self.desk_busy(), "numpy": sfx_vectors._np is not None,
                "facets": {f: len(v.get("anchors") or []) for f, v in self.store.facets.items()}}


def install(app, namespace):
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import FileResponse

    globals()["Request"] = Request      # the string annotations below resolve here
    host = _Host(namespace)
    rt = SfxVectorRuntime(host)
    holder: dict[str, Any] = {"runtime": rt}
    namespace["_sfx_vectors"] = lambda: rt

    def suggest(text, k=8, video=None):
        """For the station's own roads: recommendations for a line, off the
        section, on the caller's thread. Embedding is asynchronous, so this
        synchronous door is lexical + facets only; the async door below adds
        the semantic part."""
        return rt.store.query(text, embed=None, video=video, k=k)

    async def suggest_async(text, k=8, video=None, facets=None):
        return await rt.run(rt.store.query, text, _sync_embedder(rt), facets, video, k)

    namespace["sfx_vectors_suggest"] = suggest
    namespace["sfx_vectors_suggest_async"] = suggest_async

    @app.on_event("startup")
    async def start_sfx_vectors():
        async def keeper():
            await asyncio.sleep(90)
            while True:
                try:
                    await rt.tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    rt.fail("keeper", exc)
                await asyncio.sleep(TICK)
        holder["task"] = asyncio.create_task(keeper(), name="sfx-vectors:keeper")
        try:
            host.pipeline_log("sfx", "the SFX Guy's vector section is open: %s" % rt.store.root,
                              extra=json.dumps(rt.store.counts()))
        except Exception:  # noqa: BLE001
            pass

    @app.on_event("shutdown")
    async def stop_sfx_vectors():
        task = holder.get("task")
        if task:
            task.cancel()

    def body_json(raw):
        try:
            return json.loads(raw or b"{}")
        except ValueError as exc:
            raise HTTPException(400, "not JSON: %s" % exc) from exc

    @app.get("/api/sfx/vectors/status")
    async def sfxv_status(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        return await rt.run(rt.status)

    @app.get("/api/sfx/vectors/manifest")
    async def sfxv_manifest(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        await rt.run(rt.store._save_manifest)
        return rt.store.manifest

    @app.get("/api/sfx/vectors/facets")
    async def sfxv_facets(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        return {"facets": rt.store.facets, "floor": sfx_vectors.FLOOR, "tags_per_facet": sfx_vectors.TAGS_PER_FACET,
                "fixed": {"lexical": "FTS5 over name, transcript, thumbnail tags and tags", "semantic": "cosine over the clip vectors"}}

    @app.put("/api/sfx/vectors/facets/{facet}")
    async def sfxv_put_facet(facet: str, request: Request, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        raw = body_json(await request.body())
        anchors = raw.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            raise HTTPException(400, "anchors: a list of [tag, description]")
        facets = dict(rt.store.facets)
        facets[facet] = {"description": str(raw.get("description") or facets.get(facet, {}).get("description") or ""),
                         "anchors": [(str(a[0]), str(a[1])) for a in anchors if isinstance(a, (list, tuple)) and len(a) >= 2]}

        def apply_():
            rt.store.save_facets(facets)
            rt.store.refresh_anchors()
            rt.store.retag_all()
            rt.store._save_manifest()
        await rt.run(apply_)
        return {"facet": facet, "anchors": len(facets[facet]["anchors"]), "retag": "every clip is tagged again by the keeper"}

    @app.get("/api/sfx/vectors/query")
    async def sfxv_query(q: str = "", facets: str = "", video: str = "", k: int = 12, max_seconds: float = 0.0,
                         authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        want: dict[str, list[str]] = {}
        for piece in [x for x in facets.split(",") if ":" in x]:
            f, t = piece.split(":", 1)
            want.setdefault(f.strip(), []).append(t.strip())
        vid = None if video in ("", "any") else (video.lower() in ("1", "yes", "true", "video"))
        with rt.lock:
            rt.metrics["queries"] += 1
        return await rt.run(rt.store.query, q, _sync_embedder(rt), want or None, vid, max(1, min(100, int(k))),
                            None, float(max_seconds or 0))

    @app.get("/api/sfx/vectors/clip/{sid}")
    async def sfxv_clip(sid: str, authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        got = await rt.run(rt.store.clip, sid)
        if not got:
            raise HTTPException(404, "no clip %s in the section" % sid)
        return got

    @app.post("/api/sfx/vectors/backup")
    async def sfxv_backup(request: Request, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        raw = body_json(await request.body())
        label = str(raw.get("label") or "backup")
        if label not in ("backup", "quarantine", "export"):
            raise HTTPException(400, "label: backup, quarantine or export")
        return await rt.run(rt.backup, label, raw.get("crystals", True))

    @app.get("/api/sfx/vectors/backups")
    async def sfxv_backups(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        return {"dir": str(rt.backups), "backups": await rt.run(rt.backups_list)}

    @app.get("/api/sfx/vectors/backup/{name}")
    async def sfxv_backup_file(name: str, authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        if "/" in name or ".." in name or not name.startswith("sfx_vectors-") or not name.endswith(".tar.gz"):
            raise HTTPException(400, "a backup's own file name")
        path = rt.backups / name
        if not path.is_file():
            raise HTTPException(404, "no such backup")
        return FileResponse(str(path), media_type="application/gzip", filename=name)

    @app.post("/api/sfx/vectors/restore")
    async def sfxv_restore(request: Request, authorization: str | None = Header(default=None)):
        """Unpack a backup into a directory BESIDE the live section (never
        over it): the operator inspects it, then swaps directories by hand."""
        host.require_auth(authorization)
        raw = body_json(await request.body())
        name = str(raw.get("file") or "")
        if "/" in name or ".." in name or not name.endswith(".tar.gz"):
            raise HTTPException(400, "file: a backup's own file name")
        src = rt.backups / name
        if not src.is_file():
            raise HTTPException(404, "no such backup")
        into = str(raw.get("into") or "").strip("/ ") or ("restored-" + name[:-7])
        if "/" in into or ".." in into:
            raise HTTPException(400, "into: a plain directory name")
        target = rt.store.root.parent / into
        roots = raw.get("roots") if isinstance(raw.get("roots"), dict) else None

        def do():
            st = sfx_vectors.Store.restore(src, target, roots=roots)
            out = {"restored": str(st.root), "roots": st.manifest.get("roots"), "counts": st.counts()}
            st.close()
            return out
        try:
            return await rt.run(do)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return rt


def _sync_embedder(rt):
    """The station's async embedder, callable from the worker thread that
    runs a query: the coroutine is handed back to the event loop."""
    fn = rt.host.get("_embed_texts")
    if fn is None:
        return None
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except Exception:  # noqa: BLE001
        loop = None

    def embed(texts):
        if loop is None or not loop.is_running():
            return []
        fut = asyncio.run_coroutine_threadsafe(fn(list(texts)), loop)
        try:
            return list(fut.result(timeout=30) or [])
        except Exception:  # noqa: BLE001
            return []
    return embed
