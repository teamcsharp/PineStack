"""[s3-slash] Repair (never delete) the stored banks that already hold a turn
with a slash or a speaker marker on its front ("/Out of hand? ...",
"A: /B: every pause ...", "A: A: Well ...").

Run it AFTER tools/turn_edge_slash_patch.py is applied (the repaired scripts
parse to exactly what the patched parser makes of the stored ones - proven by
tests/test_turn_edge_slash.py - so the repair is air-neutral once the patch is
in). Pure stdlib: runs on the host against a copy of data/ first.

    python3 tools/turn_edge_slash_store_repair.py [DATA_DIR]            # report
    python3 tools/turn_edge_slash_store_repair.py [DATA_DIR] --apply    # write

What it does, per store:
- manager_memos.json [*].text, larder.json [*].script (+ recast.script),
  prep_shelf.json {kind: [ {entry: {script}} ]}: each "X: " line keeps its
  marker and loses the edge after it; a line with no marker loses a slashed edge.
- pantry.json: the TTS cache is keyed on the chunk's words. A chunk whose edge
  was only slashes / pipes (XTTS's sanitiser turned them into a space, so the
  take says nothing wrong) gets a TWIN under the key the patched road now asks
  for - pantry_key(edge-cleaned, first letter up, voice, engine) - with the same
  clip, so a banked round does not go back to a live render. Only when the old
  key re-hashes from its own text (the scheme is proven per entry). A chunk whose
  edge held a speaker MARKER ("/B: ...": the take says "B") gets no twin: the
  patched road asks for the clean words and renders them.
- gold_bars.json: a bar with a slashed edge gets its words repaired; a bar whose
  edge held a speaker marker (its take says the letter) is moved - words
  repaired - into gold_burnt.json, the bin /api/gold/burn uses (restorable).
- said_lines.json [*].t (what the copy checks compare against): repaired.
- system3_chapter_shelf.json entries' opening / context: repaired; an entry that
  is not yet aired whose opening held a marker (its first clip is that take) is
  set "expired" with its reason, the shelf's own terminal state.
Every written file is first copied to <name>.bak-slash-<stamp>. Nothing else is
touched. Exit 0 = something to repair (report) / applied, 2 = nothing to do.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

# The SAME expressions as app.py's turn_edge_clean (tests assert they match).
TURN_EDGE = re.compile(r"^(?:\s*[/\\|]+|\s*[ABCDE]\s*:(?!\d))+\s*")
TURN_EDGE_SLASH = re.compile(r"^\s*(?:[/\\|]+\s*(?:[ABCDE]\s*:(?!\d)\s*)?)+")
MARK_LINE = re.compile(r"^(\s*[A-Ea-e]\s*:\s*)(.*)$", re.S)
HAS_MARKER = re.compile(r"[ABCDE]\s*:")


def edge(text, markers=True):
    s = str(text or "")
    m = (TURN_EDGE if markers else TURN_EDGE_SLASH).match(s)
    return s[m.end():] if m and m.end() else s


def edge_part(text, markers=True):
    s = str(text or "")
    m = (TURN_EDGE if markers else TURN_EDGE_SLASH).match(s)
    return s[:m.end()] if m and m.end() else ""


def repair_line(text):
    """One stored line/chunk: (repaired, had_marker_in_edge)."""
    cut = edge_part(text)
    if not cut:
        return text, False
    rest = str(text)[len(cut):]
    if not rest.strip():
        return text, False
    return rest, bool(HAS_MARKER.search(cut))


def repair_script(script):
    out, n = [], 0
    for line in str(script or "").split("\n"):
        m = MARK_LINE.match(line)
        if m:
            rest = edge(m.group(2))
            if rest != m.group(2) and rest.strip():
                line, n = m.group(1) + rest, n + 1
        else:
            rest = edge(line, markers=False)
            if rest != line and rest.strip():
                line, n = rest, n + 1
        out.append(line)
    return "\n".join(out), n


def pantry_key(text, voice, engine):
    raw = f"{engine}\x00{voice}\x00{str(text or '').strip()}"
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, obj, stamp):
    path = Path(path)
    shutil.copy2(path, str(path) + ".bak-slash-" + stamp)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


def scripts(data, report):
    changed = {}
    p = data / "manager_memos.json"
    if p.exists():
        o, n = load(p), 0
        for row in o if isinstance(o, list) else []:
            if isinstance(row, dict) and isinstance(row.get("text"), str):
                new, k = repair_script(row["text"])
                if k:
                    row["text"], n = new, n + k
        report["manager_memos.json lines"] = n
        if n:
            changed[p] = o
    p = data / "larder.json"
    if p.exists():
        o, n = load(p), 0
        for row in o if isinstance(o, list) else []:
            for holder in (row, row.get("recast") if isinstance(row, dict) else None):
                if isinstance(holder, dict) and isinstance(holder.get("script"), str):
                    new, k = repair_script(holder["script"])
                    if k:
                        holder["script"], n = new, n + k
        report["larder.json script lines"] = n
        if n:
            changed[p] = o
    p = data / "prep_shelf.json"
    if p.exists():
        o, n = load(p), 0
        for _kind, rows in (o.items() if isinstance(o, dict) else []):
            for row in rows if isinstance(rows, list) else []:
                ent = row.get("entry") if isinstance(row, dict) else None
                for holder in (ent, (ent or {}).get("recast") if isinstance(ent, dict) else None):
                    if isinstance(holder, dict) and isinstance(holder.get("script"), str):
                        new, k = repair_script(holder["script"])
                        if k:
                            holder["script"], n = new, n + k
        report["prep_shelf.json script lines"] = n
        if n:
            changed[p] = o
    return changed


def pantry(data, report):
    p = data / "pantry.json"
    if not p.exists():
        return {}
    o = load(p)
    twins, marker, unproven, present = 0, 0, 0, 0
    add = {}
    for key, row in list(o.items()):
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            continue
        new, had_marker = repair_line(row["text"])
        if new == row["text"]:
            continue
        if had_marker:
            marker += 1
            continue
        clip = row.get("clip") or {}
        engine = str(clip.get("engine") or "")
        voice = str(row.get("voice") or clip.get("voice") or "")
        if pantry_key(row["text"], voice, engine) != key:
            unproven += 1
            continue
        new = new[:1].upper() + new[1:]
        nkey = pantry_key(new, voice, engine)
        if nkey in o or nkey in add:
            present += 1
            continue
        twin = json.loads(json.dumps(row))
        twin["text"] = new
        twin["repaired_from"] = key
        twin["repaired_why"] = "[s3-slash] the chunk's words without the slash on their front"
        add[nkey] = twin
        twins += 1
    o.update(add)
    report["pantry.json twins added (slash-only edge, take clean)"] = twins
    report["pantry.json left (edge held a marker: the take says it)"] = marker
    report["pantry.json skipped (key does not re-hash)"] = unproven
    report["pantry.json twin already there"] = present
    return {p: o} if twins else {}


def lines(data, report, stamp):
    changed = {}
    p = data / "gold_bars.json"
    if p.exists():
        o, fixed, burnt = load(p), 0, []
        keep = []
        for bar in o if isinstance(o, list) else []:
            if isinstance(bar, dict) and isinstance(bar.get("text"), str):
                new, had_marker = repair_line(bar["text"])
                if new != bar["text"]:
                    bar["text"] = new
                    if had_marker:
                        bar["burnt_at"] = int(time.time())
                        bar["burnt_why"] = ("[s3-slash] its take says the speaker marker the writer "
                                            "left on the line's front")
                        burnt.append(bar)
                        continue
                    fixed += 1
            keep.append(bar)
        report["gold_bars.json words repaired"] = fixed
        report["gold_bars.json moved to gold_burnt.json (take says the marker)"] = len(burnt)
        if fixed or burnt:
            changed[p] = keep
        if burnt:
            bp = data / "gold_burnt.json"
            b = load(bp) if bp.exists() else []
            changed[bp] = (burnt + list(b))[:4000]
    p = data / "said_lines.json"
    if p.exists():
        o, n = load(p), 0
        for row in o if isinstance(o, list) else []:
            if isinstance(row, dict) and isinstance(row.get("t"), str):
                new, _m = repair_line(row["t"])
                if new != row["t"]:
                    row["t"], n = new, n + 1
        report["said_lines.json repaired"] = n
        if n:
            changed[p] = o
    p = data / "system3_chapter_shelf.json"
    if p.exists():
        o, n, expired = load(p), 0, 0
        for _key, e in (o.items() if isinstance(o, dict) else []):
            if not isinstance(e, dict):
                continue
            marker_open = False
            for field in ("opening", "context"):
                if isinstance(e.get(field), str):
                    new, had_marker = repair_line(e[field])
                    if new != e[field]:
                        e[field], n = new, n + 1
                        marker_open = marker_open or (had_marker and field == "opening")
            if marker_open and e.get("state") not in ("aired", "expired", "airing"):
                e["state"] = "expired"
                e["why"] = "[s3-slash] its opening take says the speaker marker the writer left on it"
                e["updated"] = time.time()
                expired += 1
        report["system3_chapter_shelf.json fields repaired"] = n
        report["system3_chapter_shelf.json expired (opening take says the marker)"] = expired
        if n:
            changed[p] = o
    return changed


def main(argv):
    do_apply = "--apply" in argv
    data = Path(next((a for a in argv if not a.startswith("--")), "data"))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report = {}
    changed = {}
    changed.update(scripts(data, report))
    changed.update(pantry(data, report))
    changed.update(lines(data, report, stamp))
    for k, v in report.items():
        print("%-66s %s" % (k, v))
    if not changed:
        print("nothing to repair")
        return 2
    if not do_apply:
        print("would write: " + ", ".join(sorted(p.name for p in changed)))
        return 0
    for path, obj in changed.items():
        save(path, obj, stamp)
    print("APPLIED: " + ", ".join(sorted(p.name for p in changed)) + " (backups *.bak-slash-%s)" % stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
