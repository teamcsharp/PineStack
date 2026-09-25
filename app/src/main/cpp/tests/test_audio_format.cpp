/* Sniffing, WAV, and getting to 48 kHz.
 *
 * The station serves a booth clip as mono 24 kHz mp3 OR as wav, and the
 * Content-Type header has been wrong before now. Nothing in this file guesses
 * from a file name or a header; it reads the first twelve bytes, which are
 * never wrong.
 *
 * There is no JavaScript counterpart to these cases: on the desktop,
 * decodeAudioData does all of it inside the browser. On the tablet it is our
 * code, so it needs its own tests - and the resampler in particular decides
 * what every sample on the instrument actually sounds like.
 */
#define PB_TEST_MAIN
#include "test_support.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <vector>

#include "pinebox/audio_format.h"

using namespace pinebox::sampler;

namespace {

void put32(std::vector<std::uint8_t>* out, std::uint32_t v) {
  out->push_back(static_cast<std::uint8_t>(v & 0xFF));
  out->push_back(static_cast<std::uint8_t>((v >> 8) & 0xFF));
  out->push_back(static_cast<std::uint8_t>((v >> 16) & 0xFF));
  out->push_back(static_cast<std::uint8_t>((v >> 24) & 0xFF));
}

void put16(std::vector<std::uint8_t>* out, std::uint16_t v) {
  out->push_back(static_cast<std::uint8_t>(v & 0xFF));
  out->push_back(static_cast<std::uint8_t>((v >> 8) & 0xFF));
}

void putTag(std::vector<std::uint8_t>* out, const char* four) {
  for (int i = 0; i < 4; ++i) {
    out->push_back(static_cast<std::uint8_t>(four[i]));
  }
}

/* A 16-bit PCM wav, optionally with a junk chunk in front of the data so the
 * chunk walker is actually exercised rather than assumed. */
std::vector<std::uint8_t> makeWav(const std::vector<float>& samples,
                                  int channels, int rate, bool withJunk) {
  std::vector<std::uint8_t> body;
  putTag(&body, "fmt ");
  put32(&body, 16);
  put16(&body, 1);                       /* PCM */
  put16(&body, static_cast<std::uint16_t>(channels));
  put32(&body, static_cast<std::uint32_t>(rate));
  put32(&body, static_cast<std::uint32_t>(rate * channels * 2));
  put16(&body, static_cast<std::uint16_t>(channels * 2));
  put16(&body, 16);

  if (withJunk) {
    /* A LIST/INFO block is what a real editor leaves behind, and skipping it
     * is the difference between a sample and a burst of noise. */
    putTag(&body, "LIST");
    put32(&body, 10);
    for (int i = 0; i < 10; ++i) body.push_back(0x7F);
  }

  putTag(&body, "data");
  put32(&body, static_cast<std::uint32_t>(samples.size() * 2));
  for (float v : samples) {
    /* 32768, not 32767, and then clamped.
     *
     * The decoder divides by 32768 (audio_format.cpp), which is what every
     * mainstream decoder does: it is the only scale on which -32768 maps to
     * exactly -1.0. Encoding here at 32767 and decoding there at 32768 is a
     * scale mismatch of one part in 32768, which near full scale is a whole
     * LSB of error BEFORE any rounding - and that is what used to push this
     * case past its own one-LSB tolerance. The test was reporting the
     * disagreement between the fixture and the decoder, not a fault in the
     * decoder. Encode the way it decodes and what is left is rounding. */
    const int s = static_cast<int>(std::lround(v * 32768.0f));
    const int clamped = s > 32767 ? 32767 : (s < -32768 ? -32768 : s);
    put16(&body, static_cast<std::uint16_t>(static_cast<std::int16_t>(clamped)));
  }

  std::vector<std::uint8_t> file;
  putTag(&file, "RIFF");
  put32(&file, static_cast<std::uint32_t>(body.size() + 4));
  putTag(&file, "WAVE");
  file.insert(file.end(), body.begin(), body.end());
  return file;
}

std::vector<float> sine(int frames, double hz, int rate) {
  std::vector<float> out(static_cast<size_t>(frames));
  for (int f = 0; f < frames; ++f) {
    out[static_cast<size_t>(f)] = static_cast<float>(
        std::sin(2.0 * 3.14159265358979323846 * hz * f / rate));
  }
  return out;
}

}  // namespace

