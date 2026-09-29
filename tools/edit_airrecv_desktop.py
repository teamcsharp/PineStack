#!/usr/bin/env python3
"""[airplayers] the desktop: the Playing it card becomes the receivers switch.

TARGET: desktop/renderer/renderer.js, desktop/renderer/index.html,
        desktop/renderer/air-receivers.js (new), desktop/renderer/air-receivers.css (new)
usage: edit_airrecv_desktop.py --check|--apply <repo root>

The new files are desktop-only on purpose: deploy.sh syncs pine-views as the
INTERSECTION with desktop/renderer, and the tablet's drawer is native.
"""
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from patchlib_air import run  # noqa: E402

GAG_OLD = '''    window.__pineGagged = !!(clock && clock.audio_owner)
      && clock.audio_owner !== desktopListenerId;
'''
GAG_NEW = '''    /* [airplayers:shell] ...and a shell whose receiver is switched off in
     * Playing it is hushed by the same clock, like the panel beside it. */
    window.__pineGagged = !!(clock && clock.hushed)
      || (!!(clock && clock.audio_owner)
          && clock.audio_owner !== desktopListenerId);
'''

CSS_ANCHOR = '''  <link rel="stylesheet" href="./styles.css">
'''
CSS_LINK = '''  <link rel="stylesheet" href="./air-receivers.css"><!-- [airplayers:css] -->
'''
JS_ANCHOR = '''  <script src="./lcd.js"></script>
'''
JS_TAG = '''  <script src="./air-receivers.js"></script><!-- [airplayers:js] -->
'''

NEW_FILES = ("air-receivers.js", "air-receivers.css")


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


def main(argv):
    if len(argv) != 2 or argv[0] not in ("--check", "--apply"):
        print("usage: --check|--apply <repo root>")
        return 64
    mode, root = argv
    codes = [
        run("desktop/renderer/renderer.js",
            [("[airplayers:shell]", GAG_OLD, GAG_NEW, "replace", 1)], argv),
        run("desktop/renderer/index.html",
            [("[airplayers:css]", CSS_ANCHOR, CSS_LINK, "after", 1),
             ("[airplayers:js]", JS_ANCHOR, JS_TAG, "after", 1)], argv),
    ]
    for name in NEW_FILES:
        src = os.path.join(HERE, name)
        dst = os.path.join(root, "desktop", "renderer", name)
        if os.path.exists(dst) and sha(dst) == sha(src):
            print("desktop/renderer/%s: APPLIED" % name)
            codes.append(2)
        elif os.path.exists(dst):
            print("desktop/renderer/%s: MISSING (a different file is there)" % name)
            codes.append(1)
        elif mode == "--check":
            print("desktop/renderer/%s: READY (new file)" % name)
            codes.append(0)
        else:
            shutil.copyfile(src, dst)
            print("desktop/renderer/%s: APPLIED (new file)" % name)
            codes.append(0)
    if 1 in codes or 64 in codes:
        return 1
    return 2 if all(c == 2 for c in codes) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
