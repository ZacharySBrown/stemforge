// sf_ndjson.hpp — helpers for emitting NDJSON events that match
// v0/interfaces/ndjson.schema.json.
//
// Events are produced as nlohmann::json objects, serialized to a single
// line, and delivered via sf_event_cb. The library never touches stdout
// directly (per PIVOT §B: NDJSON is a serialization sink, not the event
// type). The CLI wrapper's callback does the printf.

#pragma once

#include <cstdint>
#include <cstdio>
#include <string>

#include "stemforge.h"
#include "nlohmann_json.hpp"

namespace sf {

using json = nlohmann::json;

class EventEmitter {
public:
    EventEmitter(sf_event_cb cb, void *user) : cb_(cb), user_(user) {}

    void emit(const json &obj) const {
        if (!cb_) return;
        // compact, no pretty print, no trailing newline — callback adds newline if needed.
        std::string s = obj.dump();
        cb_(s.c_str(), user_);
    }

    void started(const std::string &track, const std::string &audio,
                 const std::string &backend, const std::string &pipeline,
                 const std::string &output_dir) const {
        emit({{"event", "started"},
              {"track", track},
              {"audio", audio},
              {"backend", backend},
              {"pipeline", pipeline},
              {"output_dir", output_dir}});
    }

    void progress(const std::string &phase, double pct,
                  const std::string &message = {}) const {
        json o = {{"event", "progress"}, {"phase", phase}, {"pct", pct}};
        if (!message.empty()) o["message"] = message;
        emit(o);
    }

    void stem(const std::string &name, const std::string &path,
              int64_t size_bytes) const {
        emit({{"event", "stem"},
              {"name", name},
              {"path", path},
              {"size_bytes", size_bytes}});
    }

    void bpm(double bpm, int beat_count) const {
        emit({{"event", "bpm"}, {"bpm", bpm}, {"beat_count", beat_count}});
    }

    void slice_dir(const std::string &stem, const std::string &dir,
                   int count) const {
        emit({{"event", "slice_dir"},
              {"stem", stem},
              {"dir", dir},
              {"count", count}});
    }

    void complete(const std::string &manifest, double bpm, int stem_count,
                  double duration_sec) const {
        emit({{"event", "complete"},
              {"manifest", manifest},
              {"bpm", bpm},
              {"stem_count", stem_count},
              {"duration_sec", duration_sec}});
    }

    void error(const std::string &phase, const std::string &message,
               bool fatal = true) const {
        emit({{"event", "error"},
              {"phase", phase},
              {"message", message},
              {"fatal", fatal}});
    }

private:
    sf_event_cb cb_;
    void *user_;
};

} // namespace sf
