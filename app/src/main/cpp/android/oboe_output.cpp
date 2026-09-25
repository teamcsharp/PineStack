#include "android/oboe_output.h"

#include <android/log.h>
#include <oboe/OboeExtensions.h>

#include <memory>

#define PB_LOG(...) \
  __android_log_print(ANDROID_LOG_INFO, "pinebox.sampler", __VA_ARGS__)

namespace pinebox {
namespace sampler {
namespace android {

bool OboeOutput::start() {
  std::lock_guard<std::mutex> guard(lock_);
  if (stream_ && stream_->getState() != oboe::StreamState::Closed) return true;

  oboe::AudioStreamBuilder builder;
  builder.setDirection(oboe::Direction::Output)
      ->setPerformanceMode(oboe::PerformanceMode::LowLatency)
      /* The ask. Oboe falls back to Shared on its own if the device will not
       * give it up, and the fallback is fine - it is slower, not broken.
       * Google's own round-trip table puts Shared at 26 ms against
       * Exclusive's 20, and PerformanceMode::None at 205 - which is the real
       * reason the line above it is the one that must never be dropped. */
      ->setSharingMode(oboe::SharingMode::Exclusive)
      ->setFormat(oboe::AudioFormat::Float)
      ->setChannelCount(kEngineChannels)
      /* BOTH CONVERSIONS DEFAULT TO FALSE, which is the trap. Ask for float
       * stereo on a HAL that will only hand out its own shape and the open
       * does not quietly adapt - it fails, or it lands somewhere slower.
       * Letting Oboe convert costs one pass over the block and keeps the
       * low-latency stream. RhythmGame's Game.cpp sets both; drumthumper
       * sets neither and is a known trap for exactly this reason. */
      ->setFormatConversionAllowed(true)
      ->setChannelConversionAllowed(true)
      /* 48 kHz IS this device's native rate - MEASURED: the flinger's
       * primary output runs at 48000 with a 256-frame HAL period - and the
       * whole engine decodes to it, so asking costs nothing here. It would
       * be a serious mistake anywhere else: forcing 44100 on a 48 kHz device
       * measures 160 ms round trip against 20, because the framework
       * resampler arrives with a buffer nobody agreed to. If this ever runs
       * on a part that is not 48 kHz, the fix is to resample the SAMPLES at
       * load and take whatever rate the device offers - not to keep this. */
      ->setSampleRate(kEngineRate)
      ->setSampleRateConversionQuality(oboe::SampleRateConversionQuality::Medium)
      /* Game, not Media: it is the usage that asks the platform for the
       * short path, and a pad hit is much closer to a game sound than to a
       * track. Sonification keeps it out of the way of media transport keys. */
      ->setUsage(oboe::Usage::Game)
      ->setContentType(oboe::ContentType::Sonification)
      /* NOT setFramesPerDataCallback(). Leaving it unspecified is what makes
       * the callback size equal the burst; pinning it is for block-oriented
       * DSP that needs a fixed window, and here it only costs latency. */
      ->setDataCallback(this)
      ->setErrorCallback(this);

  std::shared_ptr<oboe::AudioStream> stream;
  oboe::Result result = builder.openStream(stream);
  if (result != oboe::Result::OK) {
    PB_LOG("could not open the audio stream: %s", oboe::convertToText(result));
    core_->setStreamState(0, 0.0, 0.0);
    return false;
  }

  /* CLOSING IS NOT INSTANT. Oboe's crash note is blunt about it: callback
   * threads, error callbacks especially, can still be running after close()
   * has returned, and most Oboe crashes in the wild are a use-after-free of
   * exactly that shape. Half a second of grace costs nothing on a kiosk
   * that opens this stream once and keeps it. */
  stream->setDelayBeforeCloseMillis(500);

  /* ADPF - the Android Dynamic Performance Framework, Oboe 1.8 and up.
   *
   * THIS IS THE ONE THAT MATTERS ON THIS PART. The audio callback sleeps
   * through most of every burst, so a governor watching it sees an idle
   * core and clocks it down; the next time a hand lands on four pads at
   * once the work arrives on a slow core, and the ramp back up can take a
   * hundred milliseconds - a hundred milliseconds of glitching. ADPF tells
   * the scheduler what the deadline actually is instead of letting it infer
   * one. It is the modern replacement for oboe::StabilizedCallback, which
   * fixed the same problem by burning CPU in a spin loop to keep the core
   * awake: the right answer for a plugged-in desktop, the wrong one for a
   * tablet somebody is holding. */
  stream->setPerformanceHintEnabled(true);

  /* Two bursts to open with, then let Oboe's tuner find the real floor.
   *
   * Two is the standard opening bid: one underruns the moment the big cores
   * go elsewhere, and on this part they do. But it is a GUESS, and the point
   * of the tuner below is that the device does not have to be guessed about.
   * It starts here and adds a burst whenever the underrun count moves.
   *
   * THE CEILING IS A MUSICAL DECISION, not a technical one. Four bursts is
   * about twenty-one milliseconds on this hardware, and past that the
   * instrument stops being playable: a drummer feels a late hit long before
   * they notice a glitch, so if four bursts is not enough the answer is to
   * find what is eating the CPU, not to keep adding lag until the noise
   * stops. Oboe's default ceiling is the whole buffer capacity, which on
   * this device would let it grow to something nobody could play. */
  const int burst = stream->getFramesPerBurst();
  stream->setBufferSizeInFrames(burst * 2);
  tuner_ = std::make_unique<oboe::LatencyTuner>(*stream, burst * 4);

  result = stream->requestStart();
  if (result != oboe::Result::OK) {
    PB_LOG("the audio stream would not start: %s", oboe::convertToText(result));
    stream->close();
    tuner_.reset();
    core_->setStreamState(0, 0.0, 0.0);
    return false;
  }

  exclusive_.store(stream->getSharingMode() == oboe::SharingMode::Exclusive,
                   std::memory_order_relaxed);
  burst_.store(burst, std::memory_order_relaxed);
  stream_ = stream;
  /* Published only now that the stream is started and stored: the callback
   * may already be running, and it must not find a tuner pointing at a
   * stream this function might still abandon. */
  tuning_.store(tuner_.get(), std::memory_order_release);

  /* WHAT WE ACTUALLY GOT, not what was asked for. Every one of these can
   * come back different from the request, silently, and a stream that feels
   * late with no explanation is nearly always one of them. */
  PB_LOG("stream up: %d Hz, %d ch, %s, burst %d, buffer %d of %d, %s, api %s, "
         "perf %s, mmap %s, %s",
         stream->getSampleRate(), stream->getChannelCount(),
         oboe::convertToText(stream->getFormat()), burst,
         stream->getBufferSizeInFrames(), stream->getBufferCapacityInFrames(),
         exclusive_.load(std::memory_order_relaxed) ? "exclusive" : "shared",
         oboe::convertToText(stream->getAudioApi()),
         oboe::convertToText(stream->getPerformanceMode()),
         oboe::OboeExtensions::isMMapUsed(stream.get()) ? "yes" : "no",
         stream->isPerformanceHintEnabled() ? "adpf" : "no-adpf");

  publishState();
  return true;
}

void OboeOutput::publishState() {
  if (!stream_) {
    core_->setStreamState(0, 0.0, 0.0);
    core_->setStreamFacts(StreamFacts());
    return;
  }
  const int rate = stream_->getSampleRate() > 0 ? stream_->getSampleRate()
                                                : kEngineRate;
  const double base =
      static_cast<double>(stream_->getFramesPerBurst()) / rate;
  double output = 0.0;
  auto latency = stream_->calculateLatencyMillis();
  if (latency) output = latency.value() / 1000.0;
  const bool running = stream_->getState() == oboe::StreamState::Started ||
                       stream_->getState() == oboe::StreamState::Starting;
  core_->setStreamState(running ? 2 : 1, base, output);

  StreamFacts facts;
  facts.burstFrames = stream_->getFramesPerBurst();
  facts.bufferFrames = stream_->getBufferSizeInFrames();
  facts.capacityFrames = stream_->getBufferCapacityInFrames();
  auto xruns = stream_->getXRunCount();
  facts.xruns = xruns ? xruns.value() : 0;
  facts.exclusive = stream_->getSharingMode() == oboe::SharingMode::Exclusive;
  facts.api = stream_->getAudioApi() == oboe::AudioApi::AAudio ? 2 : 1;
  /* Did this stream get the MMAP data path, or the legacy one underneath?
   * AAudio hands back a perfectly good stream either way and never mentions
   * which, and the difference is most of the latency budget. */
  facts.mmap = oboe::OboeExtensions::isMMapUsed(stream_.get());
  /* calculateLatencyMillis() is built on the stream's TIMESTAMP, not on its
   * buffer size, so a zero here is not a fast stream - it is a stream the
   * platform will not timestamp, which in practice means the legacy path
   * rather than MMAP. Worth reporting as itself. */
  facts.timestampLatency = latency ? latency.value() / 1000.0 : 0.0;
  core_->setStreamFacts(facts);
}

void OboeOutput::retune() {
  std::lock_guard<std::mutex> guard(lock_);
  if (!stream_) return;
  /* Back to the opening bid, and let the underruns argue it up again. */
  stream_->setBufferSizeInFrames(stream_->getFramesPerBurst() * 2);
  if (tuner_) tuner_->requestReset();
  publishState();
}

void OboeOutput::stop() {
  std::lock_guard<std::mutex> guard(lock_);
  if (!stream_) return;
  /* Unpublish the tuner BEFORE close(), not after: close() is what
   * guarantees no callback is running, so the pointer has to stop being
   * readable on the near side of it. */
  tuning_.store(nullptr, std::memory_order_release);
  stream_->requestStop();
  stream_->close();
  tuner_.reset();
  stream_.reset();
  core_->setStreamState(0, 0.0, 0.0);
  core_->setStreamFacts(StreamFacts());
}

bool OboeOutput::running() const {
  std::lock_guard<std::mutex> guard(lock_);
  return stream_ && stream_->getState() == oboe::StreamState::Started;
}

oboe::DataCallbackResult OboeOutput::onAudioReady(oboe::AudioStream* stream,
                                                  void* audioData,
                                                  int32_t numFrames) {
  /* THE HOT PATH. No allocation, no locks, no logging, no JNI. Everything
   * this touches was set up before the stream opened. */
  core_->render(static_cast<float*>(audioData), numFrames);

  /* Oboe's own instruction: tune at the END of the callback, so the
   * measurement the tuner reads describes the block that just happened. */
  /* Guarded on AAudio, exactly as hello-oboe's LatencyTuningCallback does:
   * buffer tuning is unimplemented on OpenSL ES, and tune() there is a
   * failing call made several thousand times a second for nothing. */
  oboe::LatencyTuner* tuner = tuning_.load(std::memory_order_acquire);
  if (tuner != nullptr && stream->getAudioApi() == oboe::AudioApi::AAudio) {
    tuner->tune();

    /* And let the UI see the underruns. Reading the counter every callback
     * would be a call into the stream five thousand times a second for a
     * number nobody looks at more than a few times a second. */
    const int since = sinceReport_.fetch_add(1, std::memory_order_relaxed) + 1;
    if (since >= 200) {
      sinceReport_.store(0, std::memory_order_relaxed);
      auto xruns = stream->getXRunCount();
      if (xruns) core_->setStreamXRuns(xruns.value(),
                                       stream->getBufferSizeInFrames());
    }
  }
  return oboe::DataCallbackResult::Continue;
}

void OboeOutput::onErrorAfterClose(oboe::AudioStream* stream,
                                   oboe::Result error) {
  (void)stream;
  PB_LOG("the audio stream went away (%s); reopening",
         oboe::convertToText(error));
  {
    std::lock_guard<std::mutex> guard(lock_);
    stream_.reset();
  }
  /* A headset pulled out, or the exclusive port taken by something else.
   * Reopen: the pads have to keep working. */
  start();
}

}  // namespace android
}  // namespace sampler
}  // namespace pinebox
