package com.pinebox.kiosk.camlink

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.MacAddress
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.net.wifi.WifiNetworkSpecifier
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import org.json.JSONObject
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.Socket

/**
 * [tabrelay] THE CAMERA SIDE-LINK: the Pine Cam's hotspot as a SECOND,
 * local-only Wi-Fi network, with TacoNet kept as the tablet's own.
 *
 * WHY THIS IS SAFE ONLY ON ONE CONDITION. Android serves a WifiNetworkSpecifier
 * request on a SECONDARY station interface only when the ROM enables "STA + STA
 * for local-only connections" (config_wifiMultiStaLocalOnlyConcurrencyEnabled,
 * read back as WifiManager.isStaConcurrencyForLocalOnlyConnectionsSupported()).
 * Without it the same request is served on the PRIMARY interface - the tablet
 * leaves TacoNet for the camera, and the station, the panel and the air go
 * with it. Measured 2026-09-29 on this tablet: the chip allows two STAs
 * (`dumpsys wifi`: "STA + STA Concurrency Supported: true", a 2 x STA
 * combination) but "Local only use-case enabled: false". So [start] refuses
 * unless the platform says yes, and says why; that is the whole gate.
 *
 * AND THE STATION IS WATCHED EVEN THEN. The default network at the moment of
 * asking is remembered; if it changes or is lost while the side-link is up,
 * the request is dropped at once and not tried again for [UNSAFE_REST_MS].
 *
 * NO DIALOG, IF THE PLATFORM AGREES. As a platform-signed app the kiosk holds
 * NETWORK_SETTINGS (signature), and the request names the exact SSID and BSSID;
 * AOSP skips the "connect to device" approval for such a request from a
 * NETWORK_SETTINGS holder. If this build shows the dialog anyway, one tap on
 * "Connect" is remembered by the platform for this app and this camera.
 *
 * Reconnects by itself: onLost / onUnavailable -> a fresh request after
 * 2, 4, 8 ... 60 s. Nothing here moves a byte; CamRelay does, through
 * [upstream], which binds its sockets to this network.
 */
class CamLink(context: Context, private val log: (String) -> Unit) {

    data class Want(val ssid: String, val psk: String, val bssid: String?)

    private val cm = context.getSystemService(ConnectivityManager::class.java)
    private val wifi = context.applicationContext.getSystemService(WifiManager::class.java)
    private val thread = HandlerThread("camlink").apply { start() }
    private val handler = Handler(thread.looper)

    @Volatile var state = "off"; private set
    @Volatile var why = ""; private set
    @Volatile var network: Network? = null; private set
    @Volatile private var info: WifiInfo? = null
    @Volatile private var want: Want? = null
    private var callback: ConnectivityManager.NetworkCallback? = null
    private var defaultWatch: ConnectivityManager.NetworkCallback? = null
    @Volatile private var primary: Network? = null
    private var backoffMs = 0L
    private var restUntil = 0L
    private var joinedAt = 0L
    private var attempts = 0
    private var retry: Runnable? = null

    /** Does this ROM run a local-only second STA? The one gate; see above. */
    fun localOnlySupported(): Boolean =
        Build.VERSION.SDK_INT >= 31 && try {
            wifi.isStaConcurrencyForLocalOnlyConnectionsSupported
        } catch (_: Throwable) { false }

    val joined: Boolean get() = state == "joined" && network != null

    /** Ask for the camera. Idempotent: a second call with the same want is nothing. */
    fun start(w: Want) = handler.post {
        if (want == w && state != "off" && state != "unsupported") return@post
        want = w
        if (!localOnlySupported()) {
            state = "unsupported"
            why = "this ROM does not run a local-only second Wi-Fi station " +
                "(config_wifiMultiStaLocalOnlyConcurrencyEnabled is off) - joining the camera " +
                "would take the tablet off TacoNet, so it is not asked"
            return@post
        }
        watchDefault()
        request()
    }

    /** Let the camera go: the platform tears the secondary STA down. */
    fun stop(reason: String = "not wanted") = handler.post {
        want = null
        drop()
        retry?.let { handler.removeCallbacks(it) }
        retry = null
        backoffMs = 0L
        defaultWatch?.let { try { cm.unregisterNetworkCallback(it) } catch (_: Exception) {} }
        defaultWatch = null
        state = "off"
        why = reason
    }

    private fun drop() {
        callback?.let { try { cm.unregisterNetworkCallback(it) } catch (_: Exception) {} }
        callback = null
        network = null
        info = null
    }

