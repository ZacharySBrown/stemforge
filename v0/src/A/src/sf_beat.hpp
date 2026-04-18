// sf_beat.hpp — a minimum-viable port of librosa-style beat tracking.
//
// librosa.beat.beat_track is a two-stage pipeline:
//   1. Estimate global tempo from a mel-spectrogram onset strength
//      envelope's autocorrelation (librosa.beat.tempo).
//   2. Dynamic-programming beat tracker over the onset envelope given a
//      target tempo (Ellis 2007).
//
// This is a pragmatic port: we compute a spectral-flux onset envelope
// on a mono downmix at 22050 Hz (librosa's default beat-track sr), then:
//   - Tempo via autocorrelation of the onset envelope, peak-picked
//     between 40 and 240 BPM with a 120-BPM prior (log-normal, std=1
//     octave).
//   - Beats via the Ellis DP: max over t of (cum_score[prev] +
//     -|log(period / (t - prev))|^2 * lambda) + onset[t], lambda=100.
//
// This is NOT bit-for-bit-identical to librosa; we accept ±1 BPM and a
// beat-grid that differs by up to a hop (23 ms @ 22050, hop=512). The
// manifest's `bpm` field tolerates this (Python rounds to 2dp; consumers
// compare integer BPM). The slice boundary offsets flow through the bar
// slicer; ±1 hop per bar is audibly fine.
//
// If G tests demand tighter parity, swap this for an aubio-wrapped
// tempo/beat call.

#pragma once

#include <cmath>
#include <cstring>
#include <numeric>
#include <stdexcept>
#include <vector>

#include "kiss_fftr.h"

