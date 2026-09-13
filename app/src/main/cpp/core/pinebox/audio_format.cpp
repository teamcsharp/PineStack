#include "pinebox/audio_format.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "pinebox/mixer.h"

namespace pinebox {
namespace sampler {

namespace {

bool tag(const std::uint8_t* d, std::size_t len, std::size_t at,
         const char* four) {
  if (at + 4 > len) return false;
  return std::memcmp(d + at, four, 4) == 0;
}

std::uint32_t le32(const std::uint8_t* d) {
  return static_cast<std::uint32_t>(d[0]) |
         (static_cast<std::uint32_t>(d[1]) << 8) |
         (static_cast<std::uint32_t>(d[2]) << 16) |
         (static_cast<std::uint32_t>(d[3]) << 24);
}

std::uint16_t le16(const std::uint8_t* d) {
  return static_cast<std::uint16_t>(static_cast<std::uint16_t>(d[0]) |
                                    (static_cast<std::uint16_t>(d[1]) << 8));
}

}  // namespace

Container sniff(const std::uint8_t* data, std::size_t length) {
  if (data == nullptr || length < 4) return Container::Unknown;
  if (tag(data, length, 0, "RIFF") && tag(data, length, 8, "WAVE")) {
    return Container::Wav;
  }
  if (tag(data, length, 0, "OggS")) return Container::Ogg;
  if (tag(data, length, 0, "fLaC")) return Container::Flac;
  if (tag(data, length, 4, "ftyp")) return Container::Mp4;
  if (length >= 3 && data[0] == 'I' && data[1] == 'D' && data[2] == '3') {
    return Container::Mp3;
  }
  /* A bare mp3 with no ID3 header: eleven bits of frame sync. The station's
   * /api/booth/clip has served both. */
  if (length >= 2 && data[0] == 0xFF && (data[1] & 0xE0) == 0xE0) {
    return Container::Mp3;
  }
  return Container::Unknown;
}

const char* containerName(Container container) {
  switch (container) {
    case Container::Wav: return "wav";
    case Container::Mp3: return "mp3";
    case Container::Ogg: return "ogg";
    case Container::Flac: return "flac";
    case Container::Mp4: return "mp4";
    default: return "unknown";
  }
}

DecodedPcm decodeWav(const std::uint8_t* data, std::size_t length) {
  DecodedPcm out;
  if (data == nullptr || length < 44 || !tag(data, length, 0, "RIFF") ||
      !tag(data, length, 8, "WAVE")) {
    out.error = "That is not a WAV file.";
    return out;
  }

  int format = 0;         /* 1 PCM, 3 IEEE float, 0xFFFE extensible */
  int channels = 0;
  int rate = 0;
  int bits = 0;
  const std::uint8_t* audio = nullptr;
  std::size_t audioBytes = 0;

  std::size_t at = 12;
  while (at + 8 <= length) {
    const std::size_t size = le32(data + at + 4);
    const std::size_t body = at + 8;
    if (tag(data, length, at, "fmt ") && body + 16 <= length) {
      format = le16(data + body);
      channels = le16(data + body + 2);
      rate = static_cast<int>(le32(data + body + 4));
      bits = le16(data + body + 14);
      if (format == 0xFFFE && body + 26 <= length) {
        /* WAVE_FORMAT_EXTENSIBLE: the real format is the first two bytes of
         * the sub-format GUID. Anything Audacity writes above 16 bits is
         * this shape. */
        format = le16(data + body + 24);
      }
    } else if (tag(data, length, at, "data")) {
      audio = data + body;
      audioBytes = std::min<std::size_t>(size, length - std::min(body, length));
    }
    /* RIFF chunks are word aligned; an odd size carries a pad byte. */
    at = body + size + (size & 1u);
    if (size == 0) break;
  }

  if (channels <= 0 || rate <= 0 || audio == nullptr || audioBytes == 0) {
    out.error = "That WAV had no usable audio in it.";
    return out;
  }

  const int bytesPerSample = bits / 8;
  if (bytesPerSample <= 0) {
    out.error = "That WAV declares no sample width.";
    return out;
  }
  const std::size_t total = audioBytes / bytesPerSample;
  out.samples.resize(total);
  out.channels = channels;
  out.rate = rate;

  for (std::size_t i = 0; i < total; ++i) {
    const std::uint8_t* p = audio + i * bytesPerSample;
    float v = 0.0f;
    if (format == 3 && bits == 32) {
      float f;
      std::memcpy(&f, p, 4);
      v = f;
    } else if (bits == 8) {
      /* 8-bit wav is UNSIGNED, unlike every other width. */
      v = (static_cast<int>(p[0]) - 128) / 128.0f;
    } else if (bits == 16) {
      const std::int16_t s = static_cast<std::int16_t>(le16(p));
      v = s / 32768.0f;
    } else if (bits == 24) {
      std::int32_t s = (static_cast<std::int32_t>(p[0])) |
                       (static_cast<std::int32_t>(p[1]) << 8) |
                       (static_cast<std::int32_t>(p[2]) << 16);
      if (s & 0x800000) s |= ~0xFFFFFF;   /* sign extend */
      v = static_cast<float>(s) / 8388608.0f;
    } else if (bits == 32) {
      const std::int32_t s = static_cast<std::int32_t>(le32(p));
      v = static_cast<float>(s) / 2147483648.0f;
    } else {
      out.samples.clear();
      out.error = "That WAV is " + std::to_string(bits) +
                  " bit, which this build cannot read.";
      return out;
    }
    out.samples[i] = v;
  }

  /* A data chunk that did not divide evenly by the frame size leaves a
   * partial frame on the end; drop it rather than smear the channels. */
  const std::size_t whole = (out.samples.size() / channels) * channels;
  out.samples.resize(whole);
  return out;
}

namespace {

/* A single second-order Butterworth section, run forwards over one channel.
 * Only used when a file arrives at a HIGHER rate than the engine, which on
 * this station means "somebody dropped a studio file on a pad". */
void lowpass(std::vector<float>* samples, int channels, int channel, double rate,
             double cutoff) {
  if (cutoff <= 0.0 || cutoff >= rate * 0.5) return;
  const double w = std::tan(3.14159265358979323846 * cutoff / rate);
  const double k = 1.41421356237309504880;   /* sqrt(2), Butterworth Q */
  const double norm = 1.0 / (1.0 + k * w + w * w);
  const double b0 = w * w * norm;
  const double b1 = 2.0 * b0;
  const double b2 = b0;
  const double a1 = 2.0 * (w * w - 1.0) * norm;
  const double a2 = (1.0 - k * w + w * w) * norm;

  double x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  const std::size_t frames = samples->size() / channels;
  for (std::size_t f = 0; f < frames; ++f) {
    const std::size_t i = f * channels + channel;
    const double x0 = (*samples)[i];
    const double y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1; x1 = x0;
    y2 = y1; y1 = y0;
    (*samples)[i] = static_cast<float>(y0);
  }
}

float readAt(const std::vector<float>& samples, int channels, int frames,
             double position, int channel) {
  if (frames <= 0) return 0.0f;
  double p = position;
  if (p < 0.0) p = 0.0;
  if (p > static_cast<double>(frames - 1)) p = static_cast<double>(frames - 1);
  const int i = static_cast<int>(p);
  const float t = static_cast<float>(p - i);
  auto pick = [&](int f) -> float {
    if (f < 0) f = 0;
    if (f >= frames) f = frames - 1;
    return samples[static_cast<std::size_t>(f) * channels + channel];
  };
  return hermite4(pick(i - 1), pick(i), pick(i + 1), pick(i + 2), t);
}

}  // namespace

DecodedPcm resample(const DecodedPcm& in, int targetRate) {
  DecodedPcm out;
  if (!in.ok() || targetRate <= 0) {
    out.error = in.error.empty() ? "Nothing to resample." : in.error;
    return out;
  }
  if (in.rate == targetRate) return in;

  DecodedPcm work = in;
  if (in.rate > targetRate) {
    /* Downsampling: filter before decimating or the top end folds back over
     * the material as a whistle that no amount of trimming removes. */
    const double cutoff = targetRate * 0.45;
    for (int c = 0; c < work.channels; ++c) {
      lowpass(&work.samples, work.channels, c, work.rate, cutoff);
    }
  }

  const int channels = work.channels;
  const int inFrames = work.frames();
  const double ratio = static_cast<double>(work.rate) / targetRate;
  const int outFrames = static_cast<int>(
      std::llround(static_cast<double>(inFrames) / ratio));

  out.channels = channels;
  out.rate = targetRate;
  out.samples.assign(static_cast<std::size_t>(outFrames) * channels, 0.0f);
  for (int f = 0; f < outFrames; ++f) {
    const double source = f * ratio;
    for (int c = 0; c < channels; ++c) {
      out.samples[static_cast<std::size_t>(f) * channels + c] =
          readAt(work.samples, channels, inFrames, source, c);
    }
  }
  return out;
}

SampleRef toSampleBuffer(const DecodedPcm& pcm, int targetRate) {
  if (!pcm.ok()) return nullptr;
  if (pcm.rate == targetRate) {
    return std::make_shared<const SampleBuffer>(pcm.samples, pcm.channels,
                                                targetRate);
  }
  DecodedPcm converted = resample(pcm, targetRate);
  if (!converted.ok()) return nullptr;
  return std::make_shared<const SampleBuffer>(std::move(converted.samples),
                                              converted.channels, targetRate);
}

}  // namespace sampler
}  // namespace pinebox
