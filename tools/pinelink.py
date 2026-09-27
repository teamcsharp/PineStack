#!/usr/bin/env python3
"""PineLink: the camera, held on the spare radio and served to the house.

The camera is an ACCESS POINT. Anything that wants its video has to join
`H88_<mac>`, and a device with one radio that joins it drops off the house
LAN - which for the tablet means losing the station entirely. The DGX has
two radios, so this holds the camera on the spare one (`wlx…`) while
`wlP9s9` keeps 10.89.1.246 and the broadcast. That asymmetry is the whole
reason the link lives here and not on the tablet.

One ffmpeg, one input, four outputs:

    rtsp://192.168.1.254:554/live  (h264 848x480, the preview substream)
      ├─ HLS   → data/pinelink/live/index.m3u8   what the house watches
      ├─ mp4   → data/pinelink/clips/<stamp>.mp4  what is kept
      ├─ jpeg  → data/pinelink/frame.jpg          the corner preview, 4 fps
      └─ TS    → udp://127.0.0.1:18081            the picture AS IT ARRIVES,
                 served by TsDoor at http://10.89.1.246:8098/live.ts

All but the still are `-c copy`. The camera already hands over h264, so nothing is
re-encoded: no GPU, no quality loss, and a recording that is byte-identical
to what was broadcast. The 4K H.265 never comes down this pipe - it stays
on the camera's card and is fetched over its HTTP server afterwards. 4K
over a 10 m camera AP into a live broadcast would be a bad trade even if it
worked.

`-use_wallclock_as_timestamps` is not optional. The camera sends packets
with no PTS at all - measured: "Timestamps are unset in a packet for stream
0" and non-monotonic DTS on the very first test pull - and a `-c copy`
without it produces a file whose timing is broken in a way that only shows
up later, when you try to play it back or cut it.
"""
from __future__ import annotations

import argparse
import glob                  # #1359: finding the adapter on the bus
import itertools             # TsDoor: the tail of the ring, from the right
import json
import os
import re                    # #1118: the clips folder preference
import shutil
import signal
import socket                # TsDoor: the UDP side
import subprocess
import sys
import threading             # TsDoor: one ring, one condition, n clients
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pinelink"
LIVE = OUT / "live"
CLIPS = OUT / "clips"
STATE = OUT / "state.json"
PREF = ROOT / "data" / "pinelink_pref.json"


def clips_dir() -> Path:
    """#1118: the operator may move the kept clips. The station writes the
    choice to data/pinelink_pref.json as data/<folder> and refuses anything
    outside data/ (the container that serves the clips can see nothing
    else), so only that shape is honoured here; anything else is the
    default. Read at every (re)start of the recorder, which is when the
    segmenter's output pattern is fixed."""
    try:
        raw = str(json.loads(PREF.read_text()).get("clips_dir") or "")
    except Exception:  # noqa: BLE001
        raw = ""
    flat = raw.replace("\\", "/").strip().strip("/")
    m = re.search(r"(?:^|/)data/(.+)$", flat) if flat else None
    if m:
        parts = [p for p in m.group(1).split("/") if p and p not in (".", "..")]
        if parts:
            return ROOT.joinpath("data", *parts)
    return OUT / "clips"

STATION_IF = "wlP9s9"           # holds 10.89.1.246 - never touched
SPARE_IF = "wlx984827b6b478"
# #1388: how long without a new frame before the link is declared gone.
FRAME_STALL_S = 20.0
# #1359: the TP-Link Archer T2U PLUS (RTL8821AU) that IS the spare
# radio. Used only to find it on the USB bus for a reset, and matched
# exactly - never as a prefix.
ADAPTER_VENDOR = "2357"
SSID = "H88_5c8e8bddfab1"
PSK = "12345678"
CAMERA = "192.168.1.254"
RTSP = "rtsp://%s:554/live" % CAMERA

SEGMENT_SECONDS = 300           # one file per five minutes
KEEP_HOURS = 48.0               # same as every other ledger here
RESTART_REST = 5.0
_LAST_SEEN: dict = {"seen": False, "signal": 0}

# #1250b: WHICH TRANSPORT, and it is a measurement, not a taste.
#
# Measured 2026-09-21 against this camera with nothing else watching it:
#   tcp  30.2 s / 896 packets, then "EOF while reading input"
#        29.8 s / 887 packets, then "Error during demuxing: Connection
#        timed out"                      - three runs, all thirty seconds
#   udp  400 s with no drop at all, and a five-minute segment that ran
#        to its full five minutes for the first time
#
# The camera runs "Nvt RTSP, streamed by the LIVE555 Media Server" and it
# closes an INTERLEAVED RTP-over-TCP session at thirty seconds. ffmpeg
# does send the GET_PARAMETER keepalive; it is torn down regardless.
# Thirty seconds of picture plus the twenty-three the supervisor spent
# rescanning the radio before each retry IS the ten-to-fifteen seconds
# the operator saw - and it is why no clip ever reached five minutes.
#
# TCP is kept as the fallback rather than deleted, because a network
# that blocks the RTP ports is the one case where it is the only way
# through. Nothing here is a standing guess: a transport that cannot
# hold a stream for TRANSPORT_GOOD_S is rotated away from.
TRANSPORTS = ("udp", "tcp")
TRANSPORT_GOOD_S = 45.0         # longer than the camera's 30 s TCP cut
_TRANSPORT = [0]
# #1250b: udp is the transport that can lose a packet, and on this link
# it does - 22 "RTP: missed" in a clean two-minute run. That is half a
# packet a second out of thirty frames a second, and the recording came
# back 119.5 seconds long out of 120, so it is a blemish and not a hole.
# A 4 MB socket buffer and a wider reorder window were MEASURED against
# the defaults and were WORSE (53 s of media in 94 s, and the wider
# reorder window only adds latency: RTP over udp has no retransmission,
# so waiting longer for a lost packet recovers nothing). The defaults
# stand; this comment is here so nobody spends the afternoon again.
#
# #1388's `-timeout` stays exactly as it is. Two udp runs did end on
# "Error during demuxing: Connection timed out" at 94 s and 338 s, and
# an idle RTSP control socket was the suspicion - but the camera's own
# RTSP server was then observed to shut down entirely (port 554 refused
# while its HTTP server still answered 302), which produces the same
# line, so the suspicion is unproven and the timeout is not worth
# touching on one. What it costs is now small: with the rescan gated
# below, a drop is five seconds off the air instead of twenty-five.
# Lines ffmpeg prints once per muxer at start-up that mean nothing at
# all. They cost this request two sessions: they were the whole of the
# drop reason, so the muxer was blamed and the closed session was not.
STREAM_NOISE = (
    "Timestamps are unset in a packet",
    "Non-monotonic DTS in output",
)
_STREAM: dict = {"transport": TRANSPORTS[0], "class": "", "say": "",
                 "life_s": 0.0, "lives": [], "exit": "", "noise": 0}
