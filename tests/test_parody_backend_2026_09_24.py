"""Focused backend contracts with isolated media and no station runtime import."""
import ast
import asyncio
import errno
from functools import lru_cache
import os
from pathlib import Path
import subprocess
import time
import uuid
from types import SimpleNamespace

import pytest
import numpy as np

import comfy_workshop
import video_editor
from parody_stinger_queue import ParodyQueue
import sfx_glue
from video_editor import VideoEditor


ROOT = Path(__file__).resolve().parents[1]


def test_media_commit_falls_back_across_filesystems(tmp_path, monkeypatch):
    source = tmp_path / "work" / "splice.mp4"
    target = tmp_path / "ads" / "finished.mp4"
    source.parent.mkdir()
    target.parent.mkdir()
    source.write_bytes(b"rendered-media")
    real_replace = os.replace

    def replace(left, right):
        if Path(left) == source:
            raise OSError(errno.EXDEV, "different mounts")
        return real_replace(left, right)

    monkeypatch.setattr(video_editor.os, "replace", replace)
    video_editor._move_into_place(source, target)
    assert target.read_bytes() == b"rendered-media"
    assert not source.exists()
    assert not list(target.parent.glob("*.part"))


@lru_cache(maxsize=1)
def app_text():
    return (ROOT / "app.py").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def app_tree():
    return ast.parse(app_text())


def wait_for(editor, kind, identifier):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        row = editor.read(kind, identifier)
        if row["status"] in {"ready", "complete", "failed"}:
            return row
        time.sleep(.03)
    pytest.fail("media worker did not finish")


@pytest.fixture
def editor(tmp_path):
    instance = VideoEditor(tmp_path / "edits", tmp_path)
    yield instance
    instance.worker.shutdown(wait=True)


def make_video(editor, path, color, audio=False):
    command = [editor.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
               f"color=c={color}:s=160x96:r=12:d=2"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-map", "0:v", "-map", "1:a", "-c:a", "aac"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    editor.run(command)


def test_h3_duration_tracks_reference_or_requested_length():
    assert comfy_workshop.duration_frames() in {124, 169}
    assert comfy_workshop.duration_frames(reference_s=4.9,
                                          duration_mode="reference") == 124
    assert comfy_workshop.duration_frames(reference_s=4.9,
                                          duration_mode="double") == 241
    assert comfy_workshop.duration_frames(15) == 361
    with pytest.raises(ValueError):
        comfy_workshop.duration_frames(30)
    graph = comfy_workshop.build_workflow("extended", frames=361)
    assert graph["6"]["inputs"]["length"] == 361


def test_reference_window_limits_and_exact_trim():
    assert comfy_workshop.reference_window(25, trim_in_s=6.2,
                                           trim_out_s=11.4) == pytest.approx((6.2, 5.2))
    assert comfy_workshop.reference_window(30) == (0, 15)
    for start, end in [(3, 4), (0, 16), (-1, 3), (24, 28), (3, None),
                       (float("nan"), 6)]:
        with pytest.raises(ValueError):
            comfy_workshop.reference_window(25, trim_in_s=start,
                                            trim_out_s=end)


def test_h3_reference_extractor_uses_requested_in_out(tmp_path):
    node = next(node for node in app_tree().body if isinstance(node, ast.FunctionDef)
                and node.name == "workshop_reference_video")
    node = ast.FunctionDef(name=node.name, args=node.args, body=node.body,
                           decorator_list=[], returns=node.returns,
                           type_comment=None)
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"video" * 1024)
        return SimpleNamespace(returncode=0)

    namespace = {"Path": Path, "RADIO_CACHE": tmp_path,
                 "_media_duration_probe": lambda _path: 25.0,
                 "_real_subprocess_run": run,
                 "comfy_workshop": comfy_workshop, "uuid": uuid}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "app.py", "exec"), namespace)
    blob = namespace["workshop_reference_video"](tmp_path / "source.mp4",
                                                  trim_in_s=6.2, trim_out_s=11.4)
    assert blob.startswith(b"video")
    command = commands[0]
    assert command[command.index("-ss") + 1] == "6.200"
    assert command[command.index("-t") + 1] == "5.200"
    assert not Path(command[-1]).exists()


def test_parody_queue_persists_fifo_and_never_replays_uncertain_submit(tmp_path):
    path = tmp_path / "queue.sqlite3"
    queue = ParodyQueue(path)
    first = queue.add({"purpose": "parody_stinger", "prompt": "first", "frames": 73})
    second = queue.add({"purpose": "parody_stinger", "prompt": "second", "frames": 121})
    assert queue.list()[1]["position"] == 1
    assert queue.list()[0]["position"] == 2
    assert queue.next()["id"] == first["id"]
    assert queue.claim(first["id"])["prompt"] == "first"
    assert queue.claim(second["id"]) is None
    restarted = ParodyQueue(path)
    assert restarted.get(first["id"])["status"] == "paused"
    assert restarted.next()["id"] == second["id"]
    assert restarted.claim(second["id"])["prompt"] == "second"
    restarted.update(second["id"], "running", prompt_id="h3-ticket", model="MiniMax H3")
    assert restarted.active()["prompt_id"] == "h3-ticket"
    restarted.update(second["id"], "done")
    assert ParodyQueue(path).get(second["id"])["status"] == "done"


