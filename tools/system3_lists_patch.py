"""[s3-lists] Every list that feeds the air is an editable table in System 3's
Tables tab.

Operator (2026-09-28), pointing at the empty space under POOL in the Tables
tab: "the system that made the 'I sold the tapes to Sawyer.'. I need to be
able to access that list of items in that database and be able to edit them
and remove them / add to it. Any list to do with conversation or the
roulette needs to be listed here as an editable table." And: "no dialogue
hit the station unless it is scripted via the RNG roulette system".

This registers each list against the store that owns it - its own load,
save and lock, nothing written around them - in a registry
(system3_lists.py) and serves it:

    GET    /api/system3/lists                       the registry, with counts
    GET    /api/system3/lists/{id}?offset=&limit=&q=&state=
    POST   /api/system3/lists/{id}/rows             add            {text, ...}
    PUT    /api/system3/lists/{id}/rows/{row_id}    edit / switch  {text?, on?}
    DELETE /api/system3/lists/{id}/rows/{row_id}    remove

Reads are open like the other System 3 reads (require_read_auth); writes
need the key (require_auth). Every write is written down before the store
is called - who (address, desktop app or browser tab), when, which list,
which row, what was asked, what it was before - in
data/system3_list_edits.jsonl, and a failure after it (the word-cause
doors' rule). Stores are called off the loop (asyncio.to_thread) except the
gold bank, whose writers all run on the loop unlocked (as its burn door
does).

Registered, first to last:
  sfxguy.bank      BANK  the SFX Guy's recorded speech bank (sfx_speech_bank.py
                         desk_* - needs that module's [s3-lists] edit)
  sfxguy.quips     LIST  his quip shelf for the voice on air; the shelf gets
                         the one lock it never had (_SFXGUY_QUIPS_LOCK), taken
                         by the quips doors and the line votes too
  topics.board     LIST  the topics board System 3's TOPIC roll draws from
                         (_BOMBSHELL_LOCK; a removed topic goes to the bin)
  ads.book         LIST  the ad book (_ADS_LOCK; on/off is auto_air, which
                         every ad pick already honours)
  upstairs.pages   LIST  the manager's intercom pages (_UPSTAIRS_LOCK)
  gold.bars        BANK  the gold bank - remove only (burnt to the bin,
                         restorable at /api/gold/restore)

Needs system3_lists.py beside app.py, and sfx_speech_bank.py with
edit_bank_module.py applied.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

REGISTRY = r'''


# --- [s3-lists] EVERY LIST THAT FEEDS THE AIR IS A TABLE ON THE DESK ----------
# Operator (2026-09-28), pointing under POOL in System 3's Tables tab: "the
# system that made the 'I sold the tapes to Sawyer.'. I need to be able to
# access that list of items in that database and be able to edit them and
# remove them / add to it. Any list to do with conversation or the roulette
# needs to be listed here as an editable table." The machinery is
# system3_lists.py; each list is registered here against the store that owns
# it - its own load, save and lock - and nothing writes around them. The
# lists that are NOT here (the response bank, the continuity pairs, the
# liners, call scenarios, caller themes, guests, plots, the hard-coded line
# tuples) are named in the [s3-lists] hand-off with why.
from system3_lists import (ListError as _S3ListError, ListRegistry as _S3ListRegistry,
                           clean_words as _s3_list_words, text_id as _s3_list_id,
                           who_of as _s3_list_who_of)

_S3_LISTS = _S3ListRegistry(data_path("system3_list_edits.jsonl"))


def _s3_list_air() -> tuple[str, str]:
    """The SFX speaker's voice and Crystal profile on air now ('' when he is off)."""
    voice = str(dj_settings().get("drop_voice") or "")
    return voice, (_sfxguy_ready_profile() if voice else "")


# --- the SFX Guy's speech bank: whole lines recorded in his voice ------------
def _s3_bank_add(body: dict[str, Any]) -> str:
    voice, profile = _s3_list_air()
    return _SFX_READY_BANK.desk_add(body.get("text"), voice, profile,
                                    generic=body.get("generic", True) is not False)


