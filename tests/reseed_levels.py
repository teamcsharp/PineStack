"""[levels-one] re-seed the one set from the PineTab's own levels (the desk seeded it
first with its app volume as the master - 0 - which is that computer's output,
not the station's). Run in the container:  python tests/reseed_levels.py"""
import json
import os
import urllib.request

H = {"Authorization": "Bearer " + os.environ.get("SPARK_AGENT_API_KEY", ""), "Content-Type": "application/json"}
tab = {"master": 1.0, "voice": 0.9918, "music": 0.3023, "sfx": 1.0, "video": 1.0, "pads": 1.0}
req = urllib.request.Request("http://127.0.0.1:8096/api/levels", method="POST", headers=H,
                             data=json.dumps({"levels": tab, "by": "reseeded from the PineTab"}).encode())
print(json.dumps(json.load(urllib.request.urlopen(req, timeout=30))["levels"]))
