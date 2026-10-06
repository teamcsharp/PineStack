"""Narrow, checked wiring for the station's existing troubleshooting console.

The default invocation validates without changing app.py. Pass --apply only
after the backend has been merged. Existing manual console controls remain.
"""
from __future__ import annotations

import argparse
import pathlib
import re


MARKER = "/* --- Station troubleshooting jobs: live progress and dialogue recovery --- */"

JAVASCRIPT = r'''
/* --- Station troubleshooting jobs: live progress and dialogue recovery --- */
let wedgeTroubleshootId = "";
let wedgeTroubleshootBusy = false;
let wedgeTroubleshootStarting = null;
let wedgeTroubleshootTimer = null;
let wedgeTroubleshootSeen = 0;
let wedgeTroubleshootNotice = "";
let wedgeTroubleshootAllowRestarts = true;
const WEDGE_JOB_MARK = "pineStationTroubleshootJob";

function wedgeTroubleshootStore() {
  try {
    if (wedgeTroubleshootId && wedgeTroubleshootBusy) {
      sessionStorage.setItem(WEDGE_JOB_MARK, wedgeTroubleshootId);
    } else {
      sessionStorage.removeItem(WEDGE_JOB_MARK);
    }
  } catch (e) {}
}

function wedgeTroubleshootButtons() {
  document.querySelectorAll(".pb-station-troubleshoot").forEach(button => {
    button.disabled = !!wedgeTroubleshootStarting;
    button.textContent = wedgeTroubleshootBusy
      ? "Show troubleshooting progress" : "Troubleshoot station";
  });
  document.querySelectorAll(".pb-station-restarts").forEach(input => {
    input.disabled = wedgeTroubleshootBusy;
  });
}

function wedgeTroubleshootLine(value) {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return String(value || "");
  return String(value.message || value.line || value.text || value.say || "");
}

function wedgeTroubleshootRetry(at) {
  if (!at) return "";
  const date = typeof at === "number"
    ? new Date(at < 100000000000 ? at * 1000 : at) : new Date(at);
  return Number.isNaN(date.getTime()) || date.getTime() <= Date.now()
    ? "" : date.toLocaleTimeString();
}

function wedgeTroubleshootPaint(job) {
  const lines = Array.isArray(job.transcript) ? job.transcript : [];
  if (lines.length < wedgeTroubleshootSeen) wedgeTroubleshootSeen = 0;
  lines.slice(wedgeTroubleshootSeen).forEach(line => {
    const text = wedgeTroubleshootLine(line);
    if (text) wedgeLines.push(text);
  });
  wedgeTroubleshootSeen = lines.length;
  const status = String(job.status || "running").toLowerCase();
  const terminal = job.running === false || ["succeeded", "completed", "complete", "success", "failed",
                    "error", "blocked", "cancelled", "canceled", "idle"].includes(status);
  const recovery = job.recovery && typeof job.recovery === "object" ? job.recovery : {};
  const observed = job.observation && typeof job.observation === "object" ? job.observation : {};
  const retry = wedgeTroubleshootRetry(job.next_retry_at || recovery.next_retry_at
                                      || recovery.cooldown_until || observed.next_retry_at);
  let notice = String(job.summary || job.report || "");
  if (!notice && status === "cooldown") notice = "Dialogue is waiting before a fresh retry.";
  if (!notice && status === "queued") notice = "Station troubleshooting is queued.";
  if (!notice && terminal) notice = "Troubleshooting finished. Read the results above.";
  if (retry && !["success", "succeeded", "completed", "complete"].includes(status)) {
    notice += (notice ? " " : "") + "Next retry: " + retry + ".";
  }
  if (notice && notice !== wedgeTroubleshootNotice) {
    wedgeLines.push(notice);
    wedgeTroubleshootNotice = notice;
  }
  const say = wedgeConsole && wedgeConsole.querySelector(".pb-station-troubleshoot-status");
  if (say) say.textContent = notice || "Checking the station and working through repairs.";
  wedgeTroubleshootBusy = !terminal;
  wedgeTroubleshootStore();
  if (wedgeLines.length > 400) wedgeLines = wedgeLines.slice(-400);
  wedgeTermPaint();
  wedgeTroubleshootButtons();
}

function wedgeTroubleshootSchedule(delay) {
  if (wedgeTroubleshootTimer !== null) clearTimeout(wedgeTroubleshootTimer);
  wedgeTroubleshootTimer = setTimeout(wedgeTroubleshootPoll, delay);
}

async function wedgeTroubleshootPoll() {
  wedgeTroubleshootTimer = null;
  if (!wedgeTroubleshootId || !wedgeTroubleshootBusy) return;
  try {
    const job = await api("/api/station/troubleshoot/" + encodeURIComponent(wedgeTroubleshootId));
    wedgeTroubleshootPaint(job);
    if (wedgeTroubleshootBusy) {
      wedgeTroubleshootSchedule(job.status === "cooldown" ? 5000 : 2000);
    }
  } catch (e) {
    const error = String(e.message || e);
    if (/not found|unknown troubleshooting job|expired|unauthorized|forbidden/i.test(error)) {
      wedgeTroubleshootBusy = false;
      wedgeTroubleshootStore();
      wedgeLines.push("Troubleshooting progress is unavailable: " + error
        + ". Click Troubleshoot station to try again.");
      wedgeTermPaint();
      wedgeTroubleshootButtons();
      return;
    }
    const notice = "The station is reconnecting. Waiting for troubleshooting progress: "
      + error;
    if (notice !== wedgeTroubleshootNotice) {
      wedgeLines.push(notice);
      wedgeTroubleshootNotice = notice;
      wedgeTermPaint();
    }
    // An affected service may restart; keep the same job rather than submit it again.
    wedgeTroubleshootSchedule(5000);
  }
}

function wedgeTroubleshootLocalPlayback() {
  // Browser permission belongs to this click: request playback before any fetch.
  // Resume existing audio contexts without changing levels, mute, or routing.
  const contexts = new Set();
  try {
    if (typeof gains !== "undefined") {
      Object.values(gains || {}).forEach(entry => { if (entry && entry.context) contexts.add(entry.context); });
    }
    contexts.add(window.pineAudioCtx);
    contexts.add(window.__pineAudioCtx);
    contexts.forEach(context => {
      if (!context || context.state !== "suspended" || !context.resume) return;
      const resumed = context.resume();
      if (resumed && resumed.catch) resumed.catch(() => {});
    });
  } catch (e) {}
  // An intentional pause or cache listening session keeps its existing hold.
  if ((typeof pineAirPaused !== "undefined" && pineAirPaused) || window.cacheHold) return;
  try {
    const unlock = document.getElementById("pineAudioUnlock");
    if (unlock && typeof unlock.click === "function") unlock.click();
  } catch (e) {}
  try {
    if (typeof djVoiceEls !== "undefined" && typeof playOrPrompt === "function") {
      djVoiceEls.forEach(player => {
        // A warmed future clip must keep its schedule; only resume accepted speech.
        if (player && player.pineDeliveryClip && player.src && player.paused
            && !player.ended && !player.muted && Number(player.volume) > 0) {
          playOrPrompt(player);
        }
      });
    }
  } catch (e) {}
  try { if (typeof djVoiceUnstick === "function") djVoiceUnstick(); } catch (e) {}
}

function wedgeTroubleshootStart() {
  wedgeTroubleshootLocalPlayback();
  if (!wedgeConsole) wedgeConsoleOpen();
  if (wedgeTroubleshootStarting) return wedgeTroubleshootStarting;
  if (wedgeTroubleshootBusy && wedgeTroubleshootId) {
    wedgeTroubleshootSchedule(0);
    return Promise.resolve();
  }
  wedgeTroubleshootBusy = true;
  wedgeTroubleshootSeen = 0;
  wedgeTroubleshootNotice = "";
  wedgeLines.push("", "Checking the station and recovering stuck dialogue...");
  wedgeTermPaint();
  wedgeTroubleshootStarting = (async () => {
    try {
      const job = await api("/api/station/troubleshoot", {
        method: "POST", body: JSON.stringify({fix: true,
          allow_restarts: wedgeTroubleshootAllowRestarts})
      });
      if (!job || !job.id) throw new Error("The station did not return a troubleshooting job.");
      wedgeTroubleshootId = String(job.id);
      wedgeTroubleshootPaint(job);
      if (wedgeTroubleshootBusy) wedgeTroubleshootSchedule(1500);
      return job;
    } catch (e) {
      wedgeTroubleshootBusy = false;
      wedgeTroubleshootStore();
      wedgeLines.push("Could not start troubleshooting: " + String(e.message || e));
      wedgeTermPaint();
    } finally {
      wedgeTroubleshootStarting = null;
      wedgeTroubleshootButtons();
    }
  })();
  wedgeTroubleshootButtons();
  return wedgeTroubleshootStarting;
}

function wedgeTroubleshootControls(box) {
  const actions = el("div", "", "");
  actions.style.cssText = "padding:10px 12px;border-bottom:1px solid #2a1f18;"
    + "display:flex;align-items:center;flex-wrap:wrap;gap:10px";
  const go = el("button", "pb-station-troubleshoot", "Troubleshoot station");
  go.style.cssText = "padding:10px 14px;border-radius:8px;border:none;cursor:pointer;"
    + "background:#ff9d4d;color:#160d05;font-weight:700";
  go.onclick = wedgeTroubleshootStart;
  actions.appendChild(go);
  const label = el("label", "", "");
  label.style.cssText = "font-size:11px;display:flex;align-items:center;gap:6px";
  const restarts = el("input", "pb-station-restarts", "");
  restarts.type = "checkbox";
  restarts.checked = wedgeTroubleshootAllowRestarts;
  restarts.onchange = () => { wedgeTroubleshootAllowRestarts = !!restarts.checked; };
  label.appendChild(restarts);
  label.appendChild(el("span", "", "Restart affected services if needed"));
  actions.appendChild(label);
  const note = el("div", "pb-station-troubleshoot-status muted",
    "Checks playback, repairs dialogue and tries fresh variations when needed.");
  note.style.cssText = "width:100%;font-size:11px;line-height:1.5";
  actions.appendChild(note);
  box.appendChild(actions);
  wedgeTroubleshootButtons();
}

// Keep tracking the existing job through a panel reload without starting another.
try {
  wedgeTroubleshootId = sessionStorage.getItem(WEDGE_JOB_MARK) || "";
  if (wedgeTroubleshootId) {
    wedgeTroubleshootBusy = true;
    wedgeTroubleshootSchedule(1500);
  }
} catch (e) {}
'''


