"""[s3-dice4] The last station randoms that chose on-air words outside System
3's roulette roll through the dice door, and the door's pools are editable.

Operator, 2026-09-28: "the point of making everything go on system 3 is to
have no dialogue hit the station unless it is scripted via the RNG roulette
system", and "all of the requests for randomness on the station to be broken
down and tabled and made into a roulette rolodex entry that dice is rolling a
chance of hitting".

Words the station picked with no roll at all:
  rerun-intro            call_rerun_take's intro (CALL_RERUN_INTROS) ->
                         s3_unrepeated, POOLS1 call.rerun_intro; the slots
                         are filled by name (_s3_fill), never str.format
  caller-topic           a caller ringing cold about one of your Topics ->
                         System 3's pick (call.planted_topic; the Topics
                         list is its own editor, so it is not tabled)
  call-scenario(-path)   the scenario, its six beats and its landing (the
                         pure call_scenarios module drew on `random`) ->
                         _S3Weighted: s3_weighted at the catalog's own
                         weights (call.scenario, call.scenario.<beat>,
                         call.scenario.conclusion); needs call_scenarios.py
                         [s3-dice4] (edit_call_scenarios.py) for the picks -
                         without it the module's random() is a recorded roll
  sfxguy-director        sfxguy_line with no System 3 plan: the news break
                         (0.15), the warp dial and the picks off his shelf
                         and his warp pile were random() - now _S3SfxGuyDice
                         (STATION1 sfxguy.news_take / sfxguy.warp_take, picks
                         sfxguy.quip / sfxguy.reaction)
  dice-monologue         /api/dj/dice had no guard: under System 3 the room's
                         answer is its running order's (as speakbox_angle);
                         otherwise speakbox.reaction / speakbox.engage rows
  flood-angle-*          what the pair say cracking under a phone flood ->
                         POOLS1 call.flood_angle

"Only when System 3 is not in charge" - still a recorded roll:
  complaint-import + helpers: complaint_due() is STATION1 sting.complaint
                         (both complaint roads, the cadence's and the sting's)
  complaint-line         POOLS1 sting.complaint_line
  host-tempers           POOLS1 banter.host_temper (rings temper-a/-b kept)
  suspense-format        POOLS1 button.suspense_format
  aside-engage, scene-reaction, angle-monologue, angle-drop,
  angle-reaction-engage  the speakbox fallbacks: POOLS1 speakbox.reaction,
                         speakbox.engage, speakbox.monologue_form,
                         speakbox.drop_form

Through the door but untabled - now POOLS1 rows the operator can edit:
  drop-shelf             sfxguy.id_shelf (the shelf IDs naming the station)
  heat-seed              banter.heat_seed_<band> (heat_lines.json, which the
                         model rewrites every ~25 min, is not frozen into it)
  stock-angle-*          banter.stock_angle (the fixed stock list; the
                         track, sponsor, domestic and callback angles are
                         built per round and stay the station's)
  heat-jokes             call.heat_jokes (HEAT_SO_HOT; the evolved lines too
                         stay the station's)

A tabled pool that could not be edited right:
  callin-who-slot/-fill  call.callin_who carried f"someone on {line_say}": the
                         first roll would freeze that call's line number into
                         POOLS1 for every call-in after it. The row is now the
                         slot "someone on {line}", filled per call (_s3_fill)

Where the desk reaches the draw. Every tabled row set above answers on/off
and rewritten words. The row WEIGHTS reach the pick where the pick's key is
the pool's key and its candidates are the rows' words (the s3_unrepeated
roads, call.heat_jokes, banter.stock_angle). Three roads draw under a
different key or over filled-in words, so only on/off and the words reach
them: banter.heat_seed_<band> (picked as banter.heat_line, with the evolved
lines), sfxguy.id_shelf (picked after {station} is filled), call.callin_who
(picked before {line} is filled - the row's own weight does reach it).

Left untabled on purpose (tabled=False stays; each lives inside an older
dice tool's stored text, and switched as it stands would break its road):
  line.stock_phrase      one key over six DJ-settings phrase banks: the first
                         bank rolled would become the rows for every kind
  ad.break_sponsor, ad.sponsor, banter.interjections
                         DJ-settings lists with their own editor; a POOLS1
                         copy would outrank every later edit there
  call.weather           MACRO_STATES names: a typed row is no voice state
  gallery.hawk_moods     HAWK_MOODS keys: a typed row is a KeyError on air
  angle.topic_shape / angle.topic_fresh_shape
                         BANTER_SHAPES names, filtered per topic
  angle.topic_swerve     (label, text) pairs - a POOLS1 row is one string
  call.duo_name          filtered per call (never the caller's own name);
                         tabling the whole list and filtering after, as the
                         cast names do, is a restructure for the name owner
None of these picks words outside the roulette: each is already a recorded
System 3 roll; only the desk cannot edit its options.

Every rolled key and ring is new or unchanged; with System 3 off each is the
station's own random, as it was. Every anchor sits on lines no other tool's
stored text covers. Verified ready, applied and idempotent on wave A
(int7/app.py) and wave B1 (int8/app_b1.py).

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('complaint-import',
     'from sfx_reaction import COMPLAINT_LINES, complaint_due\n',
     "from sfx_reaction import COMPLAINT_LINES   # [s3-dice4] complaint_due() is System 3's roll now\n", 1),
    ('helpers',
     'SPEAKBOX_DIR = data_path("speakbox")\n',
     ('SPEAKBOX_DIR = data_path("speakbox")\n'
      '\n'
      '\n'
      '# --- [s3-dice4] THE LAST STATION RANDOMS GO THROUGH THE DICE DOOR -------------\n'
      '# "the point of making everything go on system 3 is to have no dialogue hit the\n'
      '# station unless it is scripted via the RNG roulette system" (operator,\n'
      '# 2026-09-28). The door ([s3-dice-door]: s3_chance / s3_pool / s3_unrepeated /\n'
      "# _S3Dice) takes the station's draws; these are what the last roads needed to\n"
      "# go through it: a pure module's weighted draws (the call scenarios), the SFX\n"
      "# Guy's line when no System 3 plan chose it, #292's complaint odds, and a\n"
      '# filler for a tabled template whose words the desk may rewrite.\n'
      '_S3_FILL_SLOT = re.compile(r"\\{([A-Za-z_][A-Za-z0-9_]*)\\}")\n'
      '\n'
      '\n'
      'def _s3_fill(template: Any, **values: Any) -> str:\n'
      '    """Fill `{name}` slots by name, in one pass. A POOLS1 row is the\n'
      "    operator's text: a brace they typed, or a slot this road does not fill,\n"
      '    stays as written - never the KeyError str.format would raise on air."""\n'
      '    return _S3_FILL_SLOT.sub(\n'
      '        lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),\n'
      '        str(template or ""))\n'
      '\n'
      '\n'
      'def complaint_due() -> bool:\n'
      '    """#292\'s one-in-three (sfx_reaction.complaint_due) as a STATION1 row:\n'
      "    the other presenter groans at the board's clip when System 3's die says\n"
      '    so. Both complaint roads - the cadence\'s and the sting\'s - roll it here."""\n'
      '    return s3_chance("sting.complaint", 1.0 / 3.0,\n'
      '                     "the other presenter groans at the board\'s clip (#292)")\n'
      '\n'
      '\n'
      'class _S3Weighted:\n'
      '    """A random source for a pure module that draws by its own weights (the\n'
      '    call scenarios: which scenario, one path per beat, the landing).\n'
      "    draw(what, labels, weights) is System 3's pick at exactly those weights,\n"
      '    recorded under `key.what` with what was on offer; random() is a recorded\n'
      "    roll, for a module that only knows random(). System 3 off: the station's\n"
      '    own random, at the same weights."""\n'
      '\n'
      '    def __init__(self, key: str, label: str = "") -> None:\n'
      '        self.key, self.label = str(key), str(label or key)\n'
      '\n'
      '    def draw(self, what: str, labels: list[Any], weights: list[Any]) -> int:\n'
      '        key = "%s.%s" % (self.key, what) if what else self.key\n'
      '        return s3_weighted(key, [str(x) for x in labels], [float(w or 0) for w in weights],\n'
      '                           "%s: %s" % (self.label, what) if what else self.label)\n'
      '\n'
      '    def random(self) -> float:\n'
      '        return s3_roll(self.key, self.label)\n'
      '\n'
      '\n'
      'class _S3SfxGuyDice:\n'
      '    """sfxguy_line\'s director when no System 3 plan chose his line: the news\n'
      '    break and the warp dial are STATION1 odds, and each pick off a pile (his\n'
      '    shelf sayings, his written warps) is a recorded draw - the three random()\n'
      '    calls and the two picks that line made on the station\'s own random."""\n'
      '\n'
      '    def __init__(self, warp: Any) -> None:\n'
      '        self.warp = max(0.0, min(100.0, float(warp or 0)))\n'
      '\n'
      '    def takes(self, kind: str, available: Any) -> bool:\n'
      '        if not available:\n'
      '            return False\n'
      '        if kind == "news":\n'
      '            return s3_chance("sfxguy.news_take", 0.15,\n'
      '                             "he breaks a news story with a spicy take (#804)")\n'
      '        if kind == "reaction" and self.warp > 0:\n'
      '            return s3_chance("sfxguy.warp_take", self.warp / 100.0,\n'
      '                             "he says a written warp off his pile, not a shelf saying (#799, #820)",\n'
      '                             dial="sfxguy_warp")\n'
      '        return False\n'
      '\n'
      '    def pick(self, label: str, candidates: list[Any]) -> int:\n'
      '        return _S3Dice("sfxguy." + str(label), "which %s he says off his pile" % label).pick(\n'
      '            str(label), list(candidates))\n'
      '\n'
      '    def done(self, line: str, kind: str) -> None:\n'
      '        return None\n'
      '\n'), 1),
    ('sfxguy-director',
     ('        _wstr = max(int(c.get("strength") or 50) for c in _wcrs)\n'
      '        warp = max(warp, min(95, _wstr))\n'),
     ('        _wstr = max(int(c.get("strength") or 50) for c in _wcrs)\n'
      '        warp = max(warp, min(95, _wstr))\n'
      '    # [s3-dice4] a line no System 3 plan chose (a round it did not write)\n'
      "    # still rolls System 3's dice: the news break and the warp dial as\n"
      '    # STATION1 odds, each pick off a pile recorded - never random() here\n'
      '    if director is None:\n'
      '        director = _S3SfxGuyDice(warp)\n'), 1),
    ('rerun-intro',
     ('            intro = unrepeated(list(CALL_RERUN_INTROS), "rerun-intro").format(\n'
      '                name=name, premise=premise or "something")\n'),
     ('            # [s3-dice4] the intro is a POOLS1 row set (call.rerun_intro) drawn\n'
      "            # by System 3's dice; the desk may rewrite it, so the slots are\n"
      "            # filled by name and a stray brace is the operator's words\n"
      '            intro = _s3_fill(s3_unrepeated(\n'
      '                "call.rerun_intro", CALL_RERUN_INTROS, "rerun-intro",\n'
      '                "the host\'s intro to a call aired again from earlier tonight (#1033)"),\n'
      '                name=name, premise=premise or "something")\n'), 1),
    ('caller-topic',
     '                f"\\"{unrepeated(planted, \'caller-topic\')}\\" They have "\n',
     '                f"\\"{unrepeated(planted, \'caller-topic\', director=_S3Dice(\'call.planted_topic\', \'which of your Topics a caller rings about, cold (#395)\'))}\\" They have "   # [s3-dice4]\n', 1),
    ('call-scenario',
     '            target_heat=case_heat(_case) / 3.0 if _case else None)\n',
     ('            target_heat=case_heat(_case) / 3.0 if _case else None,\n'
      '            # [s3-dice4] the scenario, its six beats and its landing are System\n'
      "            # 3's draws at the catalog's own weights (the catalog is the editor)\n"
      '            rng=_S3Weighted("call.scenario", "which scenario frames the call"))\n'), 1),
    ('call-scenario-path',
     '                case_outcome=str(rule.get("text") or ""))\n',
     ('                case_outcome=str(rule.get("text") or ""),\n'
      '                rng=_S3Weighted("call.scenario", "the call\'s path"))   # [s3-dice4]\n'), 1),
    ('dice-monologue',
     ('            f"and then {others} is "\n'
      '            f"{unrepeated(list(SPEAKBOX_REACTIONS), \'reaction\')}, and must "\n'
      '            f"{unrepeated(list(SPEAKBOX_ENGAGE), \'engage\')}, and the room "\n'
      '            "takes the conversation onward from there."\n'),
     ('            "and then "\n'
      "            # [s3-dice4] the guard speakbox_angle has: under System 3 the room's\n"
      "            # answer is its running order's; otherwise the reaction and the\n"
      "            # engagement are POOLS1 rows drawn by System 3's dice\n"
      '            + ("the room answers it - System 3 chooses who responds, the "\n'
      '               "responses, the emotions and the flow."\n'
      '               if _s3_active() else\n'
      '               f"{others} is "\n'
      '               f"{s3_unrepeated(\'speakbox.reaction\', SPEAKBOX_REACTIONS, \'reaction\', \'how the one who hears the passage takes it\')}, and must "\n'
      '               f"{s3_unrepeated(\'speakbox.engage\', SPEAKBOX_ENGAGE, \'engage\', \'what the one who hears the passage must do with it\')}, and the room "\n'
      '               "takes the conversation onward from there.")\n'), 1),
    ('complaint-line',
     '                       line=unrepeated(list(COMPLAINT_LINES), "sting-react"),\n',
     ('                       line=s3_unrepeated("sting.complaint_line", COMPLAINT_LINES, "sting-react",   # [s3-dice4]\n'
      '                                          "what the other presenter groans after the board\'s clip (#292)"),\n'), 1),
    ('host-tempers',
     ('                + unrepeated(list(HOST_TEMPERS), "temper-a") + "; B is "\n'
      '                + unrepeated(list(HOST_TEMPERS), "temper-b")\n'),
     ('                + s3_unrepeated("banter.host_temper", HOST_TEMPERS, "temper-a",   # [s3-dice4]\n'
      '                                "the temper a host is caught in when the dice are on (#676)") + "; B is "\n'
      '                + s3_unrepeated("banter.host_temper", HOST_TEMPERS, "temper-b",\n'
      '                                "the temper a host is caught in when the dice are on (#676)")\n'), 1),
    ('suspense-format',
     '        form = unrepeated(list(SUSPENSE_FORMATS), "button-format")\n',
     ('        form = s3_unrepeated("button.suspense_format", SUSPENSE_FORMATS, "button-format",   # [s3-dice4]\n'
      '                             "the shape of a round you push from the button (#133, #348)")\n'), 1),
    ('aside-engage',
     '        + (f" Whoever hears it must {unrepeated(list(SPEAKBOX_ENGAGE), \'engage\')}"\n',
     '        + (f" Whoever hears it must {s3_unrepeated(\'speakbox.engage\', SPEAKBOX_ENGAGE, \'engage\', \'what the one who hears the passage must do with it\')}"   # [s3-dice4]\n', 1),
    ('scene-reaction',
     '        f"{unrepeated(list(SPEAKBOX_REACTIONS), \'reaction\')}, refusing to "\n',
     '        f"{s3_unrepeated(\'speakbox.reaction\', SPEAKBOX_REACTIONS, \'reaction\', \'how the one who hears the passage takes it\')}, refusing to "   # [s3-dice4]\n', 1),
    ('angle-monologue',
     '    drop = (unrepeated(list(SPEAKBOX_MONOLOGUE), "monologue")\n',
     ('    drop = (s3_unrepeated("speakbox.monologue_form", SPEAKBOX_MONOLOGUE, "monologue",   # [s3-dice4]\n'
      '                          "how a passage lands as a speech (#223)")\n'), 1),
    ('angle-drop',
     ('            else unrepeated(list(SPEAKBOX_DROPS), "drop"))\n'
      '    drop = drop.format(first=first, other=other)\n'),
     ('            else s3_unrepeated("speakbox.drop_form", SPEAKBOX_DROPS, "drop",   # [s3-dice4]\n'
      '                               "how a passage is dropped into the show (#233)"))\n'
      "    drop = _s3_fill(drop, first=first, other=other)   # [s3-dice4] a desk row is the operator's words\n"), 1),
    ('angle-reaction-engage',
     ('        f"{other} is {unrepeated(list(SPEAKBOX_REACTIONS), \'reaction\')}, and "\n'
      '        f"must {unrepeated(list(SPEAKBOX_ENGAGE), \'engage\')} — in the very "\n'),
     ('        f"{other} is {s3_unrepeated(\'speakbox.reaction\', SPEAKBOX_REACTIONS, \'reaction\', \'how the one who hears the passage takes it\')}, and "   # [s3-dice4]\n'
      '        f"must {s3_unrepeated(\'speakbox.engage\', SPEAKBOX_ENGAGE, \'engage\', \'what the one who hears the passage must do with it\')} — in the very "\n'), 1),
    ('callin-who-slot',
     '        ["a caller", "a listener", f"someone on {line_say}",\n',
     '        ["a caller", "a listener", "someone on {line}",   # [s3-dice4] a slot: a tabled row froze the first call\'s line\n', 1),
    ('callin-who-fill',
     ('    angle = (\n'
      '        f"{who} has just rung the station about this, and it is now on air: "\n'),
     ("    who = _s3_fill(who, line=line_say)   # [s3-dice4] this call's line fills the desk row's slot\n"
      '    angle = (\n'
      '        f"{who} has just rung the station about this, and it is now on air: "\n'), 1),
    ('flood-angle-open',
     '                    await dj_banter(None, lines=3, angle=unrepeated([\n',
     '                    await dj_banter(None, lines=3, angle=s3_unrepeated("call.flood_angle", [   # [s3-dice4]\n', 1),
    ('flood-angle-close',
     '                    ], "phonetired"))\n',
     '                    ], "phonetired", "what the pair say, cracking under a phone flood (#352)"))\n', 1),
    ('drop-shelf',
     '    naming = [ln for ln in DROP_LINES if "{station}" in ln] or list(DROP_LINES)\n',
     ('    naming = [ln for ln in DROP_LINES if "{station}" in ln] or list(DROP_LINES)\n'
      '    # [s3-dice4] the shelf is a POOLS1 row set (sfxguy.id_shelf) the desk may\n'
      '    # rewrite; the draw below fills {station} with str.format, so any other\n'
      "    # brace in a row is escaped - the operator's words are never a format error\n"
      '    naming = [ln.replace("{", "{{").replace("}", "}}").replace("{{station}}", "{station}")\n'
      '              for ln in s3_pool("sfxguy.id_shelf", naming, "which shelf station ID he shouts (none written)")]\n'), 1),
    ('heat-seed',
     '    pool = list(HEAT_SEED.get(band, [])) + _heat_read().get(band, [])\n',
     ('    # [s3-dice4] the seed imagery is a POOLS1 row set per band; what the model\n'
      '    # has evolved since (heat_lines.json, rewritten every ~25 minutes) stays\n'
      "    # the station's growing pile, drawn with it by System 3's dice below\n"
      '    pool = (list(s3_pool("banter.heat_seed_" + band.replace(" ", "_"), HEAT_SEED.get(band, []),\n'
      '                         "the heat asides a host lets slip, %s (#626)" % band))\n'
      '            + _heat_read().get(band, []))\n'), 1),
    ('stock-angle-open',
     '                  + domestic_angles() + callback_angles() + [\n',
     '                  + domestic_angles() + callback_angles() + s3_pool("banter.stock_angle", [   # [s3-dice4] a POOLS1 row set\n', 1),
    ('stock-angle-close',
     ('        ])\n'
      '        # The art-hawking governor: outside the ~15-minute window the\n'),
     ('        ], "which stock angle the free round takes"))\n'
      '        # The art-hawking governor: outside the ~15-minute window the\n'), 1),
    ('heat-jokes',
     '    pool = list(HEAT_SO_HOT)\n',
     '    pool = list(s3_pool("call.heat_jokes", HEAT_SO_HOT, "which heat comparatives the pair are handed"))   # [s3-dice4] a POOLS1 row set\n', 1),
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
