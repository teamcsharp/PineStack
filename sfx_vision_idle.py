"""[sfx-vision-idle] THE SFX GUY WATCHES HIS CLIPS WHILE THE STATION RESTS.

"For the SFX guy, I want him also running image analysis on the clips that
he's adding to his vector database ... so he also has a visual context library
of understanding what the contents of media is. So during times where the
station is idle or offline, I want him basically inspecting videos and running
those as tasks through the AI ... image analysis of various frames that he's
able to use to add additional tags ... and then we want to use the
descriptions of those frames for tags ... to better match videos to
subtitles."                                           - the operator, 2026-09-30

#1386's vision bite looked at ONE frame per clip, ran only when someone
POSTed /api/sfx/vision, and stopped the moment the radio was off or paused -
the opposite of this ask. This keeper:

  WHEN   the station is paused or switched off, and nothing else holds the
         model (_OLLAMA_GATE free); one clip at a time, a rest between.
  WHAT   up to three frames per video clip (15 %, 50 %, 85 %; one for a clip
         under 2.5 s), each described ("DESCRIPTION: ... / TAGS: ...").
  WHERE  the clip book: `seen_frames` (JSON [{at, desc, tags}]) and
         `seen_desc` - the merged tags, which the matcher (sfx_match) and the
         vector keeper (sfx_vectors: embedding, facet tags, full text) already
         read, so better words reach the line-to-clip matching unchanged.
  ORDER  clips nobody has looked at yet, those he has aired first.

The SFX database window shows each clip's frames (sfx_frames_of).
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from typing import Any

FRAME_SHARES = (0.15, 0.5, 0.85)
SHORT_S = 2.5
REST_S = 2.0              # between clips: the box runs hot (#1285)
IDLE_POLL_S = 20.0
BATCH = 8                 # clips per pass before the conditions are read again
SEEN_MOST = 600
ASK = ("Describe this video still for a sound-effects library. Answer in exactly two lines:\n"
       "DESCRIPTION: one short sentence - who or what is in it, what is happening, where.\n"
       "TAGS: comma-separated words and short phrases - people, objects, actions, the place, "
       "the mood, any words written on screen.")

STATE: dict[str, Any] = {"running": False, "looked": 0, "frames": 0, "blank": 0, "at": 0.0,
                         "why": "", "last": "", "enabled": True}


def parse_answer(text: str) -> tuple[str, list[str]]:
    """'DESCRIPTION: ... / TAGS: a, b' -> (desc, [a, b]). A model that ignores
    the format still gives tags: the whole answer is read as a list."""
    text = str(text or "").strip()
    desc, tags = "", ""
    m = re.search(r"description\s*:\s*(.+)", text, re.I)
    if m:
        desc = m.group(1).split("\n")[0].strip()
    m = re.search(r"tags\s*:\s*(.+)", text, re.I | re.S)
    if m:
        tags = m.group(1)
    elif not desc:
        tags = text
    out: list[str] = []
    for piece in re.split(r"[,\n;]", tags):
        p = " ".join(piece.strip(" .*-#\t").split()).lower()
        if p and len(p) <= 48 and p not in out:
            out.append(p)
    return desc[:240], out[:24]


def merge_seen(frames: list[dict[str, Any]], old: str = "") -> str:
    """The clip's seen_desc: every frame's tags, most-shared first, then the
    words already there (a hand edit survives a later look)."""
    count: dict[str, int] = {}
    order: list[str] = []
    for f in frames:
        for t in f.get("tags") or []:
            if t not in count:
                order.append(t)
            count[t] = count.get(t, 0) + 1
    for t in [x.strip().lower() for x in str(old or "").split(",") if x.strip()]:
        if t not in count:
            order.append(t)
            count[t] = 0
    ranked = sorted(order, key=lambda t: (-count[t], order.index(t)))
    out = ""
    for t in ranked:
        nxt = (out + ", " + t) if out else t
        if len(nxt) > SEEN_MOST:
            break
        out = nxt
    return out


def install(app: Any, namespace: dict[str, Any]) -> None:
    from fastapi import Header

    def ns(name: str) -> Any:
        return namespace.get(name)

    def column() -> bool:
        con, lock = ns("sfx_db")(), ns("_SFX_DB_LOCK")
        cols = {r[1] for r in con.execute("PRAGMA table_info(clips)")}
        with lock:
            for col, kind in (("seen_desc", "TEXT"), ("seen_desc_at", "REAL"), ("seen_frames", "TEXT")):
                if col not in cols:
                    con.execute("ALTER TABLE clips ADD COLUMN %s %s" % (col, kind))
            con.commit()
        return True

    def frames_of(sid: str) -> list[dict[str, Any]]:
        try:
            row = ns("sfx_db_reader")().execute("SELECT seen_frames FROM clips WHERE sid = ?", (sid,)).fetchone()
            return json.loads(row[0]) if row and row[0] else []
        except Exception:  # noqa: BLE001
            return []
    namespace["sfx_frames_of"] = frames_of

    def counts() -> dict[str, int]:
        try:
            con = ns("sfx_db_reader")()
            tot = con.execute("SELECT COUNT(*) FROM clips WHERE playable=1 AND video=1").fetchone()[0]
            done = con.execute("SELECT COUNT(*) FROM clips WHERE playable=1 AND video=1 "
                               "AND seen_frames IS NOT NULL").fetchone()[0]
            return {"video": int(tot), "studied": int(done)}
        except Exception:  # noqa: BLE001
            return {"video": 0, "studied": 0}

    def todo_rows(most: int) -> list[tuple[str, str, float, str]]:
        """(path, sid, seconds, seen_desc) of clips not yet studied, shortest first."""
        con = ns("sfx_db_reader")()
        return [tuple(r) for r in con.execute(
            "SELECT path, sid, seconds, coalesce(seen_desc,'') FROM clips WHERE playable=1 AND video=1 "
            "AND seen_frames IS NULL AND seconds > 0 ORDER BY seconds LIMIT ?", (most,)).fetchall()]

    async def todo(most: int) -> list[tuple[str, str, float, str]]:
        """The ones he airs first (the vector section's count, read on its own
        thread), then the shortest."""
        rows = await asyncio.to_thread(todo_rows, most * 40)
        aired: dict[str, int] = {}
        try:
            rt = ns("_sfx_vectors")()
            sids = [r[1] for r in rows if r[1]]
            if sids:
                marks = ",".join("?" * len(sids))
                aired = dict(await rt.run(lambda: rt.store.con.execute(
                    "select sid, aired from clips where sid in (%s)" % marks, sids).fetchall()))
        except Exception:  # noqa: BLE001
            aired = {}
        rows = sorted(rows, key=lambda r: (-int(aired.get(r[1]) or 0), float(r[2] or 0)))
        return rows[:most]

    def resting() -> str:
        """Why not now, or '' when the station is resting and the model is free."""
        if not STATE.get("enabled"):
            return "switched off"
        radio = ns("_RADIO") or {}
        paused = ns("radio_paused")
        if radio.get("on") and not (callable(paused) and paused()):
            return "the station is on air"
        gate = ns("_OLLAMA_GATE")
        if gate is not None and gate.locked():
            return "the model is busy"
        return ""

    async def look(path: str, seconds: float) -> list[dict[str, Any]]:
        httpx = ns("httpx")
        post = ns("recorded_ollama_post")
        frame_of = ns("clip_speech").frame_of
        shares = (0.5,) if float(seconds or 0) < SHORT_S else FRAME_SHARES
        out: list[dict[str, Any]] = []
        for share in shares:
            if resting():
                break
            jpeg = await asyncio.to_thread(frame_of, path, share)
            if not jpeg:
                continue
            try:
                async with ns("_OLLAMA_GATE"), httpx.AsyncClient(timeout=120) as client:
                    answer = await post(client, "%s/api/chat" % ns("OLLAMA_URL"), purpose="sfx vision (idle)",
                                        json={"model": ns("VISION_MODEL"),
                                              "messages": [{"role": "user", "content": ASK,
                                                            "images": [base64.b64encode(jpeg).decode()]}],
                                              "stream": False, "think": False, "keep_alive": "10m"})
                text = ((answer.json().get("message") or {}).get("content") or "")
            except Exception as exc:  # noqa: BLE001
                STATE["why"] = "the model would not answer: %s" % type(exc).__name__
                continue
            desc, tags = parse_answer(text)
            if desc or tags:
                out.append({"at": round(float(seconds or 0) * share, 2), "desc": desc, "tags": tags})
        return out

    def write(path: str, frames: list[dict[str, Any]], old: str) -> None:
        con, lock = ns("sfx_db")(), ns("_SFX_DB_LOCK")
        seen = merge_seen(frames, old) if frames else old
        with lock:
            con.execute("UPDATE clips SET seen_frames = ?, seen_desc = ?, seen_desc_at = ? WHERE path = ?",
                        (json.dumps(frames), seen, time.time(), path))
            con.commit()

    async def keeper() -> None:
        await asyncio.sleep(120)
        try:
            await asyncio.to_thread(column)
        except Exception as exc:  # noqa: BLE001
            STATE["why"] = "the clip book would not take the columns: %s" % type(exc).__name__
            return
        while True:
            try:
                why = resting()
                if why:
                    STATE["why"] = why
                    await asyncio.sleep(IDLE_POLL_S)
                    continue
                rows = await todo(BATCH)
                if not rows:
                    STATE["why"] = "every video clip has been studied"
                    await asyncio.sleep(IDLE_POLL_S * 6)
                    continue
                STATE.update(running=True, why="studying his clips while the station rests")
                did = 0
                for path, sid, seconds, old in rows:
                    if resting():
                        break
                    frames = await look(path, seconds)
                    if resting() and not frames:
                        break               # interrupted: the clip is not marked as studied
                    await asyncio.to_thread(write, path, frames, old)
                    did += 1
                    STATE["looked"] = int(STATE["looked"]) + 1
                    STATE["frames"] = int(STATE["frames"]) + len(frames)
                    STATE["blank"] = int(STATE["blank"]) + (0 if frames else 1)
                    STATE["at"] = time.time()
                    STATE["last"] = sid
                    await asyncio.sleep(REST_S)
                if did:
                    kick = ns("sfx_match_kick")
                    if callable(kick):
                        kick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                STATE["why"] = "%s: %s" % (type(exc).__name__, exc)
                await asyncio.sleep(IDLE_POLL_S)
            finally:
                STATE["running"] = False

    holder: dict[str, Any] = {}

    @app.on_event("startup")
    async def start_sfx_vision_idle():
        holder["task"] = asyncio.create_task(keeper(), name="sfx-vision-idle")

    @app.on_event("shutdown")
    async def stop_sfx_vision_idle():
        if holder.get("task"):
            holder["task"].cancel()

    @app.get("/api/sfx/vision/idle")
    async def sfx_vision_idle_state(authorization: str | None = Header(default=None)):
        ns("require_read_auth")(authorization)
        return dict(STATE, **(await asyncio.to_thread(counts)), now=resting() or "studying")

    @app.post("/api/sfx/vision/idle")
    async def sfx_vision_idle_switch(payload: dict[str, Any] | None = None,
                                     authorization: str | None = Header(default=None)):
        ns("require_auth")(authorization)
        if payload and "enabled" in payload:
            STATE["enabled"] = bool(payload["enabled"])
        return dict(STATE)
