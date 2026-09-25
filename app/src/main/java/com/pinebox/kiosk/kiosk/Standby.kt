package com.pinebox.kiosk.kiosk

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import com.pinebox.kiosk.PineApp

/**
 * #1182T - THE TERMINAL RELAXES WHILE SOMEBODY ELSE IS USING THE GLASS.
 *
 * WHO ASKED, AND WHY. AutoBrowse, a Chromium browser being ported to this same
 * Lenovo Tab M9, sent a measured document on 15 Sep 2026. The number that
 * matters in it was taken by accident, while this app was dead from the boot
 * crash BootReceiver now records:
 *
 *                       MemFree      MemAvailable
 *   kiosk NOT running    488 MB        2.65 GB
 *   kiosk running     374-421 MB    1.39-1.44 GB
 *
 * The terminal is worth roughly 1.2 GB of available memory on a 4 GB tablet -
 * considerably more than its 777 MB RSS implies, once shared pages and its
 * cache pressure are counted. Freshly started it sits at 290 MB and climbs to
 * about 750 MB inside half a minute as the ring and the caches fill. None of
 * that is wrong for a device that expects to be the only thing on itself; all
 * of it is expensive now that it is not.
 *
 * THE ONE RULE THIS IS WRITTEN UNDER. The owner's requirement outranks every
 * line below: THE RADIO MUST NEVER STOP. Audio, StationFeed and the Oboe
 * sampler are untouched at EVERY level, and that is not an oversight to be
 * tidied up later by somebody optimising - it is the requirement. The
 * acceptance test AutoBrowse proposed is the right one and it is the one to
 * run: the number of started AAudio streams must not change, in either
 * direction, across an entire standby cycle. If a future level makes that
 * number move, that level is wrong, however much memory it saves.
 *
 * WHAT WAS ASKED FOR AND DELIBERATELY NOT DONE. The document's `light` asks
 * for webView.onPause() and pauseTimers(); its `deep` asks that the WebView be
 * allowed to drop its document and reload on the way back. Both are refused,
 * and the evidence is our own, not an opinion:
 *
 *  - #1241 measured this exact state on this exact tablet - foreground, screen
 *    awake, page visible - with rAF firing and setTimeout and setInterval not:
 *    a freshly installed one-second interval managed zero ticks in fifteen.
 *    What it cost was the whole station. The page's voice-feed poll, the
 *    station's "reload every page" stamp, the solo-gate un-gag and the page's
 *    own stuck-clip watchdog are every one of them driven by setInterval, so a
 *    tablet in that state goes silent and CANNOT BE RECOVERED FROM THE WEB
 *    SIDE AT ALL - the reload stamp it would need to read is itself read by a
 *    timer. That is the failure this project spent days finding. We are not
 *    going to cause it on purpose to save memory.
 *
 *  - There is also a plainer reason pauseTimers would not even work here:
 *    MainActivity's #1241 timer guard calls resumeTimers() every twenty
 *    seconds, from a main-thread Handler that a paused WebView cannot stop. A
 *    standby that paused timers would produce a twenty-second sawtooth, not a
 *    saving.
 *
 *  - And the document is out by one on the WebView anyway: the broadcast the
 *    operator is listening to IS an <audio> element inside that document.
 *    "Let the WebView drop its document" is spelled, on this device, "stop the
 *    radio". It is the one thing in the whole compromise that cannot be given.
 *
 * WHAT IS GIVEN INSTEAD, and it is the bulk of the memory either way:
 *
 *   light  the ScreenReplay ring is written to disk and then LET GO - the
 *          90 MB blob, the encoder and the VirtualDisplay, which is the single
 *          largest releasable thing the terminal holds, and also the thing
 *          that was quietly filming the other app's browser. The PineNet
 *          picture cache is trimmed. The wallpaper stops repainting.
 *
 *   deep   everything in light, plus the wallpaper poll suspended outright,
 *          JackWatch's two-second `dumpsys input` poll rested, and the
 *          WebView's in-memory resource cache dropped - the cache, not the
 *          document and not the timers.
 *
 * THE LEASE IS THE IMPORTANT PART, and this is the document's own reasoning,
 * which is correct and worth keeping in its own words:
 *
 *   "ttl_ms means you never have to trust us to clean up. We re-send the
 *    request on a heartbeat while we are in front, so a missed one is
 *    indistinguishable from our app being killed, crashing, or being swiped
 *    away - and in every one of those cases you come back on your own. The
 *    only failure mode is 'the kiosk restored itself a little early', never
 *    'the kiosk stayed relaxed forever because a dead app never said
 *    otherwise'."
 *
 * So the terminal also restores itself unconditionally on its own onResume, on
 * SCREEN_ON, on an explicit level=off, and on the Revive path - four roads
 * back, none of which depends on anybody being alive to ask.
 */
