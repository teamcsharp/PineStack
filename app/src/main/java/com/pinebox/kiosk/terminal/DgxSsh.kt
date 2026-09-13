package com.pinebox.kiosk.terminal

import com.jcraft.jsch.ChannelShell
import com.jcraft.jsch.JSch
import com.jcraft.jsch.Session
import com.jcraft.jsch.UserInfo
import java.io.InputStream
import java.io.OutputStream
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * A SHELL ON THE SPARK, OVER THE TAILNET.
 *
 * "I want to be able to SSH into the Spark. I want to be able to access the
 *  console. I want to be able to type in commands and work through a terminal
 *  in a separate app called DGX Terminal."
 *
 * THERE ARE NO KEYS HERE, AND THAT IS THE WHOLE POINT.
 *
 * Tailscale SSH is enabled on lilspark, and it intercepts port 22 for tailnet
 * peers. Measured from this tablet:
 *
 *     100.74.95.59:22   ->  SSH-2.0-Tailscale
 *     10.89.1.246:22    ->  SSH-2.0-OpenSSH_9.6p1
 *
 * The first is Tailscale answering; the second is the box's own sshd on the
 * LAN. Against the first, the WireGuard tunnel has already proved who this
 * device is before a single SSH packet is sent, so the server authorises on
 * tailnet identity and accepts the protocol's `none` method. No private key
 * on the tablet, no passphrase to type on a nine-inch screen, no
 * authorized_keys to maintain, and nothing to leak if the tablet is lost -
 * revoking the device in the Tailscale console revokes the shell with it.
 *
 * It also means the LAN address must NOT be offered as a fallback here, even
 * though everything else in this terminal falls back to it happily. sshd on
 * :22 would demand a password or a key, and the honest thing is to say the
 * tailnet is not up rather than to present a password box for a road the
 * operator never asked to take.
 *
 * HOST KEYS. Tailscale presents its own host key for the session and the
 * tunnel is what is actually being trusted, so StrictHostKeyChecking is off.
 * That is not a shrug: on a normal network it would be the wrong call, and
 * here the transport underneath has already done a stronger check than a
 * fingerprint comparison would.
 */
