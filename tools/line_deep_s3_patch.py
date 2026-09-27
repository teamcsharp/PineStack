"""The line inspector ("How this line came to be") gets System 3's section.

Operator, 2026-09-27: "In this window also do a section for system three
showing how the R N G system constructed this line and how it resulted in
the system prompt that resulted in this particular dialogue coming together.
So I want to see the roller deck, I want to see the R and G system, I wanna
see everything involved with system three and how this line came to be
whenever I go into the examine this element window."

System 3's own module draws the section (frontend/system3.js
mountLineStory, served by the station), so it changes with System 3 and
not with this file or the APK. This file only makes room for it, right
under the step-by-step broadcast stepper, and hands it the line and the
prompt the inspector already fetched from /api/dj/provenance.

Both repo copies are patched - desktop/renderer and the repo's pine-views;
the kiosk's own copy is patched by pointing COPIES at it (line endings are
kept). Idempotent: --check exits 0 when every edit can apply, 2 when
already applied, 1 when an anchor is missing; --apply writes the files.
"""
import sys
from pathlib import Path

COPIES = ["desktop/renderer", "app/src/main/assets/pine-views"]

JS = [
    ("    section(body, 'how this line came to be broadcast, step by step', flowNode(line, all));\n",
     "    section(body, 'how this line came to be broadcast, step by step', flowNode(line, all));\n"
     "    section(body, 'System 3 - how the dice built this line', s3Story(line, all));   /* [s3-story] */\n"),
    ("  /* ---------------------------------------------------------- the stepper */\n",
     "  /* [s3-story] SYSTEM 3'S PART OF THE STORY, drawn by System 3 itself: the\n"
     "   * station serves frontend/system3.js, whose mountLineStory rolls the\n"
     "   * line's dice again and shows the running-order row it wrote and where\n"
     "   * that row sits in the prompt (the provenance fetched above). */\n"
     "  var s3Load = null;\n"
     "  function s3Url(name) {\n"
     "    try {\n"
     "      if (/^https?:$/.test(location.protocol) && location.origin && location.origin !== 'null') {\n"
     "        return location.origin + name;\n"
     "      }\n"
     "    } catch (err) { /* no location worth having */ }\n"
     "    try {\n"
     "      if (root.pineThreeUrl) return String(root.pineThreeUrl()).replace(/\\/vendor\\/three\\.min\\.js.*$/, '') + name;\n"
     "    } catch (err) { /* older shell */ }\n"
     "    return 'http://127.0.0.1:8096' + name;\n"
     "  }\n"
     "  function s3Story(line, all) {\n"
     "    var node = make('div', 'ld-s3', 'Reading System 3...');\n"
     "    if (!document.querySelector('link[data-pine-s3]')) {\n"
     "      var link = document.createElement('link');\n"
     "      link.rel = 'stylesheet';\n"
     "      link.href = s3Url('/system3/system3.css?v=3');\n"
     "      link.setAttribute('data-pine-s3', '');\n"
     "      document.head.appendChild(link);\n"
     "    }\n"
     "    var prov = (all && all.prov) || {};\n"
     "    var prompt = String(((prov.written || {}).prompt) || prov.prompt || '');\n"
     "    (s3Load = s3Load || import(s3Url('/system3/system3.js?v=3'))).then(function (mod) {\n"
     "      if (!node.isConnected) return null;\n"
     "      return mod.mountLineStory(node, {request: function (path) { return api().get(path); },\n"
     "        lineId: String((line && line.id) || ''), prompt: prompt});\n"
     "    })['catch'](function (err) {\n"
     "      s3Load = null;\n"
     "      node.textContent = 'System 3 could not be read here: ' + String((err && err.message) || err);\n"
     "    });\n"
     "    return node;\n"
     "  }\n"
     "\n"
     "  /* ---------------------------------------------------------- the stepper */\n"),
]


def main(argv):
    apply = "--apply" in argv
    writes, todo = {}, 0
    for base in COPIES:
        path = Path(base) / "line-deep.js"
        raw = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw[:4000]
        text = raw.replace("\r\n", "\n")
        for old, new in JS:
            if new in text:
                continue
            if text.count(old) != 1:
                print("MISSING (%d) in %s: %r" % (text.count(old), path, old[:70]))
                return 1
            text = text.replace(old, new)
            todo += 1
        writes[path] = (text, crlf)
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for path, (text, crlf) in writes.items():
        path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
