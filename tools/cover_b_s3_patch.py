"""[s3-cover-b] Total-coverage gaps 2/3/4/5/9/10: the last un-rolled, un-stamped
audio becomes recorded rolls and stamped ledger rows.

Measured (s3cover census q13 at HEAD b019ad4; re-measured live at 05917b1 over
the 13 post-[s3-sfx-roll] hours):

  GAP 2  music spins: 359/24 h, music_log.jsonl carries no roll at all and the
         album popup has no data road.
  GAP 3  the sampler's clip picks (sting_due's never-heard / fresh / rotation
         legs) draw with no director and note no roll; a loose dj_sting row
         airs with no node (3/13 h live).
  GAP 4  produced/promo ad reads: 34/34 unstamped live - _air_produced_ad and
         dj_music_ad file booth rows with no node (example ledger id bd161f).
  GAP 5  manager memo reads: 28/39 unstamped live - dj_upstairs_page airs a
         book page whose row predates the [s3-roads] write-time stamp.
  GAP 9  gold bars: gold_pick's source gate keys on _s3_active() while the
         stamp keys on _s3_dice_live() (mode active_selected_roads slips
         through), and an unstampable bar still airs. 31/579 in the census.
  GAP 10 residue: loose board clips (with GAP 3), and the door-planned nodes
         above close the ad/manager rows; the pre-deploy buckets (station ID,
         track-talk intro, news/ad interjections, sfxguy) measure 0 partial
         live at 05917b1.

Files: app.py + desktop/renderer/album-popup.js (takes the REPO ROOT). Anchors cut
against HEAD 617abbc. --check exits 0 ready / 2 applied / 1 anchors missing
(naming which); --apply is idempotent, asserts anchors, writes LF atomically.
TARGET: app.py
"""
import os
import sys
import tempfile
from pathlib import Path

H = "   # [s3-cover-b]"

