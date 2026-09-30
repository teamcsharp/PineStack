package com.pinebox.kiosk.audio

import android.content.Context
import android.media.AudioManager
import android.util.Log
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * [smart-reinit] IS THIS TABLET ACTUALLY RENDERING WHAT IT PLAYS?
 *
 * Measured 2026-09-30, the fault no page reading could see: the replay ring's
 * playback capture (PlaybackLoopback - an AudioPolicy mix with
 * ROUTE_FLAG_RENDER|LOOP_BACK over USAGE_MEDIA/GAME/UNKNOWN) left the kiosk's
 * streams going ONLY to AUDIO_DEVICE_OUT_REMOTE_SUBMIX after the headphones
 * were plugged in (stream_devices_changed 2 -> 8). `dumpsys media.audio_flinger`
 * showed the only active tracks were patch tracks on the REMOTE_SUBMIX thread
 * and none on the headphone thread; every player on the page was playing, the
 * meters moved, and the operator heard nothing. A kiosk restart re-registered
 * the policy and the headphone path came back.
 *
 * And the older one (MediaFocus): every output thread in standby, no active
 * track at all, while the WebView advanced its media clock.
 *
 * The kiosk is platform-signed and holds DUMP, so it can ask the same two
 * dumps the diagnosis was made from - the idiom JackWatch already uses for
 * `dumpsys input`. Parsing and judging are pure (unit-tested against the
 * measured dumps); only [read] touches the device. READ-ONLY: nothing here
 * changes a route, a volume or a stream.
 */
object AudioHealth {

    private const val TAG = "PineAudioHealth"

    /** One output thread of audio_flinger's dump. */
    data class OutThread(
        val name: String,
        val type: String,
        val devices: String,
        val standby: Boolean,
        val active: Int,
        /** Client pids of the rows marked active in its track table. */
        val activeClients: List<Int>,
    ) {
        val submix: Boolean get() = devices.contains("REMOTE_SUBMIX")
        /** A thread that ends at something a person can hear. */
        val audible: Boolean get() = devices.contains("AUDIO_DEVICE_OUT_") && !submix
            && !devices.contains("TELEPHONY_TX") && !devices.contains("OUT_BUS")
        val mmap: Boolean get() = type.contains("MMAP")
        val busy: Boolean get() = active > 0 || (mmap && !standby)
    }

    /** One AudioPlaybackConfiguration line of `dumpsys audio`. */
    data class Player(val piid: Int, val deviceId: Int, val pid: Int,
                      val state: String, val usage: String)

    enum class Verdict { RENDERING, CAPTURED_NOT_RENDERED, NOT_RENDERED, NO_PLAYER, UNKNOWN }

    data class Reading(
        val verdict: Verdict,
        val say: String,
        val route: String,
        val musicIndex: Int,
        val musicMax: Int,
        val musicMuted: Boolean,
        val players: Int,
        val threads: List<OutThread>,
    ) {
        fun toJson(): JSONObject = JSONObject()
            .put("verdict", verdict.name).put("say", say).put("route", route)
            .put("music_index", musicIndex).put("music_max", musicMax)
            .put("music_muted", musicMuted).put("players", players)
            .put("threads", threads.filter { it.busy }.joinToString("; ") {
                it.name + " " + it.devices + " x" + it.active
            })
    }

    private val THREAD_HEAD = Regex("""^Output thread \S+ name ([^,\s]+), tid \d+, type \d+ \(([^)]*)\)""")
    /** Any other thread's header (Input, Mmap...) - it ends an output thread. */
    private val OTHER_THREAD = Regex("""^\w[\w ]* thread 0x""")
    /** A flush-left section header such as "Patches:". */
    private val SECTION = Regex("""^[A-Z][A-Za-z ]*:$""")
    private val TRACKS = Regex("""^\s+(\d+) Tracks(?: of which (\d+) are active)?""")
    private val DEVICES = Regex("""^\s+Output devices:\s*(.*)$""")
    private val STANDBY = Regex("""^\s+Standby:\s*(yes|no)""")
    /* A track row: an optional type column (F2, P, ...), the id, Active,
     * then the client pid. Normal tracks leave the type column blank. */
    private val TRACK_ROW = Regex("""^\s+(?:[A-Z][A-Z0-9]*\s+)?(\d+)\s+(yes|no)\s+(\d+)\s""")
    private val PLAYER = Regex(
        """AudioPlaybackConfiguration piid:(\d+) deviceId:(\d+) type:\S+ u/pid:\d+/(\d+) state:(\S+) attr:AudioAttributes: usage=(\S+)""")

