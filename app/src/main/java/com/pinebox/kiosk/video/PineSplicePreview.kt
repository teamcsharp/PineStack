package com.pinebox.kiosk.video

import android.content.Context
import android.net.Uri
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import com.pinebox.kiosk.net.StationClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

/** One continuous export-equivalent preview, cached locally before playback.
 * The hardware surface bypasses WebView's compositor and decoder-start stalls.
 */
@UnstableApi
class PineSplicePreview(context: Context, private val client: StationClient,
                        private val scope: CoroutineScope) : FrameLayout(context) {
    private val screen = SurfaceView(context).apply { setZOrderMediaOverlay(true) }
    private var player: ExoPlayer? = null
    private var download: Job? = null
    private var revision = 0
    private var phase = "idle"
    private var failure = ""
    private var currentId = ""
    private var lastAsk = 0L
    private val lease = object : Runnable {
        override fun run() {
            if (System.currentTimeMillis() - lastAsk > 5000) stop()
            else postDelayed(this, 1000)
        }
    }

    init {
        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        visibility = View.GONE
        isClickable = false
        isFocusable = false
    }

    fun command(op: String, args: JSONObject): JSONObject {
        lastAsk = System.currentTimeMillis()
        when (op) {
            "prepare" -> prepare(args)
            "box" -> box(args)
            "pause" -> { player?.pause(); visibility = View.GONE; phase = "paused" }
            "stop" -> stop()
        }
        return state()
    }

    private fun box(args: JSONObject) {
        val w = args.optInt("w").coerceIn(1, 4096)
        val h = args.optInt("h").coerceIn(1, 4096)
        layoutParams = LayoutParams(w, h).apply {
            leftMargin = args.optInt("x").coerceIn(0, 8192)
            topMargin = args.optInt("y").coerceIn(0, 8192)
        }
    }

    private fun prepare(args: JSONObject) {
        val id = args.optString("id")
        require(Regex("[0-9a-f]{32}").matches(id)) { "Invalid preview identity" }
        stop()
        val mine = ++revision
        currentId = id
        phase = "caching"
        failure = ""
        box(args)
        removeCallbacks(lease)
        postDelayed(lease, 1000)
        download = scope.launch {
            try {
                val file = withContext(Dispatchers.IO) {
                    val dir = File(context.cacheDir, "splice-preview").apply { mkdirs() }
                    val target = File(dir, "$id.mp4")
                    if (!target.isFile || target.length() < 64) {
                        val temp = File(dir, "$id-$mine.part")
                        try {
                            client.getVideoEditorExport(id, temp)
                            check(temp.length() >= 64) { "The preview file is empty" }
                            check(temp.renameTo(target)) { "Could not commit the cached preview" }
                        } finally { temp.delete() }
                    }
                    target.setLastModified(System.currentTimeMillis())
                    // Keep at most 256 MB of completed previews on the tablet.
                    var used = target.length()
                    dir.listFiles()?.filter { it != target && it.extension == "mp4" }
                        ?.sortedByDescending { it.lastModified() }?.forEach {
                            used += it.length()
                            if (used > 256L * 1024 * 1024) it.delete()
                        }
                    target
                }
                if (mine != revision) return@launch
                val loadControl = DefaultLoadControl.Builder()
                    .setBufferDurationsMs(15000, 30000, 1000, 1000)
                    .setTargetBufferBytes(32 * 1024 * 1024).build()
                val next = ExoPlayer.Builder(context).setLoadControl(loadControl).build()
                player = next
                visibility = View.VISIBLE
                next.setVideoSurfaceView(screen)
                next.volume = if (args.optBoolean("muted")) 0f else 1f
                next.addListener(object : Player.Listener {
                    override fun onRenderedFirstFrame() { if (mine == revision) visibility = View.VISIBLE }
                    override fun onPlaybackStateChanged(state: Int) {
                        if (mine != revision) return
                        phase = when (state) {
                            Player.STATE_READY -> "ready"
                            Player.STATE_BUFFERING -> "buffering"
                            Player.STATE_ENDED -> "ended"
                            else -> "idle"
                        }
                    }
                    override fun onPlayerError(error: PlaybackException) {
                        if (mine != revision) return
                        failure = error.message ?: "Native preview playback failed"
                        phase = "failed"
                        visibility = View.GONE
                    }
                })
                next.setMediaItem(MediaItem.fromUri(Uri.fromFile(file)))
                val seconds = args.optDouble("at", 0.0).let { if (it.isFinite()) it.coerceAtLeast(0.0) else 0.0 }
                next.seekTo((seconds * 1000).toLong())
                next.prepare()
                next.playWhenReady = true
            } catch (error: Exception) {
                if (mine == revision) {
                    phase = "failed"
                    failure = error.message ?: "Could not cache the preview"
                    visibility = View.GONE
                }
            }
        }
    }

    fun state(): JSONObject {
        val p = player
        val counters = p?.videoDecoderCounters
        counters?.ensureUpdated()
        return JSONObject().put("supported", true).put("id", currentId).put("phase", phase)
            .put("playing", p?.isPlaying == true).put("at", (p?.currentPosition ?: 0) / 1000.0)
            .put("duration", (p?.duration ?: 0).coerceAtLeast(0) / 1000.0)
            .put("buffered", (p?.bufferedPosition ?: 0) / 1000.0)
            .put("renderedFrames", counters?.renderedOutputBufferCount ?: 0)
            .put("droppedFrames", counters?.droppedBufferCount ?: 0).put("error", failure)
    }

    fun stop() {
        revision++
        removeCallbacks(lease)
        download?.cancel(); download = null
        player?.release(); player = null
        visibility = View.GONE
        phase = "idle"
    }
}
