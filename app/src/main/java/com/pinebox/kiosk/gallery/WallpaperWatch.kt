package com.pinebox.kiosk.gallery

import android.app.WallpaperManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import com.pinebox.kiosk.net.StationClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import kotlin.math.max
import kotlin.math.min

/**
 * THE TABLET WEARS WHAT THE STATION IS SELLING.
 *
 * "On the Pine Box tablet constantly every five minutes be replacing the
 * wallpaper with the latest image being hawked by the Pine Box gallery on the
 * station. I want the lock screen and the home screen to always have images
 * from the Pine Box Gallery as they are being chosen by the station and being
 * sold."
 *
 * WHICH PICTURE, and in what order. The station already knows - three roads
 * sell things (the sales floor, the ad break, the gallery press) and #900
 * folded all three into one answer, `selling_now`, which rides on /api/dj
 * carrying the bare gallery filename. That is the piece "being sold", so it
 * is asked for first and it is what the operator actually meant.
 *
 * But the station is not selling something every minute of the day, and a
 * tablet that reverts to a black rectangle between spots is not what was
 * asked for either - "always have images from the Pine Box Gallery". So when
 * nothing is on the block the newest render in the gallery log is used
 * instead. The wallpaper therefore always shows the station's own work, and
 * shows the thing on the block whenever there is one.
 *
 * IT ASKS THE ONE POLLER FIRST. StationFeed already holds /api/dj for the
 * whole app - that is the single-poller rule this project has starved the
 * station by breaking before - so `selling_now` is read out of its snapshot
 * and costs nothing at all. A direct fetch happens ONLY when that snapshot is
 * stale, which means nothing is collecting the feed: the wallpaper still has
 * to change on a locked tablet with no view attached, and that is precisely
 * when it matters most. One 80 kB read every five minutes, in that case only.
 *
 * ONLY WHEN IT CHANGES. Setting the same wallpaper again is not free - it
 * decodes a multi-megabyte PNG, writes it to the wallpaper store and
 * broadcasts a change to everything listening. The filename last hung is
 * remembered, and an unchanged answer does nothing at all.
 */
