/* What the loaded pads actually cost in memory.
 *
 * Mirrors 'the memory footprint is real, and a chopped bank is counted once'
 * and 'chop shares one decoded buffer across pads instead of decoding again'
 * from tests/test_sampler_engine_2026_09_10.cjs.
 *
 * MEASURED, not assumed: a booth "line" off this station ran 62.97 s, which
 * decodes to roughly twelve megabytes of float32 at 48 kHz - not the fraction
 * of a megabyte its 596 KB mp3 suggests. Sixteen of them is a quarter of a
 * gigabyte, on a tablet. If chop's shared buffer were counted per pad the
 * reading would be sixteen times the truth and the warning it drives would be
 * nonsense; if it were not reported at all the operator would find out by
 * watching the app die.
 */
#define PB_TEST_MAIN
#include "test_support.h"

#include "fixture.h"
#include "pinebox/engine.h"

using namespace pinebox::sampler;

namespace {
/* One second, 48 kHz, mono, float32. */
constexpr std::uint64_t kOnePad = 48000ull * 1 * 4;
}  // namespace

PB_TEST(one_pad_costs_what_it_costs) {
  SamplerCore core;
  core.load("f1", pbtest::sineBuffer());
  const Footprint one = core.footprint();
  PB_EQ(one.pads, 1);
  PB_EQ(one.buffers, 1);
  PB_EQ_MSG(one.bytes, kOnePad, "float32 per sample per channel");
}

PB_TEST(two_decodes_cost_twice) {
  SamplerCore core;
  core.load("f1", pbtest::sineBuffer());
  core.load("f2", pbtest::sineBuffer());
  PB_EQ(core.footprint().bytes, kOnePad * 2);
  PB_EQ(core.footprint().buffers, 2);
}

PB_TEST(a_chopped_bank_is_counted_once) {
  SamplerCore core;
  core.load("f1", pbtest::sineBuffer());
  core.load("f2", pbtest::sineBuffer());

  PB_CHECK(core.copy("f1", "f3"));
  PB_CHECK(core.copy("f1", "f4"));

  const Footprint shared = core.footprint();
  PB_EQ_MSG(shared.pads, 4, "four pads have audio on them");
  PB_EQ_MSG(shared.buffers, 2, "but only two decodes happened");
  PB_EQ_MSG(shared.bytes, kOnePad * 2, "shared buffers are counted once");

  PB_CHECK_MSG(!core.copy("nothing-here", "f5"),
               "copying from an empty pad says no rather than emptying the "
               "destination");
}

PB_TEST(a_sixteen_way_chop_costs_one_decode) {
  /* The actual shape of the feature: thirty seconds of air across the whole
   * grid, one buffer, sixteen windows. */
  SamplerCore core;
  core.load("b1:0", pbtest::sineBuffer());
  for (int pad = 1; pad < 16; ++pad) {
    PB_CHECK(core.copy("b1:0", "b1:" + std::to_string(pad)));
    PadPatch slice;
    slice.hasTrim = true;
    slice.trim.set = true;
    slice.trim.start = pad / 16.0;
    slice.trim.end = (pad + 1) / 16.0;
    core.set("b1:" + std::to_string(pad), slice);
  }
  const Footprint footprint = core.footprint();
  PB_EQ(footprint.pads, 16);
  PB_EQ(footprint.buffers, 1);
  PB_EQ_MSG(footprint.bytes, kOnePad,
            "sixteen pads on one sample is one sample's worth of memory");

  /* And the windows really are different, which is the reason to share at
   * all. */
  PadSettings settings;
  PB_CHECK(core.get("b1:9", &settings, nullptr));
  const PlayWindow window = computeWindow(settings, core.seconds("b1:9"));
  PB_NEAR(window.offset, 9.0 / 16.0, 1e-9);
  PB_NEAR(window.duration, 1.0 / 16.0, 1e-9);
}

PB_TEST(reversing_a_pad_shows_up_in_the_reading) {
  /* A reversed pad holds a second, mirrored copy. That is another twelve
   * megabytes for a booth line and the operator is entitled to see it rather
   * than discover it. */
  SamplerCore core;
  core.load("back", pbtest::sineBuffer());
  PadPatch flip;
  flip.hasReverse = true;
  flip.reverse = true;
  core.set("back", flip);

  PB_EQ_MSG(core.footprint().bytes, kOnePad,
            "nothing is mirrored until the pad is actually played backwards");

  core.fire("back", FireOptions());
  const Footprint after = core.footprint();
  PB_EQ_MSG(after.buffers, 2, "the mirrored copy is a second buffer");
  PB_EQ(after.bytes, kOnePad * 2);
  PB_EQ_MSG(after.pads, 1, "on one pad");

  /* Turning reverse back off throws the copy away rather than holding it for
   * a pad that no longer plays backwards. */
  PadPatch unflip;
  unflip.hasReverse = true;
  unflip.reverse = false;
  core.set("back", unflip);
  PB_EQ(core.footprint().bytes, kOnePad);
}

PB_TEST(unloading_gives_the_memory_back) {
  SamplerCore core;
  core.load("f1", pbtest::sineBuffer());
  core.copy("f1", "f2");
  PB_EQ(core.footprint().pads, 2);
  core.unload("f1");
  const Footprint left = core.footprint();
  PB_EQ_MSG(left.pads, 1, "the copy still has it");
  PB_EQ_MSG(left.bytes, kOnePad,
            "and it still costs one decode, not zero and not two");
  core.unload("f2");
  PB_EQ(core.footprint().bytes, std::uint64_t(0));
}
