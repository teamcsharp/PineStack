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
        // [aspect-keep] the smallest it may go, still 5:3 (240 wide pins 144 high)
        assertEquals(WallRect(100, 120, 240, 144),
            VideoWallGeometry.resize(start, -900, -900, 1340, 800, 240, 140))
    }

    @Test
    fun aCornerDraggedSidewaysStillKeepsTheShape() {
        // [aspect-keep] a sideways drag scales both sides - never a wider, flatter box
        val start = WallRect(100, 120, 500, 300)
        assertEquals(WallRect(100, 120, 721, 432),
            VideoWallGeometry.resize(start, 300, 0, 1340, 800, 240, 140))
        // bounded by the screen: it stops where the bottom edge is, shape intact
        val big = VideoWallGeometry.resize(start, 2000, 2000, 1340, 800, 240, 140)
        assertEquals(WallRect(100, 120, 1133, 680), big)
    }

    @Test
    fun incomingPageRectCannotHangOffThePhysicalDisplay() {
        assertEquals(WallRect(10, 377, 663, 423),
            VideoWallGeometry.fit(WallRect(10, 405, 663, 423),
                1340, 800, 240, 140))
    }
}
