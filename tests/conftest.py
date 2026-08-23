"""Shared fixtures for the offline scraper test suite.

These tests never touch the network. Instead they build a synthetic HTML
payload shaped like the real wuwatracker.com/timeline response (a
``self.__next_f.push([1, "..."])`` script tag wrapping a JSON-escaped
string that contains a ``{"banners": [...], "activities": [...]}`` object)
and feed it through the scraper's own extraction/normalization pipeline.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scrape_wuwa_timeline.py"


def build_timeline_html(payload: dict) -> str:
    """Wrap a banners/activities payload as a Next.js flight push script tag."""

    json_str = json.dumps(payload)
    escaped = json_str.replace("\\", "\\\\").replace('"', '\\"')
    return f'<script>self.__next_f.push([1,"3:{escaped}"])</script>'


@pytest.fixture
def sample_payload() -> dict:
    return {
        "banners": [
            {
                "name": "Active Banner",
                "description": "A featured convene",
                "coverImgSrc": "/images/banner-a.png",
                "color": "#ffcc00",
                "sourceUrl": "https://wuwatracker.com/banners/active-banner",
                "group": 1,
                "startDate": "2026-08-01 04:00:00",
                "endDate": "2026-09-15 03:59:59",
                "isCstStart": True,
                "banner": {"isBannerEvent": True, "group": 1},
            },
            {
                "name": "Expired Banner",
                "description": "",
                "coverImgSrc": "/images/banner-b.png",
                "color": "#111111",
                "sourceUrl": "https://wuwatracker.com/banners/expired-banner",
                "group": 2,
                "startDate": "2026-01-01 04:00:00",
                "endDate": "2026-01-15 03:59:59",
                "isCstStart": True,
                "banner": {"isBannerEvent": True, "group": 2},
            },
        ],
        "activities": [
            {
                "name": "Active Activity",
                "description": "$undefined",
                "coverImgSrc": "/images/activity-a.png",
                "color": "#00ccff",
                "sourceUrl": "https://wuwatracker.com/activities/active-activity",
                "group": None,
                "startDate": "2026-08-01 04:00:00",
                "endDate": "2026-09-10 03:59:59",
                "isCstStart": False,
                "banner": {},
            }
        ],
    }


@pytest.fixture
def sample_html(sample_payload: dict) -> str:
    return build_timeline_html(sample_payload)


@pytest.fixture
def scraper_module() -> ModuleType:
    """Import the real scraper module directly for unit-level function tests."""

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("scrape_wuwa_timeline", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Dataclasses looks itself up in sys.modules by __module__ name, so the
    # module must be registered there before exec_module runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def isolated_scraper_module(tmp_path: Path) -> ModuleType:
    """Load a copy of the scraper from a temp dir so `main()` writes to a
    throwaway `output/` directory instead of the real repo tree."""

    dest = tmp_path / "scrape_wuwa_timeline.py"
    dest.write_text(SCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "scrape_wuwa_timeline_isolated", dest
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
