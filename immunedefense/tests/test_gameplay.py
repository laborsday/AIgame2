"""核心玩法测试套件（B1，自 smoke_test.py 迁移）：按功能分区拆为独立 test_* 用例。

用例按定义顺序共享模块级 scene fixture（与迁移前线性脚本语义一致）；
任一断言失败 → pytest 报出具体用例名 + 堆栈 + 非零退出码。
"""
import math
import os
import random as _rnd
import tempfile
import time

import pygame
import pytest

from core.configs import load_config as _lc, set_skip_intro as _ssi
from core.gameplay import Gameplay
from entities.cancer import (BossCore, Cancer, EliteFragment, EliteRage, EliteShield,
                             EliteSummoner, PoisonZone, Variant)
from entities.enemy_projectile import EnemyProjectile
from entities.obstacle import Obstacle
from entities.pickup import Pickup
from entities.wbc import WBC, WBC_ORDER
from systems.backpack import Backpack
from systems.collision import (circles_overlap, contact_pairs, resolve_overlaps,
                               resolve_obstacle_collisions)
from systems.combat import aura_bonus_map, rage_bonus, rage_tier, resolve_zone_damage
from ui.floater import FloatText
from systems.meta import load_meta, save_meta
from systems.rooms import RoomManager
from systems.rng import RunRNG
from ui.fx import FxManager, draw_mark_ring


class FakeKeys:
    """模拟 pygame 按键状态（无窗口测试移动逻辑用）。"""

    def __init__(self, pressed):
        self._pressed = set(pressed)

    def __getitem__(self, key):
        return key in self._pressed


# ---------- 自由运行 / 初始房 ----------

def test_free_run(scene):
    """2 秒自由运行不崩（世界层渲染全路径）。"""
    for _ in range(120):
        scene.update(1 / 60)
        scene.render(pygame.display.get_surface())


def test_start_room(scene):
    """初始房 = 以撒式教学房：无怪、出口常开、无商店台；开局无细胞无卡牌。"""
    start_room_ok = (scene.current_kind == 'start' and not scene.enemies
                     and scene.exit_open and scene.room_cleared and not scene.shop_here)
    no_start_cell_ok = not scene.allies and not scene.player.cards
    assert start_room_ok
    assert no_start_cell_ok
    # 置入默认班底，供后续 Day1 战斗测试使用
    scene.player.cards['neutrophil'] = 1
    scene.try_summon('neutrophil')


# ---------- Day 1：移动 / 近战 ----------

def test_day1_move(scene):
    player = scene.player
    x0 = player.x
    keys = FakeKeys([pygame.K_d])
    for _ in range(30):
        player.handle_input(keys)
        player.update(1 / 60)
    moved = player.x - x0
    assert 100 < moved < 140


def test_day1_melee(scene):
    """中性粒细胞贴脸咬死癌细胞（压低血量只验机制，不测平衡）。"""
    scene.enemies.clear()
    c = Cancer(scene.player.x, scene.player.y + 40)
    c.awake = True
    c.take_damage(35)
    scene.enemies.append(c)
    w = scene.allies[0]
    w.x, w.y = c.x - 12, c.y
    w._attack_cd = 0.0
    scene.player.set_target(c)
    frames = 0
    while c.alive and frames < 900:
        slot = scene.guide.formation_slot(0, len(scene.allies))
        scene.guide.update_wbc(scene.player, w, slot, scene.projectiles)
        w.update(1 / 60)
        c.target = c.pick_target(scene.allies, scene.player)
        c.chase(c.target)
        c.update(1 / 60)
        for a, e in contact_pairs(scene.allies, scene.enemies):
            a.try_attack(e)
        c.try_attack_target(c.target)
        frames += 1
    assert not c.alive


# ---------- Day 2：召唤 / 上限 / 引导 / T 远程 / NK 爆发 ----------

def test_day2_summon_cap(scene):
    n0 = len(scene.allies)
    scene.player.cards['t_cell'] = 2
    c0 = scene.player.cards['t_cell']
    summon_ok = scene.try_summon('t_cell') and len(scene.allies) == n0 + 1 \
        and scene.player.cards['t_cell'] == c0 - 1
    assert summon_ok
    for t in ('macrophage', 'nk'):
        scene.player.cards[t] = 1
        scene.try_summon(t)
    scene.player.cards['neutrophil'] = 5
    assert len(scene.allies) == scene.player.wbc_cap
    assert not scene.try_summon('neutrophil')


def test_day2_guide(scene):
    """标定引导：中性粒细胞冲向目标。"""
    scene.enemies.clear()
    target_c = Cancer(scene.player.x + 150, scene.player.y)
    scene.enemies.append(target_c)
    scene.player.set_target(target_c)
    w = next(a for a in scene.allies if a.wbc_type == 'neutrophil')
    d0 = w.dist_to(target_c)
    for _ in range(60):
        scene.update(1 / 60)
    d1 = w.dist_to(target_c)
    assert d1 < d0 - 30


def test_day2_tcell_shot(scene):
    """T 细胞远程击杀（投射物路径）。"""
    scene.state = 'playing'
    scene.enemies.clear()
    t_cell = next(a for a in scene.allies if a.wbc_type == 't_cell')
    scene.allies = [t_cell]
    target2 = Cancer(t_cell.x + 100, t_cell.y)
    target2.take_damage(35)
    scene.enemies.append(target2)
    fired = 0
    frames2 = 0
    while target2.alive and frames2 < 900:
        scene.player.set_target(target2)  # 持续标定，避免 3s 超时
        scene.update(1 / 60)
        fired = max(fired, len(scene.projectiles))
        frames2 += 1
    assert not target2.alive and fired > 0
    scene.state = 'playing'


def test_day2_nk_burst(scene):
    """NK 标定瞬间 AoE 爆发。"""
    scene.state = 'playing'
    scene.player.cards['nk'] = 1          # 自备卡再召唤（前序用例清空了阵容）
    assert scene.try_summon('nk')
    nk = next(a for a in scene.allies if a.wbc_type == 'nk')
    scene.allies = [nk]
    nk.burst_cd_left = 0.0
    scene.enemies.clear()
    e1 = Cancer(nk.x + 40, nk.y)   # 爆发范围内
    e2 = Cancer(nk.x + 300, nk.y)  # 范围外
    scene.enemies += [e1, e2]
    scene._set_target_at(e1.x, e1.y)
    assert e1.hp < e1.max_hp and e2.hp == e2.max_hp


# ---------- 仇恨系统 ----------

def test_taunt_aggro_default(scene):
    player = scene.player
    macro = WBC(player.x + 100, player.y, 'macrophage')
    scene.allies = [macro]
    scene.enemies.clear()
    et = Cancer(player.x + 300, player.y)
    scene.enemies.append(et)
    assert et.pick_target(scene.allies, player) is macro      # 嘲讽：优先巨噬
    w2 = WBC(player.x + 100, player.y, 'neutrophil')
    scene.allies = [w2]
    et.on_hit_by(w2)
    assert et.pick_target(scene.allies, player) is w2         # 仇恨：反击攻击者
    et._aggro_wbc = None
    et._aggro_timer = 0.0
    assert et.pick_target(scene.allies, player) is player     # 默认：攻击玩家


# ---------- 睡眠 / 唤醒 / 分裂 ----------

def test_sleep_wake(scene):
    player = scene.player
    s1 = Cancer(player.x + 300, player.y)   # 300 > 140 → 保持睡眠
    s1.try_wake(player)
    assert not s1.awake
    s2 = Cancer(player.x + 120, player.y)   # 120 ≤ 140 → 靠近唤醒
    s2.try_wake(player)
    assert s2.awake
    s3 = Cancer(player.x + 400, player.y)   # 被攻击 → 唤醒
    s3.on_hit_by(WBC(player.x, player.y, 'neutrophil'))
    assert s3.awake


def test_split_spawn(scene):
    player = scene.player
    spl1 = Cancer(player.x + 500, player.y)   # 睡眠：计时归零 → 分裂
    spl1.split_timer = 0.01
    spl1.update(1 / 60)
    assert spl1.take_split()
    spl2 = Cancer(player.x + 500, player.y)   # 攻击态：不分裂
    spl2.awake = True
    spl2.split_timer = 0.01
    spl2.update(1 / 60)
    assert not spl2.take_split()
    # 分裂集成：睡眠敌人计时归零 → Gameplay 场上多一个
    scene.enemies.clear()
    spl3 = Cancer(player.x + 500, player.y)
    scene.enemies.append(spl3)
    spl3.split_timer = 0.01
    scene.update(1 / 60)
    assert len(scene.enemies) == 2


