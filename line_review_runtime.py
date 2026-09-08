"""Pure recovery plans from retained editorial evidence. Never renders or airs."""
from __future__ import annotations

import copy
import hashlib


_MARKERS = {"A", "B", "C", "D", "E"}
_SPEAKERS = {"dj": "A", "host": "A", "cohost": "B", "skip": "B",
             "caller": "C", "third": "D", "caller2": "E"}
_ENTRY_FIELDS = {"label", "caller_name", "caller_voice", "caller_fx", "caller2_name",
                 "caller2_voice", "caller2_fx", "caller_id", "caller2_id", "story", "plot",
                 "verbatim", "vouched", "speakerbox_sources", "gallery_names", "product", "seed"}
_CALL_FIELDS = {"topic", "speakerbox_text", "story", "plot", "theme", "seed", "pivots",
                "source", "source_file", "request"}
_WHOLE_GATES = {"segment_brief", "radio_draft", "draft_fragment", "draft_trimming"}


class _NoTurns(ValueError):
    pass


def _hash(text):
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def _same(left, right):
    return " ".join(str(left or "").split()) == " ".join(str(right or "").split())


def _text(*values):
    return next((value for value in values if isinstance(value, str) and value.strip()), "")


def _blocked(reason):
    return {"blocked_reason": reason}


def _parse(parse_turns, script, entry):
    # The application's parser accepts caller identities; simple test/third-party
    # parsers may expose only their one-argument form.
    if entry.get("caller_name") or entry.get("caller2_name"):
        try:
            rows = parse_turns(script, str(entry.get("caller_name") or ""),
                               str(entry.get("caller2_name") or ""))
        except TypeError:
            rows = parse_turns(script)
    else:
        rows = parse_turns(script)
    if not isinstance(rows, (list, tuple)) or not rows:
        raise _NoTurns("The retained script has no parseable speaker turns")
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError("The retained script has an invalid turn")
        marker, said = row
        if marker not in _MARKERS or not isinstance(said, str) or not said.strip():
            raise ValueError("The retained script has an unknown speaker or empty turn")
        out.append((marker, said))
    return out


def _track(row, context, review_id):
    track = context.get("track")
    if not isinstance(track, dict) or not _text(track.get("id")):
        return _blocked("Track recovery requires the original track ID and snapshot")
    part = context.get("part")
    if part not in ("intro", "outro"):
        return _blocked("Track recovery requires its original intro or outro position")
    side = context.get("side") if isinstance(context.get("side"), dict) else (
        context.get("entry") if isinstance(context.get("entry"), dict) else {})
    candidate = _text(row.get("candidate"), context.get("script"), row.get("source"), side.get("text"))
    original = _text(context.get("script_plain"), context.get("plain_script"), side.get("text_plain"), row.get("source"))
    if not candidate or not original:
        return _blocked("Track recovery has no retained source or reviewed candidate")
    if row.get("gate") == "track_talk" and not _same(row.get("source"), candidate):
        return _blocked("The retained track link differs from the reviewed text")
    if row.get("gate") == "track_talk_fidelity" and not _same(row.get("source"), original):
        return _blocked("The retained track source differs from the reviewed original")
    entry = {"text": candidate, "text_plain": original,
             "who": "dj" if part == "intro" else "cohost", "review_ids": [review_id]}
    progress = side.get("tint_progress") if isinstance(side.get("tint_progress"), dict) else {}
    tint = side.get("tint") if isinstance(side.get("tint"), dict) else {}
    evidence = side.get("review_tint") if isinstance(side.get("review_tint"), dict) else {}
    chunks = next((one.get("chunks") for one in (context, evidence, progress, tint)
                   if isinstance(one.get("chunks"), list) and one["chunks"]), [])
    world = _text(context.get("world"), context.get("crystal"), evidence.get("world"),
                  progress.get("world"), tint.get("world"))
    if chunks or world:
        entry["review_tint"] = {"chunks": copy.deepcopy(chunks), "world": world}
    if progress.get("source") == _hash(original.strip()):
        # This is retained resume evidence, never a new passing evaluation.
        # The recording road regrades the exact candidate before using it.
        entry["tint_progress"] = copy.deepcopy(progress)
    return {"recovery_kind": "track_talk", "track": copy.deepcopy(track),
            "part": part, "entry": entry, "review_ids": [review_id]}


