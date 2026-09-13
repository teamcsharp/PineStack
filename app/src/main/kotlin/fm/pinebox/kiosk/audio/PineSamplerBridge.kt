package fm.pinebox.kiosk.audio

import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/**
 * The WebView's door into the native engine.
 *
 * WHY THIS EXISTS. The sampler UI is a web page and it ships UNCHANGED on
 * both terminals - the desktop's Electron window and this tablet load the
 * same HTML, the same CSS and the same sampler.js. That page talks to
 * `window.pineSampler` and to nothing else. On the desktop, sampler-engine.js
 * defines it in Web Audio. Here, [SHIM_JS] defines it first (and
 * sampler-engine.js politely declines to overwrite it), and every call lands
 * on the native engine instead.
 *
 * Two things about the shape of this class:
 *
 * BYTES. `@JavascriptInterface` speaks strings and primitives - there is no
 * way to hand an ArrayBuffer across. So [beginLoad]/[pushChunk]/[finishLoad]
 * move a clip over in base64 in pieces. A booth line is about 600 KB, which
 * is 800 KB of base64; sending it as one string works most of the time and
 * fails on the transaction size the day someone loads a longer one, so it
 * goes in [CHUNK_BYTES] pieces and is reassembled here. It happens once per
 * pad, not per press.
 *
 * PROMISES. load() is asynchronous on both sides. finishLoad returns a
 * request id at once and the decode runs on a worker; when it finishes, this
 * class calls back into the page to settle the promise the shim is holding.
 * Nothing about a PRESS is asynchronous - fire() is a plain synchronous call
 * that returns a voice id, exactly as it does in Web Audio.
 */
class PineSamplerBridge(private val webView: WebView) {

    private val pending = ConcurrentHashMap<String, ByteArrayOutputStream>()
    private val tokens = AtomicLong(0)
    private val requests = AtomicLong(0)

    // ------------------------------------------------------------ loading --

    @JavascriptInterface
    fun beginLoad(): String {
        val token = "t" + tokens.incrementAndGet()
        pending[token] = ByteArrayOutputStream()
        return token
    }

    @JavascriptInterface
    fun pushChunk(token: String, base64: String): Boolean {
        val sink = pending[token] ?: return false
        return try {
            sink.write(Base64.decode(base64, Base64.DEFAULT))
            true
        } catch (error: IllegalArgumentException) {
            pending.remove(token)
            false
        }
    }

    @JavascriptInterface
    fun abortLoad(token: String) {
        pending.remove(token)
    }

    /**
     * Decode what was pushed and hold it on [padId]. Returns a request id; the
     * page's promise is settled later through `window.__pineSamplerSettle`.
     */
    @JavascriptInterface
    fun finishLoad(token: String, padId: String): String {
        val request = "r" + requests.incrementAndGet()
        val sink = pending.remove(token)
        if (sink == null) {
            settle(request, false, JSONObject().put("error", "That upload went missing."))
            return request
        }
        val bytes = sink.toByteArray()
        if (bytes.isEmpty()) {
            settle(request, false, JSONObject().put("error", "That sample was empty."))
            return request
        }
        PineSampler.load(padId, bytes) { result, error ->
            if (result == null) {
                settle(request, false, JSONObject()
                    .put("error", error ?: "That sample would not decode."))
            } else {
                settle(request, true, JSONObject()
                    .put("seconds", result.seconds)
                    .put("rate", result.rate)
                    .put("channels", result.channels))
            }
        }
        return request
    }

    private fun settle(request: String, ok: Boolean, payload: JSONObject) {
        val script = "window.__pineSamplerSettle && window.__pineSamplerSettle(" +
            JSONObject.quote(request) + "," + ok + "," + payload.toString() + ");"
        webView.post { webView.evaluateJavascript(script, null) }
    }

    // ------------------------------------------------------------- surface --

