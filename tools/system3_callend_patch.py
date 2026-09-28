"""[s3-callend] A call ends the way System 3's roulette rolled it.

The operator, 2026-09-28: "for phone calls. At the end of the node tree. I want to put a
resolution node with an RNG for setting up how a phone call is wrapped up so we can have a
roulette and table for how phone calls end and customers roll a wheel for how their call is
ended. If the last segment was selling a painting than in the roulette we want to offer
options for the caller ... these should have a response chain that follows + a rebuttal from
the caller before the call ends by somone one the station ending the call in response to the
customer "wrap call" roulette node"

System 3 plans the call's end (system3.py [s3-callend]: RESOLVE1 the caller's wheel, the
response chain, the caller's rebuttal, WRAP1 who on the station ends it and how) and its
runtime puts the plan's end on the call's meta as `callend`. This is the station's side:

  hooks          system3_painting_on_offer - the painting the last selling segment put on
                 offer (the sales floor, a painting spot, the gallery press; the price said
                 on air), read only from what the station recorded when it aired;
                 system3_gallery_outcome - what the rolled outcome does to the gallery's real
                 state at air (the pile by the desk, the wall's rest list);
                 s3_callend_angle / s3_callend_topic_turns / s3_callend_report
  callend-kwarg  call_flow_report(callend=...): the planned end
  callend-closed the checker keys on the planned WRAP CALL node, not on a word list: the
                 last turn by a station seat is the sign-off even when the rolled way of
                 ending is no goodbye ("cuts them off"); the rebuttal is still the caller's
                 last word, second to last. Unchanged for calls System 3 did not plan.
  callend-report the report says which it was
  site-*         every gate that grades a call passes the meta's `callend` on, the call
                 log's own grade too (a dead-line wrap closes a call a happening ended)
  callend-angle  the call's prompt: the angle's own ending (the ending shelf's line) and,
                 when the wheel is the painting's, the "still trying to shift a painting"
                 offer, give way to the running order's rolled end
  callend-topic  the topic contract grades the call without its rolled end (protocol, like
                 the sign-off it already sets aside)
  callend-ended  the booth row and the call log say the rolled end as the reason

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

HOOKS = r'''# --- [s3-callend] HOW A CALL ENDS, AS THE STATION SEES IT ------------------------------------
#
# System 3 plans the call's end (system3.py [s3-callend]): the caller's wheel (RESOLVE1),
# the response chain, the caller's rebuttal and WRAP CALL (WRAP1). The painting wheel is
# offered only when the last segment sold a painting - read here, only from what the
# station recorded as it aired the pitch - and what the wheel lands on acts on the
# gallery's real state when the call airs. Nothing here draws a number.
S3_CALLEND_PRICE = re.compile(r"\$\s?(\d[\d,]{0,8})|\b(\d[\d,]{0,8})\s*(?:dollars|bucks)\b", re.I)


def _s3_callend_price(text: str) -> int:
    """A price said in dollars ("298 dollars", "$298"), or 0."""
    try:
        m = S3_CALLEND_PRICE.search(str(text or ""))
        return int((m.group(1) or m.group(2)).replace(",", "")) if m else 0
    except Exception:  # noqa: BLE001
        return 0


def _s3_callend_terms(text: str) -> str:
    """The pitch's terms as said on air ("first caller takes it"), or ""."""
    return ("first caller takes it" if re.search(r"first caller|whoever (?:calls|rings)|next caller",
                                                   str(text or ""), re.I) else "")


