#!/usr/bin/env python3
"""p2-direction measurement (READ-ONLY). Aired seat lines -> their System 3 turn's
rolls -> the exact prompt that wrote them -> is the direction there, where, and
what fights it -> does the written line act it -> was the take shaped.

    python3 measure.py --data data --hours 3 --json out.json
"""
import argparse, json, os, re, sqlite3, time, zlib, collections
from pathlib import Path

SEATS = ("dj", "cohost", "caller", "caller2", "third")
WRITERS = ("station:round", "station:round live", "station:banter beat", "station:turn rewrite",
           "station:caller", "station:caller live", "station:caller rewrite", "station:writing",
           "station:chapter repair", "station:writers room", "station:call pivots")
FIGHTERS = {
    "no_interjection_noises": "no interjection noises",
    "warm_dry_persona": "Warm, dry, a little conspiratorial",
    "clean_turns": "Take clean turns. Let each other finish.",
    "short_sentences": "Keep each turn to one or two short speakable sentences",
    "play_it_straight": "Play it straight",
    "word_band": "words per ordinary turn",
    "amiable_ending": "brief, amiable ending",
    "never_name_them": "perform both, never name them",
}
INTERJ = set("oh ah whoa wow what no god damn hell ugh hey yes yeah ha jesus christ seriously wait okay "
             "listen look please stop come huh eh boy man dude fuck shit".split())