# #1250b: a wifi rescan takes the spare radio off channel for about
# twenty-three seconds. Paying that before every retry doubled the hole.
DOCTOR_EVERY_S = 300.0
_DOCTOR = [0.0]


def run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as err:  # noqa: BLE001
        return 1, str(err)


def say(state: str, **more) -> None:
    """One state file, written whole. The station reads this; it never
    reads the process table, so a stale file is a lie and the only defence
    is that every path through this program writes one."""
    # The TS door's line travels with every write - where it is and
    # whether it is being fed - and a fault in the door can never stop
    # this file: it is the one reading the station has of this process.
    try:
        ts = (_TS_DOOR[0].summary() if _TS_DOOR[0] is not None
              else {"ok": False, "port": TS_HTTP_PORT, "path": "/live.ts"})
    except Exception:  # noqa: BLE001
        ts = {"ok": False}
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "at": time.time(), "state": state, "camera": CAMERA,
            "rtsp": RTSP, "ssid": SSID, "iface": SPARE_IF,
            # #1347: so a surface can draw "the camera is there but not
            # joined yet" without being able to see a radio.
            # #1250b: how the last stream ended travels with every
            # other reading, so no surface has to ask a second door.
            **_LAST_SEEN, "stream": dict(_STREAM), "ts": ts, **more},
            indent=2))
    except Exception:  # noqa: BLE001
        pass


def station_safe() -> bool:
    code, out = run(["ip", "-4", "-br", "addr", "show", STATION_IF])
    return "10.89.1.246" in out


def linked() -> bool:
    code, out = run(["ip", "-4", "-br", "addr", "show", SPARE_IF])
    return "192.168.1." in out


def remember() -> None:
    """#1350: so turning the camera on is the whole procedure.

    NetworkManager keeps a profile after the first successful join, but
    two of its defaults are wrong for this. Autoconnect has to be ON, or
    the camera coming back is noticed by nobody. And the profile has to
    be PINNED to the spare interface: an unbound profile is a profile
    NetworkManager may bring up on wlP9s9, which is the station's radio
    and the only way anything reaches the broadcast. That is not a
    trade worth making for a camera.

    Low priority on purpose, so it can never win against the house
    network on a radio that can see both.
    """
    try:
        code, out = run(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection',
                         'show'], 20)
        name = ''
        for line in (out or '').splitlines():
            bits = line.split(':')
            if bits and bits[0] == SSID:
                name = bits[0]
                break
        if not name:
            return          # nothing joined yet; nothing to remember
        run(['nmcli', 'connection', 'modify', name,
             'connection.autoconnect', 'yes',
             'connection.autoconnect-priority', '-10',
             # #1250: NEVER let this radio doze. In power
             # save an RTL8821AU sleeps between beacons and
             # the camera's AP does not buffer for it, so
             # the RTSP stream stalls and the watchdog kills
             # ffmpeg - measured as two recorder lifetimes
             # inside fifty-three seconds. 2 is 'disable'.
             '802-11-wireless.powersave', '2',
             'connection.interface-name', SPARE_IF], 20)
    except Exception:  # noqa: BLE001
        pass          # the sweep rejoins anyway; this only makes it quicker


def join() -> bool:
    """Join the camera's AP on the spare radio only."""
    if linked():
        return True
    run(["nmcli", "device", "set", SPARE_IF, "managed", "yes"])
    run(["ip", "link", "set", SPARE_IF, "up"])
    run(["nmcli", "device", "wifi", "rescan", "ifname", SPARE_IF], 45)
    time.sleep(4)
    code, out = run(["nmcli", "device", "wifi", "connect", SSID,
                     "password", PSK, "ifname", SPARE_IF], 60)
    ok = code == 0 and linked()
    if ok:
        remember()          # #1350: next time, it just comes back
        # #1250: the profile setting applies at ACTIVATION, and
        # this activation has already happened - so say it to the
        # interface too, or the first session after a fresh join
        # is the one that dozes.
        run(['iw', 'dev', SPARE_IF, 'set', 'power_save', 'off'], 10)
    return ok


