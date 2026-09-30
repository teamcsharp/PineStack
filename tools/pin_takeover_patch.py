"""[pin-takeover] the video set hears the folder pin.

2026-09-30, the operator: "Make sure that it's loading clips from the right
directory ... make it where when i set the folder, it takes over fully and
properly." Measured with sfx_ads pinned: the station drew 165 of 165 clips
from the folder, and the tablet still showed samples_grabbed/bart - its
larder (240 cached clips from every folder) filled in whenever the ring had
nothing new, and a 219-clip folder soon has nothing new.

/api/dj/video now names the pin: {"pin": {"path", "ids"}} - the folder's
playable video ids when there are at most PIN_IDS_MOST of them (a bigger
folder never runs dry, so the path alone tells the set to keep its larder
shut). PineVideoWall reads it: larder only from the folder, repeats inside
it before anything outside, and a new pin drops what is queued from
elsewhere.

Usage (ON THE HOST): python3 tools/pin_takeover_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[pin-takeover]"

EDITS = [
    ("helper",
     '''def sfx_pin_set(path: str, hours: float) -> dict[str, Any]:
''',
     '''PIN_IDS_MOST = 3000
_SFX_PIN_IDS_MEMO: dict[str, Any] = {"key": "", "at": 0.0, "ids": None}


def sfx_pin_public() -> dict[str, Any] | None:
    """[pin-takeover] the pin as the video set needs it: the folder and, when it
    is not huge, every playable video id in it (memoised for a minute - the
    set polls this door)."""
    prefix = sfx_pin_prefix()
    if not prefix:
        return None
    now = time.time()
    memo = _SFX_PIN_IDS_MEMO
    if memo["key"] != prefix or now - float(memo["at"]) > 60:
        ids: list[str] | None = None
        try:
            con = sfx_db_reader()
            rows = con.execute("SELECT sid FROM clips WHERE playable = 1 AND video = 1 "
                               "AND substr(path, 1, ?) = ? LIMIT ?",
                               (len(prefix), prefix, PIN_IDS_MOST + 1)).fetchall()
            got = [str(r[0]) for r in rows]
            ids = got if len(got) <= PIN_IDS_MOST else None
        except Exception:  # noqa: BLE001
            ids = None
        memo.update({"key": prefix, "at": now, "ids": ids})
    return {"path": prefix.rstrip("/"), "ids": memo["ids"]}


def sfx_pin_set(path: str, hours: float) -> dict[str, Any]:
'''),
    ("video door",
     '''            "endless": sfx_video_mode_on(),         # 2026-09-14
            # 2026-09-15 (#1184): the hand-over style, on the poll the set
            # already makes. The station does nothing with this; it is the
            # tube's behaviour, kept here so both surfaces agree.
            "seamless": sfx_video_seam_on()}''',
     '''            "endless": sfx_video_mode_on(),         # 2026-09-14
            "pin": sfx_pin_public(),                # [pin-takeover] the folder owns the set
            # 2026-09-15 (#1184): the hand-over style, on the poll the set
            # already makes. The station does nothing with this; it is the
            # tube's behaviour, kept here so both surfaces agree.
            "seamless": sfx_video_seam_on()}'''),
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
    shutil.copy(path, "/tmp/app.py.bak-pin-takeover")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
