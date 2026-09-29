#!/usr/bin/env python3
"""[everything-rolls] The deterministic picks that decide what goes on air, rolled.

"I want all the logic exceptions conformed to the RNG roulette node system so
these decisions are up to chance and are able to be traced to roulette choices
and table offerings." (operator, 2026-09-29)

The sweep (docs in the hand-back) found the remaining plain-random / first /
least-recent picks on the air roads. This converts the ones that touch air
most often, each through the dice door (s3_roll / _S3Dice / s3_unrepeated), so
the dice are recorded on System 3's desk and traceable:

  cadence-cue    _sfx_cadence_additions_inner: picture-or-sound for a due SFX
                 slot was random.random -> s3_roll("sfx.cadence_picture")      (every ~2 lines)
  gap-video      _sfx_any_video: the gap filler's picture clip was a plain
                 unrepeated() draw -> norepeat_roll_clip("sfx.gap_video"):
                 24 h-heard clips struck, then System 3 rolls; the roll rides
                 the clip to the sting row (origin ledger)                     (every gap)
  gap-audio      _sfx_any_audio's walked-pool fallback, the same ("sfx.gap_audio")
  ad-clip        voice_ad_person_clip: random.choice over the top 8 matches and
                 over the 80 newest indexed clips -> _S3Dice("ads.person_clip",
                 "ads.person_clip_any")                                        (every video ad)
  upstairs-voc   dj_upstairs_render: the memo's vocoder character was an
                 unrepeated() with no director -> s3_unrepeated("upstairs.vocoder"),
                 a POOLS1 row the desk may edit                                (every memo)
  sfxguy-quip    sfxguy_line: quips heard inside the day are not offered, and
                 with nothing left he stays quiet (recorded) instead of the
                 least-recently-said repeat                                    (SFX Guy lines)

REQUIRES norepeat_24h_patch.py (norepeat_roll_clip, norepeat_text_used).

    python3 tools/everything_rolls_patch.py --check | --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3_patchlib import Edit, run  # noqa: E402

A = "app.py"

CUE_ANCHOR = "            max_seconds=max(1.0, sfx_cap_seconds()), random_float=random.random,\n"
CUE_NEW = '''            max_seconds=max(1.0, sfx_cap_seconds()),
            random_float=lambda: s3_roll("sfx.cadence_picture",                # [everything-rolls:cadence-cue]
                                         "whether a due SFX slot reaches for a picture (MP4) "
                                         "before a sound, against the video share dial"),
'''

GAPV_ANCHOR = '''    got = unrepeated([str(p) for p in pool], "sting",
                     keep=sting_keep(len(pool)))                   # #1223
    return Path(got) if got else None
'''
GAPV_NEW = '''    # [everything-rolls:gap-video] the day's heard clips struck, then System 3
    # rolls (sfx.gap_video) - the roll rides the clip to its sting row
    return norepeat_roll_clip(pool, "sfx.gap_video", "which picture clip answers the gap (the airable video pool)")
'''

GAPA_ANCHOR = '''    names = unrepeated([str(p) for p in pool], "sting",
                       keep=sting_keep(len(pool)))                 # #1223
    return Path(names) if names else None
'''
GAPA_NEW = '''    # [everything-rolls:gap-audio] the day's heard clips struck, then System 3 rolls (sfx.gap_audio)
    return norepeat_roll_clip(pool, "sfx.gap_audio", "which sound clip answers the gap (the walked pool)")
'''

ADTOP_ANCHOR = "        path, seconds, candidate = random.choice(picked[:min(8, len(picked))])\n"
ADTOP_NEW = '''        _top = picked[:min(8, len(picked))]                                  # [everything-rolls:ad-clip]
        _k = _S3Dice("ads.person_clip", "which of the best-matched clips a video ad is built on").pick(
            "ads.person_clip", [str(getattr(p[0], "stem", p[0])) for p in _top])
        path, seconds, candidate = _top[_k if 0 <= _k < len(_top) else 0]
'''

ADANY_ANCHOR = "            row = random.choice(rows[:min(80, len(rows))])\n"
ADANY_NEW = '''            _top = rows[:min(80, len(rows))]                                 # [everything-rolls:ad-clip-any]
            _k = _S3Dice("ads.person_clip_any", "which speech-indexed clip a video ad falls back to").pick(
                "ads.person_clip_any", [str(r[1] or r[0] or "") for r in _top])
            row = _top[_k if 0 <= _k < len(_top) else 0]
'''

VOC_ANCHOR = '        unrepeated(names, "upstairs-vocode") if names else "megaphone")\n'
VOC_NEW = ('        s3_unrepeated("upstairs.vocoder", names, "upstairs-vocode",   # [everything-rolls:upstairs-voc]\n'
           '                      "the manager memo\'s vocoder character") if names else "megaphone")\n')

QUIP_ANCHOR = "                if now - float(said.get(_sfxguy_key(r)) or 0) > 3600]\n"
QUIP_NEW = '''                if now - float(said.get(_sfxguy_key(r)) or 0) > 3600
                and not norepeat_text_used(r)]                                # [everything-rolls:sfxguy-quip]
        if not pool and norepeat_on():
            norepeat_refuse("line", "", "sfxguy", why="every quip on his shelf was heard inside the day "
                            "(or this hour) - he stays quiet rather than repeat one", stage="select", say=False)
            return ""
'''

EDITS = [
    Edit("cadence-cue", A, CUE_ANCHOR, CUE_NEW, "[everything-rolls:cadence-cue]", "replace"),
    Edit("gap-video", A, GAPV_ANCHOR, GAPV_NEW, "[everything-rolls:gap-video]", "replace"),
    Edit("gap-audio", A, GAPA_ANCHOR, GAPA_NEW, "[everything-rolls:gap-audio]", "replace"),
    Edit("upstairs-voc", A, VOC_ANCHOR, VOC_NEW, "[everything-rolls:upstairs-voc]", "replace"),
    Edit("sfxguy-quip", A, QUIP_ANCHOR, QUIP_NEW, "[everything-rolls:sfxguy-quip]", "replace"),
]

if __name__ == "__main__":
    sys.exit(run("everything_rolls_patch", EDITS, requires=[("app.py", "[no-repeat-24h:helpers]")]))
