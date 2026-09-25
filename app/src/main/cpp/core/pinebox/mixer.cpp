#include "pinebox/mixer.h"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace pinebox {
namespace sampler {

float sampleAt(const SampleBuffer& buffer, double position, int channel) {
  const int frames = buffer.frames();
  if (frames <= 0) return 0.0f;
  double p = position;
  if (p < 0.0) p = 0.0;
  if (p > static_cast<double>(frames - 1)) p = static_cast<double>(frames - 1);
  const int i = static_cast<int>(p);
  const float t = static_cast<float>(p - i);
  return hermite4(buffer.at(i - 1, channel), buffer.at(i, channel),
                  buffer.at(i + 1, channel), buffer.at(i + 2, channel), t);
}

namespace {

/* Turn the envelope towards zero from wherever it actually is. Ramping from
 * the peak instead would make a note cut during its own attack jump UP
 * before it faded, which is the click this whole mechanism exists to avoid. */
inline void beginRelease(VoiceRT* voice) {
  if (voice->stage == static_cast<int>(EnvStage::Release)) return;
  voice->stage = static_cast<int>(EnvStage::Release);
  const double tail = voice->tailFrames > 0.0 ? voice->tailFrames : 1.0;
  voice->releaseDec = static_cast<float>(voice->env / tail);
  if (!(voice->releaseDec > 0.0f)) {
    /* Nothing audible to fade - end it on this frame rather than sit at
     * zero forever holding a slot. */
    voice->releaseDec = 1.0f;
  }
}

}  // namespace

bool renderVoice(VoiceRT* voice, float* out, int frames, int outChannels,
                 int engineRate) {
  (void)engineRate;
  const SampleBuffer* buffer = voice->buffer;
  if (buffer == nullptr || buffer->frames() <= 0) return true;

  /* Read once per block. A release asked for mid-block takes effect at the
   * next callback, which is a couple of milliseconds - well inside the
   * envelope it is about to ride anyway. */
  const bool releaseWanted =
      voice->releaseRequested.load(std::memory_order_relaxed);

  const int channels = buffer->channels();
  const double totalFrames = static_cast<double>(buffer->frames());
  /* A one-shot owns its own end. A gate or a loop runs until released, but
   * still cannot read past the end of the sample. */
  const double limit = voice->loop
                           ? totalFrames
                           : (voice->bounded
                                  ? std::min(voice->endFrame, totalFrames)
                                  : totalFrames);
  const double step = voice->step > 0.0 ? voice->step : 1e-9;
  bool finished = false;

  for (int f = 0; f < frames; ++f) {
    bool tailReached = false;
    if (voice->loop) {
      const double span = voice->loopEnd - voice->loopStart;
      if (span > 0.0) {
        while (voice->position >= voice->loopEnd) voice->position -= span;
        while (voice->position < voice->loopStart) voice->position += span;
      }
    } else {
      if (voice->position >= limit) {
        finished = true;
        break;
      }
      /* How many more output frames before the window runs out. Compared in
       * OUTPUT frames, not source frames, because a hit pitched up covers
       * the same window in fewer callbacks and would otherwise start its
       * tail far too late. */
      const double remaining = (limit - voice->position) / step;
      tailReached = remaining <= voice->tailFrames;
    }

    /* A release NEVER cuts into an attack. A finger that taps and lifts
     * inside one audio callback would otherwise get a note that ramps from
     * silence towards silence and is never heard at all - a pad that plays
     * nothing when you hit it fast is the worst bug this instrument could
     * have. The attack finishes, then the release starts. Three milliseconds
     * is not a latency anyone can feel; a missing note is. */
    if ((releaseWanted || tailReached) &&
        voice->stage == static_cast<int>(EnvStage::Sustain)) {
      beginRelease(voice);
    }

    /* Write with the envelope where it is, THEN move it. The first sample of
     * every note is therefore exactly zero, which is what "no click on the
     * way in" means. */
    const float gain = voice->env;
    /* The pan gains are precomputed per voice - see VoiceRT. Two multiplies
     * per frame is what this costs, and nothing in here calls a transcendental
     * function. */
    const float gl = gain * voice->panL;
    const float gr = gain * voice->panR;
    if (channels >= 2) {
      out[f * outChannels + 0] += sampleAt(*buffer, voice->position, 0) * gl;
      if (outChannels > 1) {
        out[f * outChannels + 1] += sampleAt(*buffer, voice->position, 1) * gr;
      }
    } else {
      /* The station serves mono. One read, two stores. */
      const float m = sampleAt(*buffer, voice->position, 0) * gain;
      out[f * outChannels + 0] += m * voice->panL;
      if (outChannels > 1) out[f * outChannels + 1] += m * voice->panR;
    }

    switch (static_cast<EnvStage>(voice->stage)) {
      case EnvStage::Attack:
        voice->env += voice->attackInc;
        if (voice->env >= voice->peak) {
          voice->env = voice->peak;
          voice->stage = static_cast<int>(EnvStage::Sustain);
        }
        break;
      case EnvStage::Sustain:
        break;
      case EnvStage::Release:
        voice->env -= voice->releaseDec;
        if (voice->env <= 0.0f) {
          voice->env = 0.0f;
          finished = true;
        }
        break;
    }

    voice->position += voice->step;
    if (finished) break;
  }

  return finished;
}

int renderBlock(VoiceRT* table, int slots, float* out, int frames,
                int outChannels, int engineRate) {
  std::memset(out, 0,
              sizeof(float) * static_cast<size_t>(frames) * outChannels);
  int ringing = 0;
  for (int i = 0; i < slots; ++i) {
    VoiceRT& voice = table[i];
    /* Acquire pairs with the control thread's release-store when it publishes
     * the slot, so everything it wrote into the slot is visible here. */
    if (voice.state.load(std::memory_order_acquire) !=
        static_cast<int>(VoiceState::Active)) {
      continue;
    }
    const bool done = renderVoice(&voice, out, frames, outChannels, engineRate);
    if (done) {
      /* A voice is never left dangling. A one-shot that ran out of window
       * frees its slot through exactly the same door a released gate does. */
      voice.buffer = nullptr;
      voice.state.store(static_cast<int>(VoiceState::Finished),
                        std::memory_order_release);
    } else {
      ++ringing;
    }
  }
  return ringing;
}

}  // namespace sampler
}  // namespace pinebox
