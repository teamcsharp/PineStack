package com.pinebox.kiosk.replay

import android.content.Context
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.hardware.display.VirtualDisplayConfig
import android.media.ImageReader
import android.net.LocalSocketAddress
import android.net.LocalServerSocket
import android.net.LocalSocket
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Log
import java.nio.ByteBuffer
import org.json.JSONObject

/** Full-sized mirror frames without a hardware video encoder. Lease ownership
 * is checked by ScreenReplay before start; this object never touches audio or
 * replay history. Capture, socket writes and potentially slow release each run
 * separately. A failed release retains the owner and every uncertain handle. */
internal object JpegMirrorCapture {
    const val SOCKET = "pine_mirror"
    private const val TAG = "PineMirrorJPEG"
    private const val STOP_WAIT_MS = 3000L
    private val gate = Any()
    @Volatile private var app: Context? = null
    @Volatile private var current: Session? = null

    fun initialize(context: Context) { app = context.applicationContext }
    fun isReleased(): Boolean = current?.released() != false

    fun status(): JSONObject = synchronized(gate) {
        current?.report() ?: emptyStatus()
    }

    fun start(owner: String, streamId: String, width: Int, height: Int, jpegQuality: Int, fps: Int): JSONObject = synchronized(gate) {
        if (!JpegStreamFence.valid(owner) || !JpegStreamFence.valid(streamId)) return rejection("Invalid mirror owner or stream")
        try { ReplayRgbaRows.byteCount(width, height) }
        catch (error: IllegalArgumentException) { return rejection(error.message ?: "Invalid mirror dimensions") }
        if (width > 4096 || height > 4096) return rejection("Mirror dimensions exceed the display limit")
        val context = app ?: return rejection("Mirror capture is not initialized")
        val quality = jpegQuality.coerceIn(10, 90)
        val rate = fps.coerceIn(1, 12)
        val old = current
        if (old != null) {
            if (old.owner != owner) return old.report(false, "JPEG mirror is held by another owner")
            if (old.streamId != streamId && !old.released()) return old.report(false, "The previous JPEG stream must stop before replacement")
            if (old.running() && old.width == width && old.height == height && old.quality == quality && old.fps == rate)
                return old.report()
            if (!old.stop()) return old.report(false, "Previous JPEG mirror resources have not released")
            current = null
        }
        val session = Session(context, owner, streamId, width, height, quality, rate)
        current = session // Partial allocation must remain owned until cleanup succeeds.
        try {
            session.start()
            session.report()
        } catch (error: Throwable) {
            session.lastError = error.message ?: error.javaClass.simpleName
            Log.w(TAG, "JPEG mirror could not start", error)
            val cleared = session.stop()
            val answer = session.report(false, session.lastError)
            if (cleared) current = null
            answer
        }
    }

    fun stopExactOwner(owner: String, streamId: String): JSONObject = synchronized(gate) {
        val session = current ?: return emptyStatus()
        val released = session.fence.stopExact(owner, streamId) { session.stop() }
            ?: return session.report(false, "JPEG mirror owner or stream does not match")
        finishStop(session, released)
    }

    /** Only the exact lease owner can stop the current stream without a token.
     * Called by ScreenReplay under its lease gate for release/TTL recovery. */
    fun stopOwned(owner: String): JSONObject = synchronized(gate) {
        val session = current ?: return emptyStatus()
        if (session.owner != owner) return session.report(false, "JPEG mirror is held by another owner")
        finishStop(session, session.stop())
    }

    fun stopAllOnExpired(): JSONObject = synchronized(gate) {
        val session = current ?: return emptyStatus()
        stopOwned(session.owner)
    }

    private fun finishStop(session: Session, released: Boolean): JSONObject {
        val answer = session.report(released, if (released) null else "JPEG mirror cleanup is still pending")
        if (released) current = null
        return answer
    }

    private fun rejection(detail: String): JSONObject = current?.report(false, detail) ?: emptyStatus(false, detail)

