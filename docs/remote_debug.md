# StemForge Remote Debug Stack

Drive the StemForge M4L device from a remote Claude Code session (or your
phone over SSH) while Max + Ableton keep running on your Mac. No Max GUI
interaction required.

## What it gives you

| Capability | How |
|------------|-----|
| Fire any module function | UDP packet to `127.0.0.1:7420`, shape `<target> <body...>` |
| Dump any dict into a log | UDP packet to `127.0.0.1:7421`, shape `dumpDict <dictName>` |
| Read everything the device prints | Tail `~/stemforge/logs/sf_debug.log` |
| Push canned sf_state JSON | `sf-remote setstate idle` |
| Clear the log both ends | `sf-remote log --clear` |

The Max patcher has two `[udpreceive]` boxes built by
`v0/src/maxpat-builder/builder.py`:
- **`[udpreceive 7420]`** → `[route state forge preset-loader manifest-loader settings ui logger]` → each module's inlet.
- **`[udpreceive 7421]`** → `sf_state_mgr` (direct; receives `dumpDict` only).

Every JS module has an inlined `_sfFileLog(module, msg)` helper that appends
to the shared log file. `sf_logger.js` is also loaded as a standalone `[js]`
so remote senders can write ad-hoc log lines through UDP target `logger`.

## QuickStart

Install once:

```bash
uv sync                        # picks up the `sf-remote` script entry
uv run python tools/sf_deploy.py    # copies JS + rebuilds .amxd
```

In Live, reload the device so it picks up the new .amxd (or just open
`v0/build/stemforge-debug.maxpat` in standalone Max for faster iteration —
see `m4l_device_development_guide.md`).

Then from any shell (including SSH from your phone):

```bash
# Tail the log live
uv run sf-remote log --follow

# Fire a function on a module
uv run sf-remote fire forge startForge
uv run sf-remote fire preset-loader scan
uv run sf-remote fire state markPhase1Progress 0.5 downloading vocals

# Snapshot a dict into the log
uv run sf-remote dump sf_preset
uv run sf-remote dump sf_state

# Push canned UI state
uv run sf-remote setstate idle
uv run sf-remote setstate forging
uv run sf-remote setstate done
uv run sf-remote setstate error

# Status overview (last 60 lines + sf_state dump)
uv run sf-remote status
```

`sf-remote` writes UDP to `127.0.0.1` by default. Override via env vars:
`SF_REMOTE_HOST`, `SF_REMOTE_BUS_PORT`, `SF_REMOTE_DUMP_PORT`.

## CLI reference

### `sf-remote log`

| Flag | Effect |
|------|--------|
| `--follow` / `-f` | Follow (tail -f) |
| `--clear` | Truncate local log AND send `logger clear` via UDP |

### `sf-remote fire <target> <message...>`

Targets: `state`, `forge`, `preset-loader`, `manifest-loader`, `settings`,
`ui`, `logger`. Body is sent verbatim to the module's inlet. Examples:

```bash
sf-remote fire state markStemDone drums
sf-remote fire state markDone 11 4 15 38.2
sf-remote fire state reset
sf-remote fire forge cancelForge
sf-remote fire settings get splitting.engine
sf-remote fire settings set splitting.engine demucs
sf-remote fire preset-loader select 0
sf-remote fire manifest-loader scanManifests
sf-remote fire ui refresh
sf-remote fire logger clear
```

### `sf-remote dump <dictName>`

Dicts: `sf_state`, `sf_preset`, `sf_manifest`, `sf_settings`. Writes the
dict body to the log tagged `DUMP:<name>`, then prints those lines. Uses
port 7421.

### `sf-remote setstate <shortcut-or-path>`

Shortcuts: `empty`, `idle`, `forging`, `done`, `error`.
Or a path to any JSON file. Sent as `ui setState <json>` via UDP 7420.

### `sf-remote status`

Prints last 60 log lines + a `sf_state` dump.

## Worked example: "preset config resolution not working"

Scenario: user reports the loader falls back to hardcoded IDM defaults
instead of honoring the selected preset.

```bash
# 1. Clear state
uv run sf-remote log --clear

# 2. Simulate a preset selection through the real loader flow
uv run sf-remote fire preset-loader select 0

# 3. Check that sf_preset dict got populated
uv run sf-remote dump sf_preset

# 4. Start a forge — watch what pipelineConfig the legacy loader resolves to
uv run sf-remote log --follow      # in one window
uv run sf-remote fire forge startForge    # in another

# 5. Look for "[sf_loader]" lines around "pipelineConfig" resolution
```

