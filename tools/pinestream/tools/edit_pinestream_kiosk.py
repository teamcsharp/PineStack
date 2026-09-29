"""[pinestream] the kiosk: the native pusher (replay/PineStreamPush.kt), the
bridge verb pineDesktop.pineStream(run|stop|state, opts), the JS shim's
promise, and pinestream.js in the views bundle (after pinelive.js).

    python edit_pinestream_kiosk.py --check|--apply <PineBoxKiosk root>

Also valid against the spark-agent repo's own mirror of the kiosk
(<spark-agent>/app/src/main/...) when its anchors match. The shared
pinelive.js / pinelive.css edits are edit_pinestream_panel.py's, run on
<root>/app/src/main/assets/pine-views. No new permission: the capture uses
CAPTURE_VIDEO_OUTPUT + CAPTURE_SECURE_VIDEO_OUTPUT, already declared and
granted by the platform key (ScreenReplay's road).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from patchlib import Insert, NewFile, main  # noqa: E402

NEW = HERE.parent / "new"
B = "app/src/main/java/com/pinebox/kiosk/bridge/PineDesktopBridge.kt"
V = "app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt"
S = "app/src/main/assets/pine-bridge.js"

EDITS = [
    NewFile("app/src/main/java/com/pinebox/kiosk/replay/PineStreamPush.kt", str(NEW / "PineStreamPush.kt")),
    NewFile("app/src/main/assets/pine-views/pinestream.js", str(NEW / "pinestream.js")),
    Insert(B, '            "pineStream",\n', '            "pineCam",\n',
           '            /* [pinestream] this screen on the listeners\' page - replay/PineStreamPush.kt */\n'
           '            "pineStream",\n'),
    Insert(B, "private val pineStreamPush by lazy",
           '    @Volatile var pineCam: com.pinebox.kiosk.video.PineCamWall? = null\n',
           '\n'
           '    /* [pinestream] PineStream\'s pusher: this screen, to the station, only while\n'
           '     * the page keeps saying run and the station keeps answering keep. */\n'
           '    private val pineStreamPush by lazy {\n'
           '        com.pinebox.kiosk.replay.PineStreamPush(context, client, scope)\n'
           '    }\n'),
    Insert(B, '"pineStream" -> {',
           '        "hotCorners" -> BridgeEnvelope.ok(id, HotCorners.read(configStore).toString())\n',
           '        /* [pinestream] run (every few seconds, and the dead man\'s handle), stop,\n'
           '         * state. The answer is always the pusher\'s own state. */\n'
           '        "pineStream" -> {\n'
           '            val push = pineStreamPush\n'
           '            val opts = args.optJSONObject(1)\n'
           '            val known = when (args.optString(0, "state")) {\n'
           '                "run" -> { push.run(opts); true }\n'
           '                "stop" -> {\n'
           '                    push.stop(opts?.optString("why", "").orEmpty().ifBlank { "the page said stop" })\n'
           '                    true\n'
           '                }\n'
           '                "state" -> true\n'
           '                else -> false\n'
           '            }\n'
           '            BridgeEnvelope.ok(id, push.state().put("ok", known).toString())\n'
           '        }\n'
           '\n',
           where="before"),
    Insert(S, 'pineStream: promised("pineStream")', '    pineCam: promised("pineCam"),\n',
           '    pineStream: promised("pineStream"),   // [pinestream] run | stop | state\n'),
    Insert(V, '"pinestream.js",', '        "pinelive.js",\n',
           '        "pinestream.js",          // [pinestream] this screen on the listeners\' page (reads PineLive\'s switch)\n'),
]

if __name__ == "__main__":
    sys.exit(main(EDITS))
