from pathlib import Path

import app


def test_slot_keeps_a_sanitized_operator_conversation_flow():
    slot = app._sched_slot({
        "id": "news-flow", "kind": "news", "minutes": 4,
        "flow_prompt": "Keep the hosts on the verified facts.",
        "flow": [
            {"id": "one", "type": "news_mention", "seconds": 75},
            {"id": "bad", "type": "made_up", "seconds": 99},
            {"id": "three", "type": "sfx", "seconds": 0},
        ],
    })

    assert slot["flow_prompt"] == "Keep the hosts on the verified facts."
    assert [node["type"] for node in slot["flow"]] == ["news_mention", "sfx"]
    assert slot["flow"][1]["seconds"] == 6.0


def test_orchestrator_suggestion_honors_a_segment_time_budget():
    got = app.schedule_flow_suggestion("news", 4, "News coverage")

    assert got["kind"] == "news"
    assert got["target_seconds"] == 240.0
    assert [node["type"] for node in got["nodes"]].count("sfx") >= 1
    assert sum(node["seconds"] for node in got["nodes"]) >= 220


def test_sfx_graph_beats_keep_a_selected_mp4_and_name_it_in_the_writer_clause(monkeypatch):
    """A visible graph SFX beat is a real planned library selection, not a placeholder."""
    monkeypatch.setattr(app, "sfx_video_share", lambda: 80)
    monkeypatch.setattr(app, "sfx_bans", lambda: set())
    monkeypatch.setattr(app, "sfx_weights", lambda: {})
    monkeypatch.setattr(
        app, "sfx_db_pick_short_video", lambda _cap: (Path("/clips/rimshot.mp4"), 4.5))
    monkeypatch.setattr(app, "sfx_db_pick_row", lambda _video: None)
    monkeypatch.setattr(app, "sfx_id", lambda _path: "a" * 16)

    nodes = app.schedule_flow_sfx_assign(
        [{"id": "sting", "type": "sfx", "seconds": 6}], "News coverage")

    assert nodes[0]["clip"] == {
        "id": "a" * 16, "name": "rimshot", "seconds": 4.5, "video": True}
    clause = app.schedule_flow_clause({"flow": nodes})
    assert "Scheduled clip: rimshot (MP4, 4.5s)" in clause
    assert "rather than describing a clip" in clause


def test_flow_clause_names_each_operator_beat_and_its_extra_direction():
    clause = app.schedule_flow_clause({
        "flow": [{"type": "caller", "seconds": 80,
                  "detail": "Respond to the previous news point."}],
        "flow_prompt": "Leave room for a sharp host reaction.",
    })

    assert "OPERATOR CONVERSATION FLOW" in clause
    assert "Caller for about 80s" in clause
    assert "Respond to the previous news point." in clause
    assert "Leave room for a sharp host reaction." in clause


def test_scripted_line_is_bounded_and_compiled_as_exact_dialogue():
    node = app._schedule_flow_node({
        "id": "operator-line", "type": "scripted_line", "seconds": 11,
        "after": "orchestrator-turn-3",
        "line": {"speaker": "Host", "text": "Welcome to Pine Box.",
                 "source": "operator"},
    })

    assert node["after"] == "orchestrator-turn-3"
    assert node["line"] == {"speaker": "Host", "text": "Welcome to Pine Box.",
                            "source": "operator"}
    clause = app.schedule_flow_clause({"flow": [node]})
    assert "Scripted line for Host: Welcome to Pine Box." in clause
    assert "Preserve this exact wording" in clause


def test_voice_ad_command_keeps_action_and_requested_copy():
    goal = app.voice_ad_goal(
        "generate me an ad of someone jumping up and down yelling welcome to the pine box"
    )

    assert goal == "someone jumping up and down yelling welcome to the pine box"
    assert app.voice_ad_spoken_copy(goal) == "welcome to the pine box"
    assert app.voice_ad_spoken_copy('a neon station ident "Welcome to Pine Box"') == "Welcome to Pine Box"
    assert app.voice_ad_goal("make an ad") == ""


def test_voice_ad_falls_back_to_a_short_mp4_when_dialogue_index_is_thin(monkeypatch):
    monkeypatch.setattr(app, "sfx_match_score", lambda *args, **kwargs: [])
    monkeypatch.setattr(app, "sfx_db_reader", lambda: None)
    monkeypatch.setattr(app, "sfx_db_pick_short_video",
                        lambda _cap: (app.Path("reference.mp4"), 4.0))
    monkeypatch.setattr(app, "sfx_is_video", lambda _path: True)
    monkeypatch.setattr(app, "sfx_id", lambda _path: "f" * 16)

    assert app.voice_ad_person_clip("jump and yell welcome") == {
        "id": "f" * 16, "name": "reference", "seconds": 4.0,
        "video": True,
        "match": "short MP4 fallback while dialogue matching is unavailable",
    }


def test_reusable_graph_library_keeps_its_id_and_original_save_time_on_update():
    graphs, saved = app.schedule_flow_library_upsert([], {
        "name": "News with a caller", "kind": "news", "minutes": 4,
        "flow_prompt": "Let the caller answer the final fact.",
        "flow": [{"type": "news_mention", "seconds": 80},
                 {"type": "caller", "seconds": 100}],
    })

    assert len(graphs) == 1
    assert saved["name"] == "News with a caller"
    assert [node["type"] for node in saved["flow"]] == ["news_mention", "caller"]
    created = saved["created_at"]

    graphs, updated = app.schedule_flow_library_upsert(graphs, {
        "id": saved["id"], "name": "News caller follow-up", "kind": "news",
        "minutes": 5, "flow": [{"type": "sfx", "seconds": 0}],
    })

    assert len(graphs) == 1
    assert updated["id"] == saved["id"]
    assert updated["created_at"] == created
    assert updated["name"] == "News caller follow-up"
    assert updated["flow"][0]["seconds"] == 6.0
