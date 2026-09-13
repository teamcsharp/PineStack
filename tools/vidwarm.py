import sys, time, json, urllib.request
# ask the SERVER, not a second process
d = json.load(urllib.request.urlopen("http://10.89.1.246:8096/api/dj", timeout=40))
f = d.get("dialogue_flow") or {}
print("pool from dj:", str(f.get("sfx") or "")[:80])
