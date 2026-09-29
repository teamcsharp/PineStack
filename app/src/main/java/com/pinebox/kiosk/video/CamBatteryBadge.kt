package com.pinebox.kiosk.video

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.PorterDuff
import android.graphics.RectF
import android.graphics.Typeface
import android.view.Gravity
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.widget.FrameLayout
import org.json.JSONObject
import kotlin.math.PI
import kotlin.math.ceil
import kotlin.math.cos

/**
 * [cambattery] The Pine Cam's battery, drawn in the NATIVE picture's top-left.
 *
 * "display a battery meter indicating the battery amount in the top left
 * corner of the pine cam." The page paints the same meter over its own
 * <img>, but on the tablet the picture is PineCamWall's media-overlay
 * SurfaceView, composited ABOVE the WebView - no page element can reach it.
 * So the page hands the reading over (`pineCam('battery', {...})`) and this
 * draws it: a second, tiny SurfaceView with setZOrderOnTop, which is the
 * one layer that sits over a media overlay. It is a child of the wall, so it
 * comes and goes with the picture (menu, hide, lock, off) and rides to the
 * glass's corner in full screen.
 *
 * The page decides everything (text, bars 0..4 or -1 for charging, tone,
 * pulse, stale); this only draws. Main thread only. It never takes input.
 */
class CamBatteryBadge(context: Context) : SurfaceView(context), SurfaceHolder.Callback {

    private val dp = resources.displayMetrics.density
    private val bg = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(163, 5, 8, 10) }
    private val ink = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 12f * dp
        typeface = Typeface.DEFAULT_BOLD
    }
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 1.5f * dp
    }
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }

    private var text = ""
    private var bars = 0
    private var tone = "ok"
    private var pulse = false
    private var stale = false
    private var charging = false
    private var ready = false
    private var phase = 0.0

    private val pulser = object : Runnable {
        override fun run() {
            phase += 2 * PI * PULSE_TICK_MS / PULSE_MS
            render()
            if (pulse && !stale && visibility == View.VISIBLE) postDelayed(this, PULSE_TICK_MS)
        }
    }

    init {
        setZOrderOnTop(true)
        holder.setFormat(PixelFormat.TRANSLUCENT)
        holder.addCallback(this)
        isClickable = false
        isFocusable = false
        visibility = View.GONE
    }

    /** The bridge's `battery` verb: {on, text, bars, tone, pulse, stale, charging}. */
    fun show(o: JSONObject) {
        removeCallbacks(pulser)
        if (!o.optBoolean("on", false)) {
            visibility = View.GONE
            return
        }
        text = o.optString("text", "").take(48)
        bars = o.optInt("bars", 0).coerceIn(-1, 4)
        tone = o.optString("tone", "ok")
        pulse = o.optBoolean("pulse", false)
        stale = o.optBoolean("stale", false)
        charging = o.optBoolean("charging", false) || bars < 0
        val w = ceil(PAD_L * dp + GAUGE_W * dp + NUB_W * dp + GAP * dp
            + ink.measureText(text) + PAD_R * dp).toInt()
        val h = (HEIGHT * dp).toInt()
        val lp = (layoutParams as? FrameLayout.LayoutParams)
            ?: FrameLayout.LayoutParams(w, h)
        lp.width = w
        lp.height = h
        lp.gravity = Gravity.TOP or Gravity.START
        lp.leftMargin = (INSET * dp).toInt()
        lp.topMargin = (INSET * dp).toInt()
        layoutParams = lp
        visibility = View.VISIBLE
        render()
        if (pulse && !stale) postDelayed(pulser, PULSE_TICK_MS)
    }

    private fun tint(): Int = when {
        stale -> Color.rgb(153, 163, 168)
        charging -> Color.rgb(143, 227, 176)
        tone == "red" -> Color.rgb(255, 90, 95)
        tone == "amber" -> Color.rgb(245, 165, 36)
        else -> Color.rgb(230, 238, 241)
    }

    private fun render() {
        if (!ready || visibility != View.VISIBLE) return
        val c: Canvas = (try { holder.lockCanvas() } catch (e: Throwable) { null }) ?: return
        try {
            c.drawColor(Color.TRANSPARENT, PorterDuff.Mode.CLEAR)
            val w = c.width.toFloat()
            val h = c.height.toFloat()
            c.drawRoundRect(RectF(0f, 0f, w, h), 6f * dp, 6f * dp, bg)
            val a = if (pulse && !stale) (0.71 + 0.29 * cos(phase)).toFloat() else 1f
            val col = tint()
            val alpha = (255 * a).toInt().coerceIn(0, 255)
            line.color = col; line.alpha = alpha
            fill.color = col; fill.alpha = alpha
            ink.color = col; ink.alpha = alpha
            val gx = PAD_L * dp
            val gh = GAUGE_H * dp
            val gy = (h - gh) / 2f
            val gw = GAUGE_W * dp
            if (charging) {
                val p = Path()                          // a bolt inside the outline
                p.moveTo(gx + gw * 0.58f, gy - 1f * dp)
                p.lineTo(gx + gw * 0.25f, gy + gh * 0.58f)
                p.lineTo(gx + gw * 0.5f, gy + gh * 0.58f)
                p.lineTo(gx + gw * 0.42f, gy + gh + 1f * dp)
                p.lineTo(gx + gw * 0.75f, gy + gh * 0.42f)
                p.lineTo(gx + gw * 0.5f, gy + gh * 0.42f)
                p.close()
                c.drawPath(p, fill)
            } else {
                c.drawRoundRect(RectF(gx, gy, gx + gw, gy + gh), 2.5f * dp, 2.5f * dp, line)
                c.drawRect(gx + gw + 0.75f * dp, gy + gh * 0.3f, gx + gw + NUB_W * dp,
                    gy + gh * 0.7f, fill)
                val inset = 2.5f * dp
                val cellGap = 1f * dp
                val cw = (gw - 2 * inset - 3 * cellGap) / 4f
                for (i in 0 until 4) {
                    val x0 = gx + inset + i * (cw + cellGap)
                    fill.alpha = if (i < bars) alpha else (alpha * 0.16f).toInt()
                    c.drawRect(x0, gy + inset, x0 + cw, gy + gh - inset, fill)
                }
                fill.alpha = alpha
            }
            val tx = gx + gw + NUB_W * dp + GAP * dp
            val ty = h / 2f - (ink.descent() + ink.ascent()) / 2f
            c.drawText(text, tx, ty, ink)
        } finally {
            try { holder.unlockCanvasAndPost(c) } catch (e: Throwable) { /* surface went */ }
        }
    }

    override fun surfaceCreated(holder: SurfaceHolder) { ready = true; render() }
    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        ready = true
        render()
        if (pulse && !stale) { removeCallbacks(pulser); postDelayed(pulser, PULSE_TICK_MS) }
    }
    override fun surfaceDestroyed(holder: SurfaceHolder) { ready = false; removeCallbacks(pulser) }

    companion object {
        private const val HEIGHT = 22f
        private const val INSET = 6f
        private const val PAD_L = 7f
        private const val PAD_R = 8f
        private const val GAUGE_W = 21f
        private const val GAUGE_H = 11f
        private const val NUB_W = 3f
        private const val GAP = 7f
        private const val PULSE_MS = 2400.0
        private const val PULSE_TICK_MS = 80L
    }
}
