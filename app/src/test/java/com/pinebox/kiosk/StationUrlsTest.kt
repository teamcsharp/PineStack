package com.pinebox.kiosk

import com.pinebox.kiosk.net.StationUrls
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * URL building against the routes that actually exist on the station.
 *
 * These are pinned rather than trusted because a wrong route on a terminal
 * with no address bar shows up as an empty panel and nothing else.
 */
class StationUrlsTest {

    private val base = "http://10.89.1.246:8096"

    @Test
    fun `a trailing slash on the base never doubles up`() {
        assertEquals("$base/api/dj", StationUrls.dj(base))
        assertEquals("$base/api/dj", StationUrls.dj("$base/"))
        assertEquals("$base/api/dj", StationUrls.dj("$base///"))
        assertEquals("$base/api/dj", StationUrls.dj("  $base/  "))
    }

    @Test
    fun `the documented routes`() {
        assertEquals("$base/api/dj", StationUrls.dj(base))
        assertEquals("$base/api/dj/provenance/a1b2", StationUrls.provenance(base, "a1b2"))
        assertEquals("$base/api/airlog", StationUrls.airlog(base))
        assertEquals("$base/api/dj/sfx", StationUrls.djSfx(base))
        assertEquals("$base/api/sfx/stats", StationUrls.sfxStats(base))
        assertEquals("$base/api/generations", StationUrls.generations(base))
        assertEquals(
            "$base/api/generations/image/pine-001.png",
            StationUrls.generationImage(base, "pine-001.png"),
        )
    }

    @Test
    fun `the booth clip carries both parameters`() {
        assertEquals(
            "$base/api/booth/clip?line=abc123&whole=0",
            StationUrls.boothClip(base, "abc123"),
        )
        assertEquals(
            "$base/api/booth/clip?line=abc123&whole=1",
            StationUrls.boothClip(base, "abc123", whole = true),
        )
    }

    /**
     * The cache-buster is not decoration. Without `t` a re-cued track can
     * come back out of the WebView's HTTP cache, and the terminal plays the
     * previous rendering of a line the station has already replaced.
     */
    @Test
    fun `music and media carry the cache buster`() {
        assertEquals("$base/music/track-9?t=1700000000", StationUrls.music(base, "track-9", 1700000000L))
        assertEquals("$base/media/round_88.mp3?t=42", StationUrls.media(base, "round_88.mp3", 42L))
    }

    /**
     * Ids come from the station and are usually tame, but "usually" is not
     * a guarantee, and a raw space in a path is a malformed request line.
     */
    @Test
    fun `path segments are percent encoded, not form encoded`() {
        val url = StationUrls.provenance(base, "a b/c?d#e")
        assertEquals("$base/api/dj/provenance/a%20b%2Fc%3Fd%23e", url)
        // A space must NEVER become '+' in a path: that is a literal plus.
        assertFalse(url.contains('+'))
    }

    @Test
    fun `query values are percent encoded too`() {
        val url = StationUrls.boothClip(base, "id with space&whole=1")
        assertTrue(url.contains("line=id%20with%20space%26whole%3D1"))
        // The real `whole` parameter must still be the last word on it.
        assertTrue(url.endsWith("&whole=0"))
    }

    @Test
    fun `non-ascii survives as utf-8`() {
        // The station's ids are ascii today; this is here so that the day
        // one is not, the terminal sends something the server can decode.
        assertEquals("$base/media/caf%C3%A9?t=1", StationUrls.media(base, "café", 1L))
    }
}
