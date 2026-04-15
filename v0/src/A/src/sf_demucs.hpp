// sf_demucs.hpp — Demucs inference path (ONNX Runtime + external STFT).
//
// Per PIVOT §E and A0 manifest, the ONNX graph takes (mix, z_cac) and
// returns (time_out, zout_cac). The caller (us) does STFT/CAC-pack
// beforehand and CAC-unpack/iSTFT afterwards, summing time + freq
// branches to get the final stems.
//
// Segment processing per head:
//   segment_samples = 343980 (7.8 s @ 44.1 kHz).
//   For each segment boundary:
//     mix_padded = pad(mix_segment, 0, seg - len)
//     z = apply_stft(mix_padded)
//     z_cac = pack_cac(z)
//     (time_out, zout_cac) = head.Run({"mix": mix_padded, "z_cac": z_cac})
//     z_out = unpack_cac(zout_cac)
//     x_freq = apply_istft(z_out, seg)
//     stems_segment = time_out + x_freq
//
// For htdemucs_ft bag-of-heads (S=4 sources per head), we run all 4
// heads with weights = I_4 (per-head specialists), combine per
// run_bag_onnx logic, then overlap-add the segments.
//
// Overlap-add uses 25% overlap with a triangular window, matching
// demucs.apply.apply_model's default behaviour.

#pragma once

#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "onnxruntime_cxx_api.h"
#include "coreml_provider_factory.h"

#include "sf_model_manifest.hpp"
#include "sf_stft.hpp"

namespace sf {

constexpr int   kDemucsSR = 44100;
constexpr int   kDemucsSegmentSamples = 343980; // 7.8 s @ 44.1 kHz
constexpr float kOverlap = 0.25f;

enum class DemucsVariant { Default, FT, SixSource, Fast };

struct DemucsConfig {
    DemucsVariant variant = DemucsVariant::FT;
    bool          force_cpu_only = false;
    int           intra_threads = 0;     // 0 → auto
};

struct DemucsStems {
    // (source, channels=2, samples)
    std::vector<std::vector<std::vector<float>>> data;
    std::vector<std::string> source_names; // "drums", "bass", "vocals", "other" (or 6-stem)
    int sample_rate = kDemucsSR;
};

class DemucsRunner {
public:
    DemucsRunner(const ModelManifest &mm, const DemucsConfig &cfg,
                 Ort::Env &env);

    // Run full inference on a 44.1 kHz stereo mix (channels, samples).
    // progress_cb is invoked with pct in [0, 100] for the inference
    // phase.
    DemucsStems run(const std::vector<std::vector<float>> &mix,
                    const std::function<void(double, const std::string &)> &progress_cb) const;

private:
    struct HeadSession {
        std::unique_ptr<Ort::Session> session;
        Ort::AllocatorWithDefaultOptions alloc;
        int bag_head_index = 0;
        int bag_size = 1;
        // I/O names cached (char* owned by allocator).
        std::vector<Ort::AllocatedStringPtr> input_name_holders;
        std::vector<Ort::AllocatedStringPtr> output_name_holders;
        std::vector<const char *> input_names;
        std::vector<const char *> output_names;
    };

    const ModelManifest &mm_;
    DemucsConfig cfg_;
    Ort::Env &env_;

    std::vector<std::string> source_names_;           // canonical
    std::vector<std::unique_ptr<HeadSession>> heads_; // 1 entry for single-model, 4 for htdemucs_ft
    std::vector<std::vector<float>> bag_weights_;     // (H, S)

    // Run a single segment through all heads and combine.
    // mix_seg: (C=2, N=segment_samples) already padded.
    // Returns (S, C, N) for this segment.
    std::vector<std::vector<std::vector<float>>>
    run_segment(const std::vector<std::vector<float>> &mix_seg) const;