def seen_on_air() -> dict:
    """#1347: is the camera BROADCASTING, whether or not we have joined.

    The station runs in a container with no nmcli and no systemctl, so it
    cannot ask the radio anything. This can - it is the process that owns
    the interface - so it answers here and leaves the answer in the state
    file the station already reads. One writer, one reader, no new door.
    """
    got = {'seen': False, 'signal': 0}
    try:
        code, out = run(['nmcli', '-t', '-f', 'SSID,SIGNAL', 'device',
                         'wifi', 'list', 'ifname', SPARE_IF], 25)
        for line in (out or '').splitlines():
            bits = line.split(':')
            if bits and bits[0] == SSID:
                got['seen'] = True
                try:
                    got['signal'] = int(bits[1]) if len(bits) > 1 else 0
                except ValueError:
                    got['signal'] = 0
                break
    except Exception:  # noqa: BLE001
        pass
    return got


NEIGH_CEILING = "net.ipv4.neigh.default.gc_thresh3"


def neigh_pressure() -> dict:
    """#1359: IS THE KERNEL STILL ACCEPTING NEW NEIGHBOURS?

    Measured on 2026-09-13, and it is the reason this whole diagnostic
    needed another question. The adapter associated with the camera three
    times and timed out authenticating each time; the radio looked fine,
    the camera was on the air, and the doctor's verdict was "out of range".

    It was neither. The ARP table held 1,019 entries against a
    gc_thresh3 of 1,024 - the hard ceiling - because five Docker bridge
    networks were holding about 250 each. dmesg was flooding with
    "neighbour: arp_cache: neighbor table overflow!", and a kernel that
    cannot record a new neighbour cannot finish an ARP exchange with a
    camera it has only just met.

    The defaults are sized for a machine with one or two networks on it.
    This box has eight bridges before anything else is counted, so this is
    not an edge case here - it is the normal state, and it will come back
    the moment the ceiling is lowered or a new stack is brought up.
    """
    out = {'entries': 0, 'ceiling': 0, 'full': False}
    try:
        code, txt = run(['ip', '-4', 'neigh', 'show'], 15)
        out['entries'] = len([x for x in (txt or '').splitlines() if x.strip()])
    except Exception:  # noqa: BLE001
        return out
    try:
        code, txt = run(['sysctl', '-n', NEIGH_CEILING], 10)
        out['ceiling'] = int((txt or '0').strip() or 0)
    except Exception:  # noqa: BLE001
        out['ceiling'] = 0
    if out['ceiling']:
        # 90%, not 100%. The table is refused at the ceiling, and by the
        # time it is exactly full the damage has already been done to
        # whatever tried to associate.
        out['full'] = out['entries'] >= out['ceiling'] * 0.9
    return out


def radio_reset() -> dict:
    """#1359: re-bind the USB adapter, which is what actually cured it.

    "reseat it" was the advice and it was wrong - or rather, it was the
    physical version of the right idea, and it cannot be followed from a
    panel. After a failed authentication this RTL8821AU stops scanning
    entirely: `iw dev ... scan` returns zero networks with no error, the
    interface reports admin-UP with NO-CARRIER, and `ip link` down/up does
    not clear it. Unbinding and re-binding the USB device does: the radio
    came back seeing twelve networks.

    Deliberately narrow. It finds the adapter by its USB vendor id and
    refuses to act if that lookup is ambiguous, because the one thing this
    must never do is reset a different device - the station's own radio is
    on this machine and the broadcast rides it.
    """
    out = {'ok': False, 'say': ''}
    try:
        found = []
        for path in sorted(glob.glob('/sys/bus/usb/devices/*')):
            vendor = os.path.join(path, 'idVendor')
            if not os.path.isfile(vendor):
                continue
            try:
                with open(vendor) as fh:
                    if fh.read().strip() != ADAPTER_VENDOR:
                        continue
            except OSError:
                continue
            # A USB device directory is named bus-port; an INTERFACE is
            # named bus-port:config.interface and must not be unbound here.
            name = os.path.basename(path)
            if ':' in name:
                continue
            found.append(name)
        if len(found) != 1:
            out['say'] = ('found %d adapters with vendor %s - refusing to '
                          'guess which one to reset'
                          % (len(found), ADAPTER_VENDOR))
            return out
        which = found[0]
        for door in ('unbind', 'bind'):
            with open('/sys/bus/usb/drivers/usb/' + door, 'w') as fh:
                fh.write(which)
            time.sleep(4 if door == 'unbind' else 7)
        out['ok'] = True
        out['device'] = which
        out['say'] = ('re-bound the USB adapter at %s - it takes a few '
                      'seconds to start scanning again' % which)
    except PermissionError:
        out['say'] = 'only root can re-bind a USB device'
    except Exception as err:  # noqa: BLE001
        out['say'] = str(err)[:200]
    return out


