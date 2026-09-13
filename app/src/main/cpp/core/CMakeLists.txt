# pinebox_sampler_core - the engine with no platform in it.
#
# Nothing in this target may include a JNI, NDK or Oboe header. That rule is
# what lets the whole semantic contract be tested on a build machine, and it
# is worth defending: the moment the window arithmetic needs an audio device
# to exercise, it stops being exercised.

add_library(pinebox_sampler_core STATIC
  pinebox/analysis.cpp
  pinebox/audio_format.cpp
  pinebox/duck.cpp
  pinebox/engine.cpp
  pinebox/mixer.cpp
  pinebox/pad.cpp
  pinebox/sample_buffer.cpp
  pinebox/voice.cpp
  pinebox/window.cpp
)

target_include_directories(pinebox_sampler_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(pinebox_sampler_core PUBLIC cxx_std_17)

find_package(Threads REQUIRED)
target_link_libraries(pinebox_sampler_core PUBLIC Threads::Threads)
