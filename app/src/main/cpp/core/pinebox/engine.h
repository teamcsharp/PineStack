/* pinebox/engine.h - window.pineSampler, in C++.
 *
 * THIS FILE IS A SEAM, NOT A FEATURE. The sampler UI talks to nothing but the
 * surface below; on the desktop that surface is implemented in Web Audio
 * (desktop/renderer/sampler-engine.js) and on the tablet it is implemented
 * here, on Oboe. Neither of them gets a second UI, so neither of them gets to
 * invent its own semantics.
 *
 * SamplerCore has no device in it. It owns the pads, the voice table and the
 * mixer, and it renders into a float block when someone asks. On the tablet
 * that someone is OboeOutput; in the tests it is the test itself, which is
 * how the whole engine can be exercised on a build machine with no sound
 * card and no NDK.
 */
#ifndef PINEBOX_ENGINE_H
#define PINEBOX_ENGINE_H

#include <atomic>
#include <cstdint>
#include <map>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "pinebox/analysis.h"
#include "pinebox/config.h"
#include "pinebox/duck.h"
#include "pinebox/mixer.h"
#include "pinebox/pad.h"
#include "pinebox/sample_buffer.h"
#include "pinebox/voice.h"
#include "pinebox/window.h"

namespace pinebox {
namespace sampler {

struct Footprint {
  std::uint64_t bytes = 0;
  int pads = 0;      /* pads holding audio */
  int buffers = 0;   /* DISTINCT decoded buffers - chop's sixteen share one */
};

/* What the platform's output stream is actually doing.
 *
 * Plain numbers, not oboe:: types, because this header is compiled on a
 * machine with no NDK - the whole point of the core/android split. The Oboe
 * layer fills it in after opening the stream and refreshes the counters that
 * move (xruns, buffer size) as it tunes.
 *
 * WHY IT IS REPORTED AT ALL. Every one of these was invisible before, and
 * each one is a question the operator's ear will otherwise ask and nobody
 * will be able to answer: did we get the exclusive port or the shared one,
 * is this the MMAP path or the legacy path, how big did the buffer end up
 * after tuning, and how many times has it run dry. A sampler that feels late
 * and cannot say why is a sampler nobody can fix. */
struct StreamFacts {
  int burstFrames = 0;      /* one hardware period                        */
  int bufferFrames = 0;     /* what setBufferSizeInFrames settled on      */
  int capacityFrames = 0;   /* the ceiling the tuner may not pass         */
  int xruns = 0;            /* underruns since the stream opened          */
  bool exclusive = false;   /* did we get the port to ourselves           */
  /* The MMAP data path, or the legacy one underneath it. AAudio hands back
   * a working stream either way and never says which. Whether it is
   * available at all is an OEM decision baked into the HAL and the ALSA
   * driver, not something an app can ask for. */
  bool mmap = false;
  int api = 0;              /* 0 none, 1 OpenSL ES, 2 AAudio              */
  /* Seconds from the mixer to the speaker, taken from the stream's own
   * timestamp rather than from the buffer size. 0 when the platform will
   * not give a timestamp, which is itself worth knowing: no timestamp
   * means no MMAP path. */
  double timestampLatency = 0.0;
};

/* The fire-to-sound reading.
 *
 * THIS IS NOT AN ESTIMATE. `queueMs` is wall-clock, measured with a
 * monotonic clock stamped inside fire() on the control thread and read
 * again on the audio thread in the first block in which that voice actually
 * produces a sample. It is the part of the chain this engine owns: the hop
 * from the press landing in the engine to the audio block carrying it.
 *
 * What it deliberately does NOT include, because the engine cannot see it:
 * the finger-to-digitizer time, the input stack's trip to the page, and the
 * presentation delay between the block and the speaker. The last of those
 * is StreamFacts::timestampLatency; the first two are measured on the
 * device with getevent and are not this number. Adding them up is the
 * caller's job, and it is the only honest way to say "tap to sound". */
struct StartLatency {
  double lastMs = 0.0;   /* the most recent voice                        */
  double worstMs = 0.0;  /* the worst since the counters were cleared    */
  int count = 0;         /* how many voices have been timed              */
  double totalMs = 0.0;  /* sum, so the caller can have a mean           */
};

struct Levels {
  int voices = 0;
  std::map<std::string, int> perPad;
  /* 0 closed, 1 suspended, 2 running - the same three words the Web Audio
   * context reports, so the UI's status line needs no second branch. */
  int state = 0;
  double baseLatency = 0.0;
  double outputLatency = 0.0;
  StreamFacts stream;
  StartLatency start;
};

/* What load() gives back, mirroring the {seconds, rate, channels} the JS
 * returns from decodeAudioData. */
struct LoadResult {
  double seconds = 0.0;
  int rate = 0;
  int channels = 0;
};

class SamplerCore {
 public:
  explicit SamplerCore(int engineRate = kEngineRate,
                       int outChannels = kEngineChannels);

  /* ---- loading ------------------------------------------------------- */

  /* Takes an ALREADY DECODED buffer. Decoding is the platform's job (see
   * android/media_decode.h); the core only ever holds PCM, which is what
   * lets the tests build a sample out of a sine and skip the codec. */
  LoadResult load(const std::string& padId, SampleRef buffer);

