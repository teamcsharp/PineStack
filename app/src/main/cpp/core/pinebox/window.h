/* pinebox/window.h - which slice of the sample a press actually plays.
 *
 * PURE. No device, no allocation, no clock. This is the part of the engine
 * that tests/test_sampler_engine_2026_09_10.cjs pins from the other side of
 * the seam, and every rule in here exists because a case in that file
 * asserts it:
 *
 *   - a one-shot is handed its exact window and stops itself;
 *   - a gate or a loop is handed only the offset and runs until released;
 *   - a trim narrows the window;
 *   - reverse MIRRORS the window rather than reusing it;
 *   - a nonsense trim (end not after start) falls back to the whole sample
 *     rather than to silence.
 */
#ifndef PINEBOX_WINDOW_H
#define PINEBOX_WINDOW_H

#include "pinebox/config.h"
#include "pinebox/pad.h"

namespace pinebox {
namespace sampler {

struct PlayWindow {
  double offset = 0.0;    /* seconds into the buffer handed to the voice */
  double duration = 0.0;  /* seconds */
};

/* Which fields of a fire() options object were present. Same reason as
 * PadPatch: `"loop" in options` is not the same question as `options.loop`,
 * and 16 Level depends on the difference - it overrides tune for one hit
 * without touching what the pad is set to. */
struct FireOptions {
  bool hasVelocity = false; double velocity = 1.0;
  bool hasPitch = false;    double pitch = 1.0;
  bool hasLoop = false;     bool loop = false;
  bool gate = false;
};

/* Everything the audio thread needs, worked out on the control thread. */
struct VoicePlan {
  double offset = 0.0;
  double duration = 0.0;
  /* true  -> a one-shot: the voice owns its own end at offset + duration.
   * false -> a gate or a loop: it runs until something releases it.
   * This single bool is what the JS test reads as "start() took three
   * arguments, not two". */
  bool bounded = true;
  bool loop = false;
  double loopStart = 0.0;
  double loopEnd = 0.0;
  double pitch = 1.0;
  double peakGain = 1.0;   /* pad gain * velocity */
  double pan = 0.0;        /* -1..+1, straight off the pad */
  bool reverse = false;
};

/* The JavaScript coercions, spelled out. `Number(x) || fallback` turns NaN
 * AND zero into the fallback; getting this wrong is how a trim of
 * {start: 0.5, end: 0} becomes silence on one platform and half a bar on
 * the other. */
double coerceOr(double value, double fallback);
double clampGain(double value);
double clampPitch(double value);
double clampVelocity(double value);

/* The window against the buffer the voice will be handed. For a reversed pad
 * that buffer is the mirrored copy, so the window is mirrored too: playing
 * [0.1, 0.4] of a one second sample backwards is offset 0.6, duration 0.3. */
PlayWindow computeWindow(const PadSettings& pad, double totalSeconds);

/* The whole press, decided. */
VoicePlan planFire(const PadSettings& pad, const FireOptions& options,
                   double totalSeconds);

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_WINDOW_H */