    /** audio_flinger's output threads, in dump order. */
    fun parseFlinger(dump: String): List<OutThread> {
        val out = mutableListOf<OutThread>()
        var name: String? = null
        var type = ""
        var devices = ""
        var standby = true
        var active = 0
        var inTable = false
        val clients = mutableListOf<Int>()
        fun flush() {
            val n = name ?: return
            out.add(OutThread(n, type, devices, standby, active, clients.toList()))
            name = null
        }
        for (line in dump.lineSequence()) {
            if (line.isNotEmpty() && !line[0].isWhitespace()) {
                /* MEASURED: a thread's block is NOT contiguous indented text.
                 * "Bluetooth latency modes are not enabled" and "Supported
                 * latency modes: { }" are printed flush left in the MIDDLE of
                 * it, before the "N Tracks of which M are active" line. So
                 * only another thread's header, or a section header ending in
                 * a colon ("USB audio module:", "Patches:"), ends a thread. */
                val head = THREAD_HEAD.find(line)
                if (head != null || OTHER_THREAD.containsMatchIn(line) || SECTION.matches(line.trimEnd())) {
                    flush()
                    inTable = false
                }
                if (head != null) {
                    name = head.groupValues[1]
                    type = head.groupValues[2]
                    devices = ""; standby = true; active = 0; clients.clear()
                }
                continue
            }
            if (name == null) continue
            val dev = DEVICES.find(line)
            if (dev != null) {
                devices = dev.groupValues[1].trim()
                inTable = false
                continue
            }
            val idle = STANDBY.find(line)
            if (idle != null) {
                standby = idle.groupValues[1] == "yes"
                continue
            }
            val tracks = TRACKS.find(line)
            if (tracks != null) {
                active = tracks.groupValues[2].toIntOrNull() ?: 0
                inTable = true
                continue
            }
            if (inTable) {
                val row = TRACK_ROW.find(line)
                if (row != null) {
                    if (row.groupValues[2] == "yes") row.groupValues[3].toIntOrNull()?.let { clients.add(it) }
                } else if (!line.trimStart().startsWith("Type")) {
                    inTable = false
                }
            }
        }
        flush()
        return out
    }

    fun parsePlayers(dump: String): List<Player> {
        val seen = LinkedHashMap<Int, Player>()
        for (m in PLAYER.findAll(dump)) {
            val p = Player(m.groupValues[1].toInt(), m.groupValues[2].toInt(),
                m.groupValues[3].toInt(), m.groupValues[4], m.groupValues[5])
            seen[p.piid] = p           // the dump lists the ring twice; last wins
        }
        return seen.values.toList()
    }

    /**
     * The verdict, from what the two dumps say about THIS process.
     *
     * RENDERING - a thread that ends at a real output has active tracks.
     * CAPTURED_NOT_RENDERED - the kiosk is playing, the remote-submix thread
     *   (the capture) is busy, and no audible thread is: the 09-30 fault.
     * NOT_RENDERED - the kiosk is playing and every thread is idle: the
     *   MediaFocus fault.
     * NO_PLAYER - the kiosk has no started player at all.
     */
    fun judge(threads: List<OutThread>, players: List<Player>, myPid: Int,
              route: String): Pair<Verdict, String> {
        if (threads.isEmpty()) return Verdict.UNKNOWN to "the audio dump could not be read"
        val mine = players.filter { it.pid == myPid && it.state == "started" }
        val heard = threads.filter { it.audible && it.busy }
        val capture = threads.filter { it.submix && it.busy }
        return when {
            heard.isNotEmpty() -> Verdict.RENDERING to
                ("the tablet is rendering to " + heard.joinToString(", ") { friendly(it.devices) })
            mine.isEmpty() -> Verdict.NO_PLAYER to
                "this app has no audio stream playing on the tablet at all"
            capture.isNotEmpty() -> Verdict.CAPTURED_NOT_RENDERED to
                ("the tablet's sound is being CAPTURED but not rendered: the replay ring's " +
                    "playback capture holds it on the remote submix and nothing reaches " + route)
            else -> Verdict.NOT_RENDERED to
                "this app is playing but every output on the tablet is idle - nothing is rendered"
        }
    }

    fun friendly(devices: String): String = when {
        devices.contains("WIRED_HEADPHONE") -> "the headphones"
        devices.contains("WIRED_HEADSET") -> "the headset"
        devices.contains("SPEAKER") -> "the speaker"
        devices.contains("USB") -> "the USB output"
        devices.contains("BLUETOOTH") -> "Bluetooth"
        devices.contains("LINE") -> "the line out"
        else -> devices.substringAfter("(").substringBefore(")").ifBlank { devices }
    }

    /** Both dumps plus the media volume on the current route. Off the main
     *  thread: a dump is a process and a few hundred milliseconds. */
    fun read(context: Context, route: String): Reading {
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val index = runCatching { audio.getStreamVolume(AudioManager.STREAM_MUSIC) }.getOrDefault(-1)
        val max = runCatching { audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC) }.getOrDefault(-1)
        val muted = runCatching { audio.isStreamMute(AudioManager.STREAM_MUSIC) }.getOrDefault(false)
        val threads = parseFlinger(dump("media.audio_flinger"))
        val players = parsePlayers(dump("audio"))
        val (verdict, say) = judge(threads, players, android.os.Process.myPid(), route)
        return Reading(verdict, say, route, index, max, muted,
            players.count { it.pid == android.os.Process.myPid() && it.state == "started" }, threads)
    }

    private fun dump(service: String): String = runCatching {
        val proc = ProcessBuilder("/system/bin/dumpsys", service).redirectErrorStream(true).start()
        try {
            val text = StringBuilder()
            val reader = proc.inputStream.bufferedReader()
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(4)
            while (System.nanoTime() < deadline) {
                val line = reader.readLine() ?: break
                text.append(line).append('\n')
                if (text.length > 2_000_000) break
            }
            text.toString()
        } finally {
            proc.destroy()
        }
    }.getOrElse {
        Log.w(TAG, "dumpsys $service failed: " + it.message)
        ""
    }
}
