package com.pinebox.kiosk.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.util.Log

/**
 * HOLD MEDIA AUDIO FOCUS, SO THE STATION IS AUDIBLE.
 *
 * MEASURED ON THE TABLET, and it is not what it looked like. Everything
 * downstream said the show was playing:
 *
 *   the station    routes all `here`, FM on, the tablet holding the air
 *   the drawer     "only PineTab is sounding - every other page is muted"
 *   the page       musicPlayer unmuted, volume 1, readyState 4, ungagged,
 *                  currentTime advancing 3.99s every 4s
 *   the device     STREAM_MUSIC 25/25, not muted, Devices: speaker(2)
 *
 * and the tablet was silent. The thing that settled it was one layer lower:
 *
 *   dumpsys media.audio_flinger
 *     AudioOut_D   Standby: yes
 *     AudioOut_15  Standby: yes   2 Tracks of which 0 are active
 *     AudioOut_1D  Standby: yes
 *
 * Every output thread in standby, no active track. The WebView was decoding
 * and advancing its media clock while producing no audio at all.
 *
 * The cause is in the focus log:
 *
 *   02:53:35 requestAudioFocus()  ... AudioFocusDelegate  (pid 6731)
 *   03:06:29 abandonAudioFocus()  ... AudioFocusDelegate
 *   Audio Focus stack entries (last is top of stack):   <empty>
 *
 * Chromium's own AudioFocusDelegate asked for focus in an earlier process
 * and gave it back; in the process that was running it never asked at all.
 * WebView ties media output to audio focus, and `mediaPlaybackRequiresUser-
 * Gesture = false` buys the right to START playing without a gesture - not
 * the focus that makes it audible. On a kiosk there is never a gesture, so
 * the request never came.
 *
 * So the app holds focus itself, for the whole time it is in front. This is
 * honest about what the terminal is: a dedicated radio that is always the
 * thing playing. AUDIOFOCUS_GAIN, not TRANSIENT - a transient grant would be
 * handed back and the silence would return.
 *
 * It does NOT fight the sampler. DuckController takes
 * AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK while a pad sounds and hands it back;
 * a transient request over a held gain is exactly the case the platform is
 * built for, and the station ducks under the pad rather than stopping.
 */
class MediaFocus(context: Context) {

