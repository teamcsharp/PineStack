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
import android.net.LocalServerSocket
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

    private var server: LocalServerSocket? = null
    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private var thread: HandlerThread? = null
    private var hand: Handler? = null

    @Volatile private var facing = REAR
    @Volatile private var going = false
    @Volatile private var watchers = 0
    @Volatile private var frames = 0
    @Volatile private var lastError: String = ""

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTE_ID, note(),
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA else 0)
        going = true
        listen()
        Log.i(TAG, "camera service on duty")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val want = intent?.getStringExtra(EXTRA_FACING)
        if (want != null && want != facing) {
            facing = if (want == FRONT) FRONT else REAR
            /* Reopen on the other lens if anyone is already watching. */
            if (watchers > 0) { shutCamera(); openCamera() }
        }
        return START_STICKY
    }

    /* ---------------------------------------------------------- the door */

    private fun listen() {
        thread {
            try {
                val door = LocalServerSocket(SOCKET)
                server = door
                Log.i(TAG, "listening on localabstract:" + SOCKET)
                while (going) {
                    val client = try { door.accept() } catch (err: Exception) { null }
                        ?: break
                    /* One watcher at a time is the honest shape: a second
                     * desktop would be a second reader of one camera, and
                     * the frames are the same frames. */
                    thread { serve(client) }
                }
            } catch (err: Exception) {
                lastError = err.message ?: "the socket would not open"
                Log.w(TAG, "socket: " + lastError)
            }
        }
    }

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
            if (watchers <= 0) { watchers = 0; shutCamera() }
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
        going = false
        shutCamera()
        try { server?.close() } catch (err: Exception) { /* gone */ }
        server = null
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
        private const val TAG = "PineCameraSvc"
        private const val CHANNEL = "pine-camera"
        private const val NOTE_ID = 4302

        /** Where the desktop forwards to. Abstract, so no file, no cleanup. */
        const val SOCKET = "pine_camera"
        const val EXTRA_FACING = "facing"
        const val REAR = "rear"
        const val FRONT = "front"

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
