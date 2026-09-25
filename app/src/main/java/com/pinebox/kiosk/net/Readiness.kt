package com.pinebox.kiosk.net

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.Log
import com.pinebox.kiosk.config.Config
import org.json.JSONArray
import org.json.JSONObject
import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * WHAT THE TERMINAL CONFIRMED ABOUT ITSELF WHEN IT CAME UP.
 *
 * "The first thing it should do is set itself up with Pine Box when it boots
 *  up, deploy the Pine Box, get connected to it, and have everything
 *  confirmed as far as Tailscale and getting online and making sure that we
 *  are able to directly coordinate with this tablet using the Pine Box
 *  application."
 *
 * The finding and connecting already happened - Reach settles on a road and
 * KeyDiscovery pulls the bearer off the panel, and the boot sequence narrates
 * both. What did not exist was the CONFIRMATION: somewhere to look afterwards
 * that says, in order, what was tried, what answered, and what did not.
 *
 * EVERY FIELD HERE IS SOMETHING THAT WAS ACTUALLY CHECKED. There is no
 * "configured" or "should be" in this report. A readiness screen that reports
 * intentions is worse than no readiness screen, because it is believed.
 *
 * THE TAILNET IS READ OFF THE INTERFACES, not asked of the Tailscale app.
 * A 100.64/10 address on a tun device is the fact that matters - it is what
 * makes the station reachable from a phone tether - and it needs no
 * permission, no package query and no cooperation from another app that may
 * not be running. CGNAT space is what Tailscale hands out, so the range is
 * the identification.
 *
 * WHAT THIS CANNOT SEE, and says so rather than guessing: whether the Pine
 * Box DESKTOP is talking to this tablet. That conversation happens over adb,
 * which is a socket the tablet's framework owns and this process cannot
 * inspect. The desktop knows, and reports it from its own side - see
 * tablet-vitals.cjs. What this CAN confirm is that the door the desktop uses
 * is open, which is the half that lives here.
 */
object Readiness {

    private const val TAG = "PineReady"

    @Volatile
    private var last: JSONObject? = null

    /** The most recent report, or an empty one if boot has not finished. */
    fun report(): JSONObject = last ?: JSONObject().put("ok", false)
        .put("why", "the terminal has not finished starting")

    /**
     * Write down what the terminal found on its way up.
     *
     * IT DOES NOT PROBE. The road was already settled by the startup path -
     * `app.client.reachable()` runs Reach.settle before the panel is even
     * loaded - and probing again here would be a SECOND attempt wearing the
     * clothes of a report: slower, and capable of disagreeing with the thing
     * it claims to be describing. [roadMs] is how long that real probe took,
     * timed by the caller who ran it.
     */
    fun take(context: Context, cfg: Config, roadMs: Long): JSONObject {
        val out = JSONObject()
        val steps = JSONArray()

        /* ---- is there a network at all -------------------------------- */
        val net = netKind(context)
        steps.put(step("network", net != "none",
            if (net == "none") "nothing is connected" else "on " + net))

        /* ---- the tailnet, read off the interfaces --------------------- */
        val tail = tailnetAddress()
        steps.put(step("tailscale", tail != null,
            tail ?: "no 100.64/10 address on any interface - "
                + "the tablet is only reachable on this LAN"))

        /* ---- the station, as already settled -------------------------- */
        val road = Reach.base(cfg)
        val took = roadMs
        /* NOT whether `road` is non-empty. base() hands back the configured
         * address when nothing answered, on purpose, so it says nothing
         * about success - see Reach.answered. */
        val reached = Reach.answered
        steps.put(step("station", reached,
            if (!reached) "no road answered of " + Reach.candidates(cfg).size
            else road + "  (" + took + " ms, " + Reach.said + ")"))

        /* ---- the bearer key ------------------------------------------- */
        val key = cfg.apiKey
        steps.put(step("key", key.isNotEmpty(),
            if (key.isEmpty()) "not discovered - reads are open, so this only "
                + "matters if the station locks them"
            else "discovered, " + key.length + " characters"))

        /* ---- the door the desktop comes in by ------------------------- */
        val glass = webviewDoorOpen()
        steps.put(step("desktop door", glass,
            if (glass) "the WebView's devtools socket is listening, which is "
                + "what the Pine Box application attaches to"
            else "the WebView is not offering a devtools socket, so the "
                + "desktop cannot read this screen"))

        /* ---- the recorder --------------------------------------------- */
        val replay = (context.applicationContext as? com.pinebox.kiosk.PineApp)?.replay
        val held = replay?.seconds() ?: 0.0
        steps.put(step("recorder", replay?.isRunning == true,
            if (replay?.isRunning == true) "running, holding " + held.toInt() + "s"
            else (replay?.lastError ?: "not running")))

        var good = true
        for (i in 0 until steps.length()) {
            /* The KEY is not required - reads are open on this station - and
             * the tailnet is not required on the LAN. Everything else is. */
            val one = steps.getJSONObject(i)
            val name = one.optString("what")
            if (name == "key" || name == "tailscale") continue
            if (!one.optBoolean("ok")) good = false
        }

        out.put("ok", good)
        out.put("at", System.currentTimeMillis())
        out.put("network", net)
        out.put("tailnet", tail ?: JSONObject.NULL)
        out.put("road", road)
        out.put("roadMs", took)
        out.put("steps", steps)
        last = out
        Log.i(TAG, "readiness: " + out.toString())
        return out
    }

