package fm.pinebox.kiosk.audio

/**
 * The shapes the sampler's surface is spoken in.
 *
 * Every one of these has a JavaScript counterpart in
 * desktop/renderer/sampler-engine.js, and the field names match on purpose:
 * the WebView bridge turns these into the same JSON the Web Audio engine
 * returns, so the shared sampler UI cannot tell which engine is underneath.
 */

/**
 * A pad setting patch. `null` means "this call does not mention that field",
 * which is NOT the same as setting it to a default - a `set()` that says
 * nothing about loop must not turn loop off. JavaScript expresses that with
 * the `in` operator; Kotlin expresses it with nullability, and the JNI layer
 * expresses it with a bitmask.
 */
data class PadPatch(
    val gain: Double? = null,
    val pitch: Double? = null,
    /** -1 hard left, 0 centre, +1 hard right. Absent leaves it alone. */
    val pan: Double? = null,
    val loop: Boolean? = null,
    val reverse: Boolean? = null,
    val choke: String? = null,
    /** Present-but-null clears the trim; absent leaves it alone. */
    val trim: Trim? = null,
    val trimMentioned: Boolean = trim != null
)

/** Seconds into the FORWARD sample, however the pad plays it. */
data class Trim(val start: Double, val end: Double)

/** What a pad is set to right now. The JS `get()` returns this shape. */
data class PadState(
    val id: String,
    val gain: Double,
    val pitch: Double,
    val pan: Double,
    val loop: Boolean,
    val reverse: Boolean,
    val trim: Trim?,
    val choke: String,
    val seconds: Double
)

/**
 * One press.
 *
 * `velocity`, `pitch` and `loop` are nullable for the same reason PadPatch's
 * fields are: an absent pitch uses the pad's own Tune, and a present one
 * replaces it for this hit only. 16 Level and Note Repeat both depend on the
 * difference.
 */
data class FireOptions(
    val velocity: Double? = null,
    val pitch: Double? = null,
    val loop: Boolean? = null,
    /** Hold until release() rather than stopping at the end of the window. */
    val gate: Boolean = false
)

/** What load() reports back about the sample it decoded. */
data class LoadResult(val seconds: Double, val rate: Int, val channels: Int)

/**
 * What the loaded pads cost in memory.
 *
 * MEASURED: a booth line off this station ran 62.97 s, which decodes to about
 * twelve megabytes at 48 kHz - not the fraction of a megabyte its 596 KB mp3
 * suggests. Sixteen of those is a quarter of a gigabyte, on a tablet. Buffers
 * shared by [PineSampler.copy] are counted ONCE, or the reading would be
 * sixteen times the truth for a chopped bank.
 */
data class Footprint(val bytes: Long, val pads: Int, val buffers: Int) {
    val megabytes: Double get() = bytes / (1024.0 * 1024.0)
}

/** What is ringing, and what the platform admits about its own latency. */
data class Levels(
    val voices: Int,
    val pads: Map<String, Int>,
    /** "closed", "suspended" or "running" - the Web Audio context's words. */
    val state: String,
    /**
     * One burst, in seconds. What the PLATFORM admits to.
     *
     * The real tap-to-sound figure is measured on the physical tablet with a
     * recorder and a finger. It is never reported from here as if it were,
     * because it is not: this number leaves out the touch stack, the UI
     * thread and the speaker.
     */
    val baseLatency: Double,
    val outputLatency: Double,
    /** Where a concurrently playing stream should be right now, 0..1. */
    val duckGain: Float,
    /** What the output stream turned out to be. See [StreamFacts]. */
    val stream: StreamFacts = StreamFacts(),
    /** The measured fire-to-sound reading. See [StartLatency]. */
    val start: StartLatency = StartLatency()
)

/**
 * What the platform's output stream actually gave us, as opposed to what was
 * asked for.
 *
 * Every one of these was invisible until it was reported, and each answers a
 * question the ear will otherwise ask with no way to settle it: did the
 * exclusive port get granted or was it quietly downgraded to shared, how big
 * did the buffer end up after tuning, and how many times has it run dry.
 *
 * [timestampLatency] is worth a note. It comes from the stream's own
 * timestamp, not from its buffer size, so a ZERO here does not mean a fast
 * stream - it means a stream the platform declines to timestamp, which in
 * practice is the legacy path rather than MMAP.
 */
data class StreamFacts(
    val burstFrames: Int = 0,
    val bufferFrames: Int = 0,
    val capacityFrames: Int = 0,
    val xruns: Int = 0,
    val exclusive: Boolean = false,
    /**
     * Whether this stream got the MMAP data path.
     *
     * False is not a bug and not a setting: MMAP support is an OEM decision
     * baked into the audio HAL and the ALSA driver, and it is often absent
     * on lower-end parts. Without it AAudio still works, over the legacy
     * path, and the legacy path is where the rest of the latency lives.
     */
    val mmap: Boolean = false,
    /** "none", "opensles" or "aaudio". */
    val api: String = "none",
    val timestampLatency: Double = 0.0
)

/**
 * The fire-to-sound reading, in milliseconds, MEASURED rather than derived.
 *
 * A monotonic clock is stamped inside fire() and read again on the audio
 * thread in the first block that actually gives that voice a sample. So this
 * is the part of the chain the engine owns - press lands in the engine, to
 * the audio block carrying it.
 *
 * It is NOT the tap-to-sound figure and must never be reported as one. It
 * leaves out the finger-to-digitizer time, the input stack's trip through
 * the WebView, and the presentation delay between the block and the speaker
 * ([StreamFacts.timestampLatency] is that last one). Those are measured on
 * the device, separately, and added up by whoever is quoting a number.
 */
data class StartLatency(
    val lastMs: Double = 0.0,
    val worstMs: Double = 0.0,
    val count: Int = 0,
    val meanMs: Double = 0.0
)
