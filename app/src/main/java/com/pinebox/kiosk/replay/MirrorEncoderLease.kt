package com.pinebox.kiosk.replay

/** One encoder owner at a time. Time passing alone never releases an encoder:
 * the caller must also establish that the external recorder has gone away. */
internal class MirrorEncoderLease {
    var owner: String = ""
        private set
    var untilMs: Long = 0L
        private set
    var resumeWanted: Boolean = false
        private set
    val held: Boolean get() = owner.isNotEmpty()

    fun acquire(who: String, nowMs: Long, ttlMs: Long, wasRunning: Boolean): Boolean {
        if (!validOwner(who) || (held && owner != who)) return false
        if (!held) resumeWanted = wasRunning
        owner = who
        untilMs = nowMs + ttlMs.coerceIn(MIN_TTL_MS, MAX_TTL_MS)
        return true
    }

    fun renew(who: String, nowMs: Long, ttlMs: Long): Boolean {
        if (!held || who != owner) return false
        untilMs = nowMs + ttlMs.coerceIn(MIN_TTL_MS, MAX_TTL_MS)
        return true
    }

    fun restore(who: String, deadlineMs: Long, restoreVideo: Boolean): Boolean {
        if (!validOwner(who)) return false
        owner = who
        untilMs = deadlineMs
        resumeWanted = restoreVideo
        return true
    }

    /** Retain a genuine video start requested while capture has the hold. */
    fun requestResume(): Boolean {
        if (!held) return false
        resumeWanted = true
        return true
    }

    fun cancelResume() { resumeWanted = false }

    /** Capture may only start under the exact, unexpired persisted owner. */
    fun ownsCurrent(who: String, nowMs: Long): Boolean =
        held && who == owner && validOwner(who) && nowMs < untilMs

    /** null means the hold must remain; true/false says whether to restore. */
    fun release(who: String, externalRecorderActive: Boolean?, captureReleased: Boolean = true): Boolean? {
        if (!held || who != owner || externalRecorderActive != false || !captureReleased) return null
        val restore = resumeWanted
        owner = ""
        untilMs = 0L
        resumeWanted = false
        return restore
    }

    fun expire(nowMs: Long, externalRecorderActive: Boolean?, captureReleased: Boolean = true): Boolean? {
        if (!held || nowMs < untilMs) return null
        return release(owner, externalRecorderActive, captureReleased)
    }

    companion object {
        const val MIN_TTL_MS = 15_000L
        const val MAX_TTL_MS = 120_000L
        fun validOwner(who: String) = Regex("[A-Za-z0-9_-]{8,100}").matches(who)

        fun parseExternalRecorder(dump: String): Boolean? {
            if (!Regex("(?m)^Display [0-9]+ [(](physical|virtual),").containsMatchIn(dump)) return null
            return dump.contains("ScreenRecorder", ignoreCase = true)
        }

        fun parseRecorderProcess(dump: String): Boolean? {
            if (dump.trim() == "No process found for: screenrecord") return false
            if (dump.contains("[screenrecord]") && Regex("MEMINFO in pid [0-9]+").containsMatchIn(dump)) return true
            return null
        }

        /** Resource manager retains video codec ownership through teardown.
         * Audio encoders/decoders do not compete with the H.264 encoder. */
        fun parseVideoEncoders(dump: String): Boolean? {
            if (!dump.contains("ResourceManagerService:") || !dump.contains("Processes:") ||
                !dump.contains("Process Pid override:")) return null
            val processes = dump.substringAfter("Processes:").substringBefore("Process Pid override:")
            val clients = processes.split("Client:")
            for (line in clients.first().lines().map { it.trim() }.filter { it.isNotEmpty() }) {
                if (!Regex("Pid: [0-9]+").matches(line) && !line.startsWith("Priority:")) return null
            }
            var uncertain = false
            for (client in clients.drop(1)) {
                if (!client.contains("Resources:")) return null
                val name = Regex("(?m)^[ ]*Name:[ ]*(.+)$").find(client)?.groupValues?.get(1)
                if (!client.contains("video-codec")) continue
                if (name == null) uncertain = true
                else if (name.contains("encoder", true) || name.contains("video.enc", true)) return true
                else if (!name.contains("decoder", true) && !name.contains("video.dec", true)) uncertain = true
            }
            return if (uncertain) null else false
        }

    }
}
