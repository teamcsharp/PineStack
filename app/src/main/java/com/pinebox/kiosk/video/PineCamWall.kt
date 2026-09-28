package com.pinebox.kiosk.video

import android.content.Context
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean

/**
 * THE PINE CAM, PLAYED BY THE DEVICE, AS ONE LIVE STREAM.
 *
 * WHY THE PICTURE IS NOT IN THE PAGE. The dashcam reached the tablet as a
 * JPEG poll: four asks a second, painted by a WebView that renders at
 * 8-12 fps whatever is in it (PineVideoWall's header carries the
 * measurements - the whole panel hidden, one small clip alone on the
 * document, 21-40% of frames dropped). Six frames a second of a road is
 * not a picture of a road. The host now relays the camera as a
 * progressive MPEG-TS - H.264 848x480 at 30 fps, a keyframe every half
 * second, every client started on one - and the only surface on this
 * tablet that can show thirty of those is a SurfaceView that
 * SurfaceFlinger composites from its own buffer queue, exactly the road
 * the endless set already takes.
 *
 * WHY PROGRESSIVE AND NOT HLS. Latency. A segmented stream is behind by
 * its segment length times its playlist depth before the first frame;
 * a progressive TS is behind by whatever this player chooses to hold,
 * and the load control below holds a second. It also costs no new
 * artifact: ProgressiveMediaSource, DefaultHttpDataSource and the TS
 * extractor are all inside the media3 modules the set already pulled
 * in, and the build machine may not be able to fetch another.
 *
 * IT CHASES ITS OWN BUFFER AND NOTHING ELSE. A live source that arrives
 * at exactly real time can only get AHEAD of the playhead when the
 * playhead stalls - a busy decoder, a dropped frame burst, a Wi-Fi
 * hiccup that then bursts the backlog through. Left alone that lag
 * never comes back, so the picture is permanently late by however
 * much it once stumbled. The watchdog measures it once a second: a
 * little lag is run off at 1.25x, a lot of lag - or a player that has
 * stopped moving, or one that has been buffering too long, or one that
 * has thrown - is cut off and reconnected, and the server hands the
 * new connection a fresh keyframe. Reconnects back off (1, 2, 4, 8 s)
 * so a host that is down is not hammered by a tablet.
 *
 * AND IT DOES NOT EAT TOUCHES beyond its own rectangle. The page owns
 * everything around the picture; a press ON it is a tap or a drag of
 * the box, handed back to the page as such, like the set's.
 *
 * [pincrop] A press that stays put for HOLD_MS is a HOLD, the tablet's
 * right button: the page is told (onHold, device pixels) and opens its
 * crop radial - it retires this surface (`menu`) so the HTML menu can
 * paint where the picture was. The rest of that gesture is consumed
 * here, so the release is never also a tap.
 */
@UnstableApi
class PineCamWall(context: Context) : FrameLayout(context) {

    /* THE one surface. Media-overlay so it sits over the WebView and
     * under this app's own chrome. */
    private val screen = SurfaceView(context).apply { setZOrderMediaOverlay(true) }

    private var player: ExoPlayer? = null
    private val running = AtomicBoolean(false)
    @Volatile private var url: String = ""
    /** The page asked for the picture to leave the glass (still playing). */
    @Volatile private var hidden = false
    /** A menu has the rectangle; the surface is retired so HTML can paint there. */
    @Volatile private var menuHidden = false
    @Volatile private var fullScreen = false
    private var windowed = WallRect(0, 0, 0, 0)

    /** Where the operator's press landed, as a screen point. */
    @Volatile var onTap: ((Float, Float) -> Unit)? = null

    /** [pincrop] The press stayed put for HOLD_MS: the crop radial's hold,
     *  handed to the page as a screen point like the tap. */
    @Volatile var onHold: ((Float, Float) -> Unit)? = null

    /** Final native geometry after a drag/resize, in device pixels. */
    @Volatile var onBoxChanged: ((Int, Int, Int, Int) -> Unit)? = null
    /** #1470b: a drag in flight, so the page can hide the frame it draws
     *  around the picture rather than leave it standing where the box was. */
    @Volatile var onDragging: ((Boolean) -> Unit)? = null