APP_EDITS = [
    # ------------------------------------------------------------------ GAP 2
    # The helpers, ahead of the picker that owns the decision.
    ("spin-helpers-before-the-picker",
     "def dj_next_track() -> dict[str, Any] | None:\n",
     '''# --- [s3-cover-b] GAP 2: EVERY SPIN IS A RECORDED ROLL ------------------------
#
# "MUSIC SPINS, the operator's decided FULL ROULETTE ON THE DESK." The picker
# that owns the decision is dj_next_track; each lane leaves through
# _spin_stamp with the roll that chose it (the desk's records.* rows, made
# through the [s3-dice-door]) or an honest forced note per the ONE TREE rule
# (a FIFO request, MX Live holding the air). _music_log_append writes the
# stamp on the spin's own row, so a spin joins its roll at the air door too.


def _s3_spin_roll(key: str, within: float = 60.0) -> dict[str, Any]:
    """The dice-door roll this thread last recorded under `key`, thinned for
    a spin row. {} when the station rolled its own (dice off)."""
    fn = globals().get("system3_last_roll")
    try:
        rec = fn(key) if fn else None
    except Exception:  # noqa: BLE001
        rec = None
    if (not isinstance(rec, dict)
            or time.time() - float(rec.get("at") or 0) > float(within)):
        return {}
    return {k: rec.get(k) for k in ("kind", "key", "label", "odds", "hit",
                                    "dice", "u", "index", "of", "picked")
            if rec.get(k) is not None}


def _spin_stamp(track: Any, lane: str, roll: str = "",
                note: str = "", **facts: Any) -> Any:
    """A COPY of `track` carrying its spin's record: the lane, the roll that
    let it out (read back off the dice door, never re-derived), the deal it
    joins for a rotation spin, or the honest forced note. Never raises and
    never mutates the library's own row."""
    if not isinstance(track, dict) or not track:
        return track
    out = dict(track)
    spin: dict[str, Any] = {"lane": str(lane), "at": round(time.time(), 3)}
    try:
        if roll:
            rec = _s3_spin_roll(roll)
            if rec:
                spin["roll"] = rec
        for k, v in facts.items():
            if isinstance(v, dict):
                v = {a: b for a, b in v.items() if b is not None}
            if v not in (None, "", {}):
                spin[k] = v
        if lane == "rotation":
            deal = _RADIO.get("rotation_deal_s3")
            if isinstance(deal, dict):
                spin["deal"] = {k: deal.get(k) for k in
                                ("key", "dice", "u", "at", "dealt", "loved",
                                 "loved_weight") if deal.get(k) is not None}
        if note:
            spin["why"] = str(note)[:200]
        if "roll" not in spin and "deal" not in spin and "due" not in spin:
            # the ONE TREE rule: truly unrolled = an honest forced note
            spin["forced"] = True
            spin.setdefault("why", "no roll owns this lane")
    except Exception:  # noqa: BLE001
        pass
    out["s3_spin"] = spin
    return out


def _spin_requested_by(track: Any) -> str:
    """What the station knows of who asked: the request book's last words."""
    try:
        row = read_requests().get(str((track or {}).get("id") or "")) or {}
        return str(row.get("asked_last") or "")[:120] or "a listener"
    except Exception:  # noqa: BLE001
        return "a listener"


def _spin_request_jump() -> bool:
    """The desk row over the request lane. The station's own odds are 1.0 -
    a request jumping the queue IS the request line - rolled only while the
    dice are live, so the desk can hold requests back; with the dice off the
    lane is exactly as it always was (no draw is spent)."""
    if not _s3_dice_live():
        return True
    try:
        if s3_chance("records.request_jump", 1.0,
                     "a request jumps the queue (the request line's whole point)"):
            return True
        pipeline_log("air", "[s3-cover-b] the desk held the request back this "
                            "spin - the rotation plays and the request stays queued")
        return False
    except Exception:  # noqa: BLE001
        return True


def dj_next_track() -> dict[str, Any] | None:
''', 1),

    # The live set is a spin with an honest forced note.
    ("live-set-is-a-noted-spin",
     "    _live_set = pinelive.live_track()\n"
     "    if _live_set:\n"
     "        return _live_set\n",
     "    _live_set = pinelive.live_track()\n"
     "    if _live_set:\n"
     "        return _spin_stamp(_live_set, \"live\",   # [s3-cover-b]\n"
     "                           note=\"MX Live owns the air: the set IS the record\")\n", 1),

    # The mixtape cadence becomes a desk row; the tape carries mixtape.pick.
    ("mixtape-cadence-is-a-desk-row",
     "    # Every Nth song the mail arrives: the next thing on air is a tape from\n"
     "    # the mysterious Ehm Eckx, not whatever the queue had in mind (#239).\n"
     "    if (dj[\"mixtape_every\"]\n"
     "            and _RADIO.get(\"since_tape\", 0) >= dj[\"mixtape_every\"]):\n"
     "        tape = mixtape_pick()\n"
     "        if tape:\n"
     "            _RADIO[\"since_tape\"] = 0\n"
     "            _RADIO[\"coming\"] = tape\n"
     "            return tape\n",
     "    # Every Nth song the mail arrives: the next thing on air is a tape from\n"
     "    # the mysterious Ehm Eckx, not whatever the queue had in mind (#239).\n"
     "    # [s3-cover-b] the cadence is a desk row while the dice are live: the\n"
     "    # station's own odds are the counter's verdict (1.0 when due), so the\n"
     "    # show is unchanged until the operator edits the row down.\n"
     "    _tape_due = bool(dj[\"mixtape_every\"]\n"
     "                     and _RADIO.get(\"since_tape\", 0) >= dj[\"mixtape_every\"])\n"
     "    if _tape_due and _s3_dice_live():\n"
     "        _tape_due = bool(s3_chance(\n"
     "            \"records.mixtape_due\", 1.0,\n"
     "            \"the mail arrives: every Nth record is a tape from Ehm Eckx (#239)\"))\n"
     "    if _tape_due:\n"
     "        tape = mixtape_pick()\n"
     "        if tape:\n"
     "            _RADIO[\"since_tape\"] = 0\n"
     "            tape = _spin_stamp(tape, \"mixtape\", roll=\"mixtape.pick\",   # [s3-cover-b]\n"
     "                               due=_s3_spin_roll(\"records.mixtape_due\"))\n"
     "            _RADIO[\"coming\"] = tape\n"
     "            return tape\n", 1),

    # The request lane: a roll with the requester recorded.
    ("request-jump-is-a-recorded-roll",
     "    if _RADIO[\"requests\"]:\n"
     "        track = _RADIO[\"requests\"].pop(0)\n"
     "        track = {**track, \"requested\": True}\n",
     "    if _RADIO[\"requests\"] and _spin_request_jump():   # [s3-cover-b]\n"
     "        track = {**_RADIO[\"requests\"].pop(0), \"requested\": True}\n"
     "        track = _spin_stamp(track, \"request\", roll=\"records.request_jump\",   # [s3-cover-b]\n"
     "                            requested_by=_spin_requested_by(track),\n"
     "                            note=\"requests jump the queue (FIFO front)\")\n", 1),

    # The rotation spin joins the deal.
    ("rotation-spin-joins-the-deal",
     "        track = _RADIO[\"queue\"].pop(take_at)\n",
     "        track = _spin_stamp(_RADIO[\"queue\"].pop(take_at), \"rotation\",   # [s3-cover-b]\n"
     "                            position=take_at + 1,\n"
     "                            of=len(_RADIO[\"queue\"]) + 1)\n", 1),

    # The hot-shelf swap says which road picked the stand-in.
    ("hot-shelf-swap-names-its-roll",
     "                _alt = (_RADIO[\"queue\"].pop(_alt_at) if _alt_at >= 0\n"
     "                        else _hot_shelf_pick())\n",
     "                _alt = (_RADIO[\"queue\"].pop(_alt_at) if _alt_at >= 0\n"
     "                        else _hot_shelf_pick())\n"
     "                _alt_roll = \"records.hot_shelf\" if _alt_at < 0 else \"\"   # [s3-cover-b]\n", 1),
    ("hot-shelf-take-is-stamped",
     "                        \"goes back to the top (#1156)\")\n"
     "                    track = _alt\n",
     "                        \"goes back to the top (#1156)\")\n"
     "                    track = _spin_stamp(   # [s3-cover-b]\n"
     "                        _alt, \"hot_shelf\", roll=_alt_roll,\n"
     "                        note=\"the library is crawling - a record already \"\n"
     "                             \"on the local shelf outranks the pick (#1156)\")\n", 1),

    # The plain radio picker's pop is a rotation spin too.
    ("radio-next-track-is-stamped",
     "    track = _RADIO[\"queue\"].pop(0)\n"
     "    _RADIO[\"now\"] = track\n",
     "    track = _spin_stamp(_RADIO[\"queue\"].pop(0), \"rotation\",   # [s3-cover-b]\n"
     "                        position=1, of=len(_RADIO[\"queue\"]) + 1)\n"
     "    _RADIO[\"now\"] = track\n", 1),

    # The deal keeps its record; the loved bias becomes a desk row.
    ("the-deal-keeps-its-record",
     "    _deal = random.Random(int(s3_roll(\"records.rotation_deal\", \"the order the rotation is dealt in (one roll deals the whole shuffle, #984)\") * (1 << 53)))   # [s3-dice-door]\n"
     "    _deal.shuffle(tracks)\n"
     "    if loved:\n",
     "    _deal = random.Random(int(s3_roll(\"records.rotation_deal\", \"the order the rotation is dealt in (one roll deals the whole shuffle, #984)\") * (1 << 53)))   # [s3-dice-door]\n"
     "    # [s3-cover-b] ONE roll deals the whole shuffle: keep its record, so\n"
     "    # every spin off this queue can name the roll it joins - and the loved\n"
     "    # bias is a desk row (records.loved_bias) the operator can rest.\n"
     "    _loved_w = 0.3\n"
     "    if loved and _s3_dice_live():\n"
     "        try:\n"
     "            if not s3_chance(\"records.loved_bias\", 1.0,\n"
     "                             \"a thumbs-up pulls a record toward the front \"\n"
     "                             \"of the shuffle (weight 0.3 while it holds)\"):\n"
     "                _loved_w = 1.0\n"
     "        except Exception:  # noqa: BLE001\n"
     "            _loved_w = 0.3\n"
     "    try:\n"
     "        _RADIO[\"rotation_deal_s3\"] = {\n"
     "            \"at\": round(time.time(), 3), \"dealt\": len(tracks),\n"
     "            \"loved\": len(loved or ()), \"loved_weight\": _loved_w,\n"
     "            **_s3_spin_roll(\"records.rotation_deal\")}\n"
     "    except Exception:  # noqa: BLE001\n"
     "        pass\n"
     "    _deal.shuffle(tracks)\n"
     "    if loved and _loved_w < 1.0:\n", 1),
    ("the-loved-weight-is-the-desks",
     "        tracks.sort(key=lambda t: _deal.random()   # [s3-dice-door] the same deal\n"
     "                    * (0.3 if t[\"id\"] in loved else 1.0))\n",
     "        tracks.sort(key=lambda t: _deal.random()   # [s3-dice-door] the same deal\n"
     "                    * (_loved_w if t[\"id\"] in loved else 1.0))   # [s3-cover-b]\n", 1),

    # The air door writes the spin's record on its row.
    ("the-music-log-carries-the-roll",
     "                    \"tape\": bool(track.get(\"tape\")),\n"
     "                    \"to\": _RADIO.get(\"music_to\") or \"here\",\n"
     "                }\n",
     "                    \"tape\": bool(track.get(\"tape\")),\n"
     "                    \"to\": _RADIO.get(\"music_to\") or \"here\",\n"
     "                }\n"
     "                if isinstance(track.get(\"s3_spin\"), dict):   # [s3-cover-b]\n"
     "                    row[\"s3\"] = dict(track[\"s3_spin\"])\n", 1),

    # The album popup's data road.
    ("the-spins-read-api",
     "@app.post(\"/api/dj/requests/forget\")\n",
     '''@app.get("/api/music/spins/{track_id}")
async def music_spins_api(
    track_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[s3-cover-b] GAP 2: one record's spins, each with the roll it joined -
    the album popup's data road (the full breakdown card can come later)."""
    require_read_auth(authorization)
    want = str(track_id or "")

    def _read() -> list[dict[str, Any]]:
        try:
            lines = MUSIC_LOG_PATH.read_text().splitlines()
        except Exception:  # noqa: BLE001
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-4000:]:
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if row.get("stop") or str(row.get("id") or "") != want:
                continue
            out.append({k: row.get(k) for k in
                        ("at", "id", "title", "artist", "tape", "to", "s3")
                        if row.get(k) is not None})
        return out[-200:]

    rows = await asyncio.to_thread(_read)
    lanes: dict[str, int] = {}
    for r in rows:
        lane = str((r.get("s3") or {}).get("lane") or "untraced")
        lanes[lane] = lanes.get(lane, 0) + 1
    return {"id": want, "spins": rows, "count": len(rows), "lanes": lanes}


@app.get("/api/music/spins")
async def music_spins_recent_api(
    limit: int = 60,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[s3-cover-b] the latest spins with their rolls, oldest first."""
    require_read_auth(authorization)
    most = max(1, min(500, int(limit or 60)))

    def _read() -> list[dict[str, Any]]:
        try:
            lines = MUSIC_LOG_PATH.read_text().splitlines()
        except Exception:  # noqa: BLE001
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-(most * 3):]:
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if row.get("stop"):
                continue
            out.append({k: row.get(k) for k in
                        ("at", "id", "title", "artist", "tape", "to", "s3")
                        if row.get(k) is not None})
        return out[-most:]

    rows = await asyncio.to_thread(_read)
    traced = sum(1 for r in rows if isinstance(r.get("s3"), dict))
    return {"spins": rows, "count": len(rows), "traced": traced}


@app.post("/api/dj/requests/forget")
''', 1),

    # ------------------------------------------------------------- GAPS 3/4/5
    # One shared door: a node planned where a made thing reaches the air.
    ("the-door-line-helper",
     "async def dj_sting(to_box: bool, after: str = \"\", who: str = \"\",\n",
     '''async def _s3_door_line(road: str, who: str = "dj", seat: str = "",
                        name: str = "", context: str = "", text: str = "",
                        bank: bool = True) -> dict[str, Any] | None:
    """[s3-cover-b] GAPs 3/4/5: a node planned AT AN AIRING DOOR for a thing
    that reaches the air without one - a produced spot, a music-bed spot, an
    older page from upstairs, a loose board clip. The road's plan absorbs the
    task's fresh rolls, the words are bound, and the stamp is returned for
    the ledger row. None while System 3 does not answer: the row then stays
    honestly unstamped rather than wearing an invented one."""
    direct = globals().get("system3_direct_line")
    if not direct:
        return None
    # The node is planned for words ALREADY written: it must not become the
    # conversation a later prompt on this task records its blocks on.
    _writing = globals().get("system3_writing_for")
    try:
        _was = _writing.get() if _writing is not None else None
    except Exception:  # noqa: BLE001
        _writing = _was = None
    try:
        kw: dict[str, Any] = {"road": road, "who": who, "dj": dj_settings(),
                              "context": str(context or "")[:400],
                              "text": str(text or "")[:600],
                              "bank": bool(bank)}
        if seat:
            kw["seat"] = seat
        if name:
            kw["name"] = name
        _h = await direct(**kw)
        if _h is None or not (getattr(_h, "stamp", None) or {}).get("conversation_id"):
            return None
        bind = globals().get("system3_bind_line")
        if bind and text:
            try:
                bind(_h, str(text))
            except Exception:  # noqa: BLE001
                pass
        return dict(_h.stamp)
    except Exception as _exc:  # noqa: BLE001
        pipeline_log("system3", "a door line could not be planned on the "
                     "%s road - the row airs unstamped, and says so" % road,
                     extra=("%s: %s" % (type(_exc).__name__, _exc))[:200])
        return None
    finally:
        if _writing is not None:
            try:
                _writing.set(_was)
            except Exception:  # noqa: BLE001
                pass


async def _s3_loose_board_stamp(row: dict[str, Any], sample: Any) -> None:
    """[s3-cover-b] GAPs 3/10: a board clip aired outside any round (the
    dead-air sampler, the forced door, the cycle) gets a node of its own on
    the interject road, seat D, carrying the sampler's rolls - so its ledger
    row names a conversation like every other airing."""
    try:
        if not _s3_dice_live():
            return
        got = row.get("system3")
        if isinstance(got, dict) and got.get("conversation_id"):
            return
        stamp = await _s3_door_line(
            "interject", who="board", seat="D", name="The SFX board",
            context=("the board punctuates outside a round: "
                     + str(row.get("text") or Path(str(sample)).stem))[:300])
        if not stamp:
            return
        if isinstance(row.get("sfx_roll"), dict):
            stamp["sfx_roll"] = dict(row["sfx_roll"])
        if row.get("poster"):
            stamp["poster"] = str(row["poster"])
        row["system3"] = stamp
    except Exception:  # noqa: BLE001
        pass


async def dj_sting(to_box: bool, after: str = "", who: str = "",
''', 1),

    # ------------------------------------------------------------------ GAP 3
    # The sampler's three legs draw with the dice and note their roll.
    ("sampler-unheard-leg-rolls",
     "        _pick = (unrepeated(_pool, \"sting\",\n"
     "                            keep=sting_keep(len(set(_pool))))\n"
     "                 if _pool else None)                             # #1223\n",
     "        _pick = (unrepeated(_pool, \"sting\",\n"
     "                            keep=sting_keep(len(set(_pool))),\n"
     "                            director=_S3ClipDice(\"sfx.sampler\", \"which clip the sampler drops (never-heard first)\"))   # [s3-cover-b]\n"
     "                 if _pool else None)                             # #1223\n", 1),
    ("sampler-unheard-leg-notes",
     "            try:\n"
     "                _STING_DRAW_MEMO.get(\"unheard\", set()).discard(_pick)   # [#1188] drawn = heard\n",
     "            _sfx_roll_note(_pick, \"sampler\",   # [s3-cover-b]\n"
     "                           {\"label\": Path(_pick).parent.name,\n"
     "                            \"by\": \"the never-heard-first road (#1251)\"},\n"
     "                           _s3_sfx_rolled(\"sfx.sampler\", Path(_pick).stem), 1)\n"
     "            try:\n"
     "                _STING_DRAW_MEMO.get(\"unheard\", set()).discard(_pick)   # [#1188] drawn = heard\n", 1),
    ("sampler-fresh-leg-rolls",
     "        names = unrepeated(fresh_pool, \"sting\",\n"
     "                           keep=sting_keep(len(set(fresh_pool))))  # #1223\n",
     "        names = unrepeated(fresh_pool, \"sting\",\n"
     "                           keep=sting_keep(len(set(fresh_pool))),\n"
     "                           director=_S3ClipDice(\"sfx.sampler\", \"which clip the sampler drops (a fresh one first)\"))  # #1223 [s3-cover-b]\n"
     "        if names:   # [s3-cover-b]\n"
     "            _sfx_roll_note(names, \"sampler\",\n"
     "                           {\"label\": Path(names).parent.name,\n"
     "                            \"by\": \"the fresh-first road (#1062)\"},\n"
     "                           _s3_sfx_rolled(\"sfx.sampler\", Path(names).stem), 1)\n", 1),
    ("sampler-rotation-leg-rolls",
     "    names = unrepeated(names_pool, \"sting\",\n"
     "                       keep=sting_keep(len(set(names_pool))))      # #1223\n"
     "    return Path(names) if names else None\n",
     "    names = unrepeated(names_pool, \"sting\",\n"
     "                       keep=sting_keep(len(set(names_pool))),\n"
     "                       director=_S3ClipDice(\"sfx.sampler\", \"which clip the sampler drops (the rotation)\"))      # #1223 [s3-cover-b]\n"
     "    if names:   # [s3-cover-b]\n"
     "        _sfx_roll_note(names, \"sampler\",\n"
     "                       {\"label\": Path(names).parent.name,\n"
     "                        \"by\": \"the sampler's rotation (#1223)\"},\n"
     "                       _s3_sfx_rolled(\"sfx.sampler\", Path(names).stem), 1)\n"
     "    return Path(names) if names else None\n", 1),

    # A loose sting row carries its roll and its node.
    ("loose-sting-row-is-stamped",
     "    _RADIO[\"chat\"].append(_sting_row)\n",
     "    _sfx_roll_carry(_sting_row, sample)                    # [s3-cover-b] GAP 3\n"
     "    await _s3_loose_board_stamp(_sting_row, sample)        # [s3-cover-b] GAP 10\n"
     "    _RADIO[\"chat\"].append(_sting_row)\n", 1),

    # ------------------------------------------------------------------ GAP 4
    ("produced-spot-plans-at-the-door",
     "    if isinstance(entry.get(\"system3\"), dict):               # [s3-roads]\n"
     "        booth_row[\"system3\"] = dict(entry[\"system3\"])\n",
     "    if isinstance(entry.get(\"system3\"), dict):               # [s3-roads]\n"
     "        booth_row[\"system3\"] = dict(entry[\"system3\"])\n"
     "    else:                                                    # [s3-cover-b] GAP 4\n"
     "        # A produced spot that reaches the air without a node gets one AT\n"
     "        # THE DOOR: the read planned on the ad_spot road, the task's fresh\n"
     "        # rolls (which spot, the rerun, the cupboard break) absorbed onto\n"
     "        # it, and the stamp lands on this very ledger row (census id\n"
     "        # bd161f's shape: kind=ad, round='', no s3).\n"
     "        _door_stamp = await _s3_door_line(\n"
     "            \"ad_spot\", who=\"dj\",\n"
     "            context=(\"a produced spot: \"\n"
     "                     + str(entry.get(\"product\") or \"a produced spot\")),\n"
     "            text=str(entry.get(\"text\") or label))\n"
     "        if _door_stamp:\n"
     "            booth_row[\"system3\"] = _door_stamp\n", 1),
    ("music-bed-spot-plans-at-the-door",
     "    ad_booth_row(line, product,\n"
     "                 ad_id=str((entry or {}).get(\"id\") or \"\"),\n"
     "                 media=str((play or {}).get(\"path\") or \"\"),\n"
     "                 sig=str((play or {}).get(\"sig\") or \"\"),\n"
     "                 voice=forced or \"\", air_at=_ad_at)\n",
     "    _bed_row = ad_booth_row(line, product,   # [s3-cover-b] GAP 4\n"
     "                            ad_id=str((entry or {}).get(\"id\") or \"\"),\n"
     "                            media=str((play or {}).get(\"path\") or \"\"),\n"
     "                            sig=str((play or {}).get(\"sig\") or \"\"),\n"
     "                            voice=forced or \"\", air_at=_ad_at)\n"
     "    # [s3-cover-b] the music-bed spot never passes dj_speak, so its row\n"
     "    # is stamped here, at its own door, on the ad_spot road.\n"
     "    if isinstance(_bed_row, dict) and not _bed_row.get(\"system3\"):\n"
     "        _bed_stamp = await _s3_door_line(\n"
     "            \"ad_spot\", who=\"dj\",\n"
     "            context=\"a music-bed spot: \" + str(product or \"\"), text=line)\n"
     "        if _bed_stamp:\n"
     "            _bed_row[\"system3\"] = _bed_stamp\n", 1),

    # ------------------------------------------------------------------ GAP 5
    ("older-page-gets-the-same-stamping",
     "    air_at = (float(page_clip.get(\"broadcast_ms\") or 0) / 1000.0\n"
     "              if delivery_id else started) or started\n"
     "    entry = {\n",
     "    air_at = (float(page_clip.get(\"broadcast_ms\") or 0) / 1000.0\n"
     "              if delivery_id else started) or started\n"
     "    # [s3-cover-b] GAP 5: a page written before its road was System 3's\n"
     "    # (the older book, the verbatim memo) airs with a node planned HERE -\n"
     "    # the same stamping dj_upstairs_write gives a fresh page - and the\n"
     "    # stamp is kept on the page row so its reruns name the same node.\n"
     "    if not isinstance(made.get(\"system3\"), dict):\n"
     "        _page_stamp = await _s3_door_line(\n"
     "            \"upstairs\", who=\"manager\", seat=\"C\", name=boss,\n"
     "            context=str(made.get(\"gripe\") or \"a memo from upstairs\"),\n"
     "            text=spoken)\n"
     "        if _page_stamp:\n"
     "            made[\"system3\"] = dict(_page_stamp)\n"
     "            try:\n"
     "                upstairs_update(str(made.get(\"id\") or \"\"),\n"
     "                                system3=dict(_page_stamp))\n"
     "            except Exception:  # noqa: BLE001\n"
     "                pass\n"
     "    entry = {\n", 1),

    # ------------------------------------------------------------------ GAP 9
    ("gold-gate-holds-for-every-live-mode",
     "        if _s3_active():\n"
     "            pool = [r for r in pool if gold_source(r)]\n",
     "        if _s3_active() or _s3_dice_live():   # [s3-cover-b] GAP 9\n"
     "            # The stamp keys on the DICE being live (gold_air_stamp), so\n"
     "            # the source gate must too: under active_selected_roads a bar\n"
     "            # with no System 3 turn behind it used to slip out unstamped.\n"
     "            pool = [r for r in pool if gold_source(r)]\n", 1),
    ("gold-bar-stamps-or-is-refused",
     "        _door = _dj_speak_floorless if floorless else dj_speak\n"
     "        try:\n"
     "            # #1237: a bar off the bank is the BANK filling a hole, not\n"
     "            # the round whose window the hole is in.\n"
     "            out = await _door(\"interject\", None, line=text,\n"
     "                              who=str(bar.get(\"who\") or \"dj\"),\n"
     "                              checked=True, sting=False, clip=clip,\n"
     "                              round_as=\"gold\",\n"
     "                              # [s3-banks-roll] the bar is its source turn's node on the air\n"
     "                              system3=(gold_air_stamp(bar, \"\" if bars else \"gold.run\",\n"
     "                                                      _t_run, _t_pick)\n"
     "                                       if _s3_dice_live() else None))\n",
     "        _door = _dj_speak_floorless if floorless else dj_speak\n"
     "        # [s3-cover-b] GAP 9: while the dice are live a bar either airs\n"
     "        # with its stamp (the desk chance, gold.pick, its source turn) or\n"
     "        # it does not air - an unstampable bar is refused per the gate and\n"
     "        # rested, and the run ends there (the gap goes to the next rung -\n"
     "        # never a hot loop on the event loop).\n"
     "        _bar_stamp = (gold_air_stamp(bar, \"\" if bars else \"gold.run\",\n"
     "                                     _t_run, _t_pick)\n"
     "                      if _s3_dice_live() else None)\n"
     "        if _s3_dice_live() and not _bar_stamp:\n"
     "            pipeline_log(\"air\", \"[s3-cover-b] a gold bar with no System 3 \"\n"
     "                                \"turn behind it was refused at the door: \"\n"
     "                         + str(bar.get(\"text\") or \"\")[:70])\n"
     "            try:\n"
     "                bar[\"last\"] = time.time()      # rested, so the pick moves on\n"
     "            except Exception:  # noqa: BLE001\n"
     "                pass\n"
     "            break\n"
     "        try:\n"
     "            # #1237: a bar off the bank is the BANK filling a hole, not\n"
     "            # the round whose window the hole is in.\n"
     "            out = await _door(\"interject\", None, line=text,\n"
     "                              who=str(bar.get(\"who\") or \"dj\"),\n"
     "                              checked=True, sting=False, clip=clip,\n"
     "                              round_as=\"gold\",\n"
     "                              # [s3-banks-roll] the bar is its source turn's node on the air\n"
     "                              system3=_bar_stamp)\n", 1),
]

