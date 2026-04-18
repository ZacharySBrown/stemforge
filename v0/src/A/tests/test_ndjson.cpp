// Validate that EventEmitter produces lines matching each event schema
// in v0/interfaces/ndjson.schema.json.

#include <string>
#include <vector>

#include "test_framework.hpp"
#include "sf_ndjson.hpp"

using sf::json;

static std::vector<std::string> captured;
static void capture_cb(const char *line, void *) { captured.emplace_back(line); }

static void reset() { captured.clear(); }

TEST(started_event_has_required_fields) {
    reset();
    sf::EventEmitter e(capture_cb, nullptr);
    e.started("track1", "/a.wav", "demucs", "default", "/out");
    CHECK_EQ(captured.size(), 1u);
    auto j = json::parse(captured[0]);
    CHECK_EQ(j["event"], "started");
    CHECK_EQ(j["track"], "track1");
    CHECK_EQ(j["audio"], "/a.wav");
    CHECK_EQ(j["backend"], "demucs");
    CHECK_EQ(j["pipeline"], "default");
    CHECK_EQ(j["output_dir"], "/out");
}

TEST(progress_event_pct_bounds) {
    reset();
    sf::EventEmitter e(capture_cb, nullptr);
    e.progress("loading_model", 50.0, "halfway");
    auto j = json::parse(captured[0]);
    CHECK_EQ(j["event"], "progress");
    CHECK_EQ(j["phase"], "loading_model");
    CHECK(j["pct"].get<double>() >= 0 && j["pct"].get<double>() <= 100);
    CHECK_EQ(j["message"], "halfway");
}

TEST(stem_event_shape) {
    reset();
    sf::EventEmitter e(capture_cb, nullptr);
    e.stem("drums", "/drums.wav", 1024);
    auto j = json::parse(captured[0]);
    CHECK_EQ(j["event"], "stem");
    CHECK_EQ(j["name"], "drums");
    CHECK_EQ(j["path"], "/drums.wav");
    CHECK_EQ(j["size_bytes"], 1024);
}

TEST(bpm_event_shape) {
    reset();
    sf::EventEmitter e(capture_cb, nullptr);
    e.bpm(120.0, 64);
    auto j = json::parse(captured[0]);
    CHECK_EQ(j["event"], "bpm");
    CHECK_EQ(j["bpm"], 120.0);
    CHECK_EQ(j["beat_count"], 64);
}

TEST(slice_dir_event_shape) {
    reset();
    sf::EventEmitter e(capture_cb, nullptr);
    e.slice_dir("drums", "/out/drums_beats", 32);
    auto j = json::parse(captured[0]);
    CHECK_EQ(j["event"], "slice_dir");
    CHECK_EQ(j["stem"], "drums");
    CHECK_EQ(j["dir"], "/out/drums_beats");
    CHECK_EQ(j["count"], 32);
}

TEST(complete_event_shape) {
    reset();
    sf::EventEmitter e(capture_cb, nullptr);
    e.complete("/out/stems.json", 120.5, 4, 9.8);
    auto j = json::parse(captured[0]);
    CHECK_EQ(j["event"], "complete");
    CHECK_EQ(j["manifest"], "/out/stems.json");
    CHECK_EQ(j["stem_count"], 4);
}

TEST(error_event_has_fatal) {
    reset();
    sf::EventEmitter e(capture_cb, nullptr);
    e.error("splitting", "boom", true);
    auto j = json::parse(captured[0]);
    CHECK_EQ(j["event"], "error");
    CHECK_EQ(j["phase"], "splitting");
    CHECK_EQ(j["message"], "boom");
    CHECK_EQ(j["fatal"], true);
}

TEST(progress_phases_are_schema_values) {
    // Every phase name we use MUST appear in the schema enum.
    const std::vector<std::string> allowed = {
        "downloading_weights", "loading_model", "splitting",
        "analyzing", "slicing", "writing_manifest"
    };
    reset();
    sf::EventEmitter e(capture_cb, nullptr);
    for (const auto &p : allowed) e.progress(p, 0);
    CHECK_EQ(captured.size(), allowed.size());
    for (size_t i = 0; i < allowed.size(); ++i) {
        auto j = json::parse(captured[i]);
        CHECK_EQ(j["phase"], allowed[i]);
    }
}
