# -*- mode: python ; coding: utf-8 -*-
"""《免疫防线》PyInstaller spec（onedir）。

- 收集：assets / data（排除运行期档案：meta.json、config.json、userdata）/ server.templates / server.static
- 隐藏导入：Flask 相关依赖 + server.app（面板入口）
- exe 名：免疫防线；无控制台窗口
构建：cd 仓库根 && pyinstaller packaging/immunedefense.spec
"""
import os

from PyInstaller.building.datastruct import Tree

SPECPATH = os.path.dirname(os.path.abspath(SPEC))          # noqa: F821 (spec 全局)
APP_DIR = os.path.abspath(os.path.join(SPECPATH, "..", "immunedefense"))
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    # 打包后模块为「顶层收集」(_internal 直下)：paths.py 的 sys._MEIPASS = _internal，
    # 故 assets/data/server 都收集到 _internal 顶层（不再带 immunedefense/ 前缀）
    (os.path.join(APP_DIR, "assets"), "assets"),
    (os.path.join(REPO_ROOT, "server", "templates"), "server/templates"),
    (os.path.join(REPO_ROOT, "server", "static"), "server/static"),
]

a = Analysis(
    [os.path.join(APP_DIR, "main.py")],
    pathex=[REPO_ROOT, APP_DIR],
    datas=datas,
    hiddenimports=["server.app", "flask", "werkzeug", "jinja2", "markupsafe",
                   "itsdangerous", "click", "blinker"],
    excludes=["pytest", "tests", "tkinter", "matplotlib"],
    noarchive=False,
)
# data 目录：Tree 收集但排除「开发者/本地运行期」档案——打包分发绝不含存档
a.datas += Tree(os.path.join(APP_DIR, "data"), prefix="data",
                excludes=["meta.json", "meta.json.migrated", "config.json", "userdata"])

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="免疫防线",
    console=False,          # 无控制台窗口（面板在 daemon 线程内）
    icon=os.path.join(APP_DIR, "assets", "player_avatar_96.png") if os.path.exists(
        os.path.join(APP_DIR, "assets", "player_avatar_96.png")) else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="免疫防线")
