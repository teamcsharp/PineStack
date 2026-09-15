#!/usr/bin/env python3
"""take_bench.py - measure the continuous take against today's segmented one.

docs/notes/speaker-recording-and-script-assembly.md orders a measurement and
forbids the assertion that usually stands in for it:

    "Measure both approaches before claiming that larger requests are faster.
    Record production time, accepted audio duration, retries, missing/repeated
    speech, cut accuracy and listening quality using the same scripts and
    cast."

Same scripts and same cast is the point, so this reads REAL rounds out of the
station's own larder (`data/larder.json`), where each prepared entry already
carries its frozen per-chunk text, the voice it was assigned and the order it
is read in. Nothing here invents a line.

For each performer in each round it runs two roads:

  SEGMENTED   one engine request per frozen chunk, the station's road today.
              The boundaries are free: each request IS a line.
  CONTINUOUS  the performer's whole part in ONE engine request, then
              voice-lab /align matches the recogniser's words against the
              frozen script and returns per-occurrence cuts or a refusal.

It writes down production time, accepted audio seconds, retries, the
alignment's missing/repeated/extra word counts, per-cut boundary error
against the segmented durations, and a listening-quality read (whisper
read-back CER, logprob, compression) from voice-lab /verify.

It also probes the adapter ceilings the note names as facts, because a
"continuous take" that is silently truncated is the worst of the three
outcomes: it looks like the best one.

READ-ONLY with respect to the station. It calls the engines directly
(127.0.0.1:8770 XTTS, :8772 F5, :8771 voice-lab) rather than any station
route, writes only under an output directory you name, and touches no live
store, no pantry and no shelf.

Run it where 127.0.0.1 reaches the engines - the spark-agent container is on
the host network, so:

    docker exec spark-agent python /app/tools/take_bench.py \
        --rounds 5 --out /app/data/bench/take_bench_2026_09_15

    docker exec spark-agent python /app/tools/take_bench.py --probe-only
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import statistics
import sys
import time
import wave
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from line_alignment import (MODE_CONTINUOUS, MODE_SEGMENTED,  # noqa: E402
                            AlignmentPolicy, ScriptLine, align_script,
                            from_whisper_words, normalize_tokens,
                            result_to_json)

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("SPARK_DATA", ROOT / "data"))
XTTS = os.getenv("XTTS_URL", "http://127.0.0.1:8770").rstrip("/")
F5 = os.getenv("F5_URL", "http://127.0.0.1:8772").rstrip("/")
LAB = os.getenv("VOICE_LAB_URL", "http://127.0.0.1:8771").rstrip("/")

# The ceilings the note names. They are not settings here - they are what the
# adapters DO, and the probe below measures them rather than trusting them.
XTTS_SERVER_TRUNCATES_AT = 1000     # reachy-gateway/voice_clone_server.py
STATION_VOICE_MAX_CHARS = int(os.getenv("VOICE_MAX_CHARS", "800"))
F5_SPLITS_NEAR = 280                # app.py:12454


# --- audio ----------------------------------------------------------------

def wav_meta(raw: bytes) -> tuple[int, int, int]:
    with wave.open(io.BytesIO(raw), "rb") as w:
        return w.getnframes(), w.getframerate(), w.getnchannels()


def wav_seconds(raw: bytes) -> float:
    frames, rate, _ = wav_meta(raw)
    return frames / float(rate or 1)


def wav_slice(raw: bytes, start_sample: int, end_sample: int) -> bytes:
    """Cut by SAMPLE, in stdlib. The whole point of the manifest is integer
    sample positions; converting to seconds and back here would throw away
    the exactness this is supposed to be measuring."""
    with wave.open(io.BytesIO(raw), "rb") as w:
        params = w.getparams()
        w.setpos(max(0, min(start_sample, params.nframes)))
        want = max(0, min(end_sample, params.nframes) - start_sample)
        pcm = w.readframes(want)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(pcm)
    return out.getvalue()


def wav_join(parts: list[bytes]) -> bytes:
    """Butt-join, no gap and no processing - this is a measurement artifact,
    not an air mix. The station's own _call_concat_blocking applies chosen
    gaps and processing; adding any of that here would make the two roads'
    audio durations incomparable, which is the number being measured."""
    out = io.BytesIO()
    writer: Any = None
    try:
        for raw in parts:
            with wave.open(io.BytesIO(raw), "rb") as w:
                if writer is None:
                    writer = wave.open(out, "wb")
                    writer.setnchannels(w.getnchannels())
                    writer.setsampwidth(w.getsampwidth())
                    writer.setframerate(w.getframerate())
                writer.writeframes(w.readframes(w.getnframes()))
    finally:
        if writer is not None:
            writer.close()
    return out.getvalue()


# --- engines ---------------------------------------------------------------

class EngineError(RuntimeError):
    pass


def xtts_render(client: httpx.Client, text: str, ref_b64: str,
                speed: float = 1.0) -> tuple[bytes, float]:
    """One XTTS request. Failures come back as HTTP 200 with a JSON body, so
    the content-type is the truth and the status is not - the same trap the
    station's own adapter documents."""
    started = time.monotonic()
    got = client.post(f"{XTTS}/synthesize",
                      json={"text": text, "reference_audio": ref_b64,
                            "language": "en", "opts": {"speed": speed}},
                      timeout=900)
    elapsed = time.monotonic() - started
    if not got.headers.get("content-type", "").startswith("audio/"):
        try:
            detail = str((got.json() or {}).get("error") or got.json())[:200]
        except Exception:  # noqa: BLE001
            detail = got.text[:200]
        raise EngineError(f"XTTS refused: {detail}")
    return got.content, elapsed


