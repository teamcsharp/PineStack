#!/usr/bin/env python3
"""[llm-command] Wire the LLM command book into app.py. 2026-10-06.

"when it comes to LLM commands, I want a popup where I am mapping them and
their behavior and am able to view them on a table and adjust them. Call the
popup 'LLM command' and I want to be able to add commands that then are able
to be expanded on and used with the Nabu / Pine box. List every command we
have assigned so far and keep a count of how many times I use commands
through the LLM assistant."

Four edits to app.py, each anchored on text taken from the file as it is:

  1. `import llm_commands` beside `import blocked_book` (line ~98).
  2. `llm_commands.install(app, globals())` after the blocked_book install at
     the end of the module - install() watches the parsers THERE, after
     app.py has defined every one of them, and mounts the routes.
  3. In generate_answer, right after `user_text = latest_user_text(...)`: a
     custom command whose `as` names a sentence the parsers understand is
     rewritten into that sentence before the chain sees it.
  4. Immediately before `if parse_show_doctor(user_text):` - the head of the
     command chain - two branches: a custom command's fixed reply, and a
     custom command that is an orchestrator line (run through
     orch_command_run, its `say` and first lines spoken back). Both return
     the shape every neighbouring command returns, model "llm-command".

app.py is CRLF: matching is done on LF text and the file is written back CRLF
(a BOM is kept if present), through a temp file and an atomic replace.

Usage:  llm_commands_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        llm_commands_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

IMPORT_OLD = '''import blocked_book                                          # [blocked-book]
'''
IMPORT_NEW = '''import blocked_book                                          # [blocked-book]
import llm_commands                                          # [llm-command] the LLM command book
'''

INSTALL_OLD = '''blocked_book.install(app, globals())                         # [blocked-book] GET /api/blocked
'''
INSTALL_NEW = '''blocked_book.install(app, globals())                         # [blocked-book] GET /api/blocked
llm_commands.install(app, globals())                         # [llm-command] GET /api/llm-commands; counts the parsers above
'''

REWRITE_OLD = '''    settings = load_settings()
    user_text = latest_user_text(incoming_messages)

    if not user_text:
'''
REWRITE_NEW = '''    settings = load_settings()
    user_text = latest_user_text(incoming_messages)
    # [llm-command] one of the operator's own commands whose "as" names a
    # sentence the parsers below understand is said to them as that sentence.
    user_text = llm_commands.rewrite(user_text)[0]

    if not user_text:
'''

BRANCH_OLD = '''    if parse_show_doctor(user_text):                                     # [show-doctor]
        feature_meta["system_status_used"] = True
        return (await show_doctor()), {
'''
BRANCH_NEW = '''    # [llm-command] the operator's own commands, before every built-in detector:
    # a fixed reply, or a line for the orchestrator's command line (the verbs
    # of /api/orchestrator/command), spoken back.
    _llm_said = llm_commands.fixed_reply(user_text)
    if _llm_said:
        return _llm_said, {
            **feature_meta,
            "active_prompt": prompt_entry["name"],
            "model": "llm-command",
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
    _llm_line = llm_commands.orchestrator_line(user_text)
    if _llm_line:
        _llm_got = await orch_command_run(_llm_line)
        _llm_got = _llm_got if isinstance(_llm_got, dict) else {}
        _llm_say = str(_llm_got.get("say") or _llm_got.get("said") or "done.")
        _llm_lines = [str(x).strip() for x in (_llm_got.get("lines") or [])[:4]
                      if str(x).strip()]
        if _llm_lines:
            _llm_say = _llm_say.rstrip() + " " + " ".join(_llm_lines)
        return _llm_say, {
            **feature_meta,
            "active_prompt": prompt_entry["name"],
            "model": "llm-command",
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
    if parse_show_doctor(user_text):                                     # [show-doctor]
        feature_meta["system_status_used"] = True
        return (await show_doctor()), {
'''

EDITS = {
    "app.py": [
        ("import llm_commands beside import blocked_book", IMPORT_OLD, IMPORT_NEW, 1),
        ("llm_commands.install after the blocked_book install (parsers all defined by then)", INSTALL_OLD, INSTALL_NEW, 1),
        ("generate_answer: the custom 'as' alias rewrites user_text", REWRITE_OLD, REWRITE_NEW, 1),
        ("generate_answer: fixed-reply and orchestrator branches before parse_show_doctor", BRANCH_OLD, BRANCH_NEW, 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".llmcmd.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
