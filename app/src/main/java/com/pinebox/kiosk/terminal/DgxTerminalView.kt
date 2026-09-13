package com.pinebox.kiosk.terminal

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.text.InputType
import android.util.AttributeSet
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.BaseInputConnection
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection

/**
 * THE GRID, DRAWN.
 *
 * A custom View rather than a TextView with spans. A `tail -f` repaints a
 * hundred rows several times a second, and building a Spannable for that on
 * every frame is the kind of thing that gives this tablet an ANR - it has had
 * one before, from the console, which is a lesson worth not learning twice.
 * Here a frame is one drawText per row and nothing allocated.
 *
 * TYPING GOES STRAIGHT OUT, and nothing is echoed locally. The far end echoes
 * what it chooses to - which is what makes a password prompt print nothing
 * and readline redraw a line you edited in the middle. Echoing here as well
 * would double every character and break both.
 */
class DgxTerminalView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {

    val screen = DgxScreen()

    /** Where typed bytes go. Set by the activity once SSH is up. */
    var onType: ((String) -> Unit)? = null

    /** Told when the grid changes shape, so the far end can be told too. */
    var onResize: ((cols: Int, rows: Int) -> Unit)? = null

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.MONOSPACE
        textSize = 30f
    }
    private val block = Paint()

    private var cellW = 0f
    private var cellH = 0f
    private var baseline = 0f
    private var drawn: Long = -1

    init {
        isFocusable = true
        isFocusableInTouchMode = true
        setBackgroundColor(Color.parseColor("#0a0e13"))
        measureCell()
    }

    /** Bigger or smaller type, which also changes how much fits. */
    var textSizePx: Float
        get() = paint.textSize
        set(value) {
            paint.textSize = value.coerceIn(14f, 72f)
            measureCell()
            fit(width, height)
            invalidate()
        }

    private fun measureCell() {
        /* A monospace font: every advance is the same, so one measurement
         * stands for all of them. */
        cellW = paint.measureText("M")
        val metrics = paint.fontMetrics
        cellH = (metrics.descent - metrics.ascent)
        baseline = -metrics.ascent
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        fit(w, h)
    }

    private fun fit(w: Int, h: Int) {
        if (w <= 0 || h <= 0 || cellW <= 0f || cellH <= 0f) return
        val cols = (w / cellW).toInt().coerceAtLeast(20)
        val rows = (h / cellH).toInt().coerceAtLeast(4)
        if (cols == screen.cols && rows == screen.rows) return
        screen.resize(cols, rows)
        onResize?.invoke(cols, rows)
        invalidate()
    }

    fun feed(text: String) {
        screen.feed(text)
        postInvalidateOnAnimation()
    }

    override fun onDraw(canvas: Canvas) {
        drawn = screen.revision
        val rows = screen.rows
        val cols = screen.cols
        for (r in 0 until rows) {
            val chars = screen.text[r]
            val ink = screen.ink[r]
            var c = 0
            val y = r * cellH + baseline
            while (c < cols) {
                /* RUNS OF ONE COLOUR, drawn together. A row of plain output is
                 * one drawText; only where the colour changes does it become
                 * two. Per-character drawing showed as visible tearing on a
                 * full screen of `git status`. */
                val paintByte = ink[c]
                var end = c + 1
                while (end < cols && ink[end] == paintByte) end++
                val bg = DgxScreen.bgOf(paintByte)
                if (bg != 0) {
                    block.color = PALETTE[bg]
                    canvas.drawRect(c * cellW, r * cellH, end * cellW, (r + 1) * cellH, block)
                }
                paint.color = PALETTE[DgxScreen.fgOf(paintByte)]
                canvas.drawText(String(chars, c, end - c), c * cellW, y, paint)
                c = end
            }
        }
        if (screen.cursorOn && hasFocus()) {
            block.color = Color.parseColor("#65c7da")
            val x = screen.cursorCol * cellW
            val y = screen.cursorRow * cellH
            /* An underline rather than a block: a block hides the character
               under it, and on a shell that is usually the one being typed. */
            canvas.drawRect(x, y + cellH - 3f, x + cellW, y + cellH, block)
        }
    }

    /* ------------------------------------------------------------------ */
    /* Typing                                                              */
    /* ------------------------------------------------------------------ */

    override fun onCheckIsTextEditor(): Boolean = true

    override fun onCreateInputConnection(info: EditorInfo): InputConnection {
        /* THE SHAPE OF THE PATH, NEVER ITS CONTENTS.
         *
         * While this was being chased, every callback logged the character it
         * had received - which found the bug in one build and would have
         * written every password typed at that prompt into logcat, readable
         * by anything holding READ_LOGS. A debugging aid that records what a
         * person types is a keylogger with good intentions. What is left says
         * only whether the keyboard attached and whether the shell was wired,
         * which is what would be wanted if this ever breaks again. */
        Log.i(TAG, "IME attached: focus=" + hasFocus() + " wired=" + (onType != null))
        info.inputType = InputType.TYPE_CLASS_TEXT or
            InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS or
            InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
        /* IME_ACTION_NONE and no fullscreen: a terminal wants the keys, not a
         * Done button, and never the landscape "extract" editor that replaces
         * the whole screen with a text box. */
        info.imeOptions = EditorInfo.IME_ACTION_NONE or
            EditorInfo.IME_FLAG_NO_FULLSCREEN or
            EditorInfo.IME_FLAG_NO_EXTRACT_UI
        return object : BaseInputConnection(this, false) {
            /* THE COMPOSING REGION IS WHY TYPING DID NOTHING.
             *
             * A soft keyboard does not hand over each key as it is pressed.
             * It types into a COMPOSING region - the underlined word - and
             * only commits when it reaches a space, a punctuation mark or
             * Enter. This overrode commitText and not setComposingText, so
             * every character went into BaseInputConnection's own buffer and
             * the shell heard nothing until a space. Reported from the tablet
             * as "I'm not able to type into the terminal", which is exactly
             * what that looks like at a prompt.
             *
             * A terminal has no composing region: the far end wants each
             * character as it is struck, because the far end is what decides
             * what a character means - tab completes, ^C kills, and a
             * password prompt echoes nothing. So composing text is forwarded
             * as it CHANGES, and what has already gone out is remembered so a
             * correction rubs it out with backspaces rather than sending the
             * whole word a second time. */
            private val composing = StringBuilder()

            private fun shared(now: String): Int {
                var i = 0
                while (i < composing.length && i < now.length && composing[i] == now[i]) i++
                return i
            }

            /** Send only the difference between what the far end has and `now`. */
            private fun catchUp(now: String) {
                val keep = shared(now)
                repeat(composing.length - keep) { onType?.invoke("\u007F") }
                if (now.length > keep) onType?.invoke(now.substring(keep))
            }

            override fun setComposingText(text: CharSequence?, newCursorPosition: Int): Boolean {
                val now = text?.toString() ?: ""
                catchUp(now)
                composing.setLength(0)
                composing.append(now)
                return true
            }

            override fun finishComposingText(): Boolean {
                composing.setLength(0)
                return true
            }

            override fun commitText(text: CharSequence?, newCursorPosition: Int): Boolean {
                /* Whatever was composing has already gone out; only the part
                 * that differs is still owed. Sending the whole string here
                 * would double every word the keyboard composed first. */
                catchUp(text?.toString() ?: "")
                composing.setLength(0)
                return true
            }

            override fun deleteSurroundingText(before: Int, after: Int): Boolean {
                if (composing.isNotEmpty()) {
                    val drop = minOf(before, composing.length)
                    composing.setLength(composing.length - drop)
                    repeat(drop) { onType?.invoke("\u007F") }
                    return true
                }
                repeat(before) { onType?.invoke("\u007F") }
                return true
            }

            override fun sendKeyEvent(event: KeyEvent?): Boolean {
                if (event != null && event.action == KeyEvent.ACTION_DOWN) {
                    composing.setLength(0)
                    return this@DgxTerminalView.onKeyDown(event.keyCode, event)
                }
                return true
            }

            /* Some keyboards send Enter as an editor action rather than a key. */
            override fun performEditorAction(action: Int): Boolean {
                composing.setLength(0)
                onType?.invoke("\r")
                return true
            }
        }
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        val out = when (keyCode) {
            KeyEvent.KEYCODE_ENTER -> "\r"
            KeyEvent.KEYCODE_DEL -> "\u007F"
            KeyEvent.KEYCODE_TAB -> "\t"
            KeyEvent.KEYCODE_ESCAPE -> "\u001B"
            KeyEvent.KEYCODE_DPAD_UP -> "\u001B[A"
            KeyEvent.KEYCODE_DPAD_DOWN -> "\u001B[B"
            KeyEvent.KEYCODE_DPAD_RIGHT -> "\u001B[C"
            KeyEvent.KEYCODE_DPAD_LEFT -> "\u001B[D"
            else -> {
                if (event.isCtrlPressed) {
                    /* Ctrl-C, Ctrl-D, Ctrl-Z and the rest: the control code is
                     * the letter's position in the alphabet. Without this
                     * there is no way to stop a runaway command, which on a
                     * terminal is not a nicety. */
                    val ch = event.getUnicodeChar(0).toChar().lowercaseChar()
                    if (ch in 'a'..'z') ((ch - 'a') + 1).toChar().toString() else null
                } else {
                    val unicode = event.unicodeChar
                    if (unicode != 0) unicode.toChar().toString() else null
                }
            }
        }
        if (out == null) return super.onKeyDown(keyCode, event)
        if (onType == null) Log.w(TAG, "nothing to type into - the shell is not wired")
        onType?.invoke(out)
        return true
    }

    companion object {
        private const val TAG = "DgxTerminal"

        /** The sixteen, in the Pine Box register rather than raw primaries. */
        private val PALETTE = intArrayOf(
            Color.parseColor("#11161c"), Color.parseColor("#e46b6b"),
            Color.parseColor("#7fd46a"), Color.parseColor("#e3b341"),
            Color.parseColor("#5b9dd9"), Color.parseColor("#c678dd"),
            Color.parseColor("#65c7da"), Color.parseColor("#c9d5df"),
            Color.parseColor("#4a5b68"), Color.parseColor("#ff8d8d"),
            Color.parseColor("#a5ef8f"), Color.parseColor("#ffd166"),
            Color.parseColor("#84bdf5"), Color.parseColor("#e2a1f2"),
            Color.parseColor("#8fe3f2"), Color.parseColor("#f0f3f8"),
        )
    }
}
