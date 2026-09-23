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
import com.pinebox.kiosk.R
import com.pinebox.kiosk.config.ConfigStore
import com.pinebox.kiosk.config.HotCorners
import com.pinebox.kiosk.replay.ScreenReplay
import com.pinebox.kiosk.net.StationClient
import com.pinebox.kiosk.power.PowerWatch
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
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
) {

    private val conn: TextView = rail.findViewById(R.id.railConn)
    private val now: TextView = rail.findViewById(R.id.railNow)
    private val fmSwitch: Button = rail.findViewById(R.id.fmSwitch)
    private val airPause: Button = rail.findViewById(R.id.airPause)
    private val airNote: TextView = rail.findViewById(R.id.airNote)
    private val routeNote: TextView = rail.findViewById(R.id.routeNote)
    private val jumpList: ViewGroup = rail.findViewById(R.id.jumpList)
    private val logsFull: Button = rail.findViewById(R.id.logsFull)
    private val playerList: ViewGroup = rail.findViewById(R.id.playerList)
    private val playerNote: TextView = rail.findViewById(R.id.playerNote)

    /* ---- the hot corners - see config/HotCorners.kt ---- */
    private val cornersOn: SwitchCompat = rail.findViewById(R.id.cornersOn)
    private val cornersNote: TextView = rail.findViewById(R.id.cornersNote)
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
    private var fixRunning = false

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
    )

    private val volumeLabels: Map<String, TextView> = mapOf(
        "music" to rail.findViewById(R.id.vol_music_value),
        "voice" to rail.findViewById(R.id.vol_voice_value),
        "sfx" to rail.findViewById(R.id.vol_reply_value),
        "video" to rail.findViewById(R.id.vol_video_value),
    )

    /** The last snapshot, painted or not. */
    private var state = RailState()

    /** Who is on the broadcast, from the last time the drawer was opened. */
    private var roster = AirOwners.Roster()

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

        airPause.setOnClickListener {
            val want = !state.paused
            call(if (want) "going off air" else "back on air") {
                JSONObject(client.post("/api/radio/pause", JSONObject().put("paused", want).toString()))
            }
        }

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
                /* The page can change the corners too (hotCornersSet), and
                 * HotCorners.live already holds the result; the rows only
                 * need to catch up when they come into view. */
                paintCorners()
                /* banked_seconds is on /api/radio/pause and nowhere else - one
                 * request, on the open, never on a clock. */
                call(null) { JSONObject(client.get("/api/radio/pause")) }
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
            }
        })
    }

    /** Called from the activity's feed collector, already off the tick. */
    fun render(next: RailState) {
        state = next
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

    /** A write that returns a dj_state object; its routing is adopted at once. */
    /**
     * #1212/#1213: GET THE BROADCAST BACK, whatever it takes.
     *
     * Over 2026-09-11/12 every cure was found by hand and applied by hand,
     * and the commonest of them - reload the page - had to be asked for in
     * words four times, because THE ONE THING NO SERVER CAN DO IS RELOAD
     * THIS WEBVIEW. A stale pause flag, a player holding a slot nothing
     * will clear, a page running yesterday's code: all of them live on
     * this side of the glass, and restarting the station reaches none of
     * them.
     *
     * So the ladder runs from here, cheapest first, and stops the moment
     * anybody reports hearing something. The station half of each rung is
     * the same one the wedge console and the unattended watchdog press -
     * one ladder, three ways in, so a cure can never exist in only one of
     * them (see POST /api/broadcast/fix/{step}).
     */
    private fun reinitialise() {
        if (fixRunning) return
        fixRunning = true
        fixGo.isEnabled = false
        val said = StringBuilder()
        fun say(line: String) {
            if (said.isNotEmpty()) said.appendLine()
            said.append(line)
            fixNote.text = said.toString()
        }
        scope.launch {
            try {
                say("looking…")
                var health = JSONObject(client.get("/api/broadcast/health"))
                if (heardWithin(health, 25.0)) {
                    say("the broadcast is being heard right now - nothing to do")
                    return@launch
                }

                if (health.optBoolean("paused", false)) {
                    say("1 the station was paused - lifting it")
                    client.post("/api/broadcast/fix/onair", "{}")
                } else {
                    say("1 not paused")
                }

                /* The local half, and the reason this button is on the
                 * tablet rather than only on the station. */
                say("2 clearing this page's own flags")
                runScript(
                    "(function(){try{" +
                        "if(typeof fixUngag==='function'){" +
                            "var d=fixUngag();return d.length?d.join('; '):'nothing held';}" +
                        "if(typeof pineAirPause==='function'){pineAirPause(false);return 'pause lifted';}" +
                    "}catch(e){}return 'nothing to clear';})()"
                ) { got -> say("  " + got.trim('"')) }

                /* #1318: A DUCK THAT NEVER LIFTED SOUNDS EXACTLY LIKE A
                 * DEAD STATION. Pads duck the broadcast and release it
                 * when nothing is sounding; if that release is missed,
                 * every element reports "playing" at volume 1 and the
                 * room is silent. Cheap to undo, and free when there was
                 * nothing to undo. */
                say("3 lifting any duck left on the broadcast")
                runScript(
                    "(function(){try{" +
                        "var a=window.PineAir;if(!a)return 'no mixer here';" +
                        "if(a.releaseAll)a.releaseAll();" +
                        "else if(a.release){a.release('pad');a.release('clip');}" +
                        "var d=a.duckState?a.duckState():null;" +
                        "return d?('music gain '+d.musicGain):'lifted';" +
                    "}catch(e){return 'mixer would not answer';}})()"
                ) { got -> say("  " + got.trim('"')) }

                say("4 dropping what the page was stuck on")
                client.post("/api/broadcast/fix/flush", "{}")

                health = JSONObject(client.get("/api/broadcast/health"))
                if (health.optBoolean("gagged", false)
                    || health.optString("holding_the_air").isBlank()) {
                    say("5 releasing the exclusive")
                    client.post("/api/broadcast/fix/release", "{}")
                }

                /* [#1388] THE FAULT WITH NO SOUND OF ITS OWN.
                 *
                 * "make sure this button is able to fix any and every
                 *  issue that stops the dialogue and broadcast from
                 *  happening. I need that dialogue always able to be
                 *  repaired and restored."
                 *
                 * Measured on the station 2026-09-22: the pair went
                 * unheard for 3h24m while every rung above would have
                 * reported itself healthy. Nothing was gagged, nothing
                 * was stuck, the page was fine, listeners were connected
                 * and something was sounding every single second - the
                 * board was filling the hole with 822 clips in thirty
                 * minutes. The dialogue SHELF was empty, so every round
                 * had to be written AND rendered live into its own
                 * four-minute hole, and no rung on this ladder had ever
                 * looked at the shelf.
                 *
                 * It goes HERE, before the rungs that cost a page reload
                 * or a restart, because it is cheap and because a restart
                 * does not fix it - a restarted station has an empty
                 * shelf too. /api/broadcast/health now carries `bank` on
                 * every branch, so this asks before it acts. */
                val bank = health.optJSONObject("bank")
                if (bank != null) {
                    say("4b the dialogue bank")
                    say("  " + bank.optString("say"))
                    if (bank.optBoolean("bare", false)
                        || bank.optInt("keeper_failures", 0) > 0) {
                        val out = client.post("/api/broadcast/fix/bank", "{}")
                        try {
                            val lines = JSONObject(out).optJSONArray("lines")
                            if (lines != null) {
                                for (i in 0 until lines.length()) {
                                    val line = lines.optString(i).trim()
                                    if (line.isNotEmpty()) say("  " + line)
                                }
                            }
                        } catch (err: Exception) {
                            say("  asked for a round to be banked")
                        }
                    } else {
                        say("  the shelf is stocked - not the cause here")
                    }
                }

                say("listening for eight seconds…")
                delay(8000)
                health = JSONObject(client.get("/api/broadcast/health"))
                if (heardWithin(health, 12.0)) {
                    say("sound is back - stopping here")
                    return@launch
                }

                /* #1318: IS THIS TERMINAL DEAF?
                 *
                 * Chromium's network stack inside the WebView can die
                 * while everything else stays up - the bridge answers,
                 * the feed updates, every view paints, and not one
                 * fetch, <audio> or <video> works. The panel looks alive
                 * and the station is inaudible.
                 *
                 * A RELOAD DOES NOT CURE IT, measured: the network
                 * service lives in the app process, so the same dead
                 * stack is handed to the new page. Only a fresh process
                 * brings it back.
                 *
                 * This button arrived here over the BRIDGE, which is the
                 * app's own HTTP client. So if the page cannot do what
                 * the app just did, the page is the broken half - and no
                 * amount of ordinary dead air can produce that. */
                say("6 can this page still reach the station?")
                runScript(
                    "(function(){try{" +
                        "window.__pineFixProbe='asking';" +
                        "var t=setTimeout(function(){" +
                            "if(window.__pineFixProbe==='asking')" +
                                "window.__pineFixProbe='web-timeout';},12000);" +
                        "fetch('/api/dj/sections',{cache:'no-store'}).then(" +
                            "function(r){clearTimeout(t);" +
                                "window.__pineFixProbe=r.status>0?'web-ok':'web-bad';}," +
                            "function(){clearTimeout(t);" +
                                "window.__pineFixProbe='web-dead';});" +
                        "return 'asked';" +
                    "}catch(e){window.__pineFixProbe='web-threw';return 'threw';}})()"
                ) { }
                delay(13000)
                var verdict = "unknown"
                runScript("(function(){return window.__pineFixProbe||'unknown';})()") {
                    got -> verdict = got.trim('"')
                }
                delay(400)

                if (verdict == "web-dead" || verdict == "web-timeout"
                    || verdict == "web-threw") {
                    say("  no - the app can reach it and this page cannot")
                    say("7 bringing the terminal round; it comes back by itself")
                    val went = com.pinebox.kiosk.net.Revive.now(
                        rail.context, "the repair button: the page is deaf")
                    if (!went) {
                        say("  too soon since the last one - reloading instead")
                        runScript("location.reload()") { }
                        delay(9000)
                    }
                } else {
                    say("  yes (" + verdict + ") - reloading this page")
                    runScript("location.reload()") { }
                    delay(9000)
                }

                health = JSONObject(client.get("/api/broadcast/health"))
                if (heardWithin(health, 15.0)) {
                    say("sound is back")
                    return@launch
                }

                /* #1318: AND THE CABLE. The wired-device announcement
                 * outlives the app, so a stale one points the whole
                 * broadcast at a socket with nothing in it - silence that
                 * every other check here would call healthy. */
                say("8 checking the audio is pointed at something")
                try {
                    runScript(
                        "(function(){try{" +
                            "if(window.pineDesktop&&pineDesktop.jack){" +
                                "pineDesktop.jack();return 'asked the jack to report';}" +
                            "return 'no jack door on this build';" +
                        "}catch(e){return 'the jack would not answer';}})()"
                    ) { got -> say("  " + got.trim('"')) }
                    delay(1200)
                } catch (err: Exception) {
                    say("  could not ask: " + (err.message ?: ""))
                }

                say("9 restarting the station - about twenty seconds")
                client.post("/api/broadcast/fix/restart", "{}")
            } catch (err: Exception) {
                Log.w(TAG, "reinitialise failed", err)
                say("the station would not answer: "
                    + (err.message ?: err.javaClass.simpleName))
                say("what is left needs hands: close and reopen this app,")
                say("or check the box is powered and on the network.")
            } finally {
                fixRunning = false
                fixGo.isEnabled = true
            }
        }
    }

    /** Has anybody reported AUDIBLE sound inside the last [within] seconds? */
    private fun heardWithin(health: JSONObject, within: Double): Boolean {
        if (health.isNull("heard_seconds_ago")) return false
        return health.optDouble("heard_seconds_ago", 1.0e9) <= within
    }

    private fun send(note: String?, body: () -> String) {
        call(note) { JSONObject(client.post("/api/dj/output", body())) }
    }

    /**
     * Select one complete destination with the same ordered transaction as
     * the desktop: owner first, routes second, durable settings last.
     */
    private fun selectDestination(key: String) {
        val preset = DjOutput.PRESETS[key] ?: return
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
                state = state.patched(routed)
                roster = AirOwners.read(
                    JSONObject(client.get("/api/radio/listeners")), settings,
                )
                paint()
                noteOk("broadcast -> " + preset.label)
            } catch (err: Exception) {
                Log.w(TAG, "could not select broadcast destination", err)
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
                "return [m.music,m.voice,m.sfx,m.video];" +
            "}catch(e){return [];}})()",
        ) { answer ->
            try {
                val values = org.json.JSONArray(answer)
                val names = listOf("music", "voice", "sfx", "video")
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
            chip.isActivated = if (destination in presetChips) {
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
    }
}
