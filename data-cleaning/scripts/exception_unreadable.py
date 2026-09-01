# -*- coding: utf-8 -*-
"""命名入口：exception_unreadable（实现见 final_cleaners.py / 调度见 cleaner_cli.py）。"""
import sys
from pathlib import Path

sys.exit(__import__("cleaner_cli").main(["exception_unreadable", *sys.argv[1:]]))
