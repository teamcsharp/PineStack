"""Host-side station supervision. Runs independently of the broadcast loop.

Only a running, wanted, unpaused spark-agent container may be restarted.
Healthy playback delegates production faults to the station's own owners.
No scripts, roulette choices, audio assets or conversations are modified.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def decide(state, *, now, wanted, paused, container, health_ok, feed_ok, diagnosis):
    """Pure, durable backoff policy for the host watchdog."""
    state = dict(state)
    recent = [float(t) for t in state.get("restart_times", []) if now - float(t) < 3600]
    state["restart_times"] = recent
    state["checked_at"] = now
    state["health_failures"] = 0 if health_ok else int(state.get("health_failures", 0)) + 1
    state["feed_failures"] = 0 if feed_ok else int(state.get("feed_failures", 0)) + 1
    state["action"] = "observe"
    if not wanted or paused or not container.get("Running") or container.get("Paused") or container.get("Restarting"):
        state.update(action="hold", reason="Station is off, paused, stopped or already restarting.", health_failures=0, feed_failures=0)
        return state
    # Let startup restore saved production, writers and page deliveries.
    if now - float(container.get("started_at", now)) < 180:
        state.update(action="warming", reason="The station is restoring its saved state.", health_failures=0, feed_failures=0)
        return state
    quiet = float(diagnosis.get("speech_quiet_seconds") or 0)
    live_speech = bool(diagnosis.get("page_speech_active"))
    silent = bool(diagnosis.get("listeners_present") and quiet >= 60 and not live_speech)
    feed_stalled = state["feed_failures"] >= 3 and silent and quiet >= 180
    server_stalled = state["health_failures"] >= 3
    if live_speech:
        # The known old-clip diagnostic must never trigger a reload while
        # current listener receipts show audible progression.
        server_stalled = False
        feed_stalled = False
    if server_stalled or feed_stalled:
        if len(recent) >= 3:
            state.update(action="attention", reason="Three restart attempts this hour; repeated server failure needs investigation.")
        elif now - float(state.get("last_restart_at", 0)) < max(300, 300 * 2 ** len(recent)):
            state.update(action="cooldown", reason="The previous restart is still in its recovery window.")
        else:
            state.update(action="restart_station", reason="Three consecutive station-server failures." if server_stalled
                         else "The voice feed repeatedly fails and no listener speech is advancing.")
        return state
    production = diagnosis.get("production_health") or {}
    maintenance = diagnosis.get("maintenance") or {}
    production_stalled = bool(set(production.get("issues") or []) & {"conversation_reserve_low", "recordings_owed"}
        and not diagnosis.get("writer_busy") and not diagnosis.get("recording_busy")
        and (maintenance.get("last_error") or now - float(maintenance.get("at") or 0) >= 120))
    if (silent or production_stalled or not feed_ok) and now - float(state.get("last_request_at", 0)) >= 120:
        state.update(action="troubleshoot", reason="The station's own repair owners must resolve speech or production faults.")
    elif health_ok and feed_ok:
        state["reason"] = "Station server and voice feed respond; listener receipts own playback verification."
    else:
        state["reason"] = "Confirming a failed probe before service recovery."
    return state


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    try:
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class HostWatchdog:
    def __init__(self, root, base_url="http://127.0.0.1:8096"):
        self.root = Path(root)
        self.base_url = base_url
        self.state_path = self.root / "data/station_flow_watchdog.json"

    def request(self, route, payload=None):
        key = next(line.split("=", 1)[1].strip().strip('"').strip("'")
                   for line in (self.root.parent / ".openwebui.env").read_text().splitlines()
                   if line.startswith("SPARK_AGENT_API_KEY="))
        req = urllib.request.Request(self.base_url + route,
              data=None if payload is None else json.dumps(payload).encode(),
              headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                body = json.loads(response.read(8 * 1024 * 1024 + 1))
            return body if isinstance(body, dict) else None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None

    def container(self):
        r = subprocess.run(["docker", "inspect", "--format", "{{json .State}}", "spark-agent"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode:
            return {}
        state = json.loads(r.stdout)
        try:
            state["started_at"] = datetime.datetime.fromisoformat(state["StartedAt"].replace("Z", "+00:00")).timestamp()
        except (KeyError, ValueError):
            state["started_at"] = time.time()
        return state

    def once(self):
        now = time.time()
        wanted = bool(read_json(self.root / "data/radio_on.json", {}).get("on"))
        paused = bool(read_json(self.root / "data/paused.json", {}).get("paused"))
        container = self.container()
        previous = read_json(self.state_path, {})
        # Real HTTP probes cover encoding and routing, beyond process liveness.
        health = self.request("/healthz")
        feed = self.request("/api/dj/voice?since=0") if wanted and not paused else {}
        diagnosis = self.request("/api/station/troubleshoot", {"fix": False}) if health is not None and wanted and not paused else None
        state = decide(previous, now=now, wanted=wanted, paused=paused, container=container,
                       health_ok=health is not None, feed_ok=isinstance(feed, dict) and (not wanted or paused or isinstance(feed.get("clips"), list) and not feed.get("feed_error_count")),
                       diagnosis=diagnosis or {})
        state["diagnosis_available"] = diagnosis is not None
        state["last_error"] = ""
        action = state["action"]
        if action == "troubleshoot":
            # A live manual/coordinator job keeps sole ownership.
            if diagnosis is None:
                state.update(action="attention", reason="The dialogue diagnosis did not respond; its failure is not evidence of successful recovery.")
            else:
                job = self.request("/api/station/troubleshoot", {"fix": True, "allow_restarts": True})
                state["last_request_at"] = now
                state["job_id"] = (job or {}).get("id")
                if not state["job_id"]:
                    state["last_error"] = "The station recovery request did not return a job."
        elif action == "restart_station":
            # Persist intent first. A killed host helper cannot restart twice
            # without a cooldown, and an operator stop is rechecked just before
            # issuing the one explicitly named Docker restart.
            fresh = self.container()
            still_wanted = bool(read_json(self.root / "data/radio_on.json", {}).get("on"))
            still_paused = bool(read_json(self.root / "data/paused.json", {}).get("paused"))
            if not fresh.get("Running") or fresh.get("Paused") or fresh.get("Restarting") or not still_wanted or still_paused:
                state.update(action="hold", reason="Station ownership changed before the restart.")
            elif fresh.get("StartedAt") != container.get("StartedAt"):
                state.update(action="warming", reason="Another owner already restarted the station.")
            else:
                state["last_restart_at"] = now
                state["restart_times"].append(now)
                write_state(self.state_path, state)
                r = subprocess.run(["docker", "restart", "--time", "20", "spark-agent"],
                                   capture_output=True, text=True, timeout=45)
                if r.returncode:
                    state["last_error"] = "The scoped station restart failed."
        write_state(self.state_path, state)
        # Operational counters only; no credentials or generated dialogue.
        return {k: state.get(k) for k in ("action", "reason", "health_failures", "feed_failures", "last_error", "job_id")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    watcher = HostWatchdog(args.root)
    while True:
        try:
            print(json.dumps(watcher.once()), flush=True)
        except Exception as exc:
            print(json.dumps({"action": "attention", "error": type(exc).__name__}), flush=True)
        if args.once:
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
