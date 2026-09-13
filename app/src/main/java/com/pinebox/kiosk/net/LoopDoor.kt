package com.pinebox.kiosk.net

import android.util.Log
import java.io.InputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/**
 * THE PANEL'S OWN FRONT DOOR, ON LOOPBACK.
 *
 * "The capture audio has static and noise in it. I need a Pure Mixed
 *  Broadcast." ... "I dont know why the audio stutters. Its unusual."
 *
 * THE STUTTER IS A THREAD, NOT A CODEC. The broadcast tap runs on a
 * ScriptProcessorNode, which does its work ON THE MAIN THREAD - so every time
 * that thread is busy laying out a very large panel, a whole buffer of the
 * mix is simply gone. Measured at 17-23% of buffers lost, 85 ms at a time.
 * Nothing about gain, format or sample rate can fix a hole.
 *
 * THE CURE IS ALREADY WRITTEN. sampler-air.js asks for an AudioWorklet first
 * and falls back to the ScriptProcessor; the worklet runs on the audio thread
 * and cannot be starved. It has never once loaded, because
 * `BaseAudioContext.audioWorklet` is gated on isSecureContext and the panel is
 * served over plain http. (`AudioWorkletNode` existing as a class is a red
 * herring - it is there either way. Only an INSTANCE's `.audioWorklet` tells
 * the truth, and reading it off the prototype throws "Illegal invocation".)
 *
 * SO THE ORIGIN HAS TO BECOME TRUSTWORTHY, and there are only three roads:
 *
 *   a certificate        there is none to be had for 10.89.1.246, and the
 *                        tablet is also carried onto a tailnet address.
 *   a command-line flag  --unsafely-treat-insecure-origin-as-secure. The
 *                        flag file IS read on this device (proved with
 *                        --force-device-scale-factor, which took) but that
 *                        particular switch never reached the renderer, and it
 *                        would need every road's origin listed besides.
 *   loopback             127.0.0.1 is potentially trustworthy BY SPEC, needs
 *                        no certificate and no flag, and - unlike a virtual
 *                        https origin - stays http, so the panel's own
 *                        cleartext media is not blocked as mixed content.
 *
 * MEASURED ON THIS TABLET before any of this was written: a top-level page on
 * http://127.0.0.1 reports `isSecureContext: true` and a live AudioContext
 * there has `audioWorklet` as an object. The panel on 10.89.1.246 reports
 * false and undefined.
 *
 * SO THIS IS A DOOR AND NOT A PROXY. It parses nothing. Bytes that arrive go
 * out the other side and back, which means Range requests, chunked bodies,
 * keep-alive and anything else the station and the panel agree on between
 * themselves keep working without this file having an opinion about them.
 * The only thing it changes is the ORIGIN the document is loaded from.
 *
 * IT IS FOR THE WEBVIEW ONLY. The kiosk's own OkHttp client keeps talking to
 * the station directly - there is nothing to gain by routing it through here
 * and a whole failure mode to avoid.
 */
object LoopDoor {

    private const val TAG = "PineLoopDoor"

    /** Tried first so the address is predictable; any port will do. */
    private const val WANTED_PORT = 8096

    private var server: ServerSocket? = null
    private var upstream: Pair<String, Int>? = null
    private val pumps = Executors.newCachedThreadPool { runnable ->
        Thread(runnable, "pine-loop-door").apply { isDaemon = true }
    }
    private val live = AtomicInteger(0)

    /** Where the panel should be loaded from, once open() has answered. */
    @Volatile
    var origin: String = ""
        private set

