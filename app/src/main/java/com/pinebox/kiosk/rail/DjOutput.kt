package com.pinebox.kiosk.rail

import org.json.JSONObject

/**
 * The bodies the rail is allowed to POST to `/api/dj/output`.
 *
 * Every value here is checked against the station's OWN list. app.py:93383
 * reads:
 *
 *     valid = ("box", "here", "both", "off", "nabu")
 *
 * and the handler answers a 400 with `detail: "box, here, both, nabu or off"`
 * for anything else. A terminal that has to learn that from a round trip is a
 * terminal that shows the operator a red note for a typo this file could have
 * caught - so the check is here as well, and [ROUTES] is that tuple.
 *
 * Pure Kotlin, no android.*: the payload shapes are exactly the kind of thing
 * that must be testable without a device (see StationUrls for the same
 * reasoning about URL building).
 */
object DjOutput {

    /** app.py:93383 `valid`. Do not widen without widening it there first. */
    val ROUTES: Set<String> = setOf("box", "here", "both", "off", "nabu")

    /** The three independently routable streams (#980). */
    val STREAMS: List<String> = listOf("music", "voice", "reply")

    /** The same destinations offered by the desktop's canonical picker. */
    val PRESETS: Map<String, Preset> = linkedMapOf(
        "nabu" to Preset("Nabu", "nabu", "nabu", "nabu", voiceDevice = "nabu", boxTalk = true),
        "box" to Preset("Pine Box", "box", "box", "box", voiceDevice = "pine", boxTalk = true),
        "pinetab" to Preset("PineTab", "here", "here", "here", voiceDevice = null, boxTalk = false),
        "app" to Preset("PineApp", "here", "here", "here", voiceDevice = null, boxTalk = false),
    )

    data class Preset(
        val label: String,
        val music: String,
        val voice: String,
        val reply: String,
        val voiceDevice: String?,
        val boxTalk: Boolean,
    )

    /** Move ONE stream. `{"music":"here"}` - the shape renderer.js:1776 sends. */
    fun stream(stream: String, value: String): String {
        require(stream in STREAMS) { "no such stream: $stream" }
        require(value in ROUTES) { "box, here, both, nabu or off - not $value" }
        return JSONObject().put(stream, value).toString()
    }

    /**
     * Move all three at once.
     *
     * `box_talk` and `voice_device` ride along exactly as the desktop sends
     * them, and voice_device is OMITTED for PineTab/PineApp rather than sent empty -
     * the handler validates it as `pine or nabu` when present (app.py:93395),
     * so an empty string would be a 400 on the two presets that need it least.
     */
    fun preset(target: String): String {
        val preset = PRESETS[target] ?: throw IllegalArgumentException("no such preset: $target")
        val body = JSONObject()
            .put("music", preset.music)
            .put("voice", preset.voice)
            .put("reply", preset.reply)
            .put("box_talk", preset.boxTalk)
        preset.voiceDevice?.let { body.put("voice_device", it) }
        return body.toString()
    }

    /**
     * A level for one stream, 0..1.
     *
     * The station clamps to 0..1 itself and 400s a non-finite number
     * (app.py:93401), which a SeekBar cannot produce - but it also *applies*
     * whatever arrives, immediately, to the real device (#1014: "these settings
     * are affecting the box in real time as I'm adjusting them"). So the value
     * is rounded to two places here: a drag that posts 0.3499999 and then
     * 0.35 is two writes to a speaker for one thumb movement.
     */
    fun level(stream: String, fraction: Double): String {
        require(stream in STREAMS) { "no such stream: $stream" }
        val clamped = fraction.coerceIn(0.0, 1.0)
        val rounded = Math.round(clamped * 100.0) / 100.0
        return JSONObject().put(stream + "_level", rounded).toString()
    }

    /**
     * Which broadcast presets the station's CURRENT routing is.
     *
     * A SET, not one key, because two of the four are genuinely the same
     * routing: `web` and `app` both send all three streams `here` and both
     * leave the device alone. The desktop agrees - its EMBEDDED_ROUTES rows
     * for web and app are identical (renderer.js:83) - and on a tablet there
     * is not even a philosophical difference, since "the page" IS the
     * application. Lighting one and not the other would be a claim about
     * which of two identical states the station is in, so both light.
     *
     * Worked out from what the STATION says, never from what this terminal
     * last asked for: the routing is shared between every open surface and the
     * box can move it underneath us (renderer.js paintStreamRoutes says the
     * same). An empty set means the three streams have been moved apart and no
     * preset describes them - which the rail shows as no chip lit rather than
     * a wrong one lit (#980).
     */
    fun presetsOf(
        music: String,
        voice: String,
        reply: String,
        voiceDevice: String,
    ): Set<String> {
        /* Older station builds represented Nabu as the box route plus a
         * voice-device discriminator. Keep that read compatibility while
         * every new write uses the canonical `nabu` route. */
        if (music == "box" && voice == "box" && reply == "box"
            && voiceDevice == "nabu") return setOf("nabu")
        val hit = LinkedHashSet<String>()
        for ((key, preset) in PRESETS) {
            if (preset.music != music || preset.voice != voice || preset.reply != reply) continue
            /* box and nabu differ ONLY in the device, so the device has to be
             * part of the match or every Nabu station would light "Pine Box". */
            if (preset.voiceDevice != null && preset.voiceDevice != voiceDevice) continue
            hit.add(key)
        }
        return hit
    }
}