    /**
     * Whether there is an engine behind this bridge at all.
     *
     * A build made without the native library still installs and runs, and on
     * one of those the shim must stand aside so sampler-engine.js can define
     * window.pineSampler in Web Audio. Slow beats silent.
     */
    @JavascriptInterface
    fun engineAvailable(): Boolean = PineSampler.available() && PineSampler.attached()

    @JavascriptInterface
    fun warm(): Boolean = PineSampler.warm()

    @JavascriptInterface
    fun ready(): Boolean = PineSampler.ready()

    /**
     * Give the audio output back.
     *
     * NOT an optimisation - a correctness fix, measured on the tablet. While
     * this engine held its AAudio stream, the audio server listed exactly one
     * started player:
     *
     *     piid:495 type:AAudio usage=USAGE_GAME state:started
     *
     * and NO AudioTrack for the WebView at all. The panel's <audio> element
     * was unmuted, at full volume, with readyState 4 and its clock advancing
     * in real time - and nothing came out of the tablet, because its audio
     * never reached the mixer. Every indicator said "playing".
     *
     * So the stream is held only while the sampler is the view on screen.
     * The page calls this when the sampler is left and warm() when it is
     * opened, which is what the note on PineSampler.warm always asked for.
     */
    @JavascriptInterface
    fun sleep() = PineSampler.sleep()

    @JavascriptInterface
    fun setPolyphonic(on: Boolean) = PineSampler.setPolyphonic(on)

    @JavascriptInterface
    fun isPolyphonic(): Boolean = PineSampler.isPolyphonic()

    @JavascriptInterface
    fun copy(from: String, to: String): Boolean = PineSampler.copy(from, to)

    @JavascriptInterface
    fun unload(padId: String): Boolean = PineSampler.unload(padId)

    @JavascriptInterface
    fun clear(): Boolean = PineSampler.clear()

    @JavascriptInterface
    fun loaded(padId: String): Boolean = PineSampler.loaded(padId)

    @JavascriptInterface
    fun seconds(padId: String): Double = PineSampler.seconds(padId)

    @JavascriptInterface
    fun peaks(padId: String, buckets: Int): String {
        val values = PineSampler.peaks(padId, buckets)
        val out = JSONArray()
        for (v in values) out.put(v.toDouble())
        return out.toString()
    }

    @JavascriptInterface
    fun zeroCross(padId: String, seconds: Double, withinMs: Double): Double =
        PineSampler.zeroCross(padId, seconds, withinMs)

    /**
     * [patchJson] is the object the UI passed to set(), verbatim. A field
     * that is absent stays absent - that is the whole reason this crosses as
     * JSON rather than as a fixed argument list.
     */
    @JavascriptInterface
    fun set(padId: String, patchJson: String): String {
        val patch = JSONObject(patchJson)
        var trim: Trim? = null
        val mentionsTrim = patch.has("trim")
        if (mentionsTrim && !patch.isNull("trim")) {
            val raw = patch.getJSONObject("trim")
            trim = Trim(raw.optDouble("start", 0.0), raw.optDouble("end", 0.0))
        }
        PineSampler.set(
            padId,
            PadPatch(
                gain = if (patch.has("gain")) patch.optDouble("gain", 0.0) else null,
                pitch = if (patch.has("pitch")) patch.optDouble("pitch", 1.0) else null,
                pan = if (patch.has("pan")) patch.optDouble("pan", 0.0) else null,
                loop = if (patch.has("loop")) patch.optBoolean("loop") else null,
                reverse = if (patch.has("reverse")) patch.optBoolean("reverse") else null,
                choke = if (patch.has("choke")) patch.optString("choke", "") else null,
                trim = trim,
                trimMentioned = mentionsTrim
            )
        )
        return get(padId)
    }