def test_parody_post_acknowledges_durable_queue_without_admission():
    node = next(node for node in app_tree().body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "comfy_workshop_render")
    node = ast.AsyncFunctionDef(name=node.name, args=node.args, body=node.body,
                                decorator_list=[], returns=node.returns,
                                type_comment=None)
    class Request:
        async def json(self):
            return {"purpose": "parody_stinger", "mode": "reference",
                    "source": "clip-1", "prompt": "Make it bright"}
    class Queue:
        def add(self, payload):
            assert payload["source"] == "clip-1"
            return {"id": "durable-1"}
    wake = SimpleNamespace(set=lambda: None)
    namespace = {"Request": Request, "Header": lambda default=None: default,
                 "Any": object, "require_auth": lambda *_: None,
                 "_parody_stinger_queue": lambda: Queue(),
                 "_parody_stinger_wake": wake}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "app.py", "exec"), namespace)
    got = asyncio.run(namespace["comfy_workshop_render"](Request()))
    assert got == {"queued": True, "queue_id": "durable-1", "status": "queued"}


def test_parody_worker_waits_busy_or_low_memory_then_runs_fifo(tmp_path):
    node = next(node for node in app_tree().body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_parody_stinger_step")
    node = ast.AsyncFunctionDef(name=node.name, args=node.args, body=node.body,
                                decorator_list=[], returns=node.returns,
                                type_comment=None)
    queue = ParodyQueue(tmp_path / "worker.sqlite3")
    first = queue.add({"prompt": "first"})
    second = queue.add({"prompt": "second"})
    state = {"busy": True, "free": 27.3, "unloads": 0, "sends": [], "lost": False}

    async def live():
        return {"up": True, "observed": True, "busy": state["busy"],
                "available_gb": state["free"], "idle_seconds": 10}

    async def unload(*_args):
        assert not state["busy"]
        state["unloads"] += 1

    async def submit(body):
        state["sends"].append(body["prompt"])
        return {"prompt_id": "ticket-" + body["prompt"], "model": "MiniMax H3"}

    namespace = {"ParodyQueue": ParodyQueue, "asyncio": asyncio, "time": time,
                 "comfy_idle_live": live, "comfy_unload": unload,
                 "VIDEO_RENDER_FLOOR_GB": 60,
                 "render_admission": lambda kind: (state["free"] >= 60,
                     f"the box has {state['free']:.1f} GB free and video needs 60 GB",
                     state["free"]),
                 "workshop_generation": lambda _pid: {"status": "lost"}
                     if state["lost"] else None,
                 "_comfy_workshop_render_payload": submit,
                 "HTTPException": type("HTTPException", (Exception,), {})}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "app.py", "exec"), namespace)
    step = namespace["_parody_stinger_step"]
    delay, freed = asyncio.run(step(queue, ""))
    assert delay == 10 and freed == "" and state["unloads"] == 0
    assert "busy" in queue.get(first["id"])["reason"]
    state["busy"] = False
    delay, freed = asyncio.run(step(queue, freed))
    assert delay == 10 and freed == first["id"] and state["unloads"] == 1
    assert "27.3 GB" in queue.get(first["id"])["reason"]
    asyncio.run(step(queue, freed))
    assert state["unloads"] == 1 and state["sends"] == []
    state["free"] = 70
    asyncio.run(step(queue, freed))
    assert state["sends"] == ["first"]
    assert queue.get(first["id"])["status"] == "running"
    asyncio.run(step(queue, freed))
    assert state["sends"] == ["first"]
    state["lost"] = True
    asyncio.run(step(queue, freed))
    assert queue.get(first["id"])["status"] == "failed"
    assert "review" in queue.get(first["id"])["reason"]
    asyncio.run(step(queue, freed))
    assert state["sends"] == ["first", "second"]
    assert queue.get(second["id"])["status"] == "running"


