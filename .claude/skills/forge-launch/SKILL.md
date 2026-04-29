---
name: forge-launch
description: Launch Ableton Live and (optionally) open the StemForge template `.als`. Use when the user asks to open/launch/start Ableton or "open StemForge" (e.g. "launch Live", "open the StemForge template", "boot Ableton", "fire up StemForge"). If Ableton is already running, optionally tells it to open the template.
allowed-tools: Bash(open:*), Bash(pgrep:*), Bash(ls:*), Bash(osascript:*)
---

# forge-launch — boot Ableton and the StemForge template

Opens Ableton Live, optionally with the StemForge `.als` template loaded.

User triggers:

- *"launch Ableton"* / *"open Live"* / *"boot Ableton"*
- *"open the StemForge template"* / *"fire up StemForge"*
- *"open Ableton with the StemForge set"*

## How to invoke

macOS app launch via `open -a`. The StemForge template is at:

```
/Users/zak/zacharysbrown/stemforge/v0/build/StemForge.als
```

(There's also a skeleton/working copy at `v0/assets/skeleton.als` — prefer `v0/build/StemForge.als` unless the user explicitly says otherwise.)

## Behavior

1. **Check if Ableton is already running:**

   ```bash
   pgrep -x "Live" >/dev/null && echo "running" || echo "not running"
   ```

2. **If not running:**
   - User said "open the template" / "with StemForge" → open the `.als` directly (Live boots and loads it):
     ```bash
     open "/Users/zak/zacharysbrown/stemforge/v0/build/StemForge.als"
     ```
   - User said just "launch Live" / "boot Ableton" → launch the app without a set:
     ```bash
     open -a "Ableton Live 12 Suite"
     ```
     Try common app names in order (some users have different editions installed):
     - `"Ableton Live 12 Suite"` → `"Ableton Live 12 Standard"` → `"Ableton Live 12 Intro"` → `"Ableton Live 11 Suite"` → bare `"Ableton Live"`

     Detect availability with:
     ```bash
     ls /Applications/ | grep -i "^Ableton Live"
     ```
     and pick the first match.

3. **If already running:**
   - User said "open the template" → use `open` on the `.als`; macOS will bring Live forward and prompt to open the file (or just open it if the current set is unmodified):
     ```bash
     open "/Users/zak/zacharysbrown/stemforge/v0/build/StemForge.als"
     ```
   - User said just "launch" → no-op. Tell them: *"Ableton is already running."*

## Override etiquette

| User says | Action |
|-----------|--------|
| "with the template" / "open StemForge" | Open `v0/build/StemForge.als` |
| "with the skeleton" / "open the skeleton" | Open `v0/assets/skeleton.als` |
| "open `<path>.als`" | Open that path |
| "just launch Live" / "no template" | `open -a "Ableton Live ..."` only |
| "Live 11" | Use `"Ableton Live 11 Suite"` (or whatever 11 variant is installed) |

## Failure modes to watch for

- **Ableton not installed** — `ls /Applications/ | grep "^Ableton Live"` returns nothing. Tell the user to install Live (or symlink it into `/Applications/`).
- **Template missing** — if `v0/build/StemForge.als` doesn't exist, the v0 build hasn't run. Suggest:

  ```bash
  cd /Users/zak/zacharysbrown/stemforge && uv run python v0/src/als-builder/builder.py
  ```

  …or use the skeleton (`v0/assets/skeleton.als`) as a fallback.
- **`open` returns non-zero** — surface the error verbatim. macOS sometimes refuses to re-open a `.als` if Live has unsaved changes; tell the user to save or discard first.

## Example end-to-end

User: *"open Ableton with the StemForge template"*

You:

```bash
TPL="/Users/zak/zacharysbrown/stemforge/v0/build/StemForge.als"
[ -f "$TPL" ] || { echo "Template missing — run the v0 als-builder first"; exit 1; }

if pgrep -x "Live" >/dev/null; then
  open "$TPL"
  echo "Ableton was already running — told it to open the StemForge template."
else
  open "$TPL"
  echo "Booting Ableton with the StemForge template…"
fi
```

Report in one sentence: *"Opened `v0/build/StemForge.als` in Ableton."*

## Composability

This skill is a building block for `/forge-all`. Keep its output minimal so the composed skill's log stays readable.
