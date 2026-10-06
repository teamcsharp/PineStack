"""Active plot script, source roulette, durable deck, queue and actual audio contracts."""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import h3_plotline
import h3_speak
from tests.test_h3_prompt_presets import station, function_source, FLAGS, Req


PLOT = h3_plotline.context({"id": "story", "title": "Calamity", "run": 1},
                         ["A strange light appears.", "People flee the light.", "SECRET FUTURE ENDING"], 1)
REPLY = json.dumps({"beats": [
    {"who": "Resident", "action": "runs past the shaking house.", "say": "That light is chasing us."},
    {"who": "Neighbor", "action": "pulls the resident around a corner.", "say": "Keep running toward the station."}]})


class Pure(unittest.TestCase):
    def test_only_current_and_earlier_acts_reach_writer(self):
        text = json.dumps(h3_plotline.messages(PLOT, "news", "topic", "Light", "", 19))
        self.assertIn("People flee the light.", text)
        self.assertIn("A strange light appears.", text)
        self.assertNotIn("SECRET FUTURE ENDING", text)

    def test_deck_survives_serialization_and_exhausts_eight_before_repeating(self):
        deck, seen = {}, []
        for _ in range(8):
            cards = h3_plotline.remaining(deck, PLOT)
            scene = cards[-1]
            seen.append(scene)
            deck = json.loads(json.dumps(h3_plotline.consume(deck, PLOT, scene)))
        self.assertEqual(set(seen), set(h3_plotline.SCENES))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(h3_plotline.remaining(deck, PLOT)), 8)
        self.assertEqual(len(h3_plotline.remaining(deck, dict(PLOT, id="new"))), 8)

    def test_script_keeps_actions_speakers_and_dialogue_in_order(self):
        script = h3_plotline.parse(REPLY, 19, h3_speak.speech_why)
        self.assertLess(script["direction"].index("Resident"), script["direction"].index("Neighbor"))
        self.assertEqual(script["speech"], "That light is chasing us. Keep running toward the station.")
        self.assertIn("shaking house", script["direction"])

    def test_compiler_assigns_individual_lines_to_characters(self):
        script = h3_plotline.parse(REPLY, 19, h3_speak.speech_why)
        script["scene"] = "on-the-run"
        prompt = h3_plotline.compose(script, 10)
        self.assertIn("<Subject 1> (S1) is Resident.", prompt)
        self.assertIn("<Subject 2> (S2) is Neighbor.", prompt)
        self.assertIn("<d>[English] Keep running toward the station.</d>", prompt)
        self.assertEqual(prompt.count("<d>"), 2)
        self.assertNotIn("presenter says", prompt)

    def test_reject_unresolved_slots_or_overlong_dialogue(self):
        with self.assertRaises(ValueError):
            h3_plotline.parse(REPLY, 4, h3_speak.speech_why)
        with self.assertRaises(ValueError):
            h3_plotline.parse(REPLY.replace("station.", "{activeplot}."), 19, h3_speak.speech_why)
        with self.assertRaises(ValueError):
            h3_plotline.parse("write a scene", 19, h3_speak.speech_why)


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ns = station(self.tmp.name)
        ns = self.ns
        ns.update(h3_plotline=h3_plotline, h3_speak=h3_speak,
                  plotline_now=lambda: {"h3_context": PLOT}, _H3_HOURLY_ROLLS={},
                  _H3_PLOT_PREP_LOCK=asyncio.Lock(),
                  load_settings=lambda: {"model": "writer"}, model_ctx=lambda: 4096,
                  H3_SPEAK_SECONDS=10, read_bombshells=lambda: [{"text": "Strange lights"}],
                  _h3_slot_speakerbox=lambda: "We can see a bright light.",
                  _h3_slot_note=lambda *args: None,
                  call_ollama=AsyncMock(return_value={"message": {"content": REPLY}}))
        for name in ("h3_plot_prepare", "h3_plot_generate"):
            exec(compile(function_source(name), "app.py", "exec", flags=FLAGS, dont_inherit=True), ns)
        self.picks = []
        def choose(key, choices, label):
            self.picks.append((key, list(choices)))
            return choices[0]
        ns["s3_choice"] = choose
        ns["H3_PROMPTS_BASE"] = (h3_plotline.PRESET,) + ns["H3_PROMPTS_BASE"]
        ns["h3_prompts_change"](ns["h3_prompts_seed_base"])

    def test_seed_and_availability_gate(self):
        ns = self.ns
        view = ns["h3_prompts_view"]()
        p = next(p for p in view["presets"] if p["id"] == "base-active-plot")
        self.assertEqual(p["kind"], "plotline")
        self.assertTrue(p["available"])
        ns["plotline_now"] = lambda: {}
        view = ns["h3_prompts_view"]()
        self.assertFalse(next(p for p in view["presets"] if p["kind"] == "plotline")["available"])
        with self.assertRaises(Exception) as caught:
            ns["h3_prompts_activate"]("base-active-plot")
        self.assertEqual(caught.exception.status_code, 409)
        ns["_H3_PROMPTS_MEM"][0]["active"] = "base-active-plot"
        self.assertNotEqual(ns["h3_prompts_pick"]()["preset"]["kind"], "plotline")
        ns["_H3_PROMPTS_MEM"][0]["dice"] = True
        for _ in range(5):
            self.assertNotEqual(ns["h3_prompts_pick"]()["preset"]["kind"], "plotline")

    def test_one_source_roll_and_no_air_dialogue_appended(self):
        ns = self.ns
        script = asyncio.run(ns["h3_plot_prepare"](h3_plotline.PRESET))
        self.assertEqual(len([x for x in self.picks if x[0] == "h3.plot_dialogue"]), 1)
        self.assertEqual(script["source"], "speakerbox")
        sent = ns["call_ollama"].call_args.kwargs["messages"]
        self.assertNotIn("SECRET FUTURE ENDING", json.dumps(sent))
        ns["_H3_PICKED"][0] = {"at": __import__('time').time(), "how": "active", "preset": h3_plotline.PRESET,
                                "roll": None, "pin": None, "plotline": script}
        hour = ns["h3_prompts_hour"]("Unrelated aired text")
        for road in ("clip", "gallery", "host"):
            words = ns["h3_prompts_words"](hour, road, "Old speech")
            self.assertEqual(words["speech"], script["speech"])
            self.assertEqual(words["direction"], script["direction"])
            self.assertEqual(words["plotline"]["plot"]["act"], 2)
        ns["h3_prompts_load"](fresh=True)
        self.assertEqual(len(ns["h3_prompts_load"]()["plot_deck"]["remaining"]), 7)

    def test_manual_video_queues_generated_script_without_rendering(self):
        ns = self.ns
        class Queue:
            def add(self, payload):
                self.payload = payload
                return {"id": "queued"}
        queue = Queue()
        ns.update(_parody_stinger_queue=lambda: queue, _parody_stinger_wake=asyncio.Event())
        result = asyncio.run(ns["h3_plot_generate"](Req({"preset_id": "base-active-plot"}), "key"))
        self.assertEqual(result["queue_id"], "queued")
        self.assertEqual(queue.payload["mode"], "text")
        self.assertEqual(queue.payload["h3_prompts"]["plotline"]["speech"], result["script"]["speech"])

    def test_topic_source_seeds_model_once(self):
        ns = self.ns
        def choose(key, choices, label):
            self.picks.append((key, list(choices)))
            return "topic" if key == "h3.plot_dialogue" else choices[0]
        ns["s3_choice"] = choose
        script = asyncio.run(ns["h3_plot_prepare"](h3_plotline.PRESET))
        self.assertEqual(script["seed"], "Strange lights")
        self.assertEqual(script["source"], "topic")
        self.assertEqual(len([x for x in self.picks if x[0] == "h3.plot_dialogue"]), 1)


class Audio(unittest.TestCase):
    def test_mix_keeps_dialogue_and_maps_actual_audio_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            video, audio = Path(tmp)/"render.mp4", Path(tmp)/"tape.wav"
            video.write_bytes(b"original")
            audio.write_bytes(b"source")
            calls = []
            def run(cmd, **kwargs):
                calls.append(cmd)
                Path(cmd[-1]).write_bytes(b'x' * 2048)
                return type('Result', (), {'returncode': 0})()
            out = h3_plotline.mix_audio(video, audio, "concert", "ffmpeg", 10, run)
            self.assertEqual(video.read_bytes(), b"original")
            self.assertIn(str(audio), calls[0])
            self.assertIn("-stream_loop", calls[0])
            self.assertIn("[voice][bed]amix", calls[0][calls[0].index("-filter_complex")+1])
            self.assertEqual(h3_plotline.mix_audio(video, audio, "concert", "ffmpeg", 10, run), out)
            self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