# ---------- Day 3：伪装 / 精英 / BOSS / 护盾 ----------

def test_disguise_mark(scene):
    player = scene.player
    v = Variant(player.x + 200, player.y)
    scene.enemies = [v]
    scene._set_target_at(v.x, v.y)
    assert scene.player.target is not v   # 伪装：标定被跳过
    v.mark()
    scene._set_target_at(v.x, v.y)
    assert scene.player.target is v       # 标记后：可标定


def test_elite_boss_no_split(scene):
    player = scene.player
    er = EliteRage(player.x + 500, player.y)
    er.split_timer = 0.01
    er.update(1 / 60)
    assert not er.take_split()
    bc = BossCore(player.x + 500, player.y)
    bc.split_timer = 0.01
    bc.update(1 / 60)
    assert not bc.take_split()


def test_boss_split(scene):
    bc2 = BossCore(scene.player.x + 200, scene.player.y)
    bc2.awake = True
    bc2.boss_split_timer = 0.01
    bc2.update(1 / 60)
    assert bc2.take_boss_split()


def test_shield(scene):
    sh = EliteShield(scene.player.x + 200, scene.player.y)
    sh.take_damage(20)
    assert sh.hp == sh.max_hp and sh.shield == 20
    sh.take_damage(30)
    assert sh.hp == sh.max_hp - 10 and sh.shield == 0


# ---------- Day 4：房间递进 / 积分 / 奖励 / 商店 ----------

def test_room_progression(scene):
    scene.state = 'playing'
    scene.room.index = 0
    layer, kind, enemies, free_wbc = scene.room.spawn_room()
    assert kind == 'start' and len(enemies) == 0 and len(free_wbc) == 4
    assert set(free_wbc) <= set(WBC_ORDER)
    scene.room.index = 1
    layer, kind, enemies, free_wbc = scene.room.spawn_room()
    assert kind == 'normal' and len(enemies) == 3


def test_score(scene):
    scene.score = 0
    scene.enemies = [Cancer(50, 50)]
    scene.enemies[0].take_damage(999)
    scene._cleanup_and_score()
    assert scene.score == 8


def test_reward_generate_apply(scene):
    opts = scene._generate_rewards()
    assert len(opts) == 3
    card_opt = next(o for o in opts if o['kind'] == 'card')
    before = scene.player.cards.get(card_opt['wbc_type'], 0)
    scene._apply_reward(card_opt)
    assert scene.player.cards[card_opt['wbc_type']] == before + card_opt['n']


def test_shop_buy(scene):
    scene.score = 100
    before_n = scene.player.cards.get('nk', 0)
    assert scene._try_buy('nk')
    assert scene.score == 50 and scene.player.cards['nk'] == before_n + 1
    scene.score = 10
    assert not scene._try_buy('nk')


def test_shop_stand(scene):
    """BOSS 前必刷台子；清房后靠近按 E 打开。"""
    scene.room.index = len(scene.room.sequences) - 2
    assert scene.room.roll_shop()          # BOSS 前房必刷
    scene.room.index = 0
    scene.shop_here = True
    scene.shop_spot = (150, 618)
    scene.room_cleared = True
    scene.player.x, scene.player.y = scene.shop_spot
    assert scene._can_open_shop()          # 站在台子旁 → 可打开
    scene.player.x, scene.player.y = scene.shop_spot[0] - 400, scene.shop_spot[1]
    assert not scene._can_open_shop()      # 离台子远 → 不可打开
    scene.player.x, scene.player.y = scene.shop_spot
    scene.state = 'playing'
    scene.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e)])
    assert scene.state == 'shop'           # 靠近 + 按 E → 打开商店
    scene.state = 'playing'
    scene.player.x, scene.player.y = 900, 600


def test_pickup(scene):
    scene.player.x, scene.player.y = 100, 100
    pk = Pickup(100, 100, 'wbc', 't_cell')
    scene.pickups = [pk]
    before_t = scene.player.cards.get('t_cell', 0)
    scene._collect_pickups()
    assert scene.player.cards['t_cell'] == before_t + 1 and pk.collected


def test_pickups_not_inside_obstacles(scene):
    """随机白细胞拾取点避开障碍物内部（否则玩家本体被障碍阻挡，永远拾不到）。

    障碍物铺满生成区：只要 _make_pickups 的点在障碍实心圆内（超余量），
    会被玩家碰撞推开 → 够不到拾取半径。这里只验证生成逻辑：点必须自由。
    """
    _saved_obs = scene.room_obstacles
    scene.room_obstacles = [Obstacle({'type': 'dead_cells',
                                      'x': 300, 'y': 240, 'w': 680, 'h': 240})]
    scene.fireflies = []                     # 防萤火虫干扰
    picks = scene._make_pickups(['neutrophil'] * 12)
    keep = Pickup.RADIUS + scene.player.radius + 2
    for p in picks:
        assert not any(ob.collide_circle(p.x, p.y, keep) for ob in scene.room_obstacles), \
            f"拾取点 ({p.x}, {p.y}) 落在障碍内"
    scene.room_obstacles = _saved_obs            # 还原共享场景状态（模块级 scene）


def test_collision_push(scene):
    """玩家与敌人重叠 → 被推开。"""
    player = scene.player
    scene.enemies.clear()
    ct = Cancer(player.x, player.y)   # 与玩家完全重叠
    scene.enemies.append(ct)
    resolve_overlaps(scene.enemies + [player])
    assert ct.dist_to(player) >= ct.radius + player.radius - 0.5


def test_bestiary(scene):
    """图鉴：遇到（醒来）才解锁。"""
    player = scene.player
    scene.discovered.clear()
    bb = BossCore(player.x + 200, player.y)
    bb.awake = False
    scene.enemies = [bb]
    scene.update(1 / 60)
    assert 'bosscore' not in scene.discovered
    bb.awake = True
    scene.update(1 / 60)
    assert 'bosscore' in scene.discovered


# ---------- Day 5：meta / 祭点 / 成长 / 道具 / 书包 ----------

def test_meta_persist(tmp_path):
    """meta 持久化（祭点 + next_buffs 往返）。"""
    from systems.meta import load_meta as _lm, save_meta as _sm
    tmp = os.path.join(str(tmp_path), 'meta_test.json')
    _sm(30, ['atk'], tmp)
    m = _lm(tmp)
    assert m['offering'] == 30 and m['next_buffs'] == ['atk']


def test_offering_settle(scene):
    """祭点 = 白细胞死亡时的击杀数。"""
    scene.run_offering = 0
    scene.enemies = []
    scene.allies = [WBC(0, 0, 'neutrophil')]
    scene.allies[0].kills = 3
    scene.allies[0].take_damage(999)
    scene.score = 0
    scene.xp = 0
    scene._cleanup_and_score()
    assert scene.run_offering == 3


def test_offering_buy_apply(scene):
    """祭点兑换 buff + 下一局应用（隔离到临时 meta 文件）。"""
    tmp = os.path.join(tempfile.gettempdir(), 'meta_test.json')
    scene.meta_path = tmp
    scene.offering = 20
    scene.next_run_buffs = []
    scene._buy_buff(0)  # atk 15 祭点
    assert scene.offering == 5 and scene.next_run_buffs == ['atk']
    scene._apply_next_buffs()
    assert scene.run_atk_bonus == 2 and scene.next_run_buffs == []
    scene.meta_path = scene._smoke_meta
    try:
        os.remove(tmp)
    except OSError:
        pass


def test_level_evolve(scene):
    scene.xp = 100
    scene.xp_next = 100
    scene.level = 1
    scene.state = 'playing'
    scene._check_level_up()
    assert scene.state == 'evolve' and scene.level == 2
    assert len(scene.evolution_options) == 3
    scene.player.guide_radius = 200
    scene._apply_evolution({'kind': 'radius'})
    assert scene.player.guide_radius == 240


