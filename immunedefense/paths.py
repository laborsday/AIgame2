"""运行时资源路径解析（v5 打包修复）。

开发环境：BASE_DIR = 本文件所在目录（immunedefense/）。
PyInstaller（onedir）：模块被打进 _internal，`sys._MEIPASS` = _internal，
而 assets/data 按 spec 收集为 _internal/assets 与 _internal/data（顶层 target）。
统一入口：paths.data_dir() / paths.assets_dir()，全部资源模块改走本模块，
不再用「__file__ 逐级 dirname」（该打法在打包布局下层级错位）。
"""
import os
import sys

_MEIPASS = getattr(sys, "_MEIPASS", None)
BASE_DIR = _MEIPASS if _MEIPASS else os.path.dirname(os.path.abspath(__file__))


def base_dir():
    return BASE_DIR


def assets_dir():
    return os.path.join(BASE_DIR, "assets")


def data_dir():
    return os.path.join(BASE_DIR, "data")
