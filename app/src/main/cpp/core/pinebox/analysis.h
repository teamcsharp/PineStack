/* pinebox/analysis.h - what the trim editor needs to see, and 16 Level.
 *
 * PURE. Both of these are line-for-line ports of sampler-engine.js, including
 * the parts that look odd: the bucket count that floors rather than spreads
 * the remainder, and the zero-crossing search that gives up and hands the
 * handle back unchanged rather than dragging it somewhere nobody asked for.
 */
#ifndef PINEBOX_ANALYSIS_H
#define PINEBOX_ANALYSIS_H

#include <vector>

#include "pinebox/config.h"
#include "pinebox/sample_buffer.h"

namespace pinebox {
namespace sampler {

/* A mono peak envelope at whatever resolution the waveform view asks for, so
 * the UI never touches a decoded buffer. Peak, not RMS: a transient that
 * averages away is a transient the operator cannot find a handle for. */
std::vector<float> peaks(const SampleBuffer& buffer, int buckets);

/* The nearest point to `seconds` where the waveform crosses zero. Trimming
 * anywhere else leaves a step in the signal, and a step is a click.
 *
 * The search is bounded: a pad of solid tone may have no crossing within
 * reach, and in that case the handle stays exactly where it was put. */
double zeroCross(const SampleBuffer& buffer, double seconds,
                 double withinMs = kDefaultZeroCrossMs);

/* 16 Level, Tune. One sample across the whole grid, played chromatically:
 * pad index 0..15 maps to -8..+7 semitones, so pad 8 is the sample as it was
 * recorded and pad 0 is two thirds of an octave below it.
 *
 * Exposed rather than buried so the UI can ask for the ratio and hand it back
 * as a per-hit pitch - which is how one press can be tuned without the pad's
 * own Tune setting moving at all. */
double sixteenLevelPitch(int padIndex);

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_ANALYSIS_H */
