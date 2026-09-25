package com.pinebox.kiosk.video

import android.content.Context
import android.media.AudioManager
import android.media.audiofx.LoudnessEnhancer
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
import androidx.media3.exoplayer.DefaultLoadControl   // [#1212]
import com.pinebox.kiosk.net.StationClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.log10
import kotlin.math.roundToInt

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

    /* [#1212] `seconds` is the clip's own measured length off the ring, so the
     * pump can keep a runway measured in PICTURE rather than in rows. 0 means
     * the station did not say, and secondsOf() falls back to the floor. */
    private data class Clip(val id: String, val file: File, val seconds: Double = 0.0)

    /* THE one surface. Media-overlay so it sits over the WebView and
     * under this app's own chrome. */
    private val screen = SurfaceView(context).apply { setZOrderMediaOverlay(true) }

    private var player: ExoPlayer? = null
    private val running = AtomicBoolean(false)
    /** The page's requested veil. A menu has its own temporary compositor
     *  retirement and must not overwrite this ownership state. */
    @Volatile private var veiled = false
    @Volatile private var menuHidden = false
    @Volatile private var fullScreen = false
    /* [#1386] HELD, because the operator is deciding what to do with THIS
     * clip. "if i bring up the menu, keep the video up so i can decide
     * what to do with it. Dont cycle to the next video while the popup is
     * active."
     *
     * A hold is not a stop and not a veil: the picture stays on the glass
     * exactly as it is, the playlist keeps its place, and only the moving
     * stops. It has to be a flag rather than just playWhenReady=false,
     * because watch() below sees a READY player with the play flag down
     * for 1.5s and kicks it straight back on ("play flag dropped") - which
     * is the watchdog doing its job, and would have made the menu look
     * broken for no reason anybody could see. */
    @Volatile private var held = false
    @Volatile private var holdUntil = 0L
    private var pump: Job? = null
    /** At most one network refill. The local larder never waits behind it. */
    private var fresh: Job? = null
    /** Operator shuffle owns the runway until its requested batch lands. */
    @Volatile private var reshuffling = false

    private var windowed = WallRect(0, 0, 0, 0)

    /** What is in the playlist, in the player's own index order. */
    private val listed = ArrayList<Clip>()

    /** Ids already put in the playlist, so the ring's repeats are skipped. */
    private val rung = ArrayDeque<String>()

    @Volatile private var showing: String = ""
    @Volatile private var made: Int = 0

    /** The WebView follows the exact native transition without waiting for a
     * station poll. Called on the main thread and intentionally carries only
     * the stable clip id. */
    @Volatile var onClipChanged: ((String) -> Unit)? = null

    /* [#1192]: this terminal's own video level, 0..2. Survives every rebuild
     * the watchdog below does, because build() reads it. */
    @Volatile private var wallLevel: Float = 1f
    private var wallBoost: LoudnessEnhancer? = null

    /* #1440: THE WATCHDOG. 2026-09-21 15:31 the operator: "the clips are
     * frozen on the pine tab". Measured: the wall's SurfaceView had posted
     * no frame for ~12 minutes, `playing` never changed, and `queued` sat
     * at exactly KEEP_AHEAD - the pump had filled the playlist and the
     * player was not consuming it. No error had been raised, so nothing
     * in this class could notice: the only state it watched was the
     * error callback. An off/on through the bridge cured it at once.
     *
     * So the wall now measures its own progress once a second on the main
     * thread (index, position, playbackState) and acts on a still player
     * by state: ENDED with clips queued -> seek to the next; IDLE -> prepare;
     * BUFFERING past a bound -> step past the clip; READY-but-frozen ->
     * re-attach the surface, then on the third strike rebuild the player.
     * Everything it sees is cached in volatile fields so `state()` can
     * report it from the bridge thread without touching the player. */
    @Volatile private var playback: String = "idle"
    @Volatile private var playWhenReady: Boolean = true
    @Volatile private var atIndex: Int = -1
    @Volatile private var atCount: Int = 0
    @Volatile private var atPos: Long = -1L
    @Volatile private var atDuration: Long = -1L
    @Volatile private var stillSince: Long = 0L
    @Volatile private var kicks: Int = 0
    @Volatile private var lastKick: String = ""
    @Volatile private var lastError: String = ""
    @Volatile private var repairs: Int = 0
    @Volatile private var lastRepair: String = ""
    private val watchdog = object : Runnable {
        override fun run() {
            try { watch() } catch (err: Throwable) { Log.w(TAG, "watch: ${err.message}") }
            if (running.get()) postDelayed(this, WATCH_MS)
        }
    }

    private val den: File by lazy {
        File(context.cacheDir, CACHE_DIR).apply { mkdirs() }
    }

    init {
        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        /* The activity observes taps before dispatch. The wall itself must
         * never own input: a missing box can legitimately make it full-screen,
         * and consuming that surface strands the operator outside the panel. */
        isClickable = false
        isFocusable = false
        isFocusableInTouchMode = false
        visibility = View.GONE
    }

    /** Where the operator's press lands, handed over as a screen point. */
    @Volatile var onTap: ((Float, Float) -> Unit)? = null

    /** A settled hold uses the page's radial clip menu, including in Listen. */
    @Volatile var onLongPress: ((Float, Float) -> Unit)? = null

    /** Final native geometry after a drag/resize, in device pixels. */
    @Volatile var onBoxChanged: ((Int, Int, Int, Int) -> Unit)? = null

    /** Lets the page remove an abandoned sheet when the native safety hold expires. */
    @Volatile var onHoldExpired: (() -> Unit)? = null

    private var downX = 0f
    private var downY = 0f
    private var downAt = 0L
    private var trackingTap = false
    private var moving = false
    private var longPressFired = false
    private var resizing = false
    private var gestureStart = WallRect(0, 0, 0, 0)
    private val longPressTrigger = Runnable {
        if (!trackingTap || moving || longPressFired) return@Runnable
        longPressFired = true
        try { onLongPress?.invoke(downX, downY) }
        catch (err: Throwable) { Log.w(TAG, "long press: ${err.message}") }
    }

    /**
     * [#1441] A PRESS AND A RELEASE INSIDE THE SLOP IS A TAP; anything
     * else is not, so a drag across the picture still opens nothing.
     * Consumed either way: this surface is the picture, and a press on it
     * was never meant for whatever the box happens to be lying over.
     */
    fun observeTouch(press: android.view.MotionEvent): Boolean {
        if (!running.get() || veiled || menuHidden || visibility != View.VISIBLE) {
            removeCallbacks(longPressTrigger)
            trackingTap = false
            moving = false
            longPressFired = false
            return false
        }
        val here = IntArray(2)
        getLocationOnScreen(here)
        val inside = press.rawX >= here[0] && press.rawX < here[0] + width &&
            press.rawY >= here[1] && press.rawY < here[1] + height
        when (press.actionMasked) {
            android.view.MotionEvent.ACTION_DOWN -> {
                /* Keep the left bezel for the native drawer even when the
                 * picture is full-screen. Every other point on the picture
                 * belongs to the picture, never to a control hidden behind it. */
                if (press.rawX <= EDGE_PASS_PX * resources.displayMetrics.density) {
                    trackingTap = false
                    return false
                }
                trackingTap = inside
                moving = false
                longPressFired = false
                if (!inside) return false
                downX = press.rawX
                downY = press.rawY
                downAt = android.os.SystemClock.uptimeMillis()
                val lp = layoutParams as? LayoutParams
                gestureStart = WallRect(
                    lp?.leftMargin ?: here[0], lp?.topMargin ?: here[1],
                    width.coerceAtLeast(1), height.coerceAtLeast(1))
                resizing = !fullScreen &&
                    press.rawX >= here[0] + width - RESIZE_HANDLE_PX * resources.displayMetrics.density &&
                    press.rawY >= here[1] + height - RESIZE_HANDLE_PX * resources.displayMetrics.density
                removeCallbacks(longPressTrigger)
                postDelayed(longPressTrigger, TAP_HOLD_MS)
                return true
            }
            android.view.MotionEvent.ACTION_MOVE -> {
                if (!trackingTap) return false
                val dx = (press.rawX - downX).toInt()
                val dy = (press.rawY - downY).toInt()
                if (!moving && Math.hypot(dx.toDouble(), dy.toDouble()) > TAP_SLOP_PX) {
                    moving = true
                    removeCallbacks(longPressTrigger)
                }
                if (moving && !fullScreen) {
                    val bounds = wallBounds()
                    val rect = if (resizing) {
                        VideoWallGeometry.resize(gestureStart, dx, dy,
                            bounds.first, bounds.second, minWallWidth(), minWallHeight())
                    } else {
                        VideoWallGeometry.move(gestureStart, dx, dy,
                            bounds.first, bounds.second, minWallWidth(), minWallHeight())
                    }
                    applyBox(rect)
                }
                return true
            }
            android.view.MotionEvent.ACTION_UP -> {
                if (!trackingTap) return false
                val moved = Math.hypot(
                    (press.rawX - downX).toDouble(), (press.rawY - downY).toDouble())
                val pressedFor = android.os.SystemClock.uptimeMillis() - downAt
                val wasMoving = moving
                val wasLongPress = longPressFired
                removeCallbacks(longPressTrigger)
                trackingTap = false
                moving = false
                longPressFired = false
                if (wasMoving) {
                    val lp = layoutParams as? LayoutParams
                    if (lp != null && lp.width > 0 && lp.height > 0) {
                        windowed = WallRect(lp.leftMargin, lp.topMargin, lp.width, lp.height)
                        try { onBoxChanged?.invoke(windowed.x, windowed.y,
                            windowed.width, windowed.height) }
                        catch (err: Throwable) { Log.w(TAG, "box changed: ${err.message}") }
                    }
                } else if (!wasLongPress && inside && moved <= TAP_SLOP_PX && pressedFor <= TAP_HOLD_MS) {
                    Log.i(TAG, "tap at ${press.rawX.toInt()},${press.rawY.toInt()}")
                    try { onTap?.invoke(press.rawX, press.rawY) }
                    catch (err: Throwable) { Log.w(TAG, "tap: ${err.message}") }
                }
                return true
            }
            android.view.MotionEvent.ACTION_CANCEL -> {
                val was = trackingTap
                removeCallbacks(longPressTrigger)
                trackingTap = false
                moving = false
                longPressFired = false
                return was
            }
        }
        return trackingTap
    }

    @Suppress("ClickableViewAccessibility")
    override fun onTouchEvent(event: android.view.MotionEvent?): Boolean = false

    override fun onInterceptTouchEvent(event: android.view.MotionEvent?): Boolean = false

    // ---------------------------------------------------------------- api

    /** Show the wall and keep it fed. Safe to call when already running. */
    fun start() {
        if (!running.compareAndSet(false, true)) return
        onMain {
            refreshVisibility()
            build()
        }
        pump = scope.launch { feed() }
    }

    /** Hide it and let everything go. Safe to call when already stopped. */
    fun stop() {
        if (!running.compareAndSet(true, false)) return
        pump?.cancel()
        pump = null
        fresh?.cancel()
        fresh = null
        onMain {
            removeCallbacks(watchdog)  // #1440
            releaseWallBoost()
            try { player?.release() } catch (err: Throwable) { }
            player = null
            listed.clear()
            showing = ""
            playback = "off"
            held = false; holdUntil = 0L; menuHidden = false
            atIndex = -1; atCount = 0; atPos = -1L; atDuration = -1L
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
        onMain { refreshVisibility() }
    }

    private fun refreshVisibility() {
        visibility = if (running.get() && !veiled && !menuHidden) View.VISIBLE else View.GONE
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
        lp.width = rect.width
        lp.height = rect.height
        lp.leftMargin = rect.x
        lp.topMargin = rect.y
        lp.gravity = android.view.Gravity.TOP or android.view.Gravity.START
        layoutParams = lp
    }

    /** Put the wall where the operator dragged the set to, in DEVICE pixels. */
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
                lp.gravity = android.view.Gravity.TOP or android.view.Gravity.START
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

    /** Fill the physical glass and release any inspection hold atomically. */
    fun showFullScreen() {
        onMain {
            val lp = layoutParams as? LayoutParams ?: return@onMain
            if (!fullScreen && lp.width > 0 && lp.height > 0) {
                windowed = WallRect(lp.leftMargin, lp.topMargin, lp.width, lp.height)
            }
            lp.width = LayoutParams.MATCH_PARENT
            lp.height = LayoutParams.MATCH_PARENT
            lp.leftMargin = 0; lp.topMargin = 0
            lp.gravity = android.view.Gravity.TOP or android.view.Gravity.START
            layoutParams = lp
            fullScreen = true
            releaseMenuNow()
        }
    }

    /** Return to the last measured window and resume the endless set. */
    fun showWindowed() {
        onMain {
            if (windowed.width > 0 && windowed.height > 0) applyBox(windowed)
            fullScreen = false
            releaseMenuNow()
        }
    }

    /**
     * [#1192] HOW LOUD THE SET PLAYS ON THIS TERMINAL.
     *
     * "Offer a slider for setting the volume of videos that play as well."
     *
     * The wall is not in the page, so no slider in any document could reach
     * it: `document.querySelectorAll("audio,video")` - the walk every level
     * road in this product makes - cannot see a SurfaceView.  This is the
     * door, reached through the bridge's `videoWall("level", {level: v})`.
     *
     * REMEMBERED, not written once.  The #1440 watchdog throws the player
     * away and builds a new one on the third strike of "ready but frozen",
     * and a level that lived only on the player would come back at 1 - the
     * operator would have set it, heard it, and then heard it undone by a
     * repair he never saw.  build() reads this field.
     */
    fun setLevel(value: Double) {
        val v = value.coerceIn(0.0, 2.0).toFloat()
        wallLevel = v
        onMain {
            try { player?.let { applyWallLevel(it) } }
            catch (err: Throwable) { Log.w(TAG, "level: ${err.message}") }
        }
    }

    /** What the level is, without touching the player. */
    fun level(): Double = wallLevel.toDouble()

    fun state(): JSONObject = JSONObject()
        .put("on", running.get())
        .put("held", held)                          // [#1386]
        .put("menu_hidden", menuHidden)
        .put("fullscreen", fullScreen)
        /* [#1386] WHERE THE PICTURE ACTUALLY IS, in device pixels.
         * The page cannot lay a menu over this surface - it is
         * composited above an opaque WebView - so the only way to
         * make the options reachable is to stand them CLEAR of the
         * rectangle, and the page has no other way to learn it. */
        .put("x", (layoutParams as? LayoutParams)?.leftMargin ?: 0)
        .put("y", (layoutParams as? LayoutParams)?.topMargin ?: 0)
        .put("w", width)
        .put("h", height)
        .put("veiled", veiled)
        .put("queued", aheadCount())
        .put("queued_s", aheadMs() / 1000.0)                // [#1212]
        .put("playing", showing)
        .put("made", made)
        .put("level", wallLevel.toDouble())          // [#1192]
        .put("boost_mb", if (wallLevel > 1f) (2000.0 * log10(wallLevel.toDouble())).roundToInt() else 0)
        .put("cached", den.listFiles()?.size ?: 0)
        /* #1440: what the watchdog saw on its last tick - readable from any
         * thread, and the only honest answer to "is it frozen?". */
        .put("playback", playback)
        .put("play_when_ready", playWhenReady)
        .put("index", atIndex)
        .put("count", atCount)
        .put("position_ms", atPos)
        .put("duration_ms", atDuration)
        .put("still_s", if (stillSince > 0L) (android.os.SystemClock.elapsedRealtime() - stillSince) / 1000.0 else 0.0)
        .put("kicks", kicks)
        .put("last_kick", lastKick)
        .put("last_error", lastError)
        .put("repairs", repairs)
        .put("last_repair", lastRepair)

    // ------------------------------------------------------- the watchdog

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

    private fun kick(why: String, act: () -> Unit) {
        kicks += 1
        lastKick = "${stamp()} $why"
        Log.w(TAG, "kick #$kicks: $why")
        try { act() } catch (err: Throwable) { Log.w(TAG, "kick failed: ${err.message}") }
        stillSince = android.os.SystemClock.elapsedRealtime()
    }

    /** Main thread, once a second: is the picture moving, and if not, why not. */
    /**
     * [#1386] Freeze on this clip while a menu is open over it, or let it
     * run again. The picture is untouched either way.
     */
    fun hold(on: Boolean) {
        onMain { setHoldNow(on) }
    }

    /** Restart the active playlist item and retire any menu in one main-thread turn. */
    fun replay() {
        onMain {
            val p = player ?: return@onMain
            try {
                releaseMenuNow()
                val index = p.currentMediaItemIndex
                if (index >= 0) p.seekTo(index, 0L) else p.seekTo(0L)
                p.playWhenReady = true
                if (p.playbackState == Player.STATE_IDLE) p.prepare()
                stillSince = 0L
            } catch (err: Throwable) {
                lastError = "${stamp()} replay: ${err.message}"
                Log.w(TAG, "replay: ${err.message}")
            }
        }
    }

    /** Rebuild the hardware player from its existing local runway. */
    fun repair() {
        onMain {
            repairs += 1
            lastRepair = "${stamp()} operator repair"
            lastError = ""
            menuHidden = false
            held = false
            holdUntil = 0L
            veiled = false
            if (!running.get()) {
                running.set(true)
                refreshVisibility()
                build()
                pump = scope.launch { feed() }
                return@onMain
            }
            val old = player
            val from = old?.currentMediaItemIndex?.coerceAtLeast(0) ?: 0
            val position = old?.currentPosition?.coerceAtLeast(0L) ?: 0L
            val keep = ArrayList(listed.drop(from))
            releaseWallBoost()
            try { old?.release() } catch (_: Throwable) { }
            player = null
            listed.clear()
            showing = ""
            build()
            val fresh = player ?: return@onMain
            for (clip in keep) {
                fresh.addMediaItem(MediaItem.fromUri(Uri.fromFile(clip.file)))
                listed.add(clip)
            }
            if (listed.isNotEmpty()) {
                showing = listed.first().id
                fresh.seekTo(0, position)
            }
            fresh.prepare()
            fresh.playWhenReady = true
            refreshVisibility()
        }
    }

    fun isHeld(): Boolean = held

    /** The HTML menu cannot paint over a SurfaceView. Temporarily retire the
     *  surface while preserving the page-requested veil, and bound the hold
     *  so an abandoned sheet can never stop an endless station forever. */
    fun menu(on: Boolean) {
        onMain {
            menuHidden = on
            setHoldNow(on)
            refreshVisibility()
        }
    }

    private fun setHoldNow(on: Boolean) {
        held = on
        holdUntil = if (on) android.os.SystemClock.elapsedRealtime() + MENU_HOLD_MAX_MS else 0L
        try { player?.playWhenReady = !on } catch (err: Throwable) {
            Log.w(TAG, "hold: ${err.message}")
        }
        stillSince = 0L
    }

    private fun releaseMenuNow() {
        menuHidden = false
        setHoldNow(false)
        refreshVisibility()
    }

    private fun watch() {
        val p = player ?: return
        if (!running.get()) return
        val now = android.os.SystemClock.elapsedRealtime()
        /* A held wall is standing still ON PURPOSE, but not indefinitely.
         * The main-thread watchdog owns this deadline because WebView timers
         * are exactly what become unreliable when the tablet is under load. */
        if (held) {
            if (holdUntil > 0L && now >= holdUntil) {
                Log.w(TAG, "inspection hold expired; resuming the endless set")
                releaseMenuNow()
                try { onHoldExpired?.invoke() }
                catch (err: Throwable) { Log.w(TAG, "hold expiry: ${err.message}") }
            } else {
                stillSince = 0L
                return
            }
        }
        val idx = p.currentMediaItemIndex
        val pos = p.currentPosition
        val st = p.playbackState
        playback = stateName(st)
        playWhenReady = p.playWhenReady
        atCount = p.mediaItemCount
        atDuration = p.duration
        retally()                                           // [#1212]
        val moved = idx != atIndex || pos != atPos
        atIndex = idx
        atPos = pos
        if (moved || stillSince == 0L) { stillSince = now; return }
        val still = now - stillSince
        val ahead = (p.mediaItemCount - idx - 1).coerceAtLeast(0)
        when {
            st == Player.STATE_ENDED && ahead > 0 && still > 800L ->
                kick("ended with $ahead queued") {
                    p.seekTo(idx + 1, 0L)
                    p.playWhenReady = true
                    if (p.playbackState == Player.STATE_IDLE) p.prepare()
                }
            st == Player.STATE_IDLE && p.mediaItemCount > 0 && still > 2_000L ->
                kick("idle with ${p.mediaItemCount} listed") { p.playWhenReady = true; p.prepare() }
            st == Player.STATE_BUFFERING && still > BUFFER_STUCK_MS ->
                kick("buffering ${still / 1000}s on $showing") {
                    if (ahead > 0) p.seekTo(idx + 1, 0L) else p.prepare()
                }
            st == Player.STATE_READY && !p.playWhenReady && still > 1_500L ->
                kick("play flag dropped") { p.playWhenReady = true }
            st == Player.STATE_READY && p.playWhenReady && still > READY_STUCK_MS ->
                if (kicks % 3 == 2) kick("ready but frozen ${still / 1000}s - rebuilding the player") { rebuild() }
                else kick("ready but frozen ${still / 1000}s - surface re-attached") {
                    p.setVideoSurfaceView(screen)
                    if (ahead > 0) p.seekTo(idx + 1, 0L)
                }
        }
    }

    /** Throw the player away and start a new one on the same playlist. */
    private fun rebuild() {
        val old = player ?: return
        val keep = ArrayList(listed)
        val from = atIndex.coerceAtLeast(0)
        releaseWallBoost()
        try { old.release() } catch (err: Throwable) { }
        player = null
        listed.clear()
        showing = ""
        build()
        val p = player ?: return
        for ((i, clip) in keep.withIndex()) {
            if (i < from) continue
            try {
                p.addMediaItem(MediaItem.fromUri(Uri.fromFile(clip.file)))
                listed.add(clip)
            } catch (err: Throwable) { }
        }
        if (listed.isNotEmpty()) {
            showing = listed[0].id
            try { p.seekTo(0, 0L) } catch (err: Throwable) { }
        }
    }

    // -------------------------------------------------------- the player

    /** Everything ExoPlayer is told must be told on the main thread. */
    private fun onMain(work: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) work() else post(work)
    }

    private fun build() {
        if (player != null) return
        /* [#1212] A LOAD CONTROL FOR WHOLE LOCAL FILES, BACK TO BACK.
         * DefaultLoadControl will not start an item until it holds
         * bufferForPlaybackMs of it - 2500 by default, which is longer than
         * half the clips in this library (#1422 lets a slot be the clip's own
         * length and the shortest measured is 1.1 s). Everything here is
         * already on disk, so the only honest answer is "as soon as there is
         * a frame". */
        val control = DefaultLoadControl.Builder()
            .setBufferDurationsMs(
                LOAD_MIN_MS, LOAD_MAX_MS, LOAD_PLAY_MS, LOAD_REPLAY_MS)
            .setPrioritizeTimeOverSizeThresholds(true)
            .build()
        val p = ExoPlayer.Builder(context).setLoadControl(control).build()
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
        val audioSession = audioManager?.generateAudioSessionId() ?: AudioManager.ERROR
        if (audioSession != AudioManager.ERROR) {
            try {
                p.setAudioSessionId(audioSession)
                wallBoost = LoudnessEnhancer(audioSession)
            } catch (err: Throwable) {
                releaseWallBoost()
                Log.w(TAG, "video boost unavailable: ${err.message}")
            }
        }
        p.setVideoSurfaceView(screen)
        p.repeatMode = Player.REPEAT_MODE_OFF
        p.playWhenReady = true
        applyWallLevel(p)                                        // [#1192]
        p.addListener(object : Player.Listener {
            override fun onMediaItemTransition(item: MediaItem?, reason: Int) {
                val at = p.currentMediaItemIndex
                showing = listed.getOrNull(at)?.id ?: ""
                Log.i(TAG, "now showing $showing (item $at of ${p.mediaItemCount})")
                if (showing.isNotEmpty()) onClipChanged?.invoke(showing)
                /* [#1212] NOT ON THE FRAME OF THE JOIN.
                 * Measured over thirteen transitions: four of them went
                 * BUFFERING one millisecond after this line and stayed
                 * there 31-127 ms, and the item count dropped in the same
                 * breath. removeMediaItems() inside onMediaItemTransition
                 * edits the timeline while the player is moving across it.
                 * Posted, it lands after the hand-over has settled and the
                 * picture never stops. */
                post { trimBehind(p) }
            }

            override fun onPlaybackStateChanged(state: Int) {
                playback = stateName(state)  // #1440
                Log.i(TAG, "state ${stateName(state)} at item ${p.currentMediaItemIndex} of ${p.mediaItemCount}")
            }

            override fun onPlayerError(error: PlaybackException) {
                /* A clip this device cannot decode must not stop the set.
                 * ExoPlayer has already halted on it, so it is thrown away
                 * and the playlist resumed past it. */
                val at = p.currentMediaItemIndex
                val bad = listed.getOrNull(at)
                lastError = "${stamp()} ${error.errorCodeName} on ${bad?.id}"  // #1440
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
        /* #1440: the watchdog rides the main thread's Handler, which is
         * exactly the thread that stays alive when ExoPlayer stops. */
        removeCallbacks(watchdog)
        stillSince = 0L
        postDelayed(watchdog, WATCH_MS)
    }

    /**
     * Keep the playlist from growing without end. Items behind the
     * playhead are spent; `listed` is kept in step because the player's
     * indices are the only thing that says which clip is on.
     */
    private fun trimBehind(p: ExoPlayer) {
        if (p != player || !running.get()) return          // [#1212] posted: it may have gone
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
                if (listed.any { it.id == clip.id }) return@onMain
                p.addMediaItem(MediaItem.fromUri(Uri.fromFile(clip.file)))
                listed.add(clip)
                made += 1
                if (showing.isEmpty()) {
                    showing = listed.getOrNull(p.currentMediaItemIndex)?.id ?: clip.id
                    onClipChanged?.invoke(showing)
                }
                if (p.playbackState == Player.STATE_IDLE) p.prepare()
                /* #1440: a playlist that had ENDED does not start again just
                 * because an item was appended - it has to be sought. */
                if (p.playbackState == Player.STATE_ENDED) {
                    p.seekTo(p.mediaItemCount - 1, 0L)
                    p.playWhenReady = true
                }
                retally()                                   // [#1212]
            } catch (err: Throwable) {
                Log.w(TAG, "offer ${clip.id}: ${err.message}")
            }
        }
    }

    /** Element volume carries 0..100%; LoudnessEnhancer carries 100..200%. */
    private fun applyWallLevel(p: ExoPlayer) {
        val wanted = wallLevel.coerceIn(0f, 2f)
        p.volume = wanted.coerceAtMost(1f)
        val effect = wallBoost ?: return
        if (wanted > 1f) {
            effect.setTargetGain((2000.0 * log10(wanted.toDouble())).roundToInt())
            effect.enabled = true
        } else {
            effect.enabled = false
            effect.setTargetGain(0)
        }
    }

    private fun releaseWallBoost() {
        try { wallBoost?.enabled = false } catch (err: Throwable) { }
        try { wallBoost?.release() } catch (err: Throwable) { }
        wallBoost = null
    }

    /**
     * Drop every prefetched choice and replace it with the server's freshly
     * admitted batch. The current picture may run while the first whole file
     * is cached; once it lands, it becomes current and the rest form the new
     * runway in the exact order the server returned.
     */
    fun shuffleQueue(rows: JSONArray? = null) {
        fresh?.cancel()
        fresh = null
        reshuffling = true
        val shuffledAt = System.currentTimeMillis()
        val requested = HashSet<String>()
        if (rows != null) {
            for (i in 0 until rows.length()) {
                rows.optJSONObject(i)?.optString("id")?.takeIf { it.isNotBlank() }
                    ?.let { requested.add(it) }
            }
        }
        onMain {
            val p = player ?: return@onMain
            val at = p.currentMediaItemIndex.coerceAtLeast(0)
            try {
                if (p.mediaItemCount > at + 1) p.removeMediaItems(at + 1, p.mediaItemCount)
                while (listed.size > at + 1) listed.removeAt(listed.lastIndex)
                retally()
                lastKick = "${stamp()} operator rebuilt the clip queue"
            } catch (err: Throwable) {
                lastError = "${stamp()} shuffle: ${err.message}"
                Log.w(TAG, "shuffle: ${err.message}")
            }
            val keep = listed.map { it.id }.toHashSet().apply { addAll(requested) }
            scope.launch(Dispatchers.IO) {
                try {
                    den.listFiles()?.forEach { file ->
                        /* A replacement may finish downloading after this
                         * coroutine starts. Never erase a file created by
                         * the shuffle we are servicing. */
                        if (file.isFile && file.lastModified() < shuffledAt
                            && file.nameWithoutExtension !in keep) file.delete()
                    }
                } catch (err: Throwable) { Log.w(TAG, "shuffle cache: ${err.message}") }
            }
        }

        scope.launch {
            var inserted = 0
            try {
                if (rows != null) {
                    for (i in 0 until rows.length()) {
                        val row = rows.optJSONObject(i) ?: continue
                        val id = row.optString("id")
                        val url = row.optString("url")
                        if (id.isBlank() || url.isBlank()) continue
                        val seconds = row.optDouble("seconds", row.optDouble("length", 0.0))
                        val clip = withContext(Dispatchers.IO) {
                            val base = client.config().base.trimEnd('/')
                            val absolute = if (url.startsWith("http://") || url.startsWith("https://")) {
                                url
                            } else {
                                "$base/${url.trimStart('/')}"
                            }
                            val file = pull(absolute, id) ?: return@withContext null
                            remember(id)
                            Clip(id, file, seconds)
                        } ?: continue
                        withContext(Dispatchers.Main.immediate) {
                            val p = player ?: return@withContext
                            try {
                                val place = if (inserted == 0) {
                                    (p.currentMediaItemIndex + 1).coerceIn(0, p.mediaItemCount)
                                } else {
                                    p.mediaItemCount
                                }
                                p.addMediaItem(place, MediaItem.fromUri(Uri.fromFile(clip.file)))
                                listed.add(place.coerceAtMost(listed.size), clip)
                                made += 1
                                if (inserted == 0) {
                                    releaseMenuNow()
                                    p.seekTo(place, 0L)
                                    p.playWhenReady = true
                                    if (p.playbackState == Player.STATE_IDLE) p.prepare()
                                }
                                inserted += 1
                                retally()
                            } catch (err: Throwable) {
                                lastError = "${stamp()} shuffle insert: ${err.message}"
                            }
                        }
                    }
                }
            } finally {
                reshuffling = false
            }
        }
    }

    /** Put an explicitly selected neighbour on next, without waiting behind
     *  the prefetched runway. The bytes are still pulled whole off the UI
     *  thread; only the playlist insertion and seek touch ExoPlayer. */
    fun playNow(id: String, url: String, seconds: Double) {
        if (id.isBlank() || url.isBlank()) return
        scope.launch {
            val clip = withContext(Dispatchers.IO) {
                val base = client.config().base.trimEnd('/')
                val absolute = if (url.startsWith("http://") || url.startsWith("https://")) {
                    url
                } else {
                    "$base/${url.trimStart('/')}"
                }
                val file = pull(absolute, id) ?: return@withContext null
                remember(id)
                Clip(id, file, seconds)
            }
            if (clip == null) {
                lastError = "${stamp()} selected clip $id could not be cached"
                return@launch
            }
            onMain {
                val p = player ?: return@onMain
                try {
                    val at = (p.currentMediaItemIndex + 1).coerceIn(0, p.mediaItemCount)
                    p.addMediaItem(at, MediaItem.fromUri(Uri.fromFile(clip.file)))
                    listed.add(at.coerceAtMost(listed.size), clip)
                    made += 1
                    releaseMenuNow()
                    p.seekTo(at, 0L)
                    p.playWhenReady = true
                    if (p.playbackState == Player.STATE_IDLE) p.prepare()
                    retally()
                } catch (err: Throwable) {
                    lastError = "${stamp()} selected clip $id: ${err.message}"
                    Log.w(TAG, "play selected $id: ${err.message}")
                }
            }
        }
    }

    // ------------------------------------------------------------ the pump

    private suspend fun feed() {
        while (scope.isActive && running.get()) {
            try {
                if (reshuffling) {
                    delay(250)
                    continue
                }
                /* [#1212] THE RUNWAY IS PICTURE, NOT ROWS. Three clips is
                 * eighteen seconds on a six-second library and two point two
                 * on the short end of this one, and a wall that runs out
                 * shows the join it was queued to hide. Both bounds hold: at
                 * least AHEAD_MS of picture, and never more than
                 * ROWS_MOST rows however short the clips are. */
                val thin = aheadMs() < AHEAD_MS || aheadRows() < KEEP_AHEAD
                if (thin && aheadRows() < ROWS_MOST) {
                    /* The station's ring is the full-library shuffled deck;
                     * the larder is only continuity insurance. Taking disk
                     * first made a healthy wall rotate its small local cache
                     * while thousands of unplayed server choices waited.
                     * With 24 seconds of runway the ring has time to answer;
                     * if it cannot, the least-recent local file still keeps
                     * the picture moving. */
                    val got = nextRingClip()
                    if (got != null) {
                        offer(got)
                        launchFresh()
                        delay(120)          // let the main thread's tally land
                    } else {
                        val cached = withContext(Dispatchers.IO) { fromLarder() }
                        if (cached != null) {
                            offer(cached)
                            delay(120)
                        } else {
                            delay(1_200)
                        }
                    }
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

    private fun launchFresh() {
        if (fresh?.isActive == true || !running.get() || reshuffling) return
        fresh = scope.launch {
            try {
                val got = nextRingClip()
                if (got != null && running.get()) offer(got)
            } catch (err: kotlinx.coroutines.CancellationException) {
                throw err
            } catch (err: Throwable) {
                Log.w(TAG, "fresh: ${err.javaClass.simpleName}: ${err.message}")
            } finally {
                fresh = null
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

    /* [#1212] The same question in seconds. `aheadTally` is written on the
     * main thread - by the watchdog once a second and by every offer() - and
     * read from the pump, which is why it is volatile and why the pump rests
     * a moment after an offer rather than trusting a number it just changed.
     * A clip whose length the station did not give us counts as the cycle's
     * own floor, exactly as app.py's sfx_cycle_slot does. */
    @Volatile private var aheadTally: Long = 0L
    @Volatile private var aheadRowsTally: Int = 0

    private fun secondsOf(c: Clip): Long =
        if (c.seconds > 0.0) (c.seconds * 1000.0).toLong() else SLOT_FLOOR_MS

    /** Main thread only: how much picture is queued past the one showing. */
    private fun retally() {
        val p = player
        if (p == null) { aheadTally = 0L; aheadRowsTally = 0; return }
        val at = try { p.currentMediaItemIndex } catch (err: Throwable) { 0 }
        var ms = 0L
        var rows = 0
        for (i in (at + 1) until listed.size) {
            ms += secondsOf(listed[i])
            rows += 1
        }
        aheadTally = ms
        aheadRowsTally = rows
    }

    private fun aheadMs(): Long = aheadTally

    private fun aheadRows(): Int = aheadRowsTally

    /** The next fresh clip off the ring. The caller owns the larder fallback. */
    private suspend fun nextRingClip(): Clip? = withContext(Dispatchers.IO) {
        val base = client.config().base
        val text = try {
            client.getMediaText("$base/api/dj/video")
        } catch (err: Throwable) {
            Log.w(TAG, "ring: ${err.message}")
            return@withContext null
        }
        val rows = JSONObject(text).optJSONArray("clips")
        if (rows != null) {
            for (i in 0 until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                val id = row.optString("id")
                val url = row.optString("url")
                if (id.isBlank() || url.isBlank()) continue
                if (row.optBoolean("silent_picture", false)) continue
                if (rung.contains(id) || listed.any { it.id == id }) continue
                val secs = row.optDouble("length", row.optDouble("seconds", 0.0))
                val file = pull(base + url, id)
                /* Remembered either way: a clip the station cannot give us
                 * is as finished with as one that played, and leaving a
                 * failure eligible meant picking the same dead id for ever. */
                remember(id)
                if (file == null) continue
                return@withContext Clip(id, file, secs)     // [#1212]
            }
        }
        null
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
                    && !rung.contains(it.nameWithoutExtension)
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
            val bytes = client.getMediaBytes(url).first
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
        /** Left bezel remains the drawer's gesture even over full-screen video. */
        private const val EDGE_PASS_PX = 28f
        /** A one-finger drag from this corner resizes; elsewhere it moves. */
        private const val RESIZE_HANDLE_PX = 72f
        private const val MIN_WIDTH_DP = 220f
        private const val MIN_HEIGHT_DP = 132f
        /** [#1441] a press that moves further than this was a drag, not a tap. */
        private const val TAP_SLOP_PX = 24.0
        private const val TAP_HOLD_MS = 700L
        /** An abandoned options sheet must never freeze a perpetual wall. */
        private const val MENU_HOLD_MAX_MS = 90_000L
        /** How many clips to keep queued past the one playing. */
        private const val KEEP_AHEAD = 3
        /* [#1212] ...and what actually governs the pump now: SECONDS of
         * picture queued past the one showing, which is what a hand-over
         * needs and what a row count stopped meaning when #1422 let a slot
         * be the clip's own length. 24 s is the station's own runway
         * (SFX_CYCLE_AHEAD = 28) less a poll. The row cap is only a bound. */
        private const val AHEAD_MS = 24_000L
        private const val ROWS_MOST = 12
        /** A clip the ring gave no length for, paced like app.py's floor. */
        private const val SLOT_FLOOR_MS = 6_000L
        /* [#1212] The load control, for whole files that are already on disk.
         * bufferForPlaybackMs defaults to 2500, which is longer than half
         * the clips in this library. */
        private const val LOAD_MIN_MS = 5_000
        private const val LOAD_MAX_MS = 30_000
        private const val LOAD_PLAY_MS = 250
        private const val LOAD_REPLAY_MS = 500
        /** Spent items left behind the playhead before the list is trimmed.
         * [#1212] was 2: a trim ran on nearly every join, and a trim on the
         * frame of a join is what the BUFFERING was. */
        private const val BEHIND_KEEP = 4
        private const val RUNG_KEEP = 400
        private const val MIN_BYTES = 4096
        private const val CACHE_MOST = 240
        private const val CACHE_BYTES = 768L * 1024L * 1024L
        /* #1440: the watchdog's tick and its two patience bounds. */
        private const val WATCH_MS = 1_000L
        private const val BUFFER_STUCK_MS = 8_000L
        private const val READY_STUCK_MS = 5_000L
    }
}