object Standby {

    private const val TAG = "PineStandby"

    const val OFF = 0
    const val LIGHT = 1
    const val DEEP = 2

    /** Bounds on a lease. Short enough to recover from a dead caller quickly,
     *  long enough that a heartbeat every thirty seconds is comfortable. */
    private const val TTL_MIN_MS = 5_000L
    private const val TTL_MAX_MS = 300_000L
    private const val TTL_DEFAULT_MS = 90_000L

    private val handler = Handler(Looper.getMainLooper())

    /**
     * WHERE THE HEAVY HALF RUNS, AND WHY IT IS NOT THE MAIN THREAD.
     *
     * A BroadcastReceiver's onReceive runs on the main thread, and so does the
     * SCREEN_ON receiver in PineAppRecorder. The steps below are not small:
     * ScreenReplay.stop() joins its encoder drain thread with a 1500 ms
     * timeout and then writes up to 90 MB of history to flash, and the way
     * back reads it in again. Doing that on the main thread would stall the
     * WebView that is playing the broadcast for as long as it took - which on
     * this project has a name and a history. The station has been measured
     * going silent from a starved loop more than once, and "the browser came
     * to the front and the radio hiccupped" would be the same fault wearing a
     * new coat.
     *
     * ONE thread, not a pool, because the order matters: a leave that overtook
     * the enter it is undoing would put the ring back and then immediately let
     * it go again, and the terminal would sit relaxed with nobody asking. A
     * single worker makes the sequence the sequence it was asked for.
     *
     * The state fields are set synchronously in set(), before anything is
     * handed here, so `active` and `level` are true the instant the request
     * lands - MediaFocus and WallpaperWatch both read them and both need the
     * answer now rather than in a second's time.
     */
    private val worker = java.util.concurrent.Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "pine-standby").apply { isDaemon = true }
    }

    @Volatile private var appContext: Context? = null

    /** What has actually been applied, which is not always what was asked. */
    @Volatile var level: Int = OFF
        private set

    @Volatile var since: Long = 0L
        private set

    @Volatile var requester: String = ""
        private set

    val active: Boolean get() = level != OFF

    fun levelName(): String = name(level)

    fun name(of: Int): String = when (of) {
        LIGHT -> "light"
        DEEP -> "deep"
        else -> "off"
    }

    fun rank(of: String?): Int = when (of?.lowercase()) {
        "light" -> LIGHT
        "deep" -> DEEP
        else -> OFF
    }

    private val expire = Runnable {
        val ctx = appContext
        if (ctx != null) set(ctx, OFF, 0L, "the lease expired")
    }

    /**
     * Ask for a level, for a while.
     *
     * Idempotent, and every call renews the lease - which is what makes a
     * heartbeat the right way for a caller to say "still here". Going shallower
     * undoes only the steps the shallower level does not want, so light after
     * deep puts the wallpaper and the jack poll back without touching anything
     * light is entitled to keep down.
     */
    @Synchronized
    fun set(context: Context, want: Int, ttlMs: Long, who: String) {
        val app = context.applicationContext
        appContext = app

        handler.removeCallbacks(expire)
        if (want != OFF) {
            handler.postDelayed(expire, ttlMs.coerceIn(TTL_MIN_MS, TTL_MAX_MS))
        }

        val had = level
        if (want == had) {
            if (want != OFF) Log.i(TAG, "lease renewed at " + name(want) + " by " + who)
            return
        }

        Log.i(TAG, "#1182T " + name(had) + " -> " + name(want) + " (" + who + ")")
        level = want
        requester = who
        since = System.currentTimeMillis()

        /* The flag WallpaperWatch reads, set here and not on the worker: a
         * repaint decided in the next few milliseconds must already see it.
         * Everything else below can afford to be a moment late. */
        (app as? PineApp)?.wallpaper?.standingBy = (want != OFF)

        /* Deepening: apply what is newly wanted, shallowest first.
         * Shallowing: undo what is no longer wanted, deepest first.
         * Off the main thread - see the note on `worker`. */
        worker.execute {
            try {
                if (want > had) {
                    if (had < LIGHT && want >= LIGHT) enterLight(app)
                    if (had < DEEP && want >= DEEP) enterDeep(app)
                } else {
                    if (had >= DEEP && want < DEEP) leaveDeep(app)
                    if (had >= LIGHT && want < LIGHT) leaveLight(app)
                }
            } catch (err: Throwable) {
                /* Standby is a courtesy to another app. Nothing in it is
                 * allowed to take the terminal down, and a step that throws
                 * must still leave the rest of the sequence to run. */
                Log.w(TAG, "#1182T a standby step stumbled", err)
            }
            tell(app)
        }
    }

    /** Back to normal, from anywhere, for any reason. Safe to call always. */
    fun leave(context: Context, why: String) = set(context, OFF, 0L, why)

    /* ---------------------------------------------------------------- work */

    /**
     * THE RING, THE CACHE, AND THE WALLPAPER.
     *
     * NOT the audio. Not StationFeed. Not the Oboe sampler. Not the WebView's
     * timers and not its document. See the note at the top of this file for
     * why each of those is on the untouchable list, with the item numbers.
     */
    private fun enterLight(app: Context) {
        val pine = app as? PineApp

        /* THE BIG ONE. ScreenReplay holds a ring sized from its own constants -
         * 600 kbps x 1200 s with a quarter of headroom, capped at 100 MB - as
         * one ByteArray on the Dalvik heap, plus an encoder and a
         * VirtualDisplay mirroring the whole screen at 12 fps forever.
         * release() writes the history to disk first, so nothing the operator
         * could want to look back at is lost; prime() reads it back in on the
         * way out. It also means we stop filming the other app, which the
         * AutoBrowse document raised separately and is right to raise. */
        runCatching { pine?.replay?.release() }
            .onFailure { Log.w(TAG, "the replay would not stand down: " + it.message) }

        /* The picture cache. HONEST NOTE FOR WHOEVER READS THE NUMBERS LATER:
         * the document lists this as "up to 256 MB" among the releasable
         * memory, and it is not memory. PineNet's cache is FILES in
         * cacheDir/pineimg; trimming it frees disk, not RSS. It is done here
         * because it is nearly free and a smaller cache is a smaller thing to
         * walk, but nobody should expect meminfo to move because of it. */
        runCatching { com.pinebox.kiosk.net.PineNet.relax() }
            .onFailure { Log.w(TAG, "the picture cache would not trim: " + it.message) }

        /* The wallpaper's own flag is set in set(), synchronously, because a
         * repaint decided in the next few milliseconds has to see it. It is
         * #1182T item 2 arriving by the other road: a repaint raises
         * CONFIG_ASSETS_PATHS and recreates whichever activity is in front.
         * WallpaperWatch works that out for itself now by reading the activity
         * manager, but a request is instant and a dump is not. */
    }

    private fun leaveLight(app: Context) {
        val pine = app as? PineApp

        /* START IF THE PANEL IS LIT, AND OTHERWISE DO NOTHING AT ALL.
         *
         * The screen test is not tidiness. PineAppRecorder stops the encoder
         * when the glass goes dark on purpose, and its own note says why: a
         * mirrored VirtualDisplay whose panel is off keeps handing the encoder
         * the same frozen frame and KEY_REPEAT_PREVIOUS_FRAME_AFTER dutifully
         * re-encodes it twelve times a second, which is about 20 kB/s of
         * nothing and fills the ring in roughly twelve minutes - pushing out
         * every real thing that happened before the tablet was put down.
         * Standby restoring itself on a dark screen would undo that quietly.
         *
         * And no prime() here. start() already takes the history back off disk
         * when the ring is empty - it has to, because that is the same road it
         * walks after a process death - so calling start() is the whole
         * restore. On a dark screen the history simply stays on disk, where it
         * is safe, until the next SCREEN_ON starts the encoder and reads it. */
        runCatching {
            val power = app.getSystemService(Context.POWER_SERVICE) as? PowerManager
            if (power?.isInteractive != true) {
                Log.i(TAG, "#1182T screen is dark; the ring stays on disk until it wakes")
                return@runCatching
            }
            val why = pine?.replay?.start()
            if (why != null) Log.w(TAG, "the replay would not restart: " + why)
        }.onFailure { Log.w(TAG, "the replay would not come back: " + it.message) }
    }

    private fun enterDeep(app: Context) {
        val pine = app as? PineApp

        /* Stop choosing pictures at all, rather than only holding them back. */
        runCatching { pine?.wallpaper?.stop() }
            .onFailure { Log.w(TAG, "the wallpaper watch would not stop: " + it.message) }

        /* THE JACK POLL RESTS - AND IS NOT STOPPED. JackWatch.stop() would
         * also hand the audio back from the cable to the speaker, because it
         * deliberately leaves the route as it found it. Doing that here would
         * move the sound out of the operator's headphones the moment a browser
         * came to the front, which is the owner's rule broken by a different
         * door than the one everybody was watching. rest() takes the
         * two-second `dumpsys input` poll off the CPU and touches nothing the
         * framework has been told. */
        handler.post {
            runCatching { com.pinebox.kiosk.MainActivity.live?.standbyJackPoll(false) }
                .onFailure { Log.w(TAG, "the jack poll would not rest: " + it.message) }
            /* The WebView's in-memory resource cache, which is decoded images
             * and nothing structural. NOT clearCache(true) - that would take
             * the disk cache with it and make the way back slower for no gain -
             * and NOT the document, whose <audio> element is the broadcast. */
            runCatching { com.pinebox.kiosk.MainActivity.live?.standbyDropWebCache() }
                .onFailure { Log.w(TAG, "the web cache would not drop: " + it.message) }
        }
    }

    private fun leaveDeep(app: Context) {
        val pine = app as? PineApp
        runCatching { pine?.wallpaper?.start() }
            .onFailure { Log.w(TAG, "the wallpaper watch would not restart: " + it.message) }
        handler.post {
            runCatching { com.pinebox.kiosk.MainActivity.live?.standbyJackPoll(true) }
                .onFailure { Log.w(TAG, "the jack poll would not wake: " + it.message) }
        }
    }

    /**
     * Say what state we are in, for anyone who asked to be told.
     *
     * The document asked for this and called it optional. It is cheap and it
     * is worth more than it looks: `playing` is the field they said they would
     * actually use - if the radio is live they keep their own audio muted and
     * their UI quiet - and a broadcast is how they find that out without
     * polling us. Sent with no receiver permission because it says nothing
     * private: a level name, how long it has stood, and whether the station is
     * on the air.
     */
    private fun tell(app: Context) {
        runCatching {
            app.sendBroadcast(Intent(CHANGED).apply {
                putExtra("level", levelName())
                putExtra("since_ms", System.currentTimeMillis() - since)
                putExtra("playing", playing())
            })
        }.onFailure { Log.w(TAG, "could not say what state we are in: " + it.message) }
    }

    /** Is the station actually sounding? The sampler knows; nothing else does
     *  without asking the page, and asking the page from here would be a
     *  main-thread hop for a field in a broadcast. */
    private fun playing(): Boolean =
        runCatching { fm.pinebox.kiosk.audio.PineSampler.ready() }.getOrDefault(false)

    const val ACTION = "com.pinebox.kiosk.action.SET_STANDBY"
    const val CHANGED = "com.pinebox.kiosk.action.STANDBY_CHANGED"

    /** For a caller that has only the extras, not the ranks. */
    internal fun ttlFrom(intent: Intent): Long =
        intent.getLongExtra("ttl_ms", TTL_DEFAULT_MS)
}

