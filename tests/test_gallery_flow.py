"""Gallery file operations must not block the station or move roulette off its loop."""
import ast
import asyncio
import base64
from contextlib import asynccontextmanager
from pathlib import Path
import re
import threading
from types import SimpleNamespace
import unittest


class GalleryFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_gallery_metadata_and_pixels_use_workers_but_roulette_uses_loop(self):
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        tail = source[source.index('async def describe_gallery_image('):]
        end = re.search(r'(?m)^[A-Z_]\w*\s*=', tail)
        node = ast.parse(tail[:end.start()]).body[0]
        loop_thread = threading.get_ident()
        calls = {}

        class Picture:
            name = 'fixture.png'
            def stat(self):
                calls['stat'] = threading.get_ident()
                return SimpleNamespace(st_size=100)
            def read_bytes(self):
                calls['pixels'] = threading.get_ident()
                return b'fixture image'

        @asynccontextmanager
        async def gate():
            yield

        @asynccontextmanager
        async def client(**kwargs):
            yield object()

        async def post(*args, **kwargs):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'message': {'content': ''}})

        def choice(*args, **kwargs):
            calls['roulette'] = threading.get_ident()
            return args[1][0]

        namespace = dict(asyncio=asyncio, base64=base64, re=re,
                         gallery_files=lambda: [Picture()], _RADIO={}, s3_choice=choice,
                         load_settings=lambda: {}, vision_prompt_active=lambda: 'fixture',
                         time=__import__('time'), random=__import__('random'),
                         _OLLAMA_GATE=gate(), httpx=SimpleNamespace(AsyncClient=client),
                         recorded_ollama_post=post, OLLAMA_URL='http://fixture',
                         VISION_MODEL='fixture', model_ctx=lambda: 1000)
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'gallery flow adapter', 'exec'), namespace)
        self.assertEqual(await namespace['describe_gallery_image'](), ('fixture.png', ''))
        self.assertNotEqual(calls['stat'], loop_thread)
        self.assertNotEqual(calls['pixels'], loop_thread)
        self.assertEqual(calls['roulette'], loop_thread)
