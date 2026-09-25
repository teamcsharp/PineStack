package fm.pinebox.kiosk.audio

import android.content.Context
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * window.pineSampler, in Kotlin.
 *
 * THIS IS A SEAM, NOT A FEATURE. The sampler UI - which is a web page, and
 * which ships unchanged on the desktop terminal and on this tablet - talks to
 * nothing but the surface below. On the desktop that surface is implemented
 * in Web Audio; here it is implemented in C++ on Oboe, because a WebView
 * audio path will not hold "tap the pad and it plays with no delay" on a
 * mid-range MediaTek.
 *
 * The rules, which are the same rules the Web Audio engine follows:
 *
 *  - Every sample is decoded ONCE, on load, and held resident. Nothing is
 *    decoded on the press; that is the whole point of downloading the clip.
 *  - Every start and every stop rides a short envelope. A raw start or stop
 *    at a non-zero sample is an audible click, and a sampler that clicks is
 *    a toy.
 *  - A voice is never left dangling: a one-shot that finishes on its own
 *    frees its slot by the same door a released gate does.
 *
 * THREADING. [load] decodes, which is tens to hundreds of milliseconds of
 * MediaCodec, so it never runs on the UI thread - use [load] with a callback
 * or [loadBlocking] from a worker. Everything else is cheap enough to call
 * from wherever the touch handler lives; [fire] in particular does no
 * allocation of audio and never waits on the audio thread.
 */
object PineSampler {

    /* set() presence bits. Must match jni_bridge.cpp. */
    private const val SET_GAIN = 1 shl 0
    private const val SET_PITCH = 1 shl 1
    private const val SET_LOOP = 1 shl 2
    private const val SET_REVERSE = 1 shl 3
    private const val SET_CHOKE = 1 shl 4
    private const val SET_TRIM = 1 shl 5
    private const val SET_PAN = 1 shl 6

    /* fire() presence bits. */
    private const val FIRE_VELOCITY = 1 shl 0
    private const val FIRE_PITCH = 1 shl 1
    private const val FIRE_LOOP = 1 shl 2

    /** What levels().state reports, in the Web Audio context's own words. */
    private val STATES = arrayOf("closed", "suspended", "running")

    /** Index 10 of nativeLevels. Matches the api field in engine.h. */
    private val APIS = arrayOf("none", "opensles", "aaudio")

    /** How many doubles nativeLevels returns; see its comment in jni_bridge.cpp. */
    private const val LEVEL_FIELDS = 17

    private var handle: Long = 0L
    private var scratchDir: String = ""
    private val started = AtomicBoolean(false)

