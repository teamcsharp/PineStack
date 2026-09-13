/* pinebox/duck.h - hold the music down while a pad is ringing.
 *
 * The tablet is a terminal for a radio station: something is nearly always
 * playing behind the sampler. A stab on top of a full mix at equal level is
 * mud, so the stream steps back while a pad rings and comes up again once it
 * stops.
 *
 * The only interesting part is the HOLD. A run of sixteenths is a voice
 * every 125 ms with silence between the hits; a duck that released the moment
 * a voice ended would pump the music once per note. So the gain falls fast,
 * stays down for a beat's worth of hold after the last voice, and comes back
 * slowly.
 *
 * PURE, and updated from the audio callback (one multiply-add per block).
 * The gain it produces is read by the Kotlin side and applied to whatever is
 * actually playing - the app's own player, and the rest of the device through
 * an AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK request.
 */
#ifndef PINEBOX_DUCK_H
#define PINEBOX_DUCK_H

#include "pinebox/config.h"

namespace pinebox {
namespace sampler {

class DuckBus {
 public:
  explicit DuckBus(int engineRate = kEngineRate) : rate_(engineRate) {}

  /* Called once per audio block. `ringing` is how many voices the mixer just
   * rendered. Returns the gain a concurrently playing stream should be at. */
  float advance(int ringing, int frames);

  float gain() const { return gain_; }
  bool ducked() const { return gain_ < 0.999f; }

  void reset() {
    gain_ = 1.0f;
    holdFrames_ = 0.0;
  }

  /* 1.0 disables ducking entirely; the operator may be monitoring on
   * headphones with the stream already where they want it. */
  void setDepth(float depth) {
    depth_ = depth < 0.0f ? 0.0f : (depth > 1.0f ? 1.0f : depth);
  }
  float depth() const { return depth_; }

 private:
  int rate_;
  float depth_ = kDuckDepth;
  float gain_ = 1.0f;
  double holdFrames_ = 0.0;
};

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_DUCK_H */
