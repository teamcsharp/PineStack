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
        )
    }
}
