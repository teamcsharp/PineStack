/* tests/fixture.h - the same sample the JavaScript tests use.
 *
 * A 10 Hz sine at 48 kHz, one second long: known, evenly spaced zero
 * crossings every 0.05 s, and a peak of one. Sharing the fixture with
 * tests/test_sampler_engine_2026_09_10.cjs is what makes the two suites
 * comparable rather than merely similar - the zero crossing case on both
 * sides is looking at the identical waveform.
 */
#ifndef PINEBOX_TEST_FIXTURE_H
#define PINEBOX_TEST_FIXTURE_H

#include <cmath>
#include <vector>

#include "pinebox/sample_buffer.h"

namespace pbtest {

constexpr int kRate = 48000;
constexpr double kSeconds = 1.0;

inline pinebox::sampler::SampleRef sineBuffer(int channels = 1,
                                              double hz = 10.0,
                                              double seconds = kSeconds,
                                              int rate = kRate) {
  const int frames = static_cast<int>(seconds * rate);
  std::vector<float> samples(static_cast<size_t>(frames) * channels, 0.0f);
  for (int f = 0; f < frames; ++f) {
    const float v = static_cast<float>(
        std::sin((2.0 * 3.14159265358979323846 * hz * f) / rate));
    for (int c = 0; c < channels; ++c) {
      samples[static_cast<size_t>(f) * channels + c] = v;
    }
  }
  return std::make_shared<const pinebox::sampler::SampleBuffer>(
      std::move(samples), channels, rate);
}

/* Flat DC, for tests that want to read the envelope rather than the material
 * underneath it. */
inline pinebox::sampler::SampleRef flatBuffer(double value = 1.0,
                                              double seconds = kSeconds,
                                              int rate = kRate) {
  const int frames = static_cast<int>(seconds * rate);
  std::vector<float> samples(static_cast<size_t>(frames),
                             static_cast<float>(value));
  return std::make_shared<const pinebox::sampler::SampleBuffer>(
      std::move(samples), 1, rate);
}

}  // namespace pbtest

#endif  /* PINEBOX_TEST_FIXTURE_H */
