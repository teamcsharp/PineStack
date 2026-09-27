"""Put System 3's Messenger and Technical views on the Script tab.

--check <script-page.js> <script-page.css>   exit 0 ready / 2 applied / 1 missing
--apply <script-page.js> <script-page.css>   idempotent, LF, atomic

The same two files ship in the tablet's APK (app/src/main/assets/pine-views/)
and in the desktop's runner mirror (desktop/renderer/).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCK = open(os.path.join(HERE, "system3_script_page_block.js"), encoding="utf-8").read()

JS = [
    ("s3-block",
     "  /* [#1387] ACROSS THE WHOLE BOTTOM.\n",
     BLOCK + "  /* [#1387] ACROSS THE WHOLE BOTTOM.\n"),
    ("s3-buttons",
     "    restore.appendChild(promptHistory);\n",
     "    restore.appendChild(promptHistory);\n"
     "    /* System 3: this pane cycles script -> technical -> messenger and\n"
     "       back (s3SetMode). The two stay on the toolbar even when every\n"
     "       band is open: .sp-band-always keeps the toolbar showing. */\n"
     "    s3Reset();\n"
     "    ['technical', 'messenger'].forEach(function (mode) {\n"
     "      var label = mode === 'technical'\n"
     "        ? 'Technical view: the System 3 RNG Rolodex behind these lines'\n"
     "        : 'Messenger view: this conversation as System 3 directed it';\n"
     "      var b = make('button', 'sp-band-reopen sp-band-always sp-s3-toggle');\n"
     "      b.type = 'button';\n"
     "      b.title = label;\n"
     "      b.setAttribute('aria-label', label);\n"
     "      b.setAttribute('aria-pressed', 'false');\n"
     "      b.innerHTML = folderIcon(mode === 'technical' ? 'm:casino' : 'c:chat', label)\n"
     "        || (mode === 'technical' ? 'T' : 'M');\n"
     "      b.addEventListener('click', function () { s3SetMode(mode); });\n"
     "      s3Buttons[mode] = b;\n"
     "      restore.appendChild(b);\n"
     "    });\n"),
    ("s3-pane",
     "    right.appendChild(script);\n",
     "    right.appendChild(script);\n"
     "    /* System 3's views, over the script in the script's own cell. */\n"
     "    var s3Pane = make('div', 'sp-s3');\n"
     "    s3Pane.id = 'spS3';\n"
     "    s3Pane.hidden = true;\n"
     "    right.appendChild(s3Pane);\n"),
    ("s3-toolbar-always",
     "      toolbar.hidden = !anyClosed;\n",
     "      toolbar.hidden = !anyClosed && !toolbar.querySelector('.sp-band-always');\n"),
    ("s3-tick",
     "    keepLitInView('tick');\n    playoutPoll();\n  }\n",
     "    keepLitInView('tick');\n    playoutPoll();\n"
     "    s3Tick(row ? String(row.id || '') : '', false);          /* System 3 */\n  }\n"),
]

CSS_OLD = ".sp-band-restore { display: flex; gap: 5px; min-height: 28px; min-width: 0; }\n"
CSS = [("s3-css", CSS_OLD, CSS_OLD + (
    "/* System 3's Messenger and Technical views sit in the script's own grid\n"
    "   cell, over it, so the script underneath keeps following the air. */\n"
    ".sp-right > #spScript { grid-row: 2; grid-column: 1; }\n"
    ".sp-s3 { grid-row: 2; grid-column: 1 / -1; z-index: 3; min-height: 0; overflow: hidden;\n"
    "  border: 1px solid var(--sp-line); border-radius: 10px; background: #0f171b; }\n"
    ".sp-s3[hidden] { display: none; }\n"
    ".sp-s3 > .sp-s3-host { height: 100%; }\n"
    ".sp-s3-toggle[aria-pressed=\"true\"] { border-color: var(--sp-on); color: var(--sp-on);\n"
    "  background: #16302a; }\n"))]


# An edit a given copy does not need: the tablet's build already keeps the
# band toolbar on screen permanently (Prompt History lives there).
SATISFIED = {"s3-toolbar-always": "      toolbar.hidden = false;\n"}


def _needed(text, name):
    return not (name in SATISFIED and SATISFIED[name] in text)


# The first version pinned only the script's ROW. With a row but no column,
# grid auto-placement moved the script into a new column BESIDE the System 3
# pane instead of under it (seen on the tablet, 2026-09-26). Pinning the
# column as well puts both in the one cell.
MIGRATE = [(".sp-right > #spScript { grid-row: 2; }\n",
            ".sp-right > #spScript { grid-row: 2; grid-column: 1; }\n")]


def _migrate(text):
    for old, new in MIGRATE:
        text = text.replace(old, new)
    return text


def _state(text, edits):
    applied, missing = 0, []
    for name, old, new in edits:
        if not _needed(text, name):
            applied += 1
        elif text.count(new) == 1 and (old not in new or text.count(old) == text.count(new)):
            applied += 1
        elif text.count(old) != 1:
            missing.append("%s (anchor found %d times)" % (name, text.count(old)))
    return applied, missing


def _apply(path, edits):
    raw = open(path, "rb").read().decode("utf-8")
    text = _migrate(raw.replace("\r\n", "\n"))
    for name, old, new in edits:
        if not _needed(text, name):
            continue
        if new in text and (old not in new or text.count(old) == text.count(new)):
            continue
        assert text.count(old) == 1, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    if text != raw:
        tmp = path + ".s3tmp"
        with open(tmp, "wb") as fh:
            fh.write(text.encode("utf-8"))
        os.replace(tmp, path)


if __name__ == "__main__":
    mode, js_path, css_path = sys.argv[1], sys.argv[2], sys.argv[3]
    js = open(js_path, "rb").read().decode("utf-8").replace("\r\n", "\n")
    css = _migrate(open(css_path, "rb").read().decode("utf-8").replace("\r\n", "\n"))
    a1, m1 = _state(js, JS)
    a2, m2 = _state(css, CSS)
    if mode == "--check":
        if a1 + a2 == len(JS) + len(CSS):
            print("APPLIED"); sys.exit(2)
        if m1 or m2:
            print("MISSING: " + "; ".join(m1 + m2)); sys.exit(1)
        print("READY"); sys.exit(0)
    if mode == "--apply":
        _apply(js_path, JS)
        _apply(css_path, CSS)
        print("applied")
