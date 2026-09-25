package com.pinebox.kiosk.rail

import com.pinebox.kiosk.feed.FeedState
import org.json.JSONObject

/**
 * Everything the rail paints, and NOTHING else.
 *
 * THIS CLASS IS THE OPTIMISATION, not a convenience. [StationFeed] emits at
 * 250ms - not because it polls that fast (it polls at 4s, by the station's own
 * contract) but because it re-interpolates the playhead locally between polls.
 * Measured on the TB310FU before this existed, the terminal was at 21.5% janky
 * frames with 39 "Slow UI thread" frames per 219; a rail that re-bound
 * twenty-odd views four times a second would have gone straight onto that
 * pile.
 *
 * So the feed is mapped to this small, VALUE-equal snapshot on a background
 * dispatcher and put through distinctUntilChanged. The playhead ticking does
 * not change any field here, so the rail is touched only when something it
 * actually shows has moved - which on a radio station is a few times a minute,
 * not four times a second.
 *
 * Every field is a primitive or a String on purpose: a data class holding the
 * JSONObject would compare by identity and defeat the whole thing.
 */
data class RailState(
    val connected: Boolean = false,
    val error: String? = null,
    /** `on` in /api/dj - the FM switch. app.py:39905 `on = bool(_RADIO["on"])`. */
    val fm: Boolean = false,
    /** `paused` in /api/dj - the air pause, `radio_paused()`. Not the same thing. */
    val paused: Boolean = false,
    val musicTo: String = "",
    val voiceTo: String = "",
    val replyTo: String = "",
    val voiceDevice: String = "",
    /**
     * The per-stream levels the station reports, as percentages, or -1 for
     * "the station did not say".
     *
     * It only says when the broadcast device is the Nabu: `nabu_music_level`
     * and friends are the Nabu mix. For a Pine Box the equivalent number lives
     * in settings (`box_volume`, `music_box_level`) and is not published on
     * /api/dj at all - so on those the slider is a SEND-ONLY control, exactly
     * as it is on the desktop, where its position is remembered in
     * localStorage rather than read back (renderer.js streamVolumes).
     */
    val musicLevel: Int = -1,
    val voiceLevel: Int = -1,
    val replyLevel: Int = -1,
    val stationName: String = "",
    /** The line sounding right now, already formatted for one label. */
    val nowLine: String = "",
    /** The tail of `activity_log`, already formatted. Free - see below. */
    val log: String = "",
) {

    /** Which broadcast presets the CURRENT routing is; empty if none does. */
    val presets: Set<String>
        get() = DjOutput.presetsOf(musicTo, voiceTo, replyTo, voiceDevice)

    fun levelOf(stream: String): Int = when (stream) {
        "music" -> musicLevel
        "voice" -> voiceLevel
        else -> replyLevel
    }

    fun routeOf(stream: String): String = when (stream) {
        "music" -> musicTo
        "voice" -> voiceTo
        else -> replyTo
    }

    /**
     * Take the routing straight out of a POST response.
     *
     * `/api/dj/output` answers with `dj_state()` - the same object and the
     * same field names /api/dj carries - so the confirmed routing is in hand
     * the moment the call returns. Waiting for the next 4s poll instead would
     * leave a freshly tapped chip unlit for up to four seconds, which reads as
     * a control that did nothing. The desktop reached the same conclusion for
     * the same reason (renderer.js acceptRoutingResponse: "The route POST
     * already returns the confirmed state").
     *
     * Only the routing fields are taken: the response has no `chat` and no
     * `stream_now`, so nowLine and the log must keep whatever the feed put
     * there or the rail would blank them on every tap.
     */
    fun patched(dj: JSONObject): RailState {
        val routing = dj.optJSONObject("routing") ?: dj
        fun str(key: String, fallback: String) =
            if (routing.has(key) && !routing.isNull(key)) routing.optString(key) else fallback
        return copy(
            connected = true,
            error = null,
            fm = if (routing.has("on")) routing.optBoolean("on", fm) else fm,
            paused = if (routing.has("paused")) routing.optBoolean("paused", paused) else paused,
            musicTo = str("music_to", musicTo),
            voiceTo = str("voice_to", voiceTo),
            replyTo = str("reply_to", replyTo),
            voiceDevice = str("voice_device", voiceDevice),
        )
    }

    companion object {

        /** How many activity rows the pane shows without being asked. */
        const val LOG_ROWS = 14

        fun of(feed: FeedState): RailState {
            val dj = feed.station ?: return RailState(connected = false, error = feed.error)
            return RailState(
                connected = feed.connected,
                error = feed.error,
                fm = dj.optBoolean("on", false),
                paused = dj.optBoolean("paused", false),
                musicTo = dj.optString("music_to"),
                voiceTo = dj.optString("voice_to"),
                replyTo = dj.optString("reply_to"),
                voiceDevice = dj.optString("voice_device"),
                musicLevel = percent(dj, "nabu_music_level"),
                voiceLevel = percent(dj, "nabu_voice_level"),
                replyLevel = percent(dj, "nabu_reply_level"),
                stationName = dj.optString("station_name"),
                nowLine = nowLine(feed),
                log = logOf(dj),
            )
        }

        /** -1 rather than 0 for "absent": 0 is a real level and means silence. */
        private fun percent(dj: JSONObject, key: String): Int {
            if (!dj.has(key) || dj.isNull(key)) return -1
            val value = dj.optDouble(key, -1.0)
            if (value < 0.0 || value > 1.0) return -1
            return Math.round(value * 100.0).toInt()
        }

        private fun nowLine(feed: FeedState): String {
            val row = feed.now ?: return ""
            val who = row.who.ifBlank { "dj" }
            return who + ": " + row.text.trim()
        }

        /**
         * The log pane's default content.
         *
         * `activity_log` is ALREADY in the /api/dj object the terminal polls,
         * so showing it costs the station nothing - no second route, no second
         * poller. It is short (17 rows when this was written), which is why
         * the rail also carries a Full log button that fetches
         * /api/dj/pipeline (app.py:108717, 120 events) ONCE, on the tap.
         */
        private fun logOf(dj: JSONObject): String {
            val rows = dj.optJSONArray("activity_log") ?: return ""
            val out = StringBuilder()
            val from = maxOf(0, rows.length() - LOG_ROWS)
            for (i in from until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                val stage = row.optString("stage")
                val detail = row.optString("detail")
                if (stage.isBlank() && detail.isBlank()) continue
                if (out.isNotEmpty()) out.append('\n')
                out.append(stage)
                if (detail.isNotBlank()) out.append("  ").append(detail)
            }
            return out.toString()
        }

        /**
         * The pipeline log, formatted for the pane. One line per event,
         * newest last, `extra` dropped - it carries whole swaths of mined
         * text (measured: a single event's extra ran to 1.4 kB) and a rail
         * pane is not where anyone reads those.
         */
        fun pipelineLog(body: String, rows: Int = 60): String {
            val events = JSONObject(body).optJSONArray("events") ?: return ""
            val out = StringBuilder()
            val from = maxOf(0, events.length() - rows)
            for (i in from until events.length()) {
                val event = events.optJSONObject(i) ?: continue
                val text = event.optString("text")
                if (text.isBlank()) continue
                if (out.isNotEmpty()) out.append('\n')
                out.append(event.optString("kind").ifBlank { "-" })
                    .append("  ")
                    .append(text)
            }
            return out.toString()
        }
    }
}
