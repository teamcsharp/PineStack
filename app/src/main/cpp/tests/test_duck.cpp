/* Holding the music down while a pad rings.
 *
 * No JavaScript counterpart: the desktop sampler runs alongside a stream the
 * operator can reach with a fader, and the tablet does not. The interesting
 * case is not "does it duck" but "does it stop pumping" - a run of
 * sixteenths is a voice every 125 ms, and a duck that released the instant a
 * voice ended would breathe once per note.
 */
#define PB_TEST_MAIN
#include "test_support.h"

#include <vector>

#include "fixture.h"
#include "pinebox/duck.h"
#include "pinebox/engine.h"

using namespace pinebox::sampler;

namespace {
constexpr int kBlock = 128;
}

PB_TEST(a_ringing_voice_pushes_the_stream_down) {
  DuckBus duck(kEngineRate);
  PB_NEAR_MSG(duck.gain(), 1.0, 1e-6, "nothing playing, nothing ducked");

  for (int i = 0; i < 40; ++i) duck.advance(1, kBlock);
  PB_NEAR_MSG(duck.gain(), kDuckDepth, 0.02,
              "a voice takes the stream down to the duck depth");
  PB_CHECK(duck.ducked());
}

PB_TEST(the_duck_holds_through_a_run_of_sixteenths) {
  DuckBus duck(kEngineRate);
  for (int i = 0; i < 40; ++i) duck.advance(1, kBlock);
  const float settled = duck.gain();

  /* 125 ms of nothing between hits at 120 bpm sixteenths. The hold is 350 ms,
   * so the gain must not have started climbing back yet. */
  const int gapBlocks = static_cast<int>(0.125 * kEngineRate / kBlock);
  for (int i = 0; i < gapBlocks; ++i) duck.advance(0, kBlock);
  PB_NEAR_MSG(duck.gain(), settled, 1e-4,
              "the duck holds across the gap between hits rather than "
              "breathing once per note");
}

PB_TEST(the_stream_comes_back_when_the_pads_stop) {
  DuckBus duck(kEngineRate);
  for (int i = 0; i < 40; ++i) duck.advance(1, kBlock);

  /* Hold, then release: well over a second of silence. */
  const int blocks = static_cast<int>(1.5 * kEngineRate / kBlock);
  for (int i = 0; i < blocks; ++i) duck.advance(0, kBlock);
  PB_NEAR_MSG(duck.gain(), 1.0, 1e-3, "and comes all the way back");
  PB_CHECK(!duck.ducked());
}

PB_TEST(the_duck_falls_faster_than_it_rises) {
  /* Down fast so the stab is not buried; up slowly so the return is not
   * heard as a swell. */
  DuckBus fall(kEngineRate);
  int downBlocks = 0;
  while (fall.gain() > kDuckDepth + 0.01f && downBlocks < 100000) {
    fall.advance(1, kBlock);
    downBlocks += 1;
  }

  DuckBus rise(kEngineRate);
  for (int i = 0; i < 200; ++i) rise.advance(1, kBlock);
  const int holdBlocks =
      static_cast<int>(kDuckHoldSeconds * kEngineRate / kBlock) + 2;
  for (int i = 0; i < holdBlocks; ++i) rise.advance(0, kBlock);
  int upBlocks = 0;
  while (rise.gain() < 0.99f && upBlocks < 100000) {
    rise.advance(0, kBlock);
    upBlocks += 1;
  }

  PB_CHECK_MSG(upBlocks > downBlocks * 3,
               "the return is much slower than the dip");
}

PB_TEST(depth_of_one_turns_ducking_off) {
  DuckBus duck(kEngineRate);
  duck.setDepth(1.0f);
  for (int i = 0; i < 200; ++i) duck.advance(4, kBlock);
  PB_NEAR_MSG(duck.gain(), 1.0, 1e-6,
              "an operator monitoring on headphones can switch it off");
}

PB_TEST(the_engine_reports_the_duck_gain_to_whoever_is_playing) {
  /* The engine does not touch the stream itself - it cannot, the stream is
   * an ExoPlayer or a WebView away. It publishes a number, and the Kotlin
   * side applies it. */
  SamplerCore core;
  core.load("pad", pbtest::sineBuffer());
  PB_NEAR(core.duckGain(), 1.0, 1e-6);

  FireOptions held;
  held.gate = true;
  core.fire("pad", held);

  std::vector<float> block(static_cast<size_t>(kBlock) * core.outChannels());
  for (int i = 0; i < 40; ++i) core.render(block.data(), kBlock);
  PB_CHECK_MSG(core.duckGain() < 0.9f,
               "firing a pad publishes a duck the host can act on");

  core.stopAll();
  const int blocks = static_cast<int>(2.0 * kEngineRate / kBlock);
  for (int i = 0; i < blocks; ++i) core.render(block.data(), kBlock);
  PB_NEAR(core.duckGain(), 1.0, 1e-3);
}
