import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.sources.lake_geodata import probe_lake_geodata_sources, summarize_lake_geodata_html


class LakeGeodataProbeTests(unittest.TestCase):
    def test_summary_reports_metadata_access_boundary(self):
        html = """
        <html><head><title>太湖常规观测数据</title></head>
        <body>2008年至今 太湖 叶绿素 数据样例。完整的数据可通过加入数据订单审核后获取。
        未经本平台书面许可不得复制。</body></html>
        """
        result = summarize_lake_geodata_html(html)
        self.assertTrue(result["mentions_taihu"])
        self.assertTrue(result["mentions_chlorophyll"])
        self.assertTrue(result["mentions_sample"])
        self.assertTrue(result["order_required_language"])
        self.assertTrue(result["license_restriction_language"])

    def test_probe_persists_html_and_sqlite_manifest(self):
        body = b"<html><title>Taihu</title><body>\xe5\xa4\xaa\xe6\xb9\x96 \xe6\x95\xb0\xe6\x8d\xae\xe6\xa0\xb7\xe4\xbe\x8b</body></html>"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("pipeline.sources.lake_geodata._fetch_html", return_value=(200, "text/html", body)):
                result = probe_lake_geodata_sources(root / "out", root / "data.db", urls={"test": "https://example.test/page"})
            self.assertEqual(result["metadata_pages_http_200"], 1)
            self.assertTrue((root / "out" / "lake_geodata_probe.json").exists())
            self.assertTrue((root / "data.db").exists())


if __name__ == "__main__":
    unittest.main()