_S3_LISTS.register({
    "id": "sfxguy.bank", "label": "SFX Guy's speech bank", "family": "BANK",
    "store": "data/sfxguy_speech.json",
    "what": ("Whole lines recorded in the SFX Guy's voice ('I sold the tapes to Sawyer.'). While System 3's "
             "dice are live a banked line airs only when the roulette brings one up (sfxguy.bank_line) and "
             "which one is System 3's roll among the rested takes (sfxguy.bank_take). One row is one line - "
             "every take of those words. Rewriting a line drops its recording and it is recorded again before "
             "it can air; a removed line never comes back from his sources; off keeps it, never picked."),
    "schema": [{"key": "text", "kind": "text", "label": "what he says, word for word"}],
    "rows": lambda: _SFX_READY_BANK.desk_rows(*_s3_list_air()),
    "add": _s3_bank_add,
    "edit": lambda rid, body: _SFX_READY_BANK.desk_edit(rid, body.get("text")),
    "switch": lambda rid, on: _SFX_READY_BANK.desk_switch(rid, on),
    "remove": lambda rid: _SFX_READY_BANK.desk_remove(rid),
})


# --- his quip shelf (the voice on air) ---------------------------------------
def _s3_quips_rows() -> list[dict[str, Any]]:
    said, now = _sfxguy_said(), time.time()
    out = []
    for at, q in enumerate(sfxguy_quips()):
        last = float(said.get(_sfxguy_key(q)) or 0)
        out.append({"id": _s3_list_id(q), "text": q,
                    "state": "resting" if now - last < 3600 else "ready",
                    "last_played": last,
                    "note": "also a source of his speech bank" if at < 16 else ""})
    return out


def _s3_quips_change(rid: str, text: Any = None, add: bool = False) -> str:
    with _SFXGUY_QUIPS_LOCK:
        rows = sfxguy_quips()
        ids = [_s3_list_id(q) for q in rows]
        words = _s3_list_words(text, 200) if (add or text is not None) else ""
        if words and _s3_list_id(words) in ids and _s3_list_id(words) != rid:
            raise ValueError("that line is already on his shelf")
        if add:
            rows.append(words)
        else:
            if rid not in ids:
                raise KeyError(rid)
            if text is None:
                rows.pop(ids.index(rid))
            else:
                rows[ids.index(rid)] = words
        sfxguy_quips_save(rows)
        return _s3_list_id(words) if words else rid


_S3_LISTS.register({
    "id": "sfxguy.quips", "label": "SFX Guy's quips", "family": "LIST",
    "store": "data/sfxguy_quips/<voice on air>.json",
    "what": ("His shelf of sayings for the voice on air. Under a System 3 round the line is System 3's pick "
             "among the ones that have rested an hour (director.pick 'quip'); the first 16 are also sources of "
             "his speech bank (removing one here does not take its recording out of the bank - do that there)."),
    "schema": [{"key": "text", "kind": "text", "label": "the saying, 200 characters at most"}],
    "rows": _s3_quips_rows,
    "add": lambda body: _s3_quips_change("", body.get("text"), add=True),
    "edit": lambda rid, body: _s3_quips_change(rid, body.get("text") if body.get("text") is not None else ""),
    "remove": lambda rid: _s3_quips_change(rid),
})


# --- the topics board ---------------------------------------------------------
def _s3_topics_rows() -> list[dict[str, Any]]:
    out = []
    for r in read_bombshells():
        if not isinstance(r, dict) or not r.get("id"):
            continue
        out.append({"id": str(r["id"]), "text": str(r.get("text") or ""),
                    "state": str(r.get("kind") or "topic"), "plays": int(r.get("used") or 0),
                    "last_played": float(r.get("last") or 0),
                    "note": " · ".join(x for x in (
                        ("answered with: " + str(r["reply"])) if r.get("reply") else "",
                        "by " + str(r.get("by") or "operator"),
                        time.strftime("added %Y-%m-%d", time.localtime(int(r.get("added") or 0)))
                        if r.get("added") else "") if x)})
    return out


