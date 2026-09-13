package com.pinebox.kiosk.terminal

/**
 * A CHARACTER GRID, AND ENOUGH VT100 TO BE HONEST ABOUT IT.
 *
 * The shell is told `TERM=xterm` because that is what makes programs on the
 * far end willing to colour their output and draw at all. Claiming xterm and
 * then printing the escape codes raw is the worst of both: `ls` becomes
 * `^[[0m^[[01;34mbin^[[0m` and `git status` is unreadable. So enough of the
 * protocol is interpreted here to keep that claim true.
 *
 * WHAT IS HANDLED, and it is chosen from what is actually typed at a machine
 * like this one: printable text, the control characters, cursor movement,
 * the erase family, scrolling regions, and SGR colour. That covers ls, git,
 * grep, tail -f, python, nvidia-smi, docker, journalctl - everything that
 * writes lines and colours them.
 *
 * WHAT IS NOT: the alternate screen buffer's finer points, DEC line drawing,
 * mouse reporting. vim and htop will run and will mostly look right; they are
 * not the reason this exists. Saying so here is better than a user finding
 * out, and better than pretending to a completeness this does not have.
 *
 * The grid is plain arrays rather than objects per cell. A 100x30 screen is
 * 3,000 cells redrawn on every frame of a `tail -f`, and a Cell class would
 * mean three thousand allocations a frame on a tablet that has had an ANR
 * before.
 */
class DgxScreen(cols: Int = 100, rows: Int = 30) {

    var cols = cols.coerceIn(20, 400); private set
    var rows = rows.coerceIn(4, 200); private set

    /** Character per cell, and its colour packed as fg + bg * 16. */
    var text = Array(this.rows) { CharArray(this.cols) { ' ' } }; private set
    var ink = Array(this.rows) { ByteArray(this.cols) { DEFAULT_INK } }; private set

    var cursorRow = 0; private set
    var cursorCol = 0; private set
    var cursorOn = true; private set

    /** Scrolling region, inclusive, as DECSTBM sets it. */
    private var top = 0
    private var bottom = this.rows - 1

    private var fg = 7
    private var bg = 0
    private var bright = false
    private var inverse = false

    /** Set while a sequence is being gathered. */
    private val pending = StringBuilder()
    private var state = State.TEXT

    private enum class State { TEXT, ESC, CSI, OSC }

    /** Bumped on every change, so the view can skip an identical frame. */
    var revision: Long = 0; private set

    fun resize(newCols: Int, newRows: Int) {
        val c = newCols.coerceIn(20, 400)
        val r = newRows.coerceIn(4, 200)
        if (c == cols && r == rows) return
        val freshText = Array(r) { CharArray(c) { ' ' } }
        val freshInk = Array(r) { ByteArray(c) { DEFAULT_INK } }
        /* KEEP THE BOTTOM, not the top. A resize almost always happens
         * because the keyboard appeared, and what the operator was reading is
         * the last thing printed, not the first. */
        val keepRows = minOf(rows, r)
        for (i in 0 until keepRows) {
            val from = rows - keepRows + i
            val to = r - keepRows + i
            val keepCols = minOf(cols, c)
            System.arraycopy(text[from], 0, freshText[to], 0, keepCols)
            System.arraycopy(ink[from], 0, freshInk[to], 0, keepCols)
        }
        text = freshText
        ink = freshInk
        cols = c
        rows = r
        top = 0
        bottom = r - 1
        cursorRow = cursorRow.coerceIn(0, r - 1)
        cursorCol = cursorCol.coerceIn(0, c - 1)
        revision++
    }

    fun feed(chunk: String) {
        for (ch in chunk) step(ch)
        revision++
    }