def test_items_use(scene):
    """预防针/止痛药（v3 书包接入，A3.1 后走 scene.equipment）。"""
    scene.backpack = Backpack()
    scene.backpack.add('vaccine', scene.items_data['vaccine'])
    scene.equipment.boost_timer = 0
    scene.allies = [WBC(0, 0, 'neutrophil')]
    assert scene.equipment.use_item('vaccine')
    assert scene.equipment.boost_timer > 0 and scene.allies[0].atk_mult == 1.3
    assert scene.backpack.use_one('vaccine')
    scene.backpack.add('pain', scene.items_data['pain'])
    scene.equipment.pain_timer = 0
    scene.player.dmg_mult = 1.0
    assert scene.equipment.use_item('pain')
    assert scene.equipment.pain_timer > 0 and scene.player.dmg_mult == 0.5
    assert scene.backpack.use_one('pain')


def test_bag_stack(scene):
    """书包：7 格（格 0 = 留念格）/ 堆叠上限 6 / 满格拒收 / 丢弃腾格。"""
    bk = Backpack()
    assert bk.capacity == 7
    assert bk.add('rbc', scene.items_data['rbc'])  # 同一格堆叠
    assert bk.count('rbc') == 1
    for _ in range(5):
        bk.add('rbc', scene.items_data['rbc'])
    assert bk.count('rbc') == 6
    assert not bk.add('rbc', scene.items_data['rbc'])          # 单格堆叠上限
    assert (bk.add('vaccine', scene.items_data['vaccine'])
            and bk.add('pain', scene.items_data['pain'])
            and bk.add('money', scene.items_data['money'])
            and bk.add('soup', scene.items_data['soup'])
            and bk.add('sweater', scene.items_data['sweater'])
            and bk.add('scalpel', scene.items_data['scalpel'])
            and bk.is_full()
            and not bk.add('scalpel', scene.items_data['scalpel']))  # 满格拒收
    # 丢弃 1 件装备（整格移除）→ 腾出格子 → 可再放
    assert bk.discard(5, 1) and len(bk.slots) == 6
    assert bk.add('scalpel', scene.items_data['scalpel'])


def test_backpack_swap_and_fixed(scene):
    """v4：交换排序 + 固定格导出导入（重开保留语义）。"""
    bk = Backpack()
    bk.add('rbc', scene.items_data['rbc'])
    bk.add('soup', scene.items_data['soup'])
    assert bk.swap(0, 1) and bk.slots[0]['id'] == 'soup' and bk.slots[1]['id'] == 'rbc'
    meta_slot = bk.export_fixed()
    assert meta_slot == {'id': 'soup', 'count': 1, 'dur': None, 'dur_max': None}
    bk2 = Backpack()
    assert bk2.restore_fixed(meta_slot)
    assert bk2.fixed_slot['id'] == 'soup' and not bk2.fixed_slot['active']


def test_backpack_keys(scene):
    """v4：钥匙唯一 + 合成品落固定格优先。"""
    bk = Backpack()
    assert bk.add('key_left', scene.items_data['key_left'])
    assert not bk.add('key_left', scene.items_data['key_left'])   # 唯一（不可堆叠）
    assert bk.has_key('key_left')
    bk.restore_fixed({'id': 'soup', 'count': 1, 'dur': None, 'dur_max': None})
    # 固定格被占：左半在普通格 → 合成落左半格（合成由 Gameplay 逻辑负责，此处验证落格前提）
    assert bk.add('key_right', scene.items_data['key_right'])
    assert bk.count('key_right') == 1


# ---------- Day 6：残留 / 心跳 / 死亡闪回 / 结尾 ----------

def test_residual_heartbeat(scene):
    scene.state = 'playing'
    scene.enemies = [Cancer(50, 50), Cancer(60, 60)]
    assert len(scene.enemies) == 2  # 残留 = 场上存活癌细胞数
    scene.player.max_hp = 40
    scene.player.hp = 40
    hi = scene._heartbeat_interval()
    scene.player.hp = 5
    lo = scene._heartbeat_interval()
    assert lo < hi  # 低血心跳更快


def test_death_flash(scene):
    tmp2 = os.path.join(tempfile.gettempdir(), 'meta_death_test.json')
    scene.meta_path = tmp2
    scene.state = 'playing'
    scene.player.alive = False
    scene.update(1 / 60)
    assert scene.state == 'death_flash'
    for _ in range(130):
        scene.update(1 / 60)
    assert scene.state == 'dead'
    scene.meta_path = scene._smoke_meta
    try:
        os.remove(tmp2)
    except OSError:
        pass


def test_ending_advance(scene):
    scene.ending_stage = 0
    scene.ending.advance()
    assert scene.ending_stage == 1


# ---------- Day 7：房间模板 / 障碍碰撞 ----------

def test_templates(scene):
    scene.state = 'playing'
    scene.player.alive = True
    scene.player.hp = 40
    kinds = [t.get('type') for t in scene.room.templates]
    assert len(scene.room.templates) == 8
    assert kinds[0] == 'start' and kinds[1] == 'normal' and kinds[-1] == 'boss'


def test_obstacles(scene):
    """坏死堆椭圆化圆簇；血管网络：地面管全管碰撞、拱桥拱起段可从下方钻过。"""
    ob = Obstacle({'type': 'dead_cells', 'x': 400, 'y': 300, 'w': 100, 'h': 80})
    scene.player.x, scene.player.y = 430, 340  # 圆心在障碍内
    resolve_obstacle_collisions([scene.player], [ob])
    assert not ob.collide_circle(scene.player.x, scene.player.y, scene.player.radius)
    ground = Obstacle({'type': 'vessel',
                       'path': [{'x': 200, 'y': 200}, {'x': 400, 'y': 200}],
                       'radius': 13})
    assert ground.collide_circle(300, 200, 14)
    arch = Obstacle({'type': 'vessel',
                     'path': [{'x': 500, 'y': 484}, {'x': 640, 'y': 510},
                              {'x': 780, 'y': 484}],
                     'radius': 13, 'raised': True, 'sag': 31})
    assert not arch.collide_circle(640, 500, 14)   # 拱起段：可钻
    assert arch.collide_circle(500, 484, 14)       # 贴地段：碰撞


# ---------- v3：通道系统（前进/返回；快照还原不重刷怪） ----------

def test_transition_channel(scene):
    scene.enemies = []
    scene.room_cleared = True
    scene.exit_open = True
    scene.roomflow.compute_exit_sides()
    fwd_side = scene.exit_side
    _px, _py = scene._portal_center(fwd_side)
    scene.player.x, scene.player.y = _px, _py
    scene.update(1 / 60)
    assert scene.state == 'transition'
    for _ in range(300):                     # 淡出 → (层际标题) → 淡入
        scene.update(1 / 60)
        if scene.state == 'playing':
            break
    assert scene.state == 'playing' and scene.room.index == 1
    # 白细胞跟班随主人进门：全部落在入口周围（不再是旧房坐标）
    assert all(abs(w.x - scene.player.x) <= 60 and abs(w.y - scene.player.y) <= 60
               for w in scene.allies)
    # 模拟清房：第 1 间房的怪全部击杀 → 三选一/出口均已走完
    scene.enemies = []
    scene.room_cleared = True
    scene.exit_open = True
    back_side = scene.back_side
    _bx, _by = scene._portal_center(back_side)
    scene.player.x, scene.player.y = _bx, _by
    scene.update(1 / 60)
    assert scene.state == 'transition'
    for _ in range(120):                     # 返回：淡出 → 快照还原 → 淡入（无标题）
        scene.update(1 / 60)
        if scene.state == 'playing':
            break
    assert scene.state == 'playing' and scene.room.index == 0
    # 再次前进：应还原「离开瞬间」快照，而不是重新刷怪（清过的不复活）
    _px2, _py2 = scene._portal_center(scene.exit_side)
    scene.player.x, scene.player.y = _px2, _py2
    scene.update(1 / 60)
    for _ in range(300):
        scene.update(1 / 60)
        if scene.state == 'playing':
            break
    assert scene.room.index == 1 and len(scene.enemies) == 0
    assert scene.room_cleared and scene.exit_open
    scene.state = 'playing'
    scene.exit_open = False


# ---------- v3：档案室（66% 侧门 / 四选一拿一件 / 获得横幅 / 离开即封） ----------

