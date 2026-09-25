#include "pinebox/analysis.h"

#include <algorithm>
#include <cmath>

#include "pinebox/window.h"

namespace pinebox {
namespace sampler {

std::vector<float> peaks(const SampleBuffer& buffer, int buckets) {
  const int count = std::max(1, std::min(kMaxPeakBuckets, buckets));
  std::vector<float> out(static_cast<size_t>(count), 0.0f);
  const int frames = buffer.frames();
  if (frames <= 0) return out;

  /* floor(), matching the JS. The last bucket therefore covers slightly less
   * than the tail of the sample when the division is not clean; the waveform
   * view has been drawn that way since the desktop build and changing it here
   * would make the same clip look different on the two terminals. */
  const int per = std::max(1, frames / count);
  const int channels = buffer.channels();
  const float* data = buffer.data();

  for (int i = 0; i < count; ++i) {
    const long long from = static_cast<long long>(i) * per;
    const long long to = std::min<long long>(frames, from + per);
    float peak = 0.0f;
    for (long long f = from; f < to; ++f) {
      for (int c = 0; c < channels; ++c) {
        const float v = data[static_cast<size_t>(f) * channels + c];
        const float a = v < 0.0f ? -v : v;
        if (a > peak) peak = a;
      }
    }
    out[static_cast<size_t>(i)] = peak;
  }
  return out;
}

double zeroCross(const SampleBuffer& buffer, double seconds, double withinMs) {
  const int frames = buffer.frames();
  if (frames <= 0) return seconds;
  const int rate = buffer.rate();
  const int channels = buffer.channels();
  const float* data = buffer.data();

  double wanted = seconds;
  if (std::isnan(wanted) || std::isinf(wanted)) wanted = 0.0;

  long long target = static_cast<long long>(std::llround(wanted * rate));
  target = std::max<long long>(0, std::min<long long>(frames - 1, target));
  const long long span = std::max<long long>(
      1, static_cast<long long>(std::llround((withinMs / 1000.0) * rate)));

  /* Outwards from the handle, a frame at a time, the earlier side first -
   * so a handle sitting exactly between two crossings snaps backwards, which
   * is the safe direction for a start handle and harmless for an end one. */
  for (long long step = 0; step <= span; ++step) {
    long long candidates[2];
    int howMany;
    if (step == 0) {
      candidates[0] = target;
      howMany = 1;
    } else {
      candidates[0] = target - step;
      candidates[1] = target + step;
      howMany = 2;
    }
    for (int k = 0; k < howMany; ++k) {
      const long long index = candidates[k];
      if (index <= 0 || index >= frames) continue;
      const float before = data[static_cast<size_t>(index - 1) * channels];
      const float here = data[static_cast<size_t>(index) * channels];
      if ((before <= 0.0f && here >= 0.0f) || (before >= 0.0f && here <= 0.0f)) {
        return static_cast<double>(index) / rate;
      }
    }
  }
  /* Nothing within reach. Leave the handle where the operator put it. */
  return seconds;
}

double sixteenLevelPitch(int padIndex) {
  /* Math.pow(2, (index - 8) / 12) - the same line sampler.js runs on the
   * desktop, so a chromatic run sounds identical on both terminals. */
  const double ratio = std::pow(2.0, (static_cast<double>(padIndex) - 8.0) / 12.0);
  /* Sixteen pads never come near the clamp; a caller that reaches this
   * function with a wild index still gets something playable. */
  return clampPitch(ratio);
}

}  // namespace sampler
}  // namespace pinebox
