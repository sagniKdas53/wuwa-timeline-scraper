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

Use the same Hermes thread as the HoYo jobs so the reminders stay in one place.

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
- Job status file: <STATE_DIR>/job_status.json
- Job name: WuWa Event Reminder

Task:
1. Ensure the state directory exists.
2. Run the scraper for active activities only:
   python3 <WUWA_REPO>/scrape_wuwa_timeline.py --active-only --include activities --server asia --timezone Asia/Kolkata
3. Read <WUWA_REPO>/output/latest.json.
4. From `activities`, identify records ending within the next 3 days from now using `end_at_utc`.
5. Load the job status file if it exists, otherwise start with an empty object.
6. Also count all currently active WuWa activities from this payload. Store at least:
   - active_wuwa_events
   in the job status entry.
7. Build a stable key for each record:
   wuwa:{record_type}:{record_index}:{end_at_utc}:{name}
8. Maintain status per key in `<STATE_DIR>/wuwa_event_status.json` with:
   - status = active | done | ignored
   - last_reminded_date
   - name
   - end_at_utc
9. For each qualifying record:
   - Skip if status is done or ignored.
   - Skip if last_reminded_date is today.
   - Otherwise post a reminder and update last_reminded_date to today.
10. Update the job status entry for `WuWa Event Reminder` with at least:
   - runs_this_week
   - successes_this_week
   - failures_this_week
   - triggers_this_week
   - last_run_utc
   - last_success_utc
   - last_failure_utc
   - last_failure_reason
   - last_qualifying_count
   - active_wuwa_events
11. Write the updated status and job status files back.
12. Reminder format:
   - Event name
   - Ends at Asia/Kolkata time
   - Time remaining
   - Source URL if present
   - Stable key
   - Final line:
     Use `/mark-event done "Exact Event Name"` to stop reminders after completion, or `/mark-event ignore "Exact Event Name"` to suppress reminders for this event.
13. If nothing qualifies today, post nothing.
14. On failure:
   - Update the job status entry with a failed run.
   - Post one short error message and keep prior state intact.

Rules:
- This is a one-shot cron run, not an ongoing project update.
- Never output task summaries, continuity notes, tool logs, plans, or management text.
- One reminder per event per day at most.
- Preserve done and ignored state across runs.
```

## Notes

- Use a manual Hermes slash command such as `/mark-event` instead of a polling
  command-processor cron.
- Prefer internal Hermes clones plus one shared persistent state directory instead
  of widening host folder access.
