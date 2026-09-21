package com.pinebox.kiosk.bridge

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.util.Base64
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.core.content.FileProvider
import com.pinebox.kiosk.BuildConfig
import com.pinebox.kiosk.config.ConfigStore
import com.pinebox.kiosk.config.HotCorners
import com.pinebox.kiosk.net.StationClient
import com.pinebox.kiosk.net.StationException
import com.pinebox.kiosk.net.VideoEditorContract
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.coroutines.resume

/**
 * `window.__pineNative` - the Android half of the pineDesktop bridge.
 *
 * Read assets/pine-bridge.js first; it explains the split. In short: every
 * method the panel awaits arrives here through [invoke], which accepts the
 * call, returns an ack immediately, does the work on a coroutine, and
 * settles the JavaScript promise later by evaluating __pineBridgeSettle.
 *
 * The clipboard is the exception and is synchronous - app.py:170463 tests
 * `copyImage(...) === false`, which a Promise can never satisfy.
 *
 * THREADING. Every @JavascriptInterface method here is called on WebView's
 * private JavaBridge thread, NOT the UI thread and NOT a thread with a
 * Looper. Nothing in this class may touch the WebView directly; [settle]
 * posts to the WebView's own handler, and the clipboard work is posted to
 * the main thread because ClipboardManager wants a Looper.
 */
