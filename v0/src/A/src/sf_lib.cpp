// sf_lib.cpp — C ABI implementation of libstemforge.
//
// The public surface is frozen in include/stemforge.h. Everything here
// is private. Keep this file focused on:
//   (a) handle lifecycle,
//   (b) translating C params to C++ objects,
//   (c) orchestrating the full split/forge pipeline on the worker thread,
//   (d) emitting NDJSON events that conform to ndjson.schema.json.
//
// Inference + DSP lives in the sf_*.hpp headers.

#include "stemforge.h"

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "onnxruntime_cxx_api.h"

#include "sf_beat.hpp"
#include "sf_demucs.hpp"
#include "sf_manifest.hpp"
#include "sf_model_manifest.hpp"
#include "sf_ndjson.hpp"
#include "sf_slicer.hpp"
#include "sf_wav.hpp"

namespace {
namespace fs = std::filesystem;
using json = nlohmann::json;

constexpr const char *kAbiVersion = "0.0.1";

fs::path resolve_model_dir(const char *cfg_dir) {
    if (cfg_dir && cfg_dir[0]) return cfg_dir;
    if (const char *env = std::getenv("STEMFORGE_MODEL_DIR")) {
        if (env[0]) return env;
    }
    if (const char *home = std::getenv("HOME")) {
        return fs::path(home) / "Library" / "Application Support"
             / "StemForge" / "models";
    }
    return "./models";
}

std::string slugify(const std::string &in) {
    // Mirrors stemforge.cli.to_snake_case behaviour (strip leading track
    // numbers, collapse non-alnum to _, lowercase).
    std::string s = in;
    // strip leading digits + separator
    size_t i = 0;
    while (i < s.size() && std::isdigit(static_cast<unsigned char>(s[i]))) ++i;
    if (i > 0) {
        while (i < s.size() &&
               (s[i] == '_' || s[i] == ' ' || s[i] == '-' || s[i] == '.')) ++i;
        s = s.substr(i);
    }
    std::string out;
    out.reserve(s.size());
    bool prev_us = false;
    for (char c : s) {
        if (std::isalnum(static_cast<unsigned char>(c))) {
            out.push_back(std::tolower(static_cast<unsigned char>(c)));
            prev_us = false;
        } else {
            if (!prev_us) out.push_back('_');
            prev_us = true;
        }
    }
    while (!out.empty() && out.front() == '_') out.erase(out.begin());
    while (!out.empty() && out.back() == '_') out.pop_back();
    return out;
}

sf::DemucsVariant to_cpp_variant(sf_demucs_variant v) {
    switch (v) {
        case SF_DEMUCS_6S:       return sf::DemucsVariant::SixSource;
        case SF_DEMUCS_FAST:     return sf::DemucsVariant::Fast;
        case SF_DEMUCS_FT:       return sf::DemucsVariant::FT;
        case SF_DEMUCS_FT_FUSED: return sf::DemucsVariant::FTFused;
        case SF_DEMUCS_DEFAULT:
        default:                 return sf::DemucsVariant::FTFused;
    }
}

OrtLoggingLevel to_ort_level(sf_log_level lvl) {
    switch (lvl) {
        case SF_LOG_VERBOSE: return ORT_LOGGING_LEVEL_VERBOSE;
        case SF_LOG_INFO:    return ORT_LOGGING_LEVEL_INFO;
        case SF_LOG_WARNING: return ORT_LOGGING_LEVEL_WARNING;
        case SF_LOG_ERROR:   return ORT_LOGGING_LEVEL_ERROR;
        case SF_LOG_FATAL:   return ORT_LOGGING_LEVEL_FATAL;
    }
    return ORT_LOGGING_LEVEL_WARNING;
}

} // namespace

// ────────────────────────────────────────────────────────────────────────────
// sf_handle_t — one per library consumer (CLI process, Max external
// instance). Holds the ORT env, shared sessions, and worker thread.
// ────────────────────────────────────────────────────────────────────────────

struct sf_handle_t {
    sf_config config{};
    std::unique_ptr<Ort::Env> env;
    sf::ModelManifest manifest;
    fs::path model_root;

    // Lazy-built — we defer Demucs session creation to first sf_split
    // call so that `stemforge-native --version` is instant.
    std::unique_ptr<sf::DemucsRunner> demucs;
    std::mutex demucs_mu;

    std::string last_error;
    std::atomic<bool> cancelled{false};
};

