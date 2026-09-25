#include "pinebox/window.h"

#include <algorithm>
#include <cmath>

namespace pinebox {
namespace sampler {

namespace {
bool bad(double v) { return std::isnan(v) || std::isinf(v); }
}  // namespace

double coerceOr(double value, double fallback) {
  if (bad(value) || value == 0.0) return fallback;
  return value;
}

double clampGain(double value) {
  if (bad(value)) value = 0.0;             /* JS: Number(x) || 0 */
  return std::max(0.0, std::min(kMaxGain, value));
}

double clampPitch(double value) {
  if (bad(value) || value == 0.0) value = 1.0;   /* JS: Number(x) || 1 */
  return std::max(kMinPitch, std::min(kMaxPitch, value));
}

double clampVelocity(double value) {
  /* The JS writes Math.max(0, Math.min(1, Number(v))) with no `|| 1`, so a
   * NaN velocity there produces a NaN gain, i.e. silence. That is a hole in
   * the coercion rather than a rule anyone relies on, so a NaN here reads as
   * a full-strength hit. Every real caller passes a number in 0..1. */
  if (bad(value)) return 1.0;
  return std::max(0.0, std::min(1.0, value));
}

PlayWindow computeWindow(const PadSettings& pad, double totalSeconds) {
  const double total = totalSeconds > 0.0 ? totalSeconds : 0.0;
  double start = 0.0;
  double end = total;

  if (pad.trim.set) {
    double rawStart = pad.trim.start;
    if (bad(rawStart)) rawStart = 0.0;                    /* JS: Number(s)||0 */
    start = std::max(0.0, std::min(total, rawStart));
    const double rawEnd = coerceOr(pad.trim.end, total);  /* JS: || total */
    end = std::max(start, std::min(total, rawEnd));
  }

  /* end at or before start is not a request for silence, it is a handle
   * dragged past its partner. Play the whole thing and let the operator see
   * what they did. */
  if (!(end > start)) {
    start = 0.0;
    end = total;
  }

  PlayWindow window;
  if (pad.reverse) {
    /* The voice will be handed the mirrored buffer, in which the material at
     * [start, end] lives at [total - end, total - start]. */
    window.offset = total - end;
  } else {
    window.offset = start;
  }
  window.duration = end - start;
  return window;
}

VoicePlan planFire(const PadSettings& pad, const FireOptions& options,
                   double totalSeconds) {
  const PlayWindow window = computeWindow(pad, totalSeconds);

  VoicePlan plan;
  plan.offset = window.offset;
  plan.duration = window.duration;
  plan.reverse = pad.reverse;
  plan.loop = options.hasLoop ? options.loop : pad.loop;
  /* A per-hit tune (16 Level, Note Repeat) replaces the pad's tune outright
   * for this press; it does not multiply it. */
  plan.pitch = clampPitch(options.hasPitch ? options.pitch : pad.pitch);
  plan.peakGain = clampGain(pad.gain) *
                  clampVelocity(options.hasVelocity ? options.velocity : 1.0);
  plan.pan = pad.pan;

  /* THE RULE. A held note must not schedule its own end, or the gate ends
   * when the sample does instead of when the finger lifts. */
  plan.bounded = !(plan.loop || options.gate);

  if (plan.loop) {
    plan.loopStart = window.offset;
    plan.loopEnd = window.offset + window.duration;
  }
  return plan;
}

}  // namespace sampler
}  // namespace pinebox
