package com.pinebox.kiosk.bridge

/**
 * The wire format between PineDesktopBridge and assets/pine-bridge.js.
 *
 * Two shapes, and only two:
 *
 *   the ACK, returned synchronously from invoke():
 *       {"accepted":true,"id":"r1-…"}
 *       {"accepted":false,"error":"no such bridge method: frobnicate"}
 *
 *   the SETTLEMENT, delivered later via __pineBridgeSettle:
 *       {"id":"r1-…","ok":true,"value":<any JSON>}
 *       {"id":"r1-…","ok":false,"error":"401 from the station"}
 *
 * Built by string rather than org.json for one reason: `value` is very
 * often a station response that is ALREADY JSON text, sometimes a large
 * one, and routing it through JSONObject would parse and re-serialise the
 * whole thing on the way past. [ok] takes the raw JSON and splices it in.
 *
 * Pure Kotlin so the envelope can be tested on the JVM, which matters - an
 * envelope bug shows up on the tablet as a promise that never settles, with
 * nothing in the log.
 */
object BridgeEnvelope {

    private const val FORM_FEED = '\u000C'
    private const val LINE_SEP = '\u2028'
    private const val PARA_SEP = '\u2029'

    fun accepted(id: String): String =
        """{"accepted":true,"id":${quote(id)}}"""

    fun refused(reason: String): String =
        """{"accepted":false,"error":${quote(reason)}}"""

    /**
     * @param rawJson a complete JSON value - object, array, string literal,
     *   number, true/false/null. Blank is treated as JSON null, because a
     *   204 or an empty body is a legitimate answer from the station and
     *   should resolve the promise rather than break the envelope.
     */
    fun ok(id: String, rawJson: String?): String {
        val value = rawJson?.trim().takeUnless { it.isNullOrEmpty() } ?: "null"
        return """{"id":${quote(id)},"ok":true,"value":$value}"""
    }

    /** Wrap a non-JSON value (a bare string) as the settlement's value. */
    fun okString(id: String, value: String?): String =
        """{"id":${quote(id)},"ok":true,"value":${quote(value ?: "")}}"""

    fun okBoolean(id: String, value: Boolean): String =
        """{"id":${quote(id)},"ok":true,"value":$value}"""

    fun error(id: String, reason: String?): String {
        val why = reason.orEmpty().ifBlank { "the bridge failed without saying why" }
        return """{"id":${quote(id)},"ok":false,"error":${quote(why)}}"""
    }

    /**
     * A refusal the panel is meant to SHOW rather than throw on: the LCD,
     * the terminal provisioner, the local backend. Resolved, not rejected -
     * a rejection in an unguarded handler takes the view down with it.
     */
    fun unsupported(id: String, method: String, why: String): String =
        """{"id":${quote(id)},"ok":true,"value":{"ok":false,"unsupported":true,""" +
            """"method":${quote(method)},"error":${quote(why)}}}"""

    /** JSON string escaping, plus the two JavaScript-only line breakers. */
    internal fun quote(raw: String): String {
        val out = StringBuilder(raw.length + 2)
        out.append('"')
        for (c in raw) {
            when {
                c == '"' -> out.append("\\\"")
                c == '\\' -> out.append("\\\\")
                c == '\n' -> out.append("\\n")
                c == '\r' -> out.append("\\r")
                c == '\t' -> out.append("\\t")
                c == '\b' -> out.append("\\b")
                c == FORM_FEED -> out.append("\\f")
                /* U+2028 and U+2029 are legal inside a JSON string but
                 * terminate a line in JavaScript SOURCE - and this envelope
                 * is spliced into an evaluateJavascript() call, so they
                 * would break the script rather than the parse. */
                c < ' ' || c == LINE_SEP || c == PARA_SEP ->
                    out.append("\\u").append(String.format("%04x", c.code))
                else -> out.append(c)
            }
        }
        out.append('"')
        return out.toString()
    }
}
