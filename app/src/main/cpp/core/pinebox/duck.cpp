#include "pinebox/duck.h"

#include <algorithm>

namespace pinebox {
namespace sampler {

float DuckBus::advance(int ringing, int frames) {
  if (frames <= 0) return gain_;
  const double blockFrames = static_cast<double>(frames);

  if (ringing > 0) {
    holdFrames_ = kDuckHoldSeconds * rate_;
  } else {
    holdFrames_ = std::max(0.0, holdFrames_ - blockFrames);
  }

  const float target = (ringing > 0 || holdFrames_ > 0.0) ? depth_ : 1.0f;

  /* Down fast, up slowly - a duck that comes back as quickly as it goes is
   * heard as a swell. */
  const double rampSeconds =
      target < gain_ ? kDuckAttackSeconds : kDuckReleaseSeconds;
  const double rampFrames = std::max(1.0, rampSeconds * rate_);
  const float stepSize = static_cast<float>(blockFrames / rampFrames);

  if (target < gain_) {
    gain_ = std::max(target, gain_ - stepSize * (1.0f - depth_ + 1e-6f));
  } else {
    gain_ = std::min(target, gain_ + stepSize * (1.0f - depth_ + 1e-6f));
  }
  if (gain_ < 0.0f) gain_ = 0.0f;
  if (gain_ > 1.0f) gain_ = 1.0f;
  return gain_;
}

}  // namespace sampler
}  // namespace pinebox
