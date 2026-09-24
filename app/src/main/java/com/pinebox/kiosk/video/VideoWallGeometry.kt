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

    fun resize(start: WallRect, dx: Int, dy: Int, boundWidth: Int, boundHeight: Int,
               minWidth: Int, minHeight: Int): WallRect =
        fit(start.copy(width = start.width + dx, height = start.height + dy),
            boundWidth, boundHeight, minWidth, minHeight)
}
