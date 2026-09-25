package com.pinebox.kiosk.feed

import org.json.JSONObject

/**
 * One line of the booth's dialogue, as the terminal shows it.
 *
 * A straight port of desktop/renderer/lcd-dialogue.js `stationRows`, kept
 * field-for-field so the tablet and the LCD agree about what is on air.
 */
data class FeedRow(
    val id: String,
    val text: String,
    val who: String,
    val kind: String,
    val aired: String,
    /** The human label - "Playing", "Aired", "Recorded / waiting", … */
    val status: String,
    /** True when there is (or was) real audio behind this row. */
    val hasAudio: Boolean,
    /** Unix seconds this row went out, when the station said so. */
    val airAt: Double,
) {
    val isPlaying: Boolean get() = aired == "airing"
}

object StationRows {

    /* The station puts bookkeeping rows through the same channel as speech.
     * None of them are lines and none of them should ever appear on a
     * terminal someone is reading. */
    private val NOISE = setOf("seen", "tick", "ping", "heartbeat")

    private val AIRED_WITH_AUDIO = setOf("box", "stream", "both", "airing")

    /**
     * @param station the whole /api/dj object
     * @param nowMs the clock ALREADY corrected by the station's server_ms
     *   skew. Passing an uncorrected clock is the classic way to make the
     *   playhead land on the wrong line - see StationFeed.
     */
    fun of(station: JSONObject?, nowMs: Long): List<FeedRow> {
        if (station == null) return emptyList()

        /* Insertion-ordered: the station already sorted `chat` into the
         * order the room HEARD it (app.py:25280), and re-sorting here would
         * throw that away - the store is an append log written by a dozen
         * concurrent tasks, so insertion order is not broadcast order. */
        val rows = LinkedHashMap<String, JSONObject>()

        val chat = station.optJSONArray("chat")
        if (chat != null) {
            for (i in 0 until chat.length()) {
                val row = chat.optJSONObject(i) ?: continue
                absorb(rows, row, null)
            }
        }

        /* Which turn of the current round is sounding right now. /api/dj
         * carries the whole timeline (#772) precisely so this can be worked
         * out between polls instead of on one - on an eight-second turn a
         * four-second poll lands the marker on the wrong line about half
         * the time. */
        val stream = station.optJSONObject("stream_now")
        var current: JSONObject? = null
        if (stream != null) {
            val at = stream.optDouble("at", 0.0)
            val length = stream.optDouble("length", 0.0)
            val offset = nowMs / 1000.0 - at
            if (at > 0 && offset >= 0 && offset <= length + 4.0) {
                val turns = stream.optJSONArray("rows")
                if (turns != null) {
                    for (i in 0 until turns.length()) {
                        val turn = turns.optJSONObject(i) ?: continue
                        val from = turn.optDouble("from", 0.0)
                        val until = turn.optDouble("until", 0.0)
                        if (from <= offset && offset < until) {
                            current = JSONObject(turn.toString())
                                .put("aired", "airing")
                                .put("air_at", at + from)
                        }
                    }
                }
            }
        }

        val live = current ?: station.optJSONObject("speaking_now")
        val liveId = live?.optString("id").orEmpty()
        if (live != null && liveId.isNotEmpty()) {
            /* The serialised stream_now turn carries only {id, from, until}
             * (app.py:25295) - the text was dropped on the way out. The
             * renderer's guard `if (live?.id && live.text)` therefore never
             * fires for a coalesced round, which is most of the show, and
             * nothing gets marked Playing. Here the text is taken from the
             * chat row of the same id, which is where it always was. */
            val before = rows[liveId]
            val merged = JSONObject()
            before?.let { copyInto(it, merged) }
            copyInto(live, merged)
            merged.put("aired", "airing")
            if (merged.optString("text").isBlank() && before != null) {
                merged.put("text", before.optString("text"))
            }
            // The current speaker stays visible last.
            rows.remove(liveId)
            absorb(rows, merged, "Playing")
        }

        return rows.values.map { toRow(it) }
    }

    private fun absorb(into: LinkedHashMap<String, JSONObject>, row: JSONObject, status: String?) {
        val id = row.optString("id")
        if (id.isBlank()) return
        if (row.optString("text").isBlank()) return
        if (row.optString("kind") in NOISE) return

        val previous = into[id]
        val merged = JSONObject()
        previous?.let { copyInto(it, merged) }
        copyInto(row, merged)
        merged.put("id", id)

        val aired = merged.optString("aired")
        val audio = aired in AIRED_WITH_AUDIO ||
            merged.optString("audio_url").isNotBlank() ||
            merged.optString("clip_url").isNotBlank()

        merged.put("lcdStatus", status ?: label(aired))
        merged.put("lcdAudio", audio)
        into[id] = merged
    }

    /** The same ladder the LCD uses, so the two never disagree on wording. */
    internal fun label(aired: String): String = when (aired) {
        "airing" -> "Playing"
        "box", "stream", "both" -> "Aired"
        "prepared" -> "Recorded / waiting"
        "published", "page" -> "Awaiting playback"
        "failed" -> "Audio failed"
        else -> "Booth activity"
    }

    private fun toRow(obj: JSONObject) = FeedRow(
        id = obj.optString("id"),
        text = obj.optString("text"),
        who = obj.optString("who").ifBlank { "dj" },
        kind = obj.optString("kind").ifBlank { "line" },
        aired = obj.optString("aired"),
        status = obj.optString("lcdStatus"),
        hasAudio = obj.optBoolean("lcdAudio", false),
        airAt = obj.optDouble("air_at", obj.optDouble("ts", 0.0)),
    )

    private fun copyInto(from: JSONObject, into: JSONObject) {
        val names = from.keys()
        while (names.hasNext()) {
            val key = names.next()
            into.put(key, from.opt(key))
        }
    }
}
