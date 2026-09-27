"""System 3's window on the panel and the desk ([s3-window]).

- app.py: the panel's system3Open(tab) passes a starting tab to the served
  module (v=4), and the 3JS list carries a "Sys3" entry so pineShow3JS("sys3")
  opens the three.js view of System 3 and the systems it directs.
- desktop/renderer/renderer.js: the desk's 3JS rail lists Sys3 (it calls
  pineShow3JS in the control frame, so the panel entry does the opening).

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = {
    "app.py": [
        ("system3Open-takes-a-tab",
         'async function system3Open() {\n'
         '  if (system3View) return;\n'
         '  if (!document.getElementById("system3Style")) {\n'
         '    const style = document.createElement("link"); style.id = "system3Style"; style.rel = "stylesheet";\n'
         '    style.href = "/system3/system3.css?v=1"; document.head.append(style);\n'
         '  }\n'
         '  try {\n'
         '    const module = await import("/system3/system3.js?v=1");\n'
         '    system3View = await module.openSystem3({request: (path, options) => api(path, options),\n'
         '      onClose: () => { system3View = null; }});\n',
         'async function system3Open(tab) {                       /* [s3-window] tab: tables, segments, prompts, audit, sys3 */\n'
         '  if (system3View) return;\n'
         '  if (!document.getElementById("system3Style")) {\n'
         '    const style = document.createElement("link"); style.id = "system3Style"; style.rel = "stylesheet";\n'
         '    style.href = "/system3/system3.css?v=4"; document.head.append(style);\n'
         '  }\n'
         '  try {\n'
         '    const module = await import("/system3/system3.js?v=4");\n'
         '    system3View = await module.openSystem3({request: (path, options) => api(path, options),\n'
         '      tab: typeof tab === "string" ? tab : "",\n'
         '      onClose: () => { system3View = null; }});\n', 1),
        ("sys3-in-the-3js-list",
         'const PINE_3JS = [\n'
         '  /* [#1386] one word, followed back to what made the station say it. */\n',
         'const PINE_3JS = [\n'
         '  /* [s3-window] System 3 and the systems it directs, as a circuit: paper\n'
         '     airplanes fly each decision to its road; the line on air floats above it. */\n'
         '  {key: "sys3", label: "Sys3", open: () => system3Open("sys3")},\n'
         '  /* [#1386] one word, followed back to what made the station say it. */\n', 1),
    ],
    "renderer.js": [
        ("sys3-on-the-desk-rail",
         'const THREEJS_VIEWS = [\n',
         'const THREEJS_VIEWS = [\n'
         '  { key: "sys3", icon: "3", name: "Sys3", since: "2026-09-27",\n'
         '    systems: "three.min.js · /api/system3/events · /api/system3/now",\n'
         '    what: "System 3 and the systems it directs, live",\n'
         '    desc: "The conversation director in the middle, every road it runs around it and the rooms downstream - the writer, the recording room, the ledger, the air. Circuits carry packets; a paper airplane flies each recorded decision to its road as it lands; the line on air floats above the road speaking it. Tabs: tables, segments (the node editor), prompts, audit." },\n', 1),
    ],
}


def plan(name):
    return list(EDITS.get(Path(name).name, []))


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(name, text):
    applied, missing = 0, []
    for label, old, new, count in plan(name):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (label, state))
    return applied, missing


def apply(path):
    path = Path(path)
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    applied, missing = check(path.name, text)
    if applied == len(plan(path.name)):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for label, old, new, count in plan(path.name):
        if state_of(text, old, new, count) == "applied":
            continue
        text = text.replace(old, new)
    out = text.replace("\n", "\r\n") if crlf else text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(out.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    targets = [a for a in argv if not a.startswith("--")] or ["app.py", "desktop/renderer/renderer.js"]
    worst = 0
    for target in targets:
        if not plan(target):
            print(target, ": nothing planned for this file")
            worst = 1
            continue
        if "--apply" in argv:
            code = apply(target)
            print(target, {0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        else:
            text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
            applied, missing = check(target, text)
            if missing:
                for m in missing:
                    print("missing:", m)
                code = 1
            elif applied == len(plan(target)):
                print(target, "already applied")
                code = 2
            else:
                print(target, "ready")
                code = 0
        worst = code if code == 1 or worst == 1 else max(worst, code)
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
