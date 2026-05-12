# Top 3 Tuning — Handoff Spec

**Status:** Ready for Claude Code implementation
**Target:** `agents/_toby/subagents/executive_planner/generate_top3.py` + LifeConstraints loader + dashboard
**Scope:** Tuning pass on existing v0.3 Top 3 generator. Not a rewrite.

---

## 0. What we're fixing

Today's Top 3 (Thu 4/23) output had three problems:

1. **Morning routine invisibility** — suggested a deep block at 06:30 when Zak is making coffee.
2. **Generic movement item** — "20-min walk — movement floor" when yesterday's sedentary data should be leading.
3. **Weak tracking gap callout** — "Log last night's dinner" when the real observation is "you've missed N of 7 days."

The fix is targeted: a new `routines.yaml` config, three new helper functions, a revised `_build_top3`, and a dashboard page to edit routines.

---

## 1. New file: `/home/node/.openclaw/executive_planner/routines.yaml`

Separate from `current.yaml` (which lives in the same directory). Static config. Human-authored only. Never written by the planner.

**Seed content:**

```yaml
# Routines — how my days work, independent of any given week.
# Edit via dashboard (Tailscale-only Toby UI).
# Last updated: 2026-04-23

morning_routine:
  wake: "06:00"
  coffee_until: "07:00"
  walk_window:
    weekday: ["06:45", "07:30"]   # M/W/F — desk at 08:30
    tr:      ["06:45", "08:00"]    # T/R — desk at 09:15, window extends
    weekend: ["07:00", "09:00"]
  shower_until: "07:45"
  desk_time:
    mon: "08:30"
    tue: "09:15"
    wed: "08:30"
    thu: "09:15"
    fri: "08:30"
    # weekends unlisted = no fixed desk_time (variable)

evening_pattern:
  wind_down_start: "20:30"
  latest_coding: "21:00"
  lights_out_target: "22:30"
```

### 1.1 Loader integration

The existing `LifeConstraints` loader at `openclaw/claw-os/agents/_toby/subagents/executive_planner/life_constraints.py` should be extended to read `routines.yaml` from the same directory as `current.yaml` and expose both as attributes.

**Concrete changes (from repo inspection):**

Main `LifeConstraints` dataclass (around line 170) — add two fields:

```python
morning_routine: dict = field(default_factory=dict)
evening_pattern: dict = field(default_factory=dict)
```

`_from_dict` (line 203) — populate:

```python
morning_routine = d.get("morning_routine") or {}
evening_pattern = d.get("evening_pattern") or {}
```

**Where these dicts come from:** `LifeConstraints.load_current()` currently reads `current.yaml`. Extend it to also read `routines.yaml` from the same directory (`/home/node/.openclaw/executive_planner/`) and merge the two dicts before calling `_from_dict`. If `routines.yaml` is missing, the merged dict just lacks `morning_routine` / `evening_pattern` keys, and the default `field(default_factory=dict)` kicks in.

No new nested dataclasses. Raw dicts are simpler and the Top 3 helpers already expect dict access.

After this change:

```python
day.constraints.morning_routine  # dict from routines.yaml
day.constraints.evening_pattern  # dict from routines.yaml
# plus all existing current.yaml attributes
```

If `routines.yaml` is missing entirely, the loader returns empty dicts for both — the Top 3 generator falls back to the v0.2 behavior (no desk_time gating, no walk window logic).

---

## 2. Revised `generate_top3.py`

Full replacement for `_build_top3()` plus five new helpers. Existing imports, `Top3Item` dataclass, `_format_slot()`, `_duration_minutes()`, `_read_morning_intent()`, `_read_whoop_summary()`, `_read_mfp_summary()`, `_read_last_today_jsonl()`, `_read_grooming_due()`, `_read_kid_hours_since()`, `_read_sunday_plan()`, `_V03_TRACKING_DIR` — all preserved as-is.

