package com.pinebox.kiosk.audio

import android.content.ComponentName
import android.content.Intent
import android.content.res.ColorStateList
import android.inputmethodservice.InputMethodService
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.Gravity
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.ExtractedTextRequest
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import java.util.Locale

/** LatinIME's microphone key switches to a voice subtype, not to a recognizer. */
class PineVoiceImeService : InputMethodService(), RecognitionListener {
    private var recognizer: SpeechRecognizer? = null
    private var status: TextView? = null
    private var action: Button? = null
    private var inputLevel: ProgressBar? = null
    private var inputReading: TextView? = null
    private var listening = false

    override fun onCreateInputView(): View {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density + 0.5f).toInt()
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(12), dp(8), dp(12), dp(8))
            setBackgroundColor(0xff19272d.toInt())
        }
        status = TextView(this).apply {
            text = "Listening..."
            setTextColor(0xfff1f5f3.toInt())
            textSize = 16f
        }
        action = Button(this).apply {
            text = "Stop"
            setOnClickListener {
                if (listening) {
                    listening = false
                    status?.text = "Transcribing..."
                    recognizer?.stopListening()
                } else startRecognition()
            }
        }
        val feedback = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, dp(12), 0)
        }
        feedback.addView(status)
        inputLevel = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progressTintList = ColorStateList.valueOf(0xff6bcedc.toInt())
            progressBackgroundTintList = ColorStateList.valueOf(0xff344950.toInt())
            contentDescription = "Microphone input level"
        }
        feedback.addView(inputLevel, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(12)))
        inputReading = TextView(this).apply {
            text = "Input: waiting"
            textSize = 12f
            setTextColor(0xffc5d9de.toInt())
        }
        feedback.addView(inputReading)
        row.addView(feedback, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(action, LinearLayout.LayoutParams(dp(88), dp(56)))
        row.addView(Button(this).apply {
            text = "Keyboard"
            setOnClickListener {
                disposeRecognizer()
                returnToKeyboard()
            }
        }, LinearLayout.LayoutParams(dp(112), dp(56)))
        return row
    }

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        if (!listening) startRecognition()
    }

    private fun startRecognition() {
        disposeRecognizer()
        status?.text = "Listening..."
        action?.text = "Stop"
        val component = ComponentName(this, PineRecognitionService::class.java)
        try {
            recognizer = SpeechRecognizer.createSpeechRecognizer(this, component).apply {
                setRecognitionListener(this@PineVoiceImeService)
                startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
                })
            }
            listening = true
        } catch (err: Exception) {
            status?.text = "Voice input unavailable"
            action?.text = "Retry"
            listening = false
            disposeRecognizer()
        }
    }

    override fun onResults(results: Bundle?) {
        listening = false
        val words = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.firstOrNull()?.trim().orEmpty()
        if (words.isBlank()) {
            showRetry("No words heard")
            return
        }
        val connection = currentInputConnection
        if (connection == null) {
            showRetry("Text field lost focus")
            return
        }
        val end = connection.getExtractedText(ExtractedTextRequest(), 0)?.text?.length
        if (end != null) connection.setSelection(end, end)
        val before = connection.getTextBeforeCursor(1, 0)?.toString().orEmpty()
        val prefix = if (before.isNotEmpty() && !before.last().isWhitespace()) " " else ""
        connection.commitText(prefix + words, 1)
        disposeRecognizer()
        returnToKeyboard()
    }

    override fun onError(error: Int) {
        listening = false
        showRetry(when (error) {
            SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
            SpeechRecognizer.ERROR_SERVER -> "Station unavailable"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission needed"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Microphone in use"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT, SpeechRecognizer.ERROR_NO_MATCH -> "No words heard"
            else -> "Voice input failed"
        })
    }

    private fun showRetry(message: String) {
        clearInputLevel()
        status?.text = message
        action?.text = "Retry"
    }

    override fun onReadyForSpeech(params: Bundle?) { status?.text = "Listening..." }
    override fun onBeginningOfSpeech() { status?.text = "Hearing you..." }
    override fun onEndOfSpeech() {
        listening = false
        clearInputLevel()
        status?.text = "Transcribing..."
    }
    override fun onRmsChanged(rmsdB: Float) {
        if (!listening || !rmsdB.isFinite()) return
        inputLevel?.progress = ((rmsdB + 60f) / 60f * 100f).toInt().coerceIn(0, 100)
        val reading = if (rmsdB <= -60f) "Input: < -60 dBFS"
            else String.format(Locale.US, "Input: %.1f dBFS", rmsdB)
        inputReading?.text = reading
        inputLevel?.contentDescription = reading
    }
    override fun onBufferReceived(buffer: ByteArray?) = Unit
    override fun onPartialResults(partialResults: Bundle?) = Unit
    override fun onEvent(eventType: Int, params: Bundle?) = Unit

    private fun disposeRecognizer() {
        clearInputLevel()
        val current = recognizer
        recognizer = null
        current?.cancel()
        current?.destroy()
        listening = false
    }

    private fun clearInputLevel() {
        inputLevel?.progress = 0
        inputReading?.text = "Input: waiting"
    }

    private fun returnToKeyboard() {
        if (!switchToPreviousInputMethod()) switchToNextInputMethod(false)
    }

    override fun onFinishInputView(finishingInput: Boolean) {
        disposeRecognizer()
        super.onFinishInputView(finishingInput)
    }

    override fun onDestroy() {
        disposeRecognizer()
        super.onDestroy()
    }
}
