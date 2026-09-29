#!/usr/bin/env python3
"""[s3-grip-drag] System 3 Tables: only the grip drags a row.

The item row in the Tables editor was draggable as a whole, so a click-drag
inside its text box (to select words) started a row move instead. The row is
now draggable only while the pointer went down on its grip; anywhere else the
text boxes select normally.

--check  exit 0 ready, 2 already applied, 1 anchor missing
--apply  apply (same exit codes)
"""
import sys
from pathlib import Path

MARK = "[s3-grip-drag]"
REL = "frontend/system3.js"
EDITS = [
    ("const wrap = el('div', {class: 's3-item-row', draggable: true,\n"
     "          ondragstart: e => { tableDrag = {cat, item};",
     "const wrap = el('div', {class: 's3-item-row', draggable: false,   /* [s3-grip-drag] only the grip arms the drag */\n"
     "          ondragstart: e => { if (!wrap.draggable) { e.preventDefault(); return; } tableDrag = {cat, item};"),
    ("          ondragend: () => { wrap.classList.remove('s3-dragging'); tableDrag = null; },\n"
     "          ondragover: e => { if (tableDrag && tableDrag.cat === cat",
     "          ondragend: () => { wrap.classList.remove('s3-dragging'); wrap.draggable = false; tableDrag = null; },\n"
     "          ondragover: e => { if (tableDrag && tableDrag.cat === cat"),
    ("          el('span', {class: 's3-grip', title: 'drag to reorder', text: '\\u22ee\\u22ee'}), row,",
     "          el('span', {class: 's3-grip', title: 'drag to reorder', text: '\\u22ee\\u22ee',\n"
     "            onpointerdown: () => { wrap.draggable = true; }, onpointerup: () => { wrap.draggable = false; }}), row,"),
]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    root = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    p = root / REL
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if MARK in text:
        print(f"{MARK} already applied"); return 2
    for old, _ in EDITS:
        if text.count(old) != 1:
            print(f"{MARK} anchor missing or not unique ({text.count(old)}): {old[:70]!r}"); return 1
    if mode != "--apply":
        print(f"{MARK} ready"); return 0
    for old, new in EDITS:
        text = text.replace(old, new, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))
    print(f"{MARK} applied to {REL}"); return 2


if __name__ == "__main__":
    sys.exit(main())