    private fun step(ch: Char) {
        when (state) {
            State.TEXT -> when (ch) {
                '\u001B' -> { state = State.ESC; pending.setLength(0) }
                '\n' -> newline()
                '\r' -> cursorCol = 0
                '\b' -> if (cursorCol > 0) cursorCol--
                '\t' -> cursorCol = minOf(cols - 1, (cursorCol / 8 + 1) * 8)
                '\u0007' -> Unit                       /* the bell, silently */
                else -> if (ch >= ' ') put(ch)
            }
            State.ESC -> when (ch) {
                '[' -> { state = State.CSI; pending.setLength(0) }
                ']' -> { state = State.OSC; pending.setLength(0) }
                'c' -> { hard(); state = State.TEXT }
                /* ESC ( B and friends: a charset selection, consumed whole. */
                '(', ')', '#', '%' -> Unit
                else -> state = State.TEXT
            }
            State.CSI -> {
                if (ch in '@'..'~') { csi(ch, pending.toString()); state = State.TEXT }
                else pending.append(ch)
            }
            State.OSC -> {
                /* A window title, usually. Ends at BEL or ESC \ - both are
                 * watched for, because shells differ about which they send. */
                if (ch == '\u0007') state = State.TEXT
                else if (ch == '\u001B') Unit
                else if (ch == '\\' && pending.isNotEmpty()) state = State.TEXT
                else pending.append(ch)
            }
        }
    }

    private fun put(ch: Char) {
        if (cursorCol >= cols) { cursorCol = 0; newline() }
        text[cursorRow][cursorCol] = ch
        ink[cursorRow][cursorCol] = packed()
        cursorCol++
    }

    private fun packed(): Byte {
        val f = if (inverse) bg else fg
        val b = if (inverse) fg else bg
        val lit = if (bright && !inverse) f + 8 else f
        return ((lit and 0x0f) or ((b and 0x0f) shl 4)).toByte()
    }

    private fun newline() {
        if (cursorRow == bottom) scrollUp() else if (cursorRow < rows - 1) cursorRow++
    }

    private fun scrollUp() {
        val keptText = text[top]
        val keptInk = ink[top]
        for (r in top until bottom) {
            text[r] = text[r + 1]
            ink[r] = ink[r + 1]
        }
        java.util.Arrays.fill(keptText, ' ')
        java.util.Arrays.fill(keptInk, DEFAULT_INK)
        text[bottom] = keptText
        ink[bottom] = keptInk
    }

    private fun csi(final: Char, raw: String) {
        val body = raw.removePrefix("?")
        val private = raw.startsWith("?")
        val args = body.split(';').map { it.toIntOrNull() ?: 0 }
        val first = args.getOrNull(0) ?: 0
        when (final) {
            'A' -> cursorRow = (cursorRow - maxOf(1, first)).coerceAtLeast(0)
            'B' -> cursorRow = (cursorRow + maxOf(1, first)).coerceAtMost(rows - 1)
            'C' -> cursorCol = (cursorCol + maxOf(1, first)).coerceAtMost(cols - 1)
            'D' -> cursorCol = (cursorCol - maxOf(1, first)).coerceAtLeast(0)
            'G' -> cursorCol = (maxOf(1, first) - 1).coerceIn(0, cols - 1)
            'd' -> cursorRow = (maxOf(1, first) - 1).coerceIn(0, rows - 1)
            'H', 'f' -> {
                cursorRow = ((args.getOrNull(0) ?: 1).coerceAtLeast(1) - 1).coerceIn(0, rows - 1)
                cursorCol = ((args.getOrNull(1) ?: 1).coerceAtLeast(1) - 1).coerceIn(0, cols - 1)
            }
            'J' -> erase(screen = true, how = first)
            'K' -> erase(screen = false, how = first)
            'L' -> insertLines(maxOf(1, first))
            'M' -> deleteLines(maxOf(1, first))
            'P' -> deleteChars(maxOf(1, first))
            'X' -> blank(cursorRow, cursorCol, minOf(cols - 1, cursorCol + maxOf(1, first) - 1))
            'r' -> {
                top = ((args.getOrNull(0) ?: 1).coerceAtLeast(1) - 1).coerceIn(0, rows - 1)
                bottom = ((args.getOrNull(1) ?: rows).coerceAtLeast(1) - 1).coerceIn(top, rows - 1)
                cursorRow = top
                cursorCol = 0
            }
            'm' -> sgr(if (body.isBlank()) listOf(0) else args)
            'h' -> if (private && first == 25) cursorOn = true
            'l' -> if (private && first == 25) cursorOn = false
            else -> Unit
        }
    }

