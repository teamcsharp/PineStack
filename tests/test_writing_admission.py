import asyncio
import unittest
from contextlib import ExitStack
from unittest import mock

import app


class WritingAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_model_admits_one_running_one_waiting_and_defers_the_rest(self):
        release, entered = asyncio.Event(), asyncio.Event()
        response = mock.Mock()
        response.json.return_value = {"message": {"content": "completed"}}

        async def post(*args, **kwargs):
            entered.set()
            await release.wait()
            return response

        client = mock.AsyncMock()
        client.__aenter__.return_value = client
        client.post.side_effect = post
        with (mock.patch.object(app, "_OLLAMA_JOBS", {}),
              mock.patch.object(app, "_OLLAMA_DEFERRED", {}),
              mock.patch.object(app, "_OLLAMA_ONE", {}),
              mock.patch.object(app, "_OLLAMA_GATE", asyncio.Semaphore(2)),
              mock.patch.object(app.httpx, "AsyncClient", return_value=client)):
            async def write(purpose="station:caller"):
                return await app.call_ollama(model="test", messages=[], temperature=.5,
                                              max_tokens=20, purpose=purpose)
            first = asyncio.create_task(write())
            await entered.wait()
            second = asyncio.create_task(write())
            await asyncio.sleep(0)
            state = app.writing_room_state()
            self.assertEqual((state["active"], state["waiting"]), (1, 1))
            third = await write()
            self.assertTrue(third["deferred"])
            self.assertEqual(client.post.await_count, 1)
            # A distinct, bounded repertoire job can await the same model;
            # station clocks cannot fill all future positions in front of it.
            repertoire = asyncio.create_task(write("response_bank"))
            await asyncio.sleep(0)
            self.assertTrue((await write("response_bank"))["deferred"])
            release.set()
            results = await asyncio.gather(first, second, repertoire)
            self.assertTrue(all(r["message"]["content"] == "completed" for r in results))
            self.assertEqual(app._OLLAMA_JOBS, {})

    async def test_cancelled_waiter_releases_admission(self):
        blocked = asyncio.Semaphore(0)
        with (mock.patch.object(app, "_OLLAMA_JOBS", {}),
              mock.patch.object(app, "_OLLAMA_ONE", {"test": blocked})):
            task = asyncio.create_task(app.call_ollama(model="test", messages=[],
                temperature=.5, max_tokens=20, purpose="station:gallery"))
            await asyncio.sleep(0)
            self.assertEqual(len(app._OLLAMA_JOBS), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(app._OLLAMA_JOBS, {})

    async def test_repeated_clock_triggers_coalesce_one_road_but_other_roads_continue(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def work(kind):
            started.set()
            await release.wait()
            return True

        with (mock.patch.object(app, "_PREP_ROAD_ACTIVE", {}),
              mock.patch.object(app, "_prep_one_work", side_effect=work) as prepare):
            first = asyncio.create_task(app.prep_one("caller"))
            await started.wait()
            self.assertFalse(await app.prep_one("caller"))
            other = asyncio.create_task(app.prep_one("gallery"))
            await asyncio.sleep(0)
            self.assertEqual(prepare.await_count, 2)
            release.set()
            self.assertEqual(await asyncio.gather(first, other), [True, True])
            self.assertEqual(app._PREP_ROAD_ACTIVE, {})


if __name__ == "__main__":
    unittest.main()
