/* android/jni_bridge.cpp - the only place C++ and Kotlin meet.
 *
 * Deliberately dull. Every method is typed - primitives and arrays, no JSON,
 * no reflection - because org.json is free on Android and a hand-rolled
 * parser in C++ is a place for bugs to live. The Kotlin side turns these
 * into objects and, one layer further out, into the shapes the WebView's
 * window.pineSampler expects.
 *
 * Two conventions worth knowing before reading:
 *
 *   MASKS. JavaScript distinguishes `{loop: false}` from `{}`, and the
 *   sampler's semantics depend on it: a set() that does not mention loop must
 *   not turn loop off, and a fire() that does not mention pitch uses the
 *   pad's own tune. JNI has no undefined, so presence rides in a bitmask.
 *
 *   ERRORS ARE NOT EXCEPTIONS. Throwing across JNI from a decode worker is
 *   noisy and the sampler's failures are all "that clip would not decode".
 *   A failed call returns null and leaves the reason in nativeLastError().
 */
#include <jni.h>

#include <memory>
#include <string>
#include <vector>

#include "android/media_decode.h"
#include "android/oboe_output.h"
#include "pinebox/analysis.h"
#include "pinebox/engine.h"
#include "pinebox/voice.h"

using pinebox::sampler::FireOptions;
using pinebox::sampler::Footprint;
using pinebox::sampler::Levels;
using pinebox::sampler::LoadResult;
using pinebox::sampler::PadPatch;
using pinebox::sampler::PadSettings;
using pinebox::sampler::SampleRef;
using pinebox::sampler::SamplerCore;
using pinebox::sampler::Trim;
using pinebox::sampler::android::OboeOutput;

namespace {

/* set() presence bits. Must match PineSampler.kt. */
constexpr int kSetGain = 1 << 0;
constexpr int kSetPitch = 1 << 1;
constexpr int kSetLoop = 1 << 2;
constexpr int kSetReverse = 1 << 3;
constexpr int kSetChoke = 1 << 4;
constexpr int kSetTrim = 1 << 5;
constexpr int kSetPan = 1 << 6;

/* fire() presence bits. */
constexpr int kFireVelocity = 1 << 0;
constexpr int kFirePitch = 1 << 1;
constexpr int kFireLoop = 1 << 2;

struct Engine {
  SamplerCore core;
  OboeOutput output;
  std::string lastError;
  Engine() : core(), output(&core) {}
};

Engine* engineOf(jlong handle) {
  return reinterpret_cast<Engine*>(static_cast<uintptr_t>(handle));
}

std::string toUtf8(JNIEnv* env, jstring value) {
  if (value == nullptr) return std::string();
  const char* chars = env->GetStringUTFChars(value, nullptr);
  std::string out(chars ? chars : "");
  if (chars) env->ReleaseStringUTFChars(value, chars);
  return out;
}

jstring fromUtf8(JNIEnv* env, const std::string& value) {
  return env->NewStringUTF(value.c_str());
}

}  // namespace

