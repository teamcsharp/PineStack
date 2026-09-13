package com.pinebox.kiosk.kiosk

import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.util.Log
import android.view.View
import android.view.WindowManager
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.pinebox.kiosk.MainActivity

/**
 * Everything that turns an activity into a terminal.
 *
 * There are three separate mechanisms here and they do different jobs.
 * Losing track of which is which is how a "kiosk" ends up with a visible
 * navigation bar and a Recents button:
 *
 *   1. HOME  - declared in the manifest, made STICKY here by
 *              addPersistentPreferredActivity. Decides where Back-out-of-
 *              everything and every boot land.
 *   2. LOCK TASK - startLockTask(). Decides whether the user can leave at
 *              all. Without device owner this is only screen pinning: a
 *              toast, and Back+Recents held together lets them out.
 *   3. IMMERSIVE - decides whether the bars are drawn. Cosmetic, and it is
 *              the one that keeps needing to be re-applied, because the
 *              system restores the bars on every focus change.
 */
object KioskController {

    private const val TAG = "PineKiosk"

    fun dpm(context: Context): DevicePolicyManager =
        context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager

    fun isDeviceOwner(context: Context): Boolean =
        dpm(context).isDeviceOwnerApp(context.packageName)

    /**
     * The policies that only a device owner may set. Called on admin-enable
     * and again on every activity start, because provisioning can happen
     * after the app is already running.
     */
    fun applyOwnerPolicies(context: Context) {
        if (!isDeviceOwner(context)) return
        val policy = dpm(context)
        val admin = PineDeviceAdminReceiver.component(context)
        try {
            /* Only this package may be locked into. A second package here
             * would let a lock-task app launch another and strand the
             * terminal in it. */
            policy.setLockTaskPackages(admin, arrayOf(context.packageName))

            /* Make the manifest's HOME filter STICKY. Without this the
             * first press of Home after provisioning shows the usual
             * "which launcher?" chooser - on a wall-mounted tablet nobody
             * is standing at, that chooser is where the terminal stays. */
            val home = IntentFilter(Intent.ACTION_MAIN).apply {
                addCategory(Intent.CATEGORY_HOME)
                addCategory(Intent.CATEGORY_DEFAULT)
            }
            policy.addPersistentPreferredActivity(
                admin, home,
                ComponentName(context, MainActivity::class.java),
            )

            /* The status bar cannot be pulled down at all - notifications
             * and Quick Settings are a road off the terminal that immersive
             * mode alone does not close. */
            policy.setStatusBarDisabled(admin, true)

            /* Never sleep while plugged in. The terminal is a wall panel;
             * a black screen reads as a dead station. */
            policy.setGlobalSetting(
                admin,
                android.provider.Settings.Global.STAY_ON_WHILE_PLUGGED_IN,
                (BatteryPlugged.AC or BatteryPlugged.USB or BatteryPlugged.WIRELESS).toString(),
            )
        } catch (err: SecurityException) {
            // Device owner was revoked between the check and the call.
            Log.w(TAG, "owner policies refused", err)
        }
    }

    /** BatteryManager's plug constants, named rather than magic. */
    private object BatteryPlugged {
        const val AC = 1
        const val USB = 2
        const val WIRELESS = 4
    }

    /**
     * Enter lock task if we can.
     *
     * Device owner: locks silently and the user cannot leave. Not device
     * owner: this is screen pinning, the system shows its toast, and the
     * user can escape - which is the right behaviour for a tablet that has
     * not been provisioned yet, so it is attempted rather than skipped.
     */
    fun enterLockTask(activity: Activity) {
        try {
            val policy = dpm(activity)
            if (isDeviceOwner(activity) || policy.isLockTaskPermitted(activity.packageName)) {
                activity.startLockTask()
            } else {
                Log.i(TAG, "not device owner; running unpinned (see README: dpm set-device-owner)")
            }
        } catch (err: RuntimeException) {
            /* IllegalArgumentException (package not permitted),
             * IllegalStateException (activity not resumed) and
             * SecurityException all mean the same thing here: the terminal
             * runs unpinned. None of them may take the panel down with it. */
            Log.w(TAG, "lock task refused", err)
        }
    }

    fun exitLockTask(activity: Activity) {
        try {
            activity.stopLockTask()
        } catch (err: Exception) {
            Log.w(TAG, "could not leave lock task", err)
        }
    }

    /**
     * Screen on, bars gone, and gone again after every focus change.
     *
     * FLAG_KEEP_SCREEN_ON rather than a WAKE_LOCK: the flag is scoped to
     * the window, so it cannot outlive the activity and hold the tablet
     * awake forever if the process is killed oddly.
     */
    fun applyWindowFlags(activity: Activity) {
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED)

        /* Draw under the cutout. The M9 has none, but LineageOS reports a
         * cutout mode anyway and the default leaves a letterbox on some
         * builds. The LayoutParams must be READ, changed and WRITTEN BACK:
         * mutating window.attributes in place does not re-apply them. */
        val params = activity.window.attributes
        params.layoutInDisplayCutoutMode =
            WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        activity.window.attributes = params

        WindowCompat.setDecorFitsSystemWindows(activity.window, false)
        val controller = WindowInsetsControllerCompat(activity.window, activity.window.decorView)
        controller.hide(WindowInsetsCompat.Type.systemBars())
        /* BEHAVIOUR_SHOW_TRANSIENT_BARS_BY_SWIPE, not the default: with the
         * default the first swipe from an edge brings the bars back and
         * leaves them there. Transient means they fade again on their own,
         * so a stray touch does not permanently reveal the navigation bar. */
        controller.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
    }

    /**
     * Call from onWindowFocusChanged. The system restores the system bars
     * whenever the window loses and regains focus - a dialog, a toast, the
     * charger being plugged in - so immersive mode is not something set
     * once at startup.
     */
    fun reassertImmersive(activity: Activity, hasFocus: Boolean) {
        if (!hasFocus) return
        val controller = WindowInsetsControllerCompat(activity.window, activity.window.decorView)
        controller.hide(WindowInsetsCompat.Type.systemBars())
        activity.window.decorView.systemUiVisibility =
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
    }
}