def _s3_topics_add(body: dict[str, Any]) -> str:
    text, reply = split_exchange(_s3_list_words(body.get("text")))
    reply = reply or " ".join(str(body.get("reply") or "").split())
    row = add_bombshell(text, str(body.get("kind") or "topic"), "operator", "", reply)
    if not row:
        raise OSError("the topic bank could not be written")
    return str(row["id"])


def _s3_topics_edit(rid: str, body: dict[str, Any]) -> str:
    """As the board's own edit door ([topic-edit]): the id, the uses and the
    date stay; a copy waiting in the next-banter queue is reworded with it.
    An answer is kept unless new words carry one ("1. ... 2. ...")."""
    text, reply = split_exchange(_s3_list_words(body.get("text")))
    with _BOMBSHELL_LOCK:
        rows = read_bombshells()
        row = next((r for r in rows if isinstance(r, dict) and r.get("id") == rid), None)
        if row is None:
            raise KeyError(rid)
        reply = reply or (" ".join(str(body.get("reply") or "").split()) if "reply" in body
                          else str(row.get("reply") or ""))
        row["text"] = text[:400]
        if reply:
            row["reply"] = reply[:400]
        else:
            row.pop("reply", None)
        row["edited"] = int(time.time())
        if not write_bombshells(rows):
            raise OSError("the topic bank could not be written")
        done = dict(row)
    with _SWITCH_LOCK:
        for queued in _SWITCH_QUEUE:
            if queued.get("topic_id") != rid:
                continue
            shape = queued.get("topic_shape") or bombshell_shape_for(done)
            queued["premise"] = bombshell_angle(done["text"], shape, reply)
            queued["exchange"] = {"opener": done["text"], "reply": reply} if reply else {}
    return rid


def _s3_topics_remove(rid: str) -> str:
    """Out of the bank and into the bin - nothing here is really thrown away."""
    with _BOMBSHELL_LOCK:
        rows = read_bombshells()
        gone = [r for r in rows if isinstance(r, dict) and r.get("id") == rid]
        if not gone:
            raise KeyError(rid)
        for r in gone:
            r["binned_at"] = int(time.time())
            r["binned_why"] = "removed on the System 3 desk"
        _json_write(TOPIC_TRASH_PATH, (gone + _json_rows(TOPIC_TRASH_PATH))[:3000])
        if not write_bombshells([r for r in rows if not (isinstance(r, dict) and r.get("id") == rid)]):
            raise OSError("the topic bank could not be written")
    return rid


_S3_LISTS.register({
    "id": "topics.board", "label": "Topics board", "family": "LIST",
    "store": "data/banter_topics.json",
    "what": ("The things to spring on them. System 3's TOPIC roll draws one (weight 1/(1+uses)); '1. line "
             "2. answer' is a line and the answer to it. A removed topic goes to the bin "
             "(banter_topics.trash.json)."),
    "schema": [{"key": "text", "kind": "text", "label": "the topic, or '1. line 2. answer'"}],
    "rows": _s3_topics_rows, "add": _s3_topics_add, "edit": _s3_topics_edit, "remove": _s3_topics_remove,
})


# --- the ad book --------------------------------------------------------------
def _s3_ads_rows() -> list[dict[str, Any]]:
    last: dict[str, float] = {}
    for a in ad_airings():
        last[str(a.get("id") or "")] = max(last.get(str(a.get("id") or ""), 0.0), float(a.get("ts") or 0))
    return [{"id": str(r["id"]), "text": str(r.get("text") or ""), "on": r.get("auto_air") is not False,
             "state": "produced" if r.get("audio") else "read", "plays": int(r.get("uses") or 0),
             "last_played": last.get(str(r["id"]), 0.0),
             "note": " · ".join(x for x in (str(r.get("product") or ""), str(r.get("kind") or "")) if x)}
            for r in sorted(ad_list(), key=lambda r: -int(r.get("ts") or 0)) if r.get("id")]


