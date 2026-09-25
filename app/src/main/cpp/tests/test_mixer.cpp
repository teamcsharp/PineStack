/* The envelope, and the reason there is one.
 *
 * "A raw start() or stop() on a buffer that isn't at a zero crossing is an
 * audible click, and a sampler that clicks is a toy." The JS suite can only
 * assert that a ramp was SCHEDULED - its fake context never renders a sample.
 * This one renders, so it can assert the ramp actually happened, which is the
 * fact that matters.
 *
 * Mirrors 'release and stopAll ramp a voice down rather than cutting it dead'
 * from the far side: same rule, read off the samples instead of off the call
 * log.
 */
#define PB_TEST_MAIN
#include "test_support.h"

#include <algorithm>
#include <cmath>
#include <vector>

#include "fixture.h"
#include "pinebox/engine.h"
#include "pinebox/mixer.h"

using namespace pinebox::sampler;

namespace {

/* Render into one long buffer so the shape of the envelope can be read. */
std::vector<float> capture(SamplerCore* core, double ms) {
  const int frames =
      static_cast<int>((ms / 1000.0) * core->engineRate());
  std::vector<float> out(static_cast<size_t>(frames) * core->outChannels(),
                         0.0f);
  const int block = 64;
  int done = 0;
  while (done < frames) {
    const int now = std::min(block, frames - done);
    core->render(out.data() + static_cast<size_t>(done) * core->outChannels(),
                 now);
    done += now;
  }
  return out;
}

float leftAt(const std::vector<float>& block, int channels, int frame) {
  return block[static_cast<size_t>(frame) * channels];
}

}  // namespace

PB_TEST(a_note_starts_from_silence) {
  /* Flat DC at full scale: whatever comes out IS the envelope, with no
   * waveform to confuse the reading. */
  SamplerCore core;
  core.load("dc", pbtest::flatBuffer(1.0));

  FireOptions held;
  held.gate = true;
  core.fire("dc", held);

  const std::vector<float> block = capture(&core, 10.0);
  const int channels = core.outChannels();

  PB_NEAR_MSG(leftAt(block, channels, 0), 0.0, 1e-9,
              "the first sample of a note is exactly zero");

  /* Up to full over the attack, and not before: a three millisecond ramp at
   * 48 kHz is 144 frames. */
  const int attackFrames =
      static_cast<int>(kAttackSeconds * pbtest::kRate);
  PB_CHECK_MSG(leftAt(block, channels, attackFrames / 2) < 0.75f,
               "still climbing half way through the attack");
  PB_NEAR_MSG(leftAt(block, channels, attackFrames + 4), 1.0, 0.02,
              "at full by the end of the attack");

  /* And monotone on the way up - a ramp with a step in it is the click this
   * exists to prevent. */
  for (int f = 1; f < attackFrames; ++f) {
    PB_CHECK(leftAt(block, channels, f) >= leftAt(block, channels, f - 1) - 1e-6f);
  }
}

PB_TEST(a_release_ramps_to_zero_rather_than_cutting) {
  SamplerCore core;
  core.load("dc", pbtest::flatBuffer(1.0));
  FireOptions held;
  held.gate = true;
  const std::string voice = core.fire("dc", held);

  capture(&core, 10.0);            /* past the attack, sitting at full */
  core.release(voice);
  const std::vector<float> tail = capture(&core, 30.0);
  const int channels = core.outChannels();

  const int releaseFrames =
      static_cast<int>(kReleaseSeconds * pbtest::kRate);
  PB_CHECK_MSG(leftAt(tail, channels, 1) > 0.5f,
               "a released note is still sounding on the next sample - the "
               "stop is scheduled after the ramp, not at once");
  PB_CHECK_MSG(leftAt(tail, channels, releaseFrames / 2) < 0.75f,
               "and is on its way down half way through");
  PB_NEAR_MSG(leftAt(tail, channels, releaseFrames + 8), 0.0, 1e-6,
              "reaching silence at the end of the ramp");

  /* No step anywhere on the way down. */
  for (int f = 1; f < releaseFrames; ++f) {
    PB_CHECK(leftAt(tail, channels, f) <= leftAt(tail, channels, f - 1) + 1e-6f);
  }
  PB_EQ_MSG(core.levels().voices, 0, "and the slot came back");
}

