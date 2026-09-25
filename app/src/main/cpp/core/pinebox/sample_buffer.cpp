#include "pinebox/sample_buffer.h"

#include <vector>

namespace pinebox {
namespace sampler {

SampleRef reversedCopy(const SampleRef& source) {
  if (!source) return nullptr;
  const int channels = source->channels();
  const int frames = source->frames();
  std::vector<float> out(static_cast<size_t>(frames) * channels, 0.0f);
  const float* in = source->data();
  for (int f = 0; f < frames; ++f) {
    const int from = frames - 1 - f;
    for (int c = 0; c < channels; ++c) {
      out[static_cast<size_t>(f) * channels + c] =
          in[static_cast<size_t>(from) * channels + c];
    }
  }
  return std::make_shared<const SampleBuffer>(std::move(out), channels,
                                              source->rate());
}

}  // namespace sampler
}  // namespace pinebox
