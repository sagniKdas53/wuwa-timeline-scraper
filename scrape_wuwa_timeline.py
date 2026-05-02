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
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TIMELINE_URL = "https://wuwatracker.com/timeline"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)

DEFAULT_SERVER = "asia"
DEFAULT_OUTPUT_TIMEZONE = "UTC"
DEFAULT_INCLUDE = "all"
ENV_PREFIX = "WUWA_TIMELINE_"
SERVER_TIMEZONES = {
    "asia": "Asia/Shanghai",
    "sea": "Asia/Shanghai",
    "tw_hk_mo": "Asia/Shanghai",
    "europe": "Europe/Berlin",
    "america": "America/New_York",
}
SERVER_LABELS = {
    "asia": "Asia, SEA, TW/HK/MO",
    "sea": "Asia, SEA, TW/HK/MO",
    "tw_hk_mo": "Asia, SEA, TW/HK/MO",
    "europe": "Europe",
    "america": "America",
}


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


def env_value(name: str, default: str | None = None) -> str | None:
    return os.getenv(f"{ENV_PREFIX}{name}", default)


def parse_bool_env(name: str, default: bool = False) -> bool:
    raw = env_value(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {ENV_PREFIX}{name}: {raw}")


def canonicalize_server(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace("/", "_")
    aliases = {
        "as": "asia",
        "asia_sea_tw_hk_mo": "asia",
        "asia_sea_twhkmo": "asia",
        "tw": "tw_hk_mo",
        "hk": "tw_hk_mo",
        "mo": "tw_hk_mo",
        "twhkmo": "tw_hk_mo",
        "tw_hk": "tw_hk_mo",
        "tw_hk_mo_utc8": "tw_hk_mo",
        "na": "america",
        "us": "america",
        "eu": "europe",
    }
    canonical = aliases.get(normalized, normalized)
    if canonical not in SERVER_TIMEZONES:
        valid = ", ".join(sorted(SERVER_TIMEZONES))
        raise ValueError(f"Unsupported server '{value}'. Expected one of: {valid}")
    return canonical


def parse_include(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "banner": "banners",
        "activity": "activities",
        "both": "all",
    }
    resolved = aliases.get(normalized, normalized)
    if resolved not in {"all", "banners", "activities"}:
        raise ValueError("Expected include mode to be one of: all, banners, activities")
    return resolved


def load_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone '{value}'") from exc


def parse_args() -> argparse.Namespace:
    env_server = env_value("SERVER", DEFAULT_SERVER) or DEFAULT_SERVER
    env_timezone = env_value("TIMEZONE", DEFAULT_OUTPUT_TIMEZONE) or DEFAULT_OUTPUT_TIMEZONE
    env_include = env_value("INCLUDE", DEFAULT_INCLUDE) or DEFAULT_INCLUDE
    parser = argparse.ArgumentParser(
        description="Scrape WuWa Tracker timeline data from the embedded Next.js payload."
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        default=parse_bool_env("ACTIVE_ONLY", default=False),
        help="Exclude banners and activities whose end date has already passed.",
    )
    parser.add_argument(
        "--server",
        default=env_server,
        help=(
            "Server whose timezone should be used to interpret tracker timestamps. "
            f"Supported: {', '.join(sorted(SERVER_TIMEZONES))}. "
            f"Default: {env_server}."
        ),
    )
    parser.add_argument(
        "--timezone",
        default=env_timezone,
        help=(
            "IANA timezone used for output/display fields, such as UTC or Asia/Kolkata. "
            f"Default: {env_timezone}."
        ),
    )
    parser.add_argument(
        "--include",
        default=env_include,
        help=(
            "Which record types to include in outputs: all, banners, or activities. "
            f"Default: {env_include}."
        ),
    )
    return parser.parse_args()


def parse_event_datetime(value: str | None, source_tz: ZoneInfo) -> datetime | None:
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=source_tz)
        except ValueError:
            continue
    return None


def format_duration(delta_seconds: float) -> str:
    remaining = max(int(delta_seconds), 0)
    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


def normalize_records(
    records: list[dict[str, Any]],
    record_type: str,
    source_tz: ZoneInfo,
    output_tz: ZoneInfo,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)
    for index, record in enumerate(records, start=1):
        banner_meta = record.get("banner") or {}
        end_date = record.get("endDate")
        start_date = record.get("startDate")
        start_at_source = parse_event_datetime(start_date, source_tz)
        end_at_source = parse_event_datetime(end_date, source_tz)
        start_at_utc = start_at_source.astimezone(timezone.utc) if start_at_source is not None else None
        end_at_utc = end_at_source.astimezone(timezone.utc) if end_at_source is not None else None
        start_at_output = start_at_source.astimezone(output_tz) if start_at_source is not None else None
        end_at_output = end_at_source.astimezone(output_tz) if end_at_source is not None else None
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
                "start_date": start_date,
                "end_date": end_date,
                "start_at_server": start_at_source.isoformat() if start_at_source is not None else None,
                "end_at_server": end_at_source.isoformat() if end_at_source is not None else None,
                "start_at_output_tz": start_at_output.isoformat() if start_at_output is not None else None,
                "end_at_output_tz": end_at_output.isoformat() if end_at_output is not None else None,
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
        "start_at_server",
        "end_at_server",
        "start_at_output_tz",
        "end_at_output_tz",
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


def write_summary(
    path: Path,
    payload: dict[str, Any],
    all_banners: list[dict[str, Any]],
    all_activities: list[dict[str, Any]],
) -> None:
    include = payload["filters"]["include"]
    server_name = payload["filters"]["server"]
    output_timezone = payload["filters"]["timezone"]
    active_banners = [row for row in all_banners if row.get("has_expired") is not True]
    active_activities = [row for row in all_activities if row.get("has_expired") is not True]
    lines = [
        "# WuWa Timeline Scrape Summary",
        "",
        f"- Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        f"- Server: {SERVER_LABELS.get(server_name, server_name)} ({SERVER_TIMEZONES[server_name]})",
        f"- Output timezone: {output_timezone}",
        f"- Include mode: {include}",
        f"- Banner count: {len(all_banners)}",
        f"- Activity count: {len(all_activities)}",
        f"- Total records: {len(all_banners) + len(all_activities)}",
        f"- Active banners: {len(active_banners)}",
        f"- Active activities: {len(active_activities)}",
        "",
        "## Current extraction notes",
        "",
        "- Source page embeds timeline data directly into a Next.js flight payload.",
        "- No separate public JSON metadata endpoint was required for this scrape.",
        "- `cover_img_src` points to image routes and is not the source of the event metadata.",
        "- Event timestamps are interpreted in the selected server timezone and also emitted in UTC plus the requested output timezone.",
        "",
        "## Next items to expire",
        "",
    ]

    preview_source: list[dict[str, Any]] = []
    if include in {"all", "banners"}:
        preview_source.extend(active_banners)
    if include in {"all", "activities"}:
        preview_source.extend(active_activities)

    preview = sort_records(preview_source)[:10]
    for row in preview:
        lines.append(
            f"- [{row['record_type']}] {row['name']} | ends {row['end_at_output_tz']} | time left {row['expires_in']} | {row['source_url']}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_mode_suffix(active_only: bool, include: str) -> str:
    parts: list[str] = []
    if active_only:
        parts.append("active_only")
    if include != "all":
        parts.append(include)
    return "_".join(parts) if parts else "all"


def write_run_outputs(output_dir: Path, payload: dict[str, Any], banners: list[dict[str, Any]], activities: list[dict[str, Any]]) -> None:
    suffix = build_mode_suffix(
        active_only=payload["filters"]["active_only"],
        include=payload["filters"]["include"],
    )

    write_json(output_dir / "latest.json", payload)
    write_json(output_dir / f"latest_{suffix}.json", payload)
    if payload["filters"]["include"] in {"all", "banners"}:
        write_csv(output_dir / "banners.csv", banners)
        write_csv(output_dir / f"banners_{suffix}.csv", banners)
    if payload["filters"]["include"] in {"all", "activities"}:
        write_csv(output_dir / "activities.csv", activities)
        write_csv(output_dir / f"activities_{suffix}.csv", activities)


def main() -> int:
    try:
        args = parse_args()
        server = canonicalize_server(args.server)
        include = parse_include(args.include)
        source_tz = load_timezone(SERVER_TIMEZONES[server])
        output_tz = load_timezone(args.timezone)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

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

    all_banners = sort_records(normalize_records(raw_data.get("banners", []), "banner", source_tz, output_tz))
    all_activities = sort_records(normalize_records(raw_data.get("activities", []), "activity", source_tz, output_tz))
    banners = filter_records(all_banners, args.active_only)
    activities = filter_records(all_activities, args.active_only)
    selected_banners = banners if include in {"all", "banners"} else []
    selected_activities = activities if include in {"all", "activities"} else []

    payload = {
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": TIMELINE_URL,
        "filters": {
            "active_only": args.active_only,
            "server": server,
            "server_label": SERVER_LABELS.get(server, server),
            "server_timezone": SERVER_TIMEZONES[server],
            "timezone": args.timezone,
            "include": include,
        },
        "counts": {
            "banners": len(selected_banners),
            "activities": len(selected_activities),
            "total": len(selected_banners) + len(selected_activities),
        },
        "unfiltered_counts": {
            "banners": len(all_banners),
            "activities": len(all_activities),
            "total": len(all_banners) + len(all_activities),
        },
        "banners": selected_banners,
        "activities": selected_activities,
    }
    provenance = Provenance(
        fetched_at_utc=payload["scraped_at_utc"],
        source_url=TIMELINE_URL,
        extraction_method="Parse embedded self.__next_f.push() Next.js flight payload from HTML",
        notes=[
            "Data is embedded in server-rendered HTML, not obtained from a separate public metadata API during this scrape.",
            "The chunk id prefix before the JSON object may change; scraper matches on the presence of banners and activities.",
            f"Source event timestamps were interpreted using the {SERVER_TIMEZONES[server]} timezone for server '{server}'.",
            f"Output timestamps were emitted in both UTC and the requested timezone '{args.timezone}'.",
            "If Cloudflare introduces stronger bot protection, a browser-backed fetch may be needed later.",
        ],
    )

    write_run_outputs(output_dir, payload, selected_banners, selected_activities)
    write_json(output_dir / "provenance.json", asdict(provenance))
    write_summary(output_dir / "summary.md", payload, all_banners, all_activities)

    print(f"Wrote scrape artifacts to {output_dir}")
    print(f"Active-only mode: {args.active_only}")
    print(f"Server: {server} ({SERVER_TIMEZONES[server]})")
    print(f"Output timezone: {args.timezone}")
    print(f"Include mode: {include}")
    print(f"Banners: {len(selected_banners)}")
    print(f"Activities: {len(selected_activities)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
