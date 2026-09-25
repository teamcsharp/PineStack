package com.pinebox.kiosk.config

import com.pinebox.kiosk.BuildConfig
import org.json.JSONObject

/**
 * The terminal's configuration.
 *
 * The field names are NOT arbitrary: they are exactly the keys Electron's
 * `defaults` object uses (desktop/main.js:97-107), because the panel reads
 * `readConfig()` and expects `baseUrl` and `apiKey` by those names. The
 * three that mean nothing on a tablet - `port`, `dataDir`, `python`, which
 * describe a locally-spawned station - are carried anyway so a round trip
 * through writeConfig cannot lose a key the panel put there.
 */
data class Config(
    val baseUrl: String = BuildConfig.DEFAULT_BASE_URL,
    val apiKey: String = "",
    /** Always "attach": the station runs on the box, never on the tablet. */
    val mode: String = "attach",
    val port: Int = 8096,
    val dataDir: String = "",
    val python: String = "",
    /** THE OPERATOR'S OWN WORKING FOLDER.
     *
     * "Download it to the local recording folder where I'm extracting
     * things." Which folder that is belongs to him, not to this app, so it
     * is a setting with a sensible default rather than a constant - and
     * whatever it holds, the terminal answers with the full path it wrote
     * to, so there is never a doubt about where a clip went. */
    val recordingFolder: String = "Pine Box recordings",
    /** THE STATION'S OTHER ADDRESSES, tried when the LAN one does not
     *  answer - see net/Reach.kt. Settings rather than constants because
     *  a tailnet address can change and the operator should not need a new
     *  build to follow it. */
    val tailnetUrl: String = BuildConfig.DEFAULT_TAILNET_URL,
    val tailnetName: String = BuildConfig.DEFAULT_TAILNET_NAME,
    /** THE HOT CORNERS - the switch and the four actions. See HotCorners.kt
     *  for the operator's words; this is only where they are kept. */
    val hotCorners: HotCornerPrefs = HotCornerPrefs(),
) {
    /** The base with any trailing slash removed, so `base + route` is safe. */
    val base: String get() = baseUrl.trimEnd('/')

    fun toJson(): JSONObject = JSONObject()
        .put("baseUrl", baseUrl)
        .put("apiKey", apiKey)
        .put("mode", mode)
        .put("port", port)
        .put("dataDir", dataDir)
        .put("python", python)
        .put("recordingFolder", recordingFolder)
        .put("tailnetUrl", tailnetUrl)
        .put("tailnetName", tailnetName)
        .put("hotCorners", hotCorners.toJson())
        /* Not in the Electron shape. Lets a page that cares tell a terminal
         * from a desktop without sniffing the user agent. */
        .put("platform", "android")

    /** Apply a partial patch, the way Electron's writeConfig merges. */
    fun merged(patch: JSONObject?): Config {
        if (patch == null) return this
        return copy(
            baseUrl = patch.optString("baseUrl", baseUrl).ifBlank { baseUrl },
            apiKey = if (patch.has("apiKey")) patch.optString("apiKey", "") else apiKey,
            mode = patch.optString("mode", mode).ifBlank { mode },
            port = patch.optInt("port", port),
            dataDir = if (patch.has("dataDir")) patch.optString("dataDir", "") else dataDir,
            python = if (patch.has("python")) patch.optString("python", "") else python,
            recordingFolder = patch.optString("recordingFolder", recordingFolder)
                .ifBlank { recordingFolder },
            tailnetUrl = patch.optString("tailnetUrl", tailnetUrl),
            tailnetName = patch.optString("tailnetName", tailnetName),
            hotCorners = hotCorners.merged(patch.optJSONObject("hotCorners")),
        )
    }
}

/**
 * THE FOUR CORNERS AND THE SWITCH.
 *
 * "I also want preferences in the swipe out on the pine box tablet where I
 *  can specify what these behaviors are for the gestures for each of the
 *  hot corners ... be able to also change these and set these and disable
 *  these if I want."
 *
 * Each corner names one of [ACTIONS]; the defaults are the operator's own
 * layout, corner by corner, from the request quoted in HotCorners.kt: the
 * top left shoots and draws, the top right exports the screen video, the
 * bottom left inspects the last line, the bottom right replays the SFX.
 */
data class HotCornerPrefs(
    val enabled: Boolean = true,
    val tl: String = "shot",
    val tr: String = "export",
    val bl: String = "inspect",
    val br: String = "sfx",
    /** The square at a display corner in which a gesture may begin. */
    val activationZonePx: Int = DEFAULT_ACTIVATION_ZONE_PX,
    /** How forgiving the diagonal gesture is, from 0 to 100. */
    val sensitivity: Int = DEFAULT_SENSITIVITY,
) {
    fun of(corner: String): String = when (corner) {
        "tl" -> tl
        "tr" -> tr
        "bl" -> bl
        "br" -> br
        else -> "off"
    }

    fun toJson(): JSONObject = JSONObject()
        .put("enabled", enabled)
        .put("tl", tl)
        .put("tr", tr)
        .put("bl", bl)
        .put("br", br)
        .put("activationZonePx", activationZonePx)
        .put("sensitivity", sensitivity)

    /** Merge a partial patch. A corner given a word not in [ACTIONS] keeps
     *  what it had, so a typo from the page cannot leave a corner in a
     *  state the drawer has no row for. */
    fun merged(patch: JSONObject?): HotCornerPrefs {
        if (patch == null) return this
        fun corner(key: String, was: String): String {
            val want = patch.optString(key, was)
            return if (want in ACTIONS) want else was
        }
        return copy(
            enabled = patch.optBoolean("enabled", enabled),
            tl = corner("tl", tl),
            tr = corner("tr", tr),
            bl = corner("bl", bl),
            br = corner("br", br),
            activationZonePx = bounded(
                patch.optInt("activationZonePx", activationZonePx),
                MIN_ACTIVATION_ZONE_PX,
                MAX_ACTIVATION_ZONE_PX,
            ),
            sensitivity = bounded(
                patch.optInt("sensitivity", sensitivity),
                MIN_SENSITIVITY,
                MAX_SENSITIVITY,
            ),
        )
    }

    companion object {
        const val MIN_ACTIVATION_ZONE_PX = 20
        const val MAX_ACTIVATION_ZONE_PX = 120
        const val DEFAULT_ACTIVATION_ZONE_PX = 42
        const val MIN_SENSITIVITY = 0
        const val MAX_SENSITIVITY = 100
        const val DEFAULT_SENSITIVITY = 50

        fun bounded(value: Int, minimum: Int, maximum: Int): Int =
            value.coerceIn(minimum, maximum)

        /** The contract with pine-views/hot-corners.js, one word each. */
        val ACTIONS = setOf("off", "shot", "export", "inspect", "sfx", "report")
    }
}
