package com.pinebox.kiosk.camlink

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.DataInputStream

/** [tabrelay] The RTSP the relay rewrites, one rule at a time. */
class RtspTextTest {

    private val cam = "192.168.1.254"
    private val relay = "rtsp://10.89.1.154:8554"

    private fun parse(s: String): RtspText.Message =
        (RtspText.read(DataInputStream(ByteArrayInputStream(s.toByteArray(Charsets.ISO_8859_1))))
            as RtspText.Part.Msg).m

    @Test fun requestLineIsReAimedAtTheCameraWhateverHostTheStationUsed() {
        assertEquals("DESCRIBE rtsp://192.168.1.254:554/live RTSP/1.0",
            RtspText.requestToCamera("DESCRIBE rtsp://10.89.1.154:8554/live RTSP/1.0", "rtsp://192.168.1.254:554"))
        assertEquals("SETUP rtsp://192.168.1.254:554/live/track1 RTSP/1.0",
            RtspText.requestToCamera("SETUP rtsp://pinetab:8554/live/track1 RTSP/1.0", "rtsp://192.168.1.254:554"))
        assertEquals("OPTIONS * RTSP/1.0",
            RtspText.requestToCamera("OPTIONS * RTSP/1.0", "rtsp://192.168.1.254:554"))
    }

    @Test fun contentBaseAndSdpControlLinesNameTheRelay() {
        val sdp = "v=0\r\no=- 1 1 IN IP4 192.168.1.254\r\ns=Nvt\r\nt=0 0\r\n" +
            "a=control:rtsp://192.168.1.254:554/live/\r\nm=video 0 RTP/AVP 96\r\n" +
            "a=control:rtsp://192.168.1.254/live/track1\r\n"
        val m = parse("RTSP/1.0 200 OK\r\nCSeq: 2\r\nContent-Base: rtsp://192.168.1.254:554/live/\r\n" +
            "Content-Type: application/sdp\r\nContent-Length: ${sdp.length}\r\n\r\n$sdp")
        RtspText.responseToStation(m, cam, 554, relay)
        assertEquals("rtsp://10.89.1.154:8554/live/", m.header("Content-Base"))
        val body = String(m.body, Charsets.ISO_8859_1)
        assertTrue(body.contains("a=control:rtsp://10.89.1.154:8554/live/\r\n"))
        // no port in the camera's URL means 554, and it is rewritten too
        assertTrue(body.contains("a=control:rtsp://10.89.1.154:8554/live/track1\r\n"))
        assertFalse(body.contains("rtsp://192.168.1.254"))
        // the o= line is not a URL and is left alone
        assertTrue(body.contains("o=- 1 1 IN IP4 192.168.1.254"))
        // Content-Length follows the rewritten body
        val wire = String(m.bytes(), Charsets.ISO_8859_1)
        assertTrue(wire.contains("Content-Length: ${m.body.size}\r\n"))
        assertEquals(m.body.size, wire.substringAfter("\r\n\r\n").length)
    }

    @Test fun rtpInfoIsRewrittenAndOtherHostsAreNot() {
        val m = parse("RTSP/1.0 200 OK\r\nCSeq: 5\r\n" +
            "RTP-Info: url=rtsp://192.168.1.254:554/live/track1;seq=1;rtptime=0,url=rtsp://10.0.0.9/x;seq=2\r\n\r\n")
        RtspText.responseToStation(m, cam, 554, relay)
        assertEquals("url=rtsp://10.89.1.154:8554/live/track1;seq=1;rtptime=0,url=rtsp://10.0.0.9/x;seq=2",
            m.header("RTP-Info"))
        // another port on the camera is a different server
        assertEquals("rtsp://192.168.1.254:8554/x", RtspText.swapBase("rtsp://192.168.1.254:8554/x", cam, 554, relay))
    }

    @Test fun interleavedAskBecomesAUdpAskAndTheAnswerComesBackInterleaved() {
        val ask = "RTP/AVP/TCP;unicast;interleaved=0-1"
        assertTrue(RtspText.isTcp(ask))
        assertEquals(0 to 1, RtspText.interleaved(ask))
        assertEquals("RTP/AVP;unicast;client_port=40000-40001", RtspText.toUdpAsk(ask, 40000))
        val answer = "RTP/AVP;unicast;destination=192.168.1.100;source=192.168.1.254;" +
            "client_port=40000-40001;server_port=6970-6971;ssrc=1A2B3C4D"
        assertFalse(RtspText.isTcp(answer))
        assertEquals(6970 to 6971, RtspText.serverPorts(answer))
        assertEquals("RTP/AVP/TCP;unicast;interleaved=0-1;ssrc=1A2B3C4D",
            RtspText.toInterleavedAnswer(answer, 0 to 1))
        assertNull(RtspText.interleaved(answer))
    }

    @Test fun framesAndMessagesShareOneStream() {
        val bytes = byteArrayOf('$'.code.toByte(), 1, 0, 3, 9, 8, 7) +
            "GET_PARAMETER rtsp://x/live RTSP/1.0\r\nCSeq: 9\r\n\r\n".toByteArray()
        val input = DataInputStream(ByteArrayInputStream(bytes))
        val f = RtspText.read(input) as RtspText.Part.Frame
        assertEquals(1, f.channel)
        assertEquals(listOf<Byte>(9, 8, 7), f.payload.toList())
        val m = (RtspText.read(input) as RtspText.Part.Msg).m
        assertEquals("GET_PARAMETER", m.method)
        assertEquals("9", m.header("cseq"))
        assertNull(RtspText.read(input))
        assertEquals(listOf<Byte>('$'.code.toByte(), 3, 0, 2, 5, 6), RtspText.frame(3, byteArrayOf(5, 6)).toList())
    }

    @Test fun receiverReportIsAValidRr() {
        val empty = RtspText.receiverReport(0x11223344, 0, 0, 0, 0)
        assertEquals(8, empty.size)
        assertEquals(201, RtspText.rtcpType(empty))
        assertEquals(0x80, empty[0].toInt() and 0xFF)
        val rr = RtspText.receiverReport(0x11223344, 0x1A2B3C4D, 70000, 0x55667788, 65536)
        assertEquals(32, rr.size)
        assertEquals(0x81, rr[0].toInt() and 0xFF)
        assertEquals(7, rr[3].toInt())                 // length in words - 1
        assertEquals(0x1A, rr[8].toInt() and 0xFF)     // the source's SSRC
    }

    @Test fun receiverCompoundContainsPaddedCnameForTheReporter() {
        for (source in listOf(0, 0x1A2B3C4D)) {
            val packet = RtspText.receiverCompound(0x11223344, source, 70000, 0, 0)
            val offset = if (source == 0) 8 else 32
            val sdes = java.nio.ByteBuffer.wrap(packet, offset, packet.size - offset)
            assertEquals(0x81, sdes.get().toInt() and 0xFF)
            assertEquals(202, sdes.get().toInt() and 0xFF)
            assertEquals(packet.size - offset, (sdes.short.toInt() + 1) * 4)
            assertEquals(0x11223344, sdes.int)
            assertEquals(1, sdes.get().toInt())
            val name = ByteArray(sdes.get().toInt() and 0xFF); sdes.get(name)
            assertEquals("pinecam-11223344", String(name, Charsets.US_ASCII))
            assertEquals(0, sdes.get().toInt())
            assertEquals(0, packet.size % 4)
        }
    }
}
