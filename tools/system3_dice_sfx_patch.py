"""[s3-dice-door] The SFX Guy's, the sting's and the gold bar's dice are System 3's.

Operator, 2026-09-27: "I want the roulette system encompassing all with all of
the requests for randomness on the station to be broken down and tabled and
made into a roulette rolodex entry that dice is rolling a chance of hitting."
And: "make sure that each and every request i made for spontaneity makes it to
the roulette system as a customizable entry".

system3_dice_patch.py opened the door (s3_chance, s3_roll, s3_choice,
s3_sample, _S3Dice) and walked the call road through it. This tool walks the
SFX road through the same door - every roll that decides what he SAYS, whether
a sting or a gold bar goes out at all, and which bar:
  _sfxguy_news_fill   which lit crystal tints his news take
  _sfxguy_warp_fill   which shelf sayings he warps, the crystal and the mind
                      that lend him a shard, whether the studio shelf lends one
                      (the speakbox dial), react-or-invent, the warp recipe
  drop_liner          the written / shelf station ID when no System 3 line
                      handle drew it (a shadow road): _S3Dice in the ring
  dj_sting            the voice liner shouted where a sample would have gone
  sting_due           whether a sting drops at all (the sfx_rate dial)
  sfx_topic_line      the board topic on his mind when he fills a hole
  sfx_words           how many words his line may run (25 to 50, #1034)
  gold_in_round_due   whether a banked bar fires inside the round (its dial)
  gold_pick           which bar of the least-fired tier goes first
Each is a STATION1 row (odds) or a recorded pick, with the road's own numbers;
with System 3 off each helper is the station's own random, as it was.

Left as they were, on purpose:
  sfxguy_line / _sfxguy_take - under System 3 his node's SfxGuyChooser is
      the director and answers the news / reaction / quip rolls; the random
      fallbacks only run when the round is not System 3's AND _s3_active() is
      False (the call site gates them), i.e. never under System 3.
  _sting_react - its only caller is gated `not _s3_active()`.
  sting_due's never-heard / fresh shares and the unrepeated rings - SFX
      clip FILE rotation (the matcher's job, a separate pass).
  _sting_over_record - sleep jitter only.  _sfx_verdict, scratch_stock - no
      roll of their own (scratch_stock's make_scratch is audio DSP).

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- the SFX Guy's brews: the news take -----------------------------------
    ("news-crystal",
     r'''                _ntint = crystal_tint_note(random.choice(_ncrs))
''',
     r'''                _ntint = crystal_tint_note(s3_choice("sfxguy.news_crystal", _ncrs, "which lit crystal tints his news take", tabled=False))   # [s3-dice-door]
''', 1),
    # --- the invention shed (_sfxguy_warp_fill) --------------------------------
    ("warp-sayings",
     r'''        picks = random.sample(rows, k=min(2, len(rows)))
''',
     r'''        picks = s3_sample("sfxguy.warp_sayings", rows, min(2, len(rows)), "which shelf sayings he warps", tabled=False)   # [s3-dice-door]
''', 1),
    ("warp-crystal",
     r'''            _cr0 = random.choice(_crs0)
''',
     r'''            _cr0 = s3_choice("sfxguy.warp_crystal", _crs0, "which lit crystal tints his brew", tabled=False)   # [s3-dice-door]
''', 1),
    ("warp-mind",
     r'''                    _rid0 = random.choice(_minds0)
''',
     r'''                    _rid0 = s3_choice("sfxguy.warp_mind", _minds0, "whose words (the crystal's minds) lend him a shard", tabled=False)   # [s3-dice-door]
''', 1),
    ("warp-studio-shard",
     r'''                if random.random() < box_rate_now(
                        dj_settings().get("speakbox_rate", 1.0)):
''',
     r'''                if s3_chance("sfxguy.studio_shard", box_rate_now(   # [s3-dice-door]
                        dj_settings().get("speakbox_rate", 1.0)), "the studio shelf lends him a shard of material", dial="speakbox_rate"):   # [s3-dice-door]
''', 1),
    ("warp-react",
     r'''        if context and random.random() < 0.5:
''',
     r'''        if context and s3_chance("sfxguy.warp_react", 0.5, "his brew reacts to the line that just aired (otherwise he warps a saying)"):   # [s3-dice-door]
''', 1),
    ("warp-recipe",
     r'''        recipe = random.choice((
''',
     r'''        recipe = s3_choice("sfxguy.warp_recipe", (   # [s3-dice-door]
''', 1),
    ("warp-recipe-end",
     r'''            "turn it into a proud boast that one-ups everybody "
            "listening",
        ))
''',
     r'''            "turn it into a proud boast that one-ups everybody "
            "listening",
        ), "how he warps the sayings")   # [s3-dice-door]
''', 1),
    # --- the station ID he shouts (drop_liner), when no line handle drew it ---
    ("id-written",
     r'''        line = unrepeated(pool, "drop_liner", keep=10, director=director)   # [s3-roads]
''',
     r'''        line = unrepeated(pool, "drop_liner", keep=10, director=director if director is not None else _S3Dice("sfxguy.id_written", "which written station ID he shouts"))   # [s3-roads] [s3-dice-door]
''', 1),
    ("id-shelf",
     r'''                        "drop_fallback", keep=3, director=director)   # [s3-roads]
''',
     r'''                        "drop_fallback", keep=3, director=director if director is not None else _S3Dice("sfxguy.id_shelf", "which shelf station ID he shouts (none written)"))   # [s3-roads] [s3-dice-door]
''', 1),
    # --- the sting ------------------------------------------------------------
    ("sting-voice-liner",
     r'''    if drop_voice and not force and random.random() < 0.25:
''',
     r'''    if drop_voice and not force and s3_chance("sting.voice_liner", 0.25, "the SFX guy shouts a station ID where a sample would have gone"):   # [s3-dice-door]
''', 1),
    ("sting-drop",
     r'''    if random.random() >= dj["sfx_rate"]:
        return None
''',
     r'''    if not s3_chance("sting.drop", dj["sfx_rate"], "a sting drops after the line (the SFX rate)", dial="sfx_rate"):   # [s3-dice-door]
        return None
''', 1),
    # --- what he is thinking about in a hole, and how long he may run --------
    ("gap-topic",
     r'''    pool = _sfx_topic_rows()
    return random.choice(pool) if pool else ""
''',
     r'''    pool = _sfx_topic_rows()
    return s3_choice("sfxguy.gap_topic", pool, "the board topic on his mind when he fills a hole", tabled=False) if pool else ""   # [s3-dice-door]
''', 1),
    ("words",
     r'''        return random.randint(25, 50)
''',
     r'''        return 25 + min(25, int(s3_roll("sfxguy.words", "how many words his line may run (25 to 50)") * 26))   # [s3-dice-door]
''', 1),
    # --- gold: whether a banked bar fires in the round, and which ------------
    ("gold-in-round",
     r'''    if random.random() >= rate:
        return False
    # At the historical setting this is the old behaviour exactly: the
''',
     r'''    if not s3_chance("gold.in_round", rate, "a banked gold bar fires again inside the round, sting to follow", dial="gold_in_round_rate"):   # [s3-dice-door]
        return False
    # At the historical setting this is the old behaviour exactly: the
''', 1),
    ("gold-pick",
     r'''            random.shuffle(tier)
            for r in tier:
                if (VOICE_MEDIA_DIR / str(r.get("path") or "")).is_file():
''',
     r'''            # [s3-dice-door] System 3 picks the bar that goes first; the
            # shuffle only orders the rest, for a first whose take is gone.
            _first = tier.pop(_S3Dice("gold.pick", "which banked gold bar fires (the least-fired tier)").pick(   # [s3-dice-door]
                "gold", [str(r.get("text") or "")[:160] for r in tier]))   # [s3-dice-door]
            random.shuffle(tier)
            tier.insert(0, _first)   # [s3-dice-door]
            for r in tier:
                if (VOICE_MEDIA_DIR / str(r.get("path") or "")).is_file():
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
