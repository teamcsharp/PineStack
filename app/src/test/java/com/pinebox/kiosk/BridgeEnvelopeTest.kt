package com.pinebox.kiosk

import com.pinebox.kiosk.bridge.BridgeEnvelope
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The promise bridge's wire format.
 *
 * Worth testing on the JVM because the failure mode on the device is
 * silent: a malformed envelope means __pineBridgeSettle throws inside an
 * evaluateJavascript with a null callback, so the promise never settles,
 * the panel spins, and nothing appears in logcat.
 */
class BridgeEnvelopeTest {

    @Test
    fun `an ack carries the id and is parseable`() {
        val ack = JSONObject(BridgeEnvelope.accepted("r7-1699999999"))
        assertTrue(ack.getBoolean("accepted"))
        assertEquals("r7-1699999999", ack.getString("id"))
    }

    @Test
    fun `a refusal says why and is not accepted`() {
        val ack = JSONObject(BridgeEnvelope.refused("no such bridge method: frobnicate"))
        assertFalse(ack.getBoolean("accepted"))
        assertEquals("no such bridge method: frobnicate", ack.getString("error"))
    }

    /**
     * The station's answer is spliced in as RAW JSON rather than re-encoded
     * - the whole point of building this by string. Round-tripping proves
     * the splice produces a valid document.
     */
    @Test
    fun `an ok envelope splices raw json through untouched`() {
        val stationSaid = """{"speaking":true,"chat":[{"id":"a1","text":"hello"}]}"""
        val env = JSONObject(BridgeEnvelope.ok("r1", stationSaid))
        assertEquals("r1", env.getString("id"))
        assertTrue(env.getBoolean("ok"))
        val value = env.getJSONObject("value")
        assertTrue(value.getBoolean("speaking"))
        assertEquals("hello", value.getJSONArray("chat").getJSONObject(0).getString("text"))
    }

    /** A 204 or an empty body must resolve, not break the envelope. */
    @Test
    fun `an empty body becomes json null`() {
        val env = JSONObject(BridgeEnvelope.ok("r2", ""))
        assertTrue(env.getBoolean("ok"))
        assertTrue(env.isNull("value"))
        assertTrue(JSONObject(BridgeEnvelope.ok("r2", null)).isNull("value"))
        assertTrue(JSONObject(BridgeEnvelope.ok("r2", "   ")).isNull("value"))
    }

    @Test
    fun `a raw array is a legal value too`() {
        val env = JSONObject(BridgeEnvelope.ok("r3", """[1,2,3]"""))
        assertEquals(3, env.getJSONArray("value").length())
    }

    @Test
    fun `string and boolean values`() {
        assertEquals("", JSONObject(BridgeEnvelope.okString("r4", null)).getString("value"))
        assertEquals("log line", JSONObject(BridgeEnvelope.okString("r4", "log line")).getString("value"))
        assertTrue(JSONObject(BridgeEnvelope.okBoolean("r5", true)).getBoolean("value"))
        assertFalse(JSONObject(BridgeEnvelope.okBoolean("r5", false)).getBoolean("value"))
    }

    @Test
    fun `an error envelope is not ok and always says something`() {
        val env = JSONObject(BridgeEnvelope.error("r6", "401 from the station"))
        assertFalse(env.getBoolean("ok"))
        assertEquals("401 from the station", env.getString("error"))

        // A driver that throws with a null message must not produce an
        // envelope whose `error` is missing - the shim would then reject
        // with "undefined".
        val blank = JSONObject(BridgeEnvelope.error("r6", null))
        assertTrue(blank.getString("error").isNotBlank())
        assertTrue(JSONObject(BridgeEnvelope.error("r6", "  ")).getString("error").isNotBlank())
    }

    /** The refusals the panel is meant to SHOW, not throw on. */
    @Test
    fun `unsupported resolves with an ok false value`() {
        val env = JSONObject(BridgeEnvelope.unsupported("r8", "lcdStart", "no LCD here"))
        assertTrue("the promise must RESOLVE", env.getBoolean("ok"))
        val value = env.getJSONObject("value")
        assertFalse(value.getBoolean("ok"))
        assertTrue(value.getBoolean("unsupported"))
        assertEquals("lcdStart", value.getString("method"))
        assertEquals("no LCD here", value.getString("error"))
    }

    /**
     * The settlement is passed into evaluateJavascript as a STRING
     * argument, so the envelope is quoted a second time. Anything that
     * would end a JavaScript string or a JavaScript LINE has to survive
     * both trips.
     */
    @Test
    fun `quoting survives the double trip into evaluateJavascript`() {
        val nasty = "he said \"no\"\nand a \\ and a </script> and a \u2028 line break"
        val once = BridgeEnvelope.quote(nasty)
        // Once quoted it is a legal JSON string literal.
        assertEquals(nasty, JSONObject("{\"v\":$once}").getString("v"))
        // Twice quoted it is still legal - which is the shape actually sent.
        val twice = BridgeEnvelope.quote(once)
        assertEquals(once, JSONObject("{\"v\":$twice}").getString("v"))
        // And the JS line terminators are gone from the wire form.
        assertFalse(once.contains('\u2028'))
        assertFalse(once.contains('\u2029'))
        assertFalse(once.contains('\n'))
    }

    @Test
    fun `an id with a quote in it cannot break out`() {
        val env = JSONObject(BridgeEnvelope.ok("""r9"); alert(1); //""", "null"))
        assertEquals("""r9"); alert(1); //""", env.getString("id"))
    }
}
