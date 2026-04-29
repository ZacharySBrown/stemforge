# EP-133 Playwright Exporter — Progress Log

**Date:** 2026-04-21
**Status:** Step 1 (connection) complete. Step 2 (upload) blocked on drop event simulation.

---

## What Works

### Step 1: Connection (DONE)
- Playwright launches Chrome (system Chrome via `--channel chrome` required; bundled Chromium crashes)
- Navigates to `https://teenage.engineering/apps/ep-sample-tool`
- Detects device connection by reading page text for "sample library", "KICK", etc.
- MIDI permission prompt appears once; persistent profile at `~/.stemforge/playwright-ep133-profile/` saves it
- Diagnostic command: `uv run python -m stemforge.exporters.ep133_playwright diagnostic --channel chrome`

### Navigation
- Category tab clicks work (KICK, SNARE, USER 1, etc.)
- Empty and occupied slot detection works
- Scrolling the virtualized library (29 visible rows) works

### Dry Run
- Full dry-run flow works end to end: auto-mapping, progress bars, pad assignment logging

---

## What Doesn't Work Yet

### Step 2: File Upload (BLOCKED)
The Sample Tool only accepts drag-and-drop file uploads. No `<input type="file">` exists. We need to simulate a native file drop from Playwright.

**Approaches tried:**

1. **`expect_file_chooser()` + TX icon click** — TX icon doesn't open a file picker. No file chooser event fires. Timeout.

2. **Synthetic JS `DragEvent` with `Object.defineProperty` override** — Created real `File` objects (both from base64 and from hidden input), dispatched `dragenter`/`dragover`/`drop` on multiple targets. Result: `dragenter` accepted (returns true), but `dragover` returns false and `drop` returns false. The React app's event handler rejects synthetic events because Chrome's drag-and-drop security model doesn't allow synthetic events to carry real file data through the standard pipeline.

3. **CDP `Input.dispatchDragEvent`** — Used Chrome DevTools Protocol to dispatch native-level drag events with `files: ["/path/to/file.wav"]`. Events dispatch without error but the Sample Tool doesn't react — no upload indicator appears. Likely because CDP drag events with file paths may not create proper `DataTransfer.files` entries in the page context.

4. **Hidden `<input type="file">` + `set_input_files()` + read `input.files[0]`** — Created a hidden file input, used Playwright's native `set_input_files()` to populate it (creates a real Chrome-security-context File), then read that File and added it to a DataTransfer for synthetic drop events. Same result as approach 2: dragover/drop rejected.

### Root Cause
Chrome's drag-and-drop security model distinguishes between "trusted" events (initiated by real user gesture from the OS) and "untrusted" events (dispatched via JS). The `DataTransfer` object on untrusted events has restricted access — `files` and `items` may be empty or read-only from the receiving handler's perspective, even if we populated them. The React app likely reads `event.dataTransfer.files` which is empty on synthetic events.

---

## Key DOM Findings (from recon)

The Sample Tool is an SVG-based React SPA:

- **Library panel**: `g#library` — right side, shows 29 virtualized rows
- **Occupied slot row**: `<foreignObject>` containing a `<div style="display:flex">` with:
  - `<input id="N" type="text" class="_name_6leb1_1 _uploaded_6leb1_22" value="SAMPLE NAME">`
  - `div[draggable="true"]` wrapper (for drag-to-download)
  - Delete zone (first 10px div) and download zone (last 10px divs)
- **Empty slot row**: Just `<text>` or `<tspan>` with the slot number + circle indicator
- **Category tabs**: KICK 1-99, SNARE 100-199, CYMB 200-299, PERC 300-399, BASS 400-499, MELOD 500-599, LOOP 600-699, USER 1 700-799, USER 2 800-899, SFX 900-999
- **Upload indicators per row**: `g#upload-current`, `g#upload-pending`, `g#upload-fail` (hidden by default, toggled via `style.display`)
- **Success toast**: "SUCCESSFULLY UPLOADED N / N FILES" overlay at top of library
- **Pad dropzones**: `g#dropzones` with 17 `<foreignObject>` elements (1 display + 4 group selectors + 12 pads)
- **Help overlay**: Says "drag & drop to upload samples" pointing at library, "drag & drop to assign sample" pointing at pads
- **JS bundle**: `/apps/ep-sample-tool/assets/index-BZSDxPHg.js` (minified React)
- **No inline handlers, no `<input type="file">`** — all interaction via the bundled JS

