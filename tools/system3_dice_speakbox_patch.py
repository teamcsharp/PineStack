"""[s3-dice-door] The speakbox's dice, and the pair's material, are System 3's.

Operator, 2026-09-27: "I want the roulette system encompassing all with all of
the requests for randomness on the station to be broken down and tabled and
made into a roulette rolodex entry that dice is rolling a chance of hitting."
And: "make sure that each and every request i made for spontaneity makes it to
the roulette system as a customizable entry".

system3_dice_patch.py opened the dice door (s3_chance, s3_roll, s3_choice,
s3_sample, s3_weighted, _S3Dice) and put the call road and the manager through
it. This tool puts the SPEAKBOX and the pair's MATERIAL through the same door:

  speakbox_quote        which document, passage and mind a swath comes from:
                        the theme's and the storyline's weighted document
                        bands (s3_weighted, the station's rank weights), the
                        crystal and its mind, the document itself (System 3
                        draws among what the #360 rotation leaves eligible),
                        the archive and newest dives and their bands, the
                        documents tried next, the used-up document that
                        comes back. The theme (#788), the doc lock (#674),
                        the rotation ring and the cooldowns are untouched.
  speakbox_semantic_seed  the passage out of a pinned document, and the
                        softmax draw among the closest matches (#824)
  swath_best            which of the swaths leads (#1177)
  speakbox_swath_lines  where in the document the swath starts (#895)
  banter_material / banter_pool / banter_pictures
                        which of his things the pair are handed
  domestic_angles / callback_angles
                        who wanted it; which callbacks come back
  bombshell_angle / bombshell_shape_for / drop_bombshell
                        who raises a dropped topic, its shape, its swerve,
                        whether it is said aloud, which topic off the board
  game_tip_pick / topic_set_cycle / draw_saved_banter
                        which game, which topic set, which kept exchange

Odds that follow a setting or a live figure (the theme's strength, a crystal's
strength, box depth, topic_aloud) are passed as the row's dial, so the row
rolls at that value and the setting stays where the operator put it.

Left as the station's own random, on purpose: speakbox_aside,
speakbox_scene_angle and speakbox_angle (each returns before its dice under
_s3_active(), so System 3 never reaches them), and the weighted pre-draw that
feeds the document rotation in speakbox_quote (it is how the station's
weights reach the rotation ring; System 3 makes the draw among what the ring
leaves). speakbox_flavor has no dice of its own (it is a speakbox_quote).

No awaits, locks or I/O are added: the speakbox roads are hot. With System 3
off each helper is the station's own random, exactly as it was.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- speakbox_quote: the theme, the storyline, the crystal ---------------
    ("theme-roll",
     r'''            _troll = random.random() < _tp
''',
     r'''            _troll = s3_chance("speakbox.theme", _tp, "the swath comes from tonight's theme (#788)",   # [s3-dice-door]
                               dial="theme strength")   # [s3-dice-door]
''', 1),
    ("theme-doc",
     r'''                        _tdoc = random.choices(
                            _pool, weights=[_n - i for i in range(_n)],
                            k=1)[0]
''',
     r'''                        _tdoc = _pool[s3_weighted(   # [s3-dice-door]
                            "speakbox.theme_doc", [str(x) for x in _pool], [_n - i for i in range(_n)],   # [s3-dice-door]
                            "which document serves tonight's theme (the nearer, the likelier)")]   # [s3-dice-door]
''', 1),
    ("story-roll",
     r'''            if _plt and random.random() < 0.45:
''',
     r'''            if _plt and s3_chance("speakbox.story", 0.45, "the swath serves the storyline that owns the half hour (#907)"):   # [s3-dice-door]
''', 1),
    ("story-doc",
     r'''                _pdoc = (random.choices(
                    _ppool, weights=[_pn - i for i in range(_pn)],
                    k=1)[0] if _ppool else "")
''',
     r'''                _pdoc = (_ppool[s3_weighted(   # [s3-dice-door]
                    "speakbox.story_doc", [str(x) for x in _ppool], [_pn - i for i in range(_pn)],   # [s3-dice-door]
                    "which document serves the storyline's act (the nearer, the likelier)")]   # [s3-dice-door]
                         if _ppool else "")   # [s3-dice-door]
''', 1),
    ("crystal-pick",
     r'''            _cr = random.choice(_crs)
''',
     r'''            _cr = s3_choice("speakbox.crystal", _crs, "which switched-on crystal bends the swath (#834)", tabled=False)   # [s3-dice-door]
''', 1),
    ("crystal-mind",
     r'''            if _minds and random.random() < _p:
                rid = random.choice(_minds)
''',
     r'''            if _minds and s3_chance("speakbox.crystal_mind", _p, "the swath comes from the crystal's own minds (#834)",   # [s3-dice-door]
                                    dial="crystal strength"):   # [s3-dice-door]
                rid = s3_choice("speakbox.crystal_mind_pick", _minds, "which of the crystal's minds", tabled=False)   # [s3-dice-door]
''', 1),
    # --- speakbox_quote: the document, the dives, the order, the repeat ------
    ("doc-draw",
     r'''        f"doc:{key}", keep=max(1, min(len(files) - 1,
                                      int(round(6 + 10 * _depth)))))
''',
     r'''        f"doc:{key}", keep=max(1, min(len(files) - 1,
                                      int(round(6 + 10 * _depth)))),   # [s3-dice-door]
        # the station's weights drew the pool above; System 3 draws among what the rotation leaves   # [s3-dice-door]
        director=_S3Dice("speakbox.doc", "which document the swath comes from (weighted, past the rotation)"))   # [s3-dice-door]
''', 1),
    ("dive-band",
     r'''        return random.choice(band).name
''',
     r'''        return s3_choice("speakbox.archive_doc" if oldest_end else "speakbox.newest_doc",   # [s3-dice-door]
                         [q.name for q in band],   # [s3-dice-door]
                         "which of the oldest documents the archive dive leads with" if oldest_end   # [s3-dice-door]
                         else "which of the newest documents leads (scoured promptly)", tabled=False)   # [s3-dice-door]
''', 1),
    ("dives",
     r'''    if len(files) > 2 and random.random() < (0.25 + 0.30 * _depth):
        first = _band(files, True)
    elif len(files) > 2 and random.random() < 0.32:
''',
     r'''    if len(files) > 2 and s3_chance("speakbox.archive_dive", 0.25 + 0.30 * _depth,   # [s3-dice-door]
                                    "the swath dives into the archive: an old document leads (#478)",   # [s3-dice-door]
                                    dial="box depth (#895)"):   # [s3-dice-door]
        first = _band(files, True)
    elif len(files) > 2 and s3_chance("speakbox.newest_dive", 0.32, "a newly added document leads (#547)"):   # [s3-dice-door]
''', 1),
    ("next-docs",
     r'''             + random.sample([p for p in files if p.name != first],
                             len(files) - 1))
''',
     r'''             + s3_sample("speakbox.next_docs", [p for p in files if p.name != first],   # [s3-dice-door]
                         min(5, len(files) - 1),   # the loop below reads order[:6]   # [s3-dice-door]
                         "the documents tried next if the drawn one is used up", tabled=False))   # [s3-dice-door]
''', 1),
    ("exhausted-doc",
     r'''            exhausted = random.choice(
                [r for r in _spent if _age(r) <= _oldest + 1.0]) or exhausted
''',
     r'''            _tied = [r for r in _spent if _age(r) <= _oldest + 1.0]   # [s3-dice-door]
            _tn = s3_choice("speakbox.exhausted_doc", [r[0] for r in _tied],   # [s3-dice-door]
                            "which used-up document comes back (the longest rested)", tabled=False)   # [s3-dice-door]
            exhausted = next((r for r in _tied if r[0] == _tn), None) or exhausted   # [s3-dice-door]
''', 1),
    # --- speakbox_semantic_seed, swath_best, speakbox_swath_lines -------------
    ("pin-passage",
     r'''                drawn = random.choice(chunks)
''',
     r'''                drawn = {"text": s3_choice("speakbox.pin_passage", [c.get("text") for c in chunks],   # [s3-dice-door]
                                           "which passage of the pinned document (#786)", tabled=False)}   # [s3-dice-door]
''', 1),
    ("semantic-hit",
     r'''            hits = [random.choices(_cands, weights=_ws, k=1)[0]]
''',
     r'''            hits = [_cands[s3_weighted(   # [s3-dice-door]
                "speakbox.semantic_hit",   # [s3-dice-door]
                [str(h.get("file") or "") + ": " + str(h.get("text") or "")[:120] for h in _cands], _ws,   # [s3-dice-door]
                "which close match seeds the round (the closer, the likelier, #824)")]]   # [s3-dice-door]
''', 1),
    ("swath-best",
     r'''        return random.choices(rows, weights=scores, k=1)[0]
''',
     r'''        return rows[s3_weighted("speakbox.swath_best", [str(p.get("text") or "")[:160] for p in rows], scores,   # [s3-dice-door]
                                "which swath leads (the more intriguing, the likelier, #1177)")]   # [s3-dice-door]
''', 1),
    ("swath-start",
     r'''    start = (random.randrange(min(floor, last - 1), last)
             if floor else random.randrange(last))
''',
     r'''    _lo = min(floor, last - 1)          # randrange(_lo, last); 0 at rest   # [s3-dice-door]
    start = min(last - 1, _lo + int(s3_roll("speakbox.swath_start", "where in the document the swath starts")   # [s3-dice-door]
                                    * (last - _lo)))   # [s3-dice-door]
''', 1),
    # --- the pair's material --------------------------------------------------
    ("material-turns",
     r'''        random.shuffle(turns)
        for text in turns:
''',
     r'''        turns = s3_sample("topic.material_turn", turns, max(1, limit - len(bits)),   # [s3-dice-door]
                          "which of the things he asked the box become material (#399)", tabled=False)   # [s3-dice-door]
        for text in turns:
''', 1),
    ("pool",
     r'''    random.shuffle(out)
    return out[:limit]
''',
     r'''    return s3_sample("topic.pool", out, limit,   # [s3-dice-door]
                     "which of his things the pair build a story out of (#191)", tabled=False)   # [s3-dice-door]
''', 1),
    ("domestic-who",
     r'''        f"{random.choice(DOMESTIC_WHO)} came to you the other day wanting "
''',
     r'''        f"{s3_choice('angle.domestic_who', DOMESTIC_WHO, 'who at home wanted it (the domestic story)')} came to you the other day wanting "   # [s3-dice-door]
''', 1),
    ("callbacks",
     r'''    random.shuffle(out)
    return out[:count]
''',
     r'''    return s3_sample("angle.callback", out, count,   # [s3-dice-door]
                     "which remember-that-time callbacks the pair get (#190)", tabled=False)   # [s3-dice-door]
''', 1),
    ("commission-roll",
     r'''        random.shuffle(gens)
        if gens and random.random() < 0.4:
''',
     r'''        if gens and s3_chance("topic.commission", 0.4, "one of his own picture commissions joins the material (#419)"):   # [s3-dice-door]
''', 1),
    ("commission-pick",
     r'''            subject = " ".join(str(
                gens[0].get("request") or gens[0].get("tags") or "").split())
''',
     r'''            subject = s3_choice("topic.commission_pick", [" ".join(str(   # [s3-dice-door]
                g.get("request") or g.get("tags") or "").split()) for g in gens],   # [s3-dice-door]
                "which of his commissions", tabled=False)   # [s3-dice-door]
''', 1),
    # --- the topic board, its shapes, the kept lines, the games ---------------
    ("topic-set",
     r'''    return topic_sets_load(random.choice(pool))
''',
     r'''    return topic_sets_load(s3_choice("topic.set", pool, "which topic set goes on the desk (the random mode)", tabled=False))   # [s3-dice-door]
''', 1),
    ("topic-raiser",
     r'''    first = random.choice(["A", "B"])
    other = "B" if first == "A" else "A"
    deck = dict(BANTER_SHAPES)
''',
     r'''    first = s3_choice("angle.topic_raiser", ["A", "B"], "which host raises the dropped topic", tabled=False)   # [s3-dice-door]
    other = "B" if first == "A" else "A"
    deck = dict(BANTER_SHAPES)
''', 1),
    ("topic-shape",
     r'''    name = shape if shape in deck else random.choice(
        [row[0] for row in BANTER_SHAPES])
''',
     r'''    name = shape if shape in deck else s3_choice(   # [s3-dice-door]
        "angle.topic_shape", [row[0] for row in BANTER_SHAPES],   # [s3-dice-door]
        "the shape a dropped topic arrives in (#1161)", tabled=False)   # [s3-dice-door]
''', 1),
    ("topic-swerve",
     r'''    swerve, how_far = random.choice(BANTER_SWERVES)
''',
     r'''    swerve, how_far = s3_choice("angle.topic_swerve", BANTER_SWERVES, "how far sideways the topic goes", tabled=False)   # [s3-dice-door]
''', 1),
    ("topic-aloud",
     r'''        if aloud > 0 and random.random() < aloud / 100.0:
''',
     r'''        if aloud > 0 and s3_chance("angle.topic_aloud", aloud / 100.0,   # [s3-dice-door]
                                   "the topic is said out loud: the conversation starter (#1252)",   # [s3-dice-door]
                                   dial="topic_aloud"):   # [s3-dice-door]
''', 1),
    ("topic-fresh-shape",
     r'''        return random.choice(fresh) if fresh else ""
''',
     r'''        return (s3_choice("angle.topic_fresh_shape", fresh, "a shape this topic has not played yet (#1161)", tabled=False)   # [s3-dice-door]
                if fresh else "")   # [s3-dice-door]
''', 1),
    ("bombshell",
     r'''    chosen = random.choice(
        [r for r in rows if int(r.get("used") or 0) == fewest])
    # #1161: and a shape it has not played yet, carried on the row so the
''',
     r'''    chosen = s3_choice(   # [s3-dice-door]
        "topic.bombshell", [r for r in rows if int(r.get("used") or 0) == fewest],   # [s3-dice-door]
        "which topic off the board (the least aired)", tabled=False)   # [s3-dice-door]
    # #1161: and a shape it has not played yet, carried on the row so the
''', 1),
    ("kept-exchange",
     r'''    chosen = random.choice(
        [r for r in rows if int(r.get("used") or 0) == fewest])
    with _SAVED_LOCK:
''',
     r'''    chosen = s3_choice(   # [s3-dice-door]
        "topic.kept_exchange", [r for r in rows if int(r.get("used") or 0) == fewest],   # [s3-dice-door]
        "which kept exchange comes back (the least aired, #752)", tabled=False)   # [s3-dice-door]
    with _SAVED_LOCK:
''', 1),
    ("game-tip",
     r'''        data = json.loads(random.choice(files).read_text())
''',
     r'''        data = json.loads(s3_choice("topic.game_tip", files, "which game out of the cheats library (#567)",   # [s3-dice-door]
                                    tabled=False).read_text())   # [s3-dice-door]
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
