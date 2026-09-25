/* pinebox/audio_format.h - sniffing, WAV, and getting to 48 kHz.
 *
 * SNIFF, DO NOT ASSUME. The station serves a booth clip as mono 24 kHz mp3
 * OR as wav depending on which route answered and what the operator asked
 * for, and the Content-Type has been wrong before. The first twelve bytes
 * are never wrong.
 *
 * WAV is parsed here rather than handed to MediaCodec because it is thirty
 * lines, it avoids spinning up a codec for a format that is already PCM, and
 * it means the resampler - the part that actually decides what the sample
 * sounds like - can be tested on a build machine with no NDK anywhere near
 * it.
 */
#ifndef PINEBOX_AUDIO_FORMAT_H
#define PINEBOX_AUDIO_FORMAT_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "pinebox/config.h"
#include "pinebox/sample_buffer.h"

namespace pinebox {
namespace sampler {

enum class Container {
  Unknown = 0,
  Wav,      /* RIFF/WAVE - parsed here */
  Mp3,      /* ID3 or a frame sync    */
  Ogg,      /* OggS: vorbis or opus   */
  Flac,     /* fLaC                   */
  Mp4       /* ....ftyp: m4a, aac     */
};

Container sniff(const std::uint8_t* data, std::size_t length);
const char* containerName(Container container);

/* Decoded PCM before it has been resampled: interleaved float, at whatever
 * rate the file was written at. */
struct DecodedPcm {
  std::vector<float> samples;
  int channels = 0;
  int rate = 0;
  std::string error;   /* empty on success */

  bool ok() const { return error.empty() && channels > 0 && rate > 0; }
  int frames() const {
    return channels > 0 ? static_cast<int>(samples.size() / channels) : 0;
  }
};

/* RIFF/WAVE. Handles the four things that actually turn up: 8-bit unsigned,
 * 16-bit signed, 24-bit signed packed, 32-bit signed, and 32-bit float, in
 * both plain PCM and WAVE_FORMAT_EXTENSIBLE. Chunks it does not know are
 * skipped rather than fatal - a wav with a LIST/INFO block in it is still a
 * wav. */
DecodedPcm decodeWav(const std::uint8_t* data, std::size_t length);

/* To the engine rate, keeping the channel count. Four point Hermite, with a
 * lowpass first when the source rate is HIGHER than the target - upsampling
 * 24 kHz to 48 kHz (which is what this station actually does) needs no
 * filter, but a 96 kHz file dropped on a pad would alias without one. */
DecodedPcm resample(const DecodedPcm& in, int targetRate);

/* PCM to the resident buffer the engine holds. Resamples if it has to. */
SampleRef toSampleBuffer(const DecodedPcm& pcm, int targetRate = kEngineRate);

}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_AUDIO_FORMAT_H */
