"""[pinestream] the new files in the spark-agent repo:

    pinestream.py                                 the station's half (routes, one frame)
    tests/test_pinestream.py                      its tests (and pinelive's switch)
    tests/test_pinestream_push.cjs                the desk pusher's tests (node)
    desktop/pinestream-push.cjs                   the desk's capture (main process)
    desktop/renderer/pinestream.js                the screen's half (canonical)
    app/src/main/assets/pine-views/pinestream.js  the repo's kiosk mirror (identical)

    python install_pinestream_files.py --check|--apply <spark-agent root>
Run BEFORE edit_pinestream_app.py (app.py imports pinestream).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from patchlib import NewFile, main  # noqa: E402

NEW = HERE.parent / "new"

EDITS = [
    NewFile("pinestream.py", str(NEW / "pinestream.py")),
    NewFile("tests/test_pinestream.py", str(NEW / "test_pinestream.py")),
    NewFile("tests/test_pinestream_push.cjs", str(NEW / "test_pinestream_push.cjs")),
    NewFile("desktop/pinestream-push.cjs", str(NEW / "pinestream-push.cjs")),
    NewFile("desktop/renderer/pinestream.js", str(NEW / "pinestream.js")),
    NewFile("app/src/main/assets/pine-views/pinestream.js", str(NEW / "pinestream.js")),
]

if __name__ == "__main__":
    sys.exit(main(EDITS))