def f5_render(client: httpx.Client, text: str, ref_b64: str
              ) -> tuple[bytes, float]:
    started = time.monotonic()
    got = client.post(f"{F5}/synthesize",
                      json={"text": text, "reference_audio": ref_b64,
                            "language": "en",
                            "opts": {"nfe_step": 16, "speed": 1.0}},
                      timeout=900)
    elapsed = time.monotonic() - started
    if not got.headers.get("content-type", "").startswith("audio/"):
        raise EngineError(f"F5 refused: {got.text[:200]}")
    return got.content, elapsed


def lab_align(client: httpx.Client, raw: bytes, script: list[dict[str, Any]],
              mode: str, actor: str = "") -> dict[str, Any]:
    got = client.post(f"{LAB}/align", timeout=1800, json={
        "audio": base64.b64encode(raw).decode(),
        "script": script, "mode": mode, "language": "en", "actor": actor})
    got.raise_for_status()
    return got.json()


def lab_verify(client: httpx.Client, reference: bytes, render: bytes,
               text: str) -> dict[str, Any]:
    got = client.post(f"{LAB}/verify", timeout=900, json={
        "reference": base64.b64encode(reference).decode(),
        "render": base64.b64encode(render).decode(), "text": text})
    got.raise_for_status()
    return got.json()


# --- material --------------------------------------------------------------

