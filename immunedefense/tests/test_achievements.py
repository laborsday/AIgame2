"""v5：成就系统（仅 reliquary）：判定 / 幂等 / 横幅 / 锁血钩子。"""
import os

import pygame

from core.gameplay import Gameplay
from systems import dbwrite
from systems.achievements import load_achievements


def test_achievement_defs_json():
    """成就表单一数据源：仅 reliquary（其余四项暂缓）。"""
    defs = load_achievements()
    assert len(defs) == 1 and defs[0]["aid"] == "reliquary"
    assert defs[0]["name"] == "战友的徽章"


def test_reliquary_unlock_and_banner(scene):
    tmp = os.path.join(os.path.dirname(scene._smoke_meta), "achv_meta.json")
    g = Gameplay(scene.game, seed=71, meta_path=tmp)
    g.perfect_ne_count = 2
    g.achievements = []
    g._check_achievements()
    assert g.achievements == []                       # 未达标不解锁
    g.perfect_ne_count = 3
    g._check_achievements()
    assert g.achievements == ['reliquary']            # 解锁进 meta
    assert g.state == 'story'                         # 横幅演出已触发
    assert dbwrite.achievement_unlocked('reliquary')  # 入库
    g._check_achievements()                           # 幂等：重复结算不再重复
    assert g.achievements.count('reliquary') == 1
    try:
        os.remove(tmp)
        os.remove(os.path.splitext(tmp)[0] + ".db")
    except OSError:
        pass


def test_reliquary_guard(scene):
    """锁血：持有且本局未用 → hp≤0 保到 1；第二次致命伤正常死；未持有不受影响。"""
    p = scene.player
    scene._restart_run()
    p = scene.player
    scene.achievements = []
    scene._reliquary_used = False
    p.alive = True
    p.hp = 5
    p.take_damage(10)
    assert not p.alive                                  # 无成就 → 正常死亡
    scene.achievements = ['reliquary']
    scene._reliquary_used = False
    p.alive = True
    p.hp = 5
    p.take_damage(10)
    assert p.alive and p.hp == 1                        # 保住（锁到 1 血）
    p.take_damage(10)
    assert not p.alive                                  # 本局第二次致命伤 → 死亡
    scene.achievements = []
    scene._reliquary_used = False
    scene.player.alive = True
    scene.player.hp = scene.player.max_hp


def test_reliquary_guard_ignores_story_pause(scene):
    """锁血触发不影响其它机制：带护盾时盾先扣、锁血为最后防线。"""
    scene._restart_run()
    p = scene.player
    scene.achievements = ['reliquary']
    scene._reliquary_used = False
    p.alive = True
    p.hp = 5
    p.shield = 10
    p.take_damage(12)          # 盾扣 10，溢出 2 扣血 → hp 3，未触发锁血
    assert p.alive and p.hp == 3 and p.shield == 0
    scene.achievements = []
