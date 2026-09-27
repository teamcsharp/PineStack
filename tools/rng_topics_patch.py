"""Topics come up through System 3's roulette; nothing is wedged in by itself.

Operator, 2026-09-27:
  "the SFX Guy randomly appears to be saying lines randomly and constantly
   from Topics. That is no longer needed to be automatic. Topic should be
   accessed via the RNG system on the roulette rolodex allowing for it come
   up naturally in conversation."
  "the entire dialogue system is now being built by the RNG system. Nothing
   should be automatically wedged into conversation"

A standing policy in the orchestrator's own book, turned through its own
door like the cut switches: `topics:rng` (the default, unset reads rng) or
`topics:auto` (every road below as it was). While it reads rng:

  drop_bombshell()        the station's own topic pick returns nothing - it
                          fed banter (60% of seedless rounds), the surplus
                          coin flip, the manager's memo and a "bombshell"
                          entry nobody queued a topic for
  the caller's premise    the 12% "planted topic" share of the phone and the
                          board lines in its last-resort pool
  the SFX Guy's bank      no board lines seeded into it (#1233), and the ones
                          already recorded are suspended - kept, not deleted -
                          so he stops saying them into holes and between lines

The operator's own hand is untouched: queueing a topic, "use this scenario
now", and a "1. / 2." exchange all still go straight on. The board reaches
the air through System 3's TOPIC roll (tools/system3_topic_roll_patch.py).

And on a round System 3 directs, two passes that rewrite or extend what it
planned are skipped: the blend (#862), which re-handed the whole round to
the writer with "EVERYTHING ELSE IS YOURS", and the re-seed, which appended
fresh speaker-box turns when the close drifted. System 3's running order
places each passage and has the next turn answer it, and its CTS roll
changes the subject; the legacy road keeps both passes.

Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing; --apply writes app.py. Run it ON THE
HOST.
"""
import sys
from pathlib import Path

