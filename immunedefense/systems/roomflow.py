"""房间运行流（A3.2，自 Gameplay 外迁）：障碍构建、初始房覆写、出口方向计算、
房间快照/还原、前进/返回。纯逻辑——零 pygame 依赖（A4 分层硬约束）。

持有宿主 Gameplay 引用（gp）：快照与推进会写回 Gameplay 的敌人/拾取物/出生点等
运行状态；RoomManager（systems/rooms.py）保持纯「房间模板池 + 序列」定义不动。
"""
from entities.obstacle import Obstacle
from systems.meta import save_meta

# 通道方向 §6：镜像关系——穿过本房 S 侧的门，出现在对侧（opposite(S)）的门旁
OPPOSITE_SIDE = {'right': 'left', 'left': 'right', 'down': 'up', 'up': 'down'}


class RoomFlow:
    """每局房间运行流：与 Gameplay.run 生命周期同长，随重开重建。"""

    def __init__(self, gp):
        self.gp = gp

    # ---------- 房间构建 / 初始房覆写 ----------

    def build_obstacles(self):
        """按当前模板构建障碍列表。"""
        return [Obstacle(s) for s in self.gp.room.current_tpl.get('obstacles', [])]

    def apply_room_state(self):
        """每房状态覆写：初始房 = 以撒地下室式教学房——无怪、出口常开、无商店台。"""
        if self.gp.current_kind == 'start':
            self.gp.room_cleared = True
            self.gp.exit_open = True
            self.gp.shop_here = False

    # ---------- 出口方向（v3 §6 通道系统） ----------

    def compute_exit_sides(self):
        """通道方向：层与层之间 = 垂直（下/上），同层之间 = 平级（右/左）。"""
        gp = self.gp
        seq = gp.room.sequences
        i = gp.room.index
        cur = seq[i][0]
        nxt = seq[i + 1][0] if i + 1 < len(seq) else cur
        prv = seq[i - 1][0] if i > 0 else None
        gp.exit_side = 'down' if nxt > cur else 'right'   # 前进：往下层 / 平级
        gp.exit_kind = 'vessel_hole' if gp.exit_side == 'down' else 'door'
        gp.back_side = ('up' if prv < cur else 'left') if prv is not None else None

    # ---------- 快照 / 还原（v3 返回机制） ----------

    def snapshot(self):
        """离开房间时的状态快照（返回时还原）。"""
        gp = self.gp
        return {
            'index': gp.room.index, 'layer': gp.current_layer,
            'kind': gp.current_kind,
            'pickups': list(gp.pickups), 'enemies': list(gp.enemies),
            'projectiles': list(gp.projectiles),
            'enemy_projectiles': list(gp.enemy_projectiles),
            'poison_zones': list(gp.poison_zones),
            'fireflies': list(gp.fireflies),
            'shop_here': gp.shop_here, 'shop_spot': gp.shop_spot,
            'room_cleared': gp.room_cleared, 'exit_open': gp.exit_open,
        }

    def restore(self, state):
        """还原房间到离开瞬间（敌人原样：死的不复活、动的保持位置/血/分裂计时）。

        v3 状态缓存：第二次进入（无论前进还是返回）一律还原快照，绝不重新刷怪。
        """
        gp = self.gp
        gp.room.current_tpl = gp.room.templates[gp.room.index]
        gp.room_obstacles = self.build_obstacles()
        gp.current_layer = state['layer']
        gp.current_kind = state['kind']
        gp.pickups = list(state['pickups'])
        gp.enemies = list(state['enemies'])
        gp.projectiles = list(state['projectiles'])
        gp.enemy_projectiles = list(state['enemy_projectiles'])
        gp.poison_zones = list(state['poison_zones'])
        gp.fireflies = list(state.get('fireflies', []))
        gp.shop_here, gp.shop_spot = state['shop_here'], state['shop_spot']
        gp.room_cleared = state['room_cleared']
        gp.exit_open = state['exit_open']
        self.compute_exit_sides()
        gp.floaters = []

    # ---------- 前进 / 返回 ----------

    def go_back(self):
        """返回上一房：还原快照（清过的房保留剩余拾取物/商店，未清的继续战斗）。"""
        gp = self.gp
        prev_back_side = gp.back_side       # 本房返回口 = 上一房的进入方向
        gp.room.back()
        gp._entry_side = OPPOSITE_SIDE[prev_back_side]
        state = gp.room_cache.get(gp.room.index)
        if state is None:
            # 兜底：理论不会发生（回得到的房间必然离开过 → 已缓存）
            gp.current_layer, gp.current_kind, gp.enemies, free_wbc = gp.room.spawn_room()
            gp.room_obstacles = self.build_obstacles()
            gp.pickups = gp._make_pickups(free_wbc)
            gp.fireflies = gp._spawn_fireflies()
            gp.room_cleared = False
            gp.shop_here = gp.room.roll_shop()
            gp.shop_spot = gp._shop_spot_pos()
            self.compute_exit_sides()
        else:
            self.restore(state)
        gp._place_player_at_entry(gp._entry_side)

    def advance(self):
        """进下一房（或通关结算）：离开前快照（可返回）；已访问过的房间还原不刷怪。"""
        gp = self.gp
        gp.room_cache[gp.room.index] = self.snapshot()   # 离开前快照（可返回）
        prev_layer = gp.current_layer
        prev_exit_side = gp.exit_side      # 本房前进方向的洞 = 下一房的入口方向
        gp.room.advance()
        if gp.room.done:
            gp._settle_offering()
            # NE 残留（《开头与结局设计.md》§2.2）：通关瞬间按本局死亡白细胞数计算
            gp.ending_residual = gp._residual_percent(gp.wbc_deaths)
            gp.ending_perfect = gp.ending_residual < 0.1
            if gp.ending_perfect:
                gp.perfect_ne_count += 1
                save_meta(gp.offering, gp.next_run_buffs, gp.meta_path,
                          perfect_ne_count=gp.perfect_ne_count)
            gp._te_pending = gp.perfect_ne_count >= 3   # 第 3 次完美局 → TE
            # v4 §5.6：TE2 = 本局打开过档案室左半区（与 TE 独立，可叠加）
            gp._te2_pending = gp.archive_left_read
            if gp.archive_left_read and not gp.te2_seen:
                gp.te2_seen = True
                save_meta(gp.offering, gp.next_run_buffs, gp.meta_path,
                          perfect_ne_count=gp.perfect_ne_count, te2_seen=gp.te2_seen)
            # v5：成就判定与通关战绩入库（ending 按最终标记）
            gp._check_achievements()
            _ending = "TE2" if gp._te2_pending else ("TE" if gp._te_pending else "NE")
            gp._record_run(_ending)
            # 打出 TE 后清空完美局计数：下一局从 0 重新累计，需再打 3 次完美局才再出 TE。
            # 成就在上方 _check_achievements 已按 >=3 判定并持久化，清空不影响已解锁成就。
            if gp._te_pending:
                gp.perfect_ne_count = 0
                save_meta(gp.offering, gp.next_run_buffs, gp.meta_path,
                          perfect_ne_count=0)
            gp.ending_stage = 0
            gp._set_scene('ending')
            return
        gp._entry_side = OPPOSITE_SIDE[prev_exit_side]   # 镜像：右门进→左门旁
        state = gp.room_cache.get(gp.room.index)
        if state is not None:
            # 已访问过的房间：还原离开瞬间（清过的不复活、没清完的接着打）
            self.restore(state)
            gp._title_banner_pending = False
        else:
            gp.current_layer, gp.current_kind, gp.enemies, free_wbc = gp.room.spawn_room()
            gp.room_obstacles = self.build_obstacles()
            gp.shop_here = gp.room.roll_shop()   # 本房是否生成商店台（BOSS 前房必刷）
            gp.shop_spot = gp._shop_spot_pos()
            gp.fireflies = gp._spawn_fireflies()   # v6：每房 50% 刷萤火虫（仅 dim）
            gp.exit_open = False
            gp.exit_kind = 'door'
            gp.room_cleared = False
            self.apply_room_state()
            self.compute_exit_sides()
            gp.floaters = []
            gp.pickups += gp._make_pickups(free_wbc)
            # 层际标题横幅：进入新层，或初始房之后的第 1 间战斗房（返回不触发）
            gp._title_banner_pending = (gp.room.index == 1
                                        or prev_layer != gp.current_layer)
        gp._place_player_at_entry(gp._entry_side)
