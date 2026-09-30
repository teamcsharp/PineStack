package com.pinebox.kiosk.camlink

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.BufferedInputStream
import java.io.DataInputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger

/**
 * [tabrelay] The relay end to end inside the JVM: a stand-in camera that
 * answers like LIVE555 (absolute Content-Base, UDP or interleaved SETUP) and
 * sends real UDP packets, a "station" that speaks interleaved RTSP to the
 * relay - and what each of them sees. (The Spark harness runs the same
 * relay against ffmpeg/ffprobe; see the tabrelay notes.)
 */
class CamRelayTest {

    private val lo = InetAddress.getByName("127.0.0.1")
    private val closers = CopyOnWriteArrayList<AutoCloseable>()

    @After fun tidy() { closers.forEach { runCatching { it.close() } } }

    /** The stand-in camera. Records every request line and Transport it saw. */
    private inner class Camera(private val acceptUdp: Boolean = true) {
        val server = ServerSocket(0, 4, lo).also { closers.add(it) }
        val http = ServerSocket(0, 4, lo).also { closers.add(it) }
        val rtcpIn = DatagramSocket(0, lo).also { closers.add(it) }
        val rtpOut = DatagramSocket(0, lo).also { closers.add(it) }
        val seen = CopyOnWriteArrayList<String>()
        val transports = CopyOnWriteArrayList<String>()
        val rrs = AtomicInteger(0)
        @Volatile var clientPort = 0
        val base get() = "rtsp://127.0.0.1:${server.localPort}/live/"

        init {
            Thread { serve() }.apply { isDaemon = true }.start()
            Thread {
                val b = ByteArray(2048)
                while (!rtcpIn.isClosed) try {
                    val p = DatagramPacket(b, b.size); rtcpIn.receive(p)
                    if (RtspText.rtcpType(b, p.length) == 201) rrs.incrementAndGet()
                } catch (_: Exception) { break }
            }.apply { isDaemon = true }.start()
            Thread {
                val s = http.accept(); closers.add(s)
                val req = s.getInputStream().bufferedReader().readLine() ?: ""
                seen.add("HTTP " + req)
                s.getOutputStream().write(("HTTP/1.0 200 OK\r\nContent-Type: text/xml\r\n\r\n" +
                    "<Function><Cmd>3019</Cmd><Status>0</Status><Value>2</Value></Function>").toByteArray())
                s.close()
            }.apply { isDaemon = true }.start()
        }

        private fun serve() {
            val s = server.accept(); closers.add(s)
            val input = DataInputStream(BufferedInputStream(s.getInputStream()))
            val out = s.getOutputStream()
            fun reply(cseq: String, extra: String, body: String = "") {
                val len = if (body.isEmpty()) "" else "Content-Length: ${body.length}\r\n"
                out.write("RTSP/1.0 200 OK\r\nCSeq: $cseq\r\n$extra$len\r\n$body".toByteArray()); out.flush()
            }
            while (true) {
                val u = try { RtspText.read(input) } catch (_: Exception) { null } ?: break
                if (u !is RtspText.Part.Msg) continue
                val m = u.m
                seen.add(m.start)
                val cseq = m.header("CSeq") ?: "0"
                when (m.method) {
                    "DESCRIBE" -> {
                        val sdp = "v=0\r\nm=video 0 RTP/AVP 96\r\na=control:${base}track1\r\n"
                        reply(cseq, "Content-Base: $base\r\nContent-Type: application/sdp\r\n", sdp)
                    }
                    "SETUP" -> {
                        val t = m.header("Transport") ?: ""
                        transports.add(t)
                        if (RtspText.isTcp(t)) {
                            reply(cseq, "Transport: RTP/AVP/TCP;unicast;interleaved=0-1;ssrc=01020304\r\nSession: 42\r\n")
                        } else if (acceptUdp) {
                            clientPort = Regex("client_port=(\\d+)").find(t)!!.groupValues[1].toInt()
                            reply(cseq, "Transport: RTP/AVP;unicast;client_port=$clientPort-${clientPort + 1};" +
                                "server_port=${rtpOut.localPort}-${rtcpIn.localPort};ssrc=01020304\r\nSession: 42\r\n")
                        } else {
                            out.write("RTSP/1.0 461 Unsupported Transport\r\nCSeq: $cseq\r\n\r\n".toByteArray()); out.flush()
                        }
                    }
                    "PLAY" -> {
                        reply(cseq, "Session: 42\r\nRTP-Info: url=${base}track1;seq=1\r\n")
                        if (clientPort > 0) Thread {
                            for (i in 0 until 20) {
                                val rtp = ByteArray(40)
                                rtp[0] = 0x80.toByte(); rtp[1] = 96; rtp[3] = i.toByte()
                                rtp[8] = 1; rtp[9] = 2; rtp[10] = 3; rtp[11] = 4
                                rtpOut.send(DatagramPacket(rtp, rtp.size, InetSocketAddress(lo, clientPort)))
                                Thread.sleep(10)
                            }
                        }.apply { isDaemon = true }.start()
                    }
                    else -> reply(cseq, "")
                }
            }
        }
    }

