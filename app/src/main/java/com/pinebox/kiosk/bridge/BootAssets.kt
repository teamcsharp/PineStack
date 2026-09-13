package com.pinebox.kiosk.bridge

import android.content.Context
import android.util.Log
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import java.io.BufferedReader
import java.util.concurrent.atomic.AtomicBoolean

private const val TAG = "PineBoot"
private const val BOOT_SCRIPT = "pine-boot/boot-sequence.js"

/* THE MARK AND THE ASSEMBLY, injected alongside the boot sequence.
 *
 * "When the Pine Box application is starting up, I want to see the logo
 * rotating in 3D being assembled by particles coming together."
 *
 * These two normally arrive with the view bundle, which is evaluated at
 * onPageFinished - far too late for a boot screen that has to be on glass
 * before the panel's two megabytes begin to paint. So they are injected at
 * document start, ahead of the sequence that calls them.
 *
 * The logo is a data URI rather than a file reference for the reason this
 * whole file exists: the page is on http://10.89.1.246:8096 and the assets
 * are on file:///android_asset/, and the WebView refuses the crossing. */
private const val LOGO_SCRIPT = "pine-views/pine-logo.js"
private const val SPLASH_SCRIPT = "pine-views/boot-splash.js"
private const val THREE_ASSET = "vendor/three.min.js"

private fun readAsset(context: Context, name: String): String =
    context.assets.open(name).use { it.bufferedReader().use(BufferedReader::readText) }

/**
 * The opening sequence: the station assembling itself.
 *
 * Two phases, both living in `assets/pine-boot/boot-sequence.js`:
 *
 *   PHASE 1  a three.js scene of the station's ten-stage spine building
 *            itself out of off-screen parts, over a console overlay naming
 *            what is really happening, while the panel loads behind it.
 *   PHASE 2  the panel arriving - its top-level sections transformed in from
 *            off-screen, staggered, then stripped of every transform.
 *
 * This file exists to hand that script three things the page cannot get for
 * itself, and then to get out of the way.
 *
 * ---------------------------------------------------------------------------
 * WHY THE SCRIPT IS EVALUATED AND NOT LINKED
 *
 * The same reason as SamplerAssets: the panel is served from
 * `http://10.89.1.246:8096` and the assets live at `file:///android_asset/`.
 * A `<script src>` from that page to that scheme is refused outright. So the
 * asset is read and handed to WebViewCompat.addDocumentStartJavaScript.
 *
 * DOCUMENT START rather than onPageFinished, which is the opposite of the
 * sampler and for the opposite reason. The sampler is an addition and should
 * land after the panel has had its run; a boot sequence has to be ON SCREEN
 * before the panel's two megabytes begin to paint, or there is nothing left
 * for it to cover.
 *
 * ---------------------------------------------------------------------------
 * WHERE THREE.JS COMES FROM, AND WHY IT IS NOT A DOWNLOAD
 *
 * `/vendor/three.min.js` is 593 kB and the station serves it. On this tablet
 * that is not a viable boot dependency, and the measurement is already in the
 * tree: PineNet.kt records a `<script src="/vendor/three.min.js">` that fired
 * neither onload nor onerror in THREE MINUTES, because the panel's ~180
 * full-size PNGs held every one of Chromium's six sockets to this HTTP/1.1
 * station and the script never reached the front of the queue. The same file
 * took 1.26 s from a desktop at the same moment.
 *
 * So the boot scene never asks the network. The APK already carries
 * `assets/vendor/three.min.js`; it is read into memory ONCE on a background
 * thread when the activity stands up, and handed to the page as a string
 * through `three()`. Local flash, no socket, nothing to queue behind.
 *
 * Two consequences worth stating:
 *
 *   - The string is held for the life of the sequence and dropped the moment
 *     the page calls `done()`. 593 kB resident for two seconds on a 4 GB
 *     device is a fair trade for not opening a socket during a launch.
 *   - Evaluating it defines the GLOBAL `window.THREE`, which is exactly what
 *     the panel's own 3js views look for before they inject that script tag.
 *     A side effect, but a good one: after this sequence the panel's scenes
 *     open with no fetch at all.
 */
object BootAssets {

    /** The interface name the script looks for. */
    const val NAME = "__pineBootNative"

    /**
     * Register the sequence for this WebView.
     *
     * Call ONCE, from the activity, BEFORE the first navigation - a
     * document-start script only applies to documents that start after it is
     * registered. The single line in MainActivity.standUpTheRest is
     *
     *     BootAssets.install(this, webView, statusPanel)
     *
     * placed immediately after `installBridge()`, so the pineDesktop shim,
     * the touch stylesheet and the sampler shim are all registered first and
     * this runs last of the four (registration order is evaluation order).
     *
     * @param statusPanel the native "Reaching the station" view, which is
     *   opaque and covers the WebView until MainActivity hides it. It is
     *   hidden here the moment the sequence writes its first line, so the
     *   handover reads native panel -> scene -> panel rather than the scene
     *   playing out of sight behind it. If the load then fails,
     *   onReceivedError raises the panel again on its own; nothing here
     *   touches it twice.
     */
    fun install(context: Context, webView: WebView, statusPanel: View?) {
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            Log.w(TAG, "no DOCUMENT_START_SCRIPT on this WebView; no boot sequence")
            return
        }
        val script = try {
            /* Order matters: the mark, then the assembly that draws it,
             * then the sequence that calls for it. */
            buildString {
                append(readAsset(context, LOGO_SCRIPT))
                appendLine()
                append(readAsset(context, SPLASH_SCRIPT))
                appendLine()
                append(readAsset(context, BOOT_SCRIPT))
            }
        } catch (err: Throwable) {
            Log.w(TAG, "boot sequence asset missing; skipping", err)
            return
        }

