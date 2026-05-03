# WuWa Timeline Scraper

This folder contains a minimal scraper for `https://wuwatracker.com/timeline`.

## What it does

The timeline page is a Next.js app-router page. The event data is embedded
directly in the HTML inside `self.__next_f.push(...)` payloads. This scraper:

1. Fetches the timeline page HTML.
2. Extracts the embedded payload containing `banners` and `activities`.
3. Normalizes the records into a stable schema.
4. Writes machine-readable and human-readable outputs to `output/`.

## Files

- `scrape_wuwa_timeline.py`: main scraper
- `HERMES_CRON.md`: paste-ready Hermes cron prompt for the WuWa reminder job
- `output/latest.json`: canonical combined output for downstream use
- `output/latest_all.json`: most recent unfiltered run with both record types
- `output/latest_active_only.json`: most recent active-only run with both record types
- `output/latest_banners.json`: most recent banners-only run
- `output/latest_activities.json`: most recent activities-only run
- `output/banners.csv`: flattened banner rows
- `output/activities.csv`: flattened activity rows
- `output/provenance.json`: extraction metadata and caveats
- `output/summary.md`: quick human-readable summary

## Usage

```bash
cd /home/sagnik/Projects/games/wuwa-timeline-scraper
python3 scrape_wuwa_timeline.py
```

Exclude expired items for a cleaner tracking view:

```bash
python3 scrape_wuwa_timeline.py --active-only
```

Pick a server timezone, emit timestamps in a different timezone, and keep only banners:

```bash
python3 scrape_wuwa_timeline.py --server asia --timezone Asia/Kolkata --include banners
```

The same options can be supplied through environment variables:

```bash
export WUWA_TIMELINE_SERVER=america
export WUWA_TIMELINE_TIMEZONE=America/Los_Angeles
export WUWA_TIMELINE_INCLUDE=activities
export WUWA_TIMELINE_ACTIVE_ONLY=true
python3 scrape_wuwa_timeline.py
```

## Output contract

Future agents should prefer:

- `output/latest_active_only.json` for clean "what still matters" tracking
- `output/latest_all.json` for the complete source snapshot

`output/latest.json` is still written and always points to the most recent run,
regardless of mode.

Mode-specific snapshots follow this naming rule:

- `latest_all.json`: full unfiltered run
- `latest_active_only.json`: full active-only run
- `latest_banners.json`: banners-only run
- `latest_activities.json`: activities-only run
- `latest_active_only_banners.json`: active-only banners-only run
- `latest_active_only_activities.json`: active-only activities-only run

Top-level shape:

```json
{
  "scraped_at_utc": "ISO-8601 timestamp",
  "source_url": "https://wuwatracker.com/timeline",
  "filters": {
    "active_only": false,
    "server": "asia",
    "server_label": "Asia, SEA, TW/HK/MO",
    "server_timezone": "Asia/Shanghai",
    "timezone": "UTC",
    "include": "all"
  },
  "counts": {
    "banners": 0,
    "activities": 0,
    "total": 0
  },
  "unfiltered_counts": {
    "banners": 0,
    "activities": 0,
    "total": 0
  },
  "banners": [],
  "activities": []
}
```

Normalized record shape:

```json
{
  "record_type": "banner | activity",
  "record_index": 1,
  "name": "string",
  "description": "string | null",
  "cover_img_src": "string",
  "color": "#hex",
  "source_url": "string",
  "group": "number | null",
  "start_date": "string",
  "end_date": "string",
  "start_at_server": "ISO-8601 timestamp | null",
  "end_at_server": "ISO-8601 timestamp | null",
  "start_at_output_tz": "ISO-8601 timestamp | null",
  "end_at_output_tz": "ISO-8601 timestamp | null",
  "end_at_utc": "ISO-8601 timestamp | null",
  "has_expired": false,
  "expires_in": "Xd Yh Zm | null",
  "is_cst_start": true,
  "is_banner_event": true,
  "banner_group": 1
}
```

## Notes

- `cover_img_src` is an image path, not the metadata source.
- The internal Next.js chunk id may change over time, so extraction is matched by
  payload content rather than a fixed numeric prefix.
- `--server` controls how the tracker timestamps are interpreted before conversion.
- `--timezone` controls the output/display timezone written into normalized records.
- `--include` accepts `all`, `banners`, or `activities`.
- `--active-only` keeps only records whose converted `end_at_utc` is still in the future.
- If plain HTTP fetches stop working due to bot protection, the next fallback is a
  browser-backed fetch, but that is not currently required.
