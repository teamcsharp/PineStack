package com.pinebox.kiosk.kiosk

import android.app.Activity
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.util.Log

/**
 * WHEN THE TABLET IS LOCKED, THE STATION IS STILL ON.
 *
 * "I want the Pine Box radio to have a splash screen on the lock screen
 * where it's showing me the status of the radio station, the script window,
 * and the media player... just from the lock screen of the tablet itself
 * whenever it's closed."
 *
 * WHAT IS ACTUALLY POSSIBLE HERE, measured rather than assumed. Replacing
 * Android's keyguard needs device-owner privilege, and this app does not
 * hold it - `dumpsys device_policy` reports `Device Owner Type: -1`. So the
 * keyguard stays, and the kiosk draws OVER it, which the manifest already
 * permits with `android:showWhenLocked` and `android:turnScreenOn`. The
 * practical difference for the operator: Android's own lock is still
 * underneath and a swipe still reaches the rest of the device. What he
 * gets is the station on the glass the moment the screen comes on, without
 * unlocking anything.
 *
 * THREE SIGNALS, AND THEY ARE NOT INTERCHANGEABLE:
 *
 *   SCREEN_OFF     the glass went dark. The lock screen is armed here, not
 *                  on the way back on, so it is already painted and
 *                  correct when the screen lights - not assembling itself
 *                  while the operator watches.
 *   SCREEN_ON      show it, but ONLY if the keyguard is actually locked.
 *                  A tablet with no lock set never locks, and covering an
 *                  unlocked screen with a lock screen would be a bug.
 *   USER_PRESENT   the operator unlocked. Put the terminal back exactly as
 *                  it was.
 *
 * The work itself is a page call, not a native layout: everything on that
 * screen already exists in the view bundle (assets/pine-views/lock.js), and
 * a second native account of the same things is the one that drifts.
 */
class LockWatch(
    private val activity: Activity,
    /** Run JavaScript in the terminal's one WebView, with the answer. */
    private val runScript: (String, (String) -> Unit) -> Unit,
    /** Post work back onto the WebView's thread after a delay. */
    private val later: (Long, () -> Unit) -> Unit,
) {

    private val keyguard: KeyguardManager? =
        activity.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager

    private var registered = false

    private val watcher = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                Intent.ACTION_SCREEN_OFF -> {
                    /* Built and painted in the dark, so the first frame the
                     * operator sees is the finished thing. */
                    show("screen off")
                }
                Intent.ACTION_SCREEN_ON -> {
                    if (locked()) show("screen on, locked") else hide("screen on, not locked")
                }
                Intent.ACTION_USER_PRESENT -> hide("unlocked")
            }
        }
    }

    fun locked(): Boolean = keyguard?.isKeyguardLocked ?: false

    fun start() {
        if (registered) return
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_USER_PRESENT)
        }
        /* These three are protected broadcasts and CANNOT be received from
         * the manifest - they have to be registered at runtime, by a
         * process that is alive. That is exactly what this kiosk is. */
        activity.registerReceiver(watcher, filter)
        registered = true
        Log.i(TAG, "lock watch on; keyguard is " +
            (if (locked()) "locked" else "open"))
    }

    fun stop() {
        if (!registered) return
        try { activity.unregisterReceiver(watcher) } catch (err: Exception) {
            Log.w(TAG, "lock watch was already gone", err)
        }
        registered = false
    }

    /** Called when the activity resumes: catch up with reality, because the
     *  screen may have gone off and on again while this was not listening. */
    fun settle() {
        if (locked()) show("resumed while locked") else hide("resumed unlocked")
    }

    /**
     * ASK THE PAGE, AND WAIT FOR IT TO EXIST.
     *
     * The view bundle is evaluated at onPageFinished, and on a cold start
     * that is AFTER this class first wants to raise the lock screen.
     * Measured: the first `settle()` at 1.2 s logged "lock screen up" and
     * nothing appeared, because `window.PineLock` was still undefined and
     * `PineLock && PineLock.show()` is a perfectly quiet way to do nothing.
     * Six seconds later the global was there.
     *
     * So the call is retried until the page answers `true`, and gives up
     * after TRIES so a page that will never load cannot leave a timer
     * running for the life of the kiosk.
     */
    private fun ask(wanted: Boolean, why: String, attempt: Int = 0) {
        val verb = if (wanted) "show" else "hide"
        runScript(
            "(function(){ try {"
                + " if (!window.PineLock) return 'absent';"
                + " PineLock." + verb + "(); return 'done';"
                + " } catch (e) { return 'threw: ' + e.message; } })()"
        ) { answer ->
            val said = answer.trim().trim('"')
            when {
                said == "done" -> Log.i(TAG, "lock screen $verb ($why)")
                said == "absent" && attempt < TRIES -> later(RETRY_MS) {
                    ask(wanted, why, attempt + 1)
                }
                said == "absent" -> Log.w(
                    TAG, "gave up telling the page to $verb: the view bundle " +
                        "never loaded (" + why + ")")
                else -> Log.w(TAG, "lock $verb failed: $said")
            }
        }
    }

    private fun show(why: String) = ask(true, why)

    private fun hide(why: String) = ask(false, why)

    private companion object {
        const val TAG = "PineLock"
        /* Twelve tries at 900 ms covers a cold boot on this tablet, which
         * was measured reaching the bundle at about six seconds. */
        const val TRIES = 12
        const val RETRY_MS = 900L
    }
}
