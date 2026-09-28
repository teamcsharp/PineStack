"""[s3-cast] The Mind desk's note book and the thumbs-up become System 3 tables.

Operator, 2026-09-27, finding "LIVE MIND ADJUSTMENTS FOR THIS CHARACTER" in a
System 3 prompt: "Even 'favorites' should be in the reply roulette wheel able
to access with RNG and then a subsequent roulette scroll can bring up 'my
favorite lines' for suggestion NOT repeat in dialogue ... unifying everything
into a controllable and randomized fashion with full accountability."

What stood here: mind_adjustment_prompt() stapled up to twelve notes onto the
persona in dj_line (every single line) and dj_deep_round (and through its
angle, banter) - no roll, no odds, no Rolodex record. The thumbs-up wrote
"The operator liked this line of yours ... say things like it, and you may
repeat it" into that book.

app.py edits:
  dj-line / deep-round   the notes are gone from both prompts; System 3's
                         FAV1 / DIRECTIVE1 rolls land on one turn of the sheet
  directives-helper      mind_adjustment_prompt is replaced by
                         _s3_directives_for(role): the seat's DIRECTIVE1 rows,
                         read-only, for the Mind desk and the prompt tracer
  topology-state         the Mind desk shows those rows
  topology-adjust        its note book is retired: 410, pointing at the table
  tracer / tracer-text   the line inspector reports directives, not notes
  vote-up / vote-down    a thumbs-up is a FAV1 row (system3_favorite); a
                         thumbs-down takes it off the wheel
  battle-gate / -api     THE BATTLE (#1090) rode every scheduled round's
                         SCHEDULE clause; it rides only while a crystal is on
                         and the tint pass is wanted (dialogue_tint_wanted)
  panel-adjust / -heading
                         the Mind desk's buttons open System 3 > Tables >
                         DIRECTIVE1 (system3Open("tables:DIRECTIVE1"); the
                         module is served no-cache, so no ?v= bump)

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes
LF atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("dj-line",
     r'''                f"{radio_persona('host', dj['persona'])}{mind_adjustment_prompt('dj')}"
''',
     r'''                f"{radio_persona('host', dj['persona'])}"   # [s3-cast] notes are FAV1/DIRECTIVE1 rolls on the sheet
''', 1),
    ("deep-round",
     r'''        f"HOST A — {host}: {dj['persona']}{mind_adjustment_prompt('dj')}\n\n"
        f"HOST B — {dj['cohost_name']}: {dj['cohost_persona']}{mind_adjustment_prompt('cohost')}\n\n"
''',
     r'''        # [s3-cast] no Mind desk notes: the favourites and directives are System 3 rolls
        f"HOST A — {host}: {dj['persona']}\n\n"
        f"HOST B — {dj['cohost_name']}: {dj['cohost_persona']}\n\n"
''', 1),
    ("directives-helper",
     r'''def mind_adjustment_prompt(who: str = "dj") -> str:
    """Operator-authored live directives for the cast, visible in Mind Topology."""
    rows = (dj_settings().get("mind_adjustments") or {}).get(who) or []
    notes = [str(row.get("text") or "").strip() for row in rows
             if isinstance(row, dict) and str(row.get("text") or "").strip()]
    return ("\n\nLIVE MIND ADJUSTMENTS FOR THIS CHARACTER: "
            + " | ".join(notes[:12])) if notes else ""
''',
     r'''def _s3_directives_for(role: str = "dj") -> list[dict[str, Any]]:
    """[s3-cast] The operator's directives for a seat as System 3 holds them
    (DIRECTIVE1 and any other DIRECTIVE table, edited in its Tables tab):
    what the Mind desk and the line inspector show, read-only. The Mind
    desk's own note book is retired - it reached every host prompt as "LIVE
    MIND ADJUSTMENTS" with no roll and no record; each row is a roll now,
    with its own odds, landing on one turn."""
    cat = {"dj": "host", "host": "host", "cohost": "cohost", "third": "third"}.get(str(role or ""))
    if not cat:
        return []
    try:
        getter = globals().get("_system3")
        config = getter().config if callable(getter) else {}
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    for table in (config or {}).get("tables") or []:
        if not isinstance(table, dict) or table.get("family") != "DIRECTIVE" or table.get("enabled") is False:
            continue
        for c in table.get("categories") or []:
            if not isinstance(c, dict) or c.get("id") not in (cat, "cast"):
                continue
            for it in c.get("items") or []:
                if isinstance(it, dict) and str(it.get("text") or "").strip():
                    out.append({"id": str(it.get("id") or ""), "text": str(it["text"]),
                                "odds": it.get("odds", 1.0), "enabled": it.get("enabled", True) is not False,
                                "table": str(table.get("id") or ""), "category": str(c.get("id") or ""),
                                "source": "System 3 " + str(table.get("id") or "")})
    return out
''', 1),
    ("topology-state",
     r'''"adjustments": (dj.get("mind_adjustments") or {}).get(role, [])''',
     r'''"adjustments": _s3_directives_for(role)''', 1),
    ("topology-adjust",
     r'''    require_auth(authorization)
    payload = await request.json(); role = str(payload.get("role") or "").strip()
    if role not in ("dj", "cohost", "third", "caller", "manager", "customer"):
        raise HTTPException(status_code=400, detail="Unknown cast role")
    settings = load_settings(); bucket = settings.setdefault("dj", {}).setdefault("mind_adjustments", {}); rows = [row for row in (bucket.get(role) or []) if isinstance(row, dict)]
    item_id = str(payload.get("id") or "")[:32]
    if str(payload.get("action") or "add") == "delete": rows = [row for row in rows if str(row.get("id") or "") != item_id]
    else:
        note = str(payload.get("text") or "").strip()[:500]
        if not note: raise HTTPException(status_code=400, detail="Write a directive")
        found = next((row for row in rows if str(row.get("id") or "") == item_id), None)
        if found: found["text"] = note
        else: rows.append({"id": uuid.uuid4().hex[:8], "text": note, "source": "Mind Topology"})
    bucket[role] = rows[:24]; save_settings(settings)
    return mind_topology_state()
''',
     r'''    require_auth(authorization)
    # [s3-cast] the Mind desk's note book is retired: a directive is a row of
    # System 3's DIRECTIVE1 table - its own odds, a lifetime, one turn per hit,
    # every hit in the Rolodex - edited in System 3's Tables tab
    raise HTTPException(status_code=410, detail="Directives live in System 3 now: open System 3 > Tables > "
                                                "DIRECTIVE1 (odds per row, one turn per hit).")
''', 1),
    ("tracer",
     r'''    # mind adjustments for the seat
    try:
        notes = [r for r in ((dj.get("mind_adjustments") or {}).get(seat) or []) if isinstance(r, dict)]
        for n in notes[-6:]:
            t = str(n.get("text") or "")
            ap = in_prompt(t)
            put("mind_adjustments", "mind note (%s)" % (seat or "?"), t[:100], "the writing prompt", ap,
                "in the prompt as sent" if ap else "not in this prompt" if ap is False else "prompt not held")
    except Exception:  # noqa: BLE001
        pass
''',
     r'''    # [s3-cast] the seat's directives, as System 3 rolls them (DIRECTIVE1)
    try:
        for n in _s3_directives_for(seat)[:8]:
            t = str(n.get("text") or "")
            ap = in_prompt(t)
            put("mind_adjustments", "directive (%s, odds %s)" % (seat or "?", n.get("odds")), t[:100],
                "the writing prompt", ap,
                "it rolled onto a turn of this prompt" if ap else "it did not come up for this prompt"
                if ap is False else "prompt not held")
    except Exception:  # noqa: BLE001
        pass
''', 1),
    ("tracer-text",
     r'''        "mind_adjustments": "this is one recorded mind note; the Mind desk owns the ordered note book",
''',
     r'''        "mind_adjustments": "this is a System 3 directive; its odds and lifetime are edited in System 3 > Tables > DIRECTIVE1",   # [s3-cast]
''', 1),
    ("vote-up",
     r'''            elif seat in ("dj", "cohost", "third"):
                try:
                    settings = load_settings()
                    bucket = settings.setdefault("dj", {}).setdefault("mind_adjustments", {})
                    rows = [r for r in (bucket.get(seat) or []) if isinstance(r, dict)]
                    note = ("The operator liked this line of yours: \"%s\" - say things like "
                            "it, and you may repeat it." % text[:300])
                    if not any(str(r.get("text") or "") == note for r in rows):
                        rows.append({"id": uuid.uuid4().hex[:8], "text": note, "at": now, "liked_line": line_id})
                    bucket[seat] = rows[-40:]
                    save_settings(settings)
                    said.append("added to the %s's repertoire" % ("host" if seat == "dj" else "co-host" if seat == "cohost" else "third seat"))
                except Exception as exc:  # noqa: BLE001
                    said.append("the repertoire would not take it: %s" % str(exc)[:60])
''',
     r'''            elif seat in ("dj", "cohost", "third"):
                # [s3-cast] a liked line is a row on System 3's favourites wheel
                # (FAV1): the FAV roll may bring it up, and the writer is told to
                # say something new in its spirit - never stapled to a prompt,
                # never "you may repeat it"
                try:
                    _fav = globals().get("system3_favorite")
                    _dj = dj_settings()
                    _name = {"dj": _dj.get("host_name"), "cohost": _dj.get("cohost_name"),
                             "third": _dj.get("third_name")}.get(seat) or ""
                    got = (_fav(line_id, text, seat, str(_name)) if _fav
                           else {"changed": False, "why": "System 3 is not loaded"})
                    said.append("added to System 3's favourites wheel (FAV1)" if got.get("changed")
                                else "the favourites wheel is unchanged: %s" % (got.get("why") or "it is already there"))
                except Exception as exc:  # noqa: BLE001
                    said.append("the favourites wheel would not take it: %s" % str(exc)[:60])
''', 1),
    ("vote-down",
     r'''        if text and seat in ("dj", "cohost", "third"):
            try:
                settings = load_settings()
                bucket = settings.setdefault("dj", {}).setdefault("mind_adjustments", {})
                rows = [r for r in (bucket.get(seat) or []) if isinstance(r, dict) and str(r.get("liked_line") or "") != line_id]
                bucket[seat] = rows
                save_settings(settings)
            except Exception:  # noqa: BLE001
                pass
''',
     r'''        if text and seat in ("dj", "cohost", "third"):
            # [s3-cast] a thumbs-down takes the line off the favourites wheel
            try:
                _fav = globals().get("system3_favorite")
                if _fav and _fav(line_id, text, seat, liked=False).get("changed"):
                    said.append("taken off System 3's favourites wheel (FAV1)")
            except Exception:  # noqa: BLE001
                pass
''', 1),
    ("battle-gate",
     r'''def rap_battle_clause(up_next: str = "") -> str:
    """#1090: the battle paragraph, or nothing if it cannot be built.

    A failure here must never cost a round its prompt - the segment still
    has a job to do whether or not the thread is readable."""
    try:
        return _BATTLE.clause(up_next)
    except Exception:  # noqa: BLE001
        return ""
''',
     r'''def rap_battle_clause(up_next: str = "") -> str:
    """#1090: the battle paragraph, or nothing if it cannot be built.

    A failure here must never cost a round its prompt - the segment still
    has a job to do whether or not the thread is readable.

    [s3-cast] 2026-09-27, the operator, finding it in a System 3 prompt:
    "this should not be in the system prompt ... this needs to be delegated
    to when the crystal is enabled and tinting is present." The battle is
    the crystal tint's register, so it rides a prompt only while the tint
    pass is wanted - the tint content gate, a crystal switched on, the two
    passes and a coverage target: dialogue_tint_wanted(), the same test
    the tint's own roads key off."""
    try:
        if not dialogue_tint_wanted():
            return ""
        return _BATTLE.clause(up_next)
    except Exception:  # noqa: BLE001
        return ""
''', 1),
    ("battle-api",
     r'''        "clause": rap_battle_clause(),
''',
     r'''        "clause": rap_battle_clause(),
        "rides": dialogue_tint_wanted(),          # [s3-cast] only with a crystal on and the tint wanted
''', 1),
    ("panel-adjust",
     r'''  async function adjust(role,item,remove){if(!role)return; if(remove){await api("/api/mind/topology/adjust",{method:"POST",body:JSON.stringify({role,id:item.id,action:"delete"})});return refresh();} const text=prompt(item?"Update live directive":"Add live directive",item?item.text:""); if(text===null)return; await api("/api/mind/topology/adjust",{method:"POST",body:JSON.stringify({role,id:item&&item.id||"",text,action:item?"update":"add"})});refresh();}
''',
     r'''  async function adjust(role,item,remove){ /* [s3-cast] directives are System 3's: its Tables tab, DIRECTIVE1 */ if(typeof system3Open==="function") system3Open("tables:DIRECTIVE1"); }
''', 1),
    ("panel-heading",
     r'''const h=el("h4","","Live directives");''',
     r'''const h=el("h4","","Directives (System 3 · DIRECTIVE1)");''', 1),
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
