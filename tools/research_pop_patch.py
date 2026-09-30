"""[research-pop] what the online research found, and the operator's say over it.

2026-09-30, the operator (tapping "Response based on online research / LLM
query for rebuttal" in a line's rolls): "I wanna see a pop up whenever I
tap on it that shows the top five results and how it acted on them. Also
allow me to tap on those entries and choose how they are affected by it in
the future."

Measured first: that entry did NO research - it carried only "rebuts it
with the facts as they know them" (system3_tables.py gains requires:
research, so it lands only with research in hand, and carries it). The
research that did exist (_s3_research_fetch, for "Online search with
searxng") kept three snippets and the first URL in memory, so nothing could
show five results or say what became of them.

Now each search keeps its top five results on disk (data/s3_research.json)
with a verdict each: handed to the host, not used and why, or refused by the
operator. data/s3_research_prefs.json holds the operator's word per site -
prefer (ranked first), normal, never (never handed to the host) - and every
later search obeys it. Roads: GET /api/system3/research?key=,
GET|POST /api/system3/research/pref.

Usage (ON THE HOST): python3 tools/research_pop_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[research-pop]"

OLD_FETCH = '''async def _s3_research_fetch(key: str, query: str) -> None:
    """What people online are saying about a subject: searched once, in the
    background - never on the planner's clock - and kept for the next round
    on the same subject."""
    got: list[dict[str, str]] = []
    try:
        got = await asyncio.wait_for(search_searxng(query), timeout=20.0)
    except Exception:  # noqa: BLE001
        got = []
    finally:
        _S3_RESEARCH_BUSY.discard(key)
    lines = []
    for row in got or []:
        said = " ".join(str(row.get("snippet") or row.get("title") or "").split())
        if said:
            lines.append(said[:260])
        if len(lines) >= 3:
            break
    _S3_RESEARCH[key] = {"at": time.time(), "text": " / ".join(lines),
                         "ref": str((got[0] if got else {}).get("url") or "")[:160]}
    while len(_S3_RESEARCH) > 200:
        _S3_RESEARCH.pop(next(iter(_S3_RESEARCH)))
'''

NEW_FETCH = '''# [research-pop] every search keeps its top five, what became of each, and
# the operator's word per site (prefer / normal / never) for the next one.
S3_RESEARCH_PATH = data_path("s3_research.json")
S3_RESEARCH_PREFS_PATH = data_path("s3_research_prefs.json")
S3_RESEARCH_SHOWN = 5          # what the popup shows
S3_RESEARCH_HANDED = 3         # what the host is handed
_S3_RESEARCH_LOCK = RLock()
_S3_RESEARCH_LOADED = {"done": False}


def s3_research_domain(url: str) -> str:
    got = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#:]+)", str(url or "").strip().lower())
    host = got.group(1) if got else ""
    return host[4:] if host.startswith("www.") else host


def s3_research_prefs() -> dict[str, str]:
    try:
        raw = json.loads(S3_RESEARCH_PREFS_PATH.read_text(encoding="utf-8"))
        doms = raw.get("domains") if isinstance(raw, dict) else {}
        return {str(k): str(v) for k, v in (doms or {}).items() if v in ("prefer", "never")}
    except Exception:  # noqa: BLE001
        return {}


def s3_research_pref_set(domain: str, pref: str) -> dict[str, str]:
    domain = s3_research_domain("x://" + str(domain or "").strip().lower()) or str(domain or "").strip().lower()
    with _S3_RESEARCH_LOCK:
        doms = s3_research_prefs()
        if pref in ("prefer", "never"):
            doms[domain] = pref
        else:
            doms.pop(domain, None)
        S3_RESEARCH_PREFS_PATH.write_text(json.dumps({"domains": doms}, indent=1), encoding="utf-8")
    return doms


def _s3_research_load() -> None:
    """The kept searches come back after a restart."""
    if _S3_RESEARCH_LOADED["done"]:
        return
    _S3_RESEARCH_LOADED["done"] = True
    try:
        kept = json.loads(S3_RESEARCH_PATH.read_text(encoding="utf-8"))
        for k, v in (kept or {}).items():
            if isinstance(v, dict):
                _S3_RESEARCH.setdefault(k, v)
    except Exception:  # noqa: BLE001
        pass


def _s3_research_save() -> None:
    try:
        with _S3_RESEARCH_LOCK:
            S3_RESEARCH_PATH.write_text(json.dumps(dict(list(_S3_RESEARCH.items())[-200:])), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def s3_research_judge(got: list[dict[str, Any]], prefs: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The top five, each with what became of it, and the lines handed on."""
    rows = []
    for n, row in enumerate(got or []):
        url = str(row.get("url") or "")
        rows.append({"n": n + 1, "title": " ".join(str(row.get("title") or "").split())[:200],
                     "url": url[:400], "domain": s3_research_domain(url),
                     "snippet": " ".join(str(row.get("snippet") or "").split())[:400]})
    # the operator's preferred sites first, the search's own order otherwise
    rows.sort(key=lambda r: (0 if prefs.get(r["domain"]) == "prefer" else 1, r["n"]))
    rows = rows[:S3_RESEARCH_SHOWN]
    lines: list[str] = []
    for r in rows:
        pref = prefs.get(r["domain"], "")
        said = r["snippet"] or r["title"]
        if pref == "never":
            r["verdict"], r["why"] = "refused", "not used - you said never use %s" % r["domain"]
        elif not said:
            r["verdict"], r["why"] = "empty", "not used - it had no words to quote"
        elif len(lines) >= S3_RESEARCH_HANDED:
            r["verdict"], r["why"] = "spare", "not used - the host is handed only the top %d" % S3_RESEARCH_HANDED
        else:
            lines.append(said[:260])
            r["verdict"] = "used"
            r["why"] = ("handed to the host as what people online are saying"
                        + (" - ranked first because you prefer %s" % r["domain"] if pref == "prefer" else ""))
        r["pref"] = pref or "normal"
    return rows, lines