    private fun sgr(args: List<Int>) {
        var i = 0
        while (i < args.size) {
            when (val a = args[i]) {
                0 -> { fg = 7; bg = 0; bright = false; inverse = false }
                1 -> bright = true
                22 -> bright = false
                7 -> inverse = true
                27 -> inverse = false
                in 30..37 -> fg = a - 30
                39 -> fg = 7
                in 40..47 -> bg = a - 40
                49 -> bg = 0
                in 90..97 -> { fg = a - 90; bright = true }
                in 100..107 -> bg = a - 100
                38, 48 -> {
                    /* 256-colour and truecolour, mapped down to the sixteen
                     * this grid holds. Consuming the arguments matters more
                     * than the shade: leaving them would paint the numbers. */
                    val mode = args.getOrNull(i + 1)
                    val approx: Int
                    if (mode == 5) { approx = (args.getOrNull(i + 2) ?: 7) % 8; i += 2 }
                    else if (mode == 2) {
                        val r = args.getOrNull(i + 2) ?: 0
                        val g = args.getOrNull(i + 3) ?: 0
                        val b = args.getOrNull(i + 4) ?: 0
                        approx = (if (r > 127) 1 else 0) or (if (g > 127) 2 else 0) or
                            (if (b > 127) 4 else 0)
                        i += 4
                    } else approx = 7
                    if (a == 38) fg = approx else bg = approx
                }
            }
            i++
        }
    }

    private fun erase(screen: Boolean, how: Int) {
        if (!screen) {
            when (how) {
                0 -> blank(cursorRow, cursorCol, cols - 1)
                1 -> blank(cursorRow, 0, cursorCol)
                else -> blank(cursorRow, 0, cols - 1)
            }
            return
        }
        when (how) {
            0 -> {
                blank(cursorRow, cursorCol, cols - 1)
                for (r in cursorRow + 1 until rows) blank(r, 0, cols - 1)
            }
            1 -> {
                for (r in 0 until cursorRow) blank(r, 0, cols - 1)
                blank(cursorRow, 0, cursorCol)
            }
            else -> for (r in 0 until rows) blank(r, 0, cols - 1)
        }
    }

    private fun blank(row: Int, from: Int, to: Int) {
        if (row !in 0 until rows) return
        for (c in from.coerceAtLeast(0)..to.coerceAtMost(cols - 1)) {
            text[row][c] = ' '
            ink[row][c] = DEFAULT_INK
        }
    }

    private fun insertLines(many: Int) {
        repeat(many.coerceAtMost(rows)) {
            for (r in bottom downTo cursorRow + 1) {
                text[r] = text[r - 1]; ink[r] = ink[r - 1]
            }
            text[cursorRow] = CharArray(cols) { ' ' }
            ink[cursorRow] = ByteArray(cols) { DEFAULT_INK }
        }
    }

    private fun deleteLines(many: Int) {
        repeat(many.coerceAtMost(rows)) {
            for (r in cursorRow until bottom) {
                text[r] = text[r + 1]; ink[r] = ink[r + 1]
            }
            text[bottom] = CharArray(cols) { ' ' }
            ink[bottom] = ByteArray(cols) { DEFAULT_INK }
        }
    }

    private fun deleteChars(many: Int) {
        val row = text[cursorRow]
        val paint = ink[cursorRow]
        for (c in cursorCol until cols) {
            val from = c + many
            row[c] = if (from < cols) row[from] else ' '
            paint[c] = if (from < cols) paint[from] else DEFAULT_INK
        }
    }

    private fun hard() {
        for (r in 0 until rows) blank(r, 0, cols - 1)
        cursorRow = 0; cursorCol = 0
        top = 0; bottom = rows - 1
        fg = 7; bg = 0; bright = false; inverse = false
    }

    /** The whole screen as plain text, for copying out. */
    fun asText(): String = buildString {
        for (r in 0 until rows) {
            append(String(text[r]).trimEnd())
            if (r < rows - 1) append('\n')
        }
    }.trimEnd()

    companion object {
        /** grey on black: fg 7, bg 0 */
        const val DEFAULT_INK: Byte = 7

        fun fgOf(packed: Byte): Int = packed.toInt() and 0x0f
        fun bgOf(packed: Byte): Int = (packed.toInt() shr 4) and 0x0f
    }
}
