"""Read-only source/take compatibility of existing current-tint saved rounds.

Import app only with an isolated data directory. The actual data is read from
disk, copied into test globals, and passed to the pure take validator. No model,
TTS, playback, state saves, private scripts or credentials are emitted.
"""
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
actual = Path("/app/data")
isolated = Path(os.environ.get("SPARK_AGENT_DATA_DIR") or "/app/data")
if isolated.resolve() == actual.resolve():
    raise SystemExit("Set an isolated SPARK_AGENT_DATA_DIR before running this audit")

import app


def main():
    shelf = json.loads((actual / "prep_shelf.json").read_text(encoding="utf-8"))
    pantry = json.loads((actual / "pantry.json").read_text(encoding="utf-8"))
    out = {"scope": "take integrity only; live outer eligibility remains authoritative", "kinds": {}}
    with ExitStack() as stack:
        for name, value in {
            "_PANTRY": copy.deepcopy(pantry), "VOICE_MEDIA_DIR": actual / "voice_media",
            "dialogue_row_ready": mock.Mock(return_value=True), "_larder_current": mock.Mock(return_value=True),
            "is_binned": mock.Mock(return_value=False), "station_name_scrub": mock.Mock(side_effect=lambda text: text),
        }.items():
            stack.enter_context(mock.patch.object(app, name, value))
        for name in ("voice_render_any", "session_voices", "freshen_script", "crystal_tint", "ask_model"):
            stack.enter_context(mock.patch.object(app, name, mock.AsyncMock(
                side_effect=AssertionError("No production work in compatibility audit"))))
        for kind in ("gallery", "manager"):
            rows = []
            for row in shelf.get(kind, []):
                entry = row.get("entry") or {}
                coverage = (entry.get("tint") or {}).get("coverage") or {}
                takes = entry.get("takes") or []
                if (int(coverage.get("version") or 0) != 4 or not coverage.get("met")
                        or not entry.get("prepared") or not takes
                        or row.get("off_brief") or entry.get("off_brief")
                        or not all(t.get("key") in pantry for t in takes)):
                    continue
                before = copy.deepcopy(row)
                valid = app._ready_round_takes(kind, row)
                assert row == before, "Validation mutated a copied inventory row"
                rows.append({"sid": row.get("sid"), "take_positions": len(takes),
                             "unique_audio_keys": len({t.get("key") for t in takes}),
                             "validated_positions": len(valid),
                             "saved_duration_seconds": round(sum(float(t.get("seconds") or 0) for t in valid), 2)})
            out["kinds"][kind] = {"candidates": len(rows),
                                  "fully_validated": sum(r["take_positions"] == r["validated_positions"] for r in rows),
                                  "validated_positions": sum(r["validated_positions"] for r in rows),
                                  "saved_duration_seconds": round(sum(r["saved_duration_seconds"] for r in rows), 2),
                                  "rows": rows}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
