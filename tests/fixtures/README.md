## real_timeline_snapshot.html

A trimmed real capture of `https://wuwatracker.com/timeline`, saved 2026-08-23.

It contains only the page's `<script>self.__next_f.push(...)</script>` tags
(all 26 of them, in original order) — the surrounding HTML (nav, footer,
styling, unrelated markup) was stripped since the scraper never reads it.
This keeps the fixture focused on what `extract_timeline_data` actually
parses, while still exercising the real quirks of production output: many
irrelevant push chunks the extractor must skip over, and the real nested
JSON shape (including a second, unrelated chunk that also happens to
contain the literal substring `"banners"`, which the extractor must not
mistake for the data payload).

At capture time it contained 10 banners and 14 activities. Since this is a
frozen snapshot, the counts are treated as fixed expectations in the tests
that use it — it will not change unless the fixture is refreshed.

To refresh: save the live page's HTML (e.g. `curl -s
https://wuwatracker.com/timeline -o page.html`, or a browser's "View
Source" / "Save As"), then run:

```bash
python3 - <<'EOF'
import re
html = open("page.html", encoding="utf-8").read()
pushes = re.findall(r'<script>self\.__next_f\.push\(\[1,".*?"\]\)</script>', html, flags=re.S)
trimmed = "<!doctype html><html><head></head><body>\n" + "\n".join(pushes) + "\n</body></html>\n"
open("tests/fixtures/real_timeline_snapshot.html", "w", encoding="utf-8").write(trimmed)
EOF
```

Then update the expected banner/activity counts in
`tests/test_scrape_wuwa_timeline.py::test_extract_timeline_data_against_real_snapshot`
and `::test_main_against_real_snapshot` to match.