def load_rounds(limit: int, min_lines: int, max_lines: int,
                only: list[int] | None = None) -> list[dict[str, Any]]:
    """Complete conversations out of the station's own larder.

    A prepared entry's `takes` list is already the frozen ordered script: the
    exact text each chunk was rendered from, the voice assigned to it and its
    position in reading order. That is the "same scripts and cast" the note
    asks for - and using it means no line in this benchmark was written by
    the benchmark."""
    rows = json.loads((DATA / "larder.json").read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(rows):
        takes = entry.get("takes") or []
        if not entry.get("prepared") or not takes:
            continue
        if not min_lines <= len(takes) <= max_lines:
            continue
        if any(not (t.get("text") or "").strip() or not t.get("voice")
               for t in takes):
            continue
        ordered = sorted(takes, key=lambda t: int(t.get("i") or 0))
        out.append({
            "round": index,
            "kind": str(entry.get("prep_kind") or "banter"),
            "lines": [{
                "occurrence_id": f"r{index}-{int(t['i']):03d}",
                "ordinal": int(t["i"]),
                "speaker": str(t.get("who") or ""),
                "voice": str(t["voice"]),
                "text": str(t["text"]),
                "segmented_seconds": float(t.get("seconds") or 0.0),
            } for t in ordered],
        })
    if only:
        wanted = list(only)
        picked = [r for r in out if r["round"] in wanted]
        picked.sort(key=lambda r: wanted.index(r["round"]))
        return picked
    # Smallest first: a bounded benchmark on a live station should spend its
    # GPU on breadth of shape, not on the single longest round in the store.
    out.sort(key=lambda r: sum(len(line["text"]) for line in r["lines"]))
    return out[:limit]


def reference_b64(voice: str, for_f5: bool = False) -> str:
    folder = DATA / "voices" / voice
    path = folder / ("reference_f5.wav" if for_f5 else "reference.wav")
    if not path.is_file():
        path = folder / "reference.wav"
    return base64.b64encode(path.read_bytes()).decode()


# --- the two roads ---------------------------------------------------------

def run_segmented(client: httpx.Client, lines: list[dict[str, Any]],
                  ref_b64: str) -> dict[str, Any]:
    """Today's road: one engine request per frozen chunk."""
    clips: list[bytes] = []
    seconds: list[float] = []
    retries = 0
    started = time.monotonic()
    for line in lines:
        for attempt in range(3):
            try:
                raw, _ = xtts_render(client, line["text"], ref_b64)
                clips.append(raw)
                seconds.append(wav_seconds(raw))
                break
            except Exception as exc:  # noqa: BLE001
                retries += 1
                if attempt == 2:
                    return {"ok": False, "why": str(exc)[:200],
                            "retries": retries}
                time.sleep(2)
    wall = time.monotonic() - started
    return {"ok": True, "wall_s": round(wall, 2), "requests": len(lines),
            "retries": retries, "audio_s": round(sum(seconds), 2),
            "per_line_s": [round(s, 3) for s in seconds],
            "clips": clips, "master": wav_join(clips)}


def run_continuous(client: httpx.Client, lines: list[dict[str, Any]],
                   ref_b64: str) -> dict[str, Any]:
    """The operator's road: the whole part in one request."""
    text = " ".join(line["text"].strip() for line in lines)
    retries = 0
    for attempt in range(3):
        try:
            raw, wall = xtts_render(client, text, ref_b64)
            break
        except Exception as exc:  # noqa: BLE001
            retries += 1
            if attempt == 2:
                return {"ok": False, "why": str(exc)[:200], "retries": retries,
                        "chars": len(text)}
            time.sleep(2)
    return {"ok": True, "wall_s": round(wall, 2), "requests": 1,
            "retries": retries, "audio_s": round(wav_seconds(raw), 2),
            "chars": len(text), "master": raw, "text": text}


def score_alignment(client: httpx.Client, master: bytes,
                    lines: list[dict[str, Any]], reference: bytes,
                    mode: str, per_cut_verify: bool) -> dict[str, Any]:
    script = [{"occurrence_id": line["occurrence_id"],
               "ordinal": line["ordinal"], "speaker": line["speaker"],
               "text": line["text"]} for line in lines]
    answer = lab_align(client, master, script, mode)
    alignment = answer.get("alignment") or {}
    out: dict[str, Any] = {
        "verdict": answer.get("verdict"),
        "words": answer.get("word_count"),
        "matcher": (answer.get("matcher") or {}).get("sha1"),
        "stats": alignment.get("stats") or {},
        "refusals": [
            {"code": r["code"], "occurrence_id": r.get("occurrence_id"),
             "says": r.get("says")} for r in (alignment.get("refusals") or [])],
        "cuts": len(alignment.get("cuts") or []),
    }
    cuts = alignment.get("cuts") or []
    if not cuts:
        return out
    wanted = {line["occurrence_id"]: line for line in lines}
    errors: list[float] = []
    cers: list[float] = []
    for cut in cuts:
        line = wanted.get(cut["occurrence_id"])
        if not line:
            continue
        # The comparison is against THIS run's segmented render of the same
        # line, not the stored seconds from whenever the larder was filled -
        # same engine, same reference, same hour, so the only difference left
        # is the one being measured.
        reference_seconds = float(line.get("reference_seconds")
                                  or line.get("segmented_seconds") or 0.0)
        if reference_seconds > 0:
            errors.append(abs(float(cut["seconds"]) - reference_seconds))
        if per_cut_verify:
            strip = wav_slice(master, cut["start_sample"], cut["end_sample"])
            try:
                scored = lab_verify(client, reference, strip, line["text"])
                cers.append(float(scored.get("cer") or 0.0))
            except Exception:  # noqa: BLE001
                pass
    out["cut_seconds_total"] = round(sum(c["seconds"] for c in cuts), 2)
    if errors:
        out["boundary_error_s_mean"] = round(statistics.fmean(errors), 3)
        out["boundary_error_s_max"] = round(max(errors), 3)
    if cers:
        out["cut_cer_mean"] = round(statistics.fmean(cers), 4)
        out["cut_cer_max"] = round(max(cers), 4)
        out["cut_cer_over_015"] = sum(1 for c in cers if c > 0.15)
    out["boundary_methods"] = sorted({c["boundary_method"] for c in cuts})
    return out


# --- the adapter ceilings --------------------------------------------------

def probe_ceilings(client: httpx.Client, voice: str, lines: list[dict[str, Any]]
                   ) -> dict[str, Any]:
    """Is a single continuous take even reachable through these adapters?

    The note states the ceilings; this measures them, because a truncation
    that returns HTTP 200 and clean audio is invisible from the outside. The
    method: build one text well past the XTTS server's 1000-character
    truncation, render it, and ask whisper what came back. If the read-back
    covers only the head of the text, the "continuous take" lost the rest
    silently - which is exactly the failure that must never be described as a
    continuous performance."""
    ref = reference_b64(voice)
    text = " ".join(line["text"].strip() for line in lines)
    out: dict[str, Any] = {"voice": voice, "asked_chars": len(text)}
    if len(text) < XTTS_SERVER_TRUNCATES_AT + 200:
        out["why"] = ("not enough material in this round to cross the "
                      f"{XTTS_SERVER_TRUNCATES_AT}-character ceiling")
        return out
    head = text[:XTTS_SERVER_TRUNCATES_AT]
    try:
        raw, wall = xtts_render(client, text, ref)
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:200]
        return out
    out.update(returned_s=round(wav_seconds(raw), 2), wall_s=round(wall, 2))
    answer = client.post(f"{LAB}/align", timeout=1800, json={
        "audio": base64.b64encode(raw).decode(), "language": "en"}).json()
    heard = normalize_tokens(" ".join(w["w"] for w in answer.get("words") or []))
    whole = normalize_tokens(text)
    inside = normalize_tokens(head)
    out.update(
        heard_words=len(heard),
        script_words=len(whole),
        head_words=len(inside),
        # If what came back matches the first 1000 characters and stops, the
        # server truncated. Coverage of the WHOLE text is the number that
        # tells the operator what they actually have.
        coverage_whole=round(_coverage(whole, heard), 4),
        coverage_head=round(_coverage(inside, heard), 4),
    )
    out["truncated"] = bool(out["coverage_head"] - out["coverage_whole"] > 0.15)
    return out


