package fm.pinebox.kiosk.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper

/**
 * Hold whatever is playing down while a pad rings.
 *
 * The tablet is a terminal for a radio station: something is nearly always
 * playing behind the sampler. A stab on top of a full mix at equal level is
 * mud.
 *
 * There are TWO things to duck and they need different mechanisms, which is
 * the only subtle part of this file:
 *
 *  - Other apps. Android does this for us, if we ask: an
 *    AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK request tells the platform to lower
 *    everyone else while we are holding it.
 *
 *  - OUR OWN player. Audio focus does nothing here - the framework will not
 *    duck an app against itself - and on this terminal the stream is very
 *    likely ours: an ExoPlayer, or an <audio> element inside the same
 *    WebView. So the engine also publishes a plain gain, and [listener] is
 *    where the host hangs the one line that applies it.
 *
 * The engine works out the SHAPE of the duck (fast down, hold through a run
 * of sixteenths, slow back up) because it is the only part of the app that
 * knows when the last voice actually stopped. This class only carries the
 * number out and asks the platform for focus.
 */
class DuckController(context: Context) {

    private val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val handler = Handler(Looper.getMainLooper())

    /** Set by the host: lower your own player to this gain, 0..1. */
    var listener: ((Float) -> Unit)? = null

    private var holdingFocus = false
    private var polling = false
    private var lastPublished = 1f

    private val focusRequest: AudioFocusRequest? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        /* Sonification, not Music: a pad hit is a sound the
                         * operator caused, and it should not fight the media
                         * transport keys or the notification policy. */
                        .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                )
                /* We do not want the callback to pause us; a sampler that
                 * stops working because a notification chimed is broken. */
                .setOnAudioFocusChangeListener({ }, handler)
                .build()
        } else {
            null
        }

    /**
     * A pad fired. Take focus if we do not have it, and start watching the
     * engine's duck gain so the host's own player can follow it down and back.
     *
     * Called from whichever thread pressed the pad - the UI thread on a
     * native press, the WebView's bridge thread on a press from the page - so
     * the work hops to the main looper rather than guarding three fields with
     * locks a touch handler would have to wait on.
     */
    fun onVoiceStarted() {
        handler.post {
            requestFocus()
            startPolling()
        }
    }

    private fun requestFocus() {
        if (holdingFocus) return
        val result = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && focusRequest != null) {
            audio.requestAudioFocus(focusRequest)
        } else {
            @Suppress("DEPRECATION")
            audio.requestAudioFocus(
                null, AudioManager.STREAM_MUSIC,
                AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK
            )
        }
        holdingFocus = result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
    }

    /**
     * Follow the engine's gain at a lazy sixty milliseconds. Deliberately NOT
     * per audio block: this is a UI-thread hop and a volume setter, and doing
     * it a few hundred times a second would cost more than the duck is worth.
     * The engine's own ramp is what makes it smooth; this only samples it.
     */
    private fun startPolling() {
        if (polling) return
        polling = true
        handler.post(object : Runnable {
            override fun run() {
                val gain = PineSampler.duckGain()
                if (kotlin.math.abs(gain - lastPublished) > 0.005f) {
                    lastPublished = gain
                    listener?.invoke(gain)
                }
                if (gain < 0.999f) {
                    handler.postDelayed(this, 60L)
                } else {
                    /* All the way back: let go of focus so other apps stop
                     * being held down by a sampler nobody is touching. */
                    polling = false
                    if (lastPublished != 1f) {
                        lastPublished = 1f
                        listener?.invoke(1f)
                    }
                    abandonFocus()
                }
            }
        })
    }

    private fun abandonFocus() {
        if (!holdingFocus) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && focusRequest != null) {
            audio.abandonAudioFocusRequest(focusRequest)
        } else {
            @Suppress("DEPRECATION")
            audio.abandonAudioFocus(null)
        }
        holdingFocus = false
    }

    /** Backgrounded, or shutting down. */
    fun release() {
        polling = false
        handler.removeCallbacksAndMessages(null)
        if (lastPublished != 1f) {
            lastPublished = 1f
            listener?.invoke(1f)
        }
        abandonFocus()
    }
}