    @JavascriptInterface
    fun get(padId: String): String {
        val state = PineSampler.get(padId) ?: return "null"
        val out = JSONObject()
            .put("id", state.id)
            .put("gain", state.gain)
            .put("pitch", state.pitch)
            .put("pan", state.pan)
            .put("loop", state.loop)
            .put("reverse", state.reverse)
            .put("choke", state.choke)
            .put("seconds", state.seconds)
        if (state.trim == null) {
            out.put("trim", JSONObject.NULL)
        } else {
            out.put("trim", JSONObject()
                .put("start", state.trim.start)
                .put("end", state.trim.end))
        }
        return out.toString()
    }

    /** THE PRESS. Synchronous, and back before the finger has moved. */
    @JavascriptInterface
    fun fire(padId: String, optionsJson: String): String {
        val options = JSONObject(optionsJson)
        return PineSampler.fire(
            padId,
            FireOptions(
                velocity = if (options.has("velocity")) options.optDouble("velocity", 1.0) else null,
                pitch = if (options.has("pitch")) options.optDouble("pitch", 1.0) else null,
                loop = if (options.has("loop")) options.optBoolean("loop") else null,
                gate = options.optBoolean("gate", false)
            )
        )
    }

    @JavascriptInterface
    fun release(voiceId: String) = PineSampler.release(voiceId)

    @JavascriptInterface
    fun stopPad(padId: String) = PineSampler.stopPad(padId)

    @JavascriptInterface
    fun stopAll() = PineSampler.stopAll()

    @JavascriptInterface
    fun sixteenLevelPitch(padIndex: Int): Double = PineSampler.sixteenLevelPitch(padIndex)

    @JavascriptInterface
    fun footprint(): String {
        val footprint = PineSampler.footprint()
        return JSONObject()
            .put("bytes", footprint.bytes)
            .put("pads", footprint.pads)
            .put("buffers", footprint.buffers)
            .toString()
    }

    @JavascriptInterface
    fun levels(): String {
        val levels = PineSampler.levels()
        val pads = JSONObject()
        for ((pad, count) in levels.pads) pads.put(pad, count)
        /* `stream` and `start` are ADDITIONS, not replacements: baseLatency
         * and outputLatency keep meaning what they mean in Web Audio so the
         * one UI can read either backend without a branch. What is new is
         * everything underneath them, which the Web Audio side has no
         * equivalent for and simply does not send. */
        val stream = JSONObject()
            .put("burstFrames", levels.stream.burstFrames)
            .put("bufferFrames", levels.stream.bufferFrames)
            .put("capacityFrames", levels.stream.capacityFrames)
            .put("xruns", levels.stream.xruns)
            .put("exclusive", levels.stream.exclusive)
            .put("mmap", levels.stream.mmap)
            .put("api", levels.stream.api)
            .put("timestampLatency", levels.stream.timestampLatency)
        val start = JSONObject()
            .put("lastMs", levels.start.lastMs)
            .put("worstMs", levels.start.worstMs)
            .put("count", levels.start.count)
            .put("meanMs", levels.start.meanMs)
        return JSONObject()
            .put("voices", levels.voices)
            .put("pads", pads)
            .put("state", levels.state)
            .put("baseLatency", levels.baseLatency)
            .put("outputLatency", levels.outputLatency)
            .put("duckGain", levels.duckGain.toDouble())
            .put("stream", stream)
            .put("start", start)
            .toString()
    }

    /**
     * Clear the fire-to-sound counters and drop the buffer back to the two
     * bursts the stream opens with.
     *
     * Called by a measuring run before it takes a reading, so the number
     * describes the run rather than whatever the last hour left behind.
     */
    @JavascriptInterface
    fun retune() = PineSampler.retune()

    /**
     * The engine's monotonic clock in nanoseconds, as a string because
     * `@JavascriptInterface` cannot return a long without JavaScript
     * rounding it - a double loses nanoseconds above about 104 days of
     * uptime, and this device is not rebooted often enough to risk it.
     */
    @JavascriptInterface
    fun nowNanos(): String = PineSampler.nowNanos().toString()


