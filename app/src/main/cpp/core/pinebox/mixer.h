/* pinebox/mixer.h - the audio callback's arithmetic, with no device in it.
 *
 * Everything here runs on the Oboe callback thread: no allocation, no locks,
 * no syscalls, no logging. It is also entirely pure with respect to the
 * platform, which is the point - the tests drive renderBlock() straight and
 * assert that a note starts from silence, that a release reaches zero over
 * twelve milliseconds, and that a one-shot frees its own slot.
 */
#ifndef PINEBOX_MIXER_H
#define PINEBOX_MIXER_H

#include "pinebox/config.h"
#include "pinebox/voice.h"

namespace pinebox {
namespace sampler {

/* Four point Hermite. Linear interpolation is audibly grainy once 16 Level
 * pushes a pad seven semitones up, and a windowed sinc is more arithmetic
 * than a mid-range MediaTek should be spending per voice per frame. This is
 * the middle, and it is what hardware samplers of this shape use. */
inline float hermite4(float xm1, float x0, float x1, float x2, float t) {
  const float c = (x1 - xm1) * 0.5f;
  const float v = x0 - x1;
  const float w = c + v;
  const float a = w + v + (x2 - x0) * 0.5f;
  const float b = w + a;
  return (((a * t) - b) * t + c) * t + x0;
}

/* Read one channel of a buffer at a fractional frame position. */
float sampleAt(const SampleBuffer& buffer, double position, int channel);

/* Render one voice into an interleaved stereo block, accumulating.
 * Returns true if the voice finished during this block. */
bool renderVoice(VoiceRT* voice, float* out, int frames, int outChannels,
                 int engineRate);

/* Render the whole table. `table` is kMaxVoices slots. Zeroes the block
 * first. Returns how many voices were still ringing when it was done - what
 * the duck bus reads, and what levels() reports. */
int renderBlock(VoiceRT* table, int slots, float* out, int frames,
                int outChannels, int engineRate);

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_MIXER_H */
