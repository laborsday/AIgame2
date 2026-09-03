"""pytest 共享 fixture（B1）：无窗口运行 + 模块级主场景（临时存档隔离，结束还原真实存档）。"""
import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import sys
import tempfile

# 测试进程路径注入（收集阶段生效）：
# - game 目录自身（python -m pytest 从任意 cwd 运行都可用）
# - git 根（server/ 包所在处）：test_panel.py 顶层 from server.app import create_app
#   需要它是可导入的；从父目录跑时 os.getcwd() 已在 path 上，但这层注入保证
#   `cd immunedefense && python -m pytest` 同样不报 ModuleNotFoundError: 'server'
_GAME_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _GAME_DIR)
sys.path.insert(0, os.path.dirname(_GAME_DIR))

# v5：本地库数据目录注入临时位（杜绝测试触碰用户真实档）
os.environ["V5_DATA_DIR"] = os.path.join(tempfile.gettempdir(), "v5_test_data")

import pygame  # noqa: E402
import pytest  # noqa: E402

from core.game import Game  # noqa: E402
from core.scene import SceneManager  # noqa: E402
from core.gameplay import Gameplay  # noqa: E402
from systems.meta import load_meta, save_meta  # noqa: E402


@pytest.fixture(scope="module")
def game():
    """模块级：一个 Game 实例（pygame 生命周期由 fixture 管理）。"""
    pygame.init()
    g = Game()
    g.scenes = SceneManager()
    yield g
    pygame.quit()


@pytest.fixture(scope="module")
def scene(game):
    """模块级主场景：同一 Gameplay 实例贯穿整个文件（用例按定义顺序共享状态，
    与迁移前的线性脚本语义一致）。

    存档隔离：快照真实 meta（V5_DATA_DIR 注入的临时档）→ 场景走临时档 →
    teardown 原样还原，测试不消费用户已购的「下一局 buff」、不污染祭点/完美局计数。
    """
    real_meta = load_meta(None)
    smoke_meta = os.path.join(tempfile.gettempdir(), "smoke_meta.json")
    game.scenes.push(Gameplay(game, meta_path=smoke_meta))
    s = game.scenes.current()
    s._smoke_meta = smoke_meta   # 供用例内把场景切回隔离档
    yield s
    save_meta(real_meta["offering"], real_meta["next_buffs"], None,
              perfect_ne_count=real_meta["perfect_ne_count"])
    for p in (smoke_meta, os.path.splitext(smoke_meta)[0] + ".db"):
        try:
            os.remove(p)
        except OSError:
            pass
