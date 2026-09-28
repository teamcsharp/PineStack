"""[review-queue] The desk's script review queue: every item can be closed,
and every item says what System 3 knows about it.

The operator, 2026-09-28, verbatim: "I don't know why these are scrolling at
the top of the screen anymore. When I tap them, there's not options to fix
them or resolve them or mark them as complete or to get rid of them. So they
just scroll forever. I don't know what they're for. And also they don't seem
to be talking about any information from system three."

Measured live that morning: ONE pending row in 58,394 - a `timing` cut from
2026-09-27 00:16 CST, the cohost's rendered take thrown away when the talk
cut stopped its round mid-flight. It was System 3's (banter round
a1b134f233c04813, turn t03), found only by its words: note_drop kept who,
stage and the words. Nothing reads the timing gate, and the pane's two
decisions were editorial (allow = rebuild a round from the capture, keep =
teach the writer the cut was right). Neither meant "done".

Edits (app.py):
  note-drop-signature / note-drop-context   note_drop takes what its caller
                          knows (System 3 turn, line id, round) into the review
  cut-held-context / cut-lost-context       the talk cut's two note_drops pass it
  scan-timing             #1192's sweep reads the timing gate too
  review-queue-block      resolve / dismiss (one or many), the open queue with
                          each item's System 3 state, the history, the System 3
                          link, plain words for each gate, and the one real fix
  detail-extras           GET /rejections/{id} carries what / system3 / resolve
  decide-close            POST /rejections/{id} {"action": "resolve"|"dismiss"}

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

BLOCK = r'''# =====================================================================
# [review-queue] 2026-09-28: EVERY ITEM ON THE DESK'S REVIEW STRIP CAN BE
# CLOSED, AND EVERY ONE SAYS WHAT SYSTEM 3 KNOWS ABOUT IT.
#
# The operator, verbatim: "When I tap them, there's not options to fix them
# or resolve them or mark them as complete or to get rid of them. So they
# just scroll forever. I don't know what they're for. And also they don't
# seem to be talking about any information from system three."
#
# MEASURED, live, before a line of this was written: one pending row in
# 58,394 - a `timing` cut 27.6 hours old, the cohost's rendered take thrown
# away when the talk cut stopped its round mid-flight and the box was not
# the destination. The desktop strip showed it eight times over (a marquee
# that recycled its first page for ever). It WAS System 3's - banter round
# a1b134f233c04813, turn t03 (Skip, response_a2) - but only its words could
# say so, because note_drop kept who, stage and the words and nothing else.
# Nothing reads the timing gate: #1192's sweep reads segment_brief and
# call_contract, the regrade reads tint. And the pane's only two decisions
# were editorial - allow rebuilds a round from the capture (which the
# strict System 3 gate then withholds from the air) and keep TEACHES the
# writer "the operator agreed with this cut". Neither of them means "done".
#
# So: RESOLVE and DISMISS, for one row or a batch. Both move a pending row to
# `noted` - where the machine's own closes already live and stay readable -
# and write the operator's decision into review_decisions, which is what
# the pane's "Review decisions" reads. Neither allows, keeps, teaches the
# writer, touches the approved-fingerprint set or puts a word on the air.
# A FIX is offered only where one exists: the allow road, while the row's
# round still waits on the shelf.
#
# System 3 is read through a READ-ONLY door of our own onto its ledger (the
# #1192 desk's shape): never System 3's connection, lock or executor, so a
# review page can never queue behind its writer.
# =====================================================================
REVIEW_CLOSE_ACTIONS = ("resolve", "dismiss")
REVIEW_CLOSE_WORDS = {"resolve": "Marked complete by the operator",
                      "dismiss": "Dismissed by the operator"}
# What the station's own desks write on a row they close (note_stale); the
# history lists these beside the operator's decisions.
REVIEW_STATION_CLOSES = ("round_gone", "superseded", "stale_grader", "read_plain")
REVIEW_BULK_MOST = int(os.getenv("PINE_REVIEW_BULK_MOST", "2000"))
REVIEW_BULK_CHUNK = 20
REVIEW_HISTORY_SCAN = int(os.getenv("PINE_REVIEW_HISTORY_SCAN", "600"))
# How far before a row's first cut its words are looked for in System 3's
# ledger, and how many rounds one lookup may open.
REVIEW_S3_BEFORE = float(os.getenv("PINE_REVIEW_S3_BEFORE", "21600"))
REVIEW_S3_AFTER = 180.0
REVIEW_S3_ROUNDS = int(os.getenv("PINE_REVIEW_S3_ROUNDS", "60"))
REVIEW_S3_BUDGET = int(os.getenv("PINE_REVIEW_S3_BUDGET", "180"))
REVIEW_S3_MEMO_TTL = 600.0
_REVIEW_S3_MEMO: dict[str, Any] = {}
REVIEW_S3_GATE_FAMILIES = ("WITHHELD", "ABANDONED", "WITHDRAWN", "CUT", "REFUSED", "DROPPED")
# Gates that judge a whole round: their row is the round, not one turn.
REVIEW_WHOLE_GATES = ("segment_brief", "call_contract", "radio_draft", "blend",
                      "tint_structure", "draft_fragment", "draft_trimming", "freshen_structure")
REVIEW_AGE_STEPS = (3600, 21600, 86400, 259200, 604800)
REVIEW_GATE_WORDS = {
    "timing": ("The talk cut stopped this line's round mid-flight - at a turn boundary, when "
               "something urgent took the floor or the turn cap ended a long round. The line had "
               "been rendered and was never heard."),
    "tint": ("The crystal rewrite refused this line: its rhymed version failed the grader, so "
             "the line left its round."),
    "tint_structure": "The crystal rewrite changed this round's shape (its turns or speakers), so the rewrite was refused.",
    "tint_length": "The crystal rewrite came back the wrong length for this line.",
    "call_contract": "The phone-call contract refused this call's script before it was recorded.",
    "segment_brief": ("The segment brief held this whole round before the recording room: the "
                      "script never got to what its slot was for."),
    "repetition": "The repetition gate took this line out: it was too close to something already said.",
    "freshness": "The line expired before it could air.",
    "recording_requirement": "The recording room could not make audio for it - a technical failure, not the words.",
    "radio_draft": "The draft missed its conversational target and was written again.",
    "blend": "The blend pass changed a preserved passage or the turn count, so the blended version was refused.",
    "track_talk": "The track-talk desk refused this link about a record.",
    "phrase_ban": "A banned phrase was found in it.",
    "line_quality": "A general quality judgment took it out.",
}


def review_cut_context(meta: Any, item: Any, round_sid: str = "") -> dict[str, Any]:
    """What a line cut at air knows about itself, for its review row: the
    System 3 turn that made it, its line id and its round. Never raises."""
    out: dict[str, Any] = {}
    try:
        meta = meta if isinstance(meta, dict) else {}
        item = item if isinstance(item, dict) else {}
        if item.get("line_id"):
            out["line_id"] = str(item.get("line_id"))
        if round_sid:
            out["round_sid"] = str(round_sid)
        kind = str(meta.get("prep_kind") or "")
        if kind:
            out["kind"] = kind
        s3 = meta.get("system3")
        if isinstance(s3, dict) and s3.get("conversation_id"):
            tid = ""
            finder = globals().get("system3_turn_id_for")
            if callable(finder):
                try:
                    tid = str(finder(meta, str(item.get("turn_text") or item.get("chunk") or ""),
                                     str(item.get("who") or "")) or "")
                except Exception:  # noqa: BLE001
                    tid = ""
            out["system3"] = {"conversation_id": str(s3.get("conversation_id") or ""),
                              "turn_id": tid, "mode": str(s3.get("mode") or "")}
    except Exception:  # noqa: BLE001
        pass
    return out


def _review_write_db() -> Any:
    """Our own WRITE door onto the review store, for closes only. One short
    BEGIN IMMEDIATE per close (or per chunk of a batch), the store's own
    discipline, so a capture on the loop never waits long behind it. The
    store keeps no in-memory copy of a row's status - only approvals,
    preferences and one-time grants, none of which a close touches - so a
    close through this door leaves the store's memory true."""
    import sqlite3
    db = sqlite3.connect(str(_LINE_REVIEW.path), timeout=20.0, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _review_positive(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(name + " must be a positive integer")
    return value


def _review_close_row(db: Any, review_id: str, action: str, note: str, by: str,
                      batch: str, why: str, revision: Any = None,
                      event_seq: Any = None) -> dict[str, Any]:
    """Inside an open transaction: close one row, or say why not."""
    row = db.execute("SELECT id,review_status,revision,latest_seq FROM line_reviews WHERE id=?",
                     (str(review_id),)).fetchone()
    if row is None:
        raise KeyError("No such line review")
    if event_seq is not None and event_seq != int(row["latest_seq"]):
        raise ReviewConflictError("This cut has a newer occurrence; reload it before closing it")
    if revision is not None and revision != int(row["revision"]):
        raise ReviewConflictError("This review changed; reload it before closing it")
    if row["review_status"] != "pending":
        return {"changed": False, "status": str(row["review_status"])}
    now = time.time()
    decision = {"action": action, "note": note, "at": now, "by": by}
    if batch:
        decision["batch"] = batch
    if why:
        decision["why"] = why
    effect = {"status": "resolved" if action == "resolve" else "dismissed",
              "say": (note or REVIEW_CLOSE_WORDS[action])[:200], "at": now, "by": by}
    db.execute("UPDATE line_reviews SET review_status='noted',revision=revision+1,effect=? WHERE id=?",
               (json.dumps(effect, ensure_ascii=False), row["id"]))
    db.execute("INSERT INTO review_decisions(review_id,at,body) VALUES (?,?,?)",
               (row["id"], now, json.dumps(decision, ensure_ascii=False)))
    return {"changed": True, "status": "noted", "effect": effect, "decision": decision}


def review_close(review_id: str, action: str, note: Any = "", expected_revision: Any = None,
                 expected_event_seq: Any = None, by: str = "operator") -> dict[str, Any]:
    """Close ONE pending row as resolved or dismissed. A worker thread only.

    Refused with a conflict when the operator read an older revision or an
    older occurrence - the same guard decide() has - and a no-op on a row
    that is already closed."""
    if action not in REVIEW_CLOSE_ACTIONS:
        raise ValueError("action must be resolve or dismiss")
    note = "" if note is None else note
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("note must be text of at most 2000 characters")
    revision = _review_positive(expected_revision, "expected_revision")
    event_seq = _review_positive(expected_event_seq, "expected_event_seq")
    db = _review_write_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            got = _review_close_row(db, review_id, action, note.strip(), str(by or "operator")[:40],
                                    "", "", revision, event_seq)
            db.execute("COMMIT")
        except BaseException:
            try:
                db.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise
    finally:
        db.close()
    if got.get("changed"):
        _REVIEW_QUEUE_SEEN["shape"] = {}         # the banner's count is stale by construction
        got["say"] = REVIEW_CLOSE_WORDS[action] + ": it left the queue and stays in the history."
    else:
        got["say"] = "Already closed - it is " + str(got.get("status") or "closed") + "."
    got["ok"] = True
    return got


async def review_close_route(review_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/orchestrator/rejections/{id} with a resolve or dismiss."""
    action = str(body.get("action") or "")
    got = await asyncio.to_thread(review_close, review_id, action, body.get("note", ""),
                                  body.get("expected_revision"), body.get("expected_event_seq"))
    if got.get("changed"):
        station_flow_event("repair", "operator",
                           "Operator " + ("resolved" if action == "resolve" else "dismissed") + " a review",
                           {"review_id": review_id, "action": action,
                            "note": str(body.get("note") or "")[:240]}, trace_id=review_id)
    got["row"] = await asyncio.to_thread(_LINE_REVIEW.get, review_id)
    return got


def review_open_rows(limit: int = 200) -> list[dict[str, Any]]:
    """The OPEN (pending) rows, newest first, through the read-only door, with
    only the context fields the desk reads - never the whole parent script."""
    most = max(1, min(int(limit or 1), REVIEW_BULK_MOST))
    out: list[dict[str, Any]] = []
    db = _review_queue_db()
    try:
        cursor = db.execute(
            "SELECT id,gate,disposition,technical,first_at,last_at,latest_seq,revision,"
            "occurrences,reasons,substr(source,1,4000) AS source,substr(candidate,1,400) AS candidate,"
            "json_extract(context,'$.system3') AS s3,json_extract(context,'$.entry.system3') AS entry_s3,"
            "json_extract(context,'$.line_id') AS line_id,json_extract(context,'$.kind') AS kind,"
            "json_extract(context,'$.who') AS who,json_extract(context,'$.speaker') AS speaker,"
            "json_extract(context,'$.stage') AS stage "
            "FROM line_reviews WHERE review_status='pending' ORDER BY latest_seq DESC LIMIT ?", (most,))
        for raw in cursor:
            ctx: dict[str, Any] = {"kind": str(raw["kind"] or ""),
                                   "who": str(raw["who"] or raw["speaker"] or ""),
                                   "stage": str(raw["stage"] or "")}
            if raw["line_id"]:
                ctx["line_id"] = str(raw["line_id"])
            s3 = _review_queue_json(raw["s3"]) if raw["s3"] else {}
            if isinstance(s3, dict) and s3:
                ctx["system3"] = s3
            entry_s3 = _review_queue_json(raw["entry_s3"]) if raw["entry_s3"] else {}
            if isinstance(entry_s3, dict) and entry_s3:
                ctx["entry"] = {"system3": entry_s3}
            out.append({
                "id": str(raw["id"]), "gate": str(raw["gate"] or ""),
                "disposition": str(raw["disposition"] or ""), "technical": bool(raw["technical"]),
                "first_at": float(raw["first_at"] or 0), "last_at": float(raw["last_at"] or 0),
                "latest_seq": int(raw["latest_seq"] or 0), "event_seq": int(raw["latest_seq"] or 0),
                "revision": int(raw["revision"] or 0), "occurrences": int(raw["occurrences"] or 1),
                "reasons": list(_review_queue_json(raw["reasons"], []) or []),
                "source": str(raw["source"] or ""), "candidate": str(raw["candidate"] or ""),
                "review_status": "pending", "context": ctx})
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass
    return out


def review_s3_path() -> Path:
    """System 3's ledger - the very file system3_runtime writes."""
    return data_path("system3.sqlite3")


def _review_s3_db() -> Any:
    """A READ-ONLY door onto System 3's ledger, or None when it has none."""
    import sqlite3
    path = Path(review_s3_path())
    if not path.is_file():
        return None
    return sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True, timeout=10.0)


def _review_words(text: Any) -> str:
    """Words as the ledger and the review can both be read: case, curly
    quotes and spacing do not count."""
    return " ".join(str(text or "").replace("’", "'").replace("‘", "'")
                    .replace("“", '"').replace("”", '"').lower().split())[:4000]


def _review_s3_round(db: Any, cid: str, cache: dict[str, Any], budget: dict[str, Any],
                     force: bool = False) -> Any:
    """One round out of the ledger: its body, {} when it is not held, None
    when this lookup has spent its budget (unknown - not absent)."""
    if cid in cache:
        return cache[cid]
    if not force and int(budget.get("left") or 0) <= 0:
        return None
    budget["left"] = int(budget.get("left") or 0) - 1
    import zlib
    got = db.execute("SELECT body, created FROM conversations WHERE id=?", (cid,)).fetchone()
    conv: Any = {}
    if got is not None:
        try:
            conv = json.loads(zlib.decompress(got[0]).decode("utf-8"))
        except Exception:  # noqa: BLE001
            conv = {}
        if isinstance(conv, dict) and conv:
            conv["_created"] = float(got[1] or 0)
    cache[cid] = conv if isinstance(conv, dict) else {}
    time.sleep(0.002)          # a thread: hand the interpreter back between rounds
    return cache[cid]


def _review_s3_turn(conv: Any, tid: str, words: str) -> Any:
    """The turn a review row is about: by its id, else by its words."""
    turns = [t for t in ((conv or {}).get("turns") or []) if isinstance(t, dict)]
    if tid:
        for t in turns:
            if str(t.get("turn_id") or "") == tid:
                return t
    if not words:
        return None
    loose = None
    for t in turns:
        said = _review_words(t.get("text"))
        if not said:
            continue
        if said == words:
            return t
        if loose is None and len(words) >= 16 and (words in said or (len(said) >= 16 and said in words)):
            loose = t
    return loose


def _review_s3_by_words(db: Any, words: str, first_at: float, whole: bool,
                        cache: dict[str, Any], budget: dict[str, Any]) -> tuple[str, str, str]:
    """(conversation, turn, how) for a row that kept no link: the rounds
    System 3 planned in the hours before the cut, newest first, whose turns
    carry these words. A whole-round row matches a round when two of its
    turns are inside the round's script."""
    if len(words) < 16 or not first_at:
        return "", "", "no_words"
    rows = db.execute("SELECT id FROM conversations WHERE created BETWEEN ? AND ? "
                      "ORDER BY created DESC LIMIT ?",
                      (first_at - REVIEW_S3_BEFORE, first_at + REVIEW_S3_AFTER,
                       REVIEW_S3_ROUNDS)).fetchall()
    if not rows:
        return "", "", "no_rounds"
    for (cid,) in rows:
        conv = _review_s3_round(db, str(cid), cache, budget)
        if conv is None:
            return "", "", "budget"
        if not conv:
            continue
        if whole:
            inside = [t for t in (conv.get("turns") or []) if isinstance(t, dict)
                      and len(_review_words(t.get("text"))) >= 16
                      and _review_words(t.get("text")) in words]
            if len(inside) >= min(2, len(conv.get("turns") or [])):
                return str(cid), "", "found"
            continue
        turn = _review_s3_turn(conv, "", words)
        if turn:
            return str(cid), str(turn.get("turn_id") or ""), "found"
    return "", "", "no_match"


def _review_s3_events(db: Any, cid: str, tid: str) -> list[dict[str, Any]]:
    """What System 3 itself recorded about this round being held back or cut."""
    import zlib
    out: list[dict[str, Any]] = []
    marks = ",".join("?" for _ in REVIEW_S3_GATE_FAMILIES)
    for family, turn_id, body, at in db.execute(
            "SELECT family, turn_id, body, at FROM events WHERE conversation_id=? AND kind='observation' "
            "AND family IN (" + marks + ") ORDER BY id LIMIT 20", (cid,) + tuple(REVIEW_S3_GATE_FAMILIES)):
        if turn_id and tid and str(turn_id) != tid:
            continue
        try:
            got = json.loads(zlib.decompress(body).decode("utf-8"))
        except Exception:  # noqa: BLE001
            got = {}
        out.append({"family": str(family or ""), "turn_id": str(turn_id or ""), "at": float(at or 0),
                    "stage": str(got.get("stage") or "")[:60],
                    "why": str(got.get("why") or got.get("reason") or "")[:300]})
    return out


def _review_s3_say(link: dict[str, Any], gate: str) -> str:
    how = {"round": " (the round's own System 3 stamp)", "line": " (the script ledger's link)",
           "words": " (found by its words: this review kept no link)"}.get(str(link.get("why") or ""), "")
    road = str(link.get("road") or "a")
    cid = str(link.get("conversation_id") or "")
    turn = link.get("turn") or None
    if str(link.get("mode") or "") == "shadow":
        said = ("System 3 only shadowed this %s round (%s): it planned beside the old writer, "
                "which wrote the words%s." % (road, cid, how))
    elif turn:
        said = ("System 3 directed this line: %s round %s, turn %d of %d - %s on the %s node%s."
                % (road, cid, int(turn.get("number") or 0), int(turn.get("of") or 0),
                   str(turn.get("name") or turn.get("speaker") or "a seat"),
                   str(turn.get("node_label") or turn.get("node") or "?"), how))
    elif link.get("whole"):
        said = ("System 3 directed this %s round (%s, %d turns)%s; the %s gate took the whole round, "
                "not one turn." % (road, cid, int(link.get("turns") or 0), how, gate.replace("_", " ") or "station's"))
    else:
        said = ("Part of System 3's %s round %s%s, but none of its planned turns carries these words: "
                "the station put the line in at air." % (road, cid, how))
    held = link.get("withheld")
    if isinstance(held, dict) and held.get("why"):
        said += " System 3 recorded the round as %s: %s" % (str(held.get("stage") or "withheld"),
                                                            str(held.get("why"))[:200])
    return said


def review_system3_link(row: dict[str, Any], db: Any = None, cache: Any = None,
                        budget: Any = None) -> dict[str, Any]:
    """The System 3 record behind one review row, or why there is none.

    In order: the row's own stamp (a line cut at air, from now on), the
    round's stamp (a hold or a cut that kept its entry), the script ledger's
    line link, and last the WORDS - the rounds System 3 planned in the hours
    before the cut. A worker thread only; it opens SQLite."""
    ctx = row.get("context") if isinstance(row.get("context"), dict) else {}
    entry = ctx.get("entry") if isinstance(ctx.get("entry"), dict) else {}
    gate = str(row.get("gate") or "")
    whole = (review_queue_kind(gate, row.get("disposition"), row.get("technical")) == "hold"
             or gate in REVIEW_WHOLE_GATES)
    words = _review_words(row.get("source") or row.get("candidate"))
    first_at = float(row.get("first_at") or 0)
    cache = {} if cache is None else cache
    budget = {"left": REVIEW_S3_BUDGET} if budget is None else budget
    own = db is None
    if own:
        db = _review_s3_db()
        if db is None:
            return {"state": "off", "why": "no_ledger",
                    "say": "This station keeps no System 3 ledger, so there is nothing to ask."}
    try:
        cid, tid, how = "", "", ""
        stamp = ctx.get("system3")
        if isinstance(stamp, dict) and stamp.get("conversation_id"):
            cid, tid, how = str(stamp.get("conversation_id")), str(stamp.get("turn_id") or ""), "stamp"
        entry_stamp = entry.get("system3")
        if not cid and isinstance(entry_stamp, dict) and entry_stamp.get("conversation_id"):
            cid, how = str(entry_stamp.get("conversation_id")), "round"
        if not cid and ctx.get("line_id"):
            got = db.execute("SELECT conversation_id, turn_id FROM lines WHERE line_id=?",
                             (str(ctx.get("line_id")),)).fetchone()
            if got and got[0]:
                cid, tid, how = str(got[0]), str(got[1] or ""), "line"
        search = ""
        if not cid:
            cid, tid, search = _review_s3_by_words(db, words, first_at, whole, cache, budget)
            how = "words" if cid else ""
        if not cid:
            if search == "budget":
                return {"state": "unknown", "why": "budget",
                        "say": "Not looked up this time (too many to search at once); open it to ask System 3."}
            oldest = db.execute("SELECT MIN(created) FROM conversations").fetchone()
            oldest = float((oldest[0] if oldest else 0) or 0)
            if not oldest or (first_at and first_at < oldest) or search == "no_rounds":
                return {"state": "none", "why": "before",
                        "say": ("No System 3 record: this is from before System 3 directed this road "
                                "(nothing in its ledger - which keeps seven days - planned a round then).")}
            if search == "no_words":
                return {"state": "none", "why": "no_words",
                        "say": "No System 3 record, and too few words were kept to look for one."}
            return {"state": "none", "why": "unlinked",
                    "say": ("No System 3 record: System 3 was planning rounds then, but none of its turns "
                            "carries these words - a line from a road System 3 did not direct.")}
        conv = _review_s3_round(db, cid, cache, budget, force=True)
        if not conv:
            return {"state": "gone", "why": "retention", "conversation_id": cid, "turn_id": tid,
                    "say": ("System 3 directed it (round %s), but that round is past the seven days "
                            "System 3's ledger keeps." % cid)}
        turn = _review_s3_turn(conv, tid, "" if whole else words)
        turns = [t for t in (conv.get("turns") or []) if isinstance(t, dict)]
        ident = conv.get("identity") if isinstance(conv.get("identity"), dict) else {}
        subject = conv.get("subject") if isinstance(conv.get("subject"), dict) else {}
        turn_id = str((turn or {}).get("turn_id") or tid or "")
        link: dict[str, Any] = {
            "state": "linked", "why": how, "conversation_id": cid, "turn_id": turn_id,
            "road": str(ident.get("road_kind") or ""), "mode": str(conv.get("mode") or ""),
            "status": str(conv.get("status") or ""), "engine": str(conv.get("engine") or ""),
            "created": float(conv.get("_created") or conv.get("created") or 0),
            "topic": " ".join(str(subject.get("topic") or "").split())[:240],
            "turns": len(turns), "whole": bool(whole and not turn),
            "withheld": conv.get("withheld") if isinstance(conv.get("withheld"), dict) else None,
            "events": _review_s3_events(db, cid, turn_id), "turn": None}
        if turn:
            index = int(turn.get("index") or 0)
            # the rolls the turn's own story shows: its decisions, its
            # speakerbox draws, its SFX and the SFX Guy's node (turnEvents)
            rolled = {str(d.get("event_id")) for d in (turn.get("decisions") or [])
                      if isinstance(d, dict) and d.get("event_id")}
            rolled |= {str(s.get("event_id")) for s in (turn.get("speakerbox") or [])
                       if isinstance(s, dict) and s.get("event_id")}
            for key in ("sfx", "sfxguy"):
                if isinstance(turn.get(key), dict) and turn[key].get("event_id"):
                    rolled.add(str(turn[key]["event_id"]))
            link["turn"] = {
                "turn_id": turn_id, "index": index, "number": index + 1, "of": len(turns),
                "speaker": str(turn.get("speaker") or ""), "name": str(turn.get("name") or ""),
                "node": str(turn.get("step") or turn.get("leg") or ""),
                "node_label": str(turn.get("step_label") or turn.get("leg_label")
                                  or turn.get("step") or turn.get("leg") or ""),
                "phase": str(turn.get("phase") or ""), "text": str(turn.get("text") or "")[:600],
                "rolls": len(rolled)}
        link["say"] = _review_s3_say(link, gate)
        return link
    finally:
        if own:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass


def review_s3_known(row: dict[str, Any], db: Any, cache: Any, budget: Any) -> dict[str, Any]:
    """review_system3_link, remembered for ten minutes per row revision - a
    row's System 3 record does not move under it."""
    key = str(row.get("id") or "")
    revision = int(row.get("revision") or 0)
    now = time.time()
    hit = _REVIEW_S3_MEMO.get(key)
    if (hit and hit[0] == revision and now - hit[1] < REVIEW_S3_MEMO_TTL
            and hit[2].get("state") != "unknown"):
        return copy.deepcopy(hit[2])
    got = review_system3_link(row, db=db, cache=cache, budget=budget)
    if key:
        _REVIEW_S3_MEMO[key] = (revision, now, copy.deepcopy(got))
        if len(_REVIEW_S3_MEMO) > 4000:
            for old in sorted(_REVIEW_S3_MEMO, key=lambda k: _REVIEW_S3_MEMO[k][1])[:1000]:
                _REVIEW_S3_MEMO.pop(old, None)
    return got


def review_what(row: dict[str, Any]) -> dict[str, Any]:
    """What this item is, in plain words, and whether anything reads it."""
    gate = str(row.get("gate") or "")
    kind = review_queue_kind(gate, row.get("disposition"), row.get("technical"))
    reasons = [str(r) for r in (row.get("reasons") or []) if str(r or "").strip()]
    say = REVIEW_GATE_WORDS.get(gate) or ("The %s gate took this %s out of the work."
                                          % (gate.replace("_", " ") or "station's",
                                             "round" if kind == "hold" else "line"))
    first = float(row.get("first_at") or 0)
    sweep = ""
    if gate in ("tint", "recording_tint"):
        sweep = "The station re-grades this gate's cuts every ten minutes and closes the ones that pass today."
    elif gate in REVIEW_QUEUE_SCAN_GATES and review_queue_mode() == REVIEW_QUEUE_SWEEP:
        sweep = ("The station's own sweep reads this gate every ten minutes and closes a row whose "
                 "round has been gone for %d hours." % int(REVIEW_QUEUE_GONE_AFTER // 3600))
    return {"gate": gate, "kind": kind, "label": str(CONTENT_GATE_INFO.get(gate) or ""),
            "say": say, "reason": reasons[0] if reasons else "",
            "age_s": round(max(0.0, time.time() - first), 1) if first else 0.0,
            "first_at": first, "occurrences": int(row.get("occurrences") or 1), "sweep": sweep}


def review_fix_plan(row: dict[str, Any]) -> dict[str, Any]:
    """The one real fix, where there is one: the allow road, while the row's
    round still waits on the shelf. Everywhere else, why there is none."""
    if str(row.get("review_status") or "") != "pending":
        return {"available": False, "why_not": "It is closed; nothing is waiting on it."}
    if row.get("technical"):
        return {"available": False,
                "why_not": ("A technical failure - the engine or the audio failed, not the words. The "
                            "station's own recovery repairs those; approval cannot make it playable.")}
    gate = str(row.get("gate") or "")
    if gate == "timing":
        return {"available": False,
                "why_not": ("Its round was on the air when the talk cut stopped it, and the take was "
                            "not kept (or went to the hold shelf and plays by itself). There is no "
                            "place left to put the line back.")}
    try:
        match = line_review_matching(row)
    except Exception:  # noqa: BLE001
        match = None
    if match:
        hold = review_queue_kind(gate, row.get("disposition"), row.get("technical")) == "hold"
        return {"available": True, "action": "allow",
                "label": "Fix: release the held round" if hold else "Fix: restore the words",
                "say": (("Its round still waits on the %s shelf. Releasing it sends it to the recording "
                         "room as written; it airs with its System 3 conversation.") if hold else
                        ("Its round still waits on the %s shelf. These words go back into it, through the "
                         "tint and the recording room, and air with its System 3 conversation."))
                % str(match[0] or "dialogue")}
    if _s3_active():
        return {"available": False,
                "why_not": ("Its round has aired, expired or been replaced. Rebuilding it from the "
                            "capture would make a round System 3 never planned, and the System 3 gate "
                            "withholds those from the air - so there is nothing left to fix.")}
    return {"available": True, "action": "allow", "label": "Fix: rebuild from the capture",
            "say": ("Its round is gone. Allowing rebuilds a round from the captured words (the old "
                    "road) and sends it through the tint and the recording room.")}


def review_closed_as(row: dict[str, Any]) -> dict[str, Any] | None:
    """How a row that is no longer open was closed, and by whom."""
    status = str(row.get("review_status") or "")
    if status == "pending":
        return None
    effect = row.get("effect") if isinstance(row.get("effect"), dict) else {}
    decision = next((d for d in (row.get("decisions") or [])
                     if isinstance(d, dict) and d.get("action") in ("allow", "keep", "resolve", "dismiss")),
                    None)
    closed = {"status": str(effect.get("status") or status), "say": str(effect.get("say") or "")[:240],
              "at": float(effect.get("at") or (decision or {}).get("at") or row.get("last_at") or 0),
              "by": str(effect.get("by") or ("operator" if decision else "station"))}
    if status in ("allowed", "kept"):
        closed["status"] = status
        closed["by"] = "operator"
    if decision:
        closed["note"] = str(decision.get("note") or "")[:400]
    return closed


async def review_detail_extras(row: dict[str, Any]) -> dict[str, Any]:
    """Beside a review's evidence: what it is, what System 3 knows about it,
    and what can be done with it now."""
    out: dict[str, Any] = {}
    try:
        out["what"] = await asyncio.to_thread(review_what, row)
    except Exception as exc:  # noqa: BLE001
        out["what"] = {"say": "", "error": type(exc).__name__}
    try:
        link = await asyncio.wait_for(asyncio.to_thread(review_system3_link, row), timeout=8.0)
        if row.get("id"):
            _REVIEW_S3_MEMO[str(row["id"])] = (int(row.get("revision") or 0), time.time(), copy.deepcopy(link))
        out["system3"] = link
    except asyncio.TimeoutError:
        out["system3"] = {"state": "unknown", "why": "timeout",
                          "say": "System 3's ledger did not answer in time; open it again to ask."}
    except Exception as exc:  # noqa: BLE001
        out["system3"] = {"state": "unknown", "why": "error",
                          "say": "System 3's ledger could not be read: " + type(exc).__name__}
    try:
        fix = await asyncio.to_thread(review_fix_plan, row)
    except Exception as exc:  # noqa: BLE001
        fix = {"available": False, "why_not": "The fix could not be worked out: " + type(exc).__name__}
    open_now = str(row.get("review_status") or "") == "pending" and not row.get("read_only")
    out["resolve"] = {"open": open_now, "actions": list(REVIEW_CLOSE_ACTIONS) if open_now else [],
                      "fix": fix, "closed": review_closed_as(row)}
    return out


def review_queue_open(limit: int = 200) -> dict[str, Any]:
    """The open queue for the desk: every open item once, newest first, with
    its System 3 state; how many are older than each step; how many have no
    System 3 record. A worker thread only."""
    now = time.time()
    most = max(1, min(int(limit or 1), 500))
    rows = review_open_rows(most + 1)
    db = _review_queue_db()
    try:
        firsts = [float(r[0] or 0) for r in db.execute(
            "SELECT first_at FROM line_reviews WHERE review_status='pending'")]
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass
    s3db = None
    try:
        s3db = _review_s3_db()
    except Exception:  # noqa: BLE001
        s3db = None
    cache: dict[str, Any] = {}
    budget = {"left": REVIEW_S3_BUDGET}
    items: list[dict[str, Any]] = []
    counts = {"linked": 0, "legacy": 0, "unknown": 0, "off": 0}
    try:
        for row in rows[:most]:
            if s3db is None:
                link = {"state": "off", "why": "no_ledger", "say": "This station keeps no System 3 ledger."}
            else:
                try:
                    link = review_s3_known(row, s3db, cache, budget)
                except Exception as exc:  # noqa: BLE001
                    link = {"state": "unknown", "why": "error", "say": type(exc).__name__}
            state = str(link.get("state") or "unknown")
            counts["legacy" if state in ("none", "gone") else state if state in counts else "unknown"] += 1
            ctx = row.get("context") or {}
            items.append({
                "id": row["id"], "gate": row["gate"], "disposition": row["disposition"],
                "technical": row["technical"], "kind": str(ctx.get("kind") or ""),
                "who": str(ctx.get("who") or ""), "first_at": row["first_at"], "last_at": row["last_at"],
                "age_s": round(max(0.0, now - row["first_at"]), 1), "event_seq": row["event_seq"],
                "seq": row["event_seq"], "revision": row["revision"], "occurrences": row["occurrences"],
                "reasons": row["reasons"][:4], "source_preview": row["source"][:220],
                "candidate_preview": row["candidate"][:260], "review_status": "pending",
                "system3": {k: link.get(k) for k in ("state", "why", "conversation_id", "turn_id",
                                                     "road", "say") if link.get(k) is not None}})
    finally:
        if s3db is not None:
            try:
                s3db.close()
            except Exception:  # noqa: BLE001
                pass
    return {"at": now, "count": len(firsts), "items": items, "has_more": len(rows) > most,
            "linked": counts["linked"], "legacy": counts["legacy"], "unknown": counts["unknown"],
            "ages": {str(step): sum(1 for f in firsts if f and now - f >= step) for step in REVIEW_AGE_STEPS},
            "oldest_at": min([f for f in firsts if f] or [0.0]),
            "closes": list(REVIEW_CLOSE_ACTIONS)}


def review_history(limit: int = 60, before: float = 0.0) -> dict[str, Any]:
    """What left the queue, newest first: the operator's decisions (allow,
    keep, resolve, dismiss) and the station's own closes (a round gone, a
    newer cut, a pass under today's grader). Read-only; a worker thread."""
    most = max(1, min(int(limit or 1), 200))
    edge = float(before or 0)
    out: list[dict[str, Any]] = []
    db = _review_queue_db()
    try:
        decided = db.execute(
            "SELECT d.review_id AS id, d.at AS at, d.body AS body, r.gate AS gate, r.review_status AS status,"
            "r.disposition AS disposition, substr(r.source,1,220) AS source, r.reasons AS reasons,"
            "r.first_at AS first_at, json_extract(r.context,'$.kind') AS kind,"
            "json_extract(r.context,'$.who') AS who "
            "FROM review_decisions d JOIN line_reviews r ON r.id=d.review_id "
            "WHERE (?=0 OR d.at<?) AND COALESCE(json_extract(d.body,'$.action'),'') "
            "IN ('allow','keep','resolve','dismiss') ORDER BY d.seq DESC LIMIT ?",
            (edge, edge, most)).fetchall()
        station = db.execute(
            "SELECT id, gate, disposition, substr(source,1,220) AS source, reasons, first_at, effect,"
            "json_extract(context,'$.kind') AS kind, json_extract(context,'$.who') AS who "
            "FROM line_reviews WHERE review_status='noted' ORDER BY latest_seq DESC LIMIT ?",
            (REVIEW_HISTORY_SCAN,)).fetchall()
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass
    words = {"allow": "Allowed - its words were restored", "keep": "Kept rejected",
             "resolve": "Marked complete", "dismiss": "Dismissed",
             "round_gone": "Closed by the station: its round had aired, expired or been replaced",
             "superseded": "Closed by the station: a newer cut replaced it",
             "stale_grader": "Closed by the station: today's checker passes it",
             "read_plain": "Closed by the station: the line is read plain now"}
    for raw in decided:
        body = _review_queue_json(raw["body"], {})
        action = str(body.get("action") or "")
        out.append({"id": str(raw["id"]), "gate": str(raw["gate"] or ""), "kind": str(raw["kind"] or ""),
                    "who": str(raw["who"] or ""), "source_preview": str(raw["source"] or ""),
                    "reasons": list(_review_queue_json(raw["reasons"], []) or [])[:2],
                    "first_at": float(raw["first_at"] or 0), "closed_at": float(raw["at"] or 0),
                    "closed_by": str(body.get("by") or "operator"), "action": action,
                    "label": words.get(action, action), "note": str(body.get("note") or "")[:400],
                    "why": str(body.get("why") or "")[:200],
                    "batch": str(body.get("batch") or ""), "status_now": str(raw["status"] or "")})
    for raw in station:
        effect = _review_queue_json(raw["effect"], {})
        status = str(effect.get("status") or "")
        if status not in REVIEW_STATION_CLOSES or effect.get("by") == "operator":
            continue
        at = float(effect.get("at") or 0)
        if edge and at and at >= edge:
            continue
        out.append({"id": str(raw["id"]), "gate": str(raw["gate"] or ""), "kind": str(raw["kind"] or ""),
                    "who": str(raw["who"] or ""), "source_preview": str(raw["source"] or ""),
                    "reasons": list(_review_queue_json(raw["reasons"], []) or [])[:2],
                    "first_at": float(raw["first_at"] or 0), "closed_at": at, "closed_by": "station",
                    "action": status, "label": words.get(status, status),
                    "note": str(effect.get("say") or "")[:400], "why": "", "batch": "", "status_now": "noted"})
    out.sort(key=lambda h: -float(h.get("closed_at") or 0))
    out = out[:most]
    return {"items": out, "next_before": (out[-1]["closed_at"] if len(out) >= most else None),
            "scanned_station_rows": len(station)}


def review_bulk_close(body: Any) -> dict[str, Any]:
    """Close many open rows at once: by id, by age, by gate, or every one with
    no System 3 record. At least one filter; every filter given must hold.
    `dry_run` counts and changes nothing. A worker thread only."""
    if not isinstance(body, dict) or set(body) - {"ids", "older_than_s", "legacy", "gate",
                                                 "action", "note", "dry_run"}:
        raise ValueError("supply ids, older_than_s, legacy or gate, and optional action, note, dry_run")
    action = str(body.get("action") or "dismiss")
    if action not in REVIEW_CLOSE_ACTIONS:
        raise ValueError("action must be resolve or dismiss")
    ids = body.get("ids")
    if ids is not None and (not isinstance(ids, list) or len(ids) > REVIEW_BULK_MOST
                            or not all(isinstance(x, str) and x for x in ids)):
        raise ValueError("ids must be a list of review ids")
    older = body.get("older_than_s")
    if older is not None and (isinstance(older, bool) or not isinstance(older, (int, float)) or older < 0):
        raise ValueError("older_than_s must be a number of seconds")
    legacy = body.get("legacy", False)
    if not isinstance(legacy, bool):
        raise ValueError("legacy must be true or false")
    gate = body.get("gate") or ""
    if not isinstance(gate, str) or len(gate) > 200:
        raise ValueError("gate must be a gate name")
    note = body.get("note") or ""
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError("note must be text of at most 2000 characters")
    if ids is None and older is None and not legacy and not gate:
        raise ValueError("name what to close: ids, older_than_s, legacy or gate")
    now = time.time()
    wanted = set(ids or [])
    picked = [r for r in review_open_rows(REVIEW_BULK_MOST)
              if (ids is None or r["id"] in wanted)
              and (older is None or now - float(r["first_at"] or now) >= float(older))
              and (not gate or r["gate"] == gate)]
    unknown = 0
    if legacy:
        kept: list[dict[str, Any]] = []
        s3db = _review_s3_db()
        cache: dict[str, Any] = {}
        budget = {"left": REVIEW_S3_BUDGET * 2}
        try:
            for r in picked:
                link = ({"state": "none"} if s3db is None
                        else review_s3_known(r, s3db, cache, budget))
                if link.get("state") in ("none", "gone"):
                    kept.append(r)
                elif link.get("state") == "unknown":
                    unknown += 1
        finally:
            if s3db is not None:
                try:
                    s3db.close()
                except Exception:  # noqa: BLE001
                    pass
        picked = kept
    why = ", ".join(part for part in (
        ("%d chosen" % len(wanted)) if ids is not None else "",
        ("older than %s" % _review_span(float(older))) if older is not None else "",
        "no System 3 record" if legacy else "",
        ("gate %s" % gate) if gate else "") if part)
    out: dict[str, Any] = {"ok": True, "action": action, "matched": len(picked), "closed": 0,
                           "dry_run": bool(body.get("dry_run")), "skipped_unknown": unknown,
                           "ids": [r["id"] for r in picked][:200], "why": why}
    if out["dry_run"] or not picked:
        out["say"] = ("%d open review(s) match (%s)." % (len(picked), why or "no filter")
                      + (" %d could not be looked up in System 3 this time and were left." % unknown
                         if unknown else ""))
        return out
    batch = uuid.uuid4().hex[:12]
    errors = 0
    for start in range(0, len(picked), REVIEW_BULK_CHUNK):
        chunk = picked[start:start + REVIEW_BULK_CHUNK]
        db = _review_write_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            try:
                for r in chunk:
                    try:
                        got = _review_close_row(db, r["id"], action, note.strip(), "operator",
                                                batch, why, None, None)
                    except KeyError:
                        errors += 1
                        continue
                    if got.get("changed"):
                        out["closed"] += 1
                db.execute("COMMIT")
            except BaseException:
                try:
                    db.execute("ROLLBACK")
                except Exception:  # noqa: BLE001
                    pass
                raise
        finally:
            db.close()
        time.sleep(0.05)       # a capture on the loop is never kept waiting behind the batch
    if out["closed"]:
        _REVIEW_QUEUE_SEEN["shape"] = {}
    out["batch"] = batch
    out["errors"] = errors
    out["say"] = ("%d review(s) %s (%s); they left the queue and stay in the history."
                  % (out["closed"], "marked complete" if action == "resolve" else "dismissed", why)
                  + (" %d could not be looked up in System 3 this time and were left." % unknown
                     if unknown else ""))
    return out


def _review_span(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds >= 86400:
        return "%g day(s)" % round(seconds / 86400, 1)
    if seconds >= 3600:
        return "%g hour(s)" % round(seconds / 3600, 1)
    return "%d minute(s)" % int(seconds // 60)


@app.get("/api/orchestrator/rejections/queue")
async def api_review_queue_open(limit: int = Query(default=200, ge=1, le=500),
                                authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[review-queue] The open queue, each item's System 3 state, the ages."""
    require_read_auth(authorization)
    return await asyncio.to_thread(review_queue_open, limit)


@app.get("/api/orchestrator/rejections/history")
async def api_review_history(limit: int = Query(default=60, ge=1, le=200),
                             before: float = Query(default=0.0, ge=0.0),
                             authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[review-queue] What left the queue, and who closed it."""
    require_read_auth(authorization)
    return await asyncio.to_thread(review_history, limit, before)


@app.post("/api/orchestrator/rejections/bulk-close")
async def api_review_bulk_close(request: Request,
                                authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[review-queue] Dismiss or resolve many open reviews at once."""
    require_auth(authorization)
    try:
        body = await request.json()
        got = await asyncio.to_thread(review_bulk_close, body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if got.get("closed"):
        station_flow_event("repair", "operator", "Operator closed reviews in bulk",
                           {"action": got.get("action"), "closed": got.get("closed"),
                            "why": got.get("why"), "batch": got.get("batch")})
    return got


'''

GET_ANCHOR = '@app.get("/api/orchestrator/rejections/{review_id}")\nasync def api_line_review_get(\n'
PREF_ANCHOR = ('    row["preference"] = line_review_preferences(str(row.get("context", {}).get("kind") or ""), '
               'str(row.get("gate") or ""))\n')
DECIDE_ANCHOR = '        result = _LINE_REVIEW.decide(review_id, body.get("action"),\n'
DASH = "—"

EDITS = [
    ("note-drop-signature",
     'def note_drop(who: str, text: str, why: str) -> None:\n',
     'def note_drop(who: str, text: str, why: str,\n'
     '              context: dict[str, Any] | None = None) -> None:\n', 1),
    ("note-drop-context",
     '                        context={"who": str(who or ""),\n'
     '                                 "stage": "recording_or_air_admission"},\n',
     '                        # [review-queue] what the caller knows about the line - its\n'
     '                        # System 3 turn, its line id, its round - rides the review, so\n'
     '                        # the desk finds the node that made it without guessing\n'
     '                        context={**(context if isinstance(context, dict) else {}),\n'
     '                                 "who": str(who or ""),\n'
     '                                 "stage": "recording_or_air_admission"},\n', 1),
    ("cut-held-context",
     '                    note_drop(item["who"], item["chunk"],\n'
     '                              "round cut mid-flight ' + DASH + ' held for replay")\n',
     '                    note_drop(item["who"], item["chunk"],\n'
     '                              "round cut mid-flight ' + DASH + ' held for replay",\n'
     '                              context=review_cut_context(ready_meta, item, _round_sid))   # [review-queue]\n', 1),
    ("cut-lost-context",
     '                note_drop(item["who"], item["chunk"],\n'
     '                          "round cut mid-flight ' + DASH + ' the box is not the "\n'
     '                          "destination, so nothing was shelved")\n',
     '                note_drop(item["who"], item["chunk"],\n'
     '                          "round cut mid-flight ' + DASH + ' the box is not the "\n'
     '                          "destination, so nothing was shelved",\n'
     '                          context=review_cut_context(ready_meta, item, _round_sid))   # [review-queue]\n', 1),
    ("scan-timing",
     'REVIEW_QUEUE_SCAN_GATES = ("segment_brief", "call_contract")\n',
     '# [review-queue] 2026-09-28: and the timing gate - a line the talk cut\n'
     '# stopped mid-flight. Its round was ON THE AIR when it was cut, so once the\n'
     '# round is gone there is no place left to put the line back, and nothing\n'
     '# read these rows at all: the one pending row on the desk that morning had\n'
     '# waited 27.6 hours for a decision nobody could make.\n'
     'REVIEW_QUEUE_SCAN_GATES = ("segment_brief", "call_contract", "timing")\n', 1),
    ("review-queue-block", GET_ANCHOR, BLOCK + GET_ANCHOR, 1),
    ("detail-extras", PREF_ANCHOR,
     PREF_ANCHOR + '    row.update(await review_detail_extras(row))    # [review-queue] what it is, System 3, what can be done\n', 1),
    ("decide-close", DECIDE_ANCHOR,
     '        if body.get("action") in REVIEW_CLOSE_ACTIONS:        # [review-queue] resolve / dismiss\n'
     '            return await review_close_route(review_id, body)\n' + DECIDE_ANCHOR, 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