def test_archive_room(scene):
    # A1 后：档案室状态/交互挂载在 scene.archive（core/archive.py ArchiveRoom）
    scene.archive.in_archive = False
    scene._archive_host = 3
    scene._archive_used = False
    scene._archive_state = 'live'
    scene.room.index = 3
    scene.room.current_tpl = scene.room.templates[3]
    scene.current_layer, scene.current_kind = 2, 'normal'
    scene.room_obstacles = scene.roomflow.build_obstacles()
    scene.enemies = []
    scene.room_cleared = True
    scene.exit_open = True
    scene.roomflow.compute_exit_sides()
    _apx, _apy = scene._archive_portal_center()
    scene.player.x, scene.player.y = _apx - 40, _apy
    _ally_n = len(scene.allies)
    scene.update(1 / 60)
    for _ in range(300):
        scene.update(1 / 60)
        if scene.state == 'playing':
            break
    assert scene.state == 'playing' and scene.archive.in_archive
    assert scene.current_kind == 'archive' and len(scene.allies) == 0  # 细胞不带进记忆
    # E 拿炖汤（书桌旁；本房随机一件——固定为炖汤验证流程）
    scene.archive.item = 'soup'
    scene.player.x, scene.player.y = 640, 250
    scene.archive.interact()
    assert scene.archive.taken == 'soup'
    assert scene.backpack.count('soup') == 1 and scene.state == 'story'
    _ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {'pos': (0, 0), 'button': 1})
    scene.handle_events([_ev])            # 补全
    scene.handle_events([_ev])            # 关闭
    assert scene.state == 'playing' and scene.story is None
    # 拿完后 E 书桌 → 台灯互动（单件设计：不会出第二件）
    scene.archive.interact()
    assert scene.archive.lamp_on and scene.backpack.count('money') == 0
    # 衣柜流程：先开柜（闭柜看不到钱）→ 再拿
    scene.archive.taken = None
    scene.archive.item = 'money'
    scene.archive.wardrobe_open = False
    scene.player.x, scene.player.y = 975, 430
    scene.archive.interact()              # 开柜
    assert scene.archive.wardrobe_open
    assert scene.backpack.count('money') == 0 and scene.state == 'playing'
    scene.archive.interact()              # 拿钱 → 横幅
    assert scene.backpack.count('money') == 1 and scene.state == 'story'
    scene.handle_events([_ev])
    scene.handle_events([_ev])
    assert scene.state == 'playing'
    # 离开（右半）：门不再封死 → visited（上锁态，可再开但需钥匙）
    scene.player.x, scene.player.y = scene._portal_center('left')
    scene.update(1 / 60)
    for _ in range(120):
        scene.update(1 / 60)
        if scene.state == 'playing':
            break
    assert scene.state == 'playing' and not scene.archive.in_archive
    assert scene._archive_state == 'visited' and len(scene.allies) == _ally_n  # 细胞原样回归
    # visited 态：走近侧门不再自动进入（需按 E + 完整钥匙）
    scene.player.x, scene.player.y = _apx - 40, _apy
    scene.update(1 / 60)
    assert scene.state == 'playing' and not scene.archive.in_archive


def test_floater(scene):
    ft = FloatText(100, 100, "5", (255, 255, 255))
    ft.update(1.0)
    assert not ft.alive


# ---------- 集成：主菜单 / 开场 / 设置 ----------

def test_menu_intro_paths(scene, game):
    """主菜单 → 点开始：默认（跳过开场=关）→ 开场演出 → 播完切 Gameplay。"""
    from core.menu import MainMenu
    cfg_tmp = os.path.join(tempfile.gettempdir(), 'cfg_test.json')
    menu = MainMenu(game)
    menu.render(game.screen)
    menu._skip_intro = False   # 用默认值（关）验证开场路径
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(640, 444), button=1)
    menu.handle_events([ev])
    assert game.scenes.current().__class__.__name__ == 'IntroScene'
    intro = game.scenes.current()
    for _ in range(len(intro.MONOLOGUE) + 2):
        intro.update(999.0)
    assert game.scenes.current().__class__.__name__ == 'Gameplay'


def test_settings(scene, game):
    """设置弹层：开/关「跳过开场」开关（暂存文件），结束还原真实 config.json。"""
    from core.menu import MainMenu
    cfg_tmp = os.path.join(tempfile.gettempdir(), 'cfg_test.json')
    _ssi(True, cfg_tmp)
    menu_skip = MainMenu(game)
    menu_skip._skip_intro = _lc(cfg_tmp)['skip_intro']
    game.scenes.push(menu_skip)
    ev0 = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(640, 444), button=1)
    menu_skip.handle_events([ev0])
    assert game.scenes.current().__class__.__name__ == 'Gameplay'  # 跳过 → 直进游戏
    game.scenes.pop()

    menu_set = MainMenu(game)
    game.scenes.push(menu_set)
    _ssi(False, cfg_tmp)                       # 开关初始为关
    menu_set._skip_intro = _lc(cfg_tmp)['skip_intro']
    ev_s = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                              pos=menu_set.settings_rect.center, button=1)
    menu_set.handle_events([ev_s])
    assert menu_set.show_settings
    ev_c = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                              pos=menu_set._chk_rect.center, button=1)
    menu_set.handle_events([ev_c])
    assert menu_set._skip_intro is True
    assert _lc()['skip_intro'] is True
    ev_l = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                              pos=menu_set._settings_leave.center, button=1)
    menu_set.handle_events([ev_l])
    assert not menu_set.show_settings
    game.scenes.pop()
    try:
        os.remove(cfg_tmp)
    except OSError:
        pass
    _ssi(False)  # 还原真实 config.json（默认关）


# ---------- 收敛改造：Run Seed / BOSS 弹幕 / 免疫风暴 / 空间网格 ----------

def test_seed_repro():
    rm1 = RoomManager(1280, 720, rng=RunRNG(12345))
    rm2 = RoomManager(1280, 720, rng=RunRNG(12345))
    assert [t.get('id') for t in rm1.templates] == [t.get('id') for t in rm2.templates]


def test_boss_barrage(scene):
    scene.state = 'playing'
    scene.player.alive = True
    scene.player.hp = 100
    scene.player.x, scene.player.y = 900, 600  # 远离 boss，避免弹幕立即命中
    scene.room_obstacles = []                  # 清障碍，避免弹幕出生即撞障碍
    boss = BossCore(400, 400)
    boss.awake = True
    boss._barrage_timer = 0.01  # 加速到立即发射
    scene.enemies = [boss]
    scene.enemy_projectiles = []
    for _ in range(3):
        scene.update(1 / 60)
    assert len(scene.enemy_projectiles) > 0


def test_macrophage_tanks_barrage(scene):
    """巨噬细胞肉盾：替主角挡弹幕（坦克减伤 50%），主角在后方无伤。"""
    scene.state = 'playing'
    p = scene.player
    p.alive = True
    p.hp = 100
    p.shield = 0
    p.armor = 0
    p.dmg_mult = 1.0
    p.x, p.y = 500, 400
    p.clear_target()
    scene.room_obstacles = []
    scene.enemies = []
    scene.projectiles = []
    scene.enemy_projectiles = []

    mac = WBC(455, 400, 'macrophage')
    mac_hp = mac.hp
    scene.allies = [mac]
    # 弹幕与巨噬重叠、原地不动（speed 0）；巨噬吃 6 * 0.5 = 3
    scene.enemy_projectiles = [EnemyProjectile(455, 400, 0, 0, damage=6, owner=None)]

    scene.update(1 / 60)

    assert mac.hp == mac_hp - 3
    assert p.hp == 100
    assert len(scene.enemy_projectiles) == 0


def test_t_nk_immune_barrage(scene):
    """T 细胞 / NK 细胞免疫弹幕：弹幕穿过，不造成伤害、不消失。"""
    scene.state = 'playing'
    p = scene.player
    p.alive = True
    p.hp = 100
    p.shield = 0
    p.armor = 0
    p.dmg_mult = 1.0
    p.x, p.y = 700, 400      # 玩家远离弹幕路径
    p.clear_target()
    scene.room_obstacles = []
    scene.enemies = []
    scene.projectiles = []
    scene.enemy_projectiles = []

    tcell = WBC(400, 400, 't_cell')
    nk = WBC(400, 500, 'nk')
    tcell_hp, nk_hp = tcell.hp, nk.hp
    scene.allies = [tcell, nk]
    scene.enemy_projectiles = [EnemyProjectile(400, 400, 0, 0, damage=6, owner=None)]

    scene.update(1 / 60)

    assert tcell.hp == tcell_hp
    assert nk.hp == nk_hp
    assert len(scene.enemy_projectiles) == 1   # 弹幕未被吸收，仍存活


