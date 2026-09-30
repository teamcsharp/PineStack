package com.pinebox.kiosk.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [smart-reinit] The tablet's own audio verdict, against the dumps measured
 * on the PineTab 2026-09-30 (`dumpsys media.audio_flinger` / `dumpsys audio`,
 * kiosk pid 14328). The captured-not-rendered fixture is that dump with the
 * headphone threads' active tracks gone and the remote-submix patch tracks
 * kept - the fault as it was measured the same day.
 */
class AudioHealthTest {

    private fun fixture(name: String): String =
        javaClass.getResource("/audio/$name")!!.readText()

    private val kiosk = 14328
    private val players by lazy { AudioHealth.parsePlayers(fixture("audio_players_2026_09_30.txt")) }

    @Test
    fun theThreadBlockSurvivesItsFlushLeftLines() {
        // "Bluetooth latency modes are not enabled" sits flush left between
        // a thread's devices and its track count; it must not end the thread.
        val threads = AudioHealth.parseFlinger(fixture("flinger_2026_09_30_rendering.txt"))
        val head = threads.first { it.name == "AudioOut_15" }
        assertTrue(head.devices.contains("AUDIO_DEVICE_OUT_WIRED_HEADPHONE"))
        assertEquals(2, head.active)
        assertEquals(listOf(kiosk, kiosk), head.activeClients)
        assertTrue(head.audible)
        val submix = threads.first { it.name == "AudioOut_5D" }
        assertTrue(submix.submix)
        assertEquals(2, submix.active)
        assertEquals(listOf(1266, 1266), submix.activeClients)
        // the input thread is not an output thread
        assertTrue(threads.none { it.name == "AudioIn_76" })
        assertTrue(threads.first { it.name == "AudioOut_1D" }.let { !it.audible })
    }

    @Test
    fun rendering() {
        val (verdict, say) = AudioHealth.judge(
            AudioHealth.parseFlinger(fixture("flinger_2026_09_30_rendering.txt")), players, kiosk,
            "the aux cable")
        assertEquals(AudioHealth.Verdict.RENDERING, verdict)
        assertTrue(say, say.contains("the headphones"))
    }

    @Test
    fun capturedNotRendered() {
        val (verdict, say) = AudioHealth.judge(
            AudioHealth.parseFlinger(fixture("flinger_2026_09_30_captured_not_rendered.txt")),
            players, kiosk, "the aux cable")
        assertEquals(AudioHealth.Verdict.CAPTURED_NOT_RENDERED, verdict)
        assertTrue(say, say.contains("remote submix") && say.contains("the aux cable"))
    }

    @Test
    fun everyOutputIdleIsNotRendered() {
        val (verdict, _) = AudioHealth.judge(
            AudioHealth.parseFlinger(fixture("flinger_all_idle.txt")), players, kiosk, "the speaker")
        assertEquals(AudioHealth.Verdict.NOT_RENDERED, verdict)
    }

    @Test
    fun noStartedPlayerAndNothingHeard() {
        val (verdict, _) = AudioHealth.judge(
            AudioHealth.parseFlinger(fixture("flinger_all_idle.txt")), players, 999, "the speaker")
        assertEquals(AudioHealth.Verdict.NO_PLAYER, verdict)
        assertEquals(AudioHealth.Verdict.UNKNOWN, AudioHealth.judge(emptyList(), players, kiosk, "").first)
    }

    @Test
    fun playersAreParsedOnceEach() {
        val mine = players.filter { it.pid == kiosk }
        assertEquals(3, mine.size)
        val media = mine.first { it.piid == 751 }
        assertEquals(94, media.deviceId)
        assertEquals("started", media.state)
        assertEquals("USAGE_MEDIA", media.usage)
        assertEquals(2, mine.count { it.state == "started" })
    }
}
