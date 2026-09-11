"""#1205: a turn's window is MEASURED off its own segment, not guessed.

The bug these guard against, in one line: the booth computed every turn's
window as `measured - 0.9 + 0.06 + beat`, because 0.9 is the pad a
rendered voice take carries - and then applied that to stings, board
clips, the phone ring and the hang-up, none of which carry a pad at all.
A 0.74s scratch stab was written down as 0.25s (the floor hid the rest),
the 2.20s ring as 1.36s, and everything after them in the round sat up to
a second away from the audio it named. Cutting one line out of a round -
the sampler, the booth's download - therefore handed back the tail of the
previous speaker and lost the end of the line that was asked for.

These exec the SHIPPED source, so they fail if the helpers are edited
away rather than passing against a copy of them.
"""
import io
import math
import os
import struct
import wave
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app.py"


def _shipped():
    """The #1205 helpers, lifted out of app.py and run against stubs."""
    src = io.open(APP, encoding="utf-8").read()
    start = src.index("SEG_TRIM_DB = -50.0")
    end = src.index("def _call_concat_blocking(")
    room = {
        "wave": wave, "os": os,
        "CONCAT_TAIL": 0.9, "CONCAT_KEEP": 0.06,
        "VOICE_MEDIA_DIR": Path("/data/voice_media"),
        "concat_real_seconds":
            lambda m, beat: max(0.25, m - 0.9 + 0.06 + max(0.0, beat)),
    }
    exec(compile(src[start:end], "app.py#1205", "exec"), room)  # noqa: S102
    return room


def _wav(path, seconds, tail_seconds, rate=24000, tone=True):
    """A clip of `seconds` of sound with `tail_seconds` of pure silence
    welded on the end - the shape every rendered take has."""
    frames = []
    for at in range(int(rate * seconds)):
        frames.append(int(0.4 * 32767 * math.sin(2 * math.pi * 220 * at / rate))
                      if tone else 0)
    frames += [0] * int(rate * tail_seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack("<%dh" % len(frames), *frames))
    return str(path)


def test_the_tail_is_read_off_the_file(tmp_path):
    room = _shipped()
    clip = _wav(tmp_path / "take.wav", 1.5, 0.94)
    assert room["_wav_tail_silence"](clip) == pytest.approx(0.94, abs=0.03)
    bare = _wav(tmp_path / "sting.wav", 0.74, 0.0)
    assert room["_wav_tail_silence"](bare) == pytest.approx(0.0, abs=0.03)


def test_a_sting_keeps_its_whole_length(tmp_path):
    """The heart of it. A 0.74s scratch stab off the shelf has no welded
    pad, so nothing is trimmed off it and it runs for 0.74s plus the beat
    - not the 0.25s the old floor clamped it to."""
    room = _shipped()
    sting = _wav(tmp_path / "scratch.wav", 0.74, 0.0)
    tail = room["seg_tails_for"]([sting])[0]
    real = room["seg_real_seconds"](0.74, 0.12, tail)
    assert real == pytest.approx(0.86, abs=0.03)
    # what the station used to write down for the very same clip
    assert max(0.25, 0.74 - 0.9 + 0.06 + 0.12) == pytest.approx(0.25)


def test_a_voice_take_loses_exactly_what_is_on_its_end(tmp_path):
    """A take whose engine left its own pause before the 0.9 pad loses
    ALL of it to silenceremove, not a flat 0.84."""
    room = _shipped()
    take = _wav(tmp_path / "take.wav", 4.0, 1.00)
    tail = room["seg_tails_for"]([take])[0]
    assert room["seg_real_seconds"](5.0, 0.10, tail) == pytest.approx(
        5.0 - (1.00 - 0.06) + 0.10, abs=0.04)


def test_an_unreadable_segment_falls_back_rather_than_dropping_the_round(tmp_path):
    room = _shipped()
    assert room["seg_real_seconds"](5.0, 0.1, -1.0) == pytest.approx(
        max(0.25, 5.0 - 0.9 + 0.06 + 0.1))
    gone = room["seg_tails_for"]([str(tmp_path / "not-here.wav")])
    assert gone == [-1.0]


def test_a_sample_that_is_not_a_wav_is_never_shortened_by_a_pad_it_lacks(tmp_path):
    """An mp3 off the sample shelf cannot be measured here, and the old
    assumption would take 0.9 off a file that carries nothing. Where it
    lives answers the question instead."""
    room = _shipped()
    shelf = tmp_path / "off-the-shelf.mp3"
    shelf.write_bytes(b"\x00" * 4096)
    assert room["seg_tails_for"]([str(shelf)]) == [0.0]


def test_the_round_no_longer_drifts_across_its_own_turns(tmp_path):
    """End to end on the arithmetic: a ring, four takes and two stings,
    laid out both ways. The old road's boundaries walk away from the
    audio; the new road's land on it."""
    room = _shipped()
    beats = [0.12] * 6 + [0.0]
    seg, truth = [], []
    plan = [("ring", 2.20, 0.0), ("take", 6.40, 0.96), ("sting", 0.74, 0.0),
            ("take", 8.10, 0.92), ("take", 5.30, 1.00), ("sting", 0.51, 0.0),
            ("take", 7.00, 0.90)]
    for index, (what, sound, pad) in enumerate(plan):
        seg.append(_wav(tmp_path / ("%02d-%s.wav" % (index, what)), sound, pad))
        truth.append(sound + (0.06 if pad else 0.0) + beats[index])
    measured = [sound + pad for _, sound, pad in plan]
    tails = room["seg_tails_for"](seg)

    def walk(lengths):
        at, out = 0.0, []
        for length in lengths:
            out.append(at)
            at += length
        return out

    fresh = walk([room["seg_real_seconds"](m, beats[i], tails[i])
                  for i, m in enumerate(measured)])
    stale = walk([max(0.25, m - 0.9 + 0.06 + beats[i])
                  for i, m in enumerate(measured)])
    real = walk(truth)
    assert max(abs(a - b) for a, b in zip(fresh, real)) < 0.06
    # the old road put the last turn more than a second and a half from
    # where its audio actually starts - which is the operator's clip
    # opening on somebody else's sentence.
    assert stale[-1] - real[-1] < -1.5
