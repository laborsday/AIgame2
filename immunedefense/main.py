"""《免疫防线》入口：初始化 + 主循环。

运行：python main.py（需安装 pygame）
v5：启动同时拉起本地档案管理面板（Flask，127.0.0.1:8765，失败静默）。
"""
import os
import sys

# 允许从任意工作目录运行
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _APP_DIR)
# v5：仓库根入 path（server/ 包：本地档案管理面板）
sys.path.insert(0, os.path.dirname(_APP_DIR))

from core.game import Game
from core.scene import SceneManager
from core.menu import MainMenu


def main():
    game = Game()
    game.scenes = SceneManager()
    try:
        from server.app import start_panel_thread   # v5：本地面板（daemon）
        start_panel_thread()
    except Exception:
        pass   # 面板起不来不影响游戏
    game.scenes.push(MainMenu(game))
    game.run()


if __name__ == "__main__":
    main()
