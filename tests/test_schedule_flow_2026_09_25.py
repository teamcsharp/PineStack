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
