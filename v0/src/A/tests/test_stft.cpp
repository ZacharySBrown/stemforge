// STFT/iSTFT round-trip: apply_stft → pack_cac → unpack_cac → apply_istft
// should reconstruct a moderate-length input to high accuracy. Tests the
// DSP primitives with no ONNX session.

#include <cmath>
#include <random>
#include <vector>

#include "test_framework.hpp"
#include "sf_stft.hpp"
#include "sf_demucs.hpp"  // for kDemucsSegmentSamples

TEST(stft_pack_unpack_roundtrip_bits) {
    // Build small complex spectrogram.
    int C = 2, F = 16, T = 8;
    std::vector<std::complex<float>> z(static_cast<size_t>(C) * F * T);
    std::mt19937 g(1234);
    std::uniform_real_distribution<float> u(-1.0, 1.0);
    for (auto &v : z) v = {u(g), u(g)};

    std::vector<float> packed;
    sf::pack_cac(z, C, F, T, packed);
    CHECK_EQ(packed.size(), static_cast<size_t>(2 * C) * F * T);

    // Feed as S=1 "head output" and unpack.
    std::vector<float> as_head = packed; // (1 * 2C * F * T)
    std::vector<std::vector<std::complex<float>>> per_src;
    sf::unpack_cac(as_head.data(), 1, 2 * C, F, T, per_src);
    CHECK_EQ(per_src.size(), 1u);
    CHECK_EQ(per_src[0].size(), static_cast<size_t>(C) * F * T);

    for (size_t i = 0; i < z.size(); ++i) {
        CHECK(std::abs(per_src[0][i].real() - z[i].real()) < 1e-6);
        CHECK(std::abs(per_src[0][i].imag() - z[i].imag()) < 1e-6);
    }
}

TEST(stft_then_istft_reconstructs_signal) {
    // Build a simple sinusoidal pattern at 44.1k mono->stereo, run STFT
    // then iSTFT, check middle-of-signal reconstruction quality.
    int sr = 44100;
    int length = sf::kDemucsSegmentSamples; // so framing matches _spec
    std::vector<std::vector<float>> mix(2, std::vector<float>(length, 0.0f));
    for (int i = 0; i < length; ++i) {
        float t = static_cast<float>(i) / sr;
        mix[0][i] = 0.1f * std::sin(2.0f * static_cast<float>(M_PI) * 440.0f * t);
        mix[1][i] = 0.1f * std::sin(2.0f * static_cast<float>(M_PI) * 660.0f * t);
    }
    std::vector<std::complex<float>> z;
    int Fq = 0, T = 0;
    sf::apply_stft(mix, z, Fq, T);
    CHECK_EQ(Fq, sf::kFreqBinsCropped);
    CHECK(T > 0);

    auto recon = sf::apply_istft(z, 2, Fq, T, length);
    CHECK_EQ(recon.size(), 2u);
    CHECK_EQ(recon[0].size(), static_cast<size_t>(length));

    // Check centre region — reflect pad edges can wobble.
    int margin = 16384; // skip first/last 16k samples
    double err = 0.0, ref = 0.0;
    for (int c = 0; c < 2; ++c) {
        for (int i = margin; i < length - margin; ++i) {
            double d = recon[c][i] - mix[c][i];
            err += d * d;
            ref += mix[c][i] * mix[c][i];
        }
    }
    double snr_db = 10.0 * std::log10(ref / std::max(err, 1e-30));
    std::fprintf(stderr, "    stft roundtrip SNR = %.1f dB\n", snr_db);
    CHECK(snr_db > 40.0); // generous — we're testing framing, not golden parity
}
