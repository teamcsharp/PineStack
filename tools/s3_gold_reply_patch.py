#!/usr/bin/env python3
"""[s3-gold] Gold lines become a reply System 3 rolls for; the forced gold roads retire.

"The gold system will need to be fully transitioned to system 3, made into an
option for the roulette to access as a reply possibility. By chance the people
in the booth should roll a dice for a chance to say a gold line." (operator,
2026-09-29)

Needs system3_gold.py beside app.py (the GOLD1 table and the roll) and
norepeat_24h_patch.py applied first (the 24-hour text key the bank is filtered
by).

  system3.py          GOLD joins FAMILIES; _decide_turn asks system3_gold.decide on
                      every turn (it rolls only on a host's reply turn, on its own
                      stream seed|gold); the turn sheet tells the writer the seat
                      answers with the kept line word for word - and keeps the
                      DIRECTION FOR THIS LINE block, so the delivery follows the roll
  system3_runtime.py  imports system3_gold; GOLD1 is added to the stored config once
                      (add_missing_default_tables: editable in Tables, deletable for
                      good); the plan's inputs carry "gold_bank" from the station
  app.py              system3_gold_bank(road, ctx): System 3-minted bars, not
                      heard inside the day, never on news/ads/IDs/record talk;
                      gold_in_round_due() and gold_fill_gap() stand down while
                      GOLD_REPLY is on (the default) - no gold line airs forced

    python3 tools/s3_gold_reply_patch.py --check | --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p3_patchlib import Edit, run  # noqa: E402

S = "system3.py"
R = "system3_runtime.py"
A = "app.py"

FAM_ANCHOR = 'FAMILIES = FAMILIES + ("GRAPH",)\n'
FAM_NEW = 'FAMILIES = FAMILIES + ("GOLD",)                                      # [s3-gold] a kept line, rolled as a reply\n'

DECIDE_ANCHOR = "    _attach_round_plans(conv, turn, idx, want, speaker)                      # [s3-rounds]\n"
DECIDE_NEW = '''    try:                                                                      # [s3-gold:decide]
        import sys as _sys
        import system3_gold
        system3_gold.decide(_sys.modules[__name__], conv, config, turn, idx, want, inputs, closing)
    except ImportError:
        pass
    except Exception as _gexc:  # noqa: BLE001 - a gold fault never costs the round; it is kept on it
        conv.setdefault("faults", []).append({"where": "gold roll", "error": repr(_gexc)[:200]})
'''

# answer_line / _dir are s3_direction_patch's text: the gold reply is set right
# after that block. _dir was computed for a turn with no fixed words, so the
# DIRECTION FOR THIS LINE rides the gold line.
SHEET_ANCHOR = '''    if _dir:
        feel = ""
'''
SHEET_NEW = '''    # [s3-gold:sheet] a gold reply the roulette landed on: the words are the kept
    # line, fixed; the direction rolled above still governs how it is delivered
    _gold_txt = str((turn.get("gold") or {}).get("text") or "") if (replying and not answer_text) else ""
    if _gold_txt:
        answer_text, answer_line = _gold_txt, True
'''

DESC_ANCHOR = '    acts = "; then ".join(x["text"] for x in turn["directions"] if x["family"] in ("RS", "IRS"))\n'
DESC_NEW = '''    if _gold_txt:                                                             # [s3-gold:desc]
        desc = ("answers %s with a line the station kept - a callback, these exact words, as written: %s"
                % (prev_name, json.dumps(_gold_txt)))
'''

RT_IMPORT_ANCHOR = '''    system3_mgrtopics = None
'''
RT_IMPORT_NEW = '''try:                                      # [s3-gold] gold lines as a rolled reply
    import system3_gold
except ImportError:  # pragma: no cover - a host without the module rolls no gold
    system3_gold = None
'''

RT_TABLES_ANCHOR = '''            missing += [t for t in system3_mgrtopics.default_tables() if t["id"] not in have and t["id"] not in seen]
'''
RT_TABLES_NEW = '''        if system3_gold is not None:                                        # [s3-gold:tables] GOLD1, once
            missing += [t for t in system3_gold.default_tables() if t["id"] not in have and t["id"] not in seen]
'''

RT_INPUT_ANCHOR = '            "topic_bank": topic_bank,\n'
RT_INPUT_NEW = '            "gold_bank": self._gold_bank(ctx, road),                          # [s3-gold:input]\n'

RT_METHOD_ANCHOR = "    def _topic_bank(self, ctx):\n"
RT_METHOD_NEW = '''    def _gold_bank(self, ctx, road):
        """[s3-gold:bank] The kept lines a host may roll as a reply this round -
        the station's (system3_gold_bank): minted from System 3 turns, none heard
        inside the day. Empty (nothing is rolled) on the operator's own exchange,
        a road the station keeps gold off, or a host without the module."""
        if system3_gold is None or _exchange_of(ctx).get("opener"):
            return []
        fn = getattr(self.host, "system3_gold_bank", None)
        try:
            rows = fn(road, ctx) if callable(fn) else []
        except Exception as exc:  # noqa: BLE001
            self.fail("gold bank", exc)
            return []
        return [dict(r) for r in rows or [] if isinstance(r, dict)][:system3_gold.BANK_MOST]

'''

APP_BANK_ANCHOR = "def gold_in_round_rate() -> float:\n"
APP_BANK_NEW = '''# --- [s3-gold] GOLD IS A REPLY THE ROULETTE CAN LAND ON ------------------------
# "made into an option for the roulette to access as a reply possibility. By
# chance the people in the booth should roll a dice for a chance to say a gold
# line" (operator, 2026-09-29). system3_gold rolls it on a host's reply turn
# (GOLD1 in Tables); this is the bank it rolls over. While GOLD_REPLY is on (the
# default) the forced roads stand down: no bar is dropped into a live round
# (gold_in_round_due) and no run is poured into a gap (gold_fill_gap).
GOLD_REPLY_ROADS_OFF = frozenset({"news", "ad", "ad_spot", "station_id", "track_talk"})


def gold_reply_on() -> bool:
    return os.getenv("GOLD_REPLY", "1") != "0"


def system3_gold_bank(road: str = "", ctx: Any = None) -> list[dict[str, Any]]:
    """[s3-gold:bank] The gold lines System 3 may roll as a host's reply: minted
    from System 3 turns (gold_source), no gone names, none heard inside the day
    (the same text key as the dialogue gate - struck BEFORE the roll)."""
    if not gold_reply_on() or str(road or "") in GOLD_REPLY_ROADS_OFF:
        return []
    out: list[dict[str, Any]] = []
    try:
        for r in _gold_rows():
            text = " ".join(str(r.get("text") or "").split())
            if len(text) < 12 or not gold_source(r) or cast_names_line_stale(r):
                continue
            if norepeat_text_used(text):
                continue
            out.append({"id": (str(r.get("key") or "") or hashlib.sha1(text.encode("utf-8")).hexdigest())[:40],
                        "text": text[:400], "who": str(r.get("who") or ""),
                        "fired": int(r.get("fired") or 0)})
    except Exception:  # noqa: BLE001
        return out
    return out[:80]


'''

IN_ROUND_ANCHOR = '''    rate = gold_in_round_rate()
    if rate <= 0:
        return False
'''
IN_ROUND_NEW = '''    if gold_reply_on():                                                   # [s3-gold:in-round]
        return False     # gold airs as System 3's rolled reply (GOLD1), never dropped into a live round
'''

GAP_ANCHOR = "    want = max(0.0, min(want, GOLD_RUN_SECONDS))\n"
GAP_NEW = '''    if gold_reply_on():                                                   # [s3-gold:gap]
        return ""        # a run of bars is a forced re-air; gold is a rolled reply now
'''

EDITS = [
    Edit("FAMILIES", S, FAM_ANCHOR, FAM_NEW, "[s3-gold] a kept line", "after"),
    Edit("decide", S, DECIDE_ANCHOR, DECIDE_NEW, "[s3-gold:decide]", "after"),
    Edit("sheet", S, SHEET_ANCHOR, SHEET_NEW, "[s3-gold:sheet]", "after"),
    Edit("desc", S, DESC_ANCHOR, DESC_NEW, "[s3-gold:desc]", "before"),
    Edit("runtime import", R, RT_IMPORT_ANCHOR, RT_IMPORT_NEW, "[s3-gold] gold lines as a rolled reply", "after"),
    Edit("runtime tables", R, RT_TABLES_ANCHOR, RT_TABLES_NEW, "[s3-gold:tables]", "after"),
    Edit("runtime input", R, RT_INPUT_ANCHOR, RT_INPUT_NEW, "[s3-gold:input]", "after"),
    Edit("runtime bank", R, RT_METHOD_ANCHOR, RT_METHOD_NEW, "[s3-gold:bank] The kept lines", "before"),
    Edit("app bank", A, APP_BANK_ANCHOR, APP_BANK_NEW, "[s3-gold:bank] The gold lines", "before"),
    Edit("in-round", A, IN_ROUND_ANCHOR, IN_ROUND_NEW, "[s3-gold:in-round]", "after"),
    Edit("gap", A, GAP_ANCHOR, GAP_NEW, "[s3-gold:gap]", "after"),
]

if __name__ == "__main__":
    sys.exit(run("s3_gold_reply_patch", EDITS,
                 requires=[("system3_gold.py", "def decide("), ("app.py", "[no-repeat-24h:helpers]")]))
