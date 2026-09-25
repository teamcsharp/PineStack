package com.pinebox.kiosk

import com.pinebox.kiosk.config.HotCornerPrefs
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class HotCornerPrefsTest {

    @Test
    fun `new corner precision settings have restrained defaults`() {
        val prefs = HotCornerPrefs()
        assertEquals(42, prefs.activationZonePx)
        assertEquals(50, prefs.sensitivity)
    }

    @Test
    fun `precision settings are bounded before storage or the touch road sees them`() {
        val prefs = HotCornerPrefs().merged(JSONObject()
            .put("activationZonePx", 999)
            .put("sensitivity", -12))

        assertEquals(120, prefs.activationZonePx)
        assertEquals(0, prefs.sensitivity)
        assertEquals(120, prefs.toJson().getInt("activationZonePx"))
        assertEquals(0, prefs.toJson().getInt("sensitivity"))
    }
}
