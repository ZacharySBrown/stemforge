# Automating .amxd packaging: what works, what doesn't, and the two viable paths

**Bottom line: there is no public tool, CLI, or community pipeline that fully automates "freeze + embed JS" for an `.amxd` in GitHub Actions today.** The `mx@c` header checksum has not been reverse-engineered publicly, Ableton's own maxdevtools repo ships zero build/freeze tooling, and no open-source M4L project produces frozen `.amxd` artifacts via CI. However, two production-quality CI paths exist that sidestep the problem entirely: **(1) ship the JS as a Max Package via your existing `.pkg` installer and distribute the device unfrozen**, or **(2) use Max 9's new `@embed` attribute on `[node.script]` / `[v8]`**, which stores JS source as plain text in the patcher JSON (no `mx@c` wrapper). The Package approach is recommended — it's how Cycling '74 and Ableton themselves distribute Node for Max, RNBO, BEAP, and Live 12's built-in M4L devices. Everything below is the evidence for that conclusion and the concrete pitfalls to plan around.

## Ableton's maxdevtools contains no build automation

The repo at **github.com/Ableton/maxdevtools** is documentation plus read-only Python diff helpers, nothing more. Top-level contents are four folders — `cpu-reporter/` (a measurement `.amxd`), `m4l-production-guidelines/` (markdown), `patch-code-standard/` (markdown), and `maxdiff/` (three `*_textconv.py` scripts that dump human-readable summaries for git diffing `.maxpat`, `.amxd`, and `.als`) — plus standard repo metadata. The diff scripts read the JSON body but **do not round-trip, do not decode or regenerate the `mx@c` checksum, and do not handle embedded resources**. No other Cycling '74 repo (max-sdk, n4m-examples, miraweb, rnbo.*) offers an `.amxd` builder either.

Most importantly, a Cycling '74/Ableton staffer (MattijsKneppers) confirmed in the forum thread **"amxd build process"** and **"where to best put your m4l files dependencies"** that **"we have reverse-engineered Max's freezing process and re-implemented it in typescript. I hope we'll be able to release this one day, but so far it's still a messy script that can only be used by the people who wrote it."** That internal tool has not shipped; users asking for a CLI have been told the 2017-era workaround (opening an `.amxd` in standalone Max and using a scripting host to Ctrl-S, which auto-froze on save) was removed around Max 7.3.3 and no longer works.

## No community CI pipeline produces frozen .amxd files

An extensive search across GitHub (`"amxd" extension:yml`, `"max for live" "github actions"`), the `amxd` topic page, and prolific M4L developers (zsteinkamp, tomduncalf, iainctduncan, tiagolr, isotonikstudios, cycling74, adriananders, dupontgu, versioduo, little-scale, robjac) found **zero open-source repositories with a GitHub Actions workflow that freezes or packages an `.amxd`**. Every notable M4L repo that ships releases — including zsteinkamp's ~10 modulation plugins, tomduncalf/livefader, zsteinkamp/m4l-typescript-base — freezes manually and uploads binaries by hand. The closest automated release tooling, **iainctduncan/scheme-for-max's `make-release.py`**, builds **Max externals (`.mxo`/`.mxe`), not `.amxd` devices**. TypeScript/npm dev containers exist (m4l-typescript-base, livefader) but they stop at transpiling `.ts → .js` on the developer's machine. **Treat this as a greenfield problem: you'd be among the first to solve it publicly.**

## The mx@c header checksum is not publicly decoded

The `.amxd` file is a **28-byte fixed binary header + JSON body + 4-byte little-endian uint32 trailer carrying the JSON length**, with a type FourCC (e.g. `ampf` = 1633771873) indicating audio/midi/instrument. A Cycling '74 staffer confirmed the header "contains info on kind of file and kind of checksum." Community tooling works by either **skipping the header for read-only diffing** (Ableton's own `amxd_textconv.py` does this, as does the popular `awk '(NR>1)'` trick documented by Steinkamp) or by **grafting a known-good header from another file** — neither round-trips. **No `py-amxd`, `amxd-tools`, or mx@c validator exists on GitHub.** diemoschwarz/diff-for-max, the precursor to maxdiff, is a Perl regex filter whose author explicitly says "It is not even parsing the json!" Hand-crafting the mx@c checksum for embedded resources consistently produces files Live refuses to load. Treat this as a dead end unless you want to reverse-engineer it yourself and maintain it against every Max update.

