package com.pinebox.kiosk.replay

import org.junit.Assert.*
import org.junit.Test

class MirrorEncoderLeaseTest {
    @Test fun acquireRetainsOriginalReplayStateAcrossRenewal() {
        val lease = MirrorEncoderLease()
        assertTrue(lease.acquire("mirror_first", 100L, 60_000L, true))
        assertTrue(lease.acquire("mirror_first", 200L, 60_000L, false))
        assertTrue(lease.resumeWanted)
        assertEquals(true, lease.release("mirror_first", false))
        assertFalse(lease.held)
    }

    @Test fun stoppedReplayIsNotEnabledWhenMirrorCloses() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_first", 0L, 60_000L, false)
        assertEquals(false, lease.release("mirror_first", false))
    }

    @Test fun anotherOwnerCannotAcquireRenewOrRelease() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_first", 0L, 60_000L, true)
        assertFalse(lease.acquire("mirror_second", 10L, 60_000L, true))
        assertFalse(lease.renew("mirror_second", 10L, 60_000L))
        assertNull(lease.release("mirror_second", false))
        assertEquals("mirror_first", lease.owner)
    }

    @Test fun expiryWaitsForRecorderToFinishAndForKnownProbe() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_first", 100L, 15_000L, true)
        assertNull(lease.expire(15_099L, false))
        assertNull(lease.expire(15_100L, true))
        assertNull(lease.expire(16_100L, null))
        assertTrue(lease.held)
        assertEquals(true, lease.expire(17_100L, false))
        assertFalse(lease.held)
    }

    @Test fun explicitStopDuringHoldCancelsAutomaticRestore() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_first", 0L, 60_000L, true)
        lease.cancelResume()
        assertEquals(false, lease.release("mirror_first", false))
    }

    @Test fun renewalMovesDeadlineWithoutChangingRestoreState() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_first", 0L, 15_000L, true)
        assertTrue(lease.renew("mirror_first", 10_000L, 60_000L))
        assertNull(lease.expire(20_000L, false))
        assertEquals(true, lease.expire(70_000L, false))
    }

    @Test fun ttlAndOwnerAreBounded() {
        val lease = MirrorEncoderLease()
        assertFalse(lease.acquire("x;bad", 0L, 60_000L, true))
        assertTrue(lease.acquire("mirror_first", 5L, 0L, true))
        assertEquals(15_005L, lease.untilMs)
        lease.renew("mirror_first", 5L, Long.MAX_VALUE)
        assertEquals(120_005L, lease.untilMs)
    }

    @Test fun externalRecorderProbeRejectsUnrecognisedOrRefusedDump() {
        assertNull(MirrorEncoderLease.parseExternalRecorder("Permission Denial"))
        assertNull(MirrorEncoderLease.parseExternalRecorder(""))
        assertEquals(false, MirrorEncoderLease.parseExternalRecorder("Display 0 (physical, \"Primary display\")\nDisplay 1 (virtual, \"pine-replay\")"))
        assertEquals(true, MirrorEncoderLease.parseExternalRecorder("Display 0 (physical, \"Primary display\")\nDisplay 2 (virtual, \"ScreenRecorder\")"))
    }


    @Test fun persistedExpiredLeaseStaysHeldThroughNativeRecorderTeardown() {
        val lease = MirrorEncoderLease()
        assertTrue(lease.restore("mirror_previous_process", 10L, true))
        assertTrue(lease.held)
        assertNull(lease.expire(50L, true))
        assertNull(lease.expire(50L, null))
        assertEquals(true, lease.expire(50L, false))
        assertFalse(lease.held)
    }

    @Test fun reconstructedDisabledReplayDoesNotStartAfterExpiry() {
        val lease = MirrorEncoderLease()
        assertTrue(lease.restore("mirror_previous_process", 10L, false))
        assertEquals(false, lease.expire(50L, false))
        assertFalse(lease.restore("corrupt!", 60L, true))
    }

    @Test fun recorderProcessProofCoversTimeBeforeAndAfterCompositorDisplay() {
        assertEquals(false, MirrorEncoderLease.parseRecorderProcess("No process found for: screenrecord\n"))
        assertEquals(true, MirrorEncoderLease.parseRecorderProcess("Applications Memory Usage\n** MEMINFO in pid 456 [screenrecord] **\n"))
        assertNull(MirrorEncoderLease.parseRecorderProcess("Permission Denial"))
        assertNull(MirrorEncoderLease.parseRecorderProcess("Applications Memory Usage"))
    }

    @Test fun resourceInventoryDistinguishesVideoEncodersFromAudioAndDecoders() {
        fun inventory(name: String, resource: String) =
            "ResourceManagerService: service\n  Processes:\n    Pid: 12434\n      Client:\n        Name: " + name +
                "\n        Resources:\n          non-secure-codec/" + resource + ":[]:1\n  Process Pid override:\n"
        assertEquals(true, MirrorEncoderLease.parseVideoEncoders(inventory("c2.mtk.avc.encoder", "video-codec")))
        assertEquals(true, MirrorEncoderLease.parseVideoEncoders(inventory("OMX.MTK.VIDEO.ENCODER.AVC", "video-codec")))
        assertEquals(false, MirrorEncoderLease.parseVideoEncoders(inventory("c2.mtk.avc.decoder", "video-codec")))
        assertEquals(false, MirrorEncoderLease.parseVideoEncoders(inventory("c2.android.aac.encoder", "audio-codec")))
        assertNull(MirrorEncoderLease.parseVideoEncoders("Permission Denial"))
        assertNull(MirrorEncoderLease.parseVideoEncoders(inventory("c2.vendor.avc.enc", "video-codec")))
        assertNull(MirrorEncoderLease.parseVideoEncoders("ResourceManagerService: service\n Processes:\n malformed payload\n Process Pid override:\n"))
        assertNull(MirrorEncoderLease.parseVideoEncoders(inventory("c2.mtk.avc.decoder", "video-codec").substringBefore("Process Pid override:")))
        assertNull(MirrorEncoderLease.parseVideoEncoders("ResourceManagerService: service\n Processes:\n Client:\n Resources: video-codec\n"))
    }

    @Test fun cancelledRestoreIntentRemainsOffWhenProcessIsRecreated() {
        val original = MirrorEncoderLease()
        original.acquire("mirror_original_owner", 0L, 60_000L, true)
        original.cancelResume()
        val restarted = MirrorEncoderLease()
        restarted.restore(original.owner, original.untilMs, original.resumeWanted)
        assertEquals(false, restarted.expire(60_001L, false))
    }

    @Test fun jpegCaptureRequiresTheExactUnexpiredOwner() {
        val lease = MirrorEncoderLease()
        assertTrue(lease.acquire("mirror_owner_one", 100, 15_000, true))
        assertTrue(lease.ownsCurrent("mirror_owner_one", 15_099))
        assertFalse(lease.ownsCurrent("mirror_owner_two", 101))
        assertFalse(lease.ownsCurrent("mirror_owner_one", 15_100))
    }

    @Test fun restoredExpiredHoldCannotStartCaptureUntilOwnerRenews() {
        val lease = MirrorEncoderLease()
        assertTrue(lease.restore("mirror_owner_one", 100, true))
        assertFalse(lease.ownsCurrent("mirror_owner_one", 101))
        assertTrue(lease.renew("mirror_owner_one", 101, 15_000))
        assertTrue(lease.ownsCurrent("mirror_owner_one", 102))
    }

    @Test fun jpegResourcesBlockExplicitReleaseDespiteClearExternalProof() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_owner_one", 0, 15_000, true)
        assertNull(lease.release("mirror_owner_one", false, captureReleased = false))
        assertTrue(lease.held)
        assertTrue(lease.resumeWanted)
        assertEquals(true, lease.release("mirror_owner_one", false, captureReleased = true))
        assertFalse(lease.held)
    }

    @Test fun renewedDeadlineAndPendingJpegResourcesBlockExpiry() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_owner_one", 0, 15_000, true)
        lease.renew("mirror_owner_one", 14_000, 15_000)
        assertNull(lease.expire(15_001, false, captureReleased = true))
        assertTrue(lease.held)
        assertNull(lease.expire(29_000, false, captureReleased = false))
        assertTrue(lease.held)
        assertEquals(true, lease.expire(29_000, false, captureReleased = true))
    }

    @Test fun jpegVirtualDisplayRemainsAnExternalCaptureUntilGone() {
        assertEquals(true, MirrorEncoderLease.parseExternalRecorder(
            "Display 2 (virtual, secure):\n name=ScreenRecorder-PineMirrorJPEG"))
    }

    @Test fun fullStopCancellationSurvivesDelayedJpegCleanup() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_owner_one", 0, 15_000, true)
        lease.cancelResume()
        assertNull(lease.release("mirror_owner_one", false, captureReleased = false))
        assertEquals(false, lease.release("mirror_owner_one", false, captureReleased = true))
    }


    @Test fun coldHeldVideoStartRestoresAfterRelease() {
        val lease = MirrorEncoderLease()
        assertTrue(lease.acquire("mirror_cold_start", 100L, 15000L, false))
        assertTrue(lease.requestResume())
        assertEquals(true, lease.release("mirror_cold_start", false))
    }

    @Test fun coldHeldVideoStartRestoresAfterExpiry() {
        val lease = MirrorEncoderLease()
        assertTrue(lease.acquire("mirror_cold_expiry", 100L, 15000L, false))
        assertTrue(lease.requestResume())
        assertEquals(true, lease.expire(15100L, false))
    }

    @Test fun explicitVideoStopCancelsDeferredHeldStart() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_cold_cancel", 100L, 15000L, false)
        lease.requestResume()
        lease.cancelResume()
        val restarted = MirrorEncoderLease()
        assertTrue(restarted.restore(lease.owner, lease.untilMs, lease.resumeWanted))
        assertEquals(false, restarted.release("mirror_cold_cancel", false))
    }

    @Test fun initiallyOffHoldWithoutStartRequestStaysOff() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_video_off", 100L, 15000L, false)
        assertEquals(false, lease.release("mirror_video_off", false))
    }

    @Test fun requestedStartSurvivesPersistedProcessRecreation() {
        val lease = MirrorEncoderLease()
        lease.acquire("mirror_cold_restart", 100L, 15000L, false)
        lease.requestResume()
        val restarted = MirrorEncoderLease()
        assertTrue(restarted.restore(lease.owner, lease.untilMs, lease.resumeWanted))
        assertEquals(true, restarted.release("mirror_cold_restart", false))
    }

    @Test fun startIntentNeverClearsCaptureOwnershipProof() {
        val lease = MirrorEncoderLease()
        assertFalse(lease.requestResume())
        lease.acquire("mirror_cold_proof", 100L, 15000L, false)
        lease.requestResume()
        assertNull(lease.release("mirror_cold_proof", null))
        assertTrue(lease.held)
        assertTrue(lease.resumeWanted)
        assertNull(lease.release("mirror_cold_proof", false, false))
        assertTrue(lease.held)
    }
}
