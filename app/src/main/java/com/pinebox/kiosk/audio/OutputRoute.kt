package com.pinebox.kiosk.audio

import android.content.Context
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Handler

/**
 * WHERE THE SOUND IS ACTUALLY COMING OUT.
 *
 * "When I plug an aux cable into the tablet, I want the audio coming out of
 * the aux cable that's been plugged into the tablet."
 *
 * MEASURED ON THE TABLET FIRST, because the obvious explanation was wrong.
 * The jack is not missing: /proc/bus/input/devices carries an ACCDET input
 * device (event0) with SW=0xd4 - SW_HEADPHONE_INSERT, SW_MICROPHONE_INSERT,
 * SW_LINEOUT_INSERT and SW_JACK_PHYSICAL_INSERT - and the vendor policy at
 * /vendor/etc/audio_policy_configuration.xml declares both
 * AUDIO_DEVICE_OUT_WIRED_HEADSET and AUDIO_DEVICE_OUT_WIRED_HEADPHONE. The
 * detection path is whole, end to end.
 *
 * So this class does not force a route, and deliberately cannot. Android
 * moves STREAM_MUSIC to a headset on its own the moment one is connected,
 * and an app that overrides that fights the operator's own hardware. What
 * was actually missing is two smaller things:
 *
 *   1. THE PADS DID NOT FOLLOW. The sampler holds an Oboe stream in
 *      Exclusive/LowLatency mode. Those do not migrate: the stream is
 *      DISCONNECTED on a route change and has to be reopened.
 *      OboeOutput::onErrorAfterClose already reopens, but only when the
 *      stream actually errors - a stream that is idle when the cable goes
 *      in never errors, and then the next pad press opens on a stale
 *      device. Reopening on the route change itself closes that window.
 *
 *   2. THERE WAS NO WAY TO SEE IT. "I want the audio coming out of the aux
 *      cable" is not checkable from across the room, and a tablet that is
 *      quietly playing to its own speaker looks exactly like a tablet that
 *      is playing to a cable. The rail now names the output.
 */
class OutputRoute(
    context: Context,
    private val handler: Handler,
    /** Called on the main thread whenever the output changes. */
    private val onChange: (String) -> Unit,
    /** Reopen the low-latency stream; it does not migrate by itself. */
    private val reopen: () -> Unit = {},
) {

    private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var last = ""

    private val callback = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>?) = settle()
        override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>?) = settle()
    }

    fun start() {
        audio.registerAudioDeviceCallback(callback, handler)
        settle()
    }

    fun stop() {
        audio.unregisterAudioDeviceCallback(callback)
    }

    /** The name of the output the show is going to, right now. */
    fun current(): String = describe(pick())

    private fun settle() {
        val now = current()
        if (now == last) return
        val first = last.isEmpty()
        last = now
        /* Not on the very first read: there is no route CHANGE at startup,
         * and reopening a stream that was just opened is pure jank. */
        if (!first) reopen()
        onChange(now)
    }

    /**
     * Which device Android will send media to.
     *
     * The order is Android's own routing precedence, not a preference of
     * ours: a wired plug beats Bluetooth, Bluetooth beats the speaker. USB
     * counts as wired - a USB-C to 3.5mm adapter is an aux cable as far as
     * the operator is concerned, and this tablet enumerates usb_headset.
     */
    private fun pick(): AudioDeviceInfo? {
        val outputs = audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
        for (rank in RANKS) {
            val found = outputs.firstOrNull { it.type == rank }
            if (found != null) return found
        }
        return outputs.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
    }

    private fun describe(device: AudioDeviceInfo?): String = when (device?.type) {
        null -> "no output"
        AudioDeviceInfo.TYPE_WIRED_HEADSET -> "the aux cable (headset)"
        AudioDeviceInfo.TYPE_WIRED_HEADPHONES -> "the aux cable"
        AudioDeviceInfo.TYPE_LINE_ANALOG -> "the line out"
        AudioDeviceInfo.TYPE_USB_HEADSET -> "a USB headset"
        AudioDeviceInfo.TYPE_USB_DEVICE -> "a USB audio device"
        AudioDeviceInfo.TYPE_BLUETOOTH_A2DP -> bluetoothName(device)
        AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> bluetoothName(device)
        AudioDeviceInfo.TYPE_BUILTIN_SPEAKER -> "the tablet speaker"
        else -> device.productName?.toString()?.ifBlank { "an output" } ?: "an output"
    }

    private fun bluetoothName(device: AudioDeviceInfo): String {
        val name = device.productName?.toString().orEmpty()
        return if (name.isBlank()) "Bluetooth" else name + " (Bluetooth)"
    }

    companion object {
        /** Android's own precedence for media, highest first. */
        private val RANKS = intArrayOf(
            AudioDeviceInfo.TYPE_WIRED_HEADSET,
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
            AudioDeviceInfo.TYPE_LINE_ANALOG,
            AudioDeviceInfo.TYPE_USB_HEADSET,
            AudioDeviceInfo.TYPE_USB_DEVICE,
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,
            AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
        )

        /** True when the show is going somewhere other than the speaker. */
        fun isWired(label: String): Boolean =
            label.contains("aux") || label.contains("line out") || label.contains("USB")
    }
}
