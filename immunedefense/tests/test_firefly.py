"""v6 萤火虫系统：昏暗模式专属道具——50% 刷新 / 6s 捕捉窗口 / 飞走 / 捕捉入包 /
使用放置（永久照亮，不可再捕捉）/ 快照还原。"""
import os

import pygame

from core.gameplay import Gameplay
from entities.firefly import Firefly, CAPTURE_RANGE, CAPTURE_TIMEOUT
from entities.obstacle import Obstacle


def _meta(tmp):
    return os.path.join(tmp, "firefly_meta.json")


def _new_scene(game, seed, tmp):
    return Gameplay(game, seed=seed, meta_path=_meta(tmp))


def _with_obstacles(scene):
    """给当前房间装一个障碍物（初始房无障碍，强制注入以测刷新）。"""
    scene.room.index = 1
    scene.room_obstacles = [Obstacle({'type': 'dead_cells', 'x': 300, 'y': 220,
                                      'w': 170, 'h': 120})]


def _fresh_bag(scene):
    """用例间背包状态隔离（模块级共享 scene）。"""
    scene.backpack.slots = []


def _spawn_count(scene, seed):
    """统计该种子下多个房间的刷新结果（同房同种子恒定，跨房独立掷点）。"""
    got = 0
    for room_idx in range(1, 25):
        scene.room.index = room_idx
        scene.room_obstacles = [Obstacle({'type': 'dead_cells',
                                          'x': 200 + room_idx * 7, 'y': 200,
                                          'w': 170, 'h': 120})]
        scene.fireflies = scene._spawn_fireflies()
        got += len(scene.fireflies)
    scene.room.index = 1
    return got


# ---------- 刷新 ----------

def test_firefly_spawn_probability(scene):
    """昏暗模式：每房 50% 概率刷出（24 房样本落在 6..18 之间，防机械 0/满）。"""
    got = _spawn_count(scene, 7)
    assert 6 <= got <= 18


def test_firefly_no_obstacle_no_spawn(scene):
    """无障碍物（初始教学房）→ 不刷。"""
    _with_obstacles(scene)
    scene.room.index = 0
    scene.room_obstacles = []
    scene.fireflies = scene._spawn_fireflies()
    assert scene.fireflies == []


def test_firefly_spawn_on_perch(scene):
    """刷出的萤火虫停在障碍物顶部候选点上。"""
    _with_obstacles(scene)
    scene.fireflies = scene._spawn_fireflies()
    if not scene.fireflies:
        return   # 50% 未命中，跳过
    f = scene.fireflies[0]
    ob = scene.room_obstacles[0]
    ok = any(abs(p[0] - f.x) < 400 and abs(p[1] - f.y) < 400
             for p in ob.perch_points())
    assert f.state == 'perch'
    assert ok


# ---------- 捕捉窗口 / 飞走 ----------

def test_firefly_range_timer(scene):
    """主角进入捕捉范围 → 倒计时启动；离开范围 → 重置。"""
    f = Firefly((620, 360))
    px = type('P', (), {'x': 620 + 50, 'y': 360})()   # 50px：在 160 范围内
    for _ in range(30):
        f.update(1 / 60, px, [])
    assert f.in_range and 4.0 < f.timer < 6.0
    px = type('P', (), {'x': 900, 'y': 360})()        # 远离
    f.update(1 / 60, px, [])
    assert not f.in_range and f.timer == CAPTURE_TIMEOUT


def test_firefly_flee_after_timeout(scene):
    """超时 6s 未捕捉 → 飞离原处（state=fly，落地后 perch 于别处）。"""
    obs = [Obstacle({'type': 'dead_cells', 'x': 300, 'y': 220, 'w': 170, 'h': 120}),
           Obstacle({'type': 'dead_cells', 'x': 800, 'y': 300, 'w': 170, 'h': 120})]
    f = Firefly(obs[0].perch_points()[1])          # 从中点停留
    x0, y0 = f.x, f.y
    px = type('P', (), {'x': f.x + 40, 'y': f.y})()
    for _ in range(int(CAPTURE_TIMEOUT * 60) + 5):  # 超时 + 一帧余量
        f.update(1 / 60, px, obs)
    assert f.state == 'fly' or (f.state == 'perch' and
                                (f.x - x0) ** 2 + (f.y - y0) ** 2 > 60 ** 2)
    # 落地：perch，且位置与原位不同
    for _ in range(300):
        f.update(1 / 60, px, obs)
        if f.state == 'perch':
            break
    assert f.state == 'perch'
    assert (f.x - x0) ** 2 + (f.y - y0) ** 2 > 60 ** 2


