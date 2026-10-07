"""[wave-g] The Hour Director: System 3's station core for the hour.

System 2 used to own the clock's plan, the allocation of finished rounds to
entries, and the kitchen's jobs. Under engine "system3" System 2 idles
(system2_runtime enabled is False) and this module answers the chain's two
questions instead: what does the running entry name, and which finished
round of the cupboard airs for it.

The module keeps no store of the hour of its own. The hour is read off the
running order (schedule_read / schedule_hour_slots); the clock is the legacy
schedule_take(); the doors are the ones that exist (schedule_extra_round for
the segment door, the record pin, the ad road, _ready_shelf_air with a
pick). Every station roll goes through System 3's dice (s3_weighted /
s3_chance) with the weights of the HOUR tables, and every ask is written on
the round ledger, kept 48 hours in data/system3_hour_ledger.json.

Everything the director touches arrives through `host` (the app's globals
in production, a fake in the tests), so the decisions can be proven without
the station.
"""
import json
import random
import time
from pathlib import Path

import system3_tables

ENGINES = ("legacy", "system2", "system3")
DYNAMIC_KINDS = ("book_time", "sfx_supercut")
# the kinds the running order names that the existing doors answer themselves
EXTRA_KINDS = ("record", "ad", "track_talk", "banter_caller", "recap")
LEDGER_FILE = "system3_hour_ledger.json"
LEDGER_KEEP_SECONDS = 48 * 3600
LEDGER_SAVE_EVERY = 5.0
LEDGER_ROWS_PER_HOUR = 400
DRAW_KEYS = ("silent", "quota", "jam")
HOUR_KEY_FORMAT = "%Y-%m-%dT%H"
FALLBACK_ROAD = {"track_talk": "track_talk", "ad": "ad", "manager": "manager", "caller": "caller",
                 "banter_caller": "caller", "bombshell": "ad", "gallery": "gallery", "banter": "banter",
                 "book_time": "banter", "sfx_supercut": "sfx_supercut", "news": "news"}


# --- pure helpers (no host needed) -----------------------------------------------

def leg_walk(rows, start, prompt_of=None, road_of=None):
    """The hour's legs in order: each enabled entry, its minutes, and the
    wall-clock start and deadline counted from the top of the hour."""
    legs = []
    at = float(start)
    live = [r for r in (rows or []) if isinstance(r, dict) and r.get("enabled", True)]
    for index, slot in enumerate(live):
        kind = str(slot.get("kind") or "")
        minutes = max(0.25, float(slot.get("minutes") or 3))
        road = str((road_of or (lambda k: FALLBACK_ROAD.get(k, k)))(kind) or kind)
        legs.append({
            "id": str(slot.get("id") or ""),
            "label": str(slot.get("label") or kind),
            "kind": kind,
            "road": road,
            "minutes": minutes,
            "act": str((prompt_of or (lambda s: ""))(slot) or ""),
            "dynamic_kind": kind if kind in DYNAMIC_KINDS else "",
            "start": at,
            "deadline": at + minutes * 60.0,
            "place": "open" if index == 0 else ("close" if index == len(live) - 1 else "middle"),
            "track_id": str(slot.get("track_id") or ""),
        })
        at += minutes * 60.0
    return legs


def quota_multipliers(planned, aired, gains):
    """HOUR2: how far behind pace each kind is, as a multiplier on its draw.
    behind = the share of the kind's planned legs not yet aired this hour;
    multiplier = 1 + gain * behind. A kind the sheet never plans is not behind."""
    out = {}
    for kind, gain in (gains or {}).items():
        want = int((planned or {}).get(kind, 0) or 0)
        got = int((aired or {}).get(kind, 0) or 0)
        behind = max(0, want - got) / float(want) if want > 0 else 0.0
        out[str(kind)] = round(1.0 + max(0.0, float(gain or 0)) * behind, 4)
    return out