def _coverage(script: list[str], heard: list[str]) -> float:
    if not script:
        return 0.0
    policy = AlignmentPolicy()
    lines = [ScriptLine("probe", 0, "", " ".join(script))]
    words = from_whisper_words(
        [{"w": token, "t0": index * 0.3, "t1": index * 0.3 + 0.25}
         for index, token in enumerate(heard)])
    result = align_script(lines, words, 24000, max(1, len(heard) * 7200),
                          MODE_CONTINUOUS, policy)
    return float((result.stats or {}).get("global_coverage") or 0.0)


# --- the run ---------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--min-lines", type=int, default=4)
    ap.add_argument("--max-lines", type=int, default=13)
    ap.add_argument("--out", default=str(DATA / "bench" / "take_bench"))
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--no-cut-verify", action="store_true",
                    help="skip the per-cut read-back (it is the slow half)")
    ap.add_argument("--keep-audio", action="store_true")
    ap.add_argument("--realign", default="",
                    help="re-score the alignment from masters kept by an "
                         "earlier --keep-audio run, without paying the engine "
                         "again. The only honest way to change the matcher "
                         "and compare: same audio, same recogniser.")
    ap.add_argument("--round-ids", default="",
                    help="comma-separated larder indices, instead of the "
                         "smallest-first pick")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    only = [int(x) for x in args.round_ids.split(",") if x.strip()]
    rounds = load_rounds(args.rounds, args.min_lines, args.max_lines, only)
    if not rounds:
        print("no prepared rounds matched", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "at": time.time(),
        "engine": "xtts",
        "ceilings": {
            "xtts_server_truncates_at": XTTS_SERVER_TRUNCATES_AT,
            "station_voice_max_chars": STATION_VOICE_MAX_CHARS,
            "f5_splits_near": F5_SPLITS_NEAR,
        },
        "rounds": [], "probes": [],
    }
    with httpx.Client() as client:
        if args.realign:
            return _realign(client, Path(args.realign), out_dir,
                            not args.no_cut_verify)
        if args.probe_only:
            source = load_rounds(30, 1, 200)
            for entry in source:
                by_voice: dict[str, list[dict[str, Any]]] = {}
                for line in entry["lines"]:
                    by_voice.setdefault(line["voice"], []).append(line)
                for voice, lines in by_voice.items():
                    chars = sum(len(line["text"]) for line in lines)
                    if chars < XTTS_SERVER_TRUNCATES_AT + 200:
                        continue
                    print(f"probe round {entry['round']} {voice} {chars}c",
                          file=sys.stderr)
                    probe = probe_ceilings(client, voice, lines)
                    probe["round"] = entry["round"]
                    report["probes"].append(probe)
                    break
                if len(report["probes"]) >= 3:
                    break
            _write(out_dir, report)
            return 0

        for entry in rounds:
            by_voice: dict[str, list[dict[str, Any]]] = {}
            for line in entry["lines"]:
                by_voice.setdefault(line["voice"], []).append(line)
            row: dict[str, Any] = {"round": entry["round"],
                                   "kind": entry["kind"],
                                   "lines": len(entry["lines"]),
                                   "performers": []}
            for voice, lines in by_voice.items():
                chars = sum(len(line["text"]) for line in lines)
                print(f"round {entry['round']} / {voice}: {len(lines)} lines, "
                      f"{chars} chars", file=sys.stderr)
                ref_b64 = reference_b64(voice)
                reference = base64.b64decode(ref_b64)
                seg = run_segmented(client, lines, ref_b64)
                con = run_continuous(client, lines, ref_b64)
                part: dict[str, Any] = {
                    "voice": voice, "lines": len(lines), "chars": chars,
                    "segmented": {k: v for k, v in seg.items()
                                  if k not in ("clips", "master")},
                    "continuous": {k: v for k, v in con.items()
                                   if k not in ("master", "text")},
                }
                if seg.get("ok"):
                    # The segmented road's boundaries are free - each request
                    # IS a line - so it gets the same alignment treatment only
                    # to score its LISTENING quality, never its cuts.
                    try:
                        part["segmented"]["quality"] = _quality(
                            client, reference, seg["master"],
                            " ".join(line["text"] for line in lines))
                    except Exception as exc:  # noqa: BLE001
                        part["segmented"]["quality_error"] = str(exc)[:160]
                if con.get("ok"):
                    for line, seconds in zip(lines, seg.get("per_line_s") or []):
                        line["reference_seconds"] = seconds
                    try:
                        part["continuous"]["alignment"] = score_alignment(
                            client, con["master"], lines, reference,
                            MODE_CONTINUOUS, not args.no_cut_verify)
                    except Exception as exc:  # noqa: BLE001
                        part["continuous"]["alignment_error"] = str(exc)[:200]
                    try:
                        part["continuous"]["quality"] = _quality(
                            client, reference, con["master"], con["text"])
                    except Exception as exc:  # noqa: BLE001
                        part["continuous"]["quality_error"] = str(exc)[:160]
                    if args.keep_audio:
                        stem = f"r{entry['round']}_{voice}"
                        (out_dir / f"{stem}_continuous.wav").write_bytes(
                            con["master"])
                        (out_dir / f"{stem}_segmented.wav").write_bytes(
                            seg["master"])
                row["performers"].append(part)
                # Written after every PERFORMER, not every round: a bench on a
                # live station shares its GPU and can be cut short, and a
                # partial measurement that survives is worth more than a
                # complete one that only exists in a dead process.
                if row not in report["rounds"]:
                    report["rounds"].append(row)
                _write(out_dir, report)
            if row not in report["rounds"]:
                report["rounds"].append(row)
            _write(out_dir, report)
    _write(out_dir, report)
    print(f"wrote {out_dir / 'take_bench.json'}", file=sys.stderr)
    return 0


