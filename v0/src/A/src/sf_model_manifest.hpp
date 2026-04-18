// sf_model_manifest.hpp — read v0/build/models/manifest.json and
// validate SHA256 of the model files we intend to load.

#pragma once

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include <CommonCrypto/CommonDigest.h>

#include "nlohmann_json.hpp"

namespace sf {

namespace fs = std::filesystem;
using json = nlohmann::json;

struct ModelEntry {
    std::string key;
    fs::path    path;               // absolute path to .onnx file
    std::string sha256;
    int64_t     size = 0;
    std::string precision;
    bool        coreml_ep_supported = false;
    fs::path    optimized_cache;    // absolute path or empty
    // Bag support
    int         bag_head_index = -1;
    int         bag_size = 1;
};

struct ModelManifest {
    int schema_version = 1;
    std::string ort_version;
    int opset_version = 17;
    fs::path root;
    std::unordered_map<std::string, ModelEntry> models;
};

// Compute SHA-256 hex digest of a file. Used at load time to verify
// manifest integrity (PIVOT §5 — refuse to run if a model has been
// tampered with).
inline std::string sha256_hex(const fs::path &p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) return {};
    CC_SHA256_CTX ctx;
    CC_SHA256_Init(&ctx);
    std::vector<char> buf(1 << 16);
    while (f) {
        f.read(buf.data(), buf.size());
        std::streamsize n = f.gcount();
        if (n > 0) CC_SHA256_Update(&ctx, buf.data(), static_cast<CC_LONG>(n));
    }
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256_Final(digest, &ctx);
    char out[CC_SHA256_DIGEST_LENGTH * 2 + 1];
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; ++i)
        std::snprintf(out + 2 * i, 3, "%02x", digest[i]);
    out[CC_SHA256_DIGEST_LENGTH * 2] = 0;
    return out;
}

inline ModelManifest load_model_manifest(const fs::path &model_root) {
    fs::path mfp = model_root / "manifest.json";
    std::ifstream f(mfp);
    if (!f) throw std::runtime_error("model manifest not found: " + mfp.string());
    json j;
    f >> j;
    ModelManifest mm;
    mm.root = fs::absolute(model_root);
    mm.schema_version = j.value("schema_version", 1);
    mm.ort_version = j.value("ort_version", "");
    mm.opset_version = j.value("opset_version", 17);
    if (!j.contains("models") || !j["models"].is_object())
        throw std::runtime_error("manifest.json missing models{}");
    // Repo paths in manifest are relative to repo root (v0/build/models/*).
    // We resolve against model_root regardless by stripping the prefix.
    // Accepted forms: "v0/build/models/X/Y.onnx" or just "X/Y.onnx".
    auto resolve = [&](const std::string &raw) -> fs::path {
        fs::path p(raw);
        // If absolute or already exists, use it.
        if (p.is_absolute() && fs::exists(p)) return p;
        fs::path under_root = mm.root / p.filename();
        if (fs::exists(under_root)) return under_root;
        // Try stripping "v0/build/models/" prefix.
        const std::string prefix = "v0/build/models/";
        std::string s = p.generic_string();
        if (s.rfind(prefix, 0) == 0) s = s.substr(prefix.size());
        fs::path under = mm.root / s;
        return under; // may not exist; caller will error out on verify.
    };
    for (auto it = j["models"].begin(); it != j["models"].end(); ++it) {
        ModelEntry e;
        e.key = it.key();
        const auto &v = it.value();
        e.path = resolve(v.value("path", std::string{}));
        e.sha256 = v.value("sha256", "");
        e.size = v.value("size", 0LL);
        e.precision = v.value("precision", "fp32");
        e.coreml_ep_supported = v.value("coreml_ep_supported", false);
        std::string oc = v.value("optimized_cache", std::string{});
        if (!oc.empty()) e.optimized_cache = resolve(oc);
        e.bag_head_index = v.value("bag_head_index", -1);
        e.bag_size = v.value("bag_size", 1);
        mm.models[e.key] = std::move(e);
    }
    return mm;
}

// Verify one model file exists and matches sha256. Throws on mismatch.
inline void verify_model(const ModelEntry &e) {
    if (!fs::exists(e.path))
        throw std::runtime_error("model file missing: " + e.path.string());
    if (e.sha256.empty()) return; // advisory only
    std::string got = sha256_hex(e.path);
    if (got != e.sha256)
        throw std::runtime_error("model sha256 mismatch: " + e.path.string()
                                 + " expected=" + e.sha256 + " got=" + got);
}

} // namespace sf