def silent_weights(items, multipliers):
    """HOUR1 weight of each kind, times its HOUR2 pressure."""
    return [max(0.0, float(i.get("weight", 1.0) or 0)) * float((multipliers or {}).get(i["id"], 1.0))
            for i in items]


def book_weight(row_at, now, deadline, near_seconds=900.0):
    """Waiting age (hours, capped at six) plus deadline nearness (double inside
    fifteen minutes of the leg's deadline)."""
    try:
        stamp = float(row_at or 0)
    except (TypeError, ValueError):
        stamp = 0.0
    age = max(0.0, float(now) - stamp) / 3600.0 if stamp > 0 else 0.0
    weight = 1.0 + min(6.0, age)
    if deadline and float(deadline) - float(now) < near_seconds:
        weight *= 2.0
    return round(weight, 4)


def ledger_prune(hours, now, keep_seconds=LEDGER_KEEP_SECONDS, epoch_of=None):
    """Drop the hours older than the keep window. `hours` is a dict, pruned in place."""
    cutoff = float(now) - float(keep_seconds)
    for key in list(hours):
        at = (epoch_of or (lambda k: -1.0))(key)
        if 0 <= at < cutoff:
            hours.pop(key, None)
    return hours


def _items(table, category=""):
    out = []
    for cat in (table or {}).get("categories") or []:
        if not isinstance(cat, dict) or (category and cat.get("id") != category):
            continue
        for item in cat.get("items") or []:
            if isinstance(item, dict) and item.get("id"):
                out.append(dict(item, category=str(cat.get("id") or "")))
    return out


def engine_say(engine, fallback):
    if engine == "system3":
        tail = ("the legacy chain serves what the director leaves" if fallback
                else "nothing serves what the director leaves")
        return "System 3's Hour Director runs the hour; System 2 stands down; " + tail + "."
    if engine == "system2":
        return "System 2 runs the hour (the legacy chain behind it)."
    return "The legacy chain runs the hour; System 2 and System 3's director are off."


# --- the director -----------------------------------------------------------------

class _Attrs:
    """Reads the host's attributes by name, quietly: a missing door is None."""

    def __init__(self, host):
        self.host = host

    def get(self, name, default=None):
        try:
            return getattr(self.host, name, default)
        except Exception:  # noqa: BLE001
            return default


