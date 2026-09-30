package com.pinebox.kiosk.video

/** Pure geometry for the native video wall's touch path. */
data class WallRect(val x: Int, val y: Int, val width: Int, val height: Int)

object VideoWallGeometry {
    fun fit(rect: WallRect, boundWidth: Int, boundHeight: Int,
            minWidth: Int, minHeight: Int): WallRect {
        val bw = boundWidth.coerceAtLeast(1)
        val bh = boundHeight.coerceAtLeast(1)
        val w = rect.width.coerceIn(minWidth.coerceAtMost(bw), bw)
        val h = rect.height.coerceIn(minHeight.coerceAtMost(bh), bh)
        val x = rect.x.coerceIn(0, (bw - w).coerceAtLeast(0))
        val y = rect.y.coerceIn(0, (bh - h).coerceAtLeast(0))
        return WallRect(x, y, w, h)
    }

    fun move(start: WallRect, dx: Int, dy: Int, boundWidth: Int, boundHeight: Int,
             minWidth: Int, minHeight: Int): WallRect =
        fit(start.copy(x = start.x + dx, y = start.y + dy),
            boundWidth, boundHeight, minWidth, minHeight)

    /** [aspect-keep] "through the corner, always maintain the aspect ratio" -
     *  the corner scales the window along its own diagonal (the finger's move
     *  projected onto it), bounded by the screen and the minimum size, so its
     *  shape never changes. The anchored corner stays where it was. */
    fun resize(start: WallRect, dx: Int, dy: Int, boundWidth: Int, boundHeight: Int,
               minWidth: Int, minHeight: Int): WallRect {
        val w0 = start.width.coerceAtLeast(1).toDouble()
        val h0 = start.height.coerceAtLeast(1).toDouble()
        var s = 1.0 + (dx * w0 + dy * h0) / (w0 * w0 + h0 * h0)
        val sMax = minOf((boundWidth - start.x).coerceAtLeast(1) / w0,
                         (boundHeight - start.y).coerceAtLeast(1) / h0)
        val sMin = minOf(sMax, maxOf(minWidth / w0, minHeight / h0))
        s = s.coerceIn(sMin, sMax)
        return fit(start.copy(width = Math.round(w0 * s).toInt(), height = Math.round(h0 * s).toInt()),
            boundWidth, boundHeight, minWidth, minHeight)
    }
}
