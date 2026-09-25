package com.pinebox.kiosk

import com.pinebox.kiosk.net.KeyDiscovery
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The self-provisioning road. If this regex stops matching, the terminal
 * comes up with no bearer and every write route starts answering 401 - so
 * the shapes the station actually emits are pinned here.
 */
class KeyDiscoveryTest {

    @Test
    fun `lifts the key out of a panel page`() {
        val html = """
            <script>
            const params = new URLSearchParams(location.search);
            const SERVER_KEY = "a1b2c3d4e5f6";
            const KEY = params.get("key") || SERVER_KEY || "";
            </script>
        """.trimIndent()
        assertEquals("a1b2c3d4e5f6", KeyDiscovery.extract(html))
    }

    @Test
    fun `tolerates the spacing the station actually emits`() {
        assertEquals("k", KeyDiscovery.extract("""const SERVER_KEY="k";"""))
        assertEquals("k", KeyDiscovery.extract("""const   SERVER_KEY   =   "k"   ;"""))
        assertEquals("k", KeyDiscovery.extract("const\tSERVER_KEY\t=\t\"k\";"))
    }

    /**
     * The value is embedded with json.dumps (app.py:82308), so it is a JSON
     * string literal and can carry escapes. A naive "([^"]*)" would stop at
     * the backslash-quote and hand back half a key.
     */
    @Test
    fun `handles an escaped quote inside the key`() {
        val html = """const SERVER_KEY = "ab\"cd";"""
        assertEquals("ab\"cd", KeyDiscovery.extract(html))
    }

    @Test
    fun `handles backslashes and unicode escapes`() {
        assertEquals("a\\b", KeyDiscovery.extract("""const SERVER_KEY = "a\\b";"""))
        assertEquals("a\nb", KeyDiscovery.extract("""const SERVER_KEY = "a\nb";"""))
        // The INPUT carries a literal backslash-u escape; the raw string
        // keeps it as text, which is exactly what the station emits.
        assertEquals("aXb", KeyDiscovery.extract("""const SERVER_KEY = "a\u0058b";"""))
    }

    /** The station renders "" when no key is configured. Same as absent. */
    @Test
    fun `an empty key is not a key`() {
        assertNull(KeyDiscovery.extract("""const SERVER_KEY = "";"""))
    }

    @Test
    fun `no match at all`() {
        assertNull(KeyDiscovery.extract("<html><body>nothing here</body></html>"))
        assertNull(KeyDiscovery.extract(""))
        assertNull(KeyDiscovery.extract(null))
    }

    /** The un-substituted template must not be mistaken for a key. */
    @Test
    fun `the unrendered placeholder is not a key`() {
        assertNull(KeyDiscovery.extract("const SERVER_KEY = __SERVER_KEY__;"))
    }

    /**
     * Some station pages define the constant more than once across their
     * inline scripts. First one wins, the way Electron's road does.
     */
    @Test
    fun `takes the first of several`() {
        val html = """
            const SERVER_KEY = "first";
            const SERVER_KEY = "second";
        """.trimIndent()
        assertEquals("first", KeyDiscovery.extract(html))
    }
}
