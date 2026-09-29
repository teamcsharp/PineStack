"""[pinestream] the desk: main.js wires pinestream-push.cjs to the
`pinestream:push` IPC channel, preload.js exposes pineDesktop.pineStream(verb,
opts), index.html loads renderer/pinestream.js after pinelive.js. The new
files (desktop/pinestream-push.cjs, desktop/renderer/pinestream.js) are
installed by install_pinestream_files.py.

    python edit_pinestream_desk.py --check|--apply <spark-agent root>
--apply runs `node --check` on main.js and preload.js and counts the
`pinestream:push` handlers (two handlers on one channel throw at startup).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from patchlib import Insert, main  # noqa: E402

M = "desktop/main.js"
P = "desktop/preload.js"
H = "desktop/renderer/index.html"

EDITS = [
    Insert(M, 'ipcMain.handle("pinestream:push"',
           'ipcMain.handle("open:external", (_event, url) => shell.openExternal(url));\n',
           '/* [pinestream] PineStream: this window, a few JPEGs a second, to the station -\n'
           ' * only while renderer/pinestream.js keeps saying `run` and the station keeps\n'
           ' * answering keep. See pinestream-push.cjs. */\n'
           'const { PineStreamPush } = require("./pinestream-push.cjs");\n'
           'const pineStreamPush = new PineStreamPush({\n'
           '  getWin: () => win,\n'
           '  baseUrl: () => readConfig().baseUrl,\n'
           '  headers: () => authHeaders(),\n'
           '});\n'
           'ipcMain.handle("pinestream:push", (_event, verb, opts) => pineStreamPush.verb(String(verb || "state"), opts || {}));\n'),
    Insert(P, 'pineStream: (verb, opts)',
           '  openExternal: (url) => ipcRenderer.invoke("open:external", url),\n',
           '  /* [pinestream] run | stop | state - see desktop/pinestream-push.cjs */\n'
           '  pineStream: (verb, opts) => ipcRenderer.invoke("pinestream:push", verb, opts),\n'),
    Insert(H, '<script src="./pinestream.js"></script>',
           '  <script src="./pinelive.js"></script>\n',
           '  <script src="./pinestream.js"></script>  <!-- [pinestream] this window on the listeners\' page -->\n'),
]


def verify(root: Path):
    for rel in (M, P):
        got = subprocess.run(["node", "--check", str(root / rel)], capture_output=True, text=True)
        if got.returncode != 0:
            return False, "node --check %s: %s" % (rel, got.stderr[-500:])
    n = (root / M).read_text(encoding="utf-8").count('ipcMain.handle("pinestream:push"')
    if n != 1:
        return False, "main.js has %d pinestream:push handlers" % n
    return True, "node --check main.js, preload.js ok; one pinestream:push handler"


if __name__ == "__main__":
    sys.exit(main(EDITS, after_apply=verify))
