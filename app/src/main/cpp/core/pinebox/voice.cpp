#include "pinebox/voice.h"

#include <algorithm>
#include <chrono>
#include <cmath>

namespace pinebox {
namespace sampler {

std::uint64_t monotonicNanos() {
  return static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
          std::chrono::steady_clock::now().time_since_epoch())
          .count());
}

void armVoice(VoiceRT* rt, const SampleBuffer* buffer, const VoicePlan& plan,
              int engineRate, std::uint64_t serial) {
  if (!rt || !buffer) return;
  const double rate = static_cast<double>(buffer->rate() > 0 ? buffer->rate()
                                                             : engineRate);

  rt->buffer = buffer;
  rt->frames = buffer->frames();
  rt->channels = buffer->channels();
  rt->serial = serial;

  rt->position = plan.offset * rate;
  /* Everything is decoded to the engine rate on load, so the read head moves
   * by exactly the pitch. The ratio is kept explicit anyway: the day a
   * buffer arrives at some other rate this is the line that has to hold. */
  rt->step = plan.pitch * (rate / static_cast<double>(engineRate));

  rt->bounded = plan.bounded;
  rt->loop = plan.loop;
  rt->endFrame = (plan.offset + plan.duration) * rate;
  rt->loopStart = plan.loopStart * rate;
  rt->loopEnd = plan.loopEnd * rate;
  if (rt->loop && !(rt->loopEnd > rt->loopStart + 1.0)) {
    /* A loop window shorter than a frame is a spin, not a note. */
    rt->loop = false;
  }

  rt->peak = static_cast<float>(plan.peakGain);
  {
    /* -1..+1 mapped onto the first quarter turn: 0 -> left, pi/2 -> right. */
    double pan = plan.pan;
    if (!(pan == pan)) pan = 0.0;
    if (pan < -1.0) pan = -1.0;
    if (pan > 1.0) pan = 1.0;
    const double angle = (pan + 1.0) * 0.25 * 3.14159265358979323846;
    rt->panL = static_cast<float>(std::cos(angle));
    rt->panR = static_cast<float>(std::sin(angle));
  }
  rt->env = 0.0f;
  rt->stage = static_cast<int>(EnvStage::Attack);

  /* Linear ramps, same shape as the linearRampToValueAtTime the Web Audio
   * side uses, so a hit sounds the same on both terminals. */
  double attackFrames = std::max(1.0, kAttackSeconds * engineRate);
  double tailFrames = std::max(1.0, kReleaseSeconds * engineRate);

  /* A window shorter than attack plus release would otherwise be swallowed
   * whole by its own envelope: the tail ramp would start before the attack
   * finished and the slice would never make a sound. Chop at sixteen over a
   * one second stab gets there. Squeeze both ramps to fit instead. */
  if (plan.bounded) {
    /* In OUTPUT frames: the window is measured in source seconds, and a hit
     * pitched up covers it in proportionately fewer callbacks. */
    const double windowFrames = std::max(
        1.0, plan.duration * engineRate / std::max(1e-9, plan.pitch));
    const double needed = (attackFrames + tailFrames) * 1.25;
    if (windowFrames < needed) {
      const double squeeze = windowFrames / needed;
      attackFrames = std::max(1.0, attackFrames * squeeze);
      tailFrames = std::max(1.0, tailFrames * squeeze);
    }
  }

  rt->attackInc = static_cast<float>(rt->peak / attackFrames);
  rt->tailFrames = tailFrames;
  rt->releaseDec = 0.0f;
  rt->releaseRequested.store(false, std::memory_order_relaxed);
}

void requestRelease(VoiceRT* rt) {
  if (!rt) return;
  rt->releaseRequested.store(true, std::memory_order_relaxed);
}

bool shouldCut(const std::string& firingPadId, const std::string& firingChoke,
               const std::string& ringingPadId, const std::string& ringingChoke,
               bool polyphonic) {
  const bool samePad = firingPadId == ringingPadId;
  const bool sameGroup = !firingChoke.empty() && firingChoke == ringingChoke;
  return sameGroup || (samePad && !polyphonic);
}

}  // namespace sampler
}  // namespace pinebox