```python
from datetime import date, datetime, time, timedelta
from pathlib import Path
import json

# ─────────────────────────────────────────────────────────────────
# Morning routine helpers
# ─────────────────────────────────────────────────────────────────

_WEEKDAY_TO_KEY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


def _get_morning_routine(day) -> dict:
    """Pull morning_routine from constraints. Returns empty dict if missing."""
    return getattr(day.constraints, "morning_routine", {}) or {}


def _desk_time_today(day) -> datetime | None:
    """Return datetime when Zak is at desk today, or None if variable (weekends)."""
    routine = _get_morning_routine(day)
    desk_times = routine.get("desk_time", {})
    key = _WEEKDAY_TO_KEY[day.now.weekday()]
    desk_str = desk_times.get(key)
    if not desk_str:
        return None
    h, m = map(int, desk_str.split(":"))
    return day.now.replace(hour=h, minute=m, second=0, microsecond=0)


def _walk_window_today(day) -> tuple[time, time] | None:
    """Return (start, end) walk window for today's day-class, or None if not configured."""
    routine = _get_morning_routine(day)
    windows = routine.get("walk_window", {})
    weekday = day.now.weekday()
    if weekday in (5, 6):
        key = "weekend"
    elif weekday in (1, 3):
        key = "tr"
    else:
        key = "weekday"
    win = windows.get(key)
    if not win or len(win) != 2:
        return None
    start_h, start_m = map(int, win[0].split(":"))
    end_h, end_m = map(int, win[1].split(":"))
    return (time(start_h, start_m), time(end_h, end_m))


def _walk_eligible(day) -> tuple[bool, time | None, time | None]:
    """Is the walk window still open? Returns (eligible, start, end)."""
    win = _walk_window_today(day)
    if win is None:
        return (False, None, None)
    start_t, end_t = win
    now_t = day.now.time()
    if now_t >= end_t:
        return (False, start_t, end_t)
    return (True, start_t, end_t)


# ─────────────────────────────────────────────────────────────────
# Free windows — desk_time aware
# ─────────────────────────────────────────────────────────────────

def _find_free_windows(day, min_minutes: int = 30) -> list[tuple[time, time]]:
    """Free windows for WORK blocks. Floor is desk_time (or 08:00 fallback)."""
    desk_dt = _desk_time_today(day)
    if desk_dt is not None:
        start_of_day = desk_dt
    else:
        start_of_day = day.now.replace(hour=8, minute=0, second=0, microsecond=0)

    start_of_day = max(start_of_day, day.now)
    end_of_day = day.now.replace(hour=21, minute=0, second=0, microsecond=0)

    busy = []
    for ev in day.calendar_today:
        if ev.all_day:
            continue
        busy.append((ev.start, ev.end))

    for b in day.constraints.hard_blocks:
        if day.now.weekday() not in b.days:
            continue
        b_start = day.now.replace(hour=b.start.hour, minute=b.start.minute, second=0, microsecond=0)
        b_end = day.now.replace(hour=b.end.hour, minute=b.end.minute, second=0, microsecond=0)
        busy.append((b_start, b_end))

    busy.sort(key=lambda x: x[0])

    free = []
    cursor = start_of_day
    for b_start, b_end in busy:
        if b_start > cursor and (b_start - cursor).total_seconds() / 60 >= min_minutes:
            free.append((cursor.time(), b_start.time()))
        cursor = max(cursor, b_end)
    if cursor < end_of_day and (end_of_day - cursor).total_seconds() / 60 >= min_minutes:
        free.append((cursor.time(), end_of_day.time()))
    return free


# ─────────────────────────────────────────────────────────────────
# WHOOP history + movement observation
# ─────────────────────────────────────────────────────────────────

def _read_whoop_last_n_days(today: date, n: int) -> list[dict]:
    """Read last N days of WHOOP summaries (most recent first). Missing days omitted."""
    path = _V03_TRACKING_DIR / "whoop-daily-summary.jsonl"
    if not path.exists():
        return []
    summaries_by_date = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                summaries_by_date[rec["date"]] = rec
            except (json.JSONDecodeError, KeyError):
                continue
    out = []
    for i in range(n):
        d = today - timedelta(days=i + 1)  # yesterday and back
        key = d.isoformat()
        if key in summaries_by_date:
            out.append(summaries_by_date[key])
    return out


def _movement_observation(
    whoop_today: dict | None,
    whoop_history: list[dict],
    intent: str | None,
    eligible: bool,
    walk_start: time | None,
    walk_end: time | None,
):
    """
    Return a Top3Item for the movement slot, or None if already worked out today.

    Priority:
      1. Worked out today → None (caller fills slot with tracking/kid/grooming)
      2. Intent declared (gym/walk/etc.) → reinforce it
      3. Sedentary yesterday (2+ day streak escalates) → lead with data
      4. Walk window still open → propose neutrally
      5. Fallback floor
    """
    workouts_today = (whoop_today or {}).get("workouts") or []
    if workouts_today:
        return None

    # Intent-driven
    if intent:
        intent_lower = intent.lower()
        if any(kw in intent_lower for kw in ("gym", "workout", "lift", "strength")):
            return Top3Item(0, f"Follow through on morning intent: {intent.strip()}", reason="intent:gym")
        if any(kw in intent_lower for kw in ("walk", "run", "bike", "ride")):
            return Top3Item(0, f"Walk — {intent.strip()}", reason="intent:walk")

    # Sedentary pattern detection
    sedentary_yesterday = None
    if whoop_history:
        sedentary_yesterday = (whoop_history[0] or {}).get("sedentary_hours")

    streak = 0
    for rec in whoop_history:
        sh = rec.get("sedentary_hours")
        workouts = rec.get("workouts") or []
        if sh is not None and sh >= 9.0 and not workouts:
            streak += 1
        else:
            break

    observation = None
    if sedentary_yesterday is not None and sedentary_yesterday >= 9.0:
        if streak >= 2:
            observation = f"Yesterday: {sedentary_yesterday:.1f}h sedentary. {streak}th day in a row."
        else:
            observation = f"Yesterday: {sedentary_yesterday:.1f}h sedentary."

    # Compose
    if eligible and walk_start and walk_end:
        if observation:
            title = f"Walk — {observation} Window open until {walk_end.strftime('%H:%M')}."
        else:
            title = f"Walk — window {walk_start.strftime('%H:%M')}–{walk_end.strftime('%H:%M')} if you can catch it."
        return Top3Item(0, title, reason="walk_eligible")

    # Walk window passed
    if observation:
        return Top3Item(0, f"Movement today. {observation}", reason="sedentary")

    return Top3Item(0, "Movement today — 20+ min, any time.", reason="movement_floor")


# ─────────────────────────────────────────────────────────────────
# Tracking consistency — 7-day snapshot with tiered priority
# ─────────────────────────────────────────────────────────────────

def _count_days_with_entries(path: Path, today: date, lookback: int) -> int:
    """Count distinct dates in a jsonl within the last `lookback` days (excluding today)."""
    if not path.exists():
        return 0
    seen_dates = set()
    cutoff = today - timedelta(days=lookback)
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            dkey = rec.get("date")
            if not dkey:
                lg = rec.get("logged_at")
                if lg:
                    dkey = lg[:10]
            if not dkey:
                continue
            try:
                d = date.fromisoformat(dkey)
            except ValueError:
                continue
            if cutoff <= d < today:
                seen_dates.add(d)
    return len(seen_dates)


def _count_whoop_workout_days(today: date, lookback: int) -> int:
    """Count days in last `lookback` with at least one logged WHOOP workout."""
    path = _V03_TRACKING_DIR / "whoop-daily-summary.jsonl"
    if not path.exists():
        return 0
    cutoff = today - timedelta(days=lookback)
    seen = set()
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            dkey = rec.get("date")
            if not dkey:
                continue
            try:
                d = date.fromisoformat(dkey)
            except ValueError:
                continue
            if cutoff <= d < today and (rec.get("workouts") or []):
                seen.add(d)
    return len(seen)


def _tracking_consistency(today: date, lookback: int = 7) -> dict:
    """
    Build a 7-day snapshot of tracking behaviors.

    Returns: {
        "snapshot": {source: days_logged, ...},
        "callout": {source, tier, text} or None
    }

    Tier 1 (system-critical): MFP, WHOOP workouts — if thin, always leads #3.
    Tier 2 (relationship): kid_log — handled by caller via kid_hours.
    Tier 3 (reflection): morning_intent, weight — softer, only if no Tier 1 gap.
    """
    snapshot = {
        "mfp": _count_days_with_entries(
            _V03_TRACKING_DIR / "mfp-daily-summary.jsonl", today, lookback
        ),
        "morning_intent": _count_days_with_entries(
            _V03_TRACKING_DIR / "morning-intent.jsonl", today, lookback
        ),
        "kid_log": _count_days_with_entries(
            _V03_TRACKING_DIR / "kid-log.jsonl", today, lookback
        ),
        "weight": _count_days_with_entries(
            _V03_TRACKING_DIR / "weight.jsonl", today, lookback
        ),
        "whoop_workouts": _count_whoop_workout_days(today, lookback),
    }

    callout = None

    # Tier 1
    if snapshot["mfp"] < 4:
        callout = {
            "source": "mfp",
            "tier": 1,
            "text": f"MFP: {snapshot['mfp']}/{lookback} days logged. Tracking is the system. Log last night now.",
        }
    elif snapshot["whoop_workouts"] < 2:
        callout = {
            "source": "whoop_workouts",
            "tier": 1,
            "text": f"WHOOP workouts: {snapshot['whoop_workouts']}/{lookback} days logged. Manual entry is on you.",
        }

    if callout:
        return {"snapshot": snapshot, "callout": callout}

    # Tier 3
    if snapshot["morning_intent"] < 3:
        callout = {
            "source": "morning_intent",
            "tier": 3,
            "text": f"Morning intent: {snapshot['morning_intent']}/{lookback} days. Cheap and grounds everything else.",
        }
    elif snapshot["weight"] < 2:
        callout = {
            "source": "weight",
            "tier": 3,
            "text": f"Weight: {snapshot['weight']}/{lookback} days. Every-other-day cadence.",
        }

    return {"snapshot": snapshot, "callout": callout}


# ─────────────────────────────────────────────────────────────────
# Main: revised _build_top3
# ─────────────────────────────────────────────────────────────────

def _build_top3(day, today: date) -> tuple[list[Top3Item], str, str]:
    """Return (items, state_line, context_line)."""
    intent = _read_morning_intent(today)
    whoop_today = _read_whoop_summary(today)
    whoop_history = _read_whoop_last_n_days(today, n=5)
    mfp_yesterday = _read_last_today_jsonl(
        _V03_TRACKING_DIR / "mfp-daily-summary.jsonl",
        today - timedelta(days=1),
    )
    grooming_due = _read_grooming_due()
    kid_hours = _read_kid_hours_since(today)
    tracking = _tracking_consistency(today, lookback=7)

    recovery = day.whoop_recovery
    if recovery is None:
        recovery = (whoop_today or {}).get("recovery_score")

    # ─── State line — TIGHT ───
    state_parts = [f"{WEEKDAY_NAMES[today.weekday()]} {today.strftime('%-m/%-d')}, {day.now.strftime('%H:%M')}."]
    if recovery is not None:
        state_parts.append(f"Recovery {int(recovery)}.")
    state_line = " ".join(state_parts)

    # ─── Context line — desk_time + free windows ───
    desk_dt = _desk_time_today(day)
    free_windows = _find_free_windows(day, min_minutes=45)
    ctx_parts = []
    if desk_dt is not None and day.now < desk_dt:
        ctx_parts.append(f"Desk at {desk_dt.strftime('%H:%M')}.")
    if free_windows:
        window_strs = [_format_slot(s, e) for s, e in free_windows[:2]]
        ctx_parts.append(f"Free: {', '.join(window_strs)}.")
    else:
        ctx_parts.append("Schedule dense — no windows ≥45m.")
    context_line = " ".join(ctx_parts)

    # ─── Low-recovery reframe ───
    if recovery is not None and recovery < 34:
        return (
            [
                Top3Item(1, "Rest day. Skip workout.", reason="recovery red"),
                Top3Item(2, "Protein floor and sleep runway tonight", reason="recovery red"),
                Top3Item(
                    3,
                    grooming_due[0]["name"].replace("_", " ") if grooming_due else "Recover.",
                    reason="recovery red",
                ),
            ],
            state_line,
            f"Recovery {int(recovery)} (red). Don't stack intensity.",
        )

    # ─── Build items ───
    items: list[Top3Item] = []

    # ITEM 1 — biggest free work window
    if free_windows:
        top_win = max(free_windows, key=lambda w: _duration_minutes(w[0], w[1]))
        slot = _format_slot(top_win[0], top_win[1])
        dur_min = _duration_minutes(top_win[0], top_win[1])
        hrs = dur_min // 60
        mins = dur_min % 60
        dur_str = f"{hrs}h{mins:02d}m" if hrs else f"{mins}m"
        items.append(Top3Item(0, f"deep block ({dur_str} clear)", slot_hint=slot, reason="largest free window"))
    else:
        items.append(Top3Item(0, "Meeting-dense day. No deep block available. Execute only.", reason="no free window"))

    # ITEM 2 — movement
    eligible, walk_start, walk_end = _walk_eligible(day)
    move_item = _movement_observation(whoop_today, whoop_history, intent, eligible, walk_start, walk_end)

    if move_item is not None:
        items.append(move_item)

    # ITEM 3 — tracking consistency > kid gap > grooming > default
    # If movement slot was skipped (already worked out), item 3 still uses this priority.
    third_item = None

    # Tier 1 tracking gap wins
    if tracking["callout"] and tracking["callout"]["tier"] == 1:
        third_item = Top3Item(0, tracking["callout"]["text"], reason=f"tracking:{tracking['callout']['source']}")
    # Tier 2: kid gap ≥48h
    elif kid_hours is not None and kid_hours >= 48:
        third_item = Top3Item(0, f"Kid time — last logged {kid_hours:.0f}h ago.", reason="kid_gap")
    # Tier 3 tracking (soft)
    elif tracking["callout"] and tracking["callout"]["tier"] == 3:
        third_item = Top3Item(0, tracking["callout"]["text"], reason=f"tracking:{tracking['callout']['source']}")
    # Grooming
    elif grooming_due:
        top_groom = grooming_due[0]
        third_item = Top3Item(
            0,
            f"{top_groom['name'].replace('_', ' ')} — {top_groom.get('status', 'due')}",
            reason="grooming",
        )
    # Default
    else:
        third_item = Top3Item(0, "Evening debrief to Claude iOS.", reason="default reflection")

    items.append(third_item)

    # If movement was skipped (already worked out today), item list will be 2 entries.
    # Promote a second tracking/grooming item into slot 2.
    if len(items) < 3:
        # Need a second non-work item. Try the next-highest-priority thing not already in items[2].
        used_reason = items[-1].reason
        filler = None
        if used_reason != "kid_gap" and kid_hours is not None and kid_hours >= 48:
            filler = Top3Item(0, f"Kid time — last logged {kid_hours:.0f}h ago.", reason="kid_gap")
        elif not used_reason.startswith("grooming") and grooming_due:
            top_groom = grooming_due[0]
            filler = Top3Item(
                0,
                f"{top_groom['name'].replace('_', ' ')} — {top_groom.get('status', 'due')}",
                reason="grooming",
            )
        elif used_reason != "default reflection":
            filler = Top3Item(0, "Evening debrief to Claude iOS.", reason="default reflection")

        if filler:
            items.insert(1, filler)
        else:
            # Last resort: acknowledge already-strong day
            items.insert(1, Top3Item(0, "Worked out. Hold the line.", reason="already on track"))

    for i, item in enumerate(items[:3], start=1):
        item.rank = i

    return items[:3], state_line, context_line
```

