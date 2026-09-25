package com.pinebox.kiosk

import com.pinebox.kiosk.rail.AirOwners
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The device list in the drawer: who is playing the show, and what a tap does.
 *
 * These are written against the shapes the station actually returns, copied
 * from a live call rather than imagined - including the case that started
 * this, three players on one broadcast with nobody holding the air.
 */
class AirOwnersTest {

    private val LISTENERS = """
        {"audio_owner":"",
         "listeners":[
           {"listener":"desktop-lshe6j9c","seen":0.8,"since":11.8,
            "addr":"10.89.1.13","what":"a browser tab","owns_air":false},
           {"listener":"pbvczrd67t","seen":0.8,"since":12.2,
            "addr":"10.89.1.13","what":"a browser tab","owns_air":false},
           {"listener":"pbnvgdtefn","seen":0.5,"since":11.0,
            "addr":"10.89.1.154","what":"a browser tab","owns_air":false}],
         "say":"3 players are on this broadcast"}
    """.trimIndent()

    private val SETTINGS = """
        {"terminals":{
           "pinetab":{"name":"PineTab","play":true,"addr":"10.89.1.154",
                      "music":0.8,"voice":1.0,"reply":1.0},
           "desktop":{"name":"This app","play":false,"addr":"10.89.1.13",
                      "fallback":true,"music":0.6,"voice":0.6,"reply":0.6}}}
    """.trimIndent()

    private fun roster(listeners: String = LISTENERS, settings: String? = SETTINGS) =
        AirOwners.read(JSONObject(listeners), settings?.let { JSONObject(it) })

    @Test
    fun `every player on the broadcast is listed`() {
        val out = roster()
        assertEquals(3, out.players.size)
        assertTrue(out.players.none { it.owns })
        assertEquals("", out.owner)
    }

    @Test
    fun `a player is named by its device, not its listener id`() {
        val tab = roster().of("pbnvgdtefn")!!
        assertEquals("PineTab", tab.label)
        assertEquals("pinetab", tab.device)
        assertTrue(tab.detail.contains("10.89.1.154"))
    }

    @Test
    fun `a player with no device row still shows something a person can place`() {
        val out = AirOwners.read(JSONObject(LISTENERS), null)
        assertEquals("10.89.1.13", out.of("desktop-lshe6j9c")!!.label)
    }

    @Test
    fun `the one holding the air sorts first and is the only one sounding`() {
        val held = LISTENERS.replace("\"audio_owner\":\"\"", "\"audio_owner\":\"pbnvgdtefn\"")
        val out = roster(held)
        assertEquals("pbnvgdtefn", out.players[0].listener)
        assertTrue(out.players[0].owns)
        assertEquals(1, out.players.count { it.owns })
        assertTrue(AirOwners.note(out).contains("only PineTab"))
    }

    @Test
    fun `checking a player hands it the air`() {
        val tab = roster().of("pbnvgdtefn")!!
        assertEquals("""{"listener":"pbnvgdtefn"}""", AirOwners.tap(tab))
    }

    @Test
    fun `unchecking the one that has it lets everybody play again`() {
        /* Not silence. A tablet that mutes the whole house with one tap and
         * gives no clue why is worse than one that plays in two rooms. */
        val held = LISTENERS.replace("\"audio_owner\":\"\"", "\"audio_owner\":\"pbnvgdtefn\"")
        val tab = roster(held).of("pbnvgdtefn")!!
        assertEquals("""{"clear":true}""", AirOwners.tap(tab))
    }

    @Test
    fun `the note says what is true, not what was asked for`() {
        assertTrue(AirOwners.note(roster()).contains("all sounding at once"))
        assertEquals("nothing is listening", AirOwners.note(AirOwners.Roster()))
    }

    @Test
    fun `the table says the tablet should hold the air`() {
        assertEquals("pbnvgdtefn", AirOwners.shouldOwn(roster(), JSONObject(SETTINGS)))
    }

    @Test
    fun `turning the tablet off hands the air to the fallback`() {
        /* The tablet is gone from the roster entirely - switched off, not
         * switched over. This is the operator's second trigger. */
        val without = """
            {"audio_owner":"",
             "listeners":[
               {"listener":"desktop-lshe6j9c","seen":0.8,"since":11.8,
                "addr":"10.89.1.13","what":"a browser tab","owns_air":false}],
             "say":"one player, no overlap possible"}
        """.trimIndent()
        val out = AirOwners.read(JSONObject(without), JSONObject(SETTINGS))
        assertEquals(1, out.players.size)
        assertEquals("desktop-lshe6j9c", AirOwners.shouldOwn(out, JSONObject(SETTINGS)))
    }

    @Test
    fun `switching the tablet's broadcast off hands it over too`() {
        val off = SETTINGS.replace("\"play\":true", "\"play\":false")
            .replaceFirst("\"play\":false,\"addr\":\"10.89.1.13\"",
                "\"play\":true,\"addr\":\"10.89.1.13\"")
        assertEquals("desktop-lshe6j9c",
            AirOwners.shouldOwn(roster(settings = off), JSONObject(off)))
    }

    @Test
    fun `two devices switched on is resolved to one, not left alone`() {
        /* "Individually but never at the same time." Abstaining here was the
         * worst of the three options: it left the air wherever it happened to
         * be while two rooms played a half-second apart. Resolved by id order,
         * the same rule terminal-audio.cjs uses, so both ends agree without
         * talking to each other. */
        val both = SETTINGS.replaceFirst("\"play\":false", "\"play\":true")
        val out = AirOwners.shouldOwn(roster(settings = both), JSONObject(both))
        assertEquals("desktop-lshe6j9c", out)
    }

    @Test
    fun `no terminals table means no opinion at all`() {
        assertEquals("", AirOwners.shouldOwn(roster(settings = null), JSONObject("{}")))
    }

    @Test
    fun `a device is matched by its listener id ahead of its address`() {
        /* Two tabs on one machine share an address; only the id tells them
         * apart, so a row that names one must win. */
        val pinned = SETTINGS.replace(
            "\"desktop\":{\"name\":\"This app\",\"play\":false,\"addr\":\"10.89.1.13\"",
            "\"desktop\":{\"name\":\"This app\",\"play\":false," +
                "\"listener\":\"pbvczrd67t\",\"addr\":\"10.89.1.13\""
        )
        val out = roster(settings = pinned)
        assertEquals("desktop", out.of("pbvczrd67t")!!.device)
        assertEquals("", out.of("desktop-lshe6j9c")!!.device)
    }
}
