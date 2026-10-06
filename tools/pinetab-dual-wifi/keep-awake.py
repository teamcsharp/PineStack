"""Keep the H88 secondary STA awake and its gateway neighbor stable.

Android's WifiLock applies to the primary STA. The H88 stops delivering RTP
when the secondary STA dozes. Run on Spark; reconnects after tablet reboots.
The gateway pin avoids this ROM's false IP reachability failure after ARP GC.
"""
import os
import subprocess
import time
from pathlib import Path

runtime = Path.home() / '.local/share/pinecam-adb/root'
adb = str(runtime / 'usr/bin/adb')
env = dict(os.environ, LD_LIBRARY_PATH=str(runtime / 'usr/lib/aarch64-linux-gnu/android'),
           ADB_SERVER_PORT='5039')
device = '10.89.1.154:5555'
camera_ssid = 'H88_5c8e8bddfab1'
camera_mac = '5c:8e:8b:dd:fa:b1'
camera_ip = '192.168.1.254'


def run(*args):
    result = subprocess.run([adb, '-P', '5039', *args], env=env,
                            capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


last = ''
while True:
    interval = 5
    try:
        run('connect', device)
        if 'uid=0' not in run('-s', device, 'shell', 'id'):
            run('-s', device, 'root')
            time.sleep(2)
            run('connect', device)
        # Never alter the primary interface, or a secondary used by another AP.
        link = run('-s', device, 'shell', 'iw', 'dev', 'wlan1', 'link')
        if (f'SSID: {camera_ssid}' in [line.strip() for line in link.splitlines()]
                and f'Connected to {camera_mac} (on wlan1)' in link):
            interval = 1
            # This ROM treats a gateway relearned from null as a MAC change,
            # rebuilding the IP link at its ten-minute neighbor cleanup.
            # Pin only this known camera on its own secondary interface.
            neighbor = run('-s', device, 'shell', 'ip', 'neigh', 'show',
                           camera_ip, 'dev', 'wlan1')
            if f'lladdr {camera_mac} PERMANENT' not in neighbor:
                run('-s', device, 'shell', 'ip', 'neigh', 'replace', camera_ip,
                    'lladdr', camera_mac, 'nud', 'permanent', 'dev', 'wlan1')
                print('PineCam gateway neighbor pinned on secondary Wi-Fi', flush=True)
            power = run('-s', device, 'shell', 'iw', 'dev', 'wlan1', 'get', 'power_save')
            if power == 'Power save: on':
                run('-s', device, 'shell', 'iw', 'dev', 'wlan1', 'set', 'power_save', 'off')
                print('PineCam secondary Wi-Fi power saving disabled', flush=True)
            status = 'camera link awake'
        else:
            neighbor = run('-s', device, 'shell', 'ip', 'neigh', 'show',
                           camera_ip, 'dev', 'wlan1') if 'Connected to ' in link else ''
            if f'lladdr {camera_mac} PERMANENT' in neighbor:
                run('-s', device, 'shell', 'ip', 'neigh', 'del', camera_ip, 'dev', 'wlan1')
            status = 'waiting for camera link'
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        status = str(error)
    if status != last:
        print(status, flush=True)
        last = status
    time.sleep(interval)
