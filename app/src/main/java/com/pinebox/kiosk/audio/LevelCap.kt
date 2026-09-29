package com.pinebox.kiosk.audio

import android.media.AudioDeviceInfo
import android.media.AudioManager

/**
 * A NEW OUTPUT NEVER STARTS LOUDER THAN THE ONE THE OPERATOR WAS HEARING.
 *
 * "I just don't want the audio to go louder than the level that I have it
 * set at."
 *
 * Android keeps a STREAM_MUSIC index PER OUTPUT DEVICE (dumpsys audio,
 * STREAM_MUSIC "Current:" - measured 2026-09-29: speaker 5, headset 10,
 * headphone 20, usb_headset 6). A route change therefore changes the level
 * with nobody touching a slider: speaker at 5 -> cable in -> headphone at 20.
 * For a sound-sensitive listener that is a blast, whatever caused the move.
 *
 * The rule, everywhere the route can move:
 *   - BEFORE a move this terminal makes itself (JackWatch's announcement),
 *     lower the target device's stored index to the current level, so it
 *     comes up no louder. AudioService's setDeviceVolume refuses the device
 *     in use ("skipping"), so this can never change what is audible now.
 *   - AFTER a move anyone else makes (USB, Bluetooth), OutputRoute lowers the
 *     new device to the previous device's index if it came up higher.
 * Only ever LOWERS. The operator's own raises are never undone, because a
 * raise is not a route change.
 *
 * getDeviceVolume/setDeviceVolume are @SystemApi (API 34) and need
 * MODIFY_AUDIO_ROUTING, which this platform-signed APK holds - reached by
 * reflection like JackWatch's setWiredDeviceConnectionState.
 */
object LevelCap {

    private const val ROLE_OUTPUT = 2 // AudioDeviceAttributes.ROLE_OUTPUT

    /** The stored STREAM_MUSIC index of an output, or null if it cannot be asked. */
    fun deviceIndex(audio: AudioManager, type: Int, address: String = ""): Int? = runCatching {
        val got = AudioManager::class.java.getMethod("getDeviceVolume", viClass, adaClass)
            .invoke(audio, volumeInfo(null), ada(type, address))
        viClass.getMethod("getVolumeIndex").invoke(got) as Int
    }.getOrNull()?.takeIf { it >= 0 }

    fun deviceIndex(audio: AudioManager, device: AudioDeviceInfo): Int? =
        deviceIndex(audio, device.type, device.address.orEmpty())

    /**
     * Lower a device that is NOT playing to at most [max]. Never raises; a
     * no-op on the device in use (AudioService skips it). Says what it did.
     */
    fun lowerIdle(audio: AudioManager, type: Int, max: Int, address: String = ""): String {
        val have = deviceIndex(audio, type, address) ?: return "level of type $type unknown; left alone"
        val cap = capIndex(max, have) ?: return "type $type already at $have <= $max"
        return runCatching {
            AudioManager::class.java.getMethod("setDeviceVolume", viClass, adaClass)
                .invoke(audio, volumeInfo(cap), ada(type, address))
            "type $type lowered $have -> $cap before the move"
        }.getOrElse { "could not lower type $type: " + (it.cause?.message ?: it.message) }
    }

    /**
     * After a move: if the device now in use came up louder than [before]
     * was, bring it down to [before]'s level. Never raises.
     */
    fun holdAfterMove(audio: AudioManager, before: AudioDeviceInfo): String {
        val was = deviceIndex(audio, before) ?: return "previous level unknown; left alone"
        val now = audio.getStreamVolume(AudioManager.STREAM_MUSIC)
        val cap = capIndex(was, now) ?: return "new output at $now <= previous $was; kept"
        audio.setStreamVolume(AudioManager.STREAM_MUSIC, cap, 0)
        return "new output came up at $now over the previous $was; lowered to $cap"
    }

    private val viClass by lazy { Class.forName("android.media.VolumeInfo") }
    private val builderClass by lazy { Class.forName("android.media.VolumeInfo\$Builder") }
    private val adaClass by lazy { Class.forName("android.media.AudioDeviceAttributes") }

    private fun volumeInfo(index: Int?): Any {
        val b = builderClass.getConstructor(Int::class.javaPrimitiveType)
            .newInstance(AudioManager.STREAM_MUSIC)
        if (index != null) builderClass.getMethod("setVolumeIndex", Int::class.javaPrimitiveType).invoke(b, index)
        return builderClass.getMethod("build").invoke(b)!!
    }

    private fun ada(type: Int, address: String): Any =
        adaClass.getConstructor(Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, String::class.java)
            .newInstance(ROLE_OUTPUT, type, address)
}

/**
 * The whole rule as a pure function: the index to lower [next] to so it is
 * no louder than [previous], or null when nothing may change (already at or
 * below, or a level is unknown). Never returns a raise.
 */
internal fun capIndex(previous: Int?, next: Int?): Int? {
    if (previous == null || next == null || previous < 0 || next < 0) return null
    return if (next > previous) previous else null
}
