"""[call-voice-roll] every call rolls a System 3 roulette over the voice models of
the engine the operator set - and never onto another engine.

"for customer calls in system three. I want them rolling a roulette for what voice
model is being chosen from the list of available voice model for that particular
set engine." Asked about callers heard before: "roll every call but keep it on
the same model. Dont switch engines without me doing it manually."

caller_voice_for kept a returning caller's remembered voice and gave a new one a
hidden s3_choice among a tie of the least-used; the pool (caller_clone_pool) held
the voices of BOTH clone engines, so with no station-wide clone_engine set a voice
marked F5 rang in on F5 while the cast was on XTTS. Now the pool is only the voices
whose real engine (_engine_now) is host_clone_engine(), and every call is a
visible weighted roll (s3_weighted "call.voice_model", least-aired heaviest). The
pick is still written in the book, but no longer forces the next call.

Usage (ON THE HOST): python3 tools/caller_voice_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

OLD = '''        book = _caller_voice_book()
        held = book.get(name)
        if held and held in usable:
            return held
        air = voice_airtime()
'''
NEW = '''        # [call-voice-roll] "roll every call but keep it on the same model.
        # Dont switch engines without me doing it manually": the roulette is
        # every voice of the engine the operator set - and only those.
        try:
            _set = host_clone_engine()
            _same = [v for v in usable if _engine_now(voice_meta(v) or {}) == _set]
        except Exception:  # noqa: BLE001
            _set, _same = "", list(usable)
        if _same:
            _air = voice_airtime()
            _w = [1.0 / (1.0 + float((_air.get(v) or {}).get("airings") or 0)) for v in _same]
            _i = s3_weighted("call.voice_model", _same, _w,
                             "which voice model of the %s engine this caller rings in with (every call; "
                             "the least-aired weigh most)" % (_set or "set"))
            pick = _same[int(_i)] if 0 <= int(_i) < len(_same) else _same[0]
            _caller_voice_remember(name, pick)
            return pick
        book = _caller_voice_book()
        held = book.get(name)
        if held and held in usable:
            return held
        air = voice_airtime()
'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if "[call-voice-roll]" in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "anchor found %d times" % src.count(OLD)
    out = src.replace(OLD, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/app.py.bak-call-voice-roll")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
