package com.pinebox.kiosk.video

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.view.View
import android.view.animation.LinearInterpolator
import java.util.WeakHashMap

/**
 * [vcrfx] THE CRT ON AND OFF, FOR A PICTURE NO CSS CAN REACH.
 *
 * "Across the application and then broadcast, anytime a video pops up, use
 *  the same V CR animation effect for displaying the video and showing it
 *  animate in ... And same thing if it goes away." (operator, 2026-09-29)
 *
 * Every page picture now comes on and goes off through PineVcr
 * (desktop/renderer/pine-vcr.js): a bright dot opened into a line, the line
 * pulled open into the picture (420 ms); the picture collapsed to a line, the
 * line to a dot, the dot faded (460 ms). The tablet's two native pictures -
 * PineVideoWall (the endless set) and PineCamWall (the Pine Cam) - are
 * SurfaceViews composited above the WebView, where no stylesheet reaches (see
 * tablet-video-is-a-native-surface), so they play the SAME TABLE here, on the
 * wall's own FrameLayout: scaleX/scaleY/alpha about its centre. On API 29+ a
 * SurfaceView follows its ancestors' transform on the RenderThread, so the
 * surface itself is squashed, not just the empty frame around it.
 *
 * The numbers are pine-vcr.js's IN_FRAMES / OUT_FRAMES, and the curves are its
 * cubic-beziers applied PER KEYFRAME INTERVAL (as a CSS animation-timing-
 * function is), solved by the same method. The one thing with no native twin
 * is the brightness filter (and the white pop), which a SurfaceView cannot
 * take; the geometry and the fade are exact. [VcrFxTest] pins the table.
 *
 * Main thread only. The last call on a view wins: an on during an off starts
 * again from the dot, and an off's `done` runs only if nothing overtook it,
 * so a wall is never left collapsed and VISIBLE by a race.
 */
object VcrFx {
    const val IN_MS = 420L
    const val OUT_MS = 460L

    /** offset, scaleX, scaleY, alpha - sfx-tv.css sfxTvOn / sfxTvOff. */
    val IN_FRAMES: Array<FloatArray> = arrayOf(
        floatArrayOf(0f, 0.004f, 0.004f, 1f),
        floatArrayOf(0.34f, 1f, 0.006f, 1f),
        floatArrayOf(0.58f, 1f, 0.06f, 1f),
        floatArrayOf(1f, 1f, 1f, 1f))
    val OUT_FRAMES: Array<FloatArray> = arrayOf(
        floatArrayOf(0f, 1f, 1f, 1f),
        floatArrayOf(0.40f, 1f, 0.014f, 1f),
        floatArrayOf(0.62f, 1f, 0.006f, 1f),
        floatArrayOf(1f, 0.004f, 0.004f, 0f))

    /** The CSS cubic-bezier(x1, y1, x2, y2), y at x - Newton, then bisection. */
    class Bezier(private val x1: Double, private val y1: Double,
                 private val x2: Double, private val y2: Double) {
        private fun cx(t: Double) = ((1 - 3 * x2 + 3 * x1) * t + (3 * x2 - 6 * x1)) * t * t + 3 * x1 * t
        private fun cy(t: Double) = ((1 - 3 * y2 + 3 * y1) * t + (3 * y2 - 6 * y1)) * t * t + 3 * y1 * t
        private fun dx(t: Double) = 3 * (1 - 3 * x2 + 3 * x1) * t * t + 2 * (3 * x2 - 6 * x1) * t + 3 * x1
        fun at(x: Double): Double {
            if (x <= 0.0) return 0.0
            if (x >= 1.0) return 1.0
            var t = x
            repeat(8) {
                val e = cx(t) - x
                val d = dx(t)
                if (Math.abs(e) < 1e-6) return cy(t)
                if (Math.abs(d) < 1e-6) return@repeat
                t -= e / d
            }
            var lo = 0.0
            var hi = 1.0
            t = x
            repeat(40) {
                val v = cx(t)
                if (Math.abs(v - x) < 1e-6) return cy(t)
                if (v < x) lo = t else hi = t
                t = (lo + hi) / 2
            }
            return cy(t)
        }
    }

    private val IN_CURVE = Bezier(0.18, 0.9, 0.3, 1.0)
    private val OUT_CURVE = Bezier(0.7, 0.0, 0.9, 0.35)

    data class Frame(val sx: Float, val sy: Float, val alpha: Float)

    /** The value at progress [t] (0..1) of an on ([into]) or an off. Pure. */
    fun sample(into: Boolean, t: Float): Frame {
        val f = if (into) IN_FRAMES else OUT_FRAMES
        val curve = if (into) IN_CURVE else OUT_CURVE
        val p = t.coerceIn(0f, 1f)
        var i = 0
        while (i < f.size - 2 && p > f[i + 1][0]) i++
        val a = f[i]
        val b = f[i + 1]
        val span = b[0] - a[0]
        val k = if (span > 0f) curve.at(((p - a[0]) / span).toDouble()).toFloat() else 1f
        fun mix(n: Int) = a[n] + (b[n] - a[n]) * k
        return Frame(mix(1), mix(2), mix(3))
    }

    private class Run(val animator: ValueAnimator, val into: Boolean) {
        var overtaken = false
    }

    private val runs = WeakHashMap<View, Run>()

    /** "in", "out" or "" - what is playing on [view] right now. */
    fun phase(view: View): String = runs[view]?.let { if (it.into) "in" else "out" } ?: ""

    fun isGoingOff(view: View): Boolean = runs[view]?.into == false

    private fun apply(view: View, fr: Frame) {
        view.scaleX = fr.sx
        view.scaleY = fr.sy
        view.alpha = fr.alpha
    }

    /** Whole again: scale 1, alpha 1. */
    fun reset(view: View) {
        view.scaleX = 1f
        view.scaleY = 1f
        view.alpha = 1f
    }

    /** Stop whatever is playing on [view] (its `done` never runs) and make it whole. */
    fun cancel(view: View) {
        val r = runs.remove(view) ?: run { reset(view); return }
        r.overtaken = true
        try { r.animator.cancel() } catch (err: Throwable) { }
        reset(view)
    }

    /** A wall made VISIBLE by some other road: whole, unless an on is playing. */
    fun settle(view: View) {
        if (runs[view]?.into == true) return
        cancel(view)
    }

    /**
     * Play the on ([into]) or the off on [view]. [done] runs when it completes
     * and was not overtaken. After an off, `done` is expected to hide the view;
     * the view is then made whole again (invisibly) for the next time.
     */
    fun play(view: View, into: Boolean, done: (() -> Unit)? = null) {
        runs.remove(view)?.let { old ->
            old.overtaken = true
            try { old.animator.cancel() } catch (err: Throwable) { }
        }
        if (!ValueAnimator.areAnimatorsEnabled()) {
            /* The system's own "remove animations": the state, at once. */
            reset(view)
            done?.invoke()
            return
        }
        val anim = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = if (into) IN_MS else OUT_MS
            interpolator = LinearInterpolator()      // eased per interval in sample()
        }
        val run = Run(anim, into)
        runs[view] = run
        apply(view, sample(into, 0f))
        anim.addUpdateListener { a -> if (!run.overtaken) apply(view, sample(into, a.animatedFraction)) }
        anim.addListener(object : AnimatorListenerAdapter() {
            override fun onAnimationEnd(animation: Animator) {
                if (run.overtaken) return
                runs.remove(view)
                apply(view, sample(into, 1f))
                done?.invoke()
                if (into || view.visibility != View.VISIBLE) reset(view)
            }
        })
        anim.start()
    }
}
