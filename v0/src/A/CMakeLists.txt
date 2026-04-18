cmake_minimum_required(VERSION 3.20)
project(stemforge CXX C)

# ---------------------------------------------------------------------------
# Build targets:
#   libstemforge   — static library, all inference/slicing/manifest logic.
#   stemforge-native — thin CLI wrapper.
#   stemforge_tests — GoogleTest-free lightweight test runner.
#
# v2's Max external will link libstemforge directly (see PIVOT §A).
# ---------------------------------------------------------------------------

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Aggressive optimization (PIVOT §E).
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-Wall -Wextra -Wno-unused-parameter -Wno-sign-compare)
# NB: -ffast-math audited in A.10 and deferred — it corrupts STFT accuracy.

if(APPLE)
    # Default to native arch if not specified; build-native.sh overrides for universal2 path.
    if(NOT CMAKE_OSX_ARCHITECTURES)
        execute_process(COMMAND uname -m OUTPUT_VARIABLE _HOST_ARCH OUTPUT_STRIP_TRAILING_WHITESPACE)
        set(CMAKE_OSX_ARCHITECTURES "${_HOST_ARCH}" CACHE STRING "" FORCE)
    endif()
endif()

# ---------------------------------------------------------------------------
# Vendored deps
# ---------------------------------------------------------------------------
set(VENDOR_DIR "${CMAKE_CURRENT_SOURCE_DIR}/vendor")
set(ORT_DIR    "${VENDOR_DIR}/onnxruntime-osx-arm64-1.24.4")
set(KISSFFT_DIR "${VENDOR_DIR}/kissfft")

if(NOT EXISTS "${ORT_DIR}/include/onnxruntime_cxx_api.h")
    message(FATAL_ERROR "ONNX Runtime not found at ${ORT_DIR}. Run build-native.sh to fetch.")
endif()

add_library(kissfft STATIC
    "${KISSFFT_DIR}/kiss_fft.c"
    "${KISSFFT_DIR}/kiss_fftr.c"
)
target_include_directories(kissfft PUBLIC "${KISSFFT_DIR}")
target_compile_definitions(kissfft PUBLIC KISS_FFT_USE_CPP_11)

# ---------------------------------------------------------------------------
# libstemforge — static library (the real product)
# ---------------------------------------------------------------------------
add_library(stemforge_lib STATIC
    src/sf_lib.cpp
)
set_target_properties(stemforge_lib PROPERTIES
    OUTPUT_NAME stemforge
    PREFIX "lib"
)
target_include_directories(stemforge_lib
    PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/include"
    PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
        "${ORT_DIR}/include"
        "${VENDOR_DIR}"      # for nlohmann_json.hpp
)
target_link_libraries(stemforge_lib
    PUBLIC
        kissfft
)
target_link_libraries(stemforge_lib
    PUBLIC
        "${ORT_DIR}/lib/libonnxruntime.dylib"
        "-framework CoreFoundation"
        "-framework AudioToolbox"
        "-framework Foundation"
)
# libonnxruntime.dylib's install_name is absolute; we'll rpath-fix the
# CLI binary in build-native.sh so it finds the dylib beside it.

# ---------------------------------------------------------------------------
# stemforge-native — CLI wrapper (thin, links libstemforge)
# ---------------------------------------------------------------------------
add_executable(stemforge_native cli/main.cpp)
set_target_properties(stemforge_native PROPERTIES
    OUTPUT_NAME stemforge-native
)
target_link_libraries(stemforge_native PRIVATE stemforge_lib)
set_target_properties(stemforge_native PROPERTIES
    BUILD_RPATH "@executable_path;${ORT_DIR}/lib"
    INSTALL_RPATH "@executable_path"
)

# ---------------------------------------------------------------------------
# Tests (no external framework — keep deps minimal).
# ---------------------------------------------------------------------------
enable_testing()
add_executable(stemforge_tests
    tests/test_main.cpp
    tests/test_manifest.cpp
    tests/test_ndjson.cpp
    tests/test_stft.cpp
    tests/test_slugify.cpp
)
target_link_libraries(stemforge_tests PRIVATE stemforge_lib)
target_include_directories(stemforge_tests PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${ORT_DIR}/include"
    "${VENDOR_DIR}"
)
add_test(NAME unit COMMAND stemforge_tests)
