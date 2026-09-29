package com.pinebox.kiosk.camlink

import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.EOFException
import java.io.IOException
import java.io.InputStream

/**
 * [tabrelay] THE RTSP THE RELAY HAS TO READ, AND NOTHING MORE.
 *
 * The relay forwards bytes. It reads RTSP only because three things in the
 * conversation name an ADDRESS, and an address that is right on the camera's
 * network is wrong on TacoNet:
 *
 *   - URLs. DESCRIBE answers with `Content-Base: rtsp://192.168.1.254:554/live/`
 *     and the SDP's `a=control:` lines are absolute on this camera, so a
 *     reader that follows them would dial 192.168.1.254 from the station -
 *     an address that only exists on the tablet's side-link. Every camera
 *     URL going to the station becomes the relay's, and every relay URL
 *     going to the camera becomes the camera's. RTP-Info too.
 *   - Transport. The station asks for RTP-over-TCP (interleaved), because
 *     UDP cannot cross from the camera's network to TacoNet. But this camera
 *     (LIVE555 "Nvt RTSP") CLOSES an interleaved session at thirty seconds -
 *     measured in pinelink.py #1250b, three runs of three. So by default the
 *     relay asks the CAMERA for plain UDP on its own side and carries the
 *     packets to the station inside the TCP connection itself: the camera
 *     sees a UDP client, the station sees an interleaved server, and neither
 *     finds out about the other. `pass` mode leaves Transport alone.
 *   - Content-Length, which has to follow any body that was rewritten.
 *
 * No codec, no timestamp and no payload byte is touched.
 */
object RtspText {

    /** One RTSP request or response: its first line, its headers in order,
     *  and its body (empty for most). */
    class Message(
        var start: String,
        val headers: MutableList<Pair<String, String>>,
        var body: ByteArray,
    ) {
        val isResponse: Boolean get() = start.startsWith("RTSP/")
        val method: String get() = if (isResponse) "" else start.substringBefore(' ')
        val status: Int
            get() = if (!isResponse) 0
            else start.split(' ').getOrNull(1)?.toIntOrNull() ?: 0

        fun header(name: String): String? =
            headers.firstOrNull { it.first.equals(name, ignoreCase = true) }?.second

        fun setHeader(name: String, value: String) {
            val i = headers.indexOfFirst { it.first.equals(name, ignoreCase = true) }
            if (i >= 0) headers[i] = headers[i].first to value else headers.add(name to value)
        }

        fun removeHeader(name: String) {
            headers.removeAll { it.first.equals(name, ignoreCase = true) }
        }

        /** The wire form. Content-Length always follows the body as it is NOW. */
        fun bytes(): ByteArray {
            if (body.isNotEmpty()) setHeader("Content-Length", body.size.toString())
            else if (header("Content-Length") != null) setHeader("Content-Length", "0")
            val sb = StringBuilder(256)
            sb.append(start).append("\r\n")
            for ((k, v) in headers) sb.append(k).append(": ").append(v).append("\r\n")
            sb.append("\r\n")
            val head = sb.toString().toByteArray(Charsets.ISO_8859_1)
            if (body.isEmpty()) return head
            val out = ByteArray(head.size + body.size)
            System.arraycopy(head, 0, out, 0, head.size)
            System.arraycopy(body, 0, out, head.size, body.size)
            return out
        }
    }

    /** What arrives on an RTSP connection: a message, or an interleaved
     *  binary frame (`$`, channel, 16-bit length, payload). */
    sealed class Part {
        class Msg(val m: Message) : Part()
        class Frame(val channel: Int, val payload: ByteArray) : Part()
    }

    private const val MAX_HEAD = 16 * 1024
    private const val MAX_BODY = 256 * 1024

