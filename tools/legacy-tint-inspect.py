"""Read-only evaluation of persisted tint evidence, in an isolated app import."""
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

data = Path(os.environ.get("SPARK_AGENT_DATA_DIR", "/app/data"))
os.environ["SPARK_AGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="pinebox-tint-inspect-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

settings = json.loads((data / "settings.json").read_text())
app.load_settings = lambda: settings
app.crystals_read = lambda: json.loads((data / "crystals.json").read_text())
report = {"force": app.crystal_force(), "target": app.crystal_coverage_target()}
groups = json.loads((data / "prep_shelf.json").read_text())
groups["larder"] = json.loads((data / "larder.json").read_text())
for kind, rows in groups.items():
    selected_kinds = [value for value in sys.argv[1:] if not value.startswith("--")]
    if selected_kinds and kind not in selected_kinds:
        continue
    counts, faults, examples = Counter(), Counter(), []
    for row in rows:
        entry = row.get("entry") or row
        tint = entry.get("tint") or {}
        counts["rows"] += 1
        counts["tinting"] += bool(entry.get("tinting"))
        counts["preparing"] += bool(entry.get("preparing"))
        counts["tint_ok"] += bool(tint.get("ok"))
        counts["has_chunks"] += bool(tint.get("chunks"))
        plain = str(entry.get("script_plain") or entry.get("text_plain") or "").strip()
        made = str(entry.get("script_tinted") or entry.get("text") or "").strip()
        counts["has_pair"] += bool(plain and made)
        if not (plain and made):
            continue
        source = app.banter_turns(plain) or [("", plain)]
        dest = app.banter_turns(made) or [("", made)]
        if [m for m, _ in source] != [m for m, _ in dest]:
            counts["structure_mismatch"] += 1
            continue
        okay, answering = True, ""
        for (marker, before), (_, after) in zip(source, dest):
            evaluation = app.tint_evaluate(before, after, tint.get("chunks") or [], answering,
                                           app.crystal_force(), "banter" if kind == "larder" else kind)
            counts["lines"] += 1
            counts["passed_lines"] += bool(evaluation.get("ok"))
            faults.update(evaluation.get("faults") or [])
            okay = okay and bool(evaluation.get("ok"))
            answering = after
            if "--summary" not in sys.argv and len(examples) < 2:
                examples.append({"before": before[:250], "after": after[:400],
                                 "evaluation": evaluation, "tint_fields": list(tint),
                                 "chunk_fields": [list(c) for c in (tint.get("chunks") or [])[:1]]})
        counts["all_lines_pass"] += okay
    report[kind] = {"counts": dict(counts), "faults": dict(faults), "examples": examples}
print(json.dumps(report, ensure_ascii=False, indent=2))
