/* Desktop exports belong to the shell, which stays alive in every view and PiP.
 * Share the station feed; remote webviews never need export IPC access. */
(function (root) {
  'use strict';
  const document = root.document;
function exportProgressPaint(p) {
  let bar = document.getElementById("pineExportBar");
  if (p && !["app", "pip"].includes(p.target)) p = null;
  if (!p) { if (bar) bar.hidden = true; return; }
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "pineExportBar";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    bar.style.cssText = "position:fixed;left:0;right:0;top:0;height:18px;z-index:2147483647;"
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

  const pending = new Set();
  const finished = new Set();
  async function watch(order) {
    if (!order?.id || !['app', 'pip'].includes(order.target)
        || pending.has(order.id) || finished.has(order.id)) return;
    const desk = root.pineDesktop;
    if (!desk?.replayExport) return;
    pending.add(order.id);
    try {
      const claim = await desk.post('/api/export/screen/claim', { id: order.id, device: order.target });
      if (!claim?.go) { finished.add(order.id); return; }
      let result = {}, detail = '';
      try {
        result = await desk.replayExport({ seconds: claim.seconds, upload: true, name: claim.name,
          view: order.target, require_audio: true });
      } catch (error) { detail = String(error?.message || error); }
      const uploaded = result?.uploaded;
      const ok = !!(result && result.ok !== false && uploaded && uploaded.ok !== false);
      await desk.post('/api/export/screen/done', { id: order.id, device: order.target, ok,
        result: result || {}, detail: detail || uploaded?.detail || result?.detail || '' });
      finished.add(order.id);
    } catch (error) { console.error('[screen-export]', error); }
    finally { pending.delete(order.id); }
  }
  root.PineStationFeed.subscribe(payload => {
    if (!['poll', 'join'].includes(payload.kind) || !payload.station) return;
    exportProgressPaint(payload.station.export_progress);
    watch(payload.station.screen_export);
  });
})(window);
