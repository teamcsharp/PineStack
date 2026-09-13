package com.pinebox.kiosk.power

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * HOW LONG THE RADIO HAS LEFT, AND WHAT IS EATING IT.
 *
 * "I want a section talking about the battery... how much power I have left
 * in the tablet, how much life I have left on the radio before the tablet
 * dies... what processes are being used in the back of the tablet, what's
 * choking the tablet."
 *
 * THE RUNTIME IS COMPUTED, NOT GUESSED. Android's own
 * `computeChargeTimeRemaining` only answers while CHARGING, which is the
 * case the operator cares about least. Discharge time is arithmetic the
 * platform will not do for you:
 *
 *     charge counter (µAh)  /  average current (µA)  =  hours left
 *
 * Both come from BatteryManager as integers, and both have traps that are
 * worth naming because they silently produce nonsense:
 *
 *   - CURRENT_NOW's SIGN IS NOT AGREED ON. The API says negative means
 *     discharging; a good many MediaTek kernels report a positive number
 *     while draining. So the magnitude is used and the DIRECTION is taken
 *     from the battery status, which is unambiguous.
 *   - CURRENT_NOW IS AN INSTANT, and an instant on a device that is
 *     rendering WebGL is not the hour ahead. CURRENT_AVERAGE is preferred
 *     where the kernel offers it, and where it does not the readings are
 *     smoothed here instead of being believed one at a time.
 *   - A ZERO CHARGE COUNTER means the fuel gauge is not reporting, and the
 *     honest answer is then "I cannot tell you", not a number derived from
 *     a percentage and a guess at capacity.
 *
 * WHAT IT WILL NOT PRETEND TO KNOW, measured rather than assumed:
 *
 *   - OTHER APPS' PROCESSES. Since Android 8 `getRunningAppProcesses`
 *     returns only the caller's own, and `/proc/<pid>` of anything else is
 *     unreadable. There is no per-app table to show.
 *   - SYSTEM CPU AND LOAD AVERAGE. An earlier draft of this file read
 *     /proc/stat and /proc/loadavg and reported both. Tested as the app's
 *     own uid on this device:
 *         cat: /proc/loadavg: Permission denied
 *         head: /proc/stat: Permission denied
 *     SELinux forbids them to app domains, so those two figures could
 *     NEVER have worked - they would have read "-1" and "not readable"
 *     forever, in a card whose whole job is to be trusted. They are gone.
 *
 * What is left is all measured and all real: the fuel gauge, the current
 * draw, the temperature, the thermal throttling state, memory headroom,
 * and this app's own footprint. On a kiosk the app IS very nearly the
 * whole workload, so what the TERMINAL is running - see `load` - is the
 * honest answer to "what is choking the tablet", and it is the one the
 * operator can actually act on.
 */
class PowerWatch(private val context: Context) {

    /** One reading of everything, taken together so the numbers agree. */
    data class Reading(
        val percent: Int,
        val charging: Boolean,
        val full: Boolean,
        val plugged: String,
        val milliAmps: Int,          /* magnitude; direction is `charging` */
        val chargeNowUah: Int,
        val chargeFullUah: Int,
        val volts: Double,
        val celsius: Double,
        val health: String,
        val saverOn: Boolean,
        val dozing: Boolean,
        val thermal: String,
        val minutesLeft: Int,        /* -1 when it cannot be told */
        val basis: String,           /* how minutesLeft was arrived at */
        val cores: Int,
        val ramFreeMb: Int,
        val ramTotalMb: Int,
        val ramLow: Boolean,
        val appMb: Int,
        val choke: String,           /* the constraint, in words */
    )

    /* CURRENT_NOW jumps about; a single sample is not an hour. Kept small
     * on purpose - a long average would hide the operator turning the
     * screen brightness up, which is exactly the sort of thing he wants to
     * see reflected. */
    private val recent = ArrayDeque<Int>()

    /** What this terminal has running that costs power. Set by the rail,
     *  which is the only thing that knows - the mic, the open view, the
     *  WebGL scenes. Empty is a true answer: "just the panel". */
    @Volatile var load: List<String> = emptyList()

    fun read(): Reading? {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
        val status: Intent = context.registerReceiver(
            null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        ) ?: return null

        val rawLevel = status.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = status.getIntExtra(BatteryManager.EXTRA_SCALE, 100)
        val percent = if (rawLevel < 0 || scale <= 0) -1
        else ((rawLevel * 100f) / scale).roundToInt()

        val state = status.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val charging = state == BatteryManager.BATTERY_STATUS_CHARGING
            || state == BatteryManager.BATTERY_STATUS_FULL
        val full = state == BatteryManager.BATTERY_STATUS_FULL

        val plugged = when (status.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0)) {
            BatteryManager.BATTERY_PLUGGED_AC -> "the charger"
            BatteryManager.BATTERY_PLUGGED_USB -> "USB"
            BatteryManager.BATTERY_PLUGGED_WIRELESS -> "a wireless pad"
            else -> ""
        }

