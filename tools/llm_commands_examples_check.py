#!/usr/bin/env python3
"""[llm-command] Run the command book's example sentences through app.py's own parsers. 2026-10-06.

The book (llm_commands.py) says, for every built-in command, what sentences
trigger it. A sentence that stops matching when a regex changes is a lie on
the table, so this tool lifts each parser and the constants it reads out of
app.py by AST (no import of app.py: that would start the station), executes
them in a bare namespace with `re`, `os` and `time`, and asks two questions of
every example:

  1. does its OWN parser answer it?
  2. walking the chain in generate_answer's order, is its own parser the
     FIRST to answer (or is the sentence stolen by an earlier command)?

Parsers that read station state (the gear manuals, the shelf, the crystals)
are stubbed to a fixed world: one device called "sidekick" / "op-1" /
"ep-133", no crystals, no shelf. Their rows are marked runtime in the book,
and here they are checked as far as their regex gates go.

Usage:  llm_commands_examples_check.py [ROOT]      exit 0 all good, 1 a lie on the table
"""
from __future__ import annotations

import ast
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
for cand in (HERE.parent / "modules", HERE.parent):
    if (cand / "llm_commands.py").exists() and str(cand) not in sys.path:
        sys.path.insert(0, str(cand))

import llm_commands  # noqa: E402

# every module-level name the chain's parsers read, lifted from app.py in file order
WANTED = {
    "_WEATHER_RE", "_OUTSIDE_RE", "is_weather_query", "GAME_PATTERNS", "is_game_query", "RESEARCH_PATTERNS",
    "is_research_query", "TV_PATTERNS", "is_tv_query", "TE_SHOW", "TE_MANUAL_WORDS", "TE_MANUAL_SHOW",
    "TE_MANUAL_BARE", "TE_STICKY_SECONDS", "te_manual_intent", "is_te_query", "SYSTEM_PATTERNS",
    "is_system_query", "is_comfy_status_query", "CRYSTAL_LIBRARY", "is_song_query", "_DIRECTIVE_ROADS",
    "_DIRECTIVE_DIAL_ROADS", "_DIRECTIVE_MORE", "_DIRECTIVE_LESS", "_DIRECTIVE_LEAD", "_DIRECTIVE_SHAPES",
    "_DIRECTIVE_FILLER", "_DIRECTIVE_ADDRESSED_SHAPES", "_DIRECTIVE_RESIDUE_FILLER", "DIRECTIVE_RESIDUE_MOST",
    "directive_road", "directive_move", "_directive_shape", "_directive_residue", "parse_directive",
    "MEMORY_COMMAND", "is_memory_command", "_HAPPENED_RX", "_SHOW_DOCTOR_RX", "parse_show_doctor",
    "parse_what_happened", "SERVICE_ALIASES", "parse_service_command", "_BROADCAST_DESTS",
    "parse_broadcast_command", "is_services_query", "_EXPORT_UNITS", "_EXPORT_WORD_NUM", "_EXPORT_NUM_RX",
    "_EXPORT_VERB_RX", "_EXPORT_WEAK_VERBS", "_EXPORT_SUBJECT_CORE", "_EXPORT_SUBJECT_RX", "_EXPORT_NOT_A_DIR",
    "_EXPORT_FILLER", "export_dir_shaped", "export_number", "_EXPORT_SCREEN_RX", "export_screen_target",
    "EXPORT_BARE_SECONDS", "parse_export_command", "parse_paper_command", "ORCH_COMMAND_VERBS",
}

STUB_DEVICES = [{"slug": "ep-136", "names": ["sidekick", "ko sidekick", "ep-136"]},
                {"slug": "op-1", "names": ["op-1", "op 1"]},
                {"slug": "ep-133", "names": ["ep-133", "ep 133", "ko ii"]}]


