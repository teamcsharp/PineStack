package com.pinebox.kiosk.net

/**
 * Every station route this terminal is allowed to build.
 *
 * Deliberately a closed list. The panel itself reaches whatever it likes
 * through pineDesktop.get/post - it is the station's own HTML and knows its
 * own API - but native code (the feed, the audio engine, any future native
 * view) goes through here, so that "which endpoints does the terminal
 * depend on" has a single, greppable answer instead of being scattered
 * across string literals.
 *
 * Pure Kotlin: no android.net.Uri, because Uri is one of the android.jar
 * stubs that throws under JVM unit tests, and URL building is exactly the
 * kind of thing that should be tested without a device.
 */
object StationUrls {

    /** Trailing slashes off, so `base + route` never doubles one up. */
    fun base(baseUrl: String): String = baseUrl.trim().trimEnd('/')

    /** The whole booth state. Polled every 4s and no faster - see StationFeed. */
    fun dj(baseUrl: String): String = base(baseUrl) + "/api/dj"

    /** Where a line came from: the provenance card behind a spoken row. */
    fun provenance(baseUrl: String, id: String): String =
        base(baseUrl) + "/api/dj/provenance/" + encodePath(id)

    /**
     * The audio for a line. `whole=1` asks for the entire coalesced round
     * rather than the single turn - which is what a terminal that wants to
     * play along with the box needs, since the box airs rounds, not lines.
     */
    fun boothClip(baseUrl: String, line: String, whole: Boolean = false): String =
        base(baseUrl) + "/api/booth/clip?line=" + encodeQuery(line) +
            "&whole=" + (if (whole) "1" else "0")

    fun airlog(baseUrl: String): String = base(baseUrl) + "/api/airlog"

    /** What the SFX guy has queued / just fired. */
    fun djSfx(baseUrl: String): String = base(baseUrl) + "/api/dj/sfx"

    fun sfxStats(baseUrl: String): String = base(baseUrl) + "/api/sfx/stats"

    /**
     * A music track. `t` is a cache-buster the station's own pages pass;
     * without it a re-cued track can be served from the WebView's HTTP
     * cache and the terminal plays the previous rendering.
     */
    fun music(baseUrl: String, id: String, t: Long): String =
        base(baseUrl) + "/music/" + encodePath(id) + "?t=" + t

    /** Any rendered media blob by key, same cache-busting rule. */
    fun media(baseUrl: String, key: String, t: Long): String =
        base(baseUrl) + "/media/" + encodePath(key) + "?t=" + t

    fun generations(baseUrl: String): String = base(baseUrl) + "/api/generations"

    fun generationImage(baseUrl: String, file: String): String =
        base(baseUrl) + "/api/generations/image/" + encodePath(file)

    /* ----------------------------------------------------------------- */

    private const val UNRESERVED =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"

    /**
     * Percent-encode for a PATH segment. Note this is not URLEncoder:
     * URLEncoder is form encoding and turns a space into `+`, which inside
     * a path is a literal plus and would ask the station for the wrong id.
     */
    internal fun encodePath(raw: String): String = percent(raw, extraSafe = "")

    /**
     * Percent-encode for a QUERY value. A space could legally be `+` here,
     * but `%20` is correct in both places, so one encoder with one rule
     * removes a whole class of "worked in the path, broke in the query".
     */
    internal fun encodeQuery(raw: String): String = percent(raw, extraSafe = "")

    private fun percent(raw: String, extraSafe: String): String {
        val out = StringBuilder(raw.length + 8)
        for (byte in raw.toByteArray(Charsets.UTF_8)) {
            val c = (byte.toInt() and 0xFF).toChar()
            if (c in UNRESERVED || c in extraSafe) {
                out.append(c)
            } else {
                out.append('%')
                out.append("0123456789ABCDEF"[(byte.toInt() shr 4) and 0x0F])
                out.append("0123456789ABCDEF"[byte.toInt() and 0x0F])
            }
        }
        return out.toString()
    }
}
