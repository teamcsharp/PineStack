"""[pltoggle] pinelive.py: the album switch works mid-set and is remembered.

- Recorder.suspend(): album off mid-set closes the running track cleanly
  (a sub-second stub is dropped) and writes nothing more - no tracks, no
  silence splits, no decant - until the next begin().
- PineLive._album_flip(): set_settings() calls it when `record` changes. Armed:
  on = begin() into the set's folder at the next index (a track opens with the
  next sound); off = suspend(). Idle: the choice is only remembered.
- The choice IS settings.record (data/pinelive/settings.json, written by the
  station), so the next Pine Live set starts with whatever was last used.
- control.master (the host's safety master WAVs) follows the album switch.
- state().recording.album / event_state().record.album carry the choice.

  python edit_pltoggle_py.py [--check|--apply] pinelive.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pltoggle_lib  # noqa: E402

EDITS = [
    ("recorder.held",
     '        self.why = ""\n'
     '        self._thread = threading.Thread(target=self._run, name="pinelive-cuts", daemon=True)\n',
     '        self.why = ""\n'
     '        self.held = False                      # [pltoggle] album off: frames are not written\n'
     '        self._thread = threading.Thread(target=self._run, name="pinelive-cuts", daemon=True)\n',
     "self.held = False                      # [pltoggle]"),

    ("recorder.suspend",
     '    def next_track(self) -> None:\n'
     '        """[pltrack] Close the running cut pair now; the next frame opens a new one."""\n',
     '    def suspend(self) -> None:\n'
     '        """[pltoggle] Album recording off mid-set: close the running track\n'
     '        cleanly and write nothing more until the next begin()."""\n'
     '        self.active = False\n'
     '        done = threading.Event()\n'
     '        self.q.put(("suspend", done))\n'
     '        done.wait(20.0)\n'
     '\n'
     '    def next_track(self) -> None:\n'
     '        """[pltrack] Close the running cut pair now; the next frame opens a new one."""\n',
     '    def suspend(self) -> None:\n        """[pltoggle]'),

    ("recorder.run.suspend",
     '                    self.split_waiting = False\n'
     '                    continue\n'
     '                if item and item[0] == "end":\n',
     '                    self.split_waiting = False\n'
     '                    self.held = False                  # [pltoggle] recording again\n'
     '                    continue\n'
     '                if item and item[0] == "suspend":      # [pltoggle] album off: close cleanly\n'
     '                    self._close_pair(final=False, drop_short=True)\n'
     '                    self.quiet_frames = 0\n'
     '                    self.split_waiting = False\n'
     '                    self.held = True\n'
     '                    item[1].set()\n'
     '                    continue\n'
     '                if item and item[0] == "end":\n',
     'if item and item[0] == "suspend":      # [pltoggle]'),

    ("recorder.run.held",
     '                if self.folder is None:\n'
     '                    continue\n'
     '                # [plsplit] tracks split on silence, not the clock\n',
     '                if self.folder is None or getattr(self, "held", False):   # [pltoggle]\n'
     '                    continue\n'
     '                # [plsplit] tracks split on silence, not the clock\n',
     'getattr(self, "held", False):   # [pltoggle]'),

    ("recorder.close_pair.sig",
     '    def _close_pair(self, final: bool) -> None:\n',
     '    def _close_pair(self, final: bool, drop_short: bool = False) -> None:   # [pltoggle]\n',
     'drop_short: bool = False) -> None:   # [pltoggle]'),

    ("recorder.close_pair.short",
     '        if final and frames < 10:              # under a second: not a cut\n',
     '        if (final or drop_short) and frames < 10:   # under a second: not a cut [pltoggle]\n',
     'if (final or drop_short) and frames < 10:'),

    ("settings.album_flip_call",
     '        if self.armed():\n'
     '            self.write_control()\n'
     '        if old.get("tailscale_video") != new.get("tailscale_video"):\n',
     '        if self.armed():\n'
     '            self.write_control()\n'
     '        if bool(old.get("record", True)) != bool(new.get("record", True)):   # [pltoggle]\n'
     '            self._album_flip(bool(new.get("record", True)))\n'
     '        if old.get("tailscale_video") != new.get("tailscale_video"):\n',
     'self._album_flip(bool(new.get("record", True)))'),

    ("pinelive.album_methods",
     '    def _live_params(self) -> None:\n',
     '    def _album_start(self) -> None:\n'
     '        """[pltoggle] Album recording begins: the set\'s folder at the next\n'
     '        free index; a track opens with the next sound."""\n'
     '        if self.recorder is None or self.event is None or self.event.get("rehearse"):\n'
     '            return\n'
     '        folder_name = str(self.event.get("folder") or self.event_id())\n'
     '        folder = self.cuts_root / folder_name\n'
     '        first = 1\n'
     '        try:\n'
     '            got = [int(m.group(1)) for p in folder.glob("*_c*_mix.*")\n'
     '                   for m in [re.search(r"_c(\\d+)_mix\\.", p.name)] if m]\n'
     '            first = max(got) + 1 if got else 1\n'
     '        except Exception:  # noqa: BLE001\n'
     '            first = 1\n'
     '        if self.recorder.folder == folder:\n'
     '            first = max(first, int(self.recorder.index) + 1)\n'
     '        self.recorder.begin(folder, folder_name, float(self.settings["cut_seconds"]),\n'
     '                            str(self.settings["format"]), first)\n'
     '\n'
     '    def _album_flip(self, on: bool) -> None:\n'
     '        """[pltoggle] The album switch. The choice is settings.record, so it is\n'
     '        remembered and the next set starts with it; mid-set it starts or\n'
     '        suspends the recording from this moment - the set airs either way."""\n'
     '        if not self.armed() or bool((self.event or {}).get("rehearse")):\n'
     '            self.note("album", "album recording %s - remembered for the next set"\n'
     '                      % ("ON" if on else "OFF"))\n'
     '            return\n'
     '        if self.event is not None:\n'
     '            self.event["album"] = on\n'
     '        if on:\n'
     '            self._album_start()\n'
     '            self.note("album", "album recording ON mid-set - a track opens with the next sound")\n'
     '        elif self.recorder is not None:\n'
     '            self.recorder.suspend()\n'
     '            self.note("album", "album recording OFF mid-set - the running track closed; "\n'
     '                      "the set plays on and nothing more is written")\n'
     '        self._save_event()\n'
     '\n'
     '    def _live_params(self) -> None:\n',
     '    def _album_flip(self, on: bool) -> None:\n        """[pltoggle]'),

    ("control.master",
     '                  "master": not bool((self.event or {}).get("rehearse"))})   # [plair]\n',
     '                  "master": (not bool((self.event or {}).get("rehearse"))   # [plair]\n'
     '                             and bool(s.get("record", True)))})   # [pltoggle] album off: no master\n',
     '# [pltoggle] album off: no master'),

    ("start.event_album",
     '                          "fallbacks": 0, "rehearse": rehearse}\n',
     '                          "fallbacks": 0, "rehearse": rehearse,\n'
     '                          "album": bool(s.get("record", True)) and not rehearse}   # [pltoggle]\n',
     '"album": bool(s.get("record", True)) and not rehearse}   # [pltoggle]'),

    ("start.say_album",
     '        self.note("start", "MX Live armed (%s%s) - the music keeps playing until the "\n'
     '                  "input is heard" % (source, (" " + device) if device else ""))\n'
     '        return {"ok": True, "code": "", "say": "MX Live is armed - waiting for the "\n'
     '                "first sound from the %s" % ("K.O. II" if source == "usb" else "sender")}\n',
     '        album = bool(s.get("record", True))                        # [pltoggle]\n'
     '        self.note("start", "MX Live armed (%s%s) - the music keeps playing until the "\n'
     '                  "input is heard; album recording %s" % (\n'
     '                      source, (" " + device) if device else "", "on" if album else "off"))\n'
     '        return {"ok": True, "code": "", "say": "MX Live is armed - waiting for the "\n'
     '                "first sound from the %s; album recording %s" % (\n'
     '                    "K.O. II" if source == "usb" else "sender",\n'
     '                    "on" if album else "off (the set airs, nothing is written)")}\n',
     'album = bool(s.get("record", True))                        # [pltoggle]'),

    ("state.recording_album",
     '                "on": bool(armed and s.get("record", True)),\n',
     '                "on": bool(armed and s.get("record", True)\n'
     '                           and not (self.event or {}).get("rehearse")),     # [pltoggle]\n'
     '                "album": bool(s.get("record", True)),      # [pltoggle] the remembered choice\n',
     '"album": bool(s.get("record", True)),      # [pltoggle]'),

    ("event_state.album",
     '                rec = {"cut_index": self.recorder.index, "cuts": len(self.recorder.cuts)}\n',
     '                rec = {"cut_index": self.recorder.index, "cuts": len(self.recorder.cuts),\n'
     '                       "album": bool(self.settings.get("record", True))}   # [pltoggle]\n',
     '"album": bool(self.settings.get("record", True))}   # [pltoggle]'),
]


if __name__ == "__main__":
    sys.exit(pltoggle_lib.main(lambda path: EDITS))
