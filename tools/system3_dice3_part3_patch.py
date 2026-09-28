"""[s3-dice-door] The last of the station's bare draws, part 3: System 3's dice.

Operator, 2026-09-27: "I want the roulette system encompassing all with all of
the requests for randomness on the station to be broken down and tabled and
made into a roulette rolodex entry that dice is rolling a chance of hitting."
And: "make sure that each and every request i made for spontaneity makes it to
the roulette system as a customizable entry".

system3_dice_patch.py opened the door (s3_chance, s3_roll, s3_choice,
s3_sample, s3_weighted, _S3Dice). This tool puts the remaining editorial draws
of these roads through it:

  dj_banter            the kept exchange that comes back (the saved_rate dial,
                       still only off System 3's own rounds), which edgewise
                       interjections the writer is offered (#684)
  ask_model            the deep-shelf heat (#895) and the stacked caller's heat
                       (#941) - the operator's "pushing the temperatures";
                       never rolled for a tint, whose temperature is fixed
  _swath_deal          which seat reads the first piece of a dealt passage
  api_director_script_reseed   where a reseeded passage goes in the script
  dj_banter_api / dj_converse_api   the pushed round's passage size and length
  dj_dice_api          who reads the rolled passage (#244, #315)
  _replay_volley       whether the first speaker gets the last word (#266)
  sfx_db_pick_short_video / sfx_db_pick_rotation_row / _sfx_db_pick_any
                       which folder and which clip the SFX TV draws
  _paper_seed_draw     which documents seed the Gazette, where a passage starts
  pine_submit / pine_resolve   which acknowledgement is spoken

Lists that are dynamic, large, or already the operator's own setting (the
readers, the interjections, the Pine phrases, files and rows) are drawn with
tabled=False, so the setting stays the one place they are edited.

Left as the station's own random, on purpose: audio DSP (make_hangup's click
noise, the phone line's delay/echo/room/static, the concat beats), sleep
jitter (the stunned beat), the model's decode entropy (ask_model's spice and
floor jitter, top_p jitter and seed; the Gazette writer's temperature and
seed), the crystal material/stanza pool shuffles, the Gazette plate sort-key
jitter, the panel reel (a GET that decorates the page), a docstring
(call_plot_clause), and every draw whose line lies inside another tool's
stored text (dj_banter's line count - system3_glass_patch; the SHOCK and
MENTION clauses - system3_rounds_patch; the quote door fallback -
system3_patch_app; the SFX Guy's pipe-up - system3_roads_patch; the hourly H3
source, window and shares - h3_fresh_patch, h3_cast_patch,
h3_hourly_door_patch).

Needs system3_dice_patch.py applied first (the helpers). With System 3 off each
helper is the station's own random, with the same distribution as before.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- dj_banter: the draw lines only (the prompt blocks are another tool's) -
    ("saved-replay",
     r'''            and random.random() < dj["saved_rate"]:
''',
     r'''            and s3_chance("banter.saved_replay", dj["saved_rate"],   # [s3-dice-door]
                          "a kept exchange comes back word for word (#202)", dial="saved_rate"):   # [s3-dice-door]
''', 1),
    ("interjections",
     r'''               f"{', '.join(repr(p) for p in random.sample(list(dj['diatribe_interjections']), min(11, len(dj['diatribe_interjections']))))}"
''',
     r'''               f"{', '.join(repr(p) for p in s3_sample('banter.interjections', list(dj['diatribe_interjections']), min(11, len(dj['diatribe_interjections'])), 'which edgewise interjections the writer is offered for a diatribe', tabled=False))}"   # [s3-dice-door]
''', 1),
    # --- ask_model: the operator's heat, not the decode's entropy -------------
    ("writer-heat",
     r'''                      + (random.uniform(0.0, _hot) if _hot > 0.02 else 0.0)
                      + (random.uniform(0.0, 0.35 * _heat)
                         if _heat > 0.02 else 0.0))
''',
     r'''                      + (_hot * s3_roll("writer.shelf_heat", "how far past the dial the writer runs hot on a deep shelf (#895)")   # [s3-dice-door]
                         if _hot > 0.02 and not _is_tint else 0.0)   # [s3-dice-door] a tint's temperature is set below
                      + (0.35 * _heat * s3_roll("writer.call_heat", "how hot a stacked caller is written, inside the road's heat band (#941)")   # [s3-dice-door]
                         if _heat > 0.02 and not _is_tint else 0.0))   # [s3-dice-door]
''', 1),
    # --- the speakbox's dealt passage, and the director's reseed -------------
    ("deal-lead",
     r'''        at = random.randrange(len(pool))
''',
     r'''        at = _S3Dice("speakbox.deal_lead", "which seat reads the first piece of a dealt passage").pick("deal", pool)   # [s3-dice-door]
''', 1),
    ("reseed-at",
     r'''        at = random.randint(1, max(1, len(turns) - 1))
''',
     r'''        _at_span = max(1, len(turns) - 1)   # [s3-dice-door] was randint(1, _at_span)
        at = min(_at_span, 1 + int(s3_roll("director.reseed_at", "where in the script a reseeded passage is dealt in") * _at_span))   # [s3-dice-door]
''', 1),
    # --- the buttons: a pushed round, a typed starter, the dice, a replay ------
    ("button-banter-seed",
     r'''        seed = await speakbox_quote(most=random.randint(2, 6),
                                    cap=random.randint(240, 520))
''',
     r'''        seed = await speakbox_quote(   # [s3-dice-door]
            most=2 + min(4, int(s3_roll("button.banter_most", "how many lines of the speakbox a pushed banter round is handed") * 5)),   # [s3-dice-door]
            cap=240 + min(280, int(s3_roll("button.banter_cap", "how long the passage for a pushed banter round may run") * 281)))   # [s3-dice-door]
''', 1),
    ("button-banter-lines",
     r'''        count = random.randint(7, 14)
''',
     r'''        count = 7 + min(7, int(s3_roll("button.banter_lines", "how many lines a pushed banter round runs") * 8))   # [s3-dice-door]
''', 1),
    ("converse-lines",
     r'''                            lines=random.randint(6, 12))
''',
     r'''                            lines=6 + min(6, int(s3_roll("button.converse_lines", "how many lines a typed conversation starter runs") * 7)))   # [s3-dice-door]
''', 1),
    ("dice-reader",
     r'''    first = random.choice(readers)
''',
     r'''    first = s3_choice("dice.reader", readers, "who reads the rolled passage as a monologue (#244, #315)", tabled=False)   # [s3-dice-door]
''', 1),
    ("replay-last-word",
     r'''        if reply and random.random() < 0.5:
''',
     r'''        if reply and s3_chance("replay.last_word", 0.5, "the first speaker gets the last word on a replayed line (#266)"):   # [s3-dice-door]
''', 1),
    # --- the SFX TV: which folder, which clip ------------------------------------
    # integration 2026-09-28: tools/system3_sfx_roll_patch.py (applied first)
    # put this draw inside `if rolled is None:`, four spaces deeper - anchored
    # on that version, so the old text can no longer match mid-line
    ("short-video-folder",
     r'''        if rolled is None:
            folder, count = random.choice(fresh or folders)
''',
     r'''        if rolled is None:
            _fl = fresh or folders   # [s3-dice-door]
            folder, count = _fl[_S3Dice("sfxtv.short_folder", "which folder a short SFX video comes from (unspent folders first)").pick(   # [s3-dice-door]
                "folder", [str(r[0] or "") for r in _fl])]   # [s3-dice-door]
''', 1),
    ("short-video-clip",
     r'''                          " LIMIT 1 OFFSET ?", args + (random.randrange(int(count)),)).fetchone()
''',
     r'''                          " LIMIT 1 OFFSET ?", args + (min(int(count) - 1, int(s3_roll("sfxtv.short_clip", "which clip in that folder") * int(count))),)).fetchone()   # [s3-dice-door]
''', 1),
    ("deck-clip",
     r'''                    args + (random.randrange(count),)).fetchone()
''',
     r'''                    args + (min(count - 1, int(s3_roll("sfxtv.deck_clip", "which unspent clip of the video deck comes next") * count)),)).fetchone()   # [s3-dice-door]
''', 1),
    ("any-clip",
     r'''                    + " LIMIT 1 OFFSET ?", args + (random.randrange(count),)
''',
     r'''                    + " LIMIT 1 OFFSET ?", args + (min(count - 1, int(s3_roll("sfxtv.any_clip", "which clip out of the SFX book (the length dial's window)") * count)),)   # [s3-dice-door]
''', 1),
    # --- the Gazette's seed passages -------------------------------------------
    ("paper-seed-docs",
     r'''    random.shuffle(files)
    seen = _PAPER_PRESS.setdefault("seed_hashes", set())
    used_files = _PAPER_PRESS.setdefault("seed_files", set())
    files.sort(key=lambda path: path.name in used_files)
''',
     r'''    seen = _PAPER_PRESS.setdefault("seed_hashes", set())
    used_files = _PAPER_PRESS.setdefault("seed_files", set())
    # [s3-dice-door] Was: shuffle, then the unprinted first. The loop below reads
    # at most max(12, 3n) documents, so System 3 draws exactly those, in order -
    # unprinted first, then printed - and the unread rest follows as it lies.
    _read = max(12, n * 3)   # [s3-dice-door]
    _new = [p for p in files if p.name not in used_files]   # [s3-dice-door]
    _old = [p for p in files if p.name in used_files]   # [s3-dice-door]
    _a = s3_sample("paper.seed_docs", _new, min(len(_new), _read),   # [s3-dice-door]
                   "which documents the Gazette's local passages are drawn from", tabled=False)   # [s3-dice-door]
    _b = s3_sample("paper.seed_docs_again", _old, min(len(_old), _read - len(_a)),   # [s3-dice-door]
                   "which already-printed documents the Gazette reads again", tabled=False)   # [s3-dice-door]
    files = _a + [p for p in _new if p not in _a] + _b + [p for p in _old if p not in _b]   # [s3-dice-door]
''', 1),
    ("paper-seed-start",
     r'''                start = random.randrange(max(1, len(words) - 55 + 1))
''',
     r'''                _starts = max(1, len(words) - 55 + 1)   # [s3-dice-door] was randrange(_starts)
                start = min(_starts - 1, int(s3_roll("paper.seed_start", "where in the document a Gazette passage starts") * _starts))   # [s3-dice-door]
''', 1),
    # --- the Pine inbox's spoken acknowledgements ------------------------------
    ("pine-submit",
     r'''        phrase = random.choice(
            pc.get("submit_phrases") or [pc["submit_phrase"]])
''',
     r'''        phrase = s3_choice("pine.submit_phrase", pc.get("submit_phrases") or [pc["submit_phrase"]],   # [s3-dice-door]
                           "which acknowledgement is spoken when a request is submitted", tabled=False)   # [s3-dice-door]
''', 1),
    ("pine-complete",
     r'''        phrase = random.choice(
            pc.get("complete_phrases") or [pc["complete_phrase"]])
''',
     r'''        phrase = s3_choice("pine.complete_phrase", pc.get("complete_phrases") or [pc["complete_phrase"]],   # [s3-dice-door]
                           "which acknowledgement is spoken when a request is resolved", tabled=False)   # [s3-dice-door]
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
