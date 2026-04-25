#!/usr/bin/env python3
"""Scrape WuWa Tracker timeline data from the server-rendered Next.js payload.

This scraper fetches the HTML for https://wuwatracker.com/timeline, extracts the
embedded flight payload that contains the timeline data, and writes a set of
artifacts that are easy for future agents to consume:

- output/latest.json
- output/banners.csv
- output/activities.csv
- output/summary.md
- output/provenance.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TIMELINE_URL = "https://wuwatracker.com/timeline"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


@dataclass
class Provenance:
    fetched_at_utc: str
    source_url: str
    extraction_method: str
    notes: list[str]


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_push_payloads(html: str) -> list[str]:
    return re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, flags=re.S)


def decode_flight_string(value: str) -> str:
    # The payload is JS-string escaped inside HTML.
    decoded = bytes(unescape(value), "utf-8").decode("unicode_escape")
    return decoded


def extract_timeline_data(html: str) -> dict[str, Any]:
    push_payloads = extract_push_payloads(html)
    if not push_payloads:
        raise RuntimeError("No Next.js flight payloads were found in the HTML")

    for payload in push_payloads:
        decoded = decode_flight_string(payload)
        match = re.search(r'\d+:(\{"banners":.*?"activities":.*?\})\n?$', decoded, flags=re.S)
        if not match:
            continue

        candidate = match.group(1)
        data = json.loads(candidate)
        if isinstance(data, dict) and "banners" in data and "activities" in data:
            return data

    raise RuntimeError("Timeline payload with banners and activities was not found")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape WuWa Tracker timeline data from the embedded Next.js payload."
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Exclude banners and activities whose end date has already passed.",
    )
    return parser.parse_args()


def parse_event_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def format_duration(delta_seconds: float) -> str:
    remaining = max(int(delta_seconds), 0)
    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


def normalize_records(records: list[dict[str, Any]], record_type: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)
    for index, record in enumerate(records, start=1):
        banner_meta = record.get("banner") or {}
        end_date = record.get("endDate")
        end_at_utc = parse_event_datetime(end_date)
        expires_in = None
        has_expired = None
        sort_end_at = None

        if end_at_utc is not None:
            expires_in = format_duration((end_at_utc - now_utc).total_seconds())
            has_expired = end_at_utc < now_utc
            sort_end_at = end_at_utc.isoformat()

        normalized.append(
            {
                "record_type": record_type,
                "record_index": index,
                "name": record.get("name"),
                "description": None if record.get("description") in ("", "$undefined") else record.get("description"),
                "cover_img_src": record.get("coverImgSrc"),
                "color": record.get("color"),
                "source_url": record.get("sourceUrl"),
                "group": record.get("group"),
                "start_date": record.get("startDate"),
                "end_date": record.get("endDate"),
                "end_at_utc": sort_end_at,
                "has_expired": has_expired,
                "expires_in": expires_in,
                "is_cst_start": record.get("isCstStart"),
                "is_banner_event": banner_meta.get("isBannerEvent"),
                "banner_group": banner_meta.get("group"),
            }
        )
    return normalized


def filter_records(rows: list[dict[str, Any]], active_only: bool) -> list[dict[str, Any]]:
    if not active_only:
        return rows
    return [row for row in rows if row.get("has_expired") is not True]


def sort_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
        end_at = row.get("end_at_utc") or "9999-12-31T23:59:59+00:00"
        return (1 if row.get("has_expired") else 0, end_at, row.get("name") or "")

    return sorted(rows, key=sort_key)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "record_type",
        "record_index",
        "name",
        "description",
        "cover_img_src",
        "color",
        "source_url",
        "group",
        "start_date",
        "end_date",
        "end_at_utc",
        "has_expired",
        "expires_in",
        "is_cst_start",
        "is_banner_event",
        "banner_group",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, banners: list[dict[str, Any]], activities: list[dict[str, Any]]) -> None:
    active_banners = [row for row in banners if row.get("has_expired") is not True]
    active_activities = [row for row in activities if row.get("has_expired") is not True]
    lines = [
        "# WuWa Timeline Scrape Summary",
        "",
        f"- Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        f"- Banner count: {len(banners)}",
        f"- Activity count: {len(activities)}",
        f"- Total records: {len(banners) + len(activities)}",
        f"- Active banners: {len(active_banners)}",
        f"- Active activities: {len(active_activities)}",
        "",
        "## Current extraction notes",
        "",
        "- Source page embeds timeline data directly into a Next.js flight payload.",
        "- No separate public JSON metadata endpoint was required for this scrape.",
        "- `cover_img_src` points to image routes and is not the source of the event metadata.",
        "- End dates are preserved in every output so upcoming expirations are visible.",
        "",
        "## Next items to expire",
        "",
    ]

    preview = sort_records(active_banners + active_activities)[:10]
    for row in preview:
        lines.append(
            f"- [{row['record_type']}] {row['name']} | ends {row['end_date']} UTC | time left {row['expires_in']} | {row['source_url']}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_outputs(output_dir: Path, payload: dict[str, Any], banners: list[dict[str, Any]], activities: list[dict[str, Any]]) -> None:
    suffix = "active_only" if payload["filters"]["active_only"] else "all"

    write_json(output_dir / "latest.json", payload)
    write_json(output_dir / f"latest_{suffix}.json", payload)
    write_csv(output_dir / "banners.csv", banners)
    write_csv(output_dir / "activities.csv", activities)
    write_csv(output_dir / f"banners_{suffix}.csv", banners)
    write_csv(output_dir / f"activities_{suffix}.csv", activities)


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        html = fetch_html(TIMELINE_URL)
        raw_data = extract_timeline_data(html)
    except (HTTPError, URLError) as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Extraction error: {exc}", file=sys.stderr)
        return 1

    all_banners = sort_records(normalize_records(raw_data.get("banners", []), "banner"))
    all_activities = sort_records(normalize_records(raw_data.get("activities", []), "activity"))
    banners = filter_records(all_banners, args.active_only)
    activities = filter_records(all_activities, args.active_only)

    payload = {
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": TIMELINE_URL,
        "filters": {
            "active_only": args.active_only,
        },
        "counts": {
            "banners": len(banners),
            "activities": len(activities),
            "total": len(banners) + len(activities),
        },
        "unfiltered_counts": {
            "banners": len(all_banners),
            "activities": len(all_activities),
            "total": len(all_banners) + len(all_activities),
        },
        "banners": banners,
        "activities": activities,
    }
    provenance = Provenance(
        fetched_at_utc=payload["scraped_at_utc"],
        source_url=TIMELINE_URL,
        extraction_method="Parse embedded self.__next_f.push() Next.js flight payload from HTML",
        notes=[
            "Data is embedded in server-rendered HTML, not obtained from a separate public metadata API during this scrape.",
            "The chunk id prefix before the JSON object may change; scraper matches on the presence of banners and activities.",
            "If Cloudflare introduces stronger bot protection, a browser-backed fetch may be needed later.",
        ],
    )

    write_run_outputs(output_dir, payload, banners, activities)
    write_json(output_dir / "provenance.json", asdict(provenance))
    write_summary(output_dir / "summary.md", all_banners, all_activities)

    print(f"Wrote scrape artifacts to {output_dir}")
    print(f"Active-only mode: {args.active_only}")
    print(f"Banners: {len(banners)}")
    print(f"Activities: {len(activities)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
