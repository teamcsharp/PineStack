"""Revalidate old rewrite evidence without changing any spoken words or takes."""
import hashlib
import re
from typing import Any, Callable


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", str(text or "").lower())
            if len(w) >= 4}


def align_turns(before: list[tuple[str, str]],
                after: list[tuple[str, str]]
                ) -> tuple[list[tuple[str, str]], int]:
    """2026-09-07: a stored rewrite whose turn order or count differs from
    its original is aligned line by line instead of refused whole.

    Measured: sixteen finished rounds - audio cut, bars on the shelf -
    sat "waiting for tint" behind this one refusal while the operator
    heard records and nothing else; each then cost a whole fresh pass
    on the deep lane. Every original turn takes the unused rewritten
    turn that shares the most content words with it (same speaker
    preferred); an original nothing answers is left empty for the
    resumable writer. Returns the aligned rewrite, in the ORIGINAL order
    and length, and how many rewritten turns answered no original."""
    used: set[int] = set()
    out: list[tuple[str, str]] = []
    for marker, original in before:
        want = _content_words(original)
        best, pick = 0.0, -1
        for j, (m2, cand) in enumerate(after):
            if j in used or not str(cand or "").strip():
                continue
            score = float(len(want & _content_words(cand)))
            if m2 == marker:
                score += 0.5
            if score > best:
                best, pick = score, j
        if pick >= 0 and best >= 1.0:
            used.add(pick)
            out.append((marker, after[pick][1]))
        else:
            out.append((marker, ""))
    unmatched = sum(1 for j, (_m, c) in enumerate(after)
                    if j not in used and str(c or "").strip())
    return out, unmatched


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
    before = list(parse(source) or []) or [("", source)]
    after = list(parse(tinted) or []) or [("", tinted)]
    unmatched = 0
    if ([m.upper() for m in raw_before] != [m.upper() for m in raw_after]
            or [m for m, _ in before] != [m for m, _ in after]):
        # The old rewrite changed the speaker order or turn count: align
        # it to the original line by line and grade what answers what.
        after, unmatched = align_turns(before, after)
    eligible = [i for i, (_, text) in enumerate(before)
                if len(str(text).strip()) >= floor and re.search(r"[^\W_]", str(text))]
    required = (len(eligible) * target + 99) // 100
    selected = set(eligible[:required])
    coverage = {"target": target, "eligible": len(eligible), "required": required,
                "attempted": 0, "changed": 0, "met": False,
                "version": 4, "strength": round(force, 3)}
    result["coverage"] = coverage
    candidates, reports, approved, answering = [], [], [], ""
    unchanged_outside_selection = True
    for index, ((marker, original), (_, candidate)) in enumerate(zip(before, after)):
        chosen = index in selected
        if chosen:
            if str(candidate or "").strip():
                grade = evaluate(original, candidate, chunks, answering, force, kind)
            else:
                grade = {"ok": False, "faults": ["no rewritten line answers this original"]}
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
                            and unchanged_outside_selection
                            and not unmatched)
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
        if unmatched:
            faults.append(f"{unmatched} rewritten turn(s) answer no original line "
                          "(the old rewrite changed the speaker order or turn count)")
        result["why"] = "; ".join(faults)[:600] or "selected lines remain unproved"
    return result
