/* 16 Level: one sample across the whole grid.
 *
 * The desktop computes this ratio in sampler.js and hands it to fire() as a
 * per-hit pitch. The tablet must produce the SAME ratio - a chromatic run
 * that is a semitone out on one terminal and not the other is worse than one
 * that is out on both.
 *
 * There is no case for this in test_sampler_engine_2026_09_10.cjs, because on
 * the desktop the formula lives in the UI rather than the engine. It is here
 * because the native engine owns it: the JS shim on the tablet asks the
 * engine for the ratio instead of carrying a second copy of the formula that
 * could drift. The half of it the JS suite DOES pin - that a per-hit pitch
 * reaches the voice and is clamped - is covered by 'velocity and tune reach
 * the voice, and are clamped', mirrored in test_window.cpp.
 */
#define PB_TEST_MAIN
#include "test_support.h"

#include <cmath>

#include "fixture.h"
#include "pinebox/analysis.h"
#include "pinebox/engine.h"

using namespace pinebox::sampler;

PB_TEST(the_grid_is_chromatic_around_pad_eight) {
  /* Pad index 0..15 maps to -8..+7 semitones. Pad 8 is the sample as it was
   * recorded; that anchor is what makes the feature usable, because the
   * operator can hear where "unchanged" is. */
  PB_NEAR_MSG(sixteenLevelPitch(8), 1.0, 1e-12,
              "pad 8 plays the sample as it was recorded");
  PB_NEAR(sixteenLevelPitch(0), std::pow(2.0, -8.0 / 12.0), 1e-12);
  PB_NEAR(sixteenLevelPitch(15), std::pow(2.0, 7.0 / 12.0), 1e-12);

  /* An octave apart is exactly a factor of two - the property that makes it
   * chromatic rather than merely "spread out". */
  PB_NEAR(sixteenLevelPitch(8 + 12) / sixteenLevelPitch(8), 2.0, 1e-12);
  PB_NEAR(sixteenLevelPitch(8) / sixteenLevelPitch(8 - 12), 2.0, 1e-12);
}

PB_TEST(the_grid_rises_from_pad_one) {
  /* Low at pad 1, so the layout reads left-to-right, bottom-to-top the way
   * the grid is drawn. */
  for (int pad = 1; pad < 16; ++pad) {
    PB_CHECK_MSG(sixteenLevelPitch(pad) > sixteenLevelPitch(pad - 1),
                 "the ratio rises with the pad index");
  }
  PB_CHECK(sixteenLevelPitch(0) < 1.0);
  PB_CHECK(sixteenLevelPitch(15) > 1.0);
}

PB_TEST(a_wild_index_is_still_playable) {
  /* Sixteen pads never come near the clamp. A caller that reaches this with
   * a bank offset baked in still gets something that makes a sound rather
   * than a stuck or a supersonic voice. */
  PB_NEAR(sixteenLevelPitch(1000), kMaxPitch, 1e-9);
  PB_NEAR(sixteenLevelPitch(-1000), kMinPitch, 1e-9);
}

PB_TEST(a_sixteen_level_hit_does_not_move_the_pad) {
  /* THE POINT of a per-hit pitch. The whole grid plays one pad chromatically
   * while that pad's own Tune setting stays exactly where the operator left
   * it - press pad 3, press pad 12, then press the pad itself and it is
   * still at the tune it was. */
  SamplerCore core;
  core.load("source", pbtest::sineBuffer());
  PadPatch tune;
  tune.hasPitch = true;
  tune.pitch = 1.25;
  core.set("source", tune);

  PadSettings before;
  PB_CHECK(core.get("source", &before, nullptr));

  for (int pad = 0; pad < 16; ++pad) {
    FireOptions hit;
    hit.hasPitch = true;
    hit.pitch = sixteenLevelPitch(pad);
    hit.gate = true;
    const std::string voice = core.fire("source", hit);
    PB_CHECK(!voice.empty());
    core.release(voice);
  }

  PadSettings after;
  PB_CHECK(core.get("source", &after, nullptr));
  PB_NEAR_MSG(after.pitch, before.pitch, 1e-12,
              "16 Level tunes the hit, not the pad");
  PB_NEAR(after.pitch, 1.25, 1e-12);
}

PB_TEST(the_whole_grid_shares_one_decode) {
  /* 16 Level and chop are the same memory story from two directions: one
   * sample, sixteen pads. Neither is allowed to decode sixteen times. */
  SamplerCore core;
  core.load("b1:0", pbtest::sineBuffer());
  for (int pad = 1; pad < 16; ++pad) {
    PB_CHECK(core.copy("b1:0", "b1:" + std::to_string(pad)));
  }
  PB_EQ(core.footprint().buffers, 1);

  /* And every one of them plays, at its own ratio. */
  for (int pad = 0; pad < 16; ++pad) {
    FireOptions hit;
    hit.hasPitch = true;
    hit.pitch = sixteenLevelPitch(pad);
    PB_CHECK(!core.fire("b1:" + std::to_string(pad), hit).empty());
  }
  PB_EQ(core.levels().voices, 16);
}
