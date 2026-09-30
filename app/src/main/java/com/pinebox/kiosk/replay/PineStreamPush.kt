package com.pinebox.kiosk.replay

import android.content.Context
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import android.view.WindowManager
import com.pinebox.kiosk.net.StationClient
import java.io.ByteArrayOutputStream
import java.net.URLEncoder
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * PINESTREAM, THE TABLET'S HALF: this screen, a few pictures a second, to the
 * station.  [pinestream]
 *
 * "add a section here for enabling a pip stream of the pinetab / pineapp to be
 *  streamed to the stream page ... like the pinecam and call it pinestream."
 *
 * The page (pine-views/pinestream.js) decides WHETHER: it asks the station
 * which screen PineStream shows and says `run` every few seconds while it is
 * this one. This decides nothing. It captures while it is told to and stops
 *   - when the station answers a frame with keep:false (the operator's switch
 *     went off, or the desk was chosen) - the station is the master;
 *   - when `run` has not come for [DEADMAN_MS] (a page that froze must not
 *     leave the tablet filming);
 *   - after [FAIL_LIMIT] failed posts in a row.
 *
 * NO MEDIAPROJECTION, NO PROMPT: the same road as [ScreenReplay] - a
 * VirtualDisplay mirroring the real one (AUTO_MIRROR | SECURE, on the
 * platform-signed CAPTURE_VIDEO_OUTPUT and CAPTURE_SECURE_VIDEO_OUTPUT this
 * APK already holds), here into an ImageReader instead of an encoder. The
 * display exists only while streaming; frames the mirror produces between
 * two sends are closed unread, and one is turned into a JPEG only when the
 * rate says it is time - 640 px at 2 a second is a few ms of CPU a second.
 * An unchanged screen produces no frames, so the post is an empty keep-alive.
 * A sleeping screen, or a page that says the screen is private, sends
 * private=1 and no pixels.
 */
