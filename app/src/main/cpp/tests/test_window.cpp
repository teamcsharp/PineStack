/* Which slice of the sample a press plays.
 *
 * Every case here is the C++ half of a case in
 * tests/test_sampler_engine_2026_09_10.cjs. Where that file reads the
 * arguments handed to AudioBufferSourceNode.start(), this one reads the
 * VoicePlan handed to a voice slot - `bounded` is the same fact as "start()
 * took three arguments rather than two".
 *
 * Mirrors:
 *   one_shot_gate_and_loop  <- 'a one-shot is given its exact window; a gate
 *                              and a loop are not'
 *   trim_narrows            <- 'a trim narrows the window that is played'
 *   reverse_mirrors_trim    <- 'reverse mirrors the trim rather than reusing it'
 *   nonsense_trim           <- 'a nonsense trim falls back to the whole sample
 *                              instead of silence'
 *   velocity_and_tune       <- 'velocity and tune reach the voice, and are
 *                              clamped'
 */
#define PB_TEST_MAIN
#include "test_support.h"

#include "pinebox/window.h"

using namespace pinebox::sampler;

namespace {

PadSettings plain() {
  PadSettings pad;
  pad.gain = 1.0;
  pad.pitch = 1.0;
  pad.loop = false;
  pad.reverse = false;
  pad.choke.clear();
  return pad;
}

PadSettings trimmed(double start, double end) {
  PadSettings pad = plain();
  pad.trim.set = true;
  pad.trim.start = start;
  pad.trim.end = end;
  return pad;
}

}  // namespace

PB_TEST(one_shot_gate_and_loop) {
  const PadSettings pad = plain();

  /* A one-shot owns its own end: offset AND duration. */
  VoicePlan shot = planFire(pad, FireOptions(), 1.0);
  PB_CHECK_MSG(shot.bounded, "a one-shot must schedule its own end");
  PB_NEAR(shot.offset, 0.0, 1e-9);
  PB_NEAR(shot.duration, 1.0, 1e-9);

  /* A held note must not, or the gate ends when the sample does. */
  FireOptions gate;
  gate.gate = true;
  VoicePlan held = planFire(pad, gate, 1.0);
  PB_CHECK_MSG(!held.bounded, "a held note must not schedule its own end");
  PB_NEAR(held.offset, 0.0, 1e-9);

  /* Nor does a loop, and its loop points are the window. */
  FireOptions looped;
  looped.hasLoop = true;
  looped.loop = true;
  VoicePlan round = planFire(pad, looped, 1.0);
  PB_CHECK(!round.bounded);
  PB_CHECK(round.loop);
  PB_NEAR(round.loopStart, 0.0, 1e-9);
  PB_NEAR(round.loopEnd, 1.0, 1e-9);
}

PB_TEST(trim_narrows) {
  const PlayWindow window = computeWindow(trimmed(0.25, 0.75), 1.0);
  PB_NEAR(window.offset, 0.25, 1e-9);
  PB_NEAR(window.duration, 0.5, 1e-9);
}

PB_TEST(reverse_mirrors_trim) {
  PadSettings pad = trimmed(0.1, 0.4);
  pad.reverse = true;
  const PlayWindow window = computeWindow(pad, 1.0);
  /* Played backwards, the material that ended at 0.4 s now BEGINS at
   * 1 - 0.4 = 0.6 s. Reusing the forward offset would play a different part
   * of the sample entirely, which is the bug this case exists to catch. */
  PB_NEAR_MSG(window.offset, 0.6, 1e-9, "offset mirrors");
  PB_NEAR_MSG(window.duration, 0.3, 1e-9, "duration is unchanged");
}

PB_TEST(reverse_of_the_whole_sample_is_the_whole_sample) {
  PadSettings pad = plain();
  pad.reverse = true;
  const PlayWindow window = computeWindow(pad, 1.0);
  PB_NEAR(window.offset, 0.0, 1e-9);
  PB_NEAR(window.duration, 1.0, 1e-9);
}

