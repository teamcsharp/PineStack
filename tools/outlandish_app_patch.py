#!/usr/bin/env python3
"""[outlandish] app.py: the OUTLANDISH meter, its audit log, the interjection's
mini-round and the SFX Guy's reaction, wired into the station. No word is ever
filtered, softened, blocked or rewritten: it measures, surfaces and reacts.

  A1  [outl-install]        outlandish_runtime.install() after System 3 (hooks via globals().get)
  A2  [outl-air]            the air log's writer thread scores every sounded row (off the loop)
  A3  [outl-react]          the round's assembly: a line at the react threshold gets the SFX
                            Guy's rolled reaction clip between it and the next turn
  A4  [outl-react-chapter]  a line's exchange: the reaction after the opener, before the reply
  A5  [outl-prime]          a line's exchange: once the opener's words are known its replies are
                            re-rolled with the dispute odds (Mode B observe + replan)
  A6  [outl-oneline]        the ad's out-bumper plans no exchange (a one-liner)
  A7  [outl-bumper-road]    ...and is a node on the ad road (ad_spot), traced with the ad
  A8  [outl-bumper]         dj_ad's hand-back line goes out as the ad's (round_as="ad")
  A9  [outl-hold]           the emergency reserve reached: HOLDBANTER1 rolls a hosts' aside
                            beside the SFX Guy's time-buyers (never a holding line)
  A10 [outl-aside-ask]      dj_line: an aside's task is its direction
  A11 [outl-aside-bank]     dj_line: an aside's fallback phrases

usage: outlandish_app_patch.py --check|--apply app.py   (0 ready, 2 applied, 1 missing)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outlandish_patchlib import run  # noqa: E402

EDITS = [
    ("[outl-install]", "after",
     '    print("system3 did not install: %s: %s" % (type(_system3_exc).__name__, _system3_exc))\n',
     '# [outl-install] THE OUTLANDISH METER (outlandish.py, outlandish_runtime.py, sfx_repertoire.py):\n'
     '# every aired line measured 0-100 (never filtered), the audit log, the dispute odds, the\n'
     '# interjection\'s mini-round and the SFX Guy\'s reaction. Its hooks are reached through\n'
     '# globals().get(), so an install that fails leaves the station exactly as it was.\n'
     'try:\n'
     '    from outlandish_runtime import install as install_outlandish\n'
     '    _OUTLANDISH_RUNTIME = install_outlandish(app, globals())\n'
     'except Exception as _outl_exc:  # noqa: BLE001\n'
     '    _OUTLANDISH_RUNTIME = None\n'
     '    print("the outlandish meter did not install: %s: %s" % (type(_outl_exc).__name__, _outl_exc))\n'),
    ("[outl-air]", "replace",
     '                                       str(row.get("id") or ""), row.get("air_at"))\n'
     '                if (row.get("who") in AIRLOG_CAST\n',
     '                                       str(row.get("id") or ""), row.get("air_at"))\n'
     '                _outl_note = globals().get("outlandish_note_row")          # [outl-air] the meter, off the loop\n'
     '                if _outl_note is not None and (row.get("aired") in NOREPEAT_SOUNDED or row.get(HEARD_STAMP)):\n'
     '                    _outl_note(row)\n'
     '                if (row.get("who") in AIRLOG_CAST\n'),
    ("[outl-react]", "after",
     '\n                    _sting = "" if _keep_mic else sting_due()\n',
     '                    # [outl-react] a line at the meter\'s react threshold: the SFX Guy\'s reaction,\n'
     '                    # rolled on SFXREACT1, drops between it and the next turn (before the reply)\n'
     '                    _outl_rx = globals().get("outlandish_react_clip")\n'
     '                    if not _keep_mic and _outl_rx is not None and item["who"] not in ("board", "drop"):\n'
     '                        try:\n'
     '                            _rx_clip = _outl_rx(spoken_text(item["chunk"]), item["who"], ready_meta, "round")\n'
     '                        except Exception:  # noqa: BLE001\n'
     '                            _rx_clip = None\n'
     '                        if _rx_clip:\n'
     '                            _sting = _rx_clip\n'),
    ("[outl-react-chapter]", "after",
     '    rows, clips = list(e.get("rows") or []), list(e.get("clips") or [])\n'
     '    i = max(1, int(e.get("done") or 0))\n',
     '    if i == 1 and not e.get("outl_reacted"):                                 # [outl-react-chapter]\n'
     '        e["outl_reacted"] = True       # the SFX Guy\'s reaction: after the opener, before the reply\n'
     '        _outl_between = globals().get("outlandish_react_between")\n'
     '        if _outl_between is not None:\n'
     '            try:\n'
     '                await _outl_between(e, track)\n'
     '            except Exception:  # noqa: BLE001\n'
     '                pass\n'),
    ("[outl-prime]", "before",
     '    return await _s3_chapter_take(e, lend=True)\n',
     '    _outl_prime = globals().get("outlandish_prime_chapter")                  # [outl-prime]\n'
     '    if _outl_prime is not None and not e.get("outl_primed"):\n'
     '        e["outl_primed"] = True        # the replies re-rolled once the opener\'s words are known\n'
     '        try:\n'
     '            _outl_prime(e.get("stamp") or stamp, str(e.get("opening") or spoken))\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'),
    ("[outl-oneline]", "replace",
     '                text=str(line or "")[:600], bank=bool(clip))\n',
     '                text=str(line or "")[:600], bank=bool(clip),\n'
     '                one_line=("the ad\'s out-bumper" if round_as == "ad" else ""))   # [outl-oneline]\n'),
    ("[outl-bumper-road]", "before",
     '        try:\n'
     '            _s3_spoken_handle = await system3_direct_line(\n',
     '        if kind == "interject" and round_as == "ad":                          # [outl-bumper-road]\n'
     '            try:\n'
     '                import system3 as _s3m\n'
     '                if _s3m.road_mode(globals()["_system3"]().settings, "ad_spot") != "off":\n'
     '                    _s3_road = "ad_spot"   # the ad\'s out-bumper is the ad road\'s, traced with the ad\n'
     '            except Exception:  # noqa: BLE001\n'
     '                pass\n'),
    ("[outl-bumper]", "replace",
     '            "interject", _RADIO["now"],\n',
     '            "interject", _RADIO["now"], round_as="ad",   # [outl-bumper] the ad road\'s closing turn\n'),
    ("[outl-hold]", "replace",
     '    if norepeat_on():\n'
     '        _went = await sfx_fill_gap(reason or "the emergency reserve was reached")\n',
     '    if norepeat_on():\n'
     '        _outl_hold = globals().get("outlandish_hold_roll")                  # [outl-hold] HOLDBANTER1\n'
     '        if _outl_hold is not None:\n'
     '            try:\n'
     '                _outl_hold(reason or "the emergency reserve was reached")\n'
     '            except Exception:  # noqa: BLE001\n'
     '                pass\n'
     '        _went = await sfx_fill_gap(reason or "the emergency reserve was reached")\n'),
    ("[outl-aside-ask]", "after",
     '        "reply": f"reply to what the host just said to you: {extra}",\n',
     '        "aside": (extra or "say one short, standalone thing, in character"),   # [outl-aside-ask]\n'),
    ("[outl-aside-bank]", "after",
     '        "media": dj["interject_phrases"],\n',
     '        "aside": dj["interject_phrases"],   # [outl-aside-bank]\n'),
]

if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))