---

## 3. Expected output for today (Thu 4/23)

Given these inputs:
- Now: 10:10
- Recovery: 40
- Yesterday: 11.7h sedentary, no workouts
- Day before: 10.2h sedentary, no workouts (streak = 2)
- Walk window (T/R): 06:45–08:00 — already passed
- Desk time: 09:15 — already passed
- Calendar: staff sync 13:00, meetings 09:00 + 09:30 done
- Free windows: 10:15–12:30 (135m), 14:30–17:00 (150m)
- MFP last 7 days: 5 logs (OK, no callout)
- WHOOP workouts last 7 days: 1 (< 2 threshold → Tier 1 callout)

Rendered output:

```
Thu 4/23, 10:10. Recovery 40.
Free: 10:15–12:30, 14:30–17:00.

1. 14:30–17:00 — deep block (2h30m clear)
2. Movement today. Yesterday: 11.7h sedentary. 2nd day in a row.
3. WHOOP workouts: 1/7 days logged. Manual entry is on you.

Week plan: [from sunday-plan.md if present]
```

Three things to notice vs. the old output:

- State line is one line. Recovery only. Yesterday's data moved into item 2 where it earns its place.
- Context line no longer mentions 06:30 because desk_time has passed.
- Item 2 leads with the observation, not the prescription.
- Item 3 calls out the real tracking gap (WHOOP workouts) instead of the soft "log last night's dinner" nudge.

