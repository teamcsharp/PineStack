package com.pinebox.kiosk

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.PermissionRequest
import android.Manifest
import android.content.pm.PackageManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.SeekBar
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.drawerlayout.widget.DrawerLayout
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import com.pinebox.kiosk.bridge.PineDesktopBridge
import com.pinebox.kiosk.bridge.SamplerAssets
import com.pinebox.kiosk.bridge.ViewAssets
import com.pinebox.kiosk.kiosk.KioskController
import com.pinebox.kiosk.net.PineNet
import com.pinebox.kiosk.net.Reach
import com.pinebox.kiosk.rail.RailController
import com.pinebox.kiosk.rail.RailState
import com.pinebox.kiosk.audio.MediaFocus
import com.pinebox.kiosk.audio.OutputRoute
import fm.pinebox.kiosk.audio.PineSampler
import fm.pinebox.kiosk.audio.PineSamplerBridge
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.io.BufferedReader

/**
 * The terminal.
 *
 * One full-screen WebView showing the station's own control panel, the
 * pineDesktop bridge the panel expects to find, a NATIVE left-edge rail that
 * mirrors the Pine Box desktop's sidebar (which is Electron chrome and never
 * reaches a tablet), and the kiosk behaviour that stops the tablet being a
 * tablet.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var drawer: DrawerLayout

    /** The empty drawer child in the layout; the rail is inflated INTO it
     *  after the first frame - see standUpTheRest. */
    private lateinit var railHost: ViewGroup
    private lateinit var webView: WebView
    private lateinit var statusPanel: View
    private lateinit var statusText: TextView
    private lateinit var statusRetry: Button
    private lateinit var monitorBar: SeekBar
    private lateinit var monitorValue: TextView

    private lateinit var bridge: PineDesktopBridge

    /** Null until the deferred build has run. */
    private var rail: RailController? = null

    /** Watches which socket the sound leaves by; see OutputRoute. */
    private var outputRoute: OutputRoute? = null

    /** Holds media audio focus while the terminal is in front. Without it
     *  the WebView decodes and never sounds - see MediaFocus. */
    private var mediaFocus: MediaFocus? = null

    /** A feed snapshot that arrived before the rail was built. */
    private var waiting: RailState? = null

    /** The host the panel is served from; anything else is "external". */
    private var stationHost: String = ""

    /** For the time-to-first-paint reading; see onPageFinished. */
    private var startedAt: Long = 0L

    private val app: PineApp get() = PineApp.of(this)

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        startedAt = SystemClock.uptimeMillis()
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        /* ASK FOR THE MICROPHONE UP FRONT.
         *
         * The ear is native now, and a native AudioRecord does not trigger
         * the WebView's permission callback - nothing will ever prompt on
         * the operator's behalf. Measured before this was added:
         * RECORD_AUDIO read `granted=false` on a device that had been
         * running the talk dot for days, which is exactly the sort of
         * silent no-op that reads as broken hardware.
         *
         * Asked once at start rather than at the first press: a kiosk that
         * throws a system dialog over the show the first time someone taps
         * the dot is worse than one that settles it at boot. */
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(
                this, arrayOf(Manifest.permission.RECORD_AUDIO), MIC_REQUEST)
        }

        drawer = findViewById(R.id.drawerLayout)
        railHost = findViewById(R.id.rail)
        webView = findViewById(R.id.panel)
        statusPanel = findViewById(R.id.statusPanel)
        statusText = findViewById(R.id.statusText)
        statusRetry = findViewById(R.id.statusRetry)

        KioskController.applyOwnerPolicies(this)
        KioskController.applyWindowFlags(this)

        /* Before configureWebView, because the WebViewClient it installs
         * starts answering shouldInterceptRequest the moment a load begins
         * and PineNet returns null until it has its dirs. Cheap - two
         * mkdirs and one daemon thread. */
        PineNet.install(this)

        configureWebView()
        installBackPolicy()

        statusRetry.setOnClickListener { load() }

        /* EVERYTHING ELSE WAITS FOR THE FIRST FRAME, and the number says why.
         *
         * `am start -W` on the TB310FU, three runs each and under 6ms of
         * spread: 1193ms before the rail existed, 1567ms with the rail built
         * in onCreate, 1229ms with it built here. The 340ms was the rail's
         * sixty-odd views being inflated, three assets being read off disk and
         * libpinesampler.so being loaded - none of which anybody can see
         * during a launch, because the only thing on screen in that window is
         * the "Reaching the station" panel, which is already in the layout.
         *
         * post() runs after this traversal is queued, so the frame the launch
         * is timed against is already on its way out when this begins. The
         * first load is started from in HERE rather than from onCreate so that
         * the document-start scripts - the pineDesktop shim, the touch
         * stylesheet and the sampler shim - are registered before any
         * navigation can begin, which is the one ordering that actually
         * matters (see installBridge). */
        drawer.post { standUpTheRest() }

        /* ONE collector, and the shape it collects is the optimisation.
         *
         * StationFeed emits at 250ms - it polls at 4s and interpolates the
         * playhead locally in between (app.py:155440's contract). Handing
         * those raw emissions to the rail would re-bind twenty-odd views four
         * times a second on the main thread of a device that was already at
         * 21.5% janky frames before any of this existed.
         *
         * So: map to RailState (a small value class holding only what the
         * rail paints) on a background dispatcher, distinctUntilChanged, and
         * only then touch a view. The playhead ticking changes nothing in
         * RailState, so the ticks cost one equals() each and stop there. */
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                app.feed.state
                    .map { RailState.of(it) }
                    .distinctUntilChanged()
                    .flowOn(Dispatchers.Default)
                    .collect { state ->
                        if (state.connected) hideStatus()
                        /* The feed can answer before the deferred build has
                         * run - it is one LAN round trip against a post(). The
                         * snapshot is kept so the rail opens showing the truth
                         * rather than its XML defaults. */
                        val built = rail
                        if (built != null) built.render(state) else waiting = state
                    }
            }
        }
    }

    /* onResume, not onStart: startLockTask() refuses on an activity that is
     * not yet resumed, and the refusal is an IllegalStateException rather
     * than a return value. */
    /** The station on the glass while the tablet is locked. Built lazily
     *  in onResume, because it needs the WebView to exist first. */
    private var lockWatch: com.pinebox.kiosk.kiosk.LockWatch? = null
    private var jackWatch: com.pinebox.kiosk.audio.JackWatch? = null

    /* POINTING AT THE MPC'S DISK, ONCE.
     *
     * A kit is written onto a USB volume through the Storage Access
     * Framework - see UsbTarget for why there is no path road - and SAF needs
     * a real Activity to show its picker. Registered here at construction
     * because registerForActivityResult refuses after onStart, and answered
     * back to whatever bridge call asked for it. */
    private var usbAsked: ((String) -> Unit)? = null

    private val pickUsb = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val answer = usbAsked
        usbAsked = null
        val uri = result.data?.data
        if (result.resultCode != RESULT_OK || uri == null) {
            answer?.invoke("")
            return@registerForActivityResult
        }
        /* PERSIST THE GRANT, or it dies with this process and the operator is
         * asked again on every kit. */
        runCatching {
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
        }
        val name = runCatching {
            androidx.documentfile.provider.DocumentFile.fromTreeUri(this, uri)?.name
        }.getOrNull() ?: ""
        com.pinebox.kiosk.gallery.UsbTarget.remember(this, uri, name)
        answer?.invoke(uri.toString())
    }

    /** Show the disk picker. The answer arrives on the main thread. */
    fun askForUsbDisk(answer: (String) -> Unit) {
        if (usbAsked != null) { answer(""); return }
        usbAsked = answer
        runCatching { pickUsb.launch(com.pinebox.kiosk.gallery.UsbTarget.pickIntent()) }
            .onFailure { usbAsked = null; answer("") }
    }

    /* #1241: KEEP THE WEBVIEW'S JAVASCRIPT TIMERS RUNNING.
     *
     * Measured on this tablet, foreground, screen awake, page visible:
     * requestAnimationFrame fired, and setTimeout and setInterval did
     * not - a freshly installed 1-second interval managed zero ticks in
     * fifteen. The renderer was alive and compositing; only the timer
     * queue was suspended, which is WebView.pauseTimers() semantics.
     *
     * Nothing in this app calls pauseTimers, so the platform is doing
     * it. What it costs is the whole station: the page's voice-feed
     * poll, the station's "reload every page" stamp, the solo-gate
     * un-gag and the page's own stuck-clip watchdog are all driven by
     * setInterval, so a tablet in this state goes silent and CANNOT BE
     * RECOVERED FROM THE WEB SIDE AT ALL - the reload stamp it would
     * need to read is itself read by a timer. Only the app can fix it,
     * and only from outside the WebView.
     *
     * postDelayed is the main thread's Handler, not a WebView timer, so
     * this guard keeps running precisely when the thing it repairs has
     * stopped. resumeTimers() is idempotent and process-wide; calling it
     * on a healthy WebView costs nothing. */
    private var timerGuard: Runnable? = null

    /* How many non-error console lines a second reach logcat. Thirty is far
     * more than a healthy page produces and far less than a loop does. */
    private val CONSOLE_PER_SECOND = 30
    private val CONSOLE_ERRORS_PER_SECOND = 10

    private fun keepTimersAlive() {
        if (timerGuard != null) return
        val guard = object : Runnable {
            override fun run() {
                try {
                    webView.resumeTimers()
                } catch (t: Throwable) {
                    Log.w(TAG, "resumeTimers refused: " + t)
                }
                webView.postDelayed(this, TIMER_GUARD_MS)
            }
        }
        timerGuard = guard
        webView.postDelayed(guard, TIMER_GUARD_MS)
    }

    override fun onResume() {
        /* THE RECORDER IS A SERVICE NOW, not something this activity does.
         *
         * This used to call replayFollowScreen(true), and that was the ONLY
         * call site - nothing ever passed false, so the encoder never
         * stopped and the disk cache, which is written when it does, was
         * dead code. Worse, the recorder's lifetime became this activity's,
         * and #1296 measured this activity being destroyed and recreated
         * seven times in thirty-three minutes by a wallpaper change.
         *
         * begin() is safe to call repeatedly; it is here as well as in the
         * boot receiver because a background start can be refused and a
         * visible activity is the one context that never is. */
        com.pinebox.kiosk.replay.PineAppRecorder.begin(this)
        super.onResume()
        /* #1296: a view is on the glass, so the wallpaper holds. Hanging
           one regenerates the Material You overlays, and the
           CONFIG_ASSETS_PATHS that follows relaunches this activity -
           measured at seven times in thirty-three minutes, taking the
           operator's place in the script each time. */
        app.wallpaper.reading = true
        KioskController.enterLockTask(this)

        /* THE LOCK SCREEN. Registered here rather than in onCreate because
         * SCREEN_ON/SCREEN_OFF/USER_PRESENT are protected broadcasts that a
         * manifest receiver is not allowed to take - they need a live
         * process, which a kiosk always is. `settle()` then catches up with
         * whatever happened while this was not listening. */
        /* THE HEADPHONE JACK. This GSI's framework never announces it -
         * see JackWatch for the measurements - so the terminal does. */
        if (jackWatch == null) {
            jackWatch = com.pinebox.kiosk.audio.JackWatch(this) { on ->
                Log.i(TAG, if (on) "audio handed to the jack" else "audio back to the speaker")
            }
        }
        jackWatch?.start()
        /* The page can hand the audio over by hand - see JackWatch.force.
         * GUARDED: `bridge` is lateinit and onResume runs before
         * installBridge() on the very first pass, where touching it throws
         * UninitializedPropertyAccessException and takes the kiosk down -
         * which is exactly what it did. */
        if (::bridge.isInitialized) {
            bridge.jackWatch = jackWatch
            /* The USB disk picker needs a live window - see the bridge. */
            bridge.liveActivity = this
        }

        if (lockWatch == null) {
            lockWatch = com.pinebox.kiosk.kiosk.LockWatch(
                this,
                { script, back -> webView.evaluateJavascript(script, back) },
                { delay, work -> webView.postDelayed({ work() }, delay) },
            )
        }
        lockWatch?.start()
        webView.postDelayed({ lockWatch?.settle() }, 1200)
        /* DO NOT TAKE AUDIO FOCUS HERE. IT SILENCES THE WEBVIEW.
         *
         * This used to request AUDIOFOCUS_GAIN on resume, reasoning that
         * WebView ties media output to focus and a kiosk never gets the
         * gesture Chromium's delegate hangs its own request on. That was
         * wrong in a way that was worse than the disease.
         *
         * Chromium's AudioFocusDelegate runs in THIS process, under THIS
         * uid. A second AUDIOFOCUS_GAIN from the same app evicts the first,
         * so the request meant to make the tablet audible was taking focus
         * away from the very WebView that needed it. Measured, after the
         * request went in:
         *
         *   abandonAudioFocus() from uid/pid 10201/7832
         *     ... org.chromium.content.browser.AudioFocusDelegate
         *   AudioFlinger: 2 Tracks of which 0 are active
         *
         * - Chromium gave up focus and stopped producing an output track at
         * all, while the media element happily went on advancing its clock.
         * The tablet played perfectly in the window before this was added.
         *
         * The WebView manages its own focus. Leave it alone.
         *
         * ...EXCEPT THAT REMOVING IT STOPPED THE AUDIO, so the reading above
         * was wrong and is kept as a record of the wrong turn. The evidence
         * that mattered: the tablet was CONFIRMED audible while this request
         * was in place, and went silent - AudioFlinger back to "0 are
         * active" - once it was taken out. The abandonAudioFocus line that
         * prompted the removal was Chromium letting go on a page reload, not
         * being evicted by us.
         *
         * So the app holds media focus for as long as it is in front. On a
         * kiosk there is never a gesture for Chromium's own delegate to hang
         * a request on, and WebView ties media OUTPUT to focus. */
        if (mediaFocus == null) mediaFocus = MediaFocus(applicationContext)
        mediaFocus?.hold()

        /* #1241: and the timers, which nothing else can reach. Once
         * here, because coming back to the front is the moment they are
         * most often found stopped, and then on the guard's own clock. */
        try {
            webView.resumeTimers()
        } catch (t: Throwable) {
            Log.w(TAG, "resumeTimers refused on resume: " + t)
        }
        keepTimersAlive()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        KioskController.reassertImmersive(this, hasFocus)
    }

    /**
     * Rotation, without a reload.
     *
     * The manifest lists orientation|screenSize|screenLayout|smallestScreenSize
     * in configChanges, so the system hands the turn to this method instead of
     * destroying the activity. That is not a micro-optimisation: an activity
     * recreate throws the WebView away, and the panel at :8096 is one very
     * large document - the operator would watch the show they are running
     * disappear and reload every time they turned the tablet.
     *
     * What DOES have to be redone is the scale, because the layout width in
     * CSS pixels is derived from the physical width (see initialScalePercent)
     * and the physical width is what just changed.
     */
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        val scale = initialScalePercent()
        webView.setInitialScale(scale)
        /* setInitialScale alone does not re-lay-out a page that is already
         * up, so the guard is re-run: it reports the width it actually got,
         * which is how a bad rotation is found in logcat rather than by
         * squinting at the screen. */
        webView.evaluateJavascript(WIDTH_GUARD) { got ->
            Log.i(TAG, "rotated to ${newConfig.orientation}: scale=$scale guard=$got")
        }
        KioskController.reassertImmersive(this, true)
    }

    /**
     * Hand the exclusive audio port back.
     *
     * The sampler's Oboe stream asks for SharingMode::Exclusive and
     * PerformanceMode::LowLatency (cpp/android/oboe_output.cpp:18-21). Holding
     * one of those while something else is in front is how another app gets a
     * stream it cannot open. A kiosk is almost never backgrounded, which is
     * exactly why this is easy to forget and hard to notice.
     */
    override fun onPause() {
        /* Left running on purpose while another app is in front: the ring
         * records the TABLET, and the operator being in DGX Terminal or
         * Tailscale is exactly the activity they may want to look back at.
         * Only the screen going dark stops it - see onStop. */
        super.onPause()
        /* #1296: and now there is nothing to tear down, so whatever the
           gallery chose while the view was up goes on the wall. */
        app.wallpaper.released()
        PineSampler.sleep()
        /* Give the speaker back when something else is in front. A kiosk is
         * almost never backgrounded, which is why this is easy to forget. */
        mediaFocus?.release()
    }

    override fun onDestroy() {
        timerGuard?.let { webView.removeCallbacks(it) }      // #1241
        timerGuard = null
        if (::bridge.isInitialized) bridge.liveActivity = null
        jackWatch?.stop()
        jackWatch = null
        lockWatch?.stop()
        lockWatch = null
        outputRoute?.stop()
        outputRoute = null
        mediaFocus?.release()
        mediaFocus = null
        /* Detach before destroy or the WebView leaks the activity through
         * its own view tree. */
        (webView.parent as? android.view.ViewGroup)?.removeView(webView)
        webView.destroy()
        super.onDestroy()
    }

    /* ------------------------------------------------------------------ */
    /* The WebView                                                         */
    /* ------------------------------------------------------------------ */

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView() {
        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true

            /* THE WHOLE POINT OF A RADIO TERMINAL. Without this the panel's
             * audio elements refuse to start until someone touches the screen,
             * and a wall-mounted terminal is never touched. */
            mediaPlaybackRequiresUserGesture = false

            /* The panel is plain http (there is no certificate for
             * 10.89.1.246) and it pulls audio and images from the same origin.
             * MIXED_CONTENT is about an https page pulling http subresources -
             * not our case - but a future https panel would hit it, and failing
             * silently is the one behaviour a kiosk must not have. */
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE

            loadsImagesAutomatically = true
            blockNetworkImage = false
            allowFileAccess = false
            allowContentAccess = false
            /* Pinch to zoom. The operator asked for it explicitly, and on a
             * 9" screen showing a panel laid out for a desktop it is not a
             * luxury: some consoles are dense, and being able to pull one
             * closer is the difference between reading it and guessing.
             *
             * displayZoomControls stays OFF - that is the pair of floating
             * +/- buttons, which overlap the page and are useless on a
             * touchscreen that can pinch.
             *
             * NOTE the deliberate tension with assets/pine-touch.js: that
             * stylesheet takes the gesture BACK over a three.js canvas, so
             * the page pinches and the scene rotates. Both were checked on
             * the real screen; check both again if either changes. */
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false

            /* useWideViewPort=false makes the layout width follow the initial
             * scale set below instead of the page's `width=device-width` meta.
             * With the meta in charge the M9 lays out at about 893 CSS px - and
             * the panel's narrow branch is `@media (max-width: 900px)`
             * (app.py:132011), so the terminal would get the phone layout by
             * seven pixels. Confirmed over the devtools socket: innerWidth is
             * 1000 on the real tablet. */
            useWideViewPort = false
            loadWithOverviewMode = false

            /* LOAD_DEFAULT, and it is the right answer rather than the lazy
             * one. The panel is one enormous document served by the station's
             * own FastAPI with its own validators; LOAD_CACHE_ELSE_NETWORK
             * would make the terminal show a stale console after a deploy,
             * which on this stack happens several times an hour. The station
             * already cache-busts everything that matters with ?t= (see
             * StationUrls.music / media). */
            cacheMode = WebSettings.LOAD_DEFAULT

            /* A FLOOR UNDER THE TYPE, so the layout can have the room.
             *
             * Measured on the panel in landscape: 77 visible elements at
             * 10px, 32 at 11px, 14 at 9px. Widening the layout to 1150 CSS
             * px shrinks all of those by 14% in real pixels, which would be
             * the cure causing a worse disease. This is the WebView's own
             * floor - it lifts small text without touching a single CSS rule
             * or moving anything the panel positions itself, which no
             * stylesheet override could promise on a page this large. */
            minimumFontSize = 12
            minimumLogicalFontSize = 12

            /* A desktop-class UA, derived from the real one rather than
             * invented, so the Chrome version stays truthful while the mobile
             * markers that make sites serve a phone layout are gone. */
            userAgentString = desktopUserAgent(userAgentString)
        }

        webView.setInitialScale(initialScalePercent())
        webView.setBackgroundColor(0xFF0B0F0C.toInt())
        webView.isVerticalScrollBarEnabled = false
        webView.isHorizontalScrollBarEnabled = false

        /* Keep the raster when the rail slides over it.
         *
         * OFF_SCREEN_PRERASTER tells the WebView to keep drawing the part of
         * itself that is covered rather than discarding and re-rastering it.
         * That is exactly the drawer case: without it, every open and close of
         * the rail is a re-raster of a very large document, which is visible
         * as the panel flashing back in behind the closing drawer. It costs
         * memory, which is why android:largeHeap is already on. */
        if (WebViewFeature.isFeatureSupported(WebViewFeature.OFF_SCREEN_PRERASTER)) {
            WebSettingsCompat.setOffscreenPreRaster(webView.settings, true)
        }

        /* Never let the renderer be demoted.
         *
         * The panel's renderer is a SANDBOXED process, and the default
         * policy waives its priority whenever the WebView is not visible -
         * which on this device means whenever the drawer is over it or the
         * screen has just come back. Measured here with the panel up:
         * MemFree 96 MB of 3.9 GB, renderer RSS 431 MB, browser 503 MB. At
         * that margin a waived renderer is a renderer Android is willing to
         * trim, and a trimmed renderer means the panel rebuilds a 2.19 MB
         * document from scratch - which is exactly the "it takes a long
         * time to come back" the operator reported. IMPORTANT, never
         * waived, is the whole fix. */
        webView.setRendererPriorityPolicy(
            WebView.RENDERER_PRIORITY_IMPORTANT,
            /* waivedWhenNotVisible = */ false,
        )

        /* The overscroll glow is the one piece of stock Android chrome worth
         * keeping: it is how a finger learns that a pane has ended. */
        webView.overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS

        webView.webViewClient = PanelClient()
        webView.webChromeClient = PanelChrome()
    }

    /**
     * How much to zoom so the panel takes its wide branch.
     *
     * The scale is a percentage where 100 means one CSS pixel per DEVICE
     * pixel, so `cssWidth = widthPx * 100 / scale`. The TB310FU is 1340x800
     * (`wm size`), so:
     *   landscape  1340 px at 134%  ->  1000 CSS px   (measured: innerWidth 1000)
     *   portrait    800 px at  80%  ->  1000 CSS px
     *
     * THE FLOOR USED TO BE 100 and the reasoning was sound at the time: on a
     * screen narrower than 1000 physical px, zooming out to reach 1000 CSS px
     * makes the text smaller, and the panel's narrow branch would be the
     * better answer. It is not the answer here. The operator asked for every
     * orientation, and the panel's `@media (max-width:900px)` branch is a
     * PHONE layout - on a 9" tablet held upright it throws away most of every
     * console. 80% of a 200dpi screen still renders 14px type at about 1.4mm,
     * and pinch-zoom is on. So the floor is 75, which is the shallowest zoom
     * that keeps a 750px-wide device past the 900px cutoff.
     */
    private fun initialScalePercent(): Int {
        val metrics = resources.displayMetrics
        val widthPx = metrics.widthPixels
        if (widthPx <= 0) return 100
        val scale = (widthPx * 100.0 / TARGET_CSS_WIDTH).toInt()
        return scale.coerceIn(75, 400)
    }

    /**
     * Strip the two markers that make a server (or a CSS media query, or
     * the panel's own UA sniffing) decide this is a phone.
     */
    private fun desktopUserAgent(current: String?): String {
        val base = current.orEmpty().ifBlank { DEFAULT_UA }
        return base
            .replace("; wv", "")              // the WebView marker
            .replace(" Mobile Safari", " Safari")
            .replace("Mobile Safari", "Safari")
            .replace(Regex("Android \\d+(\\.\\d+)*; ?"), "")
            .replace("Linux; ", "Linux; X11; ") +
            " PineBoxKiosk/" + BuildConfig.VERSION_NAME
    }

    /* ------------------------------------------------------------------ */
    /* The rail                                                            */
    /* ------------------------------------------------------------------ */

    /**
     * The rail, the bridges and the first load - off the launch path.
     *
     * Ordering inside here is not free-form. installBridge registers the
     * document-start scripts and must finish before load() can start a
     * navigation, or the panel's own scripts run against a page with no
     * window.pineDesktop and no window.pineSampler.
     */
    private fun standUpTheRest() {
        if (isFinishing || isDestroyed) return

        layoutInflater.inflate(R.layout.drawer_rail, railHost, true)
        monitorBar = railHost.findViewById(R.id.vol_monitor)
        monitorValue = railHost.findViewById(R.id.vol_monitor_value)

        installBridge()
        com.pinebox.kiosk.bridge.BootAssets.install(this, webView, statusPanel)   // the opening sequence; see BootAssets.kt
        installRail()

        waiting?.let { rail?.render(it) }
        waiting = null

        /* The key is self-provisioned from the panel the station serves, so
         * the tablet never has to be told a secret by hand. Done before the
         * first load so the very first pineDesktop.get already carries a
         * bearer - and the RAIL needs it for real: every route it writes
         * (/api/dj/output, /api/dj/start, /api/radio/pause) goes through
         * require_auth, even though the read routes answer without one. */
        lifecycleScope.launch {
            try {
                val cfg = app.configStore.read()
                if (cfg.apiKey.isBlank()) app.client.discoverKey()
            } catch (err: Exception) {
                Log.i(TAG, "key discovery deferred: ${err.message}")
            }
            load()
        }
    }

    private fun installRail() {
        drawer.setScrimColor(resources.getColor(R.color.pine_scrim, null))
        /* LOCKED_CLOSED would kill the edge drag; UNLOCKED is the default and
         * is named here only so that a later "lock the rail for a public
         * install" has an obvious place to go. */
        drawer.setDrawerLockMode(DrawerLayout.LOCK_MODE_UNLOCKED)
        widenDragEdge()

        findViewById<View>(R.id.edgeHandle).setOnClickListener { drawer.openDrawer(railHost) }

        val built = RailController(
            drawer = drawer,
            rail = railHost,
            client = app.client,
            scope = lifecycleScope,
            navigate = { url -> webView.loadUrl(url) },
            runScript = { script, back -> webView.evaluateJavascript(script, back) },
        )
        rail = built
        built.bind()

        /* WHERE THE SOUND LEAVES THE TABLET.
         *
         * Android moves media to a headset by itself, and this does not
         * fight that. What it does is (a) reopen the sampler's Oboe stream,
         * which is Exclusive/LowLatency and therefore does NOT migrate - it
         * is disconnected on a route change and has to be built again - and
         * (b) put the socket's name in the rail, because "the audio is
         * coming out of the aux cable" is otherwise not a thing anyone can
         * check from across the room. */
        outputRoute = OutputRoute(
            context = applicationContext,
            handler = android.os.Handler(mainLooper),
            onChange = { where ->
                built.setOutput(where)
                Log.i(TAG, "audio output is now " + where)
            },
            reopen = {
                /* ONLY IF IT WAS ALREADY RUNNING. `attached()` means the
                 * engine is BUILT; `ready()` means the stream is open. The
                 * first version asked attached(), which warmed the stream on
                 * any route change even though the sampler had never been
                 * opened - and a held AAudio output is not free.
                 *
                 * MEASURED, on the tablet, with the station correctly routed
                 * and the page's own <audio> advancing in real time:
                 *
                 *   players: piid:495 type:AAudio usage=USAGE_GAME state:started
                 *   ...and no AudioTrack for the WebView at all
                 *
                 * The one started player was this stream; the panel's media
                 * never reached the mixer, so the tablet was silent while
                 * every indicator said it was playing. Reopen what was
                 * running; never start what was not. */
                if (PineSampler.ready()) {
                    PineSampler.sleep()
                    PineSampler.warm()
                }
            },
        ).also { it.start() }

        /* The monitor slider. It drives the PANEL's own <audio> element rather
         * than anything on the station - see MONITOR_SET and the note on
         * pineMusicVolume in drawer_rail.xml. Posted on release only: every
         * volumechange writes localStorage, so a drag would be a write per
         * pixel. */
        monitorBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar, value: Int, fromUser: Boolean) {
                monitorValue.text = "$value%"
            }

            override fun onStartTrackingTouch(bar: SeekBar) = Unit

            override fun onStopTrackingTouch(bar: SeekBar) {
                webView.evaluateJavascript(monitorSet(bar.progress / 100.0), null)
            }
        })
    }

    /**
     * Make the left edge findable with a thumb.
     *
     * DrawerLayout's drag edge is a private 20dp - 25 physical px on this
     * tablet's 200dpi screen, about 3mm. That is fine for a phone held in one
     * hand and is not fine for a wall-mounted tablet with a bezel, which is
     * the difference between "swiping in my finger from the left side" working
     * first time and working one try in three.
     *
     * There is no public setter, so the ViewDragHelper's edge size is widened
     * by reflection. Wrapped in a catch that does nothing on failure: a
     * missing field on some future androidx build must cost the terminal a
     * narrower edge, never a crash on start.
     */
    private fun widenDragEdge() {
        try {
            val field = DrawerLayout::class.java.getDeclaredField("mLeftDragger")
            field.isAccessible = true
            val dragger = field.get(drawer)
            val edge = dragger.javaClass.getDeclaredField("mEdgeSize")
            edge.isAccessible = true
            val was = edge.getInt(dragger)
            val want = (EDGE_DP * resources.displayMetrics.density).toInt()
            if (want > was) edge.setInt(dragger, want)
            Log.i(TAG, "drawer edge ${was}px -> ${maxOf(was, want)}px")
        } catch (err: Exception) {
            Log.w(TAG, "could not widen the drawer edge; 20dp it is", err)
        }
    }

    /* ------------------------------------------------------------------ */
    /* The bridge                                                          */
    /* ------------------------------------------------------------------ */

    private fun installBridge() {
        bridge = PineDesktopBridge(
            context = applicationContext,
            webView = webView,
            configStore = app.configStore,
            client = app.client,
            /* The ACTIVITY's scope, not the application's: the bridge
             * holds this WebView, and a process-scoped job settling into a
             * destroyed WebView is a leak with a crash on the end of it. */
            scope = lifecycleScope,
            openExternal = ::openExternal,
        )
        webView.addJavascriptInterface(bridge, PineDesktopBridge.NAME)

        val shim = readAsset("pine-bridge.js")
        val touch = readAsset("pine-touch.js")
        /* The layout overrides. A stylesheet rather than a script because it
         * is a stylesheet; it is wrapped in the smallest possible injector so
         * it can ride the same document-start hook and be in force before the
         * first paint, which is the difference between a conformal panel and
         * one that reflows in front of the operator. */
        val tablet = styleInjector("pine-tablet-css", readAsset("tablet.css"))
        /* Media goes out the station's OTHER door. Measured: 38 requests in
         * flight on :8096 and a music fetch that took 46 seconds to return
         * its first 64 kB, purely from HTTP/1.1's six-connections-per-origin
         * queue. A second origin has its own six. See the asset's header. */
        val mediaOrigin = readAsset("pine-media-origin.js")

        /* DOCUMENT_START_SCRIPT is the correct API and is what runs here in
         * practice: it injects before ANY of the page's own scripts. The
         * onPageStarted fallback below races with them - the panel defines
         * a great deal at the top of its document, and a shim that lands
         * second is a shim some of the page has already looked for and not
         * found.
         *
         * The touch stylesheet goes in the same way and for a sharper
         * reason: it has to be in force before FIRST PAINT, or the first
         * gesture on a scene that opened during load is still the browser's. */
        /* THE SAMPLER'S NATIVE ENGINE.
         *
         * attach() is cheap - it allocates the voice table and opens NO audio
         * stream; the page calls pineSampler.warm() itself when the sampler
         * becomes visible, and THAT is where the exclusive AAudio port is
         * taken. Attaching here rather than there is only what makes
         * engineAvailable() answer true at the moment the shim asks.
         *
         * ORDER IS THE WHOLE POINT. SHIM_JS defines window.pineSampler in
         * terms of the native bridge, and sampler-engine.js politely declines
         * to overwrite an existing one. Let the engine get there first and the
         * tablet is quietly on Web Audio: it works, it sounds fine, and it is
         * far too late to play - the exact failure the native engine exists to
         * avoid, and the state the tablet was found in (backend reported
         * "webaudio", window.pineSampler undefined until the fallback loaded)
         * because nothing installed this at all. Document start is comfortably
         * before SamplerAssets, which lands in onPageFinished. */
        val samplerShim = if (PineSampler.attach(applicationContext)) {
            PineSamplerBridge.install(webView, PineSamplerBridge(webView))
            PineSamplerBridge.SHIM_JS
        } else {
            Log.w(TAG, "no native sampler engine in this build; the pads fall back to Web Audio")
            ""
        }

        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            WebViewCompat.addDocumentStartJavaScript(webView, shim, setOf("*"))
            WebViewCompat.addDocumentStartJavaScript(webView, touch, setOf("*"))
            WebViewCompat.addDocumentStartJavaScript(webView, tablet, setOf("*"))
            WebViewCompat.addDocumentStartJavaScript(webView, mediaOrigin, setOf("*"))
            if (samplerShim.isNotEmpty()) {
                WebViewCompat.addDocumentStartJavaScript(webView, samplerShim, setOf("*"))
            }
        } else {
            pendingShim = listOf(shim, touch, tablet, samplerShim).joinToString("\n")
        }
        /* The jack hand-off door, as soon as there is a bridge to put
         * it on - onResume may have run before this. */
        bridge.jackWatch = jackWatch
    }

    /**
     * Wrap a stylesheet in the smallest script that can place it.
     *
     * At document start there is often no <head> yet, so it goes on
     * documentElement if it has to and is retried on DOMContentLoaded; the
     * id makes every later call a lookup and a return. JSONObject.quote does
     * the escaping - hand-rolling that is how a stylesheet with an apostrophe
     * in a content: rule becomes a syntax error inside the station's page.
     */
    private fun styleInjector(id: String, css: String): String {
        val key = org.json.JSONObject.quote(id)
        val text = org.json.JSONObject.quote(css)
        return """
            (function () {
              function put() {
                try {
                  if (document.getElementById($key)) return true;
                  var host = document.head || document.documentElement;
                  if (!host) return false;
                  var style = document.createElement("style");
                  style.id = $key;
                  style.textContent = $text;
                  host.appendChild(style);
                  return true;
                } catch (err) { return false; }
              }
              if (!put()) document.addEventListener("DOMContentLoaded", put);
              window.addEventListener("load", put);
            })();
        """.trimIndent()
    }

    /** Only set when DOCUMENT_START_SCRIPT is unavailable. */
    private var pendingShim: String? = null

    /** One reload in flight at a time - see onReceivedError. */
    private var retryScheduled = false

    /* onReceivedError fires BEFORE onPageFinished for the same navigation,
     * so without this the banner is raised and then immediately hidden
     * again by the finish of the very page that failed. */
    private var mainFrameFailed = false

    private fun readAsset(name: String): String =
        assets.open(name).use { stream ->
            stream.bufferedReader().use(BufferedReader::readText)
        }

    /**
     * Open a link outside the kiosk.
     *
     * Refused while locked: leaving the terminal for a browser is exactly
     * what lock task mode exists to prevent, and an ACTION_VIEW that the
     * system blocks anyway would look to the panel like a success.
     */
    private fun openExternal(uri: Uri): Boolean {
        if (KioskController.isDeviceOwner(this)) {
            Log.i(TAG, "openExternal refused while the terminal is locked: $uri")
            return false
        }
        return try {
            startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (err: ActivityNotFoundException) {
            Log.w(TAG, "nothing to open $uri with", err)
            false
        }
    }

    /* ------------------------------------------------------------------ */
    /* Loading and the offline banner                                      */
    /* ------------------------------------------------------------------ */

    private fun load() {
        showStatus(getString(R.string.status_connecting), retry = false)
        lifecycleScope.launch {
            val cfg = app.configStore.read()
            /* WHICH ROAD, BEFORE THE FIRST BYTE.
             *
             * This tablet is carried. At home the station is on the LAN; on
             * the end of somebody's phone it is on the tailnet. Asking first
             * costs one /healthz against an address that is nearly always the
             * right one, and saves a whole failed load of a very large
             * document against an address that is not.
             *
             * reachable() is what settles it - see StationClient. The offline
             * banner already calls the same thing on its own retry, so a
             * tablet that walks out of the house re-chooses its road with no
             * new machinery and no "the network changed" listener. */
            val began = System.currentTimeMillis()
            val found = app.client.reachable()
            val roadMs = System.currentTimeMillis() - began
            val base = Reach.base(cfg)
            Log.i(TAG, if (found) "station " + Reach.said
                       else "no station on any road: " + Reach.said)
            /* WHAT IT CONFIRMED ON ITS WAY UP, written down where the Pine
             * Box application can read it back - see net/Readiness.kt. This
             * is on the background thread the probe already used, because
             * two of its checks read /proc and the interface list. */
            try {
                com.pinebox.kiosk.net.Readiness.take(this@MainActivity, cfg, roadMs)
            } catch (err: Exception) {
                Log.w(TAG, "readiness could not be taken: " + err.message)
            }
            stationHost = Uri.parse(base).host.orEmpty()
            webView.loadUrl("$base/")
        }
    }

    private fun showStatus(message: String, retry: Boolean) {
        statusText.text = message
        statusRetry.visibility = if (retry) View.VISIBLE else View.GONE
        statusPanel.visibility = View.VISIBLE
    }

    private fun hideStatus() {
        if (statusPanel.visibility != View.GONE) statusPanel.visibility = View.GONE
    }

    /**
     * Back: out of the rail, then back through the panel, then nowhere.
     *
     * With no history to go back through, the callback stays enabled and
     * does nothing - falling through would finish the activity, and on a
     * HOME-registered app that means a blank screen where the terminal was.
     */
    private fun installBackPolicy() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (drawer.isDrawerOpen(railHost)) {
                    drawer.closeDrawer(railHost)
                    return
                }
                if (webView.canGoBack()) webView.goBack()
            }
        })
    }

    private inner class PanelClient : WebViewClient() {

        /**
         * Two prefixes lifted off the WebView's six sockets. PineNet carries
         * the measurements; the short version is that the panel draws ~180
         * full-size 1024x1024 PNGs as thumbnails, which saturates an
         * HTTP/1.1 connection pool, and everything else queues behind them -
         * including the /vendor/three.min.js a 3JS view is waiting on, which
         * was measured still unanswered after three minutes.
         *
         * Returns null for everything it does not own, so media Range
         * requests, POSTs and the API polls go through untouched.
         */
        override fun shouldInterceptRequest(
            view: WebView,
            request: WebResourceRequest,
        ): WebResourceResponse? = PineNet.intercept(request)

        override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
            super.onPageStarted(view, url, favicon)
            mainFrameFailed = false
            pendingShim?.let { view.evaluateJavascript(it, null) }
        }

        override fun onPageFinished(view: WebView, url: String) {
            super.onPageFinished(view, url)
            if (mainFrameFailed) return
            hideStatus()

            /* THE MEASUREMENT, kept in the app rather than in a notebook.
             * `adb logcat -s PineKioskActivity` gives time-to-first-paint on
             * the real network without a profiler attached, which is the only
             * kind of number anyone will actually take again later. */
            Log.i(TAG, "panel up in ${SystemClock.uptimeMillis() - startedAt}ms: $url")

            /* Belt and braces on the layout width. If the initial scale did
             * not land us past the panel's 900px cutoff - a different WebView
             * provider, a changed viewport meta - force the layout width
             * outright. Cheap, idempotent, and it fails loudly in the log
             * rather than silently serving the phone layout. */
            view.evaluateJavascript(WIDTH_GUARD, null)

            /* THE SILENT TABLET. Not autoplay, not the station, not Android:
             * the panel's own player was at volume 0 because
             * musicVolumeRemember (app.py:142170) persists every volumechange
             * into localStorage, and this WebView is a fresh browser profile
             * whose pineMusicVolume happened to be "0". A new install, a
             * cleared profile or the next tablet would be silent again for
             * exactly the same reason, and it looks like broken audio.
             * Healed here, on every load, and ONLY the absent-or-zero case -
             * an operator who deliberately set 30% keeps 30%. */
            view.evaluateJavascript(AUDIO_HEAL) { got ->
                Log.i(TAG, "monitor level: $got")
                readMonitorInto(got)
            }

            /* The Sampler, shipped in the APK's assets and EVALUATED rather
             * than linked: the panel is an http:// origin and the assets are
             * file:///android_asset/, so a <script src> at them is refused
             * outright. Here rather than at document start on purpose - the
             * panel is a 2 MB document and its own scripts should have had
             * their run before five more files are laid on top. The bundle
             * guards itself with __pineSamplerBooted, and that guard is
             * load-bearing: onPageFinished can fire more than once for one
             * page, and a second evaluation leaves the first module's feed
             * subscription live but unreachable - a leaked poller against a
             * station with a documented history of being starved by chatty
             * clients. */
            SamplerAssets.install(this@MainActivity, webView)
            /* AFTER the sampler, on purpose. rail.js adopts the sampler's
             * existing host and edge handle rather than building a second
             * one, so the sampler must already have scaffolded itself. */
            ViewAssets.install(this@MainActivity, webView)
        }

        override fun shouldOverrideUrlLoading(
            view: WebView,
            request: WebResourceRequest,
        ): Boolean {
            val target = request.url
            val host = target.host.orEmpty()
            /* Same host stays in the panel. Everything else is a link out,
             * which on a locked terminal means "refuse", and on an
             * unprovisioned one means the system browser. */
            if (host.isEmpty() || host.equals(stationHost, ignoreCase = true)) return false
            openExternal(target)
            return true
        }

        override fun onReceivedError(
            view: WebView,
            request: WebResourceRequest,
            error: WebResourceError,
        ) {
            super.onReceivedError(view, request, error)
            // Only the MAIN document failing means the terminal is blind; a
            // missing clip is the station's business, not the kiosk's.
            if (!request.isForMainFrame) return
            mainFrameFailed = true
            showStatus(getString(R.string.status_offline, stationHost), retry = true)
            /* Retry on our own, because nobody is standing at the tablet.
             * Four seconds matches the feed's poll: if the station is on its
             * way back up, the banner clears within one cycle of it. The
             * flag is what stops a page with several failing frames
             * queueing several reloads. */
            if (!retryScheduled) {
                retryScheduled = true
                webView.postDelayed({
                    retryScheduled = false
                    if (!isFinishing) load()
                }, RETRY_MS)
            }
        }
    }

    /** Put the page's actual level on the rail's slider. */
    private fun readMonitorInto(result: String?) {
        val value = result?.trim()?.trim('"')?.toDoubleOrNull() ?: return
        if (value < 0.0 || value > 1.0) return
        val percent = Math.round(value * 100.0).toInt()
        monitorBar.progress = percent
        monitorValue.text = "$percent%"
    }

    private inner class PanelChrome : WebChromeClient() {

        /**
         * The panel's console, in logcat. This is how a bridge fault is
         * found on a device with no address bar - `adb logcat -s PinePanel`.
         */
        /* A PAGE MUST NOT BE ABLE TO FREEZE THE APP BY TALKING.
         *
         * This forwarded every console message straight to Log.d, and
         * onConsoleMessage runs on the MAIN THREAD. That is fine for the
         * handful of lines a healthy page emits and fatal for a page in a
         * loop: measured during an ANR, a WebGL scene drawing an empty
         * geometry produced "RENDER WARNING: Render count or primcount is 0"
         * several times every ten milliseconds, and each one became a
         * main-thread log write. The trace showed the main thread blocked
         * inside WebView native code with nothing else runnable, and the
         * operator got "Pine Box isn't responding".
         *
         * So the forwarding is now BUDGETED. Anything worse than a warning
         * always goes through - an error is the thing you are looking for -
         * and the rest is capped at a few dozen lines a second, with one
         * line saying how many were dropped so the silence is never a
         * mystery. The console stays useful and stops being a lever that
         * can stop the terminal. */
        private var spoke = 0
        private var dropped = 0
        private var windowAt = 0L

        override fun onConsoleMessage(message: ConsoleMessage): Boolean {
            val now = android.os.SystemClock.uptimeMillis()
            if (now - windowAt >= 1000L) {
                if (dropped > 0) {
                    Log.d("PinePanel", "(+$dropped more console lines in that second)")
                }
                windowAt = now
                spoke = 0
                dropped = 0
            }
            /* ERRORS GET A BIGGER ALLOWANCE, NOT AN UNLIMITED ONE.
             *
             * Letting every error through was the first shape of this, and it
             * missed the point: the flood that caused the ANR was an ERROR -
             * one TypeError thrown from an animation frame, 144 times in a
             * single window. A repeating error floods exactly as well as a
             * repeating warning, and the first few carry all the information
             * the hundredth does. */
            val loud = message.messageLevel() == ConsoleMessage.MessageLevel.ERROR
            val allowed = if (loud) CONSOLE_ERRORS_PER_SECOND else CONSOLE_PER_SECOND
            if (spoke >= allowed) {
                dropped += 1
                return true
            }
            spoke += 1
            Log.d(
                "PinePanel",
                "${message.messageLevel()} ${message.message()} " +
                    "(${message.sourceId()}:${message.lineNumber()})",
            )
            return true
        }

        /**
         * Let the page open the microphone - and ONLY the microphone.
         *
         * KEPT, THOUGH IT NO LONGER FIRES ON THIS BUILD. Measured: the
         * panel is served from http://10.89.1.246:8096, which is not a
         * secure context, so Chromium removes `navigator.mediaDevices`
         * outright and the page can never reach the point of ASKING. The
         * tablet's ear is therefore native (see MicCapture and the bridge's
         * micStart/micStop). This stays because the same APK may one day
         * load the panel from a trustworthy origin - a loopback proxy, or
         * TLS - and on that day the page will ask, and the answer should
         * still be "the microphone, and nothing else".
         *
         * Granted per-resource rather than with request.grant(request
         * .resources) wholesale: that would hand over the CAMERA too on any
         * page that asked, and nothing here wants a camera. A kiosk pointed
         * at one trusted station is still not a reason to say yes to
         * everything it requests.
         */
        override fun onPermissionRequest(request: PermissionRequest) {
            val wanted = request.resources.filter {
                it == PermissionRequest.RESOURCE_AUDIO_CAPTURE
            }.toTypedArray()
            if (wanted.isEmpty()) {
                request.deny()
                return
            }
            if (ContextCompat.checkSelfPermission(
                    this@MainActivity, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
                /* Ask the platform first; the page can try again once the
                 * operator has answered. Denying now is honest - the app
                 * genuinely cannot grant what it does not hold. */
                ActivityCompat.requestPermissions(this@MainActivity,
                    arrayOf(Manifest.permission.RECORD_AUDIO), MIC_REQUEST)
                request.deny()
                return
            }
            request.grant(wanted)
        }
    }

    companion object {
        private const val TAG = "PineKioskActivity"

        /* #1241: how often the timer guard pokes resumeTimers(). Twenty
         * seconds is far below anything a listener would notice and far
         * above anything that costs measurable battery - the call is a
         * no-op on a WebView whose timers are already running. */
        private const val TIMER_GUARD_MS = 20_000L

        /** The talk dot's microphone request. */
        private const val MIC_REQUEST = 4101

        const val EXTRA_FROM_BOOT = "com.pinebox.kiosk.FROM_BOOT"

        /** See initialScalePercent. The panel's wide branch starts at 901. */
        /**
         * The layout width the panel is asked to lay itself out at.
         *
         * RAISED FROM 1000 AFTER MEASURING, not by preference. "It is still
         * scaled too big... the application is still very cramped even on
         * mobile... I need to be able to spread the UI out." Those two
         * complaints pull opposite ways, so the page was surveyed over the
         * devtools socket in landscape:
         *
         *   viewport            1000 x 598 CSS px   (dpr 1.25, 1340x800 real)
         *   controls on screen  112, of which 94 under 32px tall, median 30
         *   text on screen      123 elements at 9-11px
         *   flex rows           60, of which 22 have neighbours under 6px apart
         *
         * The type was never too big - most of it is TINY. What is too big is
         * the scale: at 1000 CSS px across a 1340px panel everything renders
         * at 1.34x, so the furniture eats a 598px-tall viewport and the
         * content is squeezed into what is left. Height is the scarce axis in
         * landscape and nothing was being spent on it.
         *
         * 1150 buys back 15%: the viewport becomes roughly 1155 x 690, which
         * is 92 more rows of height for the same screen. The cost is that
         * 10px text would render at 11.6 physical px instead of 13.4 - so it
         * is paid for by a WebView minimum font size of 12 (see
         * configureWebView), which lifts that same text to 13.9 and leaves it
         * slightly LARGER than it was while the layout gets more room.
         *
         * Keep tablet.css's breakpoint above this number. It is the one thing
         * that can silently undo all of it: at 1155 a `max-width: 1100px`
         * query simply stops matching and every tablet rule turns off.
         */
        private const val TARGET_CSS_WIDTH = 1150.0

        /** See widenDragEdge. 20dp is DrawerLayout's own; 40 is a thumb. */
        private const val EDGE_DP = 40f

        private const val RETRY_MS = 4_000L

        private const val DEFAULT_UA =
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) " +
                "Chrome/120.0.0.0 Safari/537.36"

        /**
         * Set the panel's monitor level and make it stick.
         *
         * `volumechange` has to be dispatched explicitly: the listener
         * musicVolumeRemember installs is what writes localStorage, and
         * assigning `.volume` from script fires the event in Chrome - but the
         * panel may not have bound the listener yet on a very early call, so
         * the keys are written here too. Belt and braces, and both are cheap.
         */
        private fun monitorSet(level: Double): String = """
            (function () {
              try {
                var v = $level;
                document.querySelectorAll("audio, video").forEach(function (el) {
                  el.volume = v;
                  if (v > 0) el.muted = false;
                });
                localStorage.setItem("pineMusicVolume", String(v));
                localStorage.setItem("pineMusicMuted", v > 0 ? "0" : "1");
                return v;
              } catch (err) { return "failed:" + err; }
            })();
        """.trimIndent()

        /**
         * The silent-tablet cure. Returns the level the page is now at, so the
         * rail's slider can show the truth rather than a default.
         */
        private val AUDIO_HEAL = """
            (function () {
              try {
                var raw = localStorage.getItem("pineMusicVolume");
                var now = raw === null ? null : Number(raw);
                var muted = localStorage.getItem("pineMusicMuted") === "1";
                /* Absent or zero (or muted) only. A deliberate 30% is a
                 * decision and must survive a restart - that is the whole
                 * point of musicVolumeRemember. */
                if (now === null || !isFinite(now) || now <= 0 || muted) {
                  document.querySelectorAll("audio, video").forEach(function (el) {
                    el.volume = 1;
                    el.muted = false;
                  });
                  localStorage.setItem("pineMusicVolume", "1");
                  localStorage.setItem("pineMusicMuted", "0");
                  console.warn("[pine] the monitor was silent (" + raw
                    + "); set to 1 - see MainActivity.AUDIO_HEAL");
                  return 1;
                }
                return now;
              } catch (err) { return "failed:" + err; }
            })();
        """.trimIndent()

        /**
         * Force the layout width past the panel's `@media (max-width:900px)`
         * cutoff if the initial scale did not manage it.
         */
        private val WIDTH_GUARD = """
            (function () {
              try {
                var meta = document.querySelector('meta[name="viewport"]');
                if (!meta) {
                  meta = document.createElement("meta");
                  meta.setAttribute("name", "viewport");
                  document.head.appendChild(meta);
                }
                /* Two jobs, and they are separate.
                 *
                 * ZOOM: a page that says user-scalable=no disables pinch in
                 * WebView no matter what the app asks for, so scalability is
                 * asserted here on every page rather than hoped for. The
                 * range is wide on purpose - 0.25 pulls a whole dense console
                 * into view, 5 makes a single reading legible.
                 *
                 * WIDTH: only forced when the layout came out under the
                 * panel's @media (max-width:900px) cutoff (app.py:132011).
                 * Forcing it otherwise would fight the initial scale. */
                var scale = "minimum-scale=0.25, maximum-scale=5, user-scalable=yes";
                if (window.innerWidth > 900) {
                  var had = meta.getAttribute("content") || "";
                  if (had.indexOf("user-scalable") < 0) {
                    meta.setAttribute("content", had ? had + ", " + scale : scale);
                  }
                  return "ok:" + window.innerWidth;
                }
                meta.setAttribute("content", "width=1000, initial-scale=1, " + scale);
                console.warn("[pine] forced viewport to 1000px; innerWidth was " + window.innerWidth);
                return "forced";
              } catch (err) { return "failed:" + err; }
            })();
        """.trimIndent()
    }
}
