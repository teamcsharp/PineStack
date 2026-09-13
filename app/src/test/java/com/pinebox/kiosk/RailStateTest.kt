package com.pinebox.kiosk

import com.pinebox.kiosk.feed.FeedState
import com.pinebox.kiosk.feed.StationRows
import com.pinebox.kiosk.rail.RailState
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The rail's snapshot, and the one property the whole optimisation rests on:
 * a playhead tick must not change it.
 *
 * StationFeed emits every 250ms because it re-interpolates the playhead
 * locally between its four-second polls. If RailState changed on those ticks,
 * distinctUntilChanged would pass them through and the rail would re-bind
 * twenty-odd views four times a second on the main thread - on a device that
 * measured 21.5% janky frames before the rail existed at all.
 */
class RailStateTest {

    /** A /api/dj object shaped like the live station's, cut to what matters. */
    private fun dj(
        on: Boolean = true,
        paused: Boolean = false,
        music: String = "box",
        voice: String = "box",
        reply: String = "box",
        device: String = "nabu",
    ): JSONObject = JSONObject()
        .put("on", on)
        .put("paused", paused)
        .put("music_to", music)
        .put("voice_to", voice)
        .put("reply_to", reply)
        .put("voice_device", device)
        .put("station_name", "Pine Box FM")
        .put("nabu_music_level", 0.0)
        .put("nabu_voice_level", 1.0)
        .put("nabu_reply_level", 0.5)
        .put(
            "activity_log",
            org.json.JSONArray()
                .put(JSONObject().put("stage", "writing").put("detail", "intro"))
                .put(JSONObject().put("stage", "speaking").put("detail", "on the Nabu")),
        )

    @Test
    fun `the routing is read from the fields the station actually publishes`() {
        // Read off the live station on 2026-09-10: on=false, paused=false,
        // music_to/voice_to/reply_to=box, voice_device=nabu.
        val state = RailState.of(FeedState(station = dj(on = false)))
        assertTrue(state.connected)
        assertFalse(state.fm)
        assertFalse(state.paused)
        assertEquals("box", state.musicTo)
        assertEquals("nabu", state.voiceDevice)
        assertEquals(setOf("nabu"), state.presets)
    }

    @Test
    fun `a level the station does not publish is minus one, not zero`() {
        /* Zero is a REAL level and means silence. A missing key rendered as 0
         * would drag the operator's slider to the bottom and then, on the
         * first drag, post that silence to a real speaker. */
        val bare = JSONObject(dj().toString())
        bare.remove("nabu_music_level")
        val state = RailState.of(FeedState(station = bare))
        assertEquals(-1, state.musicLevel)
        // ...and a published zero stays zero.
        assertEquals(0, RailState.of(FeedState(station = dj())).musicLevel)
    }

    @Test
    fun `a playhead tick changes nothing the rail paints`() {
        /* THE LOAD-BEARING TEST. The feed re-derives its rows on every 250ms
         * tick from the same station object with a later clock. That produces
         * a new FeedState - different rows, different `at` - and it must
         * produce an EQUAL RailState, or distinctUntilChanged lets four
         * paints a second through. */
        val station = dj()
        val first = FeedState(station = station, rows = StationRows.of(station, 1_000L), at = 1_000L)
        val later = FeedState(station = station, rows = StationRows.of(station, 1_250L), at = 1_250L)
        assertNotEquals(first, later)
        assertEquals(RailState.of(first), RailState.of(later))
    }

    @Test
    fun `a POST answer moves the chips without waiting for the poll`() {
        // /api/dj/output answers with dj_state(), so the confirmed routing is
        // in hand at once; waiting for the 4s poll reads as a dead control.
        val before = RailState.of(FeedState(station = dj()))
        val after = before.patched(dj(music = "here", voice = "here", reply = "here", device = "pine"))
        assertEquals("here", after.musicTo)
        assertEquals(setOf("web", "app"), after.presets)
        // ...and it must not blank what the response does not carry.
        assertEquals(before.log, after.log)
    }

    @Test
    fun `a partial POST answer keeps what it does not mention`() {
        val before = RailState.of(FeedState(station = dj()))
        val after = before.patched(JSONObject().put("music_to", "off"))
        assertEquals("off", after.musicTo)
        assertEquals("box", after.voiceTo)
        assertEquals("nabu", after.voiceDevice)
    }

    @Test
    fun `the free log comes out of the feed object, newest last`() {
        val state = RailState.of(FeedState(station = dj()))
        assertEquals("writing  intro\nspeaking  on the Nabu", state.log)
    }

    @Test
    fun `the pipeline log drops the swaths`() {
        /* A single pipeline event's `extra` was measured at 1.4 kB of mined
         * source text. A rail pane is not where anyone reads those. */
        val body = JSONObject()
            .put(
                "events",
                org.json.JSONArray()
                    .put(
                        JSONObject().put("kind", "speakbox").put("text", "mined koh4.md")
                            .put("extra", "THE SWATH, word for word:\n- a very long line"),
                    )
                    .put(JSONObject().put("kind", "voice").put("text", "call coalesced")),
            )
            .toString()
        val text = RailState.pipelineLog(body)
        assertEquals("speakbox  mined koh4.md\nvoice  call coalesced", text)
    }

    @Test
    fun `no station at all is a disconnected rail carrying the reason`() {
        val state = RailState.of(FeedState(station = null, error = "timeout"))
        assertFalse(state.connected)
        assertEquals("timeout", state.error)
    }
}
