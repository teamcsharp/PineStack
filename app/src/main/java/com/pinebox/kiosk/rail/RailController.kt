package com.pinebox.kiosk.rail

import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.content.Intent
import android.provider.Settings
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.ProgressBar
import android.widget.SeekBar
import android.widget.Spinner
import android.widget.TextView
import androidx.appcompat.widget.SwitchCompat
import androidx.drawerlayout.widget.DrawerLayout
import com.pinebox.kiosk.BuildConfig
import com.pinebox.kiosk.R
import com.pinebox.kiosk.config.ConfigStore
import com.pinebox.kiosk.config.HotCorners
import com.pinebox.kiosk.config.HotCornerPrefs
import com.pinebox.kiosk.replay.ScreenReplay
import com.pinebox.kiosk.net.StationClient
import com.pinebox.kiosk.power.PowerWatch
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume
import org.json.JSONObject

/**
 * The native rail: the half of the Pine Box desktop's sidebar that means
 * something on a tablet, wired to the station.
 *
 * Everything it writes goes through routes confirmed in app.py:
 *   POST /api/dj/output    93359  the broadcast preset, the three stream
 *                                 routes and their levels
 *   POST /api/dj/start     93908  FM on
 *   POST /api/dj/stop      93925  FM off
 *   GET/POST /api/radio/pause  92925  off air, which is not off
 *   GET  /api/dj/pipeline  108717  the full log, on demand only
 *
 * Everything it READS comes off the one existing /api/dj poll. There is no
 * poller in this class and there must not be one: StationFeed's four seconds
 * are the station's own contract (app.py:155440) and this station has a
 * documented history of being starved by chatty clients.
 */
