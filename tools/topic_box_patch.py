"""The topic desk's box is two lines, and a "1. / 2." exchange reads as one.

Operator, 2026-09-27: "make the topic entry window 2 lines instead of one.
Also allow me to use 1 and 2 number with topics to set a topic and a
response that is offered to the next conversational line for guidance (as
the line). I want to be able to type 1. This is my studio 2. Thats what
you think and that is an exchange that is used in the dialogue in the
studio when that topic is used."

The station half is tools/topic_exchange_patch.py: POST /api/dj/topics
splits "1. ... 2. ..." into the topic and its reply, and the round opens on
that exchange word for word. This is the box: a two-line textarea (Enter
starts the next line; Ctrl/Cmd+Enter or the button sends), a placeholder
that shows the shape, and a bank row that reads - and refills - as the
exchange it is.

Both copies are patched - desktop/renderer and the kiosk's pine-views.
Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing; --apply writes the files.
"""
import sys
from pathlib import Path

COPIES = ["desktop/renderer", "app/src/main/assets/pine-views"]

JS = [
    ("    var input = el('input', 'pseg-topic-in');\n"
     "    input.type = 'text';\n"
     "    input.placeholder = next ? 'Describe the scenario...' : 'Something for them to get into...';\n",
     "    /* [topic-exchange] Two lines. \"1. This is my studio 2. Thats what you\n"
     "       think\" is an exchange: line 1 opens the round word for word and\n"
     "       line 2 is the reply to it, word for word (the station splits it -\n"
     "       POST /api/dj/topics). Enter starts the next line; Ctrl/Cmd+Enter,\n"
     "       or the button, sends it. */\n"
     "    var input = el('textarea', 'pseg-topic-in');\n"
     "    input.rows = 2;\n"
     "    input.placeholder = (next ? 'Describe the scenario...' : 'Something for them to get into...')\n"
     "      + '\\n1. the opening line  2. the reply - each said word for word';\n"),
    ("      if (ev && ev.key === 'Enter') { ev.preventDefault(); add(); }\n",
     "      if (ev && ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); add(); }\n"),
    ("        var words = el('button', 'pseg-topic-words', saved.text || 'Untitled scenario');\n"
     "        words.type = 'button';\n"
     "        words.title = 'Put this scenario in the editor';\n"
     "        words.addEventListener('click', function () {\n"
     "          input.value = String(saved.text || '');\n"
     "          input.focus();\n"
     "        });\n",
     "        /* [topic-exchange] an exchange reads, and refills, as its two lines */\n"
     "        var said = saved.reply\n"
     "          ? '1. ' + String(saved.text || '') + '\\n2. ' + String(saved.reply)\n"
     "          : String(saved.text || '');\n"
     "        var words = el('button', 'pseg-topic-words', said || 'Untitled scenario');\n"
     "        words.type = 'button';\n"
     "        words.title = 'Put this scenario in the editor';\n"
     "        words.addEventListener('click', function () {\n"
     "          input.value = said;\n"
     "          input.focus();\n"
     "        });\n"),
]

CSS_ADD = """
/* [topic-exchange] the box is two lines; an exchange in the bank reads as two */
textarea.pseg-topic-in { resize: vertical; min-height: 44px; }
.pseg-topic-words { white-space: pre-line; }
"""


def main(argv):
    apply = "--apply" in argv
    writes, todo = {}, 0
    for base in COPIES:
        js_path = Path(base) / "pine-segments.js"
        text = js_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        for old, new in JS:
            if new in text:
                continue
            if text.count(old) != 1:
                print("MISSING (%d) in %s: %r" % (text.count(old), js_path, old[:70]))
                return 1
            text = text.replace(old, new)
            todo += 1
        writes[js_path] = text
        css_path = Path(base) / "pine-segments.css"
        css = css_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if "textarea.pseg-topic-in" not in css:
            css = css.rstrip("\n") + "\n" + CSS_ADD
            todo += 1
        writes[css_path] = css
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for path, text in writes.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
