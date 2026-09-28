"""[s3-live-event] THE DRAWS-UNMOVED PROOF, old engine against new.

Plans N seeds (default 40) x the roads that draw from tables, with a fixed
inputs fixture and NO event active, and prints one digest line per
seed/road plus a total. Run it twice:

  1. on the PRISTINE tree (git archive HEAD): the old engine, the config
     as it is today;
  2. on the PATCHED tree: the new engine, the config WITH the six MX Live
     tables added (exactly what add_missing_default_tables will do to the
     live config) - the event itself off, as it is on any ordinary day.

Identical totals prove: the feature in place, the rows in the live
config, and not one draw of an ordinary day has moved. (With an event ON
the draws are allowed to differ - that is the feature.)

  PYTHONIOENCODING=utf-8 python tools/mxlive_seed_sweep.py [N] [--json out]

The digest strips only what cannot be equal by construction: config_hash
(the config differs by the added tables), timestamps, and the durations.
Every family, stage, candidate list, weight, dice and selected id stays in.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys

import system3
import system3_tables

VOLATILE = ("at", "config_hash")


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, float):
        return round(obj, 9)
    return obj


def fixture_inputs(road, seed_n):
    return {
        "road": road, "at": 1790000000.0, "seats": ["A", "B"],
        "names": {"A": "Pine", "B": "Box"}, "roles": {"A": "dj", "B": "cohost"},
        "turns": 8, "target_seconds": 90.0, "words_per_turn": 60.0,
        "subject": {"topic": "the seed sweep's fixed subject %d" % seed_n,
                    "category": "banter", "authority": "obligated",
                    "keywords": ["sweep"], "angle": ""},
        "availability": {"speakbox": False, "news": False, "topics": True},
        "topic_bank": [{"id": "t1", "text": "the weather on the mountain", "used": 0},
                       {"id": "t2", "text": "the record fair", "used": 1}],
        "speakerbox_rates": {"full": 0.0, "prepend": 0.0, "append": 0.0},
        "bank": False, "round_rolls": True, "rewrite_rolls": True,
        "event_rolls": True, "dice_hosts": True,
        "interjections": ["oh come on", "you cannot mean that"],
        "record": {"id": "ab12cd34ef56ab12", "title": "Night Drive", "artist": "The Pine Box Band"},
        "station_name": "Pine Box FM", "live": True,
        # the point under proof: NO event is on
        "events": {}, "record_event": "",
    }


def main(argv):
    n = next((int(a) for a in argv if a.isdigit()), 40)
    out_path = None
    if "--json" in argv:
        out_path = argv[argv.index("--json") + 1]
    settings = system3.normalise_settings({"mode": "shadow", "test_seed": ""})
    config = system3.default_config()
    if hasattr(system3_tables, "default_event_tables"):
        config["tables"] = config["tables"] + system3_tables.default_event_tables()
        print("engine: NEW (event tables in the config, no event on)")
    else:
        print("engine: OLD (pristine)")
    rows = []
    total = hashlib.sha256()
    for i in range(n):
        seed = "sweep-%04d" % i
        for road in ("banter",):
            inputs = fixture_inputs(road, i)
            conv = system3.plan_scene(inputs, copy.deepcopy(config), settings, seed=seed,
                                      conversation_id="sweep%04d" % i)
            body = {"turns": [{k: t.get(k) for k in ("index", "speaker", "step", "phase",
                                                     "topic_change", "track_talk", "events",
                                                     "shock", "mention")}
                              for t in conv["turns"]],
                    "decisions": _clean(conv["decision_events"]),
                    "draws": conv.get("draws")}
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
            rows.append({"seed": seed, "road": road, "digest": digest,
                         "events": len(conv["decision_events"]), "turns": len(conv["turns"])})
            total.update(digest.encode())
            print("%s %s %s  %3d decisions  %2d turns" % (seed, road, digest,
                                                          len(conv["decision_events"]),
                                                          len(conv["turns"])))
    print("TOTAL %s over %d plans" % (total.hexdigest()[:24], len(rows)))
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({"total": total.hexdigest()[:24], "rows": rows}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
