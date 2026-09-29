"""[pinestream] pinelive.py: PineStream's settings ride PineLive's (the same
road as PineCam to live), its flips are counted for the viewers' CRT, and the
panel's state carries a `stream` block.

    python edit_pinestream_pinelive.py --check|--apply <spark-agent root>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from patchlib import Edit, Insert, main  # noqa: E402

T = "pinelive.py"

EDITS = [
    Insert(T, '"stream_on": False,', '    "tailscale_video": False,\n',
           '    "stream_on": False,                                # [pinestream] off by default; the master\n'
           '    "stream_source": "pinetab",                        # [pinestream] pinetab | pineapp\n'
           '    "stream_fps": 2,                                   # [pinestream] 1..5 a second\n'
           '    "stream_width": 640,                               # [pinestream] 320..960 px\n'
           '    "stream_quality": 60,                              # [pinestream] JPEG 30..90\n'),
    Insert(T, '"stream_fps": (1, 5)',
           '    "return_seconds": (0.2, 30.0), "arm_timeout": (3.0, 300.0),\n}\n',
           '_RANGES.update({"stream_fps": (1, 5), "stream_width": (320, 960),   # [pinestream]\n'
           '                "stream_quality": (30, 90)})\n'),
    Edit(T, '"tailscale_video", "stream_on"):',
         '            if key in ("enabled", "record", "tailscale_video"):\n',
         '            if key in ("enabled", "record", "tailscale_video", "stream_on"):   # [pinestream]\n'),
    Insert(T, 'elif key == "stream_source":', '            elif key == "channel_mode":\n',
           '            elif key == "stream_source":                       # [pinestream]\n'
           '                if str(value) not in ("pinetab", "pineapp"):\n'
           '                    raise ValueError\n'
           '                out[key] = str(value)\n',
           where="before"),
    Insert(T, 'self.stream_flips = int(',
           '                "ON: listeners on the tailnet see the picture" if new["tailscale_video"]\n'
           '                else "OFF: the public side stops showing video now"))\n',
           '        if bool(old.get("stream_on")) != bool(new.get("stream_on")):          # [pinestream]\n'
           '            self.stream_flips = int(getattr(self, "stream_flips", 0)) + 1\n'
           '            self.note("pinestream", "PineStream %s" % (\n'
           '                ("ON: listeners see " + ("the Pine app" if new.get("stream_source") == "pineapp"\n'
           '                                          else "the PineTab"))\n'
           '                if new.get("stream_on") else "OFF: nothing is captured or served"))\n'),
    Insert(T, 'def stream_state(self)', '    def video_switch(self) -> dict[str, Any]:\n',
           '    def stream_state(self) -> dict[str, Any]:\n'
           '        """[pinestream] PineStream for the panel: the switch and the choices\n'
           '        (settings), and - when the station module is loaded - what is\n'
           '        arriving and who is watching (pinestream.status())."""\n'
           '        s = self.settings\n'
           '        out: dict[str, Any] = {\n'
           '            "on": bool(s.get("stream_on")), "source": str(s.get("stream_source") or "pinetab"),\n'
           '            "fps": s.get("stream_fps"), "width": s.get("stream_width"),\n'
           '            "quality": s.get("stream_quality"), "flips": int(getattr(self, "stream_flips", 0)),\n'
           '            "picture": "off" if not s.get("stream_on") else "waiting"}\n'
           '        try:\n'
           '            import sys\n'
           '            ps = sys.modules.get("pinestream")\n'
           '            if ps is not None and hasattr(ps, "status"):\n'
           '                out.update(ps.status())\n'
           '        except Exception:  # noqa: BLE001\n'
           '            pass\n'
           '        return out\n'
           '\n',
           where="before"),
    Insert(T, '"stream": self.stream_state(),',
           '            "picture": {"mode": s["picture_mode"], "tailscale_video": bool(s["tailscale_video"]),\n',
           '            "stream": self.stream_state(),                  # [pinestream]\n',
           where="before"),
]


def verify(root: Path):
    import py_compile
    try:
        py_compile.compile(str(root / T), doraise=True)
        return True, "py_compile ok"
    except Exception as err:  # noqa: BLE001
        return False, str(err)


if __name__ == "__main__":
    sys.exit(main(EDITS, after_apply=verify))
