# -*- coding: utf-8 -*-
"""命名入口：clean_modis_ocean_color（实现见 final_cleaners.py / 调度见 cleaner_cli.py）。"""
import sys
from pathlib import Path

sys.exit(__import__("cleaner_cli").main(["clean_modis_ocean_color", *sys.argv[1:]]))
