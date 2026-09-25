package com.pinebox.kiosk.audio

import android.Manifest
import android.content.ContextParams
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.RemoteException
import android.os.SystemClock
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import android.util.Log
import com.pinebox.kiosk.PineApp
import com.pinebox.kiosk.net.StationException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException

/** Android speech API entry point. Capture is local; recognition runs on the station. */
class PineRecognitionService : RecognitionService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    private class Session(val callback: Callback, val mic: MicCapture) {
        @Volatile var stopping = false
        @Volatile var cancelled = false
        var job: Job? = null
    }

    private var active: Session? = null

    private fun sendError(listener: Callback, code: Int) {
        try { listener.error(code) } catch (_: RemoteException) { }
    }

    private inline fun Session.deliver(block: (Callback) -> Unit) {
        if (cancelled) return
        try { block(callback) } catch (_: RemoteException) { cancelled = true }
    }

    override fun onStartListening(intent: Intent, listener: Callback) {
        if (active != null || checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            sendError(listener, if (active != null) SpeechRecognizer.ERROR_RECOGNIZER_BUSY
                else SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS)
            return
        }
        val attributed = try {
            createContext(ContextParams.Builder()
                .setNextAttributionSource(listener.callingAttributionSource)
                .build())
        } catch (err: SecurityException) {
            sendError(listener, SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS)
            return
        }
        val session = Session(listener, MicCapture(attributed, attributeToContext = true))
        if (!MicLease.acquire(session)) {
            sendError(listener, SpeechRecognizer.ERROR_RECOGNIZER_BUSY)
            return
        }
        active = session
        session.job = scope.launch { recognize(session) }
    }

    override fun onStopListening(listener: Callback) {
        active?.takeIf { it.callback === listener }?.stopping = true
    }

    override fun onCancel(listener: Callback) {
        active?.takeIf { it.callback === listener }?.let {
            it.cancelled = true
            it.job?.cancel()
        }
    }

    private suspend fun recognize(session: Session) {
        val mic = session.mic
        try {
            val problem = withContext(Dispatchers.IO) { mic.start() }
            if (problem != null) {
                session.deliver { it.error(SpeechRecognizer.ERROR_AUDIO) }
                Log.w(TAG, "microphone: $problem")
                return
            }
            if (session.cancelled) return
            session.deliver { it.readyForSpeech(Bundle()) }

            val started = SystemClock.elapsedRealtime()
            var lastVoice = started
            var heardVoice = false
            while (!session.stopping && !session.cancelled) {
                delay(100)
                val now = SystemClock.elapsedRealtime()
                if (mic.level > VOICE_PEAK) {
                    lastVoice = now
                    if (!heardVoice) {
                        heardVoice = true
                        session.deliver { it.beginningOfSpeech() }
                    }
                }
                if (mic.lastError != null || now - started >= MAX_LISTEN_MS ||
                    (heardVoice && now - lastVoice >= END_SILENCE_MS && now - started >= 600L) ||
                    (!heardVoice && now - started >= START_TIMEOUT_MS)) break
            }
            if (session.cancelled) return

            val level = mic.takeLevel()
            val wall = mic.wallSeconds
            val failure = mic.lastError
            val wav = withContext(Dispatchers.IO) { mic.stop() }
            MicLease.release(session)
            if (session.cancelled) return
            if (failure != null || wav == null || wall > 1f &&
                (wav.size - 44) / (MicCapture.RATE * 2f) < wall * 0.75f) {
                session.deliver { it.error(SpeechRecognizer.ERROR_AUDIO) }
                return
            }
            if (level < QUIET || wav.size < 44 + (MicCapture.RATE * 2 * 0.35).toInt()) {
                session.deliver { it.error(if (heardVoice || session.stopping) SpeechRecognizer.ERROR_NO_MATCH
                    else SpeechRecognizer.ERROR_SPEECH_TIMEOUT) }
                return
            }
            if (!heardVoice) session.deliver { it.beginningOfSpeech() }
            session.deliver { it.endOfSpeech() }

            val response = PineApp.of(this).client.postBytes("/api/listen/transcribe", wav, "audio/wav")
            if (session.cancelled) return
            val words = JSONObject(response).optString("text", "").trim()
            if (words.isBlank()) session.deliver { it.error(SpeechRecognizer.ERROR_NO_MATCH) }
            else session.deliver { it.results(Bundle().apply {
                putStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION, arrayListOf(words))
            }) }
        } catch (_: CancellationException) {
            // onCancel has no result callback.
        } catch (err: StationException) {
            session.deliver { it.error(
                if (err.code >= 500) SpeechRecognizer.ERROR_SERVER else SpeechRecognizer.ERROR_CLIENT) }
            Log.w(TAG, "station rejected recognition: ${err.code}")
        } catch (err: IOException) {
            session.deliver { it.error(SpeechRecognizer.ERROR_NETWORK) }
            Log.w(TAG, "station unreachable", err)
        } catch (err: Exception) {
            session.deliver { it.error(SpeechRecognizer.ERROR_SERVER) }
            Log.w(TAG, "recognition failed", err)
        } finally {
            if (mic.isRunning) withContext(NonCancellable + Dispatchers.IO) { mic.cancel() }
            MicLease.release(session)
            if (active === session) active = null
        }
    }

    override fun onDestroy() {
        active?.let { it.cancelled = true; it.job?.cancel() }
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "PineRecognition"
        private const val QUIET = 0.002f
        private const val VOICE_PEAK = 0.035f
        private const val END_SILENCE_MS = 4200L
        private const val START_TIMEOUT_MS = 7000L
        private const val MAX_LISTEN_MS = 15000L
    }
}