class WallpaperWatch(
    private val context: Context,
    private val client: StationClient,
    private val feed: com.pinebox.kiosk.feed.StationFeed,
    private val scope: CoroutineScope,
) {

    private var job: Job? = null

    /** The gallery filename currently hanging, so an unchanged one is free. */
    @Volatile private var hung: String = ""

    /* #1296: IS ANYBODY READING?
     *
     * Hanging a wallpaper makes systemui regenerate the Material You
     * overlays, which raises CONFIG_ASSETS_PATHS (0x80000000) - a
     * config change with no name in the android:configChanges flag
     * set, so MainActivity cannot declare it away and is RELAUNCHED.
     * Measured on the tablet: seven relaunches in thirty-three
     * minutes, on exactly this class's five-minute period, each one
     * taking the operator's folds and their place in the script with
     * it.
     *
     * PineApp's own note says what the resolution is - "the
     * wallpaper's whole point is to be right when the app is NOT the
     * thing on screen". So the piece is still chosen every round, and
     * hung at the first moment there is no view to tear down. It is
     * therefore always up before the home screen or the keyguard can
     * be looked at, which is the whole of where it is ever visible. */
    @Volatile var reading: Boolean = false

    /**
     * #1182T: A FOREGROUND APP HAS ASKED THE TERMINAL TO RELAX.
     *
     * Set by Standby. It is not the main defence - held() reads the activity
     * manager directly and needs nobody to ask - but it costs nothing, it is
     * instant, and it covers the second or two around a hand-over in which the
     * dump has not caught up yet.
     */
    @Volatile var standingBy: Boolean = false

    /** Chosen while someone was reading, waiting for them to stop. */
    @Volatile private var waiting: Piece? = null

    @Volatile var lastSaid: String = "not started"
        private set

    fun start() {
        if (job?.isActive == true) return
        job = scope.launch(Dispatchers.IO) {
            while (isActive) {
                try {
                    step()
                } catch (err: Exception) {
                    /* The wallpaper is decoration. Nothing here is allowed to
                     * take the terminal down with it, and a failure that
                     * repeats every five minutes belongs in the log rather
                     * than on the glass. */
                    Log.w(TAG, "wallpaper round stumbled", err)
                    lastSaid = "stumbled: " + (err.message ?: err.javaClass.simpleName)
                }
                delay(EVERY_MS)
            }
        }
        Log.i(TAG, "wallpaper watch on")
    }

    /**
     * #1296: THE VIEW HAS GONE, SO PUT UP WHAT WAS WAITING.
     *
     * Called from MainActivity.onPause. The relaunch this avoids costs
     * nothing here: there is no view left to tear down, and the
     * wallpaper is up before either surface that shows it can be seen.
     *
     * Its own coroutine on the IO dispatcher because it decodes and
     * scales a bitmap, and onPause is on the main thread.
     */
    fun released() {
        reading = false
        if (waiting == null) return
        scope.launch(Dispatchers.IO) {
            try {
                /* #1182T: LET THE GLASS SETTLE BEFORE ASKING WHO HAS IT.
                 *
                 * This runs from onPause, and onPause is precisely the moment
                 * another app is arriving - the incoming activity has not
                 * resumed yet, so the activity manager would still name us, or
                 * nobody, and held() would wave the repaint through into the
                 * face of the app that is about to appear. That is the bug
                 * this whole item is about, met on the one path where the
                 * timing is worst.
                 *
                 * A second and a half is longer than a hand-over takes and far
                 * shorter than anything the picture is racing: the piece has
                 * already waited up to five minutes to be chosen, and if this
                 * round still finds the glass busy the next one picks it up. */
                delay(SETTLE_MS)
                step()
            } catch (err: Exception) {
                Log.w(TAG, "the held piece would not hang", err)
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    /** What is hanging, for the rail to show. */
    fun state(): JSONObject = JSONObject()
        .put("showing", hung)
        .put("say", lastSaid)

    /** Hang one now, whatever the clock says. */
    suspend fun now(): String {
        step()
        return lastSaid
    }

    private suspend fun step() {
        val piece = choose()
        if (piece.name.isBlank()) {
            lastSaid = "the gallery has nothing to hang"
            return
        }
        if (piece.name == hung) {
            lastSaid = "still showing " + piece.name + " (" + piece.why + ")"
            waiting = null
            return
        }
        /* #1296, widened by #1182T: chosen now, hung when the glass is free.
         * "Free" used to mean "no view of OURS", and that turned out to mean
         * "somebody else's view" - see held(). */
        val busy = held()
        if (busy != null) {
            waiting = piece
            lastSaid = "holding " + piece.name + " until the glass is free (" + busy + ")"
            return
        }
        waiting = null
        val bytes = runCatching { client.getBytes(IMAGE + encode(piece.name)).first }
            .getOrElse {
                lastSaid = "could not fetch " + piece.name + ": " +
                    (it.message ?: it.javaClass.simpleName)
                return
            }
        val bitmap = fit(bytes)
        if (bitmap == null) {
            lastSaid = piece.name + " would not decode as a picture"
            return
        }
        hang(bitmap)
        bitmap.recycle()
        hung = piece.name
        lastSaid = "hung " + piece.name + " - " + piece.why
        Log.i(TAG, lastSaid)
    }

    /**
     * #1182T: WHO HAS THE GLASS, or null if nobody who would be hurt by a
     * repaint. The reason is returned rather than a boolean so that
     * `lastSaid` - which the rail shows the operator - says WHY a picture is
     * being held back, instead of the wallpaper appearing to be stuck.
     *
     * THE MEASUREMENT THIS WIDENS, in the AutoBrowse port's own words:
     *
     *   "Your own note says WallpaperWatch repaints 'only when no view is on
     *    the glass', which was the fix for #1296 - the kiosk relaunching
     *    itself. The consequence is that it repaints PRECISELY when a foreign
     *    app is in front, and setWallpaper raises CONFIG_ASSETS_PATHS
     *    (0x80000000), a configuration flag that cannot be declared in
     *    android:configChanges by any app. So every five minutes, our Activity
     *    is destroyed and recreated."
     *
     * That is correct, and it is our own #1296 note read back to us. The
     * platform flag was never about ownership; we only ever looked at our own
     * activity because ours was the only one that existed.
     *
     * THE ORDER OF THE CHECKS MATTERS.
     *
     *  - `reading` first, and on its own, because it is #1296 unchanged: our
     *    view is up, and nothing below is allowed to talk us out of that.
     *  - `standingBy` next, because a request is instant and a dump is not.
     *  - UNKNOWN from the dump means fall through to the pre-#1182T
     *    behaviour. A picture that is never hung again would be a feature
     *    quietly switching itself off, and this is decoration - it must fail
     *    towards doing its job, not towards stopping.
     *  - our own package is NOT safe just because the kiosk is the launcher.
     *    SparkActivity and DgxTerminalActivity are ours too and get destroyed
     *    by the same flag; #1296 was about exactly this.
     */
    private fun held(): String? {
        if (reading) return "a view of ours is on the glass"
        if (standingBy) return "a foreground app asked for standby"
        val top = com.pinebox.kiosk.kiosk.OnTheGlass.topPackage()
        if (top == com.pinebox.kiosk.kiosk.OnTheGlass.UNKNOWN) return null
        if (top == context.packageName) return "our own " + top + " is resumed"
        if (com.pinebox.kiosk.kiosk.OnTheGlass.isHomeOrSystem(context, top)) return null
        return top + " is on the glass"
    }

    private class Piece(val name: String, val why: String)

    /**
     * THE PIECE ON THE BLOCK, or the newest thing the station has made.
     *
     * The two reads are wrapped separately: the gallery fallback must still
     * work on a round where /api/dj is slow or refuses, because that is
     * exactly the round where the wallpaper would otherwise go stale.
     */
    private suspend fun choose(): Piece {
        runCatching {
            val dj = station()
            val sold = dj?.optJSONObject("selling_now")
            val name = sold?.optString("image", "") ?: ""
            if (name.isNotBlank() && looksLikeAPicture(name)) {
                return Piece(name, sold!!.optString("why", "on the block"))
            }
        }.onFailure { Log.w(TAG, "could not ask what is selling: " + it.message) }

        runCatching {
            val log = JSONObject(client.get("/api/generations?limit=24"))
            val rows = log.optJSONArray("generations")
            /* Newest first - read_generations slices the tail and reverses -
             * so the first file that is a still picture is the latest render.
             * VIDEO IS SKIPPED: that route serves .mp4 and .webm too, and a
             * wallpaper cannot be a video. */
            for (i in 0 until (rows?.length() ?: 0)) {
                val files = rows!!.optJSONObject(i)?.optJSONArray("files") ?: continue
                for (f in 0 until files.length()) {
                    val name = files.optString(f, "")
                    if (name.isNotBlank() && looksLikeAPicture(name)) {
                        return Piece(name, "the newest thing in the gallery")
                    }
                }
            }
        }.onFailure { Log.w(TAG, "could not read the gallery log: " + it.message) }

        return Piece("", "")
    }

    /**
     * THE STATION'S STATE, from the one poller where possible.
     *
     * StationFeed only polls while something is collecting its flow, so its
     * snapshot goes stale the moment no view is attached - which on a locked
     * tablet is most of the time. Freshness is therefore CHECKED rather than
     * assumed, and a stale snapshot falls through to a read of our own. An
     * earlier draft of this trusted the snapshot outright; it would have hung
     * whatever was selling when the screen was last unlocked, forever.
     */
    private suspend fun station(): JSONObject? {
        val snap = feed.snapshot()
        val held = snap.station
        if (held != null && System.currentTimeMillis() - snap.at < FRESH_MS) return held
        return runCatching { JSONObject(client.get("/api/dj")) }.getOrNull()
    }

    private fun looksLikeAPicture(name: String): Boolean {
        val low = name.lowercase()
        return low.endsWith(".png") || low.endsWith(".jpg") ||
            low.endsWith(".jpeg") || low.endsWith(".webp")
    }

    /** The route takes a bare filename, and spaces and brackets are legal in it. */
    private fun encode(name: String): String = android.net.Uri.encode(name)

    /**
     * DECODE AT A SIZE THIS TABLET CAN HOLD, THEN CENTRE-CROP TO THE SCREEN.
     *
     * ComfyUI renders can be several thousand pixels square; decoded whole on
     * a 4 GB tablet that is tens of megabytes of bitmap for a picture shown at
     * roughly 1340x800. So the bounds are read first and `inSampleSize` halves
     * it down before a single pixel is allocated.
     *
     * The crop matters because the gallery is mostly SQUARE and the screen is
     * not. Left to itself the wallpaper service letterboxes or stretches it;
     * taking the middle of the picture in the screen's own shape is what makes
     * it look like a photograph rather than a mistake.
     */
    private fun fit(bytes: ByteArray): Bitmap? {
        val manager = WallpaperManager.getInstance(context)
        val wantW = max(manager.desiredMinimumWidth, 720)
        val wantH = max(manager.desiredMinimumHeight, 720)

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

        var sample = 1
        while (bounds.outWidth / (sample * 2) >= wantW &&
            bounds.outHeight / (sample * 2) >= wantH
        ) sample *= 2

        val full = BitmapFactory.decodeByteArray(
            bytes, 0, bytes.size,
            BitmapFactory.Options().apply { inSampleSize = sample }
        ) ?: return null

        /* The largest rectangle of the picture that has the screen's shape,
         * taken from the middle. */
        val scale = max(wantW.toFloat() / full.width, wantH.toFloat() / full.height)
        val cropW = min(full.width.toFloat(), wantW / scale).toInt().coerceAtLeast(1)
        val cropH = min(full.height.toFloat(), wantH / scale).toInt().coerceAtLeast(1)
        val left = (full.width - cropW) / 2
        val top = (full.height - cropH) / 2

        val cropped = runCatching {
            Bitmap.createBitmap(full, left, top, cropW, cropH)
        }.getOrDefault(full)
        if (cropped !== full) full.recycle()

        val out = runCatching {
            Bitmap.createScaledBitmap(cropped, wantW, wantH, true)
        }.getOrDefault(cropped)
        if (out !== cropped) cropped.recycle()
        return out
    }

    /**
     * BOTH SCREENS, AND SAID SEPARATELY.
     *
     * FLAG_SYSTEM is the home screen and FLAG_LOCK the keyguard. They are set
     * in two calls rather than one because a build can refuse the lock screen
     * alone - some hand the keyguard to their own provider - and a single
     * combined call that throws would leave BOTH unchanged. The operator asked
     * for both; this way a refusal costs one of them, not the pair.
     */
    private fun hang(bitmap: Bitmap) {
        val manager = WallpaperManager.getInstance(context)
        runCatching {
            manager.setBitmap(bitmap, null, true, WallpaperManager.FLAG_SYSTEM)
        }.onFailure { Log.w(TAG, "the home screen refused it: " + it.message) }
        runCatching {
            manager.setBitmap(bitmap, null, true, WallpaperManager.FLAG_LOCK)
        }.onFailure { Log.w(TAG, "the lock screen refused it: " + it.message) }
    }

    private companion object {
        const val TAG = "PineWallpaper"
        const val EVERY_MS = 5 * 60 * 1000L
        /** Older than this and the feed is not being collected by anyone. */
        const val FRESH_MS = 30_000L
        /** #1182T: how long a hand-over is given to finish before we ask the
         *  activity manager who is actually in front. See released(). */
        const val SETTLE_MS = 1_500L
        const val IMAGE = "/api/generations/image/"
    }
}
