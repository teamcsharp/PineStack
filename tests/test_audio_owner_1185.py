# -*- coding: utf-8 -*-
"""#1185: the air follows the DEVICE, and the house is never silent.

Runs the shipped source of audio_owner() and its helpers against stubs."""
import ast
import io
import sys
import time

SRC = sys.argv[1]
s = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(s)
lines = s.split("\n")


def fn(name):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return "\n".join(lines[n.lineno - 1:n.end_lineno])
    raise SystemExit("no function " + name)


NOW = time.time()
SETTINGS = {"terminals": {}}
ns = {"time": time, "Any": object,
      "AUDIO_OWNER_LIFE": 90.0,
      "_AUDIO_OWNER": {}, "_LISTENER_SEEN": {},
      "_TERMINALS_CACHE": {"at": 0.0, "rows": {}},
      "TERMINALS_TTL": 0.0,                       # no caching in the test
      "load_settings": lambda: SETTINGS,
      "pipeline_log": lambda *a, **k: None}
for f in ("terminal_rows", "terminal_for_listener", "_listener_live",
          "_listeners_live", "_listener_for_terminal", "audio_owner"):
    exec(fn(f), ns)
audio_owner = ns["audio_owner"]

fails = []


def check(label, got, want):
    ok = got == want
    print("  %-56s %s" % (label, "PASS" if ok else "FAIL got=%r want=%r" % (got, want)))
    if not ok:
        fails.append(label)


def setup(owner="", listeners=(), terminals=None):
    """listeners: (id, addr, seconds_ago)"""
    ns["_AUDIO_OWNER"].clear()
    if owner:
        ns["_AUDIO_OWNER"].update({"who": owner, "at": time.time()})
    ns["_LISTENER_SEEN"].clear()
    for lid, addr, ago in listeners:
        ns["_LISTENER_SEEN"][lid] = {"at": time.time() - ago, "addr": addr}
    SETTINGS["terminals"] = terminals if terminals is not None else {
        "pinetab": {"name": "PineTab", "play": True, "addr": "10.89.1.154",
                    "listener": "", "fallback": False, "voice": 1.0},
        "desktop": {"name": "This app", "play": False, "addr": "10.89.1.13",
                    "listener": "", "fallback": True, "voice": 0.6},
    }
    ns["_TERMINALS_CACHE"].update({"at": 0.0, "rows": {}})


TAB, DESK = "10.89.1.154", "10.89.1.13"

print("== the owner is alive: unchanged ==")
setup(owner="tab1", listeners=[("tab1", TAB, 2), ("d1", DESK, 2)])
check("a live nominated listener keeps the air", audio_owner(), "tab1")

print("\n== THE BUG: the tablet reloads and gets a new id ==")
setup(owner="tab1", listeners=[("tab2", TAB, 1), ("d1", DESK, 2)])
check("the air follows the DEVICE to its new id", audio_owner(), "tab2")
check("  ...and is remembered, not re-resolved every call",
      ns["_AUDIO_OWNER"].get("who"), "tab2")

print("\n== nobody nominated: the table decides ==")
setup(owner="", listeners=[("tab9", TAB, 1), ("d1", DESK, 2)])
check("a present play=true device takes the air", audio_owner(), "tab9")

print("\n== the tablet is away ==")
setup(owner="", listeners=[("d1", DESK, 2)])
check("a play=false device is NEVER handed the exclusive", audio_owner(), "")
setup(owner="tab1", listeners=[("d1", DESK, 2)])
check("a dead owner with only play=false present frees the house",
      audio_owner(), "")

print("\n== the fallback is used only when it may play ==")
setup(owner="", listeners=[("d1", DESK, 2)], terminals={
    "pinetab": {"name": "PineTab", "play": True, "addr": TAB,
                "listener": "", "fallback": False},
    "desktop": {"name": "This app", "play": True, "addr": DESK,
                "listener": "", "fallback": True}})
check("fallback takes it when the primary is absent", audio_owner(), "d1")
setup(owner="", listeners=[("tab9", TAB, 1), ("d1", DESK, 2)], terminals={
    "pinetab": {"name": "PineTab", "play": True, "addr": TAB,
                "listener": "", "fallback": False},
    "desktop": {"name": "This app", "play": True, "addr": DESK,
                "listener": "", "fallback": True}})
check("the primary outranks the fallback when both are present",
      audio_owner(), "tab9")

print("\n== the house is never silent ==")
setup(owner="", listeners=[("x1", "10.0.0.9", 1)], terminals={})
check("no table at all -> nobody owns the air, everyone plays",
      audio_owner(), "")
setup(owner="ghost", listeners=[("x1", "10.0.0.9", 1)], terminals={})
check("a stale owner with an empty table releases the house",
      audio_owner(), "")
setup(owner="ghost", listeners=[], terminals=None)
check("no listeners at all -> released", audio_owner(), "")

print("\n== an explicit listener id on the row wins over the address ==")
setup(owner="", listeners=[("named", "10.9.9.9", 1), ("tab9", TAB, 1)],
      terminals={"pinetab": {"name": "PineTab", "play": True, "addr": TAB,
                             "listener": "named", "fallback": False}})
check("the row's own listener id is preferred", audio_owner(), "named")

print("\n== a stale listener does not count as present ==")
setup(owner="", listeners=[("tab9", TAB, 500)])
check("a listener past the lease is not 'present'", audio_owner(), "")

print("\n%s  (%d failure(s))" % ("ALL PASS" if not fails else "FAILURES",
                                len(fails)))
sys.exit(1 if fails else 0)