def _s3_ads_edit(rid: str, body: dict[str, Any]) -> str:
    """New words for a read. A produced spot's recording is of the old words:
    it is dropped (recut it on the ads desk to produce it again)."""
    text = _s3_list_words(body.get("text"), 1200)
    with _ADS_LOCK:
        row = next((r for r in ad_list() if r.get("id") == rid), None)
        if row is None:
            raise KeyError(rid)
        fields: dict[str, Any] = {"text": text}
        if body.get("product"):
            fields["product"] = str(body["product"])[:200]
        if row.get("audio") and text != str(row.get("text") or ""):
            try:
                (PRODUCED_ADS_DIR / str(row["audio"])).unlink(missing_ok=True)
            except OSError:
                pass
            fields["audio"] = ""
        ad_update(rid, **fields)
    return rid


def _s3_ads_switch(rid: str, on: bool) -> str:
    """auto_air: every ad pick (the book, the cupboard, System 3's ad road) skips a read that is off."""
    with _ADS_LOCK:
        rows = ad_list()
        row = next((r for r in rows if r.get("id") == rid), None)
        if row is None:
            raise KeyError(rid)
        row["auto_air"] = bool(on)
        _ads_write(rows)
    return rid


def _s3_ads_remove(rid: str) -> str:
    with _ADS_LOCK:
        if not any(r.get("id") == rid for r in ad_list()):
            raise KeyError(rid)
        ad_delete(rid)
    return rid


_S3_LISTS.register({
    "id": "ads.book", "label": "Ad book", "family": "LIST",
    "store": "data/ad_reads.json",
    "what": ("Every ad read the station keeps. System 3 draws which spot airs among the reads that have run "
             "least (road ad_spot; ad.read_pick, ad.cupboard_spot). Off keeps a read out of every draw; "
             "rewriting a produced spot drops its recording."),
    "schema": [{"key": "text", "kind": "text", "label": "the read, word for word"}],
    "rows": _s3_ads_rows,
    "add": lambda body: str(ad_save(str(body.get("product") or "house ad")[:200],
                                    _s3_list_words(body.get("text"), 1200), kind="written")["id"]),
    "edit": _s3_ads_edit, "switch": _s3_ads_switch, "remove": _s3_ads_remove,
})


# --- the manager's intercom pages ---------------------------------------------
def _s3_upstairs_edit(rid: str, body: dict[str, Any]) -> str:
    """New words for a page. Its recording is of the old words and a page airs
    only recorded, so the recording is dropped - recut it on the recordings desk."""
    text = _s3_list_words(body.get("text"), 2000)
    with _UPSTAIRS_LOCK:
        row = next((r for r in upstairs_list() if r.get("id") == rid), None)
        if row is None:
            raise KeyError(rid)
        fields: dict[str, Any] = {"text": text}
        if row.get("audio") and text != str(row.get("text") or ""):
            try:
                (UPSTAIRS_AUDIO_DIR / str(row["audio"])).unlink(missing_ok=True)
            except OSError:
                pass
            fields["audio"] = ""
        upstairs_update(rid, **fields)
    return rid


def _s3_upstairs_remove(rid: str) -> str:
    with _UPSTAIRS_LOCK:
        if not any(r.get("id") == rid for r in upstairs_list()):
            raise KeyError(rid)
        upstairs_delete(rid)
    return rid


