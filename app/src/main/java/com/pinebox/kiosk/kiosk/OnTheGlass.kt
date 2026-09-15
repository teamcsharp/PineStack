package com.pinebox.kiosk.kiosk

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log

/**
 * #1182T - WHOSE ACTIVITY IS ACTUALLY ON THE GLASS RIGHT NOW.
 *
 * WHY THIS EXISTS. WallpaperWatch was taught in #1296 to hang a picture only
 * when there is no view of OURS to tear down, because setWallpaper raises
 * CONFIG_ASSETS_PATHS (0x80000000) and no app can declare that flag away in
 * android:configChanges - AAPT refuses it, which the manifest already records
 * beside PineCameraActivity. Measured then: seven relaunches of our own
 * activity in thirty-three minutes, on the wallpaper's five-minute period.
 *
 * The AutoBrowse port measured the consequence of that fix on 15 Sep 2026, and
 * it is exact: because the repaint waits for OUR view to go away, it now fires
 * precisely when a FOREIGN app is in front, and destroys and recreates THAT
 * app's activity every five minutes instead. For a browser that reads as
 * randomly losing the page, the scroll position, and the form being filled in.
 * The configuration flag does not care whose activity it is.
 *
 * So "is a view on the glass" has to mean any view, not only ours.
 *
 * HOW IT IS READ, AND WHY NOT THE OBVIOUS WAYS.
 * ActivityManager.getRunningTasks has been useless to ordinary apps since
 * Lollipop and REAL_GET_TASKS is a permission this app does not declare;
 * UsageStatsManager needs a settings grant somebody has to give by hand on a
 * device that is meant to be left alone. What this terminal DOES have is
 * DUMP - signature|privileged, granted because deploy.sh platform-signs the
 * APK - and a proven idiom for using it: JackWatch reads `dumpsys input` for
 * SwitchValues every two seconds and has done for months. This is the same
 * road, read at a thousandth of that rate.
 *
 * THE ANSWER IS THREE-VALUED ON PURPOSE. A package name, "" for "nothing is
 * resumed" (the screen is off, or the keyguard has it), or UNKNOWN when the
 * dump could not be read at all. UNKNOWN is the one that matters: a caller
 * that cannot tell must fall back to what it did before, rather than silently
 * deciding the glass is busy forever - that would be a shipped feature
 * switching itself off with nobody ever seeing a log line about it.
 */
object OnTheGlass {

    private const val TAG = "PineGlass"

    /** The dump could not be read, or said nothing this understands. */
    const val UNKNOWN = "?"

    /** Read at most this often. See the note on cost below. */
    private const val FRESH_MS = 4_000L

    @Volatile private var lastAnswer: String = UNKNOWN
    @Volatile private var lastAt: Long = 0L

    /** The launcher, worked out once - it is not going to change under us. */
    @Volatile private var launcher: String? = null

    /**
     * The package whose activity is resumed, "" if none, or [UNKNOWN].
     *
     * CACHED FOR FOUR SECONDS. `dumpsys activity activities` is a large dump,
     * and this is read on the wallpaper's five-minute round and again when the
     * kiosk is paused, which can land within a second of each other. The cache
     * is what stops that being two dumps. It is deliberately far shorter than
     * anything a caller waits on, so it can never be the reason a stale answer
     * gets acted on.
     */
    fun topPackage(): String {
        val now = System.currentTimeMillis()
        if (now - lastAt < FRESH_MS) return lastAnswer
        val answer = read()
        lastAnswer = answer
        lastAt = now
        return answer
    }

    /**
     * Is this a package the wallpaper is allowed to repaint behind?
     *
     * The home screen and the keyguard are the only two surfaces a wallpaper
     * is ever SEEN on, so a launcher or systemui being in front is not a
     * reason to hold the picture back - it is the reason to hang it. Anything
     * else, ours included, is somebody's activity that a CONFIG_ASSETS_PATHS
     * would destroy and recreate underneath them.
     */
    fun isHomeOrSystem(context: Context, pkg: String): Boolean {
        if (pkg.isEmpty()) return true
        if (pkg == "com.android.systemui" || pkg == "android") return true
        return pkg == launcherPackage(context)
    }

    /**
     * The default HOME app's package, or "".
     *
     * NOTE that on a provisioned terminal this is US: the kiosk registers a
     * HOME + DEFAULT filter, which is what makes the tablet a terminal rather
     * than a tablet running an app. Callers must therefore check their own
     * package FIRST - being the launcher does not make our own activity safe
     * to relaunch, which is the whole of #1296.
     */
    fun launcherPackage(context: Context): String {
        launcher?.let { return it }
        val found = runCatching {
            val home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            context.packageManager
                .resolveActivity(home, PackageManager.MATCH_DEFAULT_ONLY)
                ?.activityInfo?.packageName ?: ""
        }.getOrDefault("")
        launcher = found
        return found
    }

    /**
     * Read the resumed activity out of the activity manager's own dump.
     *
     * Line by line and abandoned at the first hit, the way JackWatch reads
     * SwitchValues, because the dump is long and nothing here is worth making
     * the tablet warm for. The line looked for is one of
     *
     *   mResumedActivity: ActivityRecord{2a1b3c u0 com.pinebox.kiosk/.MainActivity t9}
     *   topResumedActivity=ActivityRecord{2a1b3c u0 com.pinebox.kiosk/.MainActivity t9}
     *
     * and the package is what sits between the user id and the "/" that starts
     * the class name. A dump that says `null` means nothing is resumed, which
     * on this tablet means the screen is off or the keyguard is up - both
     * states in which a wallpaper is exactly what is on show. So "" is the
     * right answer there, and not a failure.
     */
    private fun read(): String {
        return runCatching {
            val proc = ProcessBuilder("/system/bin/dumpsys", "activity", "activities")
                .redirectErrorStream(true).start()
            var found: String? = null
            try {
                proc.inputStream.bufferedReader().use { reader ->
                    while (true) {
                        val line = reader.readLine() ?: break
                        if (!line.contains("ResumedActivity")) continue
                        found = packageIn(line)
                        if (found != null) break
                    }
                }
            } finally {
                proc.destroy()
            }
            val answer = found ?: UNKNOWN
            if (answer == UNKNOWN) {
                Log.i(TAG, "the activity dump named no resumed activity; "
                    + "falling back to the behaviour before #1182T")
            }
            answer
        }.getOrElse {
            Log.w(TAG, "could not read the activity dump: " + (it.message ?: it.toString()))
            UNKNOWN
        }
    }

    /** "" for an explicit null, the package name, or null for "not this line". */
    private fun packageIn(line: String): String? {
        if (line.trimEnd().endsWith("null")) return ""
        val record = line.indexOf("ActivityRecord{")
        if (record < 0) return null
        /* Skip the hash and the user id, then take up to the class separator. */
        val parts = line.substring(record + 15).trim().split(" ")
        for (part in parts) {
            val slash = part.indexOf('/')
            if (slash > 0) return part.substring(0, slash)
        }
        return null
    }
}
