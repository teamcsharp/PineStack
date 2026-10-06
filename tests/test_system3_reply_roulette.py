import copy

import outlandish
import system3


EXTREME = "The moon landing was faked and reptilians control the deep state chemtrails."


def scene(seed="pine", roulette=None, opening=""):
    config = system3.default_config()
    config["tables"] += outlandish.default_tables()
    graph = config["structure"]["graph"]
    graph["enabled"] = True
    if roulette:
        graph["reply_roulette"].update(roulette)
    inputs = {"road": "banter", "seats": ["A", "B", "D"], "names": {"A": "Host", "B": "Skip", "D": "Sam"},
              "turns": 12, "subject": {"topic": "the transmitter"}, "availability": {}, "speakerbox_rates": {},
              "line_text": opening}
    conv = system3.new_conversation(inputs, config, system3.normalise_settings({}), seed=seed)
    system3.plan_more(conv, config)
    return conv, config


def test_last_speaker_target_restores_turn_and_prompts_targeted_emotion():
    conv, config = scene(roulette={"initiator_weight": 0, "last_weight": 1, "max_credits": 3})
    inner = [t for t in conv["turns"] if t.get("turn_credit") and not t.get("cast_reaction")]
    assert inner
    for turn in inner:
        target = turn["reply_to"]
        assert target["index"] < turn["index"]
        assert target["speaker"] != turn["speaker"]
        assert target["name"] in turn["protocol"]
        assert "rolled feeling" in turn["protocol"]
        assert "reply-target=" in system3._row_work(turn, conv)
    assert conv["timing"]["turn_budget"] == conv["timing"]["mainline_turn_budget"] + conv["cursor"]["reply_credits"]
    assert conv["cursor"]["reply_credits"] <= 3
    stages = [e["stages"][0]["stage"] for e in conv["decision_events"] if e["family"] == "GRAPH"]
    assert "reply_target" in stages and "reply_followup" in stages
    assert system3.replay(copy.deepcopy(conv), config)["ok"]


def test_cast_reacts_independently_to_one_extreme_source():
    conv, config = scene(opening=EXTREME)
    source = conv["turns"][0]
    reactions = [t for t in conv["turns"] if t.get("cast_reaction") and t["reply_to"]["turn_id"] == source["turn_id"]]
    assert {t["speaker"] for t in reactions} == {"A", "B", "D"} - {source["speaker"]}
    assert len(reactions) == 2
    for turn in reactions:
        assert turn["turn_credit"] == 1
        assert {d["family"] for d in turn["decisions"]} >= {"ES", "RS"}
        assert turn.get("performance")
    assert conv["cursor"]["reaction_credits"] == 2
    assert system3.replay(copy.deepcopy(conv), config)["ok"]


def test_actual_extreme_words_trigger_reactions_after_observation_and_replay():
    conv, config = scene()
    assert not any(t.get("cast_reaction") for t in conv["turns"])
    system3.observe(conv, 0, EXTREME)
    system3.replan(conv, config, 1, until=len(conv["turns"]))
    assert {t["speaker"] for t in conv["turns"] if t.get("cast_reaction")} == {"A", "B", "D"} - {conv["turns"][0]["speaker"]}
    assert system3.replay(copy.deepcopy(conv), config)["ok"]


def test_disabled_reply_wheel_keeps_the_graph_without_inner_turns():
    conv, _ = scene(roulette={"enabled": False}, opening=EXTREME)
    assert not any(t.get("reply_to") or t.get("turn_credit") or t.get("cast_reaction") for t in conv["turns"])
