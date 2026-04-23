from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from biotech_alpha.hkexnews import (
    classify_hkex_item,
    filter_hkex_items_by_ticker,
    parse_hkex_rss,
    suggest_expected_dilution_pct,
    track_hkex_news_updates,
    typed_items_to_catalyst_rows,
    typed_items_to_event_impact_suggestions,
)


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>HKEXnews</title>
    <item>
      <title>09887 - Voluntary Announcement</title>
      <link>https://www.hkexnews.hk/123</link>
      <guid>hkex-123</guid>
      <pubDate>Thu, 23 Apr 2026 10:00:00 +0800</pubDate>
      <category>Announcement</category>
    </item>
    <item>
      <title>09606 - Monthly Return</title>
      <link>https://www.hkexnews.hk/456</link>
      <guid>hkex-456</guid>
      <pubDate>Thu, 23 Apr 2026 09:00:00 +0800</pubDate>
      <category>Monthly Return</category>
    </item>
  </channel>
</rss>
"""


class HkexNewsTest(unittest.TestCase):
    def test_parse_and_filter(self) -> None:
        items = parse_hkex_rss(SAMPLE_RSS)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].guid, "hkex-123")
        filtered = filter_hkex_items_by_ticker(items, ticker="09887.HK")
        self.assertEqual(len(filtered), 1)
        self.assertIn("09887", filtered[0].title)

    def test_track_updates_with_state(self) -> None:
        items = parse_hkex_rss(SAMPLE_RSS)
        with tempfile.TemporaryDirectory() as tmpdir:
            state = Path(tmpdir) / "seen.json"
            first = track_hkex_news_updates(items=items, state_path=state)
            self.assertEqual(first["new_count"], 2)
            self.assertEqual(first["typed_new_items"][0]["event_type"], "corporate")
            second = track_hkex_news_updates(items=items, state_path=state)
            self.assertEqual(second["new_count"], 0)

    def test_classify_hkex_item_by_keywords(self) -> None:
        clinical = classify_hkex_item(
            parse_hkex_rss(
                SAMPLE_RSS.replace("Voluntary Announcement", "Phase 2 Clinical Update")
            )[0]
        )
        self.assertEqual(clinical, "clinical")

    def test_typed_item_converters(self) -> None:
        items = parse_hkex_rss(
            SAMPLE_RSS.replace("Voluntary Announcement", "Financing Placement")
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = track_hkex_news_updates(
                items=items,
                state_path=Path(tmpdir) / "seen.json",
            )
        typed = payload["typed_new_items"]
        catalysts = typed_items_to_catalyst_rows(typed)
        self.assertTrue(catalysts)
        self.assertEqual(catalysts[0]["category"], "financial")
        impacts = typed_items_to_event_impact_suggestions(typed)
        self.assertTrue(impacts)
        self.assertEqual(impacts[0]["event_type"], "hkex_financing")
        dilution = suggest_expected_dilution_pct(
            typed_items=typed,
            current_expected_dilution_pct=0.01,
        )
        self.assertGreaterEqual(dilution["suggested_expected_dilution_pct"], 0.01)


if __name__ == "__main__":
    unittest.main()