        /* Prefer the average; fall back to the instant and smooth it here. */
        val average = bm?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_AVERAGE) ?: 0
        val instant = bm?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW) ?: 0
        val microAmps = if (average != 0 && abs(average) != Int.MAX_VALUE) average else instant
        val milliAmps = smooth(abs(microAmps) / 1000)

        val chargeNow = bm?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER) ?: 0
        val capacityPct = bm?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: percent
        /* The full-charge figure the gauge implies, for context only. */
        val chargeFull = if (chargeNow > 0 && capacityPct > 0)
            (chargeNow * 100.0 / capacityPct).roundToInt() else 0

        val volts = status.getIntExtra(BatteryManager.EXTRA_VOLTAGE, 0) / 1000.0
        val celsius = status.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10.0
        val health = when (status.getIntExtra(BatteryManager.EXTRA_HEALTH, 0)) {
            BatteryManager.BATTERY_HEALTH_GOOD -> "good"
            BatteryManager.BATTERY_HEALTH_OVERHEAT -> "overheating"
            BatteryManager.BATTERY_HEALTH_DEAD -> "dead"
            BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE -> "over voltage"
            BatteryManager.BATTERY_HEALTH_COLD -> "cold"
            else -> "unknown"
        }

        val pm = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
        val saverOn = pm?.isPowerSaveMode ?: false
        val dozing = pm?.isDeviceIdleMode ?: false
        val thermal = thermalWord(pm)

        /* ---- how long that leaves ---- */
        var minutes = -1
        var basis: String
        if (charging) {
            val ms = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P)
                bm?.computeChargeTimeRemaining() ?: -1L else -1L
            if (ms > 0) {
                minutes = (ms / 60000L).toInt()
                basis = "the platform's own estimate to full"
            } else {
                basis = "charging - the platform gives no estimate on this build"
            }
        } else if (chargeNow > 0 && milliAmps > 0) {
            minutes = ((chargeNow / 1000.0) / milliAmps * 60.0).roundToInt()
            basis = "$chargeNow µAh left, drawing $milliAmps mA"
        } else if (chargeNow <= 0) {
            basis = "the fuel gauge reports no charge counter, so this " +
                "device cannot say"
        } else {
            basis = "the draw is not measurable yet - give it a moment"
        }

        /* ---- what is actually loading the thing ---- */
        val cores = Runtime.getRuntime().availableProcessors()

        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
        val mem = ActivityManager.MemoryInfo()
        am?.getMemoryInfo(mem)
        val freeMb = (mem.availMem / (1024 * 1024)).toInt()
        val totalMb = (mem.totalMem / (1024 * 1024)).toInt()

        val mine = am?.getProcessMemoryInfo(intArrayOf(android.os.Process.myPid()))
        val appMb = ((mine?.firstOrNull()?.totalPss ?: 0) / 1024)

        return Reading(
            percent = percent, charging = charging, full = full, plugged = plugged,
            milliAmps = milliAmps, chargeNowUah = chargeNow, chargeFullUah = chargeFull,
            volts = volts, celsius = celsius, health = health,
            saverOn = saverOn, dozing = dozing, thermal = thermal,
            minutesLeft = minutes, basis = basis,
            cores = cores,
            ramFreeMb = freeMb, ramTotalMb = totalMb, ramLow = mem.lowMemory,
            appMb = appMb,
            choke = chokeWord(freeMb, mem.lowMemory, thermal, celsius, milliAmps, charging),
        )
    }

    /** A short, plain sentence naming the constraint - or saying there is
     *  none, which is just as useful and is the usual answer. */
    /**
     * A short, plain sentence naming the constraint - or saying there is
     * none, which is just as useful and is the usual answer.
     *
     * The draw in milliamps stands in for the processor figure that cannot
     * be read: on a tablet doing nothing but showing a page, a few hundred
     * milliamps is the screen; a thousand and up is real work, and on this
     * terminal real work is WebGL. It is a proxy and is described as one.
     */
    private fun chokeWord(
        freeMb: Int, lowMemory: Boolean, thermal: String,
        celsius: Double, milliAmps: Int, charging: Boolean,
    ): String {
        if (thermal != "normal") {
            return "the tablet is throttling ($thermal) - it will run slower " +
                "and draw less until it cools"
        }
        if (celsius >= 43) return "running hot at ${celsius.roundToInt()}°C"
        if (lowMemory) return "memory is low - Android is killing things to keep up"
        if (freeMb in 1..180) return "only $freeMb MB of memory free"
        if (!charging && milliAmps >= 1400) {
            return "drawing $milliAmps mA - heavy, and the 3D views are the " +
                "usual reason"
        }
        if (!charging && milliAmps >= 900) return "drawing $milliAmps mA - working hard"
        val running = load.joinToString(", ")
        if (running.isNotEmpty()) return "nothing is choking it - running: $running"
        return "nothing is choking it"
    }

    private fun fmt(v: Double) = String.format("%.1f", v)

    private fun smooth(sample: Int): Int {
        if (sample <= 0) return recent.averageOrZero()
        recent.addLast(sample)
        while (recent.size > 6) recent.removeFirst()
        return recent.averageOrZero()
    }

    private fun ArrayDeque<Int>.averageOrZero(): Int =
        if (isEmpty()) 0 else (sum() / size)

    private fun thermalWord(pm: PowerManager?): String {
        if (pm == null || Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return "normal"
        return when (pm.currentThermalStatus) {
            PowerManager.THERMAL_STATUS_NONE -> "normal"
            PowerManager.THERMAL_STATUS_LIGHT -> "warm"
            PowerManager.THERMAL_STATUS_MODERATE -> "throttling"
            PowerManager.THERMAL_STATUS_SEVERE -> "throttling hard"
            PowerManager.THERMAL_STATUS_CRITICAL -> "critical"
            PowerManager.THERMAL_STATUS_EMERGENCY -> "emergency"
            PowerManager.THERMAL_STATUS_SHUTDOWN -> "shutting down"
            else -> "normal"
        }
    }

    companion object {
        /** "3h 12m", or a plain hyphen when it genuinely cannot be told. */
        fun spell(minutes: Int): String {
            if (minutes < 0) return "—"
            if (minutes < 60) return "${minutes}m"
            return "${minutes / 60}h ${minutes % 60}m"
        }
    }
}