  /* Share one decoded buffer with another pad. Chop needs the same thirty
   * seconds of air on all sixteen pads with sixteen different windows;
   * decoding it sixteen times would be sixteen times the memory and the
   * wait, for identical samples. */
  bool copy(const std::string& fromPadId, const std::string& toPadId);

  bool unload(const std::string& padId);
  bool clear();

  bool loaded(const std::string& padId) const;
  double seconds(const std::string& padId) const;

  std::vector<float> peaks(const std::string& padId, int buckets) const;
  double zeroCross(const std::string& padId, double seconds,
                   double withinMs = kDefaultZeroCrossMs) const;

  /* ---- per-pad settings ---------------------------------------------- */

  void set(const std::string& padId, const PadPatch& patch);
  /* nullptr if the pad has never been touched, mirroring the JS get(). */
  bool get(const std::string& padId, PadSettings* out, double* seconds) const;

  void setPolyphonic(bool on);
  bool isPolyphonic() const;

  /* ---- playing -------------------------------------------------------- */

  /* A voice id, or "" if the pad is empty. Never throws, never blocks on the
   * audio thread, never allocates a buffer. */
  std::string fire(const std::string& padId, const FireOptions& options);

  void release(const std::string& voiceId);
  void stopPad(const std::string& padId);
  void stopAll();

  /* ---- metering ------------------------------------------------------- */

  Footprint footprint() const;
  /* Not const: it reclaims finished slots first, or it would report voices
   * that stopped sounding several blocks ago. */
  Levels levels();

  void setStreamState(int state, double baseLatency, double outputLatency);

  /* Called by the platform layer after the stream opens and whenever the
   * tuner moves the buffer. Never from the audio thread's hot path. */
  void setStreamFacts(const StreamFacts& facts);

  /* The two facts that MOVE while the instrument is playing, and the only
   * ones the audio thread is allowed to publish. Two relaxed atomic stores:
   * no allocation, no lock, nothing that can make a callback late. */
  void setStreamXRuns(int xruns, int bufferFrames);

  /* Clear the fire-to-sound counters, so a measurement run starts from a
   * known place rather than from whatever the last hour did. */
  void resetStartLatency();

  /* ---- the audio callback --------------------------------------------- */

  /* Interleaved float, `outChannels` wide. Called from Oboe. Everything it
   * touches was preallocated; nothing here takes a lock. */
  void render(float* out, int frames);

  float duckGain() const {
    return duckGain_.load(std::memory_order_relaxed);
  }
  void setDuckDepth(float depth);

  int engineRate() const { return engineRate_; }
  int outChannels() const { return outChannels_; }

  /* Diagnostics, and what the tests read instead of a sound card.
   * activeVoices() is how many slots are ringing; releasingVoices() is how
   * many have been told to fade - the direct analogue of the JS test's
   * `stopped.length`, which counts source.stop() calls. */
  int activeVoices();
  int releasingVoices();

 private:
  /* Audio thread. Stamps the fire-to-sound reading for any voice that is
   * about to make its first sample. Costs one monotonic clock read per
   * block, and only when a voice actually started in it. */
  void timeStarts();

  /* Control thread only. Reclaims slots the audio thread has finished with,
   * which is the only place a decoded buffer is ever released. */
  void reap();
  int claimSlot();
  void cutSiblings(const Pad& firing, int exceptSlot);
  Pad& padRecord(const std::string& padId);
  const Pad* findPad(const std::string& padId) const;

  int engineRate_;
  int outChannels_;

  mutable std::mutex control_;   /* guards pads_, meta_, ids_. NEVER taken by
                                  * the audio thread. */
  std::map<std::string, Pad> pads_;
  VoiceRT rt_[kMaxVoices];
  VoiceMeta meta_[kMaxVoices];
  std::unordered_map<std::uint64_t, int> ids_;  /* voice id -> slot */
  std::uint64_t voiceSeq_ = 0;
  bool polyphonic_ = true;

  DuckBus duck_;
  std::atomic<float> duckGain_{1.0f};
  std::atomic<int> ringing_{0};

  std::atomic<int> streamState_{0};
  std::atomic<double> baseLatency_{0.0};
  std::atomic<double> outputLatency_{0.0};

  /* Written by the platform layer, read by levels(). Each field is its own
   * atomic rather than a locked struct because the audio thread refreshes
   * the xrun count and must not wait for a UI poll to let go of anything. */
  std::atomic<int> burstFrames_{0};
  std::atomic<int> bufferFrames_{0};
  std::atomic<int> capacityFrames_{0};
  std::atomic<int> xruns_{0};
  std::atomic<bool> exclusive_{false};
  std::atomic<bool> mmap_{false};
  std::atomic<int> api_{0};
  std::atomic<double> timestampLatency_{0.0};

  /* The fire-to-sound reading. Written on the audio thread, read by the UI. */
  std::atomic<double> startLastMs_{0.0};
  std::atomic<double> startWorstMs_{0.0};
  std::atomic<int> startCount_{0};
  std::atomic<double> startTotalMs_{0.0};
};

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_ENGINE_H */