def tail_lines(path, limit):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        fh.seek(max(0, size - limit))
        blob = fh.read()
    out = []
    for line in blob.split(b"\n")[1:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def norm(t):
    return " ".join(re.findall(r"[a-z0-9']+", str(t or "").lower()))


def line_feats(text, label):
    t = str(text or "")
    words = re.findall(r"[A-Za-z']+", t)
    low = [w.lower() for w in words]
    return {"chars": len(t), "words": len(words), "excl": t.count("!"), "q": t.count("?"),
            "dash_or_ellipsis": t.count("--") + t.count("—") + t.count("...") + t.count("…"),
            "interj": sum(1 for w in low[:4] if w in INTERJ),
            "caps": sum(1 for w in words if len(w) > 1 and w.isupper() and w not in ("I", "OK", "AI", "DJ", "FM")),
            "names_feeling": bool(label) and norm(label) in norm(t),
            "sentences": max(1, len(re.findall(r"[.!?]+", t)))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--hours", type=float, default=3)
    ap.add_argument("--json")
    a = ap.parse_args()
    data = Path(a.data)
    since = time.time() - a.hours * 3600
    rows = [r for r in tail_lines(data / "screenplay_lines.jsonl", 20_000_000)
            if r.get("who") in SEATS and float(r.get("at") or 0) >= since]
    s3 = sqlite3.connect("file:%s?mode=ro" % (data / "system3.sqlite3"), uri=True)
    ph = sqlite3.connect("file:%s?mode=ro" % (data / "prompt_history.sqlite3"), uri=True)
    calls = []
    for cid, at, purpose, req, resp in ph.execute(
            "select id, at, purpose, request, response from calls where at>=? and purpose in (%s) order by seq"
            % ",".join("?" * len(WRITERS)), (since - 1800,) + WRITERS):
        try:
            rq = json.loads(zlib.decompress(req)) if req else {}
            rs = json.loads(zlib.decompress(resp)) if resp else {}
        except Exception:
            continue
        prompt = "\n".join(str(m.get("content") or "") for m in rq.get("messages") or []) or str(rq.get("prompt") or "")
        out = str((rs.get("message") or {}).get("content") or rs.get("response") or "")
        calls.append({"id": cid, "at": at, "purpose": purpose, "prompt": prompt, "out": out, "nout": norm(out)})
    convs = {}
    res = []
    for r in rows:
        got = s3.execute("select conversation_id, turn_id, text from lines where line_id=?", (str(r.get("id")),)).fetchone()
        if not got:
            res.append({"id": r.get("id"), "who": r.get("who"), "link": "no s3 line"})
            continue
        cid, tid, text = got
        if cid not in convs:
            b = s3.execute("select body, mode, road from conversations where id=?", (cid,)).fetchone()
            convs[cid] = (json.loads(zlib.decompress(b[0])), b[1], b[2]) if b else (None, None, None)
        conv, mode, road = convs[cid]
        if not conv:
            continue
        turn = next((t for t in conv["turns"] if str(t.get("turn_id")) == str(tid)), None)
        if turn is None:
            res.append({"id": r.get("id"), "who": r.get("who"), "link": "turn missing", "text": text})
            continue
        es = next((d for d in turn.get("decisions") or [] if d.get("family") == "ES" and d.get("item")), None)
        rolls = [{"family": d.get("family"), "table": d.get("table"), "category": d.get("category"),
                  "item": d.get("item"), "label": d.get("label"), "intensity": d.get("intensity")}
                 for d in turn.get("decisions") or [] if d.get("item")]
        temper = (conv.get("tempers") or {}).get(turn.get("speaker")) or {}
        nt = norm(text)
        snippet = nt[:60]
        call = None
        for c in reversed(calls):
            if c["at"] <= float(r.get("at") or 0) and snippet and snippet in c["nout"]:
                call = c
                break
        info = {"id": r.get("id"), "at": r.get("at"), "who": r.get("who"), "seat": turn.get("speaker"),
                "name": turn.get("name"), "conv": cid, "mode": mode, "road": road, "turn": turn.get("index"),
                "step": turn.get("step"), "text": text, "rolls": rolls,
                "es": {k: (es or {}).get(k) for k in ("category", "item", "label", "intensity")} if es else None,
                "es_direction": (es or {}).get("direction") or (es or {}).get("text"),
                "shock": (turn.get("shock") or {}).get("text"), "temper": temper.get("text"),
                "perf_es": ((r.get("perf") or {}).get("es") if isinstance(r.get("perf"), dict) else None),
                "feats": line_feats(text, (es or {}).get("label"))}
        if call:
            p = call["prompt"]
            d = str(info["es_direction"] or "")
            core = d.split(":")[0] if d else ""
            pos = p.rfind(d[:80]) if d else -1
            if pos < 0 and core:
                pos = p.rfind(core)
            row = ""
            if pos >= 0:
                s = p.rfind("\n", 0, pos) + 1
                e = p.find("\n", pos)
                row = p[s:e if e >= 0 else None]
            info.update({"call": call["id"], "purpose": call["purpose"], "prompt_chars": len(p),
                         "es_in_prompt": pos >= 0, "es_chars_from_end": (len(p) - pos) if pos >= 0 else None,
                         "row_chars": len(row), "es_offset_in_row": (row.find(core) if core and row else None),
                         "row": row[:1600],
                         "row_intonation": re.findall(r"Deliver this in an? (\w+) intonation", row),
                         "row_internally": re.findall(r"Internally ([^.]+)", row),
                         "row_feeling_word": re.findall(r"feeling (\w+) \((\w+)\)", row) or re.findall(r"in (\w+) \((\w+)\)", row),
                         "fighters": [k for k, v in FIGHTERS.items() if v in p]})
        res.append(info)
    s = collections.Counter()
    for x in res:
        s["lines"] += 1
        if x.get("es"): s["has_es_roll"] += 1
        if x.get("call"): s["prompt_found"] += 1
        if x.get("es_in_prompt"): s["es_in_prompt"] += 1
        if x.get("row_intonation"): s["row_has_other_intonation"] += 1
        if x.get("shock"): s["shock"] += 1
        f = x.get("feats") or {}
        if f.get("excl"): s["has_exclamation"] += 1
        if f.get("interj"): s["opens_on_interjection"] += 1
        if f.get("names_feeling"): s["names_the_feeling"] += 1
        pe = x.get("perf_es") or {}
        if pe.get("voice") and pe.get("baked") is not False: s["take_shaped"] += 1
        s["purpose:%s" % x.get("purpose")] += 1
        for k in x.get("fighters") or []:
            s["fighter:%s" % k] += 1
    out = {"window_h": a.hours, "summary": dict(s), "lines": res}
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    print(json.dumps(out["summary"], indent=1))


if __name__ == "__main__":
    main()