def test_parody_import_and_splice_leave_sources_intact(editor, tmp_path):
    original = tmp_path / "original.mp4"
    generated = tmp_path / "generated.mp4"
    make_video(editor, original, "red", audio=True)
    make_video(editor, generated, "blue")
    before = (original.read_bytes(), generated.read_bytes())
    first = editor.import_source(original, "Original")
    second = editor.import_source(generated, "Generated")
    for identifier in (first, second):
        record = wait_for(editor, "sources", identifier)
        assert record["status"] == "ready"
        assert record["poster_url"].endswith(f"/{identifier}/poster.jpg")
        assert (editor.folder("sources", identifier) / "poster.jpg").stat().st_size > 100
    ads = tmp_path / "ads"
    published = []
    job = editor.start_splice_export({
        "source_ids": [first, second], "name": "Parody: cut",
        "clips": [{"source_id": first, "in_s": .2, "out_s": .8},
                  {"source_id": second, "in_s": .1, "out_s": .7}]},
        ads, lambda path, seconds: published.append((path, seconds)) or True)
    done = wait_for(editor, "exports", job["id"])
    assert done["status"] == "complete", done
    assert done["duration"] == pytest.approx(1.2, abs=.3)
    assert published and published[0][0].parent == ads
    assert (original.read_bytes(), generated.read_bytes()) == before
    with pytest.raises(ValueError):
        editor.start_splice_export({"source_ids": [first, second],
            "clips": [{"source_id": first, "in_s": 0, "out_s": 90}]}, ads,
            lambda *_: True)


def test_splice_accepts_more_than_two_distinct_sources(editor, tmp_path):
    source_ids = []
    for index, colour in enumerate(("red", "blue", "green")):
        path = tmp_path / f"source-{index}.mp4"
        make_video(editor, path, colour)
        source_id = editor.import_source(path, f"Source {index}")
        assert wait_for(editor, "sources", source_id)["status"] == "ready"
        source_ids.append(source_id)
    job = editor.start_splice_export({
        "source_ids": source_ids, "name": "Three source cut",
        "clips": [{"source_id": source_id, "in_s": 0, "out_s": .3}
                  for source_id in source_ids]}, tmp_path / "ads", lambda *_: True)
    assert wait_for(editor, "exports", job["id"])["status"] == "complete"


def mask_box(left, right):
    return [{"x": left, "y": .15, "in": [left, .15], "out": [left, .15]},
            {"x": right, "y": .15, "in": [right, .15], "out": [right, .15]},
            {"x": right, "y": .85, "in": [right, .85], "out": [right, .85]},
            {"x": left, "y": .85, "in": [left, .85], "out": [left, .85]}]


def test_nle_filter_contract_covers_order_transitions_audio_and_mask(editor, tmp_path):
    source_ids = ["1" * 32, "2" * 32, "3" * 32]
    for source_id in source_ids:
        folder = editor.folder("sources", source_id)
        folder.mkdir(parents=True)
        (folder / "original.mp4").write_bytes(b"retained source")
        editor.write("sources", source_id, {"id": source_id, "status": "ready",
                     "duration": 4.0, "has_audio": True})
    body = {
        "source_ids": source_ids,
        "clips": [
            {"source_id": source_ids[1], "in_s": .2, "out_s": 1.4,
             "volume": .7, "audio_fade_in_s": .1},
            {"source_id": source_ids[0], "in_s": .1, "out_s": 1.1,
             "volume": .4, "audio_fade_out_s": .2},
        ],
        "transitions": [{"type": "crossfade", "duration_s": .25}],
        "overlay_tracks": [{"clips": [{
            "source_id": source_ids[2], "in_s": 0, "out_s": .8,
            "start_s": .3, "opacity": .65, "volume": .2,
            "audio_fade_in_s": .1, "audio_fade_out_s": .1,
            "mask": {"type": "rotobezier", "anchors": mask_box(.1, .6)},
        }]}],
    }
    sources, plan = editor._normalize_splice(body)
    assert [clip["source_id"] for clip in plan["clips"]] == source_ids[1::-1]
    assert plan["duration_s"] == pytest.approx(1.95)
    assert plan["transitions"] == [{"type": "dissolve", "duration_s": .25}]
    command = editor._splice_command(
        plan, sources, tmp_path / "out.mp4", {0: tmp_path / "mask.mkv"})
    graph = command[command.index("-filter_complex") + 1]
    assert "xfade=transition=dissolve:duration=0.250000" in graph
    assert "acrossfade=d=0.250000" in graph
    assert "volume=0.700000" in graph and "afade=t=in" in graph
    assert "volume=0.400000" in graph and "afade=t=out" in graph
    assert "alphamerge" in graph and "overlay=0:0" in graph
    assert "adelay=300:all=1" in graph and "amix=inputs=2" in graph