---

## 4. Dashboard spec — `/routines` page

**Access:** Existing Tailscale-only Toby dashboard.

**Layout:** Single page, two sections.

### 4.1 Morning section

- **Wake** — time input
- **Coffee until** — time input
- **Shower until** — time input

**Walk window** subsection:
- **Weekday (M/W/F)** — two time inputs (start, end)
- **Tue/Thu** — two time inputs
- **Weekend** — two time inputs

**Desk time** subsection:
- **Mon / Tue / Wed / Thu / Fri** — five time inputs (weekends omitted intentionally)

### 4.2 Evening section

- **Wind-down start** — time input
- **Latest coding** — time input
- **Lights-out target** — time input

### 4.3 Save behavior

Mirror the existing prompt-editor pattern at `notify_server/app.py:1220` (`@app.put("/api/prompts/{agent}/{filename}")`). Specifically:

**Endpoints:**
- `@app.get("/api/routines")` — return current `routines.yaml` contents as JSON
- `@app.put("/api/routines")` — accept new YAML, validate, backup, write

**Auth:** None beyond Tailscale. The prompts endpoint uses the same model — notify_server binds 127.0.0.1:8790 only, Tailscale-gated at host networking. Do not add application-level auth.

**On save:**

1. Validate all fields (valid HH:MM, walk_window start < end, desk_time is after shower_until).
2. Snapshot current `routines.yaml` to `/home/node/.openclaw/executive_planner/backups/routines-YYYY-MM-DD-HHMMSS.yaml` (match the prompts endpoint's atomic-backup pattern, but use the dated filename per this spec's convention rather than `.bak.<epoch>`).
3. Rotate backups — keep 20 most recent `routines-*.yaml` files, delete older.
4. Write the new YAML with stable formatting (2-space indent, preserving the header comment).
5. Return `{"backup_name": "routines-YYYY-MM-DD-HHMMSS.yaml"}` for the UI to show a confirmation: "Saved. Backup at [path]."

