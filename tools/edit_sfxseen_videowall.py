r"""[sfxseen] PineVideoWall.kt reports what reached the glass, through the
state() the page already fetches every poll (sfx-tv.js wallFollow) - no new
bridge method, no new traffic.

  app/src/main/java/com/pinebox/kiosk/video/PineVideoWall.kt
  (the kiosk repo C:\_tools\pinebox-android\PineBoxKiosk and the mainline copy)

state() gains:
  shown_since      wall ms the current item became current (onMediaItemTransition)
  first_frame_id   the item ExoPlayer rendered a first frame for (onRenderedFirstFrame,
  first_frame_at   which fires per stream change), and when (wall ms)
  frames_rendered  decoder rendered/dropped output buffers since the item began
  frames_dropped   (sampled by the 1 s watchdog on the main thread)
  surface_w/_h     the SurfaceView's own size - "the native surface at 0x0"
  visible          isShown, VISIBLE and bigger than 1x1
  screen_on        PowerManager.isInteractive - a sleeping display shows nobody anything
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfxseen_lib import Edit, run  # noqa: E402

FIELDS = '''    /* [sfxseen] WHAT REACHED THE GLASS. `playing` says which item the
     * playlist is on, never whether a frame of it was drawn. The page's
     * display receipt (sfx-seen.js) reads these through state(): the first
     * frame ExoPlayer rendered for the item, when the item became current,
     * the decoder's rendered/dropped counts since, and whether anybody could
     * see it - the surface's own size and visibility, and the display. */
    @Volatile private var seenSince: Long = 0L
    @Volatile private var firstFrameId: String = ""
    @Volatile private var firstFrameAt: Long = 0L
    @Volatile private var framesRendered: Int = 0
    @Volatile private var framesDropped: Int = 0
    private var rendered0 = 0
    private var dropped0 = 0

    private fun seenMark(p: ExoPlayer) {                      // [sfxseen] main thread
        seenSince = System.currentTimeMillis()
        val c = p.videoDecoderCounters
        rendered0 = c?.renderedOutputBufferCount ?: 0
        dropped0 = (c?.droppedBufferCount ?: 0) + (c?.skippedOutputBufferCount ?: 0)
        framesRendered = 0
        framesDropped = 0
    }

    private fun seenCount(p: ExoPlayer) {                     // [sfxseen] the watchdog's tick
        val c = p.videoDecoderCounters ?: return
        framesRendered = (c.renderedOutputBufferCount - rendered0).coerceAtLeast(0)
        framesDropped = (c.droppedBufferCount + c.skippedOutputBufferCount - dropped0).coerceAtLeast(0)
    }

    private fun screenOn(): Boolean = try {                   // [sfxseen]
        (context.getSystemService(Context.POWER_SERVICE) as? android.os.PowerManager)?.isInteractive ?: true
    } catch (err: Throwable) { true }

'''

STATE = '''        .put("shown_since", seenSince)                       // [sfxseen] below: what reached the glass
        .put("first_frame_id", firstFrameId)
        .put("first_frame_at", firstFrameAt)
        .put("frames_rendered", framesRendered)
        .put("frames_dropped", framesDropped)
        .put("surface_w", screen.width)
        .put("surface_h", screen.height)
        .put("visible", isShown && visibility == View.VISIBLE && screen.width > 1 && screen.height > 1)
        .put("screen_on", screenOn())
'''

EDITS = [
    Edit("fields", '    @Volatile private var lastRepair: String = ""\n', "\n" + FIELDS.rstrip("\n") + "\n"),
    Edit("state", '        .put("last_repair", lastRepair)\n', STATE),
    Edit("transition", '                showing = listed.getOrNull(at)?.id ?: ""\n',
         '                seenMark(p)                                  // [sfxseen]\n'),
    Edit("first-frame", '            override fun onPlayerError(error: PlaybackException) {\n',
         '            /* [sfxseen] fired per stream change: a frame of THIS item was drawn */\n'
         '            override fun onRenderedFirstFrame() {\n'
         '                firstFrameAt = System.currentTimeMillis()\n'
         '                firstFrameId = listed.getOrNull(p.currentMediaItemIndex)?.id ?: showing\n'
         '            }\n\n', where="before"),
    Edit("count", '        atDuration = p.duration\n', '        seenCount(p)                                        // [sfxseen]\n'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS))
