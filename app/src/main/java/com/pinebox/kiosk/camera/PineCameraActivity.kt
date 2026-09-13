package com.pinebox.kiosk.camera

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.view.Gravity
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/**
 * LOOKING THROUGH THE TABLET'S CAMERA.
 *
 * "Put an icon for a webcam that when clicked activates the webcam on the
 *  pine tab and allows me to see through the camera of the pine tablet."
 * "And on the display give me options to look through the front cam or the
 *  rear cam."
 *
 * THE PICTURE REACHES THE DESKTOP THROUGH THE MIRROR THAT ALREADY EXISTS.
 * This puts the camera on the tablet's SCREEN, and the desktop is already
 * able to watch that screen live, at a chosen detail, with zoom and pan -
 * see tablet-mirror.cjs. A second video pipeline from the camera to the
 * desktop would be a second encoder, a second socket, a second set of
 * reconnect rules and a second thing to go quietly grey, for a picture the
 * operator can already see.
 *
 * The honest cost, and it is a real one: while this is open the tablet's
 * screen is the camera rather than the station. Closing it puts the terminal
 * straight back, and the rolling recorder never stopped.
 *
 * CAMERA2 AND NOT CAMERAX, because CameraX is a dependency to fetch and this
 * tablet lives on a LAN with no internet - the same reason the icons and
 * three.js are vendored. Camera2 is in the framework and costs nothing to
 * reach.
 *
 * TWO CAMERAS, MEASURED: `dumpsys media.camera` reports two on this tablet,
 * one facing Back and one Front. The buttons are laid out from what the
 * device actually reports rather than from an assumption that ids 0 and 1
 * mean what they usually do.
 */
class PineCameraActivity : Activity() {

    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var thread: HandlerThread? = null
    private var hand: Handler? = null
    private var view: SurfaceView? = null
    private var said: TextView? = null
    private var facing: String = BACK

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        facing = intent?.getStringExtra(EXTRA_FACING) ?: BACK

        val root = FrameLayout(this)
        root.setBackgroundColor(Color.BLACK)

        val glass = SurfaceView(this)
        root.addView(glass, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT))
        view = glass

        /* THE CONTROLS ARE ON THE TABLET'S SCREEN because that is what the
         * desktop is looking at - a button only the tablet could press would
         * be no use to somebody watching from another room. The desktop can
         * reach them through the mirror's touch, or send the same switch
         * through the bridge. */
        val bar = LinearLayout(this)
        bar.orientation = LinearLayout.HORIZONTAL
        bar.setBackgroundColor(Color.argb(190, 8, 13, 18))
        bar.setPadding(18, 12, 18, 12)

        said = TextView(this).apply {
            setTextColor(Color.parseColor("#9fb3c2"))
            textSize = 15f
            text = "starting the camera"
        }
        bar.addView(said, LinearLayout.LayoutParams(0,
            LinearLayout.LayoutParams.WRAP_CONTENT, 1f))

        bar.addView(button("Rear") { swap(BACK) })
        bar.addView(button("Front") { swap(FRONT) })
        bar.addView(button("Close") { finish() })

        root.addView(bar, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM))

        setContentView(root)

        glass.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) = open()
            override fun surfaceChanged(h: SurfaceHolder, f: Int, w: Int, t: Int) {}
            override fun surfaceDestroyed(holder: SurfaceHolder) = shut()
        })
    }

    private fun button(words: String, go: () -> Unit): Button =
        Button(this).apply {
            text = words
            setOnClickListener { go() }
        }

    private fun swap(want: String) {
        if (facing == want) return
        facing = want
        shut()
        open()
    }

    /** The id the device reports for a facing, rather than a guessed 0 or 1. */
    private fun idFor(manager: CameraManager, want: String): String? {
        val wanted = if (want == FRONT) CameraCharacteristics.LENS_FACING_FRONT
                     else CameraCharacteristics.LENS_FACING_BACK
        for (id in manager.cameraIdList) {
            val about = manager.getCameraCharacteristics(id)
            if (about.get(CameraCharacteristics.LENS_FACING) == wanted) return id
        }
        return manager.cameraIdList.firstOrNull()
    }

    private fun open() {
        if (checkSelfPermission(Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            /* Asked for rather than assumed. deploy.sh grants it, but a
             * fresh install that has not been through deploy should say what
             * is wrong instead of showing black. */
            said?.text = "the camera permission has not been granted"
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 41)
            return
        }
        val holder = view?.holder ?: return
        if (!holder.surface.isValid) return

        val worker = HandlerThread("pine-camera").also { it.start() }
        thread = worker
        hand = Handler(worker.looper)

        try {
            val manager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val id = idFor(manager, facing) ?: run {
                said?.text = "this tablet reports no cameras"
                return
            }
            manager.openCamera(id, object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    device = camera
                    try {
                        val ask = camera.createCaptureRequest(
                            CameraDevice.TEMPLATE_PREVIEW)
                        ask.addTarget(holder.surface)
                        @Suppress("DEPRECATION")
                        camera.createCaptureSession(listOf(holder.surface),
                            object : CameraCaptureSession.StateCallback() {
                                override fun onConfigured(made: CameraCaptureSession) {
                                    session = made
                                    made.setRepeatingRequest(ask.build(), null, hand)
                                    runOnUiThread {
                                        said?.text = facing + " camera · id " + id
                                    }
                                }
                                override fun onConfigureFailed(made: CameraCaptureSession) {
                                    runOnUiThread { said?.text = "the preview would not configure" }
                                }
                            }, hand)
                    } catch (err: Exception) {
                        Log.w(TAG, "preview failed: " + err.message)
                        runOnUiThread { said?.text = "preview failed: " + err.message }
                    }
                }

                override fun onDisconnected(camera: CameraDevice) { shut() }

                override fun onError(camera: CameraDevice, why: Int) {
                    Log.w(TAG, "camera error " + why)
                    runOnUiThread { said?.text = "the camera reported error " + why }
                    shut()
                }
            }, hand)
        } catch (err: Exception) {
            Log.w(TAG, "camera would not open: " + err.message)
            said?.text = "the camera would not open: " + err.message
        }
    }

    override fun onRequestPermissionsResult(code: Int, names: Array<out String>,
                                            got: IntArray) {
        if (code == 41 && got.isNotEmpty() && got[0] == PackageManager.PERMISSION_GRANTED) {
            open()
        }
    }

    private fun shut() {
        try { session?.close() } catch (err: Exception) { /* going */ }
        try { device?.close() } catch (err: Exception) { /* going */ }
        session = null
        device = null
        try { thread?.quitSafely() } catch (err: Exception) { /* going */ }
        thread = null
        hand = null
    }

    override fun onPause() {
        /* THE CAMERA IS NOT HELD WHILE THIS IS NOT IN FRONT. It is a single
         * shared device, and an app that keeps it open in the background is
         * an app nothing else on the tablet can use a camera behind. */
        shut()
        super.onPause()
    }

    override fun onDestroy() {
        shut()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "PineCamera"
        const val EXTRA_FACING = "facing"
        const val BACK = "rear"
        const val FRONT = "front"

        /** Open the camera on this tablet, facing [want]. */
        fun show(context: Context, want: String?) {
            val go = Intent(context, PineCameraActivity::class.java)
            go.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            go.putExtra(EXTRA_FACING, if (want == FRONT) FRONT else BACK)
            context.startActivity(go)
        }
    }
}
