import json
import tempfile
import unittest
from pathlib import Path

from pipeline.normalize import normalize_nasa_payload, normalize_open_meteo_payload


class NormalizeTests(unittest.TestCase):
    def test_nasa_payload_becomes_long_records(self):
        payload = {
            "geometry": {"coordinates": [120.3, 31.2, 29.15]},
            "properties": {
                "parameter": {
                    "T2M": {"2025060100": 20.2},
                    "WS10M": {"2025060100": 5.0},
                    "WD10M": {"2025060100": 180.0},
                    "PRECTOTCORR": {"2025060100": 24.0},
                    "ALLSKY_SFC_SW_DWN": {"2025060100": 100.0},
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.json"
            rows = normalize_nasa_payload(path, {"payload": payload})
        self.assertEqual(len(rows), 5)
        precip = next(row for row in rows if row["variable_code"] == "precipitation")
        self.assertEqual(precip["clean_value"], 1.0)
        self.assertEqual(precip["unit"], "mm")
        self.assertEqual(rows[0]["station_id"], "NASA_POWER_120.300_31.200")

    def test_open_meteo_forecast_becomes_proxy_driver_records(self):
        payload = {
            "longitude": 120.3,
            "latitude": 31.2,
            "hourly_units": {"temperature_2m": "°C", "wind_speed_10m": "m/s", "wind_direction_10m": "°", "precipitation": "mm", "shortwave_radiation": "W/m²"},
            "hourly": {
                "time": ["2026-08-18T00:00", "2026-08-18T01:00"],
                "temperature_2m": [28.0, 28.2],
                "wind_speed_10m": [2.0, 2.2],
                "wind_direction_10m": [180, 190],
                "precipitation": [0, 0.1],
                "shortwave_radiation": [0, 12],
            },
        }
        rows = normalize_open_meteo_payload(Path("forecast.json"), {"payload": payload})
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row["value_origin"] == "forecast_proxy" for row in rows))
        self.assertEqual({row["variable_code"] for row in rows}, {"air_temperature", "wind_speed", "wind_direction", "precipitation", "shortwave_radiation"})
        self.assertEqual(rows[0]["station_id"], "OPEN_METEO_120.300_31.200")


if __name__ == "__main__":
    unittest.main()
