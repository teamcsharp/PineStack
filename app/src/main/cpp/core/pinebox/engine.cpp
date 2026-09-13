#include "pinebox/engine.h"

#include <algorithm>
#include <cstdlib>
#include <set>

namespace pinebox {
namespace sampler {

namespace {

std::string makeVoiceId(std::uint64_t seq) {
  return "v" + std::to_string(seq);
}

/* "v41" -> 41. Anything else -> 0, which matches no live voice, so a stale id
 * from a UI that lost track is a no-op rather than a wrong note cut. */
std::uint64_t parseVoiceId(const std::string& id) {
  if (id.size() < 2 || id[0] != 'v') return 0;
  std::uint64_t out = 0;
  for (size_t i = 1; i < id.size(); ++i) {
    const char c = id[i];
    if (c < '0' || c > '9') return 0;
    out = out * 10 + static_cast<std::uint64_t>(c - '0');
  }
  return out;
}

}  // namespace

SamplerCore::SamplerCore(int engineRate, int outChannels)
    : engineRate_(engineRate > 0 ? engineRate : kEngineRate),
      outChannels_(outChannels > 0 ? outChannels : kEngineChannels),
      duck_(engineRate > 0 ? engineRate : kEngineRate) {}

/* ---- pads ------------------------------------------------------------- */

Pad& SamplerCore::padRecord(const std::string& padId) {
  auto it = pads_.find(padId);
  if (it != pads_.end()) return it->second;
  Pad pad;
  pad.id = padId;
  return pads_.emplace(padId, std::move(pad)).first->second;
}

const Pad* SamplerCore::findPad(const std::string& padId) const {
  auto it = pads_.find(padId);
  return it == pads_.end() ? nullptr : &it->second;
}

LoadResult SamplerCore::load(const std::string& padId, SampleRef buffer) {
  LoadResult result;
  if (!buffer) return result;
  std::lock_guard<std::mutex> lock(control_);
  Pad& pad = padRecord(padId);
  pad.buffer = std::move(buffer);
  /* The mirrored copy belonged to whatever used to be on this pad. */
  pad.reversed = nullptr;
  result.seconds = pad.buffer->seconds();
  result.rate = pad.buffer->rate();
  result.channels = pad.buffer->channels();
  return result;
}

bool SamplerCore::copy(const std::string& fromPadId,
                       const std::string& toPadId) {
  std::lock_guard<std::mutex> lock(control_);
  auto it = pads_.find(fromPadId);
  if (it == pads_.end() || !it->second.buffer) return false;
  const Pad& from = it->second;
  Pad& to = padRecord(toPadId);
  /* The SHARED reference, not a copy of the audio. This is the whole reason
   * a sixteen-way chop of a sixty second line costs twelve megabytes rather
   * than a quarter of a gigabyte. */
  to.buffer = from.buffer;
  to.reversed = (from.settings.reverse == to.settings.reverse) ? from.reversed
                                                               : nullptr;
  return true;
}

bool SamplerCore::unload(const std::string& padId) {
  {
    std::lock_guard<std::mutex> lock(control_);
    if (pads_.find(padId) == pads_.end()) return false;
  }
  stopPad(padId);
  std::lock_guard<std::mutex> lock(control_);
  auto it = pads_.find(padId);
  if (it == pads_.end()) return false;
  it->second.buffer = nullptr;
  it->second.reversed = nullptr;
  return true;
}

bool SamplerCore::clear() {
  stopAll();
  std::lock_guard<std::mutex> lock(control_);
  /* The pads let go here, but any voice still ringing holds its own
   * shared_ptr, so nothing is freed underneath the audio thread. */
  pads_.clear();
  return true;
}

bool SamplerCore::loaded(const std::string& padId) const {
  std::lock_guard<std::mutex> lock(control_);
  const Pad* pad = findPad(padId);
  return pad != nullptr && pad->loaded();
}

double SamplerCore::seconds(const std::string& padId) const {
  std::lock_guard<std::mutex> lock(control_);
  const Pad* pad = findPad(padId);
  return pad ? pad->seconds() : 0.0;
}

std::vector<float> SamplerCore::peaks(const std::string& padId,
                                      int buckets) const {
  SampleRef buffer;
  {
    std::lock_guard<std::mutex> lock(control_);
    const Pad* pad = findPad(padId);
    if (!pad || !pad->buffer) return {};
    buffer = pad->buffer;
  }
  /* Out of the lock: scanning three million samples for a waveform view must
   * not hold up the next press. */
  return sampler::peaks(*buffer, buckets);
}

double SamplerCore::zeroCross(const std::string& padId, double seconds,
                              double withinMs) const {
  SampleRef buffer;
  {
    std::lock_guard<std::mutex> lock(control_);
    const Pad* pad = findPad(padId);
    if (!pad || !pad->buffer) return seconds;
    buffer = pad->buffer;
  }
  return sampler::zeroCross(*buffer, seconds, withinMs);
}

void SamplerCore::set(const std::string& padId, const PadPatch& patch) {
  std::lock_guard<std::mutex> lock(control_);
  applyPatch(&padRecord(padId), patch);
}

bool SamplerCore::get(const std::string& padId, PadSettings* out,
                      double* seconds) const {
  std::lock_guard<std::mutex> lock(control_);
  const Pad* pad = findPad(padId);
  if (!pad) return false;
  if (out) *out = pad->settings;
  if (seconds) *seconds = pad->seconds();
  return true;
}

void SamplerCore::setPolyphonic(bool on) {
  std::lock_guard<std::mutex> lock(control_);
  polyphonic_ = on;
}

bool SamplerCore::isPolyphonic() const {
  std::lock_guard<std::mutex> lock(control_);
  return polyphonic_;
}

/* ---- voices ------------------------------------------------------------ */

void SamplerCore::reap() {
  for (int i = 0; i < kMaxVoices; ++i) {
    if (rt_[i].state.load(std::memory_order_acquire) !=
        static_cast<int>(VoiceState::Finished)) {
      continue;
    }
    /* HERE, on the control thread, is the only place decoded audio is ever
     * released. The audio thread has stopped touching this slot. */
    ids_.erase(meta_[i].voiceId);
    meta_[i].keepAlive = nullptr;
    meta_[i].padId.clear();
    meta_[i].choke.clear();
    meta_[i].voiceId = 0;
    meta_[i].inUse = false;
    rt_[i].buffer = nullptr;
    rt_[i].releaseRequested.store(false, std::memory_order_relaxed);
    rt_[i].state.store(static_cast<int>(VoiceState::Free),
                       std::memory_order_release);
  }
}

int SamplerCore::claimSlot() {
  reap();
  for (int i = 0; i < kMaxVoices; ++i) {
    if (rt_[i].state.load(std::memory_order_acquire) ==
        static_cast<int>(VoiceState::Free)) {
      /* Arming is invisible to the audio thread, so the slot can be filled
       * in at leisure before it is published. */
      rt_[i].state.store(static_cast<int>(VoiceState::Arming),
                         std::memory_order_relaxed);
      return i;
    }
  }

  /* Thirty-two voices at once is two hands on a Note Repeat run. Rather than
   * cut something mid-note to make room - which needs the audio thread's
   * agreement and would click - the oldest voice is told to fade, so the
   * NEXT press has a slot. This press is dropped. */
  int oldest = -1;
  std::uint64_t oldestSerial = 0;
  for (int i = 0; i < kMaxVoices; ++i) {
    if (rt_[i].state.load(std::memory_order_acquire) !=
        static_cast<int>(VoiceState::Active)) {
      continue;
    }
    if (oldest < 0 || rt_[i].serial < oldestSerial) {
      oldest = i;
      oldestSerial = rt_[i].serial;
    }
  }
  if (oldest >= 0) requestRelease(&rt_[oldest]);
  return -1;
}

void SamplerCore::cutSiblings(const Pad& firing, int exceptSlot) {
  for (int i = 0; i < kMaxVoices; ++i) {
    if (i == exceptSlot || !meta_[i].inUse) continue;
    if (rt_[i].state.load(std::memory_order_acquire) !=
        static_cast<int>(VoiceState::Active)) {
      continue;
    }
    if (shouldCut(firing.id, firing.settings.choke, meta_[i].padId,
                  meta_[i].choke, polyphonic_)) {
      requestRelease(&rt_[i]);
    }
  }
}

std::string SamplerCore::fire(const std::string& padId,
                              const FireOptions& options) {
  SampleRef playing;
  VoicePlan plan;
  int slot = -1;
  std::uint64_t voiceId = 0;
  std::string chokeGroup;

  {
    std::lock_guard<std::mutex> lock(control_);
    auto it = pads_.find(padId);
    if (it == pads_.end() || !it->second.buffer) return std::string();
    Pad& pad = it->second;

    if (pad.settings.reverse && !pad.reversed) {
      /* Built on the first reversed press, not on load. It is a straight
       * memcpy of the decoded audio - twelve megabytes for a booth line -
       * and it happens on the calling thread, so the first press of a
       * reversed long sample is measurably slower than the second. The
       * alternative is holding that copy for every pad nobody reverses. */
      pad.reversed = reversedCopy(pad.buffer);
    }
    playing = pad.settings.reverse ? pad.reversed : pad.buffer;
    if (!playing) return std::string();

    plan = planFire(pad.settings, options, playing->seconds());

    slot = claimSlot();
    if (slot < 0) return std::string();

    /* Cut before publishing: the new slot is still Arming, so it cannot cut
     * itself, and no ordering trick is needed to exclude it. */
    cutSiblings(pad, slot);

    voiceId = ++voiceSeq_;
    chokeGroup = pad.settings.choke;

    meta_[slot].padId = pad.id;
    meta_[slot].choke = chokeGroup;
    meta_[slot].keepAlive = playing;   /* holds the audio up under the mixer */
    meta_[slot].voiceId = voiceId;
    meta_[slot].inUse = true;
    ids_[voiceId] = slot;

    armVoice(&rt_[slot], playing.get(), plan, engineRate_, voiceId);
    /* THE FIRE-TO-SOUND STAMP, taken as late as possible inside the press so
     * that everything this function does is on the near side of it. The
     * audio thread reads it in the first block that gives this voice a
     * sample; see timeStarts(). */
    rt_[slot].firedNanos.store(monotonicNanos(), std::memory_order_relaxed);
    /* Release ordering: everything above is visible to the audio thread the
     * moment it sees Active. */
    rt_[slot].state.store(static_cast<int>(VoiceState::Active),
                          std::memory_order_release);
  }

  return makeVoiceId(voiceId);
}

void SamplerCore::release(const std::string& voiceId) {
  const std::uint64_t id = parseVoiceId(voiceId);
  if (id == 0) return;
  std::lock_guard<std::mutex> lock(control_);
  auto it = ids_.find(id);
  if (it == ids_.end()) return;
  const int slot = it->second;
  if (slot < 0 || slot >= kMaxVoices) return;
  if (meta_[slot].voiceId != id) return;
  requestRelease(&rt_[slot]);
}

void SamplerCore::stopPad(const std::string& padId) {
  std::lock_guard<std::mutex> lock(control_);
  for (int i = 0; i < kMaxVoices; ++i) {
    if (!meta_[i].inUse || meta_[i].padId != padId) continue;
    requestRelease(&rt_[i]);
  }
}

void SamplerCore::stopAll() {
  std::lock_guard<std::mutex> lock(control_);
  for (int i = 0; i < kMaxVoices; ++i) {
    if (!meta_[i].inUse) continue;
    requestRelease(&rt_[i]);
  }
}

/* ---- metering ---------------------------------------------------------- */

Footprint SamplerCore::footprint() const {
  std::lock_guard<std::mutex> lock(control_);
  std::set<const SampleBuffer*> seen;
  Footprint out;
  for (const auto& entry : pads_) {
    const Pad& pad = entry.second;
    if (!pad.buffer) continue;
    out.pads += 1;
    if (seen.count(pad.buffer.get())) continue;
    seen.insert(pad.buffer.get());
    out.bytes += pad.buffer->bytes();
    if (pad.reversed && !seen.count(pad.reversed.get())) {
      seen.insert(pad.reversed.get());
      out.bytes += pad.reversed->bytes();
    }
  }
  out.buffers = static_cast<int>(seen.size());
  return out;
}

Levels SamplerCore::levels() {
  std::lock_guard<std::mutex> lock(control_);
  reap();
  Levels out;
  for (int i = 0; i < kMaxVoices; ++i) {
    if (!meta_[i].inUse) continue;
    const int state = rt_[i].state.load(std::memory_order_acquire);
    if (state != static_cast<int>(VoiceState::Active) &&
        state != static_cast<int>(VoiceState::Arming)) {
      continue;
    }
    out.voices += 1;
    out.perPad[meta_[i].padId] += 1;
  }
  out.state = streamState_.load(std::memory_order_relaxed);
  out.baseLatency = baseLatency_.load(std::memory_order_relaxed);
  out.outputLatency = outputLatency_.load(std::memory_order_relaxed);

  out.stream.burstFrames = burstFrames_.load(std::memory_order_relaxed);
  out.stream.bufferFrames = bufferFrames_.load(std::memory_order_relaxed);
  out.stream.capacityFrames = capacityFrames_.load(std::memory_order_relaxed);
  out.stream.xruns = xruns_.load(std::memory_order_relaxed);
  out.stream.exclusive = exclusive_.load(std::memory_order_relaxed);
  out.stream.mmap = mmap_.load(std::memory_order_relaxed);
  out.stream.api = api_.load(std::memory_order_relaxed);
  out.stream.timestampLatency =
      timestampLatency_.load(std::memory_order_relaxed);

  out.start.lastMs = startLastMs_.load(std::memory_order_relaxed);
  out.start.worstMs = startWorstMs_.load(std::memory_order_relaxed);
  out.start.count = startCount_.load(std::memory_order_relaxed);
  out.start.totalMs = startTotalMs_.load(std::memory_order_relaxed);
  return out;
}

int SamplerCore::activeVoices() { return levels().voices; }

int SamplerCore::releasingVoices() {
  std::lock_guard<std::mutex> lock(control_);
  int count = 0;
  for (int i = 0; i < kMaxVoices; ++i) {
    if (!meta_[i].inUse) continue;
    const int state = rt_[i].state.load(std::memory_order_acquire);
    if (state != static_cast<int>(VoiceState::Active)) continue;
    if (rt_[i].releaseRequested.load(std::memory_order_relaxed)) count += 1;
  }
  return count;
}

void SamplerCore::setStreamState(int state, double baseLatency,
                                 double outputLatency) {
  streamState_.store(state, std::memory_order_relaxed);
  baseLatency_.store(baseLatency, std::memory_order_relaxed);
  outputLatency_.store(outputLatency, std::memory_order_relaxed);
}

void SamplerCore::setStreamFacts(const StreamFacts& facts) {
  burstFrames_.store(facts.burstFrames, std::memory_order_relaxed);
  bufferFrames_.store(facts.bufferFrames, std::memory_order_relaxed);
  capacityFrames_.store(facts.capacityFrames, std::memory_order_relaxed);
  xruns_.store(facts.xruns, std::memory_order_relaxed);
  exclusive_.store(facts.exclusive, std::memory_order_relaxed);
  mmap_.store(facts.mmap, std::memory_order_relaxed);
  api_.store(facts.api, std::memory_order_relaxed);
  timestampLatency_.store(facts.timestampLatency, std::memory_order_relaxed);
}

void SamplerCore::setStreamXRuns(int xruns, int bufferFrames) {
  xruns_.store(xruns, std::memory_order_relaxed);
  if (bufferFrames > 0) {
    bufferFrames_.store(bufferFrames, std::memory_order_relaxed);
  }
}

void SamplerCore::resetStartLatency() {
  startLastMs_.store(0.0, std::memory_order_relaxed);
  startWorstMs_.store(0.0, std::memory_order_relaxed);
  startCount_.store(0, std::memory_order_relaxed);
  startTotalMs_.store(0.0, std::memory_order_relaxed);
}

/* THE AUDIO THREAD. No allocation, no lock, no logging.
 *
 * The clock is read at most ONCE per block and only when a voice actually
 * started in it, so a block with nothing new in it pays for a scan of
 * thirty-two atomic loads and nothing else. A voice whose stamp is still
 * set but whose envelope has already moved is one this pass missed - it is
 * dropped rather than reported late, because a reading that is quietly
 * wrong is worse than no reading. */
void SamplerCore::timeStarts() {
  std::uint64_t now = 0;
  for (int i = 0; i < kMaxVoices; ++i) {
    VoiceRT& voice = rt_[i];
    if (voice.state.load(std::memory_order_acquire) !=
        static_cast<int>(VoiceState::Active)) {
      continue;
    }
    const std::uint64_t fired =
        voice.firedNanos.load(std::memory_order_relaxed);
    if (fired == 0) continue;
    voice.firedNanos.store(0, std::memory_order_relaxed);
    /* env is still exactly zero only in the block before the first sample.
     * Anything else means the slot was recycled between the store above and
     * this read; there is no honest number in it. */
    if (voice.env != 0.0f) continue;
    if (now == 0) now = monotonicNanos();
    if (now <= fired) continue;
    const double ms = static_cast<double>(now - fired) / 1.0e6;
    startLastMs_.store(ms, std::memory_order_relaxed);
    if (ms > startWorstMs_.load(std::memory_order_relaxed)) {
      startWorstMs_.store(ms, std::memory_order_relaxed);
    }
    startTotalMs_.store(startTotalMs_.load(std::memory_order_relaxed) + ms,
                        std::memory_order_relaxed);
    startCount_.store(startCount_.load(std::memory_order_relaxed) + 1,
                      std::memory_order_relaxed);
  }
}

void SamplerCore::setDuckDepth(float depth) { duck_.setDepth(depth); }

/* ---- the callback ------------------------------------------------------ */

void SamplerCore::render(float* out, int frames) {
  if (out == nullptr || frames <= 0) return;
  /* BEFORE the mixer, because "the first block in which this voice sounds"
   * is only identifiable while its envelope is still at zero. */
  timeStarts();
  const int ringing =
      renderBlock(rt_, kMaxVoices, out, frames, outChannels_, engineRate_);
  ringing_.store(ringing, std::memory_order_relaxed);
  duckGain_.store(duck_.advance(ringing, frames), std::memory_order_relaxed);
}

}  // namespace sampler
}  // namespace pinebox
