#!/usr/bin/env python3
"""[s3-rownum] [s3-scaffold] [s3-heading] [s3-echo] The gold bank's bars that say
what was never words. DRY RUN BY DEFAULT.

A gold bar re-airs its own recorded TAKE, so a bar whose words end in a running-
order row number ("...It's nothing to worry about. 5"), carry the sheet's header
("TONIGHT'S TEMPERS : 1"), open on a segment's name printed as a heading, or say
a row's direction ("In distaste, plainly: ... then doubles down on the original
point.") says it again every time it fires - cleaning the text cannot reach the
audio. The cure is the station's own door: POST /api/gold/burn, which ARCHIVES the
bars to data/gold_burnt.json (never deletes) and POST /api/gold/restore puts them
back. Measured 2026-09-28 (ledger, 24 h): the bank re-aired 34 row-number lines,
2 TEMPERS lines and 21 direction lines, every one heard.

    cd ~/pinevoice-stack/spark-agent
    SPARK_AGENT_API_KEY=$(docker exec spark-agent printenv SPARK_AGENT_API_KEY) \\
        python3 tools/gold_cleaners.py            # dry run: lists the bars and why
        python3 tools/gold_cleaners.py --apply    # burns them through the API (restorable)

Options: --data <data dir> (default data/), --bank <gold_bars.json> (default
<data>/gold_bars.json, read only),
--url <operator API> (default http://127.0.0.1:8096), --json (the list as JSON).
The checks are the station's own: the parse's row-number rule, System 3's
scaffold kit and direction matcher on the live config's direction tables (the
repo's system3.py; without the on-air cleaner engine only the row numbers and
headings are checked, and it says so), and the schedule's entry names.
Exit 0: nothing found or burnt; 3: bars found (dry run); 1: an error."""
import json
import os
import re
import sys
import urllib.request

ROW_NUMBER_TAIL = re.compile(r"(?<=[.!?\u2026\"\u201d'\u2019)\]])\s+\d{1,2}\s*$")
ROW_NUMBER_LINE = re.compile(r"(?m)^[ \t]*\d{1,3}[.)]?[ \t]*$")
DIRECTION_FAMILIES = ("RS", "IRS", "FL", "CTS", "TEMPER", "EVENT")
INTENSITIES = ("mildly", "plainly", "hard")
# the running order's own grammar (system3._row_work / _round_adds), for a bar with no sheet of its own
ROW_GRAMMAR = ("takes the lead and pushes the subject on", "picks up a word or claim from",
               "never hands that line back as the whole turn", "goes on a roll here",
               "a rant a diatribe a story with a head of steam", "carries on over the interruption that follows",
               "gets a word in edgewise", "carries straight on over the interruption",
               "reading this out word for word as their own words", "says so in as many words",
               "everything after this turn is driven by that", "opens with the passage above word for word",
               "quote back the word or claim you are answering")


def arg(name, default=""):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv[:-1] else default