def _realign(client: httpx.Client, source: Path, out_dir: Path,
             per_cut_verify: bool) -> int:
    """Re-run only the matching, over masters an earlier run kept on disk.

    Engine time is the expensive half and it is already spent; the matcher is
    the half that changes. Re-recording to re-score would also change the
    audio, which would make the two matchers incomparable - the point of
    keeping the wavs."""
    previous = json.loads((source / "take_bench.json").read_text("utf-8"))
    rounds = {int(entry["round"]): entry
              for entry in load_rounds(200, 1, 500)}
    report: dict[str, Any] = {"at": time.time(), "engine": "xtts",
                              "realigned_from": str(source), "rounds": []}
    for row in previous.get("rounds") or []:
        fresh = {"round": row["round"], "kind": row.get("kind"),
                 "lines": row.get("lines"), "performers": []}
        entry = rounds.get(int(row["round"]))
        if not entry:
            continue
        for part in row.get("performers") or []:
            voice = part["voice"]
            master_path = source / f"r{row['round']}_{voice}_continuous.wav"
            if not master_path.is_file():
                continue
            lines = [line for line in entry["lines"] if line["voice"] == voice]
            for line, seconds in zip(
                    lines, (part.get("segmented") or {}).get("per_line_s") or []):
                line["reference_seconds"] = seconds
            reference = base64.b64decode(reference_b64(voice))
            print(f"realign round {row['round']} {voice}", file=sys.stderr)
            scored = score_alignment(client, master_path.read_bytes(), lines,
                                     reference, MODE_CONTINUOUS,
                                     per_cut_verify)
            fresh["performers"].append({
                "voice": voice, "lines": len(lines),
                "chars": part.get("chars"),
                "segmented": part.get("segmented"),
                "continuous": {**{k: v for k, v in
                                  (part.get("continuous") or {}).items()
                                  if k != "alignment"},
                               "alignment": scored},
            })
            report["rounds"].append(fresh) if fresh not in report["rounds"]                 else None
            _write(out_dir, report)
    _write(out_dir, report)
    return 0


def _quality(client: httpx.Client, reference: bytes, render: bytes,
             text: str) -> dict[str, Any]:
    scored = lab_verify(client, reference, render, text)
    return {k: scored.get(k) for k in
            ("verdict", "cer", "identity", "seconds", "expected_seconds",
             "overrun", "speech", "faults")}


def _write(out_dir: Path, report: dict[str, Any]) -> None:
    (out_dir / "take_bench.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
