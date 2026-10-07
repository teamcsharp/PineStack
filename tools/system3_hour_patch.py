#!/usr/bin/env python3
"""[wave-g] The System 3 Hour Director station core (2026-10-06).

System 2 stands down under engine "system3" (its enabled is False, its planner idles) and the Hour
Director (system3_hour.py) answers the chain's two System 2 questions: the running entry's own door, then the
cupboard's booked round, with the legacy draw as the armed fallback. The hour's dice are System 3 tables (HOUR1
silent kinds, HOUR2 pace, HOUR3 jam). The round ledger is GET /api/system3/hour.

Edits:
  app.py                          the director installs (GET/POST /api/system3/engine, GET /api/system3/hour) and
                                  the two chain sites ask it where they asked System 2 (elif, same breath).
  system2_runtime.py              engine "system3" is accepted in its settings; its planner refresh idles under it.
  system3.py                      FAMILIES += HOUR; validate_table hands HOUR to system3_tables.validate_hour.
  system3_tables.py               HOUR1, HOUR2, HOUR3 (DEFAULT_TABLES) and validate_hour.
  frontend/system3.js             the HOUR family's words (FAMILY_WHAT) and its table group (TABLE_FAMILIES).
  tests/test_system3.py           the default config hash re-pinned.
  tests/test_system3_mgrtopics.py the default config hash re-pinned.

Usage:  system3_hour_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        system3_hour_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# The default config hash after the HOUR tables join DEFAULT_TABLES (computed on the stage, see wiring.md).
HOUR_HASH_OLD = "6541cb19bdeb701d"
HOUR_HASH_NEW = "a22a5ee968719641"

INSTALL_OLD = "blocked_book.install(app, globals())"
INSTALL_NEW = ("import system3_hour                                             # [wave-g] the Hour Director\n"
               "system3_hour.install(app, globals())                             # [wave-g] GET/POST /api/system3/engine, GET /api/system3/hour\n"
               "blocked_book.install(app, globals())")

CHAIN1_OLD = '''                    pipeline_log("air", "(#1070) System2 has nothing staged for the "
                                 "running entry; the legacy chain serves it")
            dj = dj_settings()
'''
CHAIN1_NEW = '''                    pipeline_log("air", "(#1070) System2 has nothing staged for the "
                                 "running entry; the legacy chain serves it")
            elif globals().get("_system3_hour") and _system3_hour().enabled():
                # [wave-g] THE HOUR DIRECTOR. Under engine system3 System 2 stands down (its enabled is False) and
                # the chain asks the director where it asked System 2: the running entry's own door, then the
                # cupboard's booked round. The legacy draw runs only when the director aired nothing and its
                # fallback is armed (fallback_due()).
                served = await _system3_hour().dispatch(_RADIO.get("now"), dj_settings())
                if served or not _system3_hour().fallback_due():
                    await asyncio.sleep(0.5)
                    continue
            dj = dj_settings()
'''

CHAIN2_OLD = '''                if served or not _system2().fallback_due():
                    continue
            # Never two rounds at once: the per-record intro is its own
'''
CHAIN2_NEW = '''                if served or not _system2().fallback_due():
                    continue
            elif globals().get("_system3_hour") and _system3_hour().enabled():
                # [wave-g] the Hour Director asks at the breath after the wait, as System 2 was asked
                served = await _system3_hour().dispatch(_RADIO.get("now"), dj)
                if served or not _system3_hour().fallback_due():
                    continue
            # Never two rounds at once: the per-record intro is its own
'''

SR_ENGINE_OLD = '''            if payload["engine"] not in ("legacy", "system2"):
                raise ValueError("engine must be legacy or system2")
'''
SR_ENGINE_NEW = '''            if payload["engine"] not in ("legacy", "system2", "system3"):
                raise ValueError("engine must be legacy, system2 or system3")
'''
SR_REFRESH_OLD = "    async def refresh(self, force=False, want_status=True):\n"
SR_REFRESH_NEW = (SR_REFRESH_OLD
                  + "        # [wave-g] Under engine system3 System 2 plans nothing: the Hour Director owns the hour.\n"
                  + '        if self.config.get("engine") == "system3":\n'
                  + "            return await asyncio.to_thread(self.status) if want_status else None\n")

S3_FAM_OLD = 'FAMILIES = FAMILIES + ("GOLD",)'
S3_FAM_NEW = ('FAMILIES = FAMILIES + ("HOUR",)                                     '
              '# [wave-g] the Hour Director\'s dice: HOUR1 silent, HOUR2 pace, HOUR3 jam\n'
              'FAMILIES = FAMILIES + ("GOLD",)')
S3_VALIDATE_OLD = '    if family == "MEMORY":'
S3_VALIDATE_NEW = ('    if family == "HOUR":                                     '
                   '# [wave-g] the Hour Director\'s three tables\n'
                   '        return system3_tables.validate_hour(table)\n'
                   '    if family == "MEMORY":')

HOUR_TABLES = '''# --- [wave-g] THE HOUR DIRECTOR'S OWN DICE (family HOUR) ---------------------------------
#
# 2026-10-06, the operator: "We need to migrate all System 2 systems over to System 3 ... put it under the roulette
# node system of System 3." The Hour Director (system3_hour.py) answers the chain's question when the running
# order is silent, behind pace, or jammed. Its three tables are the dice:
#   HOUR1  the kinds it may draw when the sheet is silent (weight = the desk's chance of each kind)
#   HOUR2  how far behind pace each kind is (gain = how hard the shortfall pulls its draw up)
#   HOUR3  the chance a jammed entry (1.5x its minutes, schedule_jammed) is displaced by a HOUR1 draw (odds)
# Every draw is written on the hour's ledger (GET /api/system3/hour).
HOUR_KINDS = ("banter", "caller", "news", "gallery", "manager", "ad", "deep", "bombshell", "recap")
HOUR1 = {
    "id": "HOUR1", "family": "HOUR", "label": "When the sheet is silent (the kinds the hour may draw)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "The running order names nothing for this breath: the hour draws one of these kinds, weighted, "
                   "and HOUR2 lifts the kinds that are behind pace.",
    "categories": [
        {"id": "silent", "label": "Silent draw", "weight": 1.0, "items": _items([
            {"id": "banter", "label": "Banter", "weight": 4.0, "text": "a banked round between the two hosts"},
            {"id": "caller", "label": "Caller", "weight": 2.0, "text": "a call from a listener"},
            {"id": "news", "label": "News", "weight": 1.5, "text": "the wire, the lead story read and reacted to"},
            {"id": "gallery", "label": "Gallery", "weight": 1.0, "text": "a piece from the Pine Box gallery"},
            {"id": "manager", "label": "Manager", "weight": 0.8, "text": "a memo from upstairs"},
            {"id": "ad", "label": "Ad", "weight": 0.6, "text": "a produced spot"},
            {"id": "deep", "label": "Deep", "weight": 0.8, "text": "a longer piece on one subject"},
            {"id": "bombshell", "label": "Bombshell", "weight": 0.5, "text": "a short written read that changes the room"},
            {"id": "recap", "label": "Recap", "weight": 0.7, "text": "the hour so far, on the hour"},
        ])},
    ],
}
HOUR2 = {
    "id": "HOUR2", "family": "HOUR", "label": "Quota pressure (how far behind pace each kind is)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "Per kind: the share of its planned legs not yet aired this hour, times its gain, lifts its HOUR1 "
                   "weight. A kind the sheet never plans is never lifted.",
    "categories": [
        {"id": "pace", "label": "Pace", "weight": 1.0, "items": _items([
            {"id": "banter", "label": "Banter", "weight": 1.0, "gain": 0.5, "text": "banter's gain"},
            {"id": "caller", "label": "Caller", "weight": 1.0, "gain": 2.0, "text": "a caller behind pace pulls hard"},
            {"id": "news", "label": "News", "weight": 1.0, "gain": 1.5, "text": "news's gain"},
            {"id": "gallery", "label": "Gallery", "weight": 1.0, "gain": 1.0, "text": "gallery's gain"},
            {"id": "manager", "label": "Manager", "weight": 1.0, "gain": 2.0, "text": "a memo behind pace pulls hard"},
            {"id": "ad", "label": "Ad", "weight": 1.0, "gain": 1.5, "text": "ad's gain"},
            {"id": "deep", "label": "Deep", "weight": 1.0, "gain": 1.0, "text": "deep's gain"},
            {"id": "bombshell", "label": "Bombshell", "weight": 1.0, "gain": 1.0, "text": "bombshell's gain"},
            {"id": "recap", "label": "Recap", "weight": 1.0, "gain": 1.0, "text": "recap's gain"},
        ])},
    ],
}
HOUR3 = {
    "id": "HOUR3", "family": "HOUR", "label": "The jam (an entry overrunning 1.5 times its minutes)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "A jammed entry is not displaced by rule: this chance decides it.",
    "categories": [
        {"id": "jam", "label": "Jam", "weight": 1.0, "items": _items([
            {"id": "displace", "label": "Displace the jammed entry", "weight": 1.0, "odds": 0.5,
             "text": "the chance a jammed entry is displaced by a HOUR1 draw"},
        ])},
    ],
}


def validate_hour(table):
    """[wave-g] Refuse an HOUR table the Hour Director cannot draw from; returns the cleaned copy."""
    if not isinstance(table, dict):
        raise ValueError("a table is an object")
    tid = str(table.get("id") or "").strip()
    if tid not in ("HOUR1", "HOUR2", "HOUR3"):
        raise ValueError("an HOUR table is HOUR1, HOUR2 or HOUR3")
    if str(table.get("family") or "HOUR") != "HOUR":
        raise ValueError("an HOUR table has the family HOUR")
    cats = table.get("categories")
    if not isinstance(cats, list) or not cats:
        raise ValueError("%s needs at least one category" % tid)
    out = copy.deepcopy(table)
    out["id"], out["family"] = tid, "HOUR"
    out["weight"] = max(0.0, float(table.get("weight", 1.0) or 0))
    out["enabled"] = bool(table.get("enabled", True))
    out["version"] = int(table.get("version") or 1)
    seen = set()
    for cat in out["categories"]:
        if not isinstance(cat, dict) or not str(cat.get("id") or "").strip():
            raise ValueError("every category needs an id")
        items = cat.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("category %s has no items" % cat["id"])
        for item in items:
            if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                raise ValueError("every item needs an id")
            key = (cat["id"], item["id"])
            if key in seen:
                raise ValueError("duplicate item %s/%s" % key)
            seen.add(key)
            if tid in ("HOUR1", "HOUR2") and item["id"] not in HOUR_KINDS:
                raise ValueError("%s names %s, which is not a schedule kind" % (tid, item["id"]))
            item["weight"] = max(0.0, float(item.get("weight", 1.0) or 0))
            item.setdefault("label", item["id"])
            if tid == "HOUR1" and not str(item.get("text") or "").strip():
                raise ValueError("HOUR1 kind %s says nothing" % item["id"])
            if tid == "HOUR2":
                item["gain"] = max(0.0, float(item.get("gain", 0) or 0))
            if tid == "HOUR3":
                item["odds"] = round(min(1.0, max(0.0, float(item.get("odds", 0.5) or 0))), 4)
    return out


'''
T_HOUR_OLD = "# families whose tables may stand empty: their rows are added from the desk,"
T_HOUR_NEW = HOUR_TABLES + T_HOUR_OLD
T_DEFAULT_OLD = "                  STATION1, POOLS1, SBEND1]"
T_DEFAULT_NEW = "                  STATION1, POOLS1, SBEND1, HOUR1, HOUR2, HOUR3]"

FRONT_WHAT_OLD = "const DIAL_FOR = {ES: ['emotional_volatility'], RS:"
FRONT_WHAT_NEW = (
    "Object.assign(FAMILY_WHAT, {   /* [wave-g] the Hour Director's own dice */\n"
    "  HOUR: ['The hour (HOUR1-3)',\n"
    "    \"When the running order is silent, HOUR1 draws the kind of round the hour airs, weighted up for the kinds that "
    "are behind pace (HOUR2). HOUR3 is the chance that an entry jammed past 1.5 times its minutes is displaced. Every "
    "draw is written on the hour's ledger in the System 3 window.\"]\n"
    "});\n"
    + FRONT_WHAT_OLD)
FRONT_TABLES_OLD = "  TABLE_FAMILIES.push('MEMORY');"
FRONT_TABLES_NEW = ("  TABLE_FAMILIES.push('HOUR');   /* [wave-g] the Hour Director's tables: HOUR1 silent, HOUR2 pace, "
                    "HOUR3 jam */\n" + FRONT_TABLES_OLD)

EDITS = {
    "app.py": [
        ("the director installs; its routes answer", INSTALL_OLD, INSTALL_NEW, 1),
        ("chain site 1: the director where System 2 was asked (breath)", CHAIN1_OLD, CHAIN1_NEW, 1),
        ("chain site 2: the director where System 2 was asked (after the breath)", CHAIN2_OLD, CHAIN2_NEW, 1),
    ],
    "system2_runtime.py": [
        ("engine system3 is accepted in System 2's settings", SR_ENGINE_OLD, SR_ENGINE_NEW, 1),
        ("System 2's planner idles under engine system3", SR_REFRESH_OLD, SR_REFRESH_NEW, 1),
    ],
    "system3.py": [
        ("FAMILIES += HOUR", S3_FAM_OLD, S3_FAM_NEW, 1),
        ("validate_table hands HOUR to system3_tables.validate_hour", S3_VALIDATE_OLD, S3_VALIDATE_NEW, 1),
    ],
    "system3_tables.py": [
        ("HOUR1-3 and validate_hour", T_HOUR_OLD, T_HOUR_NEW, 1),
        ("HOUR1-3 join DEFAULT_TABLES", T_DEFAULT_OLD, T_DEFAULT_NEW, 1),
    ],
    "frontend/system3.js": [
        ("HOUR's words (FAMILY_WHAT)", FRONT_WHAT_OLD, FRONT_WHAT_NEW, 1),
        ("HOUR's table group (TABLE_FAMILIES)", FRONT_TABLES_OLD, FRONT_TABLES_NEW, 1),
    ],
    "tests/test_system3.py": [
        ("default config hash re-pinned (HOUR tables)", HOUR_HASH_OLD, HOUR_HASH_NEW, 1),
    ],
    "tests/test_system3_mgrtopics.py": [
        ("default config hash re-pinned (HOUR tables)", HOUR_HASH_OLD, HOUR_HASH_NEW, 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".waveg.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