    private fun step(what: String, ok: Boolean, said: String): JSONObject =
        JSONObject().put("what", what).put("ok", ok).put("said", said)

    private fun netKind(context: Context): String {
        return try {
            val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE)
                as ConnectivityManager
            val active = manager.activeNetwork ?: return "none"
            val able = manager.getNetworkCapabilities(active) ?: return "none"
            when {
                able.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wi-fi"
                able.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
                able.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
                able.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "vpn"
                else -> "something"
            }
        } catch (err: Exception) {
            "unknown"
        }
    }

    /**
     * The tablet's address on the tailnet, if it has one.
     *
     * 100.64/10 is CGNAT space, which is what Tailscale hands out, and a
     * tun interface carrying one is the whole fact: it means this tablet is
     * reachable from the operator's phone on 3G, which is the reason the
     * tailnet was set up at all. Nothing is asked of the Tailscale app -
     * it may not be running, and querying another package needs a
     * declaration this build does not need to make.
     */
    private fun tailnetAddress(): String? {
        return try {
            for (face in NetworkInterface.getNetworkInterfaces()) {
                if (!face.isUp || face.isLoopback) continue
                for (address in face.inetAddresses) {
                    if (address !is Inet4Address) continue
                    val said = address.hostAddress ?: continue
                    val parts = said.split(".")
                    if (parts.size != 4) continue
                    val first = parts[0].toIntOrNull() ?: continue
                    val second = parts[1].toIntOrNull() ?: continue
                    /* 100.64.0.0 - 100.127.255.255 */
                    if (first == 100 && second in 64..127) return said
                }
            }
            null
        } catch (err: Exception) {
            null
        }
    }

    /**
     * Is the WebView offering its devtools socket?
     *
     * That abstract socket is what the Pine Box desktop forwards to in order
     * to read this screen, take its picture and pull its recordings - so it
     * is exactly "can the desktop coordinate with this tablet", from the only
     * side of it this process can see.
     */
    private fun webviewDoorOpen(): Boolean {
        return try {
            java.io.File("/proc/net/unix").readLines().any {
                it.contains("webview_devtools_remote")
            }
        } catch (err: Exception) {
            /* Unreadable is not the same as closed, and claiming a fault we
             * cannot see would be worse than admitting the blind spot. */
            false
        }
    }
}