class PineDesktopBridge(
    private val context: Context,
    private val webView: WebView,
    private val configStore: ConfigStore,
    private val client: StationClient,
    private val scope: CoroutineScope,
    /** Opens a URL outside the kiosk. Injected so the activity can refuse
     *  when lock task mode is on - see MainActivity. */
    private val openExternal: (Uri) -> Boolean,
) {

    companion object {
        const val NAME = "__pineNative"
        private const val TAG = "PineBridge"

        /* Why the LCD and the provisioner are refused here rather than
         * forwarded. Both drive hardware attached to the BOX: the LCD is a
         * serial panel on the box's USB, and the terminal provisioner
         * shells out to adb at a tablet. This IS the tablet. */
        private const val WHY_LCD =
            "the LCD is wired to the box, not to this terminal"
        private const val WHY_TERMINAL =
            "this device is the terminal; it cannot provision itself"
        /* Not `const`: BuildConfig is generated Java, and Kotlin will not
         * fold a cross-language constant into one. */
        private val WHY_BACKEND =
            "the station runs on the box at " + BuildConfig.DEFAULT_BASE_URL +
                "; there is nothing to start here"

        private val LCD_METHODS = setOf(
            "lcdState", "lcdConfigure", "lcdDiscover", "lcdConnect", "lcdStart",
            "lcdStop", "lcdDisconnect", "lcdFrame", "lcdEvents", "lcdControl",
            "lcdDisplayMode", "lcdPaperImage", "lcdFirmware", "lcdSampleDirectory",
            "lcdDownload",
        )

        private val TERMINAL_METHODS = setOf(
            "terminalTools", "terminalSurvey", "terminalSnapshot", "terminalBootloader",
            "terminalReboot", "terminalVerifyFirmware", "terminalVerifyGsi",
            "terminalUnlock", "terminalDiscover", "terminalWirelessEnable",
            "terminalWirelessConnect", "terminalWirelessDisconnect",
        )

        private val BACKEND_METHODS = setOf(
            "startBackend", "stopBackend", "setupBackend", "reconstituteDesktop",
        )

        private val ASYNC_METHODS = setOf(
            "readConfig", "writeConfig", "discoverKey", "get", "post", "put", "del",
            "openExternal", "buildInfo", "backendLog",
            /* The ear. micLevel is deliberately NOT here - it is read
             * every animation frame and must not cost a promise. */
            "micStart", "micStop", "micCancel", "micState",
            /* The take itself, for the desktop's screen recordings. */
            "micTake", "micChunk",
            /* The rolling record of the screen - see replay/ScreenReplay. */
            "replayState", "replaySave", "replayChunk",
            /* #1427: the rolling recorder's own switch. */
            "replayRun",
            /* THE HOT CORNERS - the shot for the red ink, the screen video
             * to the operator's folder, and the four corners' preferences.
             * See config/HotCorners.kt and pine-views/hot-corners.js. */
            "screenShot", "replayExport", "replayEdit", "replayKeepEdited", "hotCorners", "hotCornersSet",
            /* #1426: the native endless-video surface. */
            "videoWall",
            /* #1148: "Whenever I access the screen capture to follow
             * report, I also want to be able to scrub between the last
             * five seconds of the broadcast to find the right frame." */
            "replayFrames",
            /* What the terminal confirmed on its way up - see net/Readiness. */
            "readyReport",
            /* The mix, captured natively - see audio/AirTap.kt. */
            "airStart", "airStop", "airState", "airSlice",
            /* Looking through the tablet's own camera - see camera/. */
            "cameraShow", "cameraHide",
            /* ...and without taking the screen, which is the one that
             * matters: cameraOpen streams frames to the desktop while
             * the terminal stays on the air. */
            "cameraOpen", "cameraClose", "cameraTune", "cameraRange",
            /* Keeping a line: to the tablet, or to the working folder. */
            "keepClip", "jack", "wallpaper", "saveText", "saveBytes",
            /* #1317: the terminal bringing itself round when the
             * WebView's own network has died under it. */
            "revive",
            "usbState", "usbPick", "usbSend", "usbList", "usbRead",
        ) + LCD_METHODS + TERMINAL_METHODS + BACKEND_METHODS

        /* Below this, a take is a silent room. Measured as RMS over the
         * whole clip: sending silence to whisper wastes a second and a
         * half and comes back empty, which reads to the operator as "it
         * did not hear me" when the truth is "there was nothing to hear". */
        private const val QUIET = 0.0025f

        /* A MULTIPLE OF THREE, and that is the whole point of the odd number.
         *
         * Base64 encodes three source bytes into four characters. A chunk
         * whose length is NOT divisible by three is padded with '=', and a
         * caller that concatenates the chunks and decodes once gets only the
         * first one: every decoder stops at the padding.
         *
         * 1024 * 1024 is not divisible by three, and this shipped that way.
         * Measured: a 1,460,336-byte replay came back as exactly 1,048,576 -
         * one chunk - and produced an mp4 that ffprobe could still read the
         * header of while Chromium reported duration NaN and 0x0. A
         * truncation that looks like a decode bug.
         *
         * 1048575 = 3 x 349525: the same size to within a byte, and every
         * chunk but the last now encodes with no padding at all. */
        private const val TAKE_CHUNK = 1048575

        /* #1148, THE SCRUB STRIP: the long edge a strip thumbnail is
         * scaled to before it is compressed.
         *
         * "Whenever I access the screen capture to follow report, I also
         *  want to be able to scrub between the last five seconds of the
         *  broadcast to find the right frame."
         *
         * 640 is picked so that ten frames off this terminal's 1340x800
         * screen fit comfortably inside ONE evaluateJavascript settlement:
         * the screenshot road already carries a single ~117 kB picture
         * that way. The measured total is handed back as `bytes` so nobody
         * has to guess. If the answer ever grows past a couple of
         * megabytes the cure is a SMALLER EDGE, not fewer frames - the
         * operator asked to scrub, and a strip of four is not a scrub. */
        private const val SCRUB_EDGE = 640
    }

    /* The last take, parked between micTake and the micChunk calls that read
     * it out. Cleared by micCancel and overwritten by the next micTake, so a
     * take cannot be read twice by accident or outlive the one after it. */
    @Volatile private var heldTake: ByteArray? = null

    /** The last replay written, parked between replaySave and replayChunk. */
    @Volatile private var heldReplay: ByteArray? = null

    /** Muxing and file reads must never occupy the activity's UI thread.
     * Reuse save's monitor so metadata belongs to this exact capture even
     * when a remote replay pull overlaps an editor capture. */
    private suspend fun captureReplay(
        replay: com.pinebox.kiosk.replay.ScreenReplay,
        want: Double,
        videoOnly: Boolean,
        /** #1155: seconds before now where the written clip ends. 0 is the
         *  tail - what replaySave, replayExport and replayEdit all want. */
        back: Double = 0.0,
    ): Triple<File, Double, JSONObject> = withContext(Dispatchers.IO) {
        synchronized(replay) {
            val (file, seconds) = replay.save(want, videoOnly, back)
            Triple(file, seconds, JSONObject(replay.lastSavedAudio.toString()))
        }
    }

    /**
     * #1148 - THE PICTURES BEHIND THE SCREENSHOT.
     *
     * "Whenever I access the screen capture to follow report, I also want
     *  to be able to scrub between the last five seconds of the broadcast
     *  to find the right frame."
     *
     * [clip] is the temporary mp4 captureReplay has just written, [held]
     * what it actually holds in seconds. Pulls [count] frames EVENLY
     * SPACED across it, oldest first, each scaled so its long edge is
     * about [edge] px and compressed as JPEG at 70 - the same quality the
     * screen shot already uses.
     *
     * `at` is what the page labels a thumbnail with: SECONDS BEFORE THE
     * END OF THE CLIP, which is as near "before now" as this can honestly
     * be - the clip was written a moment ago. The last frame is 0.0 and
     * the page calls that one "now".
     *
     * A frame that comes back null is SKIPPED, not fatal. The tail of the
     * ring can end mid-GOP and some retrievers refuse the very last
     * microsecond; a strip of nine is still a scrub, and throwing here
     * would take the whole strip away for nothing.
     *
     * IO thread only - MediaMetadataRetriever decodes, and that must never
     * happen on the thread the WebView paints from.
     */
    private fun frameStrip(
        clip: File,
        held: Double,
        count: Int,
        edge: Int,
        /** #1155: how far behind NOW the clip's own END sits, as the ring
         *  reported after writing it. 0 is the tail. Every `at` is measured
         *  from now, so this is simply added to each frame's distance from
         *  the end of the clip. */
        endBack: Double,
        /** #1155: what the RING holds, in seconds - the whole range the
         *  strip may travel over. Not the clip's length, which is only the
         *  window: reporting the clip here told the page the ring was six
         *  seconds long and pinned the coarse slider to nothing. */
        ringHeld: Double,
    ): JSONObject {
        val mmr = MediaMetadataRetriever()
        var frames = 0
        var bytes = 0L
        val list = JSONArray()
        /* Hoisted out of the try because the answer below reports where the
         * window actually landed, and that is read after the finally. */
        var lastUs = 0L
        var spanFrom = 0L
        var spanTo = 0L
        try {
            mmr.setDataSource(clip.absolutePath)
            /* The container's own duration is the truth about what can be
             * seeked to; [held] is what the ring believed it wrote. Take
             * the smaller of the two so a seek never runs off the end. */
            val durMs = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L
            val heldMs = Math.round(held * 1000.0)
            val spanMs = when {
                durMs > 0L && heldMs > 0L -> Math.min(durMs, heldMs)
                durMs > 0L -> durMs
                else -> heldMs
            }
            require(spanMs > 0L) { "the ring wrote nothing to read frames from" }

            val srcW = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
                ?.toIntOrNull() ?: 0
            val srcH = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
                ?.toIntOrNull() ?: 0
            /* Scaled by the LONG edge, so a portrait terminal is not blown
             * up to 640 tall by 1070 wide and back out through base64. */
            val longest = Math.max(srcW, srcH)
            val wantW: Int
            val wantH: Int
            if (longest > edge && srcW > 0 && srcH > 0) {
                val k = edge.toDouble() / longest.toDouble()
                wantW = Math.max(2, Math.round(srcW * k).toInt())
                wantH = Math.max(2, Math.round(srcH * k).toInt())
            } else {
                wantW = srcW
                wantH = srcH
            }

            /* The newest frame sits a hair inside the end: asking for the
             * exact duration is the one seek that reliably answers null. */
            lastUs = Math.max(0L, (spanMs * 1000L) - 40000L)

            /* #1155 - THE CLIP IS THE WINDOW.
             *
             * "Okay, that is actually much smoother. That is better. Also,
             *  I would like to go back the whole recording range."
             *
             * The first cut of this asked the ring for everything from now
             * back to the far edge and sliced the wanted part out of it.
             * That is correct and it does not scale: measured on the
             * tablet, 200 seconds back took 11.1 s and the whole 1200-second
             * ring extrapolated to about 50 s - one mux of everything in
             * between, for ten thumbnails. ReplayRing.save now cuts the
             * window itself, so the clip handed here IS the window and its
             * cost is its own length whatever its distance.
             *
             * Frames are spread across the whole of it, and `at` stays what
             * it always was - seconds before NOW - by adding where the clip
             * ends. */
            spanFrom = 0L
            spanTo = lastUs
            for (i in 0 until count) {
                val us = if (count <= 1) spanTo
                    else spanFrom + Math.round((spanTo - spanFrom) * (i.toDouble() / (count - 1).toDouble()))
                val bmp: android.graphics.Bitmap? = try {
                    if (Build.VERSION.SDK_INT >= 28 && wantW > 0 && wantH > 0) {
                        mmr.getScaledFrameAtTime(
                            us, MediaMetadataRetriever.OPTION_CLOSEST, wantW, wantH)
                    } else {
                        mmr.getFrameAtTime(us, MediaMetadataRetriever.OPTION_CLOSEST)
                    }
                } catch (err: Exception) {
                    Log.w(TAG, "replayFrames: no frame at " + us + "us", err)
                    null
                }
                if (bmp == null) continue
                val out = java.io.ByteArrayOutputStream()
                bmp.compress(android.graphics.Bitmap.CompressFormat.JPEG, 70, out)
                bmp.recycle()
                val b64 = Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
                bytes += b64.length.toLong()
                frames += 1
                /* Seconds BEFORE NOW, one decimal - the page turns this
                 * into "-1.2s" or "-4m 12s", and into the line the report
                 * pad is opened with. The clip's own end may sit well
                 * behind now (#1155), so that distance is added here and
                 * the page never has to know a window from a tail. */
                val before = Math.round((endBack + (lastUs - us) / 1000000.0) * 10.0) / 10.0
                list.put(JSONObject()
                    .put("at", before)
                    .put("image", "data:image/jpeg;base64," + b64))
            }
        } finally {
            try {
                if (Build.VERSION.SDK_INT >= 29) mmr.close() else mmr.release()
            } catch (gone: Exception) { /* fine */ }
        }
        /* #1155: where the window ACTUALLY landed, in the same units the
         * frames use - seconds before now. `from` is the oldest edge and
         * `to` the newest, so a page that asked to start further back than
         * the ring reaches can see that it did not get what it asked for
         * and tell the operator, rather than silently showing him the
         * wrong minute. The caller decides `clamped`: only it knows what
         * was originally asked for before the clamp to what is held. */
        val gotFrom = Math.round((endBack + (lastUs - spanFrom) / 1000000.0) * 10.0) / 10.0
        val gotTo = Math.round((endBack + (lastUs - spanTo) / 1000000.0) * 10.0) / 10.0
        return if (frames == 0) {
            JSONObject().put("ok", false)
                .put("held", ringHeld)
                .put("detail", "nothing readable that far back; the ring holds "
                    + (Math.round(ringHeld * 10.0) / 10.0) + "s")
        } else {
            JSONObject()
                .put("ok", true)
                /* The CLIP's length - the window - kept for the callers
                 * that have always read it. */
                .put("seconds", held)
                /* What the RING holds right now, which is the whole range
                 * the strip may travel over. */
                .put("held", ringHeld)
                .put("from", gotFrom)
                .put("to", gotTo)
                .put("frames", list)
                /* MEASURED, not estimated: the base64 this settlement is
                 * about to carry through evaluateJavascript. */
                .put("bytes", bytes)
                .put("edge", edge)
                .put("detail", frames.toString() + " frames across the last "
                    + (Math.round(held * 10.0) / 10.0) + "s, "
                    + (bytes / 1024L) + " kB of base64")
        }
    }

    /* ----------------------------------------------------------------- */
    /* The asynchronous road                                              */
    /* ----------------------------------------------------------------- */

    /**
     * @param id the shim's request id; it is handed straight back in the
     *   settlement so the shim can find the right promise.
     * @param argsJson the call's arguments as a JSON array, exactly as the
     *   Electron call site passed them.
     * @return an ack envelope. `accepted:false` means no settlement is
     *   coming and the shim must reject now.
     */
    @JavascriptInterface
    fun invoke(id: String, method: String, argsJson: String): String {
        if (method !in ASYNC_METHODS) {
            return BridgeEnvelope.refused("no such bridge method: $method")
        }
        val args: JSONArray = try {
            if (argsJson.isBlank()) JSONArray() else JSONArray(argsJson)
        } catch (err: Exception) {
            return BridgeEnvelope.refused("arguments for $method were not a JSON array")
        }

        scope.launch {
            val envelope = try {
                dispatch(id, method, args)
            } catch (err: Exception) {
                Log.w(TAG, "$method failed", err)
                BridgeEnvelope.error(id, err.message ?: err.javaClass.simpleName)
            }
            settle(id, envelope)
        }
        return BridgeEnvelope.accepted(id)
    }

    private suspend fun dispatch(id: String, method: String, args: JSONArray): String = when (method) {
        "readConfig" -> BridgeEnvelope.ok(id, configStore.read().toJson().toString())

        "writeConfig" -> {
            val patch = args.optJSONObject(0)
            BridgeEnvelope.ok(id, configStore.write(patch).toJson().toString())
        }

        "discoverKey" -> BridgeEnvelope.ok(id, client.discoverKey().toString())

        "get" -> BridgeEnvelope.ok(id, client.get(route(args)))
        "post" -> BridgeEnvelope.ok(id, client.post(route(args), body(args)))
        "put" -> BridgeEnvelope.ok(id, client.put(route(args), body(args)))
        "del" -> BridgeEnvelope.ok(id, client.delete(route(args), body(args)))

        "openExternal" -> {
            val raw = args.optString(0)
            val opened = if (raw.isBlank()) false else openExternal(Uri.parse(raw))
            BridgeEnvelope.okBoolean(id, opened)
        }

        "buildInfo" -> BridgeEnvelope.ok(id, buildInfo().toString())

        /* ---- the microphone ---------------------------------------- */

        "micStart" -> {
            /* The probe may name a source and turn the effects off, to
             * tell "this microphone is silent" from "this SOURCE is
             * silent". Ordinary callers pass nothing and get the tuned
             * defaults. */
            val opts = args.optJSONObject(0)
            if (opts != null) {
                val named = opts.optString("source", "")
                if (named.isNotBlank()) {
                    mic.source = com.pinebox.kiosk.audio.MicCapture.sourceByName(named)
                }
                if (opts.has("effects")) mic.withEffects = opts.optBoolean("effects", true)
                if (opts.has("fullEffects")) mic.fullEffects = opts.optBoolean("fullEffects", false)
                if (opts.has("stereo")) mic.stereo = opts.optBoolean("stereo", false)
                if (opts.has("backMic")) mic.preferBackMic = opts.optBoolean("backMic", true)
            }
            val why = mic.start()
            BridgeEnvelope.ok(id, JSONObject()
                .put("ok", why == null)
                .put("rate", com.pinebox.kiosk.audio.MicCapture.RATE)
                .put("source", mic.sourceName())
                .put("stereo", mic.stereo)
                .put("mic", mic.micChosen)
                .put("routed", mic.micRouted)
                .put("effects", mic.effects())
                /* An orphan take was found open and discarded. Not an
                 * error - the new take is clean, which is the point - but
                 * it means something upstream leaked a capture, and a leak
                 * that is never reported is a leak nobody fixes. */
                .put("replacedStaleTake", mic.replacedStaleTake)
                .put("detail", why ?: JSONObject.NULL).toString())
        }

        /* Stop, send, answer with the words. The whole round trip lives
         * here rather than in JavaScript because the clip never needs to
         * enter the page at all - moving a ten-second WAV through the
         * bridge as base64 would cost a third more bytes and buy nothing. */
        "micStop" -> BridgeEnvelope.ok(id, transcribe().toString())

        /* KEEP A LINE.
         *
         * `{route, said, id, where}` - the clip route to fetch, the words
         * (so the file is named after what it SAYS rather than after a
         * hex id nobody can search for), and which folder.
         *
         * The bytes never enter the page: it is audio, the page does not
         * want it, and base64 through the bridge would cost a third more
         * for nothing. */
        "keepClip" -> {
            val opts = args.optJSONObject(0) ?: JSONObject()
            val route = opts.optString("route", "")
            if (route.isBlank()) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("detail", "no clip was named").toString())
            } else {
                val cfg = configStore.read()
                val where = opts.optString("where", "downloads")
                /* The operator's own working folder, from the config,
                 * because where he extracts things is his business and not
                 * a constant in this file. */
                val folder = if (where == "recordings") cfg.recordingFolder
                else "Pine Box"

                val kept = try {
                    val (bytes, kind) = client.getBytes(route)
                    val ext = when {
                        kind.contains("mpeg") || kind.contains("mp3") -> "mp3"
                        kind.contains("wav") -> "wav"
                        kind.contains("ogg") -> "ogg"
                        else -> "audio"
                    }
                    val name = com.pinebox.kiosk.audio.ClipSaver.nameFor(
                        opts.optString("said", ""), opts.optString("id", ""), ext)
                    com.pinebox.kiosk.audio.ClipSaver.keep(
                        context, bytes, name, folder, kind.substringBefore(';'))
                } catch (err: Exception) {
                    com.pinebox.kiosk.audio.ClipSaver.Kept(
                        false, "", 0, err.message ?: err.javaClass.simpleName)
                }
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", kept.ok)
                    .put("where", kept.where)
                    .put("bytes", kept.bytes)
                    .put("detail", kept.detail).toString())
            }
        }

        /* #1317: THE TERMINAL, BROUGHT ROUND.
         *
         * Chromium's network stack inside this WebView can die while
         * everything else stays up - the bridge still answers, the feed
         * still updates, the views still paint, and not one `fetch`,
         * `<audio>` or `<video>` works. See net/Revive.kt for what was
         * measured and what was ruled out.
         *
         * With no argument this REPORTS - whether a revival is allowed
         * and how long since the last - so the page can decide without
         * causing one. `{now:true}` actually does it, and the answer
         * never arrives, because the process is gone. */
        "revive" -> {
            val opts = args.optJSONObject(0)
            val why = opts?.optString("why", "") ?: ""
            if (opts != null && opts.optBoolean("now", false)) {
                val went = com.pinebox.kiosk.net.Revive.now(context, why)
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", went)
                    .put("say", if (went) "reviving" else
                        "too soon since the last one").toString())
            } else {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", true)
                    .put("rested", com.pinebox.kiosk.net.Revive.rested(context))
                    .put("sinceMs", com.pinebox.kiosk.net.Revive.sinceMs(context))
                    .put("inARow", com.pinebox.kiosk.net.Revive.inARow(context))
                    .toString())
            }
        }

        /* THE HEADPHONE JACK. `{on}` hands the audio over or takes it
         * back; with no argument it reports where things stand. */
        "jack" -> {
            val opts = args.optJSONObject(0)
            val watch = jackWatch
            if (watch == null) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false)
                    .put("detail", "the jack watch is not running").toString())
            } else {
                val said = if (opts != null && opts.has("on")) {
                    watch.force(opts.optBoolean("on", true))
                } else watch.lastSaid
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", true)
                    .put("on", watch.handedOver())
                    .put("canDetect", watch.canDetect())
                    .put("say", said).toString())
            }
        }

        /* THE WALLPAPER. With no argument it reports what is hanging; with
         * `{now:true}` it goes and looks again rather than waiting out the
         * five minutes - which is what the operator wants after changing
         * what the station is selling. */
        "wallpaper" -> {
            val opts = args.optJSONObject(0)
            val watch = com.pinebox.kiosk.PineApp.of(context).wallpaper
            val said = if (opts != null && opts.optBoolean("now", false)) {
                watch.now()
            } else watch.lastSaid
            BridgeEnvelope.ok(id, watch.state().put("ok", true).put("say", said).toString())
        }

        /* A KIT FILE, WRITTEN WHERE THE OPERATOR CAN FIND IT.
         *
         * A sampler preset carries the AUDIO, not references - a line id
         * resolves for only 48 hours and the media is then swept, so a kit of
         * references would rot into a grid of dead pads. That makes a kit
         * large, and an <a download> is inert inside this WebView, so the
         * bytes are written natively through the same MediaStore road clips
         * take. No storage permission is involved.
         */
        "saveText" -> {
            val opts = args.optJSONObject(0) ?: JSONObject()
            val text = opts.optString("text", "")
            val name = opts.optString("name", "pine-box-kit.json")
            if (text.isBlank()) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("detail", "there was nothing to write").toString())
            } else {
                val cfg = configStore.read()
                val where = opts.optString("where", "downloads")
                val folder = if (where == "recordings") cfg.recordingFolder else "Pine Box"
                val kept = try {
                    com.pinebox.kiosk.audio.ClipSaver.keep(
                        context, text.toByteArray(Charsets.UTF_8), name, folder,
                        "application/json")
                } catch (err: Exception) {
                    com.pinebox.kiosk.audio.ClipSaver.Kept(
                        false, "", 0, err.message ?: err.javaClass.simpleName)
                }
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", kept.ok)
                    .put("where", kept.where)
                    .put("bytes", kept.bytes)
                    .put("detail", kept.detail).toString())
            }
        }

        /* ONE BINARY FILE, for the MPC kit export.
         *
         * saveText above covers a preset, which is JSON. An MPC kit is a
         * FOLDER of WAVs beside an .xpm program, so the bytes are real audio
         * and have to arrive as base64 rather than as a string - a WAV put
         * through a JSON string comes out corrupted, silently, and the MPC
         * would simply refuse the kit with no clue why.
         */
        "saveBytes" -> {
            val opts = args.optJSONObject(0) ?: JSONObject()
            val b64 = opts.optString("base64", "")
            val name = opts.optString("name", "pine-box.bin")
            val folder = opts.optString("folder", "Pine Box")
            val mime = opts.optString("mime", "application/octet-stream")
            if (b64.isBlank()) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("detail", "there was nothing to write").toString())
            } else {
                val kept = try {
                    val raw = Base64.decode(b64, Base64.DEFAULT)
                    com.pinebox.kiosk.audio.ClipSaver.keep(context, raw, name, folder, mime)
                } catch (err: Exception) {
                    com.pinebox.kiosk.audio.ClipSaver.Kept(
                        false, "", 0, err.message ?: err.javaClass.simpleName)
                }
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", kept.ok)
                    .put("where", kept.where)
                    .put("bytes", kept.bytes)
                    .put("detail", kept.detail).toString())
            }
        }

        /* ---- the MPC over USB ------------------------------------------
         *
         * Three calls, because the operator does three different things:
         * ask what is plugged in, point at it once, and send. See UsbTarget
         * for why this goes through the Storage Access Framework and not
         * through a path. */
        "usbState" -> {
            val where = com.pinebox.kiosk.gallery.UsbTarget.target(context)
            /* SAY WHETHER THE TABLET CAN BE A HOST AT ALL.
             *
             * "Nothing happens when I plug it in" has three different causes
             * and they need three different answers: the tablet cannot host
             * (wrong hardware or a GSI without the feature), the tablet can
             * host but nothing is mounted (no OTG power, wrong cable, or the
             * MPC is not in USB mode), or it is mounted but has not been
             * pointed at yet. Guessing between them is what makes a USB
             * feature feel broken, so all three are reported. */
            val canHost = context.packageManager
                .hasSystemFeature(android.content.pm.PackageManager.FEATURE_USB_HOST)
            BridgeEnvelope.ok(id, JSONObject()
                .put("ok", true)
                .put("chosen", where != null)
                .put("name", com.pinebox.kiosk.gallery.UsbTarget.targetName(context))
                .put("canHost", canHost)
                .put("anyRemovable", com.pinebox.kiosk.gallery.UsbTarget.anyRemovable(context))
                .put("volumes", com.pinebox.kiosk.gallery.UsbTarget.volumes(context))
                .toString())
        }

        "usbPick" -> {
            val activity = liveActivity
            if (activity == null) {
                BridgeEnvelope.ok(id, JSONObject().put("ok", false)
                    .put("detail", "the picker needs the app in the foreground").toString())
            } else {
                val picked = kotlinx.coroutines.suspendCancellableCoroutine<String> { cont ->
                    activity.runOnUiThread {
                        activity.askForUsbDisk { answer ->
                            if (cont.isActive) cont.resumeWith(Result.success(answer))
                        }
                    }
                }
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", picked.isNotBlank())
                    .put("name", com.pinebox.kiosk.gallery.UsbTarget.targetName(context))
                    .put("detail", if (picked.isBlank()) "nothing was chosen" else "")
                    .toString())
            }
        }

        "usbSend" -> {
            val opts = args.optJSONObject(0) ?: JSONObject()
            /* The kit is already on local storage - the exporter wrote and
             * verified it there - so this copies rather than rebuilding. */
            val folder = opts.optString("folder", "")
            val into = opts.optString("into", folder.substringAfterLast('/'))
            val from = java.io.File(
                android.os.Environment.getExternalStoragePublicDirectory(
                    android.os.Environment.DIRECTORY_DOWNLOADS), folder)
            val sent = com.pinebox.kiosk.gallery.UsbTarget.sendFolder(context, from, into)
            BridgeEnvelope.ok(id, JSONObject()
                .put("ok", sent.ok)
                .put("files", sent.files)
                .put("bytes", sent.bytes)
                .put("where", sent.where)
                .put("detail", sent.detail).toString())
        }

        /* READING THE MPC'S DISK - see UsbBrowse for why this is SAF and not
         * a path, and why that covers mass storage AND MTP. */
        "usbList" -> BridgeEnvelope.ok(id,
            com.pinebox.kiosk.gallery.UsbBrowse.list(
                context, (args.optJSONObject(0) ?: JSONObject()).optString("path", "")
            ).toString())

        "usbRead" -> {
            val opts = args.optJSONObject(0) ?: JSONObject()
            BridgeEnvelope.ok(id,
                com.pinebox.kiosk.gallery.UsbBrowse.read(
                    context,
                    opts.optString("path", ""),
                    opts.optLong("offset", 0L),
                    opts.optInt("length", com.pinebox.kiosk.gallery.UsbBrowse.CHUNK)
                ).toString())
        }

        "micCancel" -> {
            mic.cancel()
            heldTake = null
            BridgeEnvelope.ok(id, JSONObject().put("ok", true).toString())
        }

        /* STOP AND KEEP THE SOUND, rather than stop and send it to whisper.
         *
         * The desktop's screen recorder needs the tablet's ear as AUDIO, to
         * lay under a video - see terminal-glass.cjs. Nothing is transcribed
         * and nothing leaves the tablet here; the take is parked and read
         * out by micChunk. */
        /* THE MIX, CAPTURED OFF THE PAGE.
         *
         * The page's own ring loses a fifth of the audio on a busy main
         * thread; this one runs on a thread of its own and cannot be
         * starved. It is started on request rather than at boot because
         * REMOTE_SUBMIX can reroute output on some builds, and a radio
         * station is the worst possible place to find that out. */
        "airStart" -> {
            val tap = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.airTap
            val why = tap?.start()
            BridgeEnvelope.ok(id, JSONObject()
                .put("ok", tap != null && why == null)
                .put("detail", why ?: JSONObject.NULL)
                .put("seconds", tap?.seconds() ?: 0.0).toString())
        }

        "airStop" -> {
            (context.applicationContext as? com.pinebox.kiosk.PineApp)?.airTap?.stop()
            BridgeEnvelope.ok(id, JSONObject().put("ok", true).toString())
        }

        "airState" -> {
            val tap = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.airTap
            BridgeEnvelope.ok(id, JSONObject()
                .put("ok", tap != null)
                .put("running", tap?.running ?: false)
                .put("seconds", tap?.seconds() ?: 0.0)
                .put("rate", tap?.rate ?: 0)
                .put("holds", com.pinebox.kiosk.audio.AirTap.HOLD_SECONDS)
                .put("detail", tap?.lastError ?: JSONObject.NULL).toString())
        }

        /* One window of it, base64, the same shape the page's sliceWav
         * answers with so the desktop does not care which road it came by. */
        "airSlice" -> {
            val tap = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.airTap
            if (tap == null || !tap.running) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false)
                    .put("detail", "the native tap is not running").toString())
            } else {
                val opts = args.optJSONObject(0) ?: JSONObject()
                val from = opts.optDouble("fromAgo", 30.0)
                val to = opts.optDouble("toAgo", 0.0)
                val wav = tap.sliceWav(from, to)
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", true)
                    .put("bytes", wav.size)
                    .put("rate", tap.rate)
                    .put("b64", android.util.Base64.encodeToString(
                        wav, android.util.Base64.NO_WRAP)).toString())
            }
        }

        /* THE CAMERA AS A STREAM, WITH THE SCREEN LEFT ALONE.
         *
         * This is the road that matters: no preview, no activity, the
         * terminal keeps drawing the station, and the frames go to the
         * desktop over a local socket. See camera/PineCameraService.kt.
         * `facing` switches the lens without stopping the service. */
        "cameraOpen" -> {
            val want = args.optJSONObject(0)?.optString("facing") ?: "rear"
            try {
                com.pinebox.kiosk.camera.PineCameraService.begin(context, want)
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", true).put("facing", want)
                    .put("socket", com.pinebox.kiosk.camera.PineCameraService.SOCKET)
                    .toString())
            } catch (err: Exception) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false)
                    .put("detail", err.message ?: "the camera would not open").toString())
            }
        }

        /* THE SENSOR'S DIALS. Gamma and the look transforms are
         * deliberately not here - see PineCameraService.dial. */
        "cameraTune" -> {
            val svc = com.pinebox.kiosk.camera.PineCameraService.live
            if (svc == null) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("detail", "the camera is not open").toString())
            } else {
                svc.tune(args.optJSONObject(0) ?: JSONObject())
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", true).put("range", svc.range()).toString())
            }
        }

        "cameraRange" -> {
            val svc = com.pinebox.kiosk.camera.PineCameraService.live
            BridgeEnvelope.ok(id, JSONObject()
                .put("ok", svc != null)
                .put("range", svc?.range() ?: JSONObject()).toString())
        }

        "cameraClose" -> {
            try {
                com.pinebox.kiosk.camera.PineCameraService.end(context)
                BridgeEnvelope.ok(id, JSONObject().put("ok", true).toString())
            } catch (err: Exception) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("detail", err.message ?: "no").toString())
            }
        }

        /* LOOKING THROUGH THE TABLET'S CAMERA.
         *
         * The picture reaches the desktop through the screen mirror that
         * already exists - this only puts the camera ON the screen. See
         * camera/PineCameraActivity for why that beats a second video
         * pipeline. */
        "cameraShow" -> {
            val want = args.optJSONObject(0)?.optString("facing") ?: "rear"
            try {
                com.pinebox.kiosk.camera.PineCameraActivity.show(context, want)
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", true).put("facing", want).toString())
            } catch (err: Exception) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false)
                    .put("detail", err.message ?: "the camera would not open").toString())
            }
        }

        /* Back to the terminal. The camera activity closes itself; this is
         * the road for a desktop that wants to put the station back without
         * reaching through the mirror's touch. */
        "cameraHide" -> {
            try {
                val go = android.content.Intent(context, com.pinebox.kiosk.MainActivity::class.java)
                go.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                go.addFlags(android.content.Intent.FLAG_ACTIVITY_CLEAR_TOP)
                context.startActivity(go)
                BridgeEnvelope.ok(id, JSONObject().put("ok", true).toString())
            } catch (err: Exception) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("detail", err.message ?: "no").toString())
            }
        }

        /* WHAT THE TERMINAL CONFIRMED WHEN IT CAME UP.
         *
         * Written at startup by MainActivity and simply handed over here -
         * asking again would be a fresh probe pretending to be a record of
         * the old one. See net/Readiness.kt. */
        "readyReport" -> {
            BridgeEnvelope.ok(id, com.pinebox.kiosk.net.Readiness.report().toString())
        }

        /* WHAT THE ROLLING RECORD HOLDS RIGHT NOW.
         *
         * `seconds` is what is actually in the ring, which is less than the
         * ceiling for the first minute after a start and after the screen has
         * been dark. Offering "the last 30" when 11 are held would be a lie
         * the operator only finds out on playback. */
        /* #1427: START OR STOP THE ROLLING RECORDER.
         *
         * It mirrors the display into an encoder through a VirtualDisplay,
         * so the screen is composited twice every frame for as long as it
         * runs - a cost the whole panel pays, and the reason this needed
         * to be measurable rather than argued about. Answers the same
         * shape replayState does, so one road reads the result. */
        "replayRun" -> {
            val replay = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.replay
            if (replay == null) {
                BridgeEnvelope.ok(id, org.json.JSONObject()
                    .put("ok", false).put("detail", "no recorder on this build").toString())
            } else {
                val want = args.optString(0, "state")
                val why = when (want) {
                    "on" -> replay.start()
                    "off" -> { replay.stop(); null }
                    else -> null
                }
                BridgeEnvelope.ok(id, org.json.JSONObject()
                    .put("ok", why == null)
                    .put("running", replay.seconds() >= 0 && want != "off")
                    .put("seconds", replay.seconds())
                    .put("bytes", replay.bytes())
                    .put("detail", why).toString())
            }
        }

        "replayState" -> {
            val replay = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.replay
            BridgeEnvelope.ok(id, JSONObject()
                .put("ok", replay != null)
                .put("running", replay?.isRunning ?: false)
                .put("seconds", replay?.seconds() ?: 0.0)
                /* THE DESIGN FLOOR, not a cap - `seconds` above is the
                 * only honest figure for how much is actually there, and it
                 * is routinely several times this. See ScreenReplay. */
                .put("atLeast", com.pinebox.kiosk.replay.ScreenReplay.HOLD_SECONDS)
                .put("bytes", replay?.bytes() ?: 0)
                .put("audio", replay?.audioStatus() ?: JSONObject.NULL)
                .put("detail", replay?.lastError ?: JSONObject.NULL).toString())
        }

        /* Write the last N seconds and park the file for reading out. The
         * bytes do not cross the bridge here - a thirty-second clip is a few
         * megabytes and this answers with its size so the caller can decide
         * whether to pull it. */
        "replaySave" -> {
            val replay = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.replay
            if (replay == null) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("detail", "no recorder on this terminal").toString())
            } else {
                val opts = args.optJSONObject(0) ?: JSONObject()
                val want = opts.optDouble("seconds", 30.0)
                try {
                    val (file, got, audio) = captureReplay(replay, want, opts.optBoolean("video_only", false))
                    heldReplay = withContext(Dispatchers.IO) {
                        try { file.readBytes() } finally { file.delete() }
                    }
                    BridgeEnvelope.ok(id, JSONObject()
                        .put("ok", true)
                        .put("bytes", heldReplay?.size ?: 0)
                        .put("asked", want)
                        .put("audio", audio)
                        /* What was ACTUALLY written, which can be less. */
                        .put("seconds", got).toString())
                } catch (err: Exception) {
                    heldReplay = null
                    BridgeEnvelope.ok(id, JSONObject()
                        .put("ok", false)
                        .put("detail", err.message ?: "the replay could not be written").toString())
                }
            }
        }

        /* ---- the hot corners --------------------------------------- */

        /* THE PICTURE, FOR THE RED INK.
         *
         * "If I swipe into the tablet from the top left of the screen down
         *  to the center, I want to take a screenshot of the screen and I
         *  want to be able to draw on the screen and outline things with my
         *  finger in red and be able to submit that image along with the
         *  report into the Pine box inbox."
         *
         * The same PixelCopy the volume-up chord uses - MainActivity.
         * shootScreen is the one road - awaited here and settled as a data
         * URL the annotator can paint onto a canvas. It needs the
         * activity's WINDOW, which this class deliberately does not hold;
         * `liveActivity` is set while the activity is resumed, which is the
         * only time there is a window worth copying. */
        "screenShot" -> {
            val activity = liveActivity
            if (activity == null) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false)
                    .put("detail", "the terminal's window is not on screen").toString())
            } else {
                val shot = suspendCancellableCoroutine<com.pinebox.kiosk.MainActivity.Shot?> { cont ->
                    activity.runOnUiThread {
                        try {
                            activity.shootScreen { got -> if (cont.isActive) cont.resume(got) }
                        } catch (err: Exception) {
                            Log.w(TAG, "screenShot failed", err)
                            if (cont.isActive) cont.resume(null)
                        }
                    }
                }
                val answer = if (shot == null) {
                    JSONObject().put("ok", false)
                        .put("detail", "the window could not be copied; see PineKiosk in the log")
                } else {
                    JSONObject().put("ok", true)
                        .put("image", shot.dataUrl)
                        .put("w", shot.w)
                        .put("h", shot.h)
                }
                BridgeEnvelope.ok(id, answer.toString())
            }
        }

        /* THE SCREEN VIDEO, TO THE OPERATOR'S FOLDER - AND UP TO THE BOX.
         *
         * "If I swipe in from the right side, I want to save a recording and
         *  save it out to the Pine Box recordings folder that I have
         *  specified. And I want to save anywhere from the last five seconds
         *  to the last 20 minutes. So the tablet should always be
         *  recording."
         *
         * replaySave above parks the bytes for the DESKTOP to pull through
         * replayChunk. This is the other road: the same ReplayRing.save
         * writes the last `seconds` to a temp file, ClipSaver streams that
         * file into Download/<recordingFolder> under a dated name, and then
         * - when asked - the file goes to the station's export courier. The
         * bytes never cross the bridge; the page gets the path, the size
         * and what was actually written.
         *
         * THE UPLOAD CANNOT FAIL THE SAVE. The courier route may not exist
         * yet, the box may be off the LAN, the tailnet may be asleep: every
         * one of those settles as `uploaded: {ok:false, detail}` beside an
         * `ok:true` save, because the file on the tablet is the thing the
         * operator asked for and the upload is the convenience. */
        "replayExport" -> {
            val replay = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.replay
            val opts = args.optJSONObject(0) ?: JSONObject()
            if (replay == null) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("uploaded", JSONObject.NULL)
                    .put("detail", "no recorder on this terminal").toString())
            } else {
                val want = opts.optDouble("seconds", 30.0)
                    .coerceIn(1.0, com.pinebox.kiosk.replay.ScreenReplay.HOLD_SECONDS.toDouble())
                val upload = opts.optBoolean("upload", false)
                var temp: File? = null
                try {
                    val (file, got, audio) = captureReplay(replay, want, opts.optBoolean("video_only", false))
                    temp = file
                    val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
                    val asked = opts.optString("name", "").trim()
                    val name = when {
                        asked.isBlank() ->
                            "pinetab-screen-" + stamp + "-" + Math.round(got) + "s.mp4"
                        asked.lowercase(Locale.US).endsWith(".mp4") -> asked
                        else -> "$asked.mp4"
                    }
                    val cfg = configStore.read()
                    val kept = withContext(Dispatchers.IO) {
                        com.pinebox.kiosk.audio.ClipSaver.keepFile(context, file, name, cfg.recordingFolder, "video/mp4")
                    }
                    /* Uploaded from the temp file even when MediaStore
                     * refused the folder: a courier that carried it to the
                     * box is still a copy the operator can get at. */
                    val uploaded: JSONObject? =
                        if (upload) uploadExport(file, name, "screen", got) else null
                    BridgeEnvelope.ok(id, JSONObject()
                        .put("ok", kept.ok)
                        .put("where", kept.where)
                        .put("bytes", kept.bytes)
                        .put("asked", want)
                        /* What was ACTUALLY written, which can be less. */
                        .put("seconds", got)
                        .put("audio", audio)
                        .put("uploaded", uploaded ?: JSONObject.NULL)
                        .put("detail", kept.detail).toString())
                } catch (err: Exception) {
                    BridgeEnvelope.ok(id, JSONObject()
                        .put("ok", false)
                        .put("uploaded", JSONObject.NULL)
                        .put("detail", err.message ?: "the replay could not be written").toString())
                } finally {
                    try { temp?.delete() } catch (gone: Exception) { /* fine */ }
                }
            }
        }

        /* THE LAST FIVE SECONDS, AS PICTURES - THE SCRUB STRIP (#1148).
         *
         * "Whenever I access the screen capture to follow report, I also
         *  want to be able to scrub between the last five seconds of the
         *  broadcast to find the right frame."
         *
         * The annotator opens on a PixelCopy of the screen AS IT IS NOW,
         * which is a moment later than the thing the operator meant to
         * point at. This hands the page the seconds just behind that shot
         * so the strip under the ink toolbar can walk back through them and
         * swap the canvas background - see pine-views/hot-corners.js.
         *
         * THE SAME MACHINERY AS replayExport, AND NOT A SECOND COPY OF IT.
         * captureReplay -> ScreenReplay.save writes the tail of the ring to
         * a temp mp4 in the app's CACHE dir; the frames are pulled out of
         * that file with MediaMetadataRetriever and the file is deleted in
         * `finally`. It never goes near the operator's recordings folder:
         * this is a scrub strip, not an export.
         *
         * video_only is forced true. The strip wants pictures; an audio
         * track that has gone missing (the capture asleep, a permission
         * withdrawn) must not be able to fail the pull.
         *
         * SIZE. Each frame is scaled so the long edge is about SCRUB_EDGE
         * px and compressed as JPEG at 70 - the same quality the screen
         * shot uses. Ten of those off a 1340x800 terminal measure a few
         * hundred kB of base64 in one settlement, the same order as the
         * screenshot road's single picture; `bytes` in the answer is the
         * measured total so the page (and the next person to read this)
         * never has to guess.
         *
         * #1155 - AND IT REACHES THE WHOLE RING, NOT ONLY THE TAIL.
         *
         * "Okay, that is actually much smoother. That is better. Also, I
         *  would like to go back the whole recording range."
         *
         * `back` is seconds before NOW where the shown window ENDS, and it
         * defaults to 0, so every call written before this one asks for and
         * gets exactly what it always did. The ring can only ever write a
         * clip ending NOW, so a window further back is cut out of a LONGER
         * write: back + seconds is muxed and frameStrip slices the part
         * that was asked for. That costs a longer mux the further back the
         * ask goes - the whole ring at the far end - which is precisely why
         * the page caches the windows it has already been given rather than
         * asking twice.
         *
         * Clamped to what the ring HOLDS, not to HOLD_SECONDS, which is a
         * design floor and not a promise: `held` in the answer is the only
         * honest figure and the page draws its range from it. */
        "replayFrames" -> {
            val replay = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.replay
            val opts = args.optJSONObject(0) ?: JSONObject()
            if (replay == null) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false)
                    .put("held", 0.0)
                    .put("detail", "no recorder on this terminal").toString())
            } else {
                val held = replay.seconds()
                val want = opts.optDouble("seconds", 5.0).coerceIn(1.0, 30.0)
                val count = opts.optInt("count", 10).coerceIn(2, 24)
                val edge = opts.optInt("edge", SCRUB_EDGE).coerceIn(160, 1280)
                /* Never past the oldest frame there is; never negative. The
                 * UNCLAMPED ask is kept so the answer can say honestly that
                 * it could not go as far back as it was asked to. */
                val askedBack = opts.optDouble("back", 0.0)
                val back = askedBack.coerceIn(0.0, Math.max(0.0, held - want))
                var temp: File? = null
                try {
                    /* The ring cuts the window itself, so this writes the
                     * window and nothing else - see ReplayRing.save(back). */
                    val written = captureReplay(replay, want, true, back)
                    temp = written.first
                    val endBack = replay.lastSavedEndBack()
                    val answer = withContext(Dispatchers.IO) {
                        frameStrip(written.first, written.second, count, edge, endBack, held)
                    }
                    answer.put("asked_back", askedBack)
                    /* True when the ask ran past the oldest thing there is. */
                    answer.put("clamped", askedBack - back > 0.6)
                    BridgeEnvelope.ok(id, answer.toString())
                } catch (err: Exception) {
                    Log.w(TAG, "replayFrames failed", err)
                    BridgeEnvelope.ok(id, JSONObject()
                        .put("ok", false)
                        .put("detail", err.message ?: "the last seconds could not be read").toString())
                } finally {
                    try { temp?.delete() } catch (gone: Exception) { /* fine */ }
                }
            }
        }

        /* Capture an immutable source for editing. No final export is saved
         * until the editor has rendered the user's chosen result. */
        "replayEdit" -> {
            val replay = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.replay
            val opts = args.optJSONObject(0) ?: JSONObject()
            if (replay == null) {
                BridgeEnvelope.ok(id, JSONObject().put("ok", false).put("detail", "no recorder on this terminal").toString())
            } else {
                var temp: File? = null
                try {
                    val want = opts.optDouble("seconds", 60.0)
                        .coerceIn(1.0, com.pinebox.kiosk.replay.ScreenReplay.HOLD_SECONDS.toDouble())
                    val (file, got, audio) = captureReplay(replay, want, opts.optBoolean("video_only", false))
                    temp = file
                    val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
                    val name = "pinetab-screen-$stamp-${Math.round(got)}s.mp4"
                    val result = JSONObject(client.postVideoEditorSource(file, audio, name))
                    val source = VideoEditorContract.identity(result.optString("source_id", result.optString("id")))
                    result.put("ok", true).put("source_id", source).put("id", source)
                        .put("editor_url", VideoEditorContract.editorPath(source))
                        .put("seconds", got).put("audio", audio)
                    BridgeEnvelope.ok(id, result.toString())
                } catch (err: Exception) {
                    // Preserve the captured moment if the upload failed. This
                    // is explicitly an original capture, not an edited result.
                    val kept = runCatching {
                        withContext(Dispatchers.IO) {
                            temp?.takeIf { it.isFile && it.length() > 0 }?.let { file ->
                                val name = "pinetab-original-${System.currentTimeMillis()}.mp4"
                                com.pinebox.kiosk.audio.ClipSaver.keepFile(context, file, name,
                                    configStore.read().recordingFolder, "video/mp4")
                            }
                        }
                    }.getOrNull()
                    BridgeEnvelope.ok(id, JSONObject().put("ok", false)
                        .put("detail", err.message ?: "the capture could not be opened for editing")
                        .put("original_saved", kept?.ok ?: false).put("where", kept?.where ?: "")
                        .put("audio", replay.audioStatus()).toString())
                } finally { try { temp?.delete() } catch (_: Exception) { } }
            }
        }

        "replayKeepEdited" -> {
            val opts = args.optJSONObject(0) ?: JSONObject()
            val exportId = opts.optString("export_id")
            var temp: File? = null
            try {
                val info = JSONObject(client.get(VideoEditorContract.exportRoute(exportId)))
                require(info.optString("status") == "complete") { "the edited video is not ready to save" }
                val file = withContext(Dispatchers.IO) { File.createTempFile("edited-video-", ".mp4", context.cacheDir) }
                temp = file
                client.getVideoEditorExport(exportId, file)
                val name = opts.optString("name").ifBlank { info.optString("name", "pine-edited-$exportId.mp4") }
                val folder = configStore.read().recordingFolder
                val kept = withContext(Dispatchers.IO) {
                    com.pinebox.kiosk.audio.ClipSaver.keepFile(context, file,
                        if (name.endsWith(".mp4", true)) name else "$name.mp4", folder, "video/mp4")
                }
                BridgeEnvelope.ok(id, JSONObject().put("ok", kept.ok).put("where", kept.where)
                    .put("bytes", kept.bytes).put("detail", kept.detail).put("export_id", exportId).toString())
            } catch (err: Exception) {
                BridgeEnvelope.ok(id, JSONObject().put("ok", false).put("detail", err.message ?: "edited video could not be saved").toString())
            } finally { try { temp?.delete() } catch (_: Exception) { } }
        }

        /* THE PREFERENCES. Read, or merge-and-persist; either way the
         * settled object is {enabled, tl, tr, bl, br, ring}, and a set
         * pushes that same object into the page. One function for this and
         * for the drawer's rows: config/HotCorners.kt. */
        /* #1426: the native endless-video surface. `on` starts it and
         * shows it, anything else stops and hides it; the answer is
         * always the wall's own state, so the page can tell whether it
         * should be drawing a picture itself. A build with no wall (no
         * activity yet) answers on:false and the page keeps its <video>,
         * which is exactly the old behaviour. */
        "videoWall" -> {
            val wall = videoWall
            val want = args.optString(0, "state")
            if (wall == null) {
                BridgeEnvelope.ok(id, org.json.JSONObject().put("on", false)
                    .put("why", "no wall on this build").toString())
            } else {
                /* #1426b: the rect the page reports, in device pixels.
                 * Sent on every ask, so dragging the set moves the wall. */
                args.optJSONObject(1)?.let { box ->
                    wall.setBox(box.optInt("x"), box.optInt("y"),
                        box.optInt("w"), box.optInt("h"))
                }
                when (want) {
                    "on" -> { wall.veil(false); wall.start() }
                    "off" -> wall.stop()
                    /* #1434: veiling is not stopping - the playlist keeps
                     * running and only the surface leaves the screen. */
                    "hide" -> wall.veil(true)
                    "show" -> wall.veil(false)
                    else -> Unit
                }
                BridgeEnvelope.ok(id, wall.state().toString())
            }
        }

        "hotCorners" -> BridgeEnvelope.ok(id, HotCorners.read(configStore).toString())

        "hotCornersSet" -> BridgeEnvelope.ok(id,
            HotCorners.set(configStore, args.optJSONObject(0)) { script ->
                webView.post { webView.evaluateJavascript(script, null) }
            }.toString())

        /* One slice of the parked replay, base64 - the same shape micChunk
         * uses, and for the same reason: a multi-megabyte return from a
         * @JavascriptInterface is the kind of thing that works in a test and
         * fails on a long clip. */
        "replayChunk" -> {
            val held = heldReplay
            if (held == null) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false).put("detail", "there is no replay waiting").toString())
            } else {
                val opts = args.optJSONObject(0) ?: JSONObject()
                val at = opts.optInt("at", 0).coerceIn(0, held.size)
                val much = opts.optInt("much", TAKE_CHUNK).coerceIn(1, TAKE_CHUNK)
                val end = minOf(held.size, at + much)
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", true).put("at", at).put("bytes", held.size)
                    .put("sent", end - at).put("done", end >= held.size)
                    .put("b64", android.util.Base64.encodeToString(
                        held.copyOfRange(at, end), android.util.Base64.NO_WRAP)).toString())
            }
        }

        "micTake" -> {
            val level = mic.takeLevel()
            val wasRunning = mic.isRunning
            val died = mic.lastError
            val wall = mic.wallSeconds.toDouble()
            val wav = mic.stop()
            heldTake = wav
            BridgeEnvelope.ok(id, JSONObject()
                .put("ok", wav != null)
                .put("bytes", wav?.size ?: 0)
                .put("rate", com.pinebox.kiosk.audio.MicCapture.RATE)
                .put("seconds", if (wav != null)
                    (wav.size - 44) / (com.pinebox.kiosk.audio.MicCapture.RATE * 2.0) else 0.0)
                /* The clock beside the sample count, the same pair micState
                 * reports: when they disagree the read loop fell behind, and
                 * a recording that is quietly short is worse than one that
                 * failed. */
                .put("wall", wall)
                .put("level", level.toDouble())
                .put("quiet", level < QUIET)
                .put("wasRunning", wasRunning)
                .put("detail", died ?: JSONObject.NULL).toString())
        }

        /* One slice of the parked take, base64. `at` and `much` in BYTES of
         * the original, so the caller walks the file rather than the
         * encoding and cannot land mid-character. */
        "micChunk" -> {
            val take = heldTake
            if (take == null) {
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", false)
                    .put("detail", "there is no take waiting to be read").toString())
            } else {
                val opts = args.optJSONObject(0) ?: JSONObject()
                val at = opts.optInt("at", 0).coerceIn(0, take.size)
                val much = opts.optInt("much", TAKE_CHUNK)
                    .coerceIn(1, TAKE_CHUNK)
                val end = minOf(take.size, at + much)
                val slice = take.copyOfRange(at, end)
                BridgeEnvelope.ok(id, JSONObject()
                    .put("ok", true)
                    .put("at", at)
                    .put("bytes", take.size)
                    .put("sent", slice.size)
                    .put("done", end >= take.size)
                    .put("b64", android.util.Base64.encodeToString(
                        slice, android.util.Base64.NO_WRAP)).toString())
            }
        }

        "micState" -> BridgeEnvelope.ok(id, JSONObject()
            .put("running", mic.isRunning)
            .put("seconds", mic.seconds.toDouble())
            /* The clock beside the sample count. They should agree; when
             * they do not, the read loop is not keeping up or a second one
             * is writing into the same buffer, and both of those reach the
             * operator as "it did not hear me". Visible here so the next
             * one is seen rather than deduced. */
            .put("wall", mic.wallSeconds.toDouble())
            .put("level", mic.level.toDouble())
            .put("effects", mic.effects())
            .put("channels", mic.channelReport())
            .put("error", mic.lastError ?: JSONObject.NULL).toString())

        /* Electron streams the local station's stdout here. There is no
         * local station, so the honest answer is an empty log rather than
         * an error the panel has to special-case. */
        "backendLog" -> BridgeEnvelope.okString(id, "")

        in BACKEND_METHODS -> BridgeEnvelope.unsupported(id, method, WHY_BACKEND)
        in LCD_METHODS -> BridgeEnvelope.unsupported(id, method, WHY_LCD)
        in TERMINAL_METHODS -> BridgeEnvelope.unsupported(id, method, WHY_TERMINAL)

        else -> BridgeEnvelope.error(id, "unrouted bridge method: $method")
    }

    /**
     * THE FILE TO THE STATION'S EXPORT COURIER, HONESTLY REPORTED.
     *
     * PUT <base>/api/export/upload?name=..&what=..&seconds=.. with the MP4
     * as the whole body, Content-Type video/mp4, streamed from the file -
     * the station container has no multipart parser, so nothing here is a
     * form. The station's answer, {ok:true, id, name, dest}, is passed
     * through where it has the fields; a refusal, a missing route (404 -
     * the courier may not be built yet) or no station at all each come
     * back as {ok:false, detail} rather than as a thrown error, because the
     * caller has already written the file and must say so whatever
     * happened here.
     */
    private suspend fun uploadExport(file: File, name: String, what: String,
                                     seconds: Double): JSONObject = try {
        val route = "/api/export/upload?name=" + URLEncoder.encode(name, "UTF-8") +
            "&what=" + URLEncoder.encode(what, "UTF-8") +
            "&seconds=" + Math.round(seconds)
        val text = client.putFile(route, file, "video/mp4")
        val answer = try { JSONObject(text) } catch (err: Exception) { JSONObject() }
        JSONObject()
            .put("ok", answer.optBoolean("ok", true))
            .put("id", answer.opt("id") ?: JSONObject.NULL)
            .put("dest", answer.opt("dest") ?: answer.opt("path") ?: JSONObject.NULL)
            .put("detail", answer.opt("detail") ?: answer.opt("error") ?: JSONObject.NULL)
    } catch (err: StationException) {
        JSONObject().put("ok", false)
            .put("detail", "the station said " + err.code + ": " + (err.message ?: ""))
    } catch (err: Exception) {
        JSONObject().put("ok", false)
            .put("detail", "no answer from the station: " + (err.message ?: err.javaClass.simpleName))
    }

    /** The ear. One instance for the app: the hardware is one microphone
     *  and two takes at once would be two failures, not two recordings. */
    private val mic = com.pinebox.kiosk.audio.MicCapture(context)

    /** Set by the activity, which owns the watch's lifetime. */
    @Volatile var jackWatch: com.pinebox.kiosk.audio.JackWatch? = null

    /* THE PICKER NEEDS AN ACTIVITY, and this class deliberately holds only an
     * application Context (see the class comment on threading). Set while the
     * activity is resumed and cleared when it is not, so a picker can never
     * be launched into a window that has gone. */
    @Volatile var liveActivity: com.pinebox.kiosk.MainActivity? = null

    /* #1426: THE PICTURE IS NOT THE PAGE'S ANY MORE.
     *
     * The endless set's clips are played by a SurfaceView that
     * SurfaceFlinger composites directly, because this WebView renders at
     * 8-12 fps whatever is in it - measured with the whole panel hidden
     * and one 427x240 video alone on the document. See PineVideoWall for
     * the numbers. The page's job is now only to say WHERE and WHETHER. */
    @Volatile var videoWall: com.pinebox.kiosk.video.PineVideoWall? = null

    /**
     * HOW LOUD IT IS RIGHT NOW, 0..1.
     *
     * Synchronous and unregistered, unlike everything else here, because
     * the talk dot's particles read it on every animation frame - sixty
     * times a second. A promise per frame would put sixty settlements a
     * second through the WebView's handler; this is a volatile field read.
     */
    @JavascriptInterface
    fun micLevel(): Double = mic.level.toDouble()

    /**
     * Stop the take, hand it to the station, return the words.
     *
     * EVERY WAY THIS CAN FAIL NOW GETS ITS OWN SENTENCE, and that is the
     * point of this method rather than a detail of it.
     *
     * The operator spoke to the dot three times running and was told
     * "Nothing was made out of that" three times, while wyoming-whisper's
     * own container log held his exact sentences - the station was reading
     * the transcript out of the wrong field and answering {"text": ""}.
     * The bug was in app.py and is fixed there. What made it cost three
     * takes to find is HERE: this method returned an empty string with no
     * `detail` for that case, and the dot has one catch-all sentence for a
     * blank answer. A transcriber that had been handed silence, a station
     * that had timed out, a refused key and a model that heard nothing all
     * arrived on screen as the same eight words, so the screen could not
     * be used as evidence about any of them.
     *
     * So there is no silent road out of here. Each return carries a
     * sentence that names what happened and, where it is a number that
     * decided it, the number: how long the take was, how loud it was, what
     * the station said. A failure that names itself is the difference
     * between a bug found in one take and a bug found in three.
     */
    private suspend fun transcribe(): JSONObject {
        /* READ THE LEVEL BEFORE STOPPING. takeLevel() is the RMS of the
         * running sums the worker keeps, which only start() resets - but
         * stop() empties the sink, and reading it after would be reading a
         * measurement of a take that no longer exists. */
        val level = mic.takeLevel()
        val wasRunning = mic.isRunning
        val died = mic.lastError
        /* Read while the take is still open: how long it has been running
         * by the CLOCK, to be set against how many samples came out of
         * it. */
        val wall = mic.wallSeconds.toDouble()
        val wav = mic.stop()

        if (wav == null) {
            /* Three different nothings, and the operator can act on only
             * two of them - so they are not allowed to share a sentence. */
            val why = when {
                !wasRunning ->
                    "that take had already been stopped - the microphone was " +
                        "not open when the dot let go of it"
                died != null ->
                    "the microphone stopped part way through the take: " + died
                else ->
                    "the microphone opened but not one sample ever arrived from it"
            }
            return JSONObject().put("ok", false).put("text", "")
                .put("level", level.toDouble()).put("detail", why)
        }

        val seconds = (wav.size - 44) / (com.pinebox.kiosk.audio.MicCapture.RATE * 2.0)

        /* SAMPLES AGAINST THE CLOCK.
         *
         * The read loop runs on a daemon thread, and a thread that stops
         * reading does not announce it: the take simply ends early and the
         * clip holds the first part of the sentence. Transcribed, that is
         * a fragment or nothing, and it is indistinguishable on screen
         * from a microphone that heard nothing - which is exactly the
         * class of fault this whole road has just cost three takes to.
         * A quarter of the audio missing is well past any rounding. */
        val dropped = wall > 1.0 && seconds < wall * 0.75

        /* A TAKE THIS SHORT IS A BUG, NOT A SENTENCE. Seen once at 0.16 s:
         * a stale capture was being stopped while a second one had already
         * replaced the sink. Whisper would answer "" for it and the screen
         * would blame the operator's voice. */
        if (seconds < 0.35) {
            return JSONObject().put("ok", false).put("text", "")
                .put("seconds", seconds).put("level", level.toDouble())
                .put("detail", String.format(
                    "the take was only %.2f seconds long, which is too short to " +
                        "be speech - the dot stopped listening before you spoke",
                    seconds))
        }

        if (level < QUIET) {
            return JSONObject().put("ok", false).put("text", "")
                .put("seconds", seconds).put("level", level.toDouble())
                .put("detail", String.format(
                    "the room was silent for all %.1f seconds of that take " +
                        "(loudness %.4f, below the %.4f floor), so nothing was sent",
                    seconds, level, QUIET))
        }

        val body = try {
            client.postBytes("/api/listen/transcribe", wav, "audio/wav")
        } catch (err: Exception) {
            /* NAME THE FAILURE, DO NOT QUOTE THE EXCEPTION. OkHttp's own
             * message for a read timeout is the single word "timeout",
             * which told the operator nothing at all when it reached the
             * screen; and a refusal by the station is a different act from
             * being unable to reach it. */
            val why = when (err) {
                is StationException ->
                    "the station refused the clip with " + err.code + ": " +
                        (err.message ?: "no reason given")
                is java.net.SocketTimeoutException ->
                    "the station took the clip but had not answered after " +
                        "two and a half minutes, so the words were lost on the " +
                        "way back"
                is java.net.ConnectException, is java.net.UnknownHostException ->
                    "this terminal could not reach the station to send the " +
                        "clip: " + (err.message ?: err.javaClass.simpleName)
                is java.io.IOException ->
                    "the clip was cut off on its way to the station: " +
                        (err.message ?: err.javaClass.simpleName)
                else ->
                    "sending the clip failed: " +
                        (err.message ?: err.javaClass.simpleName)
            }
            return JSONObject().put("ok", false).put("text", "")
                .put("seconds", seconds).put("level", level.toDouble())
                .put("detail", why)
        }

        val got = try {
            JSONObject(body)
        } catch (err: Exception) {
            /* The station answered SOMETHING that is not the shape agreed.
             * Carrying the first of it back is what turns "nothing was
             * made out of that" into a fault anyone can act on. */
            return JSONObject().put("ok", false).put("text", "")
                .put("seconds", seconds).put("level", level.toDouble())
                .put("detail", "the station answered with something that is " +
                    "not JSON: " + body.take(120).replace("\n", " "))
        }

        val text = got.optString("text", "").trim()
        if (text.isEmpty()) {
            /* The station now says WHY it has no words - whisper heard
             * none, or it never got that far. Its reason outranks anything
             * this side could guess, so it is passed through verbatim. */
            val why = if (dropped) String.format(
                "the microphone stopped part way through: %.1f seconds of " +
                    "sound out of the %.1f seconds it was open, so only the " +
                    "start of what you said was sent", seconds, wall)
            else got.optString("detail", "").ifBlank {
                String.format(
                    "the station answered with no words in it and gave no " +
                        "reason (%.1f seconds of audio at loudness %.3f)",
                    seconds, level)
            }
            return JSONObject().put("ok", false).put("text", "")
                .put("seconds", seconds).put("level", level.toDouble())
                .put("detail", why)
        }

        return JSONObject()
            .put("ok", true)
            .put("text", text)
            .put("heard", true)
            .put("seconds", seconds)
            .put("wall", wall)
            /* Carried even on the happy road: words came back, but if the
             * clip was short of the time the microphone was open they are
             * only the words from the part that survived. */
            .put("dropped", dropped)
            .put("level", level.toDouble())
            .put("lift", mic.lift.toDouble())
    }

    /** First argument, the route. */
    private fun route(args: JSONArray): String = args.optString(0)

    /**
     * Second argument, the body. It may be an object, an array, or already
     * a string; anything non-null is sent as JSON. `JSONObject.NULL` and a
     * missing argument both mean "no body", which the client turns into
     * `{}` for the methods that need one.
     */
    private fun body(args: JSONArray): String? {
        if (args.length() < 2) return null
        val raw = args.opt(1) ?: return null
        if (raw === JSONObject.NULL) return null
        return when (raw) {
            is JSONObject -> raw.toString()
            is JSONArray -> raw.toString()
            is String -> raw
            else -> raw.toString()
        }
    }

    /**
     * What this terminal is, so "am I on the latest?" has an answer here
     * too - the same question desktop/preload.js:12 asks on the desktop.
     */
    private fun buildInfo(): JSONObject = JSONObject()
        .put("shell", "android-kiosk")
        .put("versionName", BuildConfig.VERSION_NAME)
        .put("versionCode", BuildConfig.VERSION_CODE)
        .put("applicationId", BuildConfig.APPLICATION_ID)
        .put("device", Build.MODEL)
        .put("product", Build.PRODUCT)
        .put("board", Build.BOARD)
        .put("androidSdk", Build.VERSION.SDK_INT)
        .put("androidRelease", Build.VERSION.RELEASE)
        .put("abi", Build.SUPPORTED_ABIS.firstOrNull() ?: "")
        .put("fingerprint", Build.FINGERPRINT)

    /** Deliver a settlement to the shim. Must run on the WebView's thread. */
    private fun settle(id: String, envelopeJson: String) {
        val script = "window.__pineBridgeSettle && window.__pineBridgeSettle(" +
            BridgeEnvelope.quote(id) + "," + BridgeEnvelope.quote(envelopeJson) + ");"
        webView.post {
            try {
                webView.evaluateJavascript(script, null)
            } catch (err: Exception) {
                Log.w(TAG, "could not settle $id", err)
            }
        }
    }

    /**
     * Push one of Electron's two event channels into the page. Nothing
     * calls this today (there is no local backend to log) - it exists so a
     * later native producer has a landing place and does not have to invent
     * a second mechanism.
     */
    fun emit(channel: String, payloadJson: String) {
        val script = "window.__pineBridgeEmit && window.__pineBridgeEmit(" +
            BridgeEnvelope.quote(channel) + "," + BridgeEnvelope.quote(payloadJson) + ");"
        webView.post { webView.evaluateJavascript(script, null) }
    }

    /* ----------------------------------------------------------------- */
    /* The clipboard - synchronous, on purpose                            */
    /* ----------------------------------------------------------------- */

    /**
     * #990 on the desktop: the Copy button did nothing because the panel is
     * served over plain http, so `window.isSecureContext` is false and
     * `navigator.clipboard` is undefined. That is just as true inside this
     * WebView, so the same cure applies: a native clipboard that has no
     * secure-context rule.
     */
    @JavascriptInterface
    fun copyText(text: String?): Boolean = onMainBlocking(false) {
        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            ?: return@onMainBlocking false
        clipboard.setPrimaryClip(ClipData.newPlainText("Pine Box", text ?: ""))
        true
    }

    /**
     * #1047 on the desktop: copy the whole Gazette as ONE picture.
     *
     * Electron could take a nativeImage straight onto the clipboard.
     * Android cannot: its clipboard carries a content:// URI, never a
     * bitmap. So the PNG is written into cache/clipboard/ and shared
     * read-only through the FileProvider declared in the manifest. One
     * fixed filename, overwritten each time - the clipboard only ever holds
     * the most recent copy, and a terminal should not accumulate PNGs of
     * every newspaper anyone ever pressed Copy on.
     */
    @JavascriptInterface
    fun copyImage(dataUrl: String?): Boolean {
        val url = dataUrl.orEmpty()
        val comma = url.indexOf(',')
        if (comma < 0 || !url.startsWith("data:")) return false
        val header = url.substring(5, comma)
        if (!header.contains("base64")) return false
        val bytes = try {
            Base64.decode(url.substring(comma + 1), Base64.DEFAULT)
        } catch (err: IllegalArgumentException) {
            return false
        }
        if (bytes.isEmpty()) return false

        val mime = header.substringBefore(';').ifBlank { "image/png" }
        val extension = if (mime.endsWith("jpeg") || mime.endsWith("jpg")) "jpg" else "png"

        return try {
            val dir = File(context.cacheDir, "clipboard").apply { mkdirs() }
            val file = File(dir, "pinebox-clip.$extension")
            file.writeBytes(bytes)
            val uri = FileProvider.getUriForFile(
                context, BuildConfig.APPLICATION_ID + ".clipboard", file,
            )
            onMainBlocking(false) {
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                    ?: return@onMainBlocking false
                val clip = ClipData.newUri(context.contentResolver, "Pine Box", uri)
                clipboard.setPrimaryClip(clip)
                /* The clipboard service grants the eventual paster read
                 * access to the URI, but only once it holds the clip - and
                 * the system UI preview reads it before that. Granting to
                 * "android" covers the preview; without it the paste target
                 * sees a URI it cannot open. */
                context.grantUriPermission(
                    "android", uri, Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
                true
            }
        } catch (err: Exception) {
            Log.w(TAG, "copyImage failed", err)
            false
        }
    }

    /** From desktop/renderer/webview-preload.js: a real bridge says so. */
    @JavascriptInterface
    fun clipboardReady(): Boolean = true

    /**
     * Run a block on the main thread and wait for it.
     *
     * Safe here and only here: @JavascriptInterface runs on the JavaBridge
     * thread, so the main thread is not the caller and cannot deadlock
     * against it. The timeout is belt and braces - if the main thread is
     * genuinely wedged, the Copy button should report failure rather than
     * hang the JavaScript engine forever.
     */
    private fun <T> onMainBlocking(fallback: T, block: () -> T): T {
        val latch = java.util.concurrent.CountDownLatch(1)
        var result: T = fallback
        scope.launch(Dispatchers.Main) {
            try {
                /* Assigned INSIDE the try. Written as
                 * `result = try { ... } finally { countDown() }` the latch
                 * opens before the assignment lands, and the waiting thread
                 * reads the fallback about one time in a thousand. */
                result = block()
            } catch (err: Exception) {
                Log.w(TAG, "main-thread bridge work failed", err)
            } finally {
                latch.countDown()
            }
        }
        latch.await(2, java.util.concurrent.TimeUnit.SECONDS)
        return result
    }
}
