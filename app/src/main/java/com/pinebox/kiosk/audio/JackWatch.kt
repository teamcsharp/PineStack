package com.pinebox.kiosk.audio

import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.util.Log

/**
 * TELLING ANDROID THE CABLE IS IN, BECAUSE NOTHING ELSE WILL.
 *
 * "The audio still isn't being handed off to the audio jack whenever I plug
 * it into the tablet. Which is a very important feature. Typically I have
 * the audio being piped into a major system."
 *
 * THE FAULT, MEASURED END TO END WITH A CABLE IN THE SOCKET:
 *
 *     kernel        getevent: ACCDET, SW_HEADPHONE_INSERT
 *     dumpsys input SwitchValues: 4        <- the plug IS detected
 *     dumpsys audio mMainType=0x0          <- the framework does not know
 *     audio_policy  Available outputs: Speaker only
 *
 * InputManagerService reads the switch and then steps over the call that
 * would pass it on. Its own bytecode says why - the branch is guarded on
 * `mUseDevInputEventForAudioJack`, and this GSI ships that resource false:
 *
 *     iget-boolean v0, v6, InputManagerService.mUseDevInputEventForAudioJack
 *     if-eqz v0, 0080                 <- false, so jump past everything
 *     ...
 *     invoke-interface WiredAccessoryCallbacks.notifyWiredAccessoryChanged
 *
 * FIVE WAYS ROUND IT WERE TRIED AND EACH FAILED, which is why this exists:
 *
 *   1. A platform-signed RRO setting that boolean true. It installs and
 *      survives a reboot - but a /data overlay is applied AFTER IMS
 *      constructs (IMS at 15:12:43, the overlay at 15:12:44), so IMS still
 *      read false. A hard ordering wall, not a bug to fix.
 *   2. A fabricated overlay. Wiped on every framework start.
 *   3. `cmd audio` / a vendor force-route property. Neither exists here.
 *   4. AudioTrack.setPreferredDevice. Needs the device in getDevices(),
 *      which needs the framework to know - circular.
 *   5. Forcing the codec by hand as root. `HPL/HPR Mux` was set to Audio
 *      Playback and HELD, unopposed, for twenty seconds - and the operator
 *      still heard nothing. The vendor's own audio_device.xml explains it:
 *      `headphoneSpeaker_output` drives the SPEAKER through the same
 *      headphone pins in LoudSPK mode, so the amplifier's power follows
 *      whichever path the HAL opened. A mixer poke cannot open a path.
 *
 * So the announcement is the only cure, and this makes it: the same call
 * WiredAccessoryManager would have made, from a terminal that holds
 * MODIFY_AUDIO_ROUTING because it is signed with the platform key.
 *
 * WHY IT POLLS. The switch is readable through InputManager, which is a
 * question and not an event - there is no callback for a device the
 * framework has decided not to track. Two seconds is far below the time it
 * takes to plug a cable in and notice nothing happened, and the call is a
 * single binder round trip.
 */