namespace sf {

constexpr int kBeatSR = 22050;
constexpr int kBeatNFFT = 2048;
constexpr int kBeatHop = 512;
constexpr int kBeatMel = 128;

// librosa.core.resample-equivalent simple linear resampler from any input SR
// to kBeatSR. Quality is fine for onset detection; do NOT use for audio output.
inline std::vector<float> resample_linear(const float *x, size_t n_in,
                                          int sr_in, int sr_out) {
    if (sr_in == sr_out) return std::vector<float>(x, x + n_in);
    double ratio = static_cast<double>(sr_out) / sr_in;
    size_t n_out = static_cast<size_t>(std::floor(n_in * ratio));
    std::vector<float> out(n_out);
    for (size_t i = 0; i < n_out; ++i) {
        double t = static_cast<double>(i) / ratio;
        size_t lo = static_cast<size_t>(std::floor(t));
        size_t hi = std::min(lo + 1, n_in - 1);
        double a = t - lo;
        out[i] = static_cast<float>(x[lo] * (1.0 - a) + x[hi] * a);
    }
    return out;
}

// Build a mel filter bank (librosa "slaney" norm, htk=False). Simplified
// to match the shape and normalization roughly — exact parity would need
// librosa's Slaney mel code. For onset strength, spectrum shaping need
// not be exact.
inline std::vector<std::vector<float>> mel_filterbank(int sr, int n_fft,
                                                      int n_mels) {
    auto hz_to_mel = [](double hz) {
        // HTK mel
        return 2595.0 * std::log10(1.0 + hz / 700.0);
    };
    auto mel_to_hz = [](double m) {
        return 700.0 * (std::pow(10.0, m / 2595.0) - 1.0);
    };
    double fmin = 0.0, fmax = sr / 2.0;
    double mmin = hz_to_mel(fmin), mmax = hz_to_mel(fmax);
    std::vector<double> mel_points(n_mels + 2);
    for (int i = 0; i < n_mels + 2; ++i)
        mel_points[i] = mmin + (mmax - mmin) * i / (n_mels + 1);
    std::vector<double> hz_points(n_mels + 2);
    for (int i = 0; i < n_mels + 2; ++i) hz_points[i] = mel_to_hz(mel_points[i]);
    std::vector<double> bin_f(n_mels + 2);
    for (int i = 0; i < n_mels + 2; ++i)
        bin_f[i] = hz_points[i] * n_fft / sr;

    int F = n_fft / 2 + 1;
    std::vector<std::vector<float>> fb(n_mels, std::vector<float>(F, 0.0f));
    for (int m = 1; m <= n_mels; ++m) {
        double lo = bin_f[m - 1], ce = bin_f[m], hi = bin_f[m + 1];
        for (int k = 0; k < F; ++k) {
            double kf = k;
            double v = 0.0;
            if (kf > lo && kf <= ce) v = (kf - lo) / (ce - lo);
            else if (kf > ce && kf < hi) v = (hi - kf) / (hi - ce);
            fb[m - 1][k] = static_cast<float>(v * 2.0 / (hi - lo + 1e-9));
        }
    }
    return fb;
}

// Compute onset strength envelope ~ librosa.onset.onset_strength default:
//   mel_spec (power, n_fft=2048, hop=512, n_mels=128)
//   -> log (power_to_db)
//   -> diff along time, half-wave rectify, mean across mel bins.
inline std::vector<float> onset_strength(const std::vector<float> &x_mono,
                                         int sr) {
    if (static_cast<int>(x_mono.size()) < kBeatNFFT) return {};

    // Pad signal for center STFT.
    std::vector<float> padded(x_mono.size() + kBeatNFFT, 0.0f);
    std::memcpy(padded.data() + kBeatNFFT / 2, x_mono.data(),
                x_mono.size() * sizeof(float));
    // Reflect pad edges.
    for (int i = 0; i < kBeatNFFT / 2; ++i) {
        padded[kBeatNFFT / 2 - 1 - i] = x_mono[std::min(i + 1, static_cast<int>(x_mono.size()) - 1)];
        int src = static_cast<int>(x_mono.size()) - 2 - i;
        if (src < 0) src = 0;
        padded[kBeatNFFT / 2 + x_mono.size() + i] = x_mono[src];
    }

    int T = (static_cast<int>(padded.size()) - kBeatNFFT) / kBeatHop + 1;
    int F = kBeatNFFT / 2 + 1;
    kiss_fftr_cfg cfg = kiss_fftr_alloc(kBeatNFFT, 0, nullptr, nullptr);
    if (!cfg) throw std::runtime_error("kiss_fftr_alloc failed (onset)");

    // Hann window
    std::vector<float> win(kBeatNFFT);
    for (int i = 0; i < kBeatNFFT; ++i)
        win[i] = 0.5f * (1.0f - std::cos(2.0f * static_cast<float>(M_PI) * i / kBeatNFFT));

    auto fb = mel_filterbank(sr, kBeatNFFT, kBeatMel);

    std::vector<std::vector<float>> mel_db(T, std::vector<float>(kBeatMel, 0.0f));

    std::vector<float> frame(kBeatNFFT);
    std::vector<kiss_fft_cpx> spec(F);
    std::vector<float> power(F);
    for (int t = 0; t < T; ++t) {
        const float *src = padded.data() + t * kBeatHop;
        for (int i = 0; i < kBeatNFFT; ++i) frame[i] = src[i] * win[i];
        kiss_fftr(cfg, frame.data(), spec.data());
        for (int f = 0; f < F; ++f)
            power[f] = spec[f].r * spec[f].r + spec[f].i * spec[f].i;

        for (int m = 0; m < kBeatMel; ++m) {
            float v = 0.0f;
            for (int f = 0; f < F; ++f) v += fb[m][f] * power[f];
            mel_db[t][m] = 10.0f * std::log10(std::max(v, 1e-10f));
        }
    }
    kiss_fftr_free(cfg);

    // Onset strength: mean positive diff across mel.
    std::vector<float> onset(T, 0.0f);
    for (int t = 1; t < T; ++t) {
        float acc = 0.0f;
        for (int m = 0; m < kBeatMel; ++m) {
            float d = mel_db[t][m] - mel_db[t - 1][m];
            if (d > 0) acc += d;
        }
        onset[t] = acc / kBeatMel;
    }
    // Normalize mean/std.
    double mean = std::accumulate(onset.begin(), onset.end(), 0.0) / onset.size();
    double var = 0.0;
    for (float v : onset) var += (v - mean) * (v - mean);
    var /= onset.size();
    double sd = std::sqrt(std::max(var, 1e-12));
    for (auto &v : onset) v = static_cast<float>((v - mean) / sd);
    return onset;
}

// Estimate tempo via autocorrelation of the onset envelope with a
// log-normal prior centred at prior_bpm (default 120) with std = 1 octave.
inline double estimate_tempo(const std::vector<float> &onset, int sr, int hop,
                             double prior_bpm = 120.0,
                             double bpm_min = 40.0, double bpm_max = 240.0) {
    if (onset.size() < 64) return prior_bpm;

    int N = static_cast<int>(onset.size());
    // Autocorrelation up to lag corresponding to bpm_min.
    double frame_rate = static_cast<double>(sr) / hop;
    int lag_min = static_cast<int>(std::floor(60.0 / bpm_max * frame_rate));
    int lag_max = static_cast<int>(std::ceil(60.0 / bpm_min * frame_rate));
    lag_max = std::min(lag_max, N - 1);

    // Mean-subtract to match librosa's "autocorrelation of centered" semantics.
    double mean = std::accumulate(onset.begin(), onset.end(), 0.0) / N;
    std::vector<double> o(N);
    for (int i = 0; i < N; ++i) o[i] = onset[i] - mean;

    double best = -1e18;
    int best_lag = lag_min;
    for (int lag = lag_min; lag <= lag_max; ++lag) {
        double acc = 0.0;
        for (int i = 0; i < N - lag; ++i) acc += o[i] * o[i + lag];
        double bpm = 60.0 * frame_rate / lag;
        // log-normal prior, std = 1 octave = log(2).
        double log_ratio = std::log(bpm / prior_bpm);
        double prior = -0.5 * log_ratio * log_ratio / (std::log(2.0) * std::log(2.0));
        double score = acc + prior * std::abs(acc); // scale prior to acc magnitude
        if (score > best) { best = score; best_lag = lag; }
    }
    return 60.0 * frame_rate / best_lag;
}

// Ellis DP beat tracker. Returns beat frame indices in the onset envelope.
inline std::vector<int> track_beats_dp(const std::vector<float> &onset,
                                       double bpm, int sr, int hop,
                                       double lambda = 100.0) {
    int N = static_cast<int>(onset.size());
    if (N < 2 || bpm <= 0) return {};
    double frame_rate = static_cast<double>(sr) / hop;
    double period_frames = 60.0 / bpm * frame_rate;

    std::vector<double> score(N, -1e18);
    std::vector<int> back(N, -1);
    // Seed from the beginning — score[t] = onset[t] for any start
    // within the first period.
    int seed_end = std::min(N, static_cast<int>(std::ceil(period_frames)) + 1);
    for (int t = 0; t < seed_end; ++t) score[t] = onset[t];

    int win_lo = static_cast<int>(std::floor(period_frames * 0.5));
    int win_hi = static_cast<int>(std::ceil(period_frames * 2.0));

    for (int t = seed_end; t < N; ++t) {
        int lo = std::max(0, t - win_hi);
        int hi = std::max(0, t - win_lo);
        double best = -1e18; int best_prev = -1;
        for (int p = lo; p <= hi; ++p) {
            double dt = t - p;
            double err = std::log(dt / period_frames);
            double penalty = -lambda * err * err;
            double sc = score[p] + penalty;
            if (sc > best) { best = sc; best_prev = p; }
        }
        if (best_prev < 0) { score[t] = onset[t]; back[t] = -1; }
        else { score[t] = onset[t] + best; back[t] = best_prev; }
    }

    // Backtrace from global max in the last ~period window.
    int tail = std::max(0, N - static_cast<int>(std::ceil(period_frames)));
    int end = tail;
    double best = score[tail];
    for (int t = tail + 1; t < N; ++t) if (score[t] > best) { best = score[t]; end = t; }

    std::vector<int> beats;
    for (int t = end; t >= 0; t = back[t]) {
        beats.push_back(t);
        if (back[t] < 0) break;
    }
    std::reverse(beats.begin(), beats.end());
    return beats;
}

struct BeatResult {
    double bpm = 0.0;
    std::vector<double> beat_times_sec;
};

inline BeatResult detect_beats(const std::vector<float> &mono_44100) {
    auto mono = resample_linear(mono_44100.data(), mono_44100.size(), 44100, kBeatSR);
    auto onset = onset_strength(mono, kBeatSR);
    if (onset.empty()) return {};
    double bpm = estimate_tempo(onset, kBeatSR, kBeatHop);
    auto beat_frames = track_beats_dp(onset, bpm, kBeatSR, kBeatHop);
    BeatResult r;
    r.bpm = bpm;
    r.beat_times_sec.reserve(beat_frames.size());
    double frame_to_sec = static_cast<double>(kBeatHop) / kBeatSR;
    for (int f : beat_frames) r.beat_times_sec.push_back(f * frame_to_sec);
    return r;
}

} // namespace sf