No auto-save. No live-edit. One explicit save button.

**No restart needed after save.** `LifeConstraints.load_current()` reads the file fresh on each call — the next 06:10 run picks up the change automatically.

---

## 5. Implementation order

Strict sequence. Each step verifies before advancing.

### Phase A — Config plumbing (no behavior change)

1. Create `/data/executive_planner/routines.yaml` with seed content from §1.
2. Extend `LifeConstraints` loader to read `routines.yaml` and expose `morning_routine` + `evening_pattern` attributes.
3. Run existing tests. Nothing should break (morning_routine is additive).
4. Verify `_get_morning_routine(day)` returns the expected dict via a quick manual test.

### Phase B — Top 3 helpers (pure functions, testable in isolation)

5. Add `_desk_time_today()`, `_walk_window_today()`, `_walk_eligible()` helpers.
6. Add `_read_whoop_last_n_days()` + `_movement_observation()` helpers.
7. Add `_count_days_with_entries()`, `_count_whoop_workout_days()`, `_tracking_consistency()` helpers.
8. Write unit tests for each helper with fixtures covering: empty data, partial data, boundary conditions (threshold-1 and threshold).

### Phase C — Revised `_build_top3`

9. Replace `_find_free_windows()` with the desk_time-aware version.
10. Replace `_build_top3()` with the new version.
11. Run against today's live data. Compare output to the expected example in §3.
12. **Do NOT push to WhatsApp yet** — write to `todays-top-3.md` and verify by eye for 2 days before enabling the push.

