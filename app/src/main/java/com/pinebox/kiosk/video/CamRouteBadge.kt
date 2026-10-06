package com.pinebox.kiosk.video

import android.content.Context
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.PorterDuff
import android.graphics.RectF
import android.view.Gravity
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout

/** Small route icon above the native video, also visible with its header folded. */
class CamRouteBadge(context: Context) : SurfaceView(context), SurfaceHolder.Callback {
    private val dp = resources.displayMetrics.density
    private val background = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(163, 5, 8, 10) }
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(207, 224, 230)
        style = Paint.Style.STROKE
        strokeWidth = 1.7f
        strokeJoin = Paint.Join.ROUND
        strokeCap = Paint.Cap.ROUND
    }
    private var route = ""
    private var ready = false

    init {
        setZOrderOnTop(true)
        holder.setFormat(PixelFormat.TRANSLUCENT)
        holder.addCallback(this)
        isClickable = false
        isFocusable = false
        visibility = View.GONE
    }

    fun showRoute(value: String) {
        route = value.takeIf { it == "tablet" || it == "spark" } ?: ""
        contentDescription = when (route) {
            "tablet" -> "Camera connected through PineTab"
            "spark" -> "Camera connected directly to Spark"
            else -> ""
        }
        if (route.isEmpty()) { visibility = View.GONE; return }
        layoutParams = FrameLayout.LayoutParams((28 * dp).toInt(), (28 * dp).toInt(),
            Gravity.BOTTOM or Gravity.END).apply {
            rightMargin = (6 * dp).toInt()
            bottomMargin = (6 * dp).toInt()
        }
        visibility = View.VISIBLE
        render()
    }

    private fun render() {
        if (!ready || visibility != View.VISIBLE) return
        val canvas = try { holder.lockCanvas() } catch (_: Throwable) { null } ?: return
        try {
            canvas.drawColor(Color.TRANSPARENT, PorterDuff.Mode.CLEAR)
            canvas.drawRoundRect(RectF(0f, 0f, canvas.width.toFloat(), canvas.height.toFloat()),
                6 * dp, 6 * dp, background)
            canvas.translate(4 * dp, 4 * dp)
            canvas.scale(20 * dp / 24f, 20 * dp / 24f)
            if (route == "tablet") {
                canvas.drawRoundRect(RectF(5f, 2f, 19f, 22f), 2f, 2f, line)
                canvas.drawLine(10f, 18f, 14f, 18f, line)
            } else {
                val box = Path().apply {
                    moveTo(3f, 7f); lineTo(12f, 2f); lineTo(21f, 7f)
                    lineTo(21f, 17f); lineTo(12f, 22f); lineTo(3f, 17f); close()
                    moveTo(3f, 7f); lineTo(12f, 12f); lineTo(21f, 7f)
                    moveTo(12f, 12f); lineTo(12f, 22f)
                }
                canvas.drawPath(box, line)
            }
        } finally {
            try { holder.unlockCanvasAndPost(canvas) } catch (_: Throwable) { }
        }
    }

    override fun surfaceCreated(holder: SurfaceHolder) { ready = true; render() }
    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        ready = true; render()
    }
    override fun surfaceDestroyed(holder: SurfaceHolder) { ready = false }
}
