package com.pinebox.kiosk.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder

/**
 * A copy of device media playback that keeps rendering to its original output.
 * The kiosk is platform-signed and already declares MODIFY_AUDIO_ROUTING.
 * These are Android system APIs, reached reflectively because public android.jar
 * excludes them. An unsupported build fails explicitly; there is no microphone
 * or bare REMOTE_SUBMIX fallback.
 *
 * AOSP AudioMix documents RENDER|LOOP_BACK as both rendering and capturing.
 * AudioPlaybackCaptureConfiguration builds the same kind of mix for projections.
 */
internal class PlaybackLoopback private constructor(
    val record: AudioRecord,
    private val manager: AudioManager,
    private val policy: Any,
    private val policyClass: Class<*>,
) : AutoCloseable {
    override fun close() {
        try { record.stop() } catch (_: Exception) { }
        try { record.release() } catch (_: Exception) { }
        try { manager.javaClass.getMethod("unregisterAudioPolicy", policyClass).invoke(manager, policy) }
        catch (_: Exception) { }
    }

    companion object {
        fun open(context: Context, rate: Int, channels: Int): PlaybackLoopback {
            require(context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                "Playback capture unavailable: RECORD_AUDIO permission is missing"
            }
            require(context.checkSelfPermission("android.permission.MODIFY_AUDIO_ROUTING") == PackageManager.PERMISSION_GRANTED) {
                "Playback capture unavailable: platform audio-routing permission is missing"
            }
            val ruleClass = Class.forName("android.media.audiopolicy.AudioMixingRule")
            val ruleBuilderClass = Class.forName("android.media.audiopolicy.AudioMixingRule\$Builder")
            val builder = ruleBuilderClass.getConstructor().newInstance()
            val addRule = ruleBuilderClass.getMethod("addRule", AudioAttributes::class.java, Int::class.javaPrimitiveType)
            val rule = ruleClass.getField("RULE_MATCH_ATTRIBUTE_USAGE").getInt(null)
            for (usage in intArrayOf(AudioAttributes.USAGE_MEDIA, AudioAttributes.USAGE_GAME, AudioAttributes.USAGE_UNKNOWN)) {
                addRule.invoke(builder, AudioAttributes.Builder().setUsage(usage).build(), rule)
            }
            val builtRule = ruleBuilderClass.getMethod("build").invoke(builder)
            val mixClass = Class.forName("android.media.audiopolicy.AudioMix")
            val mixBuilderClass = Class.forName("android.media.audiopolicy.AudioMix\$Builder")
            val mixBuilder = mixBuilderClass.getConstructor(ruleClass).newInstance(builtRule)
            val format = AudioFormat.Builder().setSampleRate(rate)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setChannelMask(if (channels == 2) AudioFormat.CHANNEL_OUT_STEREO else AudioFormat.CHANNEL_OUT_MONO).build()
            mixBuilderClass.getMethod("setFormat", AudioFormat::class.java).invoke(mixBuilder, format)
            val flags = mixClass.getField("ROUTE_FLAG_RENDER").getInt(null) or
                mixClass.getField("ROUTE_FLAG_LOOP_BACK").getInt(null)
            mixBuilderClass.getMethod("setRouteFlags", Int::class.javaPrimitiveType).invoke(mixBuilder, flags)
            val mix = mixBuilderClass.getMethod("build").invoke(mixBuilder)
            val policyClass = Class.forName("android.media.audiopolicy.AudioPolicy")
            val policyBuilderClass = Class.forName("android.media.audiopolicy.AudioPolicy\$Builder")
            val policyBuilder = policyBuilderClass.getConstructor(Context::class.java).newInstance(context)
            policyBuilderClass.getMethod("addMix", mixClass).invoke(policyBuilder, mix)
            val policy = checkNotNull(policyBuilderClass.getMethod("build").invoke(policyBuilder)) { "Android did not build a playback policy" }
            val manager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val result = manager.javaClass.getMethod("registerAudioPolicy", policyClass).invoke(manager, policy) as Int
            check(result == 0) { "Android refused the playback-capture policy ($result)" }
            var record: AudioRecord? = null
            try {
                // AudioPolicy.createAudioRecordSink uses only the platform
                // minimum buffer (64 ms on the tablet). Preserve its exact
                // policy address/source/volume attributes with one second of
                // capacity, so a short GC/encoder stall need not lose audio.
                // Capacity does not delay reading or the audible output.
                val address = mixClass.getMethod("getRegistration").invoke(mix) as? String
                check(!address.isNullOrBlank()) { "Playback mix has no registered capture address" }
                val attributes = AudioAttributes.Builder()
                AudioAttributes.Builder::class.java.getMethod("setInternalCapturePreset", Int::class.javaPrimitiveType)
                    .invoke(attributes, MediaRecorder.AudioSource.REMOTE_SUBMIX)
                val addTag = AudioAttributes.Builder::class.java.getMethod("addTag", String::class.java)
                addTag.invoke(attributes, "addr=$address")
                addTag.invoke(attributes, AudioRecord::class.java.getField("SUBMIX_FIXED_VOLUME").get(null) as String)
                val inputFormat = AudioFormat.Builder().setSampleRate(rate)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(if (channels == 2) AudioFormat.CHANNEL_IN_STEREO else AudioFormat.CHANNEL_IN_MONO).build()
                val capacity = maxOf(rate * channels * 2,
                    AudioRecord.getMinBufferSize(rate, inputFormat.channelMask, AudioFormat.ENCODING_PCM_16BIT))
                record = AudioRecord::class.java.getConstructor(AudioAttributes::class.java, AudioFormat::class.java,
                    Int::class.javaPrimitiveType, Int::class.javaPrimitiveType)
                    .newInstance(attributes.build(), inputFormat, capacity, AudioManager.AUDIO_SESSION_ID_GENERATE)
                check(record?.state == AudioRecord.STATE_INITIALIZED) { "Android did not initialize the playback capture" }
                return PlaybackLoopback(record!!, manager, policy, policyClass)
            } catch (error: Throwable) {
                try { record?.release() } catch (_: Exception) { }
                try { manager.javaClass.getMethod("unregisterAudioPolicy", policyClass).invoke(manager, policy) }
                catch (_: Exception) { }
                throw error
            }
        }
    }
}
