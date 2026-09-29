#!/usr/bin/env python3
"""[plquiet] The station side of the two silence sliders (pinelive.py).

- settings.silence_seconds: hand the air back to the DJ after this much silence
  (default 45 s, range 10-180; was 15 s default, 2-300). The tick already
  reads it live; the separate no-frames DROPOUT path is untouched.
- settings.split_seconds (new): with album recording on, this much silence
  closes the running track (default 15 s, range 5-120; was the constant
  SPLIT_SILENCE_S = 10). Read live by the recorder, clamped under the hand-back.
- the closed track keeps SPLIT_TAIL_S (2 s) of the silence and loses the rest;
  the next track opens with SPLIT_PREROLL_S (0.5 s) of lead-in before the sound.
- a settings.json from before the sliders takes the new 45 s once (boot).
- state()["quiet"]: silent_s + both thresholds, for the status-row readout.
- tests: the old split test's lengths follow the trim; tests/test_pinelive_quiet.py.

    python3 edit_plquiet_station.py --check|--apply <repo root>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qpatch import InsertBefore, NewFile, Replace, main  # noqa: E402

M = "[plquiet]"

PY = [
    Replace('    "silence_seconds": 15.0,\n',
            '    "silence_seconds": 45.0,                           # [plquiet] hand the air back after this much silence\n'
            '    "split_seconds": 15.0,                             # [plquiet] a new album track after this much silence\n',
            '"split_seconds": 15.0,  ', "DEFAULTS"),
    Replace('    "silence_seconds": (2.0, 300.0), "silence_db": (-90.0, -20.0),\n',
            '    "silence_seconds": (10.0, 180.0), "silence_db": (-90.0, -20.0),   # [plquiet]\n'
            '    "split_seconds": (5.0, 120.0),\n',
            '"split_seconds": (5.0, 120.0)', "_RANGES"),
    Replace('        except Exception:  # noqa: BLE001\n'
            '            refused.append(key)\n'
            '    return out, refused\n',
            '        except Exception:  # noqa: BLE001\n'
            '            refused.append(key)\n'
            '    # [plquiet] a new album track has to come BEFORE the hand-back: past the\n'
            '    # hand-back the DJ already has the air, so the split follows it down.\n'
            '    try:\n'
            '        hand = float(out.get("silence_seconds") or DEFAULTS["silence_seconds"])\n'
            '        if float(out.get("split_seconds") or 0) >= hand:\n'
            '            out["split_seconds"] = max(_RANGES["split_seconds"][0], round(hand - 1.0, 2))\n'
            '    except Exception:  # noqa: BLE001\n'
            '        pass\n'
            '    return out, refused\n',
            'the split follows it down', "clean_settings clamp"),
    Replace('            got = json.loads(self.settings_path.read_text())\n'
            '            self.settings, _ = clean_settings(got)\n',
            '            got = json.loads(self.settings_path.read_text())\n'
            '            self.settings, _ = clean_settings(got)\n'
            '            if isinstance(got, dict) and "split_seconds" not in got:\n'
            '                # [plquiet] once: a settings file from before the silence sliders\n'
            '                # takes the operator\'s hand-back default (45 s) and the split\n'
            '                self.settings["silence_seconds"] = DEFAULTS["silence_seconds"]\n'
            '                self.settings, _ = clean_settings({}, self.settings)\n'
            '                try:\n'
            '                    _atomic_write(self.settings_path, json.dumps(self.settings, indent=1))\n'
            '                except Exception:  # noqa: BLE001\n'
            '                    pass\n',
            "once: a settings file from before the silence sliders", "boot migration"),
    Replace('SPLIT_SILENCE_S = 10.0\n',
            'SPLIT_SILENCE_S = 15.0          # [plquiet] the default; settings.split_seconds rules\n'
            '# [plquiet] a split keeps this much of the silence as the track\'s ring-out\n'
            '# (the rest is cut off the file); a new track opens with this much lead-in.\n'
            'SPLIT_TAIL_S = 2.0\n'
            'SPLIT_PREROLL_S = 0.5\n',
            "SPLIT_TAIL_S = 2.0", "constants"),
    InsertBefore('    def fix(self) -> None:\n'
                 '        here = self.fh.tell()\n',
                 '    def cut_to(self, nbytes: int) -> None:\n'
                 '        """[plquiet] Drop everything written after `nbytes` of audio."""\n'
                 '        nbytes = max(0, min(int(nbytes), self.bytes))\n'
                 '        self.fh.seek(len(wav_header(0)) + nbytes)\n'
                 '        self.fh.truncate()\n'
                 '        self.bytes = nbytes\n'
                 '        self.fix()\n'
                 '\n',
                 "def cut_to(self, nbytes: int)", "_Wav.cut_to"),
    Replace('                if self.inp is None:\n'
            '                    if not loud:\n'
            '                        continue                      # between tracks: nothing is recorded\n'
            '                    self._open_pair(t)\n'
            '                    self.split_waiting = False\n'
            '                self.inp.write(live if live else SILENCE)\n'
            '                self.mix.write(frame if frame else SILENCE)\n'
            '                self.frames += 1\n'
            '                self.frames_total += 1\n'
            '                self.last_frame_at = time.time()\n'
            '                if self.quiet_frames >= int(SPLIT_SILENCE_S * 1000 / FRAME_MS):   # [plsplit]\n'
            '                    self._close_pair(final=False)\n',
            '                if self.inp is None:\n'
            '                    if not loud:\n'
            '                        self._lead_keep(frame, live, t)   # [plquiet] the lead-in\n'
            '                        continue                      # between tracks: nothing is recorded\n'
            '                    lead = self._lead_take(t)            # [plquiet]\n'
            '                    self._open_pair(lead[0][2] if lead else t)\n'
            '                    self.split_waiting = False\n'
            '                    self.tail_mark = None\n'
            '                    for f0, l0, _t0 in lead:\n'
            '                        self.inp.write(l0 if l0 else SILENCE)\n'
            '                        self.mix.write(f0 if f0 else SILENCE)\n'
            '                        self.frames += 1\n'
            '                        self.frames_total += 1\n'
            '                self.inp.write(live if live else SILENCE)\n'
            '                self.mix.write(frame if frame else SILENCE)\n'
            '                self.frames += 1\n'
            '                self.frames_total += 1\n'
            '                self.last_frame_at = time.time()\n'
            '                if loud:                                  # [plquiet] where the tail ends\n'
            '                    self.tail_mark = None\n'
            '                elif self.quiet_frames == max(1, int(SPLIT_TAIL_S * 1000 / FRAME_MS)):\n'
            '                    self.tail_mark = (self.inp.bytes, self.mix.bytes, self.frames)\n'
            '                if self.quiet_frames >= self._split_frames():   # [plsplit] [plquiet] the slider\n'
            '                    self._trim_tail()\n'
            '                    self._close_pair(final=False)\n',
            "self._trim_tail()\n", "Recorder._run split"),
    InsertBefore('    def _loud(self, live: bytes | None) -> bool:\n',
                 '    def _split_frames(self) -> int:\n'
                 '        """[plquiet] settings.split_seconds in frames, read live (no restart)."""\n'
                 '        try:\n'
                 '            secs = float(self.owner.settings.get("split_seconds", SPLIT_SILENCE_S))\n'
                 '        except Exception:  # noqa: BLE001\n'
                 '            secs = SPLIT_SILENCE_S\n'
                 '        return max(10, int(round(secs * 1000 / FRAME_MS)))\n'
                 '\n'
                 '    def _trim_tail(self) -> None:\n'
                 '        """[plquiet] A silence split keeps SPLIT_TAIL_S of the quiet as the\n'
                 '        ring-out; the rest of the silence is cut off both files."""\n'
                 '        mark = getattr(self, "tail_mark", None)\n'
                 '        self.tail_mark = None\n'
                 '        if not mark or self.inp is None or self.mix is None:\n'
                 '            return\n'
                 '        self.inp.cut_to(mark[0])\n'
                 '        self.mix.cut_to(mark[1])\n'
                 '        self.frames = int(mark[2])\n'
                 '\n'
                 '    def _lead_keep(self, frame: bytes | None, live: bytes | None, t: float) -> None:\n'
                 '        """[plquiet] Between tracks: hold the last SPLIT_PREROLL_S of input."""\n'
                 '        lead = getattr(self, "lead", None)\n'
                 '        if lead is None:\n'
                 '            lead = self.lead = []\n'
                 '        lead.append((frame, live, float(t)))\n'
                 '        del lead[:-max(1, int(SPLIT_PREROLL_S * 1000 / FRAME_MS))]\n'
                 '\n'
                 '    def _lead_take(self, t: float) -> list:\n'
                 '        """[plquiet] The held lead-in, only if it is the moment just before `t`."""\n'
                 '        lead, self.lead = list(getattr(self, "lead", None) or []), []\n'
                 '        return [x for x in lead if t - SPLIT_PREROLL_S - 0.15 <= x[2] < t]\n'
                 '\n',
                 "def _split_frames(self) -> int:", "Recorder helpers"),
    Replace('"next sound" % (int(SPLIT_SILENCE_S), n - 1, n))',
            '"next sound" % (int(float(self.settings.get("split_seconds", SPLIT_SILENCE_S))),   # [plquiet]\n'
            '                                 n - 1, n))',
            'self.settings.get("split_seconds", SPLIT_SILENCE_S))),   # [plquiet]', "track_split note"),
    InsertBefore('    def _failover(self) -> dict[str, Any] | None:\n',
                 '    def _quiet(self) -> dict[str, Any]:\n'
                 '        """[plquiet] The status row\'s readout: how long the input has been\n'
                 '        silent and the two thresholds it counts toward (both read live)."""\n'
                 '        s = self.settings\n'
                 '        live = self.live\n'
                 '        out: dict[str, Any] = {\n'
                 '            "handoff_s": float(s.get("silence_seconds") or DEFAULTS["silence_seconds"]),\n'
                 '            "split_s": float(s.get("split_seconds") or SPLIT_SILENCE_S),\n'
                 '            "dropout_s": float(s.get("dropout_seconds") or 3.0),\n'
                 '            "silent_s": None, "phase": self.phase,\n'
                 '            "album": bool(self.armed() and s.get("record", True)\n'
                 '                          and not (self.event or {}).get("rehearse"))}\n'
                 '        if self.armed() and live is not None and self.phase in ("live", "fallback"):\n'
                 '            at = float(getattr(live, "signal_at", 0) or 0)\n'
                 '            if at:\n'
                 '                out["silent_s"] = round(max(0.0, time.time() - at), 1)\n'
                 '        return out\n'
                 '\n',
                 "def _quiet(self) -> dict[str, Any]:", "_quiet"),
    Replace('                           "after_s": SPLIT_SILENCE_S,\n',
            '                           "after_s": float(s.get("split_seconds", SPLIT_SILENCE_S)),   # [plquiet]\n',
            '"after_s": float(s.get("split_seconds", SPLIT_SILENCE_S)),   # [plquiet]', "state split after_s"),
    Replace('            "failover": self._failover(),                          # [plcount]\n',
            '            "failover": self._failover(),                          # [plcount]\n'
            '            "quiet": self._quiet(),                                # [plquiet]\n',
            '"quiet": self._quiet(),', "state quiet"),
]

