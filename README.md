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
- `output/latest.json`: canonical combined output for downstream use
- `output/latest_all.json`: most recent unfiltered run
- `output/latest_active_only.json`: most recent filtered run
- `output/banners.csv`: flattened banner rows
- `output/activities.csv`: flattened activity rows
- `output/provenance.json`: extraction metadata and caveats
- `output/summary.md`: quick human-readable summary

## Usage

```bash
cd /home/sagnik/Desktop/wuwa_timeline_scraper
python3 scrape_wuwa_timeline.py
```

Exclude expired items for a cleaner tracking view:

```bash
python3 scrape_wuwa_timeline.py --active-only
```

## Output contract

Future agents should prefer:

- `output/latest_active_only.json` for clean "what still matters" tracking
- `output/latest_all.json` for the complete source snapshot

`output/latest.json` is still written and always points to the most recent run,
regardless of mode.

Top-level shape:

```json
{
  "scraped_at_utc": "ISO-8601 timestamp",
  "source_url": "https://wuwatracker.com/timeline",
  "filters": {
    "active_only": false
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
- `--active-only` keeps only records whose `end_date` is still in the future.
- End dates are preserved in every output so you can sort by upcoming deadlines
  and avoid missing expiring events.
- If plain HTTP fetches stop working due to bot protection, the next fallback is a
  browser-backed fetch, but that is not currently required.
