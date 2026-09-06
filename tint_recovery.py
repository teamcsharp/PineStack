"""Revalidate old rewrite evidence without changing any spoken words or takes."""
import hashlib
import re
from typing import Any, Callable


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def evaluate_legacy(source: str, tinted: str, chunks: list[dict[str, Any]],
                    parse: Callable, evaluate: Callable, *, target: int,
                    force: float, kind: str, world: str = "", floor: int = 2) -> dict:
    """A historical `ok` stamp is evidence to inspect, never a passing grade.

    Candidates retain their original positions for the normal resumable writer.
    That writer reevaluates each candidate against its actual preceding turn.
    Missing passages cannot prove the source-copying or vocabulary contract.
    """
    result = {"state": "repair_required", "why": "", "coverage": {},
              "evaluation": {"ok": False, "turns": []}, "approved_lines": [],
              "progress": {}, "reusable_lines": 0}
    if not source.strip() or not tinted.strip():
        result["why"] = "the original and rewritten text pair is missing"
        return result
    if not chunks or not any(str(c.get("text") or "").strip() for c in chunks):
        result["why"] = "the source passages used by the old rewrite are missing"
        return result
    # The playback parser may normalize a draft (including a truncated tail).
    # Such normalization is not evidence that a rewrite preserved its source.
    raw_before = re.findall(r"(?:^|\s)([ABCDE])\s*:\s*", source, re.I)
    raw_after = re.findall(r"(?:^|\s)([ABCDE])\s*:\s*", tinted, re.I)
    if [m.upper() for m in raw_before] != [m.upper() for m in raw_after]:
        result["why"] = "the old rewrite changed the speaker order or turn count"
        return result
    before = list(parse(source) or []) or [("", source)]
    after = list(parse(tinted) or []) or [("", tinted)]
    if [m for m, _ in before] != [m for m, _ in after]:
        result["why"] = "the old rewrite changed the speaker order or turn count"
        return result
    eligible = [i for i, (_, text) in enumerate(before)
                if len(str(text).strip()) >= floor and re.search(r"[^\W_]", str(text))]
    required = (len(eligible) * target + 99) // 100
    selected = set(eligible[:required])
    coverage = {"target": target, "eligible": len(eligible), "required": required,
                "attempted": 0, "changed": 0, "met": False,
                "version": 2, "strength": round(force, 3)}
    result["coverage"] = coverage
    candidates, reports, approved, answering = [], [], [], ""
    unchanged_outside_selection = True
    for index, ((marker, original), (_, candidate)) in enumerate(zip(before, after)):
        chosen = index in selected
        if chosen:
            grade = evaluate(original, candidate, chunks, answering, force, kind)
            changed = " ".join(original.split()).lower() != " ".join(candidate.split()).lower()
            passed = bool(grade.get("ok") and changed)
            coverage["attempted"] += 1
            coverage["changed"] += int(passed)
            reports.append({"turn": index + 1, **grade})
            if passed:
                approved.append(text_hash(" ".join(candidate.split()).lower()))
                result["reusable_lines"] += 1
        else:
            grade = {"ok": original == candidate}
            unchanged_outside_selection &= original == candidate
            # A future repair must retain the original unselected words.
            candidate = original
        candidates.append({"marker": marker, "source": text_hash(original),
                           "text": candidate, "selected": chosen, "evaluation": grade})
        answering = candidate
    coverage["met"] = bool(coverage["changed"] >= required
                            and all(g.get("ok") for g in reports)
                            and unchanged_outside_selection)
    result["evaluation"] = {"ok": coverage["met"], "turns": reports}
    result["approved_lines"] = approved if coverage["met"] else []
    result["progress"] = {"source": text_hash(source), "world": world,
                          "chunks": chunks, "turns": candidates}
    if coverage["met"]:
        result.update(state="revalidated", why="every selected stored rewrite passed the current evaluator")
    else:
        faults = list(dict.fromkeys(f for g in reports for f in g.get("faults") or []))
        if not unchanged_outside_selection:
            faults.append("unselected words changed")
        result["why"] = "; ".join(faults)[:600] or "selected lines remain unproved"
    return result
