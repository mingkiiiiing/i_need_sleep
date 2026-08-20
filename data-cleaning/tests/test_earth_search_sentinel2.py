import unittest

from pipeline.sources.earth_search_sentinel2 import DEFAULT_ASSETS, build_search_payload, select_scene


class EarthSearchSentinel2Tests(unittest.TestCase):
    def test_payload_is_bounded_and_no_auth(self):
        payload = build_search_payload("2026-08-01", "2026-08-19", max_cloud=20)
        self.assertEqual(payload["collections"], ["sentinel-2-c1-l2a"])
        self.assertEqual(len(payload["bbox"]), 4)
        self.assertEqual(payload["query"]["eo:cloud_cover"]["lt"], 20)

    def test_scene_requires_every_requested_asset(self):
        incomplete = {"id": "bad", "assets": {"red": {"href": "x"}}, "properties": {}}
        complete = {"id": "ok", "assets": {name: {"href": f"https://example/{name}.tif"} for name in DEFAULT_ASSETS}, "properties": {}}
        self.assertEqual(select_scene([incomplete, complete])["id"], "ok")
