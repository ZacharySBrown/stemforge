// Verify stems.json has the exact field set + order expected by Track C.

#include <filesystem>
#include <fstream>

#include "test_framework.hpp"
#include "sf_manifest.hpp"

namespace fs = std::filesystem;

TEST(manifest_has_expected_fields) {
    auto tmp = fs::temp_directory_path() / "sf_manifest_test";
    fs::remove_all(tmp);
    fs::create_directories(tmp);

    sf::ManifestInput m;
    m.track_name = "hey_mami";
    m.source_file = tmp / "hey_mami.wav";
    m.backend = "demucs";
    m.bpm = 123.456;
    m.beat_count = 64;
    m.output_dir = tmp;
    m.pipeline = "default";

    sf::StemEntry s;
    s.name = "drums";
    s.wav_path = tmp / "drums.wav";
    s.beats_dir = tmp / "drums_beats";
    s.beat_count = 32;
    m.stems.push_back(s);

    auto out = sf::write_stems_manifest(m);
    CHECK(fs::exists(out));

    std::ifstream f(out);
    sf::json j; f >> j;

    // Required keys in Python dataclass order.
    std::vector<std::string> required = {
        "track_name", "source_file", "backend", "bpm", "beat_count",
        "stems", "output_dir", "pipeline", "processed_at",
    };
    for (const auto &k : required) CHECK(j.contains(k));
    CHECK_EQ(j["bpm"], 123.46);   // rounded to 2dp
    CHECK_EQ(j["stems"].size(), 1u);
    auto &s0 = j["stems"][0];
    CHECK_EQ(s0["name"], "drums");
    CHECK_EQ(s0["beat_count"], 32);
    CHECK(s0.contains("wav_path"));
    CHECK(s0.contains("beats_dir"));
}

TEST(index_json_single_writer) {
    auto tmp = fs::temp_directory_path() / "sf_index_test";
    fs::remove_all(tmp);
    fs::create_directories(tmp);
    sf::update_index(tmp, "trackA");
    sf::update_index(tmp, "trackB");
    sf::update_index(tmp, "trackA"); // dedupe
    std::ifstream f(tmp / "index.json");
    sf::json j; f >> j;
    CHECK(j.is_array());
    CHECK_EQ(j.size(), 2u);
    CHECK_EQ(j[0], "trackA");
    CHECK_EQ(j[1], "trackB");
}
