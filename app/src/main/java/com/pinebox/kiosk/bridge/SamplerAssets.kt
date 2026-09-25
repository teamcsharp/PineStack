package com.pinebox.kiosk.bridge

import android.content.Context
import android.webkit.WebView
import org.json.JSONObject

/**
 * Puts the Sampler into the station panel.
 *
 * The sampler is the Pine Box desktop's own code, shipped verbatim in the
 * APK's assets. It needs nothing Electron-specific - `window.pineDesktop`
 * (the bridge carries all 47 methods), a feed model, and
 * `window.pineSampler`. That was proved on this tablet by injecting the
 * same files into the live page: it mounted and drew 16 pads, 5 banks and
 * 240 feed rows.
 *
 * WHY THE FILES ARE EVALUATED RATHER THAN LINKED. The panel is served from
 * `http://10.89.1.246:8096` and the assets live at `file:///android_asset/`.
 * A `<script src>` from that page to that scheme is refused, so the content
 * is read and evaluated instead. This is also why the CSS is handed in as a
 * string rather than a stylesheet link.
 *
 * ORDER IS NOT COSMETIC. `sampler.js` binds to its host element the moment
 * it loads, so the scaffold has to exist first or the listener attaches to
 * nothing and no amount of clicking mounts anything. The feed model and the
 * engine likewise have to exist before the view that uses them.
 */
object SamplerAssets {

    private const val DIR = "pine-sampler"

    /** Evaluated in this order, for the reason above. */
    private val SCRIPTS = listOf(
        "lcd-dialogue.js",    // stationRows() - the feed model
        "sampler-engine.js",  // Web Audio; stands aside if Oboe is present
        "sampler-feed.js",    // the ONE poller, 4s, interpolated locally
        // THE AIR TAP GOES BEFORE THE VIEW. sampler.js reads PineAir when it
        // mounts - to light the SOLO PAD toggle from the remembered setting,
        // and to start the ring listening - and an undefined one there leaves
        // the toggle dark and the first hold on an empty pad finding nothing.
        //
        // This is also the file that only works HERE. It taps the page's own
        // players with createMediaElementSource, which yields silence on a
        // cross-origin element - so it needs the panel and the media to share
        // an origin. On the tablet they do, because these views are injected
        // into the station's own page at :8096. In the Electron renderer,
        // running from file://, they do not, and it says so rather than
        // recording nothing.
        "sampler-air.js",     // the last two minutes, and the pad-solo duck
        "sampler.js",         // the view
        "sampler-trim.js",    // the trim editor
        // The face: the gallery backdrop, waveforms on the pads, the knob
        // row and the edit sheet. AFTER sampler.js - it hangs off the seams
        // that file publishes and starts from its mount.
        "sampler-face.js",
        "sampler-grab.js",    // tap an empty pad: scrub the air, or a clip
        "sampler-kits.js",    // presets, and kit files that carry the audio
        // #1310: the SFX guy's little CRT set. A pad that holds a video
        // pops the picture when it is pressed, and this surface is its
        // own page - the set in the views bundle is not loaded here.
        "wall-transition.js",
        "sfx-tv.js",
        // #1317: this surface is its own page and can go deaf too.
        "deaf-watch.js"
    )

    private fun read(context: Context, name: String): String =
        context.assets.open("$DIR/$name").bufferedReader().use { it.readText() }

    /**
     * The whole sampler as one expression, safe to evaluate at document
     * start or after load. Re-entrant: `__pineSamplerScaffold` returns
     * "already" and the mount is skipped if one is running, so a reload or
     * a double call cannot produce two samplers.
     */
    fun bundle(context: Context): String {
        val css = JSONObject.quote(
            read(context, "sampler.css") + "\n" + read(context, "sfx-tv.css"))
        val boot = read(context, "boot.js")
        val libraries = SCRIPTS.joinToString("\n;\n") { read(context, it) }

        return buildString {
            append("(function(){try{")
            // ONCE PER PAGE, and the guard has to be the first thing here.
            //
            // Each sampler file is an IIFE with its own module scope. Evaluate
            // the bundle twice and the second pass builds a SECOND set of
            // those, overwriting window.PineSampler while the first set's feed
            // subscription is still live and now unreachable - a leaked poller
            // against a station with a documented history of being starved by
            // chatty clients. Measured: a second evaluation left the new module
            // with no subscription at all while the old one kept polling.
            //
            // onPageFinished can fire more than once for one page (fragment
            // navigations, some redirects), so this is not hypothetical.
            append("if(window.__pineSamplerBooted)return;")
            append("window.__pineSamplerBooted=true;\n")
            // The stylesheet text, handed to boot.js rather than linked.
            append("window.__pineSamplerCss=").append(css).append(";\n")
            append(boot).append("\n;\n")
            append("window.__pineSamplerScaffold();\n")
            append(libraries).append("\n;\n")
            append("window.__pineSamplerReady();\n")
            // A failure here must never take the panel down with it: the
            // station is the point, the sampler is an addition to it. The
            // guard is released so a later attempt can still succeed.
            append("}catch(e){window.__pineSamplerBooted=false;")
            append("if(window.console)console.error('[pine] sampler boot failed:',e);}})();")
        }
    }

    /**
     * Install into a loaded page. Call from `onPageFinished` - the panel is
     * a two-megabyte document and its own scripts should have had their run
     * before another five files are laid on top.
     */
    fun install(context: Context, webView: WebView) {
        webView.evaluateJavascript(bundle(context), null)
    }
}