EDITS = [
    # 1. the switch, in the orchestrator's policy door
    ('        elif verb == "thin":\n',
     '        elif verb == "topics":\n'
     '            # [rng-topics] 2026-09-27: "Topic should be accessed via the RNG\n'
     '            # system on the roulette rolodex". rng: the board comes up only\n'
     '            # through System 3\'s TOPIC roll; auto: every road as it was.\n'
     '            _want = str(arg or "rng") != "auto"\n'
     '            _ORCH["policy"]["topics_by_rng"] = {"value": bool(_want), "at": time.time()}\n'
     '            said = ("the topics board comes up only when System 3\'s roulette draws it - "\n'
     '                    "nothing springs a topic by itself" if _want else\n'
     '                    "the station springs topics by itself again (banter, callers, the "\n'
     '                    "manager\'s memo, the SFX Guy)")\n'
     '        elif verb == "thin":\n'),
    # 2. the station's own pick
    ('def drop_bombshell() -> dict[str, Any]:\n'
     '    """Pick one, favouring whatever has had the least air time."""\n'
     '    rows = read_bombshells()\n',
     'def drop_bombshell() -> dict[str, Any]:\n'
     '    """Pick one, favouring whatever has had the least air time."""\n'
     '    # [rng-topics] THE STATION NO LONGER PICKS ONE BY ITSELF. Every caller\n'
     '    # of this is automatic - seedless banter, the surplus coin flip, the\n'
     '    # manager\'s memo, a "bombshell" entry nobody queued - and "nothing\n'
     '    # should be automatically wedged into conversation". The board comes\n'
     '    # up through System 3\'s TOPIC roll; `topics:auto` restores this pick.\n'
     '    if orch_policy("topics_by_rng", True) is not False:\n'
     '        return {}\n'
     '    rows = read_bombshells()\n'),
    # 3. the caller's premise: the planted-topic share, and the last-resort pool
    ('    if roll < 0.84:\n'
     '        # Your Topics list gets its own share of the phone (#395): any\n',
     '    if roll < 0.84 and orch_policy("topics_by_rng", True) is False:   # [rng-topics]\n'
     '        # Your Topics list gets its own share of the phone (#395): any\n'),
    ('    pool = banter_pool(6) + [r["text"] for r in read_bombshells()[:4]]\n'
     '    topic = random.choice(pool) if pool else "the state of the station"\n',
     '    pool = banter_pool(6) + ([] if orch_policy("topics_by_rng", True) is not False   # [rng-topics]\n'
     '                             else [r["text"] for r in read_bombshells()[:4]])\n'
     '    topic = random.choice(pool) if pool else "the state of the station"\n'),
    # 4. the SFX Guy's bank
    ('        sources += [{"text": text, "generic": True}\n'
     '                    for text in sfx_topic_sources(SFXGUY_TOPIC_SEED)]\n'
     '        _SFX_READY_BANK.seed(voice, profile, sources)\n',
     '        # [rng-topics] ...but not while the board comes up through System\n'
     '        # 3\'s roulette: "the SFX Guy randomly appears to be saying lines\n'
     '        # randomly and constantly from Topics. That is no longer needed to\n'
     '        # be automatic." The lines already recorded are rested, not deleted.\n'
     '        if orch_policy("topics_by_rng", True) is False:\n'
     '            sources += [{"text": text, "generic": True}\n'
     '                        for text in sfx_topic_sources(SFXGUY_TOPIC_SEED)]\n'
     '            _sfxguy_topics_rest(voice, profile, rest=False)\n'
     '        else:\n'
     '            _sfxguy_topics_rest(voice, profile, rest=True)\n'
     '        _SFX_READY_BANK.seed(voice, profile, sources)\n'),
    ('async def sfxguy_ready_prepare(limit: int = 1) -> dict[str, Any]:\n',
     'SFXGUY_TOPIC_REST_WHY = ("a line off the topics board - the board comes up through System 3\'s "\n'
     '                         "roulette now (topics:rng)")\n'
     '\n'
     '\n'
     'def _sfxguy_topics_rest(voice: str, profile: str, rest: bool = True) -> int:\n'
     '    """[rng-topics] Suspend the lines his bank took off the topics board\n'
     '    (#1233) - or, with `topics:auto`, put back the ones this suspended.\n'
     '    eligible() only offers `ready` rows, so a suspended line is never\n'
     '    picked for a hole or a cadence slot; the recording stays on disk."""\n'
     '    try:\n'
     '        board = {" ".join(str(r.get("text") or "").split())\n'
     '                 for r in (read_bombshells() or []) if isinstance(r, dict)}\n'
     '        board.discard("")\n'
     '        moved = 0\n'
     '        for row in _SFX_READY_BANK.rows(voice, profile, deep=False):\n'
     '            if rest:\n'
     '                text = " ".join(str(row.get("text_plain") or "").split())\n'
     '                if text not in board or row.get("state") == "suspended":\n'
     '                    continue\n'
     '                row.update(state="suspended", why=SFXGUY_TOPIC_REST_WHY,\n'
     '                           rested_from=str(row.get("state") or ""))\n'
     '            else:\n'
     '                if row.get("why") != SFXGUY_TOPIC_REST_WHY:\n'
     '                    continue\n'
     '                row.update(state=str(row.pop("rested_from", "") or "waiting"), why="")\n'
     '            _SFX_READY_BANK.put(row)\n'
     '            moved += 1\n'
     '        if moved:\n'
     '            pipeline_log("sfxguy", ("%d line(s) off the topics board suspended in his bank - "\n'
     '                                    "topics come up through System 3\'s roulette" if rest else\n'
     '                                    "%d topics-board line(s) back in his bank (topics:auto)")\n'
     '                         % moved)\n'
     '        return moved\n'
     '    except Exception:  # noqa: BLE001\n'
     '        return 0\n'
     '\n'
     '\n'
     'async def sfxguy_ready_prepare(limit: int = 1) -> dict[str, Any]:\n'),
    # 5. the passes that rewrite or extend what System 3 planned
    ('    _prepared = bool(bank) or bool(_system2_job)\n'
     '    if _prepared and _dealt:\n',
     '    _prepared = bool(bank) or bool(_system2_job)\n'
     '    # [rng-topics] NOT ON A ROUND SYSTEM 3 DIRECTED. Its running order\n'
     '    # already places each passage and has the next turn answer it; this\n'
     '    # pass re-handed the whole round to the writer ("EVERYTHING ELSE IS\n'
     '    # YOURS") and rewrote the turns the dice had shaped. "Nothing should\n'
     '    # be automatically wedged into conversation." The legacy road keeps it.\n'
     '    _s3_directed = bool(_s3 is not None and getattr(_s3, "active", False))\n'
     '    if _prepared and _dealt and not _s3_directed:\n'),
    ('    if _prepared and _dealt and not own_material:\n'
     '        try:\n'
     '            _now_turns = banter_turns(script, caller_name)\n',
     '    # [rng-topics] ...nor the re-seed: fresh speaker-box turns appended by\n'
     '    # the station. On System 3\'s rounds its CTS roll changes the subject.\n'
     '    if _prepared and _dealt and not own_material and not _s3_directed:\n'
     '        try:\n'
     '            _now_turns = banter_turns(script, caller_name)\n'),
]


def main(argv):
    apply = "--apply" in argv
    path = Path("app.py")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    todo = 0
    for old, new in EDITS:
        if new in text:
            continue
        if text.count(old) != 1:
            print("MISSING (%d): %r" % (text.count(old), old[:90]))
            return 1
        text = text.replace(old, new)
        todo += 1
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    path.write_text(text, encoding="utf-8", newline="\n")
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
