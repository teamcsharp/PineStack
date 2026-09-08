"""Concatenate one real saved round with isolated output and no publication."""
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
actual = Path("/app/data")
isolated = Path(os.environ.get("SPARK_AGENT_DATA_DIR") or "/app/data")
if isolated.resolve() == actual.resolve() or not str(isolated.resolve()).startswith("/tmp/"):
    raise SystemExit("Use a dedicated SPARK_AGENT_DATA_DIR beneath /tmp")

import app


def main():
    sid = "gallery-204adcc544"
    shelf = json.loads((actual / "prep_shelf.json").read_text(encoding="utf-8"))
    pantry = json.loads((actual / "pantry.json").read_text(encoding="utf-8"))
    row = next(r for r in shelf["gallery"] if r.get("sid") == sid)
    entry = row["entry"]
    takes = sorted(entry["takes"], key=lambda t: int(t["i"]))
    assert len(takes) == 18 and [t["i"] for t in takes] == list(range(18))
    keys = [t["key"] for t in takes]
    assert len(set(keys)) == 17
    paths = [actual / "voice_media" / str(pantry[key]["clip"]["path"]).rsplit("/", 1)[-1].split("?", 1)[0]
             for key in keys]
    assert all(p.is_file() and p.stat().st_size > 0 for p in paths)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in set(paths)}
    work = isolated / "concat-output"
    work.mkdir(parents=True, exist_ok=True)
    command_inputs = []
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        inputs = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "-i"]
        assert inputs == [str(p) for p in paths], "Concatenator changed source order or deduplicated an input"
        assert Path(command[-1]).resolve().is_relative_to(work.resolve()), "Output escaped isolated directory"
        command_inputs.extend(inputs)
        return real_run(command, *args, **kwargs)

    started = time.monotonic()
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(tempfile, "tempdir", str(work)))
        stack.enter_context(mock.patch.object(subprocess, "run", side_effect=run))
        for name in ("_store_media", "voice_render_any", "ask_model", "page_feed_append", "_play_on_box"):
            stack.enter_context(mock.patch.object(app, name, side_effect=AssertionError("Forbidden production operation")))
        beats = [0.20] * (len(paths) - 1) + [0.0]
        blob = app._call_concat_blocking([str(p) for p in paths], crackle=False, beats=beats)
    assert blob and len(blob) > 4000, "Production concatenator returned no complete media"
    with wave.open(io.BytesIO(blob), "rb") as wav:
        frames, rate, channels, width = wav.getnframes(), wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        pcm = wav.readframes(frames)
    assert (rate, channels, width) == (24000, 1, 2)
    assert len(pcm) == frames * channels * width and any(pcm), "WAV size header or audio payload is invalid"
    seconds = frames / rate
    saved_seconds = sum(float(t.get("seconds") or 0) for t in takes)
    assert 0 < seconds <= saved_seconds + sum(beats) + 2, "Combined WAV has an impossible duration"
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in set(paths)}
    assert before == after, "An original source recording was modified"
    output = work / (sid + ".wav")
    output.write_bytes(blob)
    report = {
        "scope": "Actual production concatenation only; no live routing, publication, synthesis, or playback",
        "sid": sid, "ordered_input_positions": len(command_inputs), "unique_input_files": len(set(paths)),
        "input_order_verified": command_inputs == [str(p) for p in paths],
        "saved_input_seconds": round(saved_seconds, 2), "output_seconds": round(seconds, 3),
        "output_bytes": len(blob), "sample_rate": rate, "channels": channels, "sample_width_bytes": width,
        "header_matches_pcm": True, "nonempty_signal": True, "source_hashes_unchanged": before == after,
        "output_sha256": hashlib.sha256(blob).hexdigest(), "isolated_output": str(output),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "outer_eligibility_limit": "Live profile, tint, operator withdrawal and transport checks remain authoritative",
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
