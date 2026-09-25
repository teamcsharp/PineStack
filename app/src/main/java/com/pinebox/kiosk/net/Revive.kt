package com.pinebox.kiosk.net

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * BRINGING THE TERMINAL BACK WHEN ITS NETWORK HAS DIED UNDER IT.
 *
 * 2026-09-13: the station was dispatching for hours and the tablet was
 * silent. The panel looked perfectly alive - the feed updating, every view
 * painting - because `PineStationFeed` and the whole API surface go through
 * the NATIVE BRIDGE. What had died was Chromium's own network stack inside
 * the WebView, and with it every `fetch`, every `<audio>` and every
 * `<video>`: the only three things the broadcast actually needs.
 *
 * The tell was that images kept loading. PineNet serves those through the
 * app's own HTTP client, so they were never touching the dead stack.
 *
 * Measured, and each of these is already ruled out - do not go round them
 * again: no proxy is set, Tailscale is up but `ip route get` for this uid
 * goes straight out wlan0, mediaPlaybackRequiresUserGesture is already
 * false, nothing was ducked and every element was unmuted at volume 1, and
 * the LoopDoor proxy answered two requests on one connection in 0.02s.
 *
 * WHAT DOES CURE IT is a fresh process. `am force-stop` + `am start` took
 * `fetch` from "TypeError: Failed to fetch in 82ms" to "200 in 442ms" on
 * the instant, and audio came straight back. A WebView RELOAD would not do
 * it: the network service lives in the app process, so the same dead stack
 * would be handed to the new page.
 *
 * And it came back about twenty minutes later, which is why this exists as
 * code rather than as a note. The operator should not have to notice.
 */
object Revive {

    private const val TAG = "PineRevive"

    /** Nothing may bring the terminal round more often than this. */
    private const val REST_MS = 5 * 60 * 1000L

    /* A REVIVAL THAT DOES NOT HELP MUST NOT REPEAT.
     *
     * The rest below used to live in a field, and a field is born again
     * with the process it lives in - so a terminal that came back still
     * deaf would have revived again, and again, for ever. A restart loop
     * is worse than a silent screen: the operator can at least read a
     * silent screen. These are on disk, so the new process inherits what
     * the old one did. */
    private const val PREFS = "pine.revive"
    private const val KEY_AT = "lastAt"
    private const val KEY_RUN = "inARow"
    private const val GIVE_UP_AFTER = 3
    private const val RUN_WINDOW_MS = 30 * 60 * 1000L

    private fun prefs(context: Context) =
        context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun lastAtOf(context: Context): Long =
        try { prefs(context).getLong(KEY_AT, 0L) } catch (e: Exception) { 0L }

    private fun runOf(context: Context): Int =
        try { prefs(context).getInt(KEY_RUN, 0) } catch (e: Exception) { 0 }

    /** Whether a revival would be allowed right now. */
    fun rested(context: Context): Boolean {
        val at = lastAtOf(context)
        if (at == 0L) return true
        val since = System.currentTimeMillis() - at
        if (since < REST_MS) return false
        /* Past the window the run is forgotten - whatever it was, it is
         * not the same episode any more. */
        if (since >= RUN_WINDOW_MS) return true
        return runOf(context) < GIVE_UP_AFTER
    }

    fun sinceMs(context: Context): Long {
        val at = lastAtOf(context)
        return if (at == 0L) -1L else System.currentTimeMillis() - at
    }

    fun inARow(context: Context): Int {
        val at = lastAtOf(context)
        if (at == 0L) return 0
        if (System.currentTimeMillis() - at >= RUN_WINDOW_MS) return 0
        return runOf(context)
    }

