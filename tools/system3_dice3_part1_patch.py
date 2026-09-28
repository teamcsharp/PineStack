"""[s3-dice-door] The rest of the station's own dice are System 3's (part 1).

Operator, 2026-09-27: "I want the roulette system encompassing all with all of
the requests for randomness on the station to be broken down and tabled and
made into a roulette rolodex entry that dice is rolling a chance of hitting."
And: "make sure that each and every request i made for spontaneity makes it to
the roulette system as a customizable entry".

tools/system3_dice_patch.py opened the dice door (s3_chance, s3_roll,
s3_choice, s3_sample, s3_weighted - each a STATION1 / POOLS1 row, drawn by
System 3, recorded on the round it shaped and in the Audit feed; the station's
own random when System 3 is off). This tool walks the bare draws still left
on these roads through it:

  render.reply              which render reply the box speaks
  ad.voice_at_share         where in its source clip a voice ad is taken
  records.hot_shelf         the record off the local shelf (#1156)
  voice.reply_*             the box's intonation on a reply (#297)
  records.rotation_deal     the rotation's shuffle - ONE roll deals it (#984)
  speakbox.response_*       the response bank's documents and swaths
  records.callback*         a record's callback and its frames (#1062)
  torrent.round_kind        the torrent's kind of round (#1027)
  orch.routine_questions    the six-hourly check's questions (#1056)
  ad.gap_spot / ad.read_pick / ad.bed_*   the spot, the read, the bed
  torrent.breath            the breath of music between rounds (#700)
  police.*                  the officer outside: character, pitch, siren
  manager.cut_in*           upstairs cutting in (#1162)
  manager.page_*            the clock of pages from upstairs

Left alone, on purpose: render and model seeds, the share probe's file, a log
sample, and two roads whose lines are another tool's stored text
(system3_hygiene_patch 'loop-interject', ads_fresh_patch) - see REPORT.md.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST, after tools/system3_dice_patch.py.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- announce_render_complete -----------------------------------------------
    ("render-reply",
     r'''            await speak(random.choice(replies), event="render")
''',
     r'''            await speak(s3_choice("render.reply", replies, "which of the render replies the box speaks when an image lands", tabled=False), event="render")   # [s3-dice-door]
''', 1),
    # --- voice_ad_render --------------------------------------------------------
    ("voice-ad-at-share",
     r'''            "at_share": random.random(), "prompt": direction + continuation,
''',
     r'''            "at_share": s3_roll("ad.voice_at_share", "where in its source clip a voice ad's performance is taken (a share of the clip)"), "prompt": direction + continuation,   # [s3-dice-door]
''', 1),
    # --- _hot_shelf_pick --------------------------------------------------------
    ("hot-shelf",
     r'''        return random.choice(picks) if picks else None
''',
     r'''        return s3_choice("records.hot_shelf", picks, "which record already on the local shelf airs while the share crawls (#1156)", tabled=False) if picks else None   # [s3-dice-door]
''', 1),
    # --- speak: the box's intonation on a reply (#297) --------------------------
    ("speak-perf",
     r'''            "pace": round(random.uniform(0.95, 1.08), 3),
            "pitch_st": random.choice([0, 0, 0, 1, -1, 2]),
            "pitch_var": round(random.uniform(0.9, 1.25), 3),
            "energy": round(random.uniform(-0.15, 0.3), 3),
            "pause_scale": round(random.uniform(0.9, 1.2), 3),
''',
     r'''            "pace": round(0.95 + (1.08 - 0.95) * s3_roll("voice.reply_pace", "how fast the box speaks a reply (#297)"), 3),   # [s3-dice-door]
            "pitch_st": s3_choice("voice.reply_pitch", [0, 0, 0, 1, -1, 2], "the pitch step, in semitones, of the box's reply (#297)", tabled=False),   # [s3-dice-door]
            "pitch_var": round(0.9 + (1.25 - 0.9) * s3_roll("voice.reply_pitch_var", "how far the box's pitch wanders in a reply (#297)"), 3),   # [s3-dice-door]
            "energy": round(-0.15 + (0.3 + 0.15) * s3_roll("voice.reply_energy", "how much energy the box puts into a reply (#297)"), 3),   # [s3-dice-door]
            "pause_scale": round(0.9 + (1.2 - 0.9) * s3_roll("voice.reply_pauses", "how long the box's pauses run in a reply (#297)"), 3),   # [s3-dice-door]
''', 1),
    # --- radio_fill: one roll deals the rotation (#984) -------------------------
    # A shuffle of the whole library is thousands of draws; System 3 rolls the
    # deal once and that number seeds it (recorded, replayable).
    ("rotation-deal",
     r'''    random.shuffle(tracks)
    if loved:
''',
     r'''    _deal = random.Random(int(s3_roll("records.rotation_deal", "the order the rotation is dealt in (one roll deals the whole shuffle, #984)") * (1 << 53)))   # [s3-dice-door]
    _deal.shuffle(tracks)
    if loved:
''', 1),
    ("rotation-deal-loved",
     r'''        tracks.sort(key=lambda t: random.random()
''',
     r'''        tracks.sort(key=lambda t: _deal.random()   # [s3-dice-door] the same deal
''', 1),
    # --- response_bank_sources --------------------------------------------------
    # Only the documents the draft reads are dealt - the first max(8, count * 3)
    # of fresh-then-old, exactly what the two whole-shelf shuffles fed it.
    ("response-docs",
     r'''    random.shuffle(fresh)
    random.shuffle(old)
''',
     r'''    fresh = s3_sample("speakbox.response_docs", fresh, min(len(fresh), max(8, count * 3)),
                      "which Speakerbox documents the response bank drafts from", tabled=False)   # [s3-dice-door]
    old = s3_sample("speakbox.response_docs_old", old, min(len(old), max(0, max(8, count * 3) - len(fresh))),
                    "which already-drafted Speakerbox documents fill the rest", tabled=False)   # [s3-dice-door]
''', 1),
    ("response-swath",
     r'''        start = random.randint(0, max(0, len(words) - 75))
''',
     r'''        start = min(max(0, len(words) - 75), int(s3_roll("speakbox.response_swath", "where in a document the response bank's swath starts") * (max(0, len(words) - 75) + 1)))   # [s3-dice-door]
''', 1),
    # --- track_callback (#1062) -------------------------------------------------
    ("callback-rate",
     r'''        if random.random() > track_callback_rate():
''',
     r'''        if not s3_chance("records.callback", track_callback_rate(), "a record talked about before gets the callback, not a fresh look (#1062)", dial="callback_rate"):   # [s3-dice-door]
''', 1),
    ("callback-after",
     r'''            frame = random.choice(TRACK_CALLBACK_AFTER)
''',
     r'''            frame = s3_choice("records.callback_after", TRACK_CALLBACK_AFTER, "the send-off a record's callback is framed with (#1062)")   # [s3-dice-door]
''', 1),
    ("callback-before",
     r'''            body = said + " " + random.choice(TRACK_CALLBACK_BEFORE)
''',
     r'''            body = said + " " + s3_choice("records.callback_before", TRACK_CALLBACK_BEFORE, "the line that hands an advert's callback over to its record (#1062)")   # [s3-dice-door]
''', 1),
    # --- directive_draw_kind (#1027) --------------------------------------------
    ("torrent-kind",
     r'''        return random.choices(list(choices), weights=weights, k=1)[0]
''',
     r'''        return list(choices)[s3_weighted("torrent.round_kind", [str(c) for c in choices], weights, "which kind of round the torrent draws next (#1027)")]   # [s3-dice-door]
''', 1),
    ("torrent-kind-plain",
     r'''        return random.choice(list(choices))
''',
     r'''        return s3_choice("torrent.round_kind", list(choices), "which kind of round the torrent draws next (#1027)", tabled=False)   # [s3-dice-door]
''', 1),
    # --- orch_routine_questions (#1056) -----------------------------------------
    ("orch-questions-pinned",
     r'''            return [_pinned] + random.sample(bank, min(2, len(bank)))
''',
     r'''            return [_pinned] + s3_sample("orch.routine_questions", bank, min(2, len(bank)), "which questions the six-hourly check asks (#1056)", tabled=False)   # [s3-dice-door]
''', 1),
    ("orch-questions",
     r'''        return random.sample(bank, min(3, len(bank)))
''',
     r'''        return s3_sample("orch.routine_questions", bank, min(3, len(bank)), "which questions the six-hourly check asks (#1056)", tabled=False)   # [s3-dice-door]
''', 1),
    # --- coord_spot_ready (#916d) -----------------------------------------------
    ("gap-spot",
     r'''        return random.choice([r for r in pool
                              if int(r.get("uses") or 0) == fewest])
''',
     r'''        return s3_choice("ad.gap_spot", [r for r in pool
                                         if int(r.get("uses") or 0) == fewest],
                         "which least-run produced spot fills a hole in the air (#916d)", tabled=False)   # [s3-dice-door]
''', 1),
    # --- torrent_breath (#700) --------------------------------------------------
    ("breath-top",
     r'''        return random.uniform(0.12, 0.35)
''',
     r'''        return 0.12 + (0.35 - 0.12) * s3_roll("torrent.breath", "how long a breath of music between rounds (#700)")   # [s3-dice-door]
''', 1),
    ("breath-box-alone",
     r'''        return max(1.5, random.uniform(middle * 0.45, middle * 0.95))
''',
     r'''        return max(1.5, middle * 0.45 + (middle * 0.95 - middle * 0.45) * s3_roll("torrent.breath", "how long a breath of music between rounds (#700)"))   # [s3-dice-door]
''', 1),
    ("breath",
     r'''    return max(2.0, random.uniform(middle * 0.65, middle * 1.45))
''',
     r'''    return max(2.0, middle * 0.65 + (middle * 1.45 - middle * 0.65) * s3_roll("torrent.breath", "how long a breath of music between rounds (#700)"))   # [s3-dice-door]
''', 1),
    # --- loved_moment (#683): a roll when a bed opens on it; a question when
    # _music_bed_track only asks whether a favourite has a marked moment -------
    ("loved-moment-def",
     r'''def loved_moment(track_id: str) -> float | None:
''',
     r'''def loved_moment(track_id: str, roll: bool = True) -> float | None:   # [s3-dice-door] roll=False only asks
''', 1),
    ("loved-moment-pick",
     r'''        return random.choice(marks)
''',
     r'''        return (s3_choice("ad.bed_moment", marks, "which of the moments he liked an ad bed opens on (#683)", tabled=False)
                if roll else marks[0])   # [s3-dice-door]
''', 1),
    # --- ad_pick ----------------------------------------------------------------
    ("read-pick",
     r'''    return random.choice([r for r in rows if r.get("uses", 0) == fewest])
''',
     r'''    return s3_choice("ad.read_pick", [r for r in rows if r.get("uses", 0) == fewest], "which of the least-run ad reads airs", tabled=False)   # [s3-dice-door]
''', 1),
    # --- the officer outside (#636) ---------------------------------------------
    ("siren",
     r'''    return str(random.choice(pool)) if pool else None
''',
     r'''    return str(s3_choice("police.siren", pool, "which siren off the sample shelf wails behind the megaphone (#636)", tabled=False)) if pool else None   # [s3-dice-door]
''', 1),
    ("police-character",
     r'''    character = random.choice(names) if names else "plain"
''',
     r'''    character = s3_choice("police.character", names, "which vocoder character the officer outside speaks in (#636)") if names else "plain"   # [s3-dice-door]
''', 1),
    ("police-pitch",
     r'''                "pitch": VOCODER_DEFAULT_PITCH.get(
                    character, random.randint(-4, 4))})
''',
     r'''                "pitch": (VOCODER_DEFAULT_PITCH[character] if character in VOCODER_DEFAULT_PITCH else
                          -4 + min(8, int(s3_roll("police.pitch", "the officer's pitch, in semitones, when his character has none set (#636)") * 9)))})   # [s3-dice-door]
''', 1),
    # --- manager_cut_in_clause (#1162) ------------------------------------------
    ("cut-in",
     r'''        if pct > 0 and not radio_paused() and random.randint(1, 100) <= pct:
''',
     r'''        if pct > 0 and not radio_paused() and s3_chance("manager.cut_in", pct / 100.0, "a memo from upstairs cuts into this round (#1162)", dial="manager_cut_in_pct"):   # [s3-dice-door]
''', 1),
    ("cut-in-gripe",
     r'''                row = random.choice(
                    [r for r in rows if int(r.get("uses") or 0) == fewest])
''',
     r'''                row = s3_choice(   # [s3-dice-door]
                    "manager.cut_in_gripe", [r for r in rows if int(r.get("uses") or 0) == fewest],
                    "which gripe (the least aired) upstairs cuts in with (#1162)", tabled=False)
''', 1),
    ("cut-in-manner",
     r'''random.choice(MANAGER_CUT_INS).capitalize()
''',
     r'''s3_choice("manager.cut_in_manner", MANAGER_CUT_INS, "how upstairs cuts in on the pair (#1162)").capitalize()   # [s3-dice-door]
''', 1),
    ("cut-in-react",
     r'''random.choice(MANAGER_CUT_REACTS)
''',
     r'''s3_choice("manager.cut_in_react", MANAGER_CUT_REACTS, "how the pair take the interruption from upstairs (#1162)")   # [s3-dice-door]
''', 1),
    # --- upstairs_clock ---------------------------------------------------------
    ("page-wait",
     r'''            wait = random.uniform(90.0, 200.0) if first else \
                random.uniform(gap * 0.6, gap * 1.4)
''',
     r'''            wait = (90.0 + (200.0 - 90.0) * s3_roll("manager.page_first_wait", "how soon the first page from upstairs comes in a fresh show")
                    if first else
                    gap * 0.6 + (gap * 1.4 - gap * 0.6) * s3_roll("manager.page_wait", "how long until the next page from upstairs (its hourly rate, jittered)"))   # [s3-dice-door]
''', 1),
    # --- _music_bed_track (#463, #526, #683) ------------------------------------
    ("bed-marked-ask",
     r'''                  if loved_moment(str(t.get("id") or "")) is not None]
''',
     r'''                  if loved_moment(str(t.get("id") or ""), roll=False) is not None]   # [s3-dice-door] a question, not a roll
''', 1),
    # The whole-library fallback is a roll into the list, not a pick: a pick
    # hands System 3 every track in the library as a candidate string.
    ("bed-draws",
     r'''    if marked and random.random() < 0.85:
        return random.choice(marked)
    if faves and random.random() < 0.8:
        return random.choice(faves)
    return random.choice(pool)
''',
     r'''    if marked and s3_chance("ad.bed_marked", 0.85, "an advert is bedded on a favourite whose liked moment is marked (#683)"):   # [s3-dice-door]
        return s3_choice("ad.bed_marked_pick", marked, "which marked favourite beds the advert", tabled=False)   # [s3-dice-door]
    if faves and s3_chance("ad.bed_fave", 0.8, "an advert is bedded on one of his favourites (#526)"):   # [s3-dice-door]
        return s3_choice("ad.bed_fave_pick", faves, "which favourite beds the advert", tabled=False)   # [s3-dice-door]
    return pool[min(len(pool) - 1, int(s3_roll("ad.bed_any", "which long track beds the advert when no favourite does (#463)") * len(pool)))]   # [s3-dice-door]
''', 1),
    # --- where the swell drops in, with no liked moment (dj_music_ad, ad_produce)
    ("bed-start-air",
     r'''            start = random.uniform(20.0, max(21.0, min(70.0, secs - 25.0))) \
                if secs > 50 else 15.0
''',
     r'''            start = 20.0 + (max(21.0, min(70.0, secs - 25.0)) - 20.0) * s3_roll("ad.bed_start", "where in the record an advert's swell drops in, with no liked moment marked") \
                if secs > 50 else 15.0   # [s3-dice-door]
''', 1),
    ("bed-start-produce",
     r'''            start = (random.uniform(20.0, max(21.0, min(70.0, secs - 25.0)))
                     if secs > 50 else 15.0)
''',
     r'''            start = (20.0 + (max(21.0, min(70.0, secs - 25.0)) - 20.0) * s3_roll("ad.bed_start", "where in the record an advert's swell drops in, with no liked moment marked")
                     if secs > 50 else 15.0)   # [s3-dice-door]
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
