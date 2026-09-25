package com.pinebox.kiosk.camera

import android.content.Context
import android.net.LocalServerSocket
import android.net.LocalSocket
import android.util.Log
import java.util.concurrent.LinkedBlockingQueue
import kotlin.concurrent.thread

/**
 * #1182T - THE CAMERA'S DOOR, WITH NO SERVICE BEHIND IT UNTIL SOMEBODY KNOCKS.
 *
 * THE THING THIS FIXES, MEASURED ON THE TABLET BY THE AUTOBROWSE PORT ON
 * 15 Sep 2026 and confirmed line by line against our own source:
 *
 *     FATAL EXCEPTION: main
 *     java.lang.RuntimeException: Unable to create service
 *       com.pinebox.kiosk.camera.PineCameraService:
 *     java.lang.SecurityException: Starting FGS with type camera ... targetSDK=34
 *       requires permissions: all of [FOREGROUND_SERVICE_CAMERA]
 *       any of [CAMERA, SYSTEM_CAMERA]
 *       and the app must be in the eligible state/exemptions
 *       at com.pinebox.kiosk.camera.PineCameraService.onCreate(PineCameraService.kt:100)
 *
 * It fired twice in three seconds on that boot (pids 2603 and 3182) and
 * ActivityManager then scheduled the restart 1,800,000 ms - THIRTY MINUTES -
 * later. The radio was silent for the whole window, on every boot. It is not
 * a low-memory kill (OomAdjuster logged "Not killing cached processes"
 * throughout) and it is not a missing permission: both CAMERA and
 * FOREGROUND_SERVICE_CAMERA are granted, and both are in our manifest. It is
 * purely the BACKGROUND START. Launching MainActivity by hand recovered it
 * immediately, which is the proof: from the foreground the same call is legal.
 *
 * WHY THE DOOR MOVED OUT OF THE SERVICE, rather than the start just being
 * wrapped. PineCameraService's own note says what the design is:
 *
 *   "IT HOLDS THE CAMERA ONLY WHILE SOMEONE IS WATCHING... No client on the
 *    socket, no capture session."
 *
 * and the operator's ask behind it:
 *
 *   "I'm able to grab and connect to the webcam through the Pinebox app no
 *    matter what whenever I want just through the service."
 *
 * Both of those are about the SOCKET being answered, not about a foreground
 * service standing at boot. A LocalServerSocket costs one blocked thread and
 * no notification, no camera type and no permission at all - so the door can
 * be opened from BOOT_COMPLETED with nothing to refuse. The foreground
 * service is started only when a reader actually connects, which is the
 * moment the lens is going to be opened anyway and, in practice, a moment
 * when the kiosk is the thing on the glass.
 *
 * So after this: "always available" is still true (the socket is answered
 * from boot), "not holding the camera" is still true (the lens opens on the
 * first watcher, exactly as before), and a refusal from the foreground
 * service manager can no longer be a refusal to boot the radio.
 */
object PineCameraDoor {

    private const val TAG = "PineCameraDoor"

    @Volatile private var open = false
    @Volatile private var server: LocalServerSocket? = null

    /**
     * Readers that have knocked and are waiting for the service to exist.
     *
     * A queue rather than a field because two desktops can knock in the same
     * second while the service is still being created, and a field would
     * quietly drop one of them onto the floor with its socket never closed.
     */
    internal val waiting = LinkedBlockingQueue<LocalSocket>()

    /**
     * Answer the socket. Idempotent, cheap, and safe from any context -
     * including a BOOT_COMPLETED receiver, which is the whole point.
     */
    @Synchronized
    fun open(context: Context) {
        if (open) return
        open = true
        val app = context.applicationContext
        thread(name = "pine-camera-door", isDaemon = true) {
            try {
                val door = LocalServerSocket(PineCameraService.SOCKET)
                server = door
                Log.i(TAG, "listening on localabstract:" + PineCameraService.SOCKET
                    + " - the lens stays shut until somebody connects")
                while (open) {
                    val client = try { door.accept() } catch (err: Exception) { null } ?: break
                    /* A reader is here, so NOW the foreground service is
                     * worth asking for. Handed over rather than served from
                     * this thread: the capture session, the dials and the
                     * frame pump all live on the service, and two owners of
                     * one camera is how a shared device stops being shared. */
                    waiting.add(client)
                    /* Handed to the service if one is standing, AND a service
                     * asked for if the queue is still not empty afterwards.
                     * Both halves matter. A service that is part-way through
                     * onDestroy has already set `going` false and will drain
                     * nothing, so handing to it alone can leave a reader in the
                     * queue with nobody coming - which on the desk is a camera
                     * window that stays black for ever. begin() against a
                     * service that is already running is one onStartCommand
                     * and costs nothing. */
                    PineCameraService.live?.takeWaiting()
                    if (waiting.isNotEmpty()) PineCameraService.begin(app, null)
                }
            } catch (err: Exception) {
                /* The commonest cause is a second process still holding the
                 * abstract name after a force-stop. It is not fatal and it
                 * must never be: this runs on the boot path. */
                Log.w(TAG, "the camera door would not open: " + (err.message ?: err.toString()))
            } finally {
                open = false
            }
        }
    }

    /** For a deliberate shutdown, and for a test that wants the name freed. */
    @Synchronized
    fun close() {
        open = false
        try { server?.close() } catch (err: Exception) { /* gone */ }
        server = null
        while (true) {
            val left = waiting.poll() ?: break
            try { left.close() } catch (err: Exception) { /* gone */ }
        }
    }

    /** Tell a waiting reader, plainly, that the lens could not be opened. */
    internal fun turnAwayEveryone(why: String) {
        while (true) {
            val left = waiting.poll() ?: break
            Log.w(TAG, "turning a reader away: " + why)
            try { left.close() } catch (err: Exception) { /* gone */ }
        }
    }
}
