// sf_wav.hpp — minimal WAV read/write using macOS ExtAudioFile (system
// framework, no vendored deps). Handles common sample-rate conversion
// via ExtAudioFileSetProperty(kExtAudioFileProperty_ClientDataFormat),
// which gives us resample-on-read for free via AudioConverter.
//
// This replaces libsndfile + libsamplerate for v0 on macOS. If we ever
// port to Linux/Windows we'll swap in dr_wav + speexdsp or libsndfile+SRC.

#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <stdexcept>
#include <filesystem>

#include <AudioToolbox/AudioToolbox.h>

namespace sf {

namespace fs = std::filesystem;

struct WavData {
    std::vector<float> samples; // interleaved [L,R,L,R,...] if channels==2, else mono
    int channels = 0;
    int sample_rate = 0;
    size_t num_frames() const {
        return channels ? samples.size() / static_cast<size_t>(channels) : 0;
    }
};

// Read a WAV/AIFF/CAF/... file via ExtAudioFile, converting to float32
// interleaved at the requested target (sr=0 → native SR, channels=0 → native).
// If channels mismatches source (e.g. mono → stereo), we duplicate.
inline WavData read_audio(const fs::path &path, int target_sr = 44100,
                          int target_channels = 2) {
    WavData out;
    ExtAudioFileRef ref = nullptr;
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(
        kCFAllocatorDefault,
        reinterpret_cast<const UInt8 *>(path.c_str()),
        static_cast<CFIndex>(path.native().size()),
        false);
    if (!url) throw std::runtime_error("CFURL create failed: " + path.string());

    OSStatus st = ExtAudioFileOpenURL(url, &ref);
    CFRelease(url);
    if (st != noErr) throw std::runtime_error("ExtAudioFileOpen failed: " + std::to_string(st));

    // Source format (for channel-count fallback).
    AudioStreamBasicDescription src{};
    UInt32 sz = sizeof(src);
    ExtAudioFileGetProperty(ref, kExtAudioFileProperty_FileDataFormat, &sz, &src);

    int final_channels = target_channels > 0 ? target_channels : static_cast<int>(src.mChannelsPerFrame);
    int final_sr = target_sr > 0 ? target_sr : static_cast<int>(src.mSampleRate);

    AudioStreamBasicDescription client{};
    client.mFormatID = kAudioFormatLinearPCM;
    client.mFormatFlags = kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked;
    client.mSampleRate = final_sr;
    client.mChannelsPerFrame = static_cast<UInt32>(final_channels);
    client.mBitsPerChannel = 32;
    client.mFramesPerPacket = 1;
    client.mBytesPerFrame = 4 * client.mChannelsPerFrame;
    client.mBytesPerPacket = client.mBytesPerFrame;

    st = ExtAudioFileSetProperty(ref, kExtAudioFileProperty_ClientDataFormat,
                                 sizeof(client), &client);
    if (st != noErr) {
        ExtAudioFileDispose(ref);
        throw std::runtime_error("ExtAudioFileSetProperty(client) failed: " + std::to_string(st));
    }

    SInt64 total_frames = 0;
    sz = sizeof(total_frames);
    ExtAudioFileGetProperty(ref, kExtAudioFileProperty_FileLengthFrames, &sz, &total_frames);
    // With SR conversion, output frame count is approx total_frames * final_sr / src.mSampleRate
    size_t approx_out_frames = src.mSampleRate > 0
        ? static_cast<size_t>(static_cast<double>(total_frames) * final_sr / src.mSampleRate) + 4096
        : static_cast<size_t>(total_frames);

    out.samples.reserve(approx_out_frames * static_cast<size_t>(final_channels));
    out.channels = final_channels;
    out.sample_rate = final_sr;

    // Stream in chunks.
    const UInt32 kChunkFrames = 8192;
    std::vector<float> buf(kChunkFrames * static_cast<size_t>(final_channels));
    AudioBufferList abl;
    abl.mNumberBuffers = 1;
    abl.mBuffers[0].mNumberChannels = client.mChannelsPerFrame;
    abl.mBuffers[0].mDataByteSize = static_cast<UInt32>(buf.size() * sizeof(float));
    abl.mBuffers[0].mData = buf.data();

    while (true) {
        UInt32 frames = kChunkFrames;
        abl.mBuffers[0].mDataByteSize = static_cast<UInt32>(buf.size() * sizeof(float));
        st = ExtAudioFileRead(ref, &frames, &abl);
        if (st != noErr) {
            ExtAudioFileDispose(ref);
            throw std::runtime_error("ExtAudioFileRead failed: " + std::to_string(st));
        }
        if (frames == 0) break;
        out.samples.insert(out.samples.end(),
                           buf.begin(),
                           buf.begin() + static_cast<ptrdiff_t>(frames) * final_channels);
    }

    ExtAudioFileDispose(ref);
    return out;
}

// Write 24-bit PCM WAV (matches soundfile.write subtype="PCM_24").
inline void write_wav_pcm24(const fs::path &path, const float *interleaved,
                            size_t frames, int channels, int sample_rate) {
    AudioStreamBasicDescription out_fmt{};
    out_fmt.mFormatID = kAudioFormatLinearPCM;
    out_fmt.mFormatFlags = kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked;
    out_fmt.mSampleRate = sample_rate;
    out_fmt.mChannelsPerFrame = static_cast<UInt32>(channels);
    out_fmt.mBitsPerChannel = 24;
    out_fmt.mFramesPerPacket = 1;
    out_fmt.mBytesPerFrame = 3 * out_fmt.mChannelsPerFrame;
    out_fmt.mBytesPerPacket = out_fmt.mBytesPerFrame;

    CFURLRef url = CFURLCreateFromFileSystemRepresentation(
        kCFAllocatorDefault,
        reinterpret_cast<const UInt8 *>(path.c_str()),
        static_cast<CFIndex>(path.native().size()),
        false);
    if (!url) throw std::runtime_error("CFURL create failed: " + path.string());

    ExtAudioFileRef ref = nullptr;
    OSStatus st = ExtAudioFileCreateWithURL(url, kAudioFileWAVEType, &out_fmt,
                                            nullptr, kAudioFileFlags_EraseFile, &ref);
    CFRelease(url);
    if (st != noErr) throw std::runtime_error("ExtAudioFileCreate failed: " + std::to_string(st));

    AudioStreamBasicDescription client{};
    client.mFormatID = kAudioFormatLinearPCM;
    client.mFormatFlags = kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked;
    client.mSampleRate = sample_rate;
    client.mChannelsPerFrame = static_cast<UInt32>(channels);
    client.mBitsPerChannel = 32;
    client.mFramesPerPacket = 1;
    client.mBytesPerFrame = 4 * client.mChannelsPerFrame;
    client.mBytesPerPacket = client.mBytesPerFrame;

    st = ExtAudioFileSetProperty(ref, kExtAudioFileProperty_ClientDataFormat,
                                 sizeof(client), &client);
    if (st != noErr) {
        ExtAudioFileDispose(ref);
        throw std::runtime_error("ExtAudioFileSetProperty(client) failed: " + std::to_string(st));
    }

    AudioBufferList abl;
    abl.mNumberBuffers = 1;
    abl.mBuffers[0].mNumberChannels = static_cast<UInt32>(channels);
    abl.mBuffers[0].mDataByteSize = static_cast<UInt32>(frames * channels * sizeof(float));
    abl.mBuffers[0].mData = const_cast<float *>(interleaved);

    st = ExtAudioFileWrite(ref, static_cast<UInt32>(frames), &abl);
    ExtAudioFileDispose(ref);
    if (st != noErr) throw std::runtime_error("ExtAudioFileWrite failed: " + std::to_string(st));
}

// Helper: deinterleaved (channels, frames) → interleaved; then call write_wav_pcm24.
inline void write_wav_pcm24_deinterleaved(const fs::path &path,
                                          const std::vector<std::vector<float>> &chans,
                                          int sample_rate) {
    if (chans.empty()) throw std::runtime_error("write_wav: zero channels");
    size_t frames = chans[0].size();
    int nch = static_cast<int>(chans.size());
    std::vector<float> interleaved(frames * nch);
    for (size_t i = 0; i < frames; ++i)
        for (int c = 0; c < nch; ++c)
            interleaved[i * nch + c] = chans[c][i];
    write_wav_pcm24(path, interleaved.data(), frames, nch, sample_rate);
}

} // namespace sf
