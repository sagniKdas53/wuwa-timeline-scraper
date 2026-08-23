"""Offline tests for scrape_wuwa_timeline.py.

None of these tests hit the network. Extraction/normalization logic is
exercised against a synthetic HTML payload built to match the real
wuwatracker.com/timeline response shape; see conftest.py.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

import pytest

from conftest import build_timeline_html


# --- extraction -------------------------------------------------------


def test_extract_timeline_data_finds_payload(scraper_module: ModuleType, sample_html: str):
    data = scraper_module.extract_timeline_data(sample_html)
    assert [b["name"] for b in data["banners"]] == ["Active Banner", "Expired Banner"]
    assert [a["name"] for a in data["activities"]] == ["Active Activity"]


def test_extract_timeline_data_no_payloads_raises(scraper_module: ModuleType):
    with pytest.raises(RuntimeError, match="No Next.js flight payloads"):
        scraper_module.extract_timeline_data("<html><body>nothing here</body></html>")


def test_extract_timeline_data_missing_keys_raises(scraper_module: ModuleType):
    html = build_timeline_html({"other": "stuff"})
    with pytest.raises(RuntimeError, match="was not found"):
        scraper_module.extract_timeline_data(html)


def test_extract_timeline_data_ignores_unrelated_chunks(
    scraper_module: ModuleType, sample_payload: dict
):
    unrelated = '<script>self.__next_f.push([1,"2:{\\"unrelated\\":true}"])</script>'
    real = build_timeline_html(sample_payload)
    data = scraper_module.extract_timeline_data(unrelated + real)
    assert len(data["banners"]) == 2


# --- CLI parsing / normalization helpers -------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("asia", "asia"),
        ("ASIA", "asia"),
        ("na", "america"),
        ("us", "america"),
        ("eu", "europe"),
        ("tw", "tw_hk_mo"),
        ("hk", "tw_hk_mo"),
    ],
)
def test_canonicalize_server_aliases(scraper_module: ModuleType, value, expected):
    assert scraper_module.canonicalize_server(value) == expected


def test_canonicalize_server_rejects_unknown(scraper_module: ModuleType):
    with pytest.raises(ValueError, match="Unsupported server"):
        scraper_module.canonicalize_server("mars")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("all", "all"),
        ("both", "all"),
        ("banner", "banners"),
        ("banners", "banners"),
        ("activity", "activities"),
        ("activities", "activities"),
    ],
)
def test_parse_include_aliases(scraper_module: ModuleType, value, expected):
    assert scraper_module.parse_include(value) == expected


def test_parse_include_rejects_unknown(scraper_module: ModuleType):
    with pytest.raises(ValueError, match="Expected include mode"):
        scraper_module.parse_include("everything")


def test_parse_event_datetime_accepts_known_formats(scraper_module: ModuleType):
    tz = ZoneInfo("Asia/Shanghai")
    with_seconds = scraper_module.parse_event_datetime("2026-08-01 04:00:00", tz)
    without_seconds = scraper_module.parse_event_datetime("2026-08-01 04:00", tz)
    assert with_seconds is not None and with_seconds.tzinfo is tz
    assert without_seconds is not None and without_seconds.tzinfo is tz


def test_parse_event_datetime_handles_missing_and_invalid(scraper_module: ModuleType):
    tz = ZoneInfo("UTC")
    assert scraper_module.parse_event_datetime(None, tz) is None
    assert scraper_module.parse_event_datetime("not a date", tz) is None


def test_format_duration(scraper_module: ModuleType):
    assert scraper_module.format_duration(0) == "0d 0h 0m"
    assert scraper_module.format_duration(-5) == "0d 0h 0m"
    assert scraper_module.format_duration(90061) == "1d 1h 1m"


# --- normalize/filter/sort ---------------------------------------------


def test_normalize_records_marks_expiry_and_converts_timezone(
    scraper_module: ModuleType, sample_payload: dict
):
    source_tz = ZoneInfo("Asia/Shanghai")
    output_tz = ZoneInfo("Asia/Kolkata")
    rows = scraper_module.normalize_records(
        sample_payload["banners"], "banner", source_tz, output_tz
    )
    active, expired = rows
    assert active["has_expired"] is False
    assert expired["has_expired"] is True
    # Asia/Shanghai (+08:00) -> Asia/Kolkata (+05:30) is a -2:30 shift.
    assert active["start_at_server"] == "2026-08-01T04:00:00+08:00"
    assert active["start_at_output_tz"] == "2026-08-01T01:30:00+05:30"


def test_normalize_records_blanks_undefined_description(
    scraper_module: ModuleType, sample_payload: dict
):
    rows = scraper_module.normalize_records(
        sample_payload["activities"], "activity", ZoneInfo("UTC"), ZoneInfo("UTC")
    )
    assert rows[0]["description"] is None


def test_normalize_records_handles_missing_end_date(scraper_module: ModuleType):
    record = {"name": "No End Date", "startDate": "2026-08-01 04:00:00", "endDate": None}
    rows = scraper_module.normalize_records([record], "activity", ZoneInfo("UTC"), ZoneInfo("UTC"))
    assert rows[0]["has_expired"] is None
    assert rows[0]["end_at_utc"] is None
    assert rows[0]["expires_in"] is None


def test_filter_records_drops_expired_when_active_only(scraper_module: ModuleType):
    rows = [{"has_expired": True}, {"has_expired": False}, {"has_expired": None}]
    assert scraper_module.filter_records(rows, active_only=False) == rows
    filtered = scraper_module.filter_records(rows, active_only=True)
    assert filtered == [{"has_expired": False}, {"has_expired": None}]


def test_sort_records_orders_active_before_expired_then_by_end_then_name(
    scraper_module: ModuleType,
):
    rows = [
        {"name": "Z", "has_expired": False, "end_at_utc": "2026-09-01T00:00:00+00:00"},
        {"name": "A", "has_expired": True, "end_at_utc": "2026-01-01T00:00:00+00:00"},
        {"name": "B", "has_expired": False, "end_at_utc": "2026-08-01T00:00:00+00:00"},
    ]
    ordered = [row["name"] for row in scraper_module.sort_records(rows)]
    assert ordered == ["B", "Z", "A"]


@pytest.mark.parametrize(
    "active_only,include,expected",
    [
        (False, "all", "all"),
        (True, "all", "active_only"),
        (False, "banners", "banners"),
        (True, "activities", "active_only_activities"),
    ],
)
def test_build_mode_suffix(scraper_module: ModuleType, active_only, include, expected):
    assert scraper_module.build_mode_suffix(active_only, include) == expected


# --- full pipeline -------------------------------------------------------


def test_main_writes_expected_artifacts(
    isolated_scraper_module: ModuleType,
    sample_html: str,
    monkeypatch: pytest.MonkeyPatch,
):
    module = isolated_scraper_module
    monkeypatch.setattr(module, "fetch_html", lambda url: sample_html)
    monkeypatch.setattr(
        "sys.argv",
        [
            "scrape_wuwa_timeline.py",
            "--active-only",
            "--server",
            "asia",
            "--timezone",
            "Asia/Kolkata",
        ],
    )

    exit_code = module.main()
    assert exit_code == 0

    output_dir = Path(module.__file__).resolve().parent / "output"
    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))

    # The expired banner must be dropped by --active-only.
    assert latest["counts"] == {"banners": 1, "activities": 1, "total": 2}
    assert latest["unfiltered_counts"] == {"banners": 2, "activities": 1, "total": 3}
    assert latest["filters"]["active_only"] is True
    assert latest["filters"]["server"] == "asia"
    assert [b["name"] for b in latest["banners"]] == ["Active Banner"]

    # Mode-suffixed files use the active_only suffix (include stayed "all").
    assert (output_dir / "latest_active_only.json").exists()
    assert (output_dir / "banners_active_only.csv").exists()
    assert (output_dir / "activities_active_only.csv").exists()

    provenance = json.loads((output_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["source_url"] == module.TIMELINE_URL

    with (output_dir / "banners.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["name"] for row in rows] == ["Active Banner"]

    summary = (output_dir / "summary.md").read_text(encoding="utf-8")
    assert "Active Banner" in summary
    assert "Expired Banner" not in summary  # only active items appear in the preview


def test_main_returns_error_code_on_missing_payload(
    isolated_scraper_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
):
    module = isolated_scraper_module
    monkeypatch.setattr(module, "fetch_html", lambda url: "<html>no payload</html>")
    monkeypatch.setattr("sys.argv", ["scrape_wuwa_timeline.py"])

    assert module.main() == 1


def test_main_returns_config_error_code_on_bad_server(
    isolated_scraper_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
):
    module = isolated_scraper_module
    monkeypatch.setattr("sys.argv", ["scrape_wuwa_timeline.py", "--server", "mars"])

    assert module.main() == 2
