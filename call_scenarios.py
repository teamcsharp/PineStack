"""Phone-call scenario selection and after-air checks."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any


def load_scenario_catalog(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError, TypeError):
        raw = {}
    if isinstance(raw, list):
        raw = {"scenarios": raw}
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("source", str(path))
    raw.setdefault("scenarios", [])
    return raw


def save_scenario_catalog(path: str | Path, catalog: dict[str, Any]) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(catalog or {}, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)
    return dict(catalog or {})


def select_call_scenario(catalog: dict[str, Any], target_heat: float | None = None) -> dict[str, Any] | None:
    rows = [row for row in (catalog or {}).get("scenarios", []) if isinstance(row, dict)]
    if not rows:
        return None
    if target_heat is None:
        return random.choice(rows)
    target = max(0.0, min(1.0, float(target_heat)))
    return min(rows, key=lambda row: abs(float(row.get("heat") or row.get("intensity") or 0.5) - target))


def call_path_draw(
    scenario: dict[str, Any],
    *,
    caller_name: str = "",
    topic: str = "",
    case_outcome: str = "",
) -> dict[str, Any]:
    return {
        "id": str(scenario.get("id") or scenario.get("name") or "scenario"),
        "name": str(scenario.get("name") or scenario.get("title") or "Scenario"),
        "beats": list(scenario.get("beats") or []),
        "expected_conclusion": str(scenario.get("conclusion") or case_outcome or "")[:500],
        "caller": str(caller_name or "")[:120],
        "topic": str(topic or "")[:700],
        "drawn_at": time.time(),
    }


def call_scenario_clause(plan: dict[str, Any]) -> str:
    if not isinstance(plan, dict):
        raise ValueError("Call scenario is not an object")
    name = str(plan.get("name") or plan.get("id") or "").strip()
    if not name:
        raise ValueError("Call scenario has no name")
    beats = [str(row).strip() for row in (plan.get("beats") or []) if str(row).strip()]
    lines = ["CALL SCENARIO: " + name + "."]
    if plan.get("topic"):
        lines.append("The caller is here about: " + str(plan["topic"])[:500])
    if beats:
        lines.append("Required scenario beats: " + " / ".join(beats[:8]))
    if plan.get("expected_conclusion"):
        lines.append("By the end, land this outcome: "
                     + str(plan["expected_conclusion"])[:500])
    return "\n".join(lines)


def call_conclusion_report(plan: dict[str, Any], script: str, **_: Any) -> dict[str, Any]:
    expected = str((plan or {}).get("expected_conclusion") or "").strip()
    ok = not expected or expected.casefold() in str(script or "").casefold()
    return {"ok": ok, "status": "matched" if ok else "missed",
            "soft_faults": [] if ok else ["expected conclusion was not found"]}


def call_aired_conclusion_report(
    plan: dict[str, Any],
    receipts: list[dict[str, Any]],
    *,
    sid: str = "",
    expected_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expected_ids = {str(row.get("line_id") or "") for row in (expected_lines or [])}
    heard_ids = {str(row.get("line_id") or row.get("id") or "") for row in (receipts or [])}
    if expected_ids and expected_ids <= heard_ids:
        status = "matched"
    elif receipts:
        status = "missed"
    else:
        status = "insufficient_evidence"
    return {"sid": sid, "status": status, "aired_verified": status == "matched",
            "expected": len(expected_ids), "heard": len(heard_ids),
            "soft_faults": [] if status == "matched" else ["not every expected call line was heard"]}