    /**
     * Open the door in front of [station] (e.g. "http://10.89.1.246:8096").
     *
     * Returns the loopback origin to load, or null if it could not be opened
     * at all - in which case the caller must fall back to the station's own
     * address. A terminal with a worse audio tap is worth having; a blind one
     * is not.
     */
    @Synchronized
    fun open(station: String): String? {
        val aim = parse(station) ?: run {
            Log.w(TAG, "cannot read a host out of $station")
            return null
        }
        upstream = aim

        server?.let { if (!it.isClosed) return origin }

        val local = InetAddress.getByName("127.0.0.1")
        val sock = try {
            ServerSocket(WANTED_PORT, 64, local)
        } catch (err: Exception) {
            /* Something already holds it. Any port beats no door. */
            try {
                ServerSocket(0, 64, local)
            } catch (worse: Exception) {
                Log.w(TAG, "no loopback door: " + worse.message)
                return null
            }
        }
        server = sock
        origin = "http://127.0.0.1:" + sock.localPort
        Log.i(TAG, "door open at $origin -> ${aim.first}:${aim.second}")

        pumps.execute {
            while (!sock.isClosed) {
                val from = try {
                    sock.accept()
                } catch (err: Exception) {
                    if (!sock.isClosed) Log.w(TAG, "accept: " + err.message)
                    return@execute
                }
                pumps.execute { carry(from) }
            }
        }
        return origin
    }

    /**
     * Point the door somewhere else, for when the road changes underneath.
     * Only new connections follow; the ones already open belong to whoever
     * opened them.
     */
    @Synchronized
    fun aim(station: String) {
        parse(station)?.let {
            if (it != upstream) {
                Log.i(TAG, "door now aims at ${it.first}:${it.second}")
                upstream = it
            }
        }
    }

    @Synchronized
    fun close() {
        try { server?.close() } catch (err: Exception) { /* going anyway */ }
        server = null
        origin = ""
    }

    /** How many conversations are in flight, for the readiness report. */
    fun busy(): Int = live.get()

    fun isOpen(): Boolean = server?.isClosed == false

    /* ------------------------------------------------------------------ */

    private fun parse(station: String): Pair<String, Int>? {
        val trimmed = station.trim().removePrefix("http://").removePrefix("https://")
        val stop = trimmed.indexOf('/')
        val hostPort = if (stop >= 0) trimmed.substring(0, stop) else trimmed
        if (hostPort.isBlank()) return null
        val colon = hostPort.lastIndexOf(':')
        return if (colon > 0) {
            val port = hostPort.substring(colon + 1).toIntOrNull() ?: return null
            hostPort.substring(0, colon) to port
        } else {
            hostPort to 80
        }
    }

    /**
     * One conversation, both ways, until either end stops talking.
     *
     * Both directions have to be pumped at once - a request body can still be
     * arriving while the response starts coming back, and a single-threaded
     * "read it all then write it all" deadlocks on exactly that.
     */
    private fun carry(from: Socket) {
        val aim = upstream ?: run { quietly(from); return }
        live.incrementAndGet()
        var to: Socket? = null
        try {
            from.tcpNoDelay = true
            val out = Socket(aim.first, aim.second)
            out.tcpNoDelay = true
            to = out

            val up = pumps.submit { pump(from.getInputStream(), out.getOutputStream()) }
            pump(out.getInputStream(), from.getOutputStream())
            up.get()
        } catch (err: Exception) {
            /* A conversation ending early is ordinary - a panel navigating
             * away closes sockets mid-response all day. Only say something
             * when the far end is the problem. */
            if (err !is java.io.IOException) Log.w(TAG, "carry: " + err.message)
        } finally {
            quietly(from)
            to?.let { quietly(it) }
            live.decrementAndGet()
        }
    }

    private fun pump(input: InputStream, output: OutputStream) {
        val bite = ByteArray(32 * 1024)
        try {
            while (true) {
                val got = input.read(bite)
                if (got < 0) break
                output.write(bite, 0, got)
                output.flush()
            }
        } catch (err: Exception) {
            /* Closed underneath us; the finally in carry() tidies both ends. */
        } finally {
            try { output.flush() } catch (err: Exception) { /* gone */ }
        }
    }

    private fun quietly(sock: Socket) {
        try { if (!sock.isClosed) sock.close() } catch (err: Exception) { /* gone */ }
    }
}
