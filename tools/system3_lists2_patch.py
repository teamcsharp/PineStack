"""[s3-lists2] The DJ settings' lists and the evolved heat lines are desk
lists; the second caller's name is a desk row set; the heat seed rows' desk
weights reach their draw.

Operator's standing request (2026-09-28): every list that feeds conversation
or the roulette is an editable table ("Any list to do with conversation or
the roulette needs to be listed here as an editable table").

  registry  [s3-lists] LIST entries backed by their OWN stores - no POOLS1
            copy, so the desk and the DJ settings editor write one list:
              dj.intro_phrases, dj.station_ids, dj.request_phrases,
              dj.interject_phrases, dj.open_phrases (the phrase banks
              behind line.stock_phrase - five lists; "media" lines use the
              interject list), dj.sponsors (ad.sponsor, ad.break_sponsor,
              product placement), dj.diatribe_interjections (banter.
              interjections, System 3's INTERJECT) - settings.json "dj",
              read-modify-written under _WORD_DIAL_LOCK through
              save_settings (the DJ settings editor's own validation);
              heat.cool, heat.warm, heat.hot, heat.running_hot,
              heat.scorching - heat_lines.json by band, under _HEAT_LOCK as
              heat_evolve writes it (an unparsable file is refused, never
              overwritten with one band).
            Rows: bare words, id = the words' digest (a repeat gets -2, -3).
            Doors: add, edit, remove - no switch (neither store has one).
            Refused with the reason: words already on the list, an add past
            the DJ list's 40 (sponsors 20 - validation would drop the newest
            silently), removing a phrase bank's last row (empty brings the
            built-in list back). A heat add past 48 drops the band's oldest,
            as heat_evolve does.
  duo-name  call.duo_name: the whole NEW_VOICE_NAMES list is tabled
            (s3_pool, POOLS1 call.duo_name) and this call's filter - never
            the caller's own name, now case-blind - runs on the desk's rows,
            then System 3's pick with the desk's weights (the cast names'
            pattern). With the list as shipped, today's odds are unchanged.
  heat-key  heat_reference's pick is made under banter.heat_seed_<band> (was
            banter.heat_line), so the seed rows' desk weights reach it; an
            evolved line weighs 1.

Two of these lines are stored text of older tools, which this batch
reconciles (tools/edit_lists2_reconcile.py, the house's "[integration]"
block): system3_dice_patch.py 'call-duo-name-end' (duo-name) and
system3_dice_banter_patch.py 'heat-line' (heat-key). Apply this tool, then
install the reconciled tools; each then re-checks as applied.

Not done: sfxguy.id_shelf's row weights. Its draw line is stored text of two
tools already reconciled around each other (system3_roads_patch
'liner-fallback' carries system3_dice_sfx_patch 'id-shelf'), and its pick is
over the rows with {station} filled in, so the desk's weights would need
that line rewritten in both. Its on/off and words reach it already.

No engine, table or runtime file changes: ENGINE_VERSION, GOLDEN and the
pinned default-config hash do not move.

--check exits 0 ready / 2 applied / 1 missing. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

REGISTRY2 = ('# --- [s3-lists2] THE DJ-SETTINGS LISTS AND THE EVOLVED HEAT LINES ARE DESK LISTS\n'
             '# "Any list to do with conversation or the roulette needs to be listed here as\n'
             '# an editable table" (operator, 2026-09-28). [s3-lists] put the banks and the\n'
             "# book stores on the desk; these are the DJ settings' own lists and the heat\n"
             '# asides the model grows, registered the same way - against the store that\n'
             '# owns each, never copied onto POOLS1, so the desk and the DJ settings editor\n'
             '# write one list and neither overrides the other:\n'
             '#   the DJ settings document (settings.json "dj"), read-modify-written under\n'
             '#   _WORD_DIAL_LOCK as the word-cause doors write it, through save_settings,\n'
             "#   which validates it exactly as the DJ settings editor's save does;\n"
             '#   heat_lines.json, under _HEAT_LOCK as heat_evolve writes it.\n'
             '# The registry calls every door off the loop; a lock is held only for its\n'
             "# store's read-modify-write.\n"
             '_S3_DJ_LISTS = (\n'
             '    # (list id, the DJ-settings key, label, most rows, most characters,\n'
             '    #  fewest rows kept, what the desk says about it)\n'
             '    ("dj.intro_phrases", "intro_phrases", "DJ · Between tracks", 40, 300, 1,\n'
             '     "Stock phrases for introducing a record ({station}, {title} and {by} are filled in). When a line "\n'
             '     "falls back to a stock phrase, and as the example the writer riffs on, System 3 picks one of these "\n'
             '     "(line.stock_phrase); a kind of line with no list of its own uses this one. The DJ settings\' "\n'
             '     "\'Between tracks\' box is this same list. Empty, the station\'s built-in phrases come back, so the "\n'
             '     "last row stays."),\n'
             '    ("dj.station_ids", "station_ids", "DJ · Station identifications", 40, 300, 1,\n'
             '     "Stock station idents ({station} is filled in): System 3\'s pick when an ident falls back to a stock "\n'
             '     "phrase (line.stock_phrase). The DJ settings\' \'Station identifications\' box is this same list. "\n'
             '     "Empty, the built-in idents come back, so the last row stays."),\n'
             '    ("dj.request_phrases", "request_phrases", "DJ · When a request comes in", 40, 300, 1,\n'
             '     "Stock phrases for a listener\'s request ({title} and {by} are filled in): System 3\'s pick when the "\n'
             '     "line falls back to a stock phrase (line.stock_phrase). The DJ settings\' \'When a request comes in\' "\n'
             '     "box is this same list. Empty, the built-in phrases come back, so the last row stays."),\n'
             '    ("dj.interject_phrases", "interject_phrases", "DJ · Said in the middle of a track", 40, 300, 1,\n'
             '     "Stock things said over a record, and in reply to something shown: System 3\'s pick when the line "\n'
             '     "falls back to a stock phrase (line.stock_phrase). The DJ settings\' \'Said in the middle of a track\' "\n'
             '     "box is this same list. Empty, the built-in phrases come back, so the last row stays."),\n'
             '    ("dj.open_phrases", "open_phrases", "DJ · Opening the session", 40, 300, 1,\n'
             '     "The first thing said when the station comes on air, as a stock phrase: System 3\'s pick "\n'
             '     "(line.stock_phrase). The DJ desk\'s \'Opening the session\' card is this same list. Empty, the "\n'
             '     "built-in phrases come back, so the last row stays."),\n'
             '    ("dj.sponsors", "sponsors", "DJ · Products to place", 20, 200, 0,\n'
             '     "Who the station sells, one per line with as much detail as you like. A produced advert\'s product "\n'
             '     "(ad.sponsor) and a live break\'s sponsor (ad.break_sponsor) are System 3\'s picks among these, and "\n'
             '     "the first three can be worked into the banter as product placement. The DJ settings\' \'Products to "\n'
             '     "place\' box is this same list; empty, nothing is placed."),\n'
             '    ("dj.diatribe_interjections", "diatribe_interjections", "DJ · Diatribe interjections", 40, 300, 1,\n'
             '     "What the other one forces in edgewise while somebody is on a roll. Under System 3 its INTERJECT "\n'
             '     "roll draws from this list; otherwise the writer is offered up to eleven of them, sampled by "\n'
             '     "System 3\'s dice (banter.interjections). Empty, the built-in list comes back, so the last row "\n'
             '     "stays."),\n'
             ')\n'
             '_S3_DJ_LIST_BY_KEY = {row[1]: row for row in _S3_DJ_LISTS}\n'
             '\n'
             '\n'
             'def _s3_row_ids(rows: list[str]) -> list[str]:\n'
             '    """A bare-words list\'s row ids: the words\' digest, and \'-2\', \'-3\'... on a\n'
             "    repeat of the same words (the DJ settings' boxes allow one), so every\n"
             '    row can be reached."""\n'
             '    seen: dict[str, int] = {}\n'
             '    out = []\n'
             '    for text in rows:\n'
             '        base = _s3_list_id(text)\n'
             '        seen[base] = seen.get(base, 0) + 1\n'
             '        out.append(base if seen[base] == 1 else "%s-%d" % (base, seen[base]))\n'
             '    return out\n'
             '\n'
             '\n'
             'def _s3_words_change(rows: list[str], rid: str, text: Any, add: bool, most: int,\n'
             '                     chars: int, fewest: int) -> tuple[list[str], str]:\n'
             '    """One desk change to a bare-words list: (its new rows, the row\'s id).\n'
             '    New words that are already on the list (however spaced or cased) are\n'
             "    refused; so is an add past `most` - the store's own validation would\n"
             '    drop the newest row without a word - and a removal below `fewest`."""\n'
             '    rows = list(rows)\n'
             '    ids = _s3_row_ids(rows)\n'
             '    words = _s3_list_words(text, chars) if (add or text is not None) else ""\n'
             '    if words and _s3_list_id(words) in {_s3_list_id(r) for r, i in zip(rows, ids) if i != rid}:\n'
             '        raise ValueError("those words are already on the list")\n'
             '    if add:\n'
             '        if len(rows) >= most:\n'
             '            raise ValueError("the list holds %d at most - remove one first" % most)\n'
             '        rows.append(words)\n'
             '        return rows, _s3_list_id(words)\n'
             '    if rid not in ids:\n'
             '        raise KeyError(rid)\n'
             '    at = ids.index(rid)\n'
             '    if words:\n'
             '        rows[at] = words\n'
             '        return rows, _s3_row_ids(rows)[at]\n'
             '    if len(rows) <= fewest:\n'
             '        raise ValueError("the last row stays: empty, the station\'s built-in list comes back - "\n'
             '                         "rewrite it instead")\n'
             '    rows.pop(at)\n'
             '    return rows, rid\n'
             '\n'
             '\n'
             'def _s3_dj_rows(key: str) -> list[dict[str, Any]]:\n'
             '    """The list as the DJ settings hold it - what the air draws from."""\n'
             '    rows = [str(t) for t in ((load_settings().get("dj") or {}).get(key) or []) if str(t or "").strip()]\n'
             '    return [{"id": rid, "text": text} for rid, text in zip(_s3_row_ids(rows), rows)]\n'
             '\n'
             '\n'
             'def _s3_dj_change(key: str, rid: str = "", text: Any = None, add: bool = False) -> str:\n'
             '    _lid, _key, _label, most, chars, fewest, _what = _S3_DJ_LIST_BY_KEY[key]\n'
             '    with _WORD_DIAL_LOCK:\n'
             '        settings = load_settings()\n'
             '        dj = dict(settings.get("dj") or {})\n'
             '        rows, got = _s3_words_change(\n'
             '            [str(t) for t in (dj.get(key) or []) if str(t or "").strip()],\n'
             '            rid, text, add, most, chars, fewest)\n'
             '        dj[key] = rows\n'
             '        save_settings({**settings, "dj": dj})\n'
             '    return got\n'
             '\n'
             '\n'
             'def _s3_heat_store() -> dict[str, list[str]]:\n'
             '    """heat_lines.json as heat_evolve keeps it. A file that is there but will\n'
             '    not parse is refused: _heat_read answers {} for it, and one band written\n'
             '    over that would drop every other band\'s lines."""\n'
             '    try:\n'
             '        raw = HEAT_LINES_PATH.read_text()\n'
             '    except FileNotFoundError:\n'
             '        return {}\n'
             '    try:\n'
             '        got = json.loads(raw)\n'
             '    except ValueError as exc:\n'
             '        raise OSError("heat_lines.json will not parse (%s) - nothing written" % exc) from exc\n'
             '    if not isinstance(got, dict):\n'
             '        raise OSError("heat_lines.json is not a table of bands - nothing written")\n'
             '    return {str(k): [str(x) for x in v] for k, v in got.items() if isinstance(v, list)}\n'
             '\n'
             '\n'
             'def _s3_heat_rows(band: str) -> list[dict[str, Any]]:\n'
             '    rows = [str(t) for t in _heat_read().get(band, []) if str(t or "").strip()]\n'
             '    return [{"id": rid, "text": text} for rid, text in zip(_s3_row_ids(rows), rows)]\n'
             '\n'
             '\n'
             'def _s3_heat_change(band: str, rid: str = "", text: Any = None, add: bool = False) -> str:\n'
             '    """As heat_evolve grows a band: an add goes on the end and the band keeps\n'
             '    its newest _HEAT_MAX_PER_BAND, so a full band drops its oldest line."""\n'
             '    with _HEAT_LOCK:\n'
             '        data = _s3_heat_store()\n'
             '        rows, got = _s3_words_change(\n'
             '            [str(t) for t in data.get(band, []) if str(t or "").strip()],\n'
             '            rid, text, add, 10 ** 6, 200, 0)\n'
             '        data[band] = rows[-_HEAT_MAX_PER_BAND:]\n'
             '        _heat_write(data)\n'
             '    return got\n'
             '\n'
             '\n'
             'def _s3_lists2_register() -> None:\n'
             '    for lid, key, label, _most, chars, _fewest, what in _S3_DJ_LISTS:\n'
             '        _S3_LISTS.register({\n'
             '            "id": lid, "label": label, "family": "LIST", "store": "data/settings.json (dj.%s)" % key,\n'
             '            "what": what,\n'
             '            "schema": [{"key": "text", "kind": "text", "label": "one line, %d characters at most" % chars}],\n'
             '            "rows": lambda key=key: _s3_dj_rows(key),\n'
             '            "add": lambda body, key=key: _s3_dj_change(key, text=body.get("text"), add=True),\n'
             '            "edit": lambda rid, body, key=key: _s3_dj_change(\n'
             '                key, rid, body.get("text") if body.get("text") is not None else ""),\n'
             '            "remove": lambda rid, key=key: _s3_dj_change(key, rid),\n'
             '        })\n'
             '    low = None\n'
             '    for ceiling, band in HEAT_BANDS:\n'
             '        key = band.replace(" ", "_")\n'
             '        span = ("under %d C" % ceiling if low is None else "from %d C" % low if ceiling >= 999\n'
             '                else "%d to %d C" % (low, ceiling))\n'
             '        low = ceiling\n'
             '        _S3_LISTS.register({\n'
             '            "id": "heat." + key, "label": "Heat asides · " + band, "family": "LIST",\n'
             '            "store": "data/heat_lines.json (%s)" % band,\n'
             '            "what": ("Asides about how hot the machine is running while it is %s (%s). The model writes "\n'
             '                     "these as it runs (heat_evolve, about every 25 minutes) and the band keeps its newest "\n'
             '                     "%d - an add here past that drops the oldest too. A host lets one slip mid-round and "\n'
             '                     "callers reach for them in heat jokes: System 3 picks among these and the seed "\n'
             '                     "imagery, which is in Tables (POOLS1 banter.heat_seed_%s)."\n'
             '                     % (band, span, _HEAT_MAX_PER_BAND, key)),\n'
             '            "schema": [{"key": "text", "kind": "text", "label": "one aside, 200 characters at most"}],\n'
             '            "rows": lambda band=band: _s3_heat_rows(band),\n'
             '            "add": lambda body, band=band: _s3_heat_change(band, text=body.get("text"), add=True),\n'
             '            "edit": lambda rid, body, band=band: _s3_heat_change(\n'
             '                band, rid, body.get("text") if body.get("text") is not None else ""),\n'
             '            "remove": lambda rid, band=band: _s3_heat_change(band, rid),\n'
             '        })\n'
             '\n'
             '\n'
             '_s3_lists2_register()\n')

