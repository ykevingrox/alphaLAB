from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from biotech_alpha.hkexnews import (
    filter_hkex_items_by_ticker,
    parse_hkex_rss,
    track_hkex_news_updates,
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
            second = track_hkex_news_updates(items=items, state_path=state)
            self.assertEqual(second["new_count"], 0)


if __name__ == "__main__":
    unittest.main()
