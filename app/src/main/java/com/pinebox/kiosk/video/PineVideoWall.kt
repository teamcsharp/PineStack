package com.pinebox.kiosk.video

import android.content.Context
import android.net.Uri
import android.os.Looper
import android.util.Log
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import com.pinebox.kiosk.net.StationClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * THE ENDLESS SET, PLAYED BY THE DEVICE, AS ONE PLAYLIST.
 *
 * WHY THE PICTURE IS NOT IN THE PAGE. Measured on the tablet while it was
 * stuttering, with the page's own whole-clip pre-fetch already deployed:
 *
 *     buffered ahead of the playhead   9.5 s
 *     stalls / re-buffers / waits      0 / 0 / 0
 *     ping to the station              2-5 ms
 *     and still                        21-40% of frames DROPPED
 *
 * The delivery was never the fault. `droppedVideoFrames` counts frames
 * DECODED BUT NEVER PRESENTED, and the page could not present them: it
 * renders at 8-12 fps whatever is in it - measured with the entire panel
 * hidden, every decorative decoder released, and one 427x240 clip alone
 * on an otherwise empty document. No arrangement of HTML was ever going
 * to fix that, so the picture lives on a SurfaceView that SurfaceFlinger
 * composites straight from its own buffer queue. The WebView may jank as
 * badly as it likes above it.
 *
 * WHY ONE PLAYER AND NOT TWO. The first cut leapfrogged two MediaPlayers
 * across two SurfaceViews so the next clip was decoded and waiting.
 * Deciding which surface you SAW turned out to be impossible to do
 * reliably: bringToFront re-orders the View and SurfaceFlinger ignores it
 * for a media-overlay layer, and alpha is not honoured on one either. The
 * operator got two pictures - "a clip in a window i cant interact with
 * and another clip that is frozen behind it". Collapsing to ONE surface
 * cured that and cost a 200-340 ms hole at every join, because a
 * MediaPlayer may not take a surface until the outgoing one has let go.
 *
 * ExoPlayer holds a PLAYLIST against a single surface and performs the
 * transition itself, with the next item's decoder already warm. One
 * player, one surface, and no hand-over of my own left to get wrong.
 * That is the whole reason media3 is a dependency now.
 *
 * IT DOES NOT STREAM. Every clip is pulled down WHOLE to the cache first
 * and the playlist points at local files, so nothing about playing one
 * can wait on the network. At a median 0.60 MB that costs nothing and
 * removes the entire class of fault.
 *
 * IT DOES NOT CHASE THE STATION'S CLOCK. #1173 put a clip's position
 * under a station clock so two surfaces would show the same frame, and
 * #1421 had to bound it because holding a clip there re-seeked it
 * mid-picture. A wall whose whole job is to be perpetual has no business
 * seeking.
 *
 * AND IT DOES NOT EAT TOUCHES. It lies over the WebView and the operator
 * reaches the panel through it. The page's own CRT set is not just a
 * picture - it drags, it closes, it carries the pad button and the hold
 * sheet - and a native surface has none of that and must not pretend to.
 */
