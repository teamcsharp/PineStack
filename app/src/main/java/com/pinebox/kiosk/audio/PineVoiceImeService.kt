package com.pinebox.kiosk.audio

import android.content.ComponentName
import android.content.Intent
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
import android.widget.TextView

/** LatinIME's microphone key switches to a voice subtype, not to a recognizer. */
class PineVoiceImeService : InputMethodService(), RecognitionListener {
    private var recognizer: SpeechRecognizer? = null
    private var status: TextView? = null
    private var action: Button? = null
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
        row.addView(status, LinearLayout.LayoutParams(0, dp(56), 1f))
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
        startRecognition()
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
        status?.text = message
        action?.text = "Retry"
    }

    override fun onReadyForSpeech(params: Bundle?) { status?.text = "Listening..." }
    override fun onBeginningOfSpeech() { status?.text = "Hearing you..." }
    override fun onEndOfSpeech() { status?.text = "Transcribing..." }
    override fun onRmsChanged(rmsdB: Float) = Unit
    override fun onBufferReceived(buffer: ByteArray?) = Unit
    override fun onPartialResults(partialResults: Bundle?) = Unit
    override fun onEvent(eventType: Int, params: Bundle?) = Unit

    private fun disposeRecognizer() {
        val current = recognizer
        recognizer = null
        if (listening) current?.cancel()
        current?.destroy()
        listening = false
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
