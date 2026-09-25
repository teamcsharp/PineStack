/* Which voices a new hit is allowed to cut, and which it must leave alone.
 *
 * Mirrors, from tests/test_sampler_engine_2026_09_10.cjs:
 *   polyphony_lets_pads_ring_together  <- 'polyphony lets pads ring together;
 *                                          switching it off cuts the last hit'
 *   choke_cuts_siblings_only           <- 'a choke group cuts its siblings but
 *                                          leaves other pads alone'
 *   release_and_stop_all_ramp          <- 'release and stopAll ramp a voice
 *                                          down rather than cutting it dead'
 *   empty_pad_is_silent                <- 'an empty pad is silent rather than
 *                                          an error'
 *   unloading_forgets_the_pad          <- 'unloading a pad silences it and
 *                                          forgets it'
 *
 * The JS counts calls to source.stop(). Here the equivalent reading is
 * releasingVoices() - how many ringing slots have been told to fade - and,
 * where the test wants to know the fade actually completed, a few blocks of
 * render() standing in for time passing.
 */
#define PB_TEST_MAIN
#include "test_support.h"

#include <vector>

#include "fixture.h"
#include "pinebox/engine.h"

using namespace pinebox::sampler;

namespace {

/* Time passing, in a suite with no audio device: render `ms` worth of blocks
 * and throw the audio away. */
void advance(SamplerCore* core, double ms) {
  const int frames = 128;
  const int blocks =
      static_cast<int>((ms / 1000.0) * core->engineRate() / frames) + 1;
  std::vector<float> block(static_cast<size_t>(frames) * core->outChannels());
  for (int i = 0; i < blocks; ++i) core->render(block.data(), frames);
}

void loadPad(SamplerCore* core, const std::string& id,
             const std::string& choke = std::string()) {
  core->load(id, pbtest::sineBuffer());
  PadPatch patch;
  patch.hasGain = true;   patch.gain = 1.0;
  patch.hasPitch = true;  patch.pitch = 1.0;
  patch.hasLoop = true;   patch.loop = false;
  patch.hasReverse = true; patch.reverse = false;
  patch.hasChoke = true;  patch.choke = choke;
  patch.hasTrim = true;   patch.trim.set = false;
  core->set(id, patch);
}

FireOptions gated() {
  FireOptions options;
  options.gate = true;
  return options;
}

}  // namespace

PB_TEST(a_sample_is_resident_once_loaded) {
  /* Mirrors 'a sample is decoded once on load and reports itself'. Decoding
   * itself is the platform's job and is covered in test_audio_format; what is
   * pinned here is that the engine holds the result and answers for it, so
   * nothing has to decode on the press. */
  SamplerCore core;
  const LoadResult got = core.load("a", pbtest::sineBuffer());
  PB_NEAR(got.seconds, pbtest::kSeconds, 1e-9);
  PB_EQ(got.rate, pbtest::kRate);
  PB_EQ(got.channels, 1);
  PB_CHECK(core.loaded("a"));
  PB_NEAR(core.seconds("a"), pbtest::kSeconds, 1e-9);
  PB_CHECK_MSG(!core.loaded("b"), "and says so about a pad it does not have");
  PB_NEAR(core.seconds("b"), 0.0, 1e-12);
}

PB_TEST(empty_pad_is_silent) {
  SamplerCore core;
  PB_EQ_MSG(core.fire("never-loaded", FireOptions()), std::string(),
            "a pad with no audio answers with no voice, not an error");
}

PB_TEST(polyphony_lets_pads_ring_together) {
  SamplerCore core;
  loadPad(&core, "poly");

  /* Gated so nothing ends on its own while the test is looking. */
  core.fire("poly", gated());
  core.fire("poly", gated());
  PB_EQ(core.levels().voices, 2);
  PB_EQ_MSG(core.releasingVoices(), 0, "nothing was cut");

  core.stopAll();
  advance(&core, 40.0);

  SamplerCore mono;
  loadPad(&mono, "poly");
  mono.setPolyphonic(false);
  mono.fire("poly", gated());
  mono.fire("poly", gated());
  PB_EQ_MSG(mono.releasingVoices(), 1,
            "the earlier voice is released, not left ringing");
  /* And it really goes: after a release ramp the slot is free again. */
  advance(&mono, 40.0);
  PB_EQ(mono.levels().voices, 1);
}

PB_TEST(choke_cuts_siblings_only) {
  SamplerCore core;
  loadPad(&core, "hat-open", "hats");
  loadPad(&core, "hat-shut", "hats");
  loadPad(&core, "kick", "");

  core.fire("kick", gated());
  core.fire("hat-open", gated());
  PB_EQ_MSG(core.releasingVoices(), 0, "nothing has been cut yet");

  core.fire("hat-shut", gated());
  PB_EQ_MSG(core.releasingVoices(), 1, "the open hat is cut");

  advance(&core, 40.0);
  const Levels levels = core.levels();
  PB_EQ_MSG(pbtest::padCount(levels.perPad, "kick"), 1, "the kick keeps ringing");
  PB_EQ(pbtest::padCount(levels.perPad, "hat-shut"), 1);
  PB_EQ_MSG(levels.perPad.count("hat-open"), size_t(0),
            "the open hat is gone, not merely quiet");
}

