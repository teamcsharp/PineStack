/* The waveform view's two questions: what does it look like, and where is
 * the nearest place I can cut without a click.
 *
 * Mirrors, from tests/test_sampler_engine_2026_09_10.cjs:
 *   zero_cross_snaps        <- 'a trim handle snaps to the nearest zero
 *                              crossing'  (both halves, including the one
 *                              that must NOT move)
 *   peaks_answer_at_the_asked_resolution
 *                           <- 'peaks answer at the asked-for resolution for
 *                              the waveform view'
 *
 * Same fixture as the JS: a 10 Hz sine at 48 kHz, so the crossings really are
 * every 0.05 s and the peak really is one.
 */
#define PB_TEST_MAIN
#include "test_support.h"

#include <algorithm>

#include "fixture.h"
#include "pinebox/analysis.h"
#include "pinebox/engine.h"

using namespace pinebox::sampler;

PB_TEST(zero_cross_snaps) {
  auto buffer = pbtest::sineBuffer();
  const double snapped = zeroCross(*buffer, 0.052);
  PB_NEAR_MSG(snapped, 0.05, 0.002, "snapped to the crossing at 0.05");

  /* 0.025 s is the top of the lobe - the furthest this waveform ever gets
   * from a crossing. Half a millisecond of search reaches nothing, and the
   * handle must therefore stay exactly where the operator dropped it rather
   * than jumping twenty-five milliseconds to the nearest crossing. */
  const double far = zeroCross(*buffer, 0.025, 0.5);
  PB_NEAR_MSG(far, 0.025, 1e-12,
              "nothing within reach leaves the handle where it was put");
}

PB_TEST(zero_cross_is_bounded) {
  /* A pad of solid tone has no crossing anywhere near the handle, and a
   * search that wandered off looking for one would drag the trim somewhere
   * the operator never asked for. */
  auto flat = pbtest::flatBuffer(1.0);
  PB_NEAR(zeroCross(*flat, 0.4, 30.0), 0.4, 1e-12);
}

PB_TEST(zero_cross_on_an_empty_pad_answers_the_question_it_was_asked) {
  SamplerCore core;
  PB_NEAR(core.zeroCross("nothing", 0.3), 0.3, 1e-12);
}

PB_TEST(peaks_answer_at_the_asked_resolution) {
  SamplerCore core;
  core.load("wave", pbtest::sineBuffer());

  PB_EQ(core.peaks("wave", 256).size(), size_t(256));
  PB_EQ_MSG(core.peaks("missing", 256).size(), size_t(0),
            "a pad with no audio draws nothing rather than a flat line");

  const std::vector<float> peaks = core.peaks("wave", 64);
  const float loudest = *std::max_element(peaks.begin(), peaks.end());
  PB_CHECK_MSG(loudest > 0.9f, "a full-scale sine should peak near one");
}

PB_TEST(peaks_clamps_an_absurd_request) {
  auto buffer = pbtest::sineBuffer();
  PB_EQ(peaks(*buffer, 0).size(), size_t(1));
  PB_EQ(peaks(*buffer, -5).size(), size_t(1));
  PB_EQ_MSG(peaks(*buffer, 100000).size(), size_t(kMaxPeakBuckets),
            "the trim view is a few hundred pixels wide; a million buckets is "
            "a mistake, not a request");
}

PB_TEST(peaks_reads_every_channel) {
  /* A stereo sample whose right channel is the loud one still draws a
   * waveform: the envelope is the maximum across channels, not channel
   * zero's. */
  std::vector<float> samples(2000 * 2, 0.0f);
  for (int f = 0; f < 2000; ++f) {
    samples[static_cast<size_t>(f) * 2 + 0] = 0.05f;
    samples[static_cast<size_t>(f) * 2 + 1] = -0.8f;
  }
  const SampleBuffer buffer(std::move(samples), 2, pbtest::kRate);
  const std::vector<float> envelope = peaks(buffer, 10);
  PB_NEAR(envelope[0], 0.8, 1e-6);
}