def doctor() -> dict:
    """#1349: why is the camera not here, in terms that separate the
    three things that look identical from the outside.

    'not on the network' covers a dead radio, a camera out of range and a
    camera that is switched off, and the cure is different for each. The
    radio can tell them apart: if it can see OTHER networks, the radio
    works and the antenna is fine, so a missing camera is out of range or
    asleep - and the manual rates this link at 10 m. If it can see
    nothing at all, the radio is the problem.
    """
    out = {'iface': SPARE_IF, 'nearby': 0, 'strongest': [], 'steps': []}
    try:
        code, link = run(['ip', '-br', 'link', 'show', SPARE_IF], 10)
        out['iface_up'] = ' UP ' in (link or '') or 'UP>' in (link or '')
    except Exception:  # noqa: BLE001
        out['iface_up'] = False
    # #1250: a dozing radio drops the stream every ten or fifteen
    # seconds and every other reading here stays green while it
    # does. One line of output; it belongs on the ladder.
    try:
        code, ps = run(['iw', 'dev', SPARE_IF, 'get', 'power_save'], 10)
        out['power_save'] = 'on' if ' on' in (ps or '').lower() else (
            'off' if ' off' in (ps or '').lower() else 'unknown')
    except Exception:  # noqa: BLE001
        out['power_save'] = 'unknown'
    if out.get('power_save') == 'on':
        out['steps'].append(
            'the spare radio is in power save - it dozes between '
            'beacons and the camera stops mid-stream; run: sudo iw '
            'dev %s set power_save off' % SPARE_IF)
    seen = []
    try:
        run(['nmcli', 'device', 'wifi', 'rescan', 'ifname', SPARE_IF], 40)
        time.sleep(4)
        code, txt = run(['nmcli', '-t', '-f', 'SSID,SIGNAL', 'device',
                         'wifi', 'list', 'ifname', SPARE_IF], 25)
        for line in (txt or '').splitlines():
            bits = line.split(':')
            if bits and bits[0]:
                try:
                    seen.append((int(bits[1]) if len(bits) > 1 else 0,
                                 bits[0]))
                except ValueError:
                    seen.append((0, bits[0]))
    except Exception as err:  # noqa: BLE001
        out['why'] = str(err)[:200]
    seen.sort(reverse=True)
    out['neigh'] = neigh_pressure()
    out['nearby'] = len(seen)
    out['strongest'] = [{'ssid': n, 'signal': s} for s, n in seen[:5]]
    out['camera'] = any(n == SSID for _s, n in seen)

    # #1359: the answer that outranks all of them. A full neighbour
    # table breaks the ARP exchange itself, so the radio looks healthy,
    # the camera is visible, and the join still fails - with every
    # other reading saying nothing is wrong.
    if out.get('neigh', {}).get('full'):
        n = out['neigh']
        out['verdict'] = ('the kernel neighbour table is full (%d of %d)'
                          % (n['entries'], n['ceiling']))
        out['steps'] = [
            'new ARP entries are being refused, so this machine cannot '
            'finish an address exchange with a device it has just met - '
            'the radio and the camera can both be perfectly healthy and '
            'the join will still time out',
            'Docker bridge networks are almost always what fills it: '
            'each one holds an entry per address it has seen',
            'raise the ceiling: net.ipv4.neigh.default.gc_thresh1/2/3 '
            'to 1024/4096/8192 in /etc/sysctl.d, then sysctl -p']
        out['cure'] = 'neigh'
    elif out['camera']:
        out['verdict'] = 'the camera is on the air - joining it now'
        out['steps'] = ['found it; the link will join within 15 seconds']
    elif not out['iface_up']:
        out['verdict'] = 'the spare radio is down'
        out['steps'] = ['the USB adapter is not up - reseat it, then '
                        'restart the pinelink service']
    elif out['nearby'] == 0:
        out['verdict'] = 'the spare radio sees nothing at all'
        # #1359: and the cure is a re-bind, not a reseat. This is the
        # exact state measured on 2026-09-13 after three failed
        # authentications: admin-UP, NO-CARRIER, and a scan that
        # returns zero networks with no error at all.
        out['steps'] = [
            'the adapter is up but scanning nothing, which is how this '
            'chipset fails after a refused association',
            'press Reset radio - it unbinds and re-binds the USB '
            'device, which clears it; ip link down/up does not',
            'if that does not bring it back, reseat the adapter in a '
            'different USB port']
        out['cure'] = 'reset'
    else:
        out['verdict'] = ('the radio is fine - it can see %d other '
                          'network(s) - so the camera is out of range or '
                          'asleep') % out['nearby']
        out['steps'] = [
            'the camera Wi-Fi only reaches about 10 m (32 ft) - bring it '
            'closer to the DGX, or move the USB adapter towards it',
            'these cameras drop their Wi-Fi to save battery: press the '
            'Wi-Fi button again and watch for the solid green light',
            'a phone or the Viidure app already joined takes the only '
            'client slot - disconnect it first',
            'then press Look again',
        ]
    # #1250b: HOW THE LAST STREAM ENDED, on the ladder, in one word.
    # Every other reading here was green while the picture cut out
    # every thirty seconds, because not one of them was about the
    # stream. This rung is.
    out['stream'] = dict(_STREAM)
    if _STREAM.get('class') == 'session-cut':
        out['steps'].append(
            'the camera is ending the RTSP session itself - it does that '
            'to an interleaved TCP session at thirty seconds; the link '
            'runs on %s and rotates transport by itself if that stops '
            'holding' % rtsp_transport())
    elif _STREAM.get('class') == 'decode':
        out['steps'].append(
            'the picture is arriving damaged: bring the camera closer to '
            'the DGX, or the USB adapter towards the camera')
    elif _STREAM.get('class') == 'stalled':
        out['steps'].append(
            'the camera stopped sending mid-stream - a fresh battery or '
            'a shorter distance is usually what that wants')
    return out


def camera_awake() -> bool:
    """Does the camera answer? Asked of RTSP, not of ping: these cameras
    answer ICMP while their streamer is still coming up, so a ping is a
    reading that is true too early."""
    code, _ = run(["ffprobe", "-v", "error", "-rtsp_transport", "tcp",
                   "-timeout", "4000000", "-show_streams", RTSP], 15)
    return code == 0


def trim_old() -> int:
    """Two days of clips, like every other ledger on this box."""
    gone = 0
    floor = time.time() - KEEP_HOURS * 3600.0
    try:
        for f in CLIPS.glob("*.mp4"):
            if f.stat().st_mtime < floor:
                f.unlink()
                gone += 1
    except Exception:  # noqa: BLE001
        pass
    return gone