    private val audio =
        context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    private val attributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_MEDIA)
        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
        .build()

    private val request: AudioFocusRequest? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                .setAudioAttributes(attributes)
                /* Do not pause the station because something else wanted the
                 * speaker for a moment. The terminal is the radio; a
                 * notification chime should duck it, not stop it. */
                .setWillPauseWhenDucked(false)
                .setAcceptsDelayedFocusGain(true)
                .setOnAudioFocusChangeListener { change -> note(change) }
                .build()
        } else {
            null
        }

    private var held = false

    /**
     * #1182T: LOWER YOUR OWN PLAYER TO THIS GAIN, 0..1.
     *
     * The same shape DuckController uses for the sampler, and for the reason
     * it gives there: audio focus can lower OTHER apps for us, but the
     * framework will not duck an app against itself, and on this terminal the
     * thing playing IS ours - an <audio> element inside our own WebView. So a
     * focus loss has to be carried into the page by hand, and this is the one
     * line the host hangs on it. MainActivity sets it; the duck script is
     * there.
     */
    var onDuck: ((Float) -> Unit)? = null

    /** True if the platform granted it. */
    fun hold(): Boolean {
        /* #1182T: DO NOT RE-TAKE FOCUS WHILE A STANDBY REQUEST IS LIVE.
         *
         * Asked for by the AutoBrowse port, and right:
         *
         *   "while a standby request is live, please do not re-take
         *    AUDIOFOCUS_GAIN on a timer. Re-taking it on your own onResume is
         *    correct and expected; re-taking it while backgrounded would
         *    silently cancel the duck the user asked for by pressing play."
         *
         * Read against our own source: we have no such timer. hold() is called
         * from MainActivity.onResume and from nowhere else, and onResume
         * leaves standby before it reaches this, so the guard should never
         * fire today. It is written down because the ask is about a PROPERTY
         * and not about a line - the next person to add a "make sure we are
         * still audible" watchdog gets the right answer for free, instead of
         * discovering by ear that the browser's video went quiet. */
        if (com.pinebox.kiosk.kiosk.Standby.active) {
            Log.i(TAG, "#1182T not taking media focus: a standby request is live ("
                + com.pinebox.kiosk.kiosk.Standby.levelName()
                + "); the station keeps playing either way")
            return held
        }
        if (held) return true
        val result = if (request != null) {
            audio.requestAudioFocus(request)
        } else {
            @Suppress("DEPRECATION")
            audio.requestAudioFocus(null, AudioManager.STREAM_MUSIC,
                AudioManager.AUDIOFOCUS_GAIN)
        }
        held = result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
        Log.i(TAG, if (held) "media focus held - the station can sound"
                   else "media focus REFUSED (result $result); the tablet may stay silent")
        return held
    }

    fun release() {
        if (!held) return
        if (request != null) {
            audio.abandonAudioFocusRequest(request)
        } else {
            @Suppress("DEPRECATION")
            audio.abandonAudioFocus(null)
        }
        held = false
    }

    fun holding(): Boolean = held

    /**
     * A FOCUS CHANGE IS A VOLUME EVENT HERE, NEVER A STOP. (#1182T)
     *
     * THE OWNER'S RULE, which outranks every other consideration in this
     * file: the radio must never stop. Nothing another app does may take the
     * broadcast off the air.
     *
     * The platform does not force the issue either way, and that is the point
     * worth writing down, because it reads like a constraint and is not one.
     * Audio focus on Android is ADVISORY. Losing it does not stop an AAudio
     * stream, does not mute a track and does not pause a media element; it is
     * a message, and what an app does about the message is the app's decision.
     * The AutoBrowse port confirmed the same thing from outside on 15 Sep
     * 2026: this terminal holds AUDIOFOCUS_GAIN with usage=USAGE_MEDIA
     * through this class, with three AAudio streams in state:started from the
     * sampler underneath it. So this is a listener, not a platform rule.
     *
     * What each message now means:
     *
     *   LOSS_TRANSIENT_CAN_DUCK  duck to DUCK_GAIN and keep playing. This is
     *                            the ordinary case and always was - the focus
     *                            request below already sets
     *                            setWillPauseWhenDucked(false).
     *
     *   LOSS_TRANSIENT           duck, and keep playing. The platform's own
     *                            suggestion here is "pause", and the operator
     *                            has a standing rule that says otherwise. A
     *                            paused station on a device with no listener
     *                            in front of it is dead air that nobody is
     *                            there to un-pause, which is the failure this
     *                            project has spent months measuring.
     *
     *   LOSS                     KEEP PLAYING, and say so in the log. This is
     *                            the one that looks wrong and is not. It means
     *                            another app has taken durable focus; it does
     *                            not mean our output stopped, and on a
     *                            dedicated radio terminal it is not a reason
     *                            to stop it. `held` goes false because we no
     *                            longer hold the grant - that is bookkeeping,
     *                            so the next onResume asks again - and nothing
     *                            else happens.
     *
     *   GAIN                     back up to full, and the hold is ours again.
     *
     * The duck is carried by [onDuck] because audio focus cannot duck an app
     * against itself and the thing playing is our own WebView. If nothing is
     * listening - no activity, no page - the duck is simply not applied, and
     * the failure direction is LOUD rather than silent. That is deliberate:
     * everything in this file fails towards being heard.
     */
    private fun note(change: Int) {
        when (change) {
            AudioManager.AUDIOFOCUS_GAIN -> {
                held = true
                Log.i(TAG, "media focus gained - back to full")
                onDuck?.invoke(1f)
            }
            AudioManager.AUDIOFOCUS_LOSS -> {
                held = false
                Log.i(TAG, "#1182T media focus lost for good - STILL PLAYING. "
                    + "Focus is advisory; the owner's rule is that the radio "
                    + "does not stop because another app asked for the speaker")
            }
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> {
                Log.i(TAG, "#1182T media focus lost briefly - ducking to "
                    + DUCK_GAIN + " rather than pausing")
                onDuck?.invoke(DUCK_GAIN)
            }
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> {
                Log.i(TAG, "media focus ducked to " + DUCK_GAIN)
                onDuck?.invoke(DUCK_GAIN)
            }
            else -> Log.i(TAG, "media focus changed (" + change + ")")
        }
    }

    companion object {
        private const val TAG = "PineMediaFocus"

        /**
         * #1182T: HOW FAR DOWN A DUCK GOES.
         *
         * A fifth of full. Low enough that a browser video or a voice call is
         * plainly the thing being listened to, and high enough that the studio
         * can still hear the station is there - which is the difference
         * between a duck and a stop, and the whole of what the owner's rule
         * is protecting. The sampler's own duck is separate and deeper; this
         * one is for another app, and another app is not a stab.
         */
        const val DUCK_GAIN = 0.2f
    }
}
