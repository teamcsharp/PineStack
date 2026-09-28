"""[s3-dice-door] The station's own dice are System 3's.

Operator, 2026-09-27: "I want the roulette system encompassing all with all of
the requests for randomness on the station to be broken down and tabled and
made into a roulette rolodex entry that dice is rolling a chance of hitting."
And: "make sure that each and every request i made for spontaneity makes it to
the roulette system as a customizable entry".

Every call a station road makes on the air's behalf to random() -
random.random() < p, random.choice(...), random.sample(...), the weighted
shelf draws - goes through System 3's dice door (system3_runtime: chance,
pool, pick, roll):
  s3_chance(key, odds, label, dial="")   a yes/no at its odds: a STATION1 row
                                         (or the desk dial it follows)
  s3_pool(key, options, label)           the options a pick draws from: a
                                         POOLS1 category the desk can edit
  s3_choice / s3_unrepeated / s3_sample  a pick among them, System 3's draw
  s3_weighted(key, labels, weights)      a draw by weights the station keeps
                                         itself (the ending shelf, the deck)
  s3_roll(key, label)                    a plain number in [0, 1)
Each roll is recorded on the round it shaped (STATION events, before its turns)
and in the Audit feed. With System 3 off each helper is the station's own
random, exactly as it was.

This tool: the helpers, and the call road's rolls (dj_call_generated, dj_caller,
dj_callin, the ending shelf, the behaviour deck, the case book, the caller's
subject bands, the storyline caller), the manager's (the memo's branches, the
manner of his call) and the random ad.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

HELPERS = r'''            _recent_save()
    return pick


# --- [s3-dice-door] THE STATION'S OWN DICE ARE SYSTEM 3'S ---------------------
# "all of the requests for randomness on the station to be broken down and
# tabled and made into a roulette rolodex entry that dice is rolling a chance
# of hitting" (operator, 2026-09-27). Every roll below is a row on System 3's
# desk - STATION1 (odds) and POOLS1 (options) - added the first time the road
# makes it with the road's own numbers, drawn by System 3, recorded on the
# round it shaped. System 3 off: the station's own random, as it was.
def s3_chance(key: str, odds: float, label: str = "", dial: str = "") -> bool:
    fn = globals().get("system3_chance")
    if fn:
        try:
            got = fn(key, float(odds or 0), label, dial)
        except Exception:  # noqa: BLE001
            got = None
        if got is not None:
            return bool(got)
    return random.random() < float(odds or 0)


def s3_roll(key: str, label: str = "") -> float:
    fn = globals().get("system3_roll")
    if fn:
        try:
            got = fn(key, label)
        except Exception:  # noqa: BLE001
            got = None
        if isinstance(got, float):
            return got
    return random.random()


def s3_pool(key: str, options: Any, label: str = "") -> list[str]:
    opts = [str(o) for o in (options or [])]
    fn = globals().get("system3_pool")
    if fn and opts:
        try:
            got = fn(key, opts, label)
        except Exception:  # noqa: BLE001
            got = None
        if isinstance(got, list) and got:
            return [str(x) for x in got]
    return opts


class _S3Dice:
    """A director for unrepeated() and the picks below: System 3 draws among
    the options still eligible, with the desk's weights."""

    def __init__(self, key: str, label: str = "", weights: Any = None) -> None:
        self.key, self.label, self.weights = key, label, weights

    def pick(self, _label: str, candidates: list[Any]) -> int:
        fn = globals().get("system3_pick")
        if fn and candidates:
            try:
                got = fn(self.key, [str(c) for c in candidates], self.label, self.weights)
            except Exception:  # noqa: BLE001
                got = None
            if isinstance(got, int) and 0 <= got < len(candidates):
                return got
        if not candidates:
            return 0
        if self.weights is not None and sum(float(w or 0) for w in self.weights) > 0:
            return random.choices(range(len(candidates)), weights=[float(w or 0) for w in self.weights], k=1)[0]
        return random.randrange(len(candidates))


def s3_choice(key: str, options: Any, label: str = "", tabled: bool = True) -> Any:
    opts = list(options or [])
    if not opts:
        raise IndexError("s3_choice from an empty pool")
    pool = s3_pool(key, opts, label) if tabled else opts
    return pool[_S3Dice(key, label).pick(key, pool)]