extern "C" {

JNIEXPORT jlong JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeCreate(JNIEnv*, jobject) {
  return static_cast<jlong>(reinterpret_cast<uintptr_t>(new Engine()));
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeDestroy(JNIEnv*, jobject,
                                                      jlong handle) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return;
  engine->output.stop();
  engine->core.clear();
  delete engine;
}

JNIEXPORT jboolean JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeStart(JNIEnv*, jobject,
                                                    jlong handle) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return JNI_FALSE;
  return engine->output.start() ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeStop(JNIEnv*, jobject,
                                                   jlong handle) {
  Engine* engine = engineOf(handle);
  if (engine != nullptr) engine->output.stop();
}

JNIEXPORT jboolean JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeRunning(JNIEnv*, jobject,
                                                      jlong handle) {
  Engine* engine = engineOf(handle);
  return (engine != nullptr && engine->output.running()) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jstring JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeLastError(JNIEnv* env, jobject,
                                                        jlong handle) {
  Engine* engine = engineOf(handle);
  return fromUtf8(env, engine ? engine->lastError : std::string());
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeSetPolyphonic(JNIEnv*, jobject,
                                                            jlong handle,
                                                            jboolean on) {
  Engine* engine = engineOf(handle);
  if (engine != nullptr) engine->core.setPolyphonic(on == JNI_TRUE);
}

JNIEXPORT jboolean JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeIsPolyphonic(JNIEnv*, jobject,
                                                           jlong handle) {
  Engine* engine = engineOf(handle);
  return (engine != nullptr && engine->core.isPolyphonic()) ? JNI_TRUE
                                                            : JNI_FALSE;
}

/* Decode ONCE, here, and hold the result resident. Nothing decodes on the
 * press. Called from a worker thread on the Kotlin side, never from the UI
 * thread: a sixty second mp3 is roughly a second of MediaCodec. */
JNIEXPORT jdoubleArray JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeLoad(JNIEnv* env, jobject,
                                                   jlong handle, jstring padId,
                                                   jbyteArray bytes,
                                                   jstring scratchDir) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return nullptr;
  if (bytes == nullptr) {
    engine->lastError = "A pad needs bytes.";
    return nullptr;
  }
  const jsize length = env->GetArrayLength(bytes);
  if (length <= 0) {
    engine->lastError = "That sample was empty.";
    return nullptr;
  }

  jbyte* raw = env->GetByteArrayElements(bytes, nullptr);
  if (raw == nullptr) {
    engine->lastError = "Could not read the sample's bytes.";
    return nullptr;
  }

  std::string error;
  SampleRef buffer = pinebox::sampler::android::decodeToEngineBuffer(
      reinterpret_cast<const std::uint8_t*>(raw),
      static_cast<std::size_t>(length), toUtf8(env, scratchDir), &error);
  env->ReleaseByteArrayElements(bytes, raw, JNI_ABORT);

  if (!buffer) {
    engine->lastError = error.empty() ? "That sample would not decode." : error;
    return nullptr;
  }

  const LoadResult result = engine->core.load(toUtf8(env, padId), buffer);
  engine->lastError.clear();

  jdoubleArray out = env->NewDoubleArray(3);
  jdouble values[3] = {result.seconds, static_cast<jdouble>(result.rate),
                       static_cast<jdouble>(result.channels)};
  env->SetDoubleArrayRegion(out, 0, 3, values);
  return out;
}

JNIEXPORT jboolean JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeCopy(JNIEnv* env, jobject,
                                                   jlong handle, jstring from,
                                                   jstring to) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return JNI_FALSE;
  return engine->core.copy(toUtf8(env, from), toUtf8(env, to)) ? JNI_TRUE
                                                               : JNI_FALSE;
}

JNIEXPORT jboolean JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeUnload(JNIEnv* env, jobject,
                                                     jlong handle,
                                                     jstring padId) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return JNI_FALSE;
  return engine->core.unload(toUtf8(env, padId)) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeClear(JNIEnv*, jobject,
                                                    jlong handle) {
  Engine* engine = engineOf(handle);
  if (engine != nullptr) engine->core.clear();
}

JNIEXPORT jboolean JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeLoaded(JNIEnv* env, jobject,
                                                     jlong handle,
                                                     jstring padId) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return JNI_FALSE;
  return engine->core.loaded(toUtf8(env, padId)) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jdouble JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeSeconds(JNIEnv* env, jobject,
                                                      jlong handle,
                                                      jstring padId) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return 0.0;
  return engine->core.seconds(toUtf8(env, padId));
}

JNIEXPORT jfloatArray JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativePeaks(JNIEnv* env, jobject,
                                                    jlong handle, jstring padId,
                                                    jint buckets) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return env->NewFloatArray(0);
  const std::vector<float> values =
      engine->core.peaks(toUtf8(env, padId), static_cast<int>(buckets));
  jfloatArray out = env->NewFloatArray(static_cast<jsize>(values.size()));
  if (!values.empty()) {
    env->SetFloatArrayRegion(out, 0, static_cast<jsize>(values.size()),
                             values.data());
  }
  return out;
}

JNIEXPORT jdouble JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeZeroCross(JNIEnv* env, jobject,
                                                        jlong handle,
                                                        jstring padId,
                                                        jdouble seconds,
                                                        jdouble withinMs) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return seconds;
  return engine->core.zeroCross(toUtf8(env, padId), seconds, withinMs);
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeSet(
    JNIEnv* env, jobject, jlong handle, jstring padId, jint mask, jdouble gain,
    jdouble pitch, jboolean loop, jboolean reverse, jstring choke,
    jboolean trimSet, jdouble trimStart, jdouble trimEnd, jdouble pan) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return;

  PadPatch patch;
  if (mask & kSetGain) { patch.hasGain = true; patch.gain = gain; }
  if (mask & kSetPitch) { patch.hasPitch = true; patch.pitch = pitch; }
  if (mask & kSetPan) { patch.hasPan = true; patch.pan = pan; }
  if (mask & kSetLoop) { patch.hasLoop = true; patch.loop = loop == JNI_TRUE; }
  if (mask & kSetReverse) {
    patch.hasReverse = true;
    patch.reverse = reverse == JNI_TRUE;
  }
  if (mask & kSetChoke) {
    patch.hasChoke = true;
    patch.choke = toUtf8(env, choke);
  }
  if (mask & kSetTrim) {
    patch.hasTrim = true;
    patch.trim.set = trimSet == JNI_TRUE;
    patch.trim.start = trimStart;
    patch.trim.end = trimEnd;
  }
  engine->core.set(toUtf8(env, padId), patch);
}

