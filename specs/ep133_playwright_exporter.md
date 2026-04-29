# StemForge — EP-133 Playwright Exporter

**Status:** Draft spec for implementation
**Owner:** Zak
**Target:** `stemforge/exporters/ep133_playwright.py` (replaces `ep133_upload.py`)
**Approach:** Automate the official EP Sample Tool web app via Playwright, handing off all SysEx protocol complexity to TE's implementation.

---

## Problem

The current `ep133_upload.py` reverse-engineers the EP-133's SysEx protocol from hex dumps. It doesn't work:
- Missing TNGE WAV metadata chunk causes samples to be rejected silently
- 7-bit encoding is unverified against known-good output
- Slot addressing is approximated, not captured
- Size encoding uses 2 bytes (max 16 KB) but samples can be nearly 1 MB
- No ACK/NAK handling, so failures are invisible
- No pad assignment logic — even successful library writes wouldn't map to pads

Debugging this further is a multi-week rabbit hole with no public protocol documentation and firmware updates that can break any assumption.

## Solution

Drive the official EP Sample Tool (`https://teenage.engineering/apps/ep-sample-tool`) via Playwright. Sample Tool already handles TNGE metadata, 7-bit encoding, chunk sequencing, ACKs, slot addressing, pad assignment, and project structure correctly.

**Architecture:**

```
StemForge → Playwright → Chrome (headed) + Sample Tool → WebMIDI → EP-133
```

This is personal tooling, fragility is acceptable. When Sample Tool's DOM changes, update selectors.

---

## Deliverables

### Primary module: `stemforge/exporters/ep133_playwright.py`

Public API:

```python
async def upload_curated_export(
    export_dir: Path,
    project_slot: int,  # 1-9
    mapping: EP133Mapping,
    *,
    preserve_factory: bool = True,
    dry_run: bool = False,
) -> ExportResult:
    """Upload a curated sample set and configure a project on the EP-133.

    Args:
        export_dir: Directory containing WAV files from StemForge pipeline.
        project_slot: Project number on device (1-9).
        mapping: Which samples go to which library slots and pad assignments.
        preserve_factory: If False, deletes existing user samples in target slots.
        dry_run: Run all Playwright interactions but skip actual writes (for debugging selectors).

    Returns:
        ExportResult with per-sample status, timing, and any Sample Tool errors.
    """
```

### Supporting module: `stemforge/exporters/ep133_mapping.py`

Data classes:

```python
@dataclass
class EP133PadAssignment:
    project: int     # 1-9
    group: str       # 'A' | 'B' | 'C' | 'D'
    pad: int         # 1-12
    slot: int        # 1-999 (library slot)

@dataclass
class EP133Mapping:
    """Maps export WAVs to library slots and project/group/pad assignments."""
    slot_assignments: dict[str, int]          # filename -> slot number
    pad_assignments: list[EP133PadAssignment]

    def validate(self) -> list[str]:
        """Return list of validation errors. Empty list = valid."""
        # - No duplicate slot assignments
        # - Slot numbers in 1-999
        # - Project in 1-9
        # - Group in A-D
        # - Pad in 1-12
        # - All pad_assignments reference slots in slot_assignments
```

### Supporting module: `stemforge/exporters/ep133_playwright_driver.py`

Low-level wrapper around Playwright + Sample Tool DOM. This is where selectors live and break.

```python
class EP133SampleToolDriver:
    """Thin wrapper over Playwright interactions with EP Sample Tool."""

    async def __aenter__(self) -> "EP133SampleToolDriver": ...
    async def __aexit__(self, *args) -> None: ...

    async def wait_for_device_connected(self, timeout: float = 30.0) -> None: ...

    async def upload_sample_to_slot(
        self, wav_path: Path, slot: int, name: str | None = None
    ) -> None: ...

    async def delete_slot(self, slot: int) -> None: ...

    async def list_library(self) -> list[LibrarySlot]:
        """Returns current library contents as observed in the tool UI."""

    async def load_project(self, project_slot: int) -> None: ...

    async def assign_pad(
        self, group: str, pad: int, slot: int
    ) -> None: ...

    async def save_project(self) -> None: ...

    async def screenshot(self, path: Path) -> None:
        """Debug aid — capture current Sample Tool state."""
```