def s3_unrepeated(key: str, options: Any, ring: str, label: str = "", keep: int = 8) -> str:
    return unrepeated(s3_pool(key, options, label), ring, keep=keep, director=_S3Dice(key, label))


def s3_sample(key: str, options: Any, k: int, label: str = "", tabled: bool = True) -> list[Any]:
    left = list(s3_pool(key, options, label) if tabled else list(options or []))
    out = []
    for _ in range(max(0, min(int(k), len(left)))):
        out.append(left.pop(_S3Dice(key, label).pick(key, left)))
    return out


def s3_weighted(key: str, labels: list[str], weights: list[float], label: str = "") -> int:
    """A draw by weights the station keeps itself (the ending shelf, the
    behaviour deck): System 3's number, those weights, recorded."""
    return _S3Dice(key, label, list(weights)).pick(key, list(labels))


# --- The speakbox: other people's words'''

EDITS = [
    ("helpers",
     r'''            _recent_save()
    return pick


# --- The speakbox: other people's words''', HELPERS, 1),
    # --- dj_call_generated ---------------------------------------------------
    ("call-regular",
     r'''        if fresh and random.random() < 0.6:
''',
     r'''        if fresh and s3_chance("call.regular", 0.6, "a regular rings rather than a stranger"):   # [s3-dice-door]
''', 1),
    ("call-regular-pick",
     r'''            pick = unrepeated([r.get("name", "") for r in pool],
                              "caller-row", keep=max(1, len(pool) - 1))
''',
     r'''            pick = unrepeated([r.get("name", "") for r in pool],
                              "caller-row", keep=max(1, len(pool) - 1),
                              director=_S3Dice("call.regular_pick", "which regular rings"))   # [s3-dice-door]
''', 1),
    ("call-character",
     r'''    if seed and not caller.get("id") and random.random() < 0.6:
''',
     r'''    if seed and not caller.get("id") and s3_chance("call.character", 0.6, "the caller is a character named in the speakerbox document"):   # [s3-dice-door]
''', 1),
    ("call-state",
     r'''    state = unrepeated(list(CALLER_STATES), "caller-state")
''',
     r'''    state = s3_unrepeated("call.state", list(CALLER_STATES), "caller-state", "the state a caller rings in")   # [s3-dice-door]
''', 1),
    ("call-weather",
     r'''            random.choice(list(CALLER_WEATHER))
            if random.random() < 0.5 else "")
''',
     r'''            s3_choice("call.weather", list(CALLER_WEATHER), "the weather a caller arrives in (their voice)", tabled=False)
            if s3_chance("call.weather_on", 0.5, "the caller arrives in some weather") else "")   # [s3-dice-door]
''', 1),
    ("call-insanity",
     r'''    if insanity and random.random() < insanity / 100:
''',
     r'''    if insanity and s3_chance("call.insanity", insanity / 100, "the speakerbox obsession (caller insanity)", dial="caller_insanity"):   # [s3-dice-door]
''', 1),
    ("call-prefers",
     r'''    if random.random() < 0.3:
        favourite = random.choice(["A", "B"])
''',
     r'''    if s3_chance("call.prefers_host", 0.3, "the caller openly prefers one host"):   # [s3-dice-door]
        favourite = s3_choice("call.preferred_host", ["A", "B"], "which host the caller prefers", tabled=False)
''', 1),
    ("call-tickets",
     r'''    if (winning_call and random.random() < 0.35) or random.random() < 0.15:
''',
     r'''    if ((winning_call and s3_chance("call.tickets_winner", 0.35, "a winning caller also wins arena tickets"))
            or s3_chance("call.tickets", 0.15, "the lucky caller wins arena tickets")):   # [s3-dice-door]
''', 1),
    ("call-tickets-act",
     r'''        act = random.choice(acts) if acts else "a mystery headliner"
''',
     r'''        act = (s3_choice("call.tickets_act", acts, "whose show the tickets are for", tabled=False)
               if acts else "a mystery headliner")   # [s3-dice-door]
''', 1),
    ("call-wins",
     r'''    if winning_call or random.random() < 0.22:
''',
     r'''    if winning_call or s3_chance("call.wins_something", 0.22, "MID-CALL the caller WINS SOMETHING"):   # [s3-dice-door]
''', 1),
    ("call-prize-kind",
     r'''                  ) if (_piece and random.random() < 0.6) else random.choice((
''',
     r'''                  ) if (_piece and s3_chance("call.prize_painting", 0.6, "the prize is a painting off the wall")) else s3_choice("call.prizes", (   # [s3-dice-door]
''', 1),
    ("call-prize-list",
     r'''            "a signed photograph of the two of them, unsigned as yet"))
        _joy = random.random() < 0.5
''',
     r'''            "a signed photograph of the two of them, unsigned as yet"), "what a caller can win")
        _joy = s3_chance("call.prize_joy", 0.5, "the winner is thrilled (otherwise crushed)")   # [s3-dice-door]
''', 1),
    ("call-news",
     r'''    if random.random() < 0.3:
        try:
            headlines = await drudge_headlines(10)
            if headlines:
                story = random.choice(headlines)
''',
     r'''    if s3_chance("call.news", 0.3, "the caller brings a headline and has opinions"):   # [s3-dice-door]
        try:
            headlines = await drudge_headlines(10)
            if headlines:
                story = s3_choice("call.headline", headlines, "which headline", tabled=False)
''', 1),
    ("call-speech",
     r'''    if random.random() < 0.25:
        speech = await speakbox_quote(most=10, cap=900)
''',
     r'''    if s3_chance("call.speech", 0.25, "the caller launches into a whole prepared monologue"):   # [s3-dice-door]
        speech = await speakbox_quote(most=10, cap=900)
''', 1),
    ("call-wrestle",
     r'''    if random.random() < 0.45:
        wrestle = await speakbox_quote(most=4, cap=420)
''',
     r'''    if s3_chance("call.wrestle", 0.45, "the caller wrestles the call back on topic with a passage"):   # [s3-dice-door]
        wrestle = await speakbox_quote(most=4, cap=420)
''', 1),
    ("call-stun",
     r'''    if random.random() < 0.25:
        stun = await speakbox_quote(most=10, cap=900)
''',
     r'''    if s3_chance("call.stun", 0.25, "a host delivers a monologue AT the caller, who comes back stunned"):   # [s3-dice-door]
        stun = await speakbox_quote(most=10, cap=900)
''', 1),
    ("call-quirk",
     r'''    if random.random() < 0.6:
        quirk = await speakbox_quote(most=3, cap=280)
''',
     r'''    if s3_chance("call.quirk", 0.6, "the caller's personality is soaked in a speakerbox passage"):   # [s3-dice-door]
        quirk = await speakbox_quote(most=3, cap=280)
''', 1),
    ("call-riff",
     r'''    if random.random() < 0.25:
        extras.append(
            "Mid-call, the TWO HOSTS briefly get carried away riffing on "
''',
     r'''    if s3_chance("call.hosts_riff", 0.25, "the hosts get carried away riffing, then hand back"):   # [s3-dice-door]
        extras.append(
            "Mid-call, the TWO HOSTS briefly get carried away riffing on "
''', 1),
    ("call-knows-ai",
     r'''    if random.random() < 0.12:
        extras.append(
            "At some point the caller casually mentions, accurately, "
''',
     r'''    if s3_chance("call.knows_its_written", 0.12, "the caller knows exactly what is writing and voicing them"):   # [s3-dice-door]
        extras.append(
            "At some point the caller casually mentions, accurately, "
''', 1),
    ("call-shape",
     r'''            f"{unrepeated(list(CALLER_SHAPES), 'caller-shape')} "
''',
     r'''            f"{s3_unrepeated('call.shape', list(CALLER_SHAPES), 'caller-shape', 'the shape of a heat call')} "   # [s3-dice-door]
''', 1),
    ("call-grievances",
     r'''        _grief = random.sample(list(DGX_GRIEVANCES),
                               k=random.choice((2, 2, 3)))
''',
     r'''        _grief = s3_sample("call.grievances", list(DGX_GRIEVANCES),
                           3 if s3_chance("call.grievances_three", 1 / 3, "three grievances rather than two") else 2,
                           "where the heat comes from")   # [s3-dice-door]
''', 1),
    ("call-distress",
     r'''            f"{random.choice(DGX_DISTRESS_LEVELS)}. Blend these into ONE "
''',
     r'''            f"{s3_choice('call.distress', DGX_DISTRESS_LEVELS, 'how distressed the heat caller is')}. Blend these into ONE "   # [s3-dice-door]
''', 1),
    ("call-game-tip",
     r'''    if random.random() < 0.14:
        _tip_topic, _tip_text = game_tip_pick()
''',
     r'''    if s3_chance("call.game_tip", 0.14, "the caller is curious about the station's game talk"):   # [s3-dice-door]
        _tip_topic, _tip_text = game_tip_pick()
''', 1),
    ("call-duo",
     r'''    if not story and random.random() < 0.28:                       # #1039
        duo_name = random.choice(
''',
     r'''    if not story and s3_chance("call.duo", 0.28, "MORE THAN ONE person is on the line"):   # #1039 [s3-dice-door]
        duo_name = s3_choice("call.duo_name",
''', 1),
    ("call-duo-name-end",
     r'''            [n for n in NEW_VOICE_NAMES if n != caller.get("name")]
            or list(NEW_VOICE_NAMES))
''',
     r'''            [n for n in NEW_VOICE_NAMES if n != caller.get("name")]
            or list(NEW_VOICE_NAMES), "the second person's name", tabled=False)
''', 1),
    ("call-duo-scenario",
     r'''        extras.append(random.choice([
            (f"TWO people are on this call: {caller['name']} AND their "
''',
     r'''        extras.append(s3_choice("call.duo_scenario", [   # [s3-dice-door] who else is on the line
            (f"TWO people are on this call: {caller['name']} AND their "
''', 1),
    ("call-duo-scenario-end",
     r'''        ]) + f" Label every line {duo_name} speaks as 'E: ...' — E is "
''',
     r'''        ], "who else is on the line and what happens", tabled=False) + f" Label every line {duo_name} speaks as 'E: ...' — E is "
''', 1),
    ("call-name-remark",
     r'''    if random.random() < float(dj.get("name_remark_rate", 0.3) or 0):
''',
     r'''    if s3_chance("call.name_remark", float(dj.get("name_remark_rate", 0.3) or 0),
                 "a host is struck by the caller's name", dial="name_remark_rate"):   # [s3-dice-door]
''', 1),
    ("call-hostile",
     r'''    hostile = (random.random() < float(dj.get("hostile_rate", 0.14) or 0)
''',
     r'''    hostile = (s3_chance("call.hostile", float(dj.get("hostile_rate", 0.14) or 0),
                         "THE CALL GOES WRONG (the seven-beat hostile arc)", dial="hostile_rate")   # [s3-dice-door]
''', 1),
    ("call-offence",
     r'''        offence = unrepeated(list(CALLER_OFFENCES), "hostile-offence")
        turned = unrepeated(list(HOSTILE_TURNS), "hostile-turn")
''',
     r'''        offence = s3_unrepeated("call.offence", list(CALLER_OFFENCES), "hostile-offence", "what the host says that offends")   # [s3-dice-door]
        turned = s3_unrepeated("call.hostile_turn", list(HOSTILE_TURNS), "hostile-turn", "how both round on the peacemaker")
''', 1),
    ("call-temper",
     r'''        temper = random.choice(CALLER_TEMPERS)
''',
     r'''        temper = s3_choice("call.temper", CALLER_TEMPERS, "the caller's temper tonight (the caller dice)")   # [s3-dice-door]
''', 1),
    ("call-pitch",
     r'''        mangle["pitch"] = float(mangle.get("pitch") or 1.0) * random.uniform(
            0.94, 1.08)
''',
     r'''        mangle["pitch"] = float(mangle.get("pitch") or 1.0) * (
            0.94 + 0.14 * s3_roll("call.pitch", "the caller's pitch nudged with their temper"))   # [s3-dice-door]
''', 1),
    ("call-approach",
     r'''        + approach_clause(approach_pick())                     # #752
''',
     r'''        + approach_clause(approach_pick() if not _s3_active() else {})   # #752 [s3-dice-door] FL frames it under System 3
''', 1),
    # --- the ending shelf, the deck, the case book, the subject bands --------
    ("ending-fallback",
     r'''            return {"id": "", "text": random.choice(CALLER_OUTCOMES)}
''',
     r'''            return {"id": "", "text": s3_choice("call.outcome_fallback", CALLER_OUTCOMES, "how a call ends (the built-in list, when the shelf is empty)")}   # [s3-dice-door]
''', 1),
    ("ending-success",
     r'''        desired = random.random() < max(0, min(100, int(success_rate))) / 100
''',
     r'''        desired = s3_chance("call.ending_success", max(0, min(100, int(success_rate))) / 100,
                            "the call ends on a success rather than otherwise", dial="caller_success_rate")   # [s3-dice-door]
''', 1),
    ("ending-pick",
     r'''        pick = random.choices(pool, weights=weights, k=1)[0]
''',
     r'''        pick = pool[s3_weighted("call.ending", [str(r.get("text") or r.get("id") or "") for r in pool], weights,
                                "how the call ends (the ending shelf, its own weights)")]   # [s3-dice-door]
''', 1),
    ("deck",
     r'''    roll = random.uniform(0, total)
    remaining = roll
    for key, weight in deck:
        roll -= weight
        if roll <= 0:
            phone_draw_note(key, deck, remaining)
            return key, CALLER_BEHAVIORS[key]
    phone_draw_note("plain", deck, remaining)
    return "plain", ""
''',
     r'''    # [s3-dice-door] the operator's weights, System 3's number, recorded
    _keys = [k for k, _w in deck]
    _i = s3_weighted("call.deck", _keys, [w for _k, w in deck], "the behaviour deck (#798): which card this caller plays")
    key = _keys[_i]
    phone_draw_note(key, deck, sum(w for _k, w in deck[:_i]) + deck[_i][1] / 2.0)
    return key, CALLER_BEHAVIORS.get(key, "")
''', 1),
    ("case",
     r'''        if random.random() >= rate / 100:
            return {}
''',
     r'''        if not s3_chance("call.case", rate / 100, "the caller rings about a case from the case book", dial="caller_case_rate"):   # [s3-dice-door]
            return {}
''', 1),
    ("plotline-call",
     r'''        if random.random() >= plotline_call_share():
            return {}
''',
     r'''        if not s3_chance("call.plotline", plotline_call_share(), "a caller rings inside the storyline", dial="plot_call_pct"):   # [s3-dice-door]
            return {}
''', 1),
    ("topic-bands",
     r'''    roll = random.random()
    # The mixtape haters (#453): they ring DEMANDING no more MX tapes. The
''',
     r'''    roll = s3_roll("call.subject_band", "which kind of subject a caller rings about (the #680 bands)")   # [s3-dice-door]
    # The mixtape haters (#453): they ring DEMANDING no more MX tapes. The
''', 1),
    ("topic-crazy",
     r'''        premise = unrepeated(list(CRAZY_CALLS), "crazy-call")
''',
     r'''        premise = s3_unrepeated("call.crazy", list(CRAZY_CALLS), "crazy-call", "what the unhinged ones are on about")   # [s3-dice-door]
''', 1),
    ("topic-headline",
     r'''                    f"\"{random.choice(headlines)['title']}\"", {})
    pool = banter_pool(6) + ([] if orch_policy("topics_by_rng", True) is not False   # [rng-topics]
''',
     r'''                    f"\"{s3_choice('call.subject_headline', headlines, 'which headline the caller rings about', tabled=False)['title']}\"", {})   # [s3-dice-door]
    pool = banter_pool(6) + ([] if orch_policy("topics_by_rng", True) is not False   # [rng-topics]
''', 1),
    ("topic-pool",
     r'''    topic = random.choice(pool) if pool else "the state of the station"
''',
     r'''    topic = (s3_choice("call.subject", pool, "what a caller rings about (the banter pool)", tabled=False)
             if pool else "the state of the station")   # [s3-dice-door]
''', 1),
    ("line-number",
     r'''    return random.randint(1, CALL_LINES)
''',
     r'''    return 1 + min(CALL_LINES - 1, int(s3_roll("call.line_number", "which line the caller is on") * CALL_LINES))   # [s3-dice-door]
''', 1),
    # --- the request line (dj_caller) and the call-in (dj_callin) -----------
    ("caller-heat",
     r'''    heat_call = hot >= 62 and random.random() < 0.45 and not _themed
''',
     r'''    heat_call = hot >= 62 and not _themed and s3_chance("call.heat_call", 0.45, "a hot box makes it a heat-joke call")   # [s3-dice-door]
''', 1),
    ("caller-mono",
     r'''            if random.random() < float(dj_settings().get(
                    "mono_pct", 85)) / 100.0:
''',
     r'''            if s3_chance("call.monologue", float(dj_settings().get(
                    "mono_pct", 85)) / 100.0, "the caller gets a three-or-four-sentence monologue", dial="mono_pct"):   # [s3-dice-door]
''', 2),
    ("caller-want",
     r'''    want = (random.choice(wants)[:160] if wants else
''',
     r'''    want = (s3_choice("call.want", wants, "which listener request the caller rings with", tabled=False)[:160] if wants else   # [s3-dice-door]
''', 1),
    ("caller-moods",
     r'''        f"{random.choice(CALLER_MOODS)}."
''',
     r'''        f"{s3_choice('call.host_mood', CALLER_MOODS, 'how the hosts take the call')}."   # [s3-dice-door]
''', 1),
    ("caller-disposition",
     r'''    mood = random.choice(CALLER_DISPOSITIONS)
''',
     r'''    mood = s3_choice("call.disposition", CALLER_DISPOSITIONS, "the request-line caller's disposition")   # [s3-dice-door]
''', 1),
    ("callin-moods",
     r'''    moods = random.sample(CALLIN_MOODS, 2)
''',
     r'''    moods = s3_sample("call.callin_moods", CALLIN_MOODS, 2, "the hosts' moods on a listener's call-in")   # [s3-dice-door]
''', 1),
    ("callin-who",
     r'''    who = caller.strip() or random.choice(
''',
     r'''    who = caller.strip() or s3_choice("call.callin_who",   # [s3-dice-door]
''', 1),
    ("callin-who-end",
     r'''         "a caller who would not give a name"])          # #673
''',
     r'''         "a caller who would not give a name"], "who the call-in is announced as")          # #673
''', 1),
    # --- upstairs -------------------------------------------------------------
    ("manager-manner",
     r'''                + random.choice(MANAGER_CALL_MANNER) + "\n"
''',
     r'''                + s3_choice("manager.call_manner", MANAGER_CALL_MANNER, "how the manager rings the booth") + "\n"   # [s3-dice-door]
''', 1),
    ("memo-hot",
     r'''    _hot_memo = hot >= 70 and random.random() < 0.5
''',
     r'''    _hot_memo = hot >= 70 and s3_chance("manager.hot_memo", 0.5, "a hot box makes the memo about the heat")   # [s3-dice-door]
''', 1),
    ("memo-crystal",
     r'''            _mcr = random.choice(_mcrs)
''',
     r'''            _mcr = s3_choice("manager.memo_crystal", _mcrs, "which crystal upstairs has fallen into", tabled=False)   # [s3-dice-door]
''', 1),
    ("memo-gripe",
     r'''        if random.random() < float(dj_settings().get(
                "manager_gripe_pct", MANAGER_GRIPE_PCT)) / 100.0:
''',
     r'''        if s3_chance("manager.gripe", float(dj_settings().get(
                "manager_gripe_pct", MANAGER_GRIPE_PCT)) / 100.0, "the memo is a gripe from upstairs", dial="manager_gripe_pct"):   # [s3-dice-door]
''', 1),
    ("memo-gripe-pick",
     r'''                _pick = random.choice([r for r in _rows
                                       if int(r.get("uses") or 0) == _fewest])
''',
     r'''                _pick = s3_choice("manager.gripe_pick", [r for r in _rows
                                       if int(r.get("uses") or 0) == _fewest],
                                  "which gripe (the least used)", tabled=False)   # [s3-dice-door]
''', 1),
    ("memo-topic",
     r'''        if _gripe and random.random() < float(dj_settings().get(
                "manager_topic_pct", MANAGER_TOPIC_PCT)) / 100.0:
''',
     r'''        if _gripe and s3_chance("manager.gripe_topic", float(dj_settings().get(
                "manager_topic_pct", MANAGER_TOPIC_PCT)) / 100.0, "the gripe is about a topic off the board", dial="manager_topic_pct"):   # [s3-dice-door]
''', 1),
    # --- the random ad ---------------------------------------------------------
    ("random-ad",
     r'''        if random.random() * 100.0 < pct:
            pipeline_log("air", "the pair just do an advert - the random "
''',
     r'''        if s3_chance("station.random_ad", pct / 100.0, "an advert out of nowhere (#1040)", dial="random_ad_pct"):   # [s3-dice-door]
            pipeline_log("air", "the pair just do an advert - the random "
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
