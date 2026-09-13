# PineBox sampler - native audio engine.
#
# Two things get built out of this tree, and the split is the point:
#
#   pinebox_sampler_core   pure C++17. No NDK, no Oboe, no JNI, no device.
#                          Windows, offsets, envelopes, choke, the mixer,
#                          the WAV reader and the resampler all live here.
#   pinebox_sampler        the shared library the app loads. JNI, Oboe, and
#                          AMediaCodec, wrapped around the core.
#
# Because the core has no platform in it, `cmake -S app/src/main/cpp -B build`
# on a build machine with nothing but a compiler produces the test suite, and
# `ctest` runs the whole semantic contract - the same contract the Web Audio
# engine is held to by tests/test_sampler_engine_2026_09_10.cjs.
#
# Gradle points externalNativeBuild at THIS file; it defines ANDROID, so the
# tests are skipped and the shared library is built instead.
#
# ---------------------------------------------------------------------------
# OBOE
#
# Fetched by default:
#
#   FetchContent, google/oboe, pinned to a tag. Needs network on the first
#   configure only; after that it is in the build directory.
#
# VENDORING IT INSTEAD - which is what a build machine with no outbound
# network wants, and what a reproducible release build should do anyway:
#
#   1. git clone --depth 1 --branch 1.9.0 https://github.com/google/oboe \
#        app/src/main/cpp/third_party/oboe
#   2. Delete oboe's own .git, or add it as a submodule rather than a clone.
#   3. Configure with -DPINEBOX_OBOE_DIR=<that path>, or just leave it: the
#      path below is checked first and used if it exists, so a clone into
#      cpp/third_party/oboe is picked up with no flags at all.
#
# Oboe is Apache 2.0. Vendoring it means its NOTICE has to travel with the
# app; the licence file in the checkout is the one to ship.
# ---------------------------------------------------------------------------

cmake_minimum_required(VERSION 3.22.1)
project(pinebox_sampler LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(PINEBOX_SAMPLER_TESTS "Build the sampler's host-side unit tests" OFF)
if(NOT ANDROID)
  set(PINEBOX_SAMPLER_TESTS ON CACHE BOOL "" FORCE)
endif()

add_subdirectory(core)

if(ANDROID)
  # -------------------------------------------------------------- oboe ----
  set(PINEBOX_VENDORED_OBOE "${CMAKE_CURRENT_SOURCE_DIR}/third_party/oboe")
  if(NOT DEFINED PINEBOX_OBOE_DIR AND EXISTS "${PINEBOX_VENDORED_OBOE}/CMakeLists.txt")
    set(PINEBOX_OBOE_DIR "${PINEBOX_VENDORED_OBOE}")
  endif()

  if(DEFINED PINEBOX_OBOE_DIR)
    message(STATUS "pinebox: using vendored Oboe at ${PINEBOX_OBOE_DIR}")
    add_subdirectory("${PINEBOX_OBOE_DIR}" "${CMAKE_BINARY_DIR}/oboe-build")
  else()
    message(STATUS "pinebox: fetching Oboe")
    include(FetchContent)
    FetchContent_Declare(
      oboe
      GIT_REPOSITORY https://github.com/google/oboe
      GIT_TAG        1.9.0
      GIT_SHALLOW    TRUE
    )
    FetchContent_MakeAvailable(oboe)
  endif()

  # MEASURED: Oboe's own CMake exports a plain `oboe` target. The namespaced
  # `oboe::oboe` alias only exists for consumers who find_package() an
  # INSTALLED Oboe - not for one pulled in by FetchContent or
  # add_subdirectory, which is how it arrives here. Linking oboe::oboe failed
  # configure outright with "links to target oboe::oboe but the target was
  # not found". Make the alias ourselves so the link line reads the same
  # either way.
  if(TARGET oboe AND NOT TARGET oboe::oboe)
    add_library(oboe::oboe ALIAS oboe)
  endif()

  add_library(pinebox_sampler SHARED
    android/jni_bridge.cpp
    android/media_decode.cpp
    android/oboe_output.cpp
  )
  target_include_directories(pinebox_sampler PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
  target_link_libraries(pinebox_sampler
    PRIVATE
      pinebox_sampler_core
      oboe::oboe
      mediandk      # AMediaExtractor / AMediaCodec
      android
      log
  )

  # The audio callback is the whole product. -ffast-math is NOT here on
  # purpose: the envelope compares against zero to decide when a voice is
  # finished, and a compiler that assumes no denormals and no exact zero is a
  # compiler that leaves voices ringing. Exceptions stay ON: the core uses
  # std::map and std::vector, so a bad_alloc has to be able to unwind through
  # the bridge rather than call std::terminate on a tablet.
  target_compile_options(pinebox_sampler PRIVATE -O3)
  target_compile_options(pinebox_sampler_core PRIVATE -O3)
endif()

if(PINEBOX_SAMPLER_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()