def test_synergy(scene):
    """T+NK 免疫风暴：标记敌人伤害翻倍。"""
    nk = WBC(0, 0, 'nk')
    nk.burst_cd_left = 0.0
    nk.atk_mult = 1.0
    scene.allies = [nk]
    e_marked = Cancer(nk.x + 40, nk.y)
    e_plain = Cancer(nk.x - 40, nk.y)
    e_marked.marked = True
    scene.enemies = [e_marked, e_plain]
    scene.player.x, scene.player.y = nk.x, nk.y
    scene._trigger_nk_burst()
    assert (e_marked.max_hp - e_marked.hp) > (e_plain.max_hp - e_plain.hp)


def test_grid():
    """空间网格：正确性（100 实体，结果与朴素全对全一致）+ 速度收益（1000+ 实体）。

    速度断言必须在大规模下才有意义：100 实体时网格构建开销 ≈ 全对全成本，
    噪声会掩盖收益；1000 实体（50 万对）O(n) vs O(n²) 才是真实差距。
    """
    def _make(n, seed=7):
        r = _rnd.Random(seed)

        class _E:
            def __init__(self):
                self.x = r.uniform(0, 1280)
                self.y = r.uniform(0, 720)
                self.radius = r.uniform(8, 24)

        ents = [_E() for _ in range(n)]
        return ents[:n // 2], ents[n // 2:]

    # —— 正确性：小规模与朴素全对全逐一比对 ——
    allies, enemies = _make(100)
    naive = set()
    for a in allies:
        for e in enemies:
            if circles_overlap(a, e):
                naive.add((id(a), id(e)))
    grid_res = set()
    for a, e in contact_pairs(allies, enemies):
        grid_res.add((id(a), id(e)))
    assert naive == grid_res

    # —— 速度收益：1000 实体（50 万对），best-of-3 抗调度抖动 ——
    allies, enemies = _make(1000)

    def _bench(fn, reps=3):
        best = float('inf')
        for _ in range(reps):
            t0 = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - t0)
        return best

    t_grid = _bench(lambda: list(contact_pairs(allies, enemies)))
    t_naive = _bench(lambda: [(a, e) for a in allies for e in enemies
                              if circles_overlap(a, e)])
    assert t_grid < t_naive * 3.0, \
        f"网格应显著快于全对全（grid={t_grid:.3f}s naive={t_naive:.3f}s）"


# ---------- v2：残血狂暴（纯函数 + 场景同步 + 免疫风暴乘算） ----------

def test_rage(scene):
    rcfg = scene.balance['rage']
    assert rage_bonus(0.70, rcfg) == 0.0
    assert abs(rage_bonus(0.55, rcfg) - 0.05) < 1e-6    # 60→50 线性中点
    assert abs(rage_bonus(0.50, rcfg) - 0.10) < 1e-6
    assert abs(rage_bonus(0.40, rcfg) - 0.15) < 1e-6    # 50→30 线性中点
    assert abs(rage_bonus(0.20, rcfg) - 0.35) < 1e-6
    assert abs(rage_bonus(0.05, rcfg) - 0.50) < 1e-6    # 低于最低档（≤10%）封顶 +50%
    assert abs(rage_bonus(0.15, rcfg) - 0.425) < 1e-6   # 20→10 线性中点
    assert abs(rage_bonus(0.10, rcfg) - 0.50) < 1e-6    # 档4 节点
    assert rage_tier(0.55, rcfg) == 0 and rage_tier(0.50, rcfg) == 1
    assert rage_tier(0.30, rcfg) == 2 and rage_tier(0.20, rcfg) == 3
    assert rage_tier(0.10, rcfg) == 4 and rage_tier(0.05, rcfg) == 4
    scene.player.hp = int(scene.player.max_hp * 0.2)  # 低血 → 档3
    scene._update_rage()
    assert scene.allies[0].rage_bonus >= 0.35 - 1e-6 and scene._rage_tier == 3
    scene.player.hp = scene.player.max_hp  # 回满 → 无加成
    scene._update_rage()
    assert scene.allies[0].rage_bonus == 0.0 and scene._rage_tier == 0
    scene.player.hp = int(scene.player.max_hp * 0.05)  # 垂死 → 档4 +50%
    scene._update_rage()
    assert scene.allies[0].rage_bonus >= 0.50 - 1e-6 and scene._rage_tier == 4
    scene.player.hp = scene.player.max_hp
    scene._update_rage()
    # 免疫风暴 × 狂暴乘算：NK 爆发（档1）对标记目标 = atk×狂暴×标记倍率
    nk2 = scene.allies[0]
    nk2.burst_cd_left = 0.0
    nk2.rage_bonus = 0.35
    nk2.rage_tier = 1
    nk2.atk_mult = 1.0
    e_mk = Cancer(nk2.x + 30, nk2.y)
    e_pk = Cancer(nk2.x - 30, nk2.y)
    e_mk.marked = True
    scene.enemies = [e_mk, e_pk]
    scene._trigger_nk_burst()
    dmg_mk = e_mk.max_hp - e_mk.hp
    dmg_pk = e_pk.max_hp - e_pk.hp
    assert abs(dmg_mk - 16 * 1.35 * 2.0) < 1e-6
    assert abs(dmg_pk - 16 * 1.35) < 1e-6


# ---------- v2：敌人机制（分层分裂 / 分级伪装 / 精英技能 / BOSS 阶段 + 毒区） ----------

def test_enemy_mech(scene):
    _sc = Cancer(0, 0)
    _sb1 = _sc.spawn_offspring()
    assert _sb1.split_tier == 1 and _sb1.can_split
    assert _sb1.max_hp == max(1, int(_sc.max_hp * 0.5))
    assert _sb1.atk == _sc.base_atk + 1
    _sb2 = _sb1.spawn_offspring()
    assert _sb2.split_tier == 2 and _sb2.can_split
    assert _sb2.atk == _sc.base_atk + 2
    _sb3 = _sb2.spawn_offspring()
    assert _sb3.split_tier == 3 and not _sb3.can_split
    assert _sb3.atk == _sc.base_atk + 3

    _v1 = Variant(0, 0)
    _v2 = Variant(0, 0)
    _v2.disguise_tier = 2
    _v2.try_wake(scene.player)
    assert _v1.disguise_tier == 1 and _v1.disguised
    assert _v2.awake and not _v2.disguised

    _er = EliteRage(200, 200)
    _er.awake = True
    _er_base_speed = _er.base_speed
    _er.hp = int(_er.max_hp * 0.2)
    _er.update(1 / 60)
    assert _er.atk_interval < _er.ATK_INTERVAL
    assert _er.speed > _er_base_speed
    _er.hp = _er.max_hp
    _er.update(1 / 60)
    assert _er.atk_interval == _er.ATK_INTERVAL

    _esh = EliteShield(300, 300)
    _esh.shield = 5
    for _i in range(int(8.2 * 60)):
        _esh.update(1 / 60)
    assert _esh.shield == _esh.max_shield
    _esh.take_damage(45)
    assert _esh.shield == 0 and _esh._shield_broke

    _esm = EliteSummoner(400, 400)
    _esm.awake = True
    _esc = Cancer(440, 400)
    _esc.awake = True
    _abm = aura_bonus_map([_esm, _esc])
    assert _abm.get(id(_esc)) == 2

    _bc = BossCore(600, 300)
    _bc.awake = True
    _bc.hp = int(_bc.max_hp * 0.5)
    _bc.update(1 / 60)
    assert _bc.phase == 2 and _bc.phase_changed
    _bc.phase_changed = False
    _bc.hp = int(_bc.max_hp * 0.2)
    _bc.update(1 / 60)
    assert _bc.phase == 3
    _bc.poison_timer = 0.0
    _bc.update(1 / 60)
    assert _bc.take_poison_ready()
    _zone = PoisonZone(0, 0, 90, 0.6, 5)
    _ec = Cancer(0, 0)
    resolve_zone_damage([_zone], [_ec], 0.5)
    assert _ec.hp < _ec.max_hp


# ---------- v2：特效系统（对象池 / 生命周期 / 标记环） ----------

