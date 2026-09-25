package com.pinebox.kiosk.camera

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.net.LocalSocket
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Log
import java.io.OutputStream
import kotlin.concurrent.thread

/**
 * THE TABLET'S CAMERA, WITHOUT TAKING ITS SCREEN.
 *
 * "I want to stay inside of the Pine Box application and not change it over
 *  to being displaying a camera. I want to be in the Pine Box app. I just
 *  happen to want to be able to enable the camera... and use it for accessing
 *  the camera if I need to through the tablet."
 *
 * The first version of this put a camera preview ON the tablet's screen and
 * let the existing screen mirror carry it here. That was cheap and it was
 * wrong: the terminal is a radio station somebody is watching, and looking
 * through its camera must not take it off the air.
 *
 * SO THERE IS NO PREVIEW AND NO ACTIVITY. Camera2 will render into an
 * ImageReader instead of a Surface on screen, and an ImageReader can be
 * asked for JPEG directly - so the frames arrive already compressed, with no
 * encoder, no muxer and no colour conversion of our own. The station keeps
 * running, the kiosk keeps drawing, and the only thing that changes is that
 * a camera is open.
 *
 * EACH FRAME IS LENGTH-PREFIXED, AND THAT IS NOT FUSSINESS.
 *
 * The screen mirror's wire format is bare concatenated JPEGs, split on the far
 * end by scanning for the SOI and EOI markers, and it has worked for months.
 * It CANNOT carry these frames. An ImageReader's JPEG arrives with an EXIF
 * block, and Android's EXIF routinely embeds a THUMBNAIL - which is itself a
 * JPEG, so there is a second `ff d8 ... ff d9` pair inside the header of the
 * first. A marker scan stops at the thumbnail's end and hands over a
 * truncated file.
 *
 * Measured before this: 12,658 bytes ending correctly in ff d9, and every
 * frame refused by the decoder. ffmpeg's JPEGs carry no thumbnail, which is
 * exactly why the mirror never met this.
 *
 * So: four bytes of big-endian length, then that many bytes of JPEG. The far
 * end never has to guess where a frame ends.
 *
 * IT HOLDS THE CAMERA ONLY WHILE SOMEONE IS WATCHING. A camera is one shared
 * device; a service that keeps it open with no reader is a service nothing
 * else on the tablet can use a camera behind. No client on the socket, no
 * capture session.
 */
class PineCameraService : Service() {

    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private var thread: HandlerThread? = null
    private var hand: Handler? = null

    /* THE DIALS, held across a lens change on purpose: switching to the
     * front camera to check something and losing a carefully set exposure is
     * worse than either camera.
     *
     * #1182T MOVED THEM TO THE COMPANION, and that is not tidying. They used
     * to be instance fields and that was safe because the service stood from
     * boot to shutdown; it does not any more - it now stands down when the
     * last reader disconnects, so instance fields would quietly reset every
     * exposure the operator had set the moment they closed the window. The
     * dials belong to the CAMERA, which outlives any one look through it. */
    @Volatile private var going = false
    @Volatile private var watchers = 0
    @Volatile private var frames = 0
    @Volatile private var lastError: String = ""

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        live = this

