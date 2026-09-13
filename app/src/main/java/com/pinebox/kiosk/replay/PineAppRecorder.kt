package com.pinebox.kiosk.replay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * PINE APP RECORDER - the terminal records itself, as a service.
 *
 * "The tablets should just boot up and just always be capturing. Capturing is
 *  just one of the system tasks that's just running in the background that
 *  the Pine box is just using as one of the services."
 *
 * WHY THIS EXISTS AT ALL, given the ring already worked: it was driven by the
 * ACTIVITY. MainActivity.onResume started it and - measured - NOTHING ever
 * stopped it, because the only call site passed `true`. That had two
 * consequences, one of them silent:
 *
 *   the history was never written to disk, because the write happens when
 *   recording stops, and recording never stopped. The cache was dead code.
 *
 *   and the recorder's lifetime was an activity's lifetime, which is the
 *   wrong shape for something described as a system task. An activity is
 *   destroyed and recreated by things as ordinary as a wallpaper change -
 *   #1296 measured that happening seven times in thirty-three minutes.
 *
 * A foreground service is the honest shape: it starts at boot, it is restarted
 * by the system if it dies, and it outlives every activity in the app.
 *
 * IT STILL STOPS THE ENCODER WHEN THE SCREEN GOES DARK, and that is not a
 * contradiction of "always capturing" - it is what protects it. A mirrored
 * VirtualDisplay whose panel is off keeps handing the encoder the same frozen
 * frame, and KEY_REPEAT_PREVIOUS_FRAME_AFTER dutifully re-encodes it twelve
 * times a second. With a keyframe every second that is roughly 20 kB/s of
 * nothing, which fills the ring in about twelve minutes and pushes out every
 * real thing that happened before the tablet was put down. Left alone
 * overnight it would guarantee that the history is worthless exactly when
 * somebody picks the tablet up to ask what happened.
 *
 * So: the SERVICE is always on duty, the ENCODER follows the panel, and the
 * moment the screen goes dark the history is written to disk - which is the
 * moment it stops growing and starts being worth keeping.
 */
class PineAppRecorder : Service() {

    private var replay: ScreenReplay? = null
    private var eyes: BroadcastReceiver? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        /* The one instance the bridge also reads - see PineApp.replay. Two
         * recorders would mean two encoders and two rings, and the desktop
         * would pull from whichever it happened to reach. */
        replay = (applicationContext as? com.pinebox.kiosk.PineApp)?.replay

        startForeground(NOTE_ID, note(),
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0)

        /* THE PANEL, WATCHED HERE RATHER THAN IN THE ACTIVITY.
         *
         * SCREEN_ON and SCREEN_OFF are protected broadcasts: a manifest
         * receiver is not allowed to take them, they need a live process.
         * A foreground service is exactly that, and unlike an activity it is
         * still one when the activity has been destroyed. */
        val watch = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                when (intent.action) {
                    Intent.ACTION_SCREEN_ON -> wake()
                    Intent.ACTION_SCREEN_OFF -> rest()
                }
            }
        }
        registerReceiver(watch, IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_SCREEN_OFF)
        })
        eyes = watch

        /* LAST RUN'S HISTORY, TAKEN IN BEFORE ANYTHING ELSE.
         *
         * Not left to start(): that only runs when the panel is on, so a
         * terminal booting with a dark screen would hold nothing while a
         * perfectly good history sat on disk beside it. Priming costs no
         * encoder and is what makes "pull from it at any time" true. */
        replay?.prime()

        /* Catch up with whatever the screen is doing right now rather than
         * waiting for it to change - a service started at boot would
         * otherwise record nothing until somebody pressed the power key. */
        val power = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
        if (power.isInteractive) wake() else rest()

        Log.i(TAG, "Pine App Recorder on duty")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        /* STICKY: if the system reclaims this, it is brought back. A
         * recorder that stays dead after one low-memory moment is not a
         * service, it is a suggestion. */
        return START_STICKY
    }

    private fun wake() {
        val why = replay?.start()
        if (why != null) Log.w(TAG, "recorder would not start: " + why)
    }

    /**
     * Stop the encoder and put the history on disk.
     *
     * The ring itself is NOT cleared - see ScreenReplay.stop - so the last
     * minutes before the tablet was put down are still in memory when it
     * wakes, and now also on disk if the process does not survive.
     */
    private fun rest() {
        replay?.stop()
    }

    override fun onDestroy() {
        eyes?.let { try { unregisterReceiver(it) } catch (err: Exception) { /* gone */ } }
        eyes = null
        /* One last write. A service being destroyed is exactly the case the
         * cache exists for. */
        try { replay?.flush() } catch (err: Exception) { /* nothing to do */ }
        super.onDestroy()
    }

    private fun note(): Notification {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            /* IMPORTANCE_MIN: this is a terminal in a studio, not a phone.
             * The notification exists because Android requires one, and it
             * should never make a sound or push anything off the screen. */
            manager.createNotificationChannel(NotificationChannel(
                CHANNEL, "Pine App Recorder", NotificationManager.IMPORTANCE_MIN).apply {
                description = "Keeps the rolling recording of this terminal's screen."
                setShowBadge(false)
            })
        }
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Pine App Recorder")
            .setContentText("Keeping the last few minutes of this screen")
            .setSmallIcon(android.R.drawable.presence_video_online)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "PineRecorder"
        private const val CHANNEL = "pine-recorder"
        private const val NOTE_ID = 4301

        /** Start it, from boot or from the app. Safe to call repeatedly. */
        fun begin(context: Context) {
            val go = Intent(context, PineAppRecorder::class.java)
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(go)
                } else {
                    context.startService(go)
                }
            } catch (err: Exception) {
                /* A background start can be refused; the activity's own call
                 * covers that case the moment a view is on the glass. */
                Log.w(TAG, "recorder would not begin: " + err.message)
            }
        }
    }
}
