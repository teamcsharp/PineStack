package com.pinebox.kiosk.bridge

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.util.Base64
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.core.content.FileProvider
import com.pinebox.kiosk.BuildConfig
import com.pinebox.kiosk.config.ConfigStore
import com.pinebox.kiosk.net.StationClient
import com.pinebox.kiosk.net.StationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

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
            /* What the terminal confirmed on its way up - see net/Readiness. */
            "readyReport",
            /* Keeping a line: to the tablet, or to the working folder. */
            "keepClip", "jack", "wallpaper", "saveText", "saveBytes",
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
    }

    /* The last take, parked between micTake and the micChunk calls that read
     * it out. Cleared by micCancel and overwritten by the next micTake, so a
     * take cannot be read twice by accident or outlive the one after it. */
    @Volatile private var heldTake: ByteArray? = null

    /** The last replay written, parked between replaySave and replayChunk. */
    @Volatile private var heldReplay: ByteArray? = null

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
                val want = args.optJSONObject(0)?.optDouble("seconds", 30.0) ?: 30.0
                try {
                    val (file, got) = replay.save(want)
                    heldReplay = file.readBytes()
                    file.delete()
                    BridgeEnvelope.ok(id, JSONObject()
                        .put("ok", true)
                        .put("bytes", heldReplay?.size ?: 0)
                        .put("asked", want)
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
