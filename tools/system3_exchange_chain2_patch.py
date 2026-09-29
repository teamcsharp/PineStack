"""[s3-chain2] app.py: the prepared shelf, second cut (on top of
tools/system3_exchange_chain_patch.py as deployed in 00c60d8).

  * "aired" means HEARD: a chapter handed to the transports is "published"; the
    keeper promotes it to "aired" when every reply's line id has a heard receipt
    (_PAGE_ACKED_LINES: page listener ack / box audible receipt), else records it
    "unheard" with the lost turns after PINE_S3_CHAPTER_HEARD_WAIT (900 s).
    (The 03:37 station ID ddb70edb was probed while turns 3-5 were still queued
    on the page: all six were published, t03/t05 heard 03:40, t04 03:41.)
  * the writer keeps every turn that passes (on the shelf entry, across attempts)
    and writes again only from the first failing turn, told exactly what failed
    (up to 3 repair visits per attempt);
  * the reply gate: the sheet's scaffolding and the writer's own instructions are
    refused; the rolled ACT may be spoken ("no, bro, that isn't gonna work");
    a short reply that points back ("Are you sure about that?") or names a
    speaker answers; "it is what it is" style frames are refused; an exchange
    whose replies never name anything said is written again;
  * a full writers' lane is a 20 s wait, not a failed attempt; backoff capped
    15/30/60/90/120 s;
  * one waiting exchange per road: a newer source on a road whose earlier
    exchange waits is recorded "superseded" and the earlier one airs in the slot
    (an earlier one with 3 failed attempts is expired instead); by-hand lines
    are never superseded.

Hunks are cut by gen/gen_delta.py; every anchor is unique in the live HEAD
app.py (67a2524e) and applying them reproduces the v2 full tool exactly. Ship
the reconciled tools/system3_exchange_chain_patch.py (v2 stored text) with it,
so both tools --check 2 afterwards. --check exits 0 ready / 2 applied / 1
anchors missing; --apply idempotent, atomic, LF.
TARGET: app.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('chain2-hunk-01-line36070',
     'S3_CHAPTER_WAIT = float(os.getenv("PINE_S3_CHAPTER_WAIT", "5400"))\nS3_CHAPTER_FIT_WAIT = float(os.getenv("PINE_S3_CHAPTER_FIT_WAIT", "1200"))\nS3_CHAPTER_BACKOFF = (20.0, 45.0, 90.0, 180.0, 300.0)\nS3_CHAPTER_WORDS_PER_SECOND = 2.5\n_S3_CHAPTER_SHELF: dict[str, dict[str, Any]] = {}\n',
     'S3_CHAPTER_WAIT = float(os.getenv("PINE_S3_CHAPTER_WAIT", "5400"))\nS3_CHAPTER_FIT_WAIT = float(os.getenv("PINE_S3_CHAPTER_FIT_WAIT", "1200"))\nS3_CHAPTER_BACKOFF = (15.0, 30.0, 60.0, 90.0, 120.0)       # [s3-chain2] capped at two minutes\nS3_CHAPTER_LANE_RETRY = 20.0                                # a full writers\' lane is not a failed attempt\nS3_CHAPTER_HEARD_WAIT = float(os.getenv("PINE_S3_CHAPTER_HEARD_WAIT", "900"))\nS3_CHAPTER_REPAIR_VISITS = 3\nS3_CHAPTER_WORDS_PER_SECOND = 2.5\n_S3_CHAPTER_SHELF: dict[str, dict[str, Any]] = {}\n',
     1),
    ('chain2-hunk-02-line36105',
     '                e["state"] = "partial" if int(e.get("done") or 0) >= 1 else "prepared"\n                e["why"] = "the process restarted while it was on the air"\n            _S3_CHAPTER_SHELF[str(key)] = e\n    return _S3_CHAPTER_SHELF\n',
     '                e["state"] = "partial" if int(e.get("done") or 0) >= 1 else "prepared"\n                e["why"] = "the process restarted while it was on the air"\n            if e.get("state") == "published":                    # [s3-chain2] receipts died with the process\n                e["state"], e["why"] = "unheard", "the process restarted before every reply was heard"\n            _S3_CHAPTER_SHELF[str(key)] = e\n    return _S3_CHAPTER_SHELF\n',
     1),
    ('chain2-hunk-03-line36143',
     '    shelf = _s3_chapter_shelf()\n    for old in [k for k, x in shelf.items()                     # the done ones, after six hours\n                if x.get("state") not in _S3_CHAPTER_LIVE and now - float(x.get("updated") or 0) > 6 * 3600]:\n        shelf.pop(old, None)\n    shelf[key] = e\n',
     '    shelf = _s3_chapter_shelf()\n    for old in [k for k, x in shelf.items()                     # the done ones, after six hours\n                if x.get("state") not in _S3_CHAPTER_LIVE + ("published",)\n                and now - float(x.get("updated") or 0) > 6 * 3600]:\n        shelf.pop(old, None)\n    shelf[key] = e\n',
     1),
    ('chain2-hunk-04-line36188',
     '\n\ndef _s3_chapter_reply_fault(before: list[str], text: str, work: str) -> str:\n    """[s3-chain] Why a written reply is not an answer: empty, a stock frame,\n    its own direction said aloud, or no word of what was said before it."""\n    words = " ".join(str(text or "").split())\n    if not re.search(r"[^\\W_]", words):\n        return "is empty"\n    low = words.lower()\n    if any(frame in low for frame in _BANTER_BEAT_STOCK):\n        return "is a stock frame, not an answer"\n    if _beat_speaks_direction(words, {"work": work}):\n        return "speaks its own direction"\n    said = " %s " % " ".join(re.findall(r"[a-z0-9\']+", low))\n    ww = re.findall(r"[a-z0-9\']+", str(work or "").lower())\n    for k in range(max(0, len(ww) - 4)):\n        run = " ".join(ww[k:k + 5])            # five words of its direction, in order\n        if " %s " % run in said:\n            return "speaks its direction (%s)" % run\n    mine = _beat_content_words(words)\n    if not any(_beat_content_words(b) & mine for b in before if b):\n        return "answers nothing that was said before it"\n    return ""\n\n\n',
     '\n\n# [s3-chain2] the sheet\'s own scaffolding and this writer\'s instructions, never words to say\n_S3_CHAPTER_SCAFFOLD = re.compile(\n    r"message with|reflecting the mood|\\bsay it in\\b|while doing it|fixed source material|"\n    r"airs exactly as recorded|source road|numbered system three|after each dash|\\bturn \\d+\\b", re.I)\n_S3_CHAPTER_GENERIC = ("it is what it is", "just how it is", "if that\'s right", "if that is right")\n_S3_CHAPTER_POINTS_BACK = re.compile(\n    r"\\b(that|this|it|those|these|there|you|your|yours|so|why|how|what|who|really|sure)\\b", re.I)\n\n\ndef _s3_chapter_reply_fault(before: list[str], text: str, work: str, names: Any = ()) -> str:\n    """[s3-chain2] Why a written reply is not an answer: empty, a stock frame, the\n    sheet\'s scaffolding (or this writer\'s instructions) said aloud, its leg\'s\n    direction read out, or nothing that points back at what was said. The\n    rolled ACT is allowed to be spoken ("no, bro, that isn\'t gonna work" is the\n    RS roll done, not read); a short reply that points back ("Are you sure\n    about that?") answers the turn before it."""\n    words = " ".join(str(text or "").split())\n    if not re.search(r"[^\\W_]", words):\n        return "is empty"\n    low = words.lower()\n    if any(frame in low for frame in _BANTER_BEAT_STOCK) or any(g in low for g in _S3_CHAPTER_GENERIC):\n        return "is a stock frame, not an answer"\n    hit = _S3_CHAPTER_SCAFFOLD.search(words)\n    if hit:\n        return "speaks its direction (%s)" % hit.group(0).lower()\n    # the leg\'s own direction, without the rolled act ("while doing it, <act>")\n    leg = re.sub(r"(?i)while doing it,[^.;\\]]*", "", str(work or ""))\n    if _beat_speaks_direction(words, {"work": leg}):\n        return "speaks its own direction"\n    n = len(re.findall(r"[a-z0-9\']+", low))\n    if n < 3:\n        return "is too short to answer anything"\n    mine = _beat_content_words(words)\n    if any(_beat_content_words(b) & mine for b in before if b):\n        return ""\n    if any(str(nm).lower() in low for nm in (names or ()) if len(str(nm)) >= 3):\n        return ""                                  # it answers someone by name\n    if n <= 16 and _S3_CHAPTER_POINTS_BACK.search(low):\n        return ""                                  # a short reply that points back\n    return "answers nothing that was said before it"\n\n\ndef _s3_chapter_links(before: list[str], text: str) -> bool:\n    return bool(_beat_content_words(text) & set().union(*[_beat_content_words(b) for b in before if b] or [set()]))\n\n\n',
     1),
    ('chain2-hunk-05-line36261',
     '    old = e.get("stamp")\n    e["stamp"] = dict(handle.stamp)\n    if isinstance(old, dict) and old.get("conversation_id") and callable(globals().get("system3_line_chapter_state")):\n        globals()["system3_line_chapter_state"](old, "replanned", "planned again as " + str(handle.stamp.get("conversation_id")))\n',
     '    old = e.get("stamp")\n    e["stamp"] = dict(handle.stamp)\n    e["draft"], e["draft_why"] = [], ""                      # [s3-chain2] a new plan, a new draft\n    if isinstance(old, dict) and old.get("conversation_id") and callable(globals().get("system3_line_chapter_state")):\n        globals()["system3_line_chapter_state"](old, "replanned", "planned again as " + str(handle.stamp.get("conversation_id")))\n',
     1),
    ('chain2-hunk-06-line36294',
     '    except WritingDeferred:\n        why = "the writers\' lane is full"\n    except Exception as exc:  # noqa: BLE001\n        why = ("%s: %s" % (type(exc).__name__, exc))[:200]\n    if why:\n        step = S3_CHAPTER_BACKOFF[min(len(S3_CHAPTER_BACKOFF), int(e["attempts"])) - 1]\n        e["next_try"] = time.time() + step\n        _s3_chapter_note(e, "pending", "attempt %d: %s - tried again in %ds" % (e["attempts"], why, int(step)))\n',
     '    except WritingDeferred:\n        why = "the writers\' lane is full"\n        e["attempts"] = max(0, int(e["attempts"]) - 1)             # [s3-chain2] not a failed attempt\n        e["lane_waits"] = int(e.get("lane_waits") or 0) + 1\n        e["next_try"] = time.time() + S3_CHAPTER_LANE_RETRY\n        _s3_chapter_note(e, "pending", "the writers\' lane is full - asked again in %ds (the draft is kept)"\n                         % int(S3_CHAPTER_LANE_RETRY))\n        return False\n    except Exception as exc:  # noqa: BLE001\n        why = ("%s: %s" % (type(exc).__name__, exc))[:200]\n    if why:\n        step = S3_CHAPTER_BACKOFF[min(len(S3_CHAPTER_BACKOFF), max(1, int(e["attempts"]))) - 1]\n        e["next_try"] = time.time() + step\n        _s3_chapter_note(e, "pending", "attempt %d: %s - tried again in %ds" % (e["attempts"], why, int(step)))\n',
     1),
    ('chain2-hunk-07-line36307',
     '\nasync def _s3_chapter_write(e: dict[str, Any], plan: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str]:\n    """[s3-chain] The chapter\'s words: the source verbatim as turn one, every\n    later turn a new line that answers what was said, on its planned seat."""\n    seats = list(plan.get("seats") or [])\n    names = dict(plan.get("names") or {})\n',
     '\nasync def _s3_chapter_write(e: dict[str, Any], plan: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str]:\n    """[s3-chain2] The chapter\'s words: the source verbatim as turn one, every\n    later turn a new line that answers what was said, on its planned seat.\n    Turns that pass are KEPT (on the shelf entry, across attempts); only the\n    first failing turn onward is written again, and the writer is told exactly\n    what failed. Nothing is loosened: every reply still passes the gate."""\n    seats = list(plan.get("seats") or [])\n    names = dict(plan.get("names") or {})\n',
     1),
    ('chain2-hunk-08-line36316',
     '    budget = _s3_chapter_budget(e, plan)\n    opening = " ".join(str(e.get("opening") or "").split())\n    context = ("SOURCE ROAD: %s. Turn 1 is fixed source material that airs exactly as recorded: %s.\\n"\n               "Every later turn is a NEW spoken line in its speaker\'s own voice that answers what was "\n               "actually said - name something concrete from the line it answers - following its "\n               "numbered System Three roll. The words after each dash, and in brackets, say HOW a "\n               "turn behaves; they are never words to say.\\n"\n               "WHO IS SPEAKING: %s.\\n"\n               "TIME: the replies together run about %d seconds on air (about %d words in all).\\n"\n               "WHAT IT IS ABOUT: %s"\n               % (e.get("kind") or "line", str(e.get("source_is") or "a line"), cast, int(budget),\n                  int(budget * S3_CHAPTER_WORDS_PER_SECOND), str(e.get("context") or opening)[:600]))\n    script = await _banter_beats(context, str(plan.get("sheet") or ""), len(seats), seats,\n                                 seed_text=opening, verbatim_seed=True)\n    # The source is turn one exactly as recorded - never re-parsed (a "Skip:" or\n    # "host:" inside an advert\'s own words would split it): only the replies are.\n    head, _nl, rest = str(script or "").partition("\\n")\n\n    def key(text: str) -> str:\n        return " ".join(re.findall(r"[a-z0-9\']+", str(text or "").lower()))\n    if key(head.split(":", 1)[-1]) != key(opening):\n        return None, "the writer changed the source"\n    written = [(seats[0] if seats else "A", opening)] + list(banter_turns(rest))\n    if len(written) != len(seats) or [m for m, _s in written] != seats:\n        return None, "the writer missed the graph (%d of %d turns on their seats)" % (\n            sum(1 for (m, _s), s in zip(written, seats) if m == s), len(seats))\n    beats = _banter_beat_plan(str(plan.get("sheet") or ""), len(seats), seats)\n    said = [opening]\n    for i in range(1, len(written)):\n        text = " ".join(str(written[i][1]).split())\n        fault = _s3_chapter_reply_fault(said[-2:] + [opening], text,\n                                        str((beats[i] if i < len(beats) else {}).get("work") or ""))\n        if fault:\n            return None, "turn %d %s: %s" % (i + 1, fault, text[:80])\n        said.append(text)\n    written[0] = (written[0][0], str(e.get("opening") or ""))\n    rows = globals()["system3_line_chapter"](e["stamp"], written)\n    if not rows:\n        return None, "it missed its roulette contract (>= 3 turns, >= 2 voices, every turn bound)"\n',
     '    budget = _s3_chapter_budget(e, plan)\n    opening = " ".join(str(e.get("opening") or "").split())\n    sheet = str(plan.get("sheet") or "")\n    context = ("A %s is on the air: %s. What it said is the first line of the transcript below and "\n               "it airs exactly as it is; you write only the later turns.\\n"\n               "Every later turn is a NEW spoken line in its speaker\'s own voice that answers what was "\n               "actually said - name something concrete from the line it answers, or put a pointed "\n               "question back - following its numbered System Three roll. The words after each dash, "\n               "and in brackets, say HOW a turn behaves and are never read out; when a roll gives a "\n               "phrase to say, say it in that speaker\'s own words.\\n"\n               "WHO IS SPEAKING: %s.\\n"\n               "TIME: the replies together run about %d seconds on air (about %d words in all).\\n"\n               "WHAT IT IS ABOUT: %s"\n               % (e.get("kind") or "line", str(e.get("source_is") or "a line"), cast, int(budget),\n                  int(budget * S3_CHAPTER_WORDS_PER_SECOND), str(e.get("context") or opening)[:600]))\n    beats = _banter_beat_plan(sheet, len(seats), seats)\n    known = [n for n in names.values() if n]\n\n    def key(text: str) -> str:\n        return " ".join(re.findall(r"[a-z0-9\']+", str(text or "").lower()))\n\n    def accept(draft: list[tuple[str, str]], cands: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], str]:\n        why = ""\n        for marker, cand in cands:\n            k = len(draft) + 1\n            if k >= len(seats):\n                break\n            text = " ".join(str(cand or "").split())\n            if key(text) == key(opening) or any(key(text) == key(t) for _m, t in draft):\n                continue                                   # the transcript handed back, not a turn\n            if str(marker) != seats[k]:\n                why = "turn %d went to seat %s, not %s" % (k + 1, marker, seats[k])\n                break\n            said = [opening] + [t for _m, t in draft]\n            fault = _s3_chapter_reply_fault(said[-2:] + [opening], text,\n                                            str((beats[k] if k < len(beats) else {}).get("work") or ""), known)\n            if fault:\n                why = "turn %d %s: %s" % (k + 1, fault, text[:80])\n                break\n            draft.append((seats[k], text))\n        if not why and len(draft) < len(seats) - 1:\n            why = "the writer stopped at turn %d of %d" % (len(draft) + 1, len(seats))\n        return draft, why\n\n    draft = [(str(m), str(t)) for m, t in (e.get("draft") or [])]\n    why = str(e.get("draft_why") or "")\n    if not draft:\n        script = await _banter_beats(context, sheet, len(seats), seats, seed_text=opening, verbatim_seed=True)\n        # The source is turn one exactly as recorded - never re-parsed (a "Skip:" or\n        # "host:" inside an advert\'s own words would split it): only the replies are.\n        head, _nl, rest = str(script or "").partition("\\n")\n        if key(head.split(":", 1)[-1]) != key(opening):\n            return None, "the writer changed the source"\n        draft, why = accept([], list(banter_turns(rest)))\n    visits = 0\n    while len(draft) < len(seats) - 1 and visits < S3_CHAPTER_REPAIR_VISITS:\n        visits += 1\n        e["draft"], e["draft_why"] = [list(x) for x in draft], why\n        _s3_chapter_save()\n        k = len(draft) + 1\n        rows = beats[k:]\n        recent = "\\n".join("%s has just said - %s" % (m, t)\n                           for m, t in ([(seats[0], opening)] + draft)[-3:])\n        order = "\\n".join("%d  %s  - %s" % (row["turn"], row["seat"], row["work"]) for row in rows)\n        prompt = (context + "\\n\\nCOMPLETED TRANSCRIPT - these lines are immutable:\\n" + recent\n                  + "\\n\\nWRITE ONLY THESE NEXT TURNS:\\n" + order\n                  + ("\\nYOUR LAST DRAFT FAILED: %s. Write turn %d again as a NEW line that answers the line "\n                     "immediately above it." % (why, k + 1) if why else "")\n                  + "\\nOutput exactly one line per listed turn using only the listed A:/B:/C:/D: marker. "\n                    "No preface, labels, markdown or stage directions.")\n        raw = await ask_model(prompt, limit=min(2800, max(900, 450 * len(rows))), spice=0.45, num_ctx=16384,\n                              mark={"kind": "chapter repair", "turn": k + 1, "visit": visits})\n        draft, why = accept(draft, list(banter_turns(raw or "")))\n        e["repairs"] = int(e.get("repairs") or 0) + 1\n    if len(draft) == len(seats) - 1 and not any(_s3_chapter_links([opening] + [t for _m, t in draft[:i]], t)\n                                                 for i, (_m, t) in enumerate(draft)):\n        # every reply only pointed back: the exchange never names what was said\n        why, draft = "no reply names anything that was said - the replies are written again", []\n    e["draft"], e["draft_why"] = [list(x) for x in draft], why\n    if len(draft) < len(seats) - 1:\n        return None, why or "the writer stopped short"\n    written = [(seats[0], str(e.get("opening") or ""))] + draft\n    rows = globals()["system3_line_chapter"](e["stamp"], written)\n    e["draft"], e["draft_why"] = [], ""\n    if not rows:\n        return None, "it missed its roulette contract (>= 3 turns, >= 2 voices, every turn bound)"\n',
     1),
    ('chain2-hunk-09-line36442',
     '\n\nasync def _s3_line_chapter_admit(stamp: dict[str, Any], spoken: str, kind: str, who: str = "dj",\n                                 name: str = "", first_clip: Any = None, sid: str = "",\n                                 bound: Any = None, bound_part: str = "", round_as: str = "",\n                                 voice: str = "") -> dict[str, Any] | None:\n    """[s3-chain] dj_speak\'s door: the line\'s chapter, ready - or a wait."""\n    chapter = globals().get("system3_line_chapter")\n',
     '\n\ndef _s3_chapter_superseded(e: dict[str, Any]) -> bool:\n    """[s3-chain2] ONE WAITING EXCHANGE PER ROAD. A newer source on a road whose\n    earlier exchange still waits is filed as superseded - recorded on its\n    conversation and on the drop log, never silent - and the earlier one airs in\n    this slot (the keeper is told now). It was being prepared ahead of this\n    slot; a pile of waiting sources would only ever air late and out of turn.\n    An earlier one that has failed three times gives way instead (expired).\n    PINE_S3_CHAPTER_ONE_PER_ROAD=0 switches this off (every source waits)."""\n    if e.get("by_hand") or os.getenv("PINE_S3_CHAPTER_ONE_PER_ROAD", "1") == "0":\n        return False\n    now = time.time()\n    for old in sorted(_s3_chapter_shelf().values(), key=lambda x: float(x.get("created") or 0)):\n        if (old is e or old.get("by_hand") or old.get("state") not in ("pending", "prepared")\n                or old.get("road") != e.get("road") or old.get("road_fn") != e.get("road_fn")):\n            continue\n        if old.get("state") == "pending" and int(old.get("attempts") or 0) >= 3:\n            _s3_chapter_note(old, "expired", "a newer %s source replaces it after %d failed attempts (%s)"\n                             % (e.get("road"), int(old.get("attempts") or 0), str(old.get("why") or "")[:120]),\n                             drop=True)\n            continue\n        old["next_air"] = min(float(old.get("next_air") or now), now)\n        e["superseded_by"] = old.get("key")\n        _s3_chapter_note(e, "superseded", "the %s road\'s earlier exchange (%s, %s) airs in this slot"\n                         % (e.get("road"), old.get("key"), old.get("state")), drop=True)\n        _s3_chapter_keeper_start()\n        return True\n    return False\n\n\nasync def _s3_line_chapter_admit(stamp: dict[str, Any], spoken: str, kind: str, who: str = "dj",\n                                 name: str = "", first_clip: Any = None, sid: str = "",\n                                 bound: Any = None, bound_part: str = "", round_as: str = "",\n                                 voice: str = "", by_hand: bool = False) -> dict[str, Any] | None:\n    """[s3-chain] dj_speak\'s door: the line\'s chapter, ready - or a wait."""\n    chapter = globals().get("system3_line_chapter")\n',
     1),
    ('chain2-hunk-10-line36463',
     '            bound=bound if isinstance(bound, dict) else None, bound_part=str(bound_part or ""),\n            source_is="a %s line spoken by %s" % (kind, name or who),\n            context=str(spoken)[:400])\n    return await _s3_chapter_take(e, lend=True)\n\n',
     '            bound=bound if isinstance(bound, dict) else None, bound_part=str(bound_part or ""),\n            source_is="a %s line spoken by %s" % (kind, name or who),\n            context=str(spoken)[:400], by_hand=bool(by_hand))\n        if _s3_chapter_superseded(e):                            # [s3-chain2]\n            return None\n    return await _s3_chapter_take(e, lend=True)\n\n',
     1),
    ('chain2-hunk-11-line36484',
     '                            context=context, road_fn=road_fn, replay=dict(replay or {}),\n                            source_is=source_is or "a %s" % kind, sid="")\n    got = await _s3_chapter_take(e, lend=True)\n    if got and not got.get("sid"):\n',
     '                            context=context, road_fn=road_fn, replay=dict(replay or {}),\n                            source_is=source_is or "a %s" % kind, sid="")\n        if _s3_chapter_superseded(e):                            # [s3-chain2]\n            return None\n    got = await _s3_chapter_take(e, lend=True)\n    if got and not got.get("sid"):\n',
     1),
    ('chain2-hunk-12-line36538',
     '            i += 1\n            e["done"] = i\n            _s3_chapter_save()\n        _s3_chapter_note(e, "aired", "%d turns under sid %s" % (len(rows), e.get("sid")))\n        return True\n    finally:\n        _S3_CHAPTER_ROW.reset(tok)\n\n\n',
     '            i += 1\n            e["done"] = i\n            # [s3-chain2] the row\'s own line id, so "aired" means HEARD, not handed over\n            for _c in reversed((_RADIO.get("chat") or [])[-40:]):\n                if str(_c.get("who") or "") == str(row.get("who") or "") and str(_c.get("text") or "") == str(got):\n                    e.setdefault("line_ids", {})[str(i - 1)] = str(_c.get("id") or "")\n                    break\n            _s3_chapter_save()\n        e["published_at"] = time.time()\n        _s3_chapter_note(e, "published", "%d turns handed to the air under sid %s - aired when every reply is heard"\n                         % (len(rows), e.get("sid")))\n        # the page pays for its airtime before the floor frees (#1146): nothing else is\n        # published into the middle of an exchange the listener has not heard yet\n        await _paged_settle(float(_PAGE_AIR_UNTIL[0] or 0))\n        _s3_chapter_heard(e)\n        return True\n    finally:\n        _S3_CHAPTER_ROW.reset(tok)\n\n\ndef _s3_chapter_heard(e: dict[str, Any]) -> None:\n    """[s3-chain2] A published exchange is AIRED once every reply\'s line id has a\n    heard receipt (the page\'s listener ack or the box\'s audible receipt). One\n    that is never fully heard is recorded as such (unheard) with the turns it\n    lost - it is never re-aired, and never called aired."""\n    ids = {k: v for k, v in (e.get("line_ids") or {}).items() if v}\n    missing = sorted(int(k) for k, v in ids.items() if v not in _PAGE_ACKED_LINES)\n    if not ids:\n        e["aired_at"] = time.time()\n        _s3_chapter_note(e, "aired", "%d turns handed over under sid %s - no line ids to check a receipt against"\n                         % (len(e.get("rows") or []), e.get("sid")))\n    elif not missing:\n        e["aired_at"] = time.time()\n        _s3_chapter_note(e, "aired", "%d turns heard under sid %s (%d s after hand-over)"\n                         % (len(e.get("rows") or []), e.get("sid"),\n                            int(e["aired_at"] - float(e.get("published_at") or e["aired_at"]))))\n    elif time.time() - float(e.get("published_at") or time.time()) > S3_CHAPTER_HEARD_WAIT:\n        _s3_chapter_note(e, "unheard", "handed over %d min ago and turn(s) %s were never heard"\n                         % (int(S3_CHAPTER_HEARD_WAIT // 60), ",".join(str(m) for m in missing) or "?"),\n                         drop=True)\n\n\n',
     1),
    ('chain2-hunk-13-line36598',
     '            _s3_chapter_note(e, "partial" if int(e.get("done") or 0) >= 1 else "prepared",\n                             "its airing stopped without a verdict")\n    on_air = bool(_RADIO.get("on")) and not radio_paused()\n    for e in live:\n',
     '            _s3_chapter_note(e, "partial" if int(e.get("done") or 0) >= 1 else "prepared",\n                             "its airing stopped without a verdict")\n    for e in [x for x in _s3_chapter_shelf().values() if x.get("state") == "published"]:\n        _s3_chapter_heard(e)                                     # [s3-chain2] cheap, every sweep\n    on_air = bool(_RADIO.get("on")) and not radio_paused()\n    for e in live:\n',
     1),
    ('chain2-hunk-14-line37069',
     '        _chapter = await _s3_line_chapter_admit(\n            system3, spoken, kind, who=who, name=name, first_clip=clip, sid=sid,\n            bound=bound, bound_part=bound_part, round_as=round_as, voice=forced or "")\n        if _chapter is None:\n            # [s3-chain] it WAITS on the prepared shelf - written, voiced and aired\n',
     '        _chapter = await _s3_line_chapter_admit(\n            system3, spoken, kind, who=who, name=name, first_clip=clip, sid=sid,\n            bound=bound, bound_part=bound_part, round_as=round_as, voice=forced or "",\n            by_hand=by_hand)\n        if _chapter is None:\n            # [s3-chain] it WAITS on the prepared shelf - written, voiced and aired\n',
     1),
]

def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