        val bridge = Native(context.applicationContext, webView, statusPanel)
        webView.addJavascriptInterface(bridge, NAME)
        WebViewCompat.addDocumentStartJavaScript(webView, script, setOf("*"))
        bridge.warm()
        Log.i(TAG, "boot sequence registered (${script.length / 1024} kB of script)")
    }

    /**
     * The three things the page cannot get for itself.
     *
     * EVERY METHOD HERE RUNS ON A BINDER THREAD, not the UI thread, and must
     * return promptly - a slow answer blocks the JavaScript engine. So
     * nothing here touches the disk: three.min.js is read ahead of time by
     * [warm] on its own thread and only ever handed over from memory.
     */
    private class Native(
        private val context: Context,
        private val webView: WebView,
        private val statusPanel: View?,
    ) {

        /** ONE claim per activity. See the guard note in boot-sequence.js. */
        private val unclaimed = AtomicBoolean(true)

        private val installedAt = android.os.SystemClock.uptimeMillis()

        @Volatile private var threeSrc: String? = null
        @Volatile private var threeSize: Int = 0

        /** Read the engine off local flash, off every thread that matters. */
        fun warm() {
            Thread({
                try {
                    val src = readAsset(context, THREE_ASSET)
                    threeSrc = src
                    threeSize = src.length
                    Log.i(TAG, "three.js ready from the apk: ${src.length / 1024} kB")
                } catch (err: Throwable) {
                    Log.w(TAG, "no three.js in the apk; the console runs alone", err)
                }
            }, "pine-boot-three").apply { isDaemon = true }.start()
        }

        /**
         * True exactly once per activity.
         *
         * A document-start script is registered for EVERY navigation - the
         * rail's quick jumps included - and onPageStarted can fire more than
         * once for one page. Without this the operator would watch the
         * station assemble itself every time they opened a console.
         */
        @JavascriptInterface
        fun claim(): Boolean {
            val mine = unclaimed.compareAndSet(true, false)
            if (mine) Log.i(TAG, "sequence claimed")
            return mine
        }

        /**
         * The engine, as a string. Empty if [warm] has not finished or the
         * asset is not in this build - the page treats both as "run the
         * console alone" and still finishes on exactly the same clock.
         */
        @JavascriptInterface
        fun three(): String = threeSrc ?: ""

        @JavascriptInterface
        fun threeBytes(): Int = threeSize

        /**
         * Milliseconds since this object was installed, i.e. since the
         * activity stood the WebView up.
         *
         * This is how the window the sequence CANNOT cover gets measured. The
         * overlay can only exist once the panel's main document exists, and
         * that is the end of: the key-discovery round trip, the connect, and
         * the time-to-first-byte of a 2.1 MB uncompressed HTML document over
         * Wi-Fi. Against `performance.now()` at document start - which is
         * time-to-first-byte, because timeOrigin is navigationStart - this
         * number splits that window in two and says which half to attack.
         */
        @JavascriptInterface
        fun sinceInstall(): Int = (android.os.SystemClock.uptimeMillis() - installedAt).toInt()

        /**
         * A console line, into logcat.
         *
         * `adb logcat -s PineBoot` is how the sequence is measured on the
         * real tablet - what landed, in what order, at what millisecond -
         * without a profiler or a screenshot. That is the only kind of number
         * anyone takes twice.
         */
        @JavascriptInterface
        fun log(line: String?) {
            Log.i(TAG, line ?: "")
        }

        /**
         * The overlay has actually painted; take the native panel down.
         *
         * THIS WAS A REAL BUG, and the shape of it is worth keeping. The
         * first build hid the status panel on the sequence's FIRST LOG LINE,
         * which is written 17 ms after the document starts. On the tablet
         * that produced a black screen: the overlay existed, but Chromium
         * had not yet performed the document's first paint, because this
         * panel is 2.18 MB of HTML with no content-encoding whose <head> is
         * one enormous inline <style> - and rendering is blocked until that
         * is received and parsed in full. So the opaque native view came
         * down a second and a half before there was anything underneath it.
         *
         * The page now calls this from a PerformanceObserver on the `paint`
         * entry type, which is the browser telling us it has drawn - not us
         * guessing that it must have. Idempotent; MainActivity also hides
         * the panel on its own and either order is fine.
         */
        @JavascriptInterface
        fun painted() {
            val panel = statusPanel ?: return
            webView.post {
                if (panel.visibility != View.GONE) panel.visibility = View.GONE
            }
        }

        /**
         * The page has no further use for the engine source; give the 593 kB
         * back. Called once when the scene stands up and again at the
         * handover, because either can be the last one - and a second call
         * is a null assignment, which is cheaper than deciding.
         */
        @JavascriptInterface
        fun done() {
            if (threeSrc == null) return
            threeSrc = null
            Log.i(TAG, "three.js source released")
        }
    }
}
