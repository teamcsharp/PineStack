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
        // THE SHARED DUCK, before anything that speaks over the air:
        // talk-dot.js, script-page.js, line-deep.js, hot-corners.js and
        // tablet-doctor.js all reach for it, so it goes in ahead of the
        // first of them.
        "pine-duck.js",
        "talk-dot.js",            // the dot you speak commands into
        "vote-arrows.js",         // love it or not, on every player
        "album-popup.js",         // sleeve -> album, tracks, analysis, queue
        "listen-model.js",        // the arithmetic Listen and Music share
        "pine-meters.js",         // real levels off the real audio
        "script-lineage.js",      // reads one provenance payload
        "script-stage.js",        // the 3D presentation of it
        "script.js",              // the Script view
        "script-diagnostics.js", // evidence captured by the Script report button
        "script-page.js",         // the Script view built to the sketch
        "listen.js",
        "music.js",
        "wall-transition.js",     // what the wall shows between clips
        "video-wall.js",          // the gallery loop Presentation shows
        "presentation-source.js", // its one-request-wide traffic gate
        "presentation.js",
        "busy.js",                // a working bar on whatever is working
        // #1191/#1202: the orchestrator glass, BEFORE three-full.js because
        // the 3JS chooser now offers it as its own strip above the scenes and
        // asks window.PineOrchGlass for it. The ask is made when the sheet is
        // painted rather than at load, so the order is not load-bearing - but
        // a reader should not have to know that to see that it is satisfied.
        //
        // MEASURED, 2026-09-15: orchestrator-glass.js and its stylesheet were
        // already sitting in assets/pine-views and were in NEITHER list here,
        // so nothing on the tablet had ever evaluated them. The file existed,
        // the copy was in step, and the tablet had no orchestrator page at
        // all. Being present on disk is not being loaded, and this is the
        // list that decides which.
        //
        // It costs nothing until it is asked for: the module builds no DOM,
        // starts no timer and makes no request at load - the dot and the
        // pop-up are both created on demand, and a shut pop-up asks for
        // nothing at all.
        // #1222: the levels sheet - DJs, music and videos on THIS
        // terminal. He set the DJ gain to 200% and heard it quiet,
        // because pineMixer.voice was holding the elements at 0.68 and
        // nothing showed both numbers at once. One slider per stream
        // now drives whichever half can carry it.
        // #1226: the segments and their system prompts, the topic
        // bank, and the window a dropped markdown becomes. Before
        // orchestrator-glass.js, whose fold asks for it.
        "pine-segments.js",
        "pine-levels.js",
        "orchestrator-glass.js",  // what the orchestrator is doing, and the
                                  // rooms and the made-against-heard account
        "three-full.js",          // every 3JS scene, full screen on glass
        "line-deep.js",           // why a line was said, and how often
        "line-actions.js",        // hold a line: pad, keep, or examine
        "sfx-tv.js",              // #1306b: the SFX guy's little CRT set
        "clip-doctor.js",         // #1361b: why the video button gave nothing
        "pine-cam.js",            // #1358: the Pine Cam, self-hosted here
        "lock.js",                // the station on a locked tablet
        "spark-overlays.js",      // the backend readouts, in any host
        "slideshow-source.js",    // the slideshow's whole traffic budget
        "slideshow.js",           // ~/bin/media-slideshow, on this glass
        // #1317: the terminal noticing its own deafness. Before rail so
        // it is watching whatever else fails to start.
        "deaf-watch.js",
        "rail.js",                // it looks for the globals above
        // THE HOT CORNERS, after everything they reach for: line-deep.js
        // (the inspector), talk-dot.js and the report pad (the shot),
        // sfx-tv.js (the last clip) and rail.js (the drawer they mirror).
        // The native half is config/HotCorners.kt, the bridge's screenShot
        // / replayEdit / replayKeepEdited / hotCorners*, and MainActivity's
        // touch road. The editor is a station-served iframe: its own assets
        // must not be evaluated into the live station document here.
        "hot-corners.js"
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
        "sfx-tv.css",             // #1306b: the set, its glass and its sheet
        "clip-doctor.css",        // #1361b: the doctor's sheet
        "pine-cam.css",           // #1358: the box and the flag
        // #1191/#1202: the glass, its triangles and its headline number. Same
        // finding as the script above - the file was in assets and in no
        // list, so on the tablet the pop-up would have opened unstyled if
        // anything had been able to open it at all.
        "pine-segments.css",      // #1226
        "pine-levels.css",        // #1222
        "orchestrator-glass.css",
        "three-full.css",         // the 3JS lift and the full-screen mode
        "busy.css",               // the working bar
        "slideshow.css",          // the slideshow and its twenty transitions
        "spark-overlays.css",     // the readouts, over a picture or alone
        "hot-corners.css"         // the red ink, the export sheet, the inspector
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