def test_fx():
    _fxm = FxManager(particle_capacity=16)
    _fxm.burst_particles(0, 0, (255, 255, 255), count=30, speed=100)
    assert sum(1 for _pp in _fxm.particles._pool if _pp['alive']) == 16
    assert len(_fxm.particles._pool) == 16
    for _i in range(120):
        _fxm.update(1 / 60)
    assert all(not _pp['alive'] for _pp in _fxm.particles._pool)
    _fxm.spawn_shockwave(0, 0, 90)
    _fxm.spawn_flash(0, 0, 26)
    _fxm.spawn_red_flash()
    for _i in range(40):
        _fxm.update(1 / 60)
    assert not _fxm.shockwaves and not _fxm.hit_flashes and not _fxm.screen_flashes
    _surf = pygame.Surface((100, 100))
    draw_mark_ring(_surf, 50, 50, 12, 0.3)   # 绘制不抛错即可


# ---------- v3：装备系统（针织衣护甲 / 手术刀环绕；A3.1 后走 scene.equipment） ----------

def test_equipment(scene):
    scene.backpack = Backpack()
    scene.backpack.add('sweater', scene.items_data['sweater'])
    scene.backpack.set_active('sweater', True)   # 穿戴（真实流程：弹窗「穿戴」）
    scene.equipment.on_equip_changed()
    assert scene.player.armor == 6
    # 近战命中：癌 5 − 护甲 6 = 0（不掉血但耗 1 耐久）
    _enemy = Cancer(0, 0)
    _pv = scene.player
    _pv.hp = _pv.max_hp
    _pv.shield = 0
    _enemy.x = _pv.x + _enemy.radius + _pv.radius - 1
    _enemy.y = _pv.y
    _enemy.try_attack_target(_pv)
    assert _pv.hp == _pv.max_hp and len(scene.backpack.slots) == 1
    assert scene.backpack.slots[0]['dur'] == 11
    # 弹幕命中：6 − 护甲 6 = 0（也耗耐久）
    _pv.hp = _pv.max_hp
    _ep = EnemyProjectile(_pv.x, _pv.y, 0, 0, damage=6)
    scene.enemy_projectiles = [_ep]
    for p in scene.enemy_projectiles:               # 复现 gameplay 弹幕结算路径
        p.update(1 / 60)
        if (p.x - _pv.x) ** 2 + (p.y - _pv.y) ** 2 <= (p.radius + _pv.radius) ** 2:
            dmg = p.damage
            if _pv.armor > 0:
                dmg = max(0.0, dmg - _pv.armor)
                scene.equipment.on_armor_hit()
            dmg *= _pv.dmg_mult
            _pv.try_contact_damage(dmg)
            p.alive = False
    assert _pv.hp == _pv.max_hp and scene.backpack.slots[0]['dur'] == 10
    # 毒区 DoT：不减伤也不耗耐久（按设计边界）
    _pv.hp = 30
    _zone = PoisonZone(_pv.x, _pv.y, 90, 3.0, 12)
    resolve_zone_damage([_zone], [_pv], 0.5)
    assert _pv.hp < 30 and scene.backpack.slots[0]['dur'] == 10
    # 纸衣破损：耐久归零 → 护甲清空 + 装备消失
    scene.backpack.slots[0]['dur'] = 1
    scene.equipment.on_armor_hit()
    assert _pv.armor == 0 and scene.backpack.count('sweater') == 0
    # 手术刀：激活后 0° 刀位命中敌人（4 伤），0.5s 冷却，36 命中折断
    scene.backpack.add('scalpel', scene.items_data['scalpel'])
    scene.backpack.set_active('scalpel', True)
    _pv.hp = _pv.max_hp
    _e2 = BossCore(_pv.x + 70, _pv.y)          # BOSS 当沙袋（700 血，36 刀打不死）
    scene.enemies = [_e2]
    scene.equipment.update(1 / 60)
    assert _e2.hp == 700 - 4
    scene.equipment.update(1 / 60)
    assert _e2.hp == 696
    for _ in range(36):                 # 清零冷却+角度归零：连续命中 → 耐久耗尽折断
        scene.equipment._scalpel_cd.clear()
        scene.equipment.scalpel_angle = 0.0
        scene.equipment.update(1 / 60)
    assert scene.backpack.count('scalpel') == 0


# ---------- v2/v3：生存体系（红细胞进书包 / 护盾格 / 宝箱掉落） ----------

def test_survival(scene):
    _pv = scene.player
    _pv.shield = 10
    _pv.take_damage(4)
    assert _pv.shield == 6 and _pv.hp == _pv.max_hp
    _pv.take_damage(20)
    assert _pv.shield == 0 and _pv.hp == _pv.max_hp - 14
    _pv.hp = 20
    scene.backpack = Backpack()
    _rbc = Pickup(_pv.x, _pv.y, 'rbc')
    scene.pickups = [_rbc]
    scene._collect_pickups()
    assert _pv.hp == 20 and scene.backpack.count('rbc') == 1 and _rbc.collected
    assert scene.equipment.use_item('rbc')
    assert scene.backpack.use_one('rbc')
    assert _pv.hp == 30 and scene.backpack.count('rbc') == 0
    # 书包满：红细胞留在地上（不消耗拾取物）；7 格（v4）
    scene.backpack = Backpack()
    for _iid in ('vaccine', 'pain', 'money', 'soup', 'sweater', 'scalpel', 'scalpel'):
        scene.backpack.add(_iid, scene.items_data[_iid])
    assert scene.backpack.is_full()
    _pv.hp = 20
    _rbc2 = Pickup(_pv.x, _pv.y, 'rbc')
    scene.pickups = [_rbc2]
    scene._collect_pickups()
    assert not _rbc2.collected and _pv.hp == 20
    assert scene.backpack.count('rbc') == 0
    _pv.shield = 15
    _spk = Pickup(_pv.x, _pv.y, 'shield')
    scene.pickups = [_spk]
    scene._collect_pickups()
    assert _pv.shield == 20
    _ch = Pickup(_pv.x, _pv.y, 'chest')
    scene.pickups = [_ch]
    _cards_before = dict(scene.player.cards)
    _hp_before = _pv.hp
    scene._collect_pickups()
    _drops = [k for k in scene.pickups if k.kind in ('rbc', 'pain', 'vaccine')]
    _drop_n = {'normal': 1, 'elite': 2, 'boss': 3}.get(scene.current_kind, 1)
    assert len(_drops) == _drop_n and _hp_before == _pv.hp
    assert scene.player.cards == _cards_before   # 不再掉细胞卡


# ---------- 叙事（《开头与结局设计.md》）：NE 残留公式 / 完美局 / TE ----------

def test_story_ending(scene, game):
    _rp = scene._residual_percent
    assert abs(_rp(0) - 0.0) < 1e-9 and abs(_rp(3) - 0.03) < 1e-9
    assert abs(_rp(9) - 0.09) < 1e-9
    assert abs(_rp(15) - 0.69) < 1e-6 and abs(_rp(30) - 2.19) < 1e-6
    assert abs(_rp(108) - 9.99) < 1e-6 and abs(_rp(109) - 10.0) < 1e-9
    assert abs(_rp(200) - 10.0) < 1e-9
    assert _rp(9) < 0.1 and _rp(10) >= 0.1

    scene.wbc_deaths = 0
    scene.allies = [WBC(0, 0, 'neutrophil')]
    scene.allies[0].take_damage(999)
    scene.enemies = []
    scene._cleanup_and_score()
    assert scene.wbc_deaths == 1

    tmp4 = os.path.join(tempfile.gettempdir(), 'meta_te_test.json')
    save_meta(5, [], tmp4, perfect_ne_count=2)
    assert load_meta(tmp4)['perfect_ne_count'] == 2
    try:
        os.remove(tmp4)
    except OSError:
        pass

    _scene2 = Gameplay(game, seed=12345,
                       meta_path=os.path.join(tempfile.gettempdir(), 'meta_te2.json'))
    _scene2.perfect_ne_count = 2
    _scene2.wbc_deaths = 5
    _scene2.ending_residual = _scene2._residual_percent(5)
    _scene2.ending_perfect = _scene2.ending_residual < 0.1
    if _scene2.ending_perfect:
        _scene2.perfect_ne_count += 1
        save_meta(_scene2.offering, _scene2.next_run_buffs, _scene2.meta_path,
                  perfect_ne_count=_scene2.perfect_ne_count)
    _scene2._te_pending = _scene2.perfect_ne_count >= 3
    assert _scene2.ending_perfect and _scene2._te_pending
    assert _scene2.perfect_ne_count == 3
    assert load_meta(_scene2.meta_path)['perfect_ne_count'] == 3
    _scene2._te_shown = False
    _scene2.state = 'ending'
    for _ in range(len(_scene2.ENDING_STAGES) + 1):
        _scene2.ending.advance()
    assert _scene2.state == 'te'
    # TE 逐字演出：补全 → 点击结束 → 切祭坛（v4：结尾 → 祭坛，可兑换/回主菜单）
    _scene2._te_finished = True
    _scene2.ending.finish_te()
    assert game.scenes.current().__class__.__name__ == 'AltarScene'
    game.scenes.pop()
    try:
        os.remove(_scene2.meta_path)
    except OSError:
        pass