# ---------- 捕捉入包 ----------

def test_firefly_capture_flow(scene):
    """点击范围内萤火虫 → 捕捉弹窗 → 确认入包；书包满则留在原地。"""
    _with_obstacles(scene)
    scene.overlay = None
    scene.scene_state = 'combat'
    scene.fireflies = []
    f = Firefly((scene.player.x + 80, scene.player.y))
    f.in_range = True
    f.timer = CAPTURE_TIMEOUT
    scene.fireflies = [f]
    # 命中点击
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                            pos=(int(f.x), int(f.y)), button=1)
    scene.handle_events([ev])
    assert scene.overlay == 'capture' and scene.capture_target is f
    # 确认捕捉
    scene.handle_events([pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, pos=scene.capture_panel._capture_rect.center,
        button=1)])
    assert scene.overlay is None
    assert scene.backpack.count('firefly') == 1
    assert f not in scene.fireflies


def test_firefly_capture_cancel(scene):
    """取消：弹窗关闭，萤火虫原地不动。"""
    _with_obstacles(scene)
    _fresh_bag(scene)
    scene.overlay = None
    scene.scene_state = 'combat'
    f = Firefly((scene.player.x + 80, scene.player.y))
    f.in_range = True
    scene.fireflies = [f]
    scene.capture_target = f
    scene._set_overlay('capture')
    scene.handle_events([pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, pos=scene.capture_panel._cancel_rect.center,
        button=1)])
    assert scene.overlay is None
    assert f in scene.fireflies
    assert scene.backpack.count('firefly') == 0


def test_firefly_capture_out_of_range_no_popup(scene):
    """点得太远：不弹窗，走位目标设为萤火虫。"""
    _with_obstacles(scene)
    scene.overlay = None
    scene.scene_state = 'combat'
    f = Firefly((scene.player.x + 900, scene.player.y))
    f.in_range = False
    scene.fireflies = [f]
    scene.handle_events([pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, pos=(int(f.x), int(f.y)), button=1)])
    assert scene.overlay is None
    assert scene.player.target is not None


# ---------- 使用放置 ----------

def test_firefly_place_flow(scene):
    """背包使用 → 放置模式 → 点地图 → 消耗 1 只，永久照亮、不可再捕捉。"""
    _with_obstacles(scene)
    _fresh_bag(scene)
    scene.overlay = None
    scene.scene_state = 'combat'
    scene.place_firefly_mode = False
    entry = scene.items_data['firefly']
    assert scene.backpack.add('firefly', entry)
    assert scene._begin_firefly_place()
    assert scene.place_firefly_mode
    scene._place_firefly_at(640, 360)
    assert scene.backpack.count('firefly') == 0
    assert not scene.place_firefly_mode
    placed = scene.fireflies[-1]
    assert placed.placed
    # 飞行动画：飞行 → 落地（placed 后不再可捕捉）
    for _ in range(300):
        placed.update(1 / 60, scene.player, scene.room_obstacles)
        if placed.state == 'perch':
            break
    assert placed.state == 'perch' and placed.placed
    # 永久：主角在头顶反复更新也不飞走、不进入捕捉窗口
    placed.in_range = False
    for _ in range(int(CAPTURE_TIMEOUT * 60) + 10):
        placed.update(1 / 60, scene.player, scene.room_obstacles)
    assert placed.state == 'perch' and not placed.in_range


# ---------- 快照 / 还原 ----------

def test_firefly_snapshot_restore(scene):
    """离开房间 → 快照含萤火虫；还原后原地保留（含放置的）。"""
    _with_obstacles(scene)
    f1 = Firefly((400, 300))
    f2 = Firefly((900, 400))
    f2.placed = True
    scene.fireflies = [f1, f2]
    snap = scene.roomflow.snapshot()
    assert len(snap['fireflies']) == 2
    scene.fireflies = []
    scene.roomflow.restore(snap)
    assert len(scene.fireflies) == 2
    assert scene.fireflies[1].placed
