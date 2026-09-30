"""[export-progress] a progress bar across the top of the app while a screen export runs.

"if i tell the LLM 'export the last 5 minutes of pinetab' i want it to export the
last 5 minutes of my screen recording on the device Also show a progress bar of
the operation happening in the background at the top of the application during
export."

The station sees every stage of a screen export: the order (asked), the claim
(the device took it), the upload arriving byte by byte on PUT /api/export/upload
(its Content-Length is the whole), the courier row (owed) and its delivery (the
desk or the host placed it). export_progress() words that as one {stage, pct,
say} on /api/dj; the control panel paints a thin bar across the top of the app.

Usage (ON THE HOST): python3 tools/export_progress_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

EDITS = [
    ("progress helpers", '''def export_screen_public() -> dict[str, Any] | None:
''', '''# [export-progress] the upload as it arrives, by file name: {got, total, at}
_EXPORT_UPLOADS: dict[str, dict[str, Any]] = {}


def export_progress() -> dict[str, Any] | None:
    """[export-progress] the open screen export, stage by stage, for the bar
    across the top of the app - or None when there is nothing to show."""
    with _SCREEN_EXPORT_LOCK:
        row = dict(_SCREEN_EXPORT)
    if not row:
        return None
    now = time.time()
    name = str(row.get("name") or "")
    what = SCREEN_EXPORT_NAMES.get(row.get("target"), "the screen")
    mins = _screen_export_minutes(row.get("seconds") or 0)
    head = "Exporting the last %s of %s" % (mins, what)
    res = row.get("result") or {}
    up = _EXPORT_UPLOADS.get(name) or {}
    if row.get("done"):
        if not res.get("ok"):
            if now - float(row.get("at") or now) > 600:
                return None
            return {"stage": "failed", "pct": 100, "failed": True, "name": name,
                    "say": "%s did not finish: %s" % (head, res.get("detail") or "no reason given")}
        rows = []
        try:
            rows = [r for r in courier_read() if str(r.get("name") or "") == name]
        except Exception:  # noqa: BLE001
            rows = []
        placed = next((r for r in rows if r.get("state") != "pending"), None)
        if placed:
            at = float(placed.get("done_at") or placed.get("at") or now)
            if now - at > 20:
                return None
            by = "the host" if placed.get("carried_by") == "host" else "the desk"
            return {"stage": "placed", "pct": 100, "name": name,
                    "say": "%s - done, %s placed %s in %s" % (head, by, name,
                                                             export_desk_dir() or "data/exports")}
        if now - float(row.get("at") or now) > 900:
            return None
        return {"stage": "owed", "pct": 90, "name": name,
                "say": "%s - uploaded; carrying it to %s" % (head, export_desk_dir() or "data/exports")}
    if up and float(up.get("total") or 0) > 0:
        frac = min(1.0, float(up.get("got") or 0) / float(up["total"]))
        return {"stage": "uploading", "pct": int(45 + 40 * frac), "name": name,
                "say": "%s - uploading %d%%" % (head, int(100 * frac))}
    if row.get("claimed_by"):
        spent = now - float(row.get("claimed_at") or now)
        guess = max(8.0, float(row.get("seconds") or 60) * 0.08)   # a mux of N s takes about N/12 s here
        return {"stage": "cutting", "pct": int(15 + 30 * min(1.0, spent / guess)), "name": name,
                "say": "%s - %s is cutting it" % (head, "the tablet" if row.get("target") == "tab" else "the app")}
    if now - float(row.get("at") or now) > SCREEN_EXPORT_LIFE:
        return None
    return {"stage": "asked", "pct": 5, "name": name,
            "say": "%s - waiting for %s to pick it up" % (head, "the tablet" if row.get("target") == "tab" else "the app")}


def export_screen_public() -> dict[str, Any] | None:
''', 1),
    ("state", '''    base["screen_export"] = export_screen_public()
''', '''    base["screen_export"] = export_screen_public()
    base["export_progress"] = export_progress()              # [export-progress]
''', 1),
    ("upload counts", '''    wrote = 0
    try:
        with path.open("wb") as fh:
            async for chunk in request.stream():
                if chunk:
                    fh.write(chunk)
                    wrote += len(chunk)
''', '''    wrote = 0
    try:                                                     # [export-progress]
        _up_total = float(request.headers.get("content-length") or 0)
    except Exception:  # noqa: BLE001
        _up_total = 0.0
    _EXPORT_UPLOADS[safe] = {"got": 0, "total": _up_total, "at": time.time()}
    if len(_EXPORT_UPLOADS) > 20:
        for _k in sorted(_EXPORT_UPLOADS, key=lambda k: _EXPORT_UPLOADS[k]["at"])[:-20]:
            _EXPORT_UPLOADS.pop(_k, None)
    try:
        with path.open("wb") as fh:
            async for chunk in request.stream():
                if chunk:
                    fh.write(chunk)
                    wrote += len(chunk)
                    _EXPORT_UPLOADS[safe]["got"] = wrote
''', 1),
    ("panel poll", '''    try { screenExportWatch(state); } catch (e) { /* [screen-export] */ }
''', '''    try { screenExportWatch(state); } catch (e) { /* [screen-export] */ }
    try { exportProgressPaint(state.export_progress); } catch (e) { /* [export-progress] */ }
''', 1),
    ("panel bar", '''let screenExportSeen = "";
''', '''/* [export-progress] "show a progress bar of the operation happening in the
 * background at the top of the application during export": a thin bar across
 * the very top of the app with one line of words, from the station's own view
 * of the export (asked, cutting, uploading, owed, placed). */
function exportProgressPaint(p) {
  let bar = document.getElementById("pineExportBar");
  if (!p) { if (bar) bar.hidden = true; return; }
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "pineExportBar";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    bar.style.cssText = "position:fixed;left:0;right:0;top:0;height:18px;z-index:2147483200;"
      + "pointer-events:auto;background:rgba(10,14,18,.82);font:600 11px/18px system-ui,sans-serif;"
      + "color:#d8e0e6;overflow:hidden;";
    const fill = document.createElement("i");
    fill.id = "pineExportFill";
    fill.style.cssText = "position:absolute;left:0;top:0;bottom:0;width:0;background:rgba(84,209,139,.45);"
      + "transition:width .6s ease;";
    const say = document.createElement("span");
    say.id = "pineExportSay";
    say.style.cssText = "position:relative;padding:0 10px;white-space:nowrap;";
    bar.appendChild(fill);
    bar.appendChild(say);
    document.body.appendChild(bar);
  }
  bar.hidden = false;
  const pct = Math.max(0, Math.min(100, Number(p.pct) || 0));
  const fill = document.getElementById("pineExportFill");
  fill.style.width = pct + "%";
  fill.style.background = p.failed ? "rgba(255,95,95,.5)" : "rgba(84,209,139,.45)";
  document.getElementById("pineExportSay").textContent = String(p.say || "") + (p.failed ? "" : "  " + pct + "%");
  bar.title = String(p.say || "") + " - " + pct + "%";
  bar.setAttribute("aria-valuenow", String(pct));
  bar.setAttribute("aria-label", String(p.say || "export"));
}

let screenExportSeen = "";
''', 1),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if "[export-progress]" in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new, n in EDITS:
        got = out.count(old)
        assert got == n, "%s: anchor found %d times" % (label, got)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/app.py.bak-export-progress")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
