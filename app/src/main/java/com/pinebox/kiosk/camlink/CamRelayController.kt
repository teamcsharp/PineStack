package com.pinebox.kiosk.camlink

import android.content.Context
import android.util.Log
import com.pinebox.kiosk.config.ConfigStore
import com.pinebox.kiosk.net.StationClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.InetAddress
import java.net.URI

/**
 * [tabrelay] WHO DECIDES WHEN THE TABLET CARRIES THE CAMERA: THE STATION.
 *
 * One small loop. It tells the station what the side-link and the relay are
 * doing (POST /api/pinelink/relay/report) and the answer says whether they are
 * wanted. tools/pinelink.py makes that call - it owns the camera, knows whether
 * the dongle holds it, and reads the operator's "Relay through the PineTab:
 * auto / always / never" - so the tablet never joins a camera nobody is
 * reading, and the dongle and the tablet never fight over the camera's one
 * client slot.
 *
 * Wanted: CamLink joins, and once joined CamRelay listens on the tablet's
 * TacoNet address. Not wanted, or the station silent for [STATION_SILENT_MS]:
 * both stop, and the platform takes the second STA down - no radio time, no
 * sockets, no threads beyond this loop's one request every [IDLE_MS].
 *
 * After every join the station is asked once more at once: if it does not
 * answer, the camera is let go (CamLink's own watch catches a changed default
 * network; this catches a station that stopped answering for any reason).
 */
class CamRelayController(
    private val context: Context,
    private val client: StationClient,
    private val configStore: ConfigStore,
    private val scope: CoroutineScope,
) {
    private val link = CamLink(context) { Log.i(TAG, it) }
    @Volatile private var relay: CamRelay? = null
    private var relayKey = ""
    private var job: Job? = null
    private var silentSince = 0L
    private var wasJoined = false
    @Volatile private var lastWant = false

    fun start() {
        if (job?.isActive == true) return
        job = scope.launch(Dispatchers.IO) {
            delay(15_000)            // let the panel and the air settle after a launch
            while (isActive) {
                val wait = try { turn() } catch (err: Exception) {
                    Log.w(TAG, "turn failed", err); IDLE_MS
                }
                delay(wait)
            }
        }
    }

    private suspend fun turn(): Long {
        val reply = try {
            JSONObject(client.post(ROUTE, report().toString()))
        } catch (err: Exception) {
            null
        }
        val now = System.currentTimeMillis()
        if (reply == null) {
            if (silentSince == 0L) silentSince = now
            if (now - silentSince > STATION_SILENT_MS) stopAll("the station is not answering")
            return if (lastWant) BUSY_MS else IDLE_MS
        }
        silentSince = 0L
        val want = reply.optBoolean("want", false)
        lastWant = want
        if (!want) {
            stopAll(reply.optString("why", "not wanted"))
            return reply.optLong("every_s", IDLE_MS / 1000).coerceIn(5, 120) * 1000
        }
        link.start(CamLink.Want(
            reply.optString("ssid"), reply.optString("psk"),
            reply.optString("bssid").ifBlank { null }))
        if (link.joined) {
            if (!wasJoined) {
                wasJoined = true
                // The station must still answer with the camera joined.
                if (!withContext(Dispatchers.IO) { client.reachable(quick = true) }) {
                    Log.w(TAG, "the station stopped answering once the camera joined - letting it go")
                    stopAll("the station stopped answering once the camera joined")
                    return IDLE_MS
                }
            }
            ensureRelay(reply)
        } else {
            wasJoined = false
            relay?.close(); relay = null; relayKey = ""
        }
        return BUSY_MS
    }

    private suspend fun ensureRelay(reply: JSONObject) {
        val up = link.upstream() ?: return
        val addr = link.primaryAddress() ?: return
        val mode = reply.optString("mode", "udp")
        val allow = allowed(reply)
        val key = addr.hostAddress + "|" + mode + "|" + link.network + "|" + allow.joinToString(",") { it.hostAddress ?: "" }
        if (relay?.listening == true && key == relayKey) return
        relay?.close()
        val r = CamRelay(
            upstream = up, listenAddr = addr,
            rtspPort = reply.optInt("rtsp_port", 8554), httpPort = reply.optInt("http_port", 8580),
            cameraHost = reply.optString("camera", "192.168.1.254"),
            udpUpstream = mode != "pass",
            allow = { it in allow },
            log = { Log.i(TAG, it) },
        )
        try {
            r.start()
            relay = r
            relayKey = key
        } catch (err: Exception) {
            Log.w(TAG, "relay could not listen on ${addr.hostAddress}", err)
            relay = null
            relayKey = ""
        }
    }

    /** Only the station may use the relay: its addresses as the station
     *  names them, plus the host this kiosk is configured to reach. */
    private suspend fun allowed(reply: JSONObject): Set<InetAddress> {
        val out = HashSet<InetAddress>()
        reply.optJSONArray("allow")?.let { a ->
            for (i in 0 until a.length()) runCatching { out.add(InetAddress.getByName(a.getString(i))) }
        }
        runCatching {
            val host = URI(configStore.read().base).host
            if (!host.isNullOrBlank()) out.add(InetAddress.getByName(host))
        }
        return out
    }

    private fun stopAll(why: String) {
        relay?.close(); relay = null; relayKey = ""
        wasJoined = false
        link.stop(why)
    }

    private fun report(): JSONObject {
        val r = relay
        return JSONObject()
            .put("v", 1)
            .put("capable", link.localOnlySupported())
            .put("ip", link.primaryAddress()?.hostAddress ?: "")
            .put("link", link.snapshot())
            .put("relay", if (r != null) JSONObject(r.stats()) else JSONObject().put("listening", false))
    }

    companion object {
        private const val TAG = "PineCamRelay"
        const val ROUTE = "/api/pinelink/relay/report"
        const val BUSY_MS = 5_000L
        const val IDLE_MS = 30_000L
        const val STATION_SILENT_MS = 45_000L
    }
}