        /* #1182T: THIS CALL USED TO BE BARE, AND IT SILENCED THE RADIO FOR
         * HALF AN HOUR ON EVERY BOOT.
         *
         * Measured on the tablet on 15 Sep 2026: started from BootReceiver,
         * which is a background context, Android 14 with targetSdk 34 refuses
         * a foreground service of type `camera` - CAMERA is a foreground-only
         * permission, so "the app must be in the eligible state" is the half
         * that fails, not the permission grant. Both CAMERA and
         * FOREGROUND_SERVICE_CAMERA are granted and are in our manifest; it is
         * purely the background start. The SecurityException came out of HERE,
         * uncaught, and took the whole process with it. It fired twice in
         * three seconds (pids 2603 and 3182) and ActivityManager then
         * scheduled the restart 1,800,000 ms later. Thirty minutes of silence,
         * every time the tablet was switched on. Not a low-memory kill -
         * OomAdjuster logged "Not killing cached processes" throughout.
         *
         * Two things changed. The door is no longer started from boot at all
         * (see PineCameraDoor), so this service is created when a reader has
         * actually knocked; and the refusal is now CAUGHT, because a decision
         * the foreground service manager is entitled to make must never again
         * be a decision to stop the broadcast.
         *
         * WHY stopSelf() ON A REFUSAL RATHER THAN CARRYING ON. We were started
         * with startForegroundService, and the platform holds us to a promise:
         * if startForeground never succeeds it throws
         * ForegroundServiceDidNotStartInTimeException into this process a few
         * seconds later - which would be the same process death under another
         * name. Stopping the service cancels that timer. The DOOR is
         * unaffected and stays listening, so the next knock - most likely with
         * the kiosk on the glass, where the call is legal - simply works. */
        val standing = runCatching {
            startForeground(NOTE_ID, note(),
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA else 0)
        }.onFailure { err ->
            lastError = "the foreground service was refused: " + (err.message ?: err.toString())
            Log.w(TAG, "#1182T " + lastError + " - standing down rather than taking "
                + "the terminal with it; the socket is still answered")
        }.isSuccess

        if (!standing) {
            PineCameraDoor.turnAwayEveryone(lastError)
            live = null
            stopSelf()
            return
        }

