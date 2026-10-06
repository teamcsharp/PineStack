"""Read-only, cached census of all retained System 3 roulette/dice events.

Runs on the glass worker thread. STATION observations are authoritative;
STATION decision copies are excluded so each physical roll counts once.
"""
import json
import sqlite3
import threading
import time
import zlib
from collections import Counter
from contextlib import closing
from pathlib import Path

_LOCK = threading.Lock()
_CACHE = {}


def _top(counter, most=6):
    rows = [{"label": label, "value": count} for label, count in counter.most_common(most)]
    rest = sum(counter.values()) - sum(r["value"] for r in rows)
    if rest:
        rows.append({"label": "Other results", "value": rest})
    return rows


def roulette_history(path):
    """No writes, no runtime store lock, no scan on the audio event loop."""
    key = str(Path(path).resolve())
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        prior = cached[2] if cached else None
        outcomes, families, dice = Counter(), Counter(), Counter()
        events = skipped = rolls = cursor = 0
        oldest = newest = None
        uri = Path(key).as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            first, head = db.execute("SELECT MIN(id),MAX(id) FROM events").fetchone()
            retained = db.execute("SELECT COUNT(*) FROM events WHERE id<=?",
                                  (prior["cursor"] if prior else (head or 0),)).fetchone()[0]
            if prior and prior["first"] == first and retained == prior["retained"] and (head or 0) >= prior["cursor"]:
                outcomes, families, dice = prior["outcomes"].copy(), prior["families"].copy(), prior["dice"].copy()
                events, skipped, rolls, cursor = prior["events"], prior["skipped"], prior["rolls"], prior["cursor"]
                oldest, newest = prior["oldest"], prior["newest"]
            for rid, family, at, blob in db.execute(
                "SELECT id,family,at,body FROM events WHERE id>? AND ("
                "(kind='decision' AND family!='STATION') OR "
                "(kind='observation' AND family='STATION')) ORDER BY id", (cursor,)
            ):
                cursor = rid
                events += 1
                oldest = at if oldest is None else min(oldest, at)
                newest = at if newest is None else max(newest, at)
                try:
                    ev = json.loads(zlib.decompress(blob))
                    if family == "STATION":
                        label = ev.get("picked")
                        if "hit" in ev:
                            label = "hit" if ev["hit"] else "miss"
                        label = label or ev.get("index")
                        scope = ev.get("key") or ev.get("label") or "Station"
                        draws = [ev]
                    else:
                        selected = ev.get("selected") or {}
                        label = selected.get("label") or selected.get("id")
                        scope = family or "Unknown family"
                        draws = [stage.get("draw") for stage in ev.get("stages") or []]
                        # Staged draws and the event RNG may describe the same draw.
                        if not any(isinstance(d, dict) and d.get("dice") is not None for d in draws):
                            draws = [ev.get("rng")]
                    recorded = any(isinstance(d, dict) and isinstance(d.get("dice"), (int, float))
                                   and not isinstance(d.get("dice"), bool) and 1 <= d["dice"] <= 100 for d in draws)
                    if recorded and label is not None and str(label):
                        outcomes[str(scope) + " / " + str(label)] += 1
                    for draw in draws:
                        if not isinstance(draw, dict):
                            continue
                        value = draw.get("dice")
                        if isinstance(value, (int, float)) and not isinstance(value, bool) and 1 <= value <= 100:
                            bucket = int((value - 1) // 10) * 10 + 1
                            dice["%d–%d" % (bucket, bucket + 9)] += 1
                            families[str(scope)] += 1
                            rolls += 1
                except (ValueError, TypeError, AttributeError, zlib.error):
                    skipped += 1
            retained = db.execute("SELECT COUNT(*) FROM events WHERE id<=?", (head or 0,)).fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            dialogue = {}
            if "conversations" in tables:
                dialogue["rows"] = [{"label": str(status or "Unspecified"), "value": count}
                                    for status, count in db.execute(
                                        "SELECT status,COUNT(*) FROM conversations GROUP BY status ORDER BY COUNT(*) DESC")]
                dialogue["conversations"] = sum(row["value"] for row in dialogue["rows"])
            if "lines" in tables:
                dialogue["lines"] = db.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
        value = {"readable": True, "at": time.time(), "oldest_at": oldest,
                 "newest_at": newest, "events": events, "rolls": rolls,
                 "skipped": skipped, "outcome_total": sum(outcomes.values()),
                 "outcomes": _top(outcomes), "families": _top(families), "dialogue": dialogue,
                 "dice": [{"label": "%d–%d" % (i, i + 9), "value": dice["%d–%d" % (i, i + 9)]}
                          for i in range(1, 101, 10)],
                 "basis": "All retained System 3 decisions and station roll observations. "
                          "Retired history is unavailable; station decision copies are excluded. "
                          "Dice counts include each recorded stage draw; results count selected outcomes."}
        _CACHE[key] = (time.monotonic(), value, {
            "first": first, "retained": retained, "cursor": head or cursor, "outcomes": outcomes, "families": families,
            "dice": dice, "events": events, "skipped": skipped, "rolls": rolls,
            "oldest": oldest, "newest": newest})
        return value


def station_history(namespace):
    try:
        runtime = getattr(namespace.get("system3_dice_live"), "__self__", None)
        if runtime is None or not runtime.ready:
            return {"readable": False, "why": "System 3 ledger is not loaded"}
        value = dict(roulette_history(runtime.store.path))
        value["mode"] = runtime.settings.get("mode")
        return value
    except Exception as exc:
        return {"readable": False, "why": "Roulette history unavailable (%s)" % type(exc).__name__}