class DgxSsh(
    private val host: String,
    private val user: String,
    private val port: Int = 22,
) {

    /** What the terminal shows and what it can type into. */
    interface Wire {
        fun out(text: String)
        fun ended(why: String)
    }

    private var session: Session? = null
    private var channel: ChannelShell? = null
    private var sink: OutputStream? = null
    private val open = AtomicBoolean(false)

    /* THE WRITER'S OWN THREAD.
     *
     * Typing arrives on the main thread - it is a key callback - and writing
     * to a socket there throws NetworkOnMainThreadException. That is exactly
     * how this failed the first time: the first letter threw, the throw left
     * JSch's stream closed, and every letter after it reported "Already
     * closed". A terminal dead from the first keystroke with no sign of why.
     *
     * SINGLE-threaded, deliberately. Keystrokes are ordered - `ls` typed
     * quickly must not arrive as `lsl` - and one worker draining a queue is
     * the only arrangement that keeps that true while still being off the
     * main thread. */
    private val writer = java.util.concurrent.Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "dgx-ssh-write").apply { isDaemon = true }
    }

    val isOpen: Boolean get() = open.get()

    /** Columns and rows, so the far end wraps to THIS screen. */
    @Volatile var cols: Int = 100
    @Volatile var rows: Int = 30

    /**
     * Connect and start an interactive shell. Blocking - call it off the main
     * thread. Everything the far end says arrives on [wire] from a reader
     * thread of its own.
     */
    fun open(wire: Wire) {
        val jsch = JSch()
        val ssh = jsch.getSession(user, host, port)
        /* `none` is what Tailscale SSH accepts for an authorised peer. It is
         * named explicitly rather than left to the default order so that a
         * misconfiguration fails as "permission denied" instead of silently
         * falling through to a password prompt this app has no way to fill. */
        ssh.setConfig("PreferredAuthentications", "none,publickey")
        ssh.setConfig("StrictHostKeyChecking", "no")
        /* Keep the tunnel warm. A tablet screen goes off mid-command and a
         * dead session that only reveals itself on the next keystroke is the
         * most annoying possible failure. */
        ssh.serverAliveInterval = 20_000
        ssh.serverAliveCountMax = 3
        ssh.timeout = 15_000
        /* Nothing may ever prompt: there is no one to answer on a kiosk. */
        ssh.userInfo = object : UserInfo {
            override fun getPassphrase(): String? = null
            override fun getPassword(): String? = null
            override fun promptPassword(message: String?) = false
            override fun promptPassphrase(message: String?) = false
            override fun promptYesNo(message: String?) = true   /* host keys only */
            override fun showMessage(message: String?) { if (!message.isNullOrBlank()) wire.out(message + "\n") }
        }

        ssh.connect(15_000)
        session = ssh

        val shell = ssh.openChannel("shell") as ChannelShell
        /* xterm, because the far end's programs read TERM to decide what they
         * may draw. Claiming xterm and then not honouring it is how you get a
         * screen full of escape codes - see DgxScreen, which interprets
         * enough of them to keep that honest. */
        shell.setPtyType("xterm", cols, rows, 0, 0)
        shell.setAgentForwarding(false)
        val source: InputStream = shell.inputStream
        sink = shell.outputStream
        shell.connect(10_000)
        channel = shell
        open.set(true)

        thread(name = "dgx-ssh-read", isDaemon = true) {
            val buffer = ByteArray(8192)
            try {
                while (open.get()) {
                    val read = source.read(buffer)
                    if (read < 0) break
                    if (read > 0) wire.out(String(buffer, 0, read, Charsets.UTF_8))
                }
            } catch (err: Exception) {
                if (open.get()) wire.ended(err.message ?: "the connection dropped")
            } finally {
                if (open.getAndSet(false)) wire.ended("the shell closed")
            }
        }
    }

    /** Type. The far end echoes, so nothing is printed locally. */
    fun send(text: String) {
        val out = sink ?: return
        if (!open.get()) return
        val bytes = text.toByteArray(Charsets.UTF_8)
        /* Queued, never written here: this is the main thread. */
        try {
            writer.execute {
                try {
                    out.write(bytes)
                    out.flush()
                } catch (err: Exception) {
                    android.util.Log.w(LOG, "send failed: " + err.message)
                    open.set(false)
                }
            }
        } catch (err: java.util.concurrent.RejectedExecutionException) {
            /* The session is closing. Nothing to do and nothing to say. */
        }
    }

    /** Tell the far end the screen changed shape, so it re-wraps. */
    fun resize(newCols: Int, newRows: Int) {
        cols = newCols
        rows = newRows
        val shell = channel ?: return
        /* Also a network write, and it is called from onSizeChanged - which
         * is the main thread, and which fires every time the keyboard opens. */
        try {
            writer.execute {
                try { shell.setPtySize(newCols, newRows, 0, 0) }
                catch (err: Exception) { /* the far end will wrap as it was */ }
            }
        } catch (err: java.util.concurrent.RejectedExecutionException) { /* closing */ }
    }

    fun close() {
        open.set(false)
        /* Shut the queue before the channel, or a keystroke already queued
         * writes into a disconnected stream and logs a failure about a
         * session the operator has already closed on purpose. */
        try { writer.shutdownNow() } catch (err: Exception) { /* going anyway */ }
        try { channel?.disconnect() } catch (err: Exception) { /* already */ }
        try { session?.disconnect() } catch (err: Exception) { /* already */ }
        channel = null
        session = null
        sink = null
    }

    companion object {
        private const val LOG = "DgxTerminal"

        /** The tailnet address, which is the only one this may use. */
        const val SPARK_HOST = "100.74.95.59"
        const val SPARK_NAME = "lilspark.tail1fec29.ts.net"
        const val SPARK_USER = "ehm_eckx"

        /**
         * Is Tailscale SSH answering on the other end?
         *
         * Reading the banner is a far better question than "does the port
         * accept a socket", because the LAN sshd accepts sockets all day and
         * would then demand a password. A banner that does not say Tailscale
         * means the tunnel is down and the terminal should say so rather than
         * connect to something that cannot let it in.
         */
        fun banner(host: String, port: Int = 22, waitMs: Int = 4000): String? = try {
            java.net.Socket().use { socket ->
                socket.connect(java.net.InetSocketAddress(host, port), waitMs)
                socket.soTimeout = waitMs
                val line = StringBuilder()
                val input = socket.getInputStream()
                while (line.length < 120) {
                    val c = input.read()
                    if (c < 0 || c == '\n'.code) break
                    if (c != '\r'.code) line.append(c.toChar())
                }
                line.toString().ifBlank { null }
            }
        } catch (err: Exception) {
            null
        }

        fun isTailscaleSsh(banner: String?): Boolean =
            banner != null && banner.contains("Tailscale", ignoreCase = true)
    }
}