def test_shared_editor_payload_maps_inline_overlay_transition_and_mask(editor):
    source_ids = ["6" * 32, "7" * 32, "8" * 32]
    for source_id in source_ids:
        folder = editor.folder("sources", source_id)
        folder.mkdir(parents=True)
        (folder / "original.mp4").write_bytes(b"retained source")
        editor.write("sources", source_id, {"id": source_id, "status": "ready",
                     "duration": 4.0, "has_audio": True})

    points = [
        {"x": .1, "y": .1, "in_x": .1, "in_y": .1,
         "out_x": .1, "out_y": .1},
        {"x": .7, "y": .1, "in_x": .7, "in_y": .1,
         "out_x": .7, "out_y": .1},
        {"x": .7, "y": .8, "in_x": .7, "in_y": .8,
         "out_x": .7, "out_y": .8},
        {"x": .1, "y": .8, "in_x": .1, "in_y": .8,
         "out_x": .1, "out_y": .8},
    ]
    body = {
        "source_ids": source_ids,
        "clips": [
            {"source_id": source_ids[0], "in_s": 0, "out_s": 1,
             "track": "base", "transition": "cut", "transition_s": 0},
            {"source_id": source_ids[1], "in_s": 0, "out_s": 1,
             "track": "base", "transition": "dissolve", "transition_s": .2,
             "volume": .6, "audio_fade_in_s": .1},
            {"source_id": source_ids[2], "in_s": 0, "out_s": .6,
             "track": "overlay", "start_s": .25, "opacity": .7,
             "mask": {"closed": True, "feather": 2, "invert": False,
                      "keyframes": [{"at": 0, "points": points},
                                    {"at": .6, "points": points}]}}
        ],
    }

    _, plan = editor._normalize_splice(body)
    assert [clip["source_id"] for clip in plan["clips"]] == source_ids[:2]
    assert plan["transitions"] == [{"type": "dissolve", "duration_s": .2}]
    assert len(plan["overlays"]) == 1
    assert plan["overlays"][0]["source_id"] == source_ids[2]
    assert plan["overlays"][0]["opacity"] == .7
    assert plan["overlays"][0]["mask"]["keyframes"][1]["time_s"] == .6
    assert plan["overlays"][0]["mask"]["keyframes"][0]["anchors"][0]["in"] == {
        "x": .1, "y": .1}


@pytest.mark.parametrize("given, expected", [
    ("cut", "cut"), ("dissolve", "dissolve"), ("crossfade", "dissolve"),
    ("fade", "fade"), ("wipe", "wipeleft"), ("wipe-right", "wiperight"),
])
def test_nle_transition_names(given, expected):
    transition = VideoEditor._normalize_transition(
        {"type": given, "duration_s": .2}, 1, 1)
    assert transition["type"] == expected
    assert transition["duration_s"] == (0 if expected == "cut" else .2)


