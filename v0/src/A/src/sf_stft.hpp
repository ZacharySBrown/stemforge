// sf_stft.hpp — STFT/iSTFT matching demucs.htdemucs._spec/_ispec.
//
// Driven by the stft_params block in A0's manifest.json:
//     n_fft = 4096, hop_length = 1024, window = hann,
//     center = True, pad_mode = reflect, onesided = True.
//
// Implements the externalised contract documented in
// stemforge/_vendor/demucs_patched.HTDemucs.forward_from_spec_cac:
//
//     apply_stft(mix_padded):
//         le = ceil(N / hop)
//         pad = hop // 2 * 3
//         x = reflect_pad1d(mix, (pad, pad + le*hop - N))
//         z = spectro(x, n_fft, hop)[..., :-1, :]   # drops Nyquist bin
//         z = z[..., 2 : 2 + le]                    # centre-crop frames
//         return z                                  # (..., Fq, le) complex
//
//     apply_istft(zout, length):
//         z = pad(zout, (0,0,0,1))          # restore Nyquist
//         z = pad(z, (2,2))                 # pad frames
//         pad = hop//2*3
//         le = hop * ceil(length/hop) + 2*pad
//         x = ispectro(z, hop, length=le)
//         return x[..., pad : pad+length]
//
// demucs.spec.spectro/ispectro use torch.stft/istft with center=True,
// reflect pad, normalized=False, onesided=True, window=hann_window(n_fft).
//
// Output layout for CAC pack (view_as_real → permute 0,1,4,2,3 →
// reshape B, 2C, F, T):
//     z_cac[b, 2*c + 0, f, t] = real(z[b, c, f, t])
//     z_cac[b, 2*c + 1, f, t] = imag(z[b, c, f, t])
// For stereo (C=2) the 4 channels are [re_L, im_L, re_R, im_R].

#pragma once

#include <cmath>
#include <complex>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>

#include "kiss_fftr.h"

