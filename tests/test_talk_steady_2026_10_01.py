"""[talk-steady] The station froze its own loop 120 s in 14 min (2026-10-01): a full
fork of the 8 GB process for every SFX/video request, and System 3 lines planned
and thrown away while the voice engine was busy. Fails on the code before."""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
APP_TEXT = (ROOT / "app.py").read_text(encoding="utf-8")
TREE = ast.parse(APP_TEXT)


def app_function(name, env):
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            exec(compile(ast.Module([node], []), "app.py:" + name, "exec"), env)  # noqa: S102
            return env[name]
    raise AssertionError(name)


class Steady(unittest.TestCase):
    def env(self, inflight=0, prep=0, by=None):
        return {"recording_booths": lambda: {"capacity": 3, "prep_limit": 2},
                "engine_inflight": lambda: inflight, "_ENGINE_PREP": [prep], "_ENGINE_PREP_BY": dict(by or {})}

    def test_free_agrees_with_take_and_takes_nothing(self):
        for case in (dict(), dict(inflight=3), dict(prep=2), dict(by={"xtts": 1}), dict(by={"shared": 1}),
                     dict(prep=1)):
            for engine in ("xtts", "", "f5"):
                env = self.env(**case)
                free = app_function("engine_prep_free", env)(engine)
                self.assertEqual(env["_ENGINE_PREP"], [case.get("prep", 0)], "free takes nothing")
                took = app_function("engine_prep_take", env)(engine)
                self.assertEqual(free, took, (case, engine))

    def test_the_plan_waits_for_a_slot(self):
        src = APP_TEXT[APP_TEXT.index("async def prep_render_line("):]
        src = src[:src.index("\nasync def ", 10)]
        self.assertLess(src.index("if not engine_prep_free(engine):"), src.index('globals().get("system3_direct_line")'))
        self.assertIn("await asyncio.sleep(0)                      # [talk-steady]", src)

    def test_the_gain_stream_spawns_without_forking(self):
        src = APP_TEXT[APP_TEXT.index("async def sfx_gain_stream("):]
        src = src[:src.index("async def body():")]
        self.assertIn("close_fds=False", src)
        # the box's own ffmpeg, an absolute path (posix_spawn needs one; none is on PATH in the container)
        self.assertIn('cmd = [_sfx_ffmpeg() or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner"', APP_TEXT)


if __name__ == "__main__":
    unittest.main()
