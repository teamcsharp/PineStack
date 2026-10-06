"""Station panel recovery contract, exercised with a browser-like JS harness."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from ui_troubleshoot_patch import JAVASCRIPT, MARKER, patch_app


HARNESS = r'''
const vm = require("node:vm");
const assert = require("node:assert/strict");
const timers = new Map();
const storage = new Map();
const calls = [];
const buttons = [];
const checks = [];
let serial = 0;
let failStart = false;
let pollError = null;
let job = {id: "job-1", status: "queued", transcript: ["Checking dialogue."],
           summary: "Troubleshooting is queued."};
const document = {querySelectorAll: selector => selector === ".pb-station-troubleshoot"
  ? buttons : selector === ".pb-station-restarts" ? checks : []};
function el(tag, className, textContent) {
  const out = {tag, className, textContent, style: {}, children: [],
    appendChild(child) {this.children.push(child);},
    querySelector() {return null;}};
  if (className === "pb-station-troubleshoot") buttons.push(out);
  if (className === "pb-station-restarts") checks.push(out);
  return out;
}
const context = vm.createContext({document, el, console, Date, Promise, JSON,
  window: {},
  setTimeout(fn, ms) {const id = ++serial; timers.set(id, {fn, ms}); return id;},
  clearTimeout(id) {timers.delete(id);},
  sessionStorage: {getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
  async api(path, options = {}) {
    calls.push({path, options});
    if (options.method === "POST" && failStart) throw new Error("Recorder unavailable");
    if (!options.method && pollError) throw new Error(pollError);
    return structuredClone(job);
  },
  fixUngag: () => ["Reconnected this page's DJ feed."],
  wedgeTermPaint() {},
  wedgeConsoleOpen() {context.wedgeConsole = {querySelector() {return null;}};}
});
context.wedgeConsole = null;
context.wedgeLines = [];
const evaluate = code => vm.runInContext(code, context);
'''


def run_js(body: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    source = (HARNESS + "\nvm.runInContext(" + json.dumps(JAVASCRIPT)
              + ", context);\n(async () => {\n" + body
              + "\n})().catch(e => {console.error(e); process.exitCode = 1;});")
    result = subprocess.run([node, "-"], input=source, text=True,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_console_is_reused_and_manual_steps_remain() -> None:
    source = '''before untouched
  {key: "wedge", label: "Broadcast Fixer", open: () => wedgeConsoleOpen(),
more.onclick = () => { wedgeCardHide(); wedgeConsoleOpen(); };
async function wedgeConsoleOpen() {
  const title = el("b", "", "Broadcast troubleshooting");
  box.appendChild(head);
  wedgeConsole = shade;
  card.onclick = () => wedgeRun(String(row.key), name);
}
/* The icon itself. */
dot.onclick = wedgeConsoleOpen;
after untouched
'''
    changed = patch_app(source)
    assert changed.startswith("before untouched\n")
    assert changed.endswith("after untouched\n")
    assert 'label: "Troubleshoot station", open: () => wedgeTroubleshootStart()' in changed
    assert "card.onclick = () => wedgeRun(String(row.key), name);" in changed
    assert "wedgeTroubleshootControls(box);" in changed
    assert patch_app(changed) == changed
    assert changed.count(MARKER) == 1


def test_patch_refuses_missing_anchor_before_any_write() -> None:
    with pytest.raises(ValueError, match="UI anchor"):
        patch_app("Unrelated project.")


def test_repeated_clicks_share_job_and_authorize_diagnosed_restarts() -> None:
    run_js(r'''
await Promise.all([evaluate("wedgeTroubleshootStart()"), evaluate("wedgeTroubleshootStart()")]);
assert.equal(calls.filter(c => c.options.method === "POST").length, 1);
assert.deepEqual(JSON.parse(calls[0].options.body), {fix: true, allow_restarts: true});
await evaluate("wedgeTroubleshootStart()");
assert.equal(calls.filter(c => c.options.method === "POST").length, 1);
assert.equal(storage.get("pineStationTroubleshootJob"), "job-1");
assert.equal(evaluate("wedgeTroubleshootBusy"), true);
assert.equal(context.wedgeLines.filter(s => s === "Checking dialogue.").length, 1);
''')


def test_cooldown_shows_next_retry_then_reported_failure_is_terminal() -> None:
    run_js(r'''
await evaluate("wedgeTroubleshootStart()");
job = {id: "job-1", status: "cooldown", transcript: ["Checking dialogue.", "Trying fresh wording."],
       summary: "Dialogue is waiting before a fresh retry.", next_retry_at: Date.now() / 1000 + 60};
await evaluate("wedgeTroubleshootPoll()");
assert.equal(evaluate("wedgeTroubleshootBusy"), true);
assert.ok(context.wedgeLines.some(s => s.includes("Next retry:")));
assert.ok(Array.from(timers.values()).some(t => t.ms === 5000));
job = {id: "job-1", status: "failed", transcript: job.transcript,
       summary: "The voice service still needs attention."};
await evaluate("wedgeTroubleshootPoll()");
assert.equal(evaluate("wedgeTroubleshootBusy"), false);
assert.equal(storage.has("pineStationTroubleshootJob"), false);
assert.ok(context.wedgeLines.includes("The voice service still needs attention."));
assert.equal(context.wedgeLines.filter(s => s === "Trying fresh wording.").length, 1);
''')


def test_service_restart_connection_loss_retains_same_job() -> None:
    run_js(r'''
await evaluate("wedgeTroubleshootStart()");
pollError = "Failed to fetch";
await evaluate("wedgeTroubleshootPoll()");
assert.equal(evaluate("wedgeTroubleshootBusy"), true);
assert.equal(storage.get("pineStationTroubleshootJob"), "job-1");
assert.ok(context.wedgeLines.some(s => s.includes("reconnecting")));
assert.equal(calls.filter(c => c.options.method === "POST").length, 1);
pollError = null;
job = {id: "job-1", status: "completed", transcript: ["Dialogue is playing again."],
       summary: "The DJs are being heard."};
await evaluate("wedgeTroubleshootPoll()");
assert.equal(evaluate("wedgeTroubleshootBusy"), false);
assert.ok(context.wedgeLines.includes("The DJs are being heard."));
''')


def test_start_error_is_visible_and_button_can_retry() -> None:
    run_js(r'''
failStart = true;
await evaluate("wedgeTroubleshootStart()");
assert.equal(evaluate("wedgeTroubleshootBusy"), false);
assert.ok(context.wedgeLines.includes("Could not start troubleshooting: Recorder unavailable"));
failStart = false;
await evaluate("wedgeTroubleshootStart()");
assert.equal(calls.filter(c => c.options.method === "POST").length, 2);
assert.equal(evaluate("wedgeTroubleshootBusy"), true);
''')


def test_background_pending_report_displays_retry_without_claiming_success() -> None:
    run_js(r'''
await evaluate("wedgeTroubleshootStart()");
job = {id: "job-1", status: "pending", running: false, transcript: ["A fresh variation is queued."],
       report: "Dialogue recovery is still pending; eligible retries continue in the station worker.",
       observation: {next_retry_at: Date.now() / 1000 + 60}};
await evaluate("wedgeTroubleshootPoll()");
assert.equal(evaluate("wedgeTroubleshootBusy"), false);
assert.ok(context.wedgeLines.some(s => s.includes("recovery is still pending") && s.includes("Next retry:")));
assert.ok(!context.wedgeLines.some(s => s.includes("playback is verified")));
''')


def test_expired_job_stops_polling_and_does_not_resubmit() -> None:
    run_js(r'''
await evaluate("wedgeTroubleshootStart()");
pollError = "Troubleshooting job not found";
await evaluate("wedgeTroubleshootPoll()");
assert.equal(evaluate("wedgeTroubleshootBusy"), false);
assert.equal(storage.has("pineStationTroubleshootJob"), false);
assert.ok(context.wedgeLines.some(s => s.includes("Click Troubleshoot station to try again")));
assert.equal(calls.filter(c => c.options.method === "POST").length, 1);
''')


def test_restart_opt_out_is_sent_and_controls_show_progress() -> None:
    run_js(r'''
const box = el("div", "", "");
context.box = box;
evaluate("wedgeTroubleshootControls(box)");
assert.equal(buttons[0].textContent, "Troubleshoot station");
assert.equal(checks[0].checked, true);
checks[0].checked = false;
checks[0].onchange();
await evaluate("wedgeTroubleshootStart()");
assert.equal(JSON.parse(calls[0].options.body).allow_restarts, false);
assert.equal(buttons[0].textContent, "Show troubleshooting progress");
assert.equal(checks[0].disabled, true);
job.status = "completed";
await evaluate("wedgeTroubleshootPoll()");
assert.equal(buttons[0].textContent, "Troubleshoot station");
assert.equal(checks[0].disabled, false);
''')


def test_actual_dj_play_helper_runs_in_click_before_console_or_job_fetch() -> None:
    source = pathlib.Path(__file__).parents[1].joinpath("app.py").read_bytes().decode("utf-8")
    start = source.index("function playOrPrompt(el) {")
    end = source.index("function clipToggle(", start)
    actual_helper = source[start:end]
    run_js("vm.runInContext(" + json.dumps(actual_helper) + r''', context);
const order = [];
context.window.pineAudioCtx = {state: "suspended", resume() {
  order.push("context-resume"); return Promise.resolve();
}};
const player = {pineDeliveryClip: {}, src: "/accepted-dialogue.wav", paused: true,
  ended: false, muted: false, volume: 0.7, play() {
    order.push("dialogue-play"); return Promise.resolve();
  }};
const untouched = [];
const muted = {...player, muted: true, play() {untouched.push("muted"); return Promise.resolve();}};
const zero = {...player, volume: 0, play() {untouched.push("zero-volume"); return Promise.resolve();}};
const future = {...player, pineDeliveryClip: null, play() {untouched.push("future"); return Promise.resolve();}};
context.djVoiceEls = [player, muted, zero, future];
context.pineAirPaused = false;
context.document.getElementById = () => null;
context.djVoiceUnstick = () => {order.push("check-stale-player");};
const originalApi = context.api;
context.api = (...args) => {order.push("fetch " + args[0]); return originalApi(...args);};
context.wedgeConsoleOpen = () => {
  context.wedgeConsole = {querySelector() {return null;}};
  context.api("/api/broadcast/console");
};
await evaluate("wedgeTroubleshootStart()");
assert.deepEqual(order.slice(0, 5), ["context-resume", "dialogue-play", "check-stale-player",
  "fetch /api/broadcast/console", "fetch /api/station/troubleshoot"]);
assert.equal(muted.muted, true);
assert.equal(zero.volume, 0);
assert.deepEqual(untouched, []);
''')


def test_gesture_retry_preserves_pause_and_cache_hold() -> None:
    run_js(r'''
context.window.cacheHold = true;
context.pineAirPaused = false;
let changed = 0;
context.document.getElementById = () => ({click() {changed++;}});
context.djVoiceUnstick = () => {changed++;};
await evaluate("wedgeTroubleshootStart()");
assert.equal(context.window.cacheHold, true);
context.window.cacheHold = false;
context.pineAirPaused = true;
evaluate("wedgeTroubleshootLocalPlayback()");
assert.equal(context.pineAirPaused, true);
assert.equal(changed, 0);
''')


def test_real_panel_patch_has_valid_javascript(tmp_path: pathlib.Path) -> None:
    source = pathlib.Path(__file__).parents[1].joinpath("app.py").read_bytes().decode("utf-8")
    patched = patch_app(source)
    start = patched.index("let wedgeIconEl = null;")
    end = patched.index("/* #1209:", start)
    ui = tmp_path / "station-panel-troubleshooting.js"
    ui.write_text(patched[start:end], encoding="utf-8")
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    result = subprocess.run([node, "--check", str(ui)], text=True,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