def rtsp_transport() -> str:
    """#1250b: the transport in force. See TRANSPORTS - it rotates."""
    return TRANSPORTS[_TRANSPORT[0] % len(TRANSPORTS)]


def stream_fault(err: str, life_s: float, stalled: bool) -> dict:
    """#1250b: NAME the way a stream ended, in one word.

    `why` was already there and it was never a reading: it carried
    whichever four lines ffmpeg happened to print last, and for this
    camera those are always the two harmless start-up warnings about
    timestamps. Two sessions read them and went after the muxer. The
    line that named the fault - the session being closed at thirty
    seconds - was cut off the end and shown to nobody.
    """
    lines = [x.strip() for x in (err or "").splitlines() if x.strip()]
    noisy = [x for x in lines if any(n in x for n in STREAM_NOISE)]
    real = [x for x in lines if x not in noisy]
    last = (real[-1] if real else (lines[-1] if lines else ""))
    low = " ".join(real).lower()
    was = rtsp_transport()
    if stalled:
        cls = "stalled"
        said = ("no new frame for %ds with ffmpeg still running - the "
                "camera stopped sending" % int(FRAME_STALL_S))
    elif ("connection refused" in low or "no route to host" in low
            or "network is unreachable" in low):
        cls = "unreachable"
        said = "the camera did not answer at all"
    elif (("eof while reading input" in low or "connection timed out" in low
           or "end of file" in low or "immediate exit" in low)
          and 2.0 <= life_s <= 40.0):
        cls = "session-cut"
        said = ("the camera closed the session itself after %.0fs - it "
                "cuts an interleaved TCP session at thirty seconds, and "
                "this run was on %s" % (life_s, was))
    elif "error while decoding" in low or "corrupt" in low:
        cls = "decode"
        said = "packets are arriving damaged - the radio link is weak"
    elif life_s < 2.0:
        cls = "no-start"
        said = "ffmpeg gave up before any picture arrived"
    else:
        cls = "ended"
        said = "the stream ended after %.0fs" % life_s
    return {"class": cls, "say": said, "exit": last[:300],
            "noise": len(noisy), "transport": was,
            "life_s": round(life_s, 1)}


def ffmpeg_cmd() -> list[str]:
    # #1250b: udp first, and which one is in force is the rotating
    # measurement above rather than a constant typed in here.
    tport = rtsp_transport()
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-rtsp_transport", tport,
        # #1388: a read that gets nothing for twenty seconds is a dead
        # link, and ffmpeg must EXIT on it. Without this it sat on a
        # dropped camera for 12.9 hours (measured: pid alive, the radio
        # disconnected, the last frame from the night before) and the
        # supervisor, blocked on its pipe, never got back to its loop.
        # #1388b: measured on ffmpeg 6.1.1 - -rw_timeout is accepted but the
        # RTSP socket still opened with ?timeout=0; -timeout is the one that
        # reaches it (?timeout=20000000). Microseconds.
        "-timeout", str(int(FRAME_STALL_S * 1_000_000)),
        # The camera sets no PTS. Without this the copy is unplayable
        # later in ways that do not show up now.
        "-use_wallclock_as_timestamps", "1",
        "-i", RTSP,
        # what the house watches
        "-map", "0:v", "-c", "copy",
        "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
        "-hls_flags", "delete_segments+append_list+omit_endlist",
        "-hls_segment_filename", str(LIVE / "seg%05d.ts"),
        str(LIVE / "index.m3u8"),
        # what is kept
        "-map", "0:v", "-c", "copy",
        "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
        "-reset_timestamps", "1", "-strftime", "1",
        str(CLIPS / "%Y-%m-%d_%H-%M-%S.mp4"),
        # ...and a still, four times a second, for the picture in
        # picture. HLS would be the better picture and Chromium cannot
        # play it without a library nothing here vendors - and the
        # tablet WebView is the same engine. A JPEG in an <img> plays
        # on every surface in this house with no library at all, which
        # for a corner-of-the-screen preview is the right trade.
        #
        # It is rewritten in place, so a reader can catch it half
        # written. The door that serves it checks for the end-of-image
        # marker and hands back the last whole frame instead.
        "-map", "0:v", "-vf", "fps=4", "-q:v", "6",
        "-f", "image2", "-update", "1", "-y", str(OUT / "frame.jpg"),
        # ...and the packets themselves, as the muxer makes them, for the
        # TS door below. UDP to localhost, and that is the whole design:
        # a sendto() that nobody is listening for costs nothing and waits
        # for nobody, so a viewer that is absent, slow or gone can never
        # hold up THIS process - the one writing the clips and the HLS.
        # A pipe or an HTTP -listen output here would let it. pkt_size
        # 1316 is seven TS packets a datagram, the number the door splits
        # on; -muxdelay/-muxpreload 0 so the muxer holds nothing back;
        # PAT/PMT every 0.1 s so a joiner is never far from its tables.
        "-map", "0:v", "-c", "copy",
        "-f", "mpegts", "-muxdelay", "0", "-muxpreload", "0",
        "-mpegts_flags", "+resend_headers", "-pat_period", "0.1",
        "udp://%s:%d?pkt_size=1316" % (TS_UDP_HOST, TS_UDP_PORT),
    ]


