package com.pinebox.kiosk

import com.pinebox.kiosk.video.VideoWallGeometry
import com.pinebox.kiosk.video.WallRect
import org.junit.Assert.assertEquals
import org.junit.Test

class VideoWallGeometryTest {
    @Test
    fun moveTracksTheFingerAndStaysOnScreen() {
        val start = WallRect(100, 120, 500, 300)
        assertEquals(WallRect(180, 165, 500, 300),
            VideoWallGeometry.move(start, 80, 45, 1340, 800, 240, 140))
        assertEquals(WallRect(840, 500, 500, 300),
            VideoWallGeometry.move(start, 5000, 5000, 1340, 800, 240, 140))
    }

    @Test
    fun resizeIsBoundedButDoesNotMoveTheAnchoredCorner() {
        val start = WallRect(100, 120, 500, 300)
        assertEquals(WallRect(100, 120, 650, 390),
            VideoWallGeometry.resize(start, 150, 90, 1340, 800, 240, 140))
        assertEquals(WallRect(100, 120, 240, 140),
            VideoWallGeometry.resize(start, -900, -900, 1340, 800, 240, 140))
    }

    @Test
    fun incomingPageRectCannotHangOffThePhysicalDisplay() {
        assertEquals(WallRect(10, 377, 663, 423),
            VideoWallGeometry.fit(WallRect(10, 405, 663, 423),
                1340, 800, 240, 140))
    }
}
