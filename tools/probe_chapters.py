"""[s3-chain] LIVE ACCEPTANCE PROBE for the System 3 exchange contract.

Run ON THE HOST after the deploy, read-only (no API, no writes):

    ssh ehm_eckx@10.89.1.246 "nice python3 - SINCE_EPOCH [--quiet]" < probe_chapters.py

SINCE_EPOCH: the restart time (e.g. $(date -d '2026-09-29 03:00Z' +%s)). It
reads data/script_ledger.jsonl (rows since), data/air_log.jsonl (what was HEARD:
aired == "stream", joined on id == line_id), data/system3.sqlite3 (each
conversation's plan, decisions, chapter_state) and data/system3_chapter_shelf.json.

Per LINE-ROAD CHAPTER (road in LINE_ROADS with a graph plan) it asserts:
  A  >= 3 aired spoken rows            B  >= 2 speaker identities
  C  one non-empty sid on every row    D  every planned turn aired
  E  each row its own stamp (rows sharing a turn_id: same speaker and marked
     split / cont / listening; a board or SFX-guy row rides its turn)
  F  every planned turn carries ES, every reply RS / IRS / FL (roll stamps)
  G  ledger order follows turn order and NO other conversation's dialogue sits
     between its first and last row      H  heard (air_log) in turn order
  I  a row's dice.s3.turn_id (when present) is its own system3.turn_id
Per ROUND (banter, caller, news ...): A, B, C, D (bound turns), E, I.
FRAGMENTS: every spoken row outside a passing chapter/round, by kind - the
forced injectors (emergency_host continuity pairs, gold bars) are listed apart.
SHELF: states; pending older than 30 min; expired/stale (recorded, never silent).
Exit 0 when every chapter and round passes and no unforced fragment aired.
"""
import collections
import json
import os
import sqlite3
import sys
import time
import zlib

ROOT = os.path.expanduser("~/pinevoice-stack/spark-agent/data")
LINE_ROADS = ("track_talk", "station_id", "upstairs", "interject", "ad_spot", "reply", "request", "open", "aside")
FORCED_KINDS = ("emergency_host",)
FORCED_ROUNDS = ("gold",)
SUB_WHO = ("board",)                      # clips ride the turn they punctuate


def tail_jsonl(path, since, key, cap=16_000_000):
    out = []
    try:
        size = os.path.getsize(path)
    except OSError:
        return out
    with open(path, "rb") as f:
        f.seek(max(0, size - cap))
        if size > cap:
            f.readline()
        for ln in f:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if float(r.get(key) or 0) >= since:
                out.append(r)
    return out


def conv_of(db, cid, cache={}):
    if cid in cache:
        return cache[cid]
    row = db.execute("select body from conversations where id=?", (cid,)).fetchone()
    body = None
    if row:
        try:
            body = json.loads(zlib.decompress(row[0]))
        except Exception:
            body = None
    cache[cid] = body
    return body


def families(turn):
    return {str(d.get("family") or d.get("kind") or "") for d in (turn.get("decisions") or [])}


