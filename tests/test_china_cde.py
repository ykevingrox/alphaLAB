from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from biotech_alpha.china_cde import (
    classify_cde_item,
    filter_cde_items,
    parse_cde_feed,
    track_cde_updates,
)


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CDE</title>
    <item>
      <title>DualityBio 临床试验申请受理</title>
      <link>https://cde.example.cn/123</link>
      <guid>cde-123</guid>
      <pubDate>Thu, 23 Apr 2026 10:00:00 +0800</pubDate>
      <category>受理信息</category>
    </item>
    <item>
      <title>Other 公司公告</title>
      <link>https://cde.example.cn/456</link>
      <guid>cde-456</guid>
      <pubDate>Thu, 23 Apr 2026 09:00:00 +0800</pubDate>
      <category>公告</category>
    </item>
  </channel>
</rss>
"""


class ChinaCdeTest(unittest.TestCase):
    def test_parse_filter_track(self) -> None:
        items = parse_cde_feed(SAMPLE_FEED)
        self.assertEqual(len(items), 2)
        filtered = filter_cde_items(items, query="dualitybio")
        self.assertEqual(len(filtered), 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            state = Path(tmpdir) / "seen.json"
            first = track_cde_updates(items=filtered, state_path=state)
            self.assertEqual(first["new_count"], 1)
            second = track_cde_updates(items=filtered, state_path=state)
            self.assertEqual(second["new_count"], 0)

    def test_classify(self) -> None:
        item = parse_cde_feed(SAMPLE_FEED)[0]
        self.assertEqual(classify_cde_item(item), "clinical")


if __name__ == "__main__":
    unittest.main()
