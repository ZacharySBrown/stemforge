/*
 * stemforge.h — stable C ABI for libstemforge.
 *
 * This header is frozen. v0 CLI (`stemforge-native`) and v2 Max external
 * (`[stemforge~]`) both link libstemforge via this API. Additions are
 * backward-compatible-only; signatures never change.
 *
 * Thread safety:
 *   - sf_handle is reentrant: multiple handles may exist simultaneously.
 *   - No function in this API is safe to call from a real-time audio
 *     thread. Max externals MUST dispatch sf_split/sf_forge via
 *     defer_low() (or equivalent low-priority scheduler).
 *   - Inference runs on a dedicated worker thread spawned inside the
 *     library. Events are delivered on that worker thread via sf_event_cb;
 *     the callback must be thread-safe and non-blocking (Max externals
 *     should enqueue, return fast, drain on the main thread).
 *
 * Memory:
 *   - All strings passed to callbacks (const char*) are owned by the
 *     library and valid only for the duration of the callback.
 *   - Callers own the config/pipeline structs they pass; the library
 *     copies any data it needs to retain.
 */

#ifndef STEMFORGE_H
#define STEMFORGE_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------- types */

typedef struct sf_handle_t *sf_handle;

/* Opaque pipeline descriptor (future-proofing for sf_forge). v0 accepts
 * a NULL sf_pipeline* in sf_forge → library substitutes the default
 * pipeline. Full struct will be defined when forge YAML lands; treat as
 * forward-declared until then. */
struct sf_pipeline;

/* Event callback. `event_json` is a single NDJSON line (no trailing
 * newline) that validates against v0/interfaces/ndjson.schema.json.
 * Deliver events on the library's worker thread; callback must be
 * thread-safe. */
typedef void (*sf_event_cb)(const char *event_json, void *user);

/* Log levels match ORT_LOGGING_LEVEL_*. */
typedef enum sf_log_level {
    SF_LOG_VERBOSE = 0,
    SF_LOG_INFO    = 1,
    SF_LOG_WARNING = 2,
    SF_LOG_ERROR   = 3,
    SF_LOG_FATAL   = 4
} sf_log_level;

/* Demucs variant. Defaults to htdemucs_ft (the A0-validated primary). */
typedef enum sf_demucs_variant {
    SF_DEMUCS_DEFAULT = 0, /* htdemucs_ft (4-stem, fine-tuned, primary) */
    SF_DEMUCS_FT      = 1, /* htdemucs_ft explicit */
    SF_DEMUCS_6S      = 2, /* htdemucs_6s (6-stem) */
    SF_DEMUCS_FAST    = 3  /* htdemucs (base 4-stem, speed fallback) */
} sf_demucs_variant;

typedef struct sf_config {
    /* Absolute path to the model root. Contains manifest.json and per-model
     * subdirs (htdemucs_ft/, htdemucs_6s/, etc.). If NULL, library uses
     * $STEMFORGE_MODEL_DIR, else $HOME/Library/Application Support/StemForge/models.
     */
    const char      *model_dir;
    sf_log_level     log_level;
    /* Intra-op thread count for ONNX Runtime. 0 → hardware_concurrency()-1. */
    int              num_threads;
    /* If non-zero, disable CoreML EP and use CPU EP only. Useful for
     * debugging or when A0 manifest says coreml_ep_supported=false. */
    int              force_cpu_only;
    /* Which Demucs variant to use. */
    sf_demucs_variant demucs_variant;
    /* Reserved for future expansion — set to zero. */
    uint32_t         _reserved[8];
} sf_config;

/* Result codes. 0 = success. */
typedef enum sf_status {
    SF_OK                   = 0,
    SF_ERR_INVALID_ARG      = 1,
    SF_ERR_IO               = 2,
    SF_ERR_MODEL_LOAD       = 3,
    SF_ERR_MODEL_MISSING    = 4,
    SF_ERR_SHA_MISMATCH     = 5,
    SF_ERR_AUDIO_DECODE     = 6,
    SF_ERR_INFERENCE        = 7,
    SF_ERR_UNSUPPORTED      = 8,
    SF_ERR_CANCELLED        = 9,
    SF_ERR_INTERNAL         = 99
} sf_status;

/* -------------------------------------------------------------- lifecycle */

/* Create a new handle. Allocates Ort::Env + one Ort::Session per shipped
 * model (loaded lazily on first sf_split/sf_forge to keep cold-start fast
 * when the caller only wants --version). Returns NULL on failure; call
 * sf_last_error() to diagnose. */
sf_handle sf_create(const sf_config *cfg);

/* Destroy handle. Blocks until the worker thread's current job (if any)
 * finishes. Safe to call once per create. */
void sf_destroy(sf_handle h);

/* Return ABI version "major.minor.patch". Never NULL. */
const char *sf_version(void);

/* Return a static-lifetime human-readable description of the last error
 * on this handle. NULL handle → last create() error. */
const char *sf_last_error(sf_handle h);

/* ------------------------------------------------------------- operations */

/* Full stem-split pipeline: decode → resample to 44.1k stereo → Demucs
 * inference (external STFT/iSTFT + chunked overlap-add) → write stems →
 * beat detect → slice → write manifest. Blocks until done. Emits events
 * via cb on the library's worker thread. */
sf_status sf_split(sf_handle h,
                   const char *input_wav,
                   const char *out_dir,
                   sf_event_cb cb,
                   void *user);

/* Forge pipeline: stem-split + curate + pre-render for an Ableton
 * session. v0 accepts NULL pipe → uses default YAML from the bundled
 * pipelines catalogue. Full struct defined post-v0. */
sf_status sf_forge(sf_handle h,
                   const char *input_wav,
                   const struct sf_pipeline *pipe,
                   sf_event_cb cb,
                   void *user);

/* Request cancellation of an in-flight sf_split/sf_forge. Non-blocking.
 * The in-flight call returns SF_ERR_CANCELLED when the next chunk boundary
 * is reached. */
void sf_cancel(sf_handle h);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* STEMFORGE_H */