    // ---------------------------------------------------------- fast path --

    /*
     * THE MEASUREMENT THIS EXISTS FOR.
     *
     * On this tablet, with real taps injected through the Android input
     * stack and timed against the page's own clock, the trip from the
     * MotionEvent being stamped to the page's pointerdown handler running
     * measured a MEDIAN OF 61-67 ms (min 16, p90 94, max 112 over 65 taps).
     * The rest of the chain, measured the same way: the page's handler
     * through the bridge into the engine, 1.3 ms; fire() to the audio block
     * that carries it, 2.8 ms; that block to the speaker, 21.5 ms from the
     * stream's own timestamp. So roughly seventy per cent of everything
     * between the finger and the sound was the WebView's input dispatch,
     * and none of it was the audio engine.
     *
     * The platform agrees: dumpsys gfxinfo reported 1528 frames of "High
     * input latency" against 795 frames rendered, on a page whose render
     * thread alone was burning sixty per cent of a core.
     *
     * So the attack does not go through the WebView any more. A touch
     * listener on the WebView runs on the UI thread the moment the event
     * arrives - BEFORE the event is handed to the renderer, before layout,
     * before JavaScript - hit-tests the press against pad rectangles the
     * page published earlier, and fires the voice there and then. The page's
     * own handler still runs, a frame or two later, and picks up the voice
     * that was already started instead of starting a second one.
     *
     * WHAT IT DELIBERATELY DOES NOT DO. Only the press. Release, choke,
     * note repeat, 16 Level and the lit-pad feedback all stay in the page,
     * because a gate released two frames late is inaudible and a drum hit
     * two frames late is the whole problem. One behaviour moved, not the
     * instrument.
     *
     * IT IS OFF UNTIL THE PAGE ASKS. Nothing fires until setFastPads()
     * has been called with a geometry, and a page that never calls it
     * behaves exactly as it did before. The desktop's Web Audio engine has
     * no equivalent and does not define claimFire(), which is why the page
     * checks for it rather than assuming it.
     */

    private class FastPad(
        val padId: String,
        val left: Float, val top: Float, val right: Float, val bottom: Float,
        val gate: Boolean, val full: Boolean, val pitch: Double
    )

    /** Published by the page; read on the UI thread by the touch listener. */
    @Volatile private var fastPads: List<FastPad> = emptyList()

    /* Three counters, reported through levels(), because "the fast path is
     * not firing" has three completely different causes and no way to tell
     * them apart from outside: the page never published a geometry, the
     * touch listener is not being called at all (something else owns the
     * WebView's one OnTouchListener slot), or presses are arriving and
     * missing every rectangle. One counter each. */
    private val fastTouches = java.util.concurrent.atomic.AtomicInteger(0)
    private val fastHits = java.util.concurrent.atomic.AtomicInteger(0)
    private val fastClaimed = java.util.concurrent.atomic.AtomicInteger(0)

    /* THE NUMBER THIS WHOLE PATH EXISTS FOR, measured rather than inferred.
     *
     * MotionEvent.getEventTime() is the uptime clock reading from when the
     * event was stamped - the same instant the page's handler measures
     * itself against when it compares event.timeStamp with
     * performance.now(). Taking uptimeMillis() here, at the top of the
     * listener, produces a figure directly comparable with the page's, so
     * the two paths can be put side by side instead of one being asserted
     * to be faster than the other.
     *
     * Milliseconds, summed and counted, so a mean survives a poll. */
    private val fastDispatchSum = java.util.concurrent.atomic.AtomicLong(0)
    private val fastDispatchWorst = java.util.concurrent.atomic.AtomicLong(0)

    /**
     * CSS pixels across the page's viewport, against which the rectangles
     * above were measured. The listener scales by the WebView's own width
     * rather than trusting devicePixelRatio, because the two disagree the
     * moment anything zooms the page.
     */
    @Volatile private var fastViewportWidth: Float = 0f

