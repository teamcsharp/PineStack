"""[listener-lane] listeners' own tracks get airplay, a DJ's ear, and the request line.

2026-09-30, the operator: "If a user submits music to
\\\\10.89.1.125\\QuickSwap\\samples_grabbed\\user\\ (mp3s) play them on the broadcast
by putting the tracks in roulette so they get play on the air occasionally" -
"these are tracks by other users who want airplay. Have the djs analyze and
play them as well." - "also i want to be able to request music from the
submissions in user." - "Make sure that we also support animated album art if
it's in the MP3." (the sample tracks carry a 320x320 GIF as their APIC cover.)

- The folder joins MUSIC_ROOTS (USER_MUSIC_ROOT): every submission is a
  library record - searchable, so it can be requested, and its embedded art is
  served as it is (image/gif stays a GIF: it animates wherever a record's art
  is drawn). A submitter's folder is the record's "station".
- samples_grabbed is an SFX DROP root (every subfolder a clip folder); "user"
  is kept out of it (SFX_DROP_SKIP) so a song dropped in never airs as a sting.
- A listener lane in the record roulette: System 3 rolls records.listener_due
  (LISTENER_ODDS, occasionally) and records.listener_pick (which submission,
  never one heard inside the day). The pick airs the way a request does - its
  own introduction, the reception notes and the lyrics listened for - and the
  DJs are told it is a listener's submission: say so, shout the submitter
  out by name, say what they hear in it.

Usage (ON THE HOST): python3 tools/listener_lane_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[listener-lane]"

EDITS = [
    ("roots",
     '''SFX_ROOT = Path(os.getenv("SFX_ROOT", "/samples"))
''',
     '''SFX_ROOT = Path(os.getenv("SFX_ROOT", "/samples"))
# [listener-lane] listeners' own tracks: a music root of their own (one folder
# per submitter), a lane in the record roulette, never a sting
USER_MUSIC_ROOT = SFX_ROOT / "samples_grabbed" / "user"
if str(USER_MUSIC_ROOT) not in [str(r) for r in MUSIC_ROOTS]:
    MUSIC_ROOTS.append(USER_MUSIC_ROOT)
LISTENER_ODDS = float(os.getenv("LISTENER_ODDS", "0.15"))   # about one record in seven
'''),
    ("drop skip const",
     '''SFX_DROP_SUBS = 60                 # subfolders taken from a drop root
''',
     '''SFX_DROP_SUBS = 60                 # subfolders taken from a drop root
SFX_DROP_SKIP = {"user"}           # [listener-lane] listeners' songs, never stings
'''),
    ("drop skip",
     '''                    (one for one in root.iterdir() if one.is_dir()),
''',
     '''                    (one for one in root.iterdir() if one.is_dir()
                     and one.name.lower() not in SFX_DROP_SKIP),   # [listener-lane]
'''),
    ("pick",
     '''def dj_next_track() -> dict[str, Any] | None:
''',
     '''def listener_tracks() -> list[dict[str, Any]]:
    """[listener-lane] the library records under USER_MUSIC_ROOT."""
    root = str(USER_MUSIC_ROOT).rstrip("/") + "/"
    try:
        return [t for t in music_index() if str(t.get("path") or "").startswith(root)]
    except Exception:  # noqa: BLE001
        return []


def listener_pick() -> dict[str, Any] | None:
    """[listener-lane] one submission, System 3's pick among those not heard
    inside the day, dressed for the request line."""
    pool = [t for t in listener_tracks()
            if not (norepeat_on() and norepeat_record_used(t.get("id")))]
    if not pool:
        return None
    by_id = {str(t["id"]): t for t in pool if t.get("id")}
    got = unrepeated(list(by_id), "listener", keep=max(1, len(by_id) - 1),
                     director=_S3Dice("records.listener_pick", "which listener submission goes on"))
    track = by_id.get(str(got))
    if not track:
        return None
    who = str(track.get("artist") or track.get("station") or "a listener")
    return {**track, "requested": True, "listener": True, "submitted_by": who[:120]}


def dj_next_track() -> dict[str, Any] | None:
'''),
    ("lane",
     '''            _RADIO["coming"] = tape
            return tape
    if _RADIO["requests"] and _spin_request_jump():   # [s3-cover-b]
''',
     '''            _RADIO["coming"] = tape
            return tape
    # [listener-lane] now and then, a listener's own track - rolled, never forced
    if (not _RADIO["requests"] and not radio_paused() and listener_tracks()
            and s3_chance("records.listener_due", LISTENER_ODDS,
                          "a listener's submission gets its airplay (samples_grabbed/user)")):
        sub = listener_pick()
        if sub:
            sub = _spin_stamp(sub, "listener", roll="records.listener_pick",
                              due=_s3_spin_roll("records.listener_due"),
                              requested_by=sub.get("submitted_by"),
                              note="a listener sent this in for airplay")
            pipeline_log("air", "listener lane: %s by %s goes on (a submission)"
                         % (sub.get("title") or "a record", sub.get("submitted_by")))
            _RADIO["coming"] = sub
            _music_hot_warm(sub, "coming")
            _RADIO["since_tape"] = _RADIO.get("since_tape", 0) + 1
            return sub
    if _RADIO["requests"] and _spin_request_jump():   # [s3-cover-b]
'''),
    ("dj notes",
     '''    if notes:
        song_analysis_ready(track, notes)
''',
     '''    if notes:
        song_analysis_ready(track, notes)
    if track.get("listener"):                                                 # [listener-lane]
        notes = ("This record is a listener's own submission - %s sent it in for airplay. Say so, give "
                 "them a shout-out by name, and say what you actually hear in it: the sound, the mood, "
                 "the words." % (track.get("submitted_by") or "a listener")) + ((" " + notes) if notes else "")
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
    shutil.copy(path, "/tmp/app.py.bak-listener-lane")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