/* [gain, pitch, loop, reverse, trimSet, trimStart, trimEnd, seconds, pan], or null
 * for a pad nothing has ever touched - which is the JS get()'s null. */
JNIEXPORT jdoubleArray JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeGet(JNIEnv* env, jobject,
                                                  jlong handle, jstring padId) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return nullptr;
  PadSettings settings;
  double seconds = 0.0;
  if (!engine->core.get(toUtf8(env, padId), &settings, &seconds)) return nullptr;

  /* PAN IS APPENDED, NOT INSERTED. Every reader indexes this array by
   * position, so a new field in the middle would silently shift trim and
   * seconds by one - the kind of change that shows up as a pad playing the
   * wrong window rather than as a compile error. */
  jdouble values[9] = {settings.gain,
                       settings.pitch,
                       settings.loop ? 1.0 : 0.0,
                       settings.reverse ? 1.0 : 0.0,
                       settings.trim.set ? 1.0 : 0.0,
                       settings.trim.start,
                       settings.trim.end,
                       seconds,
                       settings.pan};
  jdoubleArray out = env->NewDoubleArray(9);
  env->SetDoubleArrayRegion(out, 0, 9, values);
  return out;
}

JNIEXPORT jstring JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeChoke(JNIEnv* env, jobject,
                                                    jlong handle,
                                                    jstring padId) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return fromUtf8(env, std::string());
  PadSettings settings;
  if (!engine->core.get(toUtf8(env, padId), &settings, nullptr)) {
    return fromUtf8(env, std::string());
  }
  return fromUtf8(env, settings.choke);
}

/* THE PRESS. Nothing in here decodes, allocates a sample, or waits on the
 * audio thread; it works out a window and publishes a voice slot. */
