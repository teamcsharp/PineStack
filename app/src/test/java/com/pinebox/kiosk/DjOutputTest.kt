package com.pinebox.kiosk

import com.pinebox.kiosk.rail.DjOutput
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The rail's payloads, checked against the station's own handler.
 *
 * These are not tests of Kotlin. They are the record of what app.py:93359
 * accepts, kept somewhere a build can fail: the handler answers 400 with
 * `detail: "box, here, both, nabu or off"` for a value outside its `valid`
 * tuple, and a terminal that learns that from a round trip shows the operator
 * a red note for a mistake that was in the APK all along.
 */
class DjOutputTest {

    @Test
    fun `the route list is the station's own tuple`() {
        // app.py:93383  valid = ("box", "here", "both", "off", "nabu")
        assertEquals(setOf("box", "here", "both", "off", "nabu"), DjOutput.ROUTES)
    }

    @Test
    fun `a stream body carries exactly one key`() {
        val body = JSONObject(DjOutput.stream("music", "here"))
        assertEquals(1, body.length())
        assertEquals("here", body.getString("music"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `a route the station would refuse never leaves the tablet`() {
        DjOutput.stream("music", "speaker")
    }

    @Test(expected = IllegalArgumentException::class)
    fun `there is no fourth stream`() {
        DjOutput.stream("sfx", "here")
    }

    @Test
    fun `the presets are the desktop's, field for field`() {
        // desktop/renderer/renderer.js:62
        val nabu = JSONObject(DjOutput.preset("nabu"))
        assertEquals("box", nabu.getString("music"))
        assertEquals("box", nabu.getString("voice"))
        assertEquals("box", nabu.getString("reply"))
        assertEquals("nabu", nabu.getString("voice_device"))
        assertTrue(nabu.getBoolean("box_talk"))

        val box = JSONObject(DjOutput.preset("box"))
        assertEquals("pine", box.getString("voice_device"))

        // #979: Application means ALL of it, here - music included. It was
        // "off", and that is recorded there as why the speaker sat silent
        // between rounds.
        val app = JSONObject(DjOutput.preset("app"))
        assertEquals("here", app.getString("music"))
        assertEquals("here", app.getString("voice"))
        assertEquals("here", app.getString("reply"))
        assertFalse(app.getBoolean("box_talk"))
    }

    @Test
    fun `web and app never name a device`() {
        /* #814: "web/app route audio to the PAGE - they must not silently
         * re-point the core DEVICE at the retired pine satellite." And an
         * EMPTY voice_device would be worse than none: the handler validates
         * it as "pine or nabu" when the key is present (app.py:93395). */
        for (key in listOf("web", "app")) {
            assertFalse(key, JSONObject(DjOutput.preset(key)).has("voice_device"))
        }
    }

    @Test
    fun `a level is clamped and rounded`() {
        assertEquals(0.35, JSONObject(DjOutput.level("music", 0.3499999)).getDouble("music_level"), 1e-9)
        assertEquals(1.0, JSONObject(DjOutput.level("voice", 4.0)).getDouble("voice_level"), 1e-9)
        assertEquals(0.0, JSONObject(DjOutput.level("reply", -2.0)).getDouble("reply_level"), 1e-9)
    }

    @Test
    fun `a level body names the stream the handler expects`() {
        assertTrue(JSONObject(DjOutput.level("reply", 0.5)).has("reply_level"))
    }

    @Test
    fun `the lit chip follows the station, and box and nabu are told apart`() {
        /* The two differ ONLY in voice_device. Ignoring it would light
         * "Pine Box" on every Nabu station, which is the one mistake an
         * operator reading this rail from across the room would act on. */
        assertEquals(setOf("nabu"), DjOutput.presetsOf("box", "box", "box", "nabu"))
        assertEquals(setOf("box"), DjOutput.presetsOf("box", "box", "box", "pine"))
    }

    @Test
    fun `web and app are the same routing, so both light`() {
        // They are identical rows, here and in the desktop's EMBEDDED_ROUTES
        // (renderer.js:83). Picking one would be a claim the station never made.
        assertEquals(setOf("web", "app"), DjOutput.presetsOf("here", "here", "here", "pine"))
    }

    @Test
    fun `three streams moved apart light no preset at all`() {
        // #980: "keep the music on the box, bring the DJs here" is a real
        // state, and lighting a preset that is no longer true is worse than
        // lighting none.
        assertTrue(DjOutput.presetsOf("box", "here", "here", "pine").isEmpty())
        assertTrue(DjOutput.presetsOf("off", "box", "box", "pine").isEmpty())
    }
}
