#!/usr/bin/env python3
"""PineLink: the camera, held on the spare radio and served to the house.

The camera is an ACCESS POINT. Anything that wants its video has to join
`H88_<mac>`, and a device with one radio that joins it drops off the house
LAN - which for the tablet means losing the station entirely. The DGX has
two radios, so this holds the camera on the spare one (`wlx…`) while
`wlP9s9` keeps 10.89.1.246 and the broadcast. That asymmetry is the whole
reason the link lives here and not on the tablet.

One ffmpeg, one input, two outputs:

    rtsp://192.168.1.254:554/live  (h264 848x480, the preview substream)
      ├─ HLS   → data/pinelink/live/index.m3u8   what the house watches
      └─ mp4   → data/pinelink/clips/<stamp>.mp4  what is kept

Both are `-c copy`. The camera already hands over h264, so nothing is
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
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pinelink"
LIVE = OUT / "live"
CLIPS = OUT / "clips"
STATE = OUT / "state.json"

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
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "at": time.time(), "state": state, "camera": CAMERA,
            "rtsp": RTSP, "ssid": SSID, "iface": SPARE_IF,
            # #1347: so a surface can draw "the camera is there but not
            # joined yet" without being able to see a radio.
            **_LAST_SEEN, **more}, indent=2))
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


def ffmpeg_cmd() -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-rtsp_transport", "tcp",
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
    ]


def supervise(once: bool = False) -> None:
    if not station_safe():
        say("refused", why="%s is not holding 10.89.1.246 - refusing to "
            "touch the radios" % STATION_IF)
        print("REFUSING: the station's radio is not where it should be.")
        sys.exit(2)
    LIVE.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)

    while True:
        _LAST_SEEN.update(seen_on_air())
        # #1349: and why not, when it is not. Cheap - the scan above
        # has already been paid for - and it is the difference between
        # a surface that says 'not found' and one that says which of
        # the three reasons it is.
        try:
            _LAST_SEEN['doctor'] = doctor()
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

        trimmed = trim_old()
        say("live", pid=0, trimmed=trimmed,
            hls="data/pinelink/live/index.m3u8")
        print("PineLink live: %s -> %s" % (RTSP, LIVE))
        proc = subprocess.Popen(ffmpeg_cmd(), stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True)
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
        tail = "\n".join((err or "").strip().splitlines()[-4:])
        # An ffmpeg that exits is not an error to swallow: the camera
        # sleeps, wanders out of range, or its battery goes. Say which,
        # as far as can be told, and try again.
        say("dropped", why=tail[:400] or "the stream ended")
        print("PineLink dropped: %s" % (tail[:200] or "stream ended"))
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