def api(url, key, path, body=None):
    req = urllib.request.Request(url.rstrip("/") + path, method="POST" if body is not None else "GET",
                                 data=None if body is None else json.dumps(body).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    repo = os.getcwd()
    sys.path.insert(0, repo)
    url, key = arg("--url", "http://127.0.0.1:8096"), os.environ.get("SPARK_AGENT_API_KEY", "")
    data = arg("--data", os.path.join(repo, "data"))
    bank_path = arg("--bank", os.path.join(data, "gold_bars.json"))
    with open(bank_path, encoding="utf-8") as fh:
        bars = [b for b in json.load(fh) if isinstance(b, dict)]
    notes = []
    try:
        import system3
    except Exception as exc:  # noqa: BLE001
        system3 = None
        notes.append("system3 not importable (%s): row numbers and headings only" % exc)
    cfg = None
    if key:
        try:
            got = api(url, key, "/api/system3/config")
            cfg = got.get("config") or got
        except Exception as exc:  # noqa: BLE001
            notes.append("the live config was not read (%s): the default config's tables stand in" % exc)
    if cfg is None and system3 is not None:
        cfg = system3.default_config()
    heads = kit = None
    if system3 is not None and hasattr(system3, "direction_kit") and hasattr(system3, "scaffold_kit"):
        heads = system3.scaffold_kit(cfg)
        texts, feels = list(ROW_GRAMMAR), set()
        for table in (cfg or {}).get("tables") or []:
            fam = str(table.get("family") or "")
            for cat in table.get("categories") or []:
                for item in cat.get("items") or []:
                    if fam in DIRECTION_FAMILIES:
                        texts.append(re.sub(r"\{[^}]*\}", " - ", str(item.get("text") or "")))
                    elif fam == "ES":
                        for w in {str(item.get("label") or ""), str(item.get("id") or "").split(".")[-1]}:
                            if re.fullmatch(r"[a-z]+", w.lower() or "-"):
                                feels.update((w.lower(), i) for i in INTENSITIES)
        phrases, _f = system3.direction_kit(*texts)
        kit = (phrases, tuple(sorted(feels)))
    elif system3 is not None:
        notes.append("this system3.py has no on-air cleaner engine: row numbers and headings only")
    names = set()
    try:
        with open(os.path.join(data, "schedule.json"), encoding="utf-8") as fh:
            sched = json.load(fh)

        def walk(x):
            if isinstance(x, dict):
                if "kind" in x and ("label" in x or "minutes" in x):
                    lab = " ".join(str(x.get("label") or "").split())
                    if len(lab) >= 3:
                        names.add(lab)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(sched)
    except Exception as exc:  # noqa: BLE001
        notes.append("schedule.json not read (%s): no heading check" % exc)
    heading = None
    if names:
        alts = []
        for n in sorted(names, key=len, reverse=True):
            core = r"[ \t]+".join(re.escape(w) for w in n.split())
            sep = r"(?:[ \t]*[:\-\u2013\u2014][ \t\n]*|[ \t]*\n[ \t\n]*%s)" % (r"|[ \t]+" if " " in n else "")
            alts.append(r"(?i:%s)[*_\"\u201d'\u2019]*%s" % (core, sep))
        heading = re.compile(r"^[ \t*_#>\"\u201c'\u2018]*(?:%s)(?=[\"\u201c\u2018'*_]*[A-Z0-9])" % "|".join(alts))
    found = []
    for b in bars:
        text = str(b.get("text") or "")
        why = []
        if ROW_NUMBER_TAIL.search(text.strip()) or ROW_NUMBER_LINE.search(text):
            why.append("row number")
        if heads is not None:
            lab = system3.find_scaffold(text, heads)
            if lab:
                why.append("prompt header: %s" % lab)
        if kit is not None:
            said = system3.direction_echo(text, kit)
            if said:
                why.append("direction: %s" % said)
        if heading is not None and heading.match(text):
            why.append("heading")
        if why:
            found.append({"key": b.get("key"), "who": b.get("who"), "fired": b.get("fired"), "why": why,
                          "text": text})
    for n in notes:
        print("note:", n)
    if "--json" in sys.argv:
        print(json.dumps(found, indent=1))
    else:
        print("%d of %d gold bars say what was never words:" % (len(found), len(bars)))
        for f in found:
            print("  %s  %-7s fired %-3s %s | ...%s" % (f["key"], f["who"], f["fired"], "; ".join(f["why"]),
                                                    f["text"][-90:]))
    if not found:
        return 0
    if "--apply" not in sys.argv:
        print("dry run - nothing burnt. --apply burns them through POST /api/gold/burn (archived, restorable).")
        return 3
    if not key:
        print("--apply needs SPARK_AGENT_API_KEY")
        return 1
    got = api(url, key, "/api/gold/burn", {"keys": [f["key"] for f in found],
                                           "why": "[s3-rownum] the take says a row number, a prompt header, a "
                                                  "heading or a running-order direction"})
    print("burnt:", json.dumps(got))
    return 0 if got.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