    /** Read the next unit, or null at a clean end of stream. */
    @Throws(IOException::class)
    fun read(input: DataInputStream): Part? {
        val first = input.read()
        if (first < 0) return null
        if (first == '$'.code) {
            val ch = input.readUnsignedByte()
            val len = input.readUnsignedShort()
            val p = ByteArray(len)
            input.readFully(p)
            return Part.Frame(ch, p)
        }
        // A message: header lines up to the blank line.
        val head = ByteArrayOutputStream(512)
        head.write(first)
        var last4 = first
        while (true) {
            val b = input.read()
            if (b < 0) throw EOFException("the connection closed inside a header")
            head.write(b)
            last4 = (last4 shl 8) or b
            if (last4 == 0x0D0A0D0A) break
            // A bare-LF sender (rare, but LIVE555 accepts it) ends on \n\n.
            if ((last4 and 0xFFFF) == 0x0A0A) break
            if (head.size() > MAX_HEAD) throw IOException("an RTSP header over 16 kB")
        }
        val text = head.toString(Charsets.ISO_8859_1.name())
        val lines = text.split("\n").map { it.trimEnd('\r') }.filter { it.isNotEmpty() }
        if (lines.isEmpty()) throw IOException("an empty RTSP message")
        val headers = ArrayList<Pair<String, String>>()
        for (line in lines.drop(1)) {
            val c = line.indexOf(':')
            if (c <= 0) continue
            headers.add(line.substring(0, c).trim() to line.substring(c + 1).trim())
        }
        val msg = Message(lines[0], headers, ByteArray(0))
        val n = msg.header("Content-Length")?.trim()?.toIntOrNull() ?: 0
        if (n < 0 || n > MAX_BODY) throw IOException("an RTSP body of $n bytes")
        if (n > 0) {
            val body = ByteArray(n)
            input.readFully(body)
            msg.body = body
        }
        return Part.Msg(msg)
    }

    fun frame(channel: Int, payload: ByteArray, off: Int = 0, len: Int = payload.size): ByteArray {
        val out = ByteArray(4 + len)
        out[0] = '$'.code.toByte()
        out[1] = channel.toByte()
        out[2] = (len shr 8).toByte()
        out[3] = len.toByte()
        System.arraycopy(payload, off, out, 4, len)
        return out
    }

    // ------------------------------------------------------------ addresses

    /** `rtsp://host[:port]` at the start of a URL, captured as host and port. */
    private val AUTHORITY = Regex("""(?i)rtsp://([^/\s;,"'>]+?)(?::(\d+))?(?=[/\s;,"'>]|$)""")

    /**
     * Every rtsp:// URL naming [fromHost] (with [fromPort], or no port when
     * that port is the default 554) becomes one naming [toBase], which is
     * `rtsp://host:port` with no trailing slash. Paths and queries are kept.
     */
    fun swapBase(text: String, fromHost: String, fromPort: Int, toBase: String): String =
        AUTHORITY.replace(text) { m ->
            val host = m.groupValues[1]
            val port = m.groupValues[2].toIntOrNull() ?: 554
            if (host.equals(fromHost, ignoreCase = true) && port == fromPort) toBase else m.value
        }

    /** The request line's URL re-aimed at the camera, whatever host the
     *  station used to reach the relay (its IP, a name, a tailnet address). */
    fun requestToCamera(start: String, cameraBase: String): String {
        val parts = start.split(' ')
        if (parts.size < 3) return start
        val url = parts[1]
        val m = AUTHORITY.find(url) ?: return start
        if (m.range.first != 0) return start
        val rest = url.substring(m.range.last + 1)
        return parts[0] + " " + cameraBase + rest + " " + parts.drop(2).joinToString(" ")
    }

    /** Headers that carry a URL back to the reader. */
    private val URL_HEADERS = listOf("Content-Base", "Content-Location", "RTP-Info", "Location")

    /** A response from the camera, made true on TacoNet: every camera URL in
     *  the URL headers and in an SDP body names the relay instead. */
    fun responseToStation(m: Message, cameraHost: String, cameraPort: Int, relayBase: String) {
        for (i in m.headers.indices) {
            val (k, v) = m.headers[i]
            if (URL_HEADERS.any { it.equals(k, ignoreCase = true) }) {
                m.headers[i] = k to swapBase(v, cameraHost, cameraPort, relayBase)
            }
        }
        val ctype = m.header("Content-Type") ?: ""
        if (m.body.isNotEmpty() && ctype.contains("sdp", ignoreCase = true)) {
            val sdp = String(m.body, Charsets.ISO_8859_1)
            val out = swapBase(sdp, cameraHost, cameraPort, relayBase)
            if (out != sdp) m.body = out.toByteArray(Charsets.ISO_8859_1)
        }
    }

