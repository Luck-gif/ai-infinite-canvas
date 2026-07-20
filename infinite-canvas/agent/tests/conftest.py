"""pytest 配置：确保 agent/ 目录在 sys.path 中，使测试可以 import 主模块。"""
from __future__ import annotations
import os
import sys

# agent/ 目录 = tests/ 的父目录
_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
