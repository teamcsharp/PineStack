"""[mp4only] The picture-share switch at 100 means MP4 ONLY, on every road;
one clip sounds at a time on the page; a clip no player can open is never
drawn again.

"I don't know why MP threes are still playing, but the switch is set to play
 only MP four."            "clips play over each other (two at once)"

Measured 2026-09-29 03:29-04:07 (37.5 min, dj.sfx_video_share = 100):
  - sfx_history: gap road 119 .mp3 / 78 .mp4 / 1 .mov; cadence 22 .mp4;
    record 3 .mp4. 84 gap fills: 42 bursts of 3 went [mp4, mp3, mp3] - the
    burst's first sting comes through sting_due (which honours the share),
    the extras are refused by sting_due's own rest clock and fall to
    _sfx_any(), which was AUDIO ONLY by design (#1263).
  - playout: 221 overlapping page reservations in the hour, 57 of them an
    MP4 sting with an MP3 sting stamped on top. page_reservation_repair()
    skips every video row when it rebuilds _PAGE_AIR_UNTIL, so the next
    append stamps at now+lead while the MP4 is still sounding on the tube.
  - 5 "undecodable" receipts: 3 clips; the /sfx route answered 404 because
    the files are gone (the whole patrice folder: 53,364 book rows, 31,413
    of them MP4, still playable=1) - a 404 reads as MEDIA_ERR 4 on a <video>.

What changes (app.py, plus a receipt hook in sfx_display.py):
  [mp4only-core]     sfx_mp4_only(), sfx_clip_refusal(path) - THE filter
                     ("mp4-only" | "undecodable" | ""), the quarantine
                     (sfx_quarantine, data/sfx_quarantine.jsonl, the book row
                     playable=0, a vanished folder stood down whole), the
                     receipt hook, and GET /api/sfx/mp4-only.
  [mp4only-match]    sfx_match_sting_pick counts removals by that filter
                     under "mp4-only" / "undecodable" in the origin record.
  [mp4only-due]      sting_due narrows its population through the filter
                     (the ratio draw let a pure-audio side through).
  [mp4only-any]      _sfx_any() - the gap road, dj_sting's force fallback and
                     its recency re-pick - draws a sounding MP4 under the
                     switch; nothing found = None, flagged, and the gap
                     filler's next rung (the SFX Guy talking) answers. The
                     two ad-bed mixes pass mix=True and keep the audio pool.
  [mp4only-gate]     dj_sting refuses any sample the filter refuses (every
                     sting road passes it: gap, record, seat door, rescue),
                     swapping through _sfx_any() when forced.
  [mp4only-cadence]  the two-line cadence tries MP4 only under the switch;
                     a miss leaves the optional slot empty (never silence -
                     it is welded into a round that speaks) and says so.
  [mp4only-flow]     the schedule graph's SFX beat does not plan an MP3.
  [mp4only-overlap]  page_reservation_repair keeps a sounding MP4 sting's
                     span on the page cursor, so nothing is stamped over it
                     and the gap filler's "air already sold" gate sees it.
  [mp4only-gone]     the /sfx route quarantines a clip whose file is gone.
  [mp4only-decode]   _as_wav quarantines a clip ffmpeg calls invalid data.
  [mp4only-published] dj_sting writes a page sting "published", not "page".
  [mp4only-heard]    page_playback_ack: the sting's own audible receipt
                     (clip["line"] = its script row) stamps heard_ack_at and
                     aired="page" (193/193 page stings had no heard receipt).

--check exits 0 ready / 2 applied / 1 missing; --apply writes atomically.
ON THE HOST, from a fresh copy:  python3 tools/mp4only_patch.py --check .
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patchlib_air import run  # noqa: E402

CORE = '''# [mp4only-core] ONE FILTER EVERY SFX ROAD ASKS.
#
# "I don't know why MP threes are still playing, but the switch is set to
#  play only MP four." The dial is sfx_video_share; at 100 (or with the
#  endless set on) it means MP4 ONLY - not "MP4 first". Four roads read it
#  differently: sting_due narrowed its pool (and let a pure-audio side
#  through), _sfx_any() was audio-only by design (#1263), the cadence tried
#  MP4 then fell back to MP3 (#1462), the schedule graph planned an MP3 when
#  the video shelf missed. Measured 2026-09-29: 119 MP3 of 198 gap stings in
#  37 minutes with the dial at 100.
#
# sfx_clip_refusal() is the one question: "" when a clip may air, else the
# rule that removes it - "mp4-only" or "undecodable" (quarantined, or its
# file is gone). The operator's own SFX buttons do not ask it: a person
# pressing a clip outranks the dial.
_MP4ONLY: dict[str, Any] = {"refused": 0, "swapped": 0, "left_empty": 0,
                            "quarantined": 0, "by_road": {}, "last": "",
                            "at": 0.0}
_SFX_QUARANTINED: set[str] = set()
_SFX_GONE_FOLDERS: set[str] = set()
_SFX_QUARANTINE_LOADED = [False]
_SFX_QUARANTINE_LOCK = RLock()
_SFX_RECEIPT_STRIKES: dict[str, set] = {}
_SFX_UNDECODABLE_RE = re.compile(
    r"invalid data|error splitting|error while decoding|error code|corrupt|"
    r"could not find codec|decoding error|not supported|moov atom",
    re.IGNORECASE)


def sfx_mp4_only() -> bool:
    """The switch: the picture share at 100 (the endless set holds it there)."""
    try:
        return sfx_video_share() >= 100
    except Exception:  # noqa: BLE001
        return False


def _sfx_quarantine_path() -> Path:
    return data_path("sfx_quarantine.jsonl")


def _sfx_quarantine_load() -> None:
    if _SFX_QUARANTINE_LOADED[0]:
        return
    with _SFX_QUARANTINE_LOCK:
        if _SFX_QUARANTINE_LOADED[0]:
            return
        try:
            for line in _sfx_quarantine_path().read_text(
                    encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("sid"):
                    _SFX_QUARANTINED.add(str(row["sid"]))
                if row.get("folder_gone") and row.get("folder"):
                    _SFX_GONE_FOLDERS.add(str(row["folder"]))
        except OSError:
            pass
        _SFX_QUARANTINE_LOADED[0] = True


def sfx_quarantined(sid: str) -> bool:
    _sfx_quarantine_load()
    return str(sid or "") in _SFX_QUARANTINED


def sfx_quarantine(sid: str, why: str, path: Any = None, by: str = "") -> bool:
    """Never draw this clip again: the book row goes playable=0 (every book
    pick has playable = 1 in its where clause), the in-memory set answers
    the matcher's index and the walked pool, and a row goes to
    data/sfx_quarantine.jsonl - the list a transcode job works from. When
    the clip's whole FOLDER is gone from the share, the folder is stood down
    in one statement. Blocking (sqlite, one stat): call it off the loop."""
    sid = str(sid or "")
    if not sid or not path:
        return False
    try:
        # only the station's own library: a scratch file (a test's tmp, a
        # listener upload) is never written into the quarantine list
        if not any(Path(str(path)).is_relative_to(root)
                   for root in (SFX_ROOT, SFX_LOCAL_ROOT)):
            return False
    except Exception:  # noqa: BLE001
        return False
    _sfx_quarantine_load()
    folder, folder_gone = "", False
    if path:
        try:
            folder = str(Path(str(path)).parent)
            folder_gone = bool(folder) and folder not in _SFX_GONE_FOLDERS \\
                and not Path(folder).is_dir()
        except OSError:
            folder_gone = False
    with _SFX_QUARANTINE_LOCK:
        if sid in _SFX_QUARANTINED and not folder_gone:
            return False
        _SFX_QUARANTINED.add(sid)
        if folder_gone:
            _SFX_GONE_FOLDERS.add(folder)
    stood = 0
    try:
        stood = sfx_db_stand_down([sid])
        if folder_gone:
            with _SFX_DB_LOCK:
                con = sfx_db()
                cur = con.execute(
                    "UPDATE clips SET playable = 0 WHERE path >= ? AND path < ?",
                    (folder + "/", folder + "0"))
                con.commit()
                stood += int(cur.rowcount or 0)
    except Exception:  # noqa: BLE001
        pass
    row = {"at": round(time.time(), 3), "sid": sid,
           "path": str(path or "")[:400], "why": str(why or "")[:300],
           "by": str(by or "")[:80], "stood_down": stood}
    if folder_gone:
        row.update({"folder": folder, "folder_gone": True})
    try:
        with _SFX_QUARANTINE_LOCK:
            with _sfx_quarantine_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\\n")
    except OSError:
        pass
    _MP4ONLY["quarantined"] = int(_MP4ONLY.get("quarantined") or 0) + 1
    try:
        pipeline_log("air", "[mp4only] quarantined %s - %s%s (%d book row(s) "
                     "stood down)" % (Path(str(path or sid)).name, why,
                                      "; its folder is gone from the share"
                                      if folder_gone else "", stood))
    except Exception:  # noqa: BLE001
        pass
    return True


def sfx_clip_refusal(path: Any, check_file: bool = False) -> str:
    """THE filter. "" when the clip may air; else the rule that removes it.
    check_file adds one stat (blocking: call off the loop) and quarantines a
    clip whose file is gone."""
    if not path:
        return "undecodable"
    try:
        p = Path(str(path))
        if sfx_mp4_only() and not sfx_is_video(p):
            return "mp4-only"
        if sfx_quarantined(sfx_id(p)) or str(p.parent) in _SFX_GONE_FOLDERS:
            return "undecodable"
        if check_file and not p.is_file():
            sfx_quarantine(sfx_id(p), "the file is gone from the share", p,
                           "the sting door")
            return "undecodable"
    except OSError:
        return "undecodable" if check_file else ""
    except Exception:  # noqa: BLE001
        return ""
    return ""


def mp4only_note(road: str, what: str, clip: Any = "") -> None:
    """Count it and say it, per road. what: refused-by-rule / swapped /
    left_empty. left_empty is the flag: the switch left a road with no
    picture clip and the road aired nothing rather than an MP3."""
    try:
        road = str(road or "sting")[:40]
        key = "left_empty" if what == "left_empty" else (
            "swapped" if what == "swapped" else "refused")
        _MP4ONLY[key] = int(_MP4ONLY.get(key) or 0) + 1
        per = _MP4ONLY.setdefault("by_road", {}).setdefault(road, {})
        per[what] = int(per.get(what) or 0) + 1
        _MP4ONLY["last"] = "%s: %s %s" % (road, what,
                                          Path(str(clip)).name if clip else "")
        _MP4ONLY["at"] = time.time()
        if what == "left_empty":
            pipeline_log("air", "[mp4only] the %s road found no picture clip "
                         "- nothing aired from it rather than an MP3" % road)
    except Exception:  # noqa: BLE001
        pass


def _sting_heard(line_id: str, delivery_id: str, at: float) -> bool:
    """(mp4only) A page sting is AIRED when a player says so: its own
    element reported playing/ended, audible, progressing (the same test the
    dialogue has, page_playback_ack). Until then the row says "published".
    Measured 2026-09-29: 193 of 193 page stings in the air log had no heard
    receipt - the audit's "aired-unconfirmed, heard 0" was every one."""
    for row in reversed(_RADIO.get("chat") or []):
        if str(row.get("id") or "") != line_id:
            continue
        if not row.get(HEARD_STAMP):
            row[HEARD_STAMP] = float(at)
            row[HEARD_STAMP_BY] = "page"
        row["aired"] = "both" if row.get("aired") in ("box", "both") else "page"
        row["delivery_id"] = delivery_id
        return True
    return False