    /** padId -> the voice the fast path started, and when. */
    private val fastClaims = ConcurrentHashMap<String, Pair<String, Long>>()

    /**
     * Publish the pad rectangles the native touch path may fire.
     *
     * `json` is `{"viewportWidth": <css px>, "pads": [{id, x, y, w, h,
     * gate, full, pitch}]}` with x/y/w/h in CSS pixels relative to the
     * viewport - which is what getBoundingClientRect() already gives, so
     * scrolling is accounted for by the page rather than guessed at here.
     * An empty pad list turns the fast path off.
     */
    @JavascriptInterface
    fun setFastPads(json: String) {
        try {
            val root = JSONObject(json)
            val width = root.optDouble("viewportWidth", 0.0).toFloat()
            val array = root.optJSONArray("pads") ?: JSONArray()
            val pads = ArrayList<FastPad>(array.length())
            for (i in 0 until array.length()) {
                val entry = array.optJSONObject(i) ?: continue
                val id = entry.optString("id", "")
                if (id.isEmpty()) continue
                val x = entry.optDouble("x", 0.0).toFloat()
                val y = entry.optDouble("y", 0.0).toFloat()
                val w = entry.optDouble("w", 0.0).toFloat()
                val h = entry.optDouble("h", 0.0).toFloat()
                if (w <= 0f || h <= 0f) continue
                pads.add(FastPad(
                    padId = id, left = x, top = y, right = x + w, bottom = y + h,
                    gate = entry.optBoolean("gate", false),
                    full = entry.optBoolean("full", false),
                    pitch = entry.optDouble("pitch", 0.0)
                ))
            }
            fastViewportWidth = width
            fastPads = pads
            if (pads.isEmpty()) fastClaims.clear()
        } catch (error: org.json.JSONException) {
            /* A malformed geometry turns the fast path off rather than
             * leaving a stale one firing at the wrong rectangles. */
            fastPads = emptyList()
            fastClaims.clear()
        }
    }

    /**
     * Hand the page the voice the fast path already started for [padId], or
     * "" if it did not.
     *
     * The claim expires: a native press whose pointerdown never reaches the
     * page - swallowed by an overlay, say - must not be picked up by some
     * later press of the same pad and reported as its voice. A quarter of a
     * second is far longer than the dispatch this exists to skip and far
     * shorter than any two deliberate hits on one pad.
     */
    @JavascriptInterface
    fun claimFire(padId: String): String {
        val claim = fastClaims.remove(padId) ?: return ""
        val age = android.os.SystemClock.uptimeMillis() - claim.second
        if (age !in 0..FAST_CLAIM_MS) return ""
        fastClaimed.incrementAndGet()
        return claim.first
    }

    /** What the fast path has been doing, for levels(). */
    @JavascriptInterface
    fun fastState(): String = JSONObject()
        .put("pads", fastPads.size)
        .put("viewportWidth", fastViewportWidth.toDouble())
        .put("touches", fastTouches.get())
        .put("hits", fastHits.get())
        .put("claimed", fastClaimed.get())
        /* The listener's own dispatch, in milliseconds: the same quantity
         * the page measures for itself, so the two can be compared. */
        .put("dispatchMeanMs", if (fastTouches.get() > 0)
            fastDispatchSum.get().toDouble() / fastTouches.get() else 0.0)
        .put("dispatchWorstMs", fastDispatchWorst.get())
        .toString()

