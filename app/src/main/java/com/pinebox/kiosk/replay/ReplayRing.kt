package com.pinebox.kiosk.replay

import android.media.MediaCodec
import android.media.MediaFormat
import android.media.MediaMuxer
import java.io.File
import java.nio.ByteBuffer
import org.json.JSONObject

/**
 * THE LAST HALF-MINUTE, ALWAYS.
 *
 * "Always have the application saving the last thirty seconds of activity...
 *  I just want it recording the tablet in general with a rolling history that
 *  I'm able to always extract."
 *
 * 2026-09-14, and then twenty minutes of it: "I want to save anywhere from
 * the last five seconds to the last 20 minutes. So the tablet should always
 * be recording." The ring's shape did not change for that; its size did -
 * the arithmetic is in ScreenReplay's header and in size() below.
 *
 * A ring of ENCODED frames, not of pictures and not of files.
 *
 *   - not pictures, because a minute of 1340x800 raw frames is gigabytes and
 *     this tablet has 4 GB with 148 MB free on a bad day. The encoder is
 *     already running; what comes out of it is a few megabytes a minute.
 *   - not files, because a ring of mp4 segments has to be stitched on the way
 *     out, and stitching mp4 means either re-muxing anyway or accepting a cut
 *     on a segment boundary rather than where the operator asked. Holding the
 *     packets means the file is written once, at the moment it is wanted, and
 *     starts exactly where it should.
 *
 * NOTHING TOUCHES THE DISK UNTIL IT IS ASKED FOR. A terminal that writes a
 * rolling recording to flash all day is a terminal whose flash wears out, and
 * the overwhelming majority of those bytes are of no interest to anyone.
 *
 * THE CUT MUST START ON A SYNC FRAME. H.264 frames refer backwards, so a file
 * that begins mid-GOP decodes as garbage until the next keyframe - which is
 * how a replay buffer produces "the first two seconds are a grey smear". The
 * search below walks back to the sync frame at or before the wanted moment,
 * which is why the encoder is asked for a keyframe every second: a longer
 * interval would be cheaper and would make the start of the clip vaguer.
 */
class ReplayRing(private val holdSeconds: Int = 60) {

    private companion object {
        /** The gap written where the screen was dark - see joinClock(). */
        const val FRAME_GAP_US = 100_000L
    }

    /** One encoded packet's place in the blob. */
    private class Mark(
        var at: Int = 0,
        var size: Int = 0,
        var flags: Int = 0,
        var timeUs: Long = 0,
    )

    /* Sized from the bitrate rather than guessed: whatever the encoder is
     * told to produce, a second of it is bitrate/8 bytes, and a quarter more
     * absorbs the peaks a screen full of motion produces. */
    private var blob: ByteArray = ByteArray(0)
    private var marks: Array<Mark> = emptyArray()
    /* THE CLOCK JOIN - see joinClock(). `continueAfter` is where the held
     * packets end, `shift` is what is added to a new encoder's timestamps to
     * land after them, and `based` says whether the first packet of this run
     * has been seen yet - which is what `shift` is worked out from. */
    private var continueAfter = 0L
    @Volatile private var shift = 0L
    @Volatile private var based = true
    private val audioGate = Any()
    private val audio = ReplayAudioWindow(24 * 1024 * 1024, holdSeconds * 60)
    private val pendingAudio = java.util.ArrayDeque<ReplayAudioPacket>()
    @Volatile private var audioFormat: MediaFormat? = null
    @Volatile var audioClockError: String? = null
        private set
    @Volatile var lastSavedAudio = JSONObject().put("present", false).put("state", "unavailable")
        private set

    private var head = 0          /* where the next packet is written */
    private var first = 0         /* the oldest packet still held */
    private var count = 0
    private var wrote = 0         /* bytes in use, for the state report */

    @Volatile
    var format: MediaFormat? = null
        private set

