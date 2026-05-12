# TOP3_TUNING_SPEC §7 — Answers

Verified against the actual repo at `/Users/zacharybrown/zacharysbrown/quarks` on 2026-04-23.

---

## 7.1 LifeConstraints loader

### 1. Path + line range

`openclaw/claw-os/agents/_toby/subagents/executive_planner/life_constraints.py`:

| Method | Line |
|---|---|
| `LifeConstraints.load(cls, path)` | 181 |
| `LifeConstraints.load_current(cls)` | 197 (reads `/home/node/.openclaw/executive_planner/current.yaml`) |
| `LifeConstraints._from_dict(cls, d)` | 203 (the actual YAML→dataclass parser) |

The extension point for `morning_routine` + `evening_pattern` is `_from_dict` at line 203.

### 2. Pattern

Plain Python `@dataclass`. The main `LifeConstraints` dataclass aggregates nested dataclasses (`Block`, `SoftBlock`, `EnergyWindow`, `GearShift`, etc.).

For the new fields, add to the main dataclass:
```python
morning_routine: dict = field(default_factory=dict)
evening_pattern: dict = field(default_factory=dict)
```

Populate in `_from_dict`:
```python
morning_routine = d.get("morning_routine") or {}
evening_pattern = d.get("evening_pattern") or {}
```

No need to build new nested dataclasses for these — raw dicts are simpler and the Top 3 helpers already expect dict access.

### 3. Tests exist

`tests/test_executive_planner_life_constraints.py` — 35 tests currently. Pattern:

```python
MINIMAL_YAML = textwrap.dedent("""\
    week_of: 2026-04-20
    ...
""")

@pytest.fixture
def minimal_constraints(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(MINIMAL_YAML)
    return LifeConstraints.load(p)
```

Add a fixture with `morning_routine:` + `evening_pattern:` sections. Assert `c.morning_routine["desk_time"]["mon"] == "08:30"` etc.

---

## 7.2 generate_top3.py

### 4. Path + tests

File: `openclaw/claw-os/agents/_toby/subagents/executive_planner/generate_top3.py`.
Tests: `tests/test_executive_planner_top3.py` — 13 tests.

### 5. `_V03_TRACKING_DIR`

Module-level constant at **line 28**:
```python
_V03_TRACKING_DIR = Path("/home/node/.openclaw/tracking")
_TOP3_PATH = _V03_TRACKING_DIR / "todays-top-3.md"
```

Tests patch via `monkeypatch.setattr("agents._toby.subagents.executive_planner.generate_top3._V03_TRACKING_DIR", tmp_path / "tracking")`.

The new helpers in the spec reference it as-is — that's correct. Either read `_V03_TRACKING_DIR` directly in the new helpers OR accept a `path:` arg with `_V03_TRACKING_DIR` as default — both patterns exist in the codebase already.

### 6. `_read_whoop_summary` at 06:10

**Returns `None`** at morning-push time.

The function looks for today's date in `whoop-daily-summary.jsonl`. At 06:10 Thursday, today's entry doesn't exist yet (the 20:30 cron will write today's summary tonight; the most recent entry in the file is yesterday's).

The live recovery value at 06:10 comes from `day.whoop_recovery` (populated by the DayModel assembler via a live API call), not from the summary file. The Top 3 generator already handles this: `recovery = day.whoop_recovery` then falls back to `(whoop_today or {}).get("recovery_score")`.

The new spec's `_read_whoop_last_n_days(today, n=5)` correctly skips today (`today - timedelta(days=i+1)` where `i ≥ 0`), so yesterday's sedentary data is reachable at 06:10 via `whoop_history[0]`. **Design is right.**

---

## 7.3 DayModel

### 7. `calendar_today` includes ended events

Yes. `_fetch_calendar()` at `day_model.py:183` returns all events in the 00:00→next-day-00:00 window without filtering by "past now."

That's fine because `_find_free_windows` does `start_of_day = max(start_of_day, day.now)` — past events become no-op intervals that sit before the cursor. The busy-interval walk is correct.

### 8. `hard_blocks[].days` type

