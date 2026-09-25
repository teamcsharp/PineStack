#include "android/media_decode.h"

#include <fcntl.h>
#include <media/NdkMediaCodec.h>
#include <media/NdkMediaExtractor.h>
#include <media/NdkMediaFormat.h>
#include <unistd.h>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <vector>

namespace pinebox {
namespace sampler {
namespace android {

namespace {

/* AMediaFormat keys that are not in every NDK header revision. Spelled out
 * so the build does not depend on which platform level happened to be
 * installed. */
constexpr const char* kKeyMime = "mime";
constexpr const char* kKeySampleRate = "sample-rate";
constexpr const char* kKeyChannelCount = "channel-count";
constexpr const char* kKeyPcmEncoding = "pcm-encoding";

/* AudioFormat.ENCODING_PCM_* as MediaCodec reports them. */
constexpr int kEncodingPcm16 = 2;
constexpr int kEncodingPcmFloat = 4;

/* An fd over the bytes, with no file left on disk. */
class ScratchFd {
 public:
  ScratchFd(const std::uint8_t* data, std::size_t length,
            const std::string& dir) {
    std::string path = dir;
    if (!path.empty() && path.back() != '/') path.push_back('/');
    path += "pinebox-sampler-decode-";
    path += std::to_string(static_cast<long long>(getpid()));
    path += "-";
    path += std::to_string(reinterpret_cast<std::uintptr_t>(data));
    path += ".bin";

    fd_ = ::open(path.c_str(), O_RDWR | O_CREAT | O_TRUNC, 0600);
    if (fd_ < 0) return;
    /* Gone from the directory the moment it exists; the descriptor keeps it
     * alive until decode is done. */
    ::unlink(path.c_str());

    std::size_t written = 0;
    while (written < length) {
      const ssize_t n = ::write(fd_, data + written, length - written);
      if (n <= 0) {
        ::close(fd_);
        fd_ = -1;
        return;
      }
      written += static_cast<std::size_t>(n);
    }
    ::lseek(fd_, 0, SEEK_SET);
    size_ = length;
  }

  ~ScratchFd() {
    if (fd_ >= 0) ::close(fd_);
  }

  ScratchFd(const ScratchFd&) = delete;
  ScratchFd& operator=(const ScratchFd&) = delete;

  int fd() const { return fd_; }
  off_t size() const { return static_cast<off_t>(size_); }
  bool ok() const { return fd_ >= 0; }

