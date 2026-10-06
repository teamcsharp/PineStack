from __future__ import annotations
import builtins
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from process_limits import ensure_nofile_headroom


class ProcessLimitTests(unittest.TestCase):
    def resource(self, soft=1024, hard=524288):
        calls = []
        return SimpleNamespace(RLIMIT_NOFILE=7, RLIM_INFINITY=-1,
                               getrlimit=lambda kind: (soft, hard),
                               setrlimit=lambda kind, pair: calls.append((kind, pair))), calls

    def test_low_soft_limit_gains_headroom_without_changing_hard(self):
        resource, calls = self.resource()
        self.assertEqual({"ok": True, "supported": True, "changed": True,
                          "soft": 8192, "hard": 524288}, ensure_nofile_headroom(resource_module=resource))
        self.assertEqual([(7, (8192, 524288))], calls)

    def test_existing_higher_soft_limit_is_preserved(self):
        resource, calls = self.resource(65536)
        result = ensure_nofile_headroom(resource_module=resource)
        self.assertFalse(result["changed"])
        self.assertEqual(65536, result["soft"])
        self.assertEqual([], calls)

    def test_infinite_soft_limit_is_preserved(self):
        resource, calls = self.resource(-1, -1)
        self.assertFalse(ensure_nofile_headroom(resource_module=resource)["changed"])
        self.assertEqual([], calls)

    def test_finite_hard_limit_caps_requested_headroom(self):
        resource, calls = self.resource(1024, 2048)
        self.assertEqual(2048, ensure_nofile_headroom(resource_module=resource)["soft"])
        self.assertEqual([(7, (2048, 2048))], calls)

    def test_infinite_hard_limit_keeps_original_hard_allowance(self):
        resource, calls = self.resource(1024, -1)
        ensure_nofile_headroom(resource_module=resource)
        self.assertEqual([(7, (8192, -1))], calls)

    def test_unraiseable_limit_does_not_fail_startup(self):
        resource, _ = self.resource()
        resource.setrlimit = lambda *args: (_ for _ in ()).throw(PermissionError("limit denied"))
        result = ensure_nofile_headroom(resource_module=resource)
        self.assertFalse(result["ok"])
        self.assertFalse(result["changed"])

    def test_unavailable_resource_module_does_not_fail_windows_startup(self):
        original = builtins.__import__
        def without_resource(name, *args, **kwargs):
            if name == "resource":
                raise ImportError("not available on Windows")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=without_resource):
            self.assertEqual({"ok": False, "supported": False, "changed": False}, ensure_nofile_headroom())

    @unittest.skipIf(sys.platform == "win32", "Unix resource limits only")
    def test_real_child_process_restores_a_low_limit_without_parent_mutation(self):
        import resource
        before = resource.getrlimit(resource.RLIMIT_NOFILE)
        code = "import json,resource; from process_limits import ensure_nofile_headroom; soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE); resource.setrlimit(resource.RLIMIT_NOFILE,(min(128,hard),hard)); print(json.dumps(ensure_nofile_headroom()))"
        output = subprocess.check_output([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], text=True, timeout=5)
        after = json.loads(output)
        self.assertTrue(after["ok"])
        self.assertEqual(min(8192, before[1]) if before[1] != resource.RLIM_INFINITY else 8192, after["soft"])
        self.assertEqual(before[1], after["hard"])
        self.assertEqual(before, resource.getrlimit(resource.RLIMIT_NOFILE))
