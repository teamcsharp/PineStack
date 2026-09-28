"""PineLive host, end to end on the NETWORK road with a generated tone.

Nothing here touches a device or the air: the "instrument" is ffmpeg's
lavfi sine, POSTed to the host's own ingest exactly as a real sender
would, and every port is a private one. It proves the whole host chain:
ingest auth -> normaliser -> ring -> the station door's /pcm and /levels
-> host_state.json -> the safety master.

  PYTHONIOENCODING=utf-8 nice -n 19 python tools/pinelive_e2e_network.py

Prints PASS/FAIL per check and exits 0 only if all pass.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOOR_PORT = int(os.environ.get("PL_E2E_DOOR", "18297"))
INGEST_PORT = int(os.environ.get("PL_E2E_INGEST", "18296"))
TOKEN = "e2e-token-1234"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, note: str = "") -> None:
    RESULTS.append((name, bool(ok), note))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" - " + note) if note else ""))


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        return shutil.which("ffmpeg") or "ffmpeg"


def http(url: str, timeout: float = 5.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def read_stream(url: str, seconds: float) -> bytes:
    out = b""
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=5.0) as r:
        while time.time() - t0 < seconds:
            got = r.read(256)
            if not got:
                break
            out += got
    return out


def main() -> int:
    ff = ffmpeg_exe()
    td = Path(tempfile.mkdtemp(prefix="pl-e2e-"))
    data = td / "data"
    data.mkdir(parents=True)
    (data / "control.json").write_text(json.dumps({
        "v": 1, "at": time.time(), "armed": True, "event_id": "e2e-test",
        "source": "network", "token": TOKEN, "master": True,
        "channel_pair": [1, 2], "channel_mode": "auto", "silence_db": -60.0}))
    env = dict(os.environ)
    env.update(PINELIVE_DATA=str(data), PINELIVE_DOOR_PORT=str(DOOR_PORT),
               PINELIVE_INGEST_PORT=str(INGEST_PORT),
               PINELIVE_INGEST_ADDRS="127.0.0.1", PINELIVE_FFMPEG=ff,
               PINELIVE_RING_SECONDS="20")
    host = subprocess.Popen([sys.executable, str(HERE / "pinelive_host.py")],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    sender = None
    try:
        up = False
        for _ in range(40):
            time.sleep(0.25)
            try:
                socket.create_connection(("127.0.0.1", DOOR_PORT), timeout=0.5).close()
                up = True
                break
            except OSError:
                continue
        check("the door binds", up, "127.0.0.1:%d" % DOOR_PORT)
        if not up:
            return 1

        # the wrong token is refused
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:%d/ingest.pcm?t=wrong&rate=48000&channels=2&format=s16le"
                % INGEST_PORT, data=b"\0" * 4096, method="POST")
            urllib.request.urlopen(req, timeout=3.0)
            check("a wrong ingest token is refused", False)
        except urllib.error.HTTPError as exc:
            check("a wrong ingest token is refused", exc.code == 403, "HTTP %d" % exc.code)
        except Exception as exc:  # noqa: BLE001
            check("a wrong ingest token is refused", False, str(exc))

        # the sender: 8 s of a -12 dBFS 440 Hz sine, as a real ffmpeg sender
        sender = subprocess.Popen(
            [ff, "-hide_banner", "-loglevel", "error", "-re",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
             # ffmpeg's sine source sits at -18 dBFS peak; +6 dB puts the
             # tone at -12 dBFS peak / ~-15 dBFS RMS, a healthy level
             "-af", "volume=6dB", "-ac", "2", "-ar", "48000", "-f", "s16le",
             "-t", "8", "-method", "POST",
             "http://127.0.0.1:%d/ingest.pcm?t=%s&rate=48000&channels=2&format=s16le&label=e2e"
             % (INGEST_PORT, TOKEN)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(2.5)

        state = json.loads((data / "host_state.json").read_text())
        lv = state.get("level") or {}
        snd = (state.get("network") or {}).get("sender") or {}
        check("host_state says the sender is on", snd.get("label") == "e2e", json.dumps(snd)[:80])
        check("the capture runs", (state.get("capture") or {}).get("state") == "running",
              json.dumps(state.get("capture"))[:80])
        got_level = lv.get("level_db")
        check("the tone is measured near -15 dBFS RMS",
              got_level is not None and -21.0 < float(got_level) < -9.0,
              "level_db=%s peak_db=%s" % (lv.get("level_db"), lv.get("peak_db")))

        pcm = read_stream("http://127.0.0.1:%d/pcm?cushion_ms=200" % DOOR_PORT, 2.0)
        check("the door serves ~2 s of s16le", len(pcm) > 250000, "%d bytes" % len(pcm))
        nz = sum(1 for i in range(0, min(len(pcm), 40000), 2)
                 if pcm[i:i + 2] != b"\0\0")
        check("the PCM is not silence", nz > 5000, "%d non-zero samples of 20000" % nz)

        levels = read_stream("http://127.0.0.1:%d/levels" % DOOR_PORT, 1.6)
        lines = [ln for ln in levels.split(b"\n") if ln.strip().startswith(b"{")]
        frames = []
        for ln in lines:
            try:
                frames.append(json.loads(ln))
            except ValueError:
                pass
        check("levels stream ~20 fps", 20 <= len(frames) <= 45, "%d frames in 1.6 s" % len(frames))
        check("levels frames carry bands", bool(frames and frames[0].get("bands")),
              "keys: %s" % sorted(frames[0].keys()) if frames else "none")

        sender.wait(timeout=15)
        time.sleep(1.0)
        masters = list((data / "master").rglob("*.wav"))
        size = sum(p.stat().st_size for p in masters)
        check("the safety master recorded", bool(masters) and size > 500000,
              "%d file(s), %d bytes" % (len(masters), size))

        # the sender gone: state says so within a few seconds
        time.sleep(2.5)
        state2 = json.loads((data / "host_state.json").read_text())
        snd2 = (state2.get("network") or {}).get("sender")
        check("the sender's leaving is seen", not snd2, json.dumps(snd2)[:60])
    finally:
        for p in (sender, host):
            if p is not None:
                try:
                    p.terminate()
                    p.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    try:
                        p.kill()
                    except Exception:  # noqa: BLE001
                        pass
        shutil.rmtree(td, ignore_errors=True)
    bad = [r for r in RESULTS if not r[1]]
    print("%d of %d checks pass" % (len(RESULTS) - len(bad), len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