def test_nle_transition_overlay_and_animated_rotobezier_render(editor, tmp_path):
    paths = []
    source_ids = []
    for index, colour in enumerate(("red", "blue", "green")):
        path = tmp_path / f"nle-{colour}.mp4"
        make_video(editor, path, colour, audio=True)
        paths.append(path)
        source_id = editor.import_source(path, colour)
        assert wait_for(editor, "sources", source_id)["status"] == "ready"
        source_ids.append(source_id)
    before = [path.read_bytes() for path in paths]
    published = []
    job = editor.start_splice_export({
        "source_ids": source_ids,
        "name": "Layered transition",
        "clips": [
            {"source_id": source_ids[0], "in_s": 0, "out_s": 1,
             "volume": .7, "audio_fade_out_s": .1},
            {"source_id": source_ids[1], "in_s": 0, "out_s": 1,
             "volume": .5, "audio_fade_in_s": .1,
             "transition": {"type": "dissolve", "duration_s": .2}},
        ],
        "overlay_tracks": [{"clips": [{
            "source_id": source_ids[2], "in_s": 0, "out_s": .8,
            "start_s": .25, "opacity": 1, "volume": .15,
            "audio_fade_in_s": .1, "audio_fade_out_s": .1,
            "mask": {"type": "rotobezier", "feather_px": 1,
                     "keyframes": [
                         {"time_s": 0, "anchors": mask_box(.05, .4)},
                         {"time_s": .8, "anchors": mask_box(.6, .95)},
                     ]},
        }]}],
    }, tmp_path / "ads", lambda path, seconds: published.append(path) or True)
    done = wait_for(editor, "exports", job["id"])
    assert done["status"] == "complete", done
    assert done["duration"] == pytest.approx(1.8, abs=.15)
    assert done["has_audio"]
    assert published and published[0].is_file()
    assert [path.read_bytes() for path in paths] == before
    assert not list(editor.folder("exports", job["id"]).glob("mask-*.mkv"))

    def frame(at):
        raw = editor.run([editor.ffmpeg, "-v", "error", "-ss", str(at),
                          "-i", str(published[0]), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
        return np.frombuffer(raw, dtype="uint8").reshape(384, 640, 3)

    early = frame(.35)
    late = frame(.95)
    assert int(early[192, 160, 1]) > int(early[192, 480, 1]) + 60
    assert int(late[192, 480, 1]) > int(late[192, 160, 1]) + 60


@pytest.mark.parametrize("mutate, message", [
    (lambda body, ids: body.update(transitions=[{"type": "spin", "duration_s": .2}]),
     "Transition"),
    (lambda body, ids: body.update(overlays=[{"source_id": ids[0], "in_s": 0,
                                               "out_s": 1, "start_s": 1.5}]),
     "inside"),
    (lambda body, ids: body.update(overlays=[{"source_id": ids[0], "in_s": 0,
                                               "out_s": 1, "mask": {
                                                   "anchors": mask_box(0, .5) * 13}}]),
     "48 anchors"),
])
def test_nle_rejects_pathological_payloads(editor, mutate, message):
    source_ids = ["4" * 32, "5" * 32]
    for source_id in source_ids:
        folder = editor.folder("sources", source_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "original.mp4").write_bytes(b"retained source")
        editor.write("sources", source_id, {"id": source_id, "status": "ready",
                     "duration": 2.0, "has_audio": False})
    body = {"source_ids": source_ids,
            "clips": [{"source_id": source_ids[0], "in_s": 0, "out_s": 1},
                      {"source_id": source_ids[1], "in_s": 0, "out_s": 1}]}
    mutate(body, source_ids)
    with pytest.raises(ValueError, match=message):
        editor._normalize_splice(body)


def test_audio_split_stages_then_retires_only_after_publication(editor, tmp_path):
    original = tmp_path / "long.wav"
    editor.run([editor.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=2", str(original)])
    before = original.read_bytes()
    source_id = "a" * 32
    editor.write("sources", source_id,
                 {"id": source_id, "status": "ready", "duration": 2.0,
                  "has_audio": True})
    published, retired, audits = [], [], []
    body = {"source_id": source_id, "keep_original": False,
            "clips": [{"in_s": 0, "out_s": .7, "name": "first"},
                      {"in_s": .7, "out_s": 1.5, "name": "second"}]}
    job = editor.start_split_export(
        body, original, original.parent,
        lambda path, seconds: published.append(path) or True,
        lambda path: retired.append(path),
        lambda *args: audits.append(args), sfx_glue.probe)
    done = wait_for(editor, "exports", job["id"])
    assert done["status"] == "complete", done
    assert len(published) == 2 and all(path.parent == original.parent for path in published)
    assert all(path.suffix == ".wav" for path in published)
    assert retired == [original] and audits
    assert original.read_bytes() == before


def test_audio_split_failure_preserves_original(editor, tmp_path):
    original = tmp_path / "long.wav"
    original.write_bytes(b"original audio")
    source_id = "b" * 32
    editor.write("sources", source_id,
                 {"id": source_id, "status": "ready", "duration": 2.0,
                  "has_audio": True})
    retired = []
    job = editor.start_split_export(
        {"source_id": source_id, "keep_original": False,
         "clips": [{"in_s": 0, "out_s": .5}, {"in_s": .5, "out_s": 1}]},
        original, original.parent, lambda *_: True,
        lambda path: retired.append(path),
        lambda *_: None, sfx_glue.probe)
    assert wait_for(editor, "exports", job["id"])["status"] == "failed"
    assert original.read_bytes() == b"original audio" and retired == []


def test_audio_split_fallback_reports_destination_and_keeps_source(editor, tmp_path):
    original_dir = tmp_path / "read-only-share"
    original_dir.mkdir()
    original = original_dir / "long.wav"
    fallback = tmp_path / "edited"
    editor.run([editor.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                "sine=frequency=550:duration=2", str(original)])
    before = original.read_bytes()
    source_id = "c" * 32
    editor.write("sources", source_id,
                 {"id": source_id, "status": "ready", "duration": 2.0,
                  "has_audio": True})
    published, retired = [], []
    job = editor.start_split_export(
        {"source_id": source_id, "keep_original": False,
         "clips": [{"in_s": 0, "out_s": .6}, {"in_s": .6, "out_s": 1.3}]},
        original, fallback, lambda path, seconds: published.append(path) or True,
        lambda path: retired.append(path), lambda *_: None, sfx_glue.probe)
    done = wait_for(editor, "exports", job["id"])
    assert done["status"] == "complete", done
    assert done["destination"] == str(fallback)
    assert done["same_directory"] is False
    assert done["original_kept_on_disk"] is True
    assert all(path.parent == fallback for path in published)
    assert retired == [original] and original.read_bytes() == before


def test_read_only_share_plan_uses_edited_shelf(tmp_path):
    share = tmp_path / "samples" / "read-only"
    share.mkdir(parents=True)
    source = share / "long.wav"
    source.write_bytes(b"original")
    edited = tmp_path / "data" / "sfx" / "edited"
    plan = sfx_glue.edit_plan(source, tmp_path / "data", edited, audio_only=True)
    assert plan["in_place"] is False
    assert Path(plan["target"]).parent == edited
    assert source.read_bytes() == b"original"


def test_core_recovery_only_restarts_unhealthy_named_services():
    tree = app_tree()
    selected = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name in {"core_service_healthy", "core_services_recovery_once"}]
    namespace = {"Any": object}
    calls = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url):
            calls.append(("get", url))
            if "searx" in url:
                raise OSError("down")
            return SimpleNamespace(status_code=200)

        async def post(self, url, **_kwargs):
            calls.append(("post", url))
            return SimpleNamespace(status_code=204)

    async def no_sleep(_seconds):
        return None

    namespace.update(httpx=SimpleNamespace(AsyncClient=Client, HTTPError=OSError),
                     asyncio=SimpleNamespace(sleep=no_sleep),
                     time=SimpleNamespace(monotonic=lambda: 1000.0),
                     CORE_SERVICE_RECOVERY={"searxng": ("http://searx/config", "searxng"),
                                            "open-webui": ("http://webui/health", "open-webui")},
                     _CORE_SERVICE_FAILURES={"searxng": 0, "open-webui": 0},
                     _CORE_SERVICE_RETRY_AT={"searxng": 0, "open-webui": 0})
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), namespace)
    report = asyncio.run(namespace["core_services_recovery_once"]())
    posts = [url for method, url in calls if method == "post"]
    assert posts == ["http://127.0.0.1:2375/containers/searxng/restart?t=10"]
    assert report["open-webui"] == "healthy"
    assert report["searxng"] == "restart requested"
    assert namespace["_CORE_SERVICE_RETRY_AT"]["searxng"] > 1000