PB_TEST(sniff_reads_the_bytes_not_the_header) {
  const std::vector<std::uint8_t> wav = makeWav(sine(100, 100.0, 24000), 1,
                                                24000, false);
  PB_EQ(sniff(wav.data(), wav.size()), Container::Wav);

  const std::uint8_t id3[] = {'I', 'D', '3', 3, 0, 0, 0, 0};
  PB_EQ(sniff(id3, sizeof(id3)), Container::Mp3);

  /* A bare mp3 with no ID3 tag: eleven bits of frame sync. The station's
   * /api/booth/clip has served both shapes. */
  const std::uint8_t bare[] = {0xFF, 0xFB, 0x90, 0x00};
  PB_EQ(sniff(bare, sizeof(bare)), Container::Mp3);

  const std::uint8_t ogg[] = {'O', 'g', 'g', 'S', 0, 2, 0, 0};
  PB_EQ(sniff(ogg, sizeof(ogg)), Container::Ogg);

  const std::uint8_t flac[] = {'f', 'L', 'a', 'C', 0, 0, 0, 34};
  PB_EQ(sniff(flac, sizeof(flac)), Container::Flac);

  const std::uint8_t m4a[] = {0, 0, 0, 32, 'f', 't', 'y', 'p', 'M', '4', 'A', ' '};
  PB_EQ(sniff(m4a, sizeof(m4a)), Container::Mp4);

  const std::uint8_t nonsense[] = {'h', 'e', 'l', 'l', 'o', '!', '!', '!'};
  PB_EQ(sniff(nonsense, sizeof(nonsense)), Container::Unknown);
  PB_EQ(sniff(nullptr, 0), Container::Unknown);
}

PB_TEST(a_wav_decodes_to_what_went_in) {
  std::vector<float> material = sine(2400, 100.0, 24000);
  const std::vector<std::uint8_t> file = makeWav(material, 1, 24000, false);
  const DecodedPcm pcm = decodeWav(file.data(), file.size());
  PB_CHECK_MSG(pcm.ok(), pcm.error);
  PB_EQ(pcm.channels, 1);
  PB_EQ(pcm.rate, 24000);
  PB_EQ(pcm.frames(), 2400);

  double worst = 0.0;
  for (size_t i = 0; i < material.size(); ++i) {
    /* The samples are float and `worst` is double, so std::max cannot
     * deduce one type for both. Widen the difference rather than narrow
     * the accumulator: the tolerance below is one 16-bit LSB and is worth
     * comparing at double precision. */
    const double error = std::fabs(static_cast<double>(pcm.samples[i]) -
                                   static_cast<double>(material[i]));
    worst = std::max(worst, error);
  }
  /* stdout, not stderr: this is a reading, not a failure, and Windows
   * PowerShell turns a native process's stderr into an error record that
   * fails the whole runner even when the exit code is zero. */
  std::printf("    [wav round trip] worst = %.9f (%.3f LSB)\n",
               worst, worst * 32768.0);
  /* ONE LSB, not half, and the extra half is not slop.
   *
   * MEASURED: worst comes out at exactly 1.000 LSB, and it comes out there
   * at the top of the sine. +1.0 is not a representable 16-bit sample -
   * lround(1.0 * 32768) is 32768, which does not fit in an int16 and is
   * clamped to 32767 - so full-scale positive loses exactly one LSB every
   * time, in this encoder and in libsndfile and in ffmpeg alike. Everything
   * away from full scale is inside half an LSB, which is what rounding
   * costs. A tolerance of half would be a test that says the format is
   * wrong; this one says the decoder is right. */
  PB_CHECK_MSG(worst <= 1.0 / 32768.0, "16-bit round trip, within one LSB");
}

PB_TEST(a_wav_with_a_junk_chunk_is_still_a_wav) {
  const std::vector<float> material = sine(480, 100.0, 24000);
  const std::vector<std::uint8_t> file = makeWav(material, 1, 24000, true);
  const DecodedPcm pcm = decodeWav(file.data(), file.size());
  PB_CHECK_MSG(pcm.ok(), pcm.error);
  PB_EQ_MSG(pcm.frames(), 480,
            "the LIST chunk was skipped rather than played");
  PB_CHECK(std::fabs(pcm.samples[0]) < 0.001f);
}