def system3_painting_on_offer(within: float = 1200.0) -> dict[str, Any]:
    """[s3-callend] The painting the station's last selling segment put on offer, for
    the caller's wheel (RESOLVE1's painting category) - or {}.

    Read ONLY from what the station recorded when it aired the pitch: the sales floor
    (`_RADIO["hawking"]` and its asking price), a spot selling a painting
    (`_RADIO["ad_now"]`: the price stamped on it or said in its product line), the
    gallery press (`_RADIO["gallery_now"]`: the price said on its lines in the booth
    log). The freshest of them, no older than `within` seconds. No walk of the wall, no
    model, never raises."""
    try:
        now = time.time()
        within = max(60.0, float(within or 1200.0))
        rows: list[dict[str, Any]] = []
        gal = _RADIO.get("gallery_now") or {}
        pics = [r for r in (gal.get("images") or []) if isinstance(r, dict) and r.get("name")]
        descs = {str(r.get("name")): str(r.get("desc") or "") for r in pics}
        hawk = _RADIO.get("hawking") or {}
        names = [str(x) for x in (hawk.get("images") or []) if x]
        if names:
            rows.append({"kind": "hawk", "at": float(hawk.get("at") or 0), "image": names[0], "title": "",
                         "desc": descs.get(names[0], ""), "price": int(hawk.get("price") or 0), "terms": "",
                         "why": "the pair hawked it on the sales floor"})
        ad = _RADIO.get("ad_now") or {}
        if ad.get("image"):
            product = str(ad.get("product") or "")
            said = re.search(r"in it: (.+?) [—–-] from the Pine Box gallery", product)
            rows.append({"kind": "ad", "at": float(ad.get("at") or 0), "image": str(ad.get("image")),
                         "title": str(ad.get("title") or ""), "desc": said.group(1) if said else "",
                         "price": int(ad.get("price") or 0) or _s3_callend_price(product),
                         "terms": _s3_callend_terms(product), "why": "a spot on air was selling it"})
        if pics:
            at = float(gal.get("at") or 0)
            pick, price, terms = str(pics[0].get("name")), 0, ""
            for e in reversed(_RADIO.get("chat") or []):
                if float(e.get("ts") or 0) < at - 5:
                    break
                hit = [str(x) for x in (e.get("images") or []) if str(x) in descs]
                said_price = _s3_callend_price(e.get("text")) if hit else 0
                if said_price:
                    pick, price, terms = hit[0], said_price, _s3_callend_terms(e.get("text"))
                    break
            rows.append({"kind": "gallery", "at": at, "image": pick, "title": "", "desc": descs.get(pick, ""),
                         "price": price, "terms": terms, "why": "the gallery press had it up on air"})
        rows = [r for r in rows if r["at"] and now - r["at"] <= within]
        if not rows:
            return {}
        best = dict(max(rows, key=lambda r: r["at"]))
        best["age"] = round(now - best["at"], 1)
        best["desc"] = " ".join(str(best.get("desc") or "").split())[:400]
        return best
    except Exception:  # noqa: BLE001
        return {}


def system3_gallery_outcome(effect: str, painting: dict[str, Any], cid: str = "") -> dict[str, Any]:
    """[s3-callend] What a call's rolled end does to the gallery, where the station keeps
    state: the pile by the desk (`_RADIO["hawk_unsold"]` - offered, not gone; the pair
    offer it to the next caller) and the wall's rest list (`gallery_shown` - pictures
    that wait until the rest of the wall has had its turn). Sold, awarded or burnt: off
    the pile and to the back of the wall's queue. Unsold (turned down, ignored, short of
    the money): on the pile, still for sale. The station keeps no ledger of sold
    paintings, so a sold or burnt one can come round again once the wall has turned
    over - said, not invented. Never raises."""
    out: dict[str, Any] = {"effect": str(effect or ""), "image": str((painting or {}).get("image") or ""),
                           "applied": False}
    try:
        name = out["image"]
        if not name:
            return out
        pile = _RADIO.setdefault("hawk_unsold", [])
        if effect in ("sold", "awarded", "burnt"):
            before = len(pile)
            pile[:] = [p for p in pile if str((p or {}).get("name") or "") != name]
            shown = _RADIO.setdefault("gallery_shown", [])
            if name in shown:
                shown.remove(name)
            shown.append(name)
            del shown[:-60]
            out.update(applied=True, off_the_pile=before - len(pile), wall="to the back of the wall's queue")
        elif effect == "unsold":
            if not any(str((p or {}).get("name") or "") == name for p in pile):
                pile.append({"name": name, "at": int(time.time()), "price": int((painting or {}).get("price") or 0),
                             "desc": str((painting or {}).get("desc") or "")[:200]})
                del pile[:-24]
            out.update(applied=True, on_the_pile=True)
        pipeline_log("gallery", "(s3-callend) a call's rolled end: %s - %s" % (effect, name), extra=str(cid or ""))
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:200]
    return out


def _s3_callend_cut(text: str, start: str, end: str, keep_end: bool) -> str:
    """`text` with the span from `start` up to `end` taken out (the end kept, or a space)."""
    if start in text:
        head, _sep, rest = text.partition(start)
        if end in rest:
            return head + (end if keep_end else " ") + rest.split(end, 1)[1]
    return text


