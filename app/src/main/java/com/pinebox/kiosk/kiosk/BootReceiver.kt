package com.pinebox.kiosk.kiosk

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.pinebox.kiosk.MainActivity

/**
 * Bring the terminal up after a power cut.
 *
 * BELT AND BRACES, not the primary road. Since Android 10 a background
 * process may not start an activity, and BOOT_COMPLETED is exactly that
 * context; the launch below succeeds when the app is device owner or the
 * default HOME and is quietly dropped otherwise.
 *
 * The mechanism that actually works is the HOME + DEFAULT intent filter in
 * the manifest: the system starts the home activity on every boot, with no
 * receiver involved. This receiver exists for the window BEFORE
 * `dpm set-device-owner` has been run, when the tablet still has its stock
 * launcher and would otherwise come up on a home screen nobody is there to
 * tap.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action != Intent.ACTION_BOOT_COMPLETED &&
            !action.endsWith("QUICKBOOT_POWERON")
        ) {
            return
        }

        /* Provisioning may have happened while the tablet was off, or the
         * global settings may have been reset by an OTA. Re-apply first, so
         * the activity finds the policies already in place. */
        KioskController.applyOwnerPolicies(context)

        /* THE RECORDER FIRST, and before the activity. It is a background
         * system task rather than something the screen does, so it must not
         * wait for a window - and starting it here means the terminal is
         * capturing from the moment it boots, which is the whole ask. */
        com.pinebox.kiosk.replay.PineAppRecorder.begin(context)

        /* AND THE CAMERA, STANDING AND READY.
         *
         * "I'm able to grab and connect to the webcam through the Pinebox app
         *  no matter what whenever I want just through the service."
         *
         * It costs nothing to leave running: the socket listens, and the LENS
         * is only opened when something actually connects to it - see
         * PineCameraService. So "always available" and "not holding the
         * camera" are both true at once, which is the only way a shared
         * device can be left on duty. */
        com.pinebox.kiosk.camera.PineCameraService.begin(context, null)

        try {
            val launch = Intent(context, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
                putExtra(MainActivity.EXTRA_FROM_BOOT, true)
            }
            context.startActivity(launch)
        } catch (err: Exception) {
            Log.i(TAG, "boot launch refused; relying on the HOME filter", err)
        }
    }

    companion object {
        private const val TAG = "PineBoot"
    }
}
