"""[s3-dice-door] The speakbox scenes, the cast, the seat, the banter dice, the
story clock, the phones and the ad clock roll System 3's dice.

Operator, 2026-09-27: "I want the roulette system encompassing all with all of
the requests for randomness on the station to be broken down and tabled and
made into a roulette rolodex entry that dice is rolling a chance of hitting."
And: "make sure that each and every request i made for spontaneity makes it to
the roulette system as a customizable entry".

system3_dice_patch.py opened the door (s3_chance, s3_roll, s3_pool, s3_choice,
s3_sample, s3_weighted, _S3Dice). This tool walks the rest of the bare draws
in this stretch of app.py through it (the third sweep, part 2):

  speakbox_harvest       where in the document the harvest reads
  switchboard_fill       which road the switchboard offers next (taste-weighted)
  speakbox_scene_angle   who performs the passage, who lands the last word,
                         whether the other one recognises the document (#577)
  speakbox_angle         who delivers the passage, speech or drop (#223), #577
  banter_voices          which Piper voice plays each seat (once per session)
  session_voices         whether the host's seat is the woman's voice
  voice_effect_pick      whether a line goes out wet (the fx_rate dial), and
                         how wet (between fx_min and fx_max)
  sting_due              the never-heard share and the fresh share (#1251/#1062)
  _sfx_deck_fill         which video clip waits on the tap-button deck
  _sting_over_record     how far into the record the sting lands
  seat_line              the leaving / coming-back line - each reason's book
                         is a POOLS1 pool (seat.<reason>_<leave|back>)
  seat_reason_draw       why a host steps out (seat.reason, a POOLS1 pool)
  _seat_door_sample_blocking  which door / footsteps sample follows them out
  seat_go_away           how long they stay out
  approach_pick          the approach book's weighted frame; the built-in list
  banter_dice_roll / banter_dice_pick  where the dice land, which card
  banter_beat_sheet      who holds the floor on a turn; whether a turn rolls
  banter_due             the gap before the pair talk again - rolled only when
                         the clock resets, not on every record
  story_open_async / story_beat_async  when a caller's story rings back
  _call_rerun_pick_blocking  which past call re-airs
  caller_face            which gallery picture a new caller wears
  caller_voice_for       which of the least-used library voices a new caller
                         gets (the random sort key became a draw among the tie)
  ad_clock               which advert the clock runs (the 0.10 / 0.22 bands)
  caller_clock           when the phone rings next; the flood-rate crack (#352)

Left as the station's own random, on purpose: describe_gallery_image's model
temperature and seed (sampling parameters), banter_gap's per-turn pause jitter,
voice_effect_pick's delay / echo / room (DSP texture), sfx_list / _sfx_draw /
_sfx_pool_refresh's per-folder cap sample and _sfx_pool_warm's shuffle (which
files are candidates, hundreds per call - the air pick is made downstream),
_sting_over_record's retry wait, speakbox_quote's weighted pre-draw (System 3
already draws past the rotation: speakbox.doc), gold_pick's shuffle (inside
system3_dice_sfx_patch.py's gold-pick text), and sfxguy_line / _sfxguy_take's
director-less fallbacks (inside system3_roads_patch.py's guy-* texts).

No awaits, locks or I/O are added. With System 3 off each helper is the
station's own random with the same distribution and the same guards. Needs
system3_dice_patch.py applied first (the helpers).

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- the speakbox: the harvest window -------------------------------------
    ("harvest-window",
     r'''        at = random.randrange(0, len(body) - SPEAKBOX_GEM_WINDOW)
''',
     r'''        at = min(len(body) - SPEAKBOX_GEM_WINDOW - 1, int(   # [s3-dice-door]
            s3_roll("speakbox.harvest_window", "where in the document the harvest reads")   # [s3-dice-door]
            * (len(body) - SPEAKBOX_GEM_WINDOW)))   # [s3-dice-door]
''', 1),
    # --- the switchboard ------------------------------------------------------
    ("switchboard-kind",
     r'''            roll = random.random() * total
''',
     r'''            roll = s3_roll("switchboard.kind", "which road the switchboard offers next (weighted by what the operator takes)") * total   # [s3-dice-door]
''', 1),
    # --- speakbox_scene_angle -------------------------------------------------
    ("scene-performer",
     r'''    first = random.choice(["A", "B"])
''',
     r'''    first = "A" if s3_chance("speakbox.scene_performer", 0.5, "the host (A) performs the whole passage, not the co-host (B)") else "B"   # [s3-dice-door]
''', 1),
    ("scene-jab",
     r'''            f" And just before the end, {random.choice([first, other])} "
''',
     r'''            f" And just before the end, {first if s3_chance('speakbox.scene_jab', 0.5, 'the performer (not the one reacting) lands the last-word passage') else other} "   # [s3-dice-door]
''', 1),
    ("scene-caught",
     r'''    if random.random() < 0.35:               # #577: caught quoting a document
        angle += doc_recognition(other, seed.get("file", ""))
''',
     r'''    if s3_chance("speakbox.caught_quoting", 0.35, "the other one recognises the document the passage came from (#577)"):   # [s3-dice-door]
        angle += doc_recognition(other, seed.get("file", ""))
''', 1),
    # --- speakbox_angle -------------------------------------------------------
    ("drop-speaker",
     r'''    first = first if first in ("A", "B") else random.choice(["A", "B"])
''',
     r'''    first = first if first in ("A", "B") else ("A" if s3_chance("speakbox.drop_speaker", 0.5, "the host (A) delivers the passage, not the co-host (B)") else "B")   # [s3-dice-door]
''', 1),
    ("drop-monologue",
     r'''            if random.random() < 0.34
''',
     r'''            if s3_chance("speakbox.monologue", 0.34, "the passage lands as a speech rather than a line dropped in (#223)")   # [s3-dice-door]
''', 1),
    ("drop-caught",
     r'''    if random.random() < 0.35:               # #577: caught quoting a document
        angle += doc_recognition(other, quote.get("file", ""))
''',
     r'''    if s3_chance("speakbox.caught_quoting", 0.35, "the other one recognises the document the passage came from (#577)"):   # [s3-dice-door]
        angle += doc_recognition(other, quote.get("file", ""))
''', 1),
    # --- the cast -------------------------------------------------------------
    ("cast-voice",
     r'''        picked[gender] = random.choice(have) if have else ""
''',
     r'''        picked[gender] = (s3_choice("cast.female_voice" if gender == "female" else "cast.male_voice", have,   # [s3-dice-door]
                                    "which Piper voice plays the %s seat (drawn once per session)" % gender,   # [s3-dice-door]
                                    tabled=False) if have else "")   # [s3-dice-door]
''', 1),
    ("cast-seat",
     r'''        fixed = ({"dj": female, "cohost": male} if random.random() < 0.5
''',
     r'''        fixed = ({"dj": female, "cohost": male} if s3_chance("cast.host_is_woman", 0.5, "the host's seat gets the woman's voice (drawn once, kept)")   # [s3-dice-door]
''', 1),
    # --- voice_effect_pick ----------------------------------------------------
    ("voice-fx",
     r'''    if random.random() >= dj["fx_rate"]:
        return {}
    depth = random.uniform(dj["fx_min"], dj["fx_max"]) / 100.0
''',
     r'''    if dj["fx_rate"] <= 0 or not s3_chance("voice.fx_wet", dj["fx_rate"], "a line goes out wet (echo and room on the voice)", dial="fx_rate"):   # [s3-dice-door]
        return {}
    depth = (dj["fx_min"] + (dj["fx_max"] - dj["fx_min"])   # [s3-dice-door]
             * s3_roll("voice.fx_depth", "how wet a wet line is (between the effect minimum and maximum)")) / 100.0   # [s3-dice-door]
''', 1),
    # --- sting_due: the never-heard and fresh shares --------------------------
    ("sting-unheard",
     r'''    if _unheard and len(_unheard) >= STING_SUBPOOL_MIN and random.random() < SFX_UNHEARD_SHARE:   # [#1188]
''',
     r'''    if _unheard and len(_unheard) >= STING_SUBPOOL_MIN and s3_chance("sting.unheard_first", SFX_UNHEARD_SHARE, "the sting is one nobody has heard yet (#1251)"):   # [#1188] [s3-dice-door]
''', 1),
    ("sting-fresh",
     r'''    if fresh and len(fresh) >= STING_SUBPOOL_MIN and random.random() < SFX_FRESH_SHARE:   # [#1188]
''',
     r'''    if fresh and len(fresh) >= STING_SUBPOOL_MIN and s3_chance("sting.fresh_first", SFX_FRESH_SHARE, "the sting is a newly added sample, ahead of the rotation (#1062)"):   # [#1188] [s3-dice-door]
''', 1),
    # --- the tap-button video deck, the sting over the record -----------------
    ("deck-video",
     r'''            pick = random.choice(pool)
            if str(pick) in have:
''',
     r'''            pick = s3_choice("sfx.deck_video", pool, "which video clip waits on the deck for the next tap", tabled=False)   # [s3-dice-door]
            if str(pick) in have:
''', 1),
    ("sting-over-record",
     r'''        await asyncio.sleep(random.uniform(8.0, 25.0))
''',
     r'''        await asyncio.sleep(8.0 + 17.0 * s3_roll("sting.over_record_at", "how far into the record a sting over it lands (8 to 25 seconds)"))   # [s3-dice-door]
''', 1),
    # --- the seat away (#1034) ------------------------------------------------
    ("seat-line-pool",
     r'''    lines = list(book.get(which) or ())
''',
     r'''    # [s3-dice-door] each reason's leaving / coming-back lines are a desk pool (POOLS1)
    _sk = "seat.%s_%s" % (reason if reason in SEAT_AWAY_BOOK else "coffee", which)   # [s3-dice-door]
    lines = s3_pool(_sk, list(book.get(which) or ()), "what a host says %s %s" % (   # [s3-dice-door]
        "coming back from" if which == "back" else "leaving for", book.get("label") or "a break"))   # [s3-dice-door]
''', 1),
    ("seat-line-pick",
     r'''    pick = random.choice(pool)
    used[f"{reason}:{which}"] = pick
''',
     r'''    pick = s3_choice(_sk, pool, "what a host says leaving or coming back", tabled=False)   # [s3-dice-door]
    used[f"{reason}:{which}"] = pick
''', 1),
    ("seat-reason",
     r'''    pool = [r for r in SEAT_AWAY_BOOK if r != _SEAT_STATE.get("last_reason")]
    pick = random.choice(pool or list(SEAT_AWAY_BOOK))
''',
     r'''    _reasons = [r for r in s3_pool("seat.reason", list(SEAT_AWAY_BOOK), "why a host steps out of the studio")   # [s3-dice-door]
                if r in SEAT_AWAY_BOOK] or list(SEAT_AWAY_BOOK)   # [s3-dice-door]
    pool = [r for r in _reasons if r != _SEAT_STATE.get("last_reason")]   # [s3-dice-door]
    pick = s3_choice("seat.reason", pool or _reasons, "why a host steps out of the studio", tabled=False)   # [s3-dice-door]
''', 1),
    ("seat-door",
     r'''        return random.choice(pool) if pool else None
''',
     r'''        return s3_choice("seat.door_sample", pool, "which door / footsteps sample follows a host out", tabled=False) if pool else None   # [s3-dice-door]
''', 1),
    ("seat-span",
     r'''        span = max(120.0, min(360.0, mins * 60.0 * random.uniform(0.75, 1.25)))
''',
     r'''        span = max(120.0, min(360.0, mins * 60.0 * (0.75 + 0.5 * s3_roll(   # [s3-dice-door]
            "seat.away_span", "how long a host stays out of the studio (0.75x to 1.25x the minutes setting)"))))   # [s3-dice-door]
''', 1),
    # --- approach_pick --------------------------------------------------------
    ("approach-builtin",
     r'''        return {"id": "", "text": random.choice(DIALOGUE_APPROACHES)}
''',
     r'''        return {"id": "", "text": s3_choice("approach.builtin", list(DIALOGUE_APPROACHES),   # [s3-dice-door]
                                            "the frame the round is played in (the built-in list, when the approach book is empty)")}   # [s3-dice-door]
''', 1),
    ("approach-frame",
     r'''    pick = random.choices(pool,
                          weights=[float(r.get("weight") or 1) for r in pool],
                          k=1)[0]
''',
     r'''    pick = pool[s3_weighted("approach.frame", [str(r.get("text") or r.get("id") or "") for r in pool],   # [s3-dice-door]
                            [float(r.get("weight") or 1) for r in pool],   # [s3-dice-door]
                            "which approach frames the round (the approach book's own weights)")]   # [s3-dice-door]
''', 1),
    # --- the banter dice ------------------------------------------------------
    ("banter-dice-roll",
     r'''    return round(low + random.random() * (high - low), 3)
''',
     r'''    return round(low + s3_roll("banter.dice_roll", "where the banter dice land on the %s axis (inside its locked band)"   # [s3-dice-door]
                               % (axis or "any")) * (high - low), 3)   # [s3-dice-door]
''', 1),
    ("banter-dice-card",
     r'''    pick = dict(random.choices(
        pool, weights=[float(x.get("weight") or 1) for x in pool], k=1)[0])
''',
     r'''    pick = dict(pool[s3_weighted("banter.dice_card", [str(x.get("text") or x.get("id") or "") for x in pool],   # [s3-dice-door]
                                 [float(x.get("weight") or 1) for x in pool],   # [s3-dice-door]
                                 "which card the banter dice deal on that half of the axis (the book's weights)")])   # [s3-dice-door]
''', 1),
    ("sheet-seat",
     r'''        seat = "A" if turn == 1 else random.choice(pool)
''',
     r'''        seat = "A" if turn == 1 else s3_choice("banter.sheet_seat", pool, "who holds the floor on a turn of the running order", tabled=False)   # [s3-dice-door]
''', 1),
    ("sheet-dice-turn",
     r'''        if random.random() > rate:
''',
     r'''        if not s3_chance("banter.sheet_dice_turn", rate, "a turn of the running order takes a rolled stance", dial="banter_dice_rate"):   # [s3-dice-door]
''', 1),
    # --- banter_due: rolled when the clock resets, not on every record --------
    ("banter-gap",
     r'''    gap = random.uniform(dj["banter_min_minutes"],
                         dj["banter_max_minutes"]) * 60
''',
     r'''    # [s3-dice-door] the minutes between the two settings are rolled below,
    # only when the clock resets - a roll on every record would be noise
    gap = 60.0   # [s3-dice-door]
''', 1),
    ("banter-gap-due",
     r'''        _RADIO["banter_due"] = time.time() + gap
''',
     r'''        _RADIO["banter_due"] = time.time() + gap * (   # [s3-dice-door]
            dj["banter_min_minutes"] + (dj["banter_max_minutes"] - dj["banter_min_minutes"])   # [s3-dice-door]
            * s3_roll("banter.clock_gap", "how long the records run before the pair talk again (between the minute settings)"))   # [s3-dice-door]
''', 1),
    # --- the caller story (#1039): when the next part rings back --------------
    ("story-open-due",
     r'''            "next_due": now + random.uniform(STORY_DUE_MIN_S, STORY_DUE_MAX_S),
''',
     r'''            "next_due": now + STORY_DUE_MIN_S + (STORY_DUE_MAX_S - STORY_DUE_MIN_S) * s3_roll(   # [s3-dice-door]
                "story.next_part_due", "how long until a caller's story rings back with its next part"),   # [s3-dice-door]
''', 1),
    ("story-beat-due",
     r'''                story["next_due"] = now + random.uniform(STORY_DUE_MIN_S,
                                                         STORY_DUE_MAX_S)
''',
     r'''                story["next_due"] = now + STORY_DUE_MIN_S + (STORY_DUE_MAX_S - STORY_DUE_MIN_S) * s3_roll(   # [s3-dice-door]
                    "story.next_part_due", "how long until a caller's story rings back with its next part")   # [s3-dice-door]
''', 1),
    # --- the phones: reruns, faces, voices ------------------------------------
    ("call-rerun",
     r'''    pick = random.choice(cands)
''',
     r'''    pick = cands[_S3Dice("call.rerun_take", "which past call airs again as a rerun").pick(   # [s3-dice-door]
        "rerun", [c["path"].name for c in cands])]   # [s3-dice-door]
''', 1),
    ("call-face",
     r'''        pick = random.choice(free)
''',
     r'''        pick = s3_choice("call.face_picture", free, "which gallery picture a new caller wears", tabled=False)   # [s3-dice-door]
''', 1),
    ("call-voice",
     r'''        fresh = sorted(
            usable,
            key=lambda v: (int(_held.get(v, 0)),
                           int((air.get(v) or {}).get("airings") or 0),
                           int((air.get(v) or {}).get("last") or 0),
                           random.random()))
        pick = fresh[0]
''',
     r'''        # [s3-dice-door] the least-held, least-aired, longest-rested voices
        # tie; System 3 draws among the tie (it was a random sort key)
        def _vrank(v: str) -> tuple[int, int, int]:
            return (int(_held.get(v, 0)),
                    int((air.get(v) or {}).get("airings") or 0),
                    int((air.get(v) or {}).get("last") or 0))
        _vbest = min(_vrank(v) for v in usable)   # [s3-dice-door]
        pick = s3_choice("call.library_voice", [v for v in usable if _vrank(v) == _vbest],   # [s3-dice-door]
                         "which of the least-used library voices a new caller gets", tabled=False)   # [s3-dice-door]
''', 1),
    # --- the clocks: the ad clock, the phone clock ----------------------------
    ("ad-clock-kind",
     r'''            roll = random.random()
            banked = len([r for r in ad_list() if r.get("audio")])
''',
     r'''            roll = s3_roll("station.clock_ad_kind", "which advert the ad clock runs (engineering < 0.10 < service < 0.22 < a produced spot or a break)")   # [s3-dice-door]
            banked = len([r for r in ad_list() if r.get("audio")])
''', 1),
    ("call-clock-wait",
     r'''        wait = (3600.0 / rate) * random.uniform(0.6, 1.4)
''',
     r'''        wait = (3600.0 / rate) * (0.6 + 0.8 * s3_roll("call.clock_wait", "how long until the phone rings again (0.6x to 1.4x the calls-an-hour spacing)"))   # [s3-dice-door]
''', 1),
    ("call-flood",
     r'''            if rate >= 20 and random.random() < 0.5:
''',
     r'''            if rate >= 20 and s3_chance("call.flood_banter", 0.5, "at flood rates the pair crack on air between calls (#352)"):   # [s3-dice-door]
''', 1),
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
