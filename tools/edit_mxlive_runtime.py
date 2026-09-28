"""[s3-live-event] Station events in the runtime (system3_runtime.py).

The runtime is where an event's ON/OFF is decided (at plan time, once, so
the plan's inputs record the view the dice saw):

  1. add_missing_station_events(): the events register (MX Live) and the
     event_facts block reach a stored config once, beside the default
     tables (add_missing_default_tables now also offers the event
     tables). Remembered in defaults_added - a row the operator deletes
     stays deleted.
  2. station_events(): {"mxlive": {"stage": ...}} while the event is ON.
     A pinelive-sourced event follows pinelive.event_state() (guarded
     import; a tree without pinelive.py simply has the event off, and
     tests stub `event_probe`): arming -> upcoming, live -> live,
     fallback -> fallback, and for after_window seconds after the set ->
     after. A manual event follows its `active` flag and window.
  3. inputs gain "events" (the view event_view filters by) and
     "record_event" (the live pseudo-record on air).
  4. The station wheels: pool() lends ANGLE rows to the wheel a table
     names (`pool`: banter.stock_angle), and direct_line() lends EVENT
     rows carrying the road (station_id) to the LINE wheel - never on a
     banked line. Both add nothing while every event is off.
  5. event_facts_text(): the words of the event_facts block for the
     prompt being written on this task - only when a roll in its round
     landed on an event row (system3.event_claims). Installed as
     namespace["system3_event_facts"].
  6. status() carries events_view() for the Controls tab.

  python edit_mxlive_runtime.py [--check|--apply] path/to/system3_runtime.py

Marker-idempotent (marker: [s3-live-event]). --check: 0 ready, 2 applied,
1 anchors missing. Keeps LF endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

METHODS = '''    # --- [s3-live-event] station events ------------------------------------
    EVENTS_MARK = "STATION_EVENTS"     # in defaults_added: register + block, once
    EVENT_AFTER_DEFAULT = 1800.0

    def add_missing_station_events(self):
        """[s3-live-event] Once: the station-events register (MX Live) and the
        event_facts block onto a stored config that predates them. Remembered
        in defaults_added, so an event or the block the operator later
        removes stays removed. Saved as a version with a note."""
        config = self.config if isinstance(self.config, dict) else {}
        seen = {str(x) for x in (config.get("defaults_added") or [])}
        if self.EVENTS_MARK in seen:
            return []
        new = copy.deepcopy(config)
        added = []
        reg = new.setdefault("events", {})
        for eid, ev in system3_tables.default_events().items():
            if eid not in reg:
                reg[eid] = ev
                added.append("event " + eid)
        blocks = new.setdefault("blocks", system3_tables.default_blocks())
        for name, rule in system3_tables.default_event_blocks().items():
            if name not in blocks:
                blocks[name] = rule
                added.append("block " + name)
        new["defaults_added"] = sorted(seen | {self.EVENTS_MARK})
        try:
            self.store.save_config(new, "station events: " + (", ".join(added) or "marker only"))
        except Exception as exc:  # noqa: BLE001
            self.fail("station events register", exc)
            return []
        self.config = new
        return added

    def _pinelive_state(self):
        """PineLive's in-process read (never raises, never blocks); tests
        stub `event_probe`."""
        probe = getattr(self, "event_probe", None)
        if callable(probe):
            try:
                return probe() or {}
            except Exception:  # noqa: BLE001
                return {}
        try:
            import pinelive
            return pinelive.event_state() or {}
        except Exception:  # noqa: BLE001
            return {}

    def station_events(self):
        """{id: {stage, name, source}} for every station event that is ON
        right now - what event_view filters the wheels by. An event that is
        off is absent, and every draw is then today's draw."""
        out = {}
        try:
            reg = (self.config.get("events") or {}) if isinstance(self.config, dict) else {}
            if not reg:
                return out
            now = time.time()
            mem = getattr(self, "_event_mem", None)
            if mem is None:
                mem = self._event_mem = {}
            for eid, ev in reg.items():
                if not isinstance(ev, dict) or ev.get("enabled") is False:
                    continue
                eid = str(eid)
                src = str(ev.get("source") or "manual")
                window = float(ev.get("after_window") or self.EVENT_AFTER_DEFAULT)
                stage = ""
                if src == "pinelive":
                    st = self._pinelive_state()
                    if st.get("enabled") is not False and st.get("armed"):
                        stage = {"arming": "upcoming", "live": "live",
                                 "fallback": "fallback"}.get(str(st.get("phase") or ""), "live")
                        mem[eid] = {"seen_at": now}
                    else:
                        seen = mem.get(eid) or {}
                        if seen.get("seen_at") and now - float(seen["seen_at"]) <= window:
                            stage = "after"
                else:
                    if ev.get("active"):
                        starts = float(ev.get("starts_at") or 0)
                        ends = float(ev.get("ends_at") or 0)
                        stage = ("upcoming" if (starts and now < starts)
                                 else "after" if (ends and now > ends) else "live")
                        if stage == "after" and ends and now - ends > window:
                            stage = ""
                        if stage == "live":
                            mem[eid] = {"seen_at": now}
                if stage:
                    out[eid] = {"stage": stage, "name": str(ev.get("name") or eid), "source": src}
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("station events", exc)
            return {}

    def events_view(self):
        """The register with each event's stage right now, for Controls."""
        out = []
        try:
            live = self.station_events()
            for eid, ev in ((self.config.get("events") or {}) if isinstance(self.config, dict) else {}).items():
                if not isinstance(ev, dict):
                    continue
                got = live.get(str(eid)) or {}
                out.append({"id": str(eid), "name": str(ev.get("name") or eid),
                            "source": str(ev.get("source") or "manual"),
                            "what": str(ev.get("what") or "")[:200],
                            "stage": str(got.get("stage") or ""), "on": bool(got),
                            "tables": [str(t.get("id")) for t in (self.config.get("tables") or [])
                                       if isinstance(t, dict) and str(t.get("event") or "") == str(eid)]})
        except Exception as exc:  # noqa: BLE001
            self.fail("events view", exc)
        return out

    def record_event_of(self, ctx):
        """The id of the pinelive-sourced event whose live set IS the record
        on air (the pseudo-record carries `pinelive`; its title is the
        event's name), or ''."""
        try:
            rec = ctx.get("record") if isinstance(ctx.get("record"), dict) else {}
            if not rec:
                return ""
            for eid, ev in (self.station_events() or {}).items():
                if ev.get("source") != "pinelive" or ev.get("stage") != "live":
                    continue
                if rec.get("pinelive") or str(rec.get("title") or "") == str(ev.get("name") or ""):
                    return str(eid)
            return ""
        except Exception:  # noqa: BLE001
            return ""

    def _pool_event_rows(self, key):
        """Rows a station event lends a station wheel while it is on (family
        ANGLE, the table's `pool` names the wheel), stage-filtered; [] while
        every event is off - the wheel then draws exactly as it always did."""
        try:
            events = self.station_events()
            if not events:
                return []
            out = []
            for t in (self.config.get("tables") or []):
                if not (isinstance(t, dict) and t.get("family") == "ANGLE" and t.get("enabled", True)
                        and str(t.get("pool") or "") == str(key) and str(t.get("event") or "") in events):
                    continue
                stage = events[str(t["event"])]["stage"]
                for c in t.get("categories") or []:
                    if not isinstance(c, dict) or c.get("enabled") is False:
                        continue
                    stages = [str(s) for s in (c.get("event_stages") or [])]
                    if stages and stage not in stages:
                        continue
                    for i in c.get("items") or []:
                        if (isinstance(i, dict) and i.get("enabled") is not False
                                and str(i.get("text") or "").strip()
                                and float(i.get("weight", 1.0) or 0) > 0):
                            out.append(" ".join(str(i["text"]).split()))
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("event pool", exc)
            return []

    def _event_line_candidates(self, road, dj):
        """Rows a station event lends a single-voice road's LINE wheel while
        it is on (EVENT tables carrying this road, stage-filtered): each item
        a candidate beside the road's own stock, weighted, its why naming the
        event. [] while every event is off."""
        try:
            events = self.station_events()
            if not events:
                return []
            station = " ".join(str((dj or {}).get("station_name") or "").split()) or "the station"
            out = []
            for t in (self.config.get("tables") or []):
                if not (isinstance(t, dict) and t.get("family") == "EVENT" and t.get("enabled", True)
                        and str(t.get("event") or "") in events
                        and road in [str(r) for r in (t.get("roads") or [])]):
                    continue
                ev = events[str(t["event"])]
                for c in t.get("categories") or []:
                    if not isinstance(c, dict) or c.get("enabled") is False:
                        continue
                    stages = [str(s) for s in (c.get("event_stages") or [])]
                    if stages and ev["stage"] not in stages:
                        continue
                    for i in c.get("items") or []:
                        if not (isinstance(i, dict) and i.get("enabled") is not False
                                and str(i.get("text") or "").strip()
                                and float(i.get("weight", 1.0) or 0) > 0):
                            continue
                        out.append({"id": "%s:%s:%s" % (t["id"], c["id"], i.get("id")),
                                    "text": " ".join(str(i["text"]).split()).replace("{station}", station)[:400],
                                    "weight": float(i.get("weight", 1.0) or 0) * float(c.get("weight", 1.0) or 0),
                                    "why": ["station event %s (%s)" % (ev["name"], ev["stage"])]})
            return out
        except Exception as exc:  # noqa: BLE001
            self.fail("event line rows", exc)
            return []

    def event_facts_text(self):
        """[s3-live-event] The words of the event_facts block for the prompt
        being written on this task - only when a roll in its round landed on
        one of the event's rows; '' otherwise (the block is then never
        marked, and decide_blocks' kind "claimed" records why)."""
        if not self.ready:
            return ""
        try:
            handle = _S3_WRITE.get()
            conv = handle.conv if handle is not None and getattr(handle, "active", False) else None
            if not isinstance(conv, dict):
                return ""
            claims = system3.event_claims(conv)
            if not claims:
                return ""
            ids = set()
            for t in (self.config.get("tables") or []):
                if (isinstance(t, dict) and t.get("event")
                        and any(c.startswith(str(t.get("id")) + ":") for c in claims)):
                    ids.add(str(t["event"]))
            live = self.station_events()
            parts = []
            for eid in sorted(ids):
                ev = ((self.config.get("events") or {}).get(eid) or {})
                facts = ev.get("facts") or {}
                stage = str((live.get(eid) or {}).get("stage") or "")
                bits = ["THE STATION EVENT ON THIS ORDER (%s): %s."
                        % (str(ev.get("name") or eid),
                           str(facts.get("what") or ev.get("what") or eid).rstrip("."))]
                if facts.get("who"):
                    bits.append("Who: %s." % str(facts["who"]).rstrip("."))
                if facts.get("device"):
                    bits.append("The instrument: %s." % str(facts["device"]).rstrip("."))
                bits.append("Right now it is %s." % {
                    "upcoming": "armed - it has not started",
                    "live": "LIVE on the air underneath you",
                    "fallback": "live, but the input has dropped out for a moment",
                    "after": "just finished"}.get(stage, "over"))
                for n in (facts.get("notes") or [])[:4]:
                    bits.append(str(n))
                parts.append(" ".join(bits))
            with self.lock:
                self.metrics["event_facts_blocks"] = self.metrics.get("event_facts_blocks", 0) + 1
            return ("\\n\\n" + "\\n".join(parts)) if parts else ""
        except Exception as exc:  # noqa: BLE001
            self.fail("event facts", exc)
            return ""

