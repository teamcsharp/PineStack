"""Synthetic full-retention timing: temporary SQLite only, no application IO."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from prompt_learning import PromptLearningStore, _evidence, _json, _outcome


def measured(i):
    kind = ["gallery", "caller", "banter", "news", "sfxguy", "manager"][i % 6]
    return {"attempt_id": f"request-{i}:0", "source": f"The source number {i} stays here.",
        "candidate": f"The number {i} stays near.", "parent": f"Parent {i // 2}", "kind": kind,
        "model": "fixture-model", "profile": "fixture-profile", "prompt_version": 3,
        "grader_version": 6, "contract_version": 1, "learning_revision": 2,
        "strategy_ids": [f"{kind}:{f}:v1" for f in ("quantities", "names", "questions", "rhyme")],
        "stage": "first", "machine_ok": False, "effective_ok": False,
        "semantic_ok": False, "rhyme_ok": False, "faults": ["quantities", "rhyme"]}


def run():
    with tempfile.TemporaryDirectory(prefix="pine-learning-cost-") as temp:
        store = PromptLearningStore(Path(temp) / "learning.sqlite3")
        originals = []
        with store._connect() as db:
            db.execute("BEGIN")
            db.executemany("INSERT INTO prompt_outcomes(attempt_id,at,body) VALUES(?,?,?)",
                [(f"request-{i}:0", float(i), _json(_outcome(measured(i)))) for i in range(4000)])
            for i in range(2000):
                row = measured(i)
                original = {"id": f"review-{i}", "event_seq": i + 1, "source": row["source"],
                    "candidate": row["candidate"], "gate": "tint",
                    "context": {"kind": row["kind"], "script_plain": row["parent"]},
                    "evaluation": {"version": 6, "grade": "meaning", "machine_ok": False,
                        "semantic": {"ok": False, "missing_numbers": [str(i)]},
                        "rhyme": {"required": True, "rap": {"ok": False}}}}
                originals.append(original)
                evidence = _evidence(original)
                db.execute("INSERT INTO prompt_evidence(review_id,event_seq,body) VALUES(?,?,?)",
                           (evidence["review_id"], evidence["event_seq"], _json(evidence)))
            db.commit()
            store._refresh(db)
        store.update(store.settings()["revision"], enabled=True)
        wall, cpu = [], []
        for i in range(4000, 4010):
            start, process = time.perf_counter(), time.process_time()
            store.outcome(measured(i))
            wall.append((time.perf_counter() - start) * 1000)
            cpu.append((time.process_time() - process) * 1000)
        result = {"basis": "Synthetic temporary local SQLite; no app, network, model, vote or playback calls.",
            "source_sha256": hashlib.sha256((ROOT / "prompt_learning.py").read_bytes()).hexdigest(),
            "retained_outcomes": store.status()["outcomes"]["observations"],
            "retained_evidence": store.status()["observation_count"],
            "active_hints": len(store.status()["hints"]),
            "used_strategy_cohorts": len(store.status()["outcomes"]["cohorts"]),
            "times_ms": wall, "cpu_times_ms": cpu, "median_ms": statistics.median(wall),
            "max_ms": max(wall), "median_cpu_ms": statistics.median(cpu)}
        with store._connect() as db:
            db.execute("BEGIN")
            for original in originals:
                evidence = _evidence(original)
                evidence["classifier_version"] = 1
                db.execute("UPDATE prompt_evidence SET body=? WHERE review_id=? AND event_seq=?",
                    (_json(evidence), evidence["review_id"], evidence["event_seq"]))
            db.commit()
        start, process = time.perf_counter(), time.process_time()
        migration = store.reclassify(originals)
        result["bulk_reclassification"] = {"rows": migration["reclassified"],
            "wall_ms": (time.perf_counter() - start) * 1000,
            "cpu_ms": (time.process_time() - process) * 1000,
            "changed_prompt": migration["changed"], "pending": store.status()["classification"]["pending"]}
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