JNIEXPORT jstring JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeFire(JNIEnv* env, jobject,
                                                   jlong handle, jstring padId,
                                                   jint mask, jdouble velocity,
                                                   jdouble pitch, jboolean loop,
                                                   jboolean gate) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return fromUtf8(env, std::string());

  FireOptions options;
  if (mask & kFireVelocity) {
    options.hasVelocity = true;
    options.velocity = velocity;
  }
  if (mask & kFirePitch) {
    options.hasPitch = true;
    options.pitch = pitch;
  }
  if (mask & kFireLoop) {
    options.hasLoop = true;
    options.loop = loop == JNI_TRUE;
  }
  options.gate = gate == JNI_TRUE;

  return fromUtf8(env, engine->core.fire(toUtf8(env, padId), options));
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeRelease(JNIEnv* env, jobject,
                                                      jlong handle,
                                                      jstring voiceId) {
  Engine* engine = engineOf(handle);
  if (engine != nullptr) engine->core.release(toUtf8(env, voiceId));
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeStopPad(JNIEnv* env, jobject,
                                                      jlong handle,
                                                      jstring padId) {
  Engine* engine = engineOf(handle);
  if (engine != nullptr) engine->core.stopPad(toUtf8(env, padId));
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeStopAll(JNIEnv*, jobject,
                                                      jlong handle) {
  Engine* engine = engineOf(handle);
  if (engine != nullptr) engine->core.stopAll();
}

/* [bytes, pads, buffers]. Buffers shared by copy() are counted ONCE - the
 * whole reason this number is worth reporting. */
JNIEXPORT jlongArray JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeFootprint(JNIEnv* env, jobject,
                                                        jlong handle) {
  Engine* engine = engineOf(handle);
  jlongArray out = env->NewLongArray(3);
  jlong values[3] = {0, 0, 0};
  if (engine != nullptr) {
    const Footprint footprint = engine->core.footprint();
    values[0] = static_cast<jlong>(footprint.bytes);
    values[1] = static_cast<jlong>(footprint.pads);
    values[2] = static_cast<jlong>(footprint.buffers);
  }
  env->SetLongArrayRegion(out, 0, 3, values);
  return out;
}

/* One snapshot of everything the UI meters, in one array, so the voice
 * count and the per-pad breakdown below cannot disagree:
 *
 *   0 state           5 burstFrames      10 api (0 none, 1 SLES, 2 AAudio)
 *   1 baseLatency     6 bufferFrames     11 timestampLatency (seconds)
 *   2 outputLatency   7 capacityFrames   12 fire-to-sound, last, ms
 *   3 voices          8 xruns            13 fire-to-sound, worst, ms
 *   4 duckGain        9 exclusive (0/1)  14 fire-to-sound, how many timed
 *                                        15 fire-to-sound, mean, ms
 *                                        16 mmap data path (0/1)
 *
 * Indices 12-15 are MEASURED WALL CLOCK, not a property of the buffer: see
 * StartLatency in pinebox/engine.h for exactly which links of the chain
 * they cover and which they do not. */
JNIEXPORT jdoubleArray JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeLevels(JNIEnv* env, jobject,
                                                     jlong handle) {
  Engine* engine = engineOf(handle);
  constexpr jsize kFields = 17;
  jdoubleArray out = env->NewDoubleArray(kFields);
  jdouble values[kFields] = {0, 0, 0, 0, 1, 0, 0, 0, 0,
                             0, 0, 0, 0, 0, 0, 0, 0};
  if (engine != nullptr) {
    const Levels levels = engine->core.levels();
    values[0] = static_cast<jdouble>(levels.state);
    values[1] = levels.baseLatency;
    values[2] = levels.outputLatency;
    values[3] = static_cast<jdouble>(levels.voices);
    values[4] = static_cast<jdouble>(engine->core.duckGain());
    values[5] = static_cast<jdouble>(levels.stream.burstFrames);
    values[6] = static_cast<jdouble>(levels.stream.bufferFrames);
    values[7] = static_cast<jdouble>(levels.stream.capacityFrames);
    values[8] = static_cast<jdouble>(levels.stream.xruns);
    values[9] = levels.stream.exclusive ? 1.0 : 0.0;
    values[10] = static_cast<jdouble>(levels.stream.api);
    values[11] = levels.stream.timestampLatency;
    values[12] = levels.start.lastMs;
    values[13] = levels.start.worstMs;
    values[14] = static_cast<jdouble>(levels.start.count);
    values[15] = levels.start.count > 0
                     ? levels.start.totalMs / levels.start.count
                     : 0.0;
    values[16] = levels.stream.mmap ? 1.0 : 0.0;
  }
  env->SetDoubleArrayRegion(out, 0, kFields, values);
  return out;
}

/* The engine's own monotonic clock, in nanoseconds.
 *
 * WHY THE PAGE NEEDS THIS. The fire-to-sound reading is stamped with
 * steady_clock down here; the page's own timings come from
 * performance.now(), which counts from a different zero. One reading of
 * both, taken next to each other, is what lets a measuring run put the two
 * halves of the chain on the same timeline instead of assuming they meet.
 * The JNI call itself costs well under a microsecond, which is three orders
 * of magnitude below anything being measured. */
JNIEXPORT jlong JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeNowNanos(JNIEnv*, jobject) {
  return static_cast<jlong>(pinebox::sampler::monotonicNanos());
}

/* Clear the fire-to-sound counters and drop the buffer back to its opening
 * two bursts. What a measuring run calls before it starts, so the numbers
 * describe the run and not the hour before it. */
JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeRetune(JNIEnv*, jobject,
                                                     jlong handle) {
  Engine* engine = engineOf(handle);
  if (engine == nullptr) return;
  engine->core.resetStartLatency();
  engine->output.retune();
}

/* Entries of the form "<count>:<padId>". The count comes first so a pad id
 * containing a colon (bank keys look like "b1:7") still splits cleanly on
 * the FIRST one. */
JNIEXPORT jobjectArray JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeLevelPads(JNIEnv* env, jobject,
                                                        jlong handle) {
  Engine* engine = engineOf(handle);
  jclass stringClass = env->FindClass("java/lang/String");
  if (engine == nullptr) {
    return env->NewObjectArray(0, stringClass, nullptr);
  }
  const Levels levels = engine->core.levels();
  jobjectArray out = env->NewObjectArray(
      static_cast<jsize>(levels.perPad.size()), stringClass, nullptr);
  jsize index = 0;
  for (const auto& entry : levels.perPad) {
    const std::string packed =
        std::to_string(entry.second) + ":" + entry.first;
    jstring value = fromUtf8(env, packed);
    env->SetObjectArrayElement(out, index++, value);
    env->DeleteLocalRef(value);
  }
  return out;
}

JNIEXPORT jfloat JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeDuckGain(JNIEnv*, jobject,
                                                       jlong handle) {
  Engine* engine = engineOf(handle);
  return engine == nullptr ? 1.0f : engine->core.duckGain();
}

JNIEXPORT void JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeSetDuckDepth(JNIEnv*, jobject,
                                                           jlong handle,
                                                           jfloat depth) {
  Engine* engine = engineOf(handle);
  if (engine != nullptr) engine->core.setDuckDepth(depth);
}

/* 16 Level, Tune. Kept on this side of the bridge so the ratio the tablet
 * plays is the ratio the engine tested, rather than a second copy of the
 * formula in Kotlin that could drift. */
JNIEXPORT jdouble JNICALL
Java_fm_pinebox_kiosk_audio_PineSampler_nativeSixteenPitch(JNIEnv*, jobject,
                                                           jint padIndex) {
  return pinebox::sampler::sixteenLevelPitch(static_cast<int>(padIndex));
}

}  // extern "C"