PB_TEST(nonsense_trim) {
  /* End before start. Silence would be technically defensible and useless:
   * the operator sees a dead pad and no reason for it. */
  const PlayWindow window = computeWindow(trimmed(0.9, 0.2), 1.0);
  PB_NEAR(window.offset, 0.0, 1e-9);
  PB_NEAR(window.duration, 1.0, 1e-9);

  /* Equal handles, same rule. */
  const PlayWindow pinched = computeWindow(trimmed(0.5, 0.5), 1.0);
  PB_NEAR(pinched.duration, 1.0, 1e-9);
}

PB_TEST(a_zero_end_handle_means_the_whole_tail) {
  /* JavaScript's `Number(trim.end) || total`. A trim of {start: 0.5, end: 0}
   * plays the second half, not nothing. Getting this wrong is silent on one
   * platform and audible on the other. */
  const PlayWindow window = computeWindow(trimmed(0.5, 0.0), 1.0);
  PB_NEAR(window.offset, 0.5, 1e-9);
  PB_NEAR(window.duration, 0.5, 1e-9);
}

PB_TEST(a_trim_past_the_end_is_clamped) {
  const PlayWindow window = computeWindow(trimmed(0.5, 9.0), 1.0);
  PB_NEAR(window.offset, 0.5, 1e-9);
  PB_NEAR(window.duration, 0.5, 1e-9);
}

PB_TEST(velocity_and_tune) {
  PadSettings pad = plain();
  pad.pitch = 2.0;
  PB_NEAR(planFire(pad, FireOptions(), 1.0).pitch, 2.0, 1e-9);

  FireOptions absurd;
  absurd.hasPitch = true;
  absurd.pitch = 1000.0;
  PB_NEAR_MSG(planFire(pad, absurd, 1.0).pitch, 32.0, 1e-9,
              "an absurd tune is clamped, not obeyed");

  FireOptions crawling;
  crawling.hasPitch = true;
  crawling.pitch = 0.0001;
  PB_NEAR(planFire(pad, crawling, 1.0).pitch, 0.03125, 1e-9);

  /* A per-hit tune REPLACES the pad's tune for that press; it does not
   * multiply it. 16 Level depends on this. */
  FireOptions oneHit;
  oneHit.hasPitch = true;
  oneHit.pitch = 1.5;
  PB_NEAR(planFire(pad, oneHit, 1.0).pitch, 1.5, 1e-9);

  /* Velocity scales the pad's gain, and is bounded at both ends. */
  pad.gain = 0.5;
  FireOptions soft;
  soft.hasVelocity = true;
  soft.velocity = 0.25;
  PB_NEAR(planFire(pad, soft, 1.0).peakGain, 0.125, 1e-9);

  FireOptions loud;
  loud.hasVelocity = true;
  loud.velocity = 9.0;
  PB_NEAR_MSG(planFire(pad, loud, 1.0).peakGain, 0.5, 1e-9,
              "velocity is 0..1, whatever the caller says");

  FireOptions negative;
  negative.hasVelocity = true;
  negative.velocity = -3.0;
  PB_NEAR(planFire(pad, negative, 1.0).peakGain, 0.0, 1e-9);
}

PB_TEST(a_missing_option_falls_back_to_the_pad) {
  PadSettings pad = plain();
  pad.pitch = 1.75;
  pad.loop = true;
  /* No fields present at all: the pad decides. This is the `in` operator's
   * job in the JS, and the reason FireOptions carries has* flags. */
  const VoicePlan plan = planFire(pad, FireOptions(), 1.0);
  PB_NEAR(plan.pitch, 1.75, 1e-9);
  PB_CHECK(plan.loop);
  PB_CHECK_MSG(!plan.bounded, "a looping pad runs until it is released");

  /* An explicit loop:false for one hit overrides a looping pad - Note Repeat
   * needs exactly this. */
  FireOptions once;
  once.hasLoop = true;
  once.loop = false;
  const VoicePlan single = planFire(pad, once, 1.0);
  PB_CHECK(!single.loop);
  PB_CHECK(single.bounded);
}
