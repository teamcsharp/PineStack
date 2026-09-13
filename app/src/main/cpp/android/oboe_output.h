/* android/oboe_output.h - the stream that has to be short.
 *
 * "Tap the pad and it plays with no delay" is not one number, it is a chain:
 * touch event -> UI thread -> engine -> audio buffer -> mixer -> DAC. This
 * file owns the last four links, and the only lever that matters is the
 * buffer.
 *
 * What that means concretely on an MT6768:
 *   - AAudio, not OpenSL ES. Oboe picks AAudio on anything from Oreo up and
 *     that is the only backend with a genuine low-latency path.
 *   - EXCLUSIVE sharing mode: the app gets the mixer port to itself and the
 *     framework's shared mixer (and its buffer) is out of the chain. The
 *     request can be refused - another app may hold it - and Oboe then hands
 *     back a SHARED stream, which still works and is merely slower. That is
 *     a fact to report in levels(), not a reason to fail.
 *   - The device's native rate and native burst size, asked for by leaving
 *     them unset where possible and by matching 48 kHz where we cannot.
 *     Asking for a rate the device does not run at inserts the framework
 *     resampler, and with it a buffer nobody agreed to.
 *   - Buffer size set to two bursts after opening, which is the standard
 *     trade: one burst underruns on a busy core, three is audible slack.
 *
 * The number this produces is NOT the tap-to-sound figure. That is measured
 * on the physical tablet with a recorder and a finger, and anything reported
 * from in here is what the platform admits to, not what the operator hears.
 */
#ifndef PINEBOX_OBOE_OUTPUT_H
#define PINEBOX_OBOE_OUTPUT_H

#include <oboe/Oboe.h>

#include <oboe/LatencyTuner.h>

#include <atomic>
#include <memory>
#include <mutex>

#include "pinebox/engine.h"

namespace pinebox {
namespace sampler {
namespace android {

class OboeOutput : public oboe::AudioStreamDataCallback,
                   public oboe::AudioStreamErrorCallback {
 public:
  explicit OboeOutput(SamplerCore* core) : core_(core) {}
  ~OboeOutput() override { stop(); }

  /* Open and start. Called from a real gesture (warm()) so the first press
   * does not pay for it. Safe to call twice. */
  bool start();
  void stop();
  bool running() const;

  oboe::DataCallbackResult onAudioReady(oboe::AudioStream* stream,
                                        void* audioData,
                                        int32_t numFrames) override;

  /* A headset unplugged, or the device handed to another app, disconnects
   * the stream. Oboe calls this on its own thread; reopening from here is
   * what keeps the pads working after someone pulls the jack. */
  void onErrorAfterClose(oboe::AudioStream* stream,
                         oboe::Result error) override;

  bool exclusive() const { return exclusive_.load(std::memory_order_relaxed); }
  int burstFrames() const { return burst_.load(std::memory_order_relaxed); }

  /* Drop the buffer back to the floor and let the tuner raise it again.
   * Called when a measuring run starts, so the number being measured is the
   * one the instrument boots with rather than whatever the last hour of
   * underruns left behind. */
  void retune();

 private:
  /* Control thread. Reads everything the stream knows and hands it to the
   * core, which is what levels() reports. */
  void publishState();

  SamplerCore* core_;
  mutable std::mutex lock_;
  std::shared_ptr<oboe::AudioStream> stream_;

  /* OBOE'S OWN BUFFER TUNER (Apache 2.0, include/oboe/LatencyTuner.h).
   *
   * The trade it makes is the one this instrument wants and is not obvious
   * enough to reinvent: start at the shortest buffer the stream will take,
   * watch getXRunCount(), and add ONE BURST each time the count moves. A
   * fixed two bursts is a guess that is either too long on a quiet device or
   * too short when the big cores wander off; this finds the floor on the
   * hardware it is actually running on, and finds it again after a glitch.
   *
   * Oboe's documentation is explicit that tune() belongs at the END of the
   * data callback, so that is where it is called from. The pointer is read
   * there without the lock - the tuner outlives every callback because Oboe
   * does not return from close() while one is running, and close() is the
   * only thing that destroys it. */
  std::unique_ptr<oboe::LatencyTuner> tuner_;
  std::atomic<oboe::LatencyTuner*> tuning_{nullptr};

  std::atomic<bool> exclusive_{false};
  std::atomic<int> burst_{0};
  /* Publishing the xrun count is a handful of atomic stores, which is cheap,
   * but getXRunCount() is a call into the stream and does not need doing
   * five thousand times a second. Once every this-many callbacks - about
   * four times a second at a 256-frame burst - is plenty to watch it climb. */
  std::atomic<int> sinceReport_{0};
};

}  // namespace android
}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_OBOE_OUTPUT_H */