class HourDirector:
    def __init__(self, host, ledger_path=None, clock=None):
        self.host = host
        self.h = _Attrs(host)
        self._clock = clock or time.time
        self._path = Path(ledger_path) if ledger_path else None
        self._rows = {}            # hour key -> [ledger row]
        self._draws = {}           # hour key -> {"silent": [], "quota": [], "jam": []}
        self._loaded = False
        self._dirty = False
        self._saved_at = 0.0
        self._book_why = ""
        self.last_error = ""

    # -- plumbing ----------------------------------------------------------------

    def now(self):
        return float(self._clock())

    def _call(self, name, *args, default=None, **kwargs):
        fn = self.h.get(name)
        if not callable(fn):
            return default
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a door that fails says nothing and is recorded
            self._error(name, exc)
            return default

    async def _acall(self, name, *args, default=None, **kwargs):
        fn = self.h.get(name)
        if not callable(fn):
            return default
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self._error(name, exc)
            return default

    def _error(self, where, exc):
        self.last_error = "%s: %s: %s" % (where, type(exc).__name__, str(exc)[:200])
        fn = self.h.get("pipeline_log")
        if callable(fn):
            try:
                fn("system3", "(hour) " + self.last_error[:300])
            except Exception:  # noqa: BLE001
                pass

    def _runtime(self):
        fn = self.h.get("_system2")
        try:
            return fn() if callable(fn) else None
        except Exception:  # noqa: BLE001 - System 2 unavailable: its config is still on disk
            return None

    def config_path(self):
        base = self.h.get("DATA_DIR")
        return Path(base) / "system2-config.json" if base is not None else Path("system2-config.json")

    def config(self):
        rt = self._runtime()
        cfg = getattr(rt, "config", None)
        if isinstance(cfg, dict):
            return cfg
        try:
            raw = json.loads(self.config_path().read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def engine(self):
        return str(self.config().get("engine") or "legacy")

    def enabled(self):
        return self.engine() == "system3"

    def fallback_on(self):
        return bool(self.config().get("fallback", True))

    def since(self):
        try:
            return float(self.config_path().stat().st_mtime)
        except OSError:
            return 0.0

    def hour_key(self, at=None):
        fn = self.h.get("_sched_hour_key")
        if callable(fn):
            return fn(at)
        return time.strftime(HOUR_KEY_FORMAT, time.localtime(at if at is not None else self.now()))

    def _epoch(self, key):
        fn = self.h.get("_sched_hour_epoch")
        if callable(fn):
            return float(fn(key))
        try:
            return time.mktime(time.strptime(str(key), HOUR_KEY_FORMAT))
        except (TypeError, ValueError, OverflowError):
            return -1.0

    def _road(self, kind):
        table = self.h.get("SCHED_PREP_KIND") or FALLBACK_ROAD
        return str(table.get(kind) or kind)

    def _tables(self, family_id):
        """The HOUR table as the running config holds it (the desk edits it);
        the shipped default when the config has none."""
        rt = self.h.get("_SYSTEM3_RUNTIME")
        try:
            rt = rt() if callable(rt) else rt
        except Exception:  # noqa: BLE001
            rt = None
        for table in ((getattr(rt, "config", None) or {}).get("tables") or []):
            if isinstance(table, dict) and table.get("id") == family_id and table.get("enabled", True) is not False:
                return table
        for table in system3_tables.default_tables():
            if table.get("id") == family_id:
                return table
        return {}

    def _odds(self, family_id, item_id, fallback):
        for item in _items(self._tables(family_id)):
            if item.get("id") == item_id:
                try:
                    return min(1.0, max(0.0, float(item.get("odds", fallback))))
                except (TypeError, ValueError):
                    return fallback
        return fallback

    def _weighted(self, key, labels, weights, label):
        if not labels or sum(max(0.0, float(w)) for w in weights) <= 0:
            return None
        fn = self.h.get("s3_weighted")
        if callable(fn):
            return int(fn(key, list(labels), [float(w) for w in weights], label))
        return random.choices(range(len(labels)), weights=[float(w) for w in weights], k=1)[0]

    def _chance(self, key, odds, label):
        fn = self.h.get("s3_chance")
        if callable(fn):
            return bool(fn(key, float(odds), label))
        return random.random() < float(odds)

    # -- the hour, read off the running order -----------------------------------------

    def legs(self, hour=""):
        hour = hour or self.hour_key()
        store = self._call("schedule_read", default={}) or {}
        got = self._call("schedule_hour_slots", store, hour, default=None)
        name, rows, over = got if isinstance(got, tuple) and len(got) == 3 else ("", [], False)
        start = self._epoch(hour)
        if start < 0:
            start = self.now()
        legs = leg_walk(rows, start,
                        prompt_of=lambda s: self._call("schedule_prompt_for", store, s, default=""),
                        road_of=self._road)
        return {"road": "hour", "id": "hour@" + str(hour), "hour": str(hour), "preset": str(name or ""),
                "overridden": bool(over), "legs": legs}

    # -- decisions -------------------------------------------------------------------

    def decide(self, dj=None):
        """What this breath airs: {kind, why, slot, policy, named}.
        policy: "sheet" (the running order names it), "silent" (the sheet is
        silent: HOUR1 draws), "jam" (the sheet is jammed and the roll displaced it)."""
        hour = self.hour_key()
        slot = self._call("schedule_take", default={}) or {}
        if slot:
            named = str(slot.get("kind") or "")
            jam = str(self._call("schedule_jammed", default="") or "")
            if not jam:
                return {"kind": named, "why": "the running order names it", "slot": slot,
                        "policy": "sheet", "named": named}
            odds = self._odds("HOUR3", "displace", 0.5)
            label = "the jam on %s (%s)" % (slot.get("label") or named, jam[:80])
            hit = self._chance("hour.jam", odds, label)
            self._draw(hour, "jam", {"at": self.now(), "named": named, "slot_id": str(slot.get("id") or ""),
                                     "why": jam[:160], "odds": round(odds, 4), "displaced": hit})
            if not hit:
                return {"kind": named, "why": "jammed (%s); the jam roll kept the entry" % jam[:120],
                        "slot": slot, "policy": "sheet", "named": named}
            kind, why = self._silent(hour, "jammed (%s); the jam roll displaced %s" % (jam[:120], named))
            return {"kind": kind, "why": why, "slot": {}, "policy": "jam", "named": named}
        kind, why = self._silent(hour, "the sheet is silent")
        return {"kind": kind, "why": why, "slot": {}, "policy": "silent", "named": ""}

    def _silent(self, hour, reason):
        items = _items(self._tables("HOUR1"), "silent") or _items(self._tables("HOUR1"))
        if not items:
            return "banter", reason + "; HOUR1 has no kinds, so banter"
        quota = self._quota(hour)
        weights = silent_weights(items, quota["multipliers"])
        labels = [str(i["id"]) for i in items]
        idx = self._weighted("hour.silent", labels, weights, "HOUR1: " + reason)
        if idx is None:
            return "banter", reason + "; every HOUR1 weight is zero, so banter"
        kind = labels[idx]
        self._draw(hour, "quota", {"at": self.now(), "planned": quota["planned"], "aired": quota["aired"],
                                   "multipliers": quota["multipliers"]})
        self._draw(hour, "silent", {"at": self.now(), "labels": labels, "weights": [round(w, 4) for w in weights],
                                    "picked": kind, "why": reason})
        return kind, "%s; HOUR1 drew %s (of %d kinds)" % (reason, kind, len(items))

    def _quota(self, hour):
        gains = {str(i["id"]): float(i.get("gain", 0) or 0) for i in _items(self._tables("HOUR2"))}
        planned, aired = {}, {}
        for leg in self.legs(hour)["legs"]:
            planned[leg["kind"]] = planned.get(leg["kind"], 0) + 1
        for row in self._rows.get(hour, []):
            if row.get("served"):
                aired[row.get("kind", "")] = aired.get(row.get("kind", ""), 0) + int(row.get("rounds") or 1)
        return {"planned": planned, "aired": aired,
                "multipliers": quota_multipliers(planned, aired, gains)}

    # -- the booking -----------------------------------------------------------------

    def book(self, kind, slot=None):
        """The finished round the cupboard offers for this leg, drawn by weight
        (waiting age, deadline nearness), or None with the reason on
        `self._book_why`."""
        slot = slot or {}
        road = self._road(kind)
        now = self.now()
        life = self.h.get("_pantry_lifecycle")
        try:
            life = life() if callable(life) else life
        except Exception:  # noqa: BLE001
            life = None
        rows = self._call("road_source", road, default=[]) or []
        refused, cands = {}, []

        def refuse(text):
            refused[text] = refused.get(text, 0) + 1

        for row in rows:
            if not isinstance(row, dict):
                continue
            entry = self._call("dialogue_entry", row, default=None) or row
            window = str(entry.get("dynamic_kind") or "")
            if window and window != kind:
                refuse("a window's part belongs to its own window")
                continue
            if not self._call("dialogue_row_ready", road, row, default=False):
                refuse("not ready")
                continue
            if life is not None and getattr(life, "enabled", False):
                try:
                    fits = bool(life.compatible(kind, row))
                except Exception as exc:  # noqa: BLE001
                    self._error("lifecycle", exc)
                    fits = False
                if not fits:
                    refuse("the lifecycle does not fit it to the leg")
                    continue
            unaired = self.h.get("row_unaired")
            was_aired = (not unaired(row)) if callable(unaired) else bool(row.get("aired"))
            if was_aired and self._call("bank_reair_refusal", road, row, default=""):
                refuse("the re-air gate retired it")
                continue
            cands.append(row)
        if not cands:
            why = ", ".join("%d %s" % (n, t) for t, n in sorted(refused.items())) or "the shelf is empty"
            self._book_why = "no finished %s round fits this leg (%s)" % (road, why)
            return None
        labels = [("%s@%d %s" % (road, i, str(r.get("id") or ""))).strip()[:80] for i, r in enumerate(cands)]
        weights = [book_weight(r.get("at") or (r.get("entry") or {}).get("at"), now, slot.get("deadline"))
                   for r in cands]
        idx = self._weighted("hour.book", labels, weights,
                             "the %s shelf for %s" % (road, slot.get("label") or kind))
        if idx is None:
            self._book_why = "every %s round weighs nothing" % road
            return None
        self._book_why = ""
        return cands[idx]

    # -- the dispatch ----------------------------------------------------------------

    def _occurrence(self, slot):
        if slot:
            return str(self._call("_schedule_dispatch_occurrence", default="") or "")
        return "silent@%d" % int(self.now() // 60)

    async def dispatch(self, track=None, dj=None):
        """One breath of the chain. True when the director aired a round; False
        when it aired nothing (the chain may then run its fallback)."""
        if not self.enabled():
            return False
        self._load()                    # the 48 hours on disk first: the save below writes them all back
        if track is None:
            track = (self.h.get("_RADIO") or {}).get("now")
        if dj is None:
            dj = self._call("dj_settings", default={}) or {}
        hour = self.hour_key()
        due = self.decide(dj)
        kind, slot = due["kind"], due["slot"]
        if not kind:
            return False
        occ = self._occurrence(slot)
        row = self._ask(hour, occ, slot, due, self._road(kind))
        served, booked, why = False, None, due["why"]
        try:
            if kind in DYNAMIC_KINDS or kind in EXTRA_KINDS:
                if kind == "record":
                    self._call("_schedule_pin_record")
                got = await self._acall("schedule_extra_round", kind, track, dj, occurrence=occ)
                served = got is True
                if not served:
                    why = ("the %s door answered nothing (not one of its own)" % kind if got is None
                           else "the %s door refused it" % kind)
            else:
                road = self._road(kind)
                picked = self.book(kind, slot)
                if picked is None:
                    why = self._book_why or "nothing booked"
                else:
                    booked = {"id": str(picked.get("id") or ""), "kind": kind,
                              "label": str(picked.get("label") or picked.get("text") or "")[:120]}
                    said = await self._acall("_ready_shelf_air", road, track, pick=picked)
                    served = bool(said)
                    refusal = str((self.h.get("_READY_SHELF_REFUSED") or [""])[0] or "")
                    if not served:
                        why = "the cupboard refused the booked round" + (": " + refusal if refusal else "")
        except Exception as exc:  # noqa: BLE001
            self._error("dispatch", exc)
            served, why = False, "the dispatch failed: %s" % type(exc).__name__
        self._settle(row, served=served, why=why, booked=booked)
        self._flow(kind, served, why, slot, booked)
        return served

    def _ask(self, hour, occ, slot, due, road):
        sid = str(slot.get("id") or "")
        rows = self._rows.setdefault(hour, [])
        for row in rows[-40:]:
            if row.get("occurrence") == occ and row.get("slot_id") == sid and row.get("kind") == due["kind"]:
                row["asks"] = int(row.get("asks") or 0) + 1
                return row
        row = {"at": round(self.now(), 3), "occurrence": occ, "slot_id": sid,
               "label": str(slot.get("label") or due["kind"])[:80], "named": due["named"],
               "kind": due["kind"], "road": road, "policy": due["policy"], "booked": None,
               "served": False, "rounds": 0, "asks": 1, "why": due["why"]}
        rows.append(row)
        del rows[:-LEDGER_ROWS_PER_HOUR]
        self._dirty = True
        self._save()
        return row

    def _settle(self, row, served, why, booked):
        row["why"] = why
        if booked is not None:
            row["booked"] = booked
        if served:
            row["served"] = True
            row["rounds"] = int(row.get("rounds") or 0) + 1
            row["aired_at"] = round(self.now(), 3)
        self._dirty = True
        self._save(force=bool(served))

    def _flow(self, kind, served, why, slot, booked):
        ledger = self.h.get("FLOW_LEDGER")
        note = getattr(ledger, "note", None)
        if not callable(note):
            return
        try:
            note("hour.dispatch", why[:240], passed=bool(served), road=self._road(kind),
                 text=str((booked or {}).get("label") or "")[:160], ref=str(slot.get("id") or ""))
        except Exception as exc:  # noqa: BLE001
            self._error("flow", exc)

    def fallback_due(self):
        """May the legacy chain serve this breath? Only under engine system3 with
        fallback on, when the director aired nothing for the running occurrence
        and nothing of its own is on the floor."""
        if not self.enabled() or not self.fallback_on():
            return False
        occ = str(self._call("_schedule_dispatch_occurrence", default="") or "")
        self._load()
        if any(r.get("served") and r.get("occurrence") == occ for r in self._rows.get(self.hour_key(), [])):
            return False
        try:
            if (self.h.get("_SPEAKING") or [0])[0] or (self.h.get("_floor_busy") or (lambda: False))():
                return False
        except Exception:  # noqa: BLE001
            return False
        return True

    # -- the draws ledger --------------------------------------------------------------

    def _draw(self, hour, which, record):
        bucket = self._draws.setdefault(hour, {k: [] for k in DRAW_KEYS})
        bucket[which].append(record)
        del bucket[which][:-60]
        self._dirty = True

    # -- the ledger on disk ------------------------------------------------------------

    def ledger_path(self):
        if self._path is not None:
            return self._path
        base = self.h.get("DATA_DIR")
        return Path(base) / LEDGER_FILE if base is not None else Path(LEDGER_FILE)

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self.ledger_path().read_text("utf-8"))
        except (OSError, ValueError):
            return
        hours = raw.get("hours") if isinstance(raw, dict) else None
        if not isinstance(hours, dict):
            return
        for key, body in hours.items():
            if not isinstance(body, dict):
                continue
            self._rows[str(key)] = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
            draws = body.get("draws") if isinstance(body.get("draws"), dict) else {}
            self._draws[str(key)] = {k: list(draws.get(k) or []) for k in DRAW_KEYS}

    def _save(self, force=False):
        if not self._dirty:
            return
        now = self.now()
        if not force and now - self._saved_at < LEDGER_SAVE_EVERY:
            return
        ledger_prune(self._rows, now, epoch_of=self._epoch)
        ledger_prune(self._draws, now, epoch_of=self._epoch)
        hours = {}
        for key in set(self._rows) | set(self._draws):
            hours[key] = {"rows": self._rows.get(key, []),
                          "draws": self._draws.get(key) or {k: [] for k in DRAW_KEYS}}
        path = self.ledger_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps({"version": 1, "hours": hours}, indent=1), "utf-8")
            tmp.replace(path)
        except OSError as exc:
            self._error("ledger", exc)
            return
        self._dirty = False
        self._saved_at = now

    def flush(self):
        self._dirty = True
        self._save(force=True)

    # -- the views ---------------------------------------------------------------------

    def engine_view(self):
        cfg = self.config()
        engine = str(cfg.get("engine") or "legacy")
        fallback = bool(cfg.get("fallback", True))
        return {"engine": engine, "fallback": fallback, "since": self.since(),
                "say": engine_say(engine, fallback)}

    def set_engine(self, body):
        if not isinstance(body, dict):
            raise ValueError("Expected an object")
        unknown = set(body) - {"engine", "fallback"}
        if unknown:
            raise ValueError("Unknown System 3 engine settings: " + ", ".join(sorted(unknown)))
        patch = {}
        if "engine" in body:
            if body["engine"] not in ENGINES:
                raise ValueError("engine must be legacy, system2 or system3")
            patch["engine"] = body["engine"]
        if "fallback" in body:
            if not isinstance(body["fallback"], bool):
                raise ValueError("fallback must be a boolean")
            patch["fallback"] = body["fallback"]
        if not patch:
            raise ValueError("Nothing to set: give engine and/or fallback")
        rt = self._runtime()
        if rt is not None:
            rt.configure(patch)                     # System 2's own door: it writes the same file
        else:
            current = dict(self.config())
            current.update(patch)
            path = self.config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(current, indent=2) + "\n", "utf-8")
        fn = self.h.get("pipeline_log")
        if callable(fn):
            fn("system3", "(hour) engine set: " + json.dumps(patch, sort_keys=True))
        return self.engine_view()

    def hour_view(self, hour=""):
        hour = hour or self.hour_key()
        plan = self.legs(hour)
        pos = (self.h.get("_RADIO") or {}).get("sched_pos") or {}
        live = str(pos.get("slot_id") or "") if hour == self.hour_key() else ""
        self._load()
        rows = list(self._rows.get(hour, []))
        draws = self._draws.get(hour) or {k: [] for k in DRAW_KEYS}
        legs = []
        for leg in plan["legs"]:
            mine = [r for r in rows if r.get("slot_id") == leg["id"]]
            booked = next((r["booked"] for r in reversed(mine) if r.get("booked")), None)
            legs.append({
                "id": leg["id"], "label": leg["label"], "kind": leg["kind"], "road": leg["road"],
                "minutes": leg["minutes"], "start": leg["start"], "deadline": leg["deadline"],
                "dynamic_kind": leg["dynamic_kind"], "act": leg["act"], "place": leg["place"],
                "on_air": bool(live) and leg["id"] == live, "booked": booked,
                "ledger": [{"at": r.get("at"), "named": r.get("named"), "policy": r.get("policy"),
                            "served": bool(r.get("served")), "why": r.get("why")} for r in mine[-20:]],
            })
        served = sum(1 for r in rows if r.get("served"))
        return {"hour": hour, "engine": self.engine(), "preset": plan["preset"],
                "overridden": plan["overridden"], "legs": legs, "draws": draws,
                "say": "%d legs in %s (%s); %d rounds aired by the director, %d ledger rows, %d draws"
                       % (len(legs), hour, plan["preset"] or "no preset", served, len(rows),
                          sum(len(v) for v in draws.values()))}


# --- the install: the director and its routes ---------------------------------------------

class _Namespace:
    """The app's globals by attribute, for the director and the auth helpers."""

    def __init__(self, namespace):
        object.__setattr__(self, "namespace", namespace)

    def __getattr__(self, name):
        try:
            return self.namespace[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def install(app, namespace):
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import JSONResponse

    host = _Namespace(namespace)
    director = HourDirector(host)
    namespace["_system3_hour"] = lambda: director

    @app.get("/api/system3/engine")
    async def engine_get(authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        return director.engine_view()

    @app.post("/api/system3/engine")
    async def engine_set(request: Request, authorization: str | None = Header(default=None)):
        host.require_auth(authorization)
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(400, "Expected JSON") from exc
        try:
            return director.set_engine(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/system3/hour")
    async def hour_get(hour: str = "", authorization: str | None = Header(default=None)):
        host.require_read_auth(authorization)
        if not director.enabled():
            return JSONResponse({"engine": director.engine(),
                                 "detail": "the Hour Director is not the engine"}, status_code=404)
        return director.hour_view(hour)

    return director
