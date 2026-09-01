# -*- coding: utf-8 -*-
"""命名入口：clean_bloom_archive（实现见 final_cleaners.py / 调度见 cleaner_cli.py）。"""
import sys
from pathlib import Path

sys.exit(__import__("cleaner_cli").main(["clean_bloom_archive", *sys.argv[1:]]))