    /* THE WATCHDOG'S LEDGER. Everything it sees is cached in volatile
     * fields so state() can answer the bridge thread without touching
     * the player, which is main-thread only. */
    @Volatile private var playback: String = "off"
    @Volatile private var playWhenReady: Boolean = true
    @Volatile private var atPos: Long = -1L
    @Volatile private var bufferedMs: Long = 0L
    @Volatile private var lagMs: Long = 0L
    @Volatile private var speed: Float = 1f
    @Volatile private var reconnects: Int = 0
    @Volatile private var lastError: String = ""
    @Volatile private var lastKick: String = ""
    @Volatile private var dropped: Int = 0
    @Volatile private var rendered: Int = 0
    /* Main-thread only, the clocks the rules below are measured against. */
    private var posSeen: Long = -1L
    private var stillSince: Long = 0L
    private var bufferingSince: Long = 0L
    private var laggingTicks: Int = 0
    private var healthyTicks: Int = 0
    private var errorPending: Boolean = false
    private var backoffMs: Long = BACKOFF_MIN_MS
    private var notBefore: Long = 0L
    private var waitingSaid: Boolean = false

    private val watchdog = object : Runnable {
        override fun run() {
            try { watch() } catch (err: Throwable) { Log.w(TAG, "watch: ${err.message}") }
            if (running.get()) postDelayed(this, WATCH_MS)
        }
    }

    init {
        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        /* The activity observes taps before dispatch. The wall itself must
         * never own input - see PineVideoWall for why. */
        isClickable = false
        isFocusable = false
        isFocusableInTouchMode = false
        visibility = View.GONE
    }

    // ---------------------------------------------------------------- touch

    private var downX = 0f
    private var downY = 0f
    private var downAt = 0L
    private var trackingTap = false
    private var moving = false
    private var resizing = false
    private var gestureStart = WallRect(0, 0, 0, 0)
    private var holdWaiter: Runnable? = null   // [pincrop] the armed hold
    private var heldFired = false              // [pincrop] eat the rest of the gesture

    /** [pincrop] The hold: HOLD_MS after a DOWN that has not moved and has
     *  not been released, tell the page and consume the rest of the
     *  gesture. Runs on the main thread (postDelayed on this view). */
    private fun armHold() {
        cancelHold()
        val waiter = Runnable {
            holdWaiter = null
            if (!trackingTap || moving) return@Runnable
            heldFired = true
            trackingTap = false
            moving = false
            Log.i(TAG, "hold at ${downX.toInt()},${downY.toInt()}")
            try { onHold?.invoke(downX, downY) }
            catch (err: Throwable) { Log.w(TAG, "hold: ${err.message}") }
        }
        holdWaiter = waiter
        postDelayed(waiter, HOLD_MS)
    }

    private fun cancelHold() {
        holdWaiter?.let { removeCallbacks(it) }
        holdWaiter = null
    }

