"""本地配置文件：读取/写入「跳过开场剧情 / 音效开关 / 模式设置（正常/昏暗）」开关。

- `skip_intro`：跳过开场剧情（答辩演示用）。
- `sound_on`  ：音效开关（关 = AudioBus 静音，全局生效）。
- `light_mode`：'dim'（昏暗模式，默认）= 战斗房四周渐暗 + 手术灯光照；
                'normal'（正常模式）= 去除灯光渲染（无黑暗、无打光）。

v5：配置随存档一起进用户数据目录（打包后 data/ 只读，config.json 不能写原位置）；
旧位置（data/config.json）仅读兼容——存在时沿用旧值，写入始终写新位置。
内存缓存：无 path 参数的读/写走缓存（切换即时生效，渲染帧不重复读盘）。
"""
import json
import os

import paths
from systems.dblocal import data_dir

CONFIG_PATH = os.path.join(data_dir(), "config.json")
_LEGACY_PATH = os.path.join(paths.data_dir(), "config.json")

_DEFAULTS = {"skip_intro": False, "sound_on": True, "light_mode": "dim"}
_cache = None


def _normalize(data):
    return {
        "skip_intro": bool(data.get("skip_intro", False)),
        "sound_on": bool(data.get("sound_on", True)),
        "light_mode": "normal" if data.get("light_mode") == "normal" else "dim",
    }


def load_config(path=None):
    """读取配置，缺失/损坏字段回退默认值；无 path 时走内存缓存。"""
    global _cache
    if path is None and _cache is not None:
        return dict(_cache)
    p = path or CONFIG_PATH
    data = {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # 兼容旧位置（仅读；写入永远去用户数据目录）
        try:
            with open(_LEGACY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
    cfg = _normalize(data)
    if path is None:
        _cache = cfg
    return cfg


def save_config(cfg, path=None):
    """写入配置（幂等合并字段），返回写入内容。"""
    global _cache
    p = path or CONFIG_PATH
    d = _normalize(cfg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    if path is None:
        _cache = d
    return d


def get_config():
    """读取当前配置（内存缓存，渲染帧零文件 IO；首次调用才读盘）。"""
    return load_config()


def set_skip_intro(value, path=None):
    """设置并落盘「跳过开场剧情」开关，返回新值。"""
    return save_config({**load_config(path), "skip_intro": bool(value)}, path)["skip_intro"]


def set_sound_on(value, path=None):
    """设置并落盘「音效开关」，返回新值。"""
    return save_config({**load_config(path), "sound_on": bool(value)}, path)["sound_on"]


def set_light_mode(value, path=None):
    """设置并落盘「模式设置」：'normal' | 'dim'，返回新值。"""
    return save_config({**load_config(path), "light_mode": value}, path)["light_mode"]