namespace sf {

constexpr int kNFFT = 4096;
constexpr int kHop = 1024;
constexpr int kFreqBinsFull = kNFFT / 2 + 1; // 2049 (includes Nyquist)
constexpr int kFreqBinsCropped = kNFFT / 2;  // 2048 (Nyquist dropped per _spec)

inline const float *hann_window() {
    // Periodic hann window matching torch.hann_window(n_fft, periodic=True).
    static std::vector<float> w = [] {
        std::vector<float> v(kNFFT);
        for (int i = 0; i < kNFFT; ++i)
            v[i] = 0.5f * (1.0f - std::cos(2.0f * static_cast<float>(M_PI) * i / kNFFT));
        return v;
    }();
    return w.data();
}

// Reflect-pad a 1-D signal by (left, right) samples, SciPy / torch semantics.
inline std::vector<float> reflect_pad1d(const float *x, size_t n,
                                        int left, int right) {
    std::vector<float> out(n + left + right);
    // Body
    std::memcpy(out.data() + left, x, n * sizeof(float));
    // Left reflect (x[0] is not duplicated; reflection starts at x[1]).
    for (int i = 0; i < left; ++i) {
        int src = left - i;
        if (src >= static_cast<int>(n)) src = static_cast<int>(n) - 1;
        if (src < 0) src = 0;
        out[i] = x[src];
    }
    // Right reflect
    for (int i = 0; i < right; ++i) {
        int src = static_cast<int>(n) - 2 - i;
        if (src < 0) src = 0;
        if (src >= static_cast<int>(n)) src = static_cast<int>(n) - 1;
        out[left + n + i] = x[src];
    }
    return out;
}

// Forward STFT matching demucs.apply_stft. Returns a column-major
// (channels, F=2048, T=le) complex tensor as a flat vector of
// std::complex<float>. Input `mix_padded` is (channels, samples).
//
// `mix_padded` is the caller's already-padded-to-segment-length mix
// (not the reflect-padded version — that happens inside).
inline void apply_stft(const std::vector<std::vector<float>> &mix_padded,
                       std::vector<std::complex<float>> &out,
                       int &Fq_out, int &T_out) {
    if (mix_padded.empty()) throw std::runtime_error("apply_stft: empty mix");
    int C = static_cast<int>(mix_padded.size());
    size_t N = mix_padded[0].size();
    int le = static_cast<int>(std::ceil(static_cast<double>(N) / kHop));
    int pad = kHop / 2 * 3;

    // Total padded length per demucs.spec.spectro: pad left + N + (pad + le*hop - N).
    int right_pad = pad + le * kHop - static_cast<int>(N);
    // STFT of reflect-padded signal has n_frames = (length - n_fft) / hop + 1
    // when length matches center-padded torch.stft semantics. demucs.spec
    // does its OWN reflect pad + torch.stft(..., center=True) so the full
    // framing is: stft(reflect_pad(x, pad, pad + le*hop - N)) with
    // torch's own center=True adding another n_fft//2 on each side inside.
    //
    // We fold both pads into one explicit reflect pad and call stft with
    // center=False to keep the framing identical and avoid double-padding.
    //
    // Effective padded length = N + pad + (pad + le*hop - N) + 2*(n_fft/2)
    //                        = 2*pad + le*hop + n_fft
    // Frame count with center=False: floor((padded_len - n_fft) / hop) + 1
    //                              = floor((2*pad + le*hop) / hop) + 1
    //                              = le + 2*pad/hop + 1 = le + 7
    // torch.stft with center=True on the non-doubled input gives the same
    // count. Demucs crops to [..., 2 : 2 + le] afterwards, so final T = le.

    int T_full = 0;

    kiss_fftr_cfg cfg = kiss_fftr_alloc(kNFFT, 0, nullptr, nullptr);
    if (!cfg) throw std::runtime_error("kiss_fftr_alloc failed");

    std::vector<std::vector<std::complex<float>>> per_chan(C);
    const float *win = hann_window();

    for (int c = 0; c < C; ++c) {
        auto padded_once = reflect_pad1d(mix_padded[c].data(), N, pad, right_pad);
        // Emulate torch.stft(center=True, pad_mode="reflect") by reflect-padding
        // by n_fft//2 on each side, then running strided DFT with hop.
        auto padded = reflect_pad1d(padded_once.data(), padded_once.size(),
                                    kNFFT / 2, kNFFT / 2);
        int T = static_cast<int>((padded.size() - kNFFT) / kHop) + 1;
        if (c == 0) T_full = T;
        per_chan[c].assign(static_cast<size_t>(T) * kFreqBinsCropped,
                           std::complex<float>(0, 0));

        std::vector<float> frame(kNFFT);
        std::vector<kiss_fft_cpx> spec(kFreqBinsFull);

        for (int t = 0; t < T; ++t) {
            const float *src = padded.data() + static_cast<size_t>(t) * kHop;
            for (int i = 0; i < kNFFT; ++i) frame[i] = src[i] * win[i];
            kiss_fftr(cfg, frame.data(), spec.data());
            // Drop Nyquist bin (kFreqBinsFull - 1).
            for (int f = 0; f < kFreqBinsCropped; ++f)
                per_chan[c][static_cast<size_t>(t) * kFreqBinsCropped + f] =
                    std::complex<float>(spec[f].r, spec[f].i);
        }
    }
    kiss_fftr_free(cfg);

    // Centre-crop frames: [..., 2 : 2 + le]
    int T_le = le;
    if (T_full < 2 + T_le) throw std::runtime_error("apply_stft: frame budget too small");

    // Output layout: (C, F, T_le) contiguous in T.
    out.assign(static_cast<size_t>(C) * kFreqBinsCropped * T_le,
               std::complex<float>(0, 0));
    for (int c = 0; c < C; ++c) {
        for (int t = 0; t < T_le; ++t) {
            int src_t = t + 2;
            for (int f = 0; f < kFreqBinsCropped; ++f) {
                out[static_cast<size_t>(c) * kFreqBinsCropped * T_le
                    + static_cast<size_t>(f) * T_le + t] =
                    per_chan[c][static_cast<size_t>(src_t) * kFreqBinsCropped + f];
            }
        }
    }
    Fq_out = kFreqBinsCropped;
    T_out  = T_le;
}

// CAC-pack: stereo complex (C=2, F, T) → real (2C=4, F, T) as
//   [re_L, im_L, re_R, im_R].
// Output layout: contiguous in T, then F, then channel.
inline void pack_cac(const std::vector<std::complex<float>> &z_complex,
                     int C, int F, int T,
                     std::vector<float> &z_cac) {
    z_cac.assign(static_cast<size_t>(2 * C) * F * T, 0.0f);
    for (int c = 0; c < C; ++c) {
        size_t src_base = static_cast<size_t>(c) * F * T;
        size_t re_ch = 2 * c;
        size_t im_ch = 2 * c + 1;
        for (int f = 0; f < F; ++f) {
            for (int t = 0; t < T; ++t) {
                const auto &z = z_complex[src_base + static_cast<size_t>(f) * T + t];
                z_cac[re_ch * F * T + static_cast<size_t>(f) * T + t] = z.real();
                z_cac[im_ch * F * T + static_cast<size_t>(f) * T + t] = z.imag();
            }
        }
    }
}

// CAC-unpack: (S, 2C, F, T) → (S, C, F, T) complex.
inline void unpack_cac(const float *zout_cac, int S, int C_times_2,
                       int F, int T,
                       std::vector<std::vector<std::complex<float>>> &per_source) {
    int C = C_times_2 / 2;
    per_source.assign(S, {});
    for (int s = 0; s < S; ++s) {
        per_source[s].assign(static_cast<size_t>(C) * F * T,
                             std::complex<float>(0, 0));
        for (int c = 0; c < C; ++c) {
            size_t re_ch = static_cast<size_t>(2 * c);
            size_t im_ch = static_cast<size_t>(2 * c + 1);
            size_t s_base = static_cast<size_t>(s) * C_times_2 * F * T;
            size_t dst_base = static_cast<size_t>(c) * F * T;
            for (int f = 0; f < F; ++f) {
                for (int t = 0; t < T; ++t) {
                    float re = zout_cac[s_base + re_ch * F * T + static_cast<size_t>(f) * T + t];
                    float im = zout_cac[s_base + im_ch * F * T + static_cast<size_t>(f) * T + t];
                    per_source[s][dst_base + static_cast<size_t>(f) * T + t] =
                        std::complex<float>(re, im);
                }
            }
        }
    }
}

// Inverse STFT matching demucs.apply_istft. Input z is (C, F=2048, T).
// Expands to (C, F+1=2049, T+2+2=T+4) before iSTFT then slice to length.
inline std::vector<std::vector<float>>
apply_istft(const std::vector<std::complex<float>> &z_complex,
            int C, int F, int T, int length) {
    if (F != kFreqBinsCropped)
        throw std::runtime_error("apply_istft: unexpected F");
    // Restore Nyquist bin (append zeros) and pad frames by (2,2).
    int F_full = F + 1;                // 2049
    int T_padded = T + 4;              // pad (2,2) in frames
    int pad = kHop / 2 * 3;
    int le = kHop * static_cast<int>(std::ceil(static_cast<double>(length) / kHop))
             + 2 * pad;

    // Synthesis-window-corrected inverse STFT (center=True, COLA=true for
    // hann/hop=N/4). We'll emulate torch.istft by overlap-add with
    // windowed IFFTs and divide by window envelope.
    int output_len_full = (T_padded - 1) * kHop + kNFFT; // length before centre trim
    std::vector<std::vector<float>> out(C, std::vector<float>(output_len_full, 0.0f));
    std::vector<float> env(output_len_full, 0.0f);

    const float *win = hann_window();
    kiss_fftr_cfg icfg = kiss_fftr_alloc(kNFFT, 1, nullptr, nullptr);
    if (!icfg) throw std::runtime_error("kiss_fftr_alloc(inverse) failed");

    // Envelope is the same for all channels; accumulate once.
    bool env_built = false;

    for (int c = 0; c < C; ++c) {
        std::vector<float> time_frame(kNFFT, 0.0f);
        std::vector<kiss_fft_cpx> spec(F_full);
        for (int t = 0; t < T_padded; ++t) {
            int src_t = t - 2;
            for (int f = 0; f < F_full; ++f) {
                if (src_t < 0 || src_t >= T || f >= F) {
                    spec[f].r = 0.0f;
                    spec[f].i = 0.0f;
                } else {
                    const auto &z = z_complex[static_cast<size_t>(c) * F * T
                                              + static_cast<size_t>(f) * T + src_t];
                    spec[f].r = z.real();
                    spec[f].i = z.imag();
                }
            }
            kiss_fftri(icfg, spec.data(), time_frame.data());
            // kiss_fftri returns un-normalized — divide by N.
            for (int i = 0; i < kNFFT; ++i) time_frame[i] /= kNFFT;

            // OLA with synthesis hann window (same as analysis for torch.istft).
            int start = t * kHop;
            for (int i = 0; i < kNFFT; ++i) {
                out[c][start + i] += time_frame[i] * win[i];
                if (!env_built) env[start + i] += win[i] * win[i];
            }
        }
        env_built = true;
    }
    kiss_fftr_free(icfg);

    // Normalize by envelope (avoid div-by-zero edges).
    for (int c = 0; c < C; ++c) {
        for (int i = 0; i < output_len_full; ++i) {
            if (env[i] > 1e-11f) out[c][i] /= env[i];
        }
    }

    // torch.istft centre-trim removes n_fft/2 from each end.
    int trim = kNFFT / 2;
    int after_center_len = output_len_full - 2 * trim;
    if (after_center_len < 0) after_center_len = 0;
    // Then demucs slices [pad : pad+length].
    std::vector<std::vector<float>> trimmed(C);
    for (int c = 0; c < C; ++c) {
        auto &src = out[c];
        // effective signal after torch.istft centre-trim is src[trim : trim+le]
        int istft_end = std::min(trim + le, static_cast<int>(src.size()));
        int demucs_start = trim + pad;
        int demucs_end   = demucs_start + length;
        if (demucs_end > istft_end) demucs_end = istft_end;
        if (demucs_start < 0) demucs_start = 0;
        if (demucs_start > demucs_end) demucs_start = demucs_end;
        trimmed[c].assign(src.begin() + demucs_start, src.begin() + demucs_end);
        if (static_cast<int>(trimmed[c].size()) < length)
            trimmed[c].resize(length, 0.0f);
    }
    return trimmed;
}

} // namespace sf