# ---------------------------------------------------------------------------
# THE TS DOOR: the picture as it arrives, over plain HTTP.
#
# HLS is two-second files and a playlist that lists them once they are
# finished, so the soonest any viewer can see a frame that way is a
# segment and a half after it happened - and the tablet, which buffers
# on top, sits four to six seconds behind the camera. The recorder cannot
# be made faster: a segment is a file, and a file has to be closed before
# it can be listed. So the same ffmpeg gets a FOURTH output - the MPEG-TS
# packets exactly as the muxer makes them, nothing re-encoded - and this
# door hands them to whoever asks. A decoder fed from here is one keyframe
# (0.5 s) behind the camera plus whatever it chooses to buffer itself.
#
# Why UDP, and why only to localhost. ffmpeg writes this output with a
# sendto() to 127.0.0.1 and never waits for anybody: if nothing is
# listening, or the listener is slow, the kernel drops the datagram and
# the muxer moves on. A pipe or an HTTP `-listen` output would do the
# opposite - one absent or stalled viewer would hold the muxer, and the
# muxer is the same process that writes the clips and the HLS the house
# watches. The recorder must never be at the mercy of a viewer, and UDP
# is the transport that cannot push back. Localhost, so nothing outside
# this machine can put packets into the ring. Nothing here goes near the
# camera: the door reads ffmpeg, never the RTSP.
#
# Each datagram is seven 188-byte TS packets (pkt_size=1316). They go
# into a ring of about three seconds. A client joining is started at the
# last PAT/PMT before the newest keyframe, so a decoder gets its tables
# and then a picture it can decode within half a second. A client that
# falls behind by more than the ring is dropped, not handed a hole.
#
# Bound to the LAN and tailnet addresses by NAME, never 0.0.0.0: the
# station's public door (:8097) must never be able to reach this by
# accident, and a bind to every interface is how that would happen.
# ---------------------------------------------------------------------------
TS_UDP_HOST, TS_UDP_PORT = "127.0.0.1", 18081
TS_HTTP_PORT = 8098
TS_HTTP_ADDRS = ("10.89.1.246", "100.74.95.59")   # LAN, tailnet; never 0.0.0.0
TS_RING_PACKETS = 7500      # ~3 s at 2,500 pkt/s; this stream is ~1,100 pkt/s
TS_FRESH_S = 5.0            # no datagram for this long = there is no stream
TS_KEY_WAIT_S = 3.0         # how long a new client waits for a keyframe
_TS_DOOR: list = [None]


def _ts_log(msg: str) -> None:
    print("TsDoor: " + msg, flush=True)


class TsDoor:
    """UDP in from ffmpeg on localhost, HTTP out to the house. See above.

    Started once, before the recorder's loop, and never restarted: ffmpeg
    comes and goes underneath it and the ring simply pauses and refills.
    """

    def __init__(self, udp=(TS_UDP_HOST, TS_UDP_PORT), port=TS_HTTP_PORT,
                 addrs=TS_HTTP_ADDRS, ring=TS_RING_PACKETS):
        self.udp, self.port, self.addrs = tuple(udp), port, tuple(addrs)
        self.cond = threading.Condition()   # guards everything below
        self.ring: deque = deque(maxlen=ring)
        self.marks: deque = deque(maxlen=ring // 4)   # (t, seq) per datagram
        self.seq = 0            # the number the NEXT packet gets
        self.pat_seq = None     # newest PAT packet
        self.key_seq = None     # the PAT at or before the newest keyframe
        self.packets = self.nbytes = self.datagrams = 0
        self.last_rx = 0.0
        self.clients = 0
        self.bound: list = []
        self.sock = None
        _TsHandler.door = self

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 4 MB asked for; the kernel caps it at net.core.rmem_max, and
        # the size it actually gave is logged so a small one is visible.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        sock.bind(self.udp)
        self.sock = sock
        _ts_log("listening on udp://%s:%d (rcvbuf %d)" % (
            self.udp[0], self.udp[1],
            sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)))
        for name, target in (("udp", self._listen), ("bind", self._bind)):
            threading.Thread(target=target, daemon=True,
                             name="tsdoor-" + name).start()

    # -- in ----------------------------------------------------------------
    def _listen(self) -> None:
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError as err:
                _ts_log("udp recv failed: %s" % err)
                time.sleep(1.0)
                continue
            self._take(data, time.monotonic())

    def _take(self, data: bytes, now: float) -> None:
        with self.cond:
            for i in range(0, len(data) - 187, 188):
                p = data[i:i + 188]
                if p[0] != 0x47:
                    continue                # not a TS packet; never ours
                pid = (p[1] & 0x1F) << 8 | p[2]
                if pid == 0:
                    self.pat_seq = self.seq
                elif (pid >= 0x20 and p[3] & 0x20 and p[4] > 0
                      and p[5] & 0x40):
                    # random_access_indicator on the video PID: a
                    # keyframe starts here. The tables that came just
                    # before it are where a new client begins.
                    self.key_seq = (self.pat_seq if self.pat_seq is not None
                                    else self.seq)
                self.ring.append(p)
                self.seq += 1
                self.packets += 1
            self.nbytes += len(data)
            self.datagrams += 1
            self.last_rx = now
            self.marks.append((now, self.seq))
            self.cond.notify_all()

    # -- out ---------------------------------------------------------------
    def fresh(self, now: float | None = None) -> bool:
        return (self.last_rx > 0
                and (now or time.monotonic()) - self.last_rx < TS_FRESH_S)

    def start_cursor(self, wait_s: float) -> int | None:
        """Where a new client begins: the PAT/PMT just before the newest
        keyframe - if the feed is alive and it is still in the ring."""
        deadline = time.monotonic() + wait_s
        with self.cond:
            while True:
                if (self.key_seq is not None and self.fresh()
                        and self.key_seq >= self.seq - len(self.ring)):
                    return self.key_seq
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self.cond.wait(left)

    def read(self, cursor: int, wait_s: float) -> tuple[bytes, int, bool]:
        """Every packet from `cursor` on: (data, new cursor, lost).
        `lost` is a cursor that has fallen out of the ring - the client
        is slower than the stream and must be dropped, not fed a hole."""
        with self.cond:
            if self.seq <= cursor:
                self.cond.wait(wait_s)
            n = self.seq - cursor
            if n <= 0:
                return b"", cursor, False
            if n > len(self.ring):
                return b"", cursor, True
            # The last n packets, taken from the right: O(n), not O(ring).
            parts = list(itertools.islice(reversed(self.ring), n))
            parts.reverse()
            return b"".join(parts), self.seq, False

    def count(self, delta: int) -> int:
        with self.cond:
            self.clients += delta
            return self.clients

    def stats(self) -> dict:
        with self.cond:
            now = time.monotonic()
            floor = self.seq - len(self.ring)
            span = 0.0
            for t, s in self.marks:        # the oldest datagram still held
                if s > floor:
                    span = self.marks[-1][0] - t
                    break
            return {
                "ok": self.fresh(now), "clients": self.clients,
                "packets": self.packets, "bytes": self.nbytes,
                "datagrams": self.datagrams,
                "last_rx_age_s": (round(now - self.last_rx, 2)
                                  if self.last_rx else None),
                "ring_packets": len(self.ring), "ring_s": round(span, 2),
                "have_key": (self.key_seq is not None
                             and self.key_seq >= floor),
                "port": self.port, "bound": list(self.bound),
            }

    def summary(self) -> dict:
        """The block say() carries: where the door is, whether it is fed."""
        s = self.stats()
        urls = ["http://%s:%d/live.ts" % (a, self.port) for a in self.addrs]
        return {"port": self.port, "path": "/live.ts",
                "url": urls[0] if urls else "",
                "tail_url": urls[1] if len(urls) > 1 else "",
                "ok": s["ok"], "clients": s["clients"],
                "ring_s": s["ring_s"], "bound": s["bound"]}

    # -- the http side -----------------------------------------------------
    def _bind(self) -> None:
        """Bind each address; one that is not there yet (the tailnet
        after a boot) is retried every 30 s and picked up when it is."""
        want = list(self.addrs)
        while want:
            for addr in list(want):
                try:
                    srv = _TsHTTP((addr, self.port), _TsHandler)
                except OSError as err:
                    _ts_log("cannot bind %s:%d (%s) - retrying every 30 s"
                            % (addr, self.port, err))
                    continue
                threading.Thread(target=srv.serve_forever, daemon=True,
                                 name="tsdoor-http-" + addr).start()
                with self.cond:
                    self.bound.append(addr)
                want.remove(addr)
                _ts_log("serving http://%s:%d/live.ts" % (addr, self.port))
            if want:
                time.sleep(30.0)