### Phase D — Dashboard

13. Build `/routines` page per §4 spec.
14. Verify save/backup round-trip works.
15. Verify a routines.yaml edit via dashboard is picked up by the next Top 3 run (no restart required, or document if restart is needed).

### Phase E — Regression confirmation

16. Morning brief renders for 2 consecutive days with no errors.
17. Existing v0.3 crons all fire as expected.
18. WhatsApp bidirectional flow unchanged (no QR re-pair).
19. MFP logging still works end-to-end.

---

## 6. Regression protection

The morning brief reads `todays-top-3.md` (via the daily-plan artifact). Any change to the format or location of that file risks the morning brief.

**Explicit constraints:**

- `todays-top-3.md` stays at its current path.
- The rendering format stays the same shape (state_line, context_line, blank line, numbered items, optional week plan). The *contents* change; the structure doesn't.
- The `daily-plan-YYYY-MM-DD.md` artifact consumes `todays-top-3.md` — no change to that consumption pattern.
- No touches to `whatsapp-sender`, Baileys session files, or the `:8791` endpoint.

**Rollback criteria** (immediate revert):
- Morning brief fails to render for 2 consecutive days.
- Top 3 produces empty or malformed output.
- Dashboard save corrupts `routines.yaml`.
- Any Protected System from v0.3 spec §5 breaks.