'''

EDITS: list[tuple[str, str, str, int]] = [
    ("add-missing-tables",
     '        missing = [t for t in system3_tables.default_tables() if t["id"] not in have and t["id"] not in seen]\n',
     '        missing = [t for t in system3_tables.default_tables()\n'
     '                   + system3_tables.default_event_tables()      # [s3-live-event]\n'
     '                   if t["id"] not in have and t["id"] not in seen]\n', 1),

    ("load-call",
     '        added = self.add_missing_default_tables()\n'
     '        if added:\n'
     '            self.log("System 3 config gained the default tables it predates: " + ", ".join(added))\n',
     '        added = self.add_missing_default_tables()\n'
     '        if added:\n'
     '            self.log("System 3 config gained the default tables it predates: " + ", ".join(added))\n'
     '        gained = self.add_missing_station_events()                       # [s3-live-event]\n'
     '        if gained:\n'
     '            self.log("System 3 config gained the station-events register: " + ", ".join(gained))\n', 1),

    ("methods",
     '    ES_EMOJI_MARK = "ES_EMOJI"         # [s3-es-emoji] in defaults_added: the badges were given once\n',
     METHODS
     + '    ES_EMOJI_MARK = "ES_EMOJI"         # [s3-es-emoji] in defaults_added: the badges were given once\n', 1),

    ("inputs-events",
     '            "event_rolls": True,\n',
     '            "event_rolls": True,\n'
     '            # [s3-live-event] the station events that are ON (stage per event):\n'
     '            # event-tagged rows are in the wheels only while listed here\n'
     '            "events": self.station_events(),\n'
     '            "record_event": self.record_event_of(ctx),\n', 1),

    ("pool-no-cat",
     '                                                  "items": [{"id": "o%d" % i, "label": o[:60], "text": o, "weight": 1.0}\n'
     '                                                            for i, o in enumerate(opts[:200])]})\n'
     '                return opts\n',
     '                                                  "items": [{"id": "o%d" % i, "label": o[:60], "text": o, "weight": 1.0}\n'
     '                                                            for i, o in enumerate(opts[:200])]})\n'
     '                return opts + self._pool_event_rows(key)         # [s3-live-event]\n', 1),

    ("pool-live",
     '            return live or opts\n',
     '            return (live or opts) + self._pool_event_rows(key)   # [s3-live-event]\n', 1),

    ("line-candidates",
     '                elif isinstance(c, str) and c.strip():\n'
     '                    cands.append({"id": str(i), "text": " ".join(c.split())[:400], "weight": 1.0, "why": []})\n'
     '            context = " ".join(str(ctx.get("context") or ctx.get("text") or "").split())\n',
     '                elif isinstance(c, str) and c.strip():\n'
     '                    cands.append({"id": str(i), "text": " ".join(c.split())[:400], "weight": 1.0, "why": []})\n'
     '            if not ctx.get("bank"):                              # [s3-live-event]\n'
     '                cands.extend(self._event_line_candidates(road, dj))\n'
     '            context = " ".join(str(ctx.get("context") or ctx.get("text") or "").split())\n', 1),

    ("status-events",
     '                "roads": self.roads(),                                           # [s3-roads]\n',
     '                "roads": self.roads(),                                           # [s3-roads]\n'
     '                "events": self.events_view(),                                    # [s3-live-event]\n', 1),

    ("namespace",
     '    namespace["system3_memory_block"] = rt.memory_block                # [s3-memory]\n',
     '    namespace["system3_memory_block"] = rt.memory_block                # [s3-memory]\n'
     '    namespace["system3_event_facts"] = rt.event_facts_text             # [s3-live-event]\n', 1),

    # The delete guard: an event-tagged table is out of the wheels whenever
    # its event is off - it cannot stand in for a family's last table.
    ("delete-guard",
     '        fams = {t["family"] for t in config["tables"] if t.get("enabled", True)}\n',
     '        fams = {t["family"] for t in config["tables"]\n'
     '                if t.get("enabled", True) and not t.get("event")}   # [s3-live-event]\n', 1),
]


def state_of(text: str, old: str, new: str, count: int) -> str:
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "system3_runtime.py")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text, "system3_runtime.py is expected LF-only"
    applied, missing = 0, []
    for name, old, new, count in EDITS:
        st = state_of(text, old, new, count)
        if st == "applied":
            applied += 1
        elif st != "ready":
            missing.append("%s (%s)" % (name, st))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, len(EDITS)))
        return 1
    if applied == len(EDITS):
        print("already applied (%d edits)" % len(EDITS))
        return 2
    if not do_apply:
        print("ready: %d edits, %d already in" % (len(EDITS), applied))
        return 0
    for name, old, new, count in EDITS:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
