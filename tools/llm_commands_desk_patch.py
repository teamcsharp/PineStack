#!/usr/bin/env python3
"""[llm-command] The desk, the PiP menu and the tablet carry the LLM command book popup. 2026-10-06.

"an LLM command popup ... every command the LLM listens for, what it does, how often it has been
used, and a way to add my own"                                  - the operator, 2026-10-06

Edits (CRLF kept where the file has it):
  desktop/renderer/index.html       <link llm-commands.css> after blocked-book.css; <script llm-commands.js>
                                    after blocked-book.js (the PiP tools catalog then finds
                                    window.PineLlmCommands.open on its own).
  desktop/pip-window.cjs            the PiP right-click menu: "LLM command..." after "Popups, 3JS and
                                    orchestra..." - openTools({id: 'module:PineLlmCommands'}).
  app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt
                                    "llm-commands.js" after speech-gates.js, "llm-commands.css" after
                                    speech-gates.css: the tablet's view bundle carries the module
                                    (the TOOLS tab lists PineLlmCommands once the global exists).
Copies (the module itself, from ../modules beside this tool, or $LLM_COMMANDS_MODULES):
  desktop/renderer/llm-commands.js, desktop/renderer/llm-commands.css
  app/src/main/assets/pine-views/llm-commands.js, app/src/main/assets/pine-views/llm-commands.css

Usage:  llm_commands_desk_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors or files missing
        llm_commands_desk_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

INDEX_CSS_OLD = '''  <link rel="stylesheet" href="./blocked-book.css">  <!-- [blocked-book] -->
'''
INDEX_CSS_NEW = '''  <link rel="stylesheet" href="./blocked-book.css">  <!-- [blocked-book] -->
  <link rel="stylesheet" href="./llm-commands.css">  <!-- [llm-command] the LLM command book -->
'''
INDEX_JS_OLD = '''  <script src="./blocked-book.js"></script>  <!-- [blocked-book] the second tab of The Works -->
'''
INDEX_JS_NEW = '''  <script src="./blocked-book.js"></script>  <!-- [blocked-book] the second tab of The Works -->
  <script src="./llm-commands.js"></script>  <!-- [llm-command] PineLlmCommands: the LLM command book popup -->
'''
MENU_OLD = '''      { label: 'Popups, 3JS and orchestra...', click: () => openTools ? openTools() : getWindow()?.webContents.send('pip:action','popups') },
'''
MENU_NEW = '''      { label: 'Popups, 3JS and orchestra...', click: () => openTools ? openTools() : getWindow()?.webContents.send('pip:action','popups') },
      { label: 'LLM command...', click: () => openTools ? openTools({ id: 'module:PineLlmCommands' }) : getWindow()?.webContents.send('pip:action', 'popups') },   /* [llm-command] the command book */
'''
KT_JS_OLD = '''        "speech-gates.js",      // [speech-gates] every gate on the station's speech (script view toolbar)
'''
KT_JS_NEW = '''        "speech-gates.js",      // [speech-gates] every gate on the station's speech (script view toolbar)
        "llm-commands.js",      // [llm-command] the LLM command book (PineLlmCommands.open / mount)
'''
KT_CSS_OLD = '''        "speech-gates.css",     // [speech-gates] the speech gates panel
'''
KT_CSS_NEW = '''        "speech-gates.css",     // [speech-gates] the speech gates panel
        "llm-commands.css",     // [llm-command] the command book
'''

EDITS = {
    "desktop/renderer/index.html": [
        ("index.html carries llm-commands.css", INDEX_CSS_OLD, INDEX_CSS_NEW, 1),
        ("index.html carries llm-commands.js", INDEX_JS_OLD, INDEX_JS_NEW, 1),
    ],
    "desktop/pip-window.cjs": [
        ("the PiP menu offers LLM command...", MENU_OLD, MENU_NEW, 1),
    ],
    "app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt": [
        ("the tablet's view bundle carries llm-commands.js", KT_JS_OLD, KT_JS_NEW, 1),
        ("the tablet's view bundle carries llm-commands.css", KT_CSS_OLD, KT_CSS_NEW, 1),
    ],
}

COPIES = [
    ("llm-commands.js", "desktop/renderer/llm-commands.js"),
    ("llm-commands.css", "desktop/renderer/llm-commands.css"),
    ("llm-commands.js", "app/src/main/assets/pine-views/llm-commands.js"),
    ("llm-commands.css", "app/src/main/assets/pine-views/llm-commands.css"),
]


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def modules_dir() -> Path:
    env = os.environ.get("LLM_COMMANDS_MODULES")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "modules"


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
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    copies = []
    src_dir = modules_dir()
    for src_name, dest_rel in COPIES:
        src = src_dir / src_name
        dest = root / dest_rel
        label = "copy %s -> %s" % (src_name, dest_rel)
        if not src.exists():
            print("%-78s MISSING (no module at %s)" % (label[:78], src))
            missing = True
            continue
        if not dest.parent.exists():
            print("%-78s MISSING (no folder %s)" % (label[:78], dest.parent))
            missing = True
            continue
        data = src.read_bytes()
        if dest.exists() and dest.read_bytes() == data:
            print("%-78s applied" % label[:78])
            continue
        print("%-78s ready" % label[:78])
        ready = True
        copies.append((dest, data))
    if missing:
        print("anchors or files missing - nothing applied")
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
    for dest, data in copies:
        tmp = dest.with_suffix(dest.suffix + ".llmcmd.tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        print("copied %s" % dest)
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