    // ------------------------------------------------------------ transport

    /** `interleaved=a-b` from a Transport header, or null. */
    fun interleaved(transport: String): Pair<Int, Int>? {
        val m = Regex("""(?i)interleaved=(\d+)(?:-(\d+))?""").find(transport) ?: return null
        val a = m.groupValues[1].toInt()
        val b = m.groupValues[2].toIntOrNull() ?: (a + 1)
        return a to b
    }

    /** `server_port=a-b` from a Transport header, or null. */
    fun serverPorts(transport: String): Pair<Int, Int>? {
        val m = Regex("""(?i)server_port=(\d+)(?:-(\d+))?""").find(transport) ?: return null
        val a = m.groupValues[1].toInt()
        val b = m.groupValues[2].toIntOrNull() ?: (a + 1)
        return a to b
    }

    fun isTcp(transport: String): Boolean =
        transport.contains("RTP/AVP/TCP", ignoreCase = true) || interleaved(transport) != null

    /** The station's interleaved ask, re-spelled as a UDP ask for the camera:
     *  `RTP/AVP;unicast;client_port=p-q`, keeping any ssrc/mode it named.
     *  Only the first transport of a comma-separated list is used. */
    fun toUdpAsk(transport: String, rtpPort: Int): String {
        val first = transport.split(',')[0]
        val keep = first.split(';').map { it.trim() }.filter { p ->
            val k = p.substringBefore('=').lowercase()
            k == "ssrc" || k == "mode"
        }
        return (listOf("RTP/AVP", "unicast", "client_port=$rtpPort-${rtpPort + 1}") + keep)
            .joinToString(";")
    }

    // ----------------------------------------------------------------- RTCP

    /**
     * An RTCP receiver report (RFC 3550 6.4.2) from [reporter] about [source].
     *
     * WHY THE RELAY WRITES ITS OWN. ffmpeg sends RRs only from a UDP RTCP
     * socket; over interleaved TCP it sends none (rtsp.c passes no handle to
     * ff_rtp_check_and_send_back_rr) - proved on the Spark against the
     * stand-in: 0 RRs in 40 s. LIVE555 counts a client alive on its RRs and
     * its RTSP commands, and this camera drops an interleaved session at
     * thirty seconds while a UDP one (which ffmpeg DOES report on) runs for
     * as long as it is watched. So the relay, which is the camera's client,
     * reports every few seconds as a UDP client would. [source] 0 = nothing
     * heard yet: an empty RR (RC=0), which still says "alive".
     */
    fun receiverReport(
        reporter: Int, source: Int, extHighestSeq: Int,
        lsr: Int, dlsr: Int,
    ): ByteArray {
        if (source == 0) {
            val b = java.nio.ByteBuffer.allocate(8)
            b.put(0x80.toByte()).put(201.toByte()).putShort(1).putInt(reporter)
            return b.array()
        }
        val b = java.nio.ByteBuffer.allocate(32)
        b.put(0x81.toByte()).put(201.toByte()).putShort(7).putInt(reporter)
        b.putInt(source).putInt(0).putInt(extHighestSeq).putInt(0).putInt(lsr).putInt(dlsr)
        return b.array()
    }

    /** RTCP packet type of the first packet in a compound, or -1. */
    fun rtcpType(p: ByteArray, len: Int = p.size): Int =
        if (len >= 2 && (p[0].toInt() and 0xC0) == 0x80) p[1].toInt() and 0xFF else -1

    /** The camera's UDP answer, re-spelled as the interleaved answer the
     *  station asked for: `RTP/AVP/TCP;unicast;interleaved=a-b` plus the
     *  camera's ssrc/mode. The UDP-only parameters (client_port,
     *  server_port, source, destination) are the relay's business, not the
     *  station's, and are dropped. */
    fun toInterleavedAnswer(transport: String, channels: Pair<Int, Int>): String {
        val keep = transport.split(';').map { it.trim() }.filter { p ->
            val k = p.substringBefore('=').lowercase()
            k == "ssrc" || k == "mode"
        }
        return (listOf("RTP/AVP/TCP", "unicast", "interleaved=${channels.first}-${channels.second}") + keep)
            .joinToString(";")
    }
}
