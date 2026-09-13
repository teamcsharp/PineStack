package com.pinebox.kiosk

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Log
import android.view.View
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import com.pinebox.kiosk.bridge.PineDesktopBridge
import com.pinebox.kiosk.net.PineNet
import kotlinx.coroutines.launch

/**
 * THE SC STACK, AS ITS OWN APPLICATION.
 *
 * "SC stack should be its own application that I'm able to access... I wanted
 *  to be able to access the media slideshow as its own application with all of
 *  its functionality inside of that, while also being able to access it as a
 *  pop up inside of Pinebox tab."
 *
 * So there are three ways in, and this is the first of them:
 *
 *   1. THIS — its own launcher icon, "SC Stack". An ordinary app: it opens on
 *      the Spark's readouts with the renders behind them, and it closes.
 *   2. A POP-UP inside Pine Box — the floating panel `SparkOverlays.popup()`
 *      builds, summoned from the panel without leaving whatever is on screen.
 *   3. The SLIDES view in the rail, full-bleed.
 *
 * WHY THIS ACTIVITY IS THIN, and why that is the point. [MainActivity] is a
 * kiosk: it owns HOME, it locks the task, it injects every view from the APK's
 * own assets, and so a change to one of those views needs a rebuild and an
 * install. This one loads `/spark?pictures=1` and nothing else. The station
 * serves the overlays, the slideshow and the transitions from
 * `desktop/renderer/`, so editing one of those files changes what this app
 * shows on its NEXT LAUNCH with no APK anywhere in the loop.
 *
 * WHAT IT STILL NEEDS FROM NATIVE. Only the bridge: a like writes to
 * favorites.md, a setting writes to the desktop app's own state file, and both
 * need the bearer that [PineDesktopBridge] holds. Without it the page would
 * still draw every readout — they are open reads — and quietly fail to write.
 *
 * NOT A KIOSK. No HOME filter, no `startLockTask`, and Back finishes it. The
 * terminal is the thing that must never show a blank screen; this is an app
 * the operator opened and is allowed to leave.
 */
class SparkActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var statusPanel: LinearLayout
    private lateinit var statusText: TextView
    private lateinit var statusRetry: Button
    private lateinit var bridge: PineDesktopBridge

    private val app: PineApp get() = application as PineApp

    /** The host we are meant to be on, so a stray link cannot navigate away. */
    private var stationHost: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_spark)

        webView = findViewById(R.id.sparkPanel)
        statusPanel = findViewById(R.id.sparkStatus)
        statusText = findViewById(R.id.sparkStatusText)
        statusRetry = findViewById(R.id.sparkRetry)
        statusRetry.setOnClickListener { load() }

        /* The same reason MainActivity installs it before the client: the
         * WebViewClient starts answering shouldInterceptRequest the moment a
         * load begins, and PineNet returns null until it has its dirs. */
        PineNet.install(this)

        configureWebView()
        installBridge()
        installBackPolicy()
        fitSystemBars()
        load()
    }

    override fun onDestroy() {
        /* Detach before destroy, or the WebView leaks this activity through
         * the JavaScript interface — the same order MainActivity uses. */
        try {
            webView.removeJavascriptInterface(PineDesktopBridge.NAME)
            (webView.parent as? android.view.ViewGroup)?.removeView(webView)
            webView.destroy()
        } catch (err: Throwable) {
            Log.w(TAG, "teardown", err)
        }
        super.onDestroy()
    }

    /**
     * KEEP THE READOUTS OUT FROM UNDER THE SYSTEM BARS.
     *
     * This is an ordinary app, so it gets Android's navigation bar — and on
     * the first build the slideshow's control bar and its filmstrip were
     * drawn underneath it. The kiosk never meets this because it goes
     * immersive, but going immersive here would be the wrong cure: this is
     * an app the operator is meant to be able to LEAVE, and hiding the Back
     * and Home buttons to gain 80px is a bad trade.
     *
     * So the root is padded by whatever the system is actually using —
     * asked for rather than assumed, because it differs between three-button
     * navigation, gesture navigation and a rotated tablet.
     */
    private fun fitSystemBars() {
        val root = findViewById<View>(R.id.sparkRoot)
        androidx.core.view.ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(
                androidx.core.view.WindowInsetsCompat.Type.systemBars()
                    or androidx.core.view.WindowInsetsCompat.Type.displayCutout())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        androidx.core.view.ViewCompat.requestApplyInsets(root)
    }

    /* ------------------------------------------------------------------ */

    private fun configureWebView() {
        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            /* The slideshow behind the readouts plays video, and a monitor
             * nobody has touched must still start it. */
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            loadsImagesAutomatically = true
            blockNetworkImage = false
            allowFileAccess = false
            allowContentAccess = false
            /* Pinch, for the same reason the panel has it: some of these
             * readouts are dense and being able to pull one closer is the
             * difference between reading it and guessing. */
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
            cacheMode = WebSettings.LOAD_DEFAULT
            minimumFontSize = 12
            minimumLogicalFontSize = 12
            userAgentString = desktopUserAgent(userAgentString)

            /* NO initial-scale override here, and that is the difference from
             * the panel. MainActivity zooms so the station's one enormous
             * document lands past its own `max-width:900px` branch. The
             * overlays have no such cliff — their layout is a grid that fits
             * itself to whatever it is given, checked at seven sizes by
             * tools/overlay-fit-probe.cjs — so this reads at 1:1 and the type
             * stays the size the tablet's own dpi makes it. */
            useWideViewPort = true
            loadWithOverviewMode = false
        }

        webView.setBackgroundColor(0xFF05080B.toInt())
        webView.isVerticalScrollBarEnabled = false
        webView.isHorizontalScrollBarEnabled = false
        if (WebViewFeature.isFeatureSupported(WebViewFeature.OFF_SCREEN_PRERASTER)) {
            WebSettingsCompat.setOffscreenPreRaster(webView.settings, true)
        }
        /* The overlays repaint on a clock; a demoted renderer rebuilds the
         * page from scratch when the operator comes back to it. */
        webView.setRendererPriorityPolicy(
            WebView.RENDERER_PRIORITY_IMPORTANT, false)
        webView.overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS
        webView.webViewClient = SparkClient()
    }

    private fun installBridge() {
        bridge = PineDesktopBridge(
            context = applicationContext,
            webView = webView,
            configStore = app.configStore,
            client = app.client,
            scope = lifecycleScope,
            openExternal = ::openExternal,
        )
        webView.addJavascriptInterface(bridge, PineDesktopBridge.NAME)

        /* ONLY the bridge shim. The views themselves are served from the
         * station — see the class header. */
        val shim = readAsset("pine-bridge.js")
        if (shim.isNotEmpty()
            && WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)
        ) {
            try {
                WebViewCompat.addDocumentStartJavaScript(
                    webView, shim, setOf("*"))
            } catch (err: Throwable) {
                Log.w(TAG, "document-start shim refused; falling back", err)
            }
        }
    }

    private fun readAsset(name: String): String = try {
        assets.open(name).bufferedReader().use { it.readText() }
    } catch (err: Throwable) {
        Log.w(TAG, "asset $name", err)
        ""
    }

    /**
     * Strip the markers that make a server decide this is a phone — the same
     * derivation MainActivity uses, so the Chrome version stays truthful.
     */
    private fun desktopUserAgent(current: String?): String {
        val ua = current ?: return ""
        return ua.replace(" Mobile", "").replace("; wv", "")
    }

    private fun load() {
        showStatus(getString(R.string.status_connecting), retry = false)
        lifecycleScope.launch {
            val cfg = app.configStore.read()
            val base = cfg.base.trimEnd('/')
            stationHost = Uri.parse(base).host.orEmpty()
            /* WITH THE PICTURES. This is the media slideshow as an
             * application, not a bare dashboard: the renders play and the
             * readouts sit over them, which is the arrangement on the box's
             * own glass. The dashboard is one tap away on the page itself. */
            webView.loadUrl("$base/spark?pictures=1")
        }
    }

    private fun showStatus(message: String, retry: Boolean) {
        statusText.text = message
        statusRetry.visibility = if (retry) View.VISIBLE else View.GONE
        statusPanel.visibility = View.VISIBLE
    }

    private fun openExternal(uri: Uri): Boolean = try {
        startActivity(Intent(Intent.ACTION_VIEW, uri))
        true
    } catch (err: Throwable) {
        Log.w(TAG, "no handler for $uri", err)
        false
    }

    /** Back leaves. This is an app, not the terminal. */
    private fun installBackPolicy() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) webView.goBack() else finish()
            }
        })
    }

    private inner class SparkClient : WebViewClient() {
        override fun onPageFinished(view: WebView?, url: String?) {
            if (url != null && url != "about:blank") {
                statusPanel.visibility = View.GONE
            }
        }

        override fun onReceivedError(
            view: WebView?, request: WebResourceRequest?, error: WebResourceError?
        ) {
            /* Only the MAIN document's failure is the app failing. A
             * sub-resource that 404s is a missing asset, not a dead station,
             * and reporting it as one sends the operator to the wrong place. */
            if (request?.isForMainFrame != true) return
            showStatus(
                getString(R.string.spark_unreachable,
                    stationHost.ifEmpty { "the station" }),
                retry = true)
        }

        /** Stay on the station; hand anything else to the system browser. */
        override fun shouldOverrideUrlLoading(
            view: WebView?, request: WebResourceRequest?
        ): Boolean {
            val uri = request?.url ?: return false
            val host = uri.host.orEmpty()
            if (host.isEmpty() || host == stationHost) return false
            return openExternal(uri)
        }
    }

    private companion object {
        const val TAG = "PineSpark"
    }
}