def _shelf_line(row, context, retained, kind, review_id, parse_turns):
    """Restore one explicit voice without assigning it to a cast member."""
    if not _text(retained.get("text")) or not _text(retained.get("voice")):
        return None
    source = _text(context.get("source_original"), row.get("source"))
    original = _text(context.get("script_plain"), context.get("plain_script"),
                     retained.get("text_plain"), source)
    active_review = row.get("gate") in {"segment_brief", "ad_length", "ad_repetition"}
    if active_review:
        # This gate judges the active candidate, while tint still needs its
        # underlying original. Changing that pair would invalidate the earlier
        # exact tint approval and regrade the candidate against itself.
        if not _same(source, retained.get("text")) or not _same(
                _text(context.get("script"), source), source):
            return _blocked("The reviewed active text differs from the retained shelf line")
        if _text(retained.get("text_plain")) and not _same(original, retained["text_plain"]):
            return _blocked("The retained underlying source differs from the shelf original")
    try:
        _parse(parse_turns, original.strip(), retained)
    except _NoTurns:
        pass
    except Exception as exc:
        return _blocked(str(exc))
    else:
        return None  # Marked dialogue keeps the conversation recovery rules.
    if not source or (not active_review and not _same(original, source)):
        return _blocked("The retained shelf source differs from the reviewed original")
    if not any(_same(source, retained.get(key)) for key in ("text", "text_plain")):
        return _blocked("The reviewed source no longer belongs to the retained shelf line")
    if context.get("entry_id") and str(context["entry_id"]) != str(retained.get("sid") or ""):
        return _blocked("The retained shelf line differs from the reviewed entry ID")
    candidate = _text(context.get("candidate_original"), row.get("candidate"), source)
    if not _same(candidate, _text(row.get("candidate"), row.get("source"))):
        return _blocked("The retained shelf candidate differs from the reviewed words")
    try:
        _parse(parse_turns, candidate.strip(), retained)
    except _NoTurns:
        pass
    except Exception as exc:
        return _blocked(str(exc))
    else:
        return _blocked("A speaker-labelled candidate cannot replace one explicit shelf voice")
    made = {key: copy.deepcopy(retained[key]) for key in
            ("voice", "who", "product", "seed", "sid", "at", "cast") if key in retained}
    made.update(text=candidate, text_plain=original, who=str(retained.get("who") or ""),
                review_ids=[review_id])
    if _text(retained.get("text_plain")) and not _same(original, retained["text_plain"]):
        made["review_source_plain"] = retained["text_plain"]
    progress = retained.get("tint_progress") if isinstance(retained.get("tint_progress"), dict) else {}
    tint = retained.get("tint") if isinstance(retained.get("tint"), dict) else {}
    prior = retained.get("review_tint") if isinstance(retained.get("review_tint"), dict) else {}
    chunks = next((one.get("chunks") for one in (context, prior, progress, tint)
                   if isinstance(one.get("chunks"), list) and one["chunks"]), [])
    world = _text(context.get("world"), context.get("crystal"), prior.get("world"),
                  progress.get("world"), tint.get("world"))
    if chunks or world:
        made["review_tint"] = {"chunks": copy.deepcopy(chunks), "world": world}
    if progress.get("source") == _hash(original.strip()):
        made["tint_progress"] = copy.deepcopy(progress)
    return {"recovery_kind": "shelf_line", "kind": kind, "row": made,
            "review_ids": [review_id]}