    /**
     * Make room for [bitrate], ONCE.
     *
     * Called on every start, and a start happens every time the screen comes
     * on - so this must not throw away what the ring is holding. stop() says
     * plainly that the ring is not cleared, "so the half-minute before the
     * tablet went to sleep is still there when it wakes"; re-allocating here
     * used to make a liar of it, and a save taken just after a restart
     * returned 8 seconds of a 30-second request.
     */
    @Synchronized
    fun size(bitrate: Int) {
        val bytes = (bitrate / 8) * holdSeconds * 5 / 4
        /* THE CEILING IS 100 MB, and it is a ceiling the design numbers
         * touch: 0.6 Mbit x 1200 s = 90 MB, and the quarter of headroom
         * would make it 112.5. The heap is largeHeap (512 MB on this
         * tablet) and this process was measured at 22 MB of Dalvik with
         * the old 15 MB ring in it, so 100 fits; 100 MB at 75 kB/s is
         * 1,398 s, which is the twenty minutes with a sixth to spare at
         * the design ceiling and far more on the mostly-static panel this
         * actually records. */
        val want = bytes.coerceIn(2 * 1024 * 1024, 100 * 1024 * 1024)
        if (blob.size == want && marks.isNotEmpty()) {
            /* Already the right shape: keep every packet in it. */
            joinClock()
            return
        }
        blob = ByteArray(want)
        /* A generous packet count: the encoder runs at 12 fps, so thirty a
         * second is two and a half times what a full hold needs, and
         * running out of marks would silently drop frames the ring has
         * room for. (It was sixty a second, sized for 30 fps and a one-
         * minute hold; at twenty minutes that is 72,000 objects for no
         * reason.) 36,000 marks is about 1.4 MB. */
        marks = Array(holdSeconds * 30) { Mark() }
        reset()
    }

    /**
     * JOIN A FRESH ENCODER'S CLOCK TO THE HELD PACKETS.
     *
     * A new encoder stamps from near zero. The packets already in the ring
     * end wherever they ended, so without this the two runs interleave into
     * nonsense: seconds() measures newest-minus-oldest and would report a
     * negative or absurd span, and save()'s walk back to a keyframe depends
     * on the timestamps rising.
     *
     * The offset is worked out from the FIRST packet of the new run rather
     * than assumed to be zero, because not every encoder starts at zero.
     * Whatever the screen was doing while it was dark is not recorded and
     * cannot be, so the join is a fixed small gap - the ring's time is
     * content time, and a cut is what the operator sees anyway.
     */
    @Synchronized
    private fun joinClock() {
        synchronized(audioGate) { pendingAudio.clear() }
        audioClockError = null
        if (count == 0) { shift = 0L; based = true; return }
        continueAfter = marks[(first + count - 1) % marks.size].timeUs
        based = false
    }

    /**
     * #1182T: GIVE THE BLOB BACK TO THE HEAP.
     *
     * reset() empties the ring but keeps its storage, which is right for every
     * caller it had: the ring is meant to be a fixed allocation that never
     * grows and never needs emptying. Standby needs the other thing. The blob
     * is sized from the design constants at up to 100 MB of Dalvik heap - the
     * largest single releasable object this process holds - and while another
     * app is in the foreground on a 4 GB tablet, holding it costs more than
     * the minutes in it are worth for that while.
     *
     * NOTHING IS LOST BY CALLING THIS, and that is a property of the CALLER
     * rather than of this method: ScreenReplay.release() writes the history to
     * disk first and primes it back in afterwards. Called on its own, this
     * does throw the held minutes away.
     *
     * `marks` is deliberately NOT dropped. It is about 1.4 MB against the
     * blob's ninety, and half the methods here index it modulo marks.size - an
     * empty array would turn a saving into an ArithmeticException on the next
     * frame that arrived. add() already refuses an empty blob, and that is
     * what makes leaving marks in place safe.
     */
    @Synchronized
    fun letGo() {
        reset()
        blob = ByteArray(0)
    }

