package com.pinebox.kiosk.terminal

import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * DGX TERMINAL.
 *
 * "I want to be able to SSH into the Spark. I want to be able to access the
 *  console. I want to be able to type in commands and be able to work through
 *  a terminal in a separate app called DGX Terminal."
 *
 * Its own launcher entry and its own task, the same shape SparkActivity
 * already uses - it appears in the app list beside Pine Box rather than being
 * a screen inside it, and backing out of it lands where the operator came
 * from rather than on the kiosk.
 *
 * IT IS NOT A KIOSK. Deliberately no HOME filter and no lock task: the
 * terminal is a thing you open, use and leave, and the one screen that must
 * never go blank is the radio.
 *
 * THE ONLY ROAD IN IS THE TAILNET, and that is a decision rather than an
 * oversight. Tailscale SSH answers on 100.74.95.59:22 and authorises on
 * tailnet identity, so there is no key on this tablet and nothing to steal
 * from it. The box's own sshd on the LAN would want a password, and putting a
 * password box on a nine-inch screen for a road nobody asked for is how
 * credentials end up typed into the wrong thing. If the tunnel is down the
 * terminal says so.
 */
class DgxTerminalActivity : AppCompatActivity() {

    private lateinit var view: DgxTerminalView
    private lateinit var status: TextView
    private var ssh: DgxSsh? = null

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        /* The keyboard must SHRINK the terminal rather than cover it, or half
         * the output is behind the keys while you type at it. */
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(android.graphics.Color.parseColor("#0a0e13"))
        }

        status = TextView(this).apply {
            setPadding(18, 12, 18, 12)
            textSize = 12f
            setTextColor(android.graphics.Color.parseColor("#8fa0ad"))
            text = "connecting to the Spark over the tailnet…"
        }
        root.addView(status, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        view = DgxTerminalView(this)
        root.addView(view, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        /* THE KEYS A SHELL NEEDS AND A SOFT KEYBOARD DOES NOT HAVE. Ctrl-C
         * above all: without it there is no way to stop a command, and a
         * terminal you cannot interrupt is a terminal you cannot trust. */
        val keys = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(8, 4, 8, 8)
        }
        fun key(label: String, send: String) {
            keys.addView(Button(this).apply {
                text = label
                textSize = 12f
                isAllCaps = false
                minWidth = 0
                minimumWidth = 0
                setPadding(22, 8, 22, 8)
                setOnClickListener { ssh?.send(send) }
            }, LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT).apply { rightMargin = 8 })
        }
        key("Ctrl-C", "\u0003")
        key("Ctrl-D", "\u0004")
        key("Tab", "\t")
        key("Esc", "\u001B")
        key("↑", "\u001B[A")
        key("↓", "\u001B[B")
        keys.addView(Button(this).apply {
            text = "keyboard"
            textSize = 12f
            isAllCaps = false
            setPadding(22, 8, 22, 8)
            setOnClickListener {
                view.requestFocus()
                (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
                    .showSoftInput(view, InputMethodManager.SHOW_IMPLICIT)
            }
        })
        root.addView(keys, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        setContentView(root)

        view.setOnClickListener {
            view.requestFocus()
            (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
                .showSoftInput(view, InputMethodManager.SHOW_IMPLICIT)
        }
        connect()
    }

    private fun say(text: String, bad: Boolean = false) {
        runOnUiThread {
            status.text = text
            status.setTextColor(android.graphics.Color.parseColor(
                if (bad) "#e46b6b" else "#8fa0ad"))
        }
    }

    private fun connect() {
        lifecycleScope.launch {
            val opened = withContext(Dispatchers.IO) {
                /* THE BANNER FIRST. "Can I open a socket" is the wrong
                 * question - the LAN sshd opens sockets all day and then
                 * wants a password. What matters is whether TAILSCALE is the
                 * thing answering, because that is what lets this tablet in
                 * without a key. Measured: 100.74.95.59:22 says
                 * SSH-2.0-Tailscale, 10.89.1.246:22 says SSH-2.0-OpenSSH. */
                val banner = DgxSsh.banner(DgxSsh.SPARK_HOST)
                if (!DgxSsh.isTailscaleSsh(banner)) {
                    return@withContext Result.failure<DgxSsh>(IllegalStateException(
                        if (banner == null)
                            "the Spark is not answering on the tailnet - is Tailscale connected?"
                        else "that is not Tailscale SSH answering (" + banner.take(40) + ")"))
                }
                val client = DgxSsh(DgxSsh.SPARK_HOST, DgxSsh.SPARK_USER)
                client.cols = view.screen.cols
                client.rows = view.screen.rows
                try {
                    client.open(object : DgxSsh.Wire {
                        override fun out(text: String) = runOnUiThread { view.feed(text) }
                        override fun ended(why: String) = say(why, bad = true)
                    })
                    Result.success(client)
                } catch (err: Exception) {
                    Result.failure(err)
                }
            }
            opened.onSuccess { client ->
                ssh = client
                view.onType = { text -> client.send(text) }
                view.onResize = { c, r -> client.resize(c, r) }
                say("ehm_eckx@lilspark (DGX Spark, GB10) over the tailnet · "
                    + view.screen.cols + "x" + view.screen.rows)
                view.requestFocus()
            }
            opened.onFailure { err ->
                say(err.message ?: "the shell would not open", bad = true)
                view.feed("\r\n  " + (err.message ?: "could not connect") + "\r\n")
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        ssh?.close()
        ssh = null
    }
}
