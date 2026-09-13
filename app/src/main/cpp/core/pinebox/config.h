/* pinebox/config.h - the constants the sampler is built out of.
 *
 * These are not taste. Each one is pinned either by the Web Audio engine this
 * file has to agree with (desktop/renderer/sampler-engine.js) or by what the
 * hardware will actually hold.
 */
#ifndef PINEBOX_CONFIG_H
#define PINEBOX_CONFIG_H

namespace pinebox {
namespace sampler {

/* Long enough to hide a discontinuity, short enough that a stab still reads as
 * a stab. Measured by ear against the station's own stings; the same two
 * numbers live at the top of sampler-engine.js and must not drift apart. */
constexpr double kAttackSeconds  = 0.003;
constexpr double kReleaseSeconds = 0.012;

/* Everything is decoded to this. AAudio's exclusive low-latency path on the
 * MT6768 wants the device's native rate, which is 48 kHz on every MediaTek
 * part we have seen; asking for anything else silently inserts the framework
 * resampler and with it a buffer we did not agree to. */
constexpr int kEngineRate = 48000;

/* The output stream is stereo even for mono samples: an exclusive AAudio
 * stream on these parts refuses mono more often than it refuses stereo, and
 * duplicating a mono voice into two channels costs one store. */
constexpr int kEngineChannels = 2;

/* Sixteen pads, four banks, Note Repeat on top of a held chord. Thirty-two
 * is comfortably past anything a pair of hands can ask for, and the whole
 * table is preallocated so fire() never touches the allocator. */
constexpr int kMaxVoices = 32;

/* The same clamps sampler-engine.js applies. A pitch of zero is a stuck
 * voice, not a slow one, and a gain of forty is a blown speaker. */
constexpr double kMinPitch = 0.03125;   /* 1/32x */
constexpr double kMaxPitch = 32.0;
constexpr double kMaxGain  = 4.0;

/* Ducking: how far a concurrently playing stream is pushed down while a pad
 * is ringing, and how long it stays down after the last voice so a run of
 * sixteenths does not pump the music once per hit. */
constexpr float  kDuckDepth       = 0.35f;  /* linear gain, not dB */
constexpr double kDuckAttackSeconds  = 0.020;
constexpr double kDuckHoldSeconds    = 0.350;
constexpr double kDuckReleaseSeconds = 0.250;

/* peaks() refuses to build an envelope longer than this; the trim view is a
 * few hundred pixels wide and asking for a million buckets is a mistake, not
 * a request. Mirrors the Math.min(4096, ...) in the JS. */
constexpr int kMaxPeakBuckets = 4096;

/* zeroCross()'s default search radius, in milliseconds. */
constexpr double kDefaultZeroCrossMs = 30.0;

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_CONFIG_H */