def s3_callend_angle(angle: Any, callend: Any) -> str:
    """[s3-callend] A call whose end System 3 rolled: the angle's own ending - the ending
    shelf's line, on each call road's wording - and, when the caller's wheel is the
    painting's, the "still trying to shift a painting" offer give way to the running
    order's rolled end, which is said once, plainly."""
    a = str(angle or "")
    ce = callend if isinstance(callend, dict) else {}
    if not ce.get("planned"):
        return a
    a = _s3_callend_cut(a, " By the end, ", "Then back to the music. ", False)
    a = _s3_callend_cut(a, " The call must END this way, arrived at honestly over the last two or three turns: ",
                        " Then cut back to the record.", True)
    a = _s3_callend_cut(a, " By the end of the call, ", " Format the caller's lines as", True)
    if (ce.get("resolve") or {}).get("category") == "painting":
        a = _s3_callend_cut(a, "THE PAIR ARE STILL TRYING TO SHIFT A PAINTING.",
                            "One quick beat; never the whole call.", False)
    says = " ".join(str(ce.get("says") or "").split())
    return (" ".join(a.split()) + " HOW THIS CALL ENDS WAS ROLLED - " + (says + ". " if says else "")
            + "The running order's last rows play it, turn by turn; whatever is said above about how the call "
              "ends, or about a painting being offered, gives way to them.")


def s3_callend_topic_turns(turns: Any, call_meta: Any) -> list[Any]:
    """[s3-callend] The turns the topic contract grades: a call whose end System 3
    rolled is graded without that end - the resolution, the chain and the rebuttal are
    the roulette's, not the caller's subject - keeping the last turn, which the
    contract already sets aside as the sign-off."""
    rows = list(turns or [])
    try:
        ce = call_meta.get("callend") if isinstance(call_meta, dict) else None
        k = int(ce.get("end_turns") or 0) if isinstance(ce, dict) and ce.get("planned") else 0
        if k > 1 and len(rows) > k + 2:
            return rows[:len(rows) - k] + rows[-1:]
    except Exception:  # noqa: BLE001
        pass
    return rows


def s3_callend_report(callend: Any, turns: Any, closed_by_words: bool) -> dict[str, Any]:
    """[s3-callend] What call_flow_report says about a planned end, {} for any other call."""
    wrap = (callend.get("wrap") if isinstance(callend, dict) else None) or {}
    if not wrap.get("planned"):
        return {}
    last = str(turns[-1][0]) if turns else ""
    return {"planned": True, "wrap": str(wrap.get("id") or ""), "wrap_seat": str(wrap.get("seat") or ""),
            "closed_by": last, "seat_as_planned": bool(last and last == str(wrap.get("seat") or "")),
            "sign_off": "spoken" if closed_by_words else "the planned WRAP CALL node",
            "polite": bool(wrap.get("polite"))}


