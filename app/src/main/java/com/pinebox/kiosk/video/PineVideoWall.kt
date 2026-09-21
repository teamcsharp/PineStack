package com.pinebox.kiosk.video

import android.content.Context
import android.media.MediaPlayer
import android.util.Log
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout
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
 * THE ENDLESS SET, PLAYED BY THE DEVICE INSTEAD OF BY THE PAGE.
 *
 * WHY THIS EXISTS AT ALL — the measurements, because every cheaper
 * explanation was tested first and each one was wrong.
 *
 * The operator reported the tablet stuttering and asked for "a high
 * density wide bandwidth tunnel... ensuring that no matter what happens
 * on the network, we always have a high priority connection". Measured on
 * the tablet while it was stuttering, the network was already innocent:
 *
 *     buffered ahead of the playhead   9.5 s
 *     stalls / re-buffers              0
 *     ping to the station              2-5 ms
 *     TTFB for a whole clip            2-150 ms
 *     clip size                        427x240, median 0.60 MB, largest 5.35
 *
 * and the picture was still dropping 21-40% of its frames. It was not the
 * delivery. It was that the PAGE the picture floats in cannot be
 * composited on this device:
 *
 *     page render rate                 7.9-12 fps
 *     Chrome_InProcGp                  89%    mali-cmar-backe 35%
 *     gfxinfo, kiosk                   25% janky, p50 frame 32 ms,
 *                                      1,008 missed vsyncs
 *
 * And that ceiling is not the page's fault either: with the entire panel
 * hidden — 28 top-level elements — and every decorative decoder released,
 * leaving ONE 427x240 video alone on an otherwise empty document, the
 * WebView still rendered at 12 fps. No arrangement of HTML gets a smooth
 * picture out of this WebView.
 *
 * So the picture leaves the WebView. A [SurfaceView] is not drawn by the
 * page's compositor at all — SurfaceFlinger composites it directly from
 * its own buffer queue, and MediaCodec fills that queue in hardware. The
 * WebView can jank as badly as it likes above it; the frames still land
 * on the panel at vsync. That — not a wider pipe — is the "high priority
 * connection for broadcasting a video" that was actually being asked for.
 *
 * WHAT IT DOES NOT DO, deliberately:
 *
 *  - It does NOT chase the station's clock. #1173 put a clip's position
 *    under a station clock so two surfaces would show the same frame, and
 *    #1421 had to bound it because holding a clip there re-seeked it
 *    mid-picture and flushed the decoder every few seconds. The wall plays
 *    the ring IN ORDER, back to back, and never seeks a clip it is
 *    playing. Perpetual and seamless was the ask; frame-identical with the
 *    desk was not.
 *
 *  - It does NOT stream. Every clip is pulled down WHOLE to the cache
 *    first and played from a local file, so a hand-over can never wait on
 *    the network. At a median 0.60 MB that costs nothing and removes the
 *    entire class of fault.
 *
 * THE HAND-OVER is why there are two of everything. A single MediaPlayer
 * reset and re-prepared between clips shows black for as long as the
 * prepare takes; two players leapfrog, so the next clip is already
 * PREPARED and holding its first frame when the current one ends, and the
 * swap is one bringToFront().
 */
