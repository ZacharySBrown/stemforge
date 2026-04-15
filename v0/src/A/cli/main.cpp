// stemforge-native — thin CLI wrapper around libstemforge.
//
// All business logic lives in the library. This wrapper does only:
//   1. argv parsing,
//   2. sf_event_cb → stdout NDJSON line serialization (PIVOT §B),
//   3. exit code mapping.
//
// Keep under ~250 LOC. v2's Max external replaces this file entirely
// and routes events to Max outlets via outlet_anything() on the main
// thread.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "stemforge.h"

namespace {

void emit_stdout(const char *event_json, void *user) {
    (void)user;
    // NDJSON: one JSON doc per line, no trailing whitespace.
    std::fputs(event_json, stdout);
    std::fputc('\n', stdout);
    std::fflush(stdout);
}

struct Args {
    std::string subcommand;
    std::string input;
    std::string out;
    bool json_events = false;
    bool print_version = false;
    bool print_help = false;
    int  num_threads = 0;
    bool force_cpu = false;
    sf_demucs_variant variant = SF_DEMUCS_DEFAULT;
};

void print_help() {
    std::fprintf(stderr,
        "stemforge-native %s\n"
        "Usage:\n"
        "  stemforge-native split <input.wav> [--out DIR] [--json-events]\n"
        "                                    [--threads N] [--cpu-only]\n"
        "                                    [--variant ft|6s|fast]\n"
        "  stemforge-native forge <input.wav> [--json-events]\n"
        "  stemforge-native --version\n"
        "\n"
        "Env:\n"
        "  STEMFORGE_MODEL_DIR  override model directory\n"
        "  (default: ~/Library/Application Support/StemForge/models)\n",
        sf_version());
}

int parse(int argc, char **argv, Args &a) {
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--version" || arg == "-V") { a.print_version = true; continue; }
        if (arg == "--help" || arg == "-h")    { a.print_help = true; continue; }
        if (arg == "--json-events")            { a.json_events = true; continue; }
        if (arg == "--cpu-only")               { a.force_cpu = true; continue; }
        if (arg == "--threads" && i + 1 < argc) {
            a.num_threads = std::atoi(argv[++i]); continue;
        }
        if (arg == "--out" && i + 1 < argc) { a.out = argv[++i]; continue; }
        if (arg == "--variant" && i + 1 < argc) {
            std::string v = argv[++i];
            if (v == "ft") a.variant = SF_DEMUCS_FT;
            else if (v == "6s") a.variant = SF_DEMUCS_6S;
            else if (v == "fast") a.variant = SF_DEMUCS_FAST;
            else { std::fprintf(stderr, "unknown variant: %s\n", v.c_str()); return 2; }
            continue;
        }
        if (a.subcommand.empty()) a.subcommand = arg;
        else if (a.input.empty()) a.input = arg;
        else {
            std::fprintf(stderr, "unexpected arg: %s\n", arg.c_str());
            return 2;
        }
    }
    return 0;
}

int map_status(sf_status st) {
    switch (st) {
        case SF_OK: return 0;
        case SF_ERR_INVALID_ARG:   return 2;
        case SF_ERR_MODEL_MISSING: return 3;
        case SF_ERR_SHA_MISMATCH:  return 3;
        case SF_ERR_MODEL_LOAD:    return 3;
        case SF_ERR_AUDIO_DECODE:  return 4;
        case SF_ERR_INFERENCE:     return 5;
        case SF_ERR_CANCELLED:     return 130;
        default:                   return 1;
    }
}

} // namespace

int main(int argc, char **argv) {
    Args a;
    if (int rc = parse(argc, argv, a); rc != 0) return rc;
    if (a.print_version) { std::printf("%s\n", sf_version()); return 0; }
    if (a.print_help || a.subcommand.empty()) { print_help(); return 0; }

    if (a.subcommand != "split" && a.subcommand != "forge") {
        std::fprintf(stderr, "unknown subcommand: %s\n", a.subcommand.c_str());
        print_help();
        return 2;
    }
    if (a.input.empty()) {
        std::fprintf(stderr, "input file required\n");
        return 2;
    }

    sf_config cfg{};
    cfg.log_level = SF_LOG_WARNING;
    cfg.num_threads = a.num_threads;
    cfg.force_cpu_only = a.force_cpu ? 1 : 0;
    cfg.demucs_variant = a.variant;

    sf_handle h = sf_create(&cfg);
    if (!h) {
        std::fprintf(stderr, "failed to initialize libstemforge\n");
        return 1;
    }

    sf_event_cb cb = a.json_events ? emit_stdout : nullptr;

    sf_status st;
    if (a.subcommand == "split") {
        std::string out = a.out;
        if (out.empty()) {
            if (const char *home = std::getenv("HOME")) {
                out = std::string(home) + "/stemforge/processed";
            } else out = "./processed";
        }
        st = sf_split(h, a.input.c_str(), out.c_str(), cb, nullptr);
    } else {
        st = sf_forge(h, a.input.c_str(), nullptr, cb, nullptr);
    }

    if (st != SF_OK && !a.json_events) {
        std::fprintf(stderr, "error: %s\n", sf_last_error(h));
    }
    sf_destroy(h);
    return map_status(st);
}
