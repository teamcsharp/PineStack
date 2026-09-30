package com.pinebox.kiosk.camlink

import java.io.BufferedInputStream
import java.io.Closeable
import java.io.DataInputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * [tabrelay] THE PINE CAM'S RELAY: TacoNet on one side, the camera on the other.
 *
 * "Make the PineTab the relay for the Pine Cam, so the camera works anywhere
 *  in the house." The camera is an access point with a weak radio; the tablet
 *  travels with it and is on TacoNet everywhere. So the tablet joins the
 *  camera's hotspot as a local-only SECOND network (CamLink) and this carries
 *  the station's two conversations with the camera across:
 *
 *    :8554  RTSP   -> 192.168.1.254:554   the picture (see RtspText)
 *    :8580  HTTP   -> 192.168.1.254:80    the camera's API (the battery)
 *
 * NOTHING IS DECODED OR ENCODED HERE. HTTP is a byte pump both ways. RTSP is
 * read message by message only to re-aim the addresses in it; every RTP and
 * RTCP payload goes through untouched, and by default the camera's UDP packets
 * are carried to the station inside the station's own TCP connection
 * (interleaved), because the camera closes an interleaved session of its own
 * at thirty seconds (pinelink.py #1250b) and UDP cannot cross networks.
 *
 * PURE JVM ON PURPOSE. The only Android in the relay is how a socket reaches
 * the camera's network, and that is [Upstream]: CamLink hands in one bound to
 * the side-link's Network; the tests and the Spark harness hand in plain
 * sockets. The same file is what is proved on the Spark with ffprobe.
 *
 * Listening is on ONE address - the tablet's TacoNet address - never the
 * wildcard, so nothing on the camera's network can reach back through it, and
 * [allow] refuses any caller that is not the station.
 */
class CamRelay(
    private val upstream: Upstream,
    private val listenAddr: InetAddress,
    val rtspPort: Int = 8554,
    val httpPort: Int = 8580,
    private val cameraHost: String = "192.168.1.254",
    private val cameraRtspPort: Int = 554,
    private val cameraHttpPort: Int = 80,
    /** true: the camera sees a UDP client (default; dodges its 30 s TCP cut).
     *  false: Transport passes through and the camera streams interleaved. */
    private val udpUpstream: Boolean = true,
    private val allow: (InetAddress) -> Boolean = { true },
    private val log: (String) -> Unit = {},
) : Closeable {

    /** How a socket reaches the camera. CamLink binds these to the side-link. */
    interface Upstream {
        /** An unconnected TCP socket that will route over the camera's network. */
        fun tcp(): Socket
        /** Bind an unbound DatagramSocket to the camera's network (before bind()). */
        fun bindUdp(socket: DatagramSocket)
    }

    object Plain : Upstream {
        override fun tcp(): Socket = Socket()
        override fun bindUdp(socket: DatagramSocket) {}
    }

    private val servers = ArrayList<ServerSocket>()
    private val open = ConcurrentHashMap.newKeySet<Closeable>()
    @Volatile private var running = false

    // What the controller reports to the station.
    val rtspSessions = AtomicInteger(0)
    val httpSessions = AtomicInteger(0)
    val bytesToStation = AtomicLong(0)
    val bytesToCamera = AtomicLong(0)
    val udpPackets = AtomicLong(0)
    val refused = AtomicLong(0)
    val reports = AtomicLong(0)
    @Volatile var lastPacketAt = 0L
    @Volatile var lastError = ""
    @Volatile var lastMode = ""

    val listening: Boolean get() = running && servers.isNotEmpty()

    @Synchronized
    fun start() {
        if (running) return
        running = true
        try {
            servers.add(listen(rtspPort, "rtsp") { s -> rtspSession(s) })
            servers.add(listen(httpPort, "http") { s -> httpSession(s) })
        } catch (err: IOException) {
            close()
            throw err
        }
        log("relay listening on ${listenAddr.hostAddress}:$rtspPort (rtsp) and :$httpPort (http) -> $cameraHost")
    }

    @Synchronized
    override fun close() {
        running = false
        for (s in servers) try { s.close() } catch (_: IOException) {}
        servers.clear()
        for (c in open.toList()) try { c.close() } catch (_: IOException) {}
        open.clear()
    }

    fun stats(): Map<String, Any> = mapOf(
        "listening" to listening,
        "rtsp_port" to rtspPort, "http_port" to httpPort,
        "rtsp_sessions" to rtspSessions.get(), "http_sessions" to httpSessions.get(),
        "bytes_to_station" to bytesToStation.get(), "bytes_to_camera" to bytesToCamera.get(),
        "udp_packets" to udpPackets.get(), "refused" to refused.get(), "rtcp_reports" to reports.get(),
        "last_packet_age_ms" to (if (lastPacketAt == 0L) -1L else System.currentTimeMillis() - lastPacketAt),
        "mode" to lastMode, "error" to lastError,
    )

    private fun listen(port: Int, name: String, serve: (Socket) -> Unit): ServerSocket {
        val ss = ServerSocket()
        ss.reuseAddress = true
        ss.bind(InetSocketAddress(listenAddr, port), 8)
        Thread({
            while (running && !ss.isClosed) {
                val s = try { ss.accept() } catch (_: IOException) { break }
                if (!allow(s.inetAddress)) {
                    refused.incrementAndGet()
                    log("refused $name from ${s.inetAddress.hostAddress} - not the station")
                    try { s.close() } catch (_: IOException) {}
                    continue
                }
                Thread({ serve(s) }, "camrelay-$name-session").apply { isDaemon = true }.start()
            }
        }, "camrelay-$name-accept").apply { isDaemon = true }.start()
        return ss
    }

    private fun dialCamera(port: Int): Socket {
        val c = upstream.tcp()
        c.tcpNoDelay = true
        c.connect(InetSocketAddress(cameraHost, port), CONNECT_TIMEOUT_MS)
        return c
    }

    // ----------------------------------------------------------------- HTTP

    private fun httpSession(station: Socket) {
        httpSessions.incrementAndGet()
        open.add(station)
        var cam: Socket? = null
        try {
            station.soTimeout = HTTP_IDLE_MS
            cam = dialCamera(cameraHttpPort)
            open.add(cam)
            cam.soTimeout = HTTP_IDLE_MS
            val a = pump(station.getInputStream(), cam.getOutputStream(), bytesToCamera, listOf(station, cam))
            val b = pump(cam.getInputStream(), station.getOutputStream(), bytesToStation, listOf(station, cam))
            a.join(); b.join()
        } catch (err: Exception) {
            lastError = "http: " + (err.message ?: err.javaClass.simpleName)
        } finally {
            quietClose(station); cam?.let { quietClose(it) }
            httpSessions.decrementAndGet()
        }
    }

    private fun pump(src: InputStream, dst: OutputStream, count: AtomicLong, both: List<Socket>): Thread =
        Thread({
            val buf = ByteArray(16 * 1024)
            try {
                while (true) {
                    val n = src.read(buf)
                    if (n < 0) break
                    dst.write(buf, 0, n)
                    dst.flush()
                    count.addAndGet(n.toLong())
                }
            } catch (_: IOException) {
            } finally {
                // One side done is the conversation done (HTTP/1.0-style camera).
                both.forEach { quietClose(it) }
            }
        }, "camrelay-pump").apply { isDaemon = true; start() }

    // ----------------------------------------------------------------- RTSP

    /** One track of a session: its interleaved channels on the station's
     *  side and, when converted, two UDP sockets on the camera's. What was
     *  last heard from the camera feeds the relay's own receiver reports. */
    private class Track(
        val channels: Pair<Int, Int>,
        val rtp: DatagramSocket? = null, val rtcp: DatagramSocket? = null,
    ) {
        @Volatile var server: Pair<Int, Int>? = null     // camera's RTP/RTCP ports (udp)
        @Volatile var ssrc = 0
        @Volatile var maxSeq = -1
        @Volatile var cycles = 0
        @Volatile var lsr = 0
        @Volatile var lsrAt = 0L
        val udp: Boolean get() = rtp != null

        fun heardRtp(p: ByteArray, off: Int, len: Int) {
            if (len < 12) return
            val seq = ((p[off + 2].toInt() and 0xFF) shl 8) or (p[off + 3].toInt() and 0xFF)
            ssrc = ((p[off + 8].toInt() and 0xFF) shl 24) or ((p[off + 9].toInt() and 0xFF) shl 16) or
                ((p[off + 10].toInt() and 0xFF) shl 8) or (p[off + 11].toInt() and 0xFF)
            if (maxSeq >= 0 && seq < maxSeq && maxSeq - seq > 0x8000) cycles += 0x10000
            if (maxSeq < 0 || seq > maxSeq || maxSeq - seq > 0x8000) maxSeq = seq
        }

        fun heardRtcp(p: ByteArray, off: Int, len: Int) {
            // A sender report: the middle 32 bits of its NTP time are the LSR.
            if (len >= 20 && (p[off + 1].toInt() and 0xFF) == 200) {
                lsr = ((p[off + 10].toInt() and 0xFF) shl 24) or ((p[off + 11].toInt() and 0xFF) shl 16) or
                    ((p[off + 12].toInt() and 0xFF) shl 8) or (p[off + 13].toInt() and 0xFF)
                lsrAt = System.currentTimeMillis()
            }
        }

        fun report(reporter: Int): ByteArray {
            val dlsr = if (lsrAt == 0L) 0 else
                ((System.currentTimeMillis() - lsrAt) * 65536L / 1000L).toInt()
            return RtspText.receiverReport(reporter, ssrc, cycles + maxOf(maxSeq, 0), lsr, dlsr)
        }
    }

    private fun rtspSession(station: Socket) {
        rtspSessions.incrementAndGet()
        open.add(station)
        station.tcpNoDelay = true
        val relayBase = "rtsp://" + (station.localAddress.hostAddress) + ":" + station.localPort
        val cameraBase = "rtsp://$cameraHost:$cameraRtspPort"
        val stationOut = station.getOutputStream()
        val tracks = ConcurrentHashMap<Int, Track>()              // by either channel
        val pending = ConcurrentHashMap<String, Pair<Track?, RtspText.Message>>()   // CSeq -> SETUP
        val socks = ArrayList<Closeable>()
        val reporter = (System.nanoTime() xor 0x5A5A5A5AL).toInt()
        val live = java.util.concurrent.atomic.AtomicBoolean(true)
        var cam: Socket? = null

        fun toStation(bytes: ByteArray) {
            synchronized(stationOut) {
                stationOut.write(bytes)
                stationOut.flush()
            }
            bytesToStation.addAndGet(bytes.size.toLong())
        }

        try {
            cam = dialCamera(cameraRtspPort)
            open.add(cam)
            val camOut = cam.getOutputStream()
            val camIn = DataInputStream(BufferedInputStream(cam.getInputStream(), 64 * 1024))
            val stIn = DataInputStream(BufferedInputStream(station.getInputStream(), 16 * 1024))

            fun toCamera(bytes: ByteArray) {
                synchronized(camOut) {
                    camOut.write(bytes)
                    camOut.flush()
                }
                bytesToCamera.addAndGet(bytes.size.toLong())
            }

            // The relay's receiver reports, as the camera's client, every few seconds.
            Thread({
                while (live.get() && running) {
                    try { Thread.sleep(RR_EVERY_MS) } catch (_: InterruptedException) { break }
                    for (tr in tracks.values.toSet()) {
                        try {
                            val rr = tr.report(reporter)
                            val server = tr.server
                            if (tr.udp && server != null) {
                                tr.rtcp!!.send(DatagramPacket(rr, rr.size, InetSocketAddress(cameraHost, server.second)))
                            } else if (!tr.udp) {
                                toCamera(RtspText.frame(tr.channels.second, rr))
                            }
                            reports.incrementAndGet()
                        } catch (_: IOException) {}
                    }
                }
            }, "camrelay-rtcp-rr").apply { isDaemon = true; start() }

            // camera -> station: responses (re-aimed) and any interleaved frames
            val back = Thread({
                try {
                    while (true) {
                        when (val u = RtspText.read(camIn) ?: break) {
                            is RtspText.Part.Frame -> {
                                tracks[u.channel]?.let { tr ->
                                    if (u.channel == tr.channels.first) tr.heardRtp(u.payload, 0, u.payload.size)
                                    else tr.heardRtcp(u.payload, 0, u.payload.size)
                                }
                                lastPacketAt = System.currentTimeMillis()
                                toStation(RtspText.frame(u.channel, u.payload))
                            }
                            is RtspText.Part.Msg -> {
                                val m = u.m
                                val setup = pending.remove(m.header("CSeq") ?: "")
                                val t = m.header("Transport") ?: ""
                                if (setup != null) {
                                    val (track, asked) = setup
                                    if (track != null && m.status in 200..299 && !RtspText.isTcp(t)) {
                                        track.server = RtspText.serverPorts(t)
                                        m.setHeader("Transport", RtspText.toInterleavedAnswer(t, track.channels))
                                        tracks[track.channels.first] = track
                                        tracks[track.channels.second] = track
                                        startUdpReaders(track, ::toStation)
                                        lastMode = "udp-upstream"
                                    } else if (track != null) {
                                        // The camera would not take UDP: ask again exactly as
                                        // the station did, and that answer goes back as it is.
                                        track.rtp?.let { quietClose(it) }; track.rtcp?.let { quietClose(it) }
                                        log("camera refused UDP (${m.status}) - passing the station's transport through")
                                        pending[asked.header("CSeq") ?: ""] = null to asked
                                        toCamera(asked.bytes())
                                        continue
                                    } else if (m.status in 200..299) {
                                        // Interleaved end to end: still reported on, still counted.
                                        RtspText.interleaved(t)?.let { ch ->
                                            val tr = Track(ch)
                                            tracks[ch.first] = tr; tracks[ch.second] = tr
                                        }
                                        lastMode = "pass"
                                    }
                                }
                                RtspText.responseToStation(m, cameraHost, cameraRtspPort, relayBase)
                                toStation(m.bytes())
                            }
                        }
                    }
                } catch (err: IOException) {
                    if (live.get() && running) lastError = "rtsp camera side: " + (err.message ?: "closed")
                } finally {
                    live.set(false)
                    quietClose(station); cam?.let { quietClose(it) }
                }
            }, "camrelay-rtsp-back").apply { isDaemon = true; start() }

            // station -> camera: requests (re-aimed, transport converted) and RTCP
            while (true) {
                when (val u = RtspText.read(stIn) ?: break) {
                    is RtspText.Part.Frame -> {
                        val tr = tracks[u.channel]
                        val server = tr?.server
                        if (tr != null && tr.udp && server != null) {
                            // Anything the station reports goes to the camera's RTCP port.
                            val isRtcp = u.channel == tr.channels.second
                            val sock = if (isRtcp) tr.rtcp!! else tr.rtp!!
                            val port = if (isRtcp) server.second else server.first
                            try {
                                sock.send(DatagramPacket(u.payload, u.payload.size,
                                    InetSocketAddress(cameraHost, port)))
                                bytesToCamera.addAndGet(u.payload.size.toLong())
                            } catch (_: IOException) {}
                        } else {
                            toCamera(RtspText.frame(u.channel, u.payload))
                        }
                    }
                    is RtspText.Part.Msg -> {
                        val m = u.m
                        m.start = RtspText.requestToCamera(m.start, cameraBase)
                        val t = m.header("Transport")
                        val cseq = m.header("CSeq") ?: ""
                        if (m.method.equals("SETUP", true) && t != null) {
                            val asked = RtspText.Message(m.start, ArrayList(m.headers), m.body)
                            val pair = if (udpUpstream && RtspText.isTcp(t)) udpPair() else null
                            if (pair != null) {
                                socks.add(pair.first); socks.add(pair.second)
                                val channels = RtspText.interleaved(t) ?: (2 * (tracks.size / 2) to 2 * (tracks.size / 2) + 1)
                                pending[cseq] = Track(channels, pair.first, pair.second) to asked
                                m.setHeader("Transport", RtspText.toUdpAsk(t, pair.first.localPort))
                            } else {
                                pending[cseq] = null to asked
                            }
                        }
                        toCamera(m.bytes())
                    }
                }
            }
        } catch (err: IOException) {
            if (live.get() && running) lastError = "rtsp: " + (err.message ?: err.javaClass.simpleName)
        } finally {
            live.set(false)
            quietClose(station); cam?.let { quietClose(it) }
            for (s in socks) quietClose(s)
            rtspSessions.decrementAndGet()
        }
    }

    /** Two UDP sockets on consecutive ports, RTP on the even one, both bound
     *  to the camera's network. null when no pair could be had. */
    private fun udpPair(): Pair<DatagramSocket, DatagramSocket>? {
        repeat(24) {
            val base = 40000 + 2 * ((System.nanoTime() / 1000 % 10000).toInt())
            var a: DatagramSocket? = null
            try {
                a = newUdp(base)
                val b = newUdp(base + 1)
                open.add(a); open.add(b)
                return a to b
            } catch (_: IOException) {
                a?.let { quietClose(it) }
            }
        }
        return null
    }

    private fun newUdp(port: Int): DatagramSocket {
        val s = DatagramSocket(null as java.net.SocketAddress?)
        try {
            upstream.bindUdp(s)
            s.reuseAddress = false
            s.receiveBufferSize = 1 shl 20
            s.bind(InetSocketAddress(port))
            return s
        } catch (err: IOException) {        // SocketException included
            s.close()
            throw err
        }
    }

    private fun startUdpReaders(track: Track, send: (ByteArray) -> Unit) {
        for ((sock, ch) in listOf(track.rtp!! to track.channels.first, track.rtcp!! to track.channels.second)) {
            val isRtp = ch == track.channels.first
            Thread({
                val buf = ByteArray(65536)
                val pkt = DatagramPacket(buf, buf.size)
                try {
                    while (!sock.isClosed) {
                        pkt.setLength(buf.size)
                        sock.receive(pkt)
                        // Only the camera may put packets on the station's connection.
                        if (pkt.address?.hostAddress != cameraHost) continue
                        if (isRtp) track.heardRtp(buf, 0, pkt.length) else track.heardRtcp(buf, 0, pkt.length)
                        udpPackets.incrementAndGet()
                        lastPacketAt = System.currentTimeMillis()
                        send(RtspText.frame(ch, buf, 0, pkt.length))
                    }
                } catch (_: IOException) {
                } finally {
                    quietClose(sock)
                }
            }, "camrelay-udp-$ch").apply { isDaemon = true; start() }
        }
    }

    private fun quietClose(c: Closeable) {
        try { c.close() } catch (_: IOException) {}
        open.remove(c)
    }

    companion object {
        const val CONNECT_TIMEOUT_MS = 4000
        const val HTTP_IDLE_MS = 20000
        const val RR_EVERY_MS = 4000L
    }
}
