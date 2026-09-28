"""[s3-dice-door] The segments' dice are System 3's too.

Operator, 2026-09-27: "I want the roulette system encompassing all with all of
the requests for randomness on the station to be broken down and tabled and
made into a roulette rolodex entry that dice is rolling a chance of hitting."
And: "make sure that each and every request i made for spontaneity makes it to
the roulette system as a customizable entry".

system3_dice_patch.py opened the door (s3_chance, s3_roll, s3_choice,
s3_unrepeated, s3_sample, s3_weighted, _S3Dice) and put the call road, the
manager's memo and the random ad through it. This tool puts the SEGMENTS'
on-air rolls through the same door, each one a STATION1 row (odds) or a
POOLS1 category (options) on the desk, recorded on the round it shaped:

  ads      what a produced advert sells (the road, the sponsor, the service,
           the house tat, the painting and its price), the MX-tape bed and
           the tape, the cease-and-desist after the MX spot, the sponsor
           spot's service, the hand-back line, the break's own rolls (the
           cupboard's share and its spot, the music bed, the rerun, the
           sponsor, the service pitch) and the prices it quotes;
  gallery  which paintings come up, which one the pair look at, the hawk's
           asking price, the buyer's mood(s) and the buyer;
  upstairs what the page from upstairs is on about, which host answers the
           hand on the record player;
  news     the bulletin's bands and stories, the stretch's draw;
  story    how many parts a caller story runs, whether a call opens one;
  call     the case book's prize and heat rolls and its draw, the name book
           (pool, name, the spent-night fallback), the heat comparatives,
           the request-line name, how many turns a call is written to;
  guest    how the guest leaves and how long the farewell runs;
  mixtape  which tape goes on;
  crystal  which of the crystal's lines ride a prompt, the room a tinted bar
           may take.

Left as the station's own random on purpose: timers and jitter (upstairs
clock, story next_due), where a bed drops into a song (the bed-start offsets
and loved_moment, which is also a filter predicate over every favourite), the
vision model's temperature and seed, ad_pick (no caller - its road is
_s3_ad_pick), and the crystal material/stanza pool shuffles (tens of thousands
of chunks; the door's pick is linear in the candidates per draw).

Needs system3_dice_patch.py applied first (the helpers). With System 3 off
each helper is the station's own random, exactly as it was.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- ads: what a produced advert sells (ad_product_one, ad_product_pick) --
    ("ad-sponsor",
     r'''            return unrepeated(pool, "ad-sponsor",
                              keep=max(0, min(4, len(pool) - 1))) if pool \
''',
     r'''            return unrepeated(pool, "ad-sponsor",
                              keep=max(0, min(4, len(pool) - 1)),   # [s3-dice-door]
                              director=_S3Dice("ad.sponsor", "which sponsor a produced advert sells")) if pool \
''', 1),
    ("ad-painting-price",
     r'''            if desc:
                price = random.randint(dj["ad_price_low"], dj["ad_price_high"])
''',
     r'''            if desc:
                price = (_span := range(dj["ad_price_low"], dj["ad_price_high"] + 1))[int(   # [s3-dice-door]
                    s3_roll("ad.painting_price", "the price of the painting a produced advert sells") * len(_span))]   # [s3-dice-door]
''', 1),
    ("ad-service",
     r'''            svc = unrepeated(list(SPONSOR_SERVICES), "ad-service")
''',
     r'''            svc = s3_unrepeated("ad.service", list(SPONSOR_SERVICES), "ad-service", "which of the box's own services a produced advert sells")   # [s3-dice-door]
''', 1),
    ("ad-house",
     r'''            return unrepeated(list(AD_HOUSE_TAT), "ad-house")
''',
     r'''            return s3_unrepeated("ad.house_tat", list(AD_HOUSE_TAT), "ad-house", "which piece of house tat a produced advert sells")   # [s3-dice-door]
''', 1),
    ("ad-road",
     r'''    first = unrepeated(list(roads), "ad-road", keep=2)
''',
     r'''    first = s3_unrepeated("ad.road", list(roads), "ad-road", "which road the next advert's product is tried from first", keep=2)   # [s3-dice-door]
''', 1),
    # --- gallery_product ---------------------------------------------------------
    ("ad-gallery-price",
     r'''    dj = dj_settings()
    price = random.randint(dj["ad_price_low"], dj["ad_price_high"])
''',
     r'''    dj = dj_settings()
    price = (_span := range(dj["ad_price_low"], dj["ad_price_high"] + 1))[int(   # [s3-dice-door]
        s3_roll("ad.gallery_price", "a gallery painting's price in an advert") * len(_span))]   # [s3-dice-door]
''', 1),
    ("ad-gallery-wall",
     r'''    if stems and (not gens or random.random() < 0.6):
''',
     r'''    if stems and (not gens or s3_chance("ad.gallery_from_wall", 0.6, "the painting an advert sells comes off the wall, not the generation ledger")):   # [s3-dice-door]
''', 1),
    ("ad-gallery-piece",
     r'''        subject = random.choice(fresh)
''',
     r'''        subject = s3_choice("ad.gallery_piece", fresh, "which painting off the wall an advert sells", tabled=False)   # [s3-dice-door]
''', 1),
    ("ad-gallery-generation",
     r'''        pick = random.choice(gens)
''',
     r'''        pick = s3_choice("ad.gallery_generation", gens, "which generation an advert sells", tabled=False)   # [s3-dice-door]
''', 1),
    # --- mx_ad_clock: the content roll, not the clock ---------------------------
    ("ad-cease-and-desist",
     r'''            if random.random() < 0.3:
                await asyncio.sleep(90)
''',
     r'''            if s3_chance("ad.cease_and_desist", 0.3, "a cease-and-desist from Ehm Eckx's lawyers arrives after the MX-tape spot"):   # [s3-dice-door]
                await asyncio.sleep(90)
''', 1),
    # --- dj_service_ad, dj_ad ----------------------------------------------------
    ("ad-sponsor-service",
     r'''    name = unrepeated(list(SPONSOR_SERVICES), "sponsor-service")
''',
     r'''    name = s3_unrepeated("ad.sponsor_service", list(SPONSOR_SERVICES), "sponsor-service", "which of the box's own services is tonight's sponsor spot")   # [s3-dice-door]
''', 1),
    ("ad-handoff",
     r'''            line=_dj_fill(unrepeated(
                list(AD_HANDOFFS), "ad_handoff",
''',
     r'''            line=_dj_fill(s3_unrepeated("ad.handoff",   # [s3-dice-door]
                list(AD_HANDOFFS), "ad_handoff", "the line that hands back after an advert",   # [s3-dice-door]
''', 1),
    # --- dj_ad_break: what the break airs (content, not the clock) --------------
    ("ad-talk-spot",
     r'''                _spot = random.choice([r for r in _cupboard
                                       if int(r.get("uses") or 0) == _few])
                said = await handoff_produced(_spot)
                if not said:
                    return ""
                pipeline_log("air", "100% talk took a zero-work produced "
''',
     r'''                _spot = s3_choice("ad.talk_spot", [r for r in _cupboard   # [s3-dice-door]
                                                   if int(r.get("uses") or 0) == _few],   # [s3-dice-door]
                                  "which produced spot a 100%-talk break plays (the least used)", tabled=False)   # [s3-dice-door]
                said = await handoff_produced(_spot)
                if not said:
                    return ""
                pipeline_log("air", "100% talk took a zero-work produced "
''', 1),
    ("ad-cupboard-break",
     r'''        if random.random() < AD_PRODUCED_BREAK_SHARE:
''',
     r'''        if s3_chance("ad.cupboard_break", AD_PRODUCED_BREAK_SHARE, "the break goes to the produced cupboard's least-used spot (#1136)"):   # [s3-dice-door]
''', 1),
    ("ad-cupboard-spot",
     r'''                _spot = random.choice([r for r in _cupboard
                                       if int(r.get("uses") or 0) == _few])
                said = await handoff_produced(_spot)
                if not said:
                    return ""
                pipeline_log("air", "the break went to the produced "
''',
     r'''                _spot = s3_choice("ad.cupboard_spot", [r for r in _cupboard   # [s3-dice-door]
                                                       if int(r.get("uses") or 0) == _few],   # [s3-dice-door]
                                  "which produced spot the cupboard's break plays (the least used)", tabled=False)   # [s3-dice-door]
                said = await handoff_produced(_spot)
                if not said:
                    return ""
                pipeline_log("air", "the break went to the produced "
''', 1),
    ("ad-music-bed",
     r'''    music_ad = (_RADIO.get("on") and random.random() < 0.75
''',
     r'''    music_ad = (_RADIO.get("on") and s3_chance("ad.music_bed", 0.75, "a fresh advert is bedded over a swell of the station's own music (#643)")   # [s3-dice-door]
''', 1),
    ("ad-rerun",
     r'''    if stored and random.random() < rerun:
''',
     r'''    if stored and (s3_chance("ad.rerun", rerun, "a stored spot reruns (eight or more produced spots on the shelf)")   # [s3-dice-door]
                   if len(produced) >= 8 else   # [s3-dice-door]
                   s3_chance("ad.rerun_thin", rerun, "a stored spot reruns while the produced shelf is thin (under eight)")):   # [s3-dice-door]
''', 1),
    ("ad-break-price",
     r'''            art_sell_mark()
            price = random.randint(dj["ad_price_low"], dj["ad_price_high"])
''',
     r'''            art_sell_mark()
            price = (_span := range(dj["ad_price_low"], dj["ad_price_high"] + 1))[int(   # [s3-dice-door]
                s3_roll("ad.break_price", "the price of the painting a live ad break sells") * len(_span))]   # [s3-dice-door]
''', 1),
    ("ad-break-sponsor",
     r'''        product = random.choice(dj["sponsors"])
''',
     r'''        product = s3_choice("ad.break_sponsor", dj["sponsors"], "which sponsor a live ad break sells", tabled=False)   # [s3-dice-door]
''', 1),
    ("ad-break-service",
     r'''    if music_ad and random.random() < 0.3:
        svc = unrepeated(list(SPONSOR_SERVICES), "sponsor-service")
''',
     r'''    if music_ad and s3_chance("ad.sells_service", 0.3, "a music-bed advert sells one of the box's own services (#526)"):   # [s3-dice-door]
        svc = s3_unrepeated("ad.break_service", list(SPONSOR_SERVICES), "sponsor-service", "which service a music-bed advert sells")   # [s3-dice-door]
''', 1),
    # --- ad_produce: the bed (the song, not where it drops in) ------------------
    ("ad-mx-bed",
     r'''    if track_id == "mx" or (not track_id and random.random() < 0.35):
''',
     r'''    if track_id == "mx" or (not track_id and s3_chance("ad.mx_bed", 0.35, "an advert with no song chosen is bedded on an MX mixtape")):   # [s3-dice-door]
''', 1),
    ("ad-mx-tape",
     r'''            _tp = random.choice(tapes)
''',
     r'''            _tp = s3_choice("ad.mx_tape", tapes, "which MX mixtape an advert is bedded on", tabled=False)   # [s3-dice-door]
''', 1),
    # --- the gallery -------------------------------------------------------------
    ("gallery-sample",
     r'''    picks = random.sample(found, min(limit, len(found))) if found else []
''',
     r'''    picks = s3_sample("gallery.sample", found, min(limit, len(found)), "which paintings off the wall come up", tabled=False) if found else []   # [s3-dice-door]
''', 1),
    ("gallery-describe",
     r'''            picked = random.choice(unseen or pool)
''',
     r'''            picked = s3_choice("gallery.describe", unseen or pool, "which painting the pair look at and describe", tabled=False)   # [s3-dice-door]
''', 1),
    ("gallery-hawk-price",
     r'''    ask = price or random.randint(dj["ad_price_low"], dj["ad_price_high"])
''',
     r'''    ask = price or (_span := range(dj["ad_price_low"], dj["ad_price_high"] + 1))[int(   # [s3-dice-door]
        s3_roll("gallery.hawk_price", "the asking price when the pair hawk art") * len(_span))]   # [s3-dice-door]
''', 1),
    ("gallery-hawk-moods",
     r'''        chosen = random.sample(list(HAWK_MOODS), k=random.choice((1, 2)))
''',
     r'''        chosen = s3_sample("gallery.hawk_moods", list(HAWK_MOODS),   # [s3-dice-door]
                           2 if s3_chance("gallery.hawk_two_moods", 0.5, "the buyer is in two moods at once, not one") else 1,   # [s3-dice-door]
                           "the buyer's mood when the pair hawk art", tabled=False)   # [s3-dice-door]
''', 1),
    ("gallery-hawk-buyer",
     r'''        _buyer = random.choice(caller_names())
''',
     r'''        _buyer = s3_choice("gallery.hawk_buyer", caller_names(), "who is on the line to buy the art", tabled=False)   # [s3-dice-door]
''', 1),
    # --- upstairs (content only; the clock's jitter stays the station's) ---------
    ("manager-page-gripe",
     r'''    gripe = unrepeated(list(UPSTAIRS_GRIPES), "upstairs-gripe")
''',
     r'''    gripe = s3_unrepeated("manager.page_gripe", list(UPSTAIRS_GRIPES), "upstairs-gripe", "what the page from upstairs is on about")   # [s3-dice-door]
''', 1),
    ("manager-react-host",
     r'''            who=random.choice(["dj", "cohost"]), by_hand=True)
''',
     r'''            who=s3_choice("manager.react_host", ["dj", "cohost"], "which host answers the hand upstairs", tabled=False), by_hand=True)   # [s3-dice-door]
''', 1),
    # --- news ----------------------------------------------------------------------
    ("news-bands",
     r'''    bands = list(by_band)
    random.shuffle(bands)
''',
     r'''    bands = s3_sample("news.bands", list(by_band), len(by_band),   # [s3-dice-door]
                      "the order a bulletin visits the bands of the page", tabled=False)   # [s3-dice-door]
''', 1),
    ("news-band-story",
     r'''        picks.append(random.choice(by_band[slot]))
''',
     r'''        picks.append(s3_choice("news.band_story", by_band[slot], "which story a bulletin takes from a band of the page", tabled=False))   # [s3-dice-door]
''', 1),
    ("news-draw",
     r'''        random.shuffle(fresh)
        picks = fresh[:want]
''',
     r'''        picks = s3_sample("news.draw", fresh, want, "which stories a news stretch takes", tabled=False)   # [s3-dice-door]
''', 1),
    ("news-draw-coolest",
     r'''        random.shuffle(band)
        picks = band[:want]
''',
     r'''        picks = s3_sample("news.draw_coolest", band, want, "which of the longest-rested stories a stretch takes (every story is inside the window)", tabled=False)   # [s3-dice-door]
''', 1),
    # --- the caller story (#1039): content, not next_due ---------------------------
    ("story-part-count",
     r'''            "parts_planned": random.randint(STORY_PARTS_MIN, STORY_PARTS_MAX),
''',
     r'''            "parts_planned": STORY_PARTS_MIN + int(s3_roll("story.part_count", "how many parts a caller's story runs") * (STORY_PARTS_MAX - STORY_PARTS_MIN + 1)),   # [s3-dice-door]
''', 1),
    ("story-opens",
     r'''        if random.random() < story_rate():
''',
     r'''        if s3_chance("story.opens", story_rate(), "a finished call opens a caller story (#1039)", dial="story_rate"):   # [s3-dice-door]
''', 1),
    # --- the case book (case_pick) -------------------------------------------------
    ("call-case-prize",
     r'''        kind = "prize" if random.random() < prize_rate / 100 else "call"
''',
     r'''        kind = "prize" if s3_chance("call.case_prize", prize_rate / 100, "the case drawn has a prize on the line", dial="caller_case_prize") else "call"   # [s3-dice-door]
''', 1),
    ("call-case-hot",
     r'''        band = (CASE_HOT_HEATS if random.random() < hot_rate / 100
''',
     r'''        band = (CASE_HOT_HEATS if s3_chance("call.case_hot", hot_rate / 100, "the case drawn is a hot one", dial="caller_case_heat")   # [s3-dice-door]
''', 1),
    ("call-case-pick",
     r'''                        else "caller-case",
                        keep=max(1, min(6, len(pool) // 2)))
''',
     r'''                        else "caller-case",
                        keep=max(1, min(6, len(pool) // 2)),   # [s3-dice-door]
                        director=_S3Dice("call.case_pick", "which case off the book (by weight)"))   # [s3-dice-door]
''', 1),
    ("call-case-fallback",
     r'''        or random.choice(pool)
    return case_drawn(dict(chosen))
''',
     r'''        or s3_choice("call.case_fallback", pool, "which case, when the draw names none", tabled=False)   # [s3-dice-door]
    return case_drawn(dict(chosen))
''', 1),
    # --- the name book (name_draw) -------------------------------------------------
    ("call-name-plain",
     r'''        return random.choice(caller_names()), ""
''',
     r'''        return s3_choice("call.name_plain", caller_names(), "a caller's name off the plain list (no name pools on)", tabled=False), ""   # [s3-dice-door]
''', 1),
    ("call-name-pool",
     r'''        pid, pool = random.choices(live, weights=weights, k=1)[0]
''',
     r'''        pid, pool = live[s3_weighted("call.name_pool", [str(q) for q, _p in live], weights,   # [s3-dice-door]
                                     "which name pool a caller's name comes from (the book's weights)")]   # [s3-dice-door]
''', 1),
    ("call-name",
     r'''            return unrepeated(free, f"caller-name-{pid}",
                              keep=min(24, max(0, len(free) - 1))), pid
''',
     r'''            return unrepeated(free, f"caller-name-{pid}",
                              keep=min(24, max(0, len(free) - 1)),   # [s3-dice-door]
                              director=_S3Dice("call.name", "a caller's name off the pool")), pid   # [s3-dice-door]
''', 1),
    ("call-name-spent",
     r'''    return random.choice(pool["names"]), pid
''',
     r'''    return s3_choice("call.name_spent", pool["names"], "a caller's name once every pool is spent for the night", tabled=False), pid   # [s3-dice-door]
''', 1),
    # --- heat_joke_bank, call_line_caller, call_turns_for_slot -------------------
    ("call-heat-jokes",
     r'''    random.shuffle(pool)
    return "; ".join(pool[:most])
''',
     r'''    return "; ".join(s3_sample("call.heat_jokes", pool, most, "which heat comparatives the pair are handed", tabled=False))   # [s3-dice-door]
''', 1),
    ("call-line-name",
     r'''            name = random.choice(caller_names())
''',
     r'''            name = s3_choice("call.line_name", caller_names(), "the request-line caller's name when the book gives none", tabled=False)   # [s3-dice-door]
''', 1),
    ("call-turns",
     r'''            got = random.randint(8, CALL_TURNS_MAX)
''',
     r'''            got = 8 + int(s3_roll("call.turns", "how many turns a call is written to (no phone segment to fill)") * (CALL_TURNS_MAX - 7))   # [s3-dice-door]
''', 1),
    ("call-turns-fallback",
     r'''        return random.randint(8, CALL_TURNS_MAX)
''',
     r'''        return 8 + int(s3_roll("call.turns_fallback", "how many turns a call is written to (when the slot could not be read)") * (CALL_TURNS_MAX - 7))   # [s3-dice-door]
''', 1),
    # --- the guest (dj_guest_send_home) --------------------------------------------
    ("guest-exit",
     r'''        f"{unrepeated(list(GUEST_EXITS), 'guest-exit')} — and the pair "
''',
     r'''        f"{s3_unrepeated('guest.exit', list(GUEST_EXITS), 'guest-exit', 'how the guest leaves the studio')} — and the pair "   # [s3-dice-door]
''', 1),
    ("guest-farewell-lines",
     r'''                            lines=random.randint(8, 13))
''',
     r'''                            lines=8 + int(s3_roll("guest.farewell_lines", "how many lines the guest's farewell round runs") * 6))   # [s3-dice-door]
''', 1),
    # --- mixtape_pick ------------------------------------------------------------------
    ("mixtape-pick",
     r'''    name = unrepeated([str(p) for p in pool], "tape",
                      keep=max(1, len(pool) - 1))
''',
     r'''    name = unrepeated([str(p) for p in pool], "tape",
                      keep=max(1, len(pool) - 1),   # [s3-dice-door]
                      director=_S3Dice("mixtape.pick", "which MX tape goes on"))   # [s3-dice-door]
''', 1),
    # --- the crystal -------------------------------------------------------------------
    ("crystal-lines",
     r'''        return random.sample(rows, k=min(int(most), len(rows)))
''',
     r'''        return s3_sample("crystal.lines", rows, min(int(most), len(rows)), "which of the crystal's own lines ride the prompt", tabled=False)   # [s3-dice-door]
''', 1),
    ("crystal-room",
     r'''        _room = random.uniform(_lo, _hi)
''',
     r'''        _room = _lo + (_hi - _lo) * s3_roll("crystal.room", "how much room a tinted bar may take, as a multiple of its source")   # [s3-dice-door]
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