        going = true
        /* #1182T: the socket belongs to PineCameraDoor now and lives in the
         * app process rather than here. Whoever is already waiting on it
         * knocked before this service existed, which is why it exists. */
        takeWaiting()
        Log.i(TAG, "camera service on duty")
    }

    /**
     * #1182T: pick up every reader the door has accepted.
     *
     * Called from onCreate, and from the door when the service is already
     * standing. It drains a queue rather than taking one socket because two
     * desktops can knock inside the same second and the second one must not
     * be dropped on the floor with its socket never closed.
     */
    internal fun takeWaiting() {
        while (going) {
            val client = PineCameraDoor.waiting.poll() ?: break
            thread { serve(client) }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        /* #1182T: and pick up anyone who knocked while we were standing up or
         * shutting down. The door calls begin() whenever its queue is still
         * not empty after a hand-over, and this is where that arrives. */
        takeWaiting()
        val want = intent?.getStringExtra(EXTRA_FACING)
        if (want != null && want != facing) {
            facing = if (want == FRONT) FRONT else REAR
            /* Reopen on the other lens if anyone is already watching. */
            if (watchers > 0) { shutCamera(); openCamera() }
        }
        return START_STICKY
    }

    /* ---------------------------------------------------------- the door */

    /* #1182T: THE DOOR IS NOT HERE ANY MORE. It used to be `listen()`, a
     * LocalServerSocket accept loop started from onCreate, and having it here
     * is what forced a camera-type foreground service to exist from boot -
     * which is the call Android 14 refused, and the refusal that killed the
     * radio for thirty minutes on every power-on. It now lives in
     * PineCameraDoor, in the app process, where it costs one blocked thread,
     * no notification, no foreground service type and no permission at all.
     * See PineCameraDoor for the measurements. */

    private fun serve(client: LocalSocket) {
        watchers += 1
        if (watchers == 1) openCamera()
        val out = try { client.outputStream } catch (err: Exception) { null }
        try {
            while (going && out != null) {
                val jpeg = nextFrame() ?: continue
                /* Four bytes of big-endian length, then the frame. See the
                 * note at the top on why markers cannot be trusted here. */
                val size = jpeg.size
                out.write(byteArrayOf(
                    ((size ushr 24) and 0xff).toByte(),
                    ((size ushr 16) and 0xff).toByte(),
                    ((size ushr 8) and 0xff).toByte(),
                    (size and 0xff).toByte()))
                out.write(jpeg)
                out.flush()
            }
        } catch (err: Exception) {
            /* A watcher closing its window is the normal way out of here. */
        } finally {
            try { client.close() } catch (err: Exception) { /* gone */ }
            watchers -= 1
            if (watchers <= 0) {
                watchers = 0
                shutCamera()
                /* #1182T: AND STAND DOWN ALTOGETHER, which is new.
                 *
                 * Before, this service stood from boot to shutdown because it
                 * was also the socket, so stopping it would have stopped the
                 * door. The door is PineCameraDoor's now and outlives us, so
                 * nothing is lost by going away: the desktop can still connect
                 * whenever it likes and the service comes back for it. What is
                 * gained is that the tablet is not sitting in a camera-type
                 * foreground service, with the notification that goes with it,
                 * at every moment of a day when nobody is looking through the
                 * lens. */
                if (PineCameraDoor.waiting.isEmpty()) stopSelf()
            }
        }
    }

    /* THE NEWEST FRAME, or nothing. A queue would add latency for no gain:
     * a viewer that has fallen behind wants the picture NOW, not the one it
     * missed. */
    @Volatile private var held: ByteArray? = null

    private fun nextFrame(): ByteArray? {
        val now = held
        if (now == null) {
            Thread.sleep(15)
            return null
        }
        held = null
        return now
    }

    /* -------------------------------------------------------- the camera */

    private fun openCamera() {
        if (checkSelfPermission(Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            lastError = "the camera permission has not been granted"
            Log.w(TAG, lastError)
            return
        }
        val worker = HandlerThread("pine-camera-svc").also { it.start() }
        thread = worker
        hand = Handler(worker.looper)
        try {
            val manager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val id = idFor(manager, facing) ?: run {
                lastError = "this tablet reports no cameras"
                return
            }
            val size = bestSize(manager, id)
            val take = ImageReader.newInstance(size.first, size.second,
                ImageFormat.JPEG, 2)
            take.setOnImageAvailableListener({ r ->
                try {
                    val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
                    val buffer = image.planes[0].buffer
                    val bytes = ByteArray(buffer.remaining())
                    buffer.get(bytes)
                    image.close()
                    held = bytes
                    frames += 1
                } catch (err: Exception) {
                    lastError = err.message ?: "a frame could not be read"
                }
            }, hand)
            reader = take

            manager.openCamera(id, object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    device = camera
                    try {
                        val ask = camera.createCaptureRequest(
                            CameraDevice.TEMPLATE_PREVIEW)
                        ask.addTarget(take.surface)
                        /* Auto everything: this is a look through a lens, not
                         * a photograph, and a fixed exposure in a dim studio
                         * is a black rectangle. */
                        ask.set(CaptureRequest.CONTROL_MODE,
                            CaptureRequest.CONTROL_MODE_AUTO)
                        dial(ask, manager, id)
                        @Suppress("DEPRECATION")
                        camera.createCaptureSession(listOf(take.surface),
                            object : CameraCaptureSession.StateCallback() {
                                override fun onConfigured(made: CameraCaptureSession) {
                                    session = made
                                    made.setRepeatingRequest(ask.build(), null, hand)
                                    Log.i(TAG, "camera " + id + " (" + facing
                                        + ") at " + size.first + "x" + size.second)
                                }
                                override fun onConfigureFailed(made: CameraCaptureSession) {
                                    lastError = "the capture session would not configure"
                                }
                            }, hand)
                    } catch (err: Exception) {
                        lastError = err.message ?: "the capture would not start"
                    }
                }
                override fun onDisconnected(camera: CameraDevice) { shutCamera() }
                override fun onError(camera: CameraDevice, why: Int) {
                    lastError = "the camera reported error " + why
                    shutCamera()
                }
            }, hand)
        } catch (err: Exception) {
            lastError = err.message ?: "the camera would not open"
            Log.w(TAG, lastError)
        }
    }

    /**
     * Put the dials on a request.
     *
     * Clamped to what CameraCharacteristics reports, because a value outside
     * the sensor's range is not rejected - it is ignored, which looks exactly
     * like a control that does nothing.
     */
    private fun dial(ask: CaptureRequest.Builder, manager: CameraManager, id: String) {
        try {
            val about = manager.getCameraCharacteristics(id)
            if (auto) {
                ask.set(CaptureRequest.CONTROL_AE_MODE,
                    CaptureRequest.CONTROL_AE_MODE_ON)
                /* Exposure compensation is an instruction TO the metering,
                 * so it only means anything while AE is on. */
                val range = about.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_RANGE)
                if (range != null) {
                    ask.set(CaptureRequest.CONTROL_AE_EXPOSURE_COMPENSATION,
                        ev.coerceIn(range.lower, range.upper))
                }
                /* LOW LIGHT: no algorithm adds photons. Letting the sensor
                 * integrate for longer does, and it costs frame rate - so it
                 * is a switch, not a secret. */
                if (slowShutter) {
                    val fps = about.get(
                        CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
                    val slowest = fps?.minByOrNull { it.lower }
                    if (slowest != null) {
                        ask.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, slowest)
                    }
                }
            } else {
                ask.set(CaptureRequest.CONTROL_AE_MODE,
                    CaptureRequest.CONTROL_AE_MODE_OFF)
                val shutterRange = about.get(
                    CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
                if (shutterNs > 0 && shutterRange != null) {
                    ask.set(CaptureRequest.SENSOR_EXPOSURE_TIME,
                        shutterNs.coerceIn(shutterRange.lower, shutterRange.upper))
                }
                val isoRange = about.get(
                    CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
                if (iso > 0 && isoRange != null) {
                    ask.set(CaptureRequest.SENSOR_SENSITIVITY,
                        iso.coerceIn(isoRange.lower, isoRange.upper))
                }
                /* A manual exposure with no frame duration runs at whatever
                 * the last auto value was, which can be SHORTER than the
                 * exposure and quietly clamps it. */
                if (shutterNs > 0) {
                    ask.set(CaptureRequest.SENSOR_FRAME_DURATION,
                        maxOf(shutterNs, 33333333L))
                }
            }
        } catch (err: Exception) {
            Log.w(TAG, "dials: " + err.message)
        }
    }

    /** What the sensor on this lens can actually be asked for. */
    fun range(): org.json.JSONObject {
        val out = org.json.JSONObject()
        try {
            val manager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val id = idFor(manager, facing) ?: return out
            val about = manager.getCameraCharacteristics(id)
            val shutter = about.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
            val sens = about.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
            val comp = about.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_RANGE)
            out.put("id", id).put("facing", facing)
            if (shutter != null) {
                out.put("shutterMinNs", shutter.lower).put("shutterMaxNs", shutter.upper)
            }
            if (sens != null) out.put("isoMin", sens.lower).put("isoMax", sens.upper)
            if (comp != null) out.put("evMin", comp.lower).put("evMax", comp.upper)
            out.put("auto", auto).put("shutterNs", shutterNs).put("iso", iso)
                .put("ev", ev).put("slowShutter", slowShutter)
        } catch (err: Exception) {
            out.put("why", err.message ?: "the sensor would not answer")
        }
        return out
    }

    /** Move the dials and re-apply them. */
    fun tune(want: org.json.JSONObject) {
        if (want.has("auto")) auto = want.optBoolean("auto", true)
        if (want.has("shutterNs")) shutterNs = want.optLong("shutterNs", 0L)
        if (want.has("iso")) iso = want.optInt("iso", 0)
        if (want.has("ev")) ev = want.optInt("ev", 0)
        if (want.has("slowShutter")) slowShutter = want.optBoolean("slowShutter", false)
        /* Rebuilding the session is the simple way to re-apply, and it is
         * cheap: the socket stays and the watcher stays. */
        if (watchers > 0) { shutCamera(); openCamera() }
    }

    /** The id the device reports for a facing, not a guessed 0 or 1. */
    private fun idFor(manager: CameraManager, want: String): String? {
        val wanted = if (want == FRONT) CameraCharacteristics.LENS_FACING_FRONT
                     else CameraCharacteristics.LENS_FACING_BACK
        for (id in manager.cameraIdList) {
            if (manager.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.LENS_FACING) == wanted) return id
        }
        return manager.cameraIdList.firstOrNull()
    }

    /**
     * A JPEG size near 720p.
     *
     * Not the largest the sensor offers: this is a picture crossing adb to
     * be looked at in a window, and a 12-megapixel frame would cost the
     * tablet and the wire for detail nobody is going to see.
     */
    private fun bestSize(manager: CameraManager, id: String): Pair<Int, Int> {
        return try {
            val map = manager.getCameraCharacteristics(id).get(
                CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val sizes = map?.getOutputSizes(ImageFormat.JPEG) ?: return 1280 to 720
            val want = 1280 * 720
            var best = sizes.first()
            for (size in sizes) {
                val mine = Math.abs(size.width * size.height - want)
                val theirs = Math.abs(best.width * best.height - want)
                if (mine < theirs) best = size
            }
            best.width to best.height
        } catch (err: Exception) {
            1280 to 720
        }
    }

    private fun shutCamera() {
        try { session?.close() } catch (err: Exception) { /* going */ }
        try { device?.close() } catch (err: Exception) { /* going */ }
        try { reader?.close() } catch (err: Exception) { /* going */ }
        session = null
        device = null
        reader = null
        held = null
        try { thread?.quitSafely() } catch (err: Exception) { /* going */ }
        thread = null
        hand = null
    }

    override fun onDestroy() {
        if (live === this) live = null
        going = false
        shutCamera()
        /* #1182T: the socket is NOT closed here. It belongs to
         * PineCameraDoor and must outlive this service - that is the whole
         * point of the split. Closing it here would mean the desktop could
         * only ever connect once. */
        super.onDestroy()
    }

    private fun note(): Notification {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(NotificationChannel(
                CHANNEL, "Pine Box camera", NotificationManager.IMPORTANCE_MIN).apply {
                description = "Lets the Pine Box application look through this tablet's camera."
                setShowBadge(false)
            })
        }
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Pine Box camera")
            .setContentText("Available to the Pine Box application")
            .setSmallIcon(android.R.drawable.presence_video_online)
            .setOngoing(true)
            .build()
    }

    companion object {
        /* THE RUNNING ONE, so the bridge can turn its dials. A bound
         * service would be the tidy answer and would mean a connection to
         * manage for a handful of setters. */
        @Volatile
        var live: PineCameraService? = null
            private set

        private const val TAG = "PineCameraSvc"
        private const val CHANNEL = "pine-camera"
        private const val NOTE_ID = 4302

        /** Where the desktop forwards to. Abstract, so no file, no cleanup. */
        const val SOCKET = "pine_camera"
        const val EXTRA_FACING = "facing"
        const val REAR = "rear"
        const val FRONT = "front"

        /* #1182T: THE DIALS AND THE LENS, HELD ABOVE THE SERVICE'S LIFETIME.
         * See the note where these used to be declared, at the top of the
         * class - the service now stands down between viewings, and a dial
         * that resets when the operator closes a window is a dial nobody can
         * set. */
        @Volatile internal var auto = true
        @Volatile internal var shutterNs = 0L
        @Volatile internal var iso = 0
        @Volatile internal var ev = 0
        @Volatile internal var slowShutter = false
        @Volatile internal var facing = REAR

        /**
         * Stand the service up.
         *
         * #1182T: THIS IS NO LONGER CALLED FROM BOOT, AND MUST NOT BE. It is
         * called by PineCameraDoor when a reader has actually connected, and
         * by nothing else. A camera-type foreground service started from a
         * background context is refused on Android 14 with targetSdk 34, and
         * the refusal killed the process - see onCreate for the measurement.
         * The catch below covers the call site; onCreate covers the refusal
         * that arrives later, inside the service.
         */
        fun begin(context: Context, want: String?) {
            val go = Intent(context, PineCameraService::class.java)
            go.putExtra(EXTRA_FACING, if (want == FRONT) FRONT else REAR)
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(go)
                } else {
                    context.startService(go)
                }
            } catch (err: Exception) {
                Log.w(TAG, "camera service would not begin: " + err.message)
            }
        }

        /**
         * Stop the service outright.
         *
         * NOT what closing a viewer should do. The service is meant to stand
         * so the desktop can attach whenever it likes, and the LENS is
         * already released the moment the last reader disconnects - so a
         * window closing needs to do nothing at all. This exists for a
         * deliberate shutdown, and for a test that wants the socket gone.
         */
        fun end(context: Context) {
            try {
                context.stopService(Intent(context, PineCameraService::class.java))
            } catch (err: Exception) { /* already gone */ }
        }
    }
}