    /**
     * The WebView's touch listener. Runs on the UI thread, on the near side
     * of the renderer, and NEVER consumes the event - the page still gets
     * every press for its own lit-pad feedback, its release and its modes.
     */
    private fun onWebViewTouch(view: android.view.View, event: android.view.MotionEvent): Boolean {
        val action = event.actionMasked
        if (action != android.view.MotionEvent.ACTION_DOWN &&
            action != android.view.MotionEvent.ACTION_POINTER_DOWN) {
            return false
        }
        /* Counted BEFORE the geometry check, so a zero here means the
         * listener is never called and a non-zero here with zero hits means
         * it is called and the rectangles are wrong. */
        val stamped = event.eventTime
        val delay = android.os.SystemClock.uptimeMillis() - stamped
        if (delay in 0..2000) {
            fastDispatchSum.addAndGet(delay)
            while (true) {
                val worst = fastDispatchWorst.get()
                if (delay <= worst || fastDispatchWorst.compareAndSet(worst, delay)) break
            }
        }
        fastTouches.incrementAndGet()
        val pads = fastPads
        if (pads.isEmpty()) return false
        /* Ask for unbuffered dispatch for the rest of this gesture. Android
         * batches motion events to vsync by default; opting out saves up to
         * a frame on everything after the press, which is what a roll made
         * of many quick contacts is. */
        if (action == android.view.MotionEvent.ACTION_DOWN) {
            try { view.requestUnbufferedDispatch(event) } catch (ignored: Throwable) {}
        }
        val width = fastViewportWidth
        val viewWidth = view.width.toFloat()
        if (width <= 0f || viewWidth <= 0f) return false
        /* CSS pixels per device pixel, taken from the WebView's own width
         * rather than devicePixelRatio - the two part company the moment
         * anything zooms the page, and a stale ratio aims every pad wrong. */
        val scale = width / viewWidth
        val index = event.actionIndex
        val x = event.getX(index) * scale
        val y = event.getY(index) * scale
        for (pad in pads) {
            if (x < pad.left || x >= pad.right || y < pad.top || y >= pad.bottom) continue
            /* The same rule the page applies: strike high on the pad for
             * loud. Duplicated rather than asked for, because asking would
             * mean a round trip into the renderer and that round trip is
             * the thing being avoided. It is pinned by the page's own
             * velocityFrom(), and the two must not drift apart. */
            val velocity = if (pad.full) 1.0 else {
                val height = (pad.bottom - pad.top).coerceAtLeast(1f)
                (1.0 - ((y - pad.top) / height) * 0.75).coerceIn(0.25, 1.0)
            }
            val voiceId = PineSampler.fire(
                pad.padId,
                FireOptions(
                    velocity = velocity,
                    gate = pad.gate,
                    pitch = if (pad.pitch > 0.0) pad.pitch else null
                )
            )
            fastHits.incrementAndGet()
            if (voiceId.isNotEmpty()) {
                fastClaims[pad.padId] = Pair(voiceId, android.os.SystemClock.uptimeMillis())
            }
            break
        }
        return false
    }

