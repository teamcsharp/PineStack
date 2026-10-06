#!/usr/bin/env python3
"""[sfx-rehome] The clip collection moves to a new drive: verify the new home, and say what a path
change would cost. Runs ON THE HOST (python3, no station imports, no share walk).

"When I plug it up to the spark, I want the database work to continue and for it to plug back up
seamlessly into the system and be the new home for clipping and SFX clip retrieval."
                                                                    - the operator, 2026-10-06

THE ONE FACT THIS TOOL IS BUILT AROUND. A clip's id (sid) is sha1(absolute container path)[:16] -
app.py sfx_id(). Every store the station keeps about a clip is keyed by that sid or by that path:
the clip book (data/sfx_clips.db), the vector section (data/sfx_vectors), the plays, the deck, the
24 h no-repeat book, the bans and weights, the quarantine, the gains, the lengths and levels
ledgers (path:mtime_ns), the posters and spectrograms, the levelled copies, the supercut plans and
their cues. Keep the container path identical - /samples/samples_grabbed/<folder>/<clip> - and
every one of them is still true after the move. Change the prefix and every sid changes with it:
the book can be rewritten (this tool does it, behind two flags), the rest cannot be rewritten
safely from here and is listed so the loss is a decision, not a surprise.

Usage (on the host, from ~/pinevoice-stack/spark-agent):
  python3 tools/sfx_rehome.py --verify [ROOT]
        ROOT is the HOST mount of the new drive (default /home/ehm_eckx/samples). The book's rows
        are container paths under --container-root (/samples); each is mapped onto ROOT and a sample
        of --sample paths (200) spread across the folders must exist with matching bytes. Reports the
        folders the book knows that are missing on the drive, the folders on the drive the book has
        never seen, mtime agreement (the lengths/levels/gains ledgers are keyed path:mtime_ns), the
        mount facts (device, fstype, ro/rw) and a verdict: PASS / WARN / FAIL. Exit 0 / 0 / 1.
  python3 tools/sfx_rehome.py --dry-run --prefix-from /samples --prefix-to /other
        What a prefix change WOULD do: rows affected, old -> new path and sid examples, and every
        sid-keyed or path-keyed store found under data/ with how many of the book's sids appear in
        it. Writes nothing. Exit 0.
  python3 tools/sfx_rehome.py --apply --i-understand-sids-change --prefix-from /samples --prefix-to /other
        Rewrites the CLIP BOOK ONLY (path, sid, folder) in one transaction after copying it to
        data/sfx_clips.db.rehome-<stamp>.bak. Everything else stays as it was and is listed as
        orphaned. Refuses while the station holds the book open for writing (the -wal is live) unless
        --force. The same-path road (bind-mount or fstab at the same mount point) needs none of this.
  --book PATH  the clip book (default data/sfx_clips.db beside tools/); --data DIR the data dir;
  --json       machine-readable output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

SID_RE = re.compile(r"\b[a-f0-9]{16}\b")
SAMPLE_DEFAULT = 200
SCAN_MOST_BYTES = 64 * 1024 * 1024        # a store bigger than this is sampled, and says so

# The stores the station keeps about clips, relative to data/, and what keys them.
STORES: list[tuple[str, str, str]] = [
    ("sfx_clips.db", "sid + path", "the clip book: path PRIMARY KEY, sid - rewritten by --apply"),
    ("sfx_vectors/sfx_vectors.sqlite3", "sid", "the vector section: clips.sid, clip_vec, facet_tags, clips_fts, dialogue.clip_sid - every embedding, tag and transcript"),
    ("sfx_plays.json", "sid", "how often each clip aired, by road"),
    ("sfx_video_played.json", "sid", "the endless set's hour cooldown"),
    ("sfx_history.json", "sid", "the sting history (seeds the recency ring)"),
    ("sfx_history.jsonl", "sid", "the sting history, appended"),
    ("norepeat_book.json", "sid", "the 24 h no-repeat book (sfx entries)"),
    ("norepeat_refusals.jsonl", "sid", "the no-repeat refusals ledger"),
    ("sfx_bans.json", "sid", "the operator's bans"),
    ("sfx_weights.json", "sid", "the operator's per-clip weights"),
    ("sfx_deleted.json", "sid", "clips the operator deleted"),
    ("sfx_quarantine.jsonl", "sid + path", "the quarantine list (append-only; releases by sid)"),
    ("sfx_quarantine_releases.jsonl", "sid", "quarantine releases"),
    ("sfx_gains.json", "sid:mtime_ns", "measured gains (the [nas-gain] road)"),
    ("sfx_levels.json", "path:mtime_ns", "measured levels"),
    ("sfx_lengths.json", "path:mtime_ns", "the lengths ledger - the walk's warm road and sfx_seconds"),
    ("sfx_seen.json", "path", "when each clip was first seen"),
    ("sfx_display_receipts.jsonl", "sid (in urls)", "the display receipts"),
    ("sfx_keywords.json", "folder", "the matcher's folder keywords (folder names only - survives)"),
    ("sfx_folder_pin.json", "path", "the sampler's folder pin"),
    ("sfx_retroname_at.json", "path", "the renamer journal's read position"),
    ("supercut_campaigns.json", "sid", "the supercut campaigns"),
    ("sfx_glue.json", "sid + path", "the glue ledger (superseded shorts)"),
    ("sfx_cadence.sqlite3", "sid", "the cadence book"),
    ("sfxguy_reactions.db", "sid", "the SFX guy's reactions"),
]
STORE_DIRS: list[tuple[str, str, str]] = [
    ("sfx_posters", "<sid>.jpg", "the video posters"),
    ("sfx_specs", "<sid>.png", "the audio spectrograms"),
    ("voice_media/sfx", "<sid>-<mtime>-*.wav", "the levelled copies"),
    ("sfx_supercuts", "cues[].sid in sc-*.json", "the supercut plans"),
    ("sfx_boomerangs", "sid", "the boomerang clips"),
]


def sid_of(path: str) -> str:
    """app.py sfx_id(): sha1 of the absolute container path, 16 hex. Kept in step by a test."""
    return hashlib.sha1(str(path).encode()).hexdigest()[:16]


def open_book(book: Path, write: bool = False) -> sqlite3.Connection:
    if not book.is_file():
        raise SystemExit("no clip book at %s" % book)
    if write:
        con = sqlite3.connect(str(book), timeout=10)
    else:
        con = sqlite3.connect("file:%s?mode=ro" % book.as_posix(), uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def map_path(container_path: str, container_root: str, host_root: Path) -> Path | None:
    root = container_root.rstrip("/")
    text = str(container_path)
    if text == root:
        return host_root
    if not text.startswith(root + "/"):
        return None
    return host_root / text[len(root) + 1:]


def spread_sample(rows: list[sqlite3.Row], want: int) -> list[sqlite3.Row]:
    """`want` rows spread across folders: round-robin over the folders, each folder's rows in a
    deterministic shuffle (by sid), so a verify is repeatable and covers every folder it can."""
    by_folder: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_folder.setdefault(str(r["folder"] or ""), []).append(r)
    for rows_f in by_folder.values():
        rows_f.sort(key=lambda r: str(r["sid"] or ""))
    out: list[sqlite3.Row] = []
    folders = sorted(by_folder)
    ix = 0
    while len(out) < want and any(by_folder.values()):
        name = folders[ix % len(folders)]
        ix += 1
        if by_folder[name]:
            out.append(by_folder[name].pop(0))
    return out


def mount_facts(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"root": str(root)}
    try:
        st = root.stat()
        out["present"] = True
        out["device"] = st.st_dev
        out["root_device"] = Path("/").stat().st_dev
        out["own_filesystem"] = st.st_dev != Path("/").stat().st_dev
    except OSError as exc:
        out["present"] = False
        out["why"] = str(exc)[:200]
        return out
    try:
        import subprocess
        got = subprocess.run(["findmnt", "-T", str(root), "-no", "SOURCE,FSTYPE,OPTIONS,TARGET"],
                             capture_output=True, text=True, timeout=10)
        line = (got.stdout or "").strip().splitlines()
        if line:
            parts = line[0].split(None, 3)
            out["source"], out["fstype"] = parts[0], (parts[1] if len(parts) > 1 else "")
            out["options"] = parts[2] if len(parts) > 2 else ""
            out["target"] = parts[3] if len(parts) > 3 else ""
            out["read_only"] = "ro" in str(out.get("options", "")).split(",")
            out["cifs"] = out["fstype"] == "cifs"
    except Exception as exc:  # noqa: BLE001 - findmnt is a courtesy
        out["findmnt_why"] = str(exc)[:120]
    return out


def verify(book: Path, root: Path, container_root: str = "/samples", sample: int = SAMPLE_DEFAULT,
           folder_dir: str = "samples_grabbed") -> dict[str, Any]:
    """The book against the mounted tree. Read-only; stats `sample` files and lists the folders."""
    con = open_book(book)
    out: dict[str, Any] = {"book": str(book), "root": str(root), "container_root": container_root,
                           "mount": mount_facts(root), "at": time.time()}
    total = con.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
    rows = con.execute("SELECT path, sid, folder, bytes, mtime, playable FROM clips WHERE path LIKE ?",
                       (container_root.rstrip("/") + "/%",)).fetchall()
    out["book_rows"] = int(total)
    out["book_rows_of_collection"] = len(rows)
    out["book_rows_elsewhere"] = int(total) - len(rows)
    # the folders the book knows, by their container parent directory
    parents: dict[str, int] = {}
    for r in rows:
        parents[str(r["path"]).rsplit("/", 1)[0]] = parents.get(str(r["path"]).rsplit("/", 1)[0], 0) + 1
    missing_folders = []
    present_folders = 0
    for parent, n in sorted(parents.items(), key=lambda kv: -kv[1]):
        host = map_path(parent, container_root, root)
        try:
            if host is not None and host.is_dir():
                present_folders += 1
                continue
        except OSError:
            pass
        missing_folders.append({"folder": parent, "rows": n})
    out["folders_in_book"] = len(parents)
    out["folders_present"] = present_folders
    out["folders_missing"] = missing_folders[:200]
    out["folders_missing_count"] = len(missing_folders)
    # the folders on the drive the book has never seen (first level under samples_grabbed)
    extra = []
    known_first = {str(p).split("/")[3] if len(str(p).split("/")) > 3 else "" for p in parents}
    grabbed = root / folder_dir
    try:
        for entry in sorted(os.scandir(str(grabbed)), key=lambda e: e.name):
            if entry.is_dir(follow_symlinks=False) and entry.name not in known_first and not entry.name.startswith("."):
                extra.append(entry.name)
        out["drive_folder_dir_present"] = True
    except OSError as exc:
        out["drive_folder_dir_present"] = False
        out["drive_folder_dir_why"] = str(exc)[:200]
    out["folders_extra_on_drive"] = extra[:200]
    out["folders_extra_count"] = len(extra)
    # the sample: exists, bytes match, mtime agreement
    picked = spread_sample(list(rows), max(1, int(sample)))
    checked = ok_bytes = ok_mtime_s = ok_mtime_ns = 0
    bad: list[dict[str, Any]] = []
    for r in picked:
        host = map_path(str(r["path"]), container_root, root)
        checked += 1
        try:
            st = host.stat() if host is not None else None
        except OSError as exc:
            bad.append({"path": str(r["path"]), "why": type(exc).__name__})
            continue
        if st is None:
            bad.append({"path": str(r["path"]), "why": "outside the collection root"})
            continue
        want = r["bytes"]
        if want is not None and int(st.st_size) != int(want):
            bad.append({"path": str(r["path"]), "why": "bytes %d, the book says %d" % (st.st_size, int(want))})
            continue
        ok_bytes += 1
        mt = r["mtime"]
        if mt is not None:
            if abs(float(st.st_mtime) - float(mt)) < 1.0:
                ok_mtime_s += 1
            if abs(float(st.st_mtime) - float(mt)) < 1e-6:
                ok_mtime_ns += 1
    out["sample"] = {"asked": int(sample), "checked": checked, "ok": ok_bytes, "bad": bad[:40],
                     "bad_count": len(bad), "mtime_within_1s": ok_mtime_s, "mtime_exact": ok_mtime_ns}
    # the verdict
    mount = out["mount"]
    problems = []
    if not mount.get("present"):
        problems.append("the root is not there")
    if not out.get("drive_folder_dir_present"):
        problems.append("%s/%s is not a directory" % (root, folder_dir))
    if checked and ok_bytes < checked:
        problems.append("%d of %d sampled clips missing or a different size" % (checked - ok_bytes, checked))
    if missing_folders:
        problems.append("%d folder(s) the book knows are not on the drive" % len(missing_folders))
    warnings = []
    if extra:
        warnings.append("%d folder(s) on the drive the book has never seen (the next walk adds them)" % len(extra))
    if checked and ok_mtime_s < ok_bytes:
        warnings.append("%d of %d sampled clips carry a different mtime: the lengths/levels/gains ledgers "
                        "(keyed path:mtime_ns) miss for them and are re-measured lazily; the book's own "
                        "seconds and playable survive" % (ok_bytes - ok_mtime_s, ok_bytes))
    if mount.get("cifs"):
        warnings.append("the root is still a CIFS mount - this is the NAS, not the new drive")
    if mount.get("present") and not mount.get("own_filesystem"):
        problems.append("the root is on the system disk, not a mounted drive (the empty folder under the mount point?)")
    out["problems"] = problems
    out["warnings"] = warnings
    out["verdict"] = "FAIL" if problems else ("WARN" if warnings else "PASS")
    out["say"] = ("%s: %d of %d sampled clips present with matching bytes across %d folders; %d folder(s) missing, "
                  "%d extra; mtime exact for %d" % (out["verdict"], ok_bytes, checked, present_folders,
                                                     len(missing_folders), len(extra), ok_mtime_ns))
    out["next"] = ("the book is true for this tree - restart the container at a gap, then POST /api/sfx/db/rebuild "
                   "so the walk writes down anything new" if not problems else
                   "do not switch the station over yet: fix the problems above, then verify again")
    con.close()
    return out


def _scan_text(path: Path, sids: set[str], most: int = SCAN_MOST_BYTES) -> dict[str, Any]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        blob = fh.read(most)
    text = blob.decode("utf-8", "replace")
    found = set(SID_RE.findall(text))
    hit = found & sids
    return {"bytes": size, "sampled": size > most, "sid_tokens": len(found), "book_sids": len(hit)}


def _scan_sqlite(path: Path, sids: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"bytes": path.stat().st_size, "tables": {}}
    con = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True, timeout=10)
    try:
        for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % json.dumps(table))]
            sid_cols = [c for c in cols if c in ("sid", "clip_sid")]
            for c in sid_cols:
                try:
                    n = con.execute("SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL" % (json.dumps(table), c)).fetchone()[0]
                except sqlite3.Error:
                    continue
                hit = 0
                try:
                    for (s,) in con.execute("SELECT DISTINCT %s FROM %s" % (c, json.dumps(table))):
                        if s in sids:
                            hit += 1
                except sqlite3.Error:
                    hit = -1
                out["tables"]["%s.%s" % (table, c)] = {"rows": int(n), "book_sids": hit}
    finally:
        con.close()
    return out


def stores_report(data: Path, book: Path, sids: set[str]) -> list[dict[str, Any]]:
    report = []
    for rel, keyed, what in STORES:
        p = data / rel
        row: dict[str, Any] = {"store": rel, "keyed_by": keyed, "what": what, "present": p.is_file()}
        if p.is_file() and p.resolve() != book.resolve():
            try:
                if rel.endswith((".db", ".sqlite3")):
                    row.update(_scan_sqlite(p, sids))
                else:
                    row.update(_scan_text(p, sids))
            except Exception as exc:  # noqa: BLE001
                row["why"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
        report.append(row)
    for rel, keyed, what in STORE_DIRS:
        p = data / rel
        row = {"store": rel + "/", "keyed_by": keyed, "what": what, "present": p.is_dir()}
        if p.is_dir():
            names = []
            try:
                names = [e.name for e in os.scandir(str(p))][:200000]
            except OSError:
                names = []
            row["files"] = len(names)
            row["book_sids"] = sum(1 for n in names if n[:16] in sids)
            if rel == "sfx_supercuts":
                hit = 0
                for n in names:
                    if n.startswith("sc-") and n.endswith(".json"):
                        try:
                            hit += len(set(SID_RE.findall((p / n).read_text(encoding="utf-8", errors="replace"))) & sids)
                        except OSError:
                            continue
                row["book_sids"] = hit
        report.append(row)
    return report


def dry_run(book: Path, data: Path, prefix_from: str, prefix_to: str, examples: int = 5) -> dict[str, Any]:
    """What a prefix change would do. Writes nothing."""
    con = open_book(book)
    pf, pt = prefix_from.rstrip("/"), prefix_to.rstrip("/")
    rows = con.execute("SELECT path, sid, folder FROM clips WHERE path = ? OR path LIKE ?",
                       (pf, pf + "/%")).fetchall()
    total = con.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
    sids = {str(r["sid"]) for r in rows}
    sample = []
    for r in rows[:examples]:
        new = pt + str(r["path"])[len(pf):]
        sample.append({"path": str(r["path"]), "sid": str(r["sid"]), "new_path": new, "new_sid": sid_of(new)})
    stale = sum(1 for r in rows if str(r["sid"]) != sid_of(str(r["path"])))
    con.close()
    out = {"book": str(book), "prefix_from": pf, "prefix_to": pt, "rows_total": int(total),
           "rows_affected": len(rows), "rows_untouched": int(total) - len(rows),
           "sids_change": True, "examples": sample, "sids_already_stale": stale,
           "stores": stores_report(data, book, sids)}
    orphaned = [s for s in out["stores"] if s.get("present") and (
        (s.get("book_sids") or 0) > 0 or any((t.get("book_sids") or 0) > 0 for t in (s.get("tables") or {}).values()))]
    out["orphaned_stores"] = [s["store"] for s in orphaned]
    out["say"] = ("A prefix change %s -> %s would touch %d of %d book rows and change EVERY one of their sids "
                  "(sid = sha1(path)[:16]). %d other store(s) key the same sids and would no longer match: %s. "
                  "The seamless way is the SAME container path: mount or bind-mount the new drive at "
                  "/home/ehm_eckx/samples so /samples/samples_grabbed/... does not move, and no sid changes."
                  % (pf, pt, len(rows), total, len(orphaned), ", ".join(out["orphaned_stores"]) or "none found"))
    return out


def apply_prefix(book: Path, prefix_from: str, prefix_to: str, force: bool = False) -> dict[str, Any]:
    """Rewrite the CLIP BOOK ONLY: path, sid, folder. A backup copy first; one transaction."""
    pf, pt = prefix_from.rstrip("/"), prefix_to.rstrip("/")
    wal = book.with_name(book.name + "-wal")
    if wal.is_file() and wal.stat().st_size > 0 and not force:
        raise SystemExit("the book's -wal is live (%d bytes): the station holds it open. Stop the container "
                         "(docker compose stop spark-agent) or pass --force." % wal.stat().st_size)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = book.with_name(book.name + ".rehome-%s.bak" % stamp)
    shutil.copy2(book, backup)
    con = open_book(book, write=True)
    try:
        rows = con.execute("SELECT path FROM clips WHERE path = ? OR path LIKE ?", (pf, pf + "/%")).fetchall()
        plan = []
        for (old,) in [(str(r["path"]),) for r in rows]:
            new = pt + old[len(pf):]
            plan.append((new, sid_of(new), new.rsplit("/", 1)[0].rsplit("/", 1)[-1], old))
        with con:
            con.execute("BEGIN")
            # a target path that already exists would collide on the PRIMARY KEY: refuse the whole move
            have = {str(r[0]) for r in con.execute("SELECT path FROM clips")}
            clash = [p for p in plan if p[0] in have and p[0] != p[3]]
            if clash:
                raise SystemExit("%d target path(s) already exist in the book (first: %s) - nothing written"
                                 % (len(clash), clash[0][0]))
            con.executemany("UPDATE clips SET path = ?, sid = ?, folder = ? WHERE path = ?", plan)
        return {"ok": True, "rows_rewritten": len(plan), "backup": str(backup), "prefix_from": pf, "prefix_to": pt,
                "say": "%d book row(s) now read %s/...; their sids changed with them. The backup is %s. "
                       "Every other sid-keyed store is orphaned for these clips (see --dry-run)."
                       % (len(plan), pt, backup)}
    finally:
        con.close()


def _print(obj: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=1, default=str))
        return
    for key in ("verdict", "say", "next"):
        if key in obj:
            print("%s: %s" % (key.upper(), obj[key]))
    for key in ("problems", "warnings"):
        for line in obj.get(key) or []:
            print("  %s: %s" % (key[:-1], line))
    if "mount" in obj:
        m = obj["mount"]
        print("mount: %s fstype=%s ro=%s own_filesystem=%s" % (m.get("source", "?"), m.get("fstype", "?"),
                                                              m.get("read_only"), m.get("own_filesystem")))
    if "sample" in obj:
        s = obj["sample"]
        print("sample: %d checked, %d ok, %d bad, mtime within 1 s %d, exact %d"
              % (s["checked"], s["ok"], s["bad_count"], s["mtime_within_1s"], s["mtime_exact"]))
        for b in s["bad"][:10]:
            print("  bad: %s - %s" % (b["path"], b["why"]))
    if "folders_missing" in obj:
        print("folders: %d in the book, %d present, %d missing, %d extra on the drive"
              % (obj["folders_in_book"], obj["folders_present"], obj["folders_missing_count"], obj["folders_extra_count"]))
        for f in obj["folders_missing"][:10]:
            print("  missing: %s (%d rows)" % (f["folder"], f["rows"]))
        for f in obj["folders_extra_on_drive"][:10]:
            print("  extra: %s" % f)
    if "examples" in obj:
        print("rows affected: %d of %d" % (obj["rows_affected"], obj["rows_total"]))
        for e in obj["examples"]:
            print("  %s (%s) -> %s (%s)" % (e["path"], e["sid"], e["new_path"], e["new_sid"]))
    if "stores" in obj:
        print("stores keyed by sid or path:")
        for s in obj["stores"]:
            if not s.get("present"):
                print("  %-36s absent" % s["store"])
                continue
            hits = s.get("book_sids")
            if s.get("tables"):
                hits = ", ".join("%s=%s" % (k, v.get("book_sids")) for k, v in s["tables"].items())
            print("  %-36s %-14s book sids: %s%s" % (s["store"], s["keyed_by"], hits,
                                                     " (sampled)" if s.get("sampled") else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", nargs="?", const="/home/ehm_eckx/samples", metavar="ROOT")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--i-understand-sids-change", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--prefix-from", default="/samples")
    ap.add_argument("--prefix-to", default="")
    ap.add_argument("--container-root", default="/samples")
    ap.add_argument("--sample", type=int, default=SAMPLE_DEFAULT)
    ap.add_argument("--book", default="")
    ap.add_argument("--data", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    here = Path(__file__).resolve().parent.parent
    data = Path(args.data) if args.data else next(
        (c for c in (here / "data", Path.cwd() / "data") if (c / "sfx_clips.db").is_file()), here / "data")
    book = Path(args.book) if args.book else data / "sfx_clips.db"
    if args.verify:
        got = verify(book, Path(args.verify), args.container_root, args.sample)
        _print(got, args.json)
        return 1 if got["verdict"] == "FAIL" else 0
    if args.dry_run or args.apply:
        if not args.prefix_to:
            ap.error("--prefix-to is required")
        if args.apply:
            if not args.i_understand_sids_change:
                ap.error("--apply needs --i-understand-sids-change: every sid of the moved rows changes, and only "
                         "the clip book is rewritten (run --dry-run first)")
            got = apply_prefix(book, args.prefix_from, args.prefix_to, args.force)
            _print(got, args.json)
            return 0
        got = dry_run(book, data, args.prefix_from, args.prefix_to)
        _print(got, args.json)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