class RailController(
    private val drawer: DrawerLayout,
    private val rail: View,
    private val client: StationClient,
    /** The terminal's own config - the hot corners live in it. */
    private val configStore: ConfigStore,
    private val scope: CoroutineScope,
    /** Load a URL in the terminal's one WebView. */
    private val navigate: (String) -> Unit,
    /** Run JavaScript in the page already loaded, with the result. */
    private val runScript: (String, (String) -> Unit) -> Unit,
    private val pageLocation: () -> String,
    private val restorePage: () -> Unit,
    private val repairAudioRoute: () -> String,
    private val openBluetooth: () -> Unit,
    private val exitToSystem: () -> Unit,
    /** [smart-reinit] the terminal's own half of the doctor; null = none. */
    private val doctor: DoctorHooks? = null,
) {

    private val conn: TextView = rail.findViewById(R.id.railConn)
    private val now: TextView = rail.findViewById(R.id.railNow)
    private val fmSwitch: Button = rail.findViewById(R.id.fmSwitch)
    private val airPause: Button = rail.findViewById(R.id.airPause)
    private val airNote: TextView = rail.findViewById(R.id.airNote)
    private val endlessVideo: Button = rail.findViewById(R.id.endlessVideo)
    private val endlessNote: TextView = rail.findViewById(R.id.endlessNote)
    private val routeNote: TextView = rail.findViewById(R.id.routeNote)
    private val jumpList: ViewGroup = rail.findViewById(R.id.jumpList)
    private val logsFull: Button = rail.findViewById(R.id.logsFull)
    private val playerList: ViewGroup = rail.findViewById(R.id.playerList)
    private val playerNote: TextView = rail.findViewById(R.id.playerNote)

    /* ---- the hot corners - see config/HotCorners.kt ---- */
    private val cornersOn: SwitchCompat = rail.findViewById(R.id.cornersOn)
    private val cornersNote: TextView = rail.findViewById(R.id.cornersNote)
    private val cornerZone: SeekBar = rail.findViewById(R.id.cornerZone)
    private val cornerZoneLabel: TextView = rail.findViewById(R.id.cornerZoneLabel)
    private val cornerSensitivity: SeekBar = rail.findViewById(R.id.cornerSensitivity)
    private val cornerSensitivityLabel: TextView = rail.findViewById(R.id.cornerSensitivityLabel)
    private val cornerSpinners: Map<String, Spinner> = mapOf(
        "tl" to rail.findViewById(R.id.corner_tl),
        "tr" to rail.findViewById(R.id.corner_tr),
        "bl" to rail.findViewById(R.id.corner_bl),
        "br" to rail.findViewById(R.id.corner_br),
    )
    /** True while paintCorners() moves the controls, so their listeners
     *  know a change came from the store and not from a finger. */
    private var cornersSyncing = false

    /* ---- #1212/#1213: the reinitialise card ---- */
    private val fixGo: Button = rail.findViewById(R.id.fixGo)
    private val fixNote: TextView = rail.findViewById(R.id.fixNote)
    /* [tablet-update-ask] the download icon: ask the desk for the newest app */
    private val fixUpdate: View = rail.findViewById(R.id.fixUpdate)
    private val updateStatus: View = rail.findViewById(R.id.updateStatus)
    private val updateCaption: TextView = rail.findViewById(R.id.updateCaption)
    private val updateConsole: TextView = rail.findViewById(R.id.updateConsole)
    private val updateConsoleLast: TextView = rail.findViewById(R.id.updateConsoleLast)
    private val updateBuildProgress: android.widget.ProgressBar = rail.findViewById(R.id.updateBuildProgress)
    private val updateInstallProgress: android.widget.ProgressBar = rail.findViewById(R.id.updateInstallProgress)
    private val updateInstall: Button = rail.findViewById(R.id.updateInstall)
    private val updateSheen = UpdateSheenDrawable()
    private var updateRequired = false
    private var updateVersionReadAt = 0L
    private var updateReadyAt = 0.0
    private var updateRequesting = false
    private var updateWatch: kotlinx.coroutines.Job? = null
    private var fixRunning = false
    /* [smart-reinit] the question after every cure */
    private val fixAsk: View = rail.findViewById(R.id.fixAsk)
    private val fixAskClose: View = rail.findViewById(R.id.fixAskClose)
    private val fixOffer: Button = rail.findViewById(R.id.fixOffer)
    private val fixAnswers: Map<String, View> = mapOf(
        "yes" to rail.findViewById(R.id.fixYes),
        "no_music" to rail.findViewById(R.id.fixNoMusic),
        "no_djs" to rail.findViewById(R.id.fixNoDjs),
        "nothing" to rail.findViewById(R.id.fixNothing),
        "other" to rail.findViewById(R.id.fixOther),
    )

    /* Native system routes stay available when the WebView itself is not. */
    private val bluetooth: Button = rail.findViewById(R.id.deviceBluetooth)
    private val leaveApp: Button = rail.findViewById(R.id.deviceExit)

    /* ---- the battery card ---- */
    private val powerCard: View = rail.findViewById(R.id.powerCard)
    private val powerPercent: TextView = rail.findViewById(R.id.powerPercent)
    private val powerLeft: TextView = rail.findViewById(R.id.powerLeft)
    private val powerBar: ProgressBar = rail.findViewById(R.id.powerBar)
    private val powerNote: TextView = rail.findViewById(R.id.powerNote)
    private val powerDetail: TextView = rail.findViewById(R.id.powerDetail)
    private val powerSaver: Button = rail.findViewById(R.id.powerSaver)
    private val hushMusic: Button = rail.findViewById(R.id.hushMusic)
    private val watch = PowerWatch(rail.context)
    private var powerOpen = false
    private var powerTicker: Runnable? = null

    /* Volume: which knob is under a finger, and when we last wrote. */
    private var dragging = ""
    private var lastVolumeSend = 0L
    /* 120 ms: fast enough that a slide sounds continuous, slow enough that
     * a full sweep of the bar is about eight writes and not eighty. */
    private val THROTTLE_MS = 120L

    /** What the music level was before it was killed, so it can come back. */
    private var musicWas = -1

    /* A literal, because a newline inside a Kotlin string written by a
     * generator is one edit away from being an actual line break. */
    private val NEWLINE = System.lineSeparator()
    private val outputNote: TextView = rail.findViewById(R.id.outputNote)
    private val logs: TextView = rail.findViewById(R.id.railLogs)

    private val presetChips: Map<String, Button> = mapOf(
        "nabu" to rail.findViewById(R.id.broadcast_nabu),
        "box" to rail.findViewById(R.id.broadcast_box),
        "pinetab" to rail.findViewById(R.id.broadcast_web),
        "app" to rail.findViewById(R.id.broadcast_app),
    )

    /** stream -> (route value -> chip). The ids are generated in lockstep with
     *  drawer_rail.xml; see the generator's note there. */
    private val streamChips: Map<String, Map<String, Button>> = mapOf(
        "music" to mapOf(
            "here" to rail.findViewById(R.id.route_music_here),
            "box" to rail.findViewById(R.id.route_music_box),
            "both" to rail.findViewById(R.id.route_music_both),
            "off" to rail.findViewById(R.id.route_music_off),
        ),
        "voice" to mapOf(
            "here" to rail.findViewById(R.id.route_voice_here),
            "box" to rail.findViewById(R.id.route_voice_box),
            "both" to rail.findViewById(R.id.route_voice_both),
            "off" to rail.findViewById(R.id.route_voice_off),
        ),
        "reply" to mapOf(
            "here" to rail.findViewById(R.id.route_reply_here),
            "box" to rail.findViewById(R.id.route_reply_box),
            "both" to rail.findViewById(R.id.route_reply_both),
            "off" to rail.findViewById(R.id.route_reply_off),
        ),
    )

    private val streamState: Map<String, TextView> = mapOf(
        "music" to rail.findViewById(R.id.route_music_state),
        "voice" to rail.findViewById(R.id.route_voice_state),
        "reply" to rail.findViewById(R.id.route_reply_state),
    )

    private val volumes: Map<String, SeekBar> = mapOf(
        "music" to rail.findViewById(R.id.vol_music),
        "voice" to rail.findViewById(R.id.vol_voice),
        "sfx" to rail.findViewById(R.id.vol_reply),
        "video" to rail.findViewById(R.id.vol_video),
        "master" to rail.findViewById(R.id.vol_master),   // [levels-one]
        "pads" to rail.findViewById(R.id.vol_pads),
    )

    private val volumeLabels: Map<String, TextView> = mapOf(
        "music" to rail.findViewById(R.id.vol_music_value),
        "voice" to rail.findViewById(R.id.vol_voice_value),
        "sfx" to rail.findViewById(R.id.vol_reply_value),
        "video" to rail.findViewById(R.id.vol_video_value),
        "master" to rail.findViewById(R.id.vol_master_value),   // [levels-one]
        "pads" to rail.findViewById(R.id.vol_pads_value),
    )

    /** The last snapshot, painted or not. */
    private var state = RailState()

    /** The mode is read when the drawer opens and after every write. It is
     *  deliberately not guessed from local playback: every terminal shares
     *  this one station setting. */
    private var endlessOn = false
    private var endlessKnown = false
    private var endlessBanking = false

    /** Who is on the broadcast, from the last time the drawer was opened. */
    private var roster = AirOwners.Roster()

    /* [airplayers:fields] the receivers switch, when the station has it
     * (GET/POST /api/air/receivers); null on a station that predates it,
     * and the old roster rows are drawn instead. */
    private var receivers: AirReceivers.State? = null

    /** Receiver ids with a write in flight: no read may repaint them. */
    private val receiversPending = mutableSetOf<String>()

    /** A refusal or a failure, said on the row it belongs to. */
    private var receiversFault: Pair<String, String>? = null

    /** The BROADCAST chip tapped and not yet confirmed by the station. */
    private var destinationPending = ""

    /** The durable destination, which distinguishes PineTab from PineApp. */
    private var destination = ""

    /** True once the air has been put where the table asks, on this run. */
    private var airSettled = false

    /** True while a SeekBar is being moved BY US, so the change listener can
     *  tell a paint from a thumb and not post the station its own number
     *  back. */
    private var syncing = false

    /** Set when a paint arrived with the drawer shut. DrawerLayout keeps a
     *  closed drawer measured and laid out, so painting it is not free - and
     *  nobody can see it. Deferred to the next open instead. */
    private var dirty = false

    /** Where the operator last dragged each slider, for the streams the
     *  station does not report a level for. See RailState.musicLevel. */
    private val localLevel = mutableMapOf(
        "music" to 100, "voice" to 100, "sfx" to 100, "video" to 100,
        "master" to 100, "pads" to 100,   // [levels-one]
    )

    fun bind() {
        for ((key, chip) in presetChips) {
            chip.setOnClickListener { selectDestination(key) }
        }
        for ((stream, chips) in streamChips) {
            for ((value, chip) in chips) {
                chip.setOnClickListener {
                    send(stream + " → " + label(value)) { DjOutput.stream(stream, value) }
                }
            }
        }
        for ((stream, bar) in volumes) {
            bar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(bar: SeekBar, value: Int, fromUser: Boolean) {
                    volumeLabels[stream]?.text = "$value%"
                    if (!fromUser || syncing) return
                    /* THE SOUND FOLLOWS THE FINGER.
                     *
                     * This used to send NOTHING until the finger was lifted -
                     * the label moved and the broadcast did not. The
                     * reasoning written here was sound as far as it went
                     * ("posting per pixel would be a write per pixel to a
                     * device on the LAN") and the conclusion was wrong: the
                     * operator sets levels for specific moments on air and
                     * needs to hear what he is doing while he does it.
                     *
                     * So it sends WHILE dragging, throttled - at most one
                     * write every THROTTLE_MS - and always sends the final
                     * position on release, so where the finger stops is
                     * where the level ends up even if the last move fell
                     * inside the throttle window. */
                    localLevel[stream] = value
                    val now = android.os.SystemClock.uptimeMillis()
                    if (now - lastVolumeSend >= THROTTLE_MS) {
                        lastVolumeSend = now
                        applyListenerLevel(stream, value)
                    }
                }

                override fun onStartTrackingTouch(bar: SeekBar) {
                    /* A drag beats the poll: without this, a reconcile
                     * landing mid-drag would yank the knob back under the
                     * finger. */
                    dragging = stream
                }

                override fun onStopTrackingTouch(bar: SeekBar) {
                    dragging = ""
                    if (syncing) return
                    localLevel[stream] = bar.progress
                    lastVolumeSend = android.os.SystemClock.uptimeMillis()
                    applyListenerLevel(stream, bar.progress)
                    noteOk(label(stream) + " level → " + bar.progress + "%")
                }
            })
        }

        wireHush()

        fmSwitch.setOnClickListener {
            val want = !state.fm
            /* Optimistic, then reconciled by the very next poll. The station
             * answers /api/dj/start with its own object but the FM state is
             * not in a fixed field of it, so the honest thing is to show the
             * intent and let the four-second poll be the truth. */
            state = state.copy(fm = want)
            paintAir()
            call(if (want) "FM on" else "FM off") {
                client.post(if (want) "/api/dj/start" else "/api/dj/stop", "{}")
                null
            }
        }

        fixGo.setOnClickListener { reinitialise() }
        rail.findViewById<View>(R.id.railPineLens).setOnClickListener {
            drawer.closeDrawer(rail)
            runScript("(function(){if(!window.PineViewRail||!PineViewRail.open)return 'absent';PineViewRail.open('pinelens');return 'ok';})()") { result ->
                if (!result.contains("ok")) {
                    noteError("Pine Lens is unavailable in this page. Open the panel or update PineTab.")
                }
            }
        }
        fixUpdate.setOnClickListener { askDeskUpdate() }
        fixUpdate.addOnAttachStateChangeListener(object : View.OnAttachStateChangeListener {
            override fun onViewAttachedToWindow(view: View) { paintUpdateSheen() }
            override fun onViewDetachedFromWindow(view: View) { updateSheen.stop() }
        })
        updateResume()
        for ((answer, chip) in fixAnswers) chip.setOnClickListener { doctorAnswer(answer) }
        fixAskClose.setOnClickListener { doctorAnswer("stopped") }
        fixOffer.setOnClickListener { doctorOffer() }
        doctorResume()
        bluetooth.setOnClickListener { openBluetooth() }
        leaveApp.setOnClickListener { exitToSystem() }

        airPause.setOnClickListener {
            val want = !state.paused
            call(if (want) "going off air" else "back on air") {
                JSONObject(client.post("/api/radio/pause", JSONObject().put("paused", want).toString()))
                    .also { pageCatchUp() }                     // [radio-tap] sound on the tap
            }
        }

        endlessVideo.setOnClickListener { toggleEndlessVideo() }
        paintEndlessVideo()

        /* A TOGGLE, not a refresh button. Lit, the pane holds the pipeline log
         * the operator asked for and the feed is not allowed to paint over it
         * on the next change; unlit, it goes back to the free activity rows
         * that ride the /api/dj object we already have. Tapping it again while
         * lit re-reads - which is the refresh, and costs exactly one request
         * per tap and none at all in between. */
        logsFull.setOnClickListener {
            if (logsFull.isActivated) {
                logsFull.isActivated = false
                logs.text = state.log
                return@setOnClickListener
            }
            logsFull.isActivated = true
            logs.text = "reading the pipeline…"
            scope.launch {
                logs.text = try {
                    RailState.pipelineLog(client.get("/api/dj/pipeline"))
                        .ifBlank { "the pipeline log is empty" }
                } catch (err: Exception) {
                    "could not read the pipeline: " + (err.message ?: err.javaClass.simpleName)
                }
            }
        }

        buildJumps()

        wirePower()

        wireCorners()

        drawer.addDrawerListener(object : DrawerLayout.SimpleDrawerListener() {
            override fun onDrawerOpened(drawerView: View) {
                if (dirty) paint()
                updateResume()
                paintUpdateSheen()
                /* The page can change the corners too (hotCornersSet), and
                 * HotCorners.live already holds the result; the rows only
                 * need to catch up when they come into view. */
                paintCorners()
                /* banked_seconds is on /api/radio/pause and nowhere else - one
                 * request, on the open, never on a clock. */
                call(null) { JSONObject(client.get("/api/radio/pause")) }
                readEndlessVideo()
                readPlayers()
                readListenerLevels()
                startPower()
            }

            /* THE BATTERY CLOCK RUNS ONLY WHILE THE DRAWER IS OPEN.
             * Reading the fuel gauge costs a binder call and a couple of
             * /proc reads; doing that every few seconds behind a closed
             * drawer would be spending the very battery it reports on. */
            override fun onDrawerClosed(drawerView: View) {
                stopPower()
                updateSheen.stop()
                fixUpdate.foreground = null
            }
        })
    }

    /** Called from the activity's feed collector, already off the tick. */
    fun render(next: RailState) {
        state = next
        if (next.connected && drawer.isDrawerOpen(rail) && updateWatch?.isActive != true &&
            android.os.SystemClock.uptimeMillis() - updateVersionReadAt > 60000L) updateResume()
        /* ONCE, when the station first answers: put the air where the table
         * says it belongs, without waiting for anyone to open the drawer.
         * The tablet is meant to be switched on and be the room - "whenever
         * I start it up, I will start up the Pine Box tab and log in to the
         * station and have it outputting through the Pine Box tablet" - and
         * that cannot depend on a gesture. It is one pair of GETs, not a
         * poller: the rail has none and must not grow one. */
        if (next.connected && !airSettled) {
            airSettled = true
            readPlayers()
        }
        if (!drawer.isDrawerOpen(rail)) {
            dirty = true
            return
        }
        paint()
    }

    /* ------------------------------------------------------------------ */

    /**
     * Name the socket the sound is leaving by.
     *
     * Called from the activity's OutputRoute watcher, which fires on every
     * route change - so plugging an aux cable in updates this line without
     * the drawer being touched.
     */
    fun setOutput(where: String) {
        outputNote.text = "out of " + where
    }

    /* ---- who is playing the show ---------------------------------------
     *
     * "I want to be able to see every application that's currently having the
     * audio broadcasted to it... and I wanna be able to check and uncheck that
     * from this Pine Box tab in order to set what device is picking it up."
     *
     * Two reads and, on a tap, one write. Read ON THE OPEN, never on a clock:
     * the rail has no poller and must not grow one, and a list of listeners is
     * of no interest at all while the drawer is shut. Settings comes along for
     * the ride so a row can say "PineTab" instead of "pbnvgdtefn".
     */
    private fun readPlayers() {
        /* [airplayers:read] the receivers switch first; the old roster
         * only for a station that does not have it yet. */
        scope.launch {
            val got = try {
                AirReceivers.read(JSONObject(client.get(AirReceivers.ROUTE)))
            } catch (err: Exception) {
                null
            }
            if (got != null) adoptReceivers(got, fromWrite = false) else readRoster()
        }
    }

    private fun readRoster() {
        scope.launch {
            try {
                val listeners = JSONObject(client.get("/api/radio/listeners"))
                val settings = try {
                    JSONObject(client.get("/api/settings"))
                } catch (err: Exception) {
                    null      /* names are a nicety; the list still works */
                }
                destination = settings?.optString("broadcast_to").orEmpty()
                roster = AirOwners.read(listeners, settings)
                paintPlayers()
                reconcileAir(settings)
            } catch (err: Exception) {
                Log.w(TAG, "could not read the listeners", err)
                playerNote.text = "could not ask the station who is listening: " +
                    (err.message ?: err.javaClass.simpleName)
            }
        }
    }

    /**
     * Put the air where the TABLE says it should be.
     *
     * THE LISTENER ID IS NOT AN IDENTITY. It is minted fresh on every page
     * load - measured across three relaunches of this app: pbnvgdtefn, then
     * pbq8gj5qvq, then another. So "the tablet has the air" is true only
     * until the tablet reloads; then the owner it named stops polling, the
     * station releases it after AUDIO_OWNER_LIFE, and every page starts
     * sounding again. That is the whole of "I'm hearing a different
     * broadcast coming out of the application than out of the Pine Box tab."
     *
     * The device row IS an identity, because it is keyed on an address. So
     * the durable statement lives in settings - pinetab.play - and this
     * re-points the station's ephemeral owner at whichever listener id that
     * device happens to be using now.
     *
     * Safe to run from every client at once: AirOwners.shouldOwn is a pure
     * function of the same two documents, so the desktop and the tablet
     * compute the same answer and write the same value. And it says nothing
     * at all when two devices are deliberately set to play, which is the
     * case where soloing one would silence the other.
     */
    private fun reconcileAir(settings: JSONObject?) {
        /* [airplayers:reconcile] the station resolves the air itself now
         * that several receivers may be on; a tablet re-pointing the
         * exclusive at the table's one device would undo the operator. */
        if (receivers != null) return
        val want = AirOwners.shouldOwn(roster, settings)
        if (want.isBlank() || want == roster.owner) return
        scope.launch {
            try {
                val body = JSONObject().put("listener", want).toString()
                val answer = JSONObject(client.post("/api/radio/solo", body))
                roster = AirOwners.read(answer, settings)
                paintPlayers()
                Log.i(TAG, "the air follows the table: " + want)
            } catch (err: Exception) {
                Log.w(TAG, "could not hand the air over", err)
            }
        }
    }

    /* ------------------------------------------------------------ power */

    private fun wirePower() {
        powerCard.setOnClickListener {
            powerOpen = !powerOpen
            powerDetail.visibility = if (powerOpen) View.VISIBLE else View.GONE
            powerSaver.visibility = if (powerOpen) View.VISIBLE else View.GONE
            paintPower()
        }
        powerSaver.setOnClickListener {
            /* The platform's own battery screen. The kiosk cannot toggle
             * power saver for the operator - that is a system setting and
             * an app has no business flipping it - but it can take him
             * straight there rather than leaving him hunting. */
            try {
                val go = Intent(Settings.ACTION_BATTERY_SAVER_SETTINGS)
                go.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                rail.context.startActivity(go)
            } catch (err: Exception) {
                powerNote.text = "this build has no battery settings screen to open"
            }
        }
        /* PRIME THE SAMPLER, THEN PAINT AGAIN.
         *
         * CPU is a difference between two readings of /proc/stat, so the
         * very first one has nothing to compare against and honestly
         * reports -1. Painting once more a moment later means the first
         * figure the operator ever sees is a real one, covering the time
         * since the rail was built. */
        paintPower()
        rail.postDelayed({ paintPower() }, 1500L)
    }

    private fun startPower() {
        stopPower()
        val tick = object : Runnable {
            override fun run() {
                paintPower()
                /* Six seconds: fast enough that plugging the charger in is
                 * seen almost at once, slow enough to be free. */
                rail.postDelayed(this, 6000L)
            }
        }
        powerTicker = tick
        rail.post(tick)
    }

    private fun stopPower() {
        powerTicker?.let { rail.removeCallbacks(it) }
        powerTicker = null
    }

    /**
     * HOW LONG THE RADIO HAS LEFT, in the operator's terms.
     *
     * The headline is deliberately not "battery 47%". The question this
     * card exists to answer is how long the broadcast can keep going, so
     * that is what the big line says; the percentage is the number beside
     * it. Everything here is measured - see PowerWatch for what the device
     * will and will not tell an app, and for why there is no list of other
     * apps' processes (since Android 8 there is no way to obtain one).
     */
    private fun paintPower() {
        /* WHAT THIS TERMINAL IS RUNNING, which is the part of "what is
         * choking the tablet" that CAN be answered. The page is asked
         * directly - it is the only thing that knows which view is mounted
         * and which WebGL scenes are live - and the answer is used on the
         * NEXT paint rather than awaited, because a battery card must never
         * block on the panel. */
        runScript(TERMINAL_LOAD) { answer ->
            watch.load = answer
                .trim().trim('"')
                .split(',')
                .map { it.trim() }
                .filter { it.isNotEmpty() && it != "null" }
        }

        val r = watch.read()
        if (r == null) {
            powerPercent.text = "—"
            powerLeft.text = "this device is not reporting its battery"
            powerNote.text = ""
            return
        }

        powerPercent.text = if (r.percent < 0) "—" else "${r.percent}%"
        powerBar.progress = r.percent.coerceIn(0, 100)

        powerLeft.text = when {
            r.full -> "full, on ${r.plugged}"
            r.charging && r.minutesLeft > 0 ->
                "charging - full in ${PowerWatch.spell(r.minutesLeft)}"
            r.charging -> "charging on ${r.plugged}"
            r.minutesLeft > 0 -> "${PowerWatch.spell(r.minutesLeft)} of radio left"
            else -> "time left cannot be measured on this device"
        }

        val bits = mutableListOf<String>()
        if (r.milliAmps > 0) {
            bits += (if (r.charging) "taking " else "drawing ") + "${r.milliAmps} mA"
        }
        if (r.celsius > 0) bits += "${r.celsius.toInt()}°C"
        if (r.saverOn) bits += "power saver ON"
        if (r.dozing) bits += "dozing"
        if (r.thermal != "normal") bits += r.thermal
        powerNote.text = bits.joinToString("  ·  ")

        /* ONE LINE IN THE LOG, every time this is painted. A kiosk that has
         * been running for a week and then died is a bug report with no
         * witness; this is the witness, and it costs a string. */
        Log.i(TAG, "power ${r.percent}% " +
            (if (r.charging) "charging" else "on battery") +
            " · ${r.milliAmps} mA · ${r.celsius}°C · " +
            "left=${PowerWatch.spell(r.minutesLeft)} (${r.basis}) · " +
            "ram=${r.ramFreeMb}/${r.ramTotalMb}MB · " +
            "choke: ${r.choke}")

        if (!powerOpen) return

        /* ---- the detail, which is the part he asked to be able to open ---- */
        val lines = mutableListOf<String>()
        lines += "WHAT IS LEFT"
        lines += "  ${PowerWatch.spell(r.minutesLeft)}  —  ${r.basis}"
        if (r.chargeFullUah > 0) {
            lines += "  gauge: ${r.chargeNowUah / 1000} mAh of about " +
                "${r.chargeFullUah / 1000} mAh"
        }
        lines += "  battery is ${r.health}, ${fmtVolts(r.volts)} V, ${r.celsius}°C"

        lines += ""
        lines += "WHAT THE TABLET IS DOING"
        lines += "  memory ${r.ramFreeMb} MB free of ${r.ramTotalMb} MB" +
            (if (r.ramLow) " — LOW" else "")
        lines += "  this app is holding ${r.appMb} MB across ${r.cores} cores"
        lines += "  thermal state: ${r.thermal}"
        lines += "  drawing ${r.milliAmps} mA at ${r.celsius}°C"
        val running = watch.load
        lines += if (running.isEmpty()) "  this terminal is running: just the panel"
        else "  this terminal is running: " + running.joinToString(", ")

        lines += ""
        lines += "WHAT IS CHOKING IT"
        lines += "  ${r.choke}"

        lines += ""
        /* SAY WHAT CANNOT BE SEEN, rather than leaving a gap that looks
         * like nothing is running. Both of these are real platform limits,
         * measured on this device, and the operator should know they are
         * the reason rather than an oversight. */
        lines += "Android has not let an app list other apps' processes"
        lines += "since version 8. /proc/stat and /proc/loadavg are also"
        lines += "refused to apps here - tested, both Permission denied -"
        lines += "so there is no system CPU figure to show. On a kiosk this"
        lines += "app is nearly the whole workload anyway, so what it is"
        lines += "running is listed above."

        powerDetail.text = lines.joinToString(NEWLINE)
    }

    private fun fmtVolts(v: Double) = String.format("%.2f", v)

    private fun paintPlayers() {
        if (receivers != null) {           // [airplayers:paint]
            paintReceivers()
            return
        }
        val inflater = android.view.LayoutInflater.from(rail.context)
        playerList.removeAllViews()
        for (player in roster.players) {
            val row = inflater.inflate(R.layout.rail_player, playerList, false)
            row.findViewById<TextView>(R.id.playerTick).text = if (player.owns) "◉" else "○"
            row.findViewById<TextView>(R.id.playerName).text = player.label
            row.findViewById<TextView>(R.id.playerDetail).text = player.detail
            row.isSelected = player.owns
            row.setOnClickListener { tapPlayer(player) }
            playerList.addView(row)
        }
        playerNote.text = AirOwners.note(roster)
    }

    /**
     * Hand this player the air, or - if it already has it - let every page
     * play again.
     *
     * The answer to /api/radio/solo carries the new roster, so the list is
     * repainted from the station's word rather than from what was asked for.
     */
    private fun tapPlayer(player: AirOwners.Player) {
        val was = roster
        /* Paint the tick at once. The post is a round trip over Wi-Fi and a
         * check that waits for it reads as a control that did nothing. */
        roster = was.copy(
            owner = if (player.owns) "" else player.listener,
            players = was.players.map { it.copy(owns = !player.owns && it.listener == player.listener) }
        )
        paintPlayers()
        scope.launch {
            try {
                val answer = JSONObject(client.post("/api/radio/solo", AirOwners.tap(player)))
                roster = AirOwners.read(answer, settingsOf(was))
                paintPlayers()
                noteOk(
                    if (roster.soloed) "only " + (roster.of(roster.owner)?.label ?: "one page") + " is sounding"
                    else "every page may sound again"
                )
            } catch (err: Exception) {
                roster = was                      /* put the tick back */
                paintPlayers()
                noteError(err.message ?: err.javaClass.simpleName)
            }
        }
    }

    /* ---- [airplayers:rows] Playing it: the receivers switch ----------------
     *
     * "i want the buttons to redirect audio to be responsive. i want to be
     * able to enable and disable streams from there as well by enabling them
     * from receiving a broadcast."
     *
     * The old rows felt dead for four measured reasons: the row holding the
     * air was never drawn differently (chip.xml has no selected state); a
     * REFUSED hand-over (/api/radio/solo answers 200 with `refused`) was
     * painted as a success and the tick bounced back; what a tap did was
     * written in the BROADCAST card, not here; and the list was read only
     * when the drawer opened. Now: the row is pressed on touch, switched
     * and marked "switching..." in the same frame as the tap, repainted from
     * the station's answer, and a refusal or failure is said ON THE ROW. */

    private fun adoptReceivers(next: AirReceivers.State, fromWrite: Boolean) {
        val was = receivers
        receivers = if (fromWrite || was == null || receiversPending.isEmpty()) next
        else next.copy(receivers = next.receivers.map { r ->
            if (r.id in receiversPending) was.of(r.id) ?: r else r
        })
        paintReceivers()
    }

    private fun paintReceivers() {
        val st = receivers ?: return
        val inflater = android.view.LayoutInflater.from(rail.context)
        /* ROWS ARE UPDATED IN PLACE when the list is the same receivers in
         * the same order - which is every paint but the first. Rebuilding
         * detached the row under a finger that was already down (the drawer
         * open fires a read, and the old code a solo answer, ~100-300 ms
         * apart), so the release landed on a new view and the tap was lost.
         * Measured the same way in the web harness: one tap in a few. */
        val same = playerList.childCount == st.receivers.size &&
            st.receivers.indices.all { playerList.getChildAt(it).tag == st.receivers[it].id }
        if (!same) playerList.removeAllViews()
        val fault = receiversFault
        for ((index, r) in st.receivers.withIndex()) {
            val row = if (same) playerList.getChildAt(index)
            else inflater.inflate(R.layout.rail_player, playerList, false)
            row.tag = r.id
            val pending = r.id in receiversPending
            row.findViewById<View>(R.id.playerTick).visibility = View.GONE
            val sw = row.findViewById<SwitchCompat>(R.id.playerSwitch)
            sw.visibility = View.VISIBLE
            sw.isChecked = r.audible
            row.findViewById<TextView>(R.id.playerName).text = r.label
            row.findViewById<View>(R.id.playerBadge).visibility =
                if (r.active) View.VISIBLE else View.GONE
            val err = if (fault != null && fault.first == r.id) fault.second else ""
            val detail = row.findViewById<TextView>(R.id.playerDetail)
            detail.text = listOf(AirReceivers.detail(r, pending), err)
                .filter { it.isNotBlank() }.joinToString(NEWLINE)
            detail.setTextColor(rail.resources.getColor(when {
                err.isNotBlank() -> R.color.pine_bad
                pending -> R.color.pine_amber
                else -> R.color.pine_dim
            }, null))
            row.isSelected = r.active
            row.alpha = if (r.kind == "page" && !r.present) 0.62f else 1f
            /* [radio-tap] The row makes this receiver THE RADIO - on, holding
             * the air, sounding now - and never switches it off: the
             * operator's "make the PineTab the radio" tap on a tablet that
             * was already on used to be the audible toggle, and silenced it.
             * Off is the switch's own job. */
            row.contentDescription = "Make " + r.label + " the radio"
            row.setOnClickListener { makeRadio(r) }
            sw.isClickable = true
            sw.contentDescription = r.label + if (r.audible)
                " is audible - switch it off" else " is off - let it sound"
            sw.setOnClickListener { flipReceiver(r) }
            val only = row.findViewById<Button>(R.id.playerOnly)
            only.visibility = View.VISIBLE
            only.contentDescription = "Make " + r.label + " the only one sounding in the house"
            only.tooltipText = only.contentDescription
            only.setOnClickListener { onlyReceiver(r) }
            if (!same) playerList.addView(row)
        }
        playerNote.text = fault?.second ?: AirReceivers.note(st)
        playerNote.setTextColor(rail.resources.getColor(
            if (fault != null || st.refused.isNotBlank()) R.color.pine_bad else R.color.pine_dim,
            null,
        ))
    }

    private fun flipReceiver(r: AirReceivers.Receiver) {
        if (r.id in receiversPending) return
        val want = !r.audible
        writeReceivers(setOf(r.id), AirReceivers.flip(r.id, want),
            "switching " + r.label + if (want) " on" else " off") {
            AirReceivers.optimistic(it, r.id, want)
        }
    }

    /** [radio-tap] On and the radio. Already both: just make the page catch
     *  up now rather than on its next poll. */
    private fun makeRadio(r: AirReceivers.Receiver) {
        if (r.id in receiversPending) return
        if (r.audible && r.active) {
            pageCatchUp()
            playerNote.text = r.label + " is the radio"
            return
        }
        writeReceivers(setOf(r.id), AirReceivers.radio(r.id),
            "making " + r.label + " the radio") { AirReceivers.optimisticRadio(it, r.id) }
    }

    /**
     * [radio-tap] THE PAGE HEARS IT NOW. A receiver switch or a return to air
     * reaches this page's audio on its own clock poll (1.5 s) and its DJ feed
     * poll (4 s); asking both the moment the station has said yes is the
     * difference between sound on the tap and sound a few seconds later.
     * Posted to the main thread: the WebView takes script from nowhere else.
     */
    private fun pageCatchUp() {
        rail.post {
            runScript("(function(){try{radioClockPoll()}catch(e){}"
                + "try{pollDJ()}catch(e){}return 'ok'})()") { }
        }
    }

    private fun onlyReceiver(r: AirReceivers.Receiver) {
        val st = receivers ?: return
        if (receiversPending.isNotEmpty()) return
        writeReceivers(AirReceivers.touched(st, r.id, true), AirReceivers.only(r.id),
            "only " + r.label) { AirReceivers.optimisticOnly(it, r.id) }
    }

    /** One write: painted before the network, repainted from the answer. */
    private fun writeReceivers(
        ids: Set<String>, body: String, saying: String,
        guess: (AirReceivers.State) -> AirReceivers.State,
    ) {
        val was = receivers ?: return
        receiversFault = null
        receiversPending.addAll(ids)
        receivers = guess(was)
        paintReceivers()
        playerNote.text = saying + "…"
        val t0 = android.os.SystemClock.uptimeMillis()
        scope.launch {
            try {
                val answer = AirReceivers.read(JSONObject(client.post(AirReceivers.ROUTE, body)))
                    ?: throw IllegalStateException("the station gave no answer")
                receiversPending.removeAll(ids)
                if (answer.refused.isNotBlank()) {
                    receiversFault = ids.first() to AirReceivers.note(answer)
                }
                adoptReceivers(answer, fromWrite = true)
                pageCatchUp()                                   // [radio-tap]
                Log.i(TAG, "playing it: " + saying + " confirmed in "
                    + (android.os.SystemClock.uptimeMillis() - t0) + " ms: "
                    + AirReceivers.summary(answer))
            } catch (err: Exception) {
                receiversPending.removeAll(ids)
                receivers = was
                receiversFault = ids.first() to ("not changed - could not reach the station: "
                    + (err.message ?: err.javaClass.simpleName))
                paintReceivers()
                Log.w(TAG, "playing it: $saying failed", err)
            }
        }
    }

    /** The names from the roster we already have, so a repaint after a solo
     *  does not cost a second settings fetch. */
    private fun settingsOf(previous: AirOwners.Roster): JSONObject? {
        if (previous.players.none { it.device.isNotBlank() }) return null
        val table = JSONObject()
        for (player in previous.players) {
            if (player.device.isBlank()) continue
            table.put(player.device, JSONObject()
                .put("name", player.label)
                .put("addr", player.addr))
        }
        return JSONObject().put("terminals", table)
    }

    private fun buildJumps() {
        val inflater = android.view.LayoutInflater.from(rail.context)
        for (jump in QuickJumps.ALL) {
            val button = inflater.inflate(R.layout.rail_jump, jumpList, false) as Button
            button.text = jump.label
            button.setOnClickListener { go(jump) }
            jumpList.addView(button)
        }
    }

    /**
     * Take a jump.
     *
     * A Scene is tried INSIDE the page first and only falls back to a
     * navigation if the panel answered that it has no pineShow3JS - which is
     * the difference between a scene appearing in about a frame and the whole
     * panel being fetched and parsed again. The drawer closes either way: the
     * thing the operator asked for is behind it.
     */
    private fun go(jump: QuickJumps.Jump) {
        drawer.closeDrawer(rail)
        when (jump) {
            is QuickJumps.Jump.Page -> scope.launch {
                navigate(QuickJumps.pageUrl(client.config().base, jump.path))
            }

            is QuickJumps.Jump.Scene -> runScript(QuickJumps.script(jump.key)) { result ->
                /* evaluateJavascript hands back a JSON value, so the string
                 * comes quoted. Anything other than "ok" means the page could
                 * not do it in place. */
                if (result.contains("ok")) return@runScript
                Log.i(TAG, "in-page jump to ${jump.key} said $result; loading the pop-out")
                scope.launch {
                    navigate(QuickJumps.viewUrl(client.config().base, jump.key))
                }
            }
        }
    }

    /**
     * #1212/#1213, rebuilt as [smart-reinit]: GET THE BROADCAST BACK.
     *
     * "Whenever I bring up the broadcast and I can't hear the music or the
     *  DJs, I just click this button. So I need this button to intelligently
     *  be able to tell what's needing to be done so it does that and doesn't
     *  reinitialize things that don't need to be reinitialized ... and then
     *  query me and ask me if the broadcast is working suitably and then from
     *  there into troubleshooting before advancing to more advanced and
     *  intense of steps." (the operator, 2026-09-30)
     *
     * It used to run every rung whatever the symptom - including restarting
     * this app, which restarts the audio. Now one press:
     *
     *   1. LOOKS before touching anything: the station names what it can see
     *      (GET /api/broadcast/diagnose), the page reports its own players
     *      twice, a second and a half apart, and the tablet reads its own
     *      audio routing (AudioHealth). BroadcastDoctor turns that into
     *      findings in plain words.
     *   2. CURES only what was named, each with its own smallest cure. The
     *      operator's levels, volume and routing are reported, never changed.
     *   3. ASKS "Is the broadcast working now?" - Yes / No music / No DJs /
     *      No sound at all / Other - and the answer steers the next look.
     *   4. Only then, with nothing named left to cure, climbs the existing
     *      ladder (BroadcastDoctor.RUNGS), one rung per answer, gentlest first.
     *
     * Every step and every answer goes to the station's run log
     * (POST /api/broadcast/reinit/log -> data/air_fixes.jsonl), so a fault
     * that keeps coming back says so ("seen in 3 earlier runs this week").
     */
    private fun reinitialise() {
        if (fixRunning) return
        doctorRun = DoctorRun("r" + java.lang.Long.toString(System.currentTimeMillis(), 36))
        doctorStep(BroadcastDoctor.Hint.NONE, answered = false)
    }

    private class DoctorRun(
        val id: String,
        var step: Int = 0,
        val tried: MutableSet<String> = mutableSetOf(),
        var nextRung: Int = 0,
        var hint: String = "",
        var captureReopened: Boolean = false,
        var device: String = "",
        var listener: String = "",
        var offer: String = "",
        val lines: MutableList<String> = mutableListOf(),
    )

    private var doctorRun: DoctorRun? = null

    /* ---- [tablet-update-ask] THE TABLET'S OWN UPDATE ----
     * "On the tablet put an icon here that allows me to connect with the desktop
     * client and download, build, and install the latest version of the Pine tab"
     * (the operator, 2026-10-01). The tablet cannot build itself: it asks the
     * station (POST /api/tablet/update-ask), the desk's tablet button takes the ask,
     * runs deploy.sh, and reports each step back to the same route. The install
     * restarts this app, so the record lives on the station and updateResume()
     * picks the progress up again when the app comes back.
     *
     * Not a standing poller (see the class comment): it reads every UPDATE_POLL_MS
     * only while an update is in flight, and stops when it is done or gone. */
    private fun askDeskUpdate() {
        if (updateRequesting) return
        if (updateReadyAt > 0.0) {
            val askAt = updateReadyAt
            updateRequesting = true
            updateInstall.isEnabled = false
            scope.launch {
                try {
                    val body = JSONObject().put("state", "install-requested").put("ask_at", askAt)
                        .put("line", "install requested by the tablet")
                    val v = JSONObject(client.post(UPDATE_ROUTE, body.toString()))
                    paintUpdate(v)
                    watchUpdate(askAt)
                } catch (err: Exception) {
                    updateCaption.text = "could not request install: " + (err.message ?: "connection failed")
                } finally {
                    updateRequesting = false
                    updateInstall.isEnabled = true
                }
            }
            return
        }
        if (updateWatch?.isActive == true) {
            fixNote.text = "an update is already under way - its progress shows here"
            return
        }
        fixNote.text = "asking the desk to build the newest PineTab app…"
        updateRequesting = true
        scope.launch {
            try {
                val v = JSONObject(client.post(UPDATE_ROUTE, JSONObject().put("by", "the PineTab").toString()))
                fixNote.text = updateLine(v, 0L)
                watchUpdate(v.optDouble("ask_at", 0.0))
            } catch (err: Exception) {
                Log.w(TAG, "update ask failed", err)
                fixNote.text = "could not ask the desk: " + (err.message ?: err.javaClass.simpleName)
            } finally {
                updateRequesting = false
            }
        }
    }

    private fun updateResume() {
        updateVersionReadAt = android.os.SystemClock.uptimeMillis()
        scope.launch {
            try {
                val v = JSONObject(client.get(UPDATE_ROUTE))
                paintUpdateAvailable(v)
                val st = v.optString("state")
                val age = v.optDouble("now", 0.0) - v.optDouble("at", 0.0)
                if (v.optBoolean("open", false)) {
                    fixNote.text = updateLine(v, 0L)
                    watchUpdate(v.optDouble("ask_at", 0.0))
                } else if ((st == "done" || st == "failed") && age in 0.0..600.0) {
                    fixNote.text = updateLine(v, 0L)
                }
            } catch (err: Exception) {
                Log.w(TAG, "update resume failed", err)
            }
        }
    }

    private fun watchUpdate(askAt: Double) {
        if (askAt <= 0.0) return
        updateWatch?.cancel()
        updateWatch = scope.launch {
            val began = System.currentTimeMillis()
            var last = ""
            while (System.currentTimeMillis() - began < UPDATE_WATCH_MS) {
                delay(UPDATE_POLL_MS)
                val v = try {
                    JSONObject(client.get(UPDATE_ROUTE))
                } catch (err: Exception) {
                    continue
                }
                if (Math.abs(v.optDouble("ask_at", 0.0) - askAt) > 0.001) return@launch
                val said = updateLine(v, System.currentTimeMillis() - began)
                if (said != last) {
                    fixNote.text = said
                    last = said
                }
                val st = v.optString("state")
                if (st == "done" || st == "failed" || !v.optBoolean("open", false)) return@launch
            }
        }
    }

    private fun paintUpdateSheen() {
        val show = updateRequired && drawer.isDrawerOpen(rail)
        fixUpdate.foreground = if (show) updateSheen else null
        if (show) updateSheen.start() else updateSheen.stop()
    }

    private fun paintUpdateAvailable(v: JSONObject) {
        val wanted = v.optString("wanted")
        val fresh = v.optDouble("now") - v.optDouble("wanted_at") in 0.0..180.0
        val installed = BuildConfig.VERSION_NAME.substringAfter('+', "")
        val st = v.optString("state")
        val busy = st in listOf("asked", "taken", "running", "install-requested", "installing") && v.optBoolean("open")
        updateRequired = !busy && ((fresh && wanted.length == 12 && wanted != installed) || (st == "ready" && v.optBoolean("open")))
        fixUpdate.contentDescription = when {
            st == "ready" && v.optBoolean("open") -> "Update ready - tap to install compiled update"
            updateRequired -> "Update available - tap to build the latest PineTab app"
            else -> "Build latest PineTab update"
        }
        paintUpdateSheen()
    }

    private fun paintUpdate(v: JSONObject) {
        paintUpdateAvailable(v)
        val st = v.optString("state")
        val ready = st == "ready"
        val installing = st == "install-requested" || st == "installing"
        val finished = st == "done"
        updateStatus.visibility = View.VISIBLE
        updateReadyAt = if (ready) v.optDouble("ask_at", 0.0) else 0.0
        updateInstall.visibility = if (ready) View.VISIBLE else View.GONE
        updateInstall.setOnClickListener { askDeskUpdate() }
        updateCaption.text = when (st) {
            "asked" -> "Build: queued / Install: waiting"
            "ready" -> "Build: complete / Tap again to install"
            "install-requested", "installing" -> "Build: complete / Install: working"
            "done" -> "Build: complete / Install: complete"
            "failed" -> "Update failed - tap to retry"
            else -> "Build: working / Install: waiting"
        }
        updateBuildProgress.isIndeterminate = st == "asked" || st == "taken" || st == "running"
        updateBuildProgress.progress = if (ready || installing || finished) 100 else 0
        updateInstallProgress.isIndeterminate = installing
        updateInstallProgress.progress = if (finished) 100 else 0
        val lines = v.optJSONArray("lines")
        val consoleLines = if (lines != null && lines.length() > 0) {
            (maxOf(0, lines.length() - 2) until lines.length()).map {
                lines.optJSONObject(it)?.optString("line") ?: ""
            }
        } else listOf(v.optString("line"))
        updateConsole.text = consoleLines.firstOrNull() ?: ""
        updateConsoleLast.text = if (consoleLines.size > 1) consoleLines.last() else ""
    }

    private fun updateLine(v: JSONObject, waitedMs: Long): String {
        paintUpdate(v)
        val st = v.optString("state")
        if (st == "asked" && waitedMs > UPDATE_UNTAKEN_MS) {
            return "the desk has not taken it yet - is the Pine Box app open on the computer?"
        }
        val head = when (st) {
            "asked" -> "asked the desk"
            "taken", "running" -> "the desk is building the update"
            "ready" -> "compiled - tap the update button again to install"
            "install-requested", "installing" -> "installing the compiled update"
            "done" -> "updated"
            "failed" -> "the update did not finish"
            else -> st
        }
        val line = v.optString("line")
        return if (line.isNotEmpty()) "$head - $line" else head
    }

    private fun fixSay(line: String) {
        val lines = doctorRun?.lines ?: mutableListOf()
        lines.add(line)
        while (lines.size > FIX_LINES) lines.removeAt(0)
        fixNote.text = lines.joinToString(NEWLINE)
    }

    private fun doctorStep(hint: BroadcastDoctor.Hint, answered: Boolean) {
        val r = doctorRun ?: return
        if (fixRunning) return
        fixRunning = true
        fixGo.isEnabled = false
        hideAsk()
        scope.launch {
            var ask = true
            try {
                r.step += 1
                r.hint = hint.key
                fixSay(if (answered) "- looking again: you said " + hint.label.lowercase() + " -"
                       else "looking before touching anything…")
                val found = doctorExamine(hint, r)
                for (line in BroadcastDoctor.describe(found)) fixSay("found  $line")
                val plan = BroadcastDoctor.plan(found, r.tried, hint, answered, r.nextRung)
                val did = mutableListOf<String>()
                val cures = mutableListOf<String>()
                for ((_, cure) in plan.cures) {
                    r.tried.add(cure)
                    cures.add(cure)
                    val said = doctorCure(cure, r)
                    did.add(said)
                    fixSay("did    $said")
                }
                val rung = plan.rung
                if (plan.cures.isEmpty() && rung != null) {
                    r.nextRung = plan.rungIndex + 1
                    cures.add("rung:" + rung.key)
                    fixSay("nothing named is left to cure, so the next step (" + (plan.rungIndex + 1)
                        + " of " + BroadcastDoctor.RUNGS.size + "): " + rung.say)
                    did.add(doctorRung(rung, r))
                } else if (plan.cures.isEmpty() && answered && plan.offers.isEmpty()) {
                    fixSay("every step the software has is spent and it is still not right.")
                    fixSay("what is left needs hands: close this app fully and open it again;")
                    fixSay("check the box is powered and on the network; power-cycle the speaker.")
                    doctorLog(r, found, "", "the ladder is spent", "")
                    ask = false
                    doctorFinish()
                    return@launch
                }
                if (did.isEmpty()) {
                    fixSay(if (plan.offers.isNotEmpty()) "that needs your say-so - see the button below"
                           else if (found.any { it.fault }) "nothing I can fix from here for that"
                           else "nothing needed doing, so nothing was touched")
                }
                r.offer = plan.offers.firstOrNull()?.cure.orEmpty()
                doctorLog(r, found, cures.joinToString(","), did.joinToString("; "), "")
                if (did.isNotEmpty()) {
                    fixSay("listening for a few seconds…")
                    delay(6000)
                }
            } catch (err: Exception) {
                Log.w(TAG, "get the broadcast back failed", err)
                fixSay("that step failed: " + (err.message ?: err.javaClass.simpleName))
            } finally {
                fixRunning = false
                fixGo.isEnabled = true
                if (ask && doctorRun === r) showAsk(r)
            }
        }
    }

    /** Everything the three sources say, turned into findings. */
    private suspend fun doctorExamine(
        hint: BroadcastDoctor.Hint, r: DoctorRun,
    ): List<BroadcastDoctor.Finding> {
        val address = pageLocation()
        if (!address.startsWith("http://") && !address.startsWith("https://")) {
            return listOf(BroadcastDoctor.Finding("page_gone", "fault",
                "The station page is not open (" + address.ifBlank { "nothing loaded" } + ").",
                "reopen_page", "tablet"))
        }
        val t0 = android.os.SystemClock.uptimeMillis()
        val a = pageProbe()
        val listener = a?.optString("listener").orEmpty().ifBlank { r.listener }
        r.listener = listener
        val station = stationDiagnosis(listener, hint)
        r.device = station?.optJSONObject("snapshot")?.optString("device").orEmpty()
            .ifBlank { r.device.ifBlank { "pinetab" } }
        val hooks = doctor
        val reading = if (hooks == null) null else withContext(Dispatchers.IO) {
            runCatching { hooks.audio() }.getOrNull()
        }
        if (reading != null) fixSay("tablet " + reading.say)
        val waited = android.os.SystemClock.uptimeMillis() - t0
        if (waited < 1500) delay(1500 - waited)
        val b = pageProbe()
        var net = b?.optString("net").orEmpty()
        var polls = 0
        while (net == "asking" && polls < 4) {
            delay(1500)
            net = pageProbe()?.optString("net") ?: net
            polls += 1
        }
        val device = BroadcastDoctor.Device(
            verdict = reading?.verdict?.name.orEmpty(),
            verdictSay = reading?.say.orEmpty(),
            route = hooks?.route().orEmpty(),
            musicIndex = reading?.musicIndex ?: -1,
            musicMuted = reading?.musicMuted ?: false,
            focusHeld = hooks?.focusHeld() ?: true,
            standby = hooks?.standby() ?: false,
            captureReopened = r.captureReopened,
        )
        return BroadcastDoctor.diagnose(station, BroadcastDoctor.Page(a, b, net), device, hint)
    }

    /** The station's own diagnosis; its health on a station that predates it. */
    private suspend fun stationDiagnosis(listener: String, hint: BroadcastDoctor.Hint): JSONObject? {
        val route = "/api/broadcast/diagnose?listener=" + java.net.URLEncoder.encode(listener, "UTF-8") +
            "&hint=" + hint.key
        try {
            return JSONObject(client.get(route))
        } catch (err: Exception) {
            fixSay("the station's diagnosis did not answer (" + (err.message ?: "?").take(80) +
                ") - reading its health instead")
        }
        return try {
            val health = JSONObject(client.get("/api/broadcast/health"))
            val paused = health.optBoolean("paused", false)
            val rows = org.json.JSONArray()
            if (paused) rows.put(JSONObject().put("key", "paused").put("kind", "fault")
                .put("say", "The station is paused: " + health.optString("say")).put("cure", "onair"))
            JSONObject().put("findings", rows)
                .put("snapshot", JSONObject().put("on", true).put("paused", paused).put("playing", false))
        } catch (err: Exception) {
            JSONObject().put("findings", org.json.JSONArray().put(JSONObject()
                .put("key", "station_unreachable").put("kind", "fault")
                .put("say", "The station does not answer this tablet (" +
                    (err.message ?: err.javaClass.simpleName).take(80) + ").")
                .put("cure", "")))
        }
    }

    /** Ask the page something and wait for the answer, or give up. */
    private suspend fun pageAsk(script: String, ms: Long = 4000L): String? = withTimeoutOrNull(ms) {
        suspendCancellableCoroutine<String?> { cont ->
            rail.post {
                try {
                    runScript(script) { got -> if (cont.isActive) cont.resume(got) }
                } catch (err: Exception) {
                    if (cont.isActive) cont.resume(null)
                }
            }
        }
    }

    private suspend fun pageProbe(): JSONObject? {
        val got = pageAsk(BroadcastDoctor.PAGE_PROBE) ?: return null
        return runCatching { JSONObject(got) }.getOrNull()
    }

    private fun firstLine(answer: String): String = try {
        val lines = JSONObject(answer).optJSONArray("lines")
        val line = (1 until (lines?.length() ?: 0)).map { lines!!.optString(it).trim() }
            .firstOrNull { it.isNotEmpty() }
        if (line.isNullOrBlank()) "" else " - " + line.take(140)
    } catch (err: Exception) { "" }

    private suspend fun fixStep(step: String): String = try {
        firstLine(client.post("/api/broadcast/fix/$step", "{}"))
    } catch (err: Exception) {
        " - the station did not confirm (" + (err.message ?: err.javaClass.simpleName).take(80) +
            "); it keeps working on it"
    }

    /** One named cure, and the words for what it did. */
    private suspend fun doctorCure(cure: String, r: DoctorRun): String {
        val words = BroadcastDoctor.CURES[cure] ?: cure
        val hooks = doctor
        return try {
            when (cure) {
                "onair", "relieve", "stock", "bank", "flush" -> words + fixStep(cure)
                "solo" -> {
                    val out = JSONObject(client.post("/api/radio/solo",
                        JSONObject().put("listener", r.listener).toString()))
                    pageCatchUp()
                    if (out.optString("refused").isNotBlank())
                        "the station would not give this tablet the air: " + out.optString("why")
                    else words
                }
                "reopen_capture" -> {
                    r.captureReopened = true
                    if (hooks == null) "this build cannot reach the capture"
                    else words + ": " + withContext(Dispatchers.IO) { hooks.reopenCapture() }
                }
                "release_capture" ->
                    if (hooks == null) "this build cannot reach the capture"
                    else words + ": " + withContext(Dispatchers.IO) { hooks.releaseCapture() }
                "refocus" ->
                    if (hooks?.refocus() == true) words else "asked Android for media focus and it refused"
                "leave_standby" -> { hooks?.leaveStandby(); words }
                "resume_ctx" -> words + ": " + (pageAsk(RESUME_CTX) ?: "no answer").trim('"')
                "catch_up" -> { pageCatchUp(); words }
                "ungag" -> words + ": " + (pageAsk(UNGAG) ?: "no answer").trim('"')
                "lift_duck" -> words + ": " + (pageAsk(LIFT_DUCK) ?: "no answer").trim('"')
                "resume_music" -> words + ": " + (pageAsk(RESUME_MUSIC) ?: "no answer").trim('"')
                "reload_page" -> {
                    rail.post { runScript("location.reload()") { } }
                    delay(9000)
                    words
                }
                "reopen_page" -> { restorePage(); delay(4000); words }
                "make_radio" -> {
                    val answer = AirReceivers.read(JSONObject(client.post(AirReceivers.ROUTE,
                        AirReceivers.radio(r.device.ifBlank { "pinetab" }))))
                    if (answer != null) adoptReceivers(answer, fromWrite = true)
                    pageCatchUp()
                    if (answer != null && answer.refused.isNotBlank()) AirReceivers.note(answer) else words
                }
                "restart_app" -> doctorRestartApp(r)
                else -> "no cure is called $cure"
            }
        } catch (err: Exception) {
            words + " - it failed: " + (err.message ?: err.javaClass.simpleName).take(100)
        }
    }

    /** A rung of the old ladder, run whole, and one line for what it did. */
    private suspend fun doctorRung(rung: BroadcastDoctor.Rung, r: DoctorRun): String {
        val said = mutableListOf<String>()
        for (cure in rung.local) {
            r.tried.add(cure)
            val line = doctorCure(cure, r)
            fixSay("did    $line")
            said.add(line)
        }
        for (step in rung.station) {
            val line = step + fixStep(step)
            fixSay("did    $line")
            said.add(line)
            if (step == "reload_pages") delay(9000)
            if (step == "restart") {
                fixSay("the station is restarting - asking you again in half a minute")
                delay(30000)
            }
        }
        return rung.key + ": " + said.joinToString("; ").take(300)
    }

    /** Restart this app. Saved first: this process ends, and the question
     *  is asked again by the next one (doctorResume). */
    private suspend fun doctorRestartApp(r: DoctorRun): String {
        val hooks = doctor ?: return "this build cannot restart itself"
        r.tried.add("restart_app")
        fixSay("restarting this app - the sound restarts with it; I will ask again when it is back")
        doctorLog(r, emptyList(), "restart_app", "restarting this app", "")
        doctorSave()
        delay(800)
        if (hooks.restartApp("the Get the broadcast back button")) {
            delay(15000)
            return "asked Android to restart this app, and it is still here"
        }
        doctorForget()
        fixSay("the app restarted itself too recently to do it again - reloading this page instead")
        rail.post { runScript("location.reload()") { } }
        delay(9000)
        return "the restart was declined (too soon since the last one); reloaded this page instead"
    }

    private fun hideAsk() {
        fixAsk.visibility = View.GONE
        fixOffer.visibility = View.GONE
    }

    private fun showAsk(r: DoctorRun) {
        fixAsk.visibility = View.VISIBLE
        val offer = r.offer
        if (offer.isNotBlank() && offer !in r.tried) {
            val words = BroadcastDoctor.CURES[offer] ?: offer
            fixOffer.text = when (offer) {
                "make_radio" -> "Make this tablet the radio (turns its out-loud switch on)"
                "restart_app" -> "Restart this app - the sound restarts with it"
                else -> words.replaceFirstChar { it.uppercase() }
            }
            fixOffer.contentDescription = fixOffer.text
            fixOffer.tooltipText = fixOffer.text
            fixOffer.visibility = View.VISIBLE
        } else {
            fixOffer.visibility = View.GONE
        }
    }

    /** The operator's answer: record it, then stop or look again. */
    private fun doctorAnswer(answer: String) {
        val r = doctorRun ?: run { hideAsk(); return }
        if (fixRunning) return
        hideAsk()
        scope.launch { doctorLog(r, emptyList(), "", "", answer) }
        when (answer) {
            "yes" -> {
                fixSay("good - stopping here.")
                doctorFinish()
            }
            "stopped" -> {
                fixSay("stopped - nothing more will be touched.")
                doctorFinish()
            }
            else -> doctorStep(BroadcastDoctor.Hint.of(answer), answered = true)
        }
    }

    /** The one cure that waits for the operator's own tap. */
    private fun doctorOffer() {
        val r = doctorRun ?: return
        val cure = r.offer
        if (cure.isBlank() || fixRunning) return
        fixRunning = true
        fixGo.isEnabled = false
        hideAsk()
        scope.launch {
            try {
                r.tried.add(cure)
                val said = doctorCure(cure, r)
                fixSay("did    $said")
                doctorLog(r, emptyList(), cure, said, "")
                delay(4000)
            } finally {
                fixRunning = false
                fixGo.isEnabled = true
                r.offer = ""
                if (doctorRun === r) showAsk(r)
            }
        }
    }

    private fun doctorFinish() {
        hideAsk()
        doctorForget()
        doctorRun = null
    }

    /** One row of the station's run log. Never fails the run. */
    private suspend fun doctorLog(
        r: DoctorRun, found: List<BroadcastDoctor.Finding>, cure: String, did: String, answer: String,
    ) {
        try {
            client.post("/api/broadcast/reinit/log", JSONObject()
                .put("run", r.id).put("step", r.step).put("device", r.device)
                .put("listener", r.listener).put("hint", r.hint)
                .put("findings", BroadcastDoctor.keys(found, faults = true))
                .put("notes", BroadcastDoctor.keys(found, faults = false))
                .put("cure", cure).put("did", did.take(400)).put("answer", answer)
                .toString())
        } catch (err: Exception) {
            Log.i(TAG, "the run log did not take this step: " + err.message)
        }
    }

    private fun doctorPrefs() = rail.context.applicationContext
        .getSharedPreferences(DOCTOR_PREFS, android.content.Context.MODE_PRIVATE)

    /** Written before this app restarts itself, so the next process asks. */
    private fun doctorSave() {
        val r = doctorRun ?: return
        val json = JSONObject().put("id", r.id).put("step", r.step).put("next", r.nextRung)
            .put("hint", r.hint).put("capture", r.captureReopened).put("device", r.device)
            .put("listener", r.listener).put("tried", org.json.JSONArray(r.tried.toList()))
            .put("lines", org.json.JSONArray(r.lines)).put("at", System.currentTimeMillis())
        doctorPrefs().edit().putString("run", json.toString()).commit()
    }

    private fun doctorForget() {
        doctorPrefs().edit().remove("run").apply()
    }

    /** After this app restarted itself mid-run: carry on asking. */
    private fun doctorResume() {
        val raw = doctorPrefs().getString("run", null) ?: return
        doctorPrefs().edit().remove("run").apply()
        val saved = runCatching { JSONObject(raw) }.getOrNull() ?: return
        if (System.currentTimeMillis() - saved.optLong("at", 0L) > DOCTOR_RESUME_MS) return
        val r = DoctorRun(saved.optString("id"), step = saved.optInt("step"),
            nextRung = saved.optInt("next"), hint = saved.optString("hint"),
            captureReopened = saved.optBoolean("capture"), device = saved.optString("device"),
            listener = saved.optString("listener"))
        saved.optJSONArray("tried")?.let { for (i in 0 until it.length()) r.tried.add(it.optString(i)) }
        saved.optJSONArray("lines")?.let { for (i in 0 until it.length()) r.lines.add(it.optString(i)) }
        doctorRun = r
        fixSay("this app has restarted.")
        showAsk(r)
        rail.postDelayed({ drawer.openDrawer(rail) }, 2500)
    }

    /** A write that returns a dj_state object; its routing is adopted at once. */
    private fun send(note: String?, body: () -> String) {
        call(note) { JSONObject(client.post("/api/dj/output", body())) }
    }

    /* ------------------------------------------------------ endless video */

    /** Read only while the drawer is visible; the native video wall and the
     *  web controls use this same server-owned mode. */
    private fun readEndlessVideo() {
        scope.launch {
            try {
                adoptEndless(JSONObject(client.get("/api/sfx/video/mode")))
            } catch (err: Exception) {
                endlessKnown = false
                paintEndlessVideo(err.message ?: "station did not answer")
            }
        }
    }

    private fun toggleEndlessVideo() {
        if (!endlessKnown) {
            readEndlessVideo()
            return
        }
        val want = !endlessOn
        endlessVideo.isEnabled = false
        endlessNote.text = if (want) "turning endless video on..." else "turning endless video off..."
        scope.launch {
            try {
                val body = JSONObject().put("on", want).toString()
                adoptEndless(JSONObject(client.post("/api/sfx/video/mode", body)))
            } catch (err: Exception) {
                paintEndlessVideo(err.message ?: "station did not answer")
            }
        }
    }

    private fun adoptEndless(answer: JSONObject) {
        endlessOn = answer.optBoolean("on", false)
        endlessBanking = answer.optBoolean("banking", false)
        endlessKnown = true
        paintEndlessVideo()
        /* [radio-tap] Turning the set off RESUMES a pause the set made, but
         * the air button used to learn that only on the next four-second
         * poll - so the operator's next tap ("back on air") could land on a
         * button that had flipped to "Off air" and take the station straight
         * back off. The answer carries the station's word; paint it now. */
        if (answer.has("off_air")) {
            val paused = answer.optBoolean("off_air", state.paused)
            if (paused != state.paused) {
                state = state.copy(paused = paused)
                paintAir()
            }
            if (!paused) pageCatchUp()
        }
    }

    private fun paintEndlessVideo(error: String? = null) {
        endlessVideo.isActivated = endlessKnown && endlessOn
        endlessVideo.isEnabled = true
        endlessVideo.alpha = if (endlessKnown || error != null) 1f else 0.55f
        endlessVideo.contentDescription = when {
            !endlessKnown -> "Read endless video mode"
            endlessOn -> "Turn endless video off"
            else -> "Turn endless video on"
        }
        endlessVideo.tooltipText = endlessVideo.contentDescription
        endlessNote.text = when {
            error != null -> "endless video: could not read it - $error"
            !endlessKnown -> rail.resources.getString(R.string.rail_endless_checking)
            endlessOn && endlessBanking -> "endless video: on - banking clips while off air"
            endlessOn -> "endless video: on - one clip after another"
            else -> "endless video: off"
        }
        endlessNote.setTextColor(rail.resources.getColor(
            if (error == null) R.color.pine_dim else R.color.pine_bad, null,
        ))
    }

    /**
     * Select one complete destination with the same ordered transaction as
     * the desktop: owner first, routes second, durable settings last.
     */
    private fun selectDestination(key: String) {
        val preset = DjOutput.PRESETS[key] ?: return
        /* [airplayers:chip] ANSWER THE THUMB FIRST. This used to light
         * nothing and say nothing until six round trips had finished (two
         * reads, the solo, the routes, a 21 KB settings PUT and another
         * read) - and a feed paint in between repainted the old chip. The
         * chip lights now and the line says "sending"; the station's answer
         * (or its refusal, in words) replaces both. */
        destinationPending = key
        for ((k, chip) in presetChips) chip.isActivated = k == key
        paintNote()
        scope.launch {
            try {
                val settings = JSONObject(client.get("/api/settings"))
                val listeners = JSONObject(client.get("/api/radio/listeners"))
                val live = AirOwners.read(listeners, settings)
                val pageDevice = when (key) {
                    "pinetab" -> "pinetab"
                    "app" -> "desktop"
                    else -> ""
                }
                val solo = if (pageDevice.isNotBlank()) {
                    val player = live.players.firstOrNull {
                        it.device == pageDevice && it.seen <= 45.0
                    } ?: throw IllegalStateException(
                        preset.label + " is not looking at the station right now"
                    )
                    JSONObject().put("listener", player.listener)
                } else {
                    JSONObject().put("clear", true)
                }

                client.post("/api/radio/solo", solo.toString())
                val routed = JSONObject(client.post("/api/dj/output", DjOutput.preset(key)))

                settings.put("broadcast_to", key)
                val terminals = settings.optJSONObject("terminals") ?: JSONObject()
                val names = ArrayList<String>()
                val keys = terminals.keys()
                while (keys.hasNext()) names.add(keys.next())
                for (name in names) {
                    terminals.optJSONObject(name)?.put("play", name == pageDevice)
                }
                settings.put("terminals", terminals)
                client.put("/api/settings", settings.toString())

                destination = key
                destinationPending = ""          // [airplayers:chip-ok]
                state = state.patched(routed)
                roster = AirOwners.read(
                    JSONObject(client.get("/api/radio/listeners")), settings,
                )
                paint()
                noteOk("broadcast -> " + preset.label)
                readPlayers()                    // [airplayers:chip-done] Playing it follows
            } catch (err: Exception) {
                Log.w(TAG, "could not select broadcast destination", err)
                destinationPending = ""          // [airplayers:chip-fail]
                paint()
                noteError(err.message ?: err.javaClass.simpleName)
            }
        }
    }

    /** The native drawer and every web view move the same page-side mixer. */
    private fun applyListenerLevel(stream: String, percent: Int) {
        val value = percent.coerceAtLeast(0) / 100.0
        runScript(
            "(function(){try{" +
                "var b=window.pineLevels;if(!b||typeof b.apply!=='function')return 'absent';" +
                "b.apply(" + JSONObject.quote(stream) + "," + value + ");return 'ok';" +
            "}catch(e){return 'error:'+e.message;}})()",
        ) { answer ->
            if (answer.contains("error") || answer.contains("absent")) {
                noteError("the shared audio mixer did not answer")
            }
        }
    }

    /** Read the shared values when the drawer opens. There is no audio poll. */
    private fun readListenerLevels() {
        runScript(
            "(function(){try{" +
                "var b=window.pineLevels,m=b&&b.get?b.get():{};" +
                "return [m.music,m.voice,m.sfx,m.video,m.master,m.pads];" +
            "}catch(e){return [];}})()",
        ) { answer ->
            try {
                val values = org.json.JSONArray(answer)
                val names = listOf("music", "voice", "sfx", "video", "master", "pads")   // [levels-one]
                for (i in names.indices) {
                    val n = values.optDouble(i, Double.NaN)
                    if (!n.isNaN()) localLevel[names[i]] = Math.round(n * 100).toInt()
                }
                paintListenerLevels()
            } catch (err: Exception) {
                Log.w(TAG, "shared audio levels did not parse", err)
            }
        }
    }

    private fun paintListenerLevels() {
        for ((stream, bar) in volumes) {
            if (dragging == stream) continue
            val want = (localLevel[stream] ?: 100).coerceIn(0, bar.max)
            if (bar.progress != want) {
                syncing = true
                bar.progress = want
                syncing = false
            }
            volumeLabels[stream]?.text = "$want%"
        }
    }

    /**
     * MUSIC OFF, IN ONE TAP - AND BACK AGAIN.
     *
     * "There are times where I need to turn the music off very quickly."
     *
     * Dragging a slider to zero takes a second and a steady hand, and the
     * per-stream OFF chip is a ROUTE change, not a level - it stops the
     * music reaching this device rather than turning it down on the air.
     * This sets the station's music level to zero, remembers what it was,
     * and restores exactly that on the next tap. The DJs are untouched,
     * which is the point: it is for talking over.
     */
    private fun wireHush() {
        hushMusic.setOnClickListener {
            val bar = volumes["music"] ?: return@setOnClickListener
            if (musicWas >= 0) {
                val back = musicWas
                musicWas = -1
                bar.progress = back
                localLevel["music"] = back
                applyListenerLevel("music", back)
                noteOk("music back to $back%")
            } else {
                musicWas = bar.progress
                bar.progress = 0
                localLevel["music"] = 0
                applyListenerLevel("music", 0)
                noteOk("music off - the DJs keep going")
            }
            paintHush()
        }
        paintHush()
    }

    private fun paintHush() {
        hushMusic.text = if (musicWas >= 0)
            rail.context.getString(R.string.rail_music_back)
        else rail.context.getString(R.string.rail_music_off)
        hushMusic.isSelected = musicWas >= 0
    }

    /**
     * Run one station call, put its answer on the rail, and say so.
     *
     * The note is the only feedback an operator gets that a chip did anything,
     * and a failure has to stay on screen - the desktop learned this the hard
     * way (renderer.js noteRouteError forces the line back on in the compact
     * rail).
     */
    private fun call(note: String?, work: suspend () -> JSONObject?) {
        scope.launch {
            try {
                val answer = work()
                if (answer != null) {
                    state = state.patched(answer)
                    if (answer.has("banked_seconds")) bankedNote(answer)
                }
                /* noteOk AFTER paint: paint() calls paintNote(), which would
                 * otherwise consume the flash before it was ever set. */
                paint()
                if (note != null) noteOk(note)
            } catch (err: Exception) {
                Log.w(TAG, "rail call failed", err)
                noteError(err.message ?: err.javaClass.simpleName)
            }
        }
    }

    private fun bankedNote(answer: JSONObject) {
        val banked = Math.round(answer.optDouble("banked_seconds", 0.0) / 60.0)
        val off = Math.round(answer.optDouble("for_seconds", 0.0) / 60.0)
        airNote.text = if (answer.optBoolean("paused", false)) {
            "off air ${off}m · ${banked}m banked and still recording"
        } else {
            "on air · ${banked}m banked"
        }
    }

    /** A failure, held until the next call succeeds. */
    private var fault: String? = null

    /** What the last tap did, shown for exactly one paint. */
    private var flash: String? = null

    private fun noteOk(text: String) {
        fault = null
        flash = text
        paintNote()
    }

    private fun noteError(text: String) {
        fault = text
        paintNote()
    }

    /**
     * The one sentence on the rail.
     *
     * Precedence, and each step earns its place: a FAULT stays up until
     * something works, because a routing failure that scrolls away is a
     * terminal quietly playing to nowhere (the desktop forces this line back
     * on in its compact rail for the same reason). A FLASH says what the tap
     * just did, for one paint. Otherwise it describes the routing - which is
     * the state the operator actually needs at a glance, and what the line
     * used to fail to say: with the chips lit and the station answering it
     * still read "routing unknown" because nothing but a tap ever wrote it.
     */
    private fun paintNote() {
        if (destinationPending.isNotBlank()) {          // [airplayers:note]
            routeNote.text = "sending: broadcast -> " +
                (DjOutput.PRESETS[destinationPending]?.label ?: destinationPending) + "…"
            routeNote.setTextColor(rail.resources.getColor(R.color.pine_amber, null))
            return
        }
        val fault = this.fault
        if (fault != null) {
            routeNote.text = fault
            routeNote.setTextColor(rail.resources.getColor(R.color.pine_bad, null))
            return
        }
        val once = flash
        flash = null
        routeNote.text = once ?: describeRouting()
        routeNote.setTextColor(rail.resources.getColor(R.color.pine_dim, null))
    }

    private fun describeRouting(): String {
        if (!state.connected && state.musicTo.isBlank()) {
            return rail.resources.getString(R.string.rail_route_unknown)
        }
        if (destination in presetChips && destination in state.presets) {
            return "broadcast: " + (DjOutput.PRESETS[destination]?.label ?: destination)
        }
        val preset = state.presets
        if (preset.isNotEmpty()) {
            val key = preset.first()
            return "broadcast: " + (DjOutput.PRESETS[key]?.label ?: key)
        }
        // #980: three streams moved apart is a real state; name all three.
        return DjOutput.STREAMS.joinToString(" · ") { stream ->
            label(stream) + " " + label(state.routeOf(stream))
        }
    }

    /* ------------------------------------------------------------------ */
    /* Painting                                                            */
    /* ------------------------------------------------------------------ */

    private fun paint() {
        dirty = false
        val s = state
        conn.text = when {
            s.error != null && !s.connected -> "the station did not answer: " + s.error
            s.connected -> (s.stationName.ifBlank { "the station" }) + " · answering"
            else -> rail.resources.getString(R.string.rail_checking)
        }
        now.text = s.nowLine
        now.visibility = if (s.nowLine.isBlank()) View.GONE else View.VISIBLE

        paintAir()

        /* #980: three streams moved apart is a legitimate state, so an empty
         * set lights NOTHING rather than a preset that is no longer true.
         * describeRouting() names the three separately in that case. */
        val presets = s.presets
        for ((key, chip) in presetChips) {
            chip.isActivated = if (destinationPending.isNotBlank()) {
                key == destinationPending        // [airplayers:pending] the tap, until answered
            } else if (destination in presetChips) {
                key == destination && key in presets
            } else {
                key in presets
            }
        }
        paintNote()

        for (stream in DjOutput.STREAMS) {
            val value = s.routeOf(stream)
            streamChips[stream]?.forEach { (route, chip) -> chip.isActivated = route == value }
            streamState[stream]?.text = label(value)
            /* Amber when this stream is NOT coming out of the app, so a silent
             * terminal is legible at a glance instead of being a mystery -
             * the desktop's paintStreamRoutes "away" class, in one colour. */
            val away = value.isNotBlank() && value != "here" && value != "both"
            streamState[stream]?.setTextColor(
                rail.resources.getColor(
                    if (away) R.color.pine_amber else R.color.pine_dim, null,
                ),
            )

        }
        paintListenerLevels()

        if (s.log.isNotBlank() && !logsShowingPipeline) logs.text = s.log
    }

    private fun paintAir() {
        fmSwitch.isActivated = state.fm
        airPause.isActivated = state.paused
        airPause.setText(if (state.paused) R.string.rail_resume else R.string.rail_pause)
    }

    /** Once the operator has asked for the full log, the feed must not
     *  overwrite it on the next change. */
    private val logsShowingPipeline: Boolean
        get() = logsFull.isActivated

    /* ---- the hot corners ------------------------------------------ */

    /**
     * THE FOUR ROWS AND THE SWITCH.
     *
     * "I also want preferences in the swipe out on the pine box tablet
     *  where I can specify what these behaviors are for the gestures for
     *  each of the hot corners ... be able to also change these and set
     *  these and disable these if I want in the sidebar that swipes out on
     *  the left side for the pine box tablet."
     *
     * Every change goes through HotCorners.set - the same function the
     * bridge's hotCornersSet calls - so the store, the touch road's copy
     * and the page are told in one place. The spinners' words come from
     * HotCorners.CHOICES rather than a string-array, so the drawer can
     * never offer a corner something the page does not understand.
     */
    private fun wireCorners() {
        val words = HotCorners.CHOICES.map { it.second }
        for ((corner, spinner) in cornerSpinners) {
            spinner.adapter = ArrayAdapter(rail.context, R.layout.rail_spinner_item, words)
                .apply { setDropDownViewResource(R.layout.rail_spinner_drop) }
            spinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(parent: AdapterView<*>?, view: View?,
                                            position: Int, id: Long) {
                    if (cornersSyncing) return
                    val action = HotCorners.CHOICES.getOrNull(position)?.first ?: return
                    /* A Spinner reports its selection once on layout as well
                     * as on a tap; only a real change is worth a write. */
                    if (action == HotCorners.live.of(corner)) return
                    setCorners(JSONObject().put(corner, action),
                        cornerName(corner) + " → " + HotCorners.labelOf(action))
                }
                override fun onNothingSelected(parent: AdapterView<*>?) { /* nothing */ }
            }
        }
        cornersOn.setOnCheckedChangeListener { _, on ->
            if (cornersSyncing || on == HotCorners.live.enabled) return@setOnCheckedChangeListener
            setCorners(JSONObject().put("enabled", on),
                if (on) "hot corners on" else "hot corners off")
        }
        cornerZone.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar, value: Int, fromUser: Boolean) {
                cornerZoneLabel.text = rail.resources.getString(
                    R.string.rail_corner_zone_value,
                    value.coerceIn(
                        HotCornerPrefs.MIN_ACTIVATION_ZONE_PX,
                        HotCornerPrefs.MAX_ACTIVATION_ZONE_PX,
                    ),
                )
            }

            override fun onStartTrackingTouch(bar: SeekBar) = Unit

            override fun onStopTrackingTouch(bar: SeekBar) {
                if (cornersSyncing) return
                val value = bar.progress.coerceIn(
                    HotCornerPrefs.MIN_ACTIVATION_ZONE_PX,
                    HotCornerPrefs.MAX_ACTIVATION_ZONE_PX,
                )
                if (value != HotCorners.live.activationZonePx) {
                    setCorners(JSONObject().put("activationZonePx", value),
                        "activation zone: $value px")
                }
            }
        })
        cornerSensitivity.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar, value: Int, fromUser: Boolean) {
                cornerSensitivityLabel.text = rail.resources.getString(
                    R.string.rail_corner_sensitivity_value,
                    value.coerceIn(HotCornerPrefs.MIN_SENSITIVITY, HotCornerPrefs.MAX_SENSITIVITY),
                )
            }

            override fun onStartTrackingTouch(bar: SeekBar) = Unit

            override fun onStopTrackingTouch(bar: SeekBar) {
                if (cornersSyncing) return
                val value = bar.progress.coerceIn(
                    HotCornerPrefs.MIN_SENSITIVITY,
                    HotCornerPrefs.MAX_SENSITIVITY,
                )
                if (value != HotCorners.live.sensitivity) {
                    setCorners(JSONObject().put("sensitivity", value),
                        "gesture sensitivity: $value%")
                }
            }
        })
        cornersNote.text = rail.resources.getString(R.string.rail_corners_note,
            ScreenReplay.HOLD_SECONDS)
        /* From the store once, so the rows show what was saved rather than
         * the defaults, and so HotCorners.live is right before the first
         * finger lands. */
        scope.launch {
            try { HotCorners.read(configStore) } catch (err: Exception) {
                Log.w(TAG, "hot corners could not be read: " + err.message)
            }
            paintCorners()
        }
    }

    private fun setCorners(patch: JSONObject, note: String) {
        scope.launch {
            try {
                HotCorners.set(configStore, patch) { script -> runScript(script) { } }
                paintCorners()
                cornersNote.text = note + " · saved"
                cornersNote.setTextColor(rail.resources.getColor(R.color.pine_dim, null))
            } catch (err: Exception) {
                Log.w(TAG, "hot corners could not be saved", err)
                cornersNote.text = "could not save: " + (err.message ?: err.javaClass.simpleName)
                cornersNote.setTextColor(rail.resources.getColor(R.color.pine_bad, null))
            }
        }
    }

    /** The controls to HotCorners.live, without the listeners hearing it. */
    private fun paintCorners() {
        val prefs = HotCorners.live
        cornersSyncing = true
        try {
            if (cornersOn.isChecked != prefs.enabled) cornersOn.isChecked = prefs.enabled
            for ((corner, spinner) in cornerSpinners) {
                val at = HotCorners.indexOf(prefs.of(corner))
                if (spinner.selectedItemPosition != at) spinner.setSelection(at, false)
                spinner.isEnabled = prefs.enabled
                spinner.alpha = if (prefs.enabled) 1f else 0.45f
            }
            if (cornerZone.progress != prefs.activationZonePx) {
                cornerZone.progress = prefs.activationZonePx
            }
            if (cornerSensitivity.progress != prefs.sensitivity) {
                cornerSensitivity.progress = prefs.sensitivity
            }
            cornerZoneLabel.text = rail.resources.getString(
                R.string.rail_corner_zone_value, prefs.activationZonePx)
            cornerSensitivityLabel.text = rail.resources.getString(
                R.string.rail_corner_sensitivity_value, prefs.sensitivity)
            cornerZone.isEnabled = prefs.enabled
            cornerSensitivity.isEnabled = prefs.enabled
            cornerZone.alpha = if (prefs.enabled) 1f else 0.45f
            cornerSensitivity.alpha = if (prefs.enabled) 1f else 0.45f
        } finally {
            cornersSyncing = false
        }
    }

    private fun cornerName(corner: String): String = when (corner) {
        "tl" -> "top left"
        "tr" -> "top right"
        "bl" -> "bottom left"
        "br" -> "bottom right"
        else -> corner
    }

    private fun label(value: String): String = when (value) {
        "here" -> "the app"
        "box" -> if (state.voiceDevice == "nabu") "Nabu" else "the Pine Box"
        "both" -> "both"
        "off" -> "off"
        "nabu" -> "Nabu"
        "music" -> "Music"
        "voice" -> "DJs"
        "reply" -> "Replies"
        "sfx" -> "Clips / SFX"
        "video" -> "Videos"
        "master" -> "Master"   // [levels-one]
        "pads" -> "Pads"
        else -> value.ifBlank { "unknown" }
    }

    companion object {
        /* Asked of the page on every power paint. Each item is something
         * the operator can switch off, which is what makes the list worth
         * showing: a view, a 3D scene, the microphone, a video. */
        private const val TERMINAL_LOAD = """
            (function () {
              try {
                var on = [];
                var host = document.querySelector('.pine-view-host.open');
                if (host) {
                  var name = String(host.className || '').split(' ')
                    .filter(function (c) { return c.indexOf('pb-') === 0 || c.indexOf('pv-') === 0 || c.indexOf('sp-') === 0; })[0];
                  if (name) on.push('the ' + name.slice(3) + ' view');
                }
                var live = document.querySelectorAll('canvas');
                var gl = 0;
                for (var i = 0; i < live.length; i += 1) {
                  var r = live[i].getBoundingClientRect();
                  if (r.width > 8 && r.height > 8) gl += 1;
                }
                if (gl) on.push(gl + ' canvas' + (gl === 1 ? '' : 'es'));
                var vids = document.querySelectorAll('video');
                var playing = 0;
                for (var v = 0; v < vids.length; v += 1) {
                  if (!vids[v].paused && vids[v].currentSrc) playing += 1;
                }
                if (playing) on.push(playing + ' video' + (playing === 1 ? '' : 's'));
                var auds = document.querySelectorAll('audio');
                var sounding = 0;
                for (var a = 0; a < auds.length; a += 1) {
                  if (!auds[a].paused && auds[a].volume > 0.01) sounding += 1;
                }
                if (sounding) on.push(sounding + ' audio stream' + (sounding === 1 ? '' : 's'));
                if (window.PineTalkDot && PineTalkDot.state
                    && PineTalkDot.state() === 'listening') on.push('the microphone');
                return on.join(',');
              } catch (err) { return ''; }
            })()
        """

        private const val TAG = "PineRail"

        /* [smart-reinit] */
        private const val FIX_LINES = 40
        /* [tablet-update-ask] */
        private const val UPDATE_ROUTE = "/api/tablet/update-ask"
        private const val UPDATE_POLL_MS = 5000L
        private const val UPDATE_WATCH_MS = 20L * 60_000L
        private const val UPDATE_UNTAKEN_MS = 60_000L
        private const val DOCTOR_PREFS = "pine.doctor"
        private const val DOCTOR_RESUME_MS = 10 * 60 * 1000L

        /** #1211/#1207: the page's own flags - its pause, a held player slot. */
        private const val UNGAG = "(function(){try{" +
            "if(typeof fixUngag==='function'){var d=fixUngag();return d.length?d.join('; '):'nothing held';}" +
            "if(typeof pineAirPause==='function'){pineAirPause(false);return 'pause lifted';}" +
            "}catch(e){}return 'nothing to clear';})()"

        /** #1318: a duck that never lifted sounds like a dead station. */
        private const val LIFT_DUCK = "(function(){try{" +
            "var a=window.PineAir;if(!a)return 'no mixer here';" +
            "if(a.releaseAll)a.releaseAll();" +
            "else if(a.release){a.release('pad');a.release('clip');}" +
            "return 'lifted';" +
            "}catch(e){return 'mixer would not answer';}})()"

        /** The page's AudioContext: every player runs through it. */
        private const val RESUME_CTX = "(function(){try{" +
            "var c=window.pineAudioCtx;if(!c)return 'no audio engine';" +
            "var was=String(c.state);if(was!=='running'){var p=c.resume();if(p&&p.catch)p.catch(function(){});}" +
            "return was+', resume asked';" +
            "}catch(e){return 'would not resume: '+e.message;}})()"

        /** The record follows the clock: re-read it, then play() if still paused. */
        private const val RESUME_MUSIC = "(function(){try{" +
            "try{radioClockPoll()}catch(e){}" +
            "var m=window.musicPlayer||musicPlayer;if(!m)return 'no music player';" +
            "if(m.paused&&(m.currentSrc||m.src)){var p=m.play();if(p&&p.catch)p.catch(function(){});" +
            "return 'the clock re-read, play() asked';}" +
            "return 'the clock re-read';" +
            "}catch(e){return 'would not resume: '+e.message;}})()"
    }
}