    void build_session(HeadSession &hs, const ModelEntry &entry) const;
    static std::vector<std::string> canonical_sources(DemucsVariant v);
};

// ----- impl ------------------------------------------------------------

inline std::vector<std::string>
DemucsRunner::canonical_sources(DemucsVariant v) {
    switch (v) {
        case DemucsVariant::SixSource:
            return {"drums", "bass", "other", "vocals", "guitar", "piano"};
        case DemucsVariant::Fast:
        case DemucsVariant::FT:
        case DemucsVariant::Default:
        default:
            return {"drums", "bass", "other", "vocals"};
    }
}

inline void DemucsRunner::build_session(HeadSession &hs,
                                        const ModelEntry &entry) const {
    verify_model(entry); // throws on missing / sha mismatch

    Ort::SessionOptions opts;
    opts.SetGraphOptimizationLevel(ORT_ENABLE_ALL);
    int threads = cfg_.intra_threads;
    if (threads <= 0) {
        threads = std::max(1u, std::thread::hardware_concurrency() - 1);
    }
    opts.SetIntraOpNumThreads(threads);

    // Optimised model cache (PIVOT §E — non-negotiable).
    if (!entry.optimized_cache.empty()) {
        fs::create_directories(entry.optimized_cache.parent_path());
        opts.SetOptimizedModelFilePath(entry.optimized_cache.c_str());
    }

    // CoreML EP. A0's manifest currently reports coreml_ep_supported=false
    // for every model (CPU-latency-only measurements). We still try the
    // MLProgram EP because A0's detection was limited to node-assignment
    // heuristics and the authoritative answer comes from runtime logs.
    // The user can pass force_cpu_only=1 to bypass.
    if (!cfg_.force_cpu_only && entry.coreml_ep_supported) {
        std::unordered_map<std::string, std::string> coreml_opts = {
            {"MLComputeUnits", "ALL"},
            {"ModelFormat",    "MLProgram"},
            {"RequireStaticInputShapes", "0"},
        };
        try {
            opts.AppendExecutionProvider("CoreML", coreml_opts);
        } catch (const Ort::Exception &e) {
            // fall through to CPU EP (implicit).
        }
    }

    hs.session = std::make_unique<Ort::Session>(env_, entry.path.c_str(), opts);
    hs.bag_head_index = entry.bag_head_index < 0 ? 0 : entry.bag_head_index;
    hs.bag_size = entry.bag_size;

    size_t ni = hs.session->GetInputCount();
    size_t no = hs.session->GetOutputCount();
    hs.input_name_holders.reserve(ni);
    hs.output_name_holders.reserve(no);
    for (size_t i = 0; i < ni; ++i) {
        hs.input_name_holders.push_back(hs.session->GetInputNameAllocated(i, hs.alloc));
        hs.input_names.push_back(hs.input_name_holders.back().get());
    }
    for (size_t i = 0; i < no; ++i) {
        hs.output_name_holders.push_back(hs.session->GetOutputNameAllocated(i, hs.alloc));
        hs.output_names.push_back(hs.output_name_holders.back().get());
    }
}

inline DemucsRunner::DemucsRunner(const ModelManifest &mm,
                                  const DemucsConfig &cfg,
                                  Ort::Env &env)
    : mm_(mm), cfg_(cfg), env_(env) {
    source_names_ = canonical_sources(cfg_.variant);

    auto find = [&](const std::string &k) -> const ModelEntry * {
        auto it = mm_.models.find(k);
        return it == mm_.models.end() ? nullptr : &it->second;
    };

    std::vector<const ModelEntry *> picks;
    if (cfg_.variant == DemucsVariant::FT || cfg_.variant == DemucsVariant::Default) {
        for (int i = 0; i < 4; ++i) {
            const auto *e = find("htdemucs_ft_head" + std::to_string(i));
            if (!e) throw std::runtime_error("htdemucs_ft.head" + std::to_string(i) + " missing");
            picks.push_back(e);
        }
        // Per-head specialist weights per stemforge/_vendor/demucs_patched
        // and A0 README: I_4 — head i emits only source i.
        bag_weights_ = {{1, 0, 0, 0}, {0, 1, 0, 0}, {0, 0, 1, 0}, {0, 0, 0, 1}};
    } else if (cfg_.variant == DemucsVariant::SixSource) {
        const auto *e = find("htdemucs_6s");
        if (!e) throw std::runtime_error("htdemucs_6s missing");
        picks.push_back(e);
        bag_weights_ = {{1, 1, 1, 1, 1, 1}};
    } else {
        const auto *e = find("htdemucs");
        if (!e) throw std::runtime_error("htdemucs missing");
        picks.push_back(e);
        bag_weights_ = {{1, 1, 1, 1}};
    }

    heads_.reserve(picks.size());
    for (const auto *e : picks) {
        auto hs = std::make_unique<HeadSession>();
        build_session(*hs, *e);
        heads_.push_back(std::move(hs));
    }
}

inline std::vector<std::vector<std::vector<float>>>
DemucsRunner::run_segment(const std::vector<std::vector<float>> &mix_seg) const {
    int C = static_cast<int>(mix_seg.size());
    int N = static_cast<int>(mix_seg[0].size());
    if (N != kDemucsSegmentSamples)
        throw std::runtime_error("run_segment: expected segment_samples="
                                 + std::to_string(kDemucsSegmentSamples));

    // 1. STFT + CAC-pack
    std::vector<std::complex<float>> z_complex;
    int Fq = 0, T = 0;
    apply_stft(mix_seg, z_complex, Fq, T);
    std::vector<float> z_cac;
    pack_cac(z_complex, C, Fq, T, z_cac);

    // 2. Build OrtValue for mix and z_cac — shared across all heads.
    std::vector<float> mix_flat(static_cast<size_t>(C) * N);
    for (int c = 0; c < C; ++c)
        std::memcpy(mix_flat.data() + static_cast<size_t>(c) * N,
                    mix_seg[c].data(), N * sizeof(float));

    auto mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    std::array<int64_t, 3> mix_shape = {1, C, N};
    std::array<int64_t, 4> zcac_shape = {1, 2 * C, Fq, T};
    Ort::Value mix_val = Ort::Value::CreateTensor<float>(
        mem, mix_flat.data(), mix_flat.size(), mix_shape.data(), mix_shape.size());
    Ort::Value zcac_val = Ort::Value::CreateTensor<float>(
        mem, z_cac.data(), z_cac.size(), zcac_shape.data(), zcac_shape.size());

    int S = static_cast<int>(source_names_.size());
    int H = static_cast<int>(heads_.size());

    // accum: (S, C, N) for combined time + freq branches, weighted combine.
    std::vector<std::vector<std::vector<float>>> combined(
        S, std::vector<std::vector<float>>(C, std::vector<float>(N, 0.0f)));
    std::vector<float> denom(S, 0.0f);
    for (int h = 0; h < H; ++h) for (int s = 0; s < S; ++s)
        denom[s] += bag_weights_[h][s];
    for (float &d : denom) if (d == 0.0f) d = 1.0f;

    for (int h = 0; h < H; ++h) {
        auto &hs = *heads_[h];
        // Two inputs, two outputs.
        std::array<Ort::Value, 2> inputs{std::move(mix_val), std::move(zcac_val)};
        // ORT takes inputs by raw pointers to Value; copies by pointer, not ownership.
        // Recreate views — OrtValue move invalidates; do it fresh each iteration.

        // (recreate each iter because Run consumes references)
        Ort::Value local_mix = Ort::Value::CreateTensor<float>(
            mem, mix_flat.data(), mix_flat.size(), mix_shape.data(), mix_shape.size());
        Ort::Value local_zcac = Ort::Value::CreateTensor<float>(
            mem, z_cac.data(), z_cac.size(), zcac_shape.data(), zcac_shape.size());
        std::array<Ort::Value, 2> in_arr{std::move(local_mix), std::move(local_zcac)};

        auto out = hs.session->Run(Ort::RunOptions{nullptr},
                                   hs.input_names.data(), in_arr.data(), in_arr.size(),
                                   hs.output_names.data(), hs.output_names.size());

        // Expect outputs: time_out (1, S, C, N), zout_cac (1, S, 2C, Fq, T)
        auto time_info = out[0].GetTensorTypeAndShapeInfo();
        auto zcac_info = out[1].GetTensorTypeAndShapeInfo();
        auto time_shape = time_info.GetShape();
        auto zcac_shape_out = zcac_info.GetShape();
        if (time_shape.size() != 4 || zcac_shape_out.size() != 5)
            throw std::runtime_error("demucs: unexpected output rank");
        int Sh = static_cast<int>(time_shape[1]);
        int Cout = static_cast<int>(time_shape[2]);
        int Nout = static_cast<int>(time_shape[3]);
        const float *time_out = out[0].GetTensorData<float>();
        const float *zout_cac = out[1].GetTensorData<float>();

        std::vector<std::vector<std::complex<float>>> per_src;
        unpack_cac(zout_cac, Sh, 2 * C, Fq, T, per_src);

        for (int s = 0; s < Sh; ++s) {
            auto x_freq = apply_istft(per_src[s], C, Fq, T, N);
            float w = (s < static_cast<int>(bag_weights_[h].size()))
                      ? bag_weights_[h][s] : 0.0f;
            if (w == 0.0f) continue;
            for (int c = 0; c < Cout; ++c) {
                const float *trow = time_out
                    + ((static_cast<size_t>(s) * Cout + c) * Nout);
                for (int n = 0; n < Nout && n < N; ++n) {
                    combined[s][c][n] += w * (trow[n] + x_freq[c][n]);
                }
            }
        }
    }

    for (int s = 0; s < S; ++s) {
        float inv = 1.0f / denom[s];
        for (int c = 0; c < C; ++c)
            for (int n = 0; n < N; ++n) combined[s][c][n] *= inv;
    }
    return combined;
}

inline DemucsStems
DemucsRunner::run(const std::vector<std::vector<float>> &mix,
                  const std::function<void(double, const std::string &)> &progress_cb) const {
    if (mix.empty() || mix.size() > 2)
        throw std::runtime_error("demucs: expected mono or stereo mix");
    int C = 2;
    std::vector<std::vector<float>> stereo(2);
    if (mix.size() == 1) { stereo[0] = mix[0]; stereo[1] = mix[0]; }
    else { stereo = mix; }

    int S = static_cast<int>(source_names_.size());
    int total = static_cast<int>(stereo[0].size());
    int hop = static_cast<int>(kDemucsSegmentSamples * (1.0f - kOverlap));

    DemucsStems out;
    out.source_names = source_names_;
    out.data.assign(S, std::vector<std::vector<float>>(C, std::vector<float>(total, 0.0f)));
    std::vector<float> weight(total, 0.0f);

    // Triangular window for overlap-add.
    std::vector<float> win(kDemucsSegmentSamples);
    int half = kDemucsSegmentSamples / 2;
    for (int i = 0; i < kDemucsSegmentSamples; ++i) {
        win[i] = static_cast<float>(1.0 - std::abs(i - half) / static_cast<double>(half));
    }

    int n_segments = static_cast<int>(std::ceil(static_cast<double>(total) / hop));
    for (int seg = 0; seg < n_segments; ++seg) {
        int start = seg * hop;
        if (start >= total) break;
        int end = std::min(start + kDemucsSegmentSamples, total);
        std::vector<std::vector<float>> mix_seg(C, std::vector<float>(kDemucsSegmentSamples, 0.0f));
        for (int c = 0; c < C; ++c)
            std::copy(stereo[c].begin() + start, stereo[c].begin() + end,
                      mix_seg[c].begin());

        auto seg_stems = run_segment(mix_seg);

        int seg_len = end - start;
        for (int s = 0; s < S; ++s) {
            for (int c = 0; c < C; ++c) {
                for (int n = 0; n < seg_len; ++n) {
                    out.data[s][c][start + n] += win[n] * seg_stems[s][c][n];
                }
            }
        }
        for (int n = 0; n < seg_len; ++n) weight[start + n] += win[n];

        if (progress_cb) {
            double pct = 100.0 * (seg + 1) / n_segments;
            progress_cb(pct, "segment " + std::to_string(seg + 1) + "/" + std::to_string(n_segments));
        }
    }

    for (int s = 0; s < S; ++s)
        for (int c = 0; c < C; ++c)
            for (int n = 0; n < total; ++n)
                if (weight[n] > 1e-8f) out.data[s][c][n] /= weight[n];

    return out;
}

} // namespace sf