`frozenset[int]` with Monday=0 (line 55 in `life_constraints.py`). The spec's `_WEEKDAY_TO_KEY = {0: "mon", 1: "tue", ...}` matches.

---

## 7.4 Dashboard

### 9. Framework

**FastAPI (in `notify_server/app.py`) + a single static `notify_server/static/dashboard.html`** (vanilla JS/HTML, no React). 

Route conventions:
- `@app.get("/api/...")` for reads
- `@app.put("/api/...")` for writes
- `@app.get("/dashboard")` serves the HTML shell

Access: notify_server binds 127.0.0.1:8790 only, Tailscale-gated at the host networking layer.

Follow the existing pattern: add `@app.get("/api/routines")` + `@app.put("/api/routines")`, extend `dashboard.html` with the form.

### 10. Existing config-save pattern

Yes — the prompt editor at `notify_server/app.py:1220`:

```python
@app.put("/api/prompts/{agent}/{filename}", response_model=PromptSaveResponse)
def prompt_save(agent: str, filename: str, req: PromptSaveRequest) -> PromptSaveResponse:
    """
    Atomically write a new prompt. The previous content is snapshotted to
    <filename>.bak.<epoch>. We keep the most recent 20 backups per file.
    """
    # 1. Backup existing to <name>.bak.<epoch_seconds>
    # 2. Rotate — keep 20 newest .bak files
    # 3. Write new content
    # 4. Return PromptSaveResponse(backup_name=...)
```

**For `/api/routines`, mirror this** but adapt the backup naming to the spec's convention:
- Backup path: `/home/node/.openclaw/executive_planner/backups/routines-YYYY-MM-DD-HHMMSS.yaml`
- Rotate: keep 20 most recent
- Auth: none beyond Tailscale (same as prompts endpoint)

---

## 7.5 Deployment

### 11. `generate_top3.py` hot-reload

**Yes.** `/opt/claw-os` is a bind mount from `openclaw/claw-os/` in the repo. Every `python3 -m ...` invocation reads the current file from disk. No container restart needed for code changes.

Caveat: within a long-running process, Python caches imported modules in `sys.modules` — but cron-spawned invocations always start fresh, and the 06:10 generator is cron-fired, so hot-reload is effective in practice.

### 12. `routines.yaml` hot-reload

**Yes.** `LifeConstraints.load_current()` reads the file fresh on each call — no in-process cache. The Top 3 generator calls `assemble()` which constructs a DayModel which constructs a LifeConstraints. Dashboard save → next 06:10 run picks up the change automatically.

No restart needed. The dashboard save handler does not need to trigger one.

---

## Path correction — critical before starting

**The spec §1 says `/data/executive_planner/routines.yaml`. That path does not exist.**

No `/data/` volume is mounted on the claw-os container. The correct path, matching where `current.yaml` already lives:

```
/home/node/.openclaw/executive_planner/routines.yaml
```

Backups per the spec's convention:

```
/home/node/.openclaw/executive_planner/backups/routines-YYYY-MM-DD-HHMMSS.yaml
```

This correction applies to:
- Spec §1 (file location)
- Spec §5 Phase A step 1 (seed target)
- Spec §4.3 (backup dir)

Otherwise every path/detail in the spec matches the actual repo.

---

## Summary — ready to implement

All 12 questions answered. Key implementation points:

| Where | What |
|---|---|
| `life_constraints.py:~170` (main dataclass) + `:203` (`_from_dict`) | Add `morning_routine`, `evening_pattern` dict fields |
| `test_executive_planner_life_constraints.py` | New fixture + 2 assertion tests |
| `generate_top3.py` | Add 6 helpers + replace `_build_top3` per spec §2 |
| `test_executive_planner_top3.py` | 6 new unit tests for the new helpers |
| `notify_server/app.py` | Add `@app.get/put /api/routines` mirroring the prompts pattern |
| `notify_server/static/dashboard.html` | Add the `/routines` page per §4 layout |
| `/home/node/.openclaw/executive_planner/routines.yaml` | Seed file (volume write via docker exec) |

No WhatsApp touch. No whatsapp-sender restart. No `.env.claw-os` changes. Protected Systems untouched.
