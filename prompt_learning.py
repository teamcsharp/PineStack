"""Auditable, deterministic prompt hints from distinct observed failures.

This module never calls a model or grades dialogue. Its bounded recipes reinforce
existing requirements and are compared using externally measured outcomes.
Acceptance mode is stored for the separate acceptance helper. Full original
evidence stays in the occurrence-pinned review journal.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path


class PromptLearningConflictError(ValueError):
    pass


WINDOW = 2000
SUPPORTED_KINDS = ("", "banter", "caller", "gallery", "news", "manager", "ad",
                   "track_talk", "sfxguy", "station_id", "reply", "continuity")
MAX_ACTIVE = len(SUPPORTED_KINDS) * 4
MAX_PER_KIND = 4
MAX_EVIDENCE = 12
CATALOG_VERSION = 2
CLASSIFIER_VERSION = 2
CATALOG = {
    "quantities": "Keep every source quantity and unit exact; do not add a number to complete a rhyme.",
    "names": "Retain the source's named people and places. Build the rhyme around their names without assigning them new actions.",
    "negation": "Keep each refusal, prohibition and negation attached to the same action and person.",
    "questions": "Keep questions as questions with the same tense, subject and scope; do not supply an invented answer.",
    "caller_structure": "Keep every caller and host turn in its original position, with the same conversational purpose and speaker.",
    "copying": "Use the style sample's cadence and individual words without copying its phrases into the dialogue.",
    "rhyme": "Recast the existing idea into short bars with clearly rhyming final words; keep its facts intact.",
    "added_tail": "Recast the original syntax and verbs; do not keep the whole sentence and append a new rhyming claim.",
    "anchors": "Keep the original concrete topic and relationships visible while changing the wording; vague imagery cannot replace the source's point.",
    "cadence": "Change the cadence using the source's existing intent, rather than adding objects, events or conclusions for style.",
}

# Bounded alternative procedures, never facts copied from a failed example.
RECIPES = {
    "quantities": ("List the exact quantities and units first. Put each unchanged in a bar; rhyme other words around them.",
                   "Draft the bars around the original quantity phrases. Compare each number and unit to the source before returning."),
    "names": ("Keep the original name phrases in place. Rewrite their surrounding verbs without moving actions between people.",
              "Map each named subject to its original action, then build rhyming bars from those same pairs."),
    "negation": ("Identify who refuses or denies which action. Keep that exact negative relationship in both the draft and final bars.",
                 "Draft a faithful negative statement first. Change word order for rhyme; do not reverse or transfer its denial."),
    "questions": ("Write the same question in plain words first. Preserve its subject and tense while moving only wording needed for rhyme.",
                  "Keep the question unanswered. Check its tense, requested information and scope against the original after rhyming."),
    "caller_structure": ("Assign every retained turn its speaker and purpose before rewriting. Change words within each turn only.",
                         "Check the caller/host sequence and each question-answer role after drafting; restore any missing original turn."),
    "copying": ("Use the style example only for rhythm. Draft from the source facts, then remove any borrowed multiword phrase.",
                "Choose ordinary source-grounded words for the same cadence; compare the final draft with the style sample for copied phrases."),
    "rhyme": ("Choose two different, clearly rhyming end words that fit the existing idea. Build short bars backward without adding facts.",
              "Draft a faithful two-bar paraphrase, then replace only the endings to make a clear rhyme. Recheck every claim against the source."),
    "added_tail": ("Replace the original sentence structure before adding a second bar. Both bars must express only the source's existing intent.",
                   "Delete any invented rhyming conclusion. Split the original proposition into two faithful clauses and rhyme those clauses."),
    "anchors": ("List the source's concrete subject, action and relationship. Make those same elements explicit in the rewritten bars.",
                "Build each bar from an original clause. Compare who did what, to whom, where and when; remove unsupported imagery."),
    "cadence": ("Divide the existing thought into short spoken clauses. Move the source's own words before adding any stylistic vocabulary.",
                "Change stress and clause order using only the original intent; do not lengthen the thought with a new event or object."),
}
OUTCOME_WINDOW = 4000
MIN_OUTCOME_SOURCES = 8


def _outcome(row):
    if not isinstance(row, dict):
        raise ValueError("outcome must be an object")
    if row.get("technical") or row.get("deferred") or row.get("preview") or row.get("regrade") or row.get("imported"):
        return None
    identity = str(row.get("attempt_id") or "").strip()
    if not identity or len(identity) > 240:
        raise ValueError("outcome needs a stable attempt_id")
    for key in ("source", "parent"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError("outcome needs " + key)
    for key in ("machine_ok", "effective_ok", "semantic_ok", "rhyme_ok"):
        if not isinstance(row.get(key), bool):
            raise ValueError("outcome needs measured " + key)
    kind = str(row.get("kind") or "")
    if kind not in SUPPORTED_KINDS:
        return None
    words = len(row["source"].split())
    band = "short" if words <= 12 else "medium" if words <= 40 else "long"
    strategies = row.get("strategy_ids") or []
    if not isinstance(strategies, list) or len(strategies) > MAX_PER_KIND:
        raise ValueError("outcome strategies must be the bounded used selection")
    allowed = {kind + ":" + pattern + ":v" + str(v) for pattern in CATALOG for v in (1, 2, 3)}
    if any(not isinstance(s, str) or s not in allowed for s in strategies):
        raise ValueError("outcome has an unknown or differently scoped strategy")
    faults = row.get("faults") or []
    if not isinstance(faults, list) or any(f not in CATALOG for f in faults):
        raise ValueError("outcome faults must be measured catalog families")
    stage = str(row.get("stage") or "first")
    if stage not in ("first", "repair"):
        raise ValueError("outcome stage must be first or repair")
    prior = str(row.get("prior_attempt_id") or "")
    if prior == identity:
        raise ValueError("outcome cannot repair itself")
    candidate_hash = str(row.get("candidate_hash") or "")
    if not candidate_hash:
        if not isinstance(row.get("candidate"), str):
            raise ValueError("outcome needs candidate or candidate_hash")
        candidate_hash = _hash(row["candidate"])
    if not re.fullmatch(r"[a-f0-9]{64}", candidate_hash):
        raise ValueError("candidate_hash must be SHA256")
    representations = row.get("parent_representations") or {}
    if (not isinstance(representations, dict) or set(representations) - {"speaker_turns"} or
            any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
                for value in representations.values())):
        raise ValueError("parent representations must be exact known source hashes")
    return {"attempt_id": identity, "source_hash": _hash(row["source"]),
        "candidate_hash": candidate_hash,
        "parent_hash": _hash(row["parent"]), "kind": kind, "source_length_band": band,
        "prompt_version": row.get("prompt_version"), "grader_version": row.get("grader_version"),
        "contract_version": row.get("contract_version"), "profile": str(row.get("profile") or ""),
        "model": str(row.get("model") or ""), "learning_revision": row.get("learning_revision"),
        "strategy_ids": list(dict.fromkeys(strategies)), "stage": stage,
        "prior_attempt_id": prior, "faults": sorted(set(faults)),
        **({"parent_representations": dict(representations)} if representations else {}),
        **{key: row[key] for key in ("machine_ok", "effective_ok", "semantic_ok", "rhyme_ok")}}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(" ".join(str(value or "").split()).encode("utf-8")).hexdigest()


def _integer(value, name, minimum=1, maximum=2**63 - 1):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(name + " must be an integer in range")
    return value


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _parent(context):
    entry = _mapping(context.get("entry"))
    for value in (context.get("script_plain"), context.get("source_script"),
                  context.get("original_script"), entry.get("script_plain")):
        if isinstance(value, str) and value.strip():
            return _hash(value)
    turns = context.get("turns")
    if isinstance(turns, (list, tuple)) and turns and all(
            isinstance(row, (list, tuple)) and len(row) == 2 and
            isinstance(row[0], str) and isinstance(row[1], str) for row in turns):
        return _hash("\n".join(marker + ": " + source for marker, source in turns))
    return ""


def _patterns(report):
    semantic = _mapping(report.get("semantic"))
    transformation = _mapping(report.get("transformation"))
    rhyme = _mapping(report.get("rhyme"))
    copying = _mapping(report.get("copying"))
    caller = _mapping(semantic.get("call_contract") or report.get("call_contract"))
    found = set()
    if semantic.get("missing_numbers") or semantic.get("added_numbers"):
        found.add("quantities")
    if semantic.get("missing_names"):
        found.add("names")
    if semantic.get("negation") is False:
        found.add("negation")
    if semantic.get("question") is False:
        found.add("questions")
    if caller.get("ok") is False and caller.get("faults"):
        found.add("caller_structure")
    if copying.get("ok") is False and copying.get("phrases"):
        found.add("copying")
    rap = _mapping(rhyme.get("rap"))
    # Meaning-grade uses actual bar evidence; its spelling-rhyme report is
    # advisory. Strict grade retains its spelling check, and fluid always
    # requires the actual bar proof too. Older reports may lack nested rap.
    required_rhyme = (rhyme.get("ok") if report.get("grade") == "strict" or "ok" not in rap
                      else rap.get("ok"))
    if _mapping(report.get("editorial")).get("mode") == "fluid" and rap.get("ok") is False:
        required_rhyme = False
    if rhyme.get("required") is True and required_rhyme is False:
        found.add("rhyme")
    if transformation.get("unchanged_proposition_with_added_tail") is True:
        found.add("added_tail")
    if semantic.get("ok") is False and semantic.get("missing"):
        found.add("anchors")
    if (semantic.get("contrast") is False and
            isinstance(semantic.get("unsupported_positive_contrasts"), (list, tuple)) and
            any(isinstance(item, dict) and item for item in semantic["unsupported_positive_contrasts"])):
        found.add("anchors")
    guard_evidence = _mapping(report.get("editorial")).get("guard_evidence")
    if isinstance(guard_evidence, (list, tuple)) and any(
            _mapping(item).get("code") in {"attempt_became_asserted_action", "source_needs_repair"}
            for item in guard_evidence):
        found.add("anchors")
    if transformation.get("ok") is False and transformation.get("cadence_changed") is False:
        found.add("cadence")
    return [key for key in CATALOG if key in found]


def _evidence(row):
    if not isinstance(row, dict):
        raise ValueError("review evidence must be an object")
    review_id = str(row.get("id") or row.get("review_id") or "")
    if not review_id or len(review_id) > 200:
        raise ValueError("review evidence needs its exact review ID")
    event_seq = _integer(row.get("event_seq") or row.get("latest_seq"), "event_seq")
    context = _mapping(row.get("context"))
    kind = str(context.get("kind") or "")[:100]
    report = _mapping(row.get("evaluation"))
    report = _mapping(report.get("tint")) or report
    source, candidate = row.get("source"), row.get("candidate")
    parent = _parent(context)
    reason = ""
    if row.get("technical"):
        reason = "technical"
    elif row.get("gate") != "tint":
        reason = "unsupported_gate"
    elif not isinstance(source, str) or not source.strip() or not isinstance(candidate, str) or not candidate.strip():
        reason = "missing_words"
    elif not isinstance(report.get("version"), (int, float)) or isinstance(report.get("version"), bool) or report["version"] < 5:
        reason = "old_or_unknown_grader"
    elif report.get("machine_ok") is not False:
        reason = "no_verified_machine_failure"
    elif not parent:
        reason = "unknown_parent"
    patterns = _patterns(report) if not reason else []
    if not reason and not patterns:
        reason = "no_specific_pattern"
    return {"review_id": review_id, "event_seq": event_seq, "kind": kind,
            "source_hash": _hash(source), "candidate_hash": _hash(candidate),
            "parent_hash": parent, "patterns": patterns, "excluded": reason,
            "grader_version": report.get("version"), "gate": str(row.get("gate") or ""),
            "classifier_version": CLASSIFIER_VERSION}


class PromptLearningStore:
    """Occurrence-idempotent evidence, cached guidance and immutable revisions.

    Three distinct sources across at least two known original parent scripts
    activate a fixed hint. Repeated attempts of one source never add votes.
    Explicit individual approvals exclude that source from automatic support;
    kept rejections confirm it. Batch approvals and free-text notes do not train.
    """
    def __init__(self, path, *, now=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or time.time
        self._lock = threading.RLock()
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS prompt_evidence (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL,
                    event_seq INTEGER NOT NULL, body TEXT NOT NULL, UNIQUE(review_id,event_seq));
                CREATE TABLE IF NOT EXISTS prompt_decisions (
                    source_key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS prompt_outcomes (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL UNIQUE,
                    at REAL NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS prompt_recipes (
                    hint_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS prompt_classifications (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL,
                    event_seq INTEGER NOT NULL, at REAL NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS prompt_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS prompt_revisions (
                    revision INTEGER PRIMARY KEY, body TEXT NOT NULL);
            """)
            stamp = self._stamp()
            initial = {"revision": 1, "enabled": False, "mode": "strict", "automation_paused": False,
                       "updated_at": stamp, "hints": [], "catalog_version": CATALOG_VERSION}
            db.execute("INSERT OR IGNORE INTO prompt_state VALUES(1,?)", (_json(initial),))
            db.execute("INSERT OR IGNORE INTO prompt_revisions VALUES(1,?)", (_json({
                "revision": 1, "at": stamp, "reason": "initialized_disabled", "before": None,
                "after": initial, "evidence": []}),))
            self._refresh(db)

    def _connect(self):
        db = sqlite3.connect(str(self.path), isolation_level=None, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def _stamp(self):
        stamp = float(self._now())
        if not math.isfinite(stamp):
            raise ValueError("clock must return a finite timestamp")
        return stamp

    def _load_state(self, db):
        return json.loads(db.execute("SELECT body FROM prompt_state WHERE singleton=1").fetchone()[0])

    def _decoded_rows(self, db, query, limit, attribute):
        """Reuse JSON decoding only after comparing every current database body.

        The bounded SQL snapshot remains authoritative, including after another
        connection changes a row or a transaction rolls back. Cached objects are
        treated as immutable by the aggregation routines.
        """
        old = getattr(self, attribute, {})
        current, result = {}, []
        for row in db.execute(query, (limit,)):
            cached = old.get(row["seq"])
            decoded = cached[1] if cached and cached[0] == row["body"] else json.loads(row["body"])
            current[row["seq"]] = (row["body"], decoded)
            result.append(decoded)
        setattr(self, attribute, current)
        return result

    def _summarize(self, db):
        observations = self._decoded_rows(db,
            "SELECT seq,body FROM prompt_evidence ORDER BY event_seq DESC,seq DESC LIMIT ?",
            WINDOW, "_evidence_decode_cache")
        decisions = {row[0]: json.loads(row[1]) for row in db.execute("SELECT source_key,body FROM prompt_decisions")}
        groups, excluded, latest_sources = {}, {}, set()
        for row in observations:
            key = row["kind"] + ":" + row["source_hash"]
            # A later candidate's changed fault families replace older ones;
            # previous failed attempts must not permanently vote for a fixed bug.
            if key in latest_sources:
                continue
            latest_sources.add(key)
            decision = decisions.get(key) or {}
            reason = row["excluded"] or ("operator_allowed" if decision.get("action") == "allow" else "")
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
                continue
            for pattern in row["patterns"]:
                group = groups.setdefault((row["kind"], pattern), {})
                # Latest immutable occurrence represents this source. Repeated
                # candidates/IDs/events never multiply its support.
                group.setdefault(row["source_hash"], {**row, "confirmed": decision.get("action") == "keep"})
        results = []
        for (kind, pattern), sources in groups.items():
            rows = list(sources.values())
            parents = len({row["parent_hash"] for row in rows})
            results.append({"id": kind + ":" + pattern, "kind": kind, "pattern": pattern,
                "text": CATALOG[pattern], "sources": len(rows), "parents": parents,
                "operator_confirmed": sum(bool(row["confirmed"]) for row in rows),
                "eligible": len(rows) >= 3 and parents >= 2,
                "evidence": [{key: row[key] for key in ("review_id", "event_seq", "source_hash", "parent_hash")}
                             for row in rows[:MAX_EVIDENCE]],
                "evidence_omitted": max(0, len(rows) - MAX_EVIDENCE)})
        results.sort(key=lambda row: (list(CATALOG).index(row["pattern"]), -row["operator_confirmed"],
                                      -row["sources"], row["kind"]))
        return results, excluded, len(observations)

    def _choose(self, state, patterns):
        eligible = [r for r in patterns if r["eligible"] and r["kind"] in SUPPORTED_KINDS]
        old_ids = {r["id"] for r in state["hints"]}
        result = []
        for kind in SUPPORTED_KINDS:
            candidates = [r for r in eligible if r["kind"] == kind]
            def score(row):
                # A modest incumbent margin avoids revision churn on a single
                # extra observation while allowing stronger current evidence in.
                severity = 1.3 if row["pattern"] in ("quantities", "names", "negation", "questions", "caller_structure", "copying", "anchors") else 1.0
                value = severity * row["sources"] + 2 * row["parents"] + 8 * row["operator_confirmed"]
                return value * (1.2 if row["id"] in old_ids else 1.0)
            candidates.sort(key=lambda r: (-score(r), list(CATALOG).index(r["pattern"])))
            selected = candidates[:MAX_PER_KIND]
            # Ordering itself is not a learned change; use a stable catalog order.
            selected.sort(key=lambda r: list(CATALOG).index(r["pattern"]))
            for row in selected:
                hint = copy.deepcopy(row)
                incumbent = next((r for r in state["hints"] if r["id"] == row["id"]), None)
                historic = getattr(self, "_recipe_history", {}).get(row["id"])
                if historic and (not incumbent or historic.get("recipe_version", 1) >= incumbent.get("recipe_version", 1)):
                    incumbent = historic
                recipe = self._recipe(hint, incumbent)
                hint.update(recipe)
                result.append(hint)
        return result

    def _outcomes(self, db):
        rows = self._decoded_rows(db, "SELECT seq,body FROM prompt_outcomes ORDER BY seq DESC LIMIT ?",
                                  OUTCOME_WINDOW, "_outcome_decode_cache")
        by_id = {r["attempt_id"]: r for r in rows}
        def totals(items):
            count = len(items)
            values = {"attempts": count, "raw_passes": sum(r["machine_ok"] for r in items),
                "effective_passes": sum(r["effective_ok"] for r in items),
                "semantic_failures": sum(not r["semantic_ok"] for r in items),
                "rhyme_failures": sum(not r["rhyme_ok"] for r in items),
                "without_strategy": sum(not r["strategy_ids"] for r in items)}
            values["raw_failures"] = count - values["raw_passes"]
            values["effective_failures"] = count - values["effective_passes"]
            return values
        groups, ignored, linked, cohort_labels = {}, {}, 0, {}
        for row in rows:
            comparable = (bool(row["model"]) and row["model"].lower() != "unknown"
                and bool(row["profile"]) and bool(row["prompt_version"])
                and isinstance(row["grader_version"], (int, float)) and row["grader_version"] >= 5
                and bool(row["contract_version"]))
            if not comparable:
                ignored["unknown_context"] = ignored.get("unknown_context", 0) + 1
            prior = by_id.get(row["prior_attempt_id"])
            is_linked = bool(prior and prior["source_hash"] == row["source_hash"]
                and prior["parent_hash"] == row["parent_hash"] and prior["kind"] == row["kind"])
            prior_comparable = bool(is_linked and all(prior[k] == row[k] for k in (
                "model", "profile", "prompt_version", "grader_version", "contract_version", "source_length_band")))
            linked += int(is_linked)
            context = tuple(row[k] for k in ("kind", "model", "profile", "prompt_version",
                                             "grader_version", "contract_version", "source_length_band", "stage"))
            try:
                cohort = cohort_labels.get(context)
                if cohort is None:
                    cohort = cohort_labels[context] = _json(context)
            except TypeError:  # malformed version metadata remains visible, not cached
                cohort = _json(context)
            exposure = {**row, "linked": is_linked, "prior_comparable": prior_comparable,
                        "prior_faults": list(prior["faults"]) if is_linked else []}
            for strategy in row["strategy_ids"]:
                group = groups.setdefault((cohort, strategy), {"rows": {}, "cohort": cohort,
                    "strategy_id": strategy, "comparable": comparable, "kind": row["kind"],
                    "model": row["model"], "profile": row["profile"], "prompt_version": row["prompt_version"],
                    "grader_version": row["grader_version"], "contract_version": row["contract_version"],
                    "source_length_band": row["source_length_band"], "stage": row["stage"]})
                # Latest observed exposure per distinct source in this cohort;
                # retry volume cannot disguise repeated failures as new data.
                group["rows"].setdefault(row["source_hash"], exposure)
        cohorts = []
        for group in groups.values():
            exposure = list(group.pop("rows").values())
            n = len(exposure)
            family = group["strategy_id"].rsplit(":", 2)[-2]
            counts = {"raw_passes": sum(r["machine_ok"] for r in exposure),
                "effective_passes": sum(r["effective_ok"] for r in exposure),
                "semantic_failures": sum(not r["semantic_ok"] for r in exposure),
                "rhyme_failures": sum(not r["rhyme_ok"] for r in exposure),
                "target_failures": sum(family in r["faults"] for r in exposure),
                "first_attempts": sum(r["stage"] == "first" for r in exposure),
                "repairs": sum(r["stage"] == "repair" for r in exposure),
                "linked_repairs": sum(r["stage"] == "repair" and r["linked"] for r in exposure)}
            pairs = [r for r in exposure if r["stage"] == "repair" and r["prior_comparable"]
                     and family in r["prior_faults"]]
            resolved = sum(family not in r["faults"] for r in pairs)
            cohorts.append({**group, "sources": n, "parents": len({r["parent_hash"] for r in exposure}),
                **counts, "rates": {k: round(v / n, 4) for k, v in counts.items() if k.endswith(("passes", "failures"))},
                "same_family_repairs": {"pairs": len(pairs), "resolved": resolved,
                    "rate": round(resolved / len(pairs), 4) if pairs else None},
                "attempt_ids": [r["attempt_id"] for r in exposure[:MAX_EVIDENCE]]})
        return {"observations": len(rows), "limit": OUTCOME_WINDOW, "linked_repairs": linked,
                "lineage_boundaries": {"count": sum(bool(r.get("lineage_boundary")) for r in rows),
                    "items": [{"attempt_id": r["attempt_id"], "prior_attempt_id": r["prior_attempt_id"],
                               **r["lineage_boundary"]} for r in rows if r.get("lineage_boundary")][:MAX_EVIDENCE]},
                "measured_attempts": {"all": totals(rows),
                    "first": totals([r for r in rows if r["stage"] == "first"]),
                    "repair": totals([r for r in rows if r["stage"] == "repair"])},
                "excluded": ignored, "cohorts": cohorts[:240],
                "basis": "Distinct-source measured attempts in matched model/profile/version/length cohorts. Observational rates are not causal proof or acoustic proof."}

    def _recipe(self, hint, incumbent=None):
        base_id = hint["id"]
        incumbent = incumbent or hint
        if incumbent.get("phase") == "exhausted":
            return {k: copy.deepcopy(incumbent[k]) for k in (
                "strategy_id", "recipe_version", "phase", "recipe_reason", "text", "outcome_cohort")}
        cohorts = getattr(self, "_outcome_status", {}).get("cohorts", [])
        # The latest observed comparable context drives this kind's recipe;
        # old models, contracts and profiles cannot vote against a new one.
        relevant = [r for r in cohorts if r["comparable"] and r["strategy_id"].startswith(base_id + ":v")]
        pinned = (incumbent.get("outcome_cohort")
                  if int(incumbent.get("recipe_version") or 1) > 1 else None)
        latest = pinned or (relevant[0]["cohort"] if relevant else None)
        matched = {r["strategy_id"]: r for r in relevant if r["cohort"] == latest}
        version, phase, reason = 1, "baseline", "Collecting comparable outcomes."
        baseline = matched.get(base_id + ":v1")
        enough = lambda r: bool(r and r["sources"] >= MIN_OUTCOME_SOURCES and r["parents"] >= 2)
        if pinned and not enough(baseline):
            # A new model/profile/length/stage or retention rollover is not
            # evidence that an old failed recipe should start again.
            return {k: copy.deepcopy(incumbent[k]) for k in (
                "strategy_id", "recipe_version", "phase", "recipe_reason", "text", "outcome_cohort")}
        if enough(baseline) and baseline["rates"]["target_failures"] >= .75:
            for trial in (2, 3):
                version, phase, reason = trial, "exploring", "Persistent matched-cohort failures justify testing this recipe; improvement is unproven."
                measured = matched.get(base_id + ":v" + str(trial))
                if not enough(measured):
                    break
                rates, before = measured["rates"], baseline["rates"]
                improved = (rates["target_failures"] <= before["target_failures"] - .15
                    and rates["effective_passes"] > before["effective_passes"]
                    and rates["semantic_failures"] <= before["semantic_failures"]
                    and rates["rhyme_failures"] <= before["rhyme_failures"])
                if improved:
                    phase, reason = "supported", "Matched observations improved without a higher factual or rhyme failure rate; not causal proof."
                    break
                if measured["sources"] < 16 and rates["target_failures"] < .75:
                    break
                if trial == 3:
                    phase, reason = "exhausted", "All bounded recipes failed to establish improvement. Base factual and rhyme requirements remain active."
        text = CATALOG[hint["pattern"]] if version == 1 else RECIPES[hint["pattern"]][version - 2]
        return {"strategy_id": base_id + ":v" + str(version), "recipe_version": version,
                "phase": phase, "recipe_reason": reason, "text": "" if phase == "exhausted" else text,
                "outcome_cohort": latest}

    def _revise(self, db, state, reason, *, after=None, patterns=None, trigger=None, aggregates=None):
        self._outcome_status = self._outcomes(db)
        if aggregates is not None:
            aggregates["outcomes"] = self._outcome_status
        self._recipe_history = {r[0]: json.loads(r[1]) for r in db.execute("SELECT hint_id,body FROM prompt_recipes")}
        next_state = copy.deepcopy(after or state)
        if next_state["enabled"] and not next_state["automation_paused"]:
            if patterns is None:
                summary = self._summarize(db)
                patterns = summary[0]
                if aggregates is not None:
                    aggregates["summary"] = summary
            next_state["hints"] = self._choose(next_state, patterns)
            for hint in next_state["hints"]:
                db.execute("INSERT INTO prompt_recipes VALUES(?,?) ON CONFLICT(hint_id) DO UPDATE SET body=excluded.body",
                           (hint["id"], _json(hint)))
        fields = ("enabled", "mode", "automation_paused")
        if (all(next_state[key] == state[key] for key in fields) and
                [(r["id"], r["text"]) for r in next_state["hints"]] == [(r["id"], r["text"]) for r in state["hints"]]):
            return False
        next_state.update(revision=state["revision"] + 1, updated_at=self._stamp(), catalog_version=CATALOG_VERSION)
        revision = {"revision": next_state["revision"], "at": next_state["updated_at"], "reason": reason,
                    "before": state, "after": next_state,
                    "trigger": copy.deepcopy(trigger or {}),
                    "evidence": [ref for hint in next_state["hints"] for ref in hint["evidence"]][:MAX_ACTIVE * MAX_EVIDENCE]}
        db.execute("INSERT INTO prompt_revisions VALUES(?,?)", (next_state["revision"], _json(revision)))
        db.execute("UPDATE prompt_state SET body=? WHERE singleton=1", (_json(next_state),))
        return True

    def _refresh(self, db, *, aggregates=None):
        self._state = self._load_state(db)
        # A mutation can share its own already-computed aggregates after commit.
        # Nothing survives into the next transaction as an unvalidated cache.
        aggregates = aggregates or {}
        self._outcome_status = aggregates["outcomes"] if "outcomes" in aggregates else self._outcomes(db)
        self._recipe_history = {r[0]: json.loads(r[1]) for r in db.execute("SELECT hint_id,body FROM prompt_recipes")}
        patterns, excluded, observations = aggregates["summary"] if "summary" in aggregates else self._summarize(db)
        visible = copy.deepcopy(self._state)
        if visible["enabled"] and not visible["automation_paused"]:
            for hint in visible["hints"]:
                recipe = self._recipe(hint)
                if recipe["strategy_id"] == hint.get("strategy_id") and recipe["text"] == hint["text"]:
                    hint.update(recipe)  # outcome confidence can change without changing the prompt
        self._status = {**visible, "patterns": patterns[:80], "excluded": excluded,
                       "observation_count": observations, "observation_limit": WINDOW,
                       "classification": {"version": CLASSIFIER_VERSION,
                           "pending": db.execute("SELECT COUNT(*) FROM prompt_evidence WHERE COALESCE(json_extract(body,'$.classifier_version'),1) < ?", (CLASSIFIER_VERSION,)).fetchone()[0],
                           "migrations": db.execute("SELECT COUNT(*) FROM prompt_classifications").fetchone()[0]},
                       "outcomes": copy.deepcopy(self._outcome_status),
                       "recipe_history": [{k: copy.deepcopy(r.get(k)) for k in (
                           "id", "strategy_id", "recipe_version", "phase", "recipe_reason", "outcome_cohort")}
                           for r in self._recipe_history.values()],
                       "basis": "Distinct source failures across known original scripts; observed machine checks, not proof of semantic correctness. Individual decisions count; batch approvals do not train.",
                       "requirements": {"distinct_sources": 3, "distinct_parents": 2,
                                        "max_hints_per_kind": MAX_PER_KIND, "max_active_hints": MAX_ACTIVE},
                       "say": "Automatic changes are paused after rollback." if self._state["automation_paused"] else
                              "Automatic prompt hints are enabled." if self._state["enabled"] else "Automatic prompt hints are disabled."}

    def settings(self):
        with self._lock:
            return {key: copy.deepcopy(value) for key, value in self._state.items() if key != "hints"}

    def status(self):
        with self._lock:
            return copy.deepcopy(self._status)

    def selection(self, kind=""):
        with self._lock:
            if not self._state["enabled"]:
                return {"guidance": "", "strategy_ids": [], "learning_revision": self._state["revision"]}
            own = [row for row in self._state["hints"] if row["kind"] == str(kind or "")]
            hints = [row for row in own if row.get("text")][:MAX_PER_KIND]
            if not hints:
                return {"guidance": "", "strategy_ids": [], "learning_revision": self._state["revision"]}
            header = ("OBSERVED REWRITE LESSONS (learning revision " + str(self._state["revision"]) +
                    "). These evidence-guided recipes do not relax meaning, rhyme, speaker or technical requirements:\n" +
                    "")
            lines, ids = [], []
            for row in hints:
                line = "- " + row["text"]
                if len(header) + sum(len(s) + 1 for s in lines) + len(line) > 1000:
                    break
                lines.append(line)
                ids.append(row.get("strategy_id") or row["id"] + ":v1")
            return {"guidance": header + "\n".join(lines), "strategy_ids": ids,
                    "learning_revision": self._state["revision"]}

    def guidance(self, kind=""):
        return self.selection(kind)["guidance"]

    def pending_reclassifications(self, limit=2000):
        """Exact references for a caller to reload from the immutable journal.

        This reads all retained evidence, newest first, in bounded batches.
        Supplying those pinned rows to observe() removes completed references;
        unavailable originals stay pending rather than being guessed or erased.
        """
        _integer(limit, "limit", 1, 2000)
        with self._lock, closing(self._connect()) as db:
            return [dict(r) for r in db.execute(
                "SELECT review_id,event_seq,COALESCE(json_extract(body,'$.classifier_version'),1) AS classifier_version "
                "FROM prompt_evidence WHERE COALESCE(json_extract(body,'$.classifier_version'),1) < ? "
                "ORDER BY event_seq DESC,seq DESC LIMIT ?", (CLASSIFIER_VERSION, limit))]

    def classification_history(self, before=0, limit=20):
        _integer(before, "before", 0)
        _integer(limit, "limit", 1, 100)
        with self._lock, closing(self._connect()) as db:
            items = [{"seq": r["seq"], **json.loads(r["body"])} for r in db.execute(
                "SELECT seq,body FROM prompt_classifications WHERE (?=0 OR seq<?) ORDER BY seq DESC LIMIT ?",
                (before, before, limit + 1))]
            total = db.execute("SELECT COUNT(*) FROM prompt_classifications").fetchone()[0]
        more = len(items) > limit
        return {"items": items[:limit], "has_more": more,
                "next_before": items[limit - 1]["seq"] if more else None, "total": total}

    def _migrate_evidence(self, db, evidence, old):
        if old == evidence:
            return False
        derived = {"patterns", "excluded", "classifier_version"}
        immutable = lambda value: {k: v for k, v in value.items() if k not in derived}
        # Upgrade only derived labels; never admit a technical, unsupported or
        # unverified record by changing its classification.
        exclusions_compatible = (old["excluded"] == evidence["excluded"] or
            {old["excluded"], evidence["excluded"]} <= {"", "no_specific_pattern"})
        if (old.get("classifier_version", 1) >= CLASSIFIER_VERSION or
                immutable(old) != immutable(evidence) or not exclusions_compatible):
            raise PromptLearningConflictError("The same occurrence has different immutable evidence")
        receipt = {"review_id": evidence["review_id"], "event_seq": evidence["event_seq"],
            "at": self._stamp(), "reason": "derived_classifier_upgrade",
            "before": {k: copy.deepcopy(old.get(k, 1 if k == "classifier_version" else None)) for k in sorted(derived)},
            "after": {k: copy.deepcopy(evidence[k]) for k in sorted(derived)}}
        db.execute("INSERT INTO prompt_classifications(review_id,event_seq,at,body) VALUES(?,?,?,?)",
                   (evidence["review_id"], evidence["event_seq"], receipt["at"], _json(receipt)))
        db.execute("UPDATE prompt_evidence SET body=? WHERE review_id=? AND event_seq=?",
                   (_json(evidence), evidence["review_id"], evidence["event_seq"]))
        return True

    def reclassify(self, rows):
        """Atomically upgrade at most 2,000 supplied exact retained occurrences.

        One invalid row aborts the entire batch. Missing originals should be
        omitted by the caller and stay pending. Decisions are never changed;
        prompt selection is recomputed only once from the final evidence.
        """
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError("reclassification needs a list of at most 2000 exact rows")
        evidence_rows = [_evidence(row) for row in rows]
        with self._lock, closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                count = 0
                for evidence in evidence_rows:
                    old = db.execute("SELECT body FROM prompt_evidence WHERE review_id=? AND event_seq=?",
                        (evidence["review_id"], evidence["event_seq"])).fetchone()
                    if old is None:
                        raise PromptLearningConflictError("Reclassification needs an existing retained occurrence")
                    count += int(self._migrate_evidence(db, evidence, json.loads(old[0])))
                aggregates = {}
                changed = self._revise(db, self._load_state(db), "derived_classifier_upgrade",
                    trigger={"reclassified": count, "classifier_version": CLASSIFIER_VERSION},
                    aggregates=aggregates) if count else False
                db.commit()
            except BaseException:
                db.rollback()
                raise
            self._refresh(db, aggregates=aggregates)
            return {"recorded": False, "reclassified": count, "changed": changed,
                "reason": "reclassified" if count else "duplicate", "revision": self._state["revision"],
                "status": self.status()}

    def outcome(self, row):
        measured = _outcome(row)
        if measured is None:
            return {"recorded": False, "changed": False, "reason": "not_a_production_outcome",
                    "revision": self.settings()["revision"]}
        with self._lock, closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                previous = db.execute("SELECT body FROM prompt_outcomes WHERE attempt_id=?",
                                      (measured["attempt_id"],)).fetchone()
                if previous:
                    previous_body = json.loads(previous[0])
                    previous_body.pop("lineage_boundary", None)  # Derived at first insertion; prior may age out.
                    if previous_body != measured:
                        raise PromptLearningConflictError("The same attempt has a different measured outcome")
                    db.rollback()
                    return {"recorded": False, "changed": False, "reason": "duplicate",
                            "revision": self._state["revision"]}
                if measured["prior_attempt_id"]:
                    prior = db.execute("SELECT body FROM prompt_outcomes WHERE attempt_id=?",
                                       (measured["prior_attempt_id"],)).fetchone()
                    if prior:
                        prior = json.loads(prior[0])
                        if any(prior[k] != measured[k] for k in ("kind", "source_hash")):
                            raise PromptLearningConflictError("Repair link belongs to different source work")
                        if prior["parent_hash"] != measured["parent_hash"]:
                            if measured.get("parent_representations", {}).get("speaker_turns") != prior["parent_hash"]:
                                raise PromptLearningConflictError("Repair link belongs to different source work")
                            measured["lineage_boundary"] = {
                                "reason": "legacy_parent_representation", "linked": False,
                                "prior_parent_hash": prior["parent_hash"],
                                "current_parent_hash": measured["parent_hash"],
                                "basis": "Prior parent matches the exact speaker-turn reconstruction of this retained raw source; kept separate from linked repair comparisons."}
                db.execute("INSERT INTO prompt_outcomes(attempt_id,at,body) VALUES(?,?,?)",
                           (measured["attempt_id"], self._stamp(), _json(measured)))
                db.execute("DELETE FROM prompt_outcomes WHERE seq NOT IN (SELECT seq FROM prompt_outcomes ORDER BY seq DESC LIMIT ?)", (OUTCOME_WINDOW,))
                state = self._load_state(db)
                aggregates = {}
                changed = self._revise(db, state, "measured_recipe_outcomes",
                    trigger={"attempt_id": measured["attempt_id"], "kind": measured["kind"]}, aggregates=aggregates)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            self._refresh(db, aggregates=aggregates)
            return {"recorded": True, "changed": changed, "reason": "measured_outcome",
                    "revision": self._state["revision"], "status": self.status()}

    def _record(self, row, *, decide=False):
        evidence = _evidence(row)
        decision = _mapping(row.get("decision"))
        if decide and (decision.get("scope") == "instance" or decision.get("action") not in ("allow", "keep") or decision.get("by") != "operator"):
            return {"changed": False, "recorded": False, "reason": "not_an_individual_operator_decision",
                    "revision": self.settings()["revision"], "status": self.status()}
        with self._lock, closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                previous = db.execute("SELECT body FROM prompt_evidence WHERE review_id=? AND event_seq=?",
                                      (evidence["review_id"], evidence["event_seq"])).fetchone()
                reclassified = False
                if previous and json.loads(previous[0]) != evidence:
                    reclassified = self._migrate_evidence(db, evidence, json.loads(previous[0]))
                recorded = previous is None
                if recorded:
                    db.execute("INSERT INTO prompt_evidence(review_id,event_seq,body) VALUES(?,?,?)",
                               (evidence["review_id"], evidence["event_seq"], _json(evidence)))
                decision_changed = False
                if decide and not evidence["excluded"]:
                    key = evidence["kind"] + ":" + evidence["source_hash"]
                    prior = db.execute("SELECT body FROM prompt_decisions WHERE source_key=?", (key,)).fetchone()
                    saved = json.loads(prior[0]) if prior else {}
                    stamp = float(decision.get("at") or 0)
                    if not math.isfinite(stamp):
                        raise ValueError("decision time must be finite")
                    current = {"review_id": evidence["review_id"], "event_seq": evidence["event_seq"],
                               "action": decision["action"], "at": stamp,
                               "revision": int(row.get("revision") or 0)}
                    if not saved or (stamp, current["revision"]) > (saved["at"], saved["revision"]):
                        db.execute("INSERT INTO prompt_decisions VALUES(?,?) ON CONFLICT(source_key) DO UPDATE SET body=excluded.body", (key, _json(current)))
                        decision_changed = current != saved
                state = self._load_state(db)
                changed = self._revise(db, state, "individual_decision" if decision_changed else
                    "derived_classifier_upgrade" if reclassified else "distinct_failure_pattern",
                    trigger={"review_id": evidence["review_id"], "event_seq": evidence["event_seq"],
                             **({"action": decision["action"], "decision_revision": int(row.get("revision") or 0)}
                                if decision_changed else {})})
                db.commit()
            except BaseException:
                db.rollback()
                raise
            self._refresh(db)
            return {"changed": changed, "recorded": recorded or decision_changed, "reclassified": reclassified,
                    "reason": "reclassified" if reclassified else evidence["excluded"] or ("recorded" if recorded or decision_changed else "duplicate"),
                    "revision": self._state["revision"], "status": self.status()}

    def observe(self, row):
        return self._record(row)

    def decision(self, row):
        return self._record(row, decide=True)

    def update(self, expected_revision, enabled=None, mode=None, resume=False):
        _integer(expected_revision, "expected_revision")
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        if mode is not None and mode not in ("strict", "fluid"):
            raise ValueError("mode must be strict or fluid")
        if not isinstance(resume, bool):
            raise ValueError("resume must be boolean")
        with self._lock, closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                state = self._load_state(db)
                if expected_revision != state["revision"]:
                    raise PromptLearningConflictError("Prompt learning changed; reload its current revision")
                after = copy.deepcopy(state)
                if enabled is not None:
                    after["enabled"] = enabled
                if mode is not None:
                    after["mode"] = mode
                if resume:
                    after["automation_paused"] = False
                self._revise(db, state, "operator_settings", after=after)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            self._refresh(db)
            return self.status()

    def rollback(self, revision, expected_revision):
        _integer(revision, "revision")
        _integer(expected_revision, "expected_revision")
        with self._lock, closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                state = self._load_state(db)
                if expected_revision != state["revision"]:
                    raise PromptLearningConflictError("Prompt learning changed; reload before rollback")
                saved = db.execute("SELECT body FROM prompt_revisions WHERE revision=?", (revision,)).fetchone()
                if not saved:
                    raise ValueError("The requested prompt revision does not exist")
                after = copy.deepcopy(json.loads(saved[0])["after"])
                after["automation_paused"] = True
                self._revise(db, state, "operator_rollback_to_" + str(revision), after=after)
                db.commit()
            except BaseException:
                db.rollback()
                raise
            self._refresh(db)
            return self.status()

    def history(self, before=0, limit=20):
        _integer(before, "before", 0)
        _integer(limit, "limit", 1, 100)
        with self._lock, closing(self._connect()) as db:
            items = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM prompt_revisions WHERE (?=0 OR revision<?) ORDER BY revision DESC LIMIT ?",
                (before, before, limit + 1))]
            total = db.execute("SELECT COUNT(*) FROM prompt_revisions").fetchone()[0]
        more = len(items) > limit
        return {"items": items[:limit], "has_more": more,
                "next_before": items[limit - 1]["revision"] if more else None, "total": total}
