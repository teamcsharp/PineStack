package com.pinebox.kiosk.audio

import android.util.Log

/**
 * Loads the native sampler, and nothing else.
 *
 * THE ENGINE IS NOT WRITTEN BY THIS PROJECT. It lives in
 * `app/src/main/cpp/` and is built by that tree's own CMakeLists.txt, which
 * `app/build.gradle.kts` picks up when it exists. What is here is the one
 * `System.loadLibrary` call and a guard, so that:
 *
 *   - a build with no engine still installs and runs (the panel's own HTML5
 *     audio carries the show), and
 *   - there is exactly ONE place the library name is written down.
 *
 * THE BINDING IS SOMEWHERE ELSE, AND ON PURPOSE.
 *
 * cpp/android/jni_bridge.cpp exports its methods as
 * `Java_fm_pinebox_kiosk_audio_PineSampler_*`, so the class that declares
 * those `external fun`s must be **fm.pinebox.kiosk.audio.PineSampler** -
 * JNI resolves by CLASS package, which is not the application id and does
 * not have to match it. A class in package `fm.pinebox.kiosk.audio` inside
 * this `com.pinebox.kiosk` app is perfectly legal and is what the engine
 * expects; declaring the same externals here under `com.pinebox.kiosk`
 * would produce UnsatisfiedLinkError at first call, not at load.
 *
 * That binding is the native engine's own Kotlin counterpart and is not in
 * the tree yet. Whoever writes it should call [ensureLoaded] first rather
 * than issuing a second `System.loadLibrary`.
 */
object NativeAudio {

    private const val TAG = "PineAudio"

    /**
     * `pinebox_sampler`, from `add_library(pinebox_sampler SHARED ...)` in
     * cpp/CMakeLists.txt - so the .so is libpinebox_sampler.so.
     * `pinebox_sampler_core` is STATIC and is linked into it; there is no
     * second library to load.
     */
    private const val LIBRARY = "pinebox_sampler"

    /**
     * True when the .so was present and loaded. Evaluated once, lazily -
     * loading it at class-init would drag Oboe's audio stream setup into
     * whatever thread first touched this object.
     */
    val available: Boolean by lazy { ensureLoaded() }

    fun ensureLoaded(): Boolean = try {
        System.loadLibrary(LIBRARY)
        Log.i(TAG, "native sampler loaded")
        true
    } catch (err: UnsatisfiedLinkError) {
        /* Not a warning. On a build made before the engine was compiled in
         * this is the expected state, and a frightening log line in a kiosk
         * is half an hour of somebody's evening. */
        Log.i(TAG, "no native sampler in this build; the panel's own audio carries the show")
        false
    }
}
