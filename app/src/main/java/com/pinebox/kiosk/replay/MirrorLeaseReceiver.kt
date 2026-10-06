package com.pinebox.kiosk.replay

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import org.json.JSONObject
import java.util.concurrent.Executors

/** Explicit, signature-guarded ADB control. Encoder/disk work stays off the UI
 * thread, and the ordered result acknowledges actual release of replay video. */
class MirrorLeaseReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION) return
        val pending = goAsync()
        worker.execute {
            var replay: ScreenReplay? = null
            try {
                replay = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.replay
                val answer = replay?.mirrorLease(
                    intent.getStringExtra("operation") ?: "status",
                    intent.getStringExtra("owner") ?: "",
                    intent.getLongExtra("ttl_ms", 60_000L),
                    intent.getIntExtra("width", 0), intent.getIntExtra("height", 0),
                    intent.getIntExtra("jpeg_quality", 50), intent.getIntExtra("fps", 12),
                    intent.getStringExtra("stream_id") ?: ""
                ) ?: JSONObject().put("ok", false).put("detail", "no replay recorder")
                pending.setResultCode(if (answer.optBoolean("ok")) 0 else 1)
                pending.setResultData(answer.toString())
            } catch (error: Throwable) {
                pending.setResultCode(1)
                pending.setResultData(JSONObject().put("ok", false)
                    .put("detail", error.message ?: error.javaClass.simpleName).toString())
            } finally {
                try { pending.finish() }
                finally {
                    // Disk persistence cannot delay the encoder-release ACK.
                    replay?.cacheMirrorHistoryAsync()
                }
            }
        }
    }

    companion object {
        const val ACTION = "com.pinebox.kiosk.action.MIRROR_ENCODER_LEASE"
        private val worker = Executors.newSingleThreadExecutor { work ->
            Thread(work, "pine-mirror-lease").apply { isDaemon = true }
        }
    }
}