def test_lightbox_duck_counts_both_videos_without_touching_levels():
    app = app_text()
    source = app[app.index("const lightboxDuckPlaying = new Set();"):
                 app.index("function lightboxCoverDrop()")]
    script = r"""
const assert = require('node:assert/strict');
const calls = [];
global.window = {
  addEventListener: (_name, fn) => { global.pagehide = fn; },
  PineSfxTv: {level: n => calls.push(['video', n])}
};
global.djApplyGain = transient => calls.push(['gain', transient]);
global.pineMixerRead = () => ({video: 0.8});
global.pineWallLevel = n => calls.push(['wall', n]);
const controls = new Function(process.env.LIGHTBOX_DUCK_SOURCE
  + '\nreturn {change: lightboxDuckChange, reset: lightboxDuckReset};')();
const made = {id: 'lightboxVid', paused: false, ended: false};
const ref = {id: 'lightboxRefVid', paused: false, ended: false};
controls.change(made, true);
assert.deepEqual(calls.slice(-3).map(([kind, n]) =>
  [kind, typeof n === 'number' ? Number(n.toFixed(2)) : n]),
  [['gain', true], ['video', 0.08], ['wall', 0.08]]);
const afterOne = calls.length;
controls.change(ref, true);
assert.equal(calls.length, afterOne);
made.paused = true;
controls.change(made, false);
assert.equal(calls.length, afterOne);
ref.ended = true;
controls.change(ref, false);
assert.deepEqual(calls.slice(-3), [['gain', true], ['video', 0.8], ['wall', 0.8]]);
controls.change(made, true);
global.pagehide();
assert.deepEqual(calls.slice(-3), [['gain', true], ['video', 0.8], ['wall', 0.8]]);
"""
    import os
    result = subprocess.run(["node", "-e", script],
                            env={**os.environ, "LIGHTBOX_DUCK_SOURCE": source},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "lightboxDuckChange(vid, true)" in app
    assert "lightboxDuckChange(refVid, true)" in app
    assert "lightboxDuckReset();" in app[app.index("function closeLightbox(event)"):]


def test_ratio_joint_selector_uses_eligible_weighted_draw_once(tmp_path):
    import sfx_match
    tree = app_tree()
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "sfx_ratio_draw"]
    calls = []

    class Selector:
        def choose_ratio_pool(self, rows, ads, video, **kwargs):
            calls.append((list(rows), ads, video))
            return sfx_match.choose_ratio_pool(
                rows, ads, video, rng=SimpleNamespace(random=lambda: .5), **kwargs)

    ns = {"Path": Path, "_sfx_match": Selector(),
          "sfx_is_video": lambda path: Path(path).suffix == ".mp4"}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), ns)
    choose = ns["sfx_ratio_draw"]
    ads = tmp_path / "sfx_ads" / "ad.mp4"
    general_video = tmp_path / "sfx" / "clip.mp4"
    general_audio = tmp_path / "sfx" / "clip.wav"
    pool = [ads, general_video, general_audio]
    names = [str(ads), str(general_video), str(general_audio)]
    ns["SFX_ADS_DIR"] = ads.parent
    assert choose(pool, names, set(names), 100, 100)[1] == [str(ads)]
    assert choose(pool, names, set(names), 0, 100)[1] == [str(general_video)]
    assert choose(pool, names, set(names), 0, 0)[1] == [str(general_audio)]
    narrowed = choose([ads], [str(ads)], {str(ads)}, 0, 0)
    assert narrowed[1] == [str(ads)] and narrowed[3] is True
    assert len(calls) == 4