EDITS = [
    ('registry',
     ('def _sfxguy_key(line: str) -> str:\n'
      '    return hashlib.sha1(line.strip().lower().encode()).hexdigest()[:12]\n'),
     REGISTRY2 + '\n\n' + ('def _sfxguy_key(line: str) -> str:\n'
      '    return hashlib.sha1(line.strip().lower().encode()).hexdigest()[:12]\n'), 1),
    ('duo-name',
     ('            [n for n in NEW_VOICE_NAMES if n != caller.get("name")]\n'
      '            or list(NEW_VOICE_NAMES), "the second person\'s name", tabled=False)\n'),
     ('            # [s3-lists2] the whole name list is a POOLS1 row set the desk may edit;\n'
      "            # this call's filter - never the caller's own name - runs on the desk's rows\n"
      '            [n for n in s3_pool("call.duo_name", NEW_VOICE_NAMES, "the second person\'s name")\n'
      '             if n.casefold() != str(caller.get("name") or "").casefold()]\n'
      '            or s3_pool("call.duo_name", NEW_VOICE_NAMES, "the second person\'s name"),\n'
      '            "the second person\'s name", tabled=False)\n'), 1),
    ('heat-key',
     '                      director=_S3Dice("banter.heat_line", "which heat aside is let slip"))   # [s3-dice-door]\n',
     ("                      # [s3-lists2] picked under the band's POOLS1 key, so the seed rows'\n"
      '                      # desk weights reach the draw (an evolved line weighs 1)\n'
      '                      director=_S3Dice("banter.heat_seed_" + band.replace(" ", "_"),\n'
      '                                       "which heat aside is let slip"))   # [s3-dice-door]\n'), 1),
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
