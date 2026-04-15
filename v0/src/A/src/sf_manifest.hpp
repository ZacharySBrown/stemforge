// sf_manifest.hpp — write stems.json byte-for-byte compatible with
// stemforge.manifest.write_manifest() output.
//
// Schema fields (in declaration order, matching dataclass asdict()):
//   track_name, source_file, backend, bpm, beat_count, stems[],
//   output_dir, pipeline, processed_at.
//
// Each StemInfo: name, wav_path, beats_dir, beat_count.

#pragma once

#include <ctime>
#include <string>
#include <vector>
#include <filesystem>
#include <fstream>

#include "nlohmann_json.hpp"

namespace sf {

namespace fs = std::filesystem;
using json = nlohmann::json;

struct StemEntry {
    std::string name;
    fs::path    wav_path;
    fs::path    beats_dir;
    int         beat_count = 0;
};

struct ManifestInput {
    std::string track_name;
    fs::path    source_file;
    std::string backend;
    double      bpm = 0;
    int         beat_count = 0;
    std::vector<StemEntry> stems;
    fs::path    output_dir;
    std::string pipeline = "default";
};

// Matches Python time.strftime("%Y-%m-%dT%H:%M:%S") — local time, no TZ.
inline std::string current_timestamp() {
    std::time_t t = std::time(nullptr);
    std::tm tm;
    localtime_r(&t, &tm);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
    return buf;
}

inline fs::path write_stems_manifest(const ManifestInput &m) {
    json stems = json::array();
    for (const auto &s : m.stems) {
        stems.push_back({
            {"name",       s.name},
            {"wav_path",   fs::absolute(s.wav_path).lexically_normal().string()},
            {"beats_dir",  fs::absolute(s.beats_dir).lexically_normal().string()},
            {"beat_count", s.beat_count}
        });
    }

    // Python rounds bpm to 2dp via round(bpm, 2).
    double bpm_rounded = std::round(m.bpm * 100.0) / 100.0;

    json manifest = {
        {"track_name",   m.track_name},
        {"source_file",  fs::absolute(m.source_file).lexically_normal().string()},
        {"backend",      m.backend},
        {"bpm",          bpm_rounded},
        {"beat_count",   m.beat_count},
        {"stems",        stems},
        {"output_dir",   fs::absolute(m.output_dir).lexically_normal().string()},
        {"pipeline",     m.pipeline},
        {"processed_at", current_timestamp()},
    };

    fs::create_directories(m.output_dir);
    fs::path out = m.output_dir / "stems.json";
    std::ofstream f(out);
    f << manifest.dump(2);
    return out;
}

// Mirrors stemforge.manifest.update_index() — single-writer per track.
inline void update_index(const fs::path &processed_dir, const std::string &track_name) {
    fs::path idx = processed_dir / "index.json";
    json entries = json::array();
    if (fs::exists(idx)) {
        try {
            std::ifstream f(idx);
            f >> entries;
            if (!entries.is_array()) entries = json::array();
        } catch (...) {
            entries = json::array();
        }
    }
    bool found = false;
    for (const auto &e : entries) if (e == track_name) { found = true; break; }
    if (!found) entries.push_back(track_name);
    std::ofstream f(idx);
    f << entries.dump(2);
}

} // namespace sf