JS_EDITS = [
    ("the-spin-dice-data-road",
     "  function readHeroDetails(box, track, data) {\n",
     '''  function readSpinDice(box, track) {
    // [s3-cover-b] GAP 2: the record's spins with the roll each joined - the
    // data road for the roulette card (the full breakdown card comes later).
    if (!track || !track.id) return;
    var serial = (box.__spinSerial || 0) + 1;
    box.__spinSerial = serial;
    api().get('/api/music/spins/' + encodeURIComponent(track.id)).then(function (got) {
      if (!back || !box.isConnected || serial !== box.__spinSerial) return;
      box.__spinDice = got || {};
      paintSpinDice(box, got || {});
    }, function () { /* no spins on the log yet is a fine answer */ });
  }

  function paintSpinDice(box, got) {
    var line = box.querySelector('.pa-spin-dice');
    if (!line) {
      var detail = box.querySelector('.pa-album-detail');
      if (!detail || !detail.parentNode) return;
      line = make('p', 'pa-spin-dice');
      detail.parentNode.insertBefore(line, detail.nextSibling);
    }
    var n = (got && got.count) || 0;
    if (!n) { line.textContent = ''; line.hidden = true; return; }
    var lanes = (got && got.lanes) || {};
    var bits = Object.keys(lanes).map(function (k) { return lanes[k] + ' ' + k; });
    var spins = (got && got.spins) || [];
    var s3 = (spins[spins.length - 1] || {}).s3 || {};
    var tail = s3.lane ? (' - last: ' + s3.lane
      + (s3.roll && s3.roll.dice != null ? ', dice ' + s3.roll.dice : '')
      + (s3.deal && s3.deal.dice != null ? ', deal dice ' + s3.deal.dice : '')) : '';
    line.hidden = false;
    line.textContent = 'Roulette: ' + n + ' spin' + (n === 1 ? '' : 's') + ' on the log ('
      + bits.join(', ') + ')' + tail;
  }

  function readHeroDetails(box, track, data) {
''', 1),
    ("the-hero-asks-for-the-spins",
     "    api().get('/api/music/track/' + encodeURIComponent(track.id)).then(function (full) {\n"
     "      if (!back || serial !== box.__detailSerial) return;\n"
     "      updateHero(box, Object.assign({}, track, full || {}), data);\n"
     "    }, function () { /* the album index still has enough to remain useful */ });\n"
     "  }\n",
     "    api().get('/api/music/track/' + encodeURIComponent(track.id)).then(function (full) {\n"
     "      if (!back || serial !== box.__detailSerial) return;\n"
     "      updateHero(box, Object.assign({}, track, full || {}), data);\n"
     "    }, function () { /* the album index still has enough to remain useful */ });\n"
     "    readSpinDice(box, track);   // [s3-cover-b]\n"
     "  }\n", 1),
]