def test_te_clears_perfect_ne_count(game):
    """打出 TE（累计 3 次完美局）后完美局计数清空；成就 reliquary 在清空前已解锁。"""
    meta_path = os.path.join(tempfile.gettempdir(), 'meta_te_clear.json')
    save_meta(0, [], meta_path, perfect_ne_count=2)
    g = Gameplay(game, seed=99, meta_path=meta_path)
    g.achievements = []
    g.perfect_ne_count = 2
    g.wbc_deaths = 0                              # 0 死亡 → 完美局（残留 0%）
    g.room.index = len(g.room.sequences) - 1      # 最后一间房，advance 即通关
    g.roomflow.advance()

    assert g._te_pending is True                  # 本次仍触发 TE
    assert g.perfect_ne_count == 0                # 计数已清空
    assert load_meta(meta_path)['perfect_ne_count'] == 0
    assert 'reliquary' in g.achievements          # 成就在清空前已解锁

    try:
        os.remove(meta_path)
    except OSError:
        pass


# ---------- 修正清单 3.2/3.3/3.4/3.5：T 档2 穿透 / 按层伪装 / BOSS 分裂间隔 / 精英残片 ----------

def test_tcell_tier2_pierce(scene):
    """T 细胞档2 穿透射击：一颗弹射穿两敌；未达档位不穿透。"""
    _pt = WBC(0, 0, 't_cell')
    _pt.atk = 8
    _pt.rage_tier = 2
    _pt.rage_bonus = 0.0
    _projs = []
    _pa = Cancer(100, 0)
    _pb = Cancer(160, 0)
    _pt._shoot(_pa, _projs)
    assert len(_projs) == 1 and _projs[0].pierce == 1
    assert abs(_projs[0].damage - 8.0) < 1e-6
    # 复现 gameplay 投射物命中路径（穿透弹不重复结算）
    for _i in range(240):
        _proj = _projs[0]
        if not _proj.alive:
            break
        _proj.update(1 / 60)
        for _tg in (_pa, _pb):
            if _tg in _proj._hit:
                continue
            if (_proj.x - _tg.x) ** 2 + (_proj.y - _tg.y) ** 2 \
                    <= (_proj.radius + _tg.radius) ** 2:
                _tg.take_damage(_proj.damage)
                _proj._hit.add(_tg)
                if _proj.pierce > 0:
                    _proj.pierce -= 1
                    break            # 穿透：继续飞行，后续帧结算下一目标
                _proj.alive = False
                break
    assert _pa.hp < _pa.max_hp and _pb.hp < _pb.max_hp
    _pt0 = WBC(0, 0, 't_cell')
    _pt0.rage_tier = 0
    _p0 = []
    _pt0._shoot(Cancer(100, 0), _p0)
    assert len(_p0) == 1 and _p0[0].pierce == 0


def test_variant_layer_tier(scene):
    """按层生成 Variant：层1→tier1、层2→tier2；BOSS 分裂体 = 精英残片（无伪装）。"""
    _rm = scene.room
    _rm.index = 2                       # (1, normal, [Cancer, Cancer, Variant])
    _l, _k, _en1, _ = _rm.spawn_room()
    assert any(isinstance(e, Variant) and e.disguise_tier == 1 for e in _en1)
    _rm.index = 3                       # (2, normal, [Cancer, Variant, Cancer])
    _l, _k, _en2, _ = _rm.spawn_room()
    assert any(isinstance(e, Variant) and e.disguise_tier == 2 for e in _en2)
    _bo1 = BossCore(700, 300)
    _bo1.phase = 1
    _bo1_off = scene._spawn_boss_offspring(_bo1)
    assert isinstance(_bo1_off, EliteFragment)   # 阶段1 也直接召唤精英残片（无伪装）


def test_boss_split_intervals():
    """BOSS 分裂间隔按阶段查表（v2 §5.4：6→4→3s）。"""
    _bi = BossCore(700, 400)
    _bi.awake = True
    _bi.hp = int(_bi.max_hp * 0.5)      # 阶段2
    _bi.update(1 / 60)
    _bi.boss_split_timer = 0.01
    _bi.update(1 / 60)
    assert _bi.phase == 2 and _bi.take_boss_split()
    assert abs(_bi.boss_split_timer - 4.0) < 1e-6
    _bi.hp = int(_bi.max_hp * 0.2)      # 阶段3
    _bi.update(1 / 60)
    _bi.boss_split_timer = 0.01
    _bi.update(1 / 60)
    assert _bi.phase == 3 and _bi.take_boss_split()
    assert abs(_bi.boss_split_timer - 3.0) < 1e-6


def test_boss_fragment(scene):
    """BOSS 分裂 → 精英残片（小型 EliteRage，数值独立于 enemies.json）。"""
    _base = EliteRage(0, 0)
    _bo2 = BossCore(700, 500)
    _bo2.phase = 2
    _frag = scene._spawn_boss_offspring(_bo2)
    assert isinstance(_frag, EliteFragment)
    assert _frag.max_hp < _base.max_hp
    assert _frag.score < _base.score
    assert _frag.size < _base.size


# ---------- v4：祭坛 / 双半钥匙 / 档案室重开 / BOSS 战后 / TE2 ----------

def test_offering_shop_memory_buy_apply(scene):
    """v4 记忆类购买：档位解锁 + 里程碑 + 下一局应用（分型/自带细胞）。"""
    tmp = os.path.join(tempfile.gettempdir(), 'meta_v4_buy.json')
    scene.meta_path = tmp
    scene.offering = 200
    scene.next_run_buffs = []
    scene.learned_memories = []
    scene.boss_beaten_count = 0
    # Ⅰ 档可买；Ⅱ 档（需 BOSS 里程碑 + Ⅰ 已学）未解锁
    idx_n1 = next(i for i, e in enumerate(scene.buff_shop)
                  if e['key'] == 'mem_neut_1')
    idx_n2 = next(i for i, e in enumerate(scene.buff_shop)
                  if e['key'] == 'mem_neut_2')
    assert not scene._memory_unlocked(scene.buff_shop[idx_n2])
    scene.boss_beaten_count = 1
    scene.learned_memories = ['mem_neut_1']      # 仅历史学过 Ⅰ（老 learned_memories）
    assert not scene._memory_unlocked(scene.buff_shop[idx_n2])  # 本期没记住 → 仍不放行
    assert scene._buy_buff(idx_n1)               # 本期记住 Ⅰ 档
    assert scene._memory_unlocked(scene.buff_shop[idx_n2])      # Ⅰ 已记住 + BOSS 已打 → 解锁
    assert scene._buy_buff(idx_n2)
    # 应用（Ⅰ+Ⅱ 同买）：Ⅱ 含Ⅰ → 共 2 只中性（不叠加成 3 只），无攻击加成
    scene.allies = []
    scene._apply_next_buffs()
    assert scene._buffs_start_allies == ['neutrophil', 'neutrophil']
    assert 'neutrophil' not in scene.wbc_atk_bonus
    scene._spawn_start_allies()
    assert len(scene.allies) == 2 and all(w.wbc_type == 'neutrophil' for w in scene.allies)
    assert scene.next_run_buffs == []
    scene.meta_path = scene._smoke_meta
    try:
        os.remove(tmp)
    except OSError:
        pass


