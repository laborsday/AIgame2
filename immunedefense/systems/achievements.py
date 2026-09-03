"""成就定义（v5）：单一数据源 data/achievements.json，游戏端与档案管理面板共用。

成就只实现「战友的徽章」（reliquary，通关 3 次完美结局）——v5 定稿，其余四项暂缓；
数据结构与判定入口预留扩展（下表加一行即可）。
"""
import json
import os

import paths

ACHIEVEMENTS_JSON = os.path.join(paths.data_dir(), "achievements.json")


def load_achievements(path=None):
    """读取成就表（list[dict]）；缺失/损坏返回 []。"""
    p = path or ACHIEVEMENTS_JSON
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("achievements", []))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def find_achievement(aid, path=None):
    for a in load_achievements(path):
        if a.get("aid") == aid:
            return a
    return None
