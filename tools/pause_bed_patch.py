"""[pause-bed] While the station is paused, the broadcast plays the endless
video set's own sound instead of silence. Anchor-asserted; run on the host."""
import ast
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def sub(text, old, new, name):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"anchor {name}: found {n} times")
    return text.replace(old, new)


# ---------------------------------------------------------------- app.py --
p = ROOT / "app.py"
a = p.read_text()
if "[pause-bed]" in a:
    raise SystemExit("app.py already patched")
a = sub(a, '''            _lv_how = "raw"
            try:
                _lv_how = (await sfx_level_for_air(
                    pick, max(1.5, min(SFX_LEVEL_WAIT, room))))[1]
''', '''            _lv_how = "raw"
            _lv_path = pick                  # [pause-bed] the file the tube gets
            try:
                _lv_path, _lv_how = await sfx_level_for_air(
                    pick, max(1.5, min(SFX_LEVEL_WAIT, room)))
''', "cycle-level")
a = sub(a, '''            plan.append({"sting": pick.stem, "start": start,
                         "end": start + seconds, "id": key})   # [#1200]
''', '''            plan.append({"sting": pick.stem, "start": start,
                         "end": start + seconds, "id": key})   # [#1200]
            # [pause-bed] the set's own sound, kept where the stream can see
            # it: while the station is paused the broadcast airs the clip the
            # tube is showing instead of silence (_stream_snapshot).
            _set_air = _SFX_CYCLE.setdefault("air", [])
            _set_air.append({"key": "set|%s|%d" % (key, int(start * 1000)),
                             "air_at": start, "slot": seconds, "length": real,
                             "path": str(_lv_path)})
            del _set_air[:-12]
''', "cycle-plan")
a = sub(a, '''        return {"on": bool(_RADIO.get("on")), "paused": radio_paused(),
                "music": music, "clips": clips,
                **pinelive.snapshot_extra()}     # [pinelive] the set, as the bed
''', '''        # [pause-bed] off air, the endless set is what the house hears - so
        # it is what the road hears too, not a held socket full of silence.
        paused = radio_paused()
        on = bool(_RADIO.get("on"))
        pause_set: list[dict[str, Any]] = []
        if (paused or not on) and sfx_video_mode_on():
            for row in list(_SFX_CYCLE.get("air") or []):
                if isinstance(row, dict) and row.get("path"):
                    pause_set.append(dict(row))
        return {"on": on, "paused": paused,
                "music": music, "clips": clips, "pause_set": pause_set,
                **pinelive.snapshot_extra()}     # [pinelive] the set, as the bed
''', "snapshot")
ast.parse(a)

# ------------------------------------------------------ station_stream.py --
q = ROOT / "station_stream.py"
s = q.read_text()
if "[pause-bed]" in s:
    raise SystemExit("station_stream.py already patched")
s = sub(s, '''        pending: list[_Voice] = []
''', '''        pending: list[_Voice] = []
        # [pause-bed] the endless set's clips while off air: the one sounding,
        # the next one opened ahead, and the last key tried (never reopened).
        set_rows: list[dict[str, Any]] = []
        set_air: _Voice | None = None
        set_next: _Voice | None = None
        set_tried = ""
''', "init")
s = sub(s, '''                        pending.append(voice)
                    pending.sort(key=lambda v: v.air_at)
''', '''                        pending.append(voice)
                    pending.sort(key=lambda v: v.air_at)
                    set_rows = [r for r in (state.get("pause_set") or [])
                                if isinstance(r, dict)]
''', "rows")
s = sub(s, '''                    frame = SILENCE
                    if airing is not None:
                        airing.decoder and airing.decoder.close()
                        airing = None
                    duck = 0.0
                else:
''', '''                    frame = SILENCE
                    if airing is not None:
                        airing.decoder and airing.decoder.close()
                        airing = None
                    duck = 0.0
                    # [pause-bed] ...unless the endless set is running: then
                    # its clip is the bed, joined at the tube's own offset,
                    # the next one opened a moment early so the seam is tight.
                    cur_row, nxt_row = _pause_set_pick(set_rows, now)
                    cur_key = str((cur_row or {}).get("key") or "")
                    if set_air is not None and set_air.key != cur_key:
                        set_air.decoder and set_air.decoder.close()
                        set_air = None
                    if (set_air is None and set_next is not None
                            and set_next.key == cur_key):
                        set_air, set_next = set_next, None
                        set_tried = cur_key
                    if set_air is None and cur_key and cur_key != set_tried:
                        set_tried = cur_key
                        set_air = _pause_set_open(
                            cur_row, max(0.0, now - float(cur_row["air_at"])))
                    nxt_key = str((nxt_row or {}).get("key") or "")
                    if set_next is not None and set_next.key != nxt_key:
                        set_next.decoder and set_next.decoder.close()
                        set_next = None
                    if set_next is None and nxt_key:
                        set_next = _pause_set_open(nxt_row, 0.0)
                    if set_air is not None and set_air.decoder is not None:
                        raw, live = set_air.decoder.read_frame()
                        if live:
                            bed = _centered_pcm(raw)
                            frame = _mixed_program(bed, None, False)
                            made_sound = True
                            self.stats["pause_set_frames"] = int(
                                self.stats.get("pause_set_frames") or 0) + 1
                        elif set_air.decoder.finished:
                            set_air.decoder.close()
                            set_air = None
                    self.stats["pause_set"] = set_air.key if set_air else ""
                else:
                    if set_air is not None or set_next is not None:
                        for _sv in (set_air, set_next):
                            if _sv is not None and _sv.decoder is not None:
                                _sv.decoder.close()
                        set_air = set_next = None
                        self.stats["pause_set"] = ""
''', "offair")
s = sub(s, '''                    if not on_air or bed is None:
                        hshaped = frame
''', '''                    if bed is None:        # [pause-bed] off air with a set = a bed
                        hshaped = frame
''', "lanes")
s = sub(s, '''def _mixed_program(bed: np.ndarray, voice: np.ndarray | None,
''', '''def _pause_set_pick(rows: list[dict[str, Any]], now: float
                    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """[pause-bed] (the set clip whose slot holds `now`, the next one due
    within two seconds). The latest start wins, so a re-planned set that
    rings a new clip over a withdrawn one is followed, not the old plan."""
    cur = nxt = None
    for row in rows:
        try:
            at = float(row.get("air_at") or 0)
            span = float(row.get("slot") or row.get("length") or 0)
        except (TypeError, ValueError):
            continue
        if not at:
            continue
        if at <= now and (span <= 0 or now < at + span):
            if cur is None or at >= float(cur["air_at"]):
                cur = row
        elif now < at <= now + 2.0:
            if nxt is None or at < float(nxt["air_at"]):
                nxt = row
    return cur, nxt


def _pause_set_open(row: dict[str, Any], offset: float) -> "_Voice | None":
    """[pause-bed] a started decoder for one set clip, or None."""
    path = str(row.get("path") or "")
    if not path or not Path(path).is_file():
        return None
    voice = _Voice(str(row.get("key") or ""), float(row.get("air_at") or 0),
                   path, float(row.get("length") or 0), True)
    voice.decoder = _Decoder(path, offset)
    if not voice.decoder.start():
        return None
    return voice


def _mixed_program(bed: np.ndarray, voice: np.ndarray | None,
''', "helpers")
ast.parse(s)

p.write_text(a)
q.write_text(s)
print("patched app.py and station_stream.py")