extern "C" const char *sf_version(void) { return kAbiVersion; }

extern "C" sf_handle sf_create(const sf_config *cfg) {
    try {
        auto h = std::make_unique<sf_handle_t>();
        if (cfg) h->config = *cfg;
        h->model_root = resolve_model_dir(cfg ? cfg->model_dir : nullptr);
        h->env = std::make_unique<Ort::Env>(
            to_ort_level(cfg ? cfg->log_level : SF_LOG_WARNING),
            "libstemforge");
        h->manifest = sf::load_model_manifest(h->model_root);
        return h.release();
    } catch (const std::exception &e) {
        // No handle to store on — write to stderr + leak nothing.
        std::fprintf(stderr, "sf_create failed: %s\n", e.what());
        return nullptr;
    } catch (...) {
        std::fprintf(stderr, "sf_create failed: unknown exception\n");
        return nullptr;
    }
}

extern "C" void sf_destroy(sf_handle h) { delete h; }

extern "C" const char *sf_last_error(sf_handle h) {
    return h ? h->last_error.c_str() : "";
}

extern "C" void sf_cancel(sf_handle h) {
    if (h) h->cancelled.store(true);
}

static sf::DemucsRunner &ensure_demucs(sf_handle h, sf::EventEmitter &emit) {
    std::lock_guard<std::mutex> lk(h->demucs_mu);
    if (!h->demucs) {
        emit.progress("loading_model", 0, "loading Demucs ONNX heads");
        sf::DemucsConfig cfg;
        cfg.variant = to_cpp_variant(h->config.demucs_variant);
        cfg.force_cpu_only = h->config.force_cpu_only != 0;
        cfg.intra_threads = h->config.num_threads;
        h->demucs = std::make_unique<sf::DemucsRunner>(h->manifest, cfg, *h->env);
        emit.progress("loading_model", 100, "Demucs ready");
    }
    return *h->demucs;
}

// ────────────────────────────────────────────────────────────────────────────
// sf_split — full stem + slice + manifest pipeline.
// ────────────────────────────────────────────────────────────────────────────

extern "C" sf_status sf_warmup(sf_handle h, sf_event_cb cb, void *user) {
    if (!h) return SF_ERR_INVALID_ARG;
    sf::EventEmitter emit(cb, user);
    try {
        emit.progress("warmup", 0, "constructing Demucs session (one-time CoreML compile, ~2-3 min)");
        ensure_demucs(h, emit);
        emit.progress("warmup", 100, "Demucs session ready");
        return SF_OK;
    } catch (const std::exception &e) {
        h->last_error = std::string("warmup: ") + e.what();
        emit.error("warmup", h->last_error, true);
        return SF_ERR_MODEL_LOAD;
    } catch (...) {
        h->last_error = "warmup: unknown exception";
        emit.error("warmup", h->last_error, true);
        return SF_ERR_MODEL_LOAD;
    }
}