---

## Implementation plan

Work in this order. Each step should be independently runnable and testable.

### Step 1: Playwright scaffold and device connection (target: 30 min)

Get Playwright to launch a persistent Chrome context, navigate to Sample Tool, and detect the EP-133.

- Use `async_playwright` with `launch_persistent_context`
- Profile directory: `~/.stemforge/playwright-ep133-profile` (configurable)
- Headed mode (`headless=False`) — WebMIDI is flaky in headless Chrome
- Pre-grant MIDI permissions: `context.grant_permissions(['midi-sysex'], origin='https://teenage.engineering')`
- Navigate to `https://teenage.engineering/apps/ep-sample-tool`
- Wait for the device-connected state in the UI (look for serial number display, library view, or similar)
- Write `wait_for_device_connected()` with a reasonable timeout

**Acceptance:** Running `python -m stemforge.exporters.ep133_playwright --diagnostic` opens Chrome, loads Sample Tool, and prints "Device connected: <serial>" within 30s.

### Step 2: Library upload (target: 2 hours, may require DOM spelunking)

Implement `upload_sample_to_slot(wav_path, slot)`.

**Approach A (preferred):** Find the hidden `<input type="file">` that Sample Tool uses for drag-drop. Use Playwright's `set_input_files()` to inject the file. Then trigger whatever JS Sample Tool expects to associate it with a slot number — likely a separate interaction after the file enters the library.

**Approach B (fallback):** Use CDP's `Input.dispatchDragEvent` to simulate a real file drop on a specific slot element.

**DOM reconnaissance:**

