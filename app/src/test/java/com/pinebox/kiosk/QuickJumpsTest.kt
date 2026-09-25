package com.pinebox.kiosk

import com.pinebox.kiosk.rail.QuickJumps
import org.json.JSONTokener
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The jumps. The point of these is not the string building - it is that a
 * jump must not navigate when it does not have to, and must not be able to
 * inject anything into the station's own page.
 */
class QuickJumpsTest {

    @Test
    fun `a scene jump is guarded, so a jump during a reload is a no-op`() {
        val script = QuickJumps.script("rapassembly")
        // pineShow3JS is installed from pine3JSInstall on DOMContentLoaded
        // (app.py:135069); tapping before that must not be a ReferenceError
        // in the operator's console.
        assertTrue(script.contains("typeof pineShow3JS!=='function'"))
        assertTrue(script.contains("\"rapassembly\""))
    }

    @Test
    fun `a key is a JSON literal, never a concatenation`() {
        /* The keys are ours today. A key carrying a quote would be an
         * injection into the STATION's page, which is the one page on this
         * tablet that can do anything - so the argument is asserted to be a
         * well-formed JSON string that parses back to exactly what went in,
         * rather than eyeballed for backslashes. */
        val key = "a\"; alert(1); //"
        val script = QuickJumps.script(key)
        val opens = "pineShow3JS("
        val from = script.indexOf(opens) + opens.length
        val to = script.indexOf(");return", from)
        assertTrue(from > opens.length && to > from)
        assertEquals(key, JSONTokener(script.substring(from, to)).nextValue())
    }

    @Test
    fun `the pop-out fallback is the route app_py actually handles`() {
        // app.py:135063 reads ?view= and opens that scene.
        assertEquals(
            "http://10.89.1.246:8096/?view=rapassembly",
            QuickJumps.viewUrl("http://10.89.1.246:8096/", "rapassembly"),
        )
    }

    @Test
    fun `a page url never doubles a slash`() {
        assertEquals(
            "http://10.89.1.246:8096/radio",
            QuickJumps.pageUrl("http://10.89.1.246:8096/", "/radio"),
        )
        assertEquals(
            "http://10.89.1.246:8096/journal",
            QuickJumps.pageUrl("http://10.89.1.246:8096", "journal"),
        )
    }

    @Test
    fun `every page jump names a document the station really serves`() {
        /* Confirmed against app.py: the only HTMLResponse GET routes are
         * "/" (82344), "/radio" (93890) and "/journal" (129142). Anything
         * else in this list would be a 404 on a tablet with no address bar
         * to get back from. */
        val served = setOf("/", "/radio", "/journal")
        val pages = QuickJumps.ALL.filterIsInstance<QuickJumps.Jump.Page>()
        assertTrue(pages.isNotEmpty())
        for (page in pages) assertTrue(page.path, page.path in served)
    }

    @Test
    fun `most of the list costs no navigation at all`() {
        /* The whole reason the list is shaped this way: the panel is one very
         * large document and reloading it is the slowest thing the terminal
         * can do. If this ever inverts, the rail has stopped being quick. */
        val scenes = QuickJumps.ALL.count { it is QuickJumps.Jump.Scene }
        assertTrue("$scenes scenes of ${QuickJumps.ALL.size}", scenes * 2 > QuickJumps.ALL.size)
    }

    @Test
    fun `no jump is listed twice`() {
        assertEquals(QuickJumps.ALL.size, QuickJumps.ALL.map { it.label }.toSet().size)
    }
}
