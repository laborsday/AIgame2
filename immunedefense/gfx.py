"""图像资源加载与缓存（单一加载点，避免重复读盘）。"""
import os

import pygame

import paths

ASSET_DIR = paths.assets_dir()

_cache = {}


def load(name, size=None, subdir=''):
    """加载 PNG 并缓存；size=(w, h) 时缩放；subdir 为 assets/ 下的子目录。"""
    key = (name, size, subdir)
    img = _cache.get(key)
    if img is None:
        path = os.path.join(ASSET_DIR, subdir, name)
        img = pygame.image.load(path).convert_alpha()
        if size:
            img = pygame.transform.smoothscale(img, size)
        _cache[key] = img
    return img


def load_ui(name, size=None):
    """加载 assets/ui 下的 UI 组件。"""
    return load(name, size=size, subdir='ui')


def load_icon_safe(name, size):
    """加载 ui/icons 图标；缺失/损坏时返回 None（调用方自行跳过绘制）。"""
    try:
        return load(name, (size, size), subdir='ui/icons')
    except Exception:
        return None


_fonts = {}


def font(size, bold=False):
    """CJK 字体（微软雅黑），缓存避免重复创建。"""
    key = (size, bold)
    f = _fonts.get(key)
    if f is None:
        f = pygame.font.SysFont("microsoftyahei", size, bold=bold)
        _fonts[key] = f
    return f