def sfx_quarantine_receipts(body: Any) -> int:
    """[mp4only-undecodable] The display receipts' hook (sfx_display.py).
    MEDIA_ERR_DECODE (3) quarantines at once. MEDIA_ERR_SRC_NOT_SUPPORTED (4)
    is also what a 404 looks like to a <video>, so the file is looked at: gone
    quarantines; present needs a second player to say the same."""
    got = 0
    rows = (body or {}).get("rows") if isinstance(body, dict) else None
    player = str((body or {}).get("player") or "") if isinstance(body, dict) else ""
    for row in rows if isinstance(rows, list) else []:
        try:
            code = int((row or {}).get("error_code") or 0)
        except (TypeError, ValueError):
            code = 0
        if code not in (3, 4):
            continue
        url = str((row or {}).get("url") or "")
        m = re.search(r"/sfx/([a-f0-9]{16})", url)
        sid = str((row or {}).get("sfx") or (m.group(1) if m else ""))
        if not re.fullmatch(r"[a-f0-9]{16}", sid) or sfx_quarantined(sid):
            continue
        path = sfx_by_id(sid)
        who = str((row or {}).get("player") or player or "a player")
        why = str((row or {}).get("error") or "undecodable")[:160]
        if code == 3 or path is None or not Path(str(path)).is_file():
            got += int(sfx_quarantine(sid, "%s said: %s" % (who, why), path,
                                      "display receipts"))
            continue
        seen = _SFX_RECEIPT_STRIKES.setdefault(sid, set())
        seen.add(who)
        if len(seen) >= 2:
            got += int(sfx_quarantine(sid, "%s said: %s" % (
                " and ".join(sorted(seen)), why), path, "display receipts"))
    return got


