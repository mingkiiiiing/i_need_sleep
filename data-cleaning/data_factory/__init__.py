"""Data Factory — 真实数据约束的太湖水环境训练数据生成与处理模块 (设计 V1.0 §13)."""

from __future__ import annotations

GENERATOR_VERSION = "df-0.3.0"  # 大任务1：统一气象驱动 observed_replay，特征/标签同源 + driver_hash 身份链
CONTRACT_VERSION = "1.2"