'''

EDITS = [
    ("callend-hooks", 'def spoken_units(text: str) -> str:\n', HOOKS + 'def spoken_units(text: str) -> str:\n', 1),
    ("callend-kwarg",
     '                     exclude_entry: Any = None,\n                     story: dict[str, Any] | None = None,\n',
     '                     exclude_entry: Any = None,\n'
     '                     callend: Any = None,          # [s3-callend] the planned end (call_meta["callend"])\n'
     '                     story: dict[str, Any] | None = None,\n', 1),
    ("callend-closed",
     '    # A sign-off is not a resolution if the hosts spend the final two turns\n',
     '    # [s3-callend] THE CALL\'S END WAS ROLLED. A call System 3 planned with a WRAP CALL\n'
     '    # node ends the way its roulette said - "cuts them off", "puts them on hold forever",\n'
     '    # "that\'s the dial tone" - so the node, not a word list, is the sign-off: the last turn\n'
     '    # is a station seat, where the plan put the wrap. The caller\'s rebuttal is still the\n'
     '    # last word second to last (below). Unchanged for every call System 3 did not plan.\n'
     '    _wrap_plan = ((callend.get("wrap") if isinstance(callend, dict) else None) or {})\n'
     '    closed_by_words = closed\n'
     '    if _wrap_plan.get("planned") and turns and not closed:\n'
     '        closed = bool(turns[-1][0] in ("A", "B", "D", "S"))\n'
     '    # A sign-off is not a resolution if the hosts spend the final two turns\n', 1),
    ("callend-report",
     '        "plot": _plot_id,                                        # #1157\n    }\n',
     '        "plot": _plot_id,                                        # #1157\n'
     '        "callend": s3_callend_report(callend, turns, closed_by_words),   # [s3-callend]\n'
     '    }\n', 1),
    ("site-regrade",
     '        topic=str(meta.get("topic") or ""), source_script=source,\n',
     '        callend=meta.get("callend"),                                  # [s3-callend] site-regrade\n'
     '        topic=str(meta.get("topic") or ""), source_script=source,\n', 1),
    ("site-log",
     '            transcript, str(entry.get("name") or ""), include_shelf=False,\n',
     '            transcript, str(entry.get("name") or ""), include_shelf=False,\n'
     '            callend=entry.get("callend"),                             # [s3-callend] site-log\n', 1),
    ("site-live",
     '                include_shelf=False, topic=str(meta.get("topic") or ""),\n',
     '                callend=meta.get("callend"),                          # [s3-callend] site-live\n'
     '                include_shelf=False, topic=str(meta.get("topic") or ""),\n', 1),
    ("site-banter",
     '            topic=str((call_meta or {}).get("topic") or ""),\n            speakerbox_text=str(\n',
     '            callend=(call_meta or {}).get("callend"),                 # [s3-callend] site-banter\n'
     '            topic=str((call_meta or {}).get("topic") or ""),\n            speakerbox_text=str(\n', 1),
    ("site-rewrite",
     '                    topic=str((call_meta or {}).get("topic") or ""),\n',
     '                    callend=(call_meta or {}).get("callend"),         # [s3-callend] site-rewrite\n'
     '                    topic=str((call_meta or {}).get("topic") or ""),\n', 1),
    ("site-review",
     '            include_shelf=True,\n            topic=str(meta.get("topic") or ""),\n',
     '            include_shelf=True,\n'
     '            callend=meta.get("callend"),                              # [s3-callend] site-review\n'
     '            topic=str(meta.get("topic") or ""),\n', 1),
    ("callend-angle",
     '            _beat_sheet, _dice_rolls = "", []\n',
     '            _beat_sheet, _dice_rolls = "", []\n'
     '        # [s3-callend] how this call ends was rolled: the angle\'s own ending gives way to the\n'
     '        # running order\'s (a call the roulette ended EARLY is the [s3-events] block\'s, below)\n'
     '        if (caller_name and isinstance(call_meta, dict) and isinstance(call_meta.get("callend"), dict)\n'
     '                and not call_meta.get("ended")):\n'
     '            angle = s3_callend_angle(angle, call_meta["callend"])\n', 1),
    ("callend-topic",
     '            _topic_ad = topic_adherence(\n                _turns_seen, str((call_meta or {}).get("topic") or ""))\n',
     '            _topic_ad = topic_adherence(                              # [s3-callend] without the rolled end\n'
     '                s3_callend_topic_turns(_turns_seen, call_meta), str((call_meta or {}).get("topic") or ""))\n', 1),
    ("callend-topic-final",
     '            _topic_final = topic_adherence(\n                banter_turns(script or "", caller_name, caller2_name),\n',
     '            _topic_final = topic_adherence(                           # [s3-callend] without the rolled end\n'
     '                s3_callend_topic_turns(banter_turns(script or "", caller_name, caller2_name), call_meta),\n', 1),
    ("callend-ended",
     '    outcome = str(rule.get("text") or "")\n    short = " ".join(outcome.split())\n',
     '    outcome = str(rule.get("text") or "")\n    short = " ".join(outcome.split())\n'
     '    # [s3-callend] a call whose end System 3 rolled ended for THAT reason: the booth row and\n'
     '    # the call log say the roll (the ending shelf\'s line was cut from the call\'s prompt)\n'
     '    _s3_end = live["meta"].get("callend") if isinstance(live["meta"].get("callend"), dict) else {}\n'
     '    if _s3_end.get("planned") and _s3_end.get("says"):\n'
     '        outcome = "System 3: " + str(_s3_end["says"])\n'
     '        short = " ".join(outcome.split())\n', 1),
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