'''

MATCH_OLD = '''    # [s3-account] how many each of the station's rules removed, for the clip's origin
    _removed = {"the picture share": 0, "banned": 0, "weighted out (#645)": 0,
'''
MATCH_NEW = '''    # [mp4only-match] THE ONE FILTER FIRST, on the tied peers themselves, so
    # an MP3 is never a candidate under the switch and the origin record
    # names the rule that removed it ("mp4-only" / "undecodable").
    _mp4_removed = {"mp4-only": 0, "undecodable": 0}
    _tied_ok = []
    for _mp4_path, _mp4_s, _mp4_cand in sfx_match_rows(tied):
        _mp4_why = sfx_clip_refusal(_mp4_path)
        if _mp4_why:
            _mp4_removed[_mp4_why] = int(_mp4_removed.get(_mp4_why) or 0) + 1
        else:
            _tied_ok.append(_mp4_cand)
    tied = _tied_ok
'''
MATCH2_OLD = '''    if not survivors:
        _SFX_MATCH["fell_back"] = int(_SFX_MATCH.get("fell_back") or 0) + 1
        return None
    # THE STATION'S OWN RECENCY RING, under the station's own key. #1223
'''
MATCH2_NEW = '''    _removed.update({k: v for k, v in _mp4_removed.items() if v})   # [mp4only-match-origin]
'''

DUE_ANCHOR = '''    _allowed = set(names_pool)
    # [#1251] MATCHED TO THE LINE, WHEN THE SWITCH IS ON.
'''
DUE_NEW = '''    _allowed = set(names_pool)
    # [mp4only-due] "A side with nothing in it is not narrowed to" is right
    # for a dial and wrong for the switch: at 100 an MP3 is never drawn here.
    if sfx_mp4_only():
        _kept = [n for n in names_pool if not sfx_clip_refusal(n)]
        if not _kept:
            mp4only_note("sampler", "left_empty")
            return None
        if len(_kept) != len(names_pool):
            _allowed = set(_kept)
            pool = [p for p in pool if str(p) in _allowed]
            fresh = {n for n in fresh if n in _allowed}
            names_pool = _kept
        _want_video = True
'''

ANY_OLD = '''def _sfx_any() -> Path | None:
    """A short unbanned sample, ignoring the rate/gap gate (#464) — for
'''
ANY_NEW = '''def _sfx_any(mix: bool = False) -> Path | None:
    """[mp4only-any] THE GAP ROAD'S CLIP, THROUGH THE ONE FILTER.

    The dead-air filler's burst is a sting from sting_due and then extras
    that sting_due refuses (its own rest clock), so the extras all came from
    here - and here was audio only. With the switch at MP4 only that made
    the burst [mp4, mp3, mp3], 42 times in 37 minutes. Under the switch this
    draws a SOUNDING picture clip (the rescue road's #1302 rule: short, not a
    measured silence), line-matched first as #1386 asks, then the book, then
    the walked video pool. Nothing found is None - flagged - and the gap
    filler's next rung, the SFX Guy talking, answers the hole. `mix` is the
    ad bed's 2.2 s under a voice: it keeps the audio pool."""
    if mix or not sfx_mp4_only():
        return _sfx_any_audio()
    try:
        if sfx_match_on(False) and sfx_match_ready():
            _hit = sfx_match_sting_pick("", want_video=True)
            _p = (_hit[0] if isinstance(_hit, tuple) and _hit else _hit)
            if _p and not sting_recent(str(_p)) and not sfx_clip_refusal(_p):
                return Path(str(_p))
    except Exception:  # noqa: BLE001
        pass
    banned = sfx_bans()
    seen: set[str] = set()
    for _ in range(14):
        try:
            got = sfx_db_pick(video=True)
        except Exception:  # noqa: BLE001
            got = None
        if not got or str(got) in seen:
            continue
        seen.add(str(got))
        try:
            if (sfx_id(got) in banned or sfx_clip_refusal(got)
                    or sfx_video_on_cooldown(sfx_id(got))
                    or sting_recent(str(got))
                    or not sfx_short(got) or sfx_is_silent(got)):
                continue
        except Exception:  # noqa: BLE001
            continue
        return got
    try:
        got = _sfx_any_video()
    except Exception:  # noqa: BLE001
        got = None
    if got is not None and not sfx_clip_refusal(got):
        return got
    mp4only_note("gap", "left_empty")
    return None


def _sfx_any_audio() -> Path | None:
    """A short unbanned sample, ignoring the rate/gap gate (#464) — for
'''

GATE_ANCHOR = '''    if sample is None and force:
        sample = await asyncio.to_thread(_sfx_any)
'''
GATE_NEW = '''    # [mp4only-gate] THE DOOR EVERY STING ROAD PASSES - the gap filler, a
    # record, a seat's door (#1034), the rescue: a clip the filter refuses
    # does not air. Forced, it is swapped through _sfx_any() (which honours
    # the switch); nothing found and the caller's next rung answers.
    if sample is not None:
        try:
            _refusal = sfx_clip_refusal(sample)
        except Exception:  # noqa: BLE001
            _refusal = ""
        if _refusal:
            mp4only_note(who or "sting", _refusal, sample)
            sample = None
            if force:
                _swap = await asyncio.to_thread(_sfx_any)
                if _swap is not None and not sfx_clip_refusal(_swap):
                    sample = _swap
                    mp4only_note(who or "sting", "swapped", _swap)
'''

CAD_OLD = '''            video_order = (requested_video, not requested_video)
'''
CAD_NEW = '''            # [mp4only-cadence] the switch means MP4 only, not MP4 first: a
            # miss leaves this optional slot empty (the round still speaks).
            video_order = ((True,) if sfx_mp4_only()
                           else (requested_video, not requested_video))
'''
CAD_WHY_OLD = '''                "nothing was drawn from the book")
    guy_interval = int(settings.get("sfxguy_every_units",
'''
CAD_WHY_NEW = '''                "nothing was drawn from the book"
                + (" - MP4 only: no picture clip drew, so no MP3 was welded"
                   " in its place [mp4only-cadence-why]"
                   if sfx_mp4_only() else ""))
    guy_interval = int(settings.get("sfxguy_every_units",
'''

FLOW_OLD = '''    for want_video in (prefer_video, not prefer_video):
'''
FLOW_NEW = '''    # [mp4only-flow] under the switch the graph never plans an MP3 beat
    for want_video in ((True,) if sfx_mp4_only()
                       else (prefer_video, not prefer_video)):
'''

OVER_OLD = '''        if clip.get("video") or clip.get("picture_only") or not did:
            continue
        # A pause or reboot cuts the old programme.'''
OVER_NEW = '''        if clip.get("video") or clip.get("picture_only") or not did:
            # [mp4only-overlap] ...BUT A STING'S MP4 SOUNDS. Its soundtrack
            # plays on the tube, so its span is sold air even though the
            # voice player never touches it. Skipping it here reset the
            # cursor under it and the next sting was stamped at now+lead:
            # 57 MP4-then-MP3 overlaps in an hour, the gap filler's burst
            # heard as two clips at once. Reserve the span; never retime it.
            if (clip.get("video") and did and not clip.get("picture_only")
                    and not clip.get("silent_picture")
                    and not clip.get("endless")
                    and not (cut_ms and clip.get("ts")
                             and int(clip["ts"]) <= cut_ms)
                    and str((_PAGE_DELIVERIES.get(did) or {}).get("state")
                            or "") not in ("ended", "error")):
                try:
                    _v_at = float(clip.get("broadcast_ms") or 0) / 1000.0
                    _v_for = float(clip.get("seconds")
                                   or clip.get("length") or 0)
                    if _v_at > 0 and _v_for > 0 and _v_at + _v_for > now:
                        cursor = max(cursor, _v_at + _v_for)
                except (TypeError, ValueError):
                    pass
            continue
        # A pause or reboot cuts the old programme.'''

ADMIX_OLD = '''        sfx = await asyncio.to_thread(_sfx_any)
        if sfx:
            sting_remember(str(sfx))
'''
ADMIX_NEW = '''        sfx = await asyncio.to_thread(_sfx_any, True)   # [mp4only-admix] a bed, not a clip
        if sfx:
            sting_remember(str(sfx))
'''

GONE_OLD = '''    try:
        size = await asyncio.to_thread(lambda: path.stat().st_size)
    except Exception:
        return Response(status_code=404)

    headers = {
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        # The desktop shell is file:// and its real >100% video gain uses a
'''
GONE_NEW = '''    try:
        size = await asyncio.to_thread(lambda: path.stat().st_size)
    except Exception:
        # [mp4only-gone] the book lists it, the share does not hold it: a
        # <video> reads this 404 as "format not supported". Never again.
        try:
            if not await asyncio.to_thread(raw.is_file):
                await asyncio.to_thread(
                    sfx_quarantine, sfx_key, "the file is gone from the share "
                    "(a 404 at /sfx)", raw, "the /sfx route")
        except Exception:  # noqa: BLE001
            pass
        return Response(status_code=404)

    headers = {
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        # The desktop shell is file:// and its real >100% video gain uses a
'''

DECODE_ANCHOR = '''            print("[sfx] could not decode %s to a wav: %s" % (
'''
DECODE_NEW = '''            # [mp4only-decode] a file ffmpeg calls invalid is not a hiccup:
            # quarantined, so no road draws it again (07 breathing.mp4).
            if _SFX_UNDECODABLE_RE.search(said or ""):
                try:
                    sfx_quarantine(sfx_id(path), "ffmpeg: %s" % " / ".join(
                        said.strip().split("\\n")[-2:])[:200], path,
                        "the wav decoder")
                except Exception:  # noqa: BLE001
                    pass
'''

API_ANCHOR = '''@app.get("/api/sfx/video/mode")
async def sfx_video_mode_get_api(
'''
API_NEW = '''@app.get("/api/sfx/mp4-only")
async def sfx_mp4_only_api(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[mp4only-api] Is the switch at MP4 only, what the filter refused per
    road, what it swapped, where it left a road empty, what is quarantined."""
    require_read_auth(authorization)
    await asyncio.to_thread(_sfx_quarantine_load)
    return {"mp4_only": sfx_mp4_only(), "share": sfx_video_share(),
            **{k: v for k, v in _MP4ONLY.items()},
            "quarantine": {"clips": len(_SFX_QUARANTINED),
                           "folders_gone": sorted(_SFX_GONE_FOLDERS)[:20],
                           "list": str(_sfx_quarantine_path())}}


'''

HEARD_ANCHOR = '''        clip = delivery.get("clip") or {}
        clip["delivery_state"] = "playing"
        if audible > 0 and progressed and delivery.get("speech"):
'''
HEARD_NEW = '''        clip = delivery.get("clip") or {}
        clip["delivery_state"] = "playing"
        # [mp4only-heard] a single sting (the SFX TV's MP4 or the voice
        # player's clip) names its script row as `line`: its own audible
        # receipt is what makes the row aired.
        if (audible > 0 and progressed and clip.get("line")
                and not (clip.get("stream") or {}).get("rows")):
            try:
                _sting_heard(str(clip.get("line")), delivery_id, now - position)
            except Exception:  # noqa: BLE001
                pass
        if audible > 0 and progressed and delivery.get("speech"):
'''

PUB_OLD = '''            _sting_row["aired"] = "box" if to_box else "page"
'''
PUB_NEW = '''            # [mp4only-published] handing it to the page is PUBLICATION.
            # "page" is written by the player's receipt (_sting_heard).
            _sting_row["aired"] = "box" if to_box else (
                "page" if _sting_row.get("aired") == "page" else "published")
'''

EDITS = [
    ("[mp4only-core]", "def sfx_ads_share() -> int:\n", CORE, "before", 1),
    ("[mp4only-match]", MATCH_OLD, MATCH_NEW, "before", 1),
    ("[mp4only-match-origin]", MATCH2_OLD, MATCH2_NEW, "before", 1),
    ("[mp4only-due]", DUE_ANCHOR, DUE_NEW, "replace", 1),
    ("[mp4only-any]", ANY_OLD, ANY_NEW, "replace", 1),
    ("[mp4only-gate]", GATE_ANCHOR, GATE_NEW, "after", 1),
    ("[mp4only-cadence]", CAD_OLD, CAD_NEW, "replace", 1),
    ("[mp4only-cadence-why]", CAD_WHY_OLD, CAD_WHY_NEW, "replace", 1),
    ("[mp4only-flow]", FLOW_OLD, FLOW_NEW, "replace", 1),
    ("[mp4only-overlap]", OVER_OLD, OVER_NEW, "replace", 1),
    ("[mp4only-admix]", ADMIX_OLD, ADMIX_NEW, "replace", 2),
    ("[mp4only-gone]", GONE_OLD, GONE_NEW, "replace", 1),
    ("[mp4only-decode]", DECODE_ANCHOR, DECODE_NEW, "before", 1),
    ("[mp4only-api]", API_ANCHOR, API_NEW, "before", 1),
    ("[mp4only-heard]", HEARD_ANCHOR, HEARD_NEW, "replace", 1),
    ("[mp4only-published]", PUB_OLD, PUB_NEW, "replace", 1),
]

HOOK_OLD = '''        addr = str(getattr(request.client, "host", "") or "")
        return await asyncio.to_thread(store.append, body, addr)
'''
HOOK_NEW = '''        addr = str(getattr(request.client, "host", "") or "")
        got = await asyncio.to_thread(store.append, body, addr)
        # [mp4only-undecodable] a clip no player could open is quarantined
        hook = namespace.get("sfx_quarantine_receipts")
        if callable(hook):
            try:
                await asyncio.to_thread(hook, body)
            except Exception:  # noqa: BLE001
                pass
        return got
'''
HOOK_EDITS = [("[mp4only-undecodable]", HOOK_OLD, HOOK_NEW, "replace", 1)]

# The tests that pinned the old rules, moved to the operator's:
CAD_TEST_OLD = '''        got = await app._sfx_cadence_additions_inner('dj', 'a line', 2, 20)
        self.assertEqual(got[0]['who'], 'board')
        self.assertEqual(Path(got[0]['path']).name, 'scratch.wav')
        app._sfx_cadence_video_pick.assert_called_once_with('a line')
        app._sfx_cadence_pick.assert_called()
'''
CAD_TEST_NEW = '''        got = await app._sfx_cadence_additions_inner('dj', 'a line', 2, 20)
        # [mp4only-test] the switch at 100 is MP4 ONLY: a picture miss leaves
        # the optional slot empty and no MP3 is welded in its place (#1462
        # fell back to audio; the operator: "the roulette should only be
        # offering mp4s").
        self.assertFalse([r for r in got if r.get('who') == 'board'])
        app._sfx_cadence_video_pick.assert_called_once_with('a line')
        app._sfx_cadence_pick.assert_not_called()
        self.assertIn('MP4 only', app._SFX_CADENCE_STATUS['omit_why'])
'''
VID_TEST_OLD = '''        for one in (self.video, self.audio):
            one.write_bytes(b"x" * 64)

    def test_the_dead_air_road_never_draws_a_picture(self):
'''
VID_TEST_NEW = '''        for one in (self.video, self.audio):
            one.write_bytes(b"x" * 64)
        # [mp4only-test] audible below the switch; at MP4 only the dead-air
        # road draws a sounding picture (test_mp4only_2026_09_29).
        _mp4 = mock.patch.object(app, "sfx_mp4_only", return_value=False)
        _mp4.start()
        self.addCleanup(_mp4.stop)

    def test_the_dead_air_road_never_draws_a_picture(self):
'''
VID_AIRED_OLD = '''        self.assertEqual(row["aired"], "page")
'''
VID_AIRED_NEW = '''        # [mp4only-test] published until a player's own receipt says heard
        self.assertEqual(row["aired"], "published")
'''
TEST_EDITS = [
    ("tests/test_sfx_stream_cadence.py",
     [("[mp4only-test]", CAD_TEST_OLD, CAD_TEST_NEW, "replace", 1)]),
    ("tests/test_sfx_video_clips_2026_09_12.py",
     [("[mp4only-test] audible", VID_TEST_OLD, VID_TEST_NEW, "replace", 1),
      ("[mp4only-test] published", VID_AIRED_OLD, VID_AIRED_NEW, "replace", 1)]),
]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    targets = [("app.py", EDITS), ("sfx_display.py", HOOK_EDITS)] + TEST_EDITS
    if argv and argv[0] == "--apply":
        # all or nothing: every target must be ready or applied first
        if any(run(rel, edits, ["--check"] + argv[1:]) == 1 for rel, edits in targets):
            return 1
    codes = [run("app.py", EDITS, argv), run("sfx_display.py", HOOK_EDITS, argv)]
    codes += [run(rel, edits, argv) for rel, edits in TEST_EDITS]
    if 1 in codes or 64 in codes:
        return 1 if 1 in codes else 64
    if argv and argv[0] == "--check":
        return 2 if all(c == 2 for c in codes) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
