"""A topic in the bank is edited where it stands: double-click or hold it.

Operator, 2026-09-27: "allow me to double click or long press to edit the
topic inline editing the entry."

The entry becomes its own two-line box in place. Ctrl/Cmd+Enter or Save
keeps it (POST /api/dj/topics/{id}/edit - tools/topic_edit_patch.py - which
splits "1. / 2." as a new topic is split); Escape or Cancel puts it back.
A single tap still puts the topic in the box at the top, as it always did;
the tap that ends a hold does not.

Needs tools/topic_box_patch.py first (the anchor is its bank row). Both
repo copies are patched here - desktop/renderer and the repo's pine-views;
the kiosk's own copy is patched by pointing COPIES at it. Idempotent:
--check exits 0 when every edit can apply, 2 when already applied, 1 when
an anchor is missing; --apply writes the files.
"""
import sys
from pathlib import Path

COPIES = ["desktop/renderer", "app/src/main/assets/pine-views"]

JS = [
    ("        words.addEventListener('click', function () {\n"
     "          input.value = said;\n"
     "          input.focus();\n"
     "        });\n",
     "        var heldAt = 0;\n"
     "        words.addEventListener('click', function () {\n"
     "          if (Date.now() - heldAt < 700) return;   /* [topic-edit] the hold answered */\n"
     "          input.value = said;\n"
     "          input.focus();\n"
     "        });\n"
     "        /* [topic-edit] DOUBLE-CLICK OR HOLD IT TO EDIT IT WHERE IT STANDS.\n"
     "           The entry becomes its own two-line box: Ctrl/Cmd+Enter or Save\n"
     "           keeps it (POST /api/dj/topics/{id}/edit, split into topic and\n"
     "           reply as a new one is), Escape or Cancel puts it back. */\n"
     "        function editInline() {\n"
     "          if (item.classList.contains('editing')) return;\n"
     "          item.classList.add('editing');\n"
     "          var box = el('textarea', 'pseg-topic-in pseg-topic-edit');\n"
     "          box.rows = 2;\n"
     "          box.value = said;\n"
     "          box.setAttribute('aria-label', 'Edit this topic');\n"
     "          var keepIt = el('button', 'pseg-topic-save', 'Save');\n"
     "          keepIt.type = 'button';\n"
     "          var drop = el('button', 'pseg-topic-cancel', 'Cancel');\n"
     "          drop.type = 'button';\n"
     "          var bar = el('div', 'pseg-topic-editbar');\n"
     "          bar.appendChild(keepIt);\n"
     "          bar.appendChild(drop);\n"
     "          var form = el('div', 'pseg-topic-editor');\n"
     "          form.appendChild(box);\n"
     "          form.appendChild(bar);\n"
     "          item.replaceChild(form, words);\n"
     "          function done() {\n"
     "            item.classList.remove('editing');\n"
     "            if (form.parentNode === item) item.replaceChild(words, form);\n"
     "          }\n"
     "          function keep() {\n"
     "            var text = String(box.value || '').trim();\n"
     "            if (!text) { note(wrap, 'an empty topic cannot be saved'); return; }\n"
     "            if (text === said) { done(); return; }\n"
     "            keepIt.disabled = true;\n"
     "            send('POST', '/api/dj/topics/' + encodeURIComponent(saved.id) + '/edit', {text: text})\n"
     "              .then(function (got) {\n"
     "                keepIt.disabled = false;\n"
     "                if (!got) { note(wrap, 'the station refused the edit'); return; }\n"
     "                note(wrap, got.requeued ? 'saved - the queued copy says it now too' : 'saved');\n"
     "                loadHistory();\n"
     "              })['catch'](function (err) {\n"
     "                keepIt.disabled = false;\n"
     "                note(wrap, 'not saved - ' + String((err && err.message) || 'the station did not answer'));\n"
     "              });\n"
     "          }\n"
     "          keepIt.addEventListener('click', function (ev) { ev.stopPropagation(); keep(); });\n"
     "          drop.addEventListener('click', function (ev) { ev.stopPropagation(); done(); });\n"
     "          box.addEventListener('keydown', function (ev) {\n"
     "            if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); done(); }\n"
     "            else if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); keep(); }\n"
     "          });\n"
     "          box.focus();\n"
     "          try { box.setSelectionRange(box.value.length, box.value.length); } catch (err) { /* older views */ }\n"
     "        }\n"
     "        words.addEventListener('dblclick', function (ev) { ev.preventDefault(); editInline(); });\n"
     "        var hold = 0, holdX = 0, holdY = 0;\n"
     "        var unhold = function () { root.clearTimeout(hold); hold = 0; };\n"
     "        words.addEventListener('pointerdown', function (ev) {\n"
     "          if (ev.button) return;\n"
     "          unhold();\n"
     "          holdX = ev.clientX; holdY = ev.clientY;\n"
     "          hold = root.setTimeout(function () { hold = 0; heldAt = Date.now(); editInline(); }, 520);\n"
     "        });\n"
     "        words.addEventListener('pointermove', function (ev) {\n"
     "          if (hold && Math.abs(ev.clientX - holdX) + Math.abs(ev.clientY - holdY) > 12) unhold();\n"
     "        });\n"
     "        ['pointerup', 'pointercancel', 'pointerleave'].forEach(function (name) {\n"
     "          words.addEventListener(name, unhold);\n"
     "        });\n"
     "        /* the WebView's own long-press (and the desk's right-click) */\n"
     "        words.addEventListener('contextmenu', function (ev) {\n"
     "          ev.preventDefault();\n"
     "          unhold();\n"
     "          heldAt = Date.now();\n"
     "          editInline();\n"
     "        });\n"),
]

CSS_ADD = """
/* [topic-edit] a bank entry edited where it stands */
.pseg-topic-words { -webkit-user-select: none; user-select: none; -webkit-touch-callout: none; }
.pseg-topic-editor { display: grid; gap: 5px; min-width: 0; }
.pseg-topic-editbar { display: flex; gap: 6px; }
.pseg-topic-save, .pseg-topic-cancel { font-size: 11px; padding: 4px 12px; border-radius: 5px; border: 1px solid #2a4257;
  background: #12202e; color: #dbe6f0; cursor: pointer; }
.pseg-topic-save { border-color: #8cd4c0; color: #8cd4c0; }
.pseg-topic-save:disabled { opacity: .5; }
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
        if ".pseg-topic-editor" not in css:
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