def build_recovery(row, parse_turns, profile=''):
    if not isinstance(row, dict) or not _text(row.get("id")):
        return _blocked("Recovery requires a stored review ID")
    if row.get("technical"):
        return _blocked("A technical failure must be repaired before content can be recovered")
    context = row.get("context") if isinstance(row.get("context"), dict) else {}
    review_id = row["id"]
    kind = str(context["kind"]) if isinstance(context.get("kind"), str) else "banter"
    gate = str(row.get("gate") or "")
    if kind == "track_talk" or str(row.get("gate") or "").startswith("track_talk"):
        return _track(row, context, review_id)
    if context.get("track") or context.get("track_id"):
        return _blocked("Track-bound text cannot be recovered as an unrelated booth conversation")
    retained = context.get("entry") if isinstance(context.get("entry"), dict) else {}
    shelf = _shelf_line(row, context, retained, kind, review_id, parse_turns)
    if shelf is not None:
        return shelf
    entry = {key: copy.deepcopy(retained[key]) for key in _ENTRY_FIELDS if key in retained}
    # Older captures carry identity alongside, rather than inside, the entry.
    for key in _ENTRY_FIELDS:
        if key not in entry and key in context:
            entry[key] = copy.deepcopy(context[key])
    call = retained.get("call") if isinstance(retained.get("call"), dict) else context.get("call")
    if isinstance(call, dict):
        entry["call"] = {key: copy.deepcopy(call[key]) for key in _CALL_FIELDS if key in call}
    original = _text(context.get("script_plain"), context.get("plain_script"),
                     retained.get("script_plain"), context.get("script"), retained.get("script"))
    candidate = _text(context.get("candidate_original"), row.get("candidate"))
    source = _text(context.get("source_original"), row.get("source"))
    if not source:
        return _blocked("The review does not retain the rejected source text")
    if gate in {"ad_length", "ad_repetition"}:
        active = _text(context.get("script"), source)
        if not _same(active, source):
            return _blocked("The retained advert differs from the reviewed source")
        if original and not _same(original, active):
            entry["review_source_plain"] = original
        original = active
    if gate in _WHOLE_GATES:
        # These gates judge a complete draft. Trimming's candidate is the
        # surviving subset, so accepting that rejection restores the source.
        original = _text(context.get("script"), row.get("source"))
        source_words = " ".join(source.split())
        original_words = " ".join(original.split())
        if original_words != source_words and not (
                gate == "draft_fragment" and original_words.startswith(source_words)):
            return _blocked("The retained draft differs from the reviewed whole-script source")
    if not original:
        marker = context.get("marker")
        if marker not in _MARKERS:
            speaker = str(context.get("who") or context.get("speaker") or row.get("who") or "").lower()
            marker = _SPEAKERS.get(speaker)
        if marker not in _MARKERS:
            return _blocked("A standalone line has no known speaker mapping")
        original = f"{marker}: {source}"
    try:
        turns = _parse(parse_turns, original.strip(), entry)
    except _NoTurns as exc:
        marker = context.get("marker")
        if marker not in _MARKERS:
            speaker = str(context.get("who") or context.get("speaker") or row.get("who") or "").lower()
            marker = _SPEAKERS.get(speaker)
        if marker not in _MARKERS:
            return _blocked(str(exc) + "; a known speaker mapping is required")
        if not _same(original, source):
            return _blocked("The unmarked script differs from the reviewed source")
        # Keep the untouched source as evidence; only the playback script gains
        # a known marker. Never assign anonymous prose to the default host.
        entry["review_original_script"] = original
        original = f"{marker}: {original}"
        try:
            turns = _parse(parse_turns, original.strip(), entry)
        except Exception as parse_exc:
            return _blocked(str(parse_exc) or "The marked source could not be parsed")
    except Exception as exc:
        return _blocked(str(exc) or "The retained script could not be parsed")
    for marker, prefix in (("C", "caller"), ("E", "caller2")):
        if any(mark == marker for mark, _said in turns):
            if not _text(entry.get(prefix + "_name")) or not _text(entry.get(prefix + "_voice")):
                return _blocked(f"The original {prefix} name and voice are required to restore that speaker")
    if kind == "caller" and not any(mark in ("C", "E") for mark, _said in turns):
        return _blocked("Caller recovery requires retained caller turns and identity")
    progress = context.get("tint_progress")
    if not isinstance(progress, dict):
        progress = retained.get("tint_progress") if isinstance(retained.get("tint_progress"), dict) else {}
    original_hash = _hash(original.strip())
    prior_turns = progress.get("turns") if progress.get("source") == original_hash else []
    prior_turns = prior_turns if isinstance(prior_turns, list) else []
    resumed = []
    for index, (marker, said) in enumerate(turns):
        prior = prior_turns[index] if index < len(prior_turns) and isinstance(prior_turns[index], dict) else {}
        text = ""
        if prior.get("marker") == marker and prior.get("source") == _hash(said):
            text = _text(prior.get("text"), prior.get("rejected_candidate"))
        # Every candidate will be graded again by crystal_tint. No old approval,
        # coverage, cut or recording state is manufactured or carried forward.
        resumed.append({"marker": marker, "source": _hash(said), "text": text, "selected": True})
    if gate in _WHOLE_GATES:
        # Leave unmatched turns for normal writing/tint validation. No retained
        # subset, new quality proof or recording state replaces the full draft.
        pass
    elif gate in {"call_contract", "tint_structure", "blend"}:
        active = _text(context.get("script"), row.get("candidate"), original)
        if not _same(active, row.get("candidate")) or not _same(original, row.get("source")):
            return _blocked("The retained scripts do not match the reviewed source and candidate")
        try:
            active_turns = _parse(parse_turns, active.strip(), entry)
        except Exception as exc:
            return _blocked(str(exc))
        if [mark for mark, _said in active_turns] != [mark for mark, _said in turns]:
            return _blocked("The reviewed candidate changed turn count or speaker order")
        for resume, (_marker, said) in zip(resumed, active_turns):
            resume["text"] = said
    else:
        at = context.get("turn")
        if at is not None:
            if isinstance(at, bool) or not isinstance(at, int) or not 1 <= at <= len(turns):
                return _blocked("The rejected turn index is outside the retained original script")
            index = at - 1
            if not _same(turns[index][1], source):
                return _blocked("The rejected source no longer matches its original turn")
        else:
            matches = [i for i, (_marker, said) in enumerate(turns) if _same(said, source)]
            if len(matches) != 1:
                return _blocked("The rejected line has no unique position in the retained original script")
            index = matches[0]
        if context.get("marker") and context["marker"] != turns[index][0]:
            return _blocked("The rejected speaker marker differs from the original turn")
        resumed[index]["text"] = candidate or turns[index][1]
        resumed[index]["rejected_source"] = turns[index][1]
        resumed[index]["rejected_candidate"] = candidate or turns[index][1]
        resumed[index]["review_id"] = review_id
    chunks = context.get("chunks")
    if not isinstance(chunks, list):
        chunks = progress.get("chunks") if isinstance(progress.get("chunks"), list) else []
    world = _text(context.get("world"), context.get("crystal"), progress.get("world"))
    entry.update(script=original, script_plain=original, prep_kind=kind, freshened=True,
                 profile=str(profile or ""), review_ids=[review_id],
                 tint_progress={"source": original_hash, "world": world,
                                "chunks": copy.deepcopy(chunks), "turns": resumed})
    if gate == "tint_structure":
        entry["tint_progress"]["rejected_candidate"] = active
    return entry