 private:
  int fd_ = -1;
  std::size_t size_ = 0;
};

bool isAudio(const char* mime) {
  return mime != nullptr && std::strncmp(mime, "audio/", 6) == 0;
}

}  // namespace

DecodedPcm decodeCompressed(const std::uint8_t* data, std::size_t length,
                            const std::string& scratchDir) {
  DecodedPcm out;
  if (data == nullptr || length == 0) {
    out.error = "That sample was empty.";
    return out;
  }

  ScratchFd scratch(data, length, scratchDir);
  if (!scratch.ok()) {
    out.error = "Could not stage the sample for decoding (no scratch file).";
    return out;
  }

  AMediaExtractor* extractor = AMediaExtractor_new();
  if (extractor == nullptr) {
    out.error = "The media extractor would not start.";
    return out;
  }
  media_status_t status =
      AMediaExtractor_setDataSourceFd(extractor, scratch.fd(), 0, scratch.size());
  if (status != AMEDIA_OK) {
    AMediaExtractor_delete(extractor);
    out.error = "Nothing in this file looked like audio.";
    return out;
  }

  const size_t tracks = AMediaExtractor_getTrackCount(extractor);
  int audioTrack = -1;
  AMediaFormat* format = nullptr;
  for (size_t i = 0; i < tracks; ++i) {
    AMediaFormat* candidate = AMediaExtractor_getTrackFormat(extractor, i);
    const char* mime = nullptr;
    if (AMediaFormat_getString(candidate, kKeyMime, &mime) && isAudio(mime)) {
      audioTrack = static_cast<int>(i);
      format = candidate;
      break;
    }
    AMediaFormat_delete(candidate);
  }
  if (audioTrack < 0 || format == nullptr) {
    AMediaExtractor_delete(extractor);
    out.error = "That file has no audio track in it.";
    return out;
  }

  const char* mime = nullptr;
  AMediaFormat_getString(format, kKeyMime, &mime);
  int32_t rate = 0;
  int32_t channels = 0;
  AMediaFormat_getInt32(format, kKeySampleRate, &rate);
  AMediaFormat_getInt32(format, kKeyChannelCount, &channels);

  AMediaExtractor_selectTrack(extractor, audioTrack);
  AMediaCodec* codec = AMediaCodec_createDecoderByType(mime);
  if (codec == nullptr) {
    AMediaFormat_delete(format);
    AMediaExtractor_delete(extractor);
    out.error = std::string("This device has no decoder for ") +
                (mime ? mime : "that format") + ".";
    return out;
  }

  if (AMediaCodec_configure(codec, format, nullptr, nullptr, 0) != AMEDIA_OK ||
      AMediaCodec_start(codec) != AMEDIA_OK) {
    AMediaCodec_delete(codec);
    AMediaFormat_delete(format);
    AMediaExtractor_delete(extractor);
    out.error = "The decoder refused this file.";
    return out;
  }

  /* MediaCodec hands back 16-bit PCM on nearly everything, and float on
   * parts that support it. Read the OUTPUT format for the truth rather than
   * the input format's guess; on some MediaTek parts the two differ. */
  int32_t encoding = kEncodingPcm16;
  std::vector<float> samples;
  bool sawInputEnd = false;
  bool sawOutputEnd = false;
  /* A minute of 48 kHz stereo is a bit under six million floats; reserving
   * roughly the right order keeps this off the allocator's hot path. */
  samples.reserve(static_cast<std::size_t>(std::max(1, rate)) *
                  static_cast<std::size_t>(std::max(1, channels)) * 8);

  while (!sawOutputEnd) {
    if (!sawInputEnd) {
      const ssize_t inIndex = AMediaCodec_dequeueInputBuffer(codec, 5000);
      if (inIndex >= 0) {
        size_t capacity = 0;
        uint8_t* buffer =
            AMediaCodec_getInputBuffer(codec, static_cast<size_t>(inIndex),
                                       &capacity);
        const ssize_t read =
            buffer ? AMediaExtractor_readSampleData(extractor, buffer, capacity)
                   : -1;
        if (read <= 0) {
          AMediaCodec_queueInputBuffer(codec, static_cast<size_t>(inIndex), 0, 0,
                                       0, AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM);
          sawInputEnd = true;
        } else {
          const int64_t pts = AMediaExtractor_getSampleTime(extractor);
          AMediaCodec_queueInputBuffer(codec, static_cast<size_t>(inIndex), 0,
                                       static_cast<size_t>(read), pts, 0);
          AMediaExtractor_advance(extractor);
        }
      }
    }

    AMediaCodecBufferInfo info;
    const ssize_t outIndex = AMediaCodec_dequeueOutputBuffer(codec, &info, 5000);
    if (outIndex >= 0) {
      size_t capacity = 0;
      uint8_t* buffer =
          AMediaCodec_getOutputBuffer(codec, static_cast<size_t>(outIndex),
                                      &capacity);
      if (buffer != nullptr && info.size > 0) {
        const uint8_t* payload = buffer + info.offset;
        if (encoding == kEncodingPcmFloat) {
          const size_t count = static_cast<size_t>(info.size) / sizeof(float);
          const float* in = reinterpret_cast<const float*>(payload);
          samples.insert(samples.end(), in, in + count);
        } else {
          const size_t count = static_cast<size_t>(info.size) / sizeof(int16_t);
          const size_t before = samples.size();
          samples.resize(before + count);
          for (size_t i = 0; i < count; ++i) {
            int16_t s;
            std::memcpy(&s, payload + i * sizeof(int16_t), sizeof(int16_t));
            samples[before + i] = s / 32768.0f;
          }
        }
      }
      AMediaCodec_releaseOutputBuffer(codec, static_cast<size_t>(outIndex),
                                      false);
      if (info.flags & AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM) sawOutputEnd = true;
    } else if (outIndex == AMEDIACODEC_INFO_OUTPUT_FORMAT_CHANGED) {
      AMediaFormat* outFormat = AMediaCodec_getOutputFormat(codec);
      if (outFormat != nullptr) {
        int32_t v = 0;
        if (AMediaFormat_getInt32(outFormat, kKeySampleRate, &v) && v > 0) {
          rate = v;
        }
        if (AMediaFormat_getInt32(outFormat, kKeyChannelCount, &v) && v > 0) {
          channels = v;
        }
        if (AMediaFormat_getInt32(outFormat, kKeyPcmEncoding, &v)) encoding = v;
        AMediaFormat_delete(outFormat);
      }
    } else if (outIndex == AMEDIACODEC_INFO_TRY_AGAIN_LATER) {
      if (sawInputEnd && samples.empty()) {
        /* A decoder that has been fed everything and produced nothing is not
         * going to start now. */
        break;
      }
    }
  }

  AMediaCodec_stop(codec);
  AMediaCodec_delete(codec);
  AMediaFormat_delete(format);
  AMediaExtractor_delete(extractor);

  if (samples.empty() || rate <= 0 || channels <= 0) {
    out.error = "That file decoded to nothing.";
    return out;
  }
  out.samples = std::move(samples);
  out.rate = rate;
  out.channels = channels;
  return out;
}

SampleRef decodeToEngineBuffer(const std::uint8_t* data, std::size_t length,
                               const std::string& scratchDir,
                               std::string* error) {
  auto fail = [&](const std::string& message) -> SampleRef {
    if (error) *error = message;
    return nullptr;
  };
  if (data == nullptr || length == 0) return fail("That sample was empty.");

  const Container container = sniff(data, length);
  DecodedPcm pcm;
  if (container == Container::Wav) {
    pcm = decodeWav(data, length);
  } else if (container == Container::Unknown) {
    /* Not recognised, but MediaExtractor knows more formats than this sniff
     * does. Try it before giving up - the cost of being wrong is one failed
     * extractor call. */
    pcm = decodeCompressed(data, length, scratchDir);
  } else {
    pcm = decodeCompressed(data, length, scratchDir);
  }

  if (!pcm.ok()) {
    return fail(pcm.error.empty()
                    ? std::string("That sample would not decode.")
                    : pcm.error);
  }

  SampleRef buffer = toSampleBuffer(pcm, kEngineRate);
  if (!buffer) return fail("That sample would not convert to 48 kHz.");
  if (error) error->clear();
  return buffer;
}

}  // namespace android
}  // namespace sampler
}  // namespace pinebox
