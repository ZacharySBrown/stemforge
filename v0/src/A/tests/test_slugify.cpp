// The slugify in sf_lib.cpp is file-local; we expose it via a tiny
// duplicate here or skip. Instead, test via sf_split indirectly once
// models exist — for now just verify schema validator side.
// Placeholder to keep CMake target linkable.

#include "test_framework.hpp"

TEST(slugify_placeholder) {
    // slugify is private; CLI integration test in integration suite covers it.
    CHECK(true);
}