def test_ratio_api_persists_both_endpoints_and_rejects_bad_values():
    from copy import deepcopy
    from fastapi import HTTPException
    selected = [node for node in app_tree().body
                if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "sfx_ratios_post_api"]
    selected = [deepcopy(selected[0])]
    selected[0].decorator_list = []
    settings = {"dj": {"sfx_ads_share": 20, "sfx_video_share": 80}}

    def save(value):
        settings.clear()
        settings.update(value)

    ns = {"Any": object, "Header": lambda default=None: default,
          "HTTPException": HTTPException, "asyncio": asyncio,
          "require_auth": lambda _auth: None, "load_settings": lambda: settings,
          "save_settings": save, "note_action": lambda _note: None,
          "sfx_ratios_state": lambda: settings["dj"]}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), ns)
    result = asyncio.run(ns["sfx_ratios_post_api"](
        {"ads_share": 0, "video_share": 100}))
    assert result["ok"] is True
    assert settings["dj"]["sfx_ads_share"] == 0
    assert settings["dj"]["sfx_video_share"] == 100
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ns["sfx_ratios_post_api"]({"video_share": 101}))
    assert exc.value.status_code == 400


def test_spoken_ad_uses_existing_auto_air_shelf():
    app = app_text()
    tree = app_tree()
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "line_ad_schedule"]
    rows = []
    ns = {"Any": object,
          "shelf_put": lambda kind, row: rows.append({"kind": kind, **row}),
          "shelf_rows": lambda kind: rows if kind == "ad" else []}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), ns)
    ad = {"id": "made-1", "product": "Pine"}
    assert ns["line_ad_schedule"](ad, "Exact spoken line", "dry.mp3", "line-1", 4)
    assert rows[0]["produced"] == ad["id"]
    assert rows[0]["auto_air"] is True
    assert rows[0]["audio"] == "dry.mp3"
    assert "music" not in rows[0]
    assert '"bed": "", "music": False' in app
    assert "scheduled = await asyncio.to_thread(\n        line_ad_schedule" in app


def test_gen_ads_catalog_exposes_signed_poster(tmp_path):
    import re
    tree = app_tree()
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "gen_ads_catalog"]
    ad_dir = tmp_path / "sfx_ads"
    ad_dir.mkdir()
    video = ad_dir / "ad.mp4"
    video.write_bytes(b"video")
    sid = "a" * 16

    class Reader:
        def execute(self, _query):
            return SimpleNamespace(fetchall=lambda: [{"sid": sid, "path": str(video),
                "name": "Ad", "seconds": 5, "seen_at": 100}])

    ns = {"Path": Path, "re": re, "SFX_ADS_DIR": ad_dir,
          "Any": object,
          "sfx_db_reader": lambda: Reader(), "_read_all_generations": lambda: [],
          "sfx_history_rows": lambda: [], "gen_ad_sends": lambda: [],
          "sfx_plays": lambda: {}, "SFX_VIDEO_TYPES": {".mp4": "video/mp4"},
          "media_sign": lambda _sid: "signed"}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), ns)
    row = ns["gen_ads_catalog"]()[0]
    assert row["poster_url"] == f"/api/sfx/poster/{sid}?t=signed"
    assert row["url"] == f"/sfx/{sid}?t=signed"


def test_gen_ads_send_records_only_accepted_handoff(tmp_path):
    from copy import deepcopy
    import json
    import threading
    from fastapi import HTTPException
    selected = [node for node in app_tree().body
                if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "gen_ads_send"]
    selected = [deepcopy(selected[0])]
    selected[0].decorator_list = []
    notes = []
    output = {"ticket": ""}
    ledger = tmp_path / "sends.jsonl"
    ns = {"Any": object, "Header": lambda default=None: default,
          "HTTPException": HTTPException, "asyncio": asyncio, "time": time,
          "json": json, "_GEN_AD_SENDS_LOCK": threading.RLock(),
          "GEN_AD_SENDS_PATH": ledger, "require_auth": lambda _auth: None,
          "gen_ad_path": lambda _id: tmp_path / "ad.mp4",
          "media_sign": lambda _id: "signed",
          "admission_admit_line": lambda *_args, **_kwargs: "admitted",
          "admission_withdraw": lambda *_args: notes.append("withdrawn"),
          "page_feed_append": lambda _clip: output["ticket"],
          "_RADIO": {"voice_to": "off"}, "_STING_AT": [0.0],
          "_play_on_box": lambda *_args: False,
          "sfx_history_add": lambda *_args: notes.append("aired"),
          "sfx_note_play": lambda *_args: notes.append("counted")}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "app.py", "exec"), ns)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ns["gen_ads_send"]("a" * 16))
    assert exc.value.status_code == 503
    assert notes == ["withdrawn"] and not ledger.exists()
    output["ticket"] = "queued-1"
    result = asyncio.run(ns["gen_ads_send"]("a" * 16))
    assert result["sent"] is True and result["page_delivery"] == "queued-1"
    assert json.loads(ledger.read_text())["id"] == "a" * 16
    assert notes == ["withdrawn"]