async def _s3_research_fetch(key: str, query: str) -> None:
    """What people online are saying about a subject: searched once, in the
    background - never on the planner's clock - and kept for the next round
    on the same subject. [research-pop] the top five are kept, judged and
    saved, and the operator's site preferences decide what is handed on."""
    got: list[dict[str, str]] = []
    try:
        got = await asyncio.wait_for(search_searxng(query), timeout=20.0)
    except Exception:  # noqa: BLE001
        got = []
    finally:
        _S3_RESEARCH_BUSY.discard(key)
    _s3_research_load()
    rows, lines = s3_research_judge(got, s3_research_prefs())
    first = next((r for r in rows if r.get("verdict") == "used"), None)
    _S3_RESEARCH[key] = {"at": time.time(), "key": key, "query": str(query or "")[:200],
                         "text": " / ".join(lines), "ref": (first or {}).get("url", "")[:160],
                         "results": rows, "found": len(got or [])}
    while len(_S3_RESEARCH) > 200:
        _S3_RESEARCH.pop(next(iter(_S3_RESEARCH)))
    _s3_research_save()


@app.get("/api/system3/research")
async def s3_research_api(key: str = "", authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[research-pop] one search: its top five, what became of each, the
    words the host was handed, and the operator's word per site."""
    require_read_auth(authorization)
    _s3_research_load()
    held = _S3_RESEARCH.get(str(key or "")) or {}
    prefs = s3_research_prefs()
    rows = [dict(r, pref=prefs.get(r.get("domain", ""), "normal")) for r in (held.get("results") or [])]
    return {"ok": bool(held), "key": key, "query": held.get("query", ""), "at": held.get("at", 0),
            "found": held.get("found", len(rows)), "handed": held.get("text", ""), "results": rows,
            "say": "" if held else "that search is no longer kept"}


@app.get("/api/system3/research/pref")
async def s3_research_pref_get_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    return {"ok": True, "domains": s3_research_prefs()}


@app.post("/api/system3/research/pref")
async def s3_research_pref_api(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[research-pop] the operator's word on a site: prefer, normal or never."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    domain = str((body or {}).get("domain") or "").strip().lower()
    pref = str((body or {}).get("pref") or "normal")
    if not domain or pref not in ("prefer", "normal", "never"):
        return {"ok": False, "say": "name a site and prefer, normal or never"}
    doms = s3_research_pref_set(domain, pref)
    word = {"prefer": "comes first in every search from now on",
            "never": "is never handed to the host again",
            "normal": "is back to normal"}[pref]
    note_action("research: %s %s [research-pop]" % (domain, word))
    return {"ok": True, "domains": doms, "say": "%s %s" % (domain, word)}
'''

EDITS = [
    ("fetch", OLD_FETCH, NEW_FETCH),
    ("material key",
     '''                    out["research"] = {"text": held["text"], "label": "what people online are saying",
                                       "ref": str(held.get("ref") or "")}
''',
     '''                    out["research"] = {"text": held["text"], "label": "what people online are saying",
                                       "ref": str(held.get("ref") or ""), "key": key}   # [research-pop]
'''),
    ("material load",
     '''        key = _s3_research_key(topic)
        if key and settings_web_search():
''',
     '''        key = _s3_research_key(topic)
        _s3_research_load()                                     # [research-pop] kept across restarts
        if key and settings_web_search():
'''),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        assert n == 1, "%s: anchor found %d times" % (label, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-research-pop")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