PB_TEST(a_one_shot_fades_its_own_tail) {
  /* The window ends mid-waveform. Web Audio cuts the source there; here the
   * last twelve milliseconds ramp down instead, so a trimmed one-shot does
   * not end on a step. */
  SamplerCore core;
  core.load("dc", pbtest::flatBuffer(1.0));
  PadPatch trim;
  trim.hasTrim = true;
  trim.trim.set = true;
  trim.trim.start = 0.0;
  trim.trim.end = 0.100;
  core.set("dc", trim);

  core.fire("dc", FireOptions());
  const std::vector<float> block = capture(&core, 120.0);
  const int channels = core.outChannels();
  const int endFrame = static_cast<int>(0.100 * pbtest::kRate);

  PB_NEAR_MSG(leftAt(block, channels, endFrame - 2), 0.0, 0.02,
              "the last sample of a one-shot is near silence, not a step");
  PB_CHECK_MSG(leftAt(block, channels, endFrame / 2) > 0.9f,
              "and the middle of it is at full level");
  PB_EQ(core.levels().voices, 0);
}

PB_TEST(a_short_slice_still_makes_a_sound) {
  /* Three milliseconds of attack plus twelve of release is fifteen; a chop
   * slice can be shorter than that. Squeezing both ramps to fit is what
   * keeps such a slice audible instead of swallowed by its own envelope. */
  SamplerCore core;
  core.load("dc", pbtest::flatBuffer(1.0));
  PadPatch trim;
  trim.hasTrim = true;
  trim.trim.set = true;
  trim.trim.start = 0.0;
  trim.trim.end = 0.005;          /* five milliseconds */
  core.set("dc", trim);

  core.fire("dc", FireOptions());
  const std::vector<float> block = capture(&core, 20.0);
  const int channels = core.outChannels();

  float loudest = 0.0f;
  for (int f = 0; f < static_cast<int>(0.005 * pbtest::kRate); ++f) {
    loudest = std::max(loudest, std::fabs(leftAt(block, channels, f)));
  }
  PB_CHECK_MSG(loudest > 0.5f, "a five millisecond slice is not silence");
}

PB_TEST(a_loop_wraps_inside_its_window) {
  /* A ramp from 0 to 1 across the sample: where the loop is reading is
   * legible straight off the output. */
  const int frames = pbtest::kRate;
  std::vector<float> ramp(static_cast<size_t>(frames), 0.0f);
  for (int f = 0; f < frames; ++f) {
    ramp[static_cast<size_t>(f)] = static_cast<float>(f) / frames;
  }
  SamplerCore core;
  core.load("ramp", std::make_shared<const SampleBuffer>(std::move(ramp), 1,
                                                        pbtest::kRate));
  PadPatch patch;
  patch.hasTrim = true;
  patch.trim.set = true;
  patch.trim.start = 0.50;
  patch.trim.end = 0.55;
  core.set("ramp", patch);

  FireOptions round;
  round.hasLoop = true;
  round.loop = true;
  core.fire("ramp", round);

  /* Well past the fifty millisecond window, and past the attack, so anything
   * still coming out has wrapped at least twice. */
  const std::vector<float> block = capture(&core, 200.0);
  const int channels = core.outChannels();
  const int from = static_cast<int>(0.120 * pbtest::kRate);
  for (int f = from; f < from + 2000; ++f) {
    const float v = leftAt(block, channels, f);
    PB_CHECK_MSG(v >= 0.49f && v <= 0.56f,
                 "a looping voice stays inside its window");
  }
  PB_EQ_MSG(core.levels().voices, 1, "and runs until it is released");
}

PB_TEST(voices_sum_rather_than_replace) {
  SamplerCore core;
  core.load("dc", pbtest::flatBuffer(0.25));
  PadPatch quiet;
  quiet.hasGain = true;
  quiet.gain = 1.0;
  core.set("dc", quiet);

  FireOptions held;
  held.gate = true;
  core.fire("dc", held);
  core.fire("dc", held);
  core.fire("dc", held);

  const std::vector<float> block = capture(&core, 20.0);
  const int channels = core.outChannels();
  PB_NEAR_MSG(leftAt(block, channels, static_cast<int>(0.010 * pbtest::kRate)),
              0.75, 0.02, "three quarter-scale voices sum to three quarters");
}
