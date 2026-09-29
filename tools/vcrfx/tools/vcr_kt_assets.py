"""[vcrfx] the kiosk injects pine-vcr.js into both of its pages, and deploy.sh
keeps the sampler's copy in step with desktop/renderer.

    python vcr_kt_assets.py --check|--apply <ViewAssets.kt>
    python vcr_kt_assets.py --check|--apply <SamplerAssets.kt>
    python vcr_kt_assets.py --check|--apply <deploy.sh>
TARGET: ViewAssets.kt, SamplerAssets.kt, deploy.sh (picked by file name)
"""
import os
import sys

from _vcrlib import Edit, main

VIEW = [
    Edit("view-script", '"pine-vcr.js",             // [vcrfx]',
         """        "pine-logo.js",           // the mark, inline - origins forbid a URL
""",
         """        "pine-vcr.js",             // [vcrfx] the one picture on/off effect (the SFX TV's CRT)
        "pine-logo.js",           // the mark, inline - origins forbid a URL
"""),
]
SAMPLER = [
    Edit("sampler-script", '"pine-vcr.js",         // [vcrfx]',
         """        "wall-transition.js",
        "sfx-tv.js",
""",
         """        "pine-vcr.js",         // [vcrfx] the CRT on/off sfx-tv.js plays
        "wall-transition.js",
        "sfx-tv.js",
"""),
]
DEPLOY = [
    Edit("deploy-sync", "for asset in sfx-tv.js sfx-tv.css pine-vcr.js; do",
         """  for asset in sfx-tv.js sfx-tv.css; do
""",
         """  for asset in sfx-tv.js sfx-tv.css pine-vcr.js; do
"""),
]

if __name__ == "__main__":
    name = os.path.basename(sys.argv[-1]) if len(sys.argv) > 1 else ""
    table = {"ViewAssets.kt": VIEW, "SamplerAssets.kt": SAMPLER, "deploy.sh": DEPLOY}.get(name)
    if table is None:
        print("unknown target %r (ViewAssets.kt, SamplerAssets.kt or deploy.sh)" % name)
        raise SystemExit(64)
    raise SystemExit(main(table))