PB_TEST(choke_does_not_cut_the_pad_that_fired_it) {
  /* Two hits on the same choked pad with polyphony ON: the second still cuts
   * the first, because they share the group. But a THIRD pad in no group is
   * untouched either way - the group is the rule, not the pad. */
  SamplerCore core;
  loadPad(&core, "hat", "hats");
  loadPad(&core, "snare", "");
  core.fire("snare", gated());
  const std::string first = core.fire("hat", gated());
  PB_CHECK(!first.empty());
  core.fire("hat", gated());
  advance(&core, 40.0);
  const Levels levels = core.levels();
  PB_EQ(pbtest::padCount(levels.perPad, "hat"), 1);
  PB_EQ(pbtest::padCount(levels.perPad, "snare"), 1);
}

PB_TEST(release_and_stop_all_ramp) {
  SamplerCore core;
  loadPad(&core, "ring");
  const std::string voice = core.fire("ring", gated());
  PB_CHECK(!voice.empty());

  core.release(voice);
  PB_EQ_MSG(core.releasingVoices(), 1, "the voice was asked to fade");
  /* Half a release ramp in, it is still sounding: the stop is scheduled
   * AFTER the ramp, not at once. That gap is the whole point. */
  advance(&core, kReleaseSeconds * 1000.0 * 0.25);
  PB_EQ_MSG(core.levels().voices, 1, "still ringing part-way through a fade");
  advance(&core, kReleaseSeconds * 1000.0 * 2.0);
  PB_EQ_MSG(core.levels().voices, 0, "and gone once the ramp finished");

  core.fire("ring", gated());
  core.fire("ring", gated());
  PB_EQ(core.levels().voices, 2);
  core.stopAll();
  PB_EQ(core.releasingVoices(), 2);
  advance(&core, 40.0);
  PB_EQ(core.levels().voices, 0);
}

PB_TEST(stop_pad_leaves_the_other_pads_alone) {
  SamplerCore core;
  loadPad(&core, "a");
  loadPad(&core, "b");
  core.fire("a", gated());
  core.fire("b", gated());
  core.stopPad("a");
  advance(&core, 40.0);
  const Levels levels = core.levels();
  PB_EQ(levels.voices, 1);
  PB_EQ(pbtest::padCount(levels.perPad, "b"), 1);
}

PB_TEST(a_one_shot_frees_its_own_slot) {
  /* THE RULE: a voice is never left dangling. A long one-shot that finishes
   * on its own must free its slot by the same door a released gate does, or
   * the voice table fills up and the sampler stops making sound after a few
   * dozen hits. The JS gets this from onended; here the mixer publishes
   * Finished and the control thread reaps it. */
  SamplerCore core;
  loadPad(&core, "shot");
  PadPatch shortWindow;
  shortWindow.hasTrim = true;
  shortWindow.trim.set = true;
  shortWindow.trim.start = 0.0;
  shortWindow.trim.end = 0.05;
  core.set("shot", shortWindow);

  core.fire("shot", FireOptions());
  PB_EQ(core.levels().voices, 1);
  advance(&core, 80.0);
  PB_EQ_MSG(core.levels().voices, 0, "the one-shot reaped itself");

  /* And the slot really is reusable: a hundred hits in a row on a table of
   * thirty-two would fail otherwise. */
  for (int i = 0; i < 100; ++i) {
    PB_CHECK(!core.fire("shot", FireOptions()).empty());
    advance(&core, 80.0);
  }
  PB_EQ(core.levels().voices, 0);
}

PB_TEST(unloading_forgets_the_pad) {
  SamplerCore core;
  loadPad(&core, "gone");
  core.fire("gone", gated());
  PB_CHECK(core.unload("gone"));
  PB_CHECK(!core.loaded("gone"));
  PB_EQ(core.fire("gone", FireOptions()), std::string());
  /* Unloading silences what was ringing. */
  advance(&core, 40.0);
  PB_EQ(core.levels().voices, 0);
  PB_CHECK_MSG(!core.unload("never-existed"),
               "unloading a pad that was never there says so");
}

PB_TEST(clearing_drops_every_pad) {
  SamplerCore core;
  loadPad(&core, "one");
  loadPad(&core, "two");
  core.fire("one", gated());
  core.clear();
  advance(&core, 40.0);
  PB_CHECK(!core.loaded("one"));
  PB_CHECK(!core.loaded("two"));
  PB_EQ(core.levels().voices, 0);
  PB_EQ(core.footprint().bytes, std::uint64_t(0));
}

PB_TEST(the_voice_table_has_a_floor_not_a_cliff) {
  /* Thirty-two gated voices is past anything two hands can ask for. The
   * thirty-third press is dropped rather than stealing a slot the audio
   * thread is still reading, and the oldest voice starts fading so the press
   * after it has somewhere to go. Silence would be a bug; a crash would be
   * worse. */
  SamplerCore core;
  loadPad(&core, "many");
  for (int i = 0; i < kMaxVoices; ++i) {
    PB_CHECK(!core.fire("many", gated()).empty());
  }
  PB_EQ(core.levels().voices, kMaxVoices);
  PB_EQ_MSG(core.fire("many", gated()), std::string(),
            "the press past the ceiling is dropped, not faked");
  PB_EQ_MSG(core.releasingVoices(), 1, "and the oldest voice starts leaving");
  advance(&core, 40.0);
  PB_CHECK_MSG(!core.fire("many", gated()).empty(),
               "the next press finds the slot that was freed");
}