OLD_TEST = [
    Replace('            self.assertAlmostEqual(rows[0]["seconds"], (20 + split) * pinelive.FRAME_MS / 1000.0)\n'
            '            self.assertAlmostEqual(rows[1]["seconds"], 15 * pinelive.FRAME_MS / 1000.0)\n',
            '            tail = int(pinelive.SPLIT_TAIL_S * 1000 / pinelive.FRAME_MS)       # [plquiet] ring-out kept\n'
            '            pre = int(pinelive.SPLIT_PREROLL_S * 1000 / pinelive.FRAME_MS)     # [plquiet] lead-in\n'
            '            self.assertAlmostEqual(rows[0]["seconds"], (20 + tail) * pinelive.FRAME_MS / 1000.0)\n'
            '            self.assertAlmostEqual(rows[1]["seconds"], (pre + 15) * pinelive.FRAME_MS / 1000.0)\n',
            "# [plquiet] ring-out kept", "split test lengths"),
]

NEW_TEST = (Path(__file__).resolve().parent / "test_pinelive_quiet.py").read_text(encoding="utf-8")

PLAN = {
    "pinelive.py": PY,
    "tests/test_pinelive.py": OLD_TEST,
    "tests/test_pinelive_quiet.py": [NewFile(NEW_TEST, M)],
}

if __name__ == "__main__":
    sys.exit(main(PLAN))