@UnstableApi
class PineVideoWall(
    context: Context,
    private val client: StationClient,
    private val scope: CoroutineScope,
) : FrameLayout(context) {

    private data class Clip(val id: String, val file: File)

    /* THE one surface. Media-overlay so it sits over the WebView and
     * under this app's own chrome. */
    private val screen = SurfaceView(context).apply { setZOrderMediaOverlay(true) }

    private var player: ExoPlayer? = null
    private val running = AtomicBoolean(false)
    @Volatile private var veiled = false
    private var pump: Job? = null

    /** What is in the playlist, in the player's own index order. */
    private val listed = ArrayList<Clip>()

    /** Ids already put in the playlist, so the ring's repeats are skipped. */
    private val rung = ArrayDeque<String>()

    @Volatile private var showing: String = ""
    @Volatile private var made: Int = 0

    private val den: File by lazy {
        File(context.cacheDir, CACHE_DIR).apply { mkdirs() }
    }

    init {
        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        /* It must not eat touches: the operator reaches the panel through it. */
        isClickable = false
        isFocusable = false
        isFocusableInTouchMode = false
        visibility = View.GONE
    }

    @Suppress("ClickableViewAccessibility")
    override fun onTouchEvent(event: android.view.MotionEvent?): Boolean = false

    override fun onInterceptTouchEvent(event: android.view.MotionEvent?): Boolean = false

    // ---------------------------------------------------------------- api

    /** Show the wall and keep it fed. Safe to call when already running. */
    fun start() {
        if (!running.compareAndSet(false, true)) return
        onMain {
            if (!veiled) visibility = View.VISIBLE
            build()
        }
        pump = scope.launch { feed() }
    }

    /** Hide it and let everything go. Safe to call when already stopped. */
    fun stop() {
        if (!running.compareAndSet(true, false)) return
        pump?.cancel()
        pump = null
        onMain {
            try { player?.release() } catch (err: Throwable) { }
            player = null
            listed.clear()
            showing = ""
            visibility = View.GONE
        }
    }

    fun isRunning(): Boolean = running.get()

    /**
     * #1434: take the picture off screen WITHOUT stopping the set.
     *
     * The listen view shows the same clip as its own backdrop and veils
     * whoever else is showing it (#1184). Veiling is not stopping: the
     * playlist keeps running, the clip does not restart and the queue is
     * not torn down, so coming back is a change of visibility and not a
     * rebuild.
     */
    fun veil(on: Boolean) {
        veiled = on
        onMain {
            visibility = if (running.get() && !veiled) View.VISIBLE else View.GONE
        }
    }

    /** Put the wall where the operator dragged the set to, in DEVICE pixels. */
    fun setBox(left: Int, top: Int, width: Int, height: Int) {
        onMain {
            val lp = layoutParams as? LayoutParams ?: return@onMain
            if (width <= 0 || height <= 0) {
                lp.width = LayoutParams.MATCH_PARENT
                lp.height = LayoutParams.MATCH_PARENT
                lp.leftMargin = 0
                lp.topMargin = 0
            } else {
                lp.width = width
                lp.height = height
                lp.leftMargin = left.coerceAtLeast(0)
                lp.topMargin = top.coerceAtLeast(0)
            }
            lp.gravity = android.view.Gravity.TOP or android.view.Gravity.START
            layoutParams = lp
        }
    }

    fun state(): JSONObject = JSONObject()
        .put("on", running.get())
        .put("veiled", veiled)
        .put("queued", aheadCount())
        .put("playing", showing)
        .put("made", made)
        .put("cached", den.listFiles()?.size ?: 0)

    // -------------------------------------------------------- the player

    /** Everything ExoPlayer is told must be told on the main thread. */
    private fun onMain(work: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) work() else post(work)
    }

    private fun build() {
        if (player != null) return
        val p = ExoPlayer.Builder(context).build()
        p.setVideoSurfaceView(screen)
        p.repeatMode = Player.REPEAT_MODE_OFF
        p.playWhenReady = true
        p.volume = 1f
        p.addListener(object : Player.Listener {
            override fun onMediaItemTransition(item: MediaItem?, reason: Int) {
                val at = p.currentMediaItemIndex
                showing = listed.getOrNull(at)?.id ?: ""
                Log.i(TAG, "now showing $showing (item $at of ${p.mediaItemCount})")
                trimBehind(p)
            }

            override fun onPlayerError(error: PlaybackException) {
                /* A clip this device cannot decode must not stop the set.
                 * ExoPlayer has already halted on it, so it is thrown away
                 * and the playlist resumed past it. */
                val at = p.currentMediaItemIndex
                val bad = listed.getOrNull(at)
                Log.w(TAG, "player: ${error.errorCodeName} on ${bad?.id}")
                try { bad?.file?.delete() } catch (err: Throwable) { }
                try {
                    if (p.mediaItemCount > at + 1) p.seekTo(at + 1, 0L)
                    p.prepare()
                } catch (err: Throwable) {
                    Log.w(TAG, "could not step past a bad clip: ${err.message}")
                }
            }
        })
        player = p
        p.prepare()
    }

    /**
     * Keep the playlist from growing without end. Items behind the
     * playhead are spent; `listed` is kept in step because the player's
     * indices are the only thing that says which clip is on.
     */
    private fun trimBehind(p: ExoPlayer) {
        val at = p.currentMediaItemIndex
        if (at < BEHIND_KEEP) return
        val cut = at - BEHIND_KEEP
        try {
            p.removeMediaItems(0, cut)
            repeat(cut) { if (listed.isNotEmpty()) listed.removeAt(0) }
        } catch (err: Throwable) {
            Log.w(TAG, "trim: ${err.message}")
        }
    }

    private fun offer(clip: Clip) {
        onMain {
            val p = player ?: return@onMain
            try {
                p.addMediaItem(MediaItem.fromUri(Uri.fromFile(clip.file)))
                listed.add(clip)
                made += 1
                if (showing.isEmpty()) {
                    showing = listed.getOrNull(p.currentMediaItemIndex)?.id ?: clip.id
                }
                if (p.playbackState == Player.STATE_IDLE) p.prepare()
            } catch (err: Throwable) {
                Log.w(TAG, "offer ${clip.id}: ${err.message}")
            }
        }
    }

    // ------------------------------------------------------------ the pump

    private suspend fun feed() {
        while (scope.isActive && running.get()) {
            try {
                if (aheadCount() < KEEP_AHEAD) {
                    val got = nextClip()
                    if (got != null) offer(got) else delay(1_200)
                } else {
                    delay(500)
                }
            } catch (err: kotlinx.coroutines.CancellationException) {
                throw err
            } catch (err: Throwable) {
                Log.w(TAG, "pump: ${err.javaClass.simpleName}: ${err.message}")
                delay(2_000)
            }
        }
    }

    private fun aheadCount(): Int {
        val p = player ?: return 0
        return try {
            (p.mediaItemCount - p.currentMediaItemIndex - 1).coerceAtLeast(0)
        } catch (err: Throwable) {
            /* mediaItemCount is main-thread only; from the pump this is a
             * read of a volatile-ish int and worth the guard, not a crash. */
            listed.size
        }
    }

    /** The next clip off the ring, or one out of the larder. */
    private suspend fun nextClip(): Clip? = withContext(Dispatchers.IO) {
        val base = client.config().base
        val text = try {
            client.request("GET", "$base/api/dj/video", null)
        } catch (err: Throwable) {
            Log.w(TAG, "ring: ${err.message}")
            return@withContext fromLarder()
        }
        val rows = JSONObject(text).optJSONArray("clips")
        if (rows != null) {
            for (i in 0 until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                val id = row.optString("id")
                val url = row.optString("url")
                if (id.isBlank() || url.isBlank()) continue
                if (rung.contains(id) || listed.any { it.id == id }) continue
                val file = pull(base + url, id)
                /* Remembered either way: a clip the station cannot give us
                 * is as finished with as one that played, and leaving a
                 * failure eligible meant picking the same dead id for ever. */
                remember(id)
                if (file == null) continue
                return@withContext Clip(id, file)
            }
        }
        fromLarder()
    }

    /**
     * A clip we already hold, when the station has nothing new.
     *
     * THE LEAST RECENTLY USED ONE, never a random one. The first cut took
     * a random file out of a 120-clip cache and the operator saw exactly
     * what that is - "it is looping some of the same clips". Touching a
     * file when it is taken turns the cache into a rotation: what comes
     * back is always what has waited longest, so nothing repeats until
     * everything else has had its turn.
     */
    private fun fromLarder(): Clip? {
        val now = showing
        val held = try {
            den.listFiles()?.filter {
                it.isFile && it.length() > MIN_BYTES && it.name.endsWith(".mp4")
                    && it.nameWithoutExtension != now
                    && listed.none { c -> c.id == it.nameWithoutExtension }
            }
        } catch (err: Throwable) {
            null
        } ?: return null
        val pick = held.minByOrNull { it.lastModified() } ?: return null
        try { pick.setLastModified(System.currentTimeMillis()) } catch (err: Throwable) { }
        return Clip(pick.nameWithoutExtension, pick)
    }

    /** This id is spent - played, or refused - and is not asked for again. */
    private fun remember(id: String) {
        rung.addLast(id)
        while (rung.size > RUNG_KEEP) rung.removeFirst()
    }

    /**
     * The clip, WHOLE, on local disk. Once this returns, nothing about
     * playing it can touch the network.
     */
    private suspend fun pull(url: String, id: String): File? {
        val out = File(den, "$id.mp4")
        if (out.isFile && out.length() > MIN_BYTES) return out
        return try {
            val bytes = client.getBytes(url).first
            if (bytes.size < MIN_BYTES) return null
            val part = File(den, "$id.part")
            part.writeBytes(bytes)
            if (!part.renameTo(out)) { part.delete(); return null }
            sweepCache()
            out
        } catch (err: Throwable) {
            Log.w(TAG, "pull $id: ${err.message}")
            null
        }
    }

    /** Bounded by count AND bytes; a cache dir nothing prunes is a full disk. */
    private fun sweepCache() {
        val files = den.listFiles()?.filter { it.isFile } ?: return
        var bytes = files.sumOf { it.length() }
        var n = files.size
        for (f in files.sortedBy { it.lastModified() }) {
            if (n <= CACHE_MOST && bytes <= CACHE_BYTES) break
            /* Never the clip on the tube, nor one already in the playlist. */
            if (f.nameWithoutExtension == showing) continue
            if (listed.any { it.id == f.nameWithoutExtension }) continue
            bytes -= f.length()
            n -= 1
            try { f.delete() } catch (err: Throwable) { }
        }
    }

    companion object {
        private const val TAG = "PineVideoWall"
        private const val CACHE_DIR = "pine-wall"
        /** How many clips to keep queued past the one playing. */
        private const val KEEP_AHEAD = 3
        /** Spent items left behind the playhead before the list is trimmed. */
        private const val BEHIND_KEEP = 2
        private const val RUNG_KEEP = 400
        private const val MIN_BYTES = 4096
        private const val CACHE_MOST = 240
        private const val CACHE_BYTES = 768L * 1024L * 1024L
    }
}
