# Top 3 tuning brief — for claude.ai tuning session

I want to tune the morning Top 3 output my executive planner sends me. It's working but a few things are off. This file has: (1) my critique, (2) the full implementation so you can propose concrete code changes, (3) the voice reference doc.

No writes to production — just give me a revised Python function + any new data wiring needed. I'll apply it locally.

---

## 1. What I'm seeing right now

Today's (Thu 4/23) Top 3 output:

```
Thu 4/23, 10:10. Recovery 40
Free: 06:30–09:00, 12:30–13:30.

1. 06:30–09:00 — deep block
2. 20-min walk — movement floor
3. Log last night's dinner to MFP — missed yesterday
```

## 2. What's off

### 2a. Morning routine is invisible to the planner

The free window `06:30–09:00` **does** correctly avoid my work calendar — but it ignores my non-negotiable morning routine:

- **06:00** — up (confirmable from WHOOP sleep end)
- **06:00–07:00** — coffee / wake up
- **07:00–07:30** — walk (on good days — aspirational, not blocked)
- **07:30–07:45** — shower
- **Then, depending on day:**
  - **M/W/F** — drive oldest to school, at desk **08:30**
  - **T/R** — kids on the bus, at desk **09:15**
  - Weekends — variable

The hard_blocks in my v0.2 YAML already include `school_run_morning` M/W/F 07:40–08:30. But the rest of this isn't baked in anywhere. Toby keeps suggesting a "deep block" at 06:30 which is wrong — I'm literally in my kitchen making coffee at 06:30.

**This is critical. Toby must pay attention to this pattern.** The morning block should never start before 08:30 (M/W/F) or 09:15 (T/R).

### 2b. "Movement floor" sounds bad, and item 2 misses the point

"20-min walk — movement floor" is the right idea but the phrasing is robotic. More importantly, the item ignores yesterday's context: **I barely moved yesterday.** WHOOP steps should confirm this (note: WHOOP API may not expose steps for OAuth apps — sedentary_hours is available). The Top 3 should lead with that observation, not with a generic floor.

Better:
- "Yesterday: N steps (≤5k). Today: walk. Start before the calendar closes."
- "Sedentary 11.7h yesterday. Earliest viable walk window: 07:00–07:30 before shower."

### 2c. Item 3 is too thin — missed the opportunity to call out the pattern

"Log last night's dinner to MFP — missed yesterday" is technically correct but weak. The whole v0.3 bet is that tracking logs are the load-bearing piece. If I've missed MFP for multiple days in a row, THAT's the observation. "You haven't logged N of the last 7 days. The system only works when tracking is in." Sharper.

Similar for kid-log, weight, morning intent — if any tracking is drifting, that's the #3 observation, not a softball "log last night."

---

## 3. What Toby should know about my mornings (codify this)

Add a new section to the v0.2 `current.yaml` (or a new data file — up to you). My preference: add to the constraints YAML as `morning_routine:` with per-day-class details.

```yaml
morning_routine:
  wake: "06:00"
  pre_work:
    coffee_until: "07:00"
    walk_window: ["07:00", "07:30"]  # aspirational, NOT blocked
    shower_until: "07:45"
  desk_time:
    mon: "08:30"
    wed: "08:30"
    fri: "08:30"
    tue: "09:15"
    thu: "09:15"
    # weekends: variable
```

The Top 3 generator should treat `today < desk_time` as "not at desk yet" and:
- NEVER propose a deep block before desk_time
- The earliest work slot is `(desk_time, next_meeting_start)`
- Pre-desk time is candidate for: walk (if in walk_window), or "you're not at your desk yet, don't start"

---

## 4. Current implementation

### 4a. Schedule

