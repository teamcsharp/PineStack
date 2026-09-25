/* pinebox/voice.h - one ringing note, and the table of them.
 *
 * THE THREADING RULE, because everything below only makes sense once it is
 * stated: there are exactly two threads. The CONTROL thread is whoever calls
 * fire()/release()/set() - the UI thread, or the WebView's bridge thread. The
 * AUDIO thread is Oboe's callback, which must never allocate, never lock and
 * never block, because a millisecond spent waiting there is an underrun and
 * an underrun is a click.
 *
 * So the table is preallocated and a slot is handed between the two threads
 * by one atomic:
 *
 *   Free  --control claims-->  Arming  --control publishes-->  Active
 *   Active  --audio finishes-->  Finished  --control reaps-->  Free
 *
 * The control thread fills every field of a slot while it is Arming (nobody
 * else can see it), then stores Active with release ordering; the audio
 * thread loads Active with acquire ordering and therefore sees all of it.
 *
 * Lifetime is the other half. The audio thread holds a RAW pointer to the
 * decoded sample; the control thread holds a shared_ptr to the same buffer in
 * the slot's meta and does not let go until it has seen Finished. That is why
 * no decoded audio is ever freed on the audio thread - freeing twelve
 * megabytes inside a 128-frame callback is exactly the kind of thing that
 * makes a sampler stutter under load.
 */
#ifndef PINEBOX_VOICE_H
#define PINEBOX_VOICE_H

#include <atomic>
#include <cstdint>
#include <string>

#include "pinebox/config.h"
#include "pinebox/sample_buffer.h"
#include "pinebox/window.h"

namespace pinebox {
namespace sampler {

enum class VoiceState : int {
  Free = 0,
  Arming = 1,
  Active = 2,
  Finished = 3
};

enum class EnvStage : int {
  Attack = 0,
  Sustain = 1,
  Release = 2
};

/* The part the audio thread touches. Plain data; no std::string, no
 * shared_ptr, nothing with a destructor that could run in the callback. */
struct VoiceRT {
  std::atomic<int> state{static_cast<int>(VoiceState::Free)};
  std::atomic<bool> releaseRequested{false};

  const SampleBuffer* buffer = nullptr;
  int frames = 0;
  int channels = 1;

  double position = 0.0;    /* in frames, fractional: the read head */
  double step = 1.0;        /* frames advanced per output frame = pitch */
  double endFrame = 0.0;    /* one-shot only; where it stops itself */
  double loopStart = 0.0;
  double loopEnd = 0.0;
  bool bounded = true;
  bool loop = false;

  float peak = 1.0f;        /* pad gain * velocity */
  /* CONSTANT POWER, WORKED OUT ONCE. Centre leaves both channels at 0.707
   * rather than 1.0, so a pad swept across the image keeps the same apparent
   * loudness - a linear pan dips 3 dB in the middle and sounds like a hole. */
  float panL = 0.70710678f;
  float panR = 0.70710678f;
  float env = 0.0f;         /* where the envelope is right now */
  float attackInc = 1.0f;   /* per output frame */
  float releaseDec = 1.0f;  /* per output frame, set when the release starts */
  /* How many OUTPUT frames the release ramp runs for. Normally twelve
   * milliseconds; squeezed for a window too short to hold a full attack and
   * a full release, because a five millisecond chop slice must still make a
   * sound rather than vanish into its own envelope. */
  double tailFrames = 1.0;
  int stage = static_cast<int>(EnvStage::Attack);

  /* Ordering, so a voice steal can pick the oldest rather than the lowest
   * numbered slot. Written by the control thread while Arming. */
  std::uint64_t serial = 0;

  /* THE FIRE-TO-SOUND STAMP. A monotonic nanosecond reading taken inside
   * fire() while this slot was Arming; the audio thread reads it in the
   * first block that gives this voice a sample, subtracts, and zeroes it.
   *
   * Atomic only so the zeroing is a defined write rather than a race the
   * sanitisers would complain about - the handover itself is already
   * ordered by the state store. On arm64 it is a plain load and store; it
   * costs the callback nothing. */
  std::atomic<std::uint64_t> firedNanos{0};
};

/* The part only the control thread touches. This is where the shared_ptr
 * lives, which is what keeps the buffer alive under the audio thread. */
struct VoiceMeta {
  std::string padId;
  std::string choke;
  SampleRef keepAlive;      /* the buffer VoiceRT::buffer points into */
  std::uint64_t voiceId = 0;
  bool inUse = false;
};

/* Start a voice from a plan. Control thread, slot must be Arming. */
void armVoice(VoiceRT* rt, const SampleBuffer* buffer, const VoicePlan& plan,
              int engineRate, std::uint64_t serial);

/* A monotonic nanosecond reading. std::chrono::steady_clock, which on this
 * platform is clock_gettime(CLOCK_MONOTONIC) through the vDSO: no syscall,
 * no allocation and no lock, which is why the audio thread may call it. */
std::uint64_t monotonicNanos();

/* Ask a ringing voice to fade out. Safe from the control thread at any time;
 * the audio thread picks it up on its next block. Used by release(), by a
 * choke, by a retrigger when polyphony is off, and by stopAll(). */
void requestRelease(VoiceRT* rt);

/* Whether a hit on `pad` should cut this ringing voice.
 *
 * PURE, and pinned by the JS test table: a non-empty choke group cuts its
 * siblings wherever they live, an identical pad id cuts only when polyphony
 * is off, and a pad outside the group keeps ringing either way.
 */
bool shouldCut(const std::string& firingPadId, const std::string& firingChoke,
               const std::string& ringingPadId, const std::string& ringingChoke,
               bool polyphonic);

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_VOICE_H */
