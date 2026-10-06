package com.pinebox.kiosk.replay

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class ReplayCacheWriterTest {
    @Test fun pendingWritesCoalesceAndFlushRetainsSynchronousBehavior() {
        val pending = mutableListOf<Runnable>()
        var writes = 0
        val cache = ReplayCacheWriter({ writes++ }, Executor { pending.add(it) })
        cache.enqueue(); cache.enqueue()
        assertEquals(1, pending.size)
        assertEquals(0, writes)
        cache.flush()
        assertEquals(1, writes)
        pending.removeAt(0).run()
        assertEquals(1, writes) // A full flush supersedes the queued snapshot.
        cache.enqueue()
        assertEquals(1, pending.size)
    }

    @Test fun slowHistoryNeverBlocksEnqueueAndFullFlushWaitsForIt() {
        val entered = CountDownLatch(1)
        val allow = CountDownLatch(1)
        val completed = CountDownLatch(1)
        val active = AtomicInteger()
        val calls = AtomicInteger()
        val pool = Executors.newSingleThreadExecutor()
        try {
            val cache = ReplayCacheWriter({
                assertEquals(1, active.incrementAndGet())
                if (calls.incrementAndGet() == 1) {
                    entered.countDown()
                    assertTrue(allow.await(3, TimeUnit.SECONDS))
                }
                active.decrementAndGet()
            }, pool)
            cache.enqueue()
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            cache.enqueue() // Would deadlock if enqueue shared the write lock.
            val fullStop = Thread { cache.flush(); completed.countDown() }
            fullStop.start()
            assertFalse(completed.await(50, TimeUnit.MILLISECONDS))
            allow.countDown()
            assertTrue(completed.await(1, TimeUnit.SECONDS))
            // The fresh rerun may acquire the write lock before full stop.
            // Both legal orders must serialize, finish and preserve the flush.
            assertTrue(calls.get() in 2..3)
        } finally { allow.countDown(); pool.shutdownNow() }
    }

    @Test fun failedWriteAllowsLaterPersistenceAttempt() {
        val pending = mutableListOf<Runnable>()
        var attempts = 0
        val cache = ReplayCacheWriter({ if (++attempts == 1) throw IllegalStateException("storage refused") }, Executor { pending.add(it) })
        cache.enqueue()
        try { pending.removeAt(0).run(); fail("write should fail") }
        catch (_: IllegalStateException) { }
        cache.enqueue()
        pending.removeAt(0).run()
        assertEquals(2, attempts)
    }

    @Test fun fullStopFlushesBeforeFreeingRingAndCancelsQueuedOldSnapshot() {
        val pending = mutableListOf<Runnable>()
        var ring = "held video"
        var disk = "previous cache"
        var writes = 0
        val cache = ReplayCacheWriter({ disk = ring; writes++ }, Executor { pending.add(it) })
        cache.enqueue()
        cache.flush() // Already-stopped video still needs this full-stop barrier.
        cache.invalidate { ring = "" }
        pending.removeAt(0).run()
        assertEquals("held video", disk)
        assertEquals(1, writes)
    }

    @Test fun qualityInvalidationCannotResurrectAnOldCache() {
        val pending = mutableListOf<Runnable>()
        var ring = "old standard format"
        var disk: String? = null
        val cache = ReplayCacheWriter({ disk = ring }, Executor { pending.add(it) })
        cache.enqueue()
        cache.invalidate { disk = null; ring = "new frame size" }
        pending.removeAt(0).run()
        assertNull(disk)
        cache.enqueue()
        pending.removeAt(0).run()
        assertEquals("new frame size", disk)
    }

    @Test fun invalidationWaitsForActiveWriterThenDeletesItsResult() {
        val entered = CountDownLatch(1)
        val allow = CountDownLatch(1)
        val removed = CountDownLatch(1)
        val pool = Executors.newSingleThreadExecutor()
        var disk: String? = null
        try {
            val cache = ReplayCacheWriter({
                entered.countDown()
                assertTrue(allow.await(3, TimeUnit.SECONDS))
                disk = "old cache"
            }, pool)
            cache.enqueue()
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            val quality = Thread { cache.invalidate { disk = null }; removed.countDown() }
            quality.start()
            assertFalse(removed.await(50, TimeUnit.MILLISECONDS))
            allow.countDown()
            assertTrue(removed.await(1, TimeUnit.SECONDS))
            assertNull(disk)
        } finally { allow.countDown(); pool.shutdownNow() }
    }


    @Test fun requestDuringActiveMuxWritesTheNewerSnapshotAfterward() {
        val snapshotted = CountDownLatch(1)
        val allow = CountDownLatch(1)
        val savedLatest = CountDownLatch(1)
        val pool = Executors.newSingleThreadExecutor()
        var ring = "first history"
        var disk = ""
        val writes = AtomicInteger()
        try {
            val cache = ReplayCacheWriter({
                val copy = ring
                if (writes.incrementAndGet() == 1) {
                    snapshotted.countDown()
                    assertTrue(allow.await(3, TimeUnit.SECONDS))
                }
                disk = copy
                if (copy == "newer history") savedLatest.countDown()
            }, pool)
            cache.enqueue()
            assertTrue(snapshotted.await(1, TimeUnit.SECONDS))
            ring = "newer history"
            cache.enqueue()
            allow.countDown()
            assertTrue(savedLatest.await(1, TimeUnit.SECONDS))
            assertEquals("newer history", disk)
            assertEquals(2, writes.get())
        } finally { allow.countDown(); pool.shutdownNow() }
    }


    @Test fun synchronousFlushAlsoAdvertisesBusyUntilFrozenBytesAreFree() {
        val entered = CountDownLatch(1)
        val allow = CountDownLatch(1)
        val done = CountDownLatch(1)
        val cache = ReplayCacheWriter({ entered.countDown(); assertTrue(allow.await(3, TimeUnit.SECONDS)) })
        val flusher = Thread { cache.flush(); done.countDown() }
        flusher.start()
        try {
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            assertTrue(cache.hasPending)
            allow.countDown()
            assertTrue(done.await(1, TimeUnit.SECONDS))
            assertFalse(cache.hasPending)
        } finally { allow.countDown() }
    }

}