FILES = {"app.py": APP_EDITS, "desktop/renderer/album-popup.js": JS_EDITS}


def plan(text, fname="app.py"):
    return list(FILES[fname])


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text, fname="app.py"):
    applied, missing = 0, []
    for name, old, new, count in plan(text, fname):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s: %s (%s)" % (fname, name, state))
    return applied, missing


def _read(path):
    return Path(path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def apply(root):
    texts = {f: _read(os.path.join(root, f)) for f in FILES}
    total, done, missing = 0, 0, []
    for f, text in texts.items():
        a, m = check(text, f)
        done += a
        total += len(FILES[f])
        missing += m
    if done == total:
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for f, text in texts.items():
        for name, old, new, count in FILES[f]:
            if state_of(text, old, new, count) == "applied":
                continue
            text = text.replace(old, new)
        path = Path(root) / f
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        os.replace(tmp, path)
    return 0


def main(argv):
    root = next((a for a in argv if not a.startswith("--")), ".")
    if os.path.isfile(root):
        root = os.path.dirname(os.path.abspath(root)) or "."
    if "--apply" in argv:
        code = apply(root)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    total, done, missing = 0, 0, []
    for f in FILES:
        a, m = check(_read(os.path.join(root, f)), f)
        done += a
        total += len(FILES[f])
        missing += m
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if done == total:
        print("already applied")
        return 2
    print("ready")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
