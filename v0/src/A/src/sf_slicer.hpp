// sf_slicer.hpp — port of stemforge.slicer.slice_at_beats.
//
// Inputs:
//   stem: deinterleaved (channels, frames) float in [-1, 1]
//   beat_times_sec: beat onsets (from sf_beat::detect_beats)
//   sr: sample rate (44100)
//   output_dir / stem_name: write <output_dir>/<stem>_beats/<stem>_beat_NNN.wav
//
// Writes 24-bit PCM WAV per slice, skips slices with RMS below
// silence_threshold, peak-normalizes stem to -1 dBFS before slicing.

#pragma once

#include <cmath>
#include <filesystem>
#include <string>
#include <vector>

#include "sf_wav.hpp"

namespace sf {

namespace fs = std::filesystem;

struct SliceOpts {
    double silence_threshold = 1e-3;
    bool   normalize = true;
    double normalize_headroom_db = -1.0;
    int    beats_per_slice = 1;
};

inline int slice_at_beats(const std::vector<std::vector<float>> &stem,
                          const std::vector<double> &beat_times_sec,
                          int sr,
                          const fs::path &output_dir,
                          const std::string &stem_name,
                          const SliceOpts &opts = {}) {
    if (stem.empty()) return 0;
    int channels = static_cast<int>(stem.size());
    size_t total = stem[0].size();

    // Peak-normalize to target dB headroom.
    std::vector<std::vector<float>> y = stem;
    if (opts.normalize) {
        float peak = 0.0f;
        for (const auto &c : y) for (float v : c) peak = std::max(peak, std::fabs(v));
        if (peak > 0) {
            double target = std::pow(10.0, opts.normalize_headroom_db / 20.0);
            float scale = static_cast<float>(target / peak);
            for (auto &c : y) for (float &v : c) v *= scale;
        }
    }

    // Build beat-sample boundaries grouped by beats_per_slice.
    std::vector<size_t> bar_samples;
    for (size_t i = 0; i < beat_times_sec.size(); i += static_cast<size_t>(opts.beats_per_slice))
        bar_samples.push_back(static_cast<size_t>(std::round(beat_times_sec[i] * sr)));
    // Append tail boundary.
    std::vector<size_t> boundaries;
    boundaries.reserve(bar_samples.size() + 1);
    for (auto s : bar_samples) boundaries.push_back(std::min(s, total));
    boundaries.push_back(total);

    fs::path slices_dir = output_dir / (stem_name + "_beats");
    fs::create_directories(slices_dir);

    int written = 0;
    for (size_t i = 0; i + 1 < boundaries.size(); ++i) {
        size_t s = boundaries[i], e = boundaries[i + 1];
        if (e <= s) continue;
        // RMS
        double acc = 0.0;
        size_t n = (e - s) * static_cast<size_t>(channels);
        for (int c = 0; c < channels; ++c)
            for (size_t k = s; k < e; ++k) { double v = y[c][k]; acc += v * v; }
        double rms = std::sqrt(acc / std::max<size_t>(1, n));
        if (rms < opts.silence_threshold) continue;

        // Slice out.
        std::vector<std::vector<float>> chunk(channels);
        for (int c = 0; c < channels; ++c)
            chunk[c].assign(y[c].begin() + s, y[c].begin() + e);

        char fname[64];
        std::snprintf(fname, sizeof(fname), "%s_beat_%03zu.wav", stem_name.c_str(), i + 1);
        write_wav_pcm24_deinterleaved(slices_dir / fname, chunk, sr);
        ++written;
    }
    return written;
}

} // namespace sf