    @Synchronized
    fun reset() {
        head = 0; first = 0; count = 0; wrote = 0
        continueAfter = 0L; shift = 0L; based = true
        audio.clear()
        synchronized(audioGate) { pendingAudio.clear() }
        audioFormat = null
        audioClockError = null
    }

    @Synchronized
    fun remember(fmt: MediaFormat) { format = fmt }

    fun rememberAudio(fmt: MediaFormat) { audioFormat = fmt }

    fun audioSeconds(): Double = audio.seconds()

    fun invalidateAudioClock(why: String) {
        audioClockError = why
        synchronized(audioGate) { pendingAudio.clear() }
    }

    /** Both encoders use CLOCK_MONOTONIC; a resumed session shares ONE shift. */
    fun addAudio(data: ByteBuffer, info: MediaCodec.BufferInfo, signal: Boolean? = null) {
        if (info.size <= 0 || info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0 || audioClockError != null) return
        val bytes = ByteArray(info.size)
        val copy = data.duplicate()
        copy.position(info.offset); copy.limit(info.offset + info.size); copy.get(bytes)
        val packet = ReplayAudioPacket(info.presentationTimeUs, bytes, info.flags, signal = signal)
        synchronized(audioGate) {
            if (!based) {
                // Wait for the video epoch; never independently zero audio.
                if (pendingAudio.size >= 128) pendingAudio.removeFirst()
                pendingAudio.addLast(packet)
            } else {
                audio.add(packet.copy(timeUs = packet.timeUs + shift))
            }
        }
    }

    /** Seconds currently held, which is what the operator is offered. */
    @Synchronized
    fun seconds(): Double {
        if (count < 2) return 0.0
        val oldest = marks[first].timeUs
        val newest = marks[(first + count - 1) % marks.size].timeUs
        return ((newest - oldest) / 1_000_000.0).coerceAtLeast(0.0)
    }

    @Synchronized
    fun bytes(): Int = wrote

    /**
     * Take one encoded packet. Oldest packets are dropped to make room, which
     * is the whole point: the ring never grows and never needs emptying.
     */
    @Synchronized
    fun add(data: ByteBuffer, info: MediaCodec.BufferInfo) {
        if (blob.isEmpty()) return
        val size = info.size
        if (size <= 0 || size > blob.size) return
        /* Codec config (SPS/PPS) rides in the MediaFormat, not the ring. */
        if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) return

        while (!fits(size) || count >= marks.size) {
            if (count == 0) return
            dropOldest()
        }

        if (head + size > blob.size) head = 0      /* wrap whole packets only */
        data.position(info.offset)
        data.limit(info.offset + size)
        data.get(blob, head, size)

        /* THE FIRST PACKET OF A RUN SETS THE OFFSET. A fresh encoder stamps
         * from near zero; the held packets end at `continueAfter`. The gap
         * stands in for however long the screen was dark. */
        synchronized(audioGate) {
            if (!based) {
                shift = continueAfter + FRAME_GAP_US - info.presentationTimeUs
                based = true
                while (pendingAudio.isNotEmpty()) {
                    val packet = pendingAudio.removeFirst()
                    audio.add(packet.copy(timeUs = packet.timeUs + shift))
                }
            }
        }