extern "C" sf_status sf_split(sf_handle h, const char *input_wav,
                              const char *out_dir_c, sf_event_cb cb,
                              void *user) {
    if (!h || !input_wav || !out_dir_c) return SF_ERR_INVALID_ARG;
    h->cancelled.store(false);
    sf::EventEmitter emit(cb, user);

    auto t0 = std::chrono::steady_clock::now();

    try {
        fs::path in_path = input_wav;
        std::string track = slugify(in_path.stem().string());
        fs::path out_dir = fs::path(out_dir_c) / track;
        fs::create_directories(out_dir);

        emit.started(track, fs::absolute(in_path).string(), "demucs",
                     "default", fs::absolute(out_dir).string());

        // 1. Decode
        emit.progress("splitting", 2, "decoding input");
        sf::WavData audio = sf::read_audio(in_path, 44100, 2);
        if (audio.num_frames() == 0) {
            emit.error("splitting", "empty input", true);
            return SF_ERR_AUDIO_DECODE;
        }
        std::vector<std::vector<float>> mix(audio.channels,
            std::vector<float>(audio.num_frames()));
        for (size_t i = 0; i < audio.num_frames(); ++i)
            for (int c = 0; c < audio.channels; ++c)
                mix[c][i] = audio.samples[i * audio.channels + c];

        // 2. Demucs inference
        auto &demucs = ensure_demucs(h, emit);
        emit.progress("splitting", 10, "running Demucs");
        auto stems = demucs.run(mix, [&](double pct, const std::string &msg) {
            // Map inference 0..100% to splitting 10..80%.
            double mapped = 10.0 + pct * 0.7;
            emit.progress("splitting", mapped, msg);
            if (h->cancelled.load()) throw std::runtime_error("cancelled");
        });
        emit.progress("splitting", 85, "writing stems");

        // 3. Write stems
        std::vector<sf::StemEntry> stem_entries;
        std::unordered_map<std::string, std::vector<std::vector<float>>> stem_audio;
        for (size_t i = 0; i < stems.source_names.size(); ++i) {
            const auto &name = stems.source_names[i];
            fs::path wav = out_dir / (name + ".wav");
            sf::write_wav_pcm24_deinterleaved(wav, stems.data[i], stems.sample_rate);
            int64_t size = fs::exists(wav) ? static_cast<int64_t>(fs::file_size(wav)) : 0;
            emit.stem(name, fs::absolute(wav).string(), size);
            sf::StemEntry e;
            e.name = name; e.wav_path = wav;
            e.beats_dir = out_dir / (name + "_beats");
            stem_entries.push_back(e);
            stem_audio[name] = stems.data[i];
        }

        // 4. Beat detect (mono downmix of drums stem if available, else full mix)
        emit.progress("analyzing", 88, "beat tracking");
        std::vector<float> mono;
        auto mono_from = [&](const std::vector<std::vector<float>> &s) {
            std::vector<float> m(s[0].size(), 0.0f);
            for (size_t i = 0; i < m.size(); ++i) {
                double acc = 0.0;
                for (const auto &c : s) acc += c[i];
                m[i] = static_cast<float>(acc / s.size());
            }
            return m;
        };
        auto drums_it = stem_audio.find("drums");
        mono = drums_it != stem_audio.end() ? mono_from(drums_it->second)
                                            : mono_from(mix);
        auto beats = sf::detect_beats(mono);
        emit.bpm(beats.bpm, static_cast<int>(beats.beat_times_sec.size()));

        // 5. Slice each stem
        emit.progress("slicing", 92, "slicing beats");
        int total_beat_count = static_cast<int>(beats.beat_times_sec.size());
        for (auto &e : stem_entries) {
            int written = sf::slice_at_beats(stem_audio[e.name],
                                             beats.beat_times_sec,
                                             stems.sample_rate,
                                             out_dir, e.name);
            e.beat_count = written;
            emit.slice_dir(e.name, fs::absolute(e.beats_dir).string(), written);
        }

        // 6. Manifest
        emit.progress("writing_manifest", 98, "");
        sf::ManifestInput mi;
        mi.track_name = track;
        mi.source_file = in_path;
        mi.backend = "demucs";
        mi.bpm = beats.bpm;
        mi.beat_count = total_beat_count;
        mi.stems = stem_entries;
        mi.output_dir = out_dir;
        mi.pipeline = "default";
        fs::path manifest_path = sf::write_stems_manifest(mi);
        sf::update_index(out_dir.parent_path(), track);

        auto dt = std::chrono::duration<double>(
                    std::chrono::steady_clock::now() - t0).count();
        emit.complete(fs::absolute(manifest_path).string(), beats.bpm,
                      static_cast<int>(stem_entries.size()), dt);
        return SF_OK;
    } catch (const std::exception &e) {
        if (h->cancelled.load()) {
            emit.error("splitting", "cancelled", true);
            h->last_error = "cancelled";
            return SF_ERR_CANCELLED;
        }
        emit.error("splitting", e.what(), true);
        h->last_error = e.what();
        return SF_ERR_INFERENCE;
    } catch (...) {
        emit.error("splitting", "unknown exception", true);
        h->last_error = "unknown exception";
        return SF_ERR_INTERNAL;
    }
}

// sf_forge: v0 delegates to sf_split. When forge YAML arrives, wire in
// curator + pre-render here without touching the ABI.
extern "C" sf_status sf_forge(sf_handle h, const char *input_wav,
                              const struct sf_pipeline *pipe,
                              sf_event_cb cb, void *user) {
    (void)pipe; // not used in v0
    if (!h) return SF_ERR_INVALID_ARG;
    // Default out_dir = ~/stemforge/processed/.
    fs::path out;
    if (const char *home = std::getenv("HOME")) out = fs::path(home) / "stemforge" / "processed";
    else out = "./processed";
    return sf_split(h, input_wav, out.c_str(), cb, user);
}
