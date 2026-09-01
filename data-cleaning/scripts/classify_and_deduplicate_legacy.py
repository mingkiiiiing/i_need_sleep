# -*- coding: utf-8 -*-
"""命名入口：classify_and_deduplicate_legacy（实现见 final_cleaners.py / 调度见 cleaner_cli.py）。"""
import sys
from pathlib import Path

sys.exit(__import__("cleaner_cli").main(["classify_and_deduplicate_legacy", *sys.argv[1:]]))
