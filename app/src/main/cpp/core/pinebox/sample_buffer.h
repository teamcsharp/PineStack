/* pinebox/sample_buffer.h - a decoded sample, resident.
 *
 * Decoded ONCE on load and held. Nothing decodes on the press: that is the
 * whole point of downloading the clip in the first place.
 *
 * Immutable once built, which is what makes copy() safe. Chop needs the same
 * thirty seconds of air on all sixteen pads with sixteen different windows;
 * they share one of these and differ only in their per-pad trim.
 */
#ifndef PINEBOX_SAMPLE_BUFFER_H
#define PINEBOX_SAMPLE_BUFFER_H

#include <cstddef>
#include <memory>
#include <vector>

namespace pinebox {
namespace sampler {

class SampleBuffer {
 public:
  /* Interleaved float32, frames * channels. Interleaved rather than planar
   * because the mixer reads it far more often than the waveform view does,
   * and the mixer wants both channels of one frame together. */
  SampleBuffer(std::vector<float> interleaved, int channels, int rate)
      : samples_(std::move(interleaved)),
        channels_(channels < 1 ? 1 : channels),
        rate_(rate < 1 ? 1 : rate) {
    frames_ = channels_ > 0
        ? static_cast<int>(samples_.size() / static_cast<size_t>(channels_))
        : 0;
  }

  int channels() const { return channels_; }
  int rate() const { return rate_; }
  int frames() const { return frames_; }
  double seconds() const {
    return rate_ > 0 ? static_cast<double>(frames_) / rate_ : 0.0;
  }

  const float* data() const { return samples_.data(); }

  float at(int frame, int channel) const {
    if (frame < 0) frame = 0;
    if (frame >= frames_) frame = frames_ - 1;
    if (frames_ <= 0) return 0.0f;
    if (channel >= channels_) channel = channels_ - 1;
    return samples_[static_cast<size_t>(frame) * channels_ + channel];
  }

  /* What this actually costs resident. float32 per sample per channel - the
   * same arithmetic footprint() does in the JS, so the two numbers can be
   * compared straight across. */
  std::size_t bytes() const { return samples_.size() * sizeof(float); }

 private:
  std::vector<float> samples_;
  int channels_ = 1;
  int rate_ = 48000;
  int frames_ = 0;
};

using SampleRef = std::shared_ptr<const SampleBuffer>;

/* The mirrored copy a reversed pad plays. Built lazily on the first reversed
 * fire, not on load - most pads are never reversed and a second copy of a
 * sixty-second line is another twelve megabytes. */
SampleRef reversedCopy(const SampleRef& source);

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_SAMPLE_BUFFER_H */