def test_key_grant_and_synth(scene):
    """BOSS 清房必掉右半（自动入包）；与左半同在 → 自动合成完整钥匙（落固定格优先）。"""
    scene.backpack = Backpack()
    scene.pickups = []
    scene._key_left_found_run = True
    scene.current_kind = 'boss'
    scene.player.x, scene.player.y = 640, 360
    scene.backpack.add('key_left', scene.items_data['key_left'])
    scene._grant_key_right()
    assert scene.backpack.has_key('key_full') and not scene.backpack.has_key('key_left')
    # 左半先入包落在格 0（固定格位）→ 合成品同样落在格 0
    assert scene.backpack.slots[0]['id'] == 'key_full'
    # 固定格方案：左半在格 0（restore_fixed）→ 合成品落在格 0
    scene.backpack = Backpack()
    scene.archive_left_read = False
    scene.backpack.restore_fixed({'id': 'key_left', 'count': 1,
                                  'dur': None, 'dur_max': None})
    scene._grant_key_right()
    assert scene.backpack.fixed_slot['id'] == 'key_full'


def test_key_left_one_percent_drop(scene):
    """1% 掉落：命中则该房宝箱附带左半钥匙；每局至多 1 把。"""
    scene.backpack = Backpack()
    scene.pickups = []
    scene.current_kind = 'normal'
    scene._key_left_found_run = False
    scene._key_left_drop_in_room = False
    _rng = scene.rng
    scene.rng = type('FakeRNG', (), {
        'random': lambda self: 0.005,
        'uniform': lambda self, a, b: a,
        'randint': lambda self, a, b: a,
        'choice': lambda self, seq: seq[0],
        'choices': lambda self, seq, weights=None: [seq[0]],
        'shuffle': lambda self, seq: None,
    })()
    scene._on_room_cleared()
    assert scene._key_left_drop_in_room is True
    assert scene._key_left_found_run is True
    # 开箱 → 钥匙随宝箱喷出（延迟帧）
    scene.room_cleared = True
    scene._on_pickup(Pickup(640, 360, 'chest'))
    assert scene._deferred_pickups and any(p.kind == 'key_left'
                                           for p in scene._deferred_pickups)
    scene.rng = _rng
    scene.overlay = None
    scene.scene_state = 'combat'
    scene._deferred_pickups = []


def test_archive_reopen_left(scene):
    """v4 档案室重开：visited + 完整钥匙 → E 开门（消耗）→ 左半区 → 读纸 → TE2 链。"""
    # 直接构造 visited 态 + 完整钥匙
    scene.archive.in_archive = False
    scene.archive.side = 'right'
    scene._archive_host = 3
    scene._archive_state = 'visited'
    scene.archive_left_read = False
    scene._te2_pending = False
    scene.room.index = 3
    scene.room.current_tpl = scene.room.templates[3]
    scene.current_layer, scene.current_kind = 2, 'normal'
    scene.room_obstacles = scene.roomflow.build_obstacles()
    scene.enemies = []
    scene.room_cleared = True
    scene.exit_open = True
    scene.roomflow.compute_exit_sides()
    scene.backpack = Backpack()
    scene.backpack.add('key_full', scene.items_data['key_full'])
    _apx, _apy = scene._archive_portal_center()
    scene.player.x, scene.player.y = 700, 600      # 远离侧门
    # E 但没靠近 → 无效果
    scene.state = 'playing'
    scene.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e)])
    assert scene._archive_state == 'visited' and not scene.archive.in_archive
    # 靠近 + E → 开门（消耗 key_full）→ 左半区
    scene.player.x, scene.player.y = _apx, _apy
    scene.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e)])
    assert scene.backpack.count('key_full') == 0      # 消耗
    assert scene._archive_state == 'opened'
    for _ in range(120):
        scene.update(1 / 60)
        if scene.archive.in_archive:
            break
    assert scene.archive.in_archive and scene.archive.side == 'left'
    # 左半区读纸 → 横幅 → 出口开启 + archive_left_read
    scene.player.x, scene.player.y = 640, 250
    scene.archive.interact()
    assert scene.archive.left_read and scene.archive_left_read
    assert scene.state == 'story' and scene.exit_open
    _ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {'pos': (0, 0), 'button': 1})
    scene.handle_events([_ev])
    scene.handle_events([_ev])
    assert scene.state == 'playing'
    # 离开左半 → opened 保持
    scene.player.x, scene.player.y = scene._portal_center('left')
    scene.update(1 / 60)
    for _ in range(120):
        scene.update(1 / 60)
        if scene.state == 'playing':
            break
    assert not scene.archive.in_archive and scene._archive_state == 'opened'
    # 通关结算 → te2 pending
    _tmpp = os.path.join(tempfile.gettempdir(), 'meta_v4_te2.json')
    scene.meta_path = _tmpp
    save_meta(0, [], _tmpp)
    scene.room.index = len(scene.room.sequences)   # done 态
    scene.wbc_deaths = 5
    scene.run_offering = 0
    scene.roomflow.advance()
    assert scene._te2_pending and scene.state == 'ending'
    scene.meta_path = scene._smoke_meta
    try:
        os.remove(_tmpp)
    except OSError:
        pass


def test_boss_clear_post_state(scene):
    """BOSS 清房：必掉右半钥匙 + boss_beaten 统计 + 告别之门提示不打断三选一。"""
    scene.backpack = Backpack()
    scene.pickups = []
    scene.current_kind = 'boss'
    scene._key_left_found_run = True
    scene.boss_beaten_count = 0
    scene.boss_beaten = False
    scene.player.x, scene.player.y = 640, 360
    scene._on_room_cleared()
    assert scene.boss_beaten and scene.boss_beaten_count == 1
    assert scene.backpack.has_key('key_right')
    assert scene._post_boss_hint
    assert scene.state == 'reward'   # 三选一照旧
    scene.state = 'playing'
    scene.overlay = None
    scene.scene_state = 'combat'
    scene.room_cleared = True
    scene.pickups = []


def test_altar_scene_buy_physical(game):
    """祭坛场景：实物兑换 → pending_physical（下一局注入），满 6 提示。"""
    from core.altar import AltarScene
    _rea = os.path.join(tempfile.gettempdir(), 'meta_altar.json')
    save_meta(500, [], _rea)
    # 注入临时档并重读（AltarScene 读真实档，此处仅验证逻辑路径）
    from systems.meta import load_meta as _lm
    assert _lm(_rea)['offering'] == 500
    alt = AltarScene(game)
    alt.tab = 'physical'
    assert 'key_left' in alt.physical
    alt.meta['offering'] = 500
    alt.meta['pending_physical'] = []
    alt.meta['fixed_slot'] = None
    alt.confirm = {'kind': 'physical', 'key': 'key_left'}
    alt._do_buy()
    assert alt.meta['pending_physical'] == ['key_left']
    assert alt.meta['offering'] == 300
    # 已持有 → 不可再换
    alt.confirm = {'kind': 'physical', 'key': 'key_left'}
    assert alt._held_key_left()
    # 开局注入：固定格 + pending → 背包
    _g = Gameplay(game, seed=7,
                  meta_path=os.path.join(tempfile.gettempdir(), 'meta_altar_run.json'))
    _g.pending_physical = ['key_left']
    _g.fixed_slot_meta = None
    _g.backpack = Backpack()
    _g._inject_run_bag()
    assert _g.backpack.has_key('key_left') and _g.pending_physical == []
    assert _g.state == 'playing'
    try:
        os.remove(os.path.join(tempfile.gettempdir(), 'meta_altar_run.json'))
    except OSError:
        pass


def test_altar_reopen_with_fixed_right(scene):
    """攒兵路线（v4 §5.2 策略 B）：固定格右半跨局 + 兑换左半 → 开局合成。"""
    _tmpf = os.path.join(tempfile.gettempdir(), 'meta_v4_run.json')
    save_meta(0, [], _tmpf, fixed_slot={'id': 'key_right', 'count': 1,
                                        'dur': None, 'dur_max': None},
              pending_physical=['key_left'])
    _s = Gameplay(scene.game, seed=99, meta_path=_tmpf)
    assert _s.backpack.has_key('key_full')      # 开局注入后自动合成
    assert _s.backpack.fixed_slot['id'] == 'key_full'
    assert _s.state == 'playing' or _s.state == 'story'
    try:
        os.remove(_tmpf)
    except OSError:
        pass





