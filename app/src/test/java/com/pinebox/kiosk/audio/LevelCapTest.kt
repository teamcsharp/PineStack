package com.pinebox.kiosk.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** "I just don't want the audio to go louder than the level that I have it set at." */
class LevelCapTest {
    @Test fun aLouderNewOutputComesDownToThePreviousLevel() {
        // 2026-09-29 measured: speaker 5, headphone 20
        assertEquals(5, capIndex(previous = 5, next = 20))
        assertEquals(0, capIndex(previous = 0, next = 1))
    }

    @Test fun neverRaisesAndNeverGuesses() {
        assertNull(capIndex(previous = 20, next = 5))
        assertNull(capIndex(previous = 7, next = 7))
        assertNull(capIndex(previous = null, next = 20))
        assertNull(capIndex(previous = 5, next = null))
        assertNull(capIndex(previous = -1, next = 20))
    }
}