## Object alternatives to node.script: Max 9's @embed changes the math

A key — and under-publicized — **Max 9.0 change** (October 2024) is the new `@embed` attribute on `[v8]`, `[node.script]`, `[js]`, `[jit.gl.slab]`, `[jit.gl.shader]`, and `[jit.gl.pass]`. Release notes: *"Save the text of v8, node.script, jit.gl.slab, jit.gl.shader and jit.gl.pass objects right in the patcher with the embed attribute."* This means JS source is stored as **plain text inside the patcher JSON**, bypassing the `mx@c` binary wrapper entirely. **You should empirically validate this on a Max 9 `.amxd` immediately** — if the embed really is plaintext for `[node.script @embed 1]`, your CI can template the JS into the patcher JSON directly from a script without Max ever running, which is the single cheapest win available.

For object capabilities, the trade-off table looks like this in Live 12.2 / Max 9:

| Object | Spawn process | Read stdout | LOM | Frozen-free CI embed | Notes |
|---|---|---|---|---|---|
| `[node.script]` | Yes (native Node) | Yes | Yes (via LiveAPI) | **Yes, via `@embed 1` in Max 9** | Your current engine; `@embed` likely eliminates mx@c entirely |
| `[v8]` | No (no `child_process`) | N/A | Yes (full LiveAPI) | Yes (plain text via `@embed`) | Clean CI story but cannot spawn your native binary |
| `[js]` (legacy) | No | N/A | Yes | Yes with `@embed` | Superseded by v8; ES5 only |
| `[jweb]` | No (CEF sandbox) | N/A | Indirect | Assets bundled on freeze | Only useful if you rewrite bridge as HTTP/WebSocket server |
| `[shell]` (Jeremy Bernstein) | **Yes** | Yes (chunked, you split lines) | No (must plumb through v8/js) | No — still a separate external that needs freeze to bundle | MIT, fat binaries, unmaintained since 2021 |
| `[aka.shell]` | Partial | Yes | No | No | 32-bit, effectively dead post–Max 6 |

