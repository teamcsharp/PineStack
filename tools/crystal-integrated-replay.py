"""Replay complete tint grades against a fixed corpus; never ask a model or vote."""
import argparse
from collections import Counter
from contextlib import closing
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def counts(rows):
    return dict(Counter(row["transition"] for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default="")
    parser.add_argument("--output", default=str(ROOT / "docs" / "crystal-integrated-replay.json"))
    parser.add_argument("--expected-count", type=int, default=920)
    args = parser.parse_args()
    data = os.environ.get("SPARK_AGENT_DATA_DIR", "")
    if not data or Path(data).resolve().is_relative_to((ROOT / "data").resolve()):
        raise SystemExit("Set SPARK_AGENT_DATA_DIR to an isolated temporary directory before importing app.")
    audit = json.loads((ROOT / "docs" / "rejection-corpus-audit.json").read_text(encoding="utf-8"))
    snapshot = Path(args.snapshot or audit["private_snapshot_path"])
    source_hashes = {name: sha256_file(ROOT / name) for name in ("app.py", "crystal_contract.py")}
    snapshot_hash = sha256_file(snapshot)
    raw = []
    with closing(sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for seq, review_id, at, body in db.execute(
                "SELECT seq,review_id,at,body FROM review_events ORDER BY seq"):
            row = json.loads(body)
            if row.get("gate") == "tint" and str(row.get("candidate") or "").strip():
                raw.append({**row, "id": review_id, "seq": seq, "at": at})
    if len(raw) != args.expected_count:
        raise SystemExit(f"Snapshot has {len(raw)} nonempty tint candidate events, expected {args.expected_count}.")

    import app
    stops = frozenset(app._TINT_EVAL_STOP)
    vocabulary, passage_count = set(), 0
    for row in raw:
        for chunk in (row.get("context") or {}).get("chunks") or []:
            text = chunk.get("text") if isinstance(chunk, dict) else ""
            if text:
                passage_count += 1
                vocabulary.update(word for word in re.findall(r"[a-z0-9']+", text.lower())
                                  if len(word) > 2 and word not in stops)
    vocabulary = frozenset(vocabulary)
    results = []
    judge_ring_before = copy.deepcopy(app._TINT_JUDGE_RING)
    preview_token = app._REJECTION_LAB_PREVIEW.set(True)
    denied = AssertionError("The offline grader must not invoke models or production review storage")
    try:
        with (mock.patch.object(app, "_crystal_vocab", return_value=vocabulary),
              mock.patch.object(app, "line_review_capture", side_effect=denied),
              mock.patch.object(app._LINE_REVIEW, "evaluate", side_effect=denied),
              mock.patch.object(app, "ask_model", new=mock.AsyncMock(side_effect=denied)),
              mock.patch.object(app, "call_ollama", new=mock.AsyncMock(side_effect=denied))):
            for row in raw:
                source = str(row.get("source") or "")
                candidate = str(row.get("candidate") or "")
                old = row.get("evaluation") or {}
                context = row.get("context") or {}
                strength = old.get("strength")
                strength_assumed = not isinstance(strength, (int, float)) or isinstance(strength, bool)
                if not strength_assumed:
                    strength_assumed = not math.isfinite(strength)
                force = .88 if strength_assumed else float(strength)
                grade = old.get("grade")
                grade_assumed = grade not in ("strict", "meaning")
                strict = grade == "strict"
                kind = str(context.get("kind") or "")
                answering = str(context.get("answering") or "")
                chunks = [chunk for chunk in context.get("chunks") or [] if isinstance(chunk, dict)]
                current = app.tint_evaluate(source, candidate, chunks, answering=answering,
                                            force=force, kind=kind, strict=strict)
                if "machine_ok" not in current or current.get("operator_accepted"):
                    raise AssertionError("Replay must return an unmodified raw machine grade")
                old_ok = old.get("machine_ok") if isinstance(old.get("machine_ok"), bool) else None
                new_ok = bool(current["machine_ok"])
                transition = ("unrecorded_machine" if old_ok is None else
                              "newly_true" if not old_ok and new_ok else
                              "newly_false" if old_ok and not new_ok else
                              "retained_true" if old_ok else "retained_false")
                results.append({"id": row["id"], "seq": row["seq"], "at": row["at"],
                    "pair_sha256": digest(json.dumps([source, candidate], ensure_ascii=False)),
                    "source": source, "candidate": candidate, "kind": kind,
                    "stage": context.get("stage") or "", "technical": bool(row.get("technical")),
                    "force": force, "force_assumed": strength_assumed,
                    "strict": strict, "grade_assumed": grade_assumed,
                    "answering": answering, "answering_present": "answering" in context,
                    "retained_chunk_count": len(chunks), "old_machine_ok": old_ok,
                    "old_effective_ok": old.get("ok"), "old_evaluation": old,
                    "new_machine_ok": new_ok, "new_evaluation": current,
                    "transition": transition, "stored_reasons": row.get("reasons") or []})
    finally:
        app._REJECTION_LAB_PREVIEW.reset(preview_token)
    if app._TINT_JUDGE_RING != judge_ring_before:
        raise AssertionError("Preview grading changed the live-style judge ring")

    pairs = {}
    for row in results:
        pair = pairs.setdefault(row["pair_sha256"], {"latest": row, "seqs": [], "known_old_states": set()})
        pair["latest"] = row
        pair["seqs"].append(row["seq"])
        if row["old_machine_ok"] is not None:
            pair["known_old_states"].add(row["old_machine_ok"])
    latest = [pair["latest"] for pair in pairs.values()]
    newly_passed = [row for row in results if row["transition"] == "newly_true"]
    newly_refused = [row for row in results if row["transition"] == "newly_false"]
    review_pairs = {}
    for row in newly_passed:
        paired = review_pairs.setdefault(row["pair_sha256"], {
            "pair_sha256": row["pair_sha256"], "source": row["source"], "candidate": row["candidate"],
            "all_pair_seqs": pairs[row["pair_sha256"]]["seqs"], "newly_passed_events": [],
            "manual_review_status": "pending", "note": "A deterministic grade transition is not an approval."})
        paired["newly_passed_events"].append({key: row[key] for key in (
            "id", "seq", "kind", "stage", "technical", "force_assumed", "grade_assumed",
            "old_evaluation", "new_evaluation")})
    hashes_after = {name: sha256_file(ROOT / name) for name in source_hashes}
    integrity = {"snapshot_unchanged": sha256_file(snapshot) == snapshot_hash,
                 "source_unchanged_during_replay": source_hashes == hashes_after,
                 "judge_ring_unchanged": app._TINT_JUDGE_RING == judge_ring_before}
    report = {"at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot": str(snapshot), "snapshot_sha256": snapshot_hash,
        "source_sha256": source_hashes, "source_sha256_after": hashes_after, "integrity": integrity,
        "scope": "All 920 retained nonempty gate=tint candidate occurrences in the fixed corpus snapshot.",
        "method": "Actual app.tint_evaluate, with recorded force/grade where available, frozen vocabulary, preview context and forbidden model/review calls. No candidate rewriting, vote, setting change or playback.",
        "vocabulary": {"basis": "Frozen union of retained context.chunks text over all selected occurrences; approximation to the original full live crystal vocabulary.",
                       "words": len(vocabulary), "passage_occurrences": passage_count,
                       "sha256": digest("\n".join(sorted(vocabulary)))},
        "events": {"count": len(results), "comparable_machine_verdicts": sum(row["old_machine_ok"] is not None for row in results),
                   "missing_stored_machine_ok": sum(row["old_machine_ok"] is None for row in results),
                   "transitions": counts(results), "new_machine_passes": sum(row["new_machine_ok"] for row in results),
                   "newly_true_kinds": dict(Counter(row["kind"] for row in newly_passed)),
                   "newly_false_kinds": dict(Counter(row["kind"] for row in newly_refused)),
                   "new_machine_faults": dict(Counter(fault for row in results for fault in row["new_evaluation"]["machine_faults"])),
                   "assumed_force": sum(row["force_assumed"] for row in results),
                   "assumed_meaning_grade": sum(row["grade_assumed"] for row in results),
                   "missing_answering_context": sum(not row["answering_present"] for row in results)},
        "distinct_pairs": {"count": len(pairs), "basis": "Exact source/candidate pair; latest occurrence supplies each pair's summary transition. Occurrence context may differ.",
                           "transitions": counts(latest),
                           "inconsistent_known_stored_machine_verdicts": sum(len(pair["known_old_states"]) > 1 for pair in pairs.values())},
        "limitations": ["Old machine_ok must be an explicit boolean. Missing historical machine verdicts are excluded from all newly_true/newly_false counts; old effective ok is never substituted.",
                        "The retained passage union approximates the original full crystal vocabulary and can affect both name inference and style lexicon evidence.",
                        "Missing strength uses 0.88; missing grade uses meaning. Each assumption is flagged per occurrence and counted.",
                        "Only retained answering context and style chunks are used. Missing preceding speech can change rhyme evidence; no context is invented.",
                        "This is the complete deterministic tint grade, including caller-specific checks, rhyme, transformation and copying. It does not prove real semantic equivalence, complete caller shape, viable audio or permission to publish.",
                        "Technical provenance remains separately flagged; a passing replay does not bypass the original technical refusal or apply an operator decision."],
        "rows": results, "newly_passed_manual_review": list(review_pairs.values())}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("events", "distinct_pairs", "vocabulary", "integrity")}))
    if not all(integrity.values()):
        raise SystemExit("Replay artifacts changed during the run; report is retained but must be repeated against stable inputs.")


if __name__ == "__main__":
    main()
