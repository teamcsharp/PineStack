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

        /* AND THE CAMERA'S DOOR, STANDING AND READY - THE DOOR, NOT THE
         * SERVICE. THIS LINE IS WHY THE RADIO WAS SILENT FOR THIRTY MINUTES
         * AFTER EVERY POWER CUT. (#1182T)
         *
         * "I'm able to grab and connect to the webcam through the Pinebox app
         *  no matter what whenever I want just through the service."
         *
         * That ask is still met, and by exactly the same two properties as
         * before: the socket is answered from the moment the tablet boots, and
         * the LENS is only opened when something actually connects to it. What
         * changed is WHICH of those two things is stood up here.
         *
         * It used to be PineCameraService.begin, and that service's onCreate
         * calls startForeground with foreground-service type `camera`. This
         * receiver is a BACKGROUND context, and Android 14 with targetSdk 34
         * refuses a camera-type foreground service started from the
         * background - CAMERA is a foreground-only permission, so it is the
         * "eligible state" half that fails, not the grant. Measured on the
         * tablet on 15 Sep 2026:
         *
         *   FATAL EXCEPTION: main
         *   java.lang.RuntimeException: Unable to create service
         *     com.pinebox.kiosk.camera.PineCameraService:
         *   java.lang.SecurityException: Starting FGS with type camera ...
         *     targetSDK=34 requires permissions:
         *     all of [FOREGROUND_SERVICE_CAMERA] any of [CAMERA, SYSTEM_CAMERA]
         *     and the app must be in the eligible state/exemptions
         *
         * Uncaught, so it took the process with it. It fired twice in three
         * seconds (pids 2603 and 3182) and ActivityManager then scheduled the
         * restart 1,800,000 ms later. Thirty minutes of dead air, on every
         * boot, while OomAdjuster logged "Not killing cached processes"
         * throughout - so not memory; and not a missing permission either,
         * because both CAMERA and FOREGROUND_SERVICE_CAMERA are granted and
         * both are in our manifest. Purely the background start. Launching
         * MainActivity by hand recovered it immediately and cleanly, which is
         * the proof: from the foreground the same call is legal.
         *
         * A LocalServerSocket needs none of that. It costs one blocked thread,
         * no notification, no service type and no permission at all, so it can
         * be opened from here with nothing for the platform to refuse - and
         * the foreground service is asked for at the moment a reader actually
         * knocks, which is when the lens was going to be opened anyway. See
         * PineCameraDoor. */
        com.pinebox.kiosk.camera.PineCameraDoor.open(context)

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