- **06:10 daily cron** runs `python3 -m agents._toby.subagents.executive_planner.generate_daily_plan`
- That module delegates to `generate_top3.write_top3()` which:
  - Assembles a `DayModel` (live WHOOP API call + calendar pull + Todoist + MFP totals)
  - Reads tracking files (morning-intent, yesterday's WHOOP/MFP summaries, kid-log, grooming)
  - Reads `sunday-plan.md` (set during Sunday Claude iOS session)
  - Reads hard_blocks from `current.yaml` (school run, dinner, recurring meetings)
  - Computes free windows
  - Ranks 3 items
  - Writes to `todays-top-3.md` (WhatsApp push source) AND `daily-plan-YYYY-MM-DD.md` (morning brief reader)

### 4b. Data available to _build_top3()

| Source | Shape | Where it comes from |
|---|---|---|
| `day.whoop_recovery` | int or None (live API) | WHOOP `/v1/recovery` |
| `day.calendar_today` | list of `CalEvent(summary, start, end, all_day)` | Google Cal (4 calendars merged) |
| `day.todoist_backlog_prioritized` | list of `Task(title, priority)` | Todoist today/overdue filter |
| `day.mfp_protein_g`, `day.mfp_protein_pct` | live MFP | MFP scraper |
| `day.active_session` | Task or None | Todoist @in-progress filter |
| `day.laptop_active_hours_today` | float or None | RescueTime API |
| `day.constraints.hard_blocks` | list of Block (name, days, start, end, why) | `current.yaml` |
| `day.constraints.intentions.work/fitness/family/health` | list[str] | `current.yaml` |
| `intent` (morning intent) | str or None | `tracking/morning-intent.jsonl` today |
| `sunday_plan` | str or None | `tracking/sunday-plan.md` |
| `whoop` (summary for today) | dict with `recovery_score`, `hrv_ms`, `sleep_hours`, `steps_total`, `sedentary_hours`, `workouts[]` | `tracking/whoop-daily-summary.jsonl` last line (may be yesterday's data at morning-push time) |
| `mfp_yesterday` | dict with `calories`, `protein_g`, `carbs_g`, `fat_g`, `binge_flag`, `meals_logged` | `tracking/mfp-daily-summary.jsonl` yesterday's entry |
| `grooming_due` | list of `{name, status, last_done, interval_days}` | `tracking/grooming-state.yaml` → `get_overdue_or_due()` |
| `kid_hours` (hours since last kid-time log) | float or None | `tracking/kid-log.jsonl` last entry |

Also available but not currently used:

- `day.whoop_last_workout` (date of last logged workout)
- `tracking/weight.jsonl` (last entry)
- Multi-day MFP history (we only read today + yesterday; could read last 7)
- Multi-day WHOOP history (same)

### 4c. Current `_build_top3()` function (full source)

```python
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

@dataclass
class Top3Item:
    rank: int
    title: str
    slot_hint: str = ""
    reason: str = ""

    def render(self) -> str:
        prefix = f"{self.rank}. "
        if self.slot_hint:
            return f"{prefix}{self.slot_hint} — {self.title}"
        return f"{prefix}{self.title}"


def _find_free_windows(day, min_minutes: int = 30) -> list[tuple[time, time]]:
    """Return today's free windows that don't collide with hard_blocks or meetings."""
    start_of_day = day.now.replace(hour=6, minute=30, second=0, microsecond=0)
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


def _build_top3(day, today: date) -> tuple[list[Top3Item], str, str]:
    """Return (items, state_line, context_line)."""
    intent = _read_morning_intent(today)
    sunday_plan = _read_sunday_plan()
    whoop = _read_whoop_summary(today)
    mfp_today = _read_mfp_summary(today)
    mfp_yesterday = _read_last_today_jsonl(
        _V03_TRACKING_DIR / "mfp-daily-summary.jsonl",
        today - timedelta(days=1),
    )
    grooming_due = _read_grooming_due()
    kid_hours = _read_kid_hours_since(today)

    recovery = day.whoop_recovery
    if recovery is None:
        recovery = (whoop or {}).get("recovery_score")
    workouts_today = (whoop or {}).get("workouts") or []

    # State line
    parts = []
    if recovery is not None:
        parts.append(f"Recovery {int(recovery)}")
    if mfp_yesterday:
        cals = mfp_yesterday.get("calories")
        if cals:
            parts.append(f"yesterday {cals} cal")
    state_line = (
        f"{WEEKDAY_NAMES[today.weekday()]} {today.strftime('%-m/%-d')}, "
        f"{day.now.strftime('%H:%M')}. "
        + (", ".join(parts) if parts else "no biometrics logged")
    )

    # Context line
    free_windows = _find_free_windows(day, min_minutes=45)
    if free_windows:
        window_strs = [_format_slot(s, e) for s, e in free_windows[:2]]
        context_line = f"Free: {', '.join(window_strs)}."
    else:
        context_line = "Schedule dense — no windows ≥45m."

    # Low-recovery reframe
    if recovery is not None and recovery < 34:
        return (
            [
                Top3Item(1, "Rest day. Skip workout.", reason="recovery red"),
                Top3Item(2, "Protein floor and sleep runway tonight", reason="recovery red"),
                Top3Item(
                    3,
                    grooming_due[0]["name"] if grooming_due else "No third push — recover.",
                    reason="recovery red",
                ),
            ],
            state_line,
            f"Recovery {int(recovery)} (red). Don't stack intensity.",
        )

    # Rank candidate items
    items = []

    # 1. Biggest free window → deep work
    if free_windows:
        top_win = max(free_windows, key=lambda w: _duration_minutes(w[0], w[1]))
        slot = _format_slot(top_win[0], top_win[1])
        items.append(Top3Item(0, "deep block", slot_hint=slot, reason="largest free window"))

    # 2. Movement item
    if workouts_today:
        pass  # worked out today — skip movement slot
    elif intent and any(kw in intent.lower() for kw in ("gym", "workout", "lift")):
        items.append(Top3Item(0, f"Follow through on morning intent: {intent.strip()}", reason="intent"))
    elif intent and any(kw in intent.lower() for kw in ("walk", "run", "bike")):
        items.append(Top3Item(0, f"Walk — {intent.strip()}", reason="intent"))
    else:
        items.append(Top3Item(0, "20-min walk — movement floor", reason="no movement logged"))

    # 3. Tracking gap
    if mfp_yesterday is None:
        items.append(Top3Item(0, "Log last night's dinner to MFP — missed yesterday", reason="tracking gap"))
    elif kid_hours is not None and kid_hours >= 48:
        items.append(Top3Item(0, f"Kid time — last logged {kid_hours:.0f}h ago", reason="kid gap"))
    elif grooming_due:
        top_groom = grooming_due[0]
        items.append(Top3Item(0, f"{top_groom['name'].replace('_', ' ')} — {top_groom.get('status', 'due')}", reason="grooming"))
    else:
        items.append(Top3Item(0, "Evening debrief to Claude iOS", reason="default reflection"))

    for i, item in enumerate(items[:3], start=1):
        item.rank = i

    return items[:3], state_line, context_line
```

### 4d. How the rendered output is assembled

```python
def render_top3(day, today):
    items, state_line, context_line = _build_top3(day, today)
    sunday_plan = _read_sunday_plan()

    lines = [state_line, context_line, ""]
    for item in items:
        lines.append(item.render())
    if sunday_plan:
        body_lines = [l for l in sunday_plan.splitlines() if not l.startswith("# ")]
        plan_body = "\n".join(body_lines).strip()
        if plan_body:
            lines.append("")
            lines.append(f"Week plan: {plan_body.splitlines()[0][:80]}")
    return "\n".join(lines).rstrip() + "\n"
```

---

## 5. Voice reference (authoritative for any message this system sends)

This was written for the v0.2 JITAI system but the voice rules still apply to v0.3 Top 3.

### Core stance

The planner is not a coach. Not a friend. Not a "helpful assistant." It is an **instrument of pre-commitment** — built to enforce decisions Zak's past self made that his present self cannot be trusted to honor. It fires when the data shows a gap.

Mental model: Zak is a competent adult who has decided what he wants. He's not confused about what's good for him. He has ADHD, autism, long history of over-indexing on work/side projects past healthy return. His problem is performance under conditions where attention pulls him toward novelty. He has explicitly asked to be interrupted.

### Voice DNA (blend of three)

1. **Peter Attia** — data-forward, mechanism-first, short declarative sentences, specifics over categories, no performative warmth. "Your ApoB is 110" beats "your cholesterol is a bit high."
2. **Russell Barkley** — externalize the agreement ("you said you'd go"), never moralize, performance failure is a design problem not a character problem.
3. **Staff engineer code review** — no opening niceties, get to the observation fast, state next action concretely, reference the artifact.

### Non-negotiable rules

- Never moralize ("you really should…", "this isn't healthy…", "your family deserves…")
- Never apologize for firing ("sorry to interrupt…")
- Never use hype words ("crush it", "beast mode", "let's go!", 💪)
- Never perform concern ("just making sure you're taking care of yourself")
- Never hedge the core observation ("it looks like you might be…")
- Never explain what the planner is ("as your executive planner, I…")
- Never assume Zak reads past line 3 — most messages 2–5 lines

### Sentence-level style

- **Lead with the observation, not the instruction.** "Wed 10:00. Your protected window. Start on X." NOT "Start on X."
- **Name specifics, never categories.** "M is downstairs" > "spend time with your kids." "Fri 13:00–17:00, 4 hours clear" > "you have some open time."
- **"You said" ties observations back to Zak's own declared commitments.** Most powerful move.
- **Never end on a question.** Messages end on the action. The period is the commitment.

### Failure mode to avoid

The worst version of this planner sounds like ChatGPT trying to be your friend: uses your name too often, softens with "just wanted to…", hype emoji, asks how you're feeling, celebrates small wins loudly, apologizes for interrupting, explains itself, writes paragraphs when sentences would do.

---

## 6. What I want from the tuning session

Specifically:

1. **Revised `_build_top3()`** that:
   - Reads a `morning_routine` config (new — define the schema you want) and NEVER proposes work blocks before desk_time
   - Pulls yesterday's sedentary_hours and/or (if available) steps_total from the WHOOP summary; surfaces it in item #2 when movement is the subject
   - Detects tracking-consistency gaps across a 7-day window (how many days of MFP logged / kid-time logged / morning-intent logged / weight logged) and, when at least one is thin, makes item #3 the pointed call-out

2. **A helper** like `_movement_observation_yesterday(whoop_yesterday_summary, mfp_yesterday)` that builds a 1-line data-driven observation instead of "20-min walk — movement floor."

3. **A helper** like `_tracking_consistency_snapshot(today, lookback_days=7)` that reads the last N days of each tracking jsonl and returns a dict of `{source: days_logged}` + proposes the sharpest call-out.

4. **Morning routine schema + block_reader integration.** Where to put it (new file under `tracking/`? extend `current.yaml`?), how block_reader should surface it to the Top 3 generator.

5. **Revised rendered output** for today's data that demonstrates the new voice. Example I'd want:

```
Thu 4/23, 10:10. Recovery 40. Yesterday: 11.7h sedentary.

Desk at 09:15 today. Free: 09:15–12:30, 13:30–17:00.

1. 09:15–12:30 — deep block (3h15m clear before staff sync)
2. 07:00–07:30 walk BEFORE shower. Yesterday was your 2nd sedentary day in a row.
3. You've logged MFP 3 of the last 7 days. This is the core of the system working. Log last night now.

Week plan: 3 gym, protect Wed AM, no coding after 17:00 M/W/F.
```

Just propose the code. I'll apply + test locally. Don't worry about backwards compat — v0.3 is young.
