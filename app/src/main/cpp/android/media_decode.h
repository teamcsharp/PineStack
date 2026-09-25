/* android/media_decode.h - mp3, ogg, m4a and flac, through the NDK.
 *
 * WAV never gets here: audio_format.cpp reads it directly, because spinning
 * up a MediaCodec for material that is already PCM costs tens of
 * milliseconds and a hardware decoder session for nothing.
 *
 * Everything else goes through AMediaExtractor + AMediaCodec, which needs a
 * file descriptor rather than a pointer. The bytes arrive in memory (out of
 * IndexedDB, or straight off /api/booth/clip), so they are written to a
 * scratch file which is UNLINKED immediately - the fd stays valid, and a
 * crash mid-decode leaves nothing behind on a tablet that lives in a rack.
 */
#ifndef PINEBOX_MEDIA_DECODE_H
#define PINEBOX_MEDIA_DECODE_H

#include <cstddef>
#include <cstdint>
#include <string>

#include "pinebox/audio_format.h"

namespace pinebox {
namespace sampler {
namespace android {

/* Decode to interleaved float at the file's own rate. `scratchDir` is the
 * app's cacheDir; it is only touched for the codec path. */
DecodedPcm decodeCompressed(const std::uint8_t* data, std::size_t length,
                            const std::string& scratchDir);

/* The one entry point the JNI layer calls: sniff, decode by whichever route
 * fits, resample to the engine rate, hand back a resident buffer. */
SampleRef decodeToEngineBuffer(const std::uint8_t* data, std::size_t length,
                               const std::string& scratchDir,
                               std::string* error);

}  // namespace android
}  // namespace sampler
}  // namespace pinebox

#endif  /* PINEBOX_MEDIA_DECODE_H */
