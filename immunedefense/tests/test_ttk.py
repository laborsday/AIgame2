"""B2：真实平衡 TTK 断言——满血标准配置 vs 满血癌细胞，锚定 balance.json → ttk_targets。

固定几何 + 固定步长（1/60s），无随机来源参与战斗，结果确定性；
窗口取 ttk_targets.minion [3.0, 4.0] 的宽松邻域 [2.0, 6.0]（清单 B2「拟合区间附近」）。
"""
from entities.cancer import Cancer
from entities.wbc import WBC


def _run_fight(scene, seconds_cap=10.0):
    """驱动战斗直到房间清空（或超时），返回耗时（秒）。"""
    frames = 0
    while scene.enemies and frames < seconds_cap * 60:
        scene.update(1 / 60)
        frames += 1
    return frames / 60.0


def test_melee_ttk_fullhp(scene):
    """标准配置（1 中性 + 1 T，满血、无 buff、无狂暴）vs 1 满血癌细胞：
    击杀耗时落在 minion TTK 窗口附近，且白细胞无阵亡（标准配置应当稳赢）。

    几何固定为「贴脸互殴」：中性初始即接触癌细胞（觉醒即被嘲讽命中记仇，
    双方停住对打），T 在射程内站桩射击；全程无随机来源，结果确定性。
    """
    scene.state = 'playing'
    scene.score = 0
    scene.xp = 0
    scene.xp_next = scene.balance['economy']['xp_next_factor']
    scene.player.hp = scene.player.max_hp
    # 玩家站在交战区（引导半径 200px 内），否则白细胞会被拉回阵型不参战
    scene.player.x, scene.player.y = 480, 360
    scene.equipment.boost_timer = 0
    scene.equipment.pain_timer = 0
    scene.room_cleared = True    # 击杀后不弹三选一，只测战斗
    scene.exit_open = False
    scene.room_obstacles = []
    # 标准小队：中性（近战 6 伤/0.83s）+ T（远程 8 伤/1.25s），参考 DPS ≈ 13.6
    n = WBC(400, 360, 'neutrophil')
    t = WBC(300, 360, 't_cell')
    scene.allies = [n, t]
    for w in scene.allies:
        w.rage_bonus = 0.0
        w.rage_tier = 0
        w.atk_mult = 1.0
    c = Cancer(424, 360)         # 与中性贴脸（半径和 24+2 内）
    c.awake = True
    scene.enemies = [c]
    scene.player.set_target(c)   # 引导中性贴脸，T 自动远程射击
    ttk = _run_fight(scene)
    assert not c.alive, "标准配置应在窗口内击杀满血癌细胞"
    assert all(w.alive for w in scene.allies), "标准配置不应减员"
    # minion 窗口 [3.0, 4.0] 的拟合邻域（追击瞬态 +10%~40% 裕量）
    assert 3.0 <= ttk <= 6.0, f"TTK={ttk:.2f}s 偏离 minion 窗口 [3.0, 6.0]"