        val slot = (first + count) % marks.size
        marks[slot].at = head
        marks[slot].size = size
        marks[slot].flags = info.flags
        marks[slot].timeUs = info.presentationTimeUs + shift
        head += size
        count += 1
        wrote += size
    }

    /**
     * Is there room for [size] IN ONE PIECE?
     *
     * This used to add the free tail to the free front and answer with the
     * total, which is the sum of two places a single packet cannot span.
     * With 3 kB at the end and 2 kB at the start it said "5 kB free" for a
     * 5 kB packet, wrapped the head to zero, and wrote over the oldest
     * packets while their marks still claimed to describe them. The ring
     * then reported 95 seconds and 19.7 MB of a 60-second, 15 MB buffer, and
     * the oldest frames it handed out were the bytes of newer ones.
     *
     * A packet lands either at the head or, if the tail is too short,
     * wrapped to zero - so it fits if EITHER of those runs is long enough on
     * its own.
     */
    private fun fits(size: Int): Boolean {
        if (count == 0) return size <= blob.size
        val oldest = marks[first].at
        return if (head >= oldest) {
            /* At the head, or wrapped to the front - and wrapping is only
             * safe as far as the oldest packet still held. */
            blob.size - head >= size || oldest >= size
        } else {
            oldest - head >= size
        }
    }

    private fun dropOldest() {
        wrote -= marks[first].size
        first = (first + 1) % marks.size
        count -= 1
        if (count == 0) { head = 0; first = 0; wrote = 0 }
    }

    /**
     * FILL THE RING FROM A FILE IT WROTE EARLIER.
     *
     * MediaExtractor hands back the same samples, flags and timestamps the
     * encoder produced, so a restored cache is indistinguishable from
     * history the ring recorded itself - and the clock join then makes new
     * frames continue after it rather than interleaving with it.
     *
     * @return how many packets were taken in. Zero is not a failure: an
     *   empty or unreadable cache simply means there is no history from
     *   before the restart, which is a normal state on a first run.
     */
    @Synchronized
    fun load(from: File): Int {
        if (!from.exists() || from.length() <= 0L) return 0
        var taken = 0
        val pull = android.media.MediaExtractor()
        try {
            pull.setDataSource(from.absolutePath)
            var track = -1
            for (i in 0 until pull.trackCount) {
                val fmt = pull.getTrackFormat(i)
                if (fmt.getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true) {
                    track = i
                    /* The format has to come from the file: the encoder's
                     * csd-0/csd-1 live in it, and a muxer given a format
                     * without them writes an unplayable file. */
                    format = fmt
                    break
                }
            }
            if (track < 0) return 0
            pull.selectTrack(track)

            /* Sized before anything is taken in, or the first packet would
             * land in a zero-length blob and be dropped. */
            if (blob.isEmpty()) return 0

            val info = MediaCodec.BufferInfo()
            val room = java.nio.ByteBuffer.allocate(1 shl 20)
            while (true) {
                val size = pull.readSampleData(room, 0)
                if (size < 0) break
                info.offset = 0
                info.size = size
                info.presentationTimeUs = pull.sampleTime
                /* MediaExtractor reports sync frames with its own flag; the
                 * ring speaks MediaCodec's, and a packet that loses its
                 * keyframe flag can never be the start of a cut. */
                info.flags = if (pull.sampleFlags and
                        android.media.MediaExtractor.SAMPLE_FLAG_SYNC != 0)
                    MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                room.position(0)
                room.limit(size)
                add(room, info)
                taken += 1
                if (!pull.advance()) break
            }
        } catch (err: Exception) {
            /* A truncated cache - a kill partway through the write - is
             * expected occasionally and is not worth losing whatever did
             * come back. */
        } finally {
            try { pull.release() } catch (err: Exception) { /* gone */ }
        }
        /* THE NEXT ENCODER RUN MUST LAND AFTER WHAT WAS JUST RESTORED.
         *
         * A fresh encoder stamps from near zero, and the packets taken in
         * here carry the timestamps they were written with - so without this
         * the new frames would interleave BEHIND the restored ones, which
         * makes seconds() nonsense and the keyframe walk in save() unable to
         * find a start. */
        if (taken > 0) {
            try { loadAudio(from) } catch (_: Exception) { /* partial audio remains evidence */ }
            finally { joinClock() }
        }
        return taken
    }

    /** Old caches without an audio track remain explicitly video-only. */
    private fun loadAudio(from: File) {
        val pull = android.media.MediaExtractor()
        try {
            pull.setDataSource(from.absolutePath)
            val track = (0 until pull.trackCount).firstOrNull {
                pull.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true
            } ?: return
            audioFormat = pull.getTrackFormat(track)
            pull.selectTrack(track)
            val room = ByteBuffer.allocate(64 * 1024)
            while (true) {
                room.clear()
                val size = pull.readSampleData(room, 0)
                if (size < 0) break
                val bytes = ByteArray(size)
                room.position(0); room.limit(size); room.get(bytes)
                audio.add(ReplayAudioPacket(pull.sampleTime, bytes))
                if (!pull.advance()) break
            }
        } finally {
            pull.release()
        }
    }

    /**
     * #1155: how far the LAST save's clip ended behind the newest thing in
     * the ring, in seconds. Zero for an ordinary save, which ends now; with
     * [save]'s `back` it is roughly that. The scrub strip needs it to label
     * a frame with its real distance from now, so it is reported rather
     * than assumed - the cut lands on a packet boundary, not exactly where
     * it was asked to.
     */
    @Volatile var lastSavedEndBack: Double = 0.0

    /**
     * Write [want] seconds to [out] as an mp4.
     *
     * @param back #1155: seconds before the newest frame in the ring where
     *   the written clip ENDS. 0 - the default, and what every caller
     *   before this asked for - writes the tail: the last [want] seconds.
     *   A larger value cuts a window out of the middle instead, which is
     *   what lets the scrub strip reach the whole twenty minutes without
     *   muxing everything between here and there: the cost of a window is
     *   its own length, not its distance.
     * @return how many seconds were actually written, which can be less than
     *   asked for - the ring holds what it holds, and saying 30 when 11 were
     *   written would be a lie the operator only discovers on playback.
     */
    fun save(out: File, want: Double, allowVideoOnly: Boolean = false, back: Double = 0.0): Double {
        lastSavedAudio = JSONObject().put("source", "android-playback-mix").put("present", false)
            .put("source_scope", "eligible-device-media").put("device_volume_applied", false)
            .put("complete", false).put("state", "unavailable")
            .put("detail", "No replay window has been selected yet.")
        // Copy the selected encoded video under its short lock, then do disk
        // I/O unlocked. Audio capture uses an independent ring throughout.
        val snapshot = synchronized(this) { videoSnapshot(want, back) }
        val fmt = snapshot.first
        val video = snapshot.second
        val zero = video.first().timeUs
        val newest = video.last().timeUs
        val capturedAudio = audio.select(zero, newest)
        val coverage = ReplayAudioCoverage.measure(capturedAudio, zero, newest)
        val audioFmt = audioFormat
        val present = audioFmt != null && coverage.present
        val complete = present && coverage.complete
        val signalKnown = capturedAudio.count { it.signal != null }
        val signalNonzero = capturedAudio.count { it.signal == true }
        val silent = signalKnown == capturedAudio.size && signalKnown > 0 && signalNonzero == 0
        val detail = if (!present) "This replay window has no captured tablet playback audio. Wait for audio capture or explicitly save video only."
            else if (!complete) "Tablet playback audio does not cover this whole replay window. Narrow the window or explicitly save the incomplete recording."
            else if (silent) "Tablet playback samples were captured continuously but contain silence. Real silence or capture-policy restrictions may be responsible."
            else "Screen and device media playback share monotonic timestamps. No microphone or server soundtrack was substituted."
        lastSavedAudio = JSONObject().put("source", "android-playback-mix")
            .put("source_scope", "eligible-device-media").put("device_volume_applied", false)
            .put("complete", complete)
            .put("present", present).put("state", if (complete && silent) "captured_silence" else if (complete) "captured" else if (present) "partial" else "unavailable")
            .put("detail", detail).put("coverage_ratio", coverage.ratio).put("gap_count", coverage.gaps)
            .put("leading_gap_ms", coverage.leadingUs / 1000.0).put("trailing_gap_ms", coverage.trailingUs / 1000.0)
            .put("max_gap_ms", coverage.maxGapUs / 1000.0).put("sample_rate", 48000).put("channels", 2)
            .put("clock", "monotonic").put("audio_packets", capturedAudio.size)
            .put("signal_packets", signalNonzero).put("signal_known_packets", signalKnown)
            .put("signal_state", if (signalNonzero > 0) "nonzero_pcm" else if (silent) "zero_pcm" else "unknown")
            .put("video_only_explicit", allowVideoOnly)
        check(complete || allowVideoOnly) { detail }

        var muxer: MediaMuxer? = null
        var success = false
        try {
            muxer = MediaMuxer(out.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val videoTrack = muxer.addTrack(fmt)
            val audioTrack = if (present) muxer.addTrack(audioFmt!!) else -1
            muxer.start()
            var v = 0; var a = 0
            val info = MediaCodec.BufferInfo()
            while (v < video.size || (audioTrack >= 0 && a < capturedAudio.size)) {
                val chooseAudio = audioTrack >= 0 && a < capturedAudio.size &&
                    (v >= video.size || capturedAudio[a].timeUs <= video[v].timeUs)
                val packet = if (chooseAudio) capturedAudio[a++] else video[v++]
                info.set(0, packet.data.size, packet.timeUs - zero, packet.flags)
                muxer.writeSampleData(if (chooseAudio) audioTrack else videoTrack, ByteBuffer.wrap(packet.data), info)
            }
            muxer.stop()
            success = true
        } finally {
            try { muxer?.release() } catch (_: Exception) { }
            if (!success) out.delete()
        }
        return (newest - zero) / 1_000_000.0
    }

    private fun videoSnapshot(want: Double, back: Double = 0.0): Pair<MediaFormat, List<ReplayAudioPacket>> {
        val fmt = format ?: throw IllegalStateException("the encoder has not started yet")
        if (count < 2) throw IllegalStateException("nothing has been recorded yet")

        val newest = marks[(first + count - 1) % marks.size].timeUs
        /* #1155: the window's NEWEST edge. `back` of zero leaves this at
         * the newest packet there is, which is the tail every caller before
         * this asked for. */
        val until = newest - (Math.max(0.0, back) * 1_000_000L).toLong()
        val from = until - (want * 1_000_000L).toLong()

        /* WALK BACK TO A SYNC FRAME. H.264 refers backwards, so a file that
         * starts mid-GOP decodes as a smear until the next keyframe. Better
         * to give slightly MORE than was asked for, starting cleanly, than
         * exactly what was asked for starting in rubbish. */
        var start = -1
        for (i in 0 until count) {
            val slot = (first + i) % marks.size
            val isSync = marks[slot].flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
            if (!isSync) continue
            if (marks[slot].timeUs <= from) start = i else if (start < 0) start = i
            if (marks[slot].timeUs > from) break
        }
        if (start < 0) throw IllegalStateException("no keyframe in the buffer yet")

        /* #1155: AND WHERE IT STOPS. Without a `back` this is the newest
         * packet and the walk below runs to the end exactly as it always
         * did. With one, the clip ends at the last packet at or before
         * `until` - a packet boundary, so up to one frame earlier than
         * asked - and lastSavedEndBack reports where it actually landed
         * rather than letting the page assume. */
        var stop = count - 1
        if (back > 0.0) {
            var i = count - 1
            while (i > start && marks[(first + i) % marks.size].timeUs > until) i -= 1
            stop = i
        }
        if (stop <= start) stop = Math.min(count - 1, start + 1)

        val packets = ArrayList<ReplayAudioPacket>(stop - start + 1)
        for (i in start..stop) {
            val mark = marks[(first + i) % marks.size]
            packets.add(ReplayAudioPacket(mark.timeUs, blob.copyOfRange(mark.at, mark.at + mark.size), mark.flags))
        }
        lastSavedEndBack = (newest - packets[packets.size - 1].timeUs) / 1_000_000.0
        return Pair(fmt, packets)
    }
}