class PineVideoWall(
    context: Context,
    private val client: StationClient,
    private val scope: CoroutineScope,
) : FrameLayout(context) {

    private data class Clip(val id: String, val url: String, val file: File)

    /** #1431: one half of the leapfrog - a player and what is on it. The
     * SURFACE is shared; see the class note on why there is only one. */
    private inner class Deck {
        var player: MediaPlayer? = null
        var clip: Clip? = null
        var ready = false

        fun release() {
            try { player?.setOnCompletionListener(null) } catch (err: Throwable) { }
            try { player?.reset() } catch (err: Throwable) { }
            try { player?.release() } catch (err: Throwable) { }
            player = null
            clip = null
            ready = false
        }
    }

    /* #1431: THE one surface. Media-overlay so it sits over the WebView
     * and under this app's own chrome. */
    private val screen = SurfaceView(context).apply { setZOrderMediaOverlay(true) }
    private var held: SurfaceHolder? = null

    private val deckA = Deck()
    private val deckB = Deck()
    private var live: Deck = deckA
    private val running = AtomicBoolean(false)
    private var pump: Job? = null

    /** Clips pulled down and waiting, oldest first. */
    private val queue = ArrayDeque<Clip>()

    /** Ids already rung, so the ring's repeats are not played twice. */
    private val rung = ArrayDeque<String>()

    private val den: File by lazy {
        File(context.cacheDir, CACHE_DIR).apply { mkdirs() }
    }

    init {
        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        screen.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) {
                held = holder
                try { live.player?.setDisplay(holder) } catch (err: Throwable) { }
            }

            override fun surfaceChanged(h: SurfaceHolder, f: Int, w: Int, ht: Int) = Unit

            override fun surfaceDestroyed(holder: SurfaceHolder) {
                /* A player left holding a dead surface is the one way this
                 * crashes rather than merely going blank. */
                held = null
                try { deckA.player?.setDisplay(null) } catch (err: Throwable) { }
                try { deckB.player?.setDisplay(null) } catch (err: Throwable) { }
            }
        })
        /* #1431: AND IT MUST NOT EAT TOUCHES. This lies over the WebView,
         * and while it is up the operator reaches the panel through it. */
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
        visibility = View.VISIBLE
        pump = scope.launch { feed() }
    }

    /** Hide it and let everything go. Safe to call when already stopped. */
    fun stop() {
        if (!running.compareAndSet(true, false)) return
        pump?.cancel()
        pump = null
        deckA.release()
        deckB.release()
        queue.clear()
        visibility = View.GONE
    }

    fun isRunning(): Boolean = running.get()

    /**
     * Put the wall where the operator dragged the set to, in DEVICE
     * pixels. A width or height of zero means full screen - which is what
     * a page too old to send a box gets, and is still better than nothing.
     */
    fun setBox(left: Int, top: Int, width: Int, height: Int) {
        post {
            val lp = layoutParams as? LayoutParams ?: return@post
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

    /** What the wall is doing, for the bridge and for a probe. */
    fun state(): JSONObject = JSONObject()
        .put("on", running.get())
        .put("queued", queue.size)
        .put("playing", live.clip?.id ?: "")
        .put("cached", (den.listFiles()?.size ?: 0))

    // -------------------------------------------------------------- the pump

    /**
     * Keep [KEEP_AHEAD] clips pulled down and the decks leapfrogging.
     *
     * One loop rather than a callback web: the completion listener only
     * flips a flag and this decides what happens next, because a
     * MediaPlayer callback arrives on a thread that must not be made to
     * wait on a download.
     */
    private suspend fun feed() {
        while (scope.isActive && running.get()) {
            try {
                if (queue.size < KEEP_AHEAD) {
                    val got = nextFromRing()
                    if (got != null) queue.addLast(got) else delay(1_500)
                }
                if (live.player == null && queue.isNotEmpty()) startFirst()
                else warmOther()
                delay(350)
            } catch (err: kotlinx.coroutines.CancellationException) {
                /* A cancel is not a fault and must not be retried - caught
                 * by `Throwable` below, it became a two second nap and
                 * another lap, for ever. */
                throw err
            } catch (err: Throwable) {
                Log.w(TAG, "pump: ${err.javaClass.simpleName}: ${err.message}")
                delay(2_000)
            }
        }
    }

    /** The next clip off /api/dj/video that we have not already rung. */
    private suspend fun nextFromRing(): Clip? = withContext(Dispatchers.IO) {
        val base = client.config().base
        val text = client.request("GET", "$base/api/dj/video", null)
        val rows = JSONObject(text).optJSONArray("clips") ?: run {
            Log.i(TAG, "pump: ring has no clips array")
            return@withContext null
        }
        if (rows.length() == 0) Log.i(TAG, "pump: ring empty")
        for (i in 0 until rows.length()) {
            val row = rows.optJSONObject(i) ?: continue
            val id = row.optString("id")
            val url = row.optString("url")
            if (id.isBlank() || url.isBlank()) continue
            if (rung.contains(id) || queue.any { it.id == id }) {
                Log.d(TAG, "pump: ring $id already spent")
                continue
            }
            Log.i(TAG, "pump: ring offers $id")
            val file = pull(base + url, id)
            /* REMEMBERED EITHER WAY. A clip the station cannot give us is
             * as finished with as one that played: leaving a failure
             * eligible meant the pump picked the same dead id on every
             * pass and never got as far as filling the queue. */
            remember(id)
            if (file == null) continue
            return@withContext Clip(id, url, file)
        }
        /* #1431c: THE RING IS EMPTY, THE LARDER IS NOT. */
        fromLarder()
    }

    /**
     * A clip we already hold, when the station has nothing new.
     *
     * The station rings in real time and the wall plays in real time, so
     * they run level and the wall is regularly a second ahead of the
     * plan - at which point it used to replay the clip on screen, which
     * is the one repeat nobody can miss. An endless set repeats by
     * definition; it just must not repeat what you are looking at.
     */
    private fun fromLarder(): Clip? {
        val now = live.clip?.file?.name
        val held = try {
            den.listFiles()?.filter {
                it.isFile && it.length() > MIN_BYTES
                    && it.name.endsWith(".mp4") && it.name != now
            }
        } catch (err: Throwable) {
            null
        } ?: return null
        if (held.isEmpty()) return null
        val pick = held[(Math.random() * held.size).toInt().coerceIn(0, held.size - 1)]
        return Clip(pick.nameWithoutExtension, "", pick)
    }

    /** This id is spent - played, or refused - and is not asked for again. */
    private fun remember(id: String) {
        rung.addLast(id)
        while (rung.size > RUNG_KEEP) rung.removeFirst()
    }

    /**
     * The clip, WHOLE, on local disk. This is the "pre-caching" half: once
     * this returns, nothing about playing the clip can touch the network.
     */
    private suspend fun pull(url: String, id: String): File? = withContext(Dispatchers.IO) {
        val out = File(den, "$id.mp4")
        if (out.isFile && out.length() > MIN_BYTES) return@withContext out
        try {
            val (bytes, _) = client.getBytes(url)
            if (bytes.size < MIN_BYTES) return@withContext null
            val part = File(den, "$id.part")
            part.writeBytes(bytes)
            if (!part.renameTo(out)) { part.delete(); return@withContext null }
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
        val oldest = files.sortedBy { it.lastModified() }.toMutableList()
        var n = oldest.size
        for (f in oldest) {
            if (n <= CACHE_MOST && bytes <= CACHE_BYTES) break
            bytes -= f.length()
            n -= 1
            try { f.delete() } catch (err: Throwable) { }
        }
    }

    // ------------------------------------------------------------ the decks

    private fun other(): Deck = if (live === deckA) deckB else deckA

    private fun startFirst() {
        val clip = queue.removeFirstOrNull() ?: return
        prepare(live, clip, andPlay = true)
    }

    /** Keep the OTHER deck loaded with the next clip, prepared and waiting. */
    private fun warmOther() {
        val idle = other()
        if (idle.player != null || queue.isEmpty()) return
        val clip = queue.removeFirstOrNull() ?: return
        prepare(idle, clip, andPlay = false)
    }

    private fun prepare(deck: Deck, clip: Clip, andPlay: Boolean) {
        deck.release()
        deck.clip = clip
        val mp = MediaPlayer()
        deck.player = mp
        try {
            mp.setDataSource(clip.file.absolutePath)
            /* Only the LIVE deck may hold the surface; the warm one takes
               it at the hand-over. Two players on one surface at once is
               the two-pictures fault all over again. */
            if (deck === live) held?.let { mp.setDisplay(it) }
            mp.setOnPreparedListener {
                deck.ready = true
                if (andPlay) show(deck)
            }
            mp.setOnErrorListener { _, what, extra ->
                Log.w(TAG, "player ${clip.id}: $what/$extra")
                /* A clip this device cannot decode must not stop the set -
                 * drop it and let the pump bring the next one. */
                try { clip.file.delete() } catch (err: Throwable) { }
                deck.release()
                true
            }
            mp.setOnCompletionListener { handOver(deck) }
            mp.prepareAsync()
        } catch (err: Throwable) {
            Log.w(TAG, "prepare ${clip.id}: ${err.message}")
            deck.release()
        }
    }

    /**
     * The clip ended. The other deck is already prepared and holding its
     * first frame, so this is a bringToFront and a start — no reset, no
     * prepare, nothing that can show black.
     */
    private fun handOver(from: Deck) {
        val next = other()
        if (next.player != null && next.ready) {
            /* #1431b: THE OUTGOING LETS GO FIRST. On one surface, starting
             * the incoming player before releasing the outgoing one leaves
             * both holding the same SurfaceHolder for an instant, and the
             * second setDisplay lands while the first still owns it -
             * MediaPlayer answers -38, INVALID_OPERATION, and the picture
             * stops. The gap this opens is two statements wide. */
            from.release()
            show(next)
        } else {
            /* Nothing warm behind it. Replaying beats a black tube, but a
             * set that quietly plays one clip for ever looks exactly like
             * a working set, so it is said out loud - this is the line
             * that tells you the pump is not keeping up. */
            Log.w(TAG, "handover: nothing warm - replaying ${from.clip?.id}")
            try { from.player?.seekTo(0); from.player?.start() } catch (err: Throwable) { }
        }
    }

    private fun show(deck: Deck) {
        live = deck
        val swap = Runnable {
            try {
                /* #1431b: no surface yet means no picture. The wall is GONE
                 * until it is started and a GONE SurfaceView has none, so on
                 * the first clip this can still be null - and starting here
                 * would be exactly "the audio plays and nothing is shown".
                 * surfaceCreated hands the surface to whatever is live. */
                val holder = held
                if (holder == null) {
                    Log.i(TAG, "show: no surface yet, waiting for it")
                    return@Runnable
                }
                deck.player?.setDisplay(holder)
                deck.player?.start()
                /* The operator's report was "the audio for the next video
                 * will play, but the video doesn't update" - which is this
                 * line being wrong, so it says what it did. */
                Log.i(TAG, "handover: deck "
                    + (if (deck === deckB) "B" else "A")
                    + " has the surface (" + (deck.clip?.id ?: "?") + ")")
            } catch (err: Throwable) {
                Log.w(TAG, "show: ${err.message}")
            }
        }
        /* #1429: MediaPlayer delivers onCompletion on the MAIN looper when
         * the player was built on a thread without one - which is how the
         * pump builds them - so we are already where we need to be. post()
         * bought another trip through a message queue measured at 100-250
         * ms of latency on this device, and that is the size of the gap he
         * was seeing. Only hop threads when we genuinely are not on it. */
        if (android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) {
            swap.run()
        } else {
            post(swap)
        }
    }

    companion object {
        private const val TAG = "PineVideoWall"
        private const val CACHE_DIR = "pine-wall"
        private const val KEEP_AHEAD = 3
        private const val RUNG_KEEP = 200
        private const val MIN_BYTES = 4096
        private const val CACHE_MOST = 120
        private const val CACHE_BYTES = 512L * 1024L * 1024L
    }
}