def check(conv, rows, heard, ledger_all, chapter):
    """(verdict dict) for one conversation's rows (ledger order)."""
    fails, notes = [], []
    s3 = [(r.get("system3") or {}) for r in rows]
    spoken = [(r, s) for r, s in zip(rows, s3)
              if r.get("who") not in SUB_WHO and not s.get("sfxguy") and r.get("kind") not in ("sfx",)]
    main = [(r, s) for r, s in spoken if not s.get("listening")]
    who = {r.get("who") for r, _s in main}
    sids = {str(r.get("sid") or "") for r, _s in spoken}
    planned = [t.get("turn_id") for t in (conv.get("turns") or [])]
    aired = [str(s.get("turn_id") or "") for _r, s in main]
    if len(main) < 3:
        fails.append("A: %d spoken row(s)" % len(main))
    if len(who) < 2:
        fails.append("B: %d speaker(s)" % len(who))
    if len(sids) != 1 or "" in sids:
        fails.append("C: sids %s" % sorted(sids))
    missing = [t for t in planned if t not in set(aired)]
    if chapter and missing:
        fails.append("D: %d of %d planned turns not aired (%s)" % (len(missing), len(planned),
                                                                   ",".join(m.rsplit(":", 1)[-1] for m in missing[:6])))
    if not chapter:
        unbound = [b for b in (conv.get("bindings") or []) if b.get("script_index") is None]
        if unbound:
            notes.append("D: %d planned turn(s) unbound in the store" % len(unbound))
    by_tid = collections.defaultdict(list)
    for r, s in main:
        by_tid[str(s.get("turn_id") or "")].append((r, s))
    for tid, group in by_tid.items():
        if not tid:
            fails.append("E: a spoken row with no turn_id")
            continue
        if len({r.get("who") for r, _s in group}) > 1:
            fails.append("E: %s spoken by %s" % (tid.rsplit(":", 1)[-1], sorted({r.get("who") for r, _s in group})))
        elif len(group) > 1 and not all(s.get("split") or r.get("cont") or s.get("cont") or (r.get("dice") or {}).get("cont")
                                        for r, s in group[1:]):
            notes.append("E: %s aired as %d unmarked chunks" % (tid.rsplit(":", 1)[-1], len(group)))
    if chapter:
        for i, t in enumerate(conv.get("turns") or []):
            fam = families(t)
            if "ES" not in fam:
                fails.append("F: %s has no ES roll" % t.get("turn_id", "?").rsplit(":", 1)[-1])
            if i > 0 and not fam & {"RS", "IRS", "FL"}:
                fails.append("F: %s has no RS/IRS/FL roll" % t.get("turn_id", "?").rsplit(":", 1)[-1])
        order = [planned.index(a) for a in aired if a in planned]
        if order != sorted(order):
            fails.append("G: ledger order %s" % order)
        keys = [(r.get("block"), r.get("ord")) for r, _s in main]
        lo, hi = min(keys), max(keys)
        mine = str(conv.get("identity", {}).get("conversation_id") or "")
        between = [r for r in ledger_all
                   if lo < (r.get("block"), r.get("ord")) < hi
                   and (r.get("system3") or {}).get("conversation_id") != mine
                   and r.get("who") not in SUB_WHO and r.get("kind") not in ("sfx", "sfxguy")]
        if between:
            fails.append("G: %d row(s) of other conversations inside it (%s)" % (
                len(between), ", ".join(sorted({str(r.get("kind")) for r in between}))))
        ht = [heard.get(str(r.get("line_id") or "")) for r, _s in main]
        known = [(planned.index(s.get("turn_id")) if s.get("turn_id") in planned else -1, h)
                 for (_r, s), h in zip(main, ht) if h]
        if len(known) >= 2 and [t for t, _h in sorted(known, key=lambda x: x[1])] != sorted(t for t, _h in known):
            fails.append("H: heard out of turn order")
        if not known:
            notes.append("H: no air_log 'stream' receipt yet")
    for r, s in main:
        d = ((r.get("dice") or {}).get("s3") or {}).get("turn_id")
        if d and d != s.get("turn_id"):
            fails.append("I: row %s wears %s's dice" % (str(r.get("line_id"))[:8], str(d).rsplit(":", 1)[-1]))
    return {"fails": fails, "notes": notes, "rows": len(main), "speakers": sorted(who),
            "sid": sorted(sids), "planned": len(planned)}