class _TsHTTP(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        # A client going away mid-body is not an error worth a traceback.
        if not isinstance(sys.exc_info()[1], OSError):
            super().handle_error(request, client_address)


class _TsHandler(BaseHTTPRequestHandler):
    # HTTP/1.0: no Content-Length and no chunking - the body is as long
    # as the socket stays open, which is what a live stream is.
    protocol_version = "HTTP/1.0"
    timeout = 10.0          # a peer that stops reading is dropped, not held
    door: TsDoor | None = None

    def log_message(self, *_a) -> None:
        pass                # one line per join and leave is plenty

    def log_error(self, fmt, *a) -> None:
        _ts_log("http %s: %s" % (self.client_address[0], fmt % a))

    def _reply(self, code: int, body: bytes,
               ctype: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        door, path = self.door, self.path.split("?", 1)[0]
        if door is None:
            self._reply(503, b"no door\n")
        elif path == "/live.ts":
            self._live(door)
        elif path == "/state":
            self._reply(200, json.dumps(door.stats()).encode() + b"\n",
                        "application/json")
        elif path == "/health":
            ok = door.fresh()
            self._reply(200 if ok else 503, b"ok\n" if ok else b"no stream\n")
        else:
            self._reply(404, b"not found\n")

    def _live(self, door: TsDoor) -> None:
        cur = door.start_cursor(TS_KEY_WAIT_S)
        if cur is None:
            self._reply(503, b"no keyframe yet\n")
            return
        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        who = "%s:%d" % self.client_address[:2]
        _ts_log("client %s joined (%d watching)" % (who, door.count(+1)))
        try:
            while True:
                data, cur, lost = door.read(cur, 1.0)
                if lost:
                    _ts_log("client %s too slow - dropped" % who)
                    break
                if data:
                    self.wfile.write(data)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                # the viewer left; nothing to say
        finally:
            _ts_log("client %s left (%d watching)" % (who, door.count(-1)))


def supervise(once: bool = False) -> None:
    global CLIPS                                          # #1118
    if not station_safe():
        say("refused", why="%s is not holding 10.89.1.246 - refusing to "
            "touch the radios" % STATION_IF)
        print("REFUSING: the station's radio is not where it should be.")
        sys.exit(2)
    LIVE.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    # The TS door opens once, here, and is never restarted: ffmpeg comes
    # and goes underneath it. A door that cannot open must not cost the
    # recorder anything - the clips and the HLS come first.
    try:
        _TS_DOOR[0] = TsDoor()
        _TS_DOOR[0].start()
    except Exception as err:  # noqa: BLE001
        _TS_DOOR[0] = None
        _ts_log("not started (%s) - the recorder runs without it" % err)

    while True:
        _LAST_SEEN.update(seen_on_air())
        # #1349: and why not, when it is not. Cheap - the scan above
        # has already been paid for - and it is the difference between
        # a surface that says 'not found' and one that says which of
        # the three reasons it is.
        # #1250b: NOT BEFORE EVERY RETRY. A rescan takes the spare
        # radio off channel for about twenty-three seconds, and the
        # old loop paid it on every pass - so a camera that dropped at
        # thirty seconds was off the air for another third of every
        # minute on top, to answer a question nobody had asked (we
        # were already joined). Scan when there is a reason to, or
        # every five minutes.
        if (not linked()) or (time.time() - _DOCTOR[0] > DOCTOR_EVERY_S):
            try:
                doc = doctor()
                doc['at'] = time.time()
                _LAST_SEEN['doctor'] = doc
                _DOCTOR[0] = time.time()
            except Exception:  # noqa: BLE001
                pass
        if not join():
            say("no-link", why="the camera's network is not being "
                "broadcast, or the join failed")
            if once:
                return
            time.sleep(15)
            continue
        if not camera_awake():
            say("linked-quiet", why="joined, but the camera is not "
                "streaming yet")
            if once:
                return
            time.sleep(8)
            continue

        # #1118: the folder may have been moved since the last start.
        CLIPS = clips_dir()
        CLIPS.mkdir(parents=True, exist_ok=True)
        trimmed = trim_old()
        say("live", pid=0, trimmed=trimmed,
            hls="data/pinelink/live/index.m3u8")
        print("PineLink live: %s -> %s" % (RTSP, LIVE))
        began = time.time()                                   # #1250b
        proc = subprocess.Popen(ffmpeg_cmd(), stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True)
        _STREAM["transport"] = rtsp_transport()               # #1250b
        say("live", pid=proc.pid, hls="data/pinelink/live/index.m3u8")
        # #1388: WATCH THE FRAMES, NOT THE PIPE.
        #
        # proc.communicate() blocks until ffmpeg exits, and an ffmpeg on a
        # dead RTSP link did not exit - so this loop stood still for 12.9
        # hours with state.json saying 'live' and `at` from the night
        # before. The station's readers were honest about it (fresh=False)
        # and the desktop's row was not, but the fault was here: a
        # supervisor that cannot see its own child has stopped supervising.
        #
        # frame.jpg is rewritten four times a second while the stream is
        # alive, so its mtime IS the heartbeat. No new frame for
        # FRAME_STALL_S seconds with ffmpeg still running means the link
        # is gone: kill it, say so, and go back to looking. The heartbeat
        # is also written into the state every pass, so `fresh` means
        # what it says while a stream is healthy.
        err = ""
        last_frame = time.time()
        stalled = False
        try:
            while proc.poll() is None:
                time.sleep(2.5)
                try:
                    m = (OUT / "frame.jpg").stat().st_mtime
                    if m > last_frame:
                        last_frame = m
                except OSError:
                    pass
                if time.time() - last_frame > FRAME_STALL_S:
                    stalled = True
                    proc.kill()
                    break
                say("live", pid=proc.pid, hls="data/pinelink/live/index.m3u8",
                    frame_age=round(time.time() - last_frame, 1))
            try:
                _, err = proc.communicate(timeout=10)
            except Exception:  # noqa: BLE001
                err = ""
        except KeyboardInterrupt:
            proc.terminate()
            say("stopped", why="asked to stop")
            return
        if stalled:
            err = (err or "") + "\nno new frame for %ds - the link is gone; ffmpeg killed (#1388)" % int(FRAME_STALL_S)
        # #1250b: THE LAST LINE IS THE ANSWER, and it was the one
        # thing thrown away. `tail[:400]` took four lines and then
        # cut them from the FRONT, so a surface was handed the two
        # start-up warnings and never the line that said the session
        # had been closed. Classify first, keep the real last line
        # whole, and count the noise instead of printing it.
        life = time.time() - began
        fault = stream_fault(err, life, stalled)
        lives = ([float(x) for x in (_STREAM.get("lives") or [])][-7:]
                 + [round(life, 1)])
        _STREAM.clear()
        _STREAM.update(fault)
        _STREAM["lives"] = lives
        # A transport that cannot hold a stream for TRANSPORT_GOOD_S
        # is the wrong transport. Do not rotate on a run that never
        # started: that says nothing about transports.
        if 2.0 <= life < TRANSPORT_GOOD_S:
            _TRANSPORT[0] += 1
            _STREAM["next_transport"] = rtsp_transport()
        rest = [x.strip() for x in (err or "").splitlines() if x.strip()
                and not any(n in x for n in STREAM_NOISE)][-4:-1]
        why = fault["say"]
        if fault["exit"]:
            why += " | " + fault["exit"]
        if rest:
            why += "\n" + "\n".join(rest)[:300]
        say("dropped", why=why[:600])
        print("PineLink dropped after %.0fs (%s): %s"
              % (life, fault["class"], fault["say"]))
        if once:
            return
        time.sleep(RESTART_REST)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="one attempt, then exit (for testing)")
    ap.add_argument("--status", action="store_true")
    # #1359b: the two answers the station asks for by name. Both are
    # root operations on the spare radio and neither can be done from
    # inside the container, so the station shells out to this.
    ap.add_argument("--doctor", action="store_true")
    ap.add_argument("--reset-radio", action="store_true")
    args = ap.parse_args()
    if args.doctor:
        print(json.dumps(doctor()))
        return
    if args.reset_radio:
        print(json.dumps(radio_reset()))
        return
    if args.status:
        try:
            print(STATE.read_text())
        except Exception:  # noqa: BLE001
            print('{"state": "never-run"}')
        return
    supervise(once=args.once)


if __name__ == "__main__":
    main()
