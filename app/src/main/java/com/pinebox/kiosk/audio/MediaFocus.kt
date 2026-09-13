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

    /** True if the platform granted it. */
    fun hold(): Boolean {
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

    /** Say what happened, so a silent tablet has a reason in logcat rather
     *  than being a mystery the next time. */
    private fun note(change: Int) {
        val what = when (change) {
            AudioManager.AUDIOFOCUS_GAIN -> "gained"
            AudioManager.AUDIOFOCUS_LOSS -> "lost for good"
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> "lost briefly"
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> "ducked"
            else -> "changed ($change)"
        }
        if (change == AudioManager.AUDIOFOCUS_LOSS) held = false
        if (change == AudioManager.AUDIOFOCUS_GAIN) held = true
        Log.i(TAG, "media focus $what")
    }

    companion object {
        private const val TAG = "PineMediaFocus"
    }
}