def test_lightbox_posters_cover_android_native_placeholder():
    app = app_text()
    assert '"pinebox.png": "image/png"' in app
    assert '"assets" / "pinebox-256.png"' in app
    assert "lightboxPoster(refVid, ref.poster, current)" in app
    assert 'api("/api/generations/poster-url/"' in app
    assert "lightboxCoverReset(refVid);" in app
    assert "lightboxCoverReset(vid);" in app
    assert ".lb-video-cover.fallback img" in app
    source = (app[app.index("function lightboxCoverFor(video)"):
                  app.index("function lightboxMediaState(")]
              + app[app.index("function lightboxVideoReady("):
                    app.index("function lightboxRadialClip(")])
    script = r"""
const assert = require('node:assert/strict');
const icon = '/spark/asset/pinebox.png';
const covers = {};
for (const id of ['lbGeneratedCover', 'lbReferenceCover']) {
  const classes = new Set(['fallback']);
  covers[id] = {hidden: true, dataset: {}, image: {src: icon},
    classList: {add: n => classes.add(n), remove: n => classes.delete(n),
                contains: n => classes.has(n)},
    querySelector: () => covers[id].image};
}
global.document = {getElementById: id => covers[id]};
global.Image = class {set src(url) { this._src = url; this.onload(); }};
global.lightboxDuckChange = () => {};
const controls = new Function(process.env.LIGHTBOX_POSTER_SOURCE
  + '\nreturn {ready: lightboxVideoReady, poster: lightboxPoster};')();
for (const [videoId, coverId] of [['lightboxVid','lbGeneratedCover'],
                                  ['lightboxRefVid','lbReferenceCover']]) {
  let painted;
  const video = {id: videoId, style: {}, paused: true, readyState: 0,
    videoWidth: 0, currentTime: 0, removeAttribute: () => {},
    addEventListener: () => {}, removeEventListener: () => {},
    requestVideoFrameCallback: fn => { painted = fn; return 1; }};
  const cover = covers[coverId];
  controls.ready(video, {}, '', () => true, () => {}, () => {});
  assert.equal(cover.hidden, false);
  assert.equal(cover.image.src, icon);
  assert.equal(cover.classList.contains('fallback'), true);
  controls.poster(video, '/api/sfx/poster/abc?t=signed', () => true);
  assert.equal(video.poster, '/api/sfx/poster/abc?t=signed');
  assert.equal(cover.classList.contains('fallback'), false);
  video.readyState = 2; video.videoWidth = 640;
  video.onloadeddata();
  assert.equal(cover.hidden, false);
  video.paused = false; video.onplaying();
  assert.equal(cover.hidden, false);
  painted();
  assert.equal(cover.hidden, true);
}
"""
    import os
    result = subprocess.run(["node", "-e", script],
                            env={**os.environ, "LIGHTBOX_POSTER_SOURCE": source},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_gen_ads_launcher_loads_umd_and_passes_authenticated_request():
    import os
    app = app_text()
    assert '"desktop" / "renderer" / name' in app
    source = app[app.index("let genAdsView = null;"):
                 app.index("let system2View = null;")]
    assert 'import("/gen-ads/gen-ads.js' not in source
    script = r"""
const assert = require('node:assert/strict');
const calls = [];
global.window = {};
global.document = {
  getElementById: () => null,
  createElement: tag => ({tagName: tag}),
  head: {append: node => {
    if (node.tagName === 'script') {
      window.PineGenAds = {open: options => {
        calls.push(['open', options]);
        return {id: 'desk'};
      }};
      node.onload();
    }
  }}
};
global.api = (path, options) => { calls.push(['api', path, options]); return {}; };
global.setStatus = message => { throw new Error(message); };
const desk = new Function(process.env.GEN_ADS_LAUNCHER
  + '\nreturn {open: genAdsOpen};')();
desk.open().then(() => {
  assert.equal(calls[0][0], 'open');
  calls[0][1].request('/api/gen-ads', {});
  calls[0][1].request('/api/gen-ads/id/send', {method: 'POST', body: '{}'});
  assert.equal(calls[1][1], '/api/gen-ads');
  assert.equal(calls[2][2].method, 'POST');
  calls[0][1].onClose();
});
"""
    result = subprocess.run(["node", "-e", script],
                            env={**os.environ, "GEN_ADS_LAUNCHER": source},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_gallery_tiles_use_posters_without_loading_video_blobs():
    app = app_text()
    image_loader = app[app.index("async function fetchImageInto(img, filename) {"):
                       app.index("function isVideoFile(f) {")]
    tile_factory = app[app.index("function mediaElement(filename) {"):
                       app.index("async function loadGallery() {")]
    assert '"/api/generations/poster-url/"' in image_loader
    assert "img.tagName === \"IMG\"" in image_loader
    assert "await imageURL(filename)" in image_loader
    assert 'document.createElement("img")' in tile_factory
    assert 'document.createElement("video")' not in tile_factory
