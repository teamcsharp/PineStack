"""[s3-dice-door] The banter road's dice are System 3's.

Operator, 2026-09-27: "I want the roulette system encompassing all with all of
the requests for randomness on the station to be broken down and tabled and
made into a roulette rolodex entry that dice is rolling a chance of hitting."
And: "make sure that each and every request i made for spontaneity makes it to
the roulette system as a customizable entry".

system3_dice_patch.py opened the door (s3_chance, s3_roll, s3_choice,
s3_unrepeated, s3_sample, s3_weighted, _S3Dice) and walked the call road
through it. This tool walks the BANTER road through the same door: every roll
that decides what the pair say on a free round, a single line, or the slot
between records.

  dj_banter          the hosts' weather (the macro moods, the feeling and how
                     hard it pushes, the weather clearing), the talk dial's
                     cold open, the angle stage (gallery hawk, box saga, game
                     tip, pushed section, speakbox seed, bombshell, the full
                     scene vs the short drop, the semantic comeback, the jab,
                     the picture, the track feelers, the booth weather, the
                     stock angle), the second aside, the SFX guy's verdict,
                     the buried heat aside, the disposition
  dj_line           the stock phrase, the chattiness gate, the unreadable
                     title riff, the speakbox seed, the disposition
  accent_directive   the plain-American-English directive (the accent pin)
  station_name_scrub the line that keeps the station's full name
  plot_advance       the storyline's next act taking the round
  heat_reference     which heat aside is let slip
  surplus_topic      the operator's bank above the surplus line
  _record_talk_body  the held-over ad's kind, the deep round
  _dj_loop           the ad slot's kind

Left as the station's own random: anything System 3 already owns or gates off
(dj_banter's line-count randint, approach_pick, the saved-banter replay, the
SHOCK / MENTION / TEMPERS / INTERJECT clauses under _s3_owns, the quote door
that already asks system3_door_roll; track_callback and _prep_intro_pad, which
return first under System 3; the loop's interject, gated on _s3_active) and
what is not the air's content (_dj_speak_floorless's 1-in-5 log sample, the
loop's interject cut point, which is timing). The stock angles' own draws
(domestic_angles, callback_angles) and the pickers behind the angles
(game_tip_pick, drop_bombshell) belong to system3_dice_speakbox_patch.py;
this tool rolls only whether dj_banter reaches for them.

Keys are banter.* / line.* / host.* / station.*; each roll is recorded on the
round it shaped. With System 3 off each helper is the station's own random,
exactly as it was. Needs system3_dice_patch.py applied first (the helpers).

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- dj_banter: the hosts' weather (#321, #371) ---------------------------
    ("host-weather",
     r'''        if random.random() < 0.32:      # more weather, more variance (#371)
            _RADIO.setdefault("speaker_macro", {})[host] = random.choice(
                ["bratty", "petulant", "flustered", "angry", "nervous",
                 "exhausted"])
            autos[host] = True
            state_bump(host, {random.choice(list(EMOTION_DIMS)):
                              random.uniform(0.4, 0.8)})
        elif autos.get(host) and random.random() < 0.5:
''',
     r'''        if s3_chance("host.weather", 0.32, "a host arrives with weather (a mood macro)"):      # more weather, more variance (#371) [s3-dice-door]
            _RADIO.setdefault("speaker_macro", {})[host] = s3_choice("host.weather_macro",   # [s3-dice-door]
                ["bratty", "petulant", "flustered", "angry", "nervous",
                 "exhausted"], "the mood a host arrives in")   # [s3-dice-door]
            autos[host] = True
            state_bump(host, {s3_choice("host.weather_emotion", list(EMOTION_DIMS), "which feeling the weather pushes"):   # [s3-dice-door]
                              0.4 + 0.4 * s3_roll("host.weather_strength", "how hard the weather pushes it")})   # [s3-dice-door]
        elif autos.get(host) and s3_chance("host.weather_clears", 0.5, "a host's weather clears"):   # [s3-dice-door]
''', 1),
    ("talk-radio",
     r'''    if not (angle or force_seed) \
            and random.random() < dj["talk_radio"] / 150.0:
''',
     r'''    if not (angle or force_seed) \
            and s3_chance("banter.talk_radio_seed", dj["talk_radio"] / 150.0,   # [s3-dice-door]
                          "the round opens cold on a speakerbox monologue (the talk dial)", dial="talk_radio"):   # [s3-dice-door]
''', 1),
    # --- dj_banter: the angle stage -------------------------------------------
    ("gallery",
     r'''    if not angle and art_sell_due() and random.random() < 0.08:
''',
     r'''    if not angle and art_sell_due() and s3_chance("banter.gallery_hawk", 0.08, "a gallery picture is held up and taken apart on air"):   # [s3-dice-door]
''', 1),
    ("box-saga",
     r'''    if not angle and random.random() < 0.14:
        angle = box_saga_angle()
''',
     r'''    if not angle and s3_chance("banter.box_saga", 0.14, "the transmitter saga takes the round"):   # [s3-dice-door]
        angle = box_saga_angle()
''', 1),
    ("game-tip",
     r'''    if not angle and random.random() < 0.16:
        angle = game_tip_angle()
''',
     r'''    if not angle and s3_chance("banter.game_tip", 0.16, "a tip out of the game library is traded like shop talk"):   # [s3-dice-door]
        angle = game_tip_angle()
''', 1),
    ("pushed",
     r'''    if not angle and random.random() < 0.6:
        pushed = await asyncio.to_thread(pushed_section_take)
''',
     r'''    if not angle and s3_chance("banter.pushed_section", 0.6, "a section the operator pushed is worked in"):   # [s3-dice-door]
        pushed = await asyncio.to_thread(pushed_section_take)
''', 1),
    ("speakbox-seed",
     r'''            force_seed or random.random() < box_rate_now(dj["speakbox_rate"])):
''',
     r'''            force_seed or s3_chance("banter.speakbox_seed", box_rate_now(dj["speakbox_rate"]),   # [s3-dice-door]
                                    "the round is built on a speakerbox swath", dial="speakbox_rate")):   # [s3-dice-door]
''', 1),
    ("bombshell",
     r'''    dropped = {} if (angle or seed) else (
        drop_bombshell() if random.random() < 0.6 else {})
''',
     r'''    dropped = {} if (angle or seed) else (
        drop_bombshell() if s3_chance("banter.bombshell", 0.6, "a bombshell topic is dropped on a round with nothing else") else {})   # [s3-dice-door]
''', 1),
    ("full-scene",
     r'''    elif seed and random.random() < 0.85:   # both trade doc lines (#360, #522)
''',
     r'''    elif seed and s3_chance("banter.full_scene", 0.85, "the seed becomes a full scene: both trade document lines"):   # both trade doc lines (#360, #522) [s3-dice-door]
''', 1),
    ("scene-semantic",
     r'''                                                 who="cohost")
                    if random.random() < 0.6 else {}) \
''',
     r'''                                                 who="cohost")
                    if s3_chance("banter.scene_rhyme", 0.6,   # [s3-dice-door]
                                 "the comeback is the passage closest in meaning (else a random document)") else {}) \
''', 1),
    ("scene-jab",
     r'''        if random.random() < 0.3:
            jab = await speakbox_quote(
''',
     r'''        if s3_chance("banter.scene_jab", 0.3, "a third document lands a jab in the scene"):   # [s3-dice-door]
            jab = await speakbox_quote(
''', 1),
    ("drop-comeback",
     r'''        if random.random() < 0.5:
            comeback = (await speakbox_semantic_seed(
''',
     r'''        if s3_chance("banter.drop_comeback", 0.5, "the short drop gets a cross-document answer"):   # [s3-dice-door]
            comeback = (await speakbox_semantic_seed(
''', 1),
    ("drop-semantic",
     r'''                who="cohost")
                if random.random() < 0.6 else {}) \
                or await speakbox_quote(exclude=seed.get("file", ""))
''',
     r'''                who="cohost")
                if s3_chance("banter.drop_rhyme", 0.6,   # [s3-dice-door]
                             "the answer is the passage closest in meaning (else a random document)") else {}) \
                or await speakbox_quote(exclude=seed.get("file", ""))
''', 1),
    ("picture",
     r'''        if random.random() < 0.15:
            _pic_name, _pic_desc = await describe_gallery_image()
''',
     r'''        if s3_chance("banter.picture", 0.15, "a picture off the render machine is held up and described"):   # [s3-dice-door]
            _pic_name, _pic_desc = await describe_gallery_image()
''', 1),
    ("track-feelers",
     r'''        if track and random.random() < 0.45:
            about_track.append(
                f"{random.choice(TRACK_FEELERS)} {random.choice(TRACK_FEELINGS)} "
''',
     r'''        if track and s3_chance("banter.track_feeling_on", 0.45, "somebody in the room has a REAL feeling about the record"):   # [s3-dice-door]
            about_track.append(
                f"{s3_choice('banter.track_feeler', TRACK_FEELERS, 'who in the room has the feeling about the record')} "   # [s3-dice-door]
                f"{s3_choice('banter.track_feeling', TRACK_FEELINGS, 'the feeling about the record')} "   # [s3-dice-door]
''', 1),
    ("station-weather",
     r'''        if not angle and random.random() < 0.14:
            # The booth weather (#375, #376): live machine numbers as
''',
     r'''        if not angle and s3_chance("banter.station_weather", 0.14, "the booth weather: live machine numbers as small talk"):   # [s3-dice-door]
            # The booth weather (#375, #376): live machine numbers as
''', 1),
    ("stock-angle",
     r'''        angle = angle or unrepeated(_stock, "angle")
''',
     r'''        angle = angle or unrepeated(_stock, "angle",   # [s3-dice-door]
                                    director=_S3Dice("banter.stock_angle", "which stock angle the free round takes"))   # [s3-dice-door]
''', 1),
    # --- dj_banter: after the angle -------------------------------------------
    ("second-aside",
     r'''    if not caller_name and not seed and not own_material and random.random() < box_rate_now(
            dj["speakbox_rate"]):
''',
     r'''    if not caller_name and not seed and not own_material and s3_chance(   # [s3-dice-door]
            "banter.speakbox_aside", box_rate_now(dj["speakbox_rate"]),   # [s3-dice-door]
            "a speakerbox line is worked into a round with its own subject", dial="speakbox_rate"):   # [s3-dice-door]
''', 1),
    ("seek-verdict",
     r'''    seek_verdict = (not caller_name and bool(dj["drop_voice"])
                    and random.random() < 0.35)
''',
     r'''    seek_verdict = (not caller_name and bool(dj["drop_voice"])
                    and s3_chance("banter.seek_verdict", 0.35, "the pair appeal to the SFX guy for his verdict"))   # [s3-dice-door]
''', 1),
    ("heat-aside",
     r'''    if not caller_name and not _air_theme \
            and random.random() < dj.get("heat_rate", 0.3):
''',
     r'''    if not caller_name and not _air_theme \
            and s3_chance("banter.heat_aside", dj.get("heat_rate", 0.3),   # [s3-dice-door]
                          "a buried aside about how hot the machine is running", dial="heat_rate"):   # [s3-dice-door]
''', 1),
    ("banter-personality",
     r'''                 if not seed and random.random() < float(
                     dj.get("personality") or 0.7) else "")
''',
     r'''                 if not seed and s3_chance("banter.personality", float(   # [s3-dice-door]
                     dj.get("personality") or 0.7), "the disposition colours the round", dial="personality") else "")   # [s3-dice-door]
''', 1),
    # --- dj_line ----------------------------------------------------------------
    ("line-stock",
     r'''    fallback = _dj_fill(random.choice(bank) if bank else "{title}", track)
''',
     r'''    fallback = _dj_fill(s3_choice("line.stock_phrase", bank, "which stock phrase the line falls back on", tabled=False)   # [s3-dice-door]
                        if bank else "{title}", track)   # [s3-dice-door]
''', 1),
    ("line-chattiness",
     r'''    if kind in ("intro", "interject") and random.random() > dj["chattiness"]:
''',
     r'''    if kind in ("intro", "interject") and not s3_chance(   # [s3-dice-door]
            "line.chattiness", dj["chattiness"], "the host riffs a fresh line rather than the stock phrase",   # [s3-dice-door]
            dial="chattiness"):   # [s3-dice-door]
''', 1),
    ("line-unreadable",
     r'''        fallback = unrepeated(list(UNREADABLE_LINES), "unreadable")
''',
     r'''        fallback = s3_unrepeated("line.unreadable", list(UNREADABLE_LINES), "unreadable",   # [s3-dice-door]
                                 "the riff on a title nobody can read")   # [s3-dice-door]
''', 1),
    ("line-speakbox",
     r'''    if seed is not None and random.random() < box_rate_now(
            dj["speakbox_rate"]):
''',
     r'''    if seed is not None and s3_chance("line.speakbox_seed", box_rate_now(   # [s3-dice-door]
            dj["speakbox_rate"]), "a speakerbox line is worked into the host's line", dial="speakbox_rate"):   # [s3-dice-door]
''', 1),
    ("line-personality",
     r'''                 if not aside and random.random() < float(
                     dj.get("personality") or 0.7) else "")
''',
     r'''                 if not aside and s3_chance("line.personality", float(   # [s3-dice-door]
                     dj.get("personality") or 0.7), "the disposition colours the line", dial="personality") else "")   # [s3-dice-door]
''', 1),
    # --- the prompt's directives and the name governor --------------------------
    ("accent-pin",
     r'''    if pin <= 0 or random.random() > pin:
        return ""
''',
     r'''    if pin <= 0 or not s3_chance("line.plain_english", pin, "the prompt demands plain American English", dial="accent_pin"):   # [s3-dice-door]
        return ""
''', 1),
    ("name-kept",
     r'''    if random.random() < 0.25:
        return text
''',
     r'''    if s3_chance("station.name_kept", 0.25, "the line keeps the station's full name"):   # [s3-dice-door]
        return text
''', 1),
    # --- the storyline, the heat, the bank --------------------------------------
    ("plot-act",
     r'''        if not row or random.random() > 0.45:
            return ""
''',
     r'''        if not row or not s3_chance("banter.plot_act", 0.45, "the storyline's next act takes the round"):   # [s3-dice-door]
            return ""
''', 1),
    ("heat-line",
     r'''    return unrepeated(pool, f"heat-{band}")
''',
     r'''    return unrepeated(pool, f"heat-{band}",   # [s3-dice-door]
                      director=_S3Dice("banter.heat_line", "which heat aside is let slip"))   # [s3-dice-door]
''', 1),
    ("surplus-topic",
     r'''        if random.random() > (0.60 + 0.4 * got):
            return {}
''',
     r'''        if not s3_chance("banter.surplus_topic", 0.60 + 0.4 * got,   # [s3-dice-door]
                         "a topic out of the operator's bank (above the surplus line)", dial="surplus"):   # [s3-dice-door]
            return {}
''', 1),
    # --- between the records ----------------------------------------------------
    ("held-ad-kind",
     r'''            roll = random.random()
            if roll < 0.15:
                await dj_engineering_ad()
''',
     r'''            roll = s3_roll("station.held_ad_kind", "which advert plays over the record (engineering < 0.15 < service < 0.35 < a break)")   # [s3-dice-door]
            if roll < 0.15:
                await dj_engineering_ad()
''', 1),
    ("deep-round",
     r'''                    and random.random() < float(dj.get("deep_rate")
                                                or 0.25))
''',
     r'''                    and s3_chance("banter.deep_round", float(dj.get("deep_rate") or 0.25),   # [s3-dice-door]
                                  "the round is a deep one (both co-workers simulated in full)", dial="deep_rate"))   # [s3-dice-door]
''', 1),
    ("ad-slot-kind",
     r'''                    ad_roll = random.random()
''',
     r'''                    ad_roll = s3_roll("station.ad_slot_kind", "which advert fills the slot (engineering < 0.15 < service < 0.35 < a break)")   # [s3-dice-door]
''', 1),
]


# [integration 2026-09-28] system3_lists2_patch.py edited inside this tool's 'heat-line' text
# ([s3-lists2] picked under the band's POOLS1 key, so the seed rows' weights reach it): "applied" is that text with that edit folded in. The anchor is
# unchanged, so a fresh file is patched exactly as before.
_RECONCILED_HEAT_LINE = '    return unrepeated(pool, f"heat-{band}",   # [s3-dice-door]\n                      # [s3-lists2] picked under the band\'s POOLS1 key, so the seed rows\'\n                      # desk weights reach the draw (an evolved line weighs 1)\n                      director=_S3Dice("banter.heat_seed_" + band.replace(" ", "_"),\n                                       "which heat aside is let slip"))   # [s3-dice-door]\n'
EDITS = [(e[0], e[1], _RECONCILED_HEAT_LINE, e[3]) if e[0] == 'heat-line' else e for e in EDITS]

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
