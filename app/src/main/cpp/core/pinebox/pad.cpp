#include "pinebox/pad.h"

#include "pinebox/window.h"

namespace pinebox {
namespace sampler {

void applyPatch(Pad* pad, const PadPatch& patch) {
  if (!pad) return;
  if (patch.hasGain) pad->settings.gain = clampGain(patch.gain);
  if (patch.hasPitch) pad->settings.pitch = clampPitch(patch.pitch);
  if (patch.hasPan) {
    double pan = patch.pan;
    if (!(pan == pan)) pan = 0.0;            /* NaN is centre, not silence */
    pad->settings.pan = pan < -1.0 ? -1.0 : (pan > 1.0 ? 1.0 : pan);
  }
  if (patch.hasLoop) pad->settings.loop = patch.loop;
  if (patch.hasChoke) pad->settings.choke = patch.choke;
  if (patch.hasReverse) {
    /* Flipping the flag throws away the mirrored copy: it is now the wrong
     * way round, and rebuilding it costs a memcpy on the next press rather
     * than twelve megabytes held for a pad nobody reversed. */
    if (patch.reverse != pad->settings.reverse) pad->reversed = nullptr;
    pad->settings.reverse = patch.reverse;
  }
  if (patch.hasTrim) {
    if (patch.trim.set) {
      Trim trim;
      trim.set = true;
      /* JS stores Number(x) || 0 for BOTH handles here; the `|| total`
       * rescue for a zero end happens later, in computeWindow. */
      trim.start = coerceOr(patch.trim.start, 0.0);
      trim.end = coerceOr(patch.trim.end, 0.0);
      pad->settings.trim = trim;
    } else {
      pad->settings.trim = Trim();
    }
  }
}

}  // namespace sampler
}  // namespace pinebox
