"""A saved topic can be reworded in place: POST /api/dj/topics/{id}/edit.

Operator, 2026-09-27, on the topic desk's bank: "allow me to double click
or long press to edit the topic inline editing the entry."

The words are split exactly as a new topic's are ("1. ... 2. ..." is the
line the round opens on and the answer to it - split_exchange); the id,
its uses and when it was added stay, so it is the same topic reworded and
its history still counts. A copy of it already waiting in the next-banter
queue (queue_bombshell keeps the words, not a pointer) is reworded with it,
or the old words would still be what airs next.

A POST beside /queue and /drop, the bank's other verbs, so every surface
reaches it through the same door. Idempotent: --check exits 0 when the edit
can apply, 2 when already applied, 1 when an anchor is missing; --apply
writes app.py. Run it ON THE HOST.
"""
import sys
from pathlib import Path

ANCHOR = '@app.post("/api/dj/topics/{topic_id}/queue")\n'
ROUTE = '''@app.post("/api/dj/topics/{topic_id}/edit")
async def dj_topics_edit(
    topic_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[topic-edit] Reword one saved topic in place - "allow me to double
    click or long press to edit the topic inline editing the entry". Split
    as a new one is; the id, the uses and the date stay. A copy waiting in
    the next-banter queue is reworded with it."""
    require_auth(authorization)
    payload = await request.json()
    raw = str(payload.get("text") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Give them something")
    text, reply = split_exchange(raw)
    reply = reply or " ".join(str(payload.get("reply") or "").split())

    def reword() -> dict[str, Any] | None:
        with _BOMBSHELL_LOCK:
            rows = read_bombshells()
            row = next((r for r in rows if r.get("id") == topic_id), None)
            if row is None:
                return None
            row["text"] = text.strip()[:400]
            if reply:
                row["reply"] = reply[:400]
            else:
                row.pop("reply", None)
            row["edited"] = int(time.time())
            return dict(row) if write_bombshells(rows) else {}

    row = await asyncio.to_thread(reword)
    if row is None:
        raise HTTPException(status_code=404, detail="No such topic")
    if not row:
        raise HTTPException(status_code=503, detail="The topic bank could not be written")
    requeued = 0
    with _SWITCH_LOCK:
        for queued in _SWITCH_QUEUE:
            if queued.get("topic_id") != topic_id:
                continue
            shape = queued.get("topic_shape") or bombshell_shape_for(row)
            queued["premise"] = bombshell_angle(row["text"], shape, reply)
            queued["exchange"] = {"opener": row["text"], "reply": reply} if reply else {}
            requeued += 1
    note_action("you reworded a topic in the bank: " + row["text"][:160])
    return {"topic": row, "requeued": requeued}


'''


def main(argv):
    apply = "--apply" in argv
    path = Path("app.py")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if '@app.post("/api/dj/topics/{topic_id}/edit")' in text:
        print("already applied")
        return 2
    if text.count(ANCHOR) != 1:
        print("MISSING (%d): %r" % (text.count(ANCHOR), ANCHOR))
        return 1
    if not apply:
        print("can apply: 1 edit(s)")
        return 0
    path.write_text(text.replace(ANCHOR, ROUTE + ANCHOR), encoding="utf-8", newline="\n")
    print("applied: 1 edit(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
