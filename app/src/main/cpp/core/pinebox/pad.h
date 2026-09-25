/* pinebox/pad.h - what a pad is, apart from the audio in it.
 *
 * One record per pad id, control-thread only. The audio thread never reads a
 * pad; fire() copies everything a voice needs into the voice slot before it
 * publishes it, so a knob turned while a note rings does not tear.
 */
#ifndef PINEBOX_PAD_H
#define PINEBOX_PAD_H

#include <string>

#include "pinebox/config.h"
#include "pinebox/sample_buffer.h"

namespace pinebox {
namespace sampler {

/* Seconds into the FORWARD sample. Stored forward even for a reversed pad,
 * because the operator dragged the handles over a forward waveform; mirroring
 * is the engine's job, not the trim editor's. */
struct Trim {
  bool set = false;
  double start = 0.0;
  double end = 0.0;
};

struct PadSettings {
  double gain = 1.0;
  double pitch = 1.0;
  /* -1 hard left, 0 centre, +1 hard right. Held as the operator set it and
   * turned into a pair of channel gains once, when a voice starts - the
   * audio thread must not be doing trigonometry per sample. */
  double pan = 0.0;
  bool loop = false;
  bool reverse = false;
  Trim trim;
  /* Pads sharing a non-empty group cut each other. Empty means "ring on". */
  std::string choke;
};

struct Pad {
  std::string id;
  SampleRef buffer;     /* shared with every pad chop copied it to */
  SampleRef reversed;   /* built lazily, only if this pad plays backwards */
  PadSettings settings;

  bool loaded() const { return static_cast<bool>(buffer); }
  double seconds() const { return buffer ? buffer->seconds() : 0.0; }
};

/* Which fields of a set() patch were actually present. Mirrors JavaScript's
 * `"gain" in patch`: a patch that does not mention loop must not turn it off. */
struct PadPatch {
  bool hasGain = false;    double gain = 1.0;
  bool hasPitch = false;   double pitch = 1.0;
  bool hasPan = false;     double pan = 0.0;
  bool hasLoop = false;    bool loop = false;
  bool hasReverse = false; bool reverse = false;
  bool hasChoke = false;   std::string choke;
  bool hasTrim = false;    Trim trim;   /* trim.set false == JS `trim: null` */
};

void applyPatch(Pad* pad, const PadPatch& patch);

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_PAD_H */