    companion object {
        /** How long a fast-path claim stays collectable, in milliseconds. */
        private const val FAST_CLAIM_MS = 250L

        /** The name the shim reaches this class by. */
        const val INTERFACE_NAME = "PineSamplerNative"

        /**
         * 96 KB of clip per call, which is 128 KB of base64. Comfortably
         * inside what a `@JavascriptInterface` string argument will carry,
         * and few enough calls that a sixty second line crosses in single
         * figures of them.
         */
        const val CHUNK_BYTES = 96 * 1024

        /**
         * Install the bridge and the shim on a WebView.
         *
         * The shim MUST be evaluated before the page's own scripts run, or
         * sampler-engine.js will get there first and the tablet will quietly
         * be running Web Audio - which works, sounds fine, and is far too
         * slow to play. The androidx.webkit document-start hook is the
         * reliable way; `onPageStarted` is the fallback where that feature is
         * unavailable.
         */
        fun install(webView: WebView, bridge: PineSamplerBridge) {
            webView.addJavascriptInterface(bridge, INTERFACE_NAME)
            /* The native press path. See the block above onWebViewTouch for
             * the measurement that put it here.
             *
             * The listener NEVER returns true, so the WebView still receives
             * every event and the page is unchanged as far as it can tell.
             *
             * ONE FRAGILITY WORTH WRITING DOWN: a View has room for exactly
             * one OnTouchListener, so anything else that sets one on this
             * WebView later silently replaces this. The failure is benign -
             * the fast path stops claiming, the page fires for itself, and
             * the instrument is merely back to being late - but it is silent,
             * and the place to look is here. */
            webView.setOnTouchListener { view, event ->
                bridge.onWebViewTouch(view, event)
                false
            }
        }

        /**
         * window.pineSampler, defined in terms of the bridge above.
         *
         * Evaluate this at document start. It is idempotent: loading it twice
         * leaves the first copy in place, and its pending-promise table with
         * it.
         */
        val SHIM_JS: String = """
(function (root) {
  "use strict";
  if (root.pineSampler && root.pineSampler.backend === "oboe") return;
  var native = root.PineSamplerNative;
  /* No bridge, or a build with no engine compiled in: stand aside and let
   * sampler-engine.js define window.pineSampler in Web Audio. Slow beats
   * silent. */
  if (!native || !native.engineAvailable()) return;

  /* Promises waiting on a decode, by request id. */
  var waiting = Object.create(null);
  root.__pineSamplerSettle = function (request, ok, payload) {
    var entry = waiting[request];
    if (!entry) return;
    delete waiting[request];
    if (ok) entry.resolve(payload);
    else entry.reject(new Error((payload && payload.error) || "That sample would not load."));
  };

  /* Kotlin interpolates CHUNK_BYTES in here, so the two sides cannot
   * disagree about how big a piece is. */
  var CHUNK = $CHUNK_BYTES;

  function toBase64(bytes) {
    var binary = "";
    var step = 8192;
    for (var i = 0; i < bytes.length; i += step) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
    }
    return root.btoa(binary);
  }

  /* JSON.stringify drops keys whose value is undefined, and the engine's
   * semantics turn on whether a key was THERE. sampler.js passes
   * {pitch: undefined} when 16 Level is off, meaning "use the pad's tune";
   * left alone, that would cross the bridge as an absent pitch - which is
   * the same thing here, but only by luck. Normalising explicitly means the
   * two engines cannot drift apart over it. */
  function options(source) {
    var out = {};
    if (!source) return out;
    if ("velocity" in source && source.velocity !== undefined) out.velocity = Number(source.velocity);
    if ("pitch" in source && source.pitch !== undefined) out.pitch = Number(source.pitch);
    if ("loop" in source && source.loop !== undefined) out.loop = !!source.loop;
    if (source.gate) out.gate = true;
    return out;
  }

  function patch(source) {
    var out = {};
    if (!source) return out;
    if ("gain" in source) out.gain = Number(source.gain);
    if ("pitch" in source) out.pitch = Number(source.pitch);
    if ("pan" in source) out.pan = Number(source.pan);
    if ("loop" in source) out.loop = !!source.loop;
    if ("reverse" in source) out.reverse = !!source.reverse;
    if ("choke" in source) out.choke = String(source.choke || "");
    if ("trim" in source) {
      out.trim = source.trim
        ? { start: Number(source.trim.start) || 0, end: Number(source.trim.end) || 0 }
        : null;
    }
    return out;
  }

  var engine = {
    backend: "oboe",

    warm: function () { return native.warm(); },
    ready: function () { return native.ready(); },
    /* Hand the output back. The station cannot sound on this tablet while
     * the low-latency stream is held - see the note on native sleep(). */
    sleep: function () { native.sleep(); },
    setPolyphonic: function (on) { native.setPolyphonic(!!on); },
    isPolyphonic: function () { return native.isPolyphonic(); },

    load: function (padId, bytesOrUrl) {
      return Promise.resolve().then(function () {
        if (typeof bytesOrUrl === "string") {
          return fetch(bytesOrUrl).then(function (response) {
            if (!response.ok) throw new Error("Could not fetch that sample (HTTP " + response.status + ").");
            return response.arrayBuffer();
          });
        }
        return bytesOrUrl;
      }).then(function (bytes) {
        if (bytes instanceof Uint8Array) bytes = bytes.buffer;
        if (!(bytes instanceof ArrayBuffer)) throw new Error("A pad needs bytes or a URL.");
        if (!bytes.byteLength) throw new Error("That sample was empty.");
        var view = new Uint8Array(bytes);
        var token = native.beginLoad();
        for (var at = 0; at < view.length; at += CHUNK) {
          if (!native.pushChunk(token, toBase64(view.subarray(at, at + CHUNK)))) {
            native.abortLoad(token);
            throw new Error("That sample did not survive the trip to the engine.");
          }
        }
        var request = native.finishLoad(token, String(padId));
        return new Promise(function (resolve, reject) {
          waiting[request] = { resolve: resolve, reject: reject };
        });
      });
    },

    copy: function (from, to) { return native.copy(String(from), String(to)); },
    unload: function (padId) { return native.unload(String(padId)); },
    clear: function () { return native.clear(); },
    loaded: function (padId) { return native.loaded(String(padId)); },
    seconds: function (padId) { return native.seconds(String(padId)); },

    peaks: function (padId, buckets) {
      return JSON.parse(native.peaks(String(padId), buckets === undefined ? 512 : (buckets | 0)));
    },

    zeroCross: function (padId, seconds, withinMs) {
      return native.zeroCross(String(padId), Number(seconds),
        withinMs === undefined ? 30 : Number(withinMs));
    },

    set: function (padId, values) {
      return JSON.parse(native.set(String(padId), JSON.stringify(patch(values))));
    },

    get: function (padId) { return JSON.parse(native.get(String(padId))); },

    fire: function (padId, values) {
      return native.fire(String(padId), JSON.stringify(options(values)));
    },

    release: function (voiceId) { native.release(String(voiceId)); },
    stopPad: function (padId) { native.stopPad(String(padId)); },
    stopAll: function () { native.stopAll(); },

    /* Not on the Web Audio engine, where sampler.js computes the ratio
     * itself. Exposed here so the tablet plays the ratio the engine tested
     * rather than a second copy of the formula. */
    sixteenLevelPitch: function (padIndex) { return native.sixteenLevelPitch(padIndex | 0); },

    footprint: function () { return JSON.parse(native.footprint()); },
    levels: function () { return JSON.parse(native.levels()); },

    /* Clear the fire-to-sound counters and put the buffer back to its
     * opening size. The Web Audio engine has no equivalent and does not
     * define it, so a caller checks for it rather than assuming it. */
    retune: function () { native.retune(); },

    /* THE NATIVE PRESS PATH. setFastPads publishes where the pads are so a
     * touch can be turned into a voice below the WebView; claimFire hands
     * back the voice a press already started, so the page adopts it instead
     * of firing a second one. Neither exists in the Web Audio engine, and
     * the page checks for them rather than assuming them. */
    setFastPads: function (spec) { native.setFastPads(JSON.stringify(spec)); },
    claimFire: function (padId) { return native.claimFire(String(padId)); },
    /* What the native press path has seen: how many pads it knows about,
     * how many touches reached it, how many landed on a pad, and how many
     * of those the page went on to adopt. */
    fastState: function () { return JSON.parse(native.fastState()); },

    /* The engine's monotonic clock, in MILLISECONDS as a float, so it can
     * be subtracted from a performance.now() reading taken beside it. The
     * bridge hands it over as a string of nanoseconds because a JavaScript
     * number cannot hold them. */
    nowMs: function () { return Number(native.nowNanos()) / 1e6; }
  };

  root.pineSampler = engine;
})(window);
"""
    }
}
