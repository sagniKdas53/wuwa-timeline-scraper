# Hermes Cron Prompts

This file contains the WuWa-specific Hermes cron prompt. The shared job
definitions live in the HoYo repo:

- `../hoyo-tracker-scraper/HERMES_CRON.md`

Before pasting the prompt into Hermes, replace these placeholders once:

- `<WUWA_REPO>`: path to the cloned `wuwa-timeline-scraper` repo
- `<STATE_DIR>`: path to the persistent writable state directory shared by all jobs

Recommended layout inside Hermes:

- `<WUWA_REPO>` = `/workspace/wuwa-timeline-scraper`
- `<STATE_DIR>` = `/workspace/hermes-state`

Use the same Hermes thread as the HoYo jobs so the shared command processor can
see the replies.

## Job: WuWa Event Reminder

- Name: `WuWa Event Reminder`
- Deliver To: same local Hermes thread as the HoYo jobs
- Schedule: `5 9 * * *`

```text
Use these absolute paths:

- WuWa repo: <WUWA_REPO>
- Scraper: <WUWA_REPO>/scrape_wuwa_timeline.py
- Output file to read after running: <WUWA_REPO>/output/latest.json
- State dir: <STATE_DIR>
- Status file: <STATE_DIR>/wuwa_event_status.json

Task:
1. Ensure the state directory exists.
2. Run the scraper for active activities only:
   python3 <WUWA_REPO>/scrape_wuwa_timeline.py --active-only --include activities --server asia --timezone Asia/Kolkata
3. Read <WUWA_REPO>/output/latest.json.
4. From `activities`, identify records ending within the next 3 days from now using `end_at_utc`.
5. Build a stable key for each record:
   wuwa:{record_type}:{record_index}:{end_at_utc}:{name}
6. Maintain status per key in `<STATE_DIR>/wuwa_event_status.json` with:
   - status = active | done | ignored
   - last_reminded_date
   - name
   - end_at_utc
7. For each qualifying record:
   - Skip if status is done or ignored.
   - Skip if last_reminded_date is today.
   - Otherwise post a reminder and update last_reminded_date to today.
8. Reminder format:
   - Event name
   - Ends at Asia/Kolkata time
   - Time remaining
   - Source URL if present
   - Stable key
   - Final line:
     Reply with `Done "Exact Event Name"` to stop reminders after completion, or `Ignore "Exact Event Name"` to suppress reminders for this event.
9. If nothing qualifies today, post nothing.
10. On failure, post one short error message and keep prior state intact.

Rules:
- One reminder per event per day at most.
- Preserve done and ignored state across runs.
```

## Notes

- Do not create a separate command processor for WuWa if you are already using the
  shared one from the HoYo repo.
- Prefer internal Hermes clones plus one shared persistent state directory instead
  of widening host folder access.
