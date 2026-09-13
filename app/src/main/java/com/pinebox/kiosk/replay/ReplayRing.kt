package com.pinebox.kiosk.replay

import android.media.MediaCodec
import android.media.MediaFormat
import android.media.MediaMuxer
import java.io.File
import java.nio.ByteBuffer

/**
 * THE LAST HALF-MINUTE, ALWAYS.
 *
 * "Always have the application saving the last thirty seconds of activity...
 *  I just want it recording the tablet in general with a rolling history that
 *  I'm able to always extract."
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
    private var shift = 0L
    private var based = true

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
        val want = bytes.coerceIn(2 * 1024 * 1024, 96 * 1024 * 1024)
        if (blob.size == want && marks.isNotEmpty()) {
            /* Already the right shape: keep every packet in it. */
            joinClock()
            return
        }
        blob = ByteArray(want)
        /* A generous packet count: at 30 fps a minute is 1,800, and running
         * out of marks would silently drop frames the ring has room for. */
        marks = Array(holdSeconds * 60) { Mark() }
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
        if (count == 0) { shift = 0L; based = true; return }
        continueAfter = marks[(first + count - 1) % marks.size].timeUs
        based = false
    }

    @Synchronized
    fun reset() {
        head = 0; first = 0; count = 0; wrote = 0
        continueAfter = 0L; shift = 0L; based = true
    }

    @Synchronized
    fun remember(fmt: MediaFormat) { format = fmt }

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
        if (!based) {
            shift = continueAfter + FRAME_GAP_US - info.presentationTimeUs
            based = true
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
            return taken
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
        if (taken > 0) joinClock()
        return taken
    }

    /**
     * Write the last [want] seconds to [out] as an mp4.
     *
     * @return how many seconds were actually written, which can be less than
     *   asked for - the ring holds what it holds, and saying 30 when 11 were
     *   written would be a lie the operator only discovers on playback.
     */
    @Synchronized
    fun save(out: File, want: Double): Double {
        val fmt = format ?: throw IllegalStateException("the encoder has not started yet")
        if (count < 2) throw IllegalStateException("nothing has been recorded yet")

        val newest = marks[(first + count - 1) % marks.size].timeUs
        val from = newest - (want * 1_000_000L).toLong()

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

        val muxer = MediaMuxer(out.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        val track = muxer.addTrack(fmt)
        muxer.start()
        val info = MediaCodec.BufferInfo()
        val buffer = ByteBuffer.wrap(blob)
        val zero = marks[(first + start) % marks.size].timeUs
        var last = 0L
        try {
            for (i in start until count) {
                val slot = (first + i) % marks.size
                val mark = marks[slot]
                buffer.position(mark.at)
                buffer.limit(mark.at + mark.size)
                info.offset = mark.at
                info.size = mark.size
                info.flags = mark.flags
                /* Restamped from zero, or every player shows the clip as
                 * starting several minutes in. */
                info.presentationTimeUs = mark.timeUs - zero
                last = info.presentationTimeUs
                muxer.writeSampleData(track, buffer, info)
            }
        } finally {
            try { muxer.stop() } catch (err: Exception) { /* nothing written */ }
            muxer.release()
        }
        return last / 1_000_000.0
    }
}