---

## 7. Repo-verified implementation details

These are answers to pre-implementation questions, verified against the actual repo at `/Users/zacharybrown/zacharysbrown/quarks` on 2026-04-23. Use these directly — do not re-derive.

### 7.1 LifeConstraints loader

**File:** `openclaw/claw-os/agents/_toby/subagents/executive_planner/life_constraints.py`

| Method | Line |
|---|---|
| `LifeConstraints.load(cls, path)` | 181 |
| `LifeConstraints.load_current(cls)` | 197 (reads `/home/node/.openclaw/executive_planner/current.yaml`) |
| `LifeConstraints._from_dict(cls, d)` | 203 (the YAML→dataclass parser) |

**Pattern:** Plain Python `@dataclass`. Main dataclass aggregates nested dataclasses (`Block`, `SoftBlock`, `EnergyWindow`, `GearShift`). For `morning_routine` + `evening_pattern`, use raw `dict` fields (no new nested dataclasses — simpler, and the helpers expect dict access).

**Extension point is line 203 in `_from_dict`.** See §1.1 for the exact additions.

**Tests:** `tests/test_executive_planner_life_constraints.py` — 35 existing tests. Pattern:

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

Add a fixture that includes `morning_routine:` and `evening_pattern:` sections. Assertions like `c.morning_routine["desk_time"]["mon"] == "08:30"`.

### 7.2 generate_top3.py

**File:** `openclaw/claw-os/agents/_toby/subagents/executive_planner/generate_top3.py`
**Tests:** `tests/test_executive_planner_top3.py` — 13 existing tests.

**`_V03_TRACKING_DIR`** is a module-level constant at line 28:

```python
_V03_TRACKING_DIR = Path("/home/node/.openclaw/tracking")
_TOP3_PATH = _V03_TRACKING_DIR / "todays-top-3.md"
```

Tests patch it via `monkeypatch.setattr(...)`. The new helpers in §2 reference `_V03_TRACKING_DIR` directly — that's correct and matches existing conventions.

**Critical behavior — `_read_whoop_summary(today)` at 06:10:**

Returns `None`. Today's entry isn't in `whoop-daily-summary.jsonl` yet because the writer cron runs at 20:30.

The live recovery value at 06:10 comes from `day.whoop_recovery` (populated by the DayModel assembler via a live API call), NOT the summary file. The existing logic handles this: `recovery = day.whoop_recovery` then falls back to `(whoop_today or {}).get("recovery_score")`.

