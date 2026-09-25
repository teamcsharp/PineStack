package com.pinebox.kiosk.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin

class MicTelemetryTest {
    @Test fun spectrumUsesTheRecordedChannel() {
        val telemetry = MicTelemetry(0L)
        val stereo = ShortArray(1024)
        for (i in 0 until 512) {
            stereo[i * 2 + 1] = (sin(2.0 * PI * 1000.0 * i / 16_000.0) * 12_000).toInt().toShort()
        }

        val frame = telemetry.feed(stereo, 512, true, 0.25f, 0.37f, 100L)
        assertEquals("speech", frame.vadState)
        assertEquals(24, frame.bands.size)
        assertTrue(frame.bands.all { it in 0f..1f })
        assertTrue(frame.bands.max() > 0.2f)
        assertTrue(frame.bands[13] > frame.bands[0])

        val leftSamples = ShortArray(1024)
        for (i in 0 until 512) leftSamples[i * 2] = stereo[i * 2 + 1]
        val leftOnly = MicTelemetry(0L).feed(leftSamples, 512, true, 0f, 0f, 100L)
        assertTrue(leftOnly.bands.all { it == 0f })
    }

    @Test fun silenceCountdownStartsOnlyAfterSpeech() {
        val telemetry = MicTelemetry(0L)
        val quiet = ShortArray(512)
        val waiting = telemetry.feed(quiet, 512, false, 0f, 0f, 500L)
        assertEquals("waiting", waiting.vadState)
        assertEquals(0L, waiting.silenceElapsedMs)

        val voice = telemetry.feed(ShortArray(512) { 8000 }, 512, false,
            0.24f, 0.24f, 1000L)
        assertEquals("speech", voice.vadState)
        assertTrue(voice.speechProbability > 0.5f)

        val quietAfter = telemetry.feed(quiet, 512, false, 0f, 0f, 1100L)
        assertEquals("silence", quietAfter.vadState)
        assertEquals(100L, quietAfter.silenceElapsedMs)
        assertEquals(4100L, quietAfter.remainingMs)
        assertEquals("endpoint", quietAfter.at(5200L).vadState)
        assertEquals(0L, quietAfter.at(5200L).remainingMs)
    }
}
