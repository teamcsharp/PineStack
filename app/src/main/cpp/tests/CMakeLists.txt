# The sampler's semantic contract, checked without an audio device.
#
#   cmake -S app/src/main/cpp -B build-host
#   cmake --build build-host
#   ctest --test-dir build-host --output-on-failure
#
# Nothing here needs the NDK, Oboe, a tablet, or a sound card. What it cannot
# tell you is whether the instrument sounds right and how long a press takes
# to become sound - that number is measured on the physical device with a
# recorder and a finger, and is never inferred from in here.

set(PINEBOX_TEST_CASES
  test_window          # the play window: trim, reverse, one-shot vs gate
  test_voices          # polyphony, choke, release, the voice table
  test_mixer           # the envelope, and the reason there is one
  test_analysis        # peaks and the zero-crossing search
  test_footprint       # what a chopped bank actually costs
  test_sixteen_level   # 16 Level, Tune
  test_audio_format    # sniffing, WAV, and getting to 48 kHz
  test_duck            # holding the music down while a pad rings
)

foreach(case IN LISTS PINEBOX_TEST_CASES)
  add_executable(${case} ${case}.cpp)
  target_link_libraries(${case} PRIVATE pinebox_sampler_core)
  target_include_directories(${case} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
  add_test(NAME ${case} COMMAND ${case})
  # A hung test is a deadlock in the voice table, and a deadlock that merely
  # sits there is worse than one that fails.
  set_tests_properties(${case} PROPERTIES TIMEOUT 120)
endforeach()