def main(argv):
    since = float(argv[0]) if argv else time.time() - 3 * 3600
    quiet = "--quiet" in argv
    ledger = tail_jsonl(os.path.join(ROOT, "script_ledger.jsonl"), since, "at")
    ledger.sort(key=lambda r: (r.get("block") or 0, r.get("ord") or 0))
    heard = {str(r.get("id")): float(r.get("air_at") or 0)
             for r in tail_jsonl(os.path.join(ROOT, "air_log.jsonl"), since - 600, "ts")
             if r.get("aired") == "stream"}
    db = sqlite3.connect("file:" + os.path.join(ROOT, "system3.sqlite3") + "?mode=ro", uri=True)
    by_conv = collections.OrderedDict()
    loose = []
    for r in ledger:
        cid = str((r.get("system3") or {}).get("conversation_id") or "")
        if cid:
            by_conv.setdefault(cid, []).append(r)
        elif r.get("who") not in SUB_WHO and r.get("kind") not in ("sfx",):
            loose.append(r)
    print("probe since %s UTC: %d ledger rows, %d conversations, %d heard receipts" % (
        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(since)), len(ledger), len(by_conv), len(heard)))
    bad = 0
    tally = collections.Counter()
    fragments = collections.Counter()
    forced = collections.Counter()
    for cid, rows in by_conv.items():
        conv = conv_of(db, cid)
        if conv is None:
            fragments["(no store record) " + str(rows[0].get("kind"))] += 1
            continue
        road = str((conv.get("identity") or {}).get("road_kind") or "")
        chapter = road in LINE_ROADS and bool(conv.get("graph_structure")) and len(conv.get("turns") or []) >= 3
        # a forced injector (a continuity pair, a gold bar re-airing a turn) is counted
        # apart and never judged as the conversation it names
        for r in rows:
            if r.get("kind") in FORCED_KINDS or r.get("round") in FORCED_ROUNDS:
                forced[str(r.get("round") if r.get("round") in FORCED_ROUNDS else r.get("kind"))] += 1
        rows = [r for r in rows if not (r.get("kind") in FORCED_KINDS or r.get("round") in FORCED_ROUNDS)]
        spoken = [r for r in rows if r.get("who") not in SUB_WHO and r.get("kind") not in ("sfx",)]
        if not spoken:
            continue                     # board clips on a node of their own (cover_b's road)
        if road in LINE_ROADS and not chapter:
            fragments["%s (graph off / < 3 turns)" % road] += 1
            continue
        v = check(conv, rows, heard, ledger, chapter)
        kind = "chapter" if chapter else "round"
        ok = not v["fails"]
        tally[(kind, road, ok)] += 1
        state = (conv.get("chapter_state") or {}).get("state", "")
        if not ok:
            bad += 1
        if not ok or not quiet:
            print("%s %-7s %-10s %s rows=%d speakers=%s sid=%s planned=%d %s%s" % (
                "PASS" if ok else "FAIL", kind, road, cid, v["rows"], ",".join(v["speakers"]),
                ",".join(v["sid"]), v["planned"], ("state=" + state + " ") if state else "",
                "; ".join(v["fails"] + v["notes"])))
    for r in loose:
        k = "forced " + str(r.get("kind")) if (r.get("kind") in FORCED_KINDS or r.get("round") in FORCED_ROUNDS) \
            else str(r.get("kind"))
        (forced if k.startswith("forced") else fragments)[k] += 1
    print("\nSUMMARY")
    for (kind, road, ok), n in sorted(tally.items()):
        print("  %-7s %-11s %s x%d" % (kind, road, "PASS" if ok else "FAIL", n))
    print("  unforced fragments (spoken rows outside a chapter/round): %s" % (dict(fragments) or "none"))
    print("  forced injectors (operator's never-quiet / gold decisions): %s" % (dict(forced) or "none"))
    try:
        shelf = json.load(open(os.path.join(ROOT, "system3_chapter_shelf.json"), encoding="utf-8"))
    except Exception:
        shelf = {}
    states = collections.Counter(str(e.get("state")) for e in shelf.values())
    old = [k for k, e in shelf.items() if e.get("state") == "pending" and time.time() - float(e.get("created") or 0) > 1800]
    print("  prepared shelf: %s%s" % (dict(states) or "empty", ("; pending > 30 min: %s" % old[:6]) if old else ""))
    for k, e in list(shelf.items())[-8:]:
        if not quiet:
            print("    %-28s %-9s attempts=%s done=%s %.0fs  %s" % (k[:28], e.get("state"), e.get("attempts"), e.get("done"),
                                                                 float(e.get("seconds") or 0), str(e.get("why"))[:90]))
    verdict = bad == 0 and not fragments
    print("\nVERDICT: %s" % ("PASS" if verdict else "FAIL (%d failing conversation(s), %d unforced fragment kind(s))"
                             % (bad, len(fragments))))
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
