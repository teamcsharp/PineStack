"""Run isolated regression checks, optionally against the pre-change app."""
import argparse
import importlib.util
import os
import sys
import unittest
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument("--baseline",action="store_true");args=parser.parse_args()
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
os.environ["SPARK_AGENT_DATA_DIR"]="/tmp/pantry-lifecycle-verification-baseline" if args.baseline else "/tmp/pantry-lifecycle-verification"
if args.baseline:
    spec=importlib.util.spec_from_file_location("app",root/"artifacts/pantry-lifecycle/source-before/app.py")
    module=importlib.util.module_from_spec(spec);sys.modules["app"]=module;spec.loader.exec_module(module)
    names=["tests.test_pantry_record_readiness", "tests.test_gold_freeze_2026_09_09.TheAirIsPumped.test_a_held_floor_is_not_a_talking_mouth"]
else:
    names=["tests.test_pantry_lifecycle","tests.test_pantry_lifecycle_integration","tests.test_pantry_record_readiness",
           "tests.test_pantry_order_handoff_integration","tests.test_boot_dj_2026_09_30",
           "tests.test_orchestrator_execution","tests.test_cupboard_unheard_2026_09_12",
           "tests.test_gold_bars","tests.test_gold_freeze_2026_09_09",
           "tests.test_system3_gold","tests.test_unheard_air_2026_09_30"]
result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
sys.exit(0 if result.wasSuccessful() else 1)