    private fun watchDefault() {
        if (defaultWatch != null) return
        primary = cm.activeNetwork
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(n: Network) {
                val was = primary
                if (was == null || callback == null) { primary = n; return }
                if (n != was) unsafe("the tablet's default network changed while the camera was joined")
            }
            override fun onLost(n: Network) {
                if (n != primary) return
                if (callback != null) unsafe("TacoNet was lost while the camera was joined") else primary = null
            }
        }
        defaultWatch = cb
        cm.registerDefaultNetworkCallback(cb, handler)
    }

    private fun unsafe(what: String) {
        log("camlink UNSAFE: $what - dropping the camera for ${UNSAFE_REST_MS / 60000} min")
        drop()
        state = "unsafe"
        why = what
        restUntil = SystemClock.elapsedRealtime() + UNSAFE_REST_MS
        schedule(UNSAFE_REST_MS)
    }

    private fun request() {
        val w = want ?: return
        if (callback != null) return
        val now = SystemClock.elapsedRealtime()
        if (now < restUntil) { schedule(restUntil - now); return }
        val spec = WifiNetworkSpecifier.Builder()
            .setSsid(w.ssid)
            .setWpa2Passphrase(w.psk)
            .apply { w.bssid?.let { runCatching { setBssid(MacAddress.fromString(it)) } } }
            .build()
        val req = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .setNetworkSpecifier(spec)
            .build()
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(n: Network) {
                if (cm.activeNetwork == n) {
                    // The camera became the DEFAULT network: exactly what must never be.
                    unsafe("the camera's network became the tablet's default")
                    return
                }
                network = n
                state = "joined"
                why = ""
                joinedAt = SystemClock.elapsedRealtime()
                log("camlink joined ${w.ssid} (attempt $attempts)")
            }
            override fun onCapabilitiesChanged(n: Network, caps: NetworkCapabilities) {
                (caps.transportInfo as? WifiInfo)?.let { info = it }
            }
            override fun onLost(n: Network) {
                if (n != network) return
                log("camlink lost ${w.ssid}")
                drop()
                state = "lost"
                again()
            }
            override fun onUnavailable() {
                drop()
                state = "unavailable"
                why = "the camera's hotspot was not found or refused the join"
                again()
            }
        }
        callback = cb
        attempts++
        state = "joining"
        try {
            cm.requestNetwork(req, cb, handler, JOIN_TIMEOUT_MS)
        } catch (err: Exception) {
            callback = null
            state = "error"
            why = (err.message ?: err.javaClass.simpleName).take(200)
            again()
        }
    }

    private fun again() {
        if (want == null) return
        // A link that held for a minute starts the ladder again from the bottom.
        if (joinedAt > 0 && SystemClock.elapsedRealtime() - joinedAt > 60_000) backoffMs = 0
        joinedAt = 0
        backoffMs = if (backoffMs == 0L) 2_000L else minOf(backoffMs * 2, MAX_BACKOFF_MS)
        schedule(backoffMs)
    }

    private fun schedule(ms: Long) {
        retry?.let { handler.removeCallbacks(it) }
        val r = Runnable { retry = null; if (want != null) request() }
        retry = r
        handler.postDelayed(r, ms)
    }

    /** Sockets for CamRelay, bound to the side-link. */
    fun upstream(): CamRelay.Upstream? {
        val n = network ?: return null
        return object : CamRelay.Upstream {
            override fun tcp(): Socket = n.socketFactory.createSocket()
            override fun bindUdp(socket: DatagramSocket) = n.bindSocket(socket)
        }
    }

    /** The tablet's own TacoNet IPv4 address - where the relay listens. */
    fun primaryAddress(): InetAddress? {
        val n = cm.activeNetwork ?: return null
        val lp: LinkProperties = cm.getLinkProperties(n) ?: return null
        return lp.linkAddresses.map { it.address }.firstOrNull { it is Inet4Address && !it.isLoopbackAddress }
    }

    fun snapshot(): JSONObject {
        val i = info
        val rssi = i?.rssi ?: 0
        return JSONObject()
            .put("state", state).put("why", why)
            .put("joined", joined)
            .put("local_only", localOnlySupported())
            .put("rssi", if (i != null) rssi else JSONObject.NULL)
            // The house's usual reading: 2 x (dBm + 100), 0-100 (NetworkManager's scale).
            .put("signal", if (i != null) (2 * (rssi + 100)).coerceIn(0, 100) else 0)
            .put("link_mbps", i?.linkSpeed ?: 0)
            .put("freq_mhz", i?.frequency ?: 0)
            .put("attempts", attempts)
            .put("backoff_s", backoffMs / 1000)
            .put("joined_s", if (joinedAt > 0) (SystemClock.elapsedRealtime() - joinedAt) / 1000 else 0)
    }

    companion object {
        const val JOIN_TIMEOUT_MS = 30_000
        const val MAX_BACKOFF_MS = 60_000L
        const val UNSAFE_REST_MS = 30 * 60_000L
    }
}