Because every module's `log()` / `status()` helper now also writes to the
shared log, you see the full timeline without needing Max Console.

## Launchd: keep Max + debug patch running

To keep the patch open across reboots (so the UDP receivers stay listening),
drop this at `~/Library/LaunchAgents/com.stemforge.debug.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.stemforge.debug</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-g</string>
    <string>-a</string><string>/Applications/Max.app</string>
    <string>/Users/zak/zacharysbrown/stemforge/v0/build/stemforge-debug.maxpat</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
  </dict>
  <key>StandardErrorPath</key>
  <string>/tmp/stemforge-debug.err</string>
</dict>
</plist>
```

Load with:
```bash
launchctl load ~/Library/LaunchAgents/com.stemforge.debug.plist
```

Unload with `launchctl unload ~/Library/LaunchAgents/com.stemforge.debug.plist`.

## Protocol reference

### UDP 7420 — general bus

Payload: `<target> <body...>` ASCII, UTF-8 encoded.

The patcher runs `[route state forge preset-loader manifest-loader settings ui logger]` on the receiver output. The matched atom is stripped; the tail is fed to the corresponding module's inlet as a Max list.

Examples:

```
state markPhase1Progress 0.5 downloading vocals
state setPreset production_idm.json
state reset
forge startForge
forge cancelForge
preset-loader scan
preset-loader select 0
manifest-loader scanManifests
manifest-loader select 2
settings get workflow.manifestDir
settings set workflow.manifestDir ~/stemforge/processed
ui refresh
ui setState {"kind":"idle",...}
logger fileLog remote "custom note"
logger clear
```

### UDP 7421 — dict-dump channel

Payload: `dumpDict <name>` where `<name>` is one of
`sf_state | sf_preset | sf_manifest | sf_settings`.

The state manager (`sf_state.js:dumpDict`) writes 3 log lines tagged
`DUMP:<name>`:

```
[ISO] [DUMP:sf_preset] BEGIN
[ISO] [DUMP:sf_preset] {"root": { ... }}
[ISO] [DUMP:sf_preset] DUMP END
```

`sf-remote dump` waits for `DUMP END`, then prints the block to stdout.

## File layout

```
v0/src/m4l-js/
  sf_logger.js                 # file log sink + UDP `logger clear`
  sf_state.js                  # dumpDict + inline _sfFileLog
  sf_forge.js                  # inline _sfFileLog in log()
  sf_preset_loader.js          # inline _sfFileLog in log()
  sf_manifest_loader.js        # inline _sfFileLog in log()
  sf_settings.js               # inline _sfFileLog in log()
  sf_ui.js                     # inline _sfFileLog wired into post() sites
  stemforge_loader.v0.js       # inline _sfFileLog in status()
v0/src/m4l-package/StemForge/javascript/
  (mirrored copy of everything above — must stay in sync)
v0/src/maxpat-builder/builder.py
  UDP_BUS_PORT = 7420, UDP_DUMP_PORT = 7421
  adds [udpreceive 7420] → [route ...] → modules
  adds [udpreceive 7421] → sf_state_mgr
tools/
  sf_remote.py                 # CLI (sf-remote = tools.sf_remote:main)
  sf_deploy.py                 # sync JS + rebuild/install .amxd
docs/remote_debug.md           # this file
```

## Troubleshooting

- **`sf-remote dump` times out.** The debug patch isn't running, or
  `[udpreceive 7421]` isn't bound (port conflict). Check Max Console for
  `udpreceive: bind: address already in use`. Nothing else on macOS uses
  7420/7421; if you hit a conflict, override via `SF_REMOTE_*_PORT` env vars
  AND rebuild the patch with matching `UDP_*_PORT` constants in `builder.py`.
- **Nothing shows up in the log.** Run `uv run sf-remote fire logger fileLog test hello` — if that appears in the log, the UDP path works, and your issue is in a specific module's `log()` wiring. If it does NOT appear, Max isn't running the updated patch; run `uv run python tools/sf_deploy.py` again.
- **Log file never rotates.** Rotation currently truncates at 10 MB rather
  than renaming (Max classic [js] has no rename API). Accept or run
  `sf-remote log --clear` periodically.
