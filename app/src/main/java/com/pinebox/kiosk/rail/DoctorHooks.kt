package com.pinebox.kiosk.rail

import com.pinebox.kiosk.audio.AudioHealth

/**
 * [smart-reinit] What the drawer's doctor may ask of the terminal itself -
 * the half of "Get the broadcast back" that no station can reach. MainActivity
 * owns every one of these objects (the jack, the output route, media focus,
 * the replay capture, standby, Revive) and hands them over as this.
 *
 * None of them changes a level, a volume or a route: [audio] only reads, and
 * the cures re-open or let go of what THIS APP holds.
 */
interface DoctorHooks {
    /** Where the sound is leaving, in words ("the aux cable"). */
    fun route(): String

    /** The two audio dumps and the media volume. Blocking - call off main. */
    fun audio(): AudioHealth.Reading?

    fun focusHeld(): Boolean

    /** Take media focus again; true when it is held. */
    fun refocus(): Boolean

    fun standby(): Boolean

    fun leaveStandby()

    /** Close and re-open the replay ring's playback capture. Blocking. */
    fun reopenCapture(): String

    /** Let the playback capture go until the app next resumes. Blocking. */
    fun releaseCapture(): String

    /** Restart this app; false when Revive declined (too soon, or a loop). */
    fun restartApp(why: String): Boolean
}