class PineStreamPush(
    private val context: Context,
    private val client: StationClient,
    private val scope: CoroutineScope,
) {
    companion object {
        private const val TAG = "PineStream"
        const val DEADMAN_MS = 12_000L
        private const val FAIL_LIMIT = 5
    }

    @Volatile private var fps = 2
    @Volatile private var width = 640
    @Volatile private var quality = 60
    @Volatile private var veiled = false
    @Volatile private var why = ""
    @Volatile private var lastRun = 0L
    @Volatile private var job: Job? = null
    @Volatile var reason = "not started"
        private set
    @Volatile private var sent = 0
    @Volatile private var kept = 0
    @Volatile private var fails = 0
    @Volatile private var lastError = ""
    @Volatile private var shape = ""

    private val latest = AtomicReference<ByteArray?>(null)
    @Volatile private var lastShotAt = 0L
    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private var reader: ImageReader? = null
    private var display: VirtualDisplay? = null
    private var builtWidth = 0
    private var scratch: Bitmap? = null

    @Synchronized
    fun run(opts: JSONObject?) {
        if (opts != null) {
            fps = opts.optInt("fps", fps).coerceIn(1, 5)
            width = opts.optInt("width", width).coerceIn(320, 960)
            quality = opts.optInt("quality", quality).coerceIn(30, 90)
            veiled = opts.optBoolean("private", false)
            why = opts.optString("why", "").take(120)
        }
        lastRun = SystemClock.elapsedRealtime()
        if (job?.isActive == true) return
        fails = 0
        reason = "running"
        job = scope.launch(Dispatchers.IO) { loop() }
    }

    @Synchronized
    fun stop(said: String) {
        job?.cancel()
        job = null
        if (reason == "running") reason = said
        release()
    }

    fun state(): JSONObject = JSONObject()
        .put("ok", true).put("running", job?.isActive == true).put("why", reason)
        .put("fps", fps).put("width", width).put("quality", quality).put("private", veiled)
        .put("sent", sent).put("kept", kept).put("fails", fails).put("lastError", lastError)
        .put("shape", shape)

    private suspend fun loop() {
        try {
            while (true) {
                if (SystemClock.elapsedRealtime() - lastRun > DEADMAN_MS) { reason = "the page stopped asking"; break }
                val t0 = SystemClock.elapsedRealtime()
                var query = "?source=pinetab"
                var body = ByteArray(0)
                val power = context.getSystemService(Context.POWER_SERVICE) as PowerManager
                val veil = when {
                    veiled -> why.ifBlank { "a private screen" }
                    !power.isInteractive -> "the PineTab's screen is asleep"
                    else -> ""
                }
                if (veil.isNotEmpty()) {
                    release()
                    query += "&private=1&why=" + URLEncoder.encode(veil, "UTF-8")
                } else {
                    val err = ensureDisplay()
                    if (err != null) {
                        query += "&private=1&why=" + URLEncoder.encode("the PineTab would not capture", "UTF-8")
                        lastError = err
                    } else {
                        val shot = latest.getAndSet(null)
                        if (shot != null) body = shot else kept += 1
                    }
                }
                val answer = try {
                    JSONObject(client.postBytes("/api/pinestream/frame$query", body, "image/jpeg"))
                } catch (err: CancellationException) {
                    throw err
                } catch (err: Exception) {
                    fails += 1
                    lastError = err.message ?: err.javaClass.simpleName
                    if (fails >= FAIL_LIMIT) { reason = "the station did not answer $FAIL_LIMIT times"; break }
                    delay(2000)
                    continue
                }
                fails = 0
                if (!answer.optBoolean("keep", false)) {
                    reason = answer.optString("say", "the station said stop").ifBlank { "the station said stop" }
                    break
                }
                if (body.isNotEmpty()) sent += 1
                /* the station is the master of the rate too */
                fps = answer.optInt("fps", fps).coerceIn(1, 5)
                width = answer.optInt("width", width).coerceIn(320, 960)
                quality = answer.optInt("quality", quality).coerceIn(30, 90)
                val every = 1000L / fps
                delay((every - (SystemClock.elapsedRealtime() - t0)).coerceAtLeast(50L))
            }
        } catch (err: CancellationException) {
            reason = if (reason == "running") "stopped" else reason
        } catch (err: Exception) {
            lastError = err.message ?: err.toString()
            reason = "failed: $lastError"
            Log.w(TAG, "PineStream stopped", err)
        } finally {
            release()
            synchronized(this) { if (job?.isActive != true) job = null }
        }
    }

    /** The mirror, built for the width asked for; null when it is up. */
    @Synchronized
    private fun ensureDisplay(): String? {
        if (display != null && builtWidth == width) return null
        release()
        return try {
            val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
            val real = android.graphics.Point()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealSize(real)
            val longSide = maxOf(real.x, 1)
            val w = (minOf(width, longSide) / 2) * 2
            val h = ((real.y.toLong() * w / longSide).toInt() / 2) * 2
            val t = HandlerThread("pine-stream").also { it.start() }
            val hd = Handler(t.looper)
            val r = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
            r.setOnImageAvailableListener({ onImage(it, w, h) }, hd)
            val dm = context.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
            /* the ScreenReplay flags, for the ScreenReplay reasons: AUTO_MIRROR
             * alone is the mirror, and SECURE or the picture is flat grey */
            display = dm.createVirtualDisplay("pine-stream", w, h, 1, r.surface,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR
                    or DisplayManager.VIRTUAL_DISPLAY_FLAG_SECURE)
            thread = t
            handler = hd
            reader = r
            builtWidth = width
            lastShotAt = 0L
            shape = "${w}x$h"
            null
        } catch (err: Exception) {
            release()
            err.message ?: err.toString()
        }
    }

    /** On the stream's own thread: every frame is closed; one is kept as a
     *  JPEG only when the rate says it is time. */
    private fun onImage(r: ImageReader, w: Int, h: Int) {
        val image = try { r.acquireLatestImage() } catch (err: Exception) { null } ?: return
        try {
            val now = SystemClock.elapsedRealtime()
            if (now - lastShotAt < 1000L / fps - 40L) return
            lastShotAt = now
            val plane = image.planes[0]
            val pixelStride = plane.pixelStride
            val rowPadding = plane.rowStride - pixelStride * w
            val padW = w + rowPadding / pixelStride
            var bmp = scratch
            if (bmp == null || bmp.width != padW || bmp.height != h) {
                bmp?.recycle()
                bmp = Bitmap.createBitmap(padW, h, Bitmap.Config.ARGB_8888)
                scratch = bmp
            }
            plane.buffer.rewind()
            bmp.copyPixelsFromBuffer(plane.buffer)
            val out = ByteArrayOutputStream(64 * 1024)
            if (padW == w) {
                bmp.compress(Bitmap.CompressFormat.JPEG, quality, out)
            } else {
                val crop = Bitmap.createBitmap(bmp, 0, 0, w, h)
                crop.compress(Bitmap.CompressFormat.JPEG, quality, out)
                crop.recycle()
            }
            latest.set(out.toByteArray())
        } catch (err: Exception) {
            lastError = err.message ?: err.toString()
        } finally {
            image.close()
        }
    }

    @Synchronized
    private fun release() {
        try { display?.release() } catch (_: Exception) { }
        display = null
        try { reader?.close() } catch (_: Exception) { }
        reader = null
        thread?.quitSafely()
        thread = null
        handler = null
        builtWidth = 0
        latest.set(null)
        /* not recycled: the reader's thread may still be finishing a frame -
         * the GC takes it */
        scratch = null
    }
}