    private fun emptyStatus(ok: Boolean = true, detail: String? = null): JSONObject = JSONObject()
        .put("ok", ok).put("jpeg_running", false).put("jpeg_released", true)
        .put("jpeg_owner", "").put("jpeg_stream_id", "").put("jpeg_socket", SOCKET).put("width", 0).put("height", 0).put("fps", 0)
        .put("jpeg_image_callbacks", 0).put("jpeg_drain_attempts", 0).put("jpeg_acquired_images", 0).put("jpeg_empty_reads", 0).put("jpeg_error", "")
        .also { if (detail != null) it.put("detail", detail) }

    private fun stopDisconnected(session: Session) {
        Thread({
            synchronized(gate) {
                if (current === session) {
                    if (session.stop()) current = null
                }
            }
        }, "pine-mirror-disconnect").apply { isDaemon = true }.start()
    }

    private class Session(val context: Context, val owner: String, val streamId: String, val width: Int, val height: Int,
                          val quality: Int, val fps: Int) {
        val fence = JpegStreamFence(owner, streamId)
        @Volatile private var active = false
        @Volatile var lastError: String? = null
        @Volatile private var releaseError: String? = null
        @Volatile private var display: VirtualDisplay? = null
        @Volatile private var reader: ImageReader? = null
        @Volatile private var bitmap: Bitmap? = null
        @Volatile private var pixels: ByteArray? = null
        private var pixelBuffer: ByteBuffer? = null
        @Volatile private var capture: HandlerThread? = null
        @Volatile private var handler: Handler? = null
        @Volatile private var server: LocalServerSocket? = null
        @Volatile private var acceptor: Thread? = null
        @Volatile private var socket: LocalSocket? = null
        @Volatile private var writer: Thread? = null
        @Volatile private var closer: Thread? = null
        private val networkGate = Any()
        private val frames = JpegLatestFrame()
        private val output = JpegFrameBuffer()
        private var lastCaptureNs = 0L
        @Volatile private var frameCount = 0L
        @Volatile private var lastFrameMs = 0L
        @Volatile private var compressMs = 0L
        // Written only on the capture Handler; status reads never probe a codec.
        @Volatile private var imageCallbacks = 0L
        @Volatile private var drainAttempts = 0L
        @Volatile private var acquiredImages = 0L
        @Volatile private var emptyReads = 0L

        fun running() = active && display != null && reader != null && capture?.isAlive == true
        fun released() = display == null && reader == null && bitmap == null && pixels == null &&
            capture == null && handler == null && server == null && socket == null && acceptor == null &&
            writer == null && closer == null

        fun report(ok: Boolean = true, detail: String? = null): JSONObject = JSONObject()
            .put("ok", ok).put("jpeg_running", running()).put("jpeg_released", released())
            .put("jpeg_owner", owner).put("jpeg_stream_id", streamId).put("jpeg_socket", SOCKET).put("width", width).put("height", height)
            .put("fps", fps).put("jpeg_quality", quality).put("jpeg_frames", frameCount)
            .put("jpeg_since_frame_ms", if (lastFrameMs == 0L) 0 else SystemClock.elapsedRealtime() - lastFrameMs)
            .put("jpeg_compress_ms", compressMs)
            .put("jpeg_image_callbacks", imageCallbacks).put("jpeg_drain_attempts", drainAttempts)
            .put("jpeg_acquired_images", acquiredImages).put("jpeg_empty_reads", emptyReads)
            .put("jpeg_error", releaseError ?: lastError ?: "")
            .put("jpeg_resources", JSONObject()
                .put("display", display != null).put("reader", reader != null)
                .put("bitmap", bitmap != null).put("pixels", pixels != null)
                .put("capture_alive", capture?.isAlive == true).put("capture_handle", capture != null)
                .put("handler", handler != null).put("listener", server != null).put("socket", socket != null)
                .put("accept_alive", acceptor?.isAlive == true).put("accept_handle", acceptor != null)
                .put("writer_alive", writer?.isAlive == true).put("writer_handle", writer != null)
                .put("cleanup_alive", closer?.isAlive == true).put("cleanup_handle", closer != null))
            .also { if (detail != null || releaseError != null || lastError != null)
                it.put("detail", detail ?: releaseError ?: lastError) }

        fun start() {
            server = LocalServerSocket(SOCKET)
            pixels = ByteArray(ReplayRgbaRows.byteCount(width, height))
            pixelBuffer = ByteBuffer.wrap(pixels!!)
            bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            val worker = HandlerThread("pine-mirror-pixels")
            capture = worker
            worker.start()
            val work = Handler(worker.looper)
            handler = work
            val input = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
            reader = input
            val manager = context.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
            val flags = DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR or DisplayManager.VIRTUAL_DISPLAY_FLAG_SECURE
            JpegCaptureStartup.run({
                // A quiet display can deliver its only image inside creation.
                // ImageReader drops notifications before its listener is set.
                active = true
                input.setOnImageAvailableListener({ incoming -> imageCallbacks++; captureFrame(incoming) }, work)
            }, {
                display = if (Build.VERSION.SDK_INT >= 34) {
                    manager.createVirtualDisplay(VirtualDisplayConfig.Builder("ScreenRecorder-PineMirrorJPEG", width, height, 1)
                        // Keep the default display cadence. Compositor phase
                        // filtering can miss sparse UI updates; cap JPEG in software.
                        .setSurface(input.surface).setFlags(flags).build())
                } else manager.createVirtualDisplay("ScreenRecorder-PineMirrorJPEG", width, height, 1, input.surface, flags)
                check(display != null) { "The JPEG mirror display was refused" }
            }, {
                // Also drain a queued initial image whose notification preceded
                // registration. Capture stays serialized on the same worker.
                check(work.post { drainAttempts++; captureFrame(input) }) { "The JPEG capture worker has stopped" }
            })
            acceptor = Thread({ acceptClients() }, "pine-mirror-socket").apply { isDaemon = true; start() }
            work.postDelayed({ if (active && socket == null) stopDisconnected(this) }, 15_000L)
        }

        private fun captureFrame(input: ImageReader) {
            var image: android.media.Image? = null
            var captured = false
            try {
                image = input.acquireLatestImage()
                if (image == null) { emptyReads++; return }
                acquiredImages++
                if (!active) return
                val now = System.nanoTime()
                if (!JpegCapturePace.allows(now, lastCaptureNs, fps)) return
                val plane = image.planes.firstOrNull() ?: return
                val raw = pixels ?: return
                val picture = bitmap ?: return
                ReplayRgbaRows.copy(plane.buffer, width, height, plane.pixelStride, plane.rowStride, raw)
                val buffer = pixelBuffer ?: return
                buffer.rewind()
                picture.copyPixelsFromBuffer(buffer)
                lastCaptureNs = now
                captured = true
            } catch (error: Throwable) {
                lastError = error.message ?: error.javaClass.simpleName
            } finally {
                try { image?.close() } catch (error: Exception) { lastError = error.message }
            }
            // Image lifetime ends before software compression or a blocked socket.
            if (!captured || !active) return
            try {
                val began = SystemClock.elapsedRealtime()
                output.reset()
                check(bitmap?.compress(Bitmap.CompressFormat.JPEG, quality, output) == true) { "JPEG compression failed" }
                val jpeg = output.toByteArray()
                if (active && frames.publish(jpeg)) {
                    frameCount++
                    lastFrameMs = SystemClock.elapsedRealtime()
                    compressMs = lastFrameMs - began
                    lastError = null
                }
            } catch (error: Throwable) { lastError = error.message ?: error.javaClass.simpleName }
        }

        private fun acceptClients() {
            try {
                while (active) {
                    val client = server?.accept() ?: break
                    val trusted = try { JpegStreamFence.allowedPeer(client.peerCredentials.uid, android.os.Process.myUid()) }
                        catch (_: Exception) { false }
                    if (!trusted) {
                        try { client.close() } catch (_: Exception) { }
                        continue
                    }
                    synchronized(networkGate) {
                        if (!active || socket != null) {
                            try { client.close() } catch (_: Exception) { }
                        } else {
                            socket = client
                            writer = Thread({ pump(client) }, "pine-mirror-send").apply { isDaemon = true; start() }
                        }
                    }
                }
            } catch (error: Exception) {
                if (active) { lastError = error.message; stopDisconnected(this) }
            }
        }

        private fun pump(client: LocalSocket) {
            try {
                val wire = client.outputStream
                var after = 0L
                while (active) {
                    val frame = frames.next(after) ?: break
                    if (!active) break
                    wire.write(frame.header)
                    wire.write(frame.jpeg)
                    wire.flush()
                    after = frame.sequence
                }
            } catch (error: Exception) { if (active) lastError = error.message }
            finally {
                synchronized(networkGate) {
                    try { client.close(); if (socket === client) socket = null }
                    catch (error: Exception) { releaseError = error.message }
                }
                if (active) stopDisconnected(this)
            }
        }

        /** The control caller waits at most three seconds; a blocked binder or
         * worker stays owned and cannot be replaced by another capture. */
        fun stop(): Boolean {
            active = false
            frames.close()
            if (closer?.isAlive != true) {
                releaseError = null
                closer = Thread({ cleanup() }, "pine-mirror-release").apply { isDaemon = true; start() }
            }
            val closing = closer
            try { closing?.join(STOP_WAIT_MS) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
            if (closing?.isAlive == false && closer === closing) closer = null
            return released()
        }

        private fun cleanup() {
            // shutdown(), unlike close alone, interrupts a blocked socket write.
            synchronized(networkGate) {
                try { socket?.shutdownOutput() } catch (_: Exception) { }
                try { socket?.shutdownInput() } catch (_: Exception) { }
                try { socket?.close(); socket = null } catch (error: Exception) { releaseError = error.message }
            }
            val listening = server
            if (listening != null) {
                try {
                    JpegListenerShutdown.run(acceptor?.isAlive == true, {
                        val wake = LocalSocket()
                        try { wake.connect(LocalSocketAddress(SOCKET, LocalSocketAddress.Namespace.ABSTRACT)) }
                        finally { wake.close() }
                    }, {
                        listening.close()
                        if (server === listening) server = null
                    })
                } catch (error: Exception) { releaseError = "Mirror listener cleanup: " + error.message }
            }
            try { display?.release(); display = null } catch (error: Exception) { releaseError = error.message }
            try { reader?.setOnImageAvailableListener(null, null) } catch (error: Exception) { releaseError = error.message }
            val worker = capture
            val work = handler
            if (worker?.isAlive == true && work != null) {
                val posted = work.post {
                    closePixels()
                    worker.quitSafely()
                }
                if (!posted) worker.quitSafely()
                try { worker.join(1500) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
            } else {
                worker?.quitSafely()
                try { worker?.join(1500) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
            }
            if (worker?.isAlive != true) {
                closePixels()
                capture = null
                handler = null
            }
            for (thread in listOf(acceptor, writer)) {
                try { thread?.join(500) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
            }
            if (acceptor?.isAlive != true) acceptor = null
            if (writer?.isAlive != true) writer = null
        }

        private fun closePixels() {
            // Only on the capture worker after its current Image has closed,
            // or after that worker is confirmed dead. No invalid plane access.
            try { reader?.close(); reader = null } catch (error: Exception) { releaseError = error.message }
            try { bitmap?.recycle(); bitmap = null } catch (error: Exception) { releaseError = error.message }
            pixels = null
            pixelBuffer = null
            output.reset()
        }
    }
}