def _one_replace(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected one UI anchor, found {count}: {old[:100]}")
    return source.replace(old, new, 1)


def patch_app(source: str) -> str:
    if MARKER in source:
        return source
    newline = "\r\n" if source.count("\r\n") > source.count("\n") / 2 else "\n"
    source = _one_replace(source, "async function wedgeConsoleOpen() {",
                          JAVASCRIPT.strip().replace("\n", newline)
                          + newline + newline + "async function wedgeConsoleOpen() {")
    # The existing menu is available even when music is playing and only DJs are quiet.
    pattern = r'(^\s*\{key: "wedge",\s*label: )"[^"\r\n]*"(,\s*open: \(\) => )wedgeConsoleOpen\(\)'
    source, count = re.subn(pattern, r'\1"Troubleshoot station"\2wedgeTroubleshootStart()',
                            source, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"Expected one station menu entry, found {count}")
    source = _one_replace(source,
                          "more.onclick = () => { wedgeCardHide(); wedgeConsoleOpen(); };",
                          "more.textContent = \"Troubleshoot station\";" + newline
                          + "  more.onclick = () => { wedgeCardHide(); wedgeTroubleshootStart(); };")
    source = _one_replace(source, "dot.onclick = wedgeConsoleOpen;",
                          "dot.onclick = wedgeTroubleshootStart;")
    start = source.index("async function wedgeConsoleOpen() {")
    end = source.index("/* The icon itself.", start)
    console = source[start:end]
    console = _one_replace(console, 'const title = el("b", "", "Broadcast troubleshooting");',
                           'const title = el("b", "", "Station troubleshooting");')
    console = _one_replace(console, "  box.appendChild(head);",
                           "  box.appendChild(head);" + newline
                           + "  wedgeTroubleshootControls(box);")
    console = _one_replace(console, "  wedgeConsole = shade;",
                           "  wedgeConsole = shade;" + newline
                           + "  wedgeTroubleshootButtons();")
    return source[:start] + console + source[end:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", nargs="?", type=pathlib.Path,
                        default=pathlib.Path(__file__).with_name("app.py"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    original = args.app.read_bytes()
    patched = patch_app(original.decode("utf-8")).encode("utf-8")
    if args.apply and patched != original:
        args.app.write_bytes(patched)
    print("UI patch applied" if args.apply else "UI patch validated; app.py unchanged")


if __name__ == "__main__":
    main()