**The new `_read_whoop_last_n_days(today, n=5)` is correct as specified** — it skips today (`today - timedelta(days=i+1)`), so yesterday's sedentary data is reachable at 06:10 via `whoop_history[0]`. No changes needed.

### 7.3 DayModel

**`calendar_today` includes already-ended events.** `_fetch_calendar()` at `day_model.py:183` returns all events in the 00:00→next-day-00:00 window without filtering by "past now." Fine for `_find_free_windows` because `start_of_day = max(start_of_day, day.now)` makes past events no-ops.

**`hard_blocks[].days` is `frozenset[int]` with Monday=0** (`life_constraints.py:55`). Spec's `_WEEKDAY_TO_KEY = {0: "mon", 1: "tue", ...}` is correct.

### 7.4 Dashboard

**Framework:** FastAPI (`notify_server/app.py`) + single static `notify_server/static/dashboard.html` (vanilla JS/HTML, no React).

**Route pattern:**
- `@app.get("/api/...")` for reads
- `@app.put("/api/...")` for writes
- `@app.get("/dashboard")` serves the HTML shell

**For `/api/routines`:** mirror the prompt-editor pattern at `notify_server/app.py:1220`:

```python
@app.put("/api/prompts/{agent}/{filename}", response_model=PromptSaveResponse)
def prompt_save(agent: str, filename: str, req: PromptSaveRequest) -> PromptSaveResponse:
    """
    Atomically write. Previous content → <filename>.bak.<epoch>.
    Keep 20 most recent backups per file.
    """
    # 1. Backup existing to <n>.bak.<epoch_seconds>
    # 2. Rotate — keep 20 newest
    # 3. Write new content
    # 4. Return PromptSaveResponse(backup_name=...)
```

Adapt for routines: use the dated filename convention from §4.3 (`routines-YYYY-MM-DD-HHMMSS.yaml` in `backups/` subdirectory) rather than `.bak.<epoch>`. Auth: none beyond Tailscale.

### 7.5 Deployment — hot-reload confirmed

**Code changes to `generate_top3.py`:** Hot-reloaded. `/opt/claw-os` is a bind mount from `openclaw/claw-os/` in the repo. Every `python3 -m ...` invocation reads fresh from disk. Cron-fired at 06:10 = always a fresh import.

**Config changes to `routines.yaml`:** Hot-reloaded. `LifeConstraints.load_current()` reads fresh on each call — no in-process cache. Dashboard save → next 06:10 run picks up the change. **No restart needed.**

---

### 7.6 Known nuance — already-worked-out fallback

When `_movement_observation()` returns `None` (Zak already worked out today), `_build_top3()` promotes a filler into slot 2 drawn from the same priority pool as item 3 (Tier 1 tracking gap → kid gap → Tier 3 tracking → grooming → default).

The corner case to watch:

If Zak has worked out AND has no other gaps worth flagging (MFP on track, kid time recent, grooming current, morning intent logged, weight on cadence), slot 2 falls through to `"Worked out. Hold the line."` This is not wrong — it acknowledges the system sees him on track — but it's thin.

**Action for CC:** Ship as written. The fallback line is a known-thin placeholder. After one week of real Top 3 outputs, review how often the "Hold the line" fallback fires and whether it feels right. If it feels weak, the v0.4 iteration should replace that branch with a positive-framing item tied to the week plan (e.g., "Protect tomorrow's Wed morning window" or "You're at 2/3 gym sessions this week, Thursday keeps the streak").

Do NOT invent a richer fallback now. The current fallback is intentionally simple so we can observe how often it's actually hit before deciding what to put there.

---

## 8. Success criteria

Tuning is done when:

1. All Phase A–E steps complete.
2. Today's Top 3 output matches the example in §3 (or Zak explicitly approves any deviation).
3. Dashboard `/routines` page saves/edits round-trip cleanly.
4. Morning brief unchanged for 2 consecutive days post-deploy.
5. No regression on Protected Systems.
6. Zak uses the dashboard to update a routine field at least once and confirms it's reflected in the next Top 3.

If any of those aren't true, don't declare done.
