package com.pinebox.kiosk.rail

import android.animation.ValueAnimator
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorFilter
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.drawable.Drawable

/** A glow, diagonal sheen and star glint drawn over the update icon. */
class UpdateSheenDrawable : Drawable() {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var phase = 0f
    private var animator: ValueAnimator? = null

    fun start() {
        if (animator != null || !ValueAnimator.areAnimatorsEnabled()) return
        animator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 2400L
            repeatCount = ValueAnimator.INFINITE
            interpolator = android.view.animation.LinearInterpolator()
            addUpdateListener { phase = it.animatedValue as Float; invalidateSelf() }
            start()
        }
    }

    fun stop() { animator?.cancel(); animator = null }

    override fun draw(canvas: Canvas) {
        val box = RectF(bounds)
        if (box.isEmpty) return
        val pulse = ((1.0 - kotlin.math.cos(phase * Math.PI * 2)) / 2).toFloat()
        val radius = box.height() * 0.16f
        paint.shader = null
        paint.style = Paint.Style.FILL
        paint.color = Color.argb((18 + pulse * 35).toInt(), 104, 230, 206)
        canvas.drawRoundRect(box, radius, radius, paint)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = box.height() * 0.035f
        paint.color = Color.argb((80 + pulse * 160).toInt(), 145, 255, 219)
        val edge = RectF(box).apply { inset(paint.strokeWidth, paint.strokeWidth) }
        canvas.drawRoundRect(edge, radius, radius, paint)
        paint.style = Paint.Style.FILL
        val saved = canvas.save()
        val clip = Path().apply { addRoundRect(box, radius, radius, Path.Direction.CW) }
        canvas.clipPath(clip)
        val sweep = (phase * 1.8f).coerceAtMost(1f)
        val x = box.left - box.width() + sweep * box.width() * 3
        val width = box.width() * 0.45f
        paint.shader = LinearGradient(x, box.top, x + width, box.bottom,
            intArrayOf(Color.TRANSPARENT, Color.argb(160, 245, 255, 234), Color.TRANSPARENT),
            floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP)
        canvas.drawRect(box, paint)
        paint.shader = null
        if (phase in 0.28f.. 0.52f) {
            val glint = kotlin.math.sin((phase - 0.28f) / 0.24f * Math.PI).toFloat()
            val cx = box.right - box.width() * 0.2f
            val cy = box.top + box.height() * 0.22f
            val r = box.height() * 0.16f * glint
            val star = Path().apply {
                moveTo(cx, cy-r); lineTo(cx+r*0.22f, cy-r*0.22f)
                lineTo(cx+r, cy); lineTo(cx+r*0.22f, cy+r*0.22f)
                lineTo(cx, cy+r); lineTo(cx-r*0.22f, cy+r*0.22f)
                lineTo(cx-r, cy); lineTo(cx-r*0.22f, cy-r*0.22f); close()
            }
            paint.color = Color.argb((255*glint).toInt(), 255, 255, 232)
            canvas.drawPath(star, paint)
        }
        canvas.restoreToCount(saved)
    }

    override fun setAlpha(alpha: Int) { }
    override fun setColorFilter(colorFilter: ColorFilter?) { }
    @Deprecated("Deprecated in Android")
    override fun getOpacity(): Int = PixelFormat.TRANSLUCENT
}