    private fun relayFor(cam: Camera, udp: Boolean = true): CamRelay =
        CamRelay(CamRelay.Plain, lo, rtspPort = 0.freePort(), httpPort = 0.freePort(),
            cameraHost = "127.0.0.1", cameraRtspPort = cam.server.localPort,
            cameraHttpPort = cam.http.localPort, udpUpstream = udp).also { it.start(); closers.add(it) }

    private fun Int.freePort(): Int = ServerSocket(0, 1, lo).use { it.localPort }

    private class Station(port: Int) {
        val s = Socket(InetAddress.getByName("127.0.0.1"), port).apply { soTimeout = 5000 }
        val input = DataInputStream(BufferedInputStream(s.getInputStream()))
        var cseq = 0
        fun ask(method: String, url: String, extra: String = ""): RtspText.Message {
            cseq++
            s.getOutputStream().write("$method $url RTSP/1.0\r\nCSeq: $cseq\r\n$extra\r\n".toByteArray())
            while (true) {
                val u = RtspText.read(input)!!
                if (u is RtspText.Part.Msg) return u.m
            }
        }
    }

    @Test fun interleavedStationUdpCameraAndEveryAddressReAimed() {
        val cam = Camera()
        val relay = relayFor(cam)
        val st = Station(relay.rtspPort)
        val url = "rtsp://127.0.0.1:${relay.rtspPort}/live"
        val d = st.ask("DESCRIBE", url)
        val relayBase = "rtsp://127.0.0.1:${relay.rtspPort}/live/"
        assertEquals(relayBase, d.header("Content-Base"))
        assertTrue(String(d.body).contains("a=control:${relayBase}track1"))
        // the camera saw ITS URL, not the relay's
        assertTrue(cam.seen.any { it == "DESCRIBE rtsp://127.0.0.1:${cam.server.localPort}/live RTSP/1.0" })

        val su = st.ask("SETUP", relayBase + "track1", "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n")
        assertEquals("RTP/AVP/TCP;unicast;interleaved=0-1;ssrc=01020304", su.header("Transport"))
        assertTrue("the camera was asked for UDP", cam.transports.single().startsWith("RTP/AVP;unicast;client_port="))

        val play = st.ask("PLAY", url, "Session: 42\r\n")
        assertEquals("url=${relayBase}track1;seq=1", play.header("RTP-Info"))
        // twenty UDP packets from the camera arrive as interleaved frames on channel 0
        var frames = 0
        while (frames < 20) {
            val u = RtspText.read(st.input)!!
            if (u is RtspText.Part.Frame) { assertEquals(0, u.channel); assertEquals(40, u.payload.size); frames++ }
        }
        assertEquals("udp-upstream", relay.lastMode)
        // and the relay reports to the camera as its UDP client would
        val deadline = System.currentTimeMillis() + CamRelay.RR_EVERY_MS + 3000
        while (cam.rrs.get() == 0 && System.currentTimeMillis() < deadline) Thread.sleep(100)
        assertTrue("an RTCP RR reached the camera", cam.rrs.get() > 0)
    }

    @Test fun aCameraThatRefusesUdpIsAskedAgainAsTheStationAsked() {
        val cam = Camera(acceptUdp = false)
        val relay = relayFor(cam)
        val st = Station(relay.rtspPort)
        val su = st.ask("SETUP", "rtsp://127.0.0.1:${relay.rtspPort}/live/track1",
            "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n")
        assertEquals(200, su.status)
        assertEquals("RTP/AVP/TCP;unicast;interleaved=0-1;ssrc=01020304", su.header("Transport"))
        assertEquals(2, cam.transports.size)
        assertTrue(RtspText.isTcp(cam.transports[1]))
        assertEquals("pass", relay.lastMode)
    }

    @Test fun httpIsABytePumpToTheCameraApi() {
        val cam = Camera()
        val relay = relayFor(cam)
        val s = Socket(lo, relay.httpPort)
        s.getOutputStream().write("GET /?custom=1&cmd=3019 HTTP/1.0\r\nHost: tablet:8580\r\n\r\n".toByteArray())
        val body = s.getInputStream().readBytes().toString(Charsets.UTF_8)
        assertTrue(body.contains("<Value>2</Value>"))
        assertTrue(cam.seen.contains("HTTP GET /?custom=1&cmd=3019 HTTP/1.0"))
    }

    @Test fun onlyTheStationMayConnect() {
        val cam = Camera()
        val relay = CamRelay(CamRelay.Plain, lo, rtspPort = 0.freePort(), httpPort = 0.freePort(),
            cameraHost = "127.0.0.1", cameraRtspPort = cam.server.localPort, cameraHttpPort = cam.http.localPort,
            allow = { false }).also { it.start(); closers.add(it) }
        val s = Socket(lo, relay.httpPort)
        s.soTimeout = 3000
        assertEquals(-1, s.getInputStream().read())
        Thread.sleep(100)
        assertEquals(1L, relay.refused.get())
        assertFalse(cam.seen.any { it.startsWith("HTTP") })
    }
}