1. Open Sample Tool in regular Chrome
2. Open DevTools
3. Manually drag a WAV onto slot 500
4. Watch the Network tab (nothing will appear — it's WebMIDI, not HTTP) and the Elements panel to see what DOM changes
5. Identify:
   - The drop zone element (likely a slot cell in a grid)
   - Any `<input type="file">` — search DOM for `type="file"`
   - The "currently uploading" state visual (progress bar, spinner)
   - The "upload complete" state (slot name appears, color changes)

Locators should use `get_by_role`, `get_by_label`, `get_by_text` where possible. CSS class selectors are fragile — Sample Tool is minified and class names change.

**Progress detection:** After triggering upload, wait for the slot to show the sample name (or a completion indicator). Use `expect(locator).to_contain_text(name)` or similar.

**Acceptance:** `upload_sample_to_slot(Path("kick.wav"), 500)` successfully puts the sample in slot 500 and the function returns only after upload completes.

### Step 3: Slot deletion and library listing (target: 30 min)

Implement `delete_slot(slot)` and `list_library()`.

- Delete: right-click slot → Delete, or select slot → press delete key, or whatever Sample Tool's UI supports. Needs DOM recon.
- List: enumerate all slot elements, extract slot number + name + any metadata visible in the UI.

**Acceptance:** After uploading to slot 500 then calling `delete_slot(500)`, the slot shows empty. `list_library()` returns a list including all currently-populated slots.

### Step 4: Project loading and pad assignment (target: 1-2 hours)

Implement `load_project(n)` and `assign_pad(group, pad, slot)`.

**Project loading:** Sample Tool likely has a project selector dropdown or button row. Click project N.

**Pad assignment:** Sample Tool displays a virtual EP-133 with 4 groups × 12 pads. Drag a library slot onto a pad. This is `locator.drag_to(target)` — source is the slot in the library list, target is the specific pad in the group.

**Group selection:** May require clicking a group selector (A/B/C/D) to show that group's pads before dragging.

**Acceptance:** After loading project 1, assigning slot 500 to group A pad 1, and pressing pad A1 on the physical device, sample 500 plays.

### Step 5: Project save (target: 15 min)

Sample Tool may auto-save, or may have an explicit save button. Verify which.

**Acceptance:** After making changes and restarting Sample Tool, the changes persist.

### Step 6: High-level curated export flow (target: 1 hour)

Wire Steps 2-5 into `upload_curated_export()`.

```python
async def upload_curated_export(export_dir, project_slot, mapping, ...):
    async with EP133SampleToolDriver() as tool:
        await tool.wait_for_device_connected()

        # Phase 1: library uploads
        for filename, slot in mapping.slot_assignments.items():
            wav_path = export_dir / filename
            await tool.upload_sample_to_slot(wav_path, slot)

        # Phase 2: project configuration
        await tool.load_project(project_slot)
        for assignment in mapping.pad_assignments:
            await tool.assign_pad(
                assignment.group, assignment.pad, assignment.slot
            )

        await tool.save_project()
```

Add a `progress_callback` parameter for UI feedback.

**Acceptance:** Running `python -m stemforge.exporters.ep133_playwright upload --export-dir ~/exports/squarepusher --project 1 --mapping mapping.yaml` completes end-to-end.

### Step 7: Error handling and retry (target: 1 hour)

- Wrap each upload in try/except with one retry
- Detect Sample Tool error toasts/modals and extract the message
- On persistent failure, take a screenshot for debugging and raise
- Log every operation with structured logging (see `promptflags` patterns for inspiration)

### Step 8: Integration with StemForge's mapping system (target: varies)

`EP133Mapping` needs to come from somewhere. Options:
- YAML file next to the export directory
- Generated automatically from StemForge's curated-song output structure
- A TUI/CLI helper that lets the user drag-and-drop in a terminal (out of scope for v1)

For v1, assume a YAML file at `<export_dir>/ep133_mapping.yaml` with this structure:

```yaml
slot_assignments:
  kick_01.wav: 1
  kick_02.wav: 2
  bass_slice_01.wav: 401
  # ...

pad_assignments:
  - {group: A, pad: 1, slot: 1}
  - {group: A, pad: 2, slot: 2}
  - {group: B, pad: 1, slot: 401}
  # ...
```

---

## Non-functional requirements

- **Headed mode by default.** WebMIDI + headless Chrome is historically flaky. Allow `headless=True` as override for advanced users.
- **Idempotent where possible.** Re-running with the same mapping should be a no-op or overwrite, not an error.
- **Slow-but-reliable defaults.** Default per-operation timeout: 30s. Uploads of 1MB samples can take 2-3s each; total for 44 samples ~60-90s is acceptable.
- **Dry-run mode.** `dry_run=True` does all Playwright navigation but skips destructive operations. For testing selectors without modifying the device.
- **Profile persistence.** Use persistent user data dir so WebMIDI permission grants survive across runs.

## Dependencies

```toml
# pyproject.toml additions
playwright = "^1.45"
pyyaml = "^6.0"
```

Post-install: `playwright install chromium`

## Testing strategy

- **Manual smoke test** per commit: run the curated-export flow on the real device, verify samples appear in expected slots.
- **Selector regression test** (optional): a script that launches Sample Tool, checks that all critical locators still find elements, and fails loudly if one breaks. Run before major releases.
- **No unit tests** on the driver layer — it's purely integration with a live web app. Integration tests with the real device are the source of truth.

## Known risks

1. **Sample Tool DOM changes without notice.** Selectors will break. Mitigation: structured logging of which selector failed, screenshots on failure, prominent "check selectors" doc section.
2. **WebMIDI permission prompts.** First run requires manual permission grant. Document this clearly. Persistent context saves the grant for subsequent runs.
3. **Chrome version drift.** Playwright bundles its own Chromium; won't drift with system Chrome updates.
4. **Headless WebMIDI.** Confirmed flaky. Default to headed.
5. **Garrett's fork alternative.** If the hosted Sample Tool proves unstable, evaluate switching to `garrettjwilke/ep_133_sample_tool` (Electron-based fork). Same DOM largely, runs locally, exposes raw SysEx logging.

## Out of scope for v1

- Backup/restore workflows (useful but secondary)
- Sample editing (trim, envelope) — let user do this in Sample Tool or pre-process in StemForge
- Factory sound restore automation — rarely needed, can be manual
- Multi-device management — one EP-133 only
- Windows/Linux support — Mac only for now (Zak's primary)

## Future enhancements (post-v1)

- Migrate to a fork of garrett's Electron app with an added HTTP API for cleaner automation
- Bi-directional sync: read current device state, diff against desired state, apply minimal changes
- Integration with StemForge's OpenClaw system for voice-controlled uploads
