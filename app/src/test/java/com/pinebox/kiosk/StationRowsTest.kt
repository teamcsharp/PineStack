package com.pinebox.kiosk

import com.pinebox.kiosk.feed.StationRows
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The feed row model - the Kotlin port of
 * desktop/renderer/lcd-dialogue.js `stationRows`.
 *
 * The terminal and the LCD must agree about what is on air, so the cases
 * pinned here are the ones where the two could quietly diverge.
 */
class StationRowsTest {

    private fun station(build: JSONObject.() -> Unit): JSONObject =
        JSONObject().apply(build)

    private fun chat(vararg rows: JSONObject): JSONArray =
        JSONArray().also { arr -> rows.forEach { arr.put(it) } }

    private fun row(
        id: String,
        text: String,
        kind: String = "line",
        aired: String? = null,
        who: String = "dj",
    ): JSONObject = JSONObject()
        .put("id", id)
        .put("text", text)
        .put("kind", kind)
        .put("who", who)
        .also { if (aired != null) it.put("aired", aired) }

    @Test
    fun `no station means no rows`() {
        assertTrue(StationRows.of(null, 0L).isEmpty())
        assertTrue(StationRows.of(JSONObject(), 0L).isEmpty())
    }

    @Test
    fun `chat rows come through in the order the station sent them`() {
        val s = station {
            put("chat", chat(row("a", "first"), row("b", "second"), row("c", "third")))
        }
        val rows = StationRows.of(s, 0L)
        assertEquals(listOf("a", "b", "c"), rows.map { it.id })
        assertEquals("first", rows[0].text)
    }

    /**
     * The station puts bookkeeping through the same channel as speech. None
     * of it is a line and none of it should reach a terminal someone reads.
     */
    @Test
    fun `bookkeeping kinds are dropped`() {
        val s = station {
            put(
                "chat",
                chat(
                    row("a", "real line"),
                    row("t1", "ignored", kind = "tick"),
                    row("s1", "ignored", kind = "seen"),
                    row("p1", "ignored", kind = "ping"),
                    row("h1", "ignored", kind = "heartbeat"),
                ),
            )
        }
        assertEquals(listOf("a"), StationRows.of(s, 0L).map { it.id })
    }

    @Test
    fun `a row with no text or no id is not a row`() {
        val s = station {
            put(
                "chat",
                chat(
                    row("a", "kept"),
                    row("b", ""),
                    JSONObject().put("text", "no id here"),
                ),
            )
        }
        assertEquals(listOf("a"), StationRows.of(s, 0L).map { it.id })
    }

    @Test
    fun `the status ladder matches the LCD word for word`() {
        assertEquals("Playing", StationRows.label("airing"))
        assertEquals("Aired", StationRows.label("box"))
        assertEquals("Aired", StationRows.label("stream"))
        assertEquals("Aired", StationRows.label("both"))
        assertEquals("Recorded / waiting", StationRows.label("prepared"))
        assertEquals("Awaiting playback", StationRows.label("published"))
        assertEquals("Awaiting playback", StationRows.label("page"))
        assertEquals("Audio failed", StationRows.label("failed"))
        assertEquals("Booth activity", StationRows.label(""))
        assertEquals("Booth activity", StationRows.label("something new"))
    }

    @Test
    fun `audio is inferred from aired state or an explicit url`() {
        val s = station {
            put(
                "chat",
                chat(
                    row("a", "went out", aired = "box"),
                    row("b", "not yet", aired = "published"),
                    row("c", "has a clip").put("clip_url", "/media/c.mp3"),
                    row("d", "has audio").put("audio_url", "/media/d.mp3"),
                ),
            )
        }
        val byId = StationRows.of(s, 0L).associateBy { it.id }
        assertTrue(byId.getValue("a").hasAudio)
        assertFalse(byId.getValue("b").hasAudio)
        assertTrue(byId.getValue("c").hasAudio)
        assertTrue(byId.getValue("d").hasAudio)
    }

    /**
     * THE CASE THE RENDERER GETS WRONG.
     *
     * /api/dj serialises a stream_now turn as {id, from, until} only -
     * app.py:25295 drops who/kind/text on the way out. lcd-dialogue.js then
     * guards with `if (live?.id && live.text)`, which can never be true for
     * a coalesced round, so nothing is marked Playing for most of the show.
     * The port takes the text from the chat row of the same id instead.
     */
    @Test
    fun `the airing turn is found and takes its text from chat`() {
        val at = 1_700_000_000.0
        val s = station {
            put("chat", chat(row("a", "first line"), row("b", "second line")))
            put(
                "stream_now",
                JSONObject()
                    .put("at", at)
                    .put("length", 20.0)
                    .put(
                        "rows",
                        JSONArray()
                            .put(JSONObject().put("id", "a").put("from", 0.0).put("until", 8.0))
                            .put(JSONObject().put("id", "b").put("from", 8.0).put("until", 20.0)),
                    ),
            )
        }

        // Ten seconds into the round: the SECOND turn is sounding.
        val rows = StationRows.of(s, ((at + 10.0) * 1000).toLong())
        val playing = rows.singleOrNull { it.isPlaying }
        assertNotNull("something must be marked Playing", playing)
        assertEquals("b", playing!!.id)
        assertEquals("second line", playing.text)
        assertEquals("Playing", playing.status)
        assertTrue(playing.hasAudio)

        // The speaker stays visible LAST, so a scrolled view keeps it in
        // sight without the list reordering under the reader.
        assertEquals("b", rows.last().id)
        assertEquals(2, rows.size)
    }

    @Test
    fun `a round that has finished leaves nobody playing`() {
        val at = 1_700_000_000.0
        val s = station {
            put("chat", chat(row("a", "first line")))
            put(
                "stream_now",
                JSONObject().put("at", at).put("length", 8.0).put(
                    "rows",
                    JSONArray().put(JSONObject().put("id", "a").put("from", 0.0).put("until", 8.0)),
                ),
            )
        }
        // Past length + the four-second grace the station itself allows.
        val rows = StationRows.of(s, ((at + 13.0) * 1000).toLong())
        assertTrue(rows.none { it.isPlaying })
    }

    /**
     * When no coalesced round is running, speaking_now is the live row -
     * and it DOES carry text (app.py:25065), so it stands on its own.
     */
    @Test
    fun `speaking_now carries the live row when there is no stream`() {
        val s = station {
            put("chat", chat(row("a", "older"), row("z", "the live one")))
            put(
                "speaking_now",
                JSONObject().put("id", "z").put("text", "the live one")
                    .put("who", "dj").put("kind", "call"),
            )
        }
        val rows = StationRows.of(s, 0L)
        assertEquals("z", rows.last().id)
        assertTrue(rows.last().isPlaying)
        assertEquals("Playing", rows.last().status)
        assertEquals(2, rows.size)
    }

    /** A later chat row for the same id updates the earlier one in place. */
    @Test
    fun `a repeated id merges rather than duplicating`() {
        val s = station {
            put(
                "chat",
                chat(
                    row("a", "draft", aired = "published"),
                    row("a", "final", aired = "box"),
                ),
            )
        }
        val rows = StationRows.of(s, 0L)
        assertEquals(1, rows.size)
        assertEquals("final", rows[0].text)
        assertEquals("Aired", rows[0].status)
    }
}