The **`[v8]` + `[shell]` combo** is the only Max-native way to get spawn-process-with-LOM without Node: `[shell]` spawns `stemforge-native` and pipes stdout, while a `[v8 @embed 1]` object splits NDJSON lines and drives LOM. But `[shell]` is still a third-party external — it will be bundled on freeze (so end-users don't need it installed) but you still need the freeze step to bundle it, which returns you to the automation problem. **`[jweb]` and legacy `[js]` cannot spawn processes and are non-starters for your architecture.**

## Headless Max freeze on CI: not viable, UI scripting is the only fallback

There is **no public CLI flag, no `;max freeze` message, no `thispatcher` freeze scripting message, and no JS Patcher freeze API**. The documented messages-to-Max list (`buildcollective`, `openfile`, `closefile`, `quit`, `nosavedialog`) contains no freeze verb. The only mechanism ever known to work — opening an `.amxd` in standalone Max and triggering Ctrl-S via a scripting host — was removed around Max 7.3.3. Ableton's internal TypeScript freezer remains unreleased. macOS GitHub Actions runners can in principle drive Live+Max via `osascript`/`cliclick` to click the Edit-in-Max button and the Freeze toolbar button, but **no community recipe for this exists publicly**, and you'd need to install and license Live on the runner, deal with first-launch authorization, and babysit UI-scripting brittleness against every Live/Max update. This is the workaround of last resort, not a production path.

## The Max Package + unfrozen .amxd approach is the clean answer

**This is the recommended path and the one Cycling '74 and Ableton themselves use.** Ship your JS bridge as a Max Package folder installed by your existing `.pkg` to `~/Documents/Max 9/Packages/StemForge/` (and mirror to `Max 8/` for back-compat). Max auto-adds `javascript/` to its flat search path at launch, so an **unfrozen** `[node.script stemforge_bridge.v0.js]` resolves the file by bare filename — no paths, no mx@c, no freeze. This works identically inside Ableton Live: the bundled M4L runtime reads the same package folder as standalone Max. Live 12 in particular does not sandbox the path. Keep your filename namespaced (you already have `stemforge_bridge.v0.js`, which is ideal) because the search path is flat.

Concrete layout:

```
~/Documents/Max 9/Packages/StemForge/
├── package-info.json          # name, version, os, forcerestart:1
├── javascript/
│   └── stemforge_bridge.v0.js
├── patchers/                   # optional shared abstractions
└── media/

~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/
└── StemForge.amxd             # unfrozen, references JS by bare filename
```

Build it from GitHub Actions with `pkgbuild`/`productbuild`. Use a Distribution.xml with `<domains enable_currentUserHome="true"/>` so no admin prompt appears and files land user-owned; otherwise `chown -R "$USER:staff"` in a `postinstall` script. Users must restart Live after install (packages are scanned at launch only). Precedent for the pattern: **Cycling '74's Node for Max, RNBO, BEAP** (all shipped as packages with unfrozen devices referencing package JS); **Ableton's built-in Live 12 M4L devices and the "Building Max Devices" pack** (unfrozen, dependencies in a shared Pack folder — explicitly codified in Ableton's public **patch-code-standard**); **MaxScore/LiveScore's custom installer** (directly parallel to your use case).

The one caveat: Ableton's public **m4l-production-guidelines** says *"Failing to freeze a device before sharing or distributing it can often result in a device malfunctioning due to broken file references,"* a warning aimed at casual drag-and-drop sharing. When you control the install vector (your `.pkg`), that risk evaporates — which is exactly why Cycling '74 and Ableton themselves use the unfrozen-plus-package pattern for their own content. Display a clear error banner in the device if the JS file is missing, use an unambiguous package name to avoid collisions, and clean up older versions on upgrade.

## Concrete recommendations for StemForge

**Do this first, in parallel, and pick whichever lands cleanly:**

1. **Test Max 9 `@embed 1` on `[node.script]` today.** Open your device in Max 9, set `@embed 1` on the node.script object, save, and diff the resulting `.amxd` JSON. If the JS body appears as a plain string inside the patcher JSON (no `mx@c` binary wrapper), you can template the JSON from CI with a ~50-line script and never run Max. This is the fastest possible win and invalidates most of the pain you described.

2. **Build the Max Package pipeline as the fallback (and arguably primary).** Structure your repo as `packages/StemForge/javascript/stemforge_bridge.v0.js` + unfrozen `StemForge.amxd`, have your GitHub Actions workflow bundle both into a `.pkg` via `pkgbuild`/`productbuild` with `enable_currentUserHome="true"` to avoid root-owned files. This is a two-day job with no Max installation required on the runner.

**Avoid these paths:** reverse-engineering the `mx@c` checksum (undocumented, unstable across Max versions, no community starting point); UI-scripting Max freeze on a GHA macOS runner (brittle, requires Live license, no public recipe); rewriting the bridge for `[v8]` (cannot spawn child processes); `[shell]` alone (no LOM access, still needs freeze to bundle the external).

## Closing perspective

The gap you've hit — no public automation for `.amxd` freezing — is real, well-documented in the community, and unlikely to close soon. Ableton has a working solution they haven't released; Cycling '74 has not added a CLI flag in either Max 9.0 or 9.1. The **two durable answers are the ones that avoid freezing altogether**: Max 9's `@embed` attribute for truly embedded inline JS, and the Max Package pattern for externally-resolved JS shipped via your installer. Both let you build `.amxd` artifacts deterministically from CI with no Max runtime and no mx@c guesswork, and the Package approach in particular has years of precedent from the vendors themselves. That's the path to ship.