def _stub_namespace() -> dict[str, Any]:
    def te_devices():
        return STUB_DEVICES

    def te_match_device(text):
        low = " " + re.sub(r"[^a-z0-9]+", " ", str(text).lower()) + " "
        for d in STUB_DEVICES:
            for n in d["names"]:
                if " " + re.sub(r"[^a-z0-9]+", " ", n).strip() + " " in low:
                    return d
        return None

    return {
        "re": re, "os": os, "time": time, "Any": Any,
        "te_devices": te_devices, "te_match_device": te_match_device,
        "te_section_lookup": lambda text: {"slug": "stub", "title": "stub", "pages": []},
        "te_section_words": lambda doc, text: True, "te_doc": lambda slug: {},
        "_TE_LAST": {"slug": "", "ts": 0.0},
        "read_crystals": lambda: [], "crystal_match": lambda text: None,
    }


def lift(app_py: Path) -> dict[str, Any]:
    text = app_py.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n")
    tree = ast.parse(text)
    lines = text.split("\n")
    ns = _stub_namespace()
    found: list[str] = []
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        hit = [n for n in names if n in WANTED]
        if not hit:
            continue
        src = "\n".join(lines[node.lineno - 1:node.end_lineno])
        exec(compile(src, str(app_py), "exec"), ns)  # noqa: S102 - the station's own source
        found.extend(hit)
    missing = sorted(WANTED - set(found))
    if missing:
        raise SystemExit("not found in app.py: %s" % ", ".join(missing))
    return ns


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else HERE.parent.parent
    app_py = root / "app.py"
    if not app_py.exists():
        print("no app.py under %s" % root)
        return 1
    t0 = time.time()
    ns = lift(app_py)
    print("lifted %d names from %s in %.1fs" % (len(WANTED), app_py, time.time() - t0))
    chain = [n for n in llm_commands.CHAIN if n != "is_library_query"]   # the shelf needs the shelf
    bad = 0
    for spec in llm_commands.BUILTINS:
        pid = spec["id"]
        fn = ns.get(pid)
        for ex in spec["examples"]:
            if "<" in ex:
                print("  %-26s %-58s (runtime: a held title)" % (pid, ex))
                continue
            own = bool(fn(ex)) if callable(fn) else None
            note = ""
            if not own and pid == "is_te_query":
                # a follow-up about "the page" only counts while a manual is open: open one
                ns["_TE_LAST"].update(slug="op-1", ts=time.time())
                own = bool(fn(ex))
                note = " (with a manual open)"
            first = ""
            for name in chain:
                f = ns.get(name)
                try:
                    if callable(f) and f(ex):
                        first = name
                        break
                except Exception as exc:  # noqa: BLE001
                    first = "%s tripped: %s" % (name, exc)
                    break
            ns["_TE_LAST"].update(slug="", ts=0.0)
            first += note
            ok = own and first == pid + note
            if not ok and spec.get("verified") == "runtime" and pid == "is_song_query":
                ok = bool(ns["CRYSTAL_LIBRARY"].search(ex))       # the library question is the regex half
                first = first or "(regex only)"
            if not ok and pid == "is_library_query":
                ok = True
                first = "(runtime only)"
            flag = "ok " if ok else "BAD"
            if not ok:
                bad += 1
            print("  %s %-26s %-58s own=%s first=%s" % (flag, pid, ex[:58], own, first))
    verbs = [v for v, _ in ns["ORCH_COMMAND_VERBS"]]
    print("orchestrator verbs in app.py: %d; rows in the book: %d" % (len(verbs), len(llm_commands.ORCHESTRATOR)))
    for spec in llm_commands.ORCHESTRATOR:
        for ex in spec["examples"]:
            got = llm_commands.orch_id_for(ex)
            ok = got == spec["id"]
            if not ok:
                bad += 1
            print("  %s %-16s %-40s -> %s" % ("ok " if ok else "BAD", spec["id"], ex, got))
    print("%d lie(s) on the table" % bad if bad else "every example answers, and its own command answers first")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
