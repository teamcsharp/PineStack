"""[publish-stamp] a line handed to the page carries its clip's own air moment.

2026-09-30, the operator: "With the dice off, I'm expecting to see line after
line after line ... consistently" and "no one is responding to the previous
person". Measured on round e0711596: three renders of one conversation, each
one welded wav, aired strictly one after another (heard_ack_at: render 1 whole,
then 2, then 3). The Script view drew them interleaved - render 2's "Go on."
between render 1's caller lines, render 3's opener above render 2's last line.

Every line's `air_at` is the RENDER estimate (_est0 + its offset in the wav),
taken when the round finished rendering. page_feed_append then stamps the clip
honestly - chained behind every clip already sold (_PAGE_AIR_UNTIL, the
playout floor) - but page_delivery_apply moves the line to `published` without
reading that stamp, and #1288 freezes `air_at` from then until the ear answers.
So a render finished while another was still sounding was drawn up to 84 s
early, inside the conversation in front of it, and the Script view's linear
rule (#1279 / [s3-script-linear]) keeps what it drew above the airing row.

Now the hand-over stamps each line at the clip's broadcast_ms plus the line's
own window in the wav, while it is still `prepared` - the last estimate before
the ear's. The ear (#1218) still corrects it exactly once.

Usage (ON THE HOST): python3 tools/publish_stamp_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[publish-stamp]"

OLD = '''    elif str(entry.get("aired") or "") not in ("box", "held"):
        entry["aired"] = "published"


def _page_delivery_rows('''
NEW = '''    elif str(entry.get("aired") or "") not in ("box", "held"):
        # [publish-stamp] the clip's honest start plus the line's window in it,
        # taken before `published` freezes the render estimate (#1288)
        try:
            _ps_clip = delivery.get("clip") or {}
            _ps_ms = float(_ps_clip.get("broadcast_ms") or 0)
            _ps_rows = list((_ps_clip.get("stream") or {}).get("rows") or [])
            if entry.get("clip_from") is not None:
                _ps_off = float(entry.get("clip_from") or 0)
            elif len(_ps_rows) <= 1:
                _ps_off = 0.0
            else:
                _ps_off = None
            if _ps_ms > 0 and _ps_off is not None:
                air_at_set(entry, _ps_ms / 1000.0 + _ps_off)
        except Exception:  # noqa: BLE001
            pass
        entry["aired"] = "published"


def _page_delivery_rows('''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "anchor %d" % src.count(OLD)
    out = src.replace(OLD, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-publish-stamp")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
