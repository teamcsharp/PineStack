package com.pinebox.kiosk.rail

import org.json.JSONObject

/**
 * The rail's "Jump to" list.
 *
 * THE POINT IS THAT NOTHING RELOADS. The operator asked to "pop up ui and
 * access scripts and logs instantly", and the slowest thing this terminal can
 * possibly do is throw the panel away and fetch it again - the panel at
 * :8096 is one very large document, and on this tablet a cold load of it is
 * seconds. So every jump that CAN be done inside the page already loaded is
 * done that way:
 *
 *   [Scene] calls `pineShow3JS(key)`, which the panel defines at
 *   app.py:135073 and which opens the scene in a pop-up frame in the CURRENT
 *   document. No navigation, no reload, no re-parse.
 *
 *   [Page] is for the two documents the station serves that are NOT the panel
 *   - `/radio` (app.py:93890) and `/journal` (app.py:129142). Those really are
 *   separate pages and really do have to be loaded.
 *
 * The fallback for a Scene is `?view=<key>`, which app.py:135063 handles - "A
 * pop-out: land on the scene rather than making the operator find it." It is
 * only used if the in-page call answers that it did not find the key, e.g.
 * against an older station.
 */
object QuickJumps {

    sealed class Jump {
        abstract val label: String

        /** Opened inside the page already loaded. Costs no navigation. */
        data class Scene(override val label: String, val key: String) : Jump()

        /** A document of its own. `path` starts with "/". */
        data class Page(override val label: String, val path: String) : Jump()
    }

    /**
     * The keys are the panel's own, taken from the desktop rail's
     * THREEJS_VIEWS list (desktop/renderer/renderer.js:1905). Trimmed to the
     * consoles an operator standing at a wall tablet actually reaches for -
     * the diagnostic ones and the two that repair something - rather than all
     * twenty-six, because a rail you have to scroll for ten seconds is not a
     * quick jump.
     */
    val ALL: List<Jump> = listOf(
        Jump.Page("○  The panel", "/"),
        Jump.Page(">  Radio", "/radio"),
        Jump.Page("📖  Request book", "/journal"),
        Jump.Scene("🎛  RapAssembly", "rapassembly"),
        Jump.Scene("🕸  Orchestrator", "orchlogic"),
        Jump.Scene("🩺  Comfy doctor", "comfydoc"),
        Jump.Scene("🏥  Services", "steward"),
        Jump.Scene("📰  The Gazette", "paper"),
        Jump.Scene("✂  Rejected lines", "rejected"),
        Jump.Scene("⏱  The half hours", "slots"),
        Jump.Scene("🧠  Dialogue Mind", "mind"),
        Jump.Scene("🗺  Station flow", "flow"),
        Jump.Scene("⬛  All scenes off", "off"),
    )

    /**
     * The JavaScript for a scene jump.
     *
     * Guarded with `typeof` because the panel installs pineShow3JS from
     * `pine3JSInstall`, which runs on DOMContentLoaded - a jump tapped during
     * a reload would otherwise be a ReferenceError in the console instead of a
     * quiet no-op. The key is JSON-quoted rather than concatenated: the keys
     * are ours today, but a key with a quote in it would be an injection into
     * the station's own page.
     */
    fun script(key: String): String {
        val quoted = JSONObject.quote(key)
        return "(function(){try{" +
            "if(typeof pineShow3JS!=='function')return 'absent';" +
            "pineShow3JS($quoted);return 'ok';" +
            "}catch(e){return 'failed:'+e}})()"
    }

    /** The pop-out fallback, app.py:135063. */
    fun viewUrl(base: String, key: String): String =
        base.trimEnd('/') + "/?view=" + key

    fun pageUrl(base: String, path: String): String =
        base.trimEnd('/') + (if (path.startsWith("/")) path else "/$path")
}
