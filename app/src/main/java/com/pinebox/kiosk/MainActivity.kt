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
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.PixelCopy
import android.os.Handler
import android.os.Looper
import android.util.Base64
import java.io.ByteArrayOutputStream
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
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.GravityCompat
import androidx.drawerlayout.widget.DrawerLayout
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import com.pinebox.kiosk.bridge.PineDesktopBridge
import com.pinebox.kiosk.bridge.SamplerAssets
import com.pinebox.kiosk.bridge.ViewAssets
import com.pinebox.kiosk.config.HotCorners
import com.pinebox.kiosk.kiosk.KioskController
import com.pinebox.kiosk.net.PineNet
import com.pinebox.kiosk.net.LoopDoor
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

    private lateinit var bridge: PineDesktopBridge
    private var videoWall: com.pinebox.kiosk.video.PineVideoWall? = null  // #1426
    private var splicePreview: com.pinebox.kiosk.video.PineSplicePreview? = null

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
        /* #1182T: the handle standby reaches us through. onCreate rather than
         * onResume, because standby acts precisely while this activity is NOT
         * in front - see the companion's note on how this differs from
         * PineDesktopBridge.liveActivity. */
        live = this
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

    // 2026-09-14: THE KEY CHORD. "if I press the lock button and the volume
    // up button, I would like to take a picture of the screen and then also
    // file a Pine report and dictate a message." Android keeps the power key
    // for itself - an app never sees it - so the chord is volume-up pressed
    // TWICE within 700 ms. The first press still changes the volume (it is
    // let through); the second is taken, the window is copied with
    // PixelCopy, and the page's PineReport.fromKey gets the picture: a flash,
    // the pad, and the dot listening.
    private var volumeUpAt = 0L

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP && event != null && event.repeatCount == 0) {
            val now = SystemClock.elapsedRealtime()
            if (now - volumeUpAt < 700L) {
                volumeUpAt = 0L
                reportShot()
                return true
            }
            volumeUpAt = now
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun reportShot() {
        shootScreen { shot ->
            /* An empty string when the copy failed, as before: the page's
             * fromKey opens the pad without a picture rather than not at
             * all. */
            val js = "window.PineReport && PineReport.fromKey(" +
                com.pinebox.kiosk.bridge.BridgeEnvelope.quote(shot?.dataUrl ?: "") + ")"
            runOnUiThread { webView.evaluateJavascript(js, null) }
        }
    }

    /** One picture of the window, ready for a page: a data URL and its size. */
    data class Shot(val dataUrl: String, val w: Int, val h: Int)

    /**
     * THE PICTURE OF THE SCREEN, SHARED BY THE KEY CHORD AND THE CORNER.
     *
     * "If I swipe into the tablet from the top left of the screen down to
     *  the center, I want to take a screenshot of the screen and I want to
     *  be able to draw on the screen and outline things with my finger in
     *  red and be able to submit that image along with the report into the
     *  Pine box inbox."
     *
     * The chord above and the bridge's `screenShot` (which the top-left
     * corner calls, through hot-corners.js) want the same thing, so there is
     * one road: PixelCopy of the whole window - the WebView, the drawer if
     * it is open, everything - compressed off the main thread and handed
     * back as a data URL. Call it on the main thread; [done] arrives ONCE,
     * on a worker thread, with null when the window could not be copied
     * (nothing on screen yet, or PixelCopy refused - the reason is in the
     * log under PineKiosk).
     */
    fun shootScreen(done: (Shot?) -> Unit) {
        try {
            val w = window
            val root = w?.decorView
            if (w == null || root == null || root.width <= 0 || root.height <= 0) {
                Log.w("PineKiosk", "screen shot: no window to copy yet")
                done(null)
                return
            }
            val width = root.width
            val height = root.height
            val bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            PixelCopy.request(w, bmp, { result ->
                if (result == PixelCopy.SUCCESS) {
                    Thread {
                        val out = ByteArrayOutputStream()
                        // JPEG at 70: a 1340x800 screen is ~120 kB, which evaluateJavascript
                        // carries without complaint; PNG would be four times that.
                        bmp.compress(Bitmap.CompressFormat.JPEG, 70, out)
                        bmp.recycle()
                        val b64 = Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
                        done(Shot("data:image/jpeg;base64," + b64, width, height))
                    }.start()
                } else {
                    Log.w("PineKiosk", "screen shot: PixelCopy result $result")
                    bmp.recycle()
                    done(null)
                }
            }, Handler(Looper.getMainLooper()))
        } catch (e: Exception) {
            Log.w("PineKiosk", "screen shot failed: ${e.message}")
            done(null)
        }
    }

    /* THE CORNER SWIPES, AND THE DRAWER THAT WOULD EAT TWO OF THEM.
     *
     * "If I swipe into the tablet from the top left of the screen down to
     *  the center ... If I swipe from the left corner up to the center ..."
     *
     * Both of those start on the LEFT edge, and the left edge belongs to the
     * DrawerLayout: its drag edge is widened to 40dp (widenDragEdge), and
     * DrawerLayout.onInterceptTouchEvent runs before the WebView sees a
     * single event, so a swipe out of the top-left or bottom-left corner
     * would open the rail and the page would never hear of it.
     *
     * So: while hot corners are on, a finger landing inside the configured
     * activation square of any
     * corner locks the drawer closed for the length of that one gesture,
     * and the events fall through to the WebView, where hot-corners.js is
     * watching. The lock is put back once the finger is up (after the UP
     * has been dispatched, so the dragger never sees a mode change mid-
     * gesture), which is what keeps an edge swipe that starts anywhere BUT
     * a corner opening the rail as before.
     *
     * THE EDGE HANDLE TAKES THE OTHER HALF. Measured with the drawer locked:
     * the right corners reached the page and the left ones still did not,
     * because the 14dp ribbon down the left bezel (R.id.edgeHandle) is a
     * clickable View ON TOP of the WebView, and a clickable View consumes
     * the DOWN it is under - the FrameLayout never offers the gesture to
     * the WebView beneath. So for a claimed corner gesture the handle is
     * made unclickable too, and clickable again on the way up; its click
     * listener is untouched and its tap works everywhere but inside a live
     * corner, which is where a tap was never going to be meant for it.
     *
     * A corner set to "off" is not claimed at all, and nothing is claimed
     * while the drawer is already open - locking it closed then would slam
     * it shut under the operator's hand. */
    private var cornerLockWas = -1

    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        /* Corners are decided first. A live corner still belongs to the page;
         * every other point inside the native picture belongs to the wall,
         * which handles tap, drag and bottom-right resize at UI-thread speed. */
        if (ev.actionMasked == MotionEvent.ACTION_DOWN) {
            cornerLockWas = -1
            val prefs = HotCorners.live
            if (prefs.enabled && ::drawer.isInitialized && ::railHost.isInitialized
                && !drawer.isDrawerOpen(railHost)) {
                val corner = cornerAt(ev.rawX, ev.rawY)
                if (corner != null && prefs.of(corner) != "off") {
                    cornerLockWas = drawer.getDrawerLockMode(GravityCompat.START)
                    drawer.setDrawerLockMode(DrawerLayout.LOCK_MODE_LOCKED_CLOSED, GravityCompat.START)
                    findViewById<View?>(R.id.edgeHandle)?.isClickable = false
                }
            }
        }
        val wallHandled = if (cornerLockWas < 0) {
            videoWall?.observeTouch(ev) ?: false
        } else {
            false
        }
        val handled = if (wallHandled) true else super.dispatchTouchEvent(ev)
        if (ev.actionMasked == MotionEvent.ACTION_UP || ev.actionMasked == MotionEvent.ACTION_CANCEL) {
            if (cornerLockWas >= 0) {
                drawer.setDrawerLockMode(cornerLockWas, GravityCompat.START)
                findViewById<View?>(R.id.edgeHandle)?.isClickable = true
                cornerLockWas = -1
            }
        }
        return handled
    }

    /** Which corner a point is in, or null. Raw coordinates are window
     *  coordinates here: the activity is full screen and the decor sits at
     *  0,0, and it is the decor's size that says where the corners are. */
    private fun cornerAt(x: Float, y: Float): String? {
        val root = window?.decorView ?: return null
        val w = root.width
        val h = root.height
        if (w <= 0 || h <= 0) return null
        val zone = HotCorners.live.activationZonePx.toFloat()
        val left = x <= zone
        val right = x >= w - zone
        val top = y <= zone
        val bottom = y >= h - zone
        return when {
            left && top -> "tl"
            right && top -> "tr"
            left && bottom -> "bl"
            right && bottom -> "br"
            else -> null
        }
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
        /* The camera's door, open and waiting. The lens stays shut until
         * somebody connects, and #1182T moved the door OUT of the service so
         * that "open and waiting" no longer means a camera-type foreground
         * service standing all day - see PineCameraDoor. */
        com.pinebox.kiosk.camera.PineCameraDoor.open(this)
        super.onResume()

        /* #1182T: THE TERMINAL IS VISIBLE, SO IT IS NOT IN STANDBY.
         *
         * Unconditional, and early - before the media focus below, and before
         * anything else in here reads the state of the world. A foreground app
         * that asked us to relax and then died without saying otherwise does
         * not get to leave the terminal relaxed while the operator is looking
         * straight at it. This is one of the four roads back that need nobody
         * alive to ask: this method, SCREEN_ON, an explicit level=off, and
         * Revive. */
        com.pinebox.kiosk.kiosk.Standby.leave(this, "kiosk onResume")
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
        if (mediaFocus == null) {
            mediaFocus = MediaFocus(applicationContext).also { focus ->
                /* #1182T: A FOCUS LOSS IS A VOLUME EVENT, NOT A STOP, and
                 * this is the line that carries it into the page.
                 *
                 * Audio focus can duck other apps for us; the framework will
                 * not duck an app against itself, and the thing playing here
                 * IS ours - the broadcast is an <audio> element inside this
                 * WebView. So MediaFocus publishes a gain and the host applies
                 * it, exactly as DuckController already does for the sampler.
                 * See MediaFocus.note for what each focus message now means
                 * and why AUDIOFOCUS_LOSS keeps playing. */
                focus.onDuck = { gain ->
                    runOnUiThread {
                        runCatching { webView.evaluateJavascript(focusDuck(gain), null) }
                            .onFailure { Log.w(TAG, "the duck would not reach the page: " + it) }
                    }
                }
            }
        }
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

    /* ------------------------------------------------------------------ */
    /* #1182T: what standby is allowed to reach in here                    */
    /* ------------------------------------------------------------------ */

    /**
     * Rest or wake the jack poll. Main thread; Standby posts it there.
     *
     * rest() rather than stop() on purpose - stop() would hand the audio back
     * from the headphone cable to the speaker, which is the owner's rule
     * broken sideways. See JackWatch.rest.
     */
    internal fun standbyJackPoll(on: Boolean) {
        if (on) jackWatch?.start() else jackWatch?.rest()
    }

    /**
     * Drop the WebView's in-memory resource cache.
     *
     * clearCache(FALSE) - the argument is `includeDiskFiles` and passing true
     * would take the disk cache with it, making the way back slower for
     * nothing. What goes is decoded images and fetched sub-resources.
     *
     * WHAT IS DELIBERATELY NOT DONE HERE, and it is the largest thing the
     * AutoBrowse document asked for: onPause(), pauseTimers(), and letting the
     * document go. All three are refused and the evidence is our own. #1241
     * measured this tablet with rAF firing and setTimeout and setInterval NOT
     * - a fresh one-second interval managed zero ticks in fifteen - and what
     * it cost was the whole station: the voice-feed poll, the reload stamp,
     * the solo-gate un-gag and the stuck-clip watchdog are all setInterval, so
     * the tablet went silent and could not be recovered from the web side at
     * all. The timer guard above exists BECAUSE of that. And the document is
     * out by one on the document itself: the broadcast the operator is
     * listening to is an <audio> element inside it, so "let the WebView drop
     * its document" is spelled, on this device, "stop the radio".
     */
    internal fun standbyDropWebCache() {
        runCatching { webView.clearCache(false) }
            .onFailure { Log.w(TAG, "the web cache would not drop: " + it) }
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
        if (live === this) live = null                       // #1182T
        timerGuard?.let { webView.removeCallbacks(it) }      // #1241
        timerGuard = null
        videoWall?.stop()
        splicePreview?.stop()
        splicePreview = null
        videoWall?.onTap = null
        videoWall?.onLongPress = null
        videoWall?.onClipChanged = null
        videoWall?.onBoxChanged = null
        videoWall?.onHoldExpired = null
        videoWall = null
        if (::bridge.isInitialized) {
            bridge.videoWall = null
            bridge.splicePreview = null
            bridge.liveActivity = null
        }
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

        /* The panel's offscreen film and gallery surfaces can already retain
         * hundreds of MB. Do not also ask Chromium to pre-raster covered
         * content: on this 4 GB tablet that pushes the renderer into LMK. */

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
                /* The touch road's copy of the corner preferences, before
                 * the first finger can land. See config/HotCorners.kt. */
                HotCorners.read(app.configStore)
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
            configStore = app.configStore,
            scope = lifecycleScope,
            navigate = { url -> webView.loadUrl(url) },
            runScript = { script, back -> webView.evaluateJavascript(script, back) },
            pageLocation = { webView.url.orEmpty() },
            restorePage = { load() },
            repairAudioRoute = {
                val jack = jackWatch?.refresh() ?: "jack watch is not running"
                "$jack; output: ${outputRoute?.current() ?: "not available"}"
            },
            openBluetooth = ::openBluetoothSettings,
            exitToSystem = ::exitToSystem,
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

    }

    /** The rail's native escape routes.  These do not depend on the page
     * being healthy, which matters most when a bluetooth route is needed. */
    private fun openBluetoothSettings() {
        KioskController.exitLockTask(this)
        KioskController.showSystemBars(this)
        val bluetooth = Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS)
        val fallback = Intent(android.provider.Settings.ACTION_SETTINGS)
        try {
            startActivity(bluetooth)
        } catch (err: ActivityNotFoundException) {
            Log.w(TAG, "bluetooth settings unavailable; opening settings", err)
            startActivity(fallback)
        }
    }

    private fun exitToSystem() {
        KioskController.leaveForSystem(this)
        try {
            startActivity(Intent(android.provider.Settings.ACTION_SETTINGS))
        } catch (err: ActivityNotFoundException) {
            Log.w(TAG, "settings unavailable while leaving kiosk", err)
        }
        finishAndRemoveTask()
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

    /**
     * #1426: THE ENDLESS SET GETS ITS OWN SURFACE.
     *
     * Added to R.id.root AFTER the WebView, so it is above it in the
     * FrameLayout; PineVideoWall's own surfaces are media-overlay, which
     * puts them over the panel and under this app's chrome. It starts
     * GONE and costs nothing until the page asks for it.
     */
    private fun installVideoWall() {
        val found = findViewById<android.view.View>(R.id.root)
        android.util.Log.i("PineVideoWall", "install: root=" + (found?.javaClass?.simpleName ?: "NULL"))
        val root = found as? android.widget.FrameLayout
        if (root == null) {
            android.util.Log.w("PineVideoWall", "install: no FrameLayout at R.id.root - no wall")
            return
        }
        val wall = try {
            com.pinebox.kiosk.video.PineVideoWall(this, app.client, lifecycleScope)
        } catch (err: Throwable) {
            android.util.Log.e("PineVideoWall", "install: build failed", err)
            return
        }
        root.addView(
            wall,
            android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        /* [#1441] the picture is native, so the tap on it is native too -
         * handed to the page, which owns the hold sheet and everything in
         * it. Screen pixels go over as they are; the page divides by its
         * own devicePixelRatio, where that number actually lives. */
        wall.onTap = { x, y ->
            val js = ("try{window.PineSfxTv&&PineSfxTv.tapPicture&&"
                + "PineSfxTv.tapPicture(" + x.toInt() + "," + y.toInt() + ")}catch(e){}")
            webView.post { webView.evaluateJavascript(js, null) }
        }
        wall.onLongPress = { x, y ->
            val js = ("try{window.PineSfxTv&&PineSfxTv.holdPicture&&"
                + "PineSfxTv.holdPicture(" + x.toInt() + "," + y.toInt() + ")}catch(e){}")
            webView.post { webView.evaluateJavascript(js, null) }
        }
        wall.onClipChanged = { id ->
            val quoted = org.json.JSONObject.quote(id)
            val js = ("try{window.PineSfxTv&&PineSfxTv.wallClip&&"
                + "PineSfxTv.wallClip($quoted)}catch(e){}")
            webView.post { webView.evaluateJavascript(js, null) }
        }
        /* The hot gesture stays native; only the settled rectangle crosses
         * into JavaScript so the next launch inherits it without flooding the
         * WebView with one evaluateJavascript call per MotionEvent. */
        wall.onBoxChanged = { x, y, w, h ->
            val js = ("try{window.PineSfxTv&&PineSfxTv.wallBoxChanged&&"
                + "PineSfxTv.wallBoxChanged($x,$y,$w,$h)}catch(e){}")
            webView.post { webView.evaluateJavascript(js, null) }
        }
        wall.onHoldExpired = {
            val js = ("try{window.PineSfxTv&&PineSfxTv.releaseHold&&"
                + "PineSfxTv.releaseHold()}catch(e){}")
            webView.post { webView.evaluateJavascript(js, null) }
        }
        videoWall = wall
        bridge.videoWall = wall
        val preview = com.pinebox.kiosk.video.PineSplicePreview(this, app.client, lifecycleScope)
        root.addView(preview, android.widget.FrameLayout.LayoutParams(1, 1))
        splicePreview = preview
        bridge.splicePreview = preview
        android.util.Log.i("PineVideoWall", "install: wall handed to the bridge")
    }

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
        /* [#1448] The WebView is left OPAQUE, and the note is here so the
         * next person does not repeat the reasoning that led away from it.
         *
         * A media-overlay SurfaceView is composited ABOVE this WebView, so
         * the picture can only sit IN FRONT of the panel. To put the
         * endless clip BEHIND the listen panel the order has to be
         * inverted: surface under the WebView, WebView transparent. That
         * was built and measured, and it changed nothing on screen,
         * because every view paints its own opaque ground anyway
         * (rgb(10,12,16), read off the device) - so it would also have
         * needed the panel's ground rebuilt view by view.
         *
         * It is not needed. `pl-bare` is the listen view's own full-screen
         * wallpaper mode and it hides the panel, so in the one place the
         * picture is meant to be the wallpaper there is nothing above it
         * to preserve, and the surface can stay where it is and take the
         * whole screen (#1448 in sfx-tv.js). A transparent WebView gives
         * up an opaque-surface compositing path for no gain, and "seamless"
         * is the whole point here, so it goes. */
        webView.addJavascriptInterface(bridge, PineDesktopBridge.NAME)
        installVideoWall()                                    // #1426
        /* THE FIRST RESUME HAS ALREADY HAPPENED. This runs from
         * standUpTheRest, posted after the first frame - which is after
         * onResume, whose `bridge.liveActivity = this` is guarded on the
         * bridge existing and so did nothing on a cold start. Measured:
         * screenShot answered "the terminal's window is not on screen"
         * on every fresh launch until something paused and resumed the
         * activity, and the USB picker had the same hole. So the window
         * is handed over here as well, when the activity is already up. */
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) {
            bridge.jackWatch = jackWatch
            bridge.liveActivity = this
        }

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
            /* THROUGH THE LOOPBACK DOOR, so the panel is a SECURE
             * CONTEXT and the broadcast tap can use an AudioWorklet instead
             * of a ScriptProcessorNode that loses 17-23% of its buffers to a
             * busy main thread. See net/LoopDoor.kt - the whole reasoning,
             * and the measurement, live there.
             *
             * If the door will not open, the station's own address is used
             * exactly as before: a worse audio tap is worth having, a blind
             * terminal is not. */
            val door = try {
                LoopDoor.open(base)
            } catch (err: Exception) {
                Log.w(TAG, "loopback door refused: " + err.message)
                null
            }
            val load = door ?: base
            if (door != null) {
                LoopDoor.aim(base)
                Log.i(TAG, "panel via $door -> $base")
            } else {
                Log.w(TAG, "panel direct from $base - no secure context, so "
                    + "the broadcast tap stays on the ScriptProcessor")
            }
            /* THE DOOR'S HOST, NOT THE STATION'S. shouldOverrideUrlLoading
             * keeps stationHost in the panel and sends everything else to the
             * browser, so this has to follow the address actually loaded or
             * every link in the panel becomes a link OUT. */
            stationHost = Uri.parse(load).host.orEmpty()
            webView.loadUrl("$load/")
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

        override fun onRenderProcessGone(
            view: WebView,
            detail: RenderProcessGoneDetail,
        ): Boolean {
            Log.e(TAG, "panel renderer gone; crashed=${detail.didCrash()}")
            mainFrameFailed = true
            showStatus("The panel stopped. Rebuilding it...", retry = false)
            /* Recreating the activity also reconstructs every document-start
             * bridge and native surface. Reusing a WebView whose renderer is
             * gone is unsupported and tends to leave a half-alive kiosk. */
            (view.parent as? android.view.ViewGroup)?.removeView(view)
            view.destroy()
            window.decorView.post {
                if (!isFinishing && !isDestroyed) recreate()
            }
            return true
        }

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
            if (url.startsWith("about:blank")) {
                Log.w(TAG, "panel fell back to $url; reopening the station")
                showStatus("Reconnecting to the station...", retry = false)
                if (!retryScheduled) {
                    retryScheduled = true
                    view.postDelayed({
                        retryScheduled = false
                        if (!isFinishing && !isDestroyed &&
                            webView.url.orEmpty().startsWith("about:blank")) load()
                    }, RETRY_MS)
                }
                return
            }
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

            /* THE HOT CORNERS, TOLD RATHER THAN ASKED. hot-corners.js is in
             * the bundle above; the moment it is, the page gets the
             * operator's corner preferences pushed in, so it never has to
             * ask the bridge and never boots on a stale default. Read from
             * the store on a coroutine, which also refreshes the copy that
             * dispatchTouchEvent reads. See config/HotCorners.kt. */
            lifecycleScope.launch {
                try {
                    HotCorners.read(app.configStore)
                    webView.evaluateJavascript(HotCorners.script(HotCorners.live), null)
                } catch (err: Exception) {
                    Log.w(TAG, "hot corners not pushed: ${err.message}")
                }
            }
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

    private inner class PanelChrome : WebChromeClient() {
        private val brandedVideoPoster: Bitmap by lazy {
            val poster = Bitmap.createBitmap(512, 288, Bitmap.Config.ARGB_8888)
            val canvas = android.graphics.Canvas(poster)
            canvas.drawColor(android.graphics.Color.rgb(6, 12, 14))
            assets.open("pinebox-256.png").use { input ->
                android.graphics.BitmapFactory.decodeStream(input)?.let { logo ->
                    val bounds = android.graphics.Rect(200, 88, 312, 200)
                    canvas.drawBitmap(logo, null, bounds, android.graphics.Paint(android.graphics.Paint.FILTER_BITMAP_FLAG))
                    logo.recycle()
                }
            }
            poster
        }

        override fun getDefaultVideoPoster(): Bitmap = brandedVideoPoster

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

        /**
         * #1182T: THE ACTIVITY THAT EXISTS, if one does.
         *
         * NOT the same thing as PineDesktopBridge.liveActivity, and the
         * difference is the point. That one is set in onResume and cleared in
         * onDestroy because its callers need a live WINDOW - the USB disk
         * picker cannot show itself without one. Standby needs the opposite:
         * it acts precisely while the kiosk is NOT in front, so it needs a
         * handle that survives being backgrounded. Set in onCreate, cleared in
         * onDestroy, and read only for things that are legal on a paused
         * activity - resting a poll, dropping a cache.
         */
        @Volatile
        var live: MainActivity? = null
            private set

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
         * #1182T: CARRY AN AUDIO-FOCUS DUCK INTO THE PAGE.
         *
         * PineDuck IS THE ONE ROAD, and this deliberately uses nothing else.
         * It is the standing rule for every duck on this terminal - reports,
         * dictation, the SFX set - and it exists because a duck has to
         * compose: the lowest hold wins, the last one out restores, and a
         * level the operator moved by hand while a hold stood is not stamped
         * on when the hold lifts. Setting el.volume here by hand would do all
         * three of those things wrong, and the third is the one that would
         * quietly overwrite the monitor slider every time a notification
         * chimed.
         *
         * A HOLD WITH NO ELEMENT GETS A NINETY-SECOND CEILING from PineDuck,
         * so a focus loss that outlasts it lifts the duck on its own. That is
         * the right direction to fail in and is why it is not fought: the
         * failure is the station coming back UP, never the station staying
         * down. Everything in this pair of files fails towards being heard.
         *
         * If the page has not loaded PineDuck yet, nothing happens and the
         * station plays at full volume. Also the right direction.
         */
        private fun focusDuck(gain: Float): String = """
            (function () {
              try {
                var lvl = $gain;
                if (!window.PineDuck || typeof window.PineDuck.hold !== "function") {
                  return "no PineDuck; left at full";
                }
                if (lvl >= 0.999) { window.PineDuck.release("androidFocus"); return "released"; }
                window.PineDuck.hold("androidFocus", lvl);
                return "held at " + lvl;
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
