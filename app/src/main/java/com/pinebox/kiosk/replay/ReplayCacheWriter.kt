package com.pinebox.kiosk.replay

import java.util.concurrent.Executor
import java.util.concurrent.Executors

/** Serialize atomic history writes while mirror control stays independent of
 * slow muxing/storage. Full stop flushes before freeing the ring; destructive
 * transitions invalidate queued snapshots and wait for in-flight disk I/O. */
internal class ReplayCacheWriter(
    private val write: () -> Unit,
    private val executor: Executor = Executors.newSingleThreadExecutor { task ->
        Thread(task, "replay-history-cache").apply { isDaemon = true }
    }
) {
    private val writeGate = Any()
    private val queueGate = Any()
    private val writing = java.util.concurrent.atomic.AtomicBoolean(false)
    private var queued = false
    private var active = false
    private var rerun = false
    private var generation = 0L
    val hasPending: Boolean get() = writing.get() || synchronized(queueGate) { queued }

    fun flush() = invalidate { write() }

    fun invalidate(action: () -> Unit) = synchronized(writeGate) {
        synchronized(queueGate) { generation++; queued = false; active = false; rerun = false }
        writing.set(true)
        try { action() } finally { writing.set(false) }
    }

    fun enqueue() {
        val ownGeneration = synchronized(queueGate) {
            if (queued) {
                if (active) rerun = true
                return
            }
            queued = true
            ++generation
        }
        try {
            executor.execute {
                try {
                    var again = true
                    while (again) {
                        synchronized(writeGate) {
                            val valid = synchronized(queueGate) {
                                if (generation != ownGeneration) false
                                else { active = true; rerun = false; true }
                            }
                            if (valid) {
                                writing.set(true)
                                try { write() } finally { writing.set(false) }
                            }
                            again = synchronized(queueGate) {
                                active = false
                                if (generation != ownGeneration) false
                                else if (rerun) true
                                else { queued = false; false }
                            }
                        }
                    }
                } finally {
                    synchronized(queueGate) {
                        if (generation == ownGeneration) { queued = false; active = false; rerun = false }
                    }
                }
            }

        } catch (error: RuntimeException) {
            synchronized(queueGate) { if (generation == ownGeneration) queued = false }
            throw error
        }
    }
}