    /**
     * A press and a release inside the slop is a tap; a press that
     * travels is a drag of the box (or a resize from its bottom-right
     * corner); a press that stays put for HOLD_MS is a hold ([pincrop]).
     * Consumed either way: this surface IS the picture, and a press on
     * it was never meant for whatever the box lies over.
     */
    fun observeTouch(press: MotionEvent): Boolean {
        if (!running.get() || hidden || menuHidden || visibility != View.VISIBLE) {
            trackingTap = false
            moving = false
            cancelHold()                       // [pincrop] the surface went away mid-press
            heldFired = false
            return false
        }
        val here = IntArray(2)
        getLocationOnScreen(here)
        val inside = press.rawX >= here[0] && press.rawX < here[0] + width &&
            press.rawY >= here[1] && press.rawY < here[1] + height
        when (press.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                cancelHold()                   // [pincrop] a new gesture
                heldFired = false
                /* The left bezel stays the native drawer's, even full-screen. */
                if (press.rawX <= EDGE_PASS_PX * resources.displayMetrics.density) {
                    trackingTap = false
                    return false
                }
                trackingTap = inside
                moving = false
                if (!inside) return false
                downX = press.rawX
                downY = press.rawY
                downAt = SystemClock.uptimeMillis()
                val lp = layoutParams as? LayoutParams
                gestureStart = WallRect(
                    lp?.leftMargin ?: here[0], lp?.topMargin ?: here[1],
                    width.coerceAtLeast(1), height.coerceAtLeast(1))
                resizing = !fullScreen &&
                    press.rawX >= here[0] + width - RESIZE_HANDLE_PX * resources.displayMetrics.density &&
                    press.rawY >= here[1] + height - RESIZE_HANDLE_PX * resources.displayMetrics.density
                armHold()                      // [pincrop] still here in HOLD_MS = the radial
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                if (heldFired) return true     // [pincrop] the gesture ended at the hold
                if (!trackingTap) return false
                val dx = (press.rawX - downX).toInt()
                val dy = (press.rawY - downY).toInt()
                if (!moving && Math.hypot(dx.toDouble(), dy.toDouble()) > TAP_SLOP_PX) {
                    cancelHold()               // [pincrop] a travelled press is a drag
                    moving = true
                    try { onDragging?.invoke(true) }
                    catch (err: Throwable) { Log.w(TAG, "dragging: ${err.message}") }
                }
                if (moving && !fullScreen) {
                    val bounds = wallBounds()
                    if (resizing) {
                        applyBox(VideoWallGeometry.resize(gestureStart, dx, dy,
                            bounds.first, bounds.second, minWallWidth(), minWallHeight()))
                    } else {
                        /* #1470b: a MOVE is a translation, not a layout. Rewriting
                         * the margins on every MotionEvent asked the root to lay
                         * out the whole panel WebView each time - that was the
                         * drag feeling slow. The surface slides on translationX/Y
                         * (a compositor transform, no layout) and the margins are
                         * written once, on release. */
                        val rect = VideoWallGeometry.move(gestureStart, dx, dy,
                            bounds.first, bounds.second, minWallWidth(), minWallHeight())
                        translationX = (rect.x - gestureStart.x).toFloat()
                        translationY = (rect.y - gestureStart.y).toFloat()
                    }
                }
                return true
            }
            MotionEvent.ACTION_UP -> {
                cancelHold()                   // [pincrop]
                if (heldFired) { heldFired = false; return true }
                if (!trackingTap) return false
                val moved = Math.hypot(
                    (press.rawX - downX).toDouble(), (press.rawY - downY).toDouble())
                val pressedFor = SystemClock.uptimeMillis() - downAt
                val wasMoving = moving
                trackingTap = false
                moving = false
                if (wasMoving) {
                    if (!resizing && !fullScreen && (translationX != 0f || translationY != 0f)) {
                        /* #1470b: the slide becomes the margins, once. */
                        applyBox(WallRect(gestureStart.x + translationX.toInt(),
                            gestureStart.y + translationY.toInt(),
                            gestureStart.width, gestureStart.height))
                    }
                    val lp = layoutParams as? LayoutParams
                    if (lp != null && lp.width > 0 && lp.height > 0) {
                        windowed = WallRect(lp.leftMargin, lp.topMargin, lp.width, lp.height)
                        try { onBoxChanged?.invoke(windowed.x, windowed.y,
                            windowed.width, windowed.height) }
                        catch (err: Throwable) { Log.w(TAG, "box changed: ${err.message}") }
                    }
                    try { onDragging?.invoke(false) }
                    catch (err: Throwable) { Log.w(TAG, "dragging: ${err.message}") }
                } else if (inside && moved <= TAP_SLOP_PX && pressedFor <= TAP_HOLD_MS) {
                    Log.i(TAG, "tap at ${press.rawX.toInt()},${press.rawY.toInt()}")
                    try { onTap?.invoke(press.rawX, press.rawY) }
                    catch (err: Throwable) { Log.w(TAG, "tap: ${err.message}") }
                }
                return true
            }
            MotionEvent.ACTION_CANCEL -> {
                cancelHold()                   // [pincrop]
                heldFired = false
                val was = trackingTap
                val wasMoving = moving
                trackingTap = false
                moving = false
                if (wasMoving) {
                    translationX = 0f
                    translationY = 0f
                    try { onDragging?.invoke(false) }
                    catch (err: Throwable) { Log.w(TAG, "dragging: ${err.message}") }
                }
                return was
            }
        }
        return trackingTap
    }

    @Suppress("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent?): Boolean = false

    override fun onInterceptTouchEvent(event: MotionEvent?): Boolean = false

    // ------------------------------------------------------------------ api

    /**
     * Show the camera from [streamUrl] and keep it there. Safe to call
     * again with the same address: that only makes sure the picture is
     * on the glass, it does not tear the stream down and start it over -
     * the page asks on every layout, and a restart per layout would be a
     * keyframe wait per layout.
     */
    fun play(streamUrl: String) {
        val wanted = streamUrl.trim()
        if (wanted.isEmpty()) return
        onMain {
            val same = running.get() && wanted == url && player != null &&
                player?.playbackState != Player.STATE_IDLE && !errorPending
            url = wanted
            running.set(true)
            build()
            hidden = false
            refreshVisibility()
            if (same) return@onMain
            open("play")
        }
    }

    /** Take the picture down and let the stream go. Safe when already stopped. */
    fun stop() {
        if (!running.compareAndSet(true, false)) return
        onMain {
            removeCallbacks(watchdog)
            try { player?.release() } catch (err: Throwable) { }
            player = null
            playback = "off"
            speed = 1f
            lagMs = 0L; bufferedMs = 0L; atPos = -1L
            posSeen = -1L; stillSince = 0L; bufferingSince = 0L
            laggingTicks = 0; healthyTicks = 0; errorPending = false
            backoffMs = BACKOFF_MIN_MS; notBefore = 0L
            menuHidden = false
            visibility = View.GONE
        }
    }

    fun isRunning(): Boolean = running.get()

    /** Off the glass, still playing - coming back is a visibility change. */
    fun hide() { hidden = true; onMain { refreshVisibility() } }

    fun show() {
        hidden = false
        onMain {
            refreshVisibility()
            /* Nothing was measured while the surface was away. */
            stillSince = 0L
        }
    }

    /**
     * The HTML menu cannot paint over a SurfaceView. Retire the surface
     * while the page's controls occupy the picture's rectangle; the
     * stream keeps running underneath so `free` is instant. Unlike the
     * endless set there is nothing to HOLD: a live picture paused is a
     * late picture, and the watchdog would only have to run it off.
     */
    fun menu(on: Boolean) {
        onMain {
            menuHidden = on
            refreshVisibility()
            if (!on) stillSince = 0L
        }
    }

    fun free() = menu(false)

    private fun refreshVisibility() {
        visibility = if (running.get() && !hidden && !menuHidden) View.VISIBLE else View.GONE
    }

    private fun wallBounds(): Pair<Int, Int> {
        val parentView = parent as? View
        val w = parentView?.width?.takeIf { it > 0 } ?: resources.displayMetrics.widthPixels
        val h = parentView?.height?.takeIf { it > 0 } ?: resources.displayMetrics.heightPixels
        return Pair(w.coerceAtLeast(1), h.coerceAtLeast(1))
    }

    private fun minWallWidth(): Int =
        (MIN_WIDTH_DP * resources.displayMetrics.density).toInt().coerceAtLeast(1)

    private fun minWallHeight(): Int =
        (MIN_HEIGHT_DP * resources.displayMetrics.density).toInt().coerceAtLeast(1)

    /** Main thread only. */
    private fun applyBox(rect: WallRect) {
        val lp = layoutParams as? LayoutParams ?: return
        translationX = 0f                     // #1470b: a slide never outlives its drag
        translationY = 0f
        lp.width = rect.width
        lp.height = rect.height
        lp.leftMargin = rect.x
        lp.topMargin = rect.y
        lp.gravity = Gravity.TOP or Gravity.START
        layoutParams = lp
    }

    /** Put the picture where the page says, in DEVICE pixels. 0,0,0,0 is the whole glass. */
    fun setBox(left: Int, top: Int, width: Int, height: Int) {
        onMain {
            val lp = layoutParams as? LayoutParams ?: return@onMain
            if (width <= 0 || height <= 0) {
                if (!fullScreen && lp.width > 0 && lp.height > 0) {
                    windowed = WallRect(lp.leftMargin, lp.topMargin, lp.width, lp.height)
                }
                lp.width = LayoutParams.MATCH_PARENT
                lp.height = LayoutParams.MATCH_PARENT
                lp.leftMargin = 0
                lp.topMargin = 0
                lp.gravity = Gravity.TOP or Gravity.START
                layoutParams = lp
                fullScreen = true
            } else {
                val bounds = wallBounds()
                windowed = VideoWallGeometry.fit(WallRect(left, top, width, height),
                    bounds.first, bounds.second, minWallWidth(), minWallHeight())
                applyBox(windowed)
                fullScreen = false
            }
        }
    }

    /** Fill the physical glass; any menu retirement ends with it. */
    fun showFullScreen() {
        onMain {
            val lp = layoutParams as? LayoutParams ?: return@onMain
            if (!fullScreen && lp.width > 0 && lp.height > 0) {
                windowed = WallRect(lp.leftMargin, lp.topMargin, lp.width, lp.height)
            }
            lp.width = LayoutParams.MATCH_PARENT
            lp.height = LayoutParams.MATCH_PARENT
            lp.leftMargin = 0; lp.topMargin = 0
            lp.gravity = Gravity.TOP or Gravity.START
            layoutParams = lp
            fullScreen = true
            menuHidden = false
            refreshVisibility()
        }
    }

    /** Back to the last measured window. */
    fun showWindowed() {
        onMain {
            if (windowed.width > 0 && windowed.height > 0) applyBox(windowed)
            fullScreen = false
            menuHidden = false
            refreshVisibility()
        }
    }

    fun state(): JSONObject = JSONObject()
        .put("on", running.get())
        .put("playing", running.get() && playback == "ready" && playWhenReady)
        .put("state", playback)
        .put("play_when_ready", playWhenReady)
        /* Where the picture is, in device pixels - the page cannot lay a
         * menu over a media-overlay surface, so it has to stand clear. */
        .put("x", (layoutParams as? LayoutParams)?.leftMargin ?: 0)
        .put("y", (layoutParams as? LayoutParams)?.topMargin ?: 0)
        .put("w", width)
        .put("h", height)
        .put("full", fullScreen)
        .put("hidden", hidden)
        .put("menu_hidden", menuHidden)
        .put("lag_ms", lagMs)
        .put("buffered_ms", bufferedMs)
        .put("position_ms", atPos)
        .put("speed", speed.toDouble())
        .put("reconnects", reconnects)
        .put("url", url)
        .put("errors", lastError)
        .put("last_kick", lastKick)
        .put("dropped", dropped)
        .put("rendered", rendered)

    // --------------------------------------------------------- the watchdog

    private fun stateName(st: Int): String = when (st) {
        Player.STATE_IDLE -> "idle"
        Player.STATE_BUFFERING -> "buffering"
        Player.STATE_READY -> "ready"
        Player.STATE_ENDED -> "ended"
        else -> "state-$st"
    }

    private fun stamp(): String {
        val c = java.util.Calendar.getInstance()
        return String.format(java.util.Locale.US, "%02d:%02d:%02d",
            c.get(java.util.Calendar.HOUR_OF_DAY), c.get(java.util.Calendar.MINUTE), c.get(java.util.Calendar.SECOND))
    }

    /** Main thread, once a second: is the picture live, and if not, why not. */
    private fun watch() {
        val p = player ?: return
        if (!running.get()) return
        val now = SystemClock.elapsedRealtime()
        val st = p.playbackState
        val pos = p.currentPosition
        val buf = p.bufferedPosition
        val lag = (buf - pos).coerceAtLeast(0L)
        playback = stateName(st)
        playWhenReady = p.playWhenReady
        atPos = pos
        bufferedMs = buf
        lagMs = lag
        try {
            p.videoDecoderCounters?.let {
                dropped = it.droppedBufferCount
                rendered = it.renderedOutputBufferCount
            }
        } catch (err: Throwable) { }

        /* The buffering clock runs whenever the state is BUFFERING. */
        if (st == Player.STATE_BUFFERING) {
            if (bufferingSince == 0L) bufferingSince = now
        } else {
            bufferingSince = 0L
        }
        /* The stillness clock runs only while the picture SHOULD move:
         * READY, asked to play, and on the glass - a retired surface may
         * legitimately stop presenting, and reconnecting a hidden picture
         * every few seconds would be noise for nobody. */
        val moved = pos != posSeen
        posSeen = pos
        val shouldMove = st == Player.STATE_READY && p.playWhenReady && visibility == View.VISIBLE
        if (moved || stillSince == 0L || !shouldMove) stillSince = now
        val still = now - stillSince
        val buffering = if (bufferingSince > 0L) now - bufferingSince else 0L

        when {
            errorPending -> reconnect(now, "player error")
            st == Player.STATE_ENDED -> reconnect(now, "stream ended")
            lag > LAG_RECONNECT_MS -> reconnect(now, "lag $lag ms")
            buffering > BUFFER_STUCK_MS -> reconnect(now, "buffering ${buffering / 1000.0}s")
            still > STILL_MS -> reconnect(now, "frozen $still ms at $pos")
            else -> {
                pace(p, lag)
                if (shouldMove && moved) {
                    healthyTicks += 1
                    /* Enough good seconds and the next fault starts the
                     * ladder from the bottom again. */
                    if (healthyTicks >= HEALTHY_TICKS) backoffMs = BACKOFF_MIN_MS
                }
            }
        }
    }

    /**
     * Run a little lag off at 1.25x rather than cutting the stream for it.
     * Two ticks over the threshold, not one: a single reading over 1.5 s
     * is what a burst through a Wi-Fi hiccup looks like on the tick it
     * lands, and it is often gone on the next.
     */
    private fun pace(p: ExoPlayer, lag: Long) {
        if (lag > LAG_CATCHUP_MS) laggingTicks += 1 else laggingTicks = 0
        try {
            if (speed == 1f && laggingTicks >= 2) {
                p.setPlaybackSpeed(CATCHUP_SPEED)
                speed = CATCHUP_SPEED
                Log.i(TAG, "lag $lag ms: running it off at ${CATCHUP_SPEED}x")
            } else if (speed != 1f && lag <= LAG_SETTLED_MS) {
                p.setPlaybackSpeed(1f)
                speed = 1f
                laggingTicks = 0
                Log.i(TAG, "lag $lag ms: back to 1x")
            }
        } catch (err: Throwable) {
            Log.w(TAG, "pace: ${err.message}")
        }
    }

    /** Cut the stream and ask for it again, no sooner than the ladder allows. */
    private fun reconnect(now: Long, why: String) {
        if (now < notBefore) {
            if (!waitingSaid) {
                Log.i(TAG, "$why - waiting ${notBefore - now} ms before reconnecting")
                waitingSaid = true
            }
            return
        }
        waitingSaid = false
        reconnects += 1
        lastKick = "${stamp()} $why"
        Log.w(TAG, "reconnect #$reconnects: $why (next no sooner than $backoffMs ms)")
        notBefore = now + backoffMs
        backoffMs = (backoffMs * 2).coerceAtMost(BACKOFF_MAX_MS)
        errorPending = false
        open("reconnect")
    }

    /** Main thread only: (re)start the one stream on the one player. */
    private fun open(how: String) {
        val p = player ?: return
        val at = url
        if (at.isEmpty()) return
        try {
            p.stop()
            if (speed != 1f) { p.setPlaybackSpeed(1f); speed = 1f }
            p.setMediaSource(source(at))
            p.prepare()
            p.playWhenReady = true
            p.play()
            Log.i(TAG, "$how: $at")
        } catch (err: Throwable) {
            lastError = "${stamp()} $how: ${err.message}"
            Log.w(TAG, "$how: ${err.message}")
        }
        posSeen = -1L
        stillSince = 0L
        bufferingSince = 0L
        laggingTicks = 0
        healthyTicks = 0
    }

    // ----------------------------------------------------------- the player

    /** Everything ExoPlayer is told must be told on the main thread. */
    private fun onMain(work: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) work() else post(work)
    }

    /**
     * ONE HTTP CONNECTION, READ AS IT ARRIVES. The four-second connect
     * is the station being one hop away; the eight-second read is longer
     * than any gap a live relay should ever leave, and shorter than the
     * WebView's own patience, so a relay that has silently stopped
     * writing turns into an error the watchdog acts on.
     */
    private fun source(at: String): ProgressiveMediaSource {
        val http = DefaultHttpDataSource.Factory()
            .setConnectTimeoutMs(CONNECT_MS)
            .setReadTimeoutMs(READ_MS)
            .setAllowCrossProtocolRedirects(true)
            .setUserAgent("PineBoxKiosk cam")
        return ProgressiveMediaSource.Factory(http)
            /* How many bytes the loader reads before asking the load
             * control whether it should still be reading. The default is a
             * megabyte - five seconds of this stream - which would let it
             * overrun the buffer ceiling below by that much before it
             * noticed. */
            .setContinueLoadingCheckIntervalBytes(LOAD_CHECK_BYTES)
            .createMediaSource(MediaItem.fromUri(at))
    }

    private fun build() {
        if (player != null) return
        /* A LOAD CONTROL FOR A LIVE PICTURE: start on a quarter second,
         * hold a second, never more than five. Anything held is latency. */
        val control = DefaultLoadControl.Builder()
            .setBufferDurationsMs(LOAD_MIN_MS, LOAD_MAX_MS, LOAD_PLAY_MS, LOAD_REPLAY_MS)
            .setPrioritizeTimeOverSizeThresholds(true)
            .build()
        val p = ExoPlayer.Builder(context).setLoadControl(control).build()
        p.setVideoSurfaceView(screen)
        p.repeatMode = Player.REPEAT_MODE_OFF
        /* The camera has no sound and must never take the air even if
         * one day it does: the broadcast is the page's. */
        p.volume = 0f
        p.playWhenReady = true
        p.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                playback = stateName(state)
                Log.i(TAG, "state ${stateName(state)}")
            }

            override fun onPlayerError(error: PlaybackException) {
                lastError = "${stamp()} ${error.errorCodeName}: ${error.message}"
                Log.w(TAG, "player: ${error.errorCodeName}: ${error.message}")
                /* Not reconnected from here: the watchdog owns the
                 * ladder, and it is at most a second away. */
                errorPending = true
            }
        })
        player = p
        removeCallbacks(watchdog)
        posSeen = -1L
        stillSince = 0L
        postDelayed(watchdog, WATCH_MS)
    }

    companion object {
        private const val TAG = "PineCamWall"
        /** Left bezel remains the drawer's gesture even over a full-screen picture. */
        private const val EDGE_PASS_PX = 28f
        /** A one-finger drag from this corner resizes; elsewhere it moves. */
        private const val RESIZE_HANDLE_PX = 72f
        private const val MIN_WIDTH_DP = 160f
        private const val MIN_HEIGHT_DP = 90f
        private const val TAP_SLOP_PX = 24.0
        private const val TAP_HOLD_MS = 700L
        /** [pincrop] The crop radial's hold - the SFX wall's 550 ms, the
         *  same wait the page uses on its own picture. */
        private const val HOLD_MS = 550L
        /* The connection. */
        private const val CONNECT_MS = 4_000
        private const val READ_MS = 8_000
        private const val LOAD_CHECK_BYTES = 64 * 1024
        /* The load control: a live picture holds as little as it can. */
        private const val LOAD_MIN_MS = 1_000
        private const val LOAD_MAX_MS = 5_000
        private const val LOAD_PLAY_MS = 250
        private const val LOAD_REPLAY_MS = 500
        /* The watchdog's tick and its bounds. */
        private const val WATCH_MS = 1_000L
        private const val LAG_CATCHUP_MS = 1_500L
        private const val LAG_SETTLED_MS = 600L
        private const val LAG_RECONNECT_MS = 6_000L
        private const val CATCHUP_SPEED = 1.25f
        private const val BUFFER_STUCK_MS = 3_000L
        private const val STILL_MS = 2_500L
        /* The reconnect ladder: 1, 2, 4, 8 s, and back to 1 after ten good seconds. */
        private const val BACKOFF_MIN_MS = 1_000L
        private const val BACKOFF_MAX_MS = 8_000L
        private const val HEALTHY_TICKS = 10
    }
}
