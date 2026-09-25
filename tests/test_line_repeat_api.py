import unittest
from unittest import mock

import app


class RepeatApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_is_authenticated_and_runs_snapshot_off_loop(self):
        with (mock.patch.object(app, "require_read_auth") as auth,
              mock.patch.object(app, "line_repeat_snapshot", return_value={"ok": True}) as snapshot):
            self.assertEqual(await app.line_repeats_api("id", "text", "Bearer test"), {"ok": True})
            auth.assert_called_once_with("Bearer test")
            snapshot.assert_called_once_with("id", "text")

    async def test_unknown_action_never_touches_the_system(self):
        request = mock.Mock(json=mock.AsyncMock(return_value={"action": "restart_everything"}))
        with (mock.patch.object(app, "require_auth"), mock.patch.object(app, "line_repeat_snapshot") as snapshot):
            with self.assertRaises(app.HTTPException) as error:
                await app.line_repeat_repair_api(request)
            self.assertEqual(error.exception.status_code, 400)
            snapshot.assert_not_called()

    async def test_generation_resolves_server_kind_and_deduplicates_active_jobs(self):
        request = mock.Mock(json=mock.AsyncMock(return_value={"action": "generate", "line_id": "id", "kind": "malicious"}))
        report = {"kind": "caller", "can_generate": True, "text": "An old line"}
        jobs = {"one": {"job": "one", "state": "waiting", "repeat_key": app.line_repeat.fingerprint(report["text"])}}
        with (mock.patch.object(app, "require_auth"),
              mock.patch.object(app, "line_repeat_snapshot", return_value=report),
              mock.patch.object(app, "_ALT_JOBS", jobs),
              mock.patch.object(app, "alt_generate_job") as generate):
            result = await app.line_repeat_repair_api(request)
            self.assertEqual(result["job"], "one")
            generate.assert_not_called()

    async def test_queue_fresh_work_keeps_existing_prompt_and_preserves_history(self):
        request = mock.Mock(json=mock.AsyncMock(return_value={"action": "generate", "line_id": "line"}))
        report = {"kind": "caller", "can_generate": True, "text": "Repeated dialogue"}
        async def capture(coro):
            await coro
        tasks = []
        def schedule(coro):
            tasks.append(coro)
        with (mock.patch.object(app, "require_auth"),
              mock.patch.object(app, "line_repeat_snapshot", return_value=report),
              mock.patch.object(app, "_ALT_JOBS", {}),
              mock.patch.object(app, "schedule_segment_prompt", return_value={"clause": "Original brief"}),
              mock.patch.object(app, "alt_job_put") as record,
              mock.patch.object(app, "pipeline_log"),
              mock.patch.object(app, "alt_generate_job", new_callable=mock.AsyncMock) as generate,
              mock.patch.object(app.asyncio, "create_task", side_effect=schedule)):
            result = await app.line_repeat_repair_api(request)
            self.assertTrue(result["ok"])
            await tasks[0]
            args, kwargs = generate.call_args
            self.assertEqual(args[1:3], ("caller", 1))
            self.assertIn("Original brief", kwargs["brief"])
            self.assertIn("Repeated dialogue", kwargs["brief"])
            self.assertEqual(record.call_args.kwargs["source"], "line")

    def test_durable_model_log_retains_prompts_and_exact_text_identity(self):
        with mock.patch.object(app, "airlog_append_bg") as append:
            app.airlog_model_call({"at": 123, "prompt": "system brief", "script": "A: Hello", "temp": 0}, {})
            row = append.call_args.args[1]
            self.assertEqual(row["prompt"], "system brief")
            self.assertEqual(row["script"], "A: Hello")
            self.assertEqual(row["temp"], 0)
        row = app.airlog_row_from({"id": "id", "text": "Long text " * 100})
        self.assertEqual(row["repeat_text_key"], app.line_repeat.fingerprint("Long text " * 100))


if __name__ == "__main__":
    unittest.main()