_S3_LISTS.register({
    "id": "upstairs.pages", "label": "Upstairs pages", "family": "LIST",
    "store": "data/upstairs_pages.json",
    "what": ("The manager's intercom pages. A recorded page is replayed least-recently-aired first; a page "
             "without a recording does not air (recut it on the recordings desk). Rewriting a page drops "
             "its recording."),
    "schema": [{"key": "text", "kind": "text", "label": "the page, word for word"}],
    "rows": lambda: [{"id": str(r["id"]), "text": str(r.get("text") or ""),
                      "state": "recorded" if r.get("audio") else "not recorded",
                      "plays": int(r.get("uses") or 0), "last_played": float(r.get("last") or 0),
                      "note": str(r.get("gripe") or "")}
                     for r in upstairs_list() if r.get("id")],
    "add": lambda body: str(upstairs_save(_s3_list_words(body.get("text"), 2000), "", "the System 3 desk")["id"]),
    "edit": _s3_upstairs_edit, "remove": _s3_upstairs_remove,
})


# --- the gold bank: rhymed bars that aired with a finished take ---------------
def _s3_gold_burn(rid: str) -> str:
    """As /api/gold/burn: into the bin (data/gold_burnt.json), restorable."""
    with _WORD_DIAL_LOCK:
        rows = _gold_rows()
        take = [b for b in rows if str(b.get("key")) == rid]
        if not take:
            raise KeyError(rid)
        for b in take:
            b["burnt_at"] = int(time.time())
            b["burnt_why"] = "removed on the System 3 desk"
        word_edit_note("/api/system3/lists/gold.bars", key=rid, was={"keys": [rid]}, now=None,
                       node_type="gold", word="", say="burnt 1 bar(s)")
        _json_write(GOLD_BURNT_PATH, (take + gold_burnt_rows())[:4000])
        rows[:] = [b for b in rows if str(b.get("key")) != rid]
        _gold_save()
    return rid


_S3_LISTS.register({
    "id": "gold.bars", "label": "Gold bars", "family": "BANK", "loop": True,
    "store": "data/gold_bars.json",
    "what": ("Rhymed lines that aired with a finished take, kept to fire again: in dead air, and inside a "
             "round when gold.in_round comes up; which bar is System 3's roll (gold.pick). A bar is its "
             "recording, so it can only be burnt here (to the bin; /api/gold/restore puts it back)."),
    "schema": [{"key": "text", "kind": "text", "label": "the bar (its recording - not editable)"}],
    "rows": lambda: [{"id": str(b.get("key")), "text": str(b.get("text") or ""), "state": "banked",
                      "plays": int(b.get("fired") or 0), "last_played": float(b.get("last") or 0),
                      "note": " · ".join(x for x in (str(b.get("who") or ""),
                                                     ("%.1f s" % float(b["seconds"])) if b.get("seconds") else "") if x)}
                     for b in list(_gold_rows()) if b.get("key")],
    "remove": _s3_gold_burn,
})


def _s3_list_who(request: Request) -> dict[str, Any]:
    return _s3_list_who_of(str(getattr(request.client, "host", "") or ""),
                           str(request.headers.get("user-agent") or ""))


async def _s3_list_call(list_id: str, fn: Any) -> Any:
    """A store's own doors, off the loop - except a store whose writers all
    live on the loop (the gold bank), which is called where they are."""
    try:
        spec = _S3_LISTS.lists.get(str(list_id)) or {}
        return fn() if spec.get("loop") else await asyncio.to_thread(fn)
    except _S3ListError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


async def _s3_list_body(request: Request) -> dict[str, Any]:
    try:
        got = await request.json() if await request.body() else {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="not JSON: %s" % exc) from exc
    if not isinstance(got, dict):
        raise HTTPException(status_code=400, detail="a JSON object, please")
    return got


@app.get("/api/system3/lists")
async def system3_lists_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[s3-lists] every list that feeds the air, with its count and the doors it has."""
    require_read_auth(authorization)
    return {"lists": await asyncio.to_thread(_S3_LISTS.catalog)}


@app.get("/api/system3/lists/{list_id}")
async def system3_list_rows_api(list_id: str, offset: int = 0, limit: int = 50, q: str = "", state: str = "",
                                authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[s3-lists] one list's rows, paged and searchable, and its newest desk edits."""
    require_read_auth(authorization)
    return await _s3_list_call(list_id, lambda: _S3_LISTS.page(list_id, offset=offset, limit=limit,
                                                                q=q, state=state))


