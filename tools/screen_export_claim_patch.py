"""[screen-export-claim] the tablet saw every screen order and never claimed one.

2026-09-30, the operator: "when i tell the nabu to export the last 5 minutes
of pinetab. I mean the screen of the pinetab. it exported the pinecam."

Measured: "Export the last minute of Pine Tab." (07:11 CST) parsed as a
PineTab screen order, the tablet's panel saw it (screenExportSeen held the
id) - and no claim ever reached the station, no file was cut, nothing was
uploaded. What the operator found in PineBoxRecordings were the Pine Cam's
five-minute segments, which the desk carries there all day.

The cause: screenExportWatch called api(path, {id, device}) - the body-style
call of the small pages' api() - but the main panel's api(path, options) takes
FETCH OPTIONS. The claim went out as a bare GET to a POST-only route, the 405
threw, and the watcher returned silently; the done report had the same fault.

Also: the Nabu hears "PineTab" as "Pine Tap" ("Export the last minute of the
Pine Tap broadcast." became an audio cut at 06:47) - the screen words take
"tap" as well as "tab".

Usage (ON THE HOST): python3 tools/screen_export_claim_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[screen-export-claim]"

EDITS = [
    ("claim POST",
     '''  try { claim = await api("/api/export/screen/claim", {id: order.id, device: mine}); } catch (e) { return; }
''',
     '''  // [screen-export-claim] this page's api() takes fetch options, not a body
  try {
    claim = await api("/api/export/screen/claim", {method: "POST",
      body: JSON.stringify({id: order.id, device: mine})});
  } catch (e) { return; }
'''),
    ("done POST",
     '''    await api("/api/export/screen/done", {id: order.id, device: mine, ok: ok,
      result: got || {}, detail: why || (up && up.detail) || (got && got.detail) || ""});
''',
     '''    await api("/api/export/screen/done", {method: "POST", body: JSON.stringify({
      id: order.id, device: mine, ok: ok, result: got || {},
      detail: why || (up && up.detail) || (got && got.detail) || ""})});
'''),
    ("pine tap",
     '''    r"pine\\s*tab(?:let)?|pinetab|tablet|"
''',
     '''    r"pine\\s*ta[bp](?:let)?|pineta[bp]|tablet|"   # [screen-export-claim] "tap": the Nabu's ear
'''),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        assert n == 1, "%s: anchor found %d times" % (label, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-screen-export-claim")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
