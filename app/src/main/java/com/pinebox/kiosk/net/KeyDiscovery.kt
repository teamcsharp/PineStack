package com.pinebox.kiosk.net

/**
 * Pulling the station's own key out of the panel it serves.
 *
 * The station embeds its key in every page it renders, as
 *
 *     const SERVER_KEY = "…";
 *
 * (app.py:134065 and friends, filled in by `.replace("__SERVER_KEY__",
 * json.dumps(embedded))`). So a terminal on the LAN can provision itself in
 * one unauthenticated GET of `/` rather than being told a secret by hand.
 * This is the same regex Electron's discoverAgentKey uses
 * (desktop/main.js:449) and it must stay the same: the value is a JSON
 * string literal, so it can carry escapes, and matching a bare `"([^"]*)"`
 * would truncate at the first escaped quote.
 *
 * Pure Kotlin with no org.json, so it is unit-testable on the JVM without
 * the Android stub jar getting in the way.
 */
object KeyDiscovery {

    private val PATTERN = Regex("""const\s+SERVER_KEY\s*=\s*("(?:\\.|[^"\\])*")\s*;""")

    /**
     * @return the key, or null when the page carries none (the station
     *   renders `""` when no key is configured - which Electron treats as
     *   "not found" too, hence the isEmpty check).
     */
    fun extract(html: String?): String? {
        if (html.isNullOrEmpty()) return null
        val literal = PATTERN.find(html)?.groupValues?.get(1) ?: return null
        val key = unquote(literal)
        return key.ifEmpty { null }
    }

    /**
     * Decode a JSON string literal, quotes included. Written out rather
     * than borrowed from org.json because this is the one piece of the
     * provisioning road that must be testable without an emulator.
     */
    internal fun unquote(literal: String): String {
        if (literal.length < 2) return ""
        val body = literal.substring(1, literal.length - 1)
        val out = StringBuilder(body.length)
        var i = 0
        while (i < body.length) {
            val c = body[i]
            if (c != '\\') {
                out.append(c)
                i++
                continue
            }
            i++
            if (i >= body.length) break
            when (val esc = body[i]) {
                '"' -> out.append('"')
                '\\' -> out.append('\\')
                '/' -> out.append('/')
                'b' -> out.append('\b')
                'f' -> out.append('\u000C')
                'n' -> out.append('\n')
                'r' -> out.append('\r')
                't' -> out.append('\t')
                'u' -> {
                    val hex = body.substring(i + 1, minOf(i + 5, body.length))
                    if (hex.length == 4) {
                        hex.toIntOrNull(16)?.let { out.append(it.toChar()) }
                        i += 4
                    }
                }
                // An unknown escape in a well-formed JSON string cannot
                // happen; keep the character rather than losing it.
                else -> out.append(esc)
            }
            i++
        }
        return out.toString()
    }
}