@app.post("/api/system3/lists/{list_id}/rows")
async def system3_list_add_api(list_id: str, request: Request,
                               authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_auth(authorization)
    body, who = await _s3_list_body(request), _s3_list_who(request)
    return await _s3_list_call(list_id, lambda: _S3_LISTS.add(list_id, body, who))


@app.put("/api/system3/lists/{list_id}/rows/{row_id}")
async def system3_list_edit_api(list_id: str, row_id: str, request: Request,
                                authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """{text} rewrites the row, {on} switches it (a list that has a switch), both at once may."""
    require_auth(authorization)
    body, who = await _s3_list_body(request), _s3_list_who(request)
    return await _s3_list_call(list_id, lambda: _S3_LISTS.edit(list_id, row_id, body, who))


@app.delete("/api/system3/lists/{list_id}/rows/{row_id}")
async def system3_list_remove_api(list_id: str, row_id: str, request: Request,
                                  authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_auth(authorization)
    who = _s3_list_who(request)
    return await _s3_list_call(list_id, lambda: _S3_LISTS.remove(list_id, row_id, who))
'''

EDITS = [
    # --- the quip shelf gets the lock it never had ----------------------------
    ("quips-lock",
     '''def sfxguy_quips_save(rows: list[str], voice: str = "") -> None:
    v = _sfxguy_voice(voice)
''',
     '''# [s3-lists] the quip shelf's one lock: the desk's table, the quips doors and
# the line votes all read-modify-write the same file.
_SFXGUY_QUIPS_LOCK = RLock()


def sfxguy_quips_save(rows: list[str], voice: str = "") -> None:
    v = _sfxguy_voice(voice)
''', 1),
    ("quips-post",
     '''    rows = sfxguy_quips(v)
    rows.extend(a for a in adds if a not in rows)
    sfxguy_quips_save(rows, v)
''',
     '''    with _SFXGUY_QUIPS_LOCK:                                   # [s3-lists]
        rows = sfxguy_quips(v)
        rows.extend(a for a in adds if a not in rows)
        sfxguy_quips_save(rows, v)
''', 1),
    ("quips-delete",
     '''    rows = [r for r in sfxguy_quips(v) if r != kill]
    sfxguy_quips_save(rows, v)
''',
     '''    with _SFXGUY_QUIPS_LOCK:                                   # [s3-lists]
        rows = [r for r in sfxguy_quips(v) if r != kill]
        sfxguy_quips_save(rows, v)
''', 1),
    ("quips-vote-up",
     '''                    quips = sfxguy_quips()
                    if text not in quips:
                        sfxguy_quips_save([text] + quips)
''',
     '''                    with _SFXGUY_QUIPS_LOCK:                   # [s3-lists]
                        quips = sfxguy_quips()
                        if text not in quips:
                            sfxguy_quips_save([text] + quips)
''', 1),
    ("quips-vote-down",
     '''                quips = sfxguy_quips()
                if text in quips:
                    sfxguy_quips_save([q for q in quips if q != text])
''',
     '''                with _SFXGUY_QUIPS_LOCK:                       # [s3-lists]
                    quips = sfxguy_quips()
                    if text in quips:
                        sfxguy_quips_save([q for q in quips if q != text])
''', 1),
    # --- the registry and its doors, after the speech bank's startup hook -----
    ("registry",
     '''@app.on_event("startup")
async def _sfxguy_ready_start() -> None:
    fire_and_forget(_sfxguy_ready_clock())
''',
     '''@app.on_event("startup")
async def _sfxguy_ready_start() -> None:
    fire_and_forget(_sfxguy_ready_clock())
''' + REGISTRY, 1),
]


def plan(_text):
    return EDITS


def state_of(text, old, new, count):
    n_old, n_new = text.count(old), text.count(new)
    if n_new >= count:
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