class JackWatch(
    private val context: Context,
    /** Told when the route changes, so the rail can say where sound is going. */
    private val onChange: (Boolean) -> Unit = {},
) {

    private val audio: AudioManager? =
        context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager

    private var ticker: Thread? = null
    @Volatile private var running = false
    /**
     * WHAT THE FRAMEWORK HAS BEEN TOLD - and `null` until we have told it
     * anything in this process.
     *
     * This was a plain `false`, and that assumption cost the operator a
     * working jack. The announcement lives in the FRAMEWORK, not here: it
     * survives this app being killed, force-stopped, crashed or reinstalled,
     * because nothing in that path runs `stop()`. Measured after a reinstall
     * with no cable in the socket:
     *
     *     dumpsys audio          mMainType=0x1            (MAIN_HEADSET)
     *     media.audio_policy     "Wired Headset" Port 278 still available
     *     dumpsys input          SwitchValues: 0          (no cable)
     *
     * A fresh watch starting at `false` then read 0, decided it already
     * agreed, and said nothing - so the tablet went on playing into a
     * headset that was not there, and no amount of unplugging fixed it
     * because unplugging is exactly the transition it thought had happened.
     *
     * `null` means "we have not spoken yet", so the FIRST reading is always
     * announced, whatever it says. One redundant binder call on startup
     * against a terminal that is silently routed to nothing.
     */
    @Volatile private var announced: Boolean? = null

    @Volatile var lastSaid: String = "not started"
        private set

    /** Is a cable in, as far as the kernel is concerned? */
    fun pluggedIn(): Boolean = switchState() == 1

    /** Can this terminal find out by itself, or must it be told? */
    fun canDetect(): Boolean = switchState() >= 0

    /**
     * HAND THE AUDIO OVER BY HAND.
     *
     * Detection is not available on this build - neither InputManager nor
     * InputManagerGlobal exposes getSwitchState, measured, and /dev/input
     * belongs to root:input - so the operator gets a switch instead of an
     * automatic hand-off. It is not a consolation prize: someone piping
     * the station into a bigger system sets this once and leaves it, and a
     * switch he controls is arguably better than a guess the tablet makes.
     */
    fun force(on: Boolean): String {
        announce(on)
        return lastSaid
    }

    /** Whether the terminal currently believes the jack is carrying it. */
    fun handedOver(): Boolean = announced == true

    fun start() {
        if (running) return
        running = true
        ticker = Thread({
            while (running) {
                try { step() } catch (err: Exception) {
                    Log.w(TAG, "jack watch stumbled", err)
                }
                try { Thread.sleep(POLL_MS) } catch (err: InterruptedException) { break }
            }
        }, "pine-jack").apply { isDaemon = true; start() }
        Log.i(TAG, "jack watch on")
    }

    fun stop() {
        running = false
        ticker?.interrupt()
        ticker = null
        /* Leave the route as we found it: a terminal that shuts down
         * holding the audio on a cable nobody is listening to is worse
         * than one that gives it back. */
        if (announced == true) announce(false)
    }

    private fun step() {
        val read = switchState()
        /* -1 is "cannot tell", NOT "unplugged". A terminal that announced
         * "no cable" every two seconds because it could not read the
         * switch would fight whatever the operator had set by hand. */
        if (read < 0) return
        val inNow = read == 1
        /* `announced` is null on the first pass through, so this never
         * matches and the first reading is always passed on - see the field
         * for why that matters more than the wasted call. */
        if (inNow == announced) return
        announce(inNow)
    }

    /**
     * THE CALL ITSELF.
     *
     * `setWiredDeviceConnectionState` is @SystemApi and not in the SDK, so
     * it is reached by reflection. Its shape changed across versions and
     * both are tried rather than assuming one: older builds take
     * (int type, int state, String name), newer ones
     * (int type, int state, String address, String name).
     */
    private fun announce(on: Boolean) {
        val manager = audio ?: run {
            lastSaid = "there is no audio service to tell"
            return
        }
        val state = if (on) 1 else 0
        val type = AudioDeviceInfo.TYPE_WIRED_HEADPHONES

        val four = runCatching {
            AudioManager::class.java.getMethod(
                "setWiredDeviceConnectionState",
                Int::class.javaPrimitiveType, Int::class.javaPrimitiveType,
                String::class.java, String::class.java
            ).invoke(manager, type, state, "", "Pine Box jack")
        }
        if (four.isSuccess) {
            settled(on, "announced (4-arg)")
            return
        }

        val three = runCatching {
            AudioManager::class.java.getMethod(
                "setWiredDeviceConnectionState",
                Int::class.javaPrimitiveType, Int::class.javaPrimitiveType,
                String::class.java
            ).invoke(manager, type, state, "Pine Box jack")
        }
        if (three.isSuccess) {
            settled(on, "announced (3-arg)")
            return
        }

        /* Say WHICH refusal: a missing method and a refused permission are
         * different problems with different cures, and "it did not work"
         * has cost this project a day already. */
        val why = (four.exceptionOrNull() ?: three.exceptionOrNull())
        lastSaid = when {
            why is NoSuchMethodException ->
                "this build has no setWiredDeviceConnectionState to call"
            why?.cause is SecurityException ->
                "refused: the terminal does not hold MODIFY_AUDIO_ROUTING " +
                    "(is this build platform-signed?)"
            else -> "the call failed: " + (why?.cause?.message ?: why?.message ?: "unknown")
        }
        Log.w(TAG, lastSaid)
    }

    private fun settled(on: Boolean, how: String) {
        announced = on
        lastSaid = (if (on) "the jack is in — audio handed to it" else
            "the jack is out — audio back to the speaker") + " ($how)"
        Log.i(TAG, lastSaid)
        try { onChange(on) } catch (err: Exception) { /* the caller's business */ }
    }

    /**
     * The kernel's own answer, through InputManager.
     *
     * `getSwitchState` is hidden, so it is reflected. -1 means "unknown",
     * which is NOT the same as "unplugged" and is treated as unknown: a
     * terminal that announced "no cable" every time it could not read the
     * switch would fight the operator every two seconds.
     */
    @Volatile private var toldWhy = false

    private fun switchState(): Int {
        /* WHERE getSwitchState LIVES CHANGED.
         *
         * Measured on this Android 14 build:
         *   NoSuchMethodException: android.hardware.input.InputManager
         *                          .getSwitchState [int, int, int]
         *
         * In 14 the InputManager facade delegates to InputManagerGlobal,
         * and the method went with it. Rather than guess a second time,
         * both holders are tried and - if neither answers - the methods
         * that DO exist are listed once into the log, so the next person
         * reads the answer instead of discovering this again. */
        val candidates = mutableListOf<Pair<Any, String>>()
        context.getSystemService(Context.INPUT_SERVICE)?.let {
            candidates += it to "InputManager"
        }
        runCatching {
            val cls = Class.forName("android.hardware.input.InputManagerGlobal")
            val get = cls.getMethod("getInstance")
            get.invoke(null)?.let { candidates += it to "InputManagerGlobal" }
        }

        for ((holder, name) in candidates) {
            val got = runCatching {
                val m = holder.javaClass.getMethod(
                    "getSwitchState",
                    Int::class.javaPrimitiveType, Int::class.javaPrimitiveType,
                    Int::class.javaPrimitiveType
                )
                m.isAccessible = true
                (m.invoke(holder, ANY_DEVICE, SOURCE_ANY, SW_HEADPHONE_INSERT) as? Int) ?: -1
            }
            if (got.isSuccess) {
                once("$name.getSwitchState answered " + got.getOrDefault(-1))
                return got.getOrDefault(-1)
            }
        }

        /* THE SERVICE'S OWN DUMP.
         *
         * Neither facade has getSwitchState on this build, but the input
         * service still knows: `dumpsys input` prints
         *     SwitchValues: 4     with a cable in
         *     SwitchValues: 0     without
         * and 4 is bit 2, which is SW_HEADPHONE_INSERT. Reading a service
         * dump needs DUMP, which is signature|privileged - this APK is
         * platform-signed, so it has it.
         *
         * Tried AFTER the reflection roads, not instead of them: if a
         * later build puts getSwitchState back, that is one binder call
         * against this one's fork and parse. */
        val dumped = fromDump()
        if (dumped >= 0) {
            once("dumpsys input answered SwitchValues " + dumped)
            return dumped
        }

        if (!toldWhy) {
            val seen = candidates.joinToString("; ") { (holder, name) ->
                name + ": " + holder.javaClass.methods
                    .filter { it.name.contains("witch") }
                    .joinToString(",") { m ->
                        m.name + "(" + m.parameterTypes.joinToString(",") { t -> t.simpleName } + ")"
                    }.ifEmpty { "nothing with 'switch' in the name" }
            }
            once("no getSwitchState anywhere - what exists is: " + seen)
        }
        return -1
    }

    /**
     * SwitchValues out of the input service's dump, or -1.
     *
     * The dump is large, so it is read line by line and abandoned the
     * moment the answer is found - this runs every couple of seconds for
     * the life of the terminal and must not become the thing that makes
     * the tablet warm.
     */
    private fun fromDump(): Int {
        return runCatching {
            val proc = ProcessBuilder("/system/bin/dumpsys", "input")
                .redirectErrorStream(true).start()
            var found = -1
            try {
                proc.inputStream.bufferedReader().use { reader ->
                    while (true) {
                        val line = reader.readLine() ?: break
                        val at = line.indexOf("SwitchValues:")
                        if (at < 0) continue
                        val value = line.substring(at + 13).trim()
                            .takeWhile { it.isDigit() }
                        found = value.toIntOrNull() ?: -1
                        break
                    }
                }
            } finally {
                proc.destroy()
            }
            /* SwitchValues is a BITMASK, not a state: bit 2 (value 4) is
             * SW_HEADPHONE_INSERT. Returning the raw 4 as if it were a
             * boolean would be wrong the first time another switch is on. */
            if (found < 0) -1 else if ((found and (1 shl SW_HEADPHONE_INSERT)) != 0) 1 else 0
        }.getOrElse { -1 }
    }

    private fun once(what: String) {
        if (toldWhy) return
        toldWhy = true
        Log.i(TAG, "reading the jack switch: " + what)
    }

    private companion object {
        const val TAG = "PineJack"
        const val POLL_MS = 2000L
        /** InputDevice.SOURCE_ANY, and "ask every device". */
        const val ANY_DEVICE = -1
        const val SOURCE_ANY = -256
        /** linux/input-event-codes.h: SW_HEADPHONE_INSERT. */
        const val SW_HEADPHONE_INSERT = 2
    }
}