PB_TEST(rubbish_is_refused_with_a_reason) {
  const std::uint8_t nonsense[64] = {0};
  const DecodedPcm pcm = decodeWav(nonsense, sizeof(nonsense));
  PB_CHECK(!pcm.ok());
  PB_CHECK_MSG(!pcm.error.empty(),
               "a refusal the operator can read, not a silent pad");
}

PB_TEST(twenty_four_kilohertz_becomes_forty_eight) {
  /* What this station actually serves. Upsampling by two needs no filter,
   * only interpolation that does not audibly grain. */
  DecodedPcm pcm;
  pcm.samples = sine(24000, 440.0, 24000);
  pcm.channels = 1;
  pcm.rate = 24000;

  const DecodedPcm up = resample(pcm, 48000);
  PB_CHECK(up.ok());
  PB_EQ(up.rate, 48000);
  PB_NEAR_MSG(up.frames(), 48000, 2,
              "a second in is a second out, whatever the rate");

  /* The material survived: compare against a 440 Hz sine generated straight
   * at 48 kHz, ignoring the first and last few frames where the
   * interpolator has no neighbours. */
  const std::vector<float> wanted = sine(48000, 440.0, 48000);
  double worst = 0.0;
  for (int f = 8; f < 47000; ++f) {
    worst = std::max<double>(worst,
                             std::fabs(up.samples[static_cast<size_t>(f)] -
                                       wanted[static_cast<size_t>(f)]));
  }
  PB_CHECK_MSG(worst < 0.02, "the sine came through the resampler intact");
}

PB_TEST(a_studio_file_is_filtered_before_it_is_decimated) {
  /* 96 kHz dropped on a pad. Without a lowpass first, everything above
   * 24 kHz folds back over the material as a whistle no trim can remove. */
  DecodedPcm pcm;
  pcm.samples = sine(96000, 40000.0, 96000);   /* well above the new Nyquist */
  pcm.channels = 1;
  pcm.rate = 96000;

  const DecodedPcm down = resample(pcm, 48000);
  PB_CHECK(down.ok());
  PB_EQ(down.rate, 48000);

  double energy = 0.0;
  for (int f = 2000; f < down.frames(); ++f) {
    const double v = down.samples[static_cast<size_t>(f)];
    energy += v * v;
  }
  const double rms = std::sqrt(energy / std::max(1, down.frames() - 2000));
  PB_CHECK_MSG(rms < 0.1,
               "a 40 kHz tone must not survive the trip to 48 kHz as an "
               "audible whistle");
}

PB_TEST(a_matching_rate_is_left_alone) {
  DecodedPcm pcm;
  pcm.samples = sine(4800, 440.0, 48000);
  pcm.channels = 1;
  pcm.rate = 48000;
  const DecodedPcm same = resample(pcm, 48000);
  PB_EQ(same.frames(), 4800);
  PB_NEAR(same.samples[1000], pcm.samples[1000], 1e-9);
}

PB_TEST(stereo_stays_stereo) {
  DecodedPcm pcm;
  pcm.channels = 2;
  pcm.rate = 24000;
  pcm.samples.assign(2400 * 2, 0.0f);
  for (int f = 0; f < 2400; ++f) {
    pcm.samples[static_cast<size_t>(f) * 2 + 0] = 0.5f;
    pcm.samples[static_cast<size_t>(f) * 2 + 1] = -0.5f;
  }
  const SampleRef buffer = toSampleBuffer(pcm, 48000);
  PB_CHECK(buffer != nullptr);
  PB_EQ(buffer->channels(), 2);
  PB_EQ(buffer->rate(), 48000);
  PB_NEAR(buffer->frames(), 4800, 2);
  PB_NEAR(buffer->at(2000, 0), 0.5, 0.01);
  PB_NEAR_MSG(buffer->at(2000, 1), -0.5, 0.01,
              "the channels did not get swapped or summed on the way through");
  /* And the footprint arithmetic follows from it. */
  PB_EQ(buffer->bytes(),
        static_cast<size_t>(buffer->frames()) * 2 * sizeof(float));
}
