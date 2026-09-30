"""[mix-prime] A personal mix is heard at once, not after half a minute.

2026-09-30: a tester on Safari set music 0 / DJ 0 and "the sliders are not
reactive". A new personal-mix lane was PRIMED with the station's DEFAULT mix
(the backlog held only finished frames), and the player starts 30-45 s behind
live - inside that prime - so every slider change played half a minute of the
old balance before the listener's own arrived.

  station_stream  the mixer banks each frame's STEMS (bed, voice, sting-or-line)
                  beside the frame, in one ring so they cannot drift apart; a
                  personal-mix or split lane is primed (and re-primed after a
                  restart) from them, re-mixed at ITS mix. The default lane is
                  primed exactly as before.
  tune page       the slider wait is 700 ms (was 1500): one lane per listener
                  ([mix-lane]) is what bounds the encoders now, not the wait.
Anchor-asserted; run on the host."""
import ast
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def sub(text, old, new, name):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"anchor {name}: found {n} times")
    return text.replace(old, new)


q = ROOT / "station_stream.py"
s = q.read_text()
if "[mix-prime]" in s:
    raise SystemExit("station_stream.py already patched")
s = sub(s, '''        self._pcm_burst: deque[bytes] = deque(
            maxlen=max(1, int(JOIN_BURST_SECONDS * 1000 / FRAME_MS)))
''', '''        self._pcm_burst: deque[bytes] = deque(
            maxlen=max(1, int(JOIN_BURST_SECONDS * 1000 / FRAME_MS)))
        # [mix-prime] the same half-minute as STEMS: (frame, bed, voice,
        # voice-is-a-sting) per entry, int16, so a personal-mix lane can be
        # primed in its own balance. One ring, so frame and stems never drift.
        self._stem_burst: deque = deque(maxlen=self._pcm_burst.maxlen)
''', "init")
s = sub(s, '''    def _burst_copy(self) -> list[bytes]:
''', '''    def _bank(self, frame: bytes, bed: Any, voice: Any, is_sfx: bool) -> None:
        """[mix-prime] One frame of real programme into both backlogs."""
        self._pcm_burst.append(frame)
        self._stem_burst.append((frame, _stem16(bed), _stem16(voice), bool(is_sfx)))

    def _burst_for(self, key: tuple[bool, tuple[int, int, int]]) -> list[bytes]:
        """[mix-prime] The backlog in THIS lane's balance: the default lane's
        frames as banked, a personal or split lane's re-mixed from the stems
        (a frame banked without stems is handed over as it was)."""
        if key == _DEFAULT_LANE:
            return self._burst_copy()
        split, mix = key
        try:
            stems = list(self._stem_burst)
        except RuntimeError:
            stems = list(self._stem_burst)
        make = _split_program if split else _mixed_program
        out: list[bytes] = []
        for frame, bed, voice, is_sfx in stems:
            if bed is None:
                out.append(frame)
            else:
                out.append(make(bed, voice, is_sfx, mix))
        return out

    def _burst_copy(self) -> list[bytes]:
''', "helpers")
s = sub(s, '''        lane = _HlsEncoder(self._hls_root, key[1], key[0], bitrate)
        lane.backlog = self._burst_copy
''', '''        lane = _HlsEncoder(self._hls_root, key[1], key[0], bitrate)
        lane.backlog = lambda: self._burst_for(key)          # [mix-prime]
''', "lane-backlog")
s = sub(s, '''        if lane.start():
            backlog = self._burst_copy()
            if lost is not None and lane.start_info.get("how") == "resume":
''', '''        if lane.start():
            backlog = self._burst_for(key)                   # [mix-prime]
            if lost is not None and lane.start_info.get("how") == "resume":
''', "lane-prime")
s = sub(s, '''                if made_sound:
                    self._pcm_burst.append(frame)
''', '''                if made_sound:
                    self._bank(frame, bed, voice_pcm,           # [mix-prime]
                               bool(airing is not None and airing.sfx))
''', "bank")
s = sub(s, '''def _mixed_program(bed: np.ndarray, voice: np.ndarray | None,
''', '''def _stem16(pcm: Any) -> "np.ndarray | None":
    """[mix-prime] A stem kept for the backlog: int16, clipped, a copy."""
    if pcm is None:
        return None
    return np.clip(pcm, -32768, 32767).astype(np.int16)


def _mixed_program(bed: np.ndarray, voice: np.ndarray | None,
''', "stem16")
ast.parse(s)

p = ROOT / "app.py"
a = p.read_text()
if "[mix-prime]" in a:
    raise SystemExit("app.py already patched")
a = sub(a, '''        mixNotApplied("the station did not answer");
        }
      });
  }, 1500);
}
''', '''        mixNotApplied("the station did not answer");
        }
      });
  }, 700);   /* [mix-prime] one lane per listener bounds the encoders now */
}
''', "debounce")
ast.parse(a)

q.write_text(s)
p.write_text(a)
print("patched station_stream.py and app.py")