/**
 * #1182T - THE DOOR A FOREGROUND APP KNOCKS ON.
 *
 * Exported and permission-guarded at signature level, which means the caller
 * has to be signed with the same key this APK is. That is not a hurdle for
 * AutoBrowse: deploy.sh already proves the platform-signing road on this
 * device, and they offered to take it. It IS a hurdle for anything else on the
 * tablet, which is the point - an unguarded receiver that can stop the screen
 * recorder is a receiver any app can use to stop the screen recorder.
 *
 *   adb shell am broadcast -a com.pinebox.kiosk.action.SET_STANDBY \
 *       --es level light --el ttl_ms 60000 --es requester manual-test
 *
 * Every extra is optional and the defaults are the safe ones: an absent level
 * is `off`, an absent ttl is ninety seconds, an absent requester is "?" in the
 * log. A malformed request therefore wakes the terminal up rather than putting
 * it to sleep, which is the direction this should fail in.
 */
class StandbyReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Standby.ACTION) return
        val who = intent.getStringExtra("requester") ?: "?"

        /* `level` is the contract. `on` is accepted as well because the
         * document's own smallest version used a boolean, and a caller who
         * implemented that version first should not be met with silence. */
        val want = when {
            intent.hasExtra("level") -> Standby.rank(intent.getStringExtra("level"))
            intent.getBooleanExtra("on", false) -> Standby.LIGHT
            else -> Standby.OFF
        }

        Log.i("PineStandby", "asked for " + Standby.name(want) + " by " + who)
        Standby.set(context, want, Standby.ttlFrom(intent), who)
    }
}