    /**
     * Start the app again and end this process.
     *
     * The alarm is armed BEFORE the exit so there is no window in which
     * the terminal is simply gone: if the exit lands first the alarm still
     * fires, and if the alarm somehow fails the exit has not happened yet
     * and the operator is no worse off than before.
     *
     * Returns false when it declined - too soon after the last one, or the
     * launcher intent could not be built - so the caller can say so rather
     * than assuming it worked.
     */
    @Synchronized
    fun now(context: Context, why: String): Boolean {
        /* #1182T: WHATEVER ELSE HAPPENS, COME OUT OF STANDBY FIRST.
         *
         * The fourth of the four unconditional roads back, and arguably the
         * one that matters most, because Revive is the path taken when
         * something has already gone wrong and nobody is yet sure what. A
         * terminal being revived must not be revived into a relaxed state that
         * some foreground app asked for and may well have died holding.
         *
         * Before the rested() check on purpose: a revive that DECLINES - too
         * soon after the last one, or a restart loop already recognised -
         * should still have woken the terminal on its way past. */
        com.pinebox.kiosk.kiosk.Standby.leave(context, "revive: " + why)
        if (!rested(context)) {
            val run = inARow(context)
            if (run >= GIVE_UP_AFTER) {
                Log.w(TAG, "NOT reviving: $run in a row already and it did " +
                    "not help - a restart loop is worse than a silent screen")
            } else {
                Log.i(TAG, "not reviving: only ${sinceMs(context) / 1000}s " +
                    "since the last one")
            }
            return false
        }
        val ctx = context.applicationContext
        val intent = ctx.packageManager
            .getLaunchIntentForPackage(ctx.packageName)
            ?.addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_CLEAR_TASK
            )
        if (intent == null) {
            Log.w(TAG, "no launch intent; staying put")
            return false
        }
        val pending = try {
            PendingIntent.getActivity(
                ctx, 0xB0A7, intent,
                PendingIntent.FLAG_CANCEL_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        } catch (err: Exception) {
            Log.w(TAG, "no pending intent: ${err.message}")
            return false
        }
        val alarm = try {
            ctx.getSystemService(AlarmManager::class.java)
        } catch (err: Exception) {
            null
        }
        if (alarm == null) {
            Log.w(TAG, "no alarm manager; staying put")
            return false
        }
        /* Written BEFORE the exit, because after it there is no us. */
        try {
            val was = inARow(context)
            prefs(context).edit()
                .putLong(KEY_AT, System.currentTimeMillis())
                .putInt(KEY_RUN, was + 1)
                .commit()          // commit, not apply: we are about to die
        } catch (err: Exception) {
            Log.w(TAG, "could not remember this revival: ${err.message}")
        }
        Log.w(TAG, "reviving the terminal (${inARow(context)} in this run): $why")
        /* Nine hundred milliseconds: long enough that this process is
         * gone before the launch lands (a launch into a dying process is
         * the one way this can fail to come back), short enough that
         * nobody watching the screen calls it a crash.
         *
         * NOT setExactAndAllowWhileIdle. Measured on this tablet the
         * first time this ran: "Package com.pinebox.kiosk, uid 10212
         * lost permission to set exact alarms!" - so the alarm was
         * refused, this returned false, and the process correctly
         * stayed alive rather than exiting into nothing. Exactness was
         * never needed: the difference between a restart at 900ms and
         * one at 1.2s is invisible, and setAndAllowWhileIdle needs no
         * permission anybody can take away. */
        /* #1317d: AND THE ALARM MUST BE ONE ANDROID WILL ACT ON.
         *
         * #1317c below blamed the clock for the panel not coming back.
         * That was a guess that fitted and it was wrong. The log:
         *
         *   ActivityTaskManager: Background activity launch blocked
         *     ... com.pinebox.kiosk/.MainActivity ... (BAL_BLOCK)
         *     result code=102
         *
         * A process that has just called exit(0) has no foreground
         * standing, and an ordinary alarm PendingIntent is a background
         * activity launch, which recent Android refuses. The tablet was
         * dead for two and a half minutes.
         *
         * setAlarmClock() is exempt - it carries the "this will wake the
         * user" contract, it does not need the SCHEDULE_EXACT_ALARM this
         * uid was measured to have LOST, and its PendingIntent may start
         * an activity. It also appears in the system's alarm list, which
         * is an honest description of what this is.
         *
         * #1317c: TWO AND A HALF SECONDS, not nine hundred milliseconds.
         *
         * Measured on the tablet: at 900ms the app came back and the
         * panel NEVER LOADED - no "panel up in" line at all, the page
         * dead, listeners=0 - while `am force-stop` + `am start` on the
         * same build loaded it in 4661ms and the station saw
         * listeners=2 immediately. The difference is the race this
         * function's own note warned about: exit(0) begins a teardown
         * that is not instant, and a launch that lands inside it gets a
         * half-dead process. Android may also be restarting the
         * foreground activity itself, so there were two launches
         * fighting.
         *
         * Long enough that the old process is genuinely gone, short
         * enough that nobody watching calls it a crash. */
        val whenAt = System.currentTimeMillis() + 2500L
        var armed = false
        /* #1317d: the BAL-exempt road first. */
        try {
            alarm.setAlarmClock(
                AlarmManager.AlarmClockInfo(whenAt, pending), pending)
            armed = true
        } catch (err: Exception) {
            Log.w(TAG, "alarm clock refused: ${err.message}")
        }
        if (!armed) {
            try {
                alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, whenAt, pending)
                armed = true
            } catch (err: Exception) {
                Log.w(TAG, "allow-while-idle refused: ${err.message}")
            }
        }
        if (!armed) {
            try {
                alarm.set(AlarmManager.RTC_WAKEUP, whenAt, pending)
                armed = true
            } catch (err: Exception) {
                Log.w(TAG, "plain alarm refused too: ${err.message}")
            }
        }
        if (!armed) {
            /* Nothing will bring it back, so it does not go away. A
             * silent terminal is bad; a terminal that is simply gone
             * until somebody walks over to it is worse. */
            Log.w(TAG, "no alarm could be armed; staying put")
            return false
        }
        Runtime.getRuntime().exit(0)
        return true            // not reached; the compiler wants it
    }
}