### Manual Upload Behavior (confirmed by Zak)
- Drag WAV from Finder onto an **empty** slot — uploads to that slot
- Drag WAV from Finder onto an **occupied** slot — places in next empty slot in the auto-detected category
- Upload shows "SUCCESSFULLY UPLOADED 1 / 1 FILES" toast
- Sample Tool may auto-rename files (e.g. `snare_os_001.wav` → `SNARE_OS_001`)

---

## Crashes Resolved

1. **`RESULT_CODE_KILLED_BAD_MESSAGE`** — Caused by `context.grant_permissions(['midi-sysex', 'midi'])`. Chrome's IPC sandbox kills the renderer. Fix: don't pre-grant MIDI permissions; let the TE app request them naturally.

2. **`Page.goto: Page crashed` / `networkidle`** — Sample Tool's WebMIDI init prevents reaching `networkidle`. Fix: use `wait_until="domcontentloaded"` + retry loop (3 attempts) with fresh page on crash.

3. **`Page.evaluate: Target crashed`** — Caused by calling `navigator.requestMIDIAccess({sysex: true})` in our code. The TE app already owns the MIDI session; duplicate calls crash the renderer. Fix: never touch WebMIDI ourselves.

---

## Next Steps

### Option A: Intercept the JS bundle
Reverse-engineer or monkey-patch the Sample Tool's upload handler from the minified React bundle (`index-BZSDxPHg.js`). Find the function that handles `drop` events and call it directly with file data, bypassing the trusted-event requirement.

### Option B: OS-level automation
Use `osascript` (AppleScript) or `cliclick` to perform a real Finder drag operation. Playwright opens the browser and navigates; then a separate tool does the actual file drag from a Finder window onto the Chrome window at specific coordinates. This would create trusted events.

### Option C: Clipboard/paste workaround
Some web apps accept file paste (`Ctrl+V`) in addition to drag-and-drop. Test if the Sample Tool handles paste events with file data. Playwright can simulate clipboard paste with file data.

### Option D: Garrett's fork
The spec mentions `garrettjwilke/ep_133_sample_tool` — an Electron-based fork that runs locally and exposes raw SysEx logging. May have a more automation-friendly upload path, or we could add one.

---

## Files Created

| File | Purpose |
|------|---------|
| `stemforge/exporters/ep133_mapping.py` | Data classes for slot/pad mapping + YAML load/save + auto-mapping |
| `stemforge/exporters/ep133_playwright_driver.py` | Low-level Playwright wrapper (selectors, navigation, upload, delete) |
| `stemforge/exporters/ep133_playwright.py` | High-level `upload_curated_export()` + CLI (`diagnostic`, `recon`, `upload`) |
| `pyproject.toml` | Added `[ep133]` optional dependency group |

## Commands

```bash
# Diagnostic (test connection)
uv run python -m stemforge.exporters.ep133_playwright diagnostic --channel chrome

# Diagnostic with browser kept open (for manual testing)
uv run python -m stemforge.exporters.ep133_playwright diagnostic --channel chrome --keep-open

# DOM recon (inspect selectors)
uv run python -m stemforge.exporters.ep133_playwright recon --channel chrome

# Upload (dry run)
uv run python -m stemforge.exporters.ep133_playwright upload \
    --export-dir /tmp/ep133-beware-drums --project 1 --start-slot 700 \
    --channel chrome --dry-run

# Upload (real)
uv run python -m stemforge.exporters.ep133_playwright upload \
    --export-dir /tmp/ep133-beware-drums --project 1 --start-slot 700 \
    --channel chrome
```
