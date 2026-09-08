"""A tiny SFX reserve joins the normal FIFO without changing any grading."""
import asyncio
from contextlib import ExitStack
from unittest import mock
import unittest

import app
import test_tint_round_pass as tint_fixture
from sfx_speech_bank import SfxSpeechBank
from pathlib import Path
import tempfile


class SfxReserveAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.row = {"id": "pending", "text_plain": "I heard what you said. Go ahead."}
        self.bank = mock.Mock()
        self.bank.rows.return_value = []
        self.bank.eligible.return_value = []
        for name, value in {"_SFX_READY_BANK": self.bank,
                "_sfxguy_ready_valid": lambda row, voice: row.get("valid", True),
                "pipeline_log": mock.Mock(), "round_mark": mock.Mock(),
                "box_depth": lambda: 0, "writing_profile": lambda: {},
                "line_review_guidance": lambda *args: ""}.items():
            self.stack.enter_context(mock.patch.object(app, name, value))
        token = app._SFX_RESERVE_WRITING.set(False)
        self.addCleanup(app._SFX_RESERVE_WRITING.reset, token)

    async def test_only_distinct_current_valid_ready_stock_satisfies_the_small_reserve(self):
        seen = []
        async def tint(*args, **kwargs):
            seen.append((app._SFX_RESERVE_WRITING.get(), args, kwargs))
            return {"ok": False, "deferred": True}
        with mock.patch.object(app, "crystal_tint", side_effect=tint):
            for stock in ([], [{"text": "same"}, {"text": " SAME "}],
                          [{"text": "one"}, {"text": "two"}]):
                self.bank.eligible.return_value = stock
                await app._sfxguy_tint_source(self.row, "exact-voice", "current-profile")
                self.assertFalse(app._SFX_RESERVE_WRITING.get())
        self.assertEqual([item[0] for item in seen], [True, True, False])
        self.assertTrue(all(item[1] == (self.row["text_plain"], "sfxguy") for item in seen))
        self.assertTrue(all(item[2]["whole_only"] and item[2]["critical"] is False for item in seen))
        self.assertEqual(self.bank.eligible.call_args.args[:3], ("", "exact-voice", "current-profile"))

    async def test_reserved_recently_heard_or_topical_stock_cannot_hide_an_empty_usable_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = [1000.0]
            root = Path(tmp)
            bank = SfxSpeechBank(root / "bank.json", root, clock=lambda: clock[0])
            bank.seed("v", "p", [{"text": "First rhyme in time.", "generic": True},
                {"text": "A second line will shine.", "generic": True},
                {"text": "The carburetor rattles loud.", "generic": False}])
            for row in bank.rows():
                (root / (row["id"] + ".wav")).write_bytes(b"fixture recording")
                row.update(state="ready", clip={"path": "/media/" + row["id"] + ".wav", "seconds": 3})
                bank.put(row)
            token = bank.pick("", "v", "p", lambda row: True)["id"]
            remaining = bank.pick("", "v", "p", lambda row: True)["id"]
            bank.finish(remaining, heard=True)
            saved = bank.path.read_bytes()
            self.assertEqual(bank.eligible("", "v", "p", lambda row: True), [])
            flags = []
            async def tint(*args, **kwargs):
                flags.append(app._SFX_RESERVE_WRITING.get()); return {"ok": False}
            with mock.patch.object(app, "_SFX_READY_BANK", bank), mock.patch.object(app, "crystal_tint", side_effect=tint):
                await app._sfxguy_tint_source(self.row, "v", "p")
                self.assertEqual(bank.path.read_bytes(), saved)
                bank.finish(token, heard=False)
                clock[0] += 181
                await app._sfxguy_tint_source(self.row, "v", "p")
            self.assertEqual(flags, [True, False])

    async def test_actual_writer_purpose_does_not_leak_to_concurrent_hosts_or_non_tint(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def model(**kwargs):
            calls.append((kwargs["messages"][-1]["content"], kwargs["purpose"], kwargs["model"]))
            return {"message": {"content": "A complete sentence."}}
        async def tint(*args, **kwargs):
            entered.set()
            await release.wait()
            await app.ask_model("reserve", mark={"kind": "tint turn"}, model="original-road-model")
            await app.ask_model("ordinary nested work", mark={"kind": "writing"}, model="original-road-model")
            return {"ok": False}
        with (mock.patch.object(app, "call_ollama", side_effect=model),
              mock.patch.object(app, "crystal_tint", side_effect=tint)):
            job = asyncio.create_task(app._sfxguy_tint_source(self.row, "v", "p"))
            await entered.wait()
            self.assertFalse(app._SFX_RESERVE_WRITING.get())
            await app.ask_model("host", mark={"kind": "tint round"}, model="host-model")
            release.set()
            await job
            await app.ask_model("later host", mark={"kind": "tint turn"}, model="host-model")
        self.assertEqual(calls, [("host", "station:tint round", "host-model"),
            ("reserve", "sfx_tint_reserve", "original-road-model"),
            ("ordinary nested work", "station:writing", "original-road-model"),
            ("later host", "station:tint turn", "host-model")])

    async def test_cancellation_restores_context_in_the_same_task(self):
        entered = asyncio.Event()
        values = []
        async def tint(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        async def run():
            try:
                await app._sfxguy_tint_source(self.row, "v", "p")
            except asyncio.CancelledError:
                values.append(app._SFX_RESERVE_WRITING.get())
                raise
        with mock.patch.object(app, "crystal_tint", side_effect=tint):
            task = asyncio.create_task(run())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(values, [False])
        self.assertFalse(app._SFX_RESERVE_WRITING.get())

    async def test_reserved_job_waits_behind_existing_tint_fifo_and_cancellation_releases_its_one_slot(self):
        entered, release = asyncio.Event(), asyncio.Event()
        heard = []
        response = mock.Mock(); response.json.return_value = {"message": {"content": "done"}}
        async def post(*args, **kwargs):
            heard.append(kwargs["json"]["messages"][0]["content"])
            entered.set()
            await release.wait()
            return response
        client = mock.AsyncMock(); client.__aenter__.return_value = client; client.post.side_effect = post
        with (mock.patch.object(app, "_OLLAMA_JOBS", {}), mock.patch.object(app, "_OLLAMA_ONE", {}),
              mock.patch.object(app, "_OLLAMA_DEFERRED", {}), mock.patch.object(app, "_OLLAMA_DEFERRED_CATEGORIES", {}),
              mock.patch.object(app, "_OLLAMA_GATE", asyncio.Semaphore(2)),
              mock.patch.object(app.httpx, "AsyncClient", return_value=client)):
            async def call(label, purpose="station:tint round"):
                return await app.call_ollama(model="same-model", messages=[{"role": "user", "content": label}],
                    temperature=.4, max_tokens=128, purpose=purpose)
            first = asyncio.create_task(call("first")); await entered.wait()
            # The tint cap is a waiting depth of three behind the lane (the
            # cupboard audit): three visible waiters, then the excess is refused.
            second = asyncio.create_task(call("second")); await asyncio.sleep(0)
            third = asyncio.create_task(call("third")); await asyncio.sleep(0)
            fourth = asyncio.create_task(call("fourth")); await asyncio.sleep(0)
            self.assertTrue((await call("excess tint"))["deferred"])
            reserve = asyncio.create_task(call("cancelled reserve", "sfx_tint_reserve")); await asyncio.sleep(0)
            self.assertTrue((await call("excess reserve", "sfx_tint_reserve"))["deferred"])
            self.assertEqual(heard, ["first"])
            self.assertEqual(app.writing_room_state()["category_limits_per_model"]["sfx_reserve"], 1)
            reserve.cancel()
            with self.assertRaises(asyncio.CancelledError): await reserve
            self.assertFalse(any(row["category"] == "sfx_reserve" for row in app._OLLAMA_JOBS.values()))
            replacement = asyncio.create_task(call("replacement reserve", "sfx_tint_reserve"))
            await asyncio.sleep(0); release.set()
            await asyncio.gather(first, second, third, fourth, replacement)
            self.assertEqual(heard, ["first", "second", "third", "fourth", "replacement reserve"])
            self.assertEqual(app._OLLAMA_JOBS, {})

    async def test_actual_crystal_selection_with_hold_off_keeps_the_original_road_model(self):
        fixture = tint_fixture.TintRoundPassTests()
        with ExitStack() as stack:
            for patch in fixture.tint_patches(False, [], []): stack.enter_context(patch)
            stack.enter_context(mock.patch.object(app, "banter_turns", return_value=[]))
            road = stack.enter_context(mock.patch.object(app, "tint_model_for", return_value="normal-sfx-model"))
            fast = stack.enter_context(mock.patch.object(app, "tint_fast_model", return_value="unexpected-fast"))
            request = stack.enter_context(mock.patch.object(app, "ask_model", new_callable=mock.AsyncMock,
                side_effect=app.WritingDeferred("fixture retains original source")))
            report = await app._sfxguy_tint_source(self.row, "v", "p")
        self.assertTrue(report.get("deferred"), report)
        road.assert_called_once_with("sfxguy")
        fast.assert_not_called()
        self.assertEqual(request.await_args.kwargs["model"], "normal-sfx-model")
        self.assertFalse(app._SFX_RESERVE_WRITING.get())


if __name__ == "__main__":
    unittest.main()