    /** Decoding happens here, one clip at a time, off every thread that matters. */
    private val decoders = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "pinebox-sampler-decode").apply { isDaemon = true }
    }

    private var duck: DuckController? = null

    /** "oboe" here, "webaudio" on the desktop. The UI may report it; it must not branch on it. */
    const val BACKEND = "oboe"

    /**
     * The .so is loaded through com.pinebox.kiosk.audio.NativeAudio, which is
     * the app's ONE place the library name is written down and which already
     * swallows the UnsatisfiedLinkError a build made without the engine
     * throws. This class lives in fm.pinebox.kiosk.audio rather than the
     * app's own package because JNI resolves by CLASS package: the exports in
     * jni_bridge.cpp are Java_fm_pinebox_kiosk_audio_PineSampler_*, and a
     * class in a different package would link at load and fail at first call.
     *
     * The reflection is deliberate: this file must not have a compile-time
     * dependency on the surrounding app, so that the engine's Kotlin half can
     * be dropped into a different host unchanged.
     */
    private val loaded: Boolean by lazy {
        try {
            val holder = Class.forName("com.pinebox.kiosk.audio.NativeAudio")
            val instance = holder.getField("INSTANCE").get(null)
            holder.getMethod("ensureLoaded").invoke(instance) as Boolean
        } catch (ignored: Throwable) {
            try {
                System.loadLibrary("pinebox_sampler")
                true
            } catch (error: UnsatisfiedLinkError) {
                false
            }
        }
    }

    /** False on a build with no engine in it; the caller falls back to the page's own audio. */
    fun available(): Boolean = loaded

    // ---------------------------------------------------------------- life --

    /**
     * Build the engine. Cheap: it allocates the voice table and nothing else.
     * The audio stream is not opened until [warm].
     */
    @Synchronized
    fun attach(context: Context): Boolean {
        if (handle != 0L) return true
        if (!loaded) return false
        scratchDir = context.cacheDir.absolutePath
        handle = nativeCreate()
        duck = DuckController(context.applicationContext)
        return true
    }

    /**
     * Open the stream, from a real gesture.
     *
     * Opening AAudio's exclusive path costs a few milliseconds; paying for it
     * on the first press is exactly the delay this engine exists to avoid.
     * Call it when the sampler page becomes visible, not when the first pad
     * is tapped.
     */
    @Synchronized
    fun warm(): Boolean {
        if (handle == 0L) return false
        val ok = nativeStart(handle)
        started.set(ok)
        return ok
    }

    /** Whether [attach] has built an engine. */
    fun attached(): Boolean = handle != 0L

    fun ready(): Boolean = handle != 0L && nativeRunning(handle)

    /** Give the stream back - another app wants the exclusive port, or we are backgrounded. */
    @Synchronized
    fun sleep() {
        if (handle == 0L) return
        nativeStopAll(handle)
        nativeStop(handle)
        started.set(false)
        duck?.release()
    }

    @Synchronized
    fun detach() {
        if (handle == 0L) return
        nativeDestroy(handle)
        handle = 0L
        duck?.release()
        duck = null
    }

    fun setPolyphonic(on: Boolean) {
        if (handle != 0L) nativeSetPolyphonic(handle, on)
    }

    fun isPolyphonic(): Boolean = handle != 0L && nativeIsPolyphonic(handle)

    // ------------------------------------------------------------- loading --

    /**
     * Decode a clip and hold it on [padId]. Blocks; call it from a worker.
     *
     * The bytes may be mp3, wav, ogg, m4a or flac - the format is SNIFFED
     * from the bytes, never taken from a Content-Type or a file name, because
     * the station has served the wrong one before.
     *
     * Returns null on failure and leaves the reason in [lastError].
     */
    fun loadBlocking(padId: String, bytes: ByteArray): LoadResult? {
        if (handle == 0L) return null
        val got = nativeLoad(handle, padId, bytes, scratchDir) ?: return null
        return LoadResult(got[0], got[1].toInt(), got[2].toInt())
    }

    /** The same, off the caller's thread. [done] runs on the decode thread. */
    fun load(padId: String, bytes: ByteArray, done: (LoadResult?, String?) -> Unit) {
        decoders.execute {
            val result = loadBlocking(padId, bytes)
            done(result, if (result == null) lastError() else null)
        }
    }

    fun lastError(): String = if (handle == 0L) "" else nativeLastError(handle)

    /**
     * Share one decoded buffer with another pad.
     *
     * Chop needs the same thirty seconds of air on all sixteen pads with
     * sixteen different windows. Decoding it sixteen times would be sixteen
     * times the memory and the wait, for identical samples; the buffer is
     * immutable once decoded, so sharing the reference is safe and only the
     * per-pad trim differs.
     */
    fun copy(from: String, to: String): Boolean =
        handle != 0L && nativeCopy(handle, from, to)

    fun unload(padId: String): Boolean = handle != 0L && nativeUnload(handle, padId)

    /**
     * Drop every pad. Handing the instrument to a different set of templates
     * must not leave a quarter of a gigabyte of decoded audio resident behind
     * the new layout.
     */
    fun clear(): Boolean {
        if (handle == 0L) return false
        nativeClear(handle)
        return true
    }

    fun loaded(padId: String): Boolean = handle != 0L && nativeLoaded(handle, padId)

    fun seconds(padId: String): Double = if (handle == 0L) 0.0 else nativeSeconds(handle, padId)

    /** A mono peak envelope for the waveform view, at the asked-for resolution. */
    fun peaks(padId: String, buckets: Int = 512): FloatArray =
        if (handle == 0L) FloatArray(0) else nativePeaks(handle, padId, buckets)

    /**
     * The nearest point to [seconds] where the waveform crosses zero.
     *
     * Trimming anywhere else leaves a step in the signal, and a step is a
     * click. The search is bounded, so a pad of solid tone - which may have
     * no crossing nearby - simply keeps the handle where it was put.
     */
    fun zeroCross(padId: String, seconds: Double, withinMs: Double = 30.0): Double =
        if (handle == 0L) seconds else nativeZeroCross(handle, padId, seconds, withinMs)

    // ------------------------------------------------------------ settings --

    fun set(padId: String, patch: PadPatch) {
        if (handle == 0L) return
        var mask = 0
        if (patch.gain != null) mask = mask or SET_GAIN
        if (patch.pitch != null) mask = mask or SET_PITCH
        if (patch.pan != null) mask = mask or SET_PAN
        if (patch.loop != null) mask = mask or SET_LOOP
        if (patch.reverse != null) mask = mask or SET_REVERSE
        if (patch.choke != null) mask = mask or SET_CHOKE
        if (patch.trimMentioned) mask = mask or SET_TRIM
        nativeSet(
            handle, padId, mask,
            patch.gain ?: 1.0,
            patch.pitch ?: 1.0,
            patch.loop ?: false,
            patch.reverse ?: false,
            patch.choke ?: "",
            patch.trim != null,
            patch.trim?.start ?: 0.0,
            patch.trim?.end ?: 0.0,
            patch.pan ?: 0.0
        )
    }

    /** Null for a pad nothing has ever touched, matching the JS get(). */
    fun get(padId: String): PadState? {
        if (handle == 0L) return null
        val values = nativeGet(handle, padId) ?: return null
        return PadState(
            id = padId,
            gain = values[0],
            pitch = values[1],
            loop = values[2] != 0.0,
            reverse = values[3] != 0.0,
            trim = if (values[4] != 0.0) Trim(values[5], values[6]) else null,
            choke = nativeChoke(handle, padId),
            seconds = values[7],
            /* APPENDED at index 8 - see the note in jni_bridge.cpp. An older
             * library that predates pan returns eight, so this asks rather
             * than indexes blind: a crash here would be a pad editor that
             * cannot open. */
            pan = if (values.size > 8) values[8] else 0.0
        )
    }

    // ------------------------------------------------------------- playing --

    /**
     * THE PRESS. Returns a voice id, or "" if the pad is empty.
     *
     * Nothing in here decodes, allocates a sample or waits on the audio
     * thread. It works out a window and publishes a voice slot, and the next
     * audio callback picks it up.
     */
    fun fire(padId: String, options: FireOptions = FireOptions()): String {
        if (handle == 0L) return ""
        var mask = 0
        if (options.velocity != null) mask = mask or FIRE_VELOCITY
        if (options.pitch != null) mask = mask or FIRE_PITCH
        if (options.loop != null) mask = mask or FIRE_LOOP
        val voice = nativeFire(
            handle, padId, mask,
            options.velocity ?: 1.0,
            options.pitch ?: 1.0,
            options.loop ?: false,
            options.gate
        )
        if (voice.isNotEmpty()) duck?.onVoiceStarted()
        return voice
    }

    /**
     * 16 Level: one sample across all sixteen pads, played chromatically.
     *
     * Pad index 0..15 maps to -8..+7 semitones, so pad 8 plays the sample as
     * it was recorded. This tunes the HIT, not the pad - the pad's own Tune
     * setting does not move, which is what lets the operator drop out of 16
     * Level and find the instrument where they left it.
     */
    fun sixteenLevelPitch(padIndex: Int): Double = nativeSixteenPitch(padIndex)

    /** The convenience the grid actually uses. */
    fun fireSixteenLevel(padId: String, padIndex: Int, options: FireOptions = FireOptions()): String =
        fire(padId, options.copy(pitch = sixteenLevelPitch(padIndex)))

    fun release(voiceId: String) {
        if (handle != 0L) nativeRelease(handle, voiceId)
    }

    fun stopPad(padId: String) {
        if (handle != 0L) nativeStopPad(handle, padId)
    }

    fun stopAll() {
        if (handle != 0L) nativeStopAll(handle)
    }

    // ----------------------------------------------------------- metering ---

    fun footprint(): Footprint {
        if (handle == 0L) return Footprint(0, 0, 0)
        val values = nativeFootprint(handle)
        return Footprint(values[0], values[1].toInt(), values[2].toInt())
    }

    fun levels(): Levels {
        if (handle == 0L) return Levels(0, emptyMap(), "closed", 0.0, 0.0, 1f)
        val values = nativeLevels(handle)
        /* The array grew when the stream facts and the fire-to-sound reading
         * were added to it. An old .so paired with new Kotlin would index off
         * the end and take the whole panel down over a METER READING, which
         * is not a thing worth crashing for. */
        if (values.size < LEVEL_FIELDS) {
            return Levels(0, emptyMap(), "closed", 0.0, 0.0, 1f)
        }
        val perPad = HashMap<String, Int>()
        for (entry in nativeLevelPads(handle)) {
            /* "<count>:<padId>". The count is first so a pad key that itself
             * contains a colon - bank keys look like "b1:7" - still splits
             * cleanly on the FIRST one. */
            val split = entry.indexOf(':')
            if (split <= 0) continue
            val count = entry.substring(0, split).toIntOrNull() ?: continue
            perPad[entry.substring(split + 1)] = count
        }
        val stateIndex = values[0].toInt().coerceIn(0, STATES.size - 1)
        return Levels(
            voices = values[3].toInt(),
            pads = perPad,
            state = STATES[stateIndex],
            baseLatency = values[1],
            outputLatency = values[2],
            duckGain = values[4].toFloat(),
            stream = StreamFacts(
                burstFrames = values[5].toInt(),
                bufferFrames = values[6].toInt(),
                capacityFrames = values[7].toInt(),
                xruns = values[8].toInt(),
                exclusive = values[9] >= 0.5,
                mmap = values[16] >= 0.5,
                api = APIS.getOrElse(values[10].toInt()) { "none" },
                timestampLatency = values[11]
            ),
            start = StartLatency(
                lastMs = values[12],
                worstMs = values[13],
                count = values[14].toInt(),
                meanMs = values[15]
            )
        )
    }

    /**
     * Clear the fire-to-sound counters and put the buffer back to the two
     * bursts it opens with, letting the tuner argue it up again from there.
     *
     * This is what a measuring run calls first. Without it every reading is
     * contaminated by whatever the last hour of underruns left the buffer
     * at, which is exactly the mistake that makes a "before" number look
     * like an "after" one.
     */
    fun retune() {
        if (handle != 0L) nativeRetune(handle)
    }

    /**
     * The engine's own monotonic clock, in nanoseconds.
     *
     * The fire-to-sound reading is stamped against this clock, and the page
     * times itself with performance.now(), which counts from a different
     * zero. Reading both next to each other is what puts the two halves of
     * the chain on one timeline rather than assuming they meet.
     */
    fun nowNanos(): Long = if (available()) nativeNowNanos() else 0L

    /** Where a concurrently playing stream should be right now, 0..1. */
    fun duckGain(): Float = if (handle == 0L) 1f else nativeDuckGain(handle)

    /** 1.0 turns ducking off - an operator on headphones may want the mix untouched. */
    fun setDuckDepth(depth: Float) {
        if (handle != 0L) nativeSetDuckDepth(handle, depth)
    }

    /** Where the host hangs its own player, so a pad hit can push it down. */
    fun onDuck(listener: ((Float) -> Unit)?) {
        duck?.listener = listener
    }

    // ---------------------------------------------------------------- jni ---

    private external fun nativeCreate(): Long
    private external fun nativeDestroy(handle: Long)
    private external fun nativeStart(handle: Long): Boolean
    private external fun nativeStop(handle: Long)
    private external fun nativeRunning(handle: Long): Boolean
    private external fun nativeLastError(handle: Long): String
    private external fun nativeSetPolyphonic(handle: Long, on: Boolean)
    private external fun nativeIsPolyphonic(handle: Long): Boolean
    private external fun nativeLoad(
        handle: Long, padId: String, bytes: ByteArray, scratchDir: String
    ): DoubleArray?
    private external fun nativeCopy(handle: Long, from: String, to: String): Boolean
    private external fun nativeUnload(handle: Long, padId: String): Boolean
    private external fun nativeClear(handle: Long)
    private external fun nativeLoaded(handle: Long, padId: String): Boolean
    private external fun nativeSeconds(handle: Long, padId: String): Double
    private external fun nativePeaks(handle: Long, padId: String, buckets: Int): FloatArray
    private external fun nativeZeroCross(
        handle: Long, padId: String, seconds: Double, withinMs: Double
    ): Double
    private external fun nativeSet(
        handle: Long, padId: String, mask: Int, gain: Double, pitch: Double,
        loop: Boolean, reverse: Boolean, choke: String,
        trimSet: Boolean, trimStart: Double, trimEnd: Double, pan: Double
    )
    private external fun nativeGet(handle: Long, padId: String): DoubleArray?
    private external fun nativeChoke(handle: Long, padId: String): String
    private external fun nativeFire(
        handle: Long, padId: String, mask: Int, velocity: Double, pitch: Double,
        loop: Boolean, gate: Boolean
    ): String
    private external fun nativeRelease(handle: Long, voiceId: String)
    private external fun nativeStopPad(handle: Long, padId: String)
    private external fun nativeStopAll(handle: Long)
    private external fun nativeFootprint(handle: Long): LongArray
    private external fun nativeLevels(handle: Long): DoubleArray
    private external fun nativeRetune(handle: Long)
    private external fun nativeNowNanos(): Long
    private external fun nativeLevelPads(handle: Long): Array<String>
    private external fun nativeDuckGain(handle: Long): Float
    private external fun nativeSetDuckDepth(handle: Long, depth: Float)
    private external fun nativeSixteenPitch(padIndex: Int): Double
}
