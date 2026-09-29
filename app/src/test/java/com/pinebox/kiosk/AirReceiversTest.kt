package com.pinebox.kiosk

import com.pinebox.kiosk.rail.AirReceivers
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [airplayers] Playing it as a SET of receivers: what the station's answer
 * reads as, what a tap looks like before the answer, and the words.
 * The shape is GET /api/air/receivers as app.py's air_receivers_state
 * builds it, on the house measured 2026-09-29 with the DJs on the Nabu.
 */
class AirReceiversTest {

    private val STATE = """
        {"active":"pinetab","owner":"","rescued":false,
         "say":"sounding: PineTab, Web pages, Nabu - PineTab is the active radio",
         "receivers":[
          {"id":"pinetab","kind":"page","label":"PineTab","audible":true,"sounding":true,
           "present":true,"active":true,"owns_air":false,
           "detail":"10.89.1.154 · 0s ago","heard_ago":0.7},
          {"id":"desktop","kind":"page","label":"This app","audible":false,"sounding":false,
           "present":true,"active":false,"owns_air":false,
           "detail":"10.89.1.13 · 2 tabs · 1s ago","heard_ago":null},
          {"id":"web","kind":"page","label":"Web pages","audible":true,"sounding":true,
           "present":true,"active":false,"owns_air":false,"detail":"8s ago","heard_ago":null},
          {"id":"car","kind":"page","label":"Car / tune-in","audible":true,"sounding":false,
           "present":false,"active":false,"owns_air":false,"detail":"not open","heard_ago":null},
          {"id":"nabu","kind":"speaker","label":"Nabu","audible":true,"sounding":true,
           "present":true,"active":false,"owns_air":false,
           "detail":"carries the DJs, replies","heard_ago":3.0},
          {"id":"box","kind":"speaker","label":"Pine Box speaker","audible":false,
           "sounding":false,"present":true,"active":false,"owns_air":false,
           "detail":"not sent to","heard_ago":null}]}
    """.trimIndent()

    private fun state() = AirReceivers.read(JSONObject(STATE))!!

    @Test
    fun everyReceiverIsListedNabuIncluded() {
        val s = state()
        assertEquals(listOf("pinetab", "desktop", "web", "car", "nabu", "box"),
            s.receivers.map { it.id })
        assertTrue(s.of("nabu")!!.audible)
        assertEquals("pinetab", s.active)
        assertTrue(s.of("pinetab")!!.active)
        assertNull(s.of("desktop")!!.heardAgo)
        assertEquals(0.7, s.of("pinetab")!!.heardAgo!!, 1e-9)
    }

    @Test
    fun aStationWithoutTheRouteReadsAsNull() {
        assertNull(AirReceivers.read(JSONObject("""{"detail":"Not Found"}""")))
    }

    @Test
    fun bodiesAreWhatTheStationValidates() {
        val flip = JSONObject(AirReceivers.flip("nabu", false))
        assertEquals("nabu", flip.getString("id"))
        assertFalse(flip.getBoolean("audible"))
        assertEquals(2, flip.length())
        val only = JSONObject(AirReceivers.only("pinetab"))
        assertEquals("pinetab", only.getString("only"))
        assertEquals(1, only.length())
    }

    @Test
    fun aTapMovesTheSwitchBeforeTheAnswer() {
        val s = AirReceivers.optimistic(state(), "nabu", false)
        assertFalse(s.of("nabu")!!.audible)
        assertTrue(s.of("pinetab")!!.audible)
        assertEquals("switching off… · carries the DJs, replies · heard 3s ago",
            AirReceivers.detail(s.of("nabu")!!, pending = true))
    }

    @Test
    fun theOperatorsStateIsOneOnlyTapAndTheCarKeepsItsSwitch() {
        val s = AirReceivers.optimisticOnly(state(), "pinetab")
        assertEquals("pinetab+* desktop- web- car+ nabu- box-", AirReceivers.summary(s))
        assertEquals(setOf("pinetab", "desktop", "web", "nabu", "box"),
            AirReceivers.touched(s, "pinetab", only = true))
    }

    @Test
    fun aRefusalIsSaidInWords() {
        val refused = JSONObject(STATE)
            .put("refused", "pinetab")
            .put("why", "that would leave nothing sounding the station - switch another receiver on first")
        assertEquals("refused: that would leave nothing sounding the station - switch another receiver on first",
            AirReceivers.note(AirReceivers.read(refused)!!))
        assertEquals("sounding: PineTab, Web pages, Nabu - PineTab is the active radio",
            AirReceivers.note(state()))
    }
}
