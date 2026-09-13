package com.pinebox.kiosk.bridge

import android.content.Context
import org.json.JSONObject

/**
 * THE OTHER VIEWS, AND THE TABS THAT REACH THEM.
 *
 * "So where are the tabs on the side of the pine tab view representing my
 * other views?"
 *
 * All three of the operator's sketches draw the same switcher, and on the
 * desktop it is the app's own tab rail. The tablet has no such rail: its
 * shell is a WebView showing the station's panel, and the panel has never
 * heard of Script, Listen, Music or Presentation. So the views and a rail to
 * reach them are welded onto the page from a document-start script, exactly
 * the way [SamplerAssets] already does it for the sampler.
 *
 * ORDER MATTERS, as it does there. A view's model must be evaluated before
 * the view that reads it, or the view's IIFE closes over an undefined
 * global and fails silently at mount time rather than at load time.
 *
 * WHY IT IS ONE BUNDLE. Each file is an IIFE with its own module scope.
 * Evaluating them twice builds a SECOND set, overwriting the globals while
 * the first set's feed subscriptions are still live and now unreachable -
 * leaked pollers against a station with a documented history of being
 * starved by chatty clients. `onPageFinished` can fire more than once for a
 * single page, so the guard is not hypothetical.
 *
 * NOTHING IS MOUNTED HERE. rail.js builds the tabs and mounts a view the
 * first time its tab is pressed. The tablet was measured at 148 MB free
 * under a load average of 25, and two of these views are WebGL; building
 * five of them at boot would spend all of that before the operator had
 * asked for any of them.
 */
object ViewAssets {

    private const val DIR = "pine-views"

    /** Evaluated in this order: models first, then the views that read them. */
    private val SCRIPTS = listOf(
        "pine-logo.js",           // the mark, inline - origins forbid a URL
        "boot-splash.js",         // the logo assembling itself at startup
        "pine-dismiss.js",        // tap away and a panel closes - one rule
        "view-chrome.js",         // the shared bar, tree and transport
        "console-line.js",        // the one-line backend readout, all screens
        "console-trace.js",       // tap that line: where the work came from
        "audio-law.js",           // ONE door to every level and route
        "talk-dot.js",            // the dot you speak commands into
        "vote-arrows.js",         // love it or not, on every player
        "listen-model.js",        // the arithmetic Listen and Music share
        "pine-meters.js",         // real levels off the real audio
        "script-lineage.js",      // reads one provenance payload
        "script-stage.js",        // the 3D presentation of it
        "script.js",              // the Script view
        "script-page.js",         // the Script view built to the sketch
        "listen.js",
        "music.js",
        "wall-transition.js",     // what the wall shows between clips
        "video-wall.js",          // the gallery loop Presentation shows
        "presentation-source.js", // its one-request-wide traffic gate
        "presentation.js",
        "busy.js",                // a working bar on whatever is working
        "three-full.js",          // every 3JS scene, full screen on glass
        "line-deep.js",           // why a line was said, and how often
        "line-actions.js",        // hold a line: pad, keep, or examine
        "lock.js",                // the station on a locked tablet
        "spark-overlays.js",      // the backend readouts, in any host
        "slideshow-source.js",    // the slideshow's whole traffic budget
        "slideshow.js",           // ~/bin/media-slideshow, on this glass
        "rail.js"                 // last: it looks for the globals above
    )

    /** Concatenated into one <style>; each keys off its own class prefix. */
    private val STYLES = listOf(
        "view-chrome.css",
        "boot-splash.css",        // the startup assembly
        "console-trace.css",      // the trace popup and the strip's menu
        "script.css",
        "script-page.css",        // the Script view laid out to the sketch
        "listen-music.css",
        "presentation.css",
        "lock.css",               // the locked screen
        "vote-arrows.css",        // the up and down arrows
        "line-actions.css",       // the hold sheet and the examination
        "three-full.css",         // the 3JS lift and the full-screen mode
        "busy.css",               // the working bar
        "slideshow.css",          // the slideshow and its twenty transitions
        "spark-overlays.css"      // the readouts, over a picture or alone
    )

    private fun read(context: Context, name: String): String =
        context.assets.open("$DIR/$name").bufferedReader().use { it.readText() }

    /**
     * The whole set as one expression, safe to evaluate at document start or
     * after load. Re-entrant: the guard returns early on a second call.
     */
    fun install(context: Context, webView: android.webkit.WebView) {
        webView.evaluateJavascript(bundle(context), null)
    }

    fun bundle(context: Context): String {
        val css = JSONObject.quote(STYLES.joinToString("\n") { read(context, it) })
        val libraries = SCRIPTS.joinToString("\n;\n") { read(context, it) }

        return buildString {
            append("(function(){try{")
            append("if(window.__pineViewsBooted)return;")
            append("window.__pineViewsBooted=true;\n")
            append("window.__pineViewsCss=").append(css).append(";\n")
            append(libraries)
            append("\n;\n")
            // The rail is built once the globals exist. It creates the hosts
            // and the tabs and mounts nothing.
            append("if(window.__pineViewRail)window.__pineViewRail();\n")
            append("}catch(e){window.__pineViewsBooted=false;")
            append("if(window.console)console.error('[pine] views failed:',e);}})();")
        }
    }
}
