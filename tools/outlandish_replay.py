#!/usr/bin/env python3
"""[outlandish] Replay aired lines through the OUTLANDISH meter (read-only).

  python3 tools/outlandish_replay.py [--hours 6] [--db data/system3.sqlite3] [--top 20] [--json]

Reads the System 3 ledger (lines + conversations) read-only, scores every aired
spoken line (all seats and roads; board clip rows are sounds and are skipped),
and prints: the score distribution, by road and seat, the top N by #code, and
for each top line whether a dispute followed (aired / planned-but-cut / none),
plus the interject-road shape (rounds per hour, turns aired per round) and the
holding-line count. Uses the station's live OUTLANDISH1 / OUTDISPUTE1 when the
ledger's current config holds them, else the defaults. Never writes.
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import outlandish  # noqa: E402

HOLDING = (
    "keeping you company while the next conversation", "the next conversation is taking",
    "we have more conversation waiting", "still on the air. the studio is finishing",
    "births take a minute", "records are patient people", "a conversation about to be born",
    "the desk is busy behind us", "the next piece is being checked", "better a short wait",
    "nothing gets read out before it is ready", "we are between thoughts",
    "we will be back with words when the words", "we'll return to it when it is ready",
    "until it arrives, the music has the room", "what comes next is worth finishing",
    "we are keeping the station moving", "something is being", "the part of the show where the music does",
)


def unpack(blob):
    try:
        return json.loads(zlib.decompress(blob))
    except Exception:  # noqa: BLE001
        return json.loads(blob)


def code_of(line_id):
    return "#" + str(line_id or "")[:6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--db", default="data/system3.sqlite3")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--until", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % a.db, uri=True)
    until = a.until or con.execute("SELECT MAX(at) FROM lines").fetchone()[0] or time.time()
    since = until - a.hours * 3600
    cfg_tables = None
    try:
        row = con.execute("SELECT body FROM configs ORDER BY created DESC LIMIT 1").fetchone()
        cfg_tables = unpack(row[0]) if row else None
    except Exception:  # noqa: BLE001
        cfg_tables = None
    meter = outlandish.table_of(cfg_tables, "OUTLANDISH1")
    th = outlandish.thresholds(meter)
    rows = con.execute(
        "SELECT l.line_id, l.conversation_id, l.turn_id, l.who, l.text, l.at, v.road "
        "FROM lines l JOIN conversations v ON v.id = l.conversation_id WHERE l.at > ? AND l.at <= ? "
        "ORDER BY l.at", (since, until)).fetchall()
    aired_tids = collections.defaultdict(set)
    for _lid, cid, tid, _w, _t, _at, _r in rows:
        if tid:
            aired_tids[cid].add(tid)
    t0 = time.perf_counter()
    scored = []
    for lid, cid, tid, who, text, at, road in rows:
        if who in ("board",) or not str(text or "").strip():
            continue
        r = outlandish.score(text, meter)
        scored.append({"line_id": lid, "code": code_of(lid), "cid": cid, "turn_id": tid, "who": who,
                       "road": road, "at": at, "text": text, "score": r["score"], "tags": r["tags"],
                       "cues": [c["label"] + ": " + c["match"] for c in r["cues"]], "level": r["level"]})
    ms = (time.perf_counter() - t0) * 1000.0
    hist = collections.Counter(min(9, s["score"] // 10) for s in scored)
    top = sorted(scored, key=lambda s: (-s["score"], s["at"]))[:a.top]
    convs = {}
    for s in top + [x for x in scored if x["score"] >= th["audit"]]:
        if s["cid"] in convs:
            continue
        got = con.execute("SELECT body FROM conversations WHERE id=?", (s["cid"],)).fetchone()
        convs[s["cid"]] = unpack(got[0]) if got else None
    follow = collections.Counter()
    for s in [x for x in scored if x["score"] >= th["audit"]]:
        conv = convs.get(s["cid"]) or {}
        turns = conv.get("turns") or []
        idx = next((i for i, t in enumerate(turns) if t.get("turn_id") == s["turn_id"]), -1)
        f = outlandish.follow_of(turns, idx, aired_tids.get(s["cid"], ())) if idx >= 0 else {"state": "none",
                                                                                              "why": "no planned turn"}
        s["follow"] = f["state"]
        follow[f["state"]] += 1
    for s in top:
        s.setdefault("follow", "-")
    by_road = collections.defaultdict(list)
    for s in scored:
        by_road[s["road"]].append(s["score"])
    # the interject road's shape
    iconv = con.execute("SELECT id, body FROM conversations WHERE road='interject' AND created > ? AND created <= ?",
                        (since, until)).fetchall()
    per_round = collections.Counter()
    board_rounds = 0
    for cid, body in iconv:
        n = len(aired_tids.get(cid, ()))
        b = unpack(body)
        roles = (b.get("inputs") or {}).get("roles") or {}
        first = (b.get("turns") or [{}])[0].get("speaker") if b.get("turns") else ""
        if roles.get(first) == "board":
            board_rounds += 1
            continue
        per_round[n] += 1
    # dispute follow-through by road: of the rounds with 2+ aired turns, how many aired a
    # different seat's turn that rolled a dispute (RS argue/push_back/oppositional,
    # IRS refutation/confrontational/opposite)
    by_conv = collections.defaultdict(list)
    for lid, cid, tid, who, text, at, road in rows:
        by_conv[cid].append((road, tid))
    disp = collections.defaultdict(lambda: [0, 0])
    for cid, got in by_conv.items():
        tids = {t for _r, t in got if t}
        if len(tids) < 2:
            continue
        body = con.execute("SELECT body FROM conversations WHERE id=?", (cid,)).fetchone()
        if not body:
            continue
        turns = unpack(body[0]).get("turns") or []
        first = next((t for t in turns if t.get("turn_id") in tids), None)
        if not first:
            continue
        road = got[0][0]
        disp[road][1] += 1
        if any(t.get("turn_id") in tids and t.get("speaker") != first.get("speaker")
               and outlandish.is_dispute(t.get("decisions") or []) for t in turns):
            disp[road][0] += 1
    holding = sum(1 for lid, cid, tid, who, text, at, road in rows
                  if any(h in " ".join(str(text or "").lower().split()) for h in HOLDING))
    out = {"window": {"since": since, "until": until, "hours": a.hours}, "thresholds": th,
           "lines_scored": len(scored), "rule_pass_ms_total": round(ms, 1),
           "rule_pass_us_per_line": round(ms * 1000.0 / max(1, len(scored)), 1),
           "distribution": {"%d-%d" % (k * 10, k * 10 + 9 if k < 9 else 100): hist.get(k, 0) for k in range(10)},
           "at_or_above": {k: sum(1 for s in scored if s["score"] >= v) for k, v in th.items()},
           "by_road": {r: {"n": len(v), "mean": round(sum(v) / len(v), 1), "audit": sum(1 for x in v if x >= th["audit"])}
                       for r, v in sorted(by_road.items())},
           "follow_after_audit": dict(follow),
           "interject": {"rounds": len(iconv), "per_hour": round(len(iconv) / a.hours, 1),
                         "board_stamp_rounds": board_rounds,
                         "spoken_rounds_by_turns_aired": dict(sorted(per_round.items()))},
           "holding_lines": holding,
           "dispute_follow_through": {r: {"rounds": v[1], "disputed": v[0],
                                          "pct": round(100.0 * v[0] / max(1, v[1]))} for r, v in sorted(disp.items())},
           "top": [{k: s[k] for k in ("code", "score", "tags", "who", "road", "follow", "text", "cues")} for s in top]}
    if a.json:
        print(json.dumps(out, indent=1, default=str))
        return 0
    print("window %.1f h, %d spoken lines scored in %.1f ms (%.1f us/line); thresholds %s"
          % (a.hours, len(scored), ms, out["rule_pass_us_per_line"], th))
    print("distribution:", out["distribution"])
    print("at or above:", out["at_or_above"], " follow after audit-level lines:", dict(follow))
    for r, v in out["by_road"].items():
        print("  %-12s n=%-4d mean=%-5s audit=%d" % (r, v["n"], v["mean"], v["audit"]))
    print("interject road:", out["interject"], " holding lines:", holding)
    print("dispute follow-through (rounds with 2+ aired turns):",
          ", ".join("%s %d/%d (%d%%)" % (r, v["disputed"], v["rounds"], v["pct"])
                    for r, v in out["dispute_follow_through"].items()))
    print("top %d:" % a.top)
    for s in top:
        print("  %s %3d %-26s %-7s %-10s %-11s %s" % (s["code"], s["score"], ",".join(s["tags"])[:26], s["who"],
                                                    s["road"], s["follow"], " ".join(s["text"].split())[:90]))
        print("        cues: %s" % "; ".join(s["cues"])[:160])
    return 0


if __name__ == "__main__":
    sys.exit(main())
