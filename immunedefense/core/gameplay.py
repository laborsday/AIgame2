"""核心战斗场景：引导 + 卡牌 + 敌人 + 肉鸽循环 + 成长 + 叙事。"""
import json
import math
import os
import random

import pygame

import gfx

import paths

from .scene import Scene
from .audio import AudioBus
from .configs import get_config
from .archive import ArchiveRoom   # 档案室「阳光书房」：状态与交互已外迁（修正清单 A1）
from .ending import EndingDirector, ENDING_STAGES   # 结局/故事演出已外迁（A3.4）
from entities.player import Player
from entities.wbc import WBC, WBC_NAMES, WBC_ORDER
from entities.cancer import Cancer, EliteFragment, PoisonZone
from entities.pickup import Pickup
from entities.firefly import (Firefly, CLICK_RADIUS, CAPTURE_RANGE,
                               FIREFLY_HALO_RADIUS)
from systems.collision import (contact_pairs, circles_overlap, resolve_overlaps,
                               resolve_obstacle_collisions)
from systems.combat import (aura_bonus_map, rage_bonus, rage_tier,
                             resolve_zone_damage, shield_break_hits)
from ui.floater import FloatText   # 飘字渲染住 ui/（A4：systems/ 禁用 blit）
from ui.fx import FxManager, draw_mark_ring   # A4：特效渲染住 ui/（systems/ 禁 pygame）
from systems.guide import GuideSystem, GroundTarget
from systems.rooms import RoomManager
from systems.roomflow import RoomFlow   # 房间运行流：快照/还原/前进/返回（A3.2）
from systems.meta import load_meta, save_meta
from systems import dbwrite   # v5：本地库写入（战绩/流水/成就，异常兜底）
from systems.achievements import load_achievements   # v5：成就表单一数据源
from systems.rng import RunRNG
from systems.backpack import Backpack
from systems.equipment import Equipment   # 装备/道具结算：使用/穿脱/耐久/buff（A3.1）
from ui.cardbar import CardBar
from ui.bestiary import BestiaryPanel
from ui.backpack import BackpackPanel, draw_bag_hud
from ui.panels import RewardPanel, ShopPanel, DeathPanel, CapturePanel
from ui.scalpel import draw_scalpel   # 手术刀只读渲染（A3.1）
from ui.world import WorldRenderer    # 世界层渲染：背景/门/商店台/布幡（A3.3）
from ui.lighting import LightRenderer  # 手术灯光照：中央亮区 + 四周渐暗（美术优化批次）
import settings

ITEMS_JSON = os.path.join(paths.data_dir(), "items.json")
STORY_JSON = os.path.join(paths.data_dir(), "story.json")
OFFERING_JSON = os.path.join(paths.data_dir(), "offering_shop.json")
BALANCE_JSON = os.path.join(paths.data_dir(), "balance.json")


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_items():
    """v3 道具层：全部道具定义（消耗品/装备，含数值），见 data/items.json。"""
    return _load_json(ITEMS_JSON)


def load_story():
    """档案室获得横幅文案（v3 §5.3 story.json：title/subtitle/text + type_speed）。"""
    return _load_json(STORY_JSON)


def _wrap_text(text, per_line):
    return [text[i:i + per_line] for i in range(0, len(text), per_line)]


def load_offering_shop():
    """把 offering_shop.json 转成按 key 顺序的条目列表（v4：记忆类 + 实物类）。

    记忆条目：{key,type,tier,group,name,effect,cost,unlock,requires,unlock_hint}
    实物条目由 OfferingPanel 从 data['physical'] 读取（key_left）。
    """
    d = _load_json(OFFERING_JSON)
    return d['entries']


# 兼容旧名（buffs.json → offering_shop.json 迁移期）
load_buffs = load_offering_shop


def load_balance():
    """加载 v2 数值框架（TTK/DPS/狂暴/护盾/经济）。"""
    return _load_json(BALANCE_JSON)


class Gameplay(Scene):
    MAX_ENEMIES = 60
    EVOLUTIONS = ['radius', 'cap', 'wbc', 'speed', 'maxhp']
    WALL_T = 72          # 组织墙带视觉厚度（对齐 gen_walls.py / wall_*_top.png 高度）
    TITLE_SECONDS = 2.2  # 层际标题横幅时长（点击可跳过）
    # v3 §5.4：层际标题横幅只显示主标题，无副题
    LAYER_TITLES = {1: '肝脏·表面', 2: '肝脏·深层', 3: '肿瘤核心'}
    # 档案室（v3 §4）：宿主房 = 第 2 层随机一间普通房（66% 概率/局）
    ARCHIVE_PROB = 0.66
    ARCHIVE_HOST_CANDIDATES = (3, 4)
    # 四选一实物摆放：道具 → (家具边缘外公可达点, 家具名)——手术刀为隐藏项（双击主角×3）
    # v4 修正（2026-08-30）：pos 移到家具边缘外——家具碰撞会把玩家推出到离家具最近点
    # ≈ 玩家半径处，旧 pos 在矩形内部 → 床/衣柜的实物永远够不到（互动半径同样放宽到 125）
    ARCHIVE_SPOTS = [
        {'item': 'soup', 'pos': (650, 180), 'label': '书桌'},
        {'item': 'money', 'pos': (975, 480), 'label': '衣柜'},
        {'item': 'sweater', 'pos': (400, 482), 'label': '床'},
    ]
    # 阳光书房：室内区域（紧凑房间，四周厚墙）+ 家具碰撞矩形（床/衣柜/书桌）
    # 与 gen_bedroom.py 的 X0/Y0/X1/Y1 对齐
    ARCHIVE_RECT = (200, 110, 1080, 610)
    ARCHIVE_FURNITURE = [
        pygame.Rect(250, 330, 300, 190),    # 床（左）
        pygame.Rect(880, 320, 190, 210),    # 衣柜（右）
        pygame.Rect(490, 120, 320, 170),    # 书桌（上）
    ]
    # v4 §5.4 左半区（暮色书房）：旧书桌上的纸 + 家具碰撞（档案架/旧书桌）
    ARCHIVE_LEFT_SPOTS = [
        {'item': 'paper', 'pos': (640, 250), 'label': '旧书桌'},
    ]
    ARCHIVE_LEFT_FURNITURE = [
        pygame.Rect(150, 300, 180, 240),    # 档案架（左）
        pygame.Rect(480, 120, 320, 170),    # 旧书桌（上）
    ]

    def __init__(self, game, seed=None, meta_path=None):
        super().__init__(game)
        cx, cy = settings.WIDTH // 2, settings.HEIGHT // 2
        self.rng = RunRNG(seed)      # 每局独立随机源（内容生成可复现）
        self.run_seed = self.rng.seed
        self.audio = getattr(self.game, 'audio', None) or AudioBus()   # 共享总线（菜单/祭坛同一实例）
        self.audio.set_enabled(get_config()["sound_on"])   # 设置 → 音效开关
        self.items_data = load_items()
        self.story_data = load_story()
        self.balance = load_balance()
        self.buff_shop = load_buffs()
        self.enemy_projectiles = []
        self.poison_zones = []               # BOSS 三阶段场地毒区
        self.fx = FxManager()                # 战斗特效（对象池）
        self._synergy_cd = 0.0               # 协同提示音冷却
        self._deferred_pickups = []          # 宝箱掉落（延迟 1 帧生成，避免同帧误拾）
        self.meta_path = meta_path           # 测试可注入（隔离真实存档）
        meta = load_meta(self.meta_path)
        self.offering = meta['offering']         # 累计祭点
        self.next_run_buffs = meta['next_buffs']  # 已购、仅下一局生效的记忆类 buff
        self.memories = meta['memories']          # 分型牺牲史（祭坛脚注）
        self.learned_memories = meta['learned_memories']   # 已学过的记忆（Ⅱ 档解锁判定）
        self.boss_beaten_count = meta['boss_beaten_count']  # 击败 BOSS 次数（里程碑）
        self.pending_physical = list(meta['pending_physical'])  # 待注入开局的实物类
        self.fixed_slot_meta = meta['fixed_slot']  # 背包固定格跨局道具
        self.te2_seen = meta['te2_seen']           # TE2 是否已播过
        self.achievements = list(meta['achievements'])  # 成就解锁（v5 数据位）
        self.wbc_atk_bonus = {}                   # 本局进化/记忆：某类白细胞攻击加成
        self.run_atk_bonus = 0                   # 下一局 buff：全局白细胞攻击加成
        self._buffs_start_allies = []             # 记忆 buff：开局自带细胞（neutrophil/nk）

        self.player = Player(cx, cy)
        self.guide = GuideSystem()
        self._apply_next_buffs()
        self.allies = []        # 开局无细胞：初始房随机刷 4 个游离白细胞给玩家拾取
        self._spawn_start_allies()

        self.room = RoomManager(settings.WIDTH, settings.HEIGHT, rng=self.rng)
        self.roomflow = RoomFlow(self)   # 房间运行流（A3.2 外迁 systems/roomflow.py）
        self.current_layer, self.current_kind, self.enemies, free_wbc = self.room.spawn_room()
        self.room_obstacles = self.roomflow.build_obstacles()
        self.shop_here = self.room.roll_shop()   # 本房是否生成商店台（BOSS 前房必刷）
        self.shop_spot = self._shop_spot_pos()
        self.exit_open = False
        self.exit_kind = 'door'
        self.room_cleared = False
        self.exit_side = 'down'    # 前进方向：down=往下层 / right=同层平级（v3 §6）
        self.back_side = None      # 后退方向：up=回上层 / left=同层平级；None=无（初始房）
        self._entry_side = None    # 本房进入方向（出生点跟随：从哪个门进来，就在门旁）
        self._transit_dir = 1      # 本次过渡方向：1 前进 / -1 返回
        self.room_cache = {}       # 已离开房间的状态快照（index → snapshot）
        self.roomflow.apply_room_state()
        self.roomflow.compute_exit_sides()
        self.transition_phase = 'out'
        self.transition_t = 0.0
        self._title_banner_pending = False   # 层际标题横幅（进入新层/初始房后首间）
        self.shake_timer = 0.0
        self.shake_strength = 0.0
        self.floaters = []
        self.pickups = self._make_pickups(free_wbc)
        self.projectiles = []
        self.score = 0
        self.overlay = None          # 面板层（A2）：None / reward / evolve / shop / bag / story
        self.scene_state = 'combat'  # 场景层（A2）：combat / transition / death_flash / dead / ending / te

        # 本局成长
        self.run_offering = 0   # 本局通过白细胞死亡累计的祭点
        self.run_memories = {t: {'deaths': 0, 'kills': 0} for t in self.memories}
        self.run_mark_bonus = 0.0     # 记忆 buff：T 标记时间 +3s
        self.run_nk_cd_reduce = 0.0   # 记忆 buff：NK 爆发 CD −2s
        self.run_atk_bonus = 0
        self.xp = 0
        self.level = 1
        self.xp_next = self.balance['economy']['xp_next_factor']
        # v3 道具层：书包（每局重置）+ 装备/道具结算（A3.1 外迁 systems/equipment.py）
        self.backpack = Backpack()
        self._inject_run_bag()      # v4：固定格注入 + 待注入实物 + 钥匙合成检查
        self.bag_panel = BackpackPanel()
        self.bag_panel.layout(settings.WIDTH, settings.HEIGHT)
        self.equipment = Equipment(self)
        self.player.on_hit_cb = self.equipment.on_armor_hit   # 针织衣：直接攻击命中 → 扣耐久
        self.player.on_life_guard = self._reliquary_guard     # v5：战友的徽章锁血回调
        self._reliquary_used = False
        self.achievement_defs = None                          # 成就表惰性加载
        # 档案室（v3 §4.1 + v4 §5.3）：66% 判定宿主房；门状态机 none/live/visited/opened
        # [演示临时] 档案室必现：固定在第 2 间（教学房后第一间战斗房）；演示后改回随机 66% (ARCHIVE_HOST_CANDIDATES=(3,4))
        self._archive_host = 1
        self._archive_used = False
        self._archive_state = 'live' if self._archive_host is not None else 'none'
        self._archive_enter_side = 'right'   # 本次进档案室的目标半区（'right' 免费 / 'left' 钥匙）
        self.archive = ArchiveRoom(self)   # 阳光书房：状态与交互已外迁（修正清单 A1）
        self.world = WorldRenderer(self)   # 世界层渲染已外迁（A3.3）
        self.lights = LightRenderer(settings.WIDTH, settings.HEIGHT)  # 手术灯照明
        self.ending = EndingDirector(self)  # 结局/故事演出已外迁（A3.4）
        self.story = None                 # 获得横幅：{'id','data','chars','acc','speed'}

        self.discovered = set()
        self.show_bestiary = False
        self.bestiary = BestiaryPanel()
        self.bestiary.layout(settings.WIDTH, settings.HEIGHT)

        self.cardbar = CardBar(self.player, self.try_summon)
        self.cardbar.layout(settings.WIDTH, settings.HEIGHT)

        self.reward_panel = RewardPanel()
        self.reward_panel.layout(settings.WIDTH, settings.HEIGHT)
        self.evolve_panel = RewardPanel()
        self.evolve_panel.layout(settings.WIDTH, settings.HEIGHT)
        self.evolve_panel.title = "选择你的强化方向"
        self.shop_panel = ShopPanel(self.balance['economy']['shop_prices'])
        self.shop_panel.layout(settings.WIDTH, settings.HEIGHT)
        self.death_panel = DeathPanel()
        self.death_panel.layout(settings.WIDTH, settings.HEIGHT)
        self.reward_options = []
        self.evolution_options = []

        # v6 萤火虫（昏暗模式专属道具）：仅 dim 下按房 50% 刷新；捕捉/放置状态见更新与事件
        self.fireflies = self._spawn_fireflies()
        self.capture_panel = CapturePanel()
        self.capture_panel.layout(settings.WIDTH, settings.HEIGHT)
        self.capture_target = None      # 正在弹捕捉窗的萤火虫
        self.place_firefly_mode = False # 使用萤火虫后的「点地图放置」模式

        # 叙事/UI 状态
        self.heartbeat_timer = 0.0
        self._pulse = 0.0
        self.flash_timer = 0.0      # 死亡闪回计时
        self.ending_stage = 0       # 结尾演出阶段
        self._rage_tier = 0         # 残血狂暴当前档位（升档播音效用）

        # 叙事（《开头与结局设计.md》）：NE 残留 / 完美局 / TE
        self.wbc_deaths = 0         # 本局死亡白细胞数（NE 残留公式 D）
        self.perfect_ne_count = meta.get('perfect_ne_count', 0)  # 累计完美局次数（TE 触发）
        self.ending_residual = 0.0  # 通关时残留癌细胞百分比
        self.ending_perfect = False # 本局是否完美局（残留 < 0.1%）
        self._te_pending = False    # 本局通关是否触发 TE 追加演出
        self._te_shown = False
        self.te_timer = 0.0         # TE 打字机进度（从 0 递增）
        self._te_finished = False   # TE 文案是否全部显现

        # v4：钥匙 / BOSS 战后 / TE2（v4祭点层.md §4-§5）
        self._key_left_found_run = False    # 本局 1% 掉落是否已发生
        self._key_left_drop_in_room = False # 本房 1% 命中（宝箱附带钥匙）
        self._post_boss_hint = False        # BOSS 战后提示（右上「还有什么在等你」）
        self.boss_beaten = False            # 本局是否击败 BOSS（告别之门/钥匙）
        self.archive_left_read = False      # 本局是否读过档案室左半（TE2 flag）
        self._te2_pending = False           # 本局通关是否触发 TE2 追加演出
        self._te2_shown = False
        self.te2_timer = 0.0

        self.font = gfx.font(22, True)

    def _make_pickups(self, free_wbc_types):
        return [Pickup(*self._free_pickup_spot(), 'wbc', t)
                for t in free_wbc_types]

    def _free_pickup_spot(self):
        """房间内随机拾取点，但不得被障碍物吃掉（v6.1）。

        - 点与原逻辑同分布区域（160..W-160 水平、160..H-160 垂直）；
        - 逐点检查：拾取圆（Pickup.RADIUS + 玩家半径）与任一障碍实心圆重叠
          → 重新生成（最多 40 次，防极端布局死循环）；
        - 失败兜底：取最后一次生成的点（房间边界处的点仍有概率碰到障碍，
          但比「必然在障碍内部」好；正常布局 1-2 次即命中）。
        """
        keep = Pickup.RADIUS + self.player.radius + 2   # 余量：接触边界不算卡死
        for _ in range(40):
            x = self.rng.randint(160, settings.WIDTH - 160)
            y = self.rng.randint(160, settings.HEIGHT - 160)
            if self._spot_free(x, y, keep):
                return x, y
        return x, y

    def _spot_free(self, x, y, keep):
        for ob in self.room_obstacles:
            if ob.collide_circle(x, y, keep):
                return False
        return True

    # ---------- 萤火虫（v6：昏暗模式专属道具） ----------

    def _spawn_fireflies(self):
        """昏暗模式专属：每房 50% 概率刷 1 只萤火虫，停在随机障碍物顶部。

        独立随机源（run_seed + 房号）——不占用主 RunRNG 序列，房间/敌人/
        商店随机不受影响，同种子同房结果恒定。初始教学房（无障碍物）与
        档案室不刷；正常模式不刷（专属道具只属于昏暗模式）。
        """
        if get_config()["light_mode"] != "dim":
            return []
        if getattr(self, 'archive', None) is not None and self.archive.in_archive:
            return []
        rng = random.Random(f"firefly:{self.run_seed}:{self.room.index}")
        if rng.random() >= 0.5:
            return []
        pts = []
        for ob in self.room_obstacles:
            pts.extend(ob.perch_points())
        if not pts:
            return []
        x, y = rng.choice(pts)
        return [Firefly((x, y))]

    def _firefly_at(self, x, y):
        """点击命中：返回与点击点最近的停留萤火虫（perch 且未放置）。"""
        best, bd = None, CLICK_RADIUS * CLICK_RADIUS
        for f in self.fireflies:
            if f.state != 'perch' or f.placed:
                continue
            d = (f.x - x) ** 2 + (f.y - y) ** 2
            if d <= bd:
                best, bd = f, d
        return best

    def _begin_firefly_place(self):
        """使用萤火虫 → 进入放置模式：点地图一处，萤火虫从主角处飞过去。"""
        if self.backpack.count('firefly') <= 0:
            return False
        self.place_firefly_mode = True
        self._set_scene('combat')   # 关闭背包面板
        return True

    def _catch_firefly(self):
        """捕捉确认：入包成功 → 萤火虫从房间移除；书包满 → 提示并留在原地。"""
        f = self.capture_target
        self.capture_target = None
        self._set_scene('combat')
        if f is None or f not in self.fireflies:
            return
        if f.dist_to(self.player) > CAPTURE_RANGE:
            return   # 玩家走开了（弹窗暂停战斗不会发生，防御性检查）
        entry = self.items_data['firefly']
        if self.backpack.add('firefly', entry):
            self.fireflies.remove(f)
            self._add_floater(self.player.x, self.player.y - 44,
                              f"{entry['name']}已入包", (0xE8, 0xD8, 0x5C))
            self.audio.play('chime')
        else:
            self._add_floater(self.player.x, self.player.y - 44,
                              "书包已满！", (0xC9, 0xA2, 0x27))
            self.audio.play('click')

    def _place_firefly_at(self, x, y):
        """放置：消耗 1 只萤火虫，从主角处弧线飞往点击点，落地永久照亮。"""
        m = self.WALL_T + 24
        x = max(m, min(settings.WIDTH - m, x))
        y = max(m, min(settings.HEIGHT - m, y))
        if not self.backpack.use_one('firefly'):
            self.place_firefly_mode = False
            return
        f = Firefly((self.player.x, self.player.y))
        f.placed = True
        f.start_flight(x, y)
        self.fireflies.append(f)
        self.place_firefly_mode = False
        self._add_floater(self.player.x, self.player.y - 44,
                          "萤火虫飞了出去…", (0xE8, 0xD8, 0x5C))
        self.audio.play('pickup')

    # ---------- 房间布局 / 出口（A3.2：障碍构建/初始房覆写/出口方向已外迁 systems/roomflow.py） ----------

    def _portal_center(self, side):
        W, H = settings.WIDTH, settings.HEIGHT
        if self.archive.in_archive and side == 'left':
            # 档案室：出口位于室内区域左墙
            return (self.ARCHIVE_RECT[0] - 30, H // 2)
        t = self.WALL_T
        return {'down': (W // 2, H - t + 18), 'up': (W // 2, t - 14),
                'right': (W - t + 14, H // 2), 'left': (t - 14, H // 2)}[side]

    def _near_portal(self, side, r=45):
        px, py = self._portal_center(side)
        return (self.player.x - px) ** 2 + (self.player.y - py) ** 2 < r * r

    def _near_xy(self, x, y, r=45):
        return (self.player.x - x) ** 2 + (self.player.y - y) ** 2 < r * r

    def _place_player_at_entry(self, side):
        """出生点：穿过某扇门后，出现在该门对侧的门旁（向场内 95px）。side=None = 房间中心。

        白细胞跟班随主人一起进门：落到入口周围的阵型圈上（不会再从旧房坐标跑进来）。
        """
        if side is None:
            self.player.x, self.player.y = settings.WIDTH // 2, settings.HEIGHT // 2
        else:
            px, py = self._portal_center(side)
            dx, dy = {'right': (-95, 0), 'left': (95, 0),
                      'down': (0, -95), 'up': (0, 95)}[side]
            self.player.x, self.player.y = px + dx, py + dy
        for i, w in enumerate(self.allies):
            sx, sy = self.guide.formation_slot(i, len(self.allies))
            w.x, w.y = self.player.x + sx, self.player.y + sy

    def _leave_room(self, direction):
        """走进通道：快照当前房 → 淡出过渡。direction：1 前进 / -1 返回 / 2 进档案室 / -2 离档案室。"""
        if direction != -2:   # 离档案室不覆盖宿主房快照（档案室不再回访）
            self.room_cache[self.room.index] = self.roomflow.snapshot()
        self._transit_dir = direction
        self.transition_phase = 'out'
        self.transition_t = 0.45
        self.audio.play('door_open')
        self._set_scene('transition')

    # ---------- 档案室（v3 §4 阳光书房）----------
    # 状态与交互已外迁至 core/archive.py（ArchiveRoom，修正清单 A1）；
    # Gameplay 只保留：门控字段、侧门几何、快照交接与布局常量。

    def _archive_portal_center(self):
        """宿主房右侧墙上方：档案室侧门（单向进入，离开即封）。"""
        W = settings.WIDTH
        return (W - 34, 150)

    def _open_exit(self):
        """清房奖励/商店完成后：出口解锁，走进出口进下一房。"""
        self.exit_open = True
        self._set_scene('combat')

    def _clamp_entities(self):
        if self.archive.in_archive:      # 档案室：紧凑室内区域（厚墙约束）
            x0, y0, x1, y1 = self.ARCHIVE_RECT
            for e in self.enemies + self.allies + [self.player]:
                e.x = max(x0 + 8, min(x1 - 8, e.x))
                e.y = max(y0 + 8, min(y1 - 8, e.y))
            return
        m = self.WALL_T + 8   # 墙带内缘 48px：实体中心最多贴近内缘 8px（身体不压进墙）
        max_y = settings.HEIGHT - m
        for e in self.enemies + self.allies + [self.player]:
            e.x = max(m, min(settings.WIDTH - m, e.x))
            e.y = max(m, min(max_y, e.y))

    def _add_floater(self, x, y, amount, color=(0xFF, 0xDC, 0x5A)):
        self.floaters.append(FloatText(x, y, str(amount), color))

    def _shake(self, strength=7.0):
        self.shake_timer = 0.18
        self.shake_strength = strength

    def _shake_offset(self):
        if self.shake_timer > 0:
            s = int(self.shake_strength)
            return random.randint(-s, s), random.randint(-s, s)
        return 0, 0

    def _proj_hit_obstacle(self, proj):
        for ob in self.room_obstacles:
            if ob.blocks_point(proj.x, proj.y):
                return True
        return False

    # ---------- 祭点（meta 货币，v4：记忆类 + 实物类）----------

    def _settle_offering(self):
        """本局祭点并入累计并落盘（死亡/通关时调用）；分型牺牲史同步合并；祭点流水入库。"""
        gained = self.run_offering
        self.offering += gained
        for t, m in self.run_memories.items():
            self.memories[t]['deaths'] += m['deaths']
            self.memories[t]['kills'] += m['kills']
        save_meta(self.offering, self.next_run_buffs, self.meta_path,
                  memories=self.memories, learned_memories=self.learned_memories,
                  boss_beaten_count=self.boss_beaten_count,
                  pending_physical=self.pending_physical,
                  fixed_slot=self._fixed_export(),
                  te2_seen=self.te2_seen, achievements=self.achievements)
        if gained:
            dbwrite.record_offering(gained, "settle", self.offering)

    def _fixed_export(self):
        """背包格 0 → meta.fixed_slot（供结算时持久化）。"""
        return self.backpack.export_fixed()

    def _record_run(self, ending):
        """v5：一局战绩入库（异常兜底于 dbwrite）。ending: 'NE'|'TE'|'TE2'|'died'。"""
        dbwrite.record_run({
            "score": self.score,
            "layers": self.current_layer,
            "wbc_deaths": self.wbc_deaths,
            "residual": (self.ending_residual if ending != "died" else None),
            "ending": ending,
            "key_left_found": self._key_left_found_run,
            "archive_left_read": self.archive_left_read,
        })

    # ---------- v5 成就（仅「战友的徽章」） ----------

    def _load_achievement_defs(self):
        if self.achievement_defs is None:
            self.achievement_defs = load_achievements()
        return self.achievement_defs

    def _achievement_met(self, aid):
        return aid == 'reliquary' and self.perfect_ne_count >= 3

    def _check_achievements(self):
        """结算时成就判定（死亡/通关各一次）：新解锁 → meta + 库 + 横幅演出。"""
        for a in self._load_achievement_defs():
            aid = a['aid']
            if aid in self.achievements:
                continue
            if not self._achievement_met(aid):
                continue
            self.achievements.append(aid)
            save_meta(self.offering, self.next_run_buffs, self.meta_path,
                      achievements=self.achievements)
            dbwrite.unlock_achievement(aid)
            self._play_achievement_banner(aid)

    def _play_achievement_banner(self, aid):
        entry = self.story_data.get('achv_' + aid)
        if entry is None:
            return
        self.story = {'id': 'achv_' + aid, 'data': entry, 'chars': 0, 'acc': 0.0,
                      'speed': self.story_data.get('type_speed', 25)}
        self._set_overlay('story')
        self.audio.play('chime')

    def _reliquary_guard(self):
        """玩家 hp≤0 兜底（成就锁血）：减伤/盾全结算后触发，每局一次。"""
        if 'reliquary' not in self.achievements or self._reliquary_used:
            return False
        self._reliquary_used = True
        self._add_floater(self.player.x, self.player.y - 70,
                          "记忆挡下了这一击", (0xE9, 0xC4, 0x6A))
        self.audio.play('chime')
        return True

    def _memory_unlocked(self, item):
        """记忆条目是否已解锁（里程碑 + 本期已记住前置档——Ⅱ 档不能跳级）。"""
        u = item.get('unlock')
        if isinstance(u, dict) and u.get('milestone') == 'boss_beaten_1':
            if self.boss_beaten_count < 1:
                return False
        for req in item.get('requires', []):
            if req not in self.next_run_buffs:
                return False
        return True

    def _buy_buff(self, i):
        """记忆类购买（祭坛 / 死亡面板兼容入口）。解锁与余额检查通过 → 入下一局。"""
        item = self.buff_shop[i]
        if not self._memory_unlocked(item):
            return False
        if self.offering < item['cost']:
            return False
        self.offering -= item['cost']
        self.next_run_buffs.append(item['key'])
        if item['key'] not in self.learned_memories:
            self.learned_memories.append(item['key'])
        save_meta(self.offering, self.next_run_buffs, self.meta_path,
                  learned_memories=self.learned_memories)
        self.audio.play('shop_buy')   # 祭坛/死亡面板记忆购买（祭祀铃）
        return True

    def _apply_next_buffs(self):
        """应用「仅下一局」的记忆 buff（重开/首次加载时调用），应用后清空。"""
        self.run_atk_bonus = 0
        self._buffs_start_allies = []
        for key in self.next_run_buffs:
            if key == 'atk':
                self.run_atk_bonus += 2
            elif key == 'cards':
                for _ in range(2):
                    t = self.rng.choice(WBC_ORDER)
                    self.player.cards[t] = self.player.cards.get(t, 0) + 1
            elif key == 'radius':
                self.player.guide_radius += 40
            elif key == 'cap':
                self.player.wbc_cap += 1
            elif key == 'speed':
                self.player.speed += 20
            elif key == 'mem_neut_1':
                if 'mem_neut_2' not in self.next_run_buffs:  # Ⅱ 含Ⅰ（2只）→ Ⅰ 不额外加
                    self._buffs_start_allies.append('neutrophil')
            elif key == 'mem_neut_2':
                self._buffs_start_allies.append('neutrophil')  # 含Ⅰ档：共 2 只
                self._buffs_start_allies.append('neutrophil')
            elif key == 'mem_mac_1':
                self.player.max_hp += 10
            elif key == 'mem_mac_2':
                sc = self.balance['shield']
                self.player.shield = min(sc['max_cells'] * sc['cell_value'],
                                         self.player.shield + sc['cell_value'])
            elif key == 'mem_t_1':
                self.player.cards['t_cell'] = self.player.cards.get('t_cell', 0) + 1
            elif key == 'mem_t_2':
                self.run_mark_bonus = 3.0     # T 标记时间 +3s（cancer.mark 读取）
            elif key == 'mem_nk_1':
                if 'mem_nk_2' not in self.next_run_buffs:  # Ⅱ（−4s）含Ⅰ → 不叠加
                    self.run_nk_cd_reduce = max(self.run_nk_cd_reduce, 2.0)
            elif key == 'mem_nk_2':
                self.run_nk_cd_reduce = max(self.run_nk_cd_reduce, 4.0)  # 含Ⅰ档：−4s
        self.next_run_buffs = []
        save_meta(self.offering, self.next_run_buffs, self.meta_path,
                  learned_memories=self.learned_memories)

    def _spawn_start_allies(self):
        """记忆 buff「开局自带细胞」：在主角周围生成（施予全局/类型攻击加成）。"""
        for t in self._buffs_start_allies:
            ang = self.rng.uniform(0, math.tau)
            w = WBC(self.player.x + math.cos(ang) * 42,
                    self.player.y + math.sin(ang) * 42, t)
            w.atk += self.run_atk_bonus + self.wbc_atk_bonus.get(t, 0)
            self.allies.append(w)

    # ---------- v4 钥匙 / 背包注入 / 档案室左半 ----------

    def _inject_run_bag(self):
        """开局背包注入（v4 §4.5）：固定格 → 待注入实物 → 钥匙合成检查 → 清空 pending。"""
        self.backpack.restore_fixed(self.fixed_slot_meta)
        for item_id in list(self.pending_physical):
            if item_id in self.items_data:
                self.backpack.add(item_id, self.items_data[item_id])
        self.pending_physical = []
        self._check_key_synth(startup=True)

    def _has_key(self, item_id):
        """钥匙是否在背包（含固定格）。"""
        return self.backpack.has_key(item_id)

    def _grant_key_right(self):
        """BOSS 清房 100% 掉落右半钥匙：自动入包；全满 → 固定格（空时）；否则留地面。"""
        entry = self.items_data['key_right']
        if self.backpack.add('key_right', entry):
            self._add_floater(self.player.x, self.player.y - 60,
                              "右半钥匙！", (0xE9, 0xC4, 0x6A))
            self.audio.play('chime')
            self._check_key_synth()
        elif not self._has_key('key_right'):
            # 背包全满：固定格空 → 强制入固定格；否则生成地面拾取物（不消失）
            if self.backpack.fixed_slot is None:
                self.backpack.insert_slot(self.backpack.FIXED_INDEX, 'key_right', entry)
                self._add_floater(self.player.x, self.player.y - 60,
                                  "右半钥匙（放进留念格）", (0xE9, 0xC4, 0x6A))
                self.audio.play('chime')
                self._check_key_synth()
            else:
                self.pickups.append(Pickup(settings.WIDTH // 2, settings.HEIGHT // 2 + 60,
                                           'key_right'))

    def _check_key_synth(self, startup=False):
        """双半同在 → 自动合成完整钥匙（落格：固定格 > 左半格 > 右半格）+ 演出。"""
        li = self.backpack.find('key_left')
        ri = self.backpack.find('key_right')
        if li is None or ri is None:
            return False
        target = 0 if (li == 0 or ri == 0) else li
        self.backpack.remove_slot(max(li, ri))
        self.backpack.remove_slot(min(li, ri))
        self.backpack.insert_slot(target if target not in (li, ri) else min(li, ri),
                                  'key_full', self.items_data['key_full'])
        self._add_floater(self.player.x, self.player.y - 60,
                          "两半钥匙…合上了！", (0xF4, 0xE0, 0xA0))
        self.audio.play('chime')
        # 获得横幅（开局注入时也播：开场即"记忆"演出）
        gp_story = {'id': 'key_full', 'data': self.story_data['key_full'],
                    'chars': 0, 'acc': 0.0,
                    'speed': self.story_data.get('type_speed', 25)}
        self.story = gp_story
        self._set_overlay('story')
        return True

    def _try_open_archive_left(self):
        """档案室门（visited 态）按 E：持完整钥匙 → 消耗 + 开门进左半区。"""
        if self._archive_state != 'visited' or self.archive.in_archive:
            return False
        apx, apy = self._archive_portal_center()
        if not self._near_xy(apx, apy, 60):
            return False
        i = self.backpack.find('key_full')
        if i is None:
            # 差分提示（v4 §5.3 visited 分支）
            if self._has_key('key_left'):
                msg = "锁孔透出银光——还差另一半。也许，它在最深处。"
            elif self._has_key('key_right'):
                msg = "你握着的那半对不上……它缺了另一半。"
            else:
                msg = "门上刻着一整把钥匙的形状……"
            self._add_floater(self.player.x, self.player.y - 64, msg,
                              (0x9C, 0x96, 0x88))
            return False
        # 开门：消耗 key_full → 进左半区
        self.backpack.remove_slot(i)
        self._archive_state = 'opened'
        self._archive_enter_side = 'left'
        self._leave_room(2)
        return True

    def _open_altar(self):
        """死亡结算 → 祭坛（switch 替换当前场景）：关闭/回主菜单直接回主菜单。
        （不再 push 回死亡面板 —— 死亡页背后仍是房间画面，玩家会误以为回到了游戏内。）"""
        from .altar import AltarScene
        self.game.scenes.switch(AltarScene(self.game, to_back=False))

    def _reload_meta_into_run(self):
        """重开前重读 meta（祭坛可能已消费/兑换）：刷新余额、pending、固定格等。"""
        meta = load_meta(self.meta_path)
        self.offering = meta['offering']
        self.next_run_buffs = meta['next_buffs']
        self.memories = meta['memories']
        self.learned_memories = meta['learned_memories']
        self.boss_beaten_count = meta['boss_beaten_count']
        self.pending_physical = list(meta['pending_physical'])
        self.fixed_slot_meta = meta['fixed_slot']
        self.te2_seen = meta['te2_seen']
        self.achievements = list(meta['achievements'])

    # ---------- 状态（A2 修正清单：场景层 + 面板层二分） ----------

    @property
    def state(self):
        """兼容出口：由场景层 scene_state + 面板层 overlay 合成旧字符串（smoke_test/外部脚本）。"""
        if self.overlay is not None:
            return self.overlay
        if self.scene_state == 'combat':
            return 'playing'
        return self.scene_state

    @state.setter
    def state(self, v):
        """兼容入口：旧字符串写回分解到两层。内部代码请直接用 _set_scene/_set_overlay。"""
        if v in ('reward', 'evolve', 'shop', 'bag', 'story'):
            self._set_overlay(v)
        elif v == 'playing':
            self._set_scene('combat')
        else:
            self._set_scene(v)

    def _set_scene(self, v):
        """切场景层状态（combat/transition/death_flash/dead/ending/te），并关闭面板层。"""
        self.overlay = None
        self.scene_state = v

    def _set_overlay(self, v):
        """开面板层（reward/evolve/shop/bag/story），场景层保持 combat。"""
        self.scene_state = 'combat'
        self.overlay = v

    # ---------- 输入 ----------

    def handle_events(self, events):
        for e in events:
            # 获得横幅：点击/空格/回车 = 补全 → 再按关闭；右键跳过整段
            if self.overlay == 'story':
                if (e.type == pygame.MOUSEBUTTONDOWN
                        or (e.type == pygame.KEYDOWN
                            and e.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_ESCAPE))):
                    s = self.story
                    if s is not None:
                        if s['chars'] < len(s['data']['text']):
                            s['chars'] = len(s['data']['text'])
                        else:
                            self.story = None
                            self.audio.play('click')
                            self._set_scene('combat')
                continue
            # 层际标题横幅：点击/空格/回车跳过，其余事件忽略
            if self.scene_state == 'transition' and self.transition_phase == 'title':
                if (e.type == pygame.MOUSEBUTTONDOWN
                        or (e.type == pygame.KEYDOWN
                            and e.key in (pygame.K_SPACE, pygame.K_RETURN))):
                    self.audio.play('click')
                    self.transition_t = min(self.transition_t, 0.12)
                continue
            if e.type == pygame.KEYDOWN and e.key == pygame.K_TAB \
                    and self.scene_state == 'combat' and self.overlay is None:
                self.show_bestiary = not self.show_bestiary
                self.audio.play('click')
                continue
            if self.overlay == 'bag':     # 书包打开：松开 Q 关闭，点击弹窗交互
                if e.type == pygame.KEYUP and e.key == pygame.K_q:
                    self._set_scene('combat')
                    self.bag_panel.close_popup()
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    self.bag_panel.close_popup()
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    action = self.bag_panel.handle_click(e.pos, self.backpack)
                    if action:
                        self.equipment.handle_bag_action(action)
                elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                    action = self.bag_panel.handle_release(e.pos, self.backpack)
                    if action:
                        self.equipment.handle_bag_action(action)
                continue
            if self.overlay == 'capture':  # 萤火虫捕捉确认窗：捕捉 / 取消
                if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    self.capture_target = None
                    self._set_scene('combat')
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    action = self.capture_panel.handle_click(e.pos)
                    if action == 'capture' and self.capture_target is not None:
                        self._catch_firefly()
                    elif action == 'cancel':
                        self.capture_target = None
                        self._set_scene('combat')
                        self.audio.play('click')
                continue
            if self.show_bestiary:
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.bestiary.handle_click(e.pos, self.discovered)
                continue
            if self.overlay == 'reward':
                if e.type == pygame.KEYDOWN and e.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    idx = (pygame.K_1, pygame.K_2, pygame.K_3).index(e.key)
                    if idx < len(self.reward_options):
                        self._apply_reward(self.reward_options[idx])
                        self._after_reward()
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.audio.play('click')
                    opt = self.reward_panel.handle_click(e.pos)
                    if opt:
                        self._apply_reward(opt)
                        self._after_reward()
                continue
            if self.overlay == 'evolve':
                if e.type == pygame.KEYDOWN and e.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    idx = (pygame.K_1, pygame.K_2, pygame.K_3).index(e.key)
                    if idx < len(self.evolution_options):
                        self.audio.play('click')
                        self._apply_evolution(self.evolution_options[idx])
                        self._set_scene('combat')
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.audio.play('click')
                    opt = self.evolve_panel.handle_click(e.pos)
                    if opt:
                        self._apply_evolution(opt)
                        self._set_scene('combat')
                continue
            if self.overlay == 'shop':
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.audio.play('click')
                    action = self.shop_panel.handle_click(e.pos)
                    if action == 'leave':
                        self._set_scene('combat')   # 房内商店台：买完回到房间，出口已在清房后开启
                    elif action and action.startswith('buy:'):
                        self._try_buy(action.split(':')[1])
                continue
            if self.scene_state == 'dead':
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.audio.play('click')
                    action = self.death_panel.handle_click(e.pos)
                    if action == 'restart':
                        self._restart_run()
                    elif action == 'altar':
                        self._open_altar()
                continue
            if self.scene_state == 'te2':
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.ending.finish_te2()
                continue
            if self.scene_state == 'ending':
                if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    self.game.running = False
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.ending.advance()
                continue
            if self.scene_state == 'te':
                if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    self.ending.finish_te()
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if not self._te_finished:
                        self.te_timer = self.ending.te_typing_time()
                        self._te_finished = True
                    else:
                        self.ending.finish_te()
                continue
            if self.scene_state == 'combat' and self.overlay is None:
                if self.place_firefly_mode:   # 使用萤火虫后：点地图放置，右键/Esc 取消
                    if (e.type == pygame.MOUSEBUTTONDOWN and e.button == 1
                            and not self.cardbar.handle_click(e.pos)):
                        self._place_firefly_at(*e.pos)
                    elif (e.type == pygame.MOUSEBUTTONDOWN and e.button == 3) \
                            or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                        self.place_firefly_mode = False
                        self.audio.play('click')
                    continue
                if e.type == pygame.KEYDOWN and e.key == pygame.K_q:
                    self._set_overlay('bag')     # 按住 Q 打开书包（松开关闭）
                    self.bag_panel.close_popup()
                    self.audio.play('click')
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_e:
                    if self._can_open_shop():   # 房内商店台：清房后靠近按 E
                        self._set_overlay('shop')
                    elif self._try_open_archive_left():   # v4：档案室锁门（visited 态）
                        pass
                    elif self.archive.in_archive:   # 档案室：靠近家具按 E 拿取礼物
                        self.archive.interact()
                elif e.type == pygame.KEYDOWN and e.key in (pygame.K_1, pygame.K_2,
                                                            pygame.K_3, pygame.K_4):
                    # 快捷键直接召唤：1 中性 / 2 巨噬 / 3 T / 4 NK
                    idx = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4).index(e.key)
                    if idx < len(WBC_ORDER):
                        self.try_summon(WBC_ORDER[idx])
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if self.cardbar.handle_click(e.pos):
                        continue
                    # v6 萤火虫：点击停留的萤火虫 → 捕捉确认窗（仅昏暗模式会刷）
                    if not self.archive.in_archive:
                        ff = self._firefly_at(*e.pos)
                        if ff is not None:
                            if ff.in_range:
                                self.audio.play('click')
                                self.capture_target = ff
                                self._set_overlay('capture')
                            else:
                                # 太远：走过去再捕捉（点击点即移动目标）
                                self._add_floater(self.player.x, self.player.y - 60,
                                                  "离萤火虫太远了…", (0x9C, 0x96, 0x88))
                                self.player.set_target(GroundTarget(ff.x, ff.y))
                            continue
                    self.archive.check_double_click(e.pos)   # 档案室：主角体内的手术刀
                    self._set_target_at(*e.pos)
    def _set_target_at(self, x, y):
        target = None
        for c in self.enemies:
            if getattr(c, 'disguised', False):
                continue
            if (c.x - x) ** 2 + (c.y - y) ** 2 <= (c.radius + 12) ** 2:
                target = c
                break
        if target is None:
            target = GroundTarget(x, y)
        self.player.set_target(target)
        self._trigger_nk_burst()

    def _trigger_nk_burst(self):
        """NK 标定瞬间 AoE 爆发。狂暴档位放大范围/伤害、档3 击退；免疫风暴与狂暴乘算。"""
        bs = self.balance['rage']['burst_skills']
        fx_cfg = self.balance.get('fx', {})
        burst_cfg = fx_cfg.get('burst', {})
        synergy_color = tuple(fx_cfg.get('synergy_color', (120, 230, 255)))
        particle_color = tuple(burst_cfg.get('particle_color', (235, 235, 235)))
        for wbc in self.allies:
            if (wbc.wbc_type == 'nk' and wbc.burst_cd_left <= 0
                    and wbc.dist_to(self.player) <= self.player.guide_radius):
                wbc.trigger_burst()
                if self.run_nk_cd_reduce > 0:      # v4 记忆「决断的瞬间」：爆发 CD −2s
                    wbc.burst_cd_left = max(0.0, wbc.burst_cd_left - self.run_nk_cd_reduce)
                self.audio.play('purge')
                radius = wbc.burst_radius
                dmg_mult = 1.0 + wbc.rage_bonus
                knockback = 0.0
                mark_mult = wbc.mark_multiplier
                if wbc.rage_tier >= 2:
                    radius *= bs['nk']['tier2']['radius_mult']
                    dmg_mult *= bs['nk']['tier2']['damage_mult']
                if wbc.rage_tier >= 3:
                    knockback = bs['nk']['tier3']['knockback']
                    mark_mult = bs['t_cell']['tier3']['mark_multiplier']
                # —— 爆发特效：冲击波（档位配色）+ 碎屑粒子 + 档3 全屏红闪 ——
                if wbc.rage_tier >= 3:
                    wave_color = (0xFF, 0x50, 0x50)
                elif wbc.rage_tier >= 2:
                    wave_color = (0x80, 0xC8, 0xFF)
                else:
                    wave_color = (0xFF, 0xFF, 0xFF)
                self.fx.spawn_shockwave(wbc.x, wbc.y,
                                        burst_cfg.get('shockwave_radius', 90),
                                        wave_color)
                self.fx.burst_particles(wbc.x, wbc.y, particle_color,
                                        count=burst_cfg.get('particle_count', 10),
                                        speed=burst_cfg.get('particle_speed', 170),
                                        rng=self.rng)
                if wbc.rage_tier >= 3:
                    self.fx.spawn_red_flash()
                for e in self.enemies:
                    if e.dist_to(wbc) <= radius:
                        dmg = wbc.atk * wbc.atk_mult * dmg_mult
                        if e.marked:  # 免疫风暴：T 标记 × 狂暴倍率 乘算
                            dmg *= mark_mult
                            # 协同可视化：命中标记敌人 → 专属青色白闪 + 提示音
                            self.fx.spawn_flash(e.x, e.y,
                                                burst_cfg.get('flash_radius', 26),
                                                synergy_color)
                            if self._synergy_cd <= 0:
                                self.audio.play('synergy')
                                self._synergy_cd = 0.25
                        else:
                            self.fx.spawn_flash(e.x, e.y,
                                                burst_cfg.get('flash_radius', 26))
                        e.take_damage(dmg)
                        if knockback > 0.0 and e.alive:
                            dx, dy = e.x - wbc.x, e.y - wbc.y
                            d = (dx * dx + dy * dy) ** 0.5 or 1.0
                            e.vx += dx / d * knockback
                            e.vy += dy / d * knockback
                        e.on_hit_by(wbc)
                        if not e.alive:
                            wbc.kills += 1

    def _update_rage(self):
        """残血狂暴：血量越低白细胞攻击越强（档位+线性插值），升档播提示音。"""
        config = self.balance['rage']
        ratio = self.player.hp / max(1, self.player.max_hp)
        bonus = rage_bonus(ratio, config)
        tier = rage_tier(ratio, config)
        if tier > self._rage_tier:
            self.audio.play('rage%d' % tier)
        self._rage_tier = tier
        for w in self.allies:
            w.rage_bonus = bonus
            w.rage_tier = tier

    def _update_auras(self):
        """召唤精英加攻光环：为范围内敌人提供攻击加成（结算在 systems/combat）。"""
        bonus = aura_bonus_map(self.enemies)
        for e in self.enemies:
            e.atk_aura_bonus = bonus.get(id(e), 0)

    def _apply_shield_breaks(self):
        """护盾精英破盾瞬间：范围震爆（伤害 + 击退，结算在 systems/combat）。"""
        hits = list(shield_break_hits(self.enemies, self.allies + [self.player]))
        if hits:
            self.audio.play('burst', throttle=0.15)   # 破盾震爆（节流防连爆刷屏）
        for _c, w, dmg, (nx, ny) in hits:
            w.take_damage(dmg)
            w.vx += nx * 80
            w.vy += ny * 80

    def try_summon(self, wbc_type):
        p = self.player
        if p.cards.get(wbc_type, 0) <= 0:
            return False
        if len(self.allies) >= p.wbc_cap:
            return False
        p.cards[wbc_type] -= 1
        ang = self.rng.uniform(0, math.tau)
        w = WBC(p.x + math.cos(ang) * 42, p.y + math.sin(ang) * 42, wbc_type)
        w.atk += self.run_atk_bonus + self.wbc_atk_bonus.get(wbc_type, 0)
        w.atk_mult = self.items_data['vaccine']['effect']['atk_mult'] if self.equipment.boost_timer > 0 else 1.0
        self.allies.append(w)
        self.audio.play('click')   # 卡牌点击/快捷键召唤的 UI 反馈
        return True

    # ---------- 成长逻辑 ----------

    def _generate_rewards(self):
        wtype = self.rng.choice(WBC_ORDER)
        card_opt = {'label': f'获得 2 张{WBC_NAMES[wtype]}', 'kind': 'card',
                    'wbc_type': wtype, 'n': 2}
        boost = self.rng.choice(['radius', 'cap', 'speed', 'maxhp'])
        if boost == 'radius':
            stat_opt = {'label': '引导范围 +40', 'kind': 'stat', 'stat': 'radius', 'val': 40}
        elif boost == 'cap':
            stat_opt = {'label': '白细胞上限 +1', 'kind': 'stat', 'stat': 'cap', 'val': 1}
        elif boost == 'speed':
            stat_opt = {'label': '移动速度 +20', 'kind': 'stat', 'stat': 'speed', 'val': 20}
        else:
            stat_opt = {'label': '最大血量 +15 并回满', 'kind': 'stat', 'stat': 'maxhp', 'val': 15}
        # 道具奖励（v3：kind 即 items.json 的钥匙 id，预防针 / 止痛药，单一数据源）
        item = self.rng.choice(['vaccine', 'pain'])
        dv = self.items_data['vaccine']['effect']
        dp = self.items_data['pain']['effect']
        if item == 'vaccine':
            item_opt = {'label': f'预防针（攻×{dv["atk_mult"]} {int(dv["duration"])}秒）',
                        'kind': 'vaccine'}
        else:
            pct = int((1 - dp['dmg_mult']) * 100)
            item_opt = {'label': f'止痛药（受伤-{pct}% {int(dp["duration"])}秒）',
                        'kind': 'pain'}
        return [card_opt, stat_opt, item_opt]

    def _apply_reward(self, opt):
        self.audio.play('pickup')   # 三选一奖励获得
        if opt['kind'] == 'card':
            self.player.cards[opt['wbc_type']] = self.player.cards.get(opt['wbc_type'], 0) + opt['n']
        elif opt['kind'] == 'stat':
            s = opt['stat']
            if s == 'radius':
                self.player.guide_radius += opt['val']
            elif s == 'cap':
                self.player.wbc_cap += opt['val']
            elif s == 'speed':
                self.player.speed += opt['val']
            elif s == 'maxhp':
                self.player.max_hp += opt['val']
                self.player.hp = self.player.max_hp
        elif opt['kind'] in ('vaccine', 'pain'):
            # 道具奖励 → 进书包（kind 即 items.json 钥匙 id）
            if self.backpack.add(opt['kind'], self.items_data[opt['kind']]):
                self._add_floater(self.player.x, self.player.y - 24,
                                  "已放入书包", (0x7F, 0xD8, 0xC4))
            else:
                self._add_floater(self.player.x, self.player.y - 44,
                                  "书包已满！", (0xC9, 0xA2, 0x27))

    def _after_reward(self):
        # 商店改为房内台子（本房生成时判定），清房后靠近按 E 打开，不再过关随机弹店
        self._open_exit()

    def _can_open_shop(self):
        if not self.shop_here:   # [演示临时] 不清房也能开商店（演示后改回 room_cleared and shop_here）
            return False
        x, y = self.shop_spot
        return (self.player.x - x) ** 2 + (self.player.y - y) ** 2 < 80 ** 2

    def _shop_spot_pos(self):
        """房内商店台落点：从左下角起选一个不与障碍物重叠的角落。"""
        for x, y in [(150, 618), (1126, 618), (150, 148), (1126, 148)]:
            rect = pygame.Rect(x - 46, y - 44, 92, 56)
            if not any(ob.overlaps_rect(rect) for ob in self.room_obstacles):
                return (x, y)
        return (150, 618)

    def _try_buy(self, wbc_type):
        price = self.balance['economy']['shop_prices'][wbc_type]
        if self.score < price:
            return False
        self.score -= price
        self.player.cards[wbc_type] = self.player.cards.get(wbc_type, 0) + 1
        self.audio.play('shop_buy')
        return True

    def _on_room_cleared(self):
        self.room_cleared = True
        # v3 掉落：每房清房必出宝箱，件数按房型（普通 1 / 精英 2 / BOSS 3）
        if self.current_kind in ('normal', 'elite', 'boss'):
            self.pickups.append(Pickup(settings.WIDTH // 2, settings.HEIGHT // 2, 'chest'))
        # v4 §4.1 左半钥匙 1% 掉落：普通/精英房清房 roll 一次，每局至多 1 把（BOSS 房除外）
        if self.current_kind in ('normal', 'elite') and not self._key_left_found_run:
            self._key_left_found_run = True
            if self.rng.random() < 0.01:
                if self._has_key('key_left'):
                    self.run_offering += 40      # 已持有：补偿「记忆碎片」
                    self._add_floater(self.player.x, self.player.y - 60,
                                      "记忆碎片 +40 祭点", (0xE9, 0xC4, 0x6A))
                    dbwrite.record_offering(40, "memory_frag",
                                            self.offering + self.run_offering)
                else:
                    self._key_left_drop_in_room = True
        # v4 §4.2/§5.4 BOSS 战后状态：必掉右半钥匙 + 告别之门（结算点迁移到进门）
        if self.current_kind == 'boss':
            self.boss_beaten = True
            self.boss_beaten_count += 1
            self._post_boss_hint = True
            self._grant_key_right()
            self.audio.play('victory')   # 击败 BOSS：柔和主和弦
            save_meta(self.offering, self.next_run_buffs, self.meta_path,
                      boss_beaten_count=self.boss_beaten_count)
        self.reward_options = self._generate_rewards()
        self.reward_panel.set_options(self.reward_options)
        self._set_overlay('reward')

    # ---------- 进化 ----------

    def _check_level_up(self):
        if self.xp >= self.xp_next:
            self._on_level_up()
            return True
        return False

    def _on_level_up(self):
        self.level += 1
        self.xp -= self.xp_next
        self.xp_next = self.balance['economy']['xp_next_factor'] * self.level
        self.evolution_options = self._generate_evolutions()
        self.evolve_panel.set_options(self.evolution_options)
        self.audio.play('levelup')
        self._set_overlay('evolve')

    def _generate_evolutions(self):
        pool = list(self.EVOLUTIONS)
        self.rng.shuffle(pool)
        opts = []
        for k in pool[:3]:
            if k == 'radius':
                opts.append({'label': '引导范围 +40', 'kind': 'radius'})
            elif k == 'cap':
                opts.append({'label': '白细胞上限 +1', 'kind': 'cap'})
            elif k == 'wbc':
                t = self.rng.choice(WBC_ORDER)
                opts.append({'label': f'强化{WBC_NAMES[t]}（攻击+2）', 'kind': 'wbc', 'wbc_type': t})
            elif k == 'speed':
                opts.append({'label': '移动速度 +20', 'kind': 'speed'})
            elif k == 'maxhp':
                opts.append({'label': '最大血量 +15 回满', 'kind': 'maxhp'})
        return opts

    def _apply_evolution(self, opt):
        k = opt['kind']
        if k == 'radius':
            self.player.guide_radius += 40
        elif k == 'cap':
            self.player.wbc_cap += 1
        elif k == 'wbc':
            t = opt['wbc_type']
            self.wbc_atk_bonus[t] = self.wbc_atk_bonus.get(t, 0) + 2
            for w in self.allies:
                if w.wbc_type == t:
                    w.atk += 2
        elif k == 'speed':
            self.player.speed += 20
        elif k == 'maxhp':
            self.player.max_hp += 15
            self.player.hp = self.player.max_hp

    # ---------- 道具（A3.1：使用/书包动作/穿脱/耐久/环绕命中已外迁 systems/equipment.py） ----------

    def _draw_scalpel(self, world):
        """手术刀绘制接线：状态在 self.equipment，渲染在 ui/scalpel.py（只读）。"""
        slot = self.backpack.active_slot('scalpel')
        if slot is None:
            return
        entry = self.items_data['scalpel']
        draw_scalpel(world, self.player.x, self.player.y, self.equipment.scalpel_angle,
                     entry['blades'], entry['orbit_radius'], entry['icon'])

    # ---------- 拾取 / 结算 ----------

    def _collect_pickups(self):
        for p in self.pickups:
            if not p.collected and p.dist_to(self.player) <= p.radius + self.player.radius:
                if self._on_pickup(p):     # 书包满时红细胞留在原地
                    p.collected = True
        self.pickups = [p for p in self.pickups if not p.collected]
        if self._deferred_pickups:     # 宝箱掉落的红细胞道具：延迟 1 帧进场
            self.pickups.extend(self._deferred_pickups)
            self._deferred_pickups = []

    def _on_pickup(self, p):
        if p.kind == 'wbc':
            self.player.cards[p.wbc_type] = self.player.cards.get(p.wbc_type, 0) + 1
            self.audio.play('pickup')
        elif p.kind == 'chest':
            # v3 掉落池：普通 1 / 精英 2 / BOSS 3 件随机消耗品（可重复），不再掉细胞卡
            n = {'normal': 1, 'elite': 2, 'boss': 3}.get(self.current_kind, 1)
            for _ in range(n):
                kind = self.rng.choices(('rbc', 'pain', 'vaccine'),
                                        weights=(60, 25, 15))[0]
                self._deferred_pickups.append(Pickup(
                    p.x + self.rng.uniform(-24, 24),
                    p.y + self.rng.uniform(-24, 24), kind))
            self.audio.play('chest')   # 开宝箱：木盖 + 金币
            # v4 §4.1：本房 1% 命中 → 宝箱附带左半钥匙
            if getattr(self, '_key_left_drop_in_room', False):
                self._key_left_drop_in_room = False
                self._deferred_pickups.append(Pickup(
                    p.x + self.rng.uniform(-30, 30),
                    p.y + self.rng.uniform(-30, 30), 'key_left'))
        elif p.kind in ('rbc', 'pain', 'vaccine', 'scalpel'):
            # 消耗品/装备拾取 → 进书包（满格留在原地）；手术刀触发获得横幅
            entry = self.items_data[p.kind]
            if self.backpack.add(p.kind, entry):
                self._add_floater(p.x, p.y - 20, f"{entry['name']}+1", (0xE8, 0x6A, 0x6A))
                self.audio.play('pickup')
                if p.kind == 'scalpel':
                    self.archive.start_story('scalpel')
            else:
                self._add_floater(self.player.x, self.player.y - 44,
                                  "书包已满！", (0xC9, 0xA2, 0x27))
                return False     # 留在原地，腾出格子后再捡
        elif p.kind in ('key_left', 'key_right'):
            # v4 钥匙：进书包（占格）；另一半已在 → 自动合成
            entry = self.items_data[p.kind]
            if self.backpack.add(p.kind, entry):
                self._add_floater(p.x, p.y - 20, f"{entry['name']} 获得", (0xE9, 0xC4, 0x6A))
                self.audio.play('chime')
                self._check_key_synth()
            else:
                self._add_floater(self.player.x, self.player.y - 44,
                                  "书包已满！", (0xC9, 0xA2, 0x27))
                return False
        elif p.kind == 'shield':
            sc = self.balance['shield']
            self.player.shield = min(sc['max_cells'] * sc['cell_value'],
                                     self.player.shield + sc['cell_value'])
            self._add_floater(p.x, p.y - 20, "护盾+", (0x7A, 0xC4, 0xFF))
            self.audio.play('pickup')
        return True

    def _cleanup_and_score(self):
        for c in self.enemies:
            if not c.alive:
                self.score += c.score
                self.xp += c.score
        for a in self.allies:
            if not a.alive:
                self.run_offering += a.kills  # 祭点 = 该白细胞本局击杀数
                self.run_memories[a.wbc_type]['deaths'] += 1
                self.run_memories[a.wbc_type]['kills'] += a.kills
                self.wbc_deaths += 1          # 叙事：本局死亡白细胞数（NE 残留 D）
        self.enemies = [c for c in self.enemies if c.alive]
        self.allies = [a for a in self.allies if a.alive]

    def _residual_percent(self, d):
        """NE 残留癌细胞百分比（《开头与结局设计.md》§2.2 分段线性公式，封顶 10%）。

        d <= 9  : d × 0.01%（完美局门槛：残留 < 0.1%）
        d >= 10 : 0.09% + (d - 9) × 0.1%，封顶 10%
        """
        if d <= 9:
            return d * 0.01
        return min(10.0, 0.09 + (d - 9) * 0.1)

    # ---------- 更新 ----------

    def update(self, dt):
        for c in self.enemies:
            if c.awake:
                self.discovered.add(type(c).__name__.lower())

        # 获得横幅：逐字演出（暂停战斗；点击补全/关闭见 handle_events）
        if self.overlay == 'story':
            s = self.story
            if s is not None:
                text = s['data']['text']
                if s['chars'] < len(text):
                    s['acc'] += dt * s['speed']
                    s['chars'] = min(len(text), int(s['acc']))
            return

        # 死亡闪回：短暂停顿后进入结算
        if self.scene_state == 'death_flash':
            self.flash_timer -= dt
            if self.flash_timer <= 0:
                self._settle_offering()
                self._check_achievements()
                self._record_run("died")
                self._set_scene('dead')
            return

        # TE 真结局逐字演出：打字机进度推进，全部显现后等待点击
        if self.scene_state == 'te':
            if not self._te_finished:
                self.te_timer += dt
                if self.te_timer >= self.ending.te_typing_time():
                    self.te_timer = self.ending.te_typing_time()
                    self._te_finished = True
            return

        # TE2 真结局追加演出（v4：档案室左半线）
        if self.scene_state == 'te2':
            self.te2_timer -= dt
            if self.te2_timer <= 0:
                self.ending.finish_te2()
            return

        # 房间过渡：淡出 → 进下一房/回上一房 →（层际标题横幅）→ 淡入
        if self.scene_state == 'transition':
            self.transition_t -= dt
            if self.transition_t <= 0:
                if self.transition_phase == 'out':
                    if self._transit_dir > 0 and self._transit_dir != 2:
                        self.roomflow.advance()
                        if self.scene_state == 'ending':
                            return
                        if self._title_banner_pending:   # v3 §5.4：层际标题横幅（暂停演出）
                            self._title_banner_pending = False
                            self.transition_phase = 'title'
                            self.transition_t = self.TITLE_SECONDS
                        else:
                            self.transition_phase = 'in'
                            self.transition_t = 0.4
                    elif self._transit_dir == -1:
                        self.roomflow.go_back()
                        self.transition_phase = 'in'
                        self.transition_t = 0.4
                    elif self._transit_dir == 2:      # 进入档案室（标题横幅「档案室」；v4 分左右半）
                        if self._archive_enter_side == 'left':
                            self.archive.enter_left()
                        else:
                            self.archive.enter()
                        self.transition_phase = 'title'
                        self.transition_t = self.TITLE_SECONDS
                    else:                              # -2：离开档案室（侧门永久封闭）
                        self.archive.leave()
                        self.transition_phase = 'in'
                        self.transition_t = 0.4
                elif self.transition_phase == 'title':
                    self._set_scene('combat')   # 布幡直接切入房间中央：结束后无需再淡入
                else:
                    self.audio.play('door_close')   # 门在身后合上（淡入完成）
                    self._set_scene('combat')
            return

        if self.show_bestiary or self.overlay in ('reward', 'shop', 'evolve', 'bag',
                                                  'capture') \
                or self.scene_state != 'combat':
            return  # 面板层 / 非战斗场景层，暂停战斗

        # 心跳：血量越低跳得越快（视觉脉冲 + 合成音效）
        self.heartbeat_timer -= dt
        if self.heartbeat_timer <= 0:
            self.heartbeat_timer = self._heartbeat_interval()
            self._pulse = 1.0
        self._pulse = max(0.0, self._pulse - dt * 2.5)
        self.audio.heartbeat(self.player.hp / max(1, self.player.max_hp), dt)
        # 特效：飘字 / 震屏
        for f in self.floaters:
            f.update(dt)
        self.floaters = [f for f in self.floaters if f.alive]
        self.shake_timer = max(0.0, self.shake_timer - dt)

        keys = pygame.key.get_pressed()
        self.player.handle_input(keys)
        self.player.update(dt)
        self.equipment.update(dt)       # 手术刀环绕命中 + 三 buff 倒计时（装备激活时）

        self._update_rage()
        self._synergy_cd = max(0.0, self._synergy_cd - dt)
        self.fx.update(dt)

        # 引导
        for i, wbc in enumerate(self.allies):
            slot = self.guide.formation_slot(i, len(self.allies))
            self.guide.update_wbc(self.player, wbc, slot, self.projectiles)
            wbc.update(dt)
        for wbc in self.allies:
            wbc.auto_mark(self.enemies, self.projectiles)

        # 敌人
        for c in self.enemies:
            c.try_wake(self.player)
            if c.awake:
                c.target = c.pick_target(self.allies, self.player)
                c.chase(c.target)
            else:
                c.vx = c.vy = 0.0
            c.update(dt)
            self.enemy_projectiles += c.take_barrage(self.player)
            if getattr(c, 'phase_changed', False):      # BOSS 阶段切换提示
                self.audio.play('phase')
                c.phase_changed = False
            if getattr(c, 'take_poison_ready', None) and c.take_poison_ready():
                pc = c.poison_cfg
                zx = c.x + random.uniform(-30, 30)
                zy = c.y + random.uniform(-30, 30)
                self.poison_zones.append(PoisonZone(
                    zx, zy, pc['radius'], pc['duration'], pc['damage_per_sec']))
                # 生成溅射：酸性绿闪 + 冲击波提示
                self.fx.spawn_flash(zx, zy, 46, (0x9A, 0xE0, 0x4A))
                self.fx.spawn_shockwave(zx, zy, pc['radius'] * 0.7, (0x7A, 0xD0, 0x3A))
                self.audio.play('poison')
        self._update_auras()
        self._apply_shield_breaks()
        hp_before = self.player.hp
        for c in self.enemies:
            if c.awake:
                c.try_attack_target(c.target)
        if self.player.hp < hp_before:
            self._add_floater(self.player.x, self.player.y - 34,
                              f"-{int(hp_before - self.player.hp)}", (0xFF, 0x6A, 0x6A))
            self._shake(7.0)
            self.audio.play('hurt', throttle=0.12)   # 玩家受伤：下滑闷响（非打击音）

        # 场地毒区：持续伤害（对敌人与主角，结算在 systems/combat）
        hp_poison = self.player.hp
        self.poison_zones = resolve_zone_damage(
            self.poison_zones, self.enemies + [self.player], dt)
        if self.player.hp < hp_poison:
            self._add_floater(self.player.x, self.player.y - 34,
                              f"-{int(hp_poison - self.player.hp)}", (0x6A, 0xE0, 0x4A))
            self.audio.play('poison')

        resolve_overlaps(self.enemies + self.allies)
        resolve_overlaps(self.enemies + [self.player])
        resolve_obstacle_collisions(self.enemies + self.allies + [self.player],
                                    self.room_obstacles)
        self._clamp_entities()
        if self.archive.in_archive:
            self.archive.sync_collision()   # 阳光书房：家具碰撞
            self.archive.update(dt)         # 阳光尘埃：缓漂 + 循环

        # 投射物
        for proj in self.projectiles:
            proj.update(dt)
            hit = False
            for e in self.enemies:
                if e in proj._hit:
                    continue  # 穿透弹已结算过的敌人不再重复
                if circles_overlap(proj, e):
                    e.take_damage(proj.damage)
                    self._add_floater(e.x, e.y - 18, int(proj.damage))
                    self.audio.play('hit', throttle=0.05)   # 弹道命中（节流防刷屏）
                    if proj.owner is not None:
                        e.on_hit_by(proj.owner)
                        if proj.owner.wbc_type == 't_cell':
                            e.mark()  # T 细胞投射物：揭穿伪装 + 免疫风暴标记
                            if getattr(self, 'run_mark_bonus', 0) > 0:
                                e._mark_timer += self.run_mark_bonus  # v4 记忆「看见伪装」
                        if not e.alive:
                            proj.owner.kills += 1
                    proj._hit.add(e)
                    if proj.pierce > 0:
                        proj.pierce -= 1
                        hit = True
                        break  # 穿透：继续飞行，后续帧结算下一目标
                    proj.alive = False
                    hit = True
                    break
            if not hit and self._proj_hit_obstacle(proj):
                proj.alive = False
        self.projectiles = [p for p in self.projectiles if p.alive]

        # 敌方弹幕：巨噬肉盾挡弹 → 玩家受伤 → 撞障碍消散
        # T 细胞 / NK 细胞免疫弹幕伤害：不参与碰撞检测，弹幕直接穿过
        for p in self.enemy_projectiles:
            p.update(dt)
            tank = None
            for wbc in self.allies:
                if (wbc.wbc_type == 'macrophage' and wbc.alive
                        and circles_overlap(p, wbc)):
                    tank = wbc
                    break
            if tank is not None:
                # 巨噬细胞肉盾：替主角承受弹幕（坦克减伤 dmg_mult=0.5）
                dmg = p.damage * tank.dmg_mult
                tank.take_damage(dmg)
                self._add_floater(tank.x, tank.y - 20, f"-{int(dmg)}", (0xFF, 0xD0, 0x70))
                p.alive = False
            elif circles_overlap(p, self.player):
                # 减伤顺序（v3 §2.6）：弹道伤害 −护甲 → ×止痛药 → 盾 → 血
                dmg = p.damage
                if self.player.armor > 0:
                    dmg = max(0.0, dmg - self.player.armor)
                    self.equipment.on_armor_hit()
                dmg *= self.player.dmg_mult
                self.player.try_contact_damage(dmg)
                self._add_floater(self.player.x, self.player.y - 34,
                                  f"-{int(dmg)}", (0xFF, 0x6A, 0x6A))
                self._shake(5.0)
                p.alive = False
            elif self._proj_hit_obstacle(p):
                p.alive = False
        self.enemy_projectiles = [p for p in self.enemy_projectiles if p.alive]

        # 近战
        for wbc, cancer in contact_pairs(self.allies, self.enemies):
            dmg = wbc.try_attack(cancer)
            if dmg:
                self._add_floater(cancer.x, cancer.y - 18, int(dmg))
                self.audio.play('hit', throttle=0.06)   # 近战命中（节流防刷屏）

        # 分裂 / 召唤
        if len(self.enemies) < self.MAX_ENEMIES:
            offspring = []
            for c in self.enemies:
                if c.take_split():
                    offspring.append(c.spawn_offspring())
            self.enemies += offspring
        if len(self.enemies) < self.MAX_ENEMIES:
            spawned = []
            for c in self.enemies:
                if hasattr(c, 'take_summon') and c.take_summon():
                    spawned.append(Cancer(c.x + 48, c.y))
                if hasattr(c, 'take_boss_split') and c.take_boss_split():
                    spawned.append(self._spawn_boss_offspring(c))
            self.enemies += spawned

        self._collect_pickups()
        self._cleanup_and_score()

        # 萤火虫：停留/飞行、6 秒捕捉窗口（离开范围重置；超时飞往别处）
        for f in self.fireflies:
            f.update(dt, self.player, self.room_obstacles)

        # 玩家死亡 → 闪回 → 结算
        if not self.player.alive:
            self.flash_timer = 2.0
            self._set_scene('death_flash')
            self.audio.play('alarm')
            return
        # 升级检查
        if self.xp >= self.xp_next:
            self._on_level_up()
            return
        # 房间清空 → 三选一（每房只触发一次）
        if not self.enemies and not self.room_cleared:
            self._on_room_cleared()
            return

        # 通道：前进门（清房后开，层际=下洞 / 同层=右侧平级）+ 返回口（始终可走）
        # 档案室内不走常规前进/返回（由下方 -2 分支处理离开）
        if self.exit_open and not self.archive.in_archive and self._near_portal(self.exit_side):
            self._leave_room(1)
            return
        if self.back_side and self._near_portal(self.back_side):
            self._leave_room(-1)
            return
        # 档案室（v4 §5.3）：live 态清房后侧门开放（免费进入一次）；visited 态按 E 交互（_try_open_archive_left）
        # 距离 60：与 _try_open_archive_left 一致——墙带钳制（WALL_T+8）后玩家最远
        # 到 x=1200，而侧门在 x=1246（W-34），45 判定永远差 1px（回归：6186f81 墙加厚）
        if (not self.archive.in_archive and self._archive_state == 'live'
                and self.room.index == self._archive_host
                and self._near_xy(*self._archive_portal_center(), 60)):
            self._archive_enter_side = 'right'
            self._leave_room(2)
            return
        if self.archive.in_archive and self.exit_open and self._near_portal('left'):
            self._leave_room(-2)
            return

    def _spawn_boss_offspring(self, boss):
        """BOSS 分裂体：一律召唤「精英残片」（小型狂暴精英，敌方贴图明确、无伪装）。
        节奏随阶段加快（enemies.json boss_split_intervals：6s→4s→3s）。"""
        return EliteFragment(boss.x + 72, boss.y)

    def _restart_run(self):
        cx, cy = settings.WIDTH // 2, settings.HEIGHT // 2
        # 重开用「同种子 +1」：可复现且保证新鲜
        self.run_seed += 1
        self.rng = RunRNG(self.run_seed)
        self.enemy_projectiles = []
        self._reload_meta_into_run()   # v4：祭坛可能已消费/兑换 → 重读 meta
        self.player = Player(cx, cy)
        self.guide = GuideSystem()
        self.wbc_atk_bonus = {}        # 本局进化/记忆：类型攻击加成（先清零再应用 buff）
        self.run_atk_bonus = 0
        self._apply_next_buffs()
        self.allies = []        # 开局无细胞：初始房随机刷 4 个游离白细胞给玩家拾取
        self._spawn_start_allies()
        self.room = RoomManager(settings.WIDTH, settings.HEIGHT, rng=self.rng)
        self.roomflow = RoomFlow(self)   # 房间运行流（A3.2 外迁 systems/roomflow.py）
        self.current_layer, self.current_kind, self.enemies, free_wbc = self.room.spawn_room()
        self.room_obstacles = self.roomflow.build_obstacles()
        self.shop_here = self.room.roll_shop()   # 本房是否生成商店台（BOSS 前房必刷）
        self.shop_spot = self._shop_spot_pos()
        self.fireflies = self._spawn_fireflies()
        self.capture_target = None
        self.place_firefly_mode = False
        self.exit_open = True    # [演示临时] 出口常开：不清房也能前进（演示后改回 False）
        self.exit_kind = 'door'
        self.room_cleared = False
        self.exit_side = 'down'    # 前进方向：down=往下层 / right=同层平级（v3 §6）
        self.back_side = None      # 后退方向：up=回上层 / left=同层平级；None=无（初始房）
        self._entry_side = None    # 本房进入方向（出生点跟随：从哪个门进来，就在门旁）
        self._transit_dir = 1      # 本次过渡方向：1 前进 / -1 返回
        self.room_cache = {}       # 已离开房间的状态快照（index → snapshot）
        self.roomflow.apply_room_state()
        self.roomflow.compute_exit_sides()
        self.transition_phase = 'out'
        self.transition_t = 0.0
        self._title_banner_pending = False   # 层际标题横幅（进入新层/初始房后首间）
        self.shake_timer = 0.0
        self.shake_strength = 0.0
        self.floaters = []
        self.pickups = self._make_pickups(free_wbc)
        self.projectiles = []
        self.score = 0
        self.run_offering = 0
        self.run_memories = {t: {'deaths': 0, 'kills': 0} for t in self.memories}
        self.run_mark_bonus = 0.0
        self.run_nk_cd_reduce = 0.0
        self.wbc_deaths = 0          # 重开重置叙事统计
        self.xp = 0
        self.level = 1
        self.xp_next = self.balance['economy']['xp_next_factor']
        self.backpack = Backpack()        # v3：书包每局重置
        self._inject_run_bag()            # v4：固定格 + pending 实物 + 钥匙合成
        self.equipment = Equipment(self)  # 装备/道具结算随重开一并重置
        self.player.on_hit_cb = self.equipment.on_armor_hit
        self.player.on_life_guard = self._reliquary_guard
        self._reliquary_used = False
        # [演示临时] 档案室必现：固定在第 2 间（教学房后第一间战斗房）；演示后改回随机 66% (ARCHIVE_HOST_CANDIDATES=(3,4))
        self._archive_host = 1
        self._archive_used = False
        self._archive_state = 'live' if self._archive_host is not None else 'none'
        self._archive_enter_side = 'right'
        self._key_left_found_run = False
        self._key_left_drop_in_room = False
        self._post_boss_hint = False
        self.boss_beaten = False
        self.archive_left_read = False
        self._te_pending = False
        self._te_shown = False
        self.te_timer = 0.0
        self._te_finished = False
        self._te2_pending = False
        self._te2_shown = False
        self.archive = ArchiveRoom(self)   # 档案室状态随重开一并重置
        self.world = WorldRenderer(self)   # 渲染缓存随重开一并重置
        self.ending = EndingDirector(self)
        self.story = None
        self._set_scene('combat')
        if self.story is not None:        # 开局钥匙合成演出（_inject_run_bag 设置，防被上面清掉）
            self._set_overlay('story')
        self.cardbar = CardBar(self.player, self.try_summon)
        self.cardbar.layout(settings.WIDTH, settings.HEIGHT)

    # ---------- 渲染 ----------

    def render(self, screen):
        # ---- 世界层（带震屏偏移）----
        world = getattr(self, '_world', None)
        if world is None:
            world = pygame.Surface((settings.WIDTH, settings.HEIGHT))
            self._world = world
        self.world.draw_background(world)
        for ob in self.room_obstacles:
            ob.draw_under(world)          # 坏死堆/地面血管/拱桥投影墩座（实体之下）
        self.world.draw_exit(world)
        self.world.draw_shop_stand(world)
        self._draw_guide_ring(world)
        for p in self.pickups:
            p.draw(world)
        for wbc in self.allies:
            wbc.draw(world)
        for c in self.enemies:
            c.draw(world)
        for z in self.poison_zones:
            z.draw(world)
        for c in self.enemies:
            if getattr(c, 'marked', False):     # 免疫风暴：标记可见化
                draw_mark_ring(world, c.x, c.y, c.radius, self.fx.time())
        for proj in self.projectiles:
            proj.draw(world)
        for p in self.enemy_projectiles:
            p.draw(world)
        for f in self.floaters:
            f.draw(world)
        self.player.draw(world)
        self._draw_scalpel(world)      # 手术刀：环绕刀刃（实体之上）
        for ob in self.room_obstacles:
            ob.draw_over(world)           # 拱桥管身（实体之上：钻过时被管身遮住）
        for f in self.fireflies:          # 萤火虫：悬在障碍物顶部（世界层，随灯光变暗）
            f.draw(world)
        self._draw_target(world)

        self.fx.draw_world(world)

        # 手术灯光照：暗遮罩叠加在世界内容之上（初始房/档案室为亮厅，战斗房四周渐暗）。
        # 设置「正常模式」= 去除灯光渲染（无黑暗、无打光），直接保留原色世界。
        if get_config()["light_mode"] == "dim":
            if self.archive.in_archive:
                dark = 130        # 阳光书房：明亮
            elif self.room.index == 0:
                dark = 115        # 初始教学房：轻微变暗，蚀刻说明仍可读
            else:
                dark = 210        # 战斗房：中央灯圈亮、四周渐暗（暖光叠加提亮）
            self.lights.sync(self.room.index, dark)
            halo = None
            halos = []
            if not self.archive.in_archive:
                halo = (self.player.x, self.player.y, self.player.guide_radius)
                # 萤火虫：照亮范围与主角光环相当（FIREFLY_HALO_RADIUS）
                for f in self.fireflies:
                    halos.append((f.x, f.y, FIREFLY_HALO_RADIUS))
            self.lights.draw(world, halo, halos)

        ox, oy = self._shake_offset()
        screen.fill(settings.BG_LAYER2)
        screen.blit(world, (ox, oy))
        self.fx.draw_screen(screen)   # 全屏红闪（UI 层之下、世界之上）

        # ---- UI 层（不抖）----
        self._draw_hud(screen)
        if self.overlay == 'reward':
            self.reward_panel.draw(screen)
        elif self.overlay == 'evolve':
            self.evolve_panel.draw(screen)
        elif self.overlay == 'shop':
            self.shop_panel.draw(screen, self.score, self.player.cards)
        elif self.overlay == 'bag':
            blocked = {}
            if self.player.hp >= self.player.max_hp:
                for iid in ('rbc', 'soup'):
                    if self.backpack.count(iid):
                        blocked[iid] = '生命值已满'
            self.bag_panel.draw(screen, self.backpack, self.items_data, blocked)
        elif self.overlay == 'capture':
            entry = self.items_data['firefly']
            self.capture_panel.draw(screen, entry)
        elif self.overlay == 'story':
            self.ending.draw_story(screen)
        elif self.scene_state == 'ending':
            self.ending.draw_ending(screen)
        elif self.scene_state == 'te':
            self.ending.draw_true_ending(screen)
        elif self.scene_state == 'te2':
            self.ending.draw_true_ending2(screen)
        elif self.scene_state == 'death_flash':
            self.ending.draw_death_flash(screen)
        elif self.scene_state == 'dead':
            self.death_panel.draw(screen, self.score, self.level,
                                  self.offering, self.run_offering)
        elif self.scene_state == 'transition':
            self.world.draw_transition(screen)
        if self.show_bestiary:
            self.bestiary.draw(screen, self.discovered)
        # v6 放置模式：瞄准圈随鼠标 + 顶部提示（光晕半径 = 萤火虫照亮范围）
        if self.place_firefly_mode and self.scene_state == 'combat':
            mx, my = pygame.mouse.get_pos()
            pygame.draw.circle(screen, (0xE8, 0xD8, 0x5C),
                               (mx, my), FIREFLY_HALO_RADIUS, 2)
            pygame.draw.circle(screen, (0xE8, 0xD8, 0x5C), (mx, my), 10, 1)
            hint = gfx.font(20, True).render("点击地图放置萤火虫（右键取消）", True,
                                             (0xFF, 0xE9, 0xA0))
            screen.blit(hint, hint.get_rect(center=(settings.WIDTH // 2, 70)))
        self.ending.draw_pulse(screen)

    def _heartbeat_interval(self):
        ratio = self.player.hp / max(1, self.player.max_hp)
        return 0.45 + 0.75 * ratio  # 满血 ~1.2s，濒死 ~0.45s

    # 兼容引用：NE 文案单一来源在 core/ending.py（smoke_test 读 len(ENDING_STAGES)）
    ENDING_STAGES = ENDING_STAGES

    def _draw_guide_ring(self, screen):
        r = int(self.player.guide_radius)
        img = gfx.load_ui('hud_guide_ring.png', (r * 2, r * 2))
        screen.blit(img, img.get_rect(center=(int(self.player.x), int(self.player.y))))

    def _draw_target(self, screen):
        t = self.player.target
        if t is None:
            return
        img = gfx.load_ui('hud_target_highlight.png', (78, 78))
        screen.blit(img, img.get_rect(center=(int(t.x), int(t.y))))

    def _panel(self, screen, x, y, w, h, radius=10):
        pygame.draw.rect(screen, (0x12, 0x0F, 0x0C), (x, y, w, h), border_radius=radius)
        pygame.draw.rect(screen, (0x7A, 0x6A, 0x4F), (x, y, w, h), 2, border_radius=radius)

    def _draw_boss_bar(self, screen):
        boss = next((c for c in self.enemies if type(c).__name__ == 'BossCore'), None)
        if boss is None:
            return
        w, h = 640, 40
        x = settings.WIDTH // 2 - w // 2
        y = 88
        pygame.draw.rect(screen, (0x12, 0x0F, 0x0C), (x, y, w, h), border_radius=10)
        pygame.draw.rect(screen, (0x7A, 0x6A, 0x4F), (x, y, w, h), 3, border_radius=10)
        name = gfx.font(18, True).render("癌变核心", True, settings.UI_TEXT)
        screen.blit(name, (x + 12, y + h // 2 - name.get_height() // 2))
        bx0, bx1 = x + 110, x + w - 14
        pygame.draw.rect(screen, (0x3B, 0x1A, 0x16), (bx0, y + 10, bx1 - bx0, h - 20), border_radius=6)
        ratio = boss.hp / max(1, boss.max_hp)
        pygame.draw.rect(screen, (0xD3, 0x2A, 0x2A),
                         (bx0 + 2, y + 12, max(1, int((bx1 - bx0 - 4) * ratio)), h - 24), border_radius=5)

    def _draw_hud(self, screen):
        # ---- 左上：分段血条面板 ----
        bar_x, bar_y, bar_w, bar_h = 16, 16, 290, 56
        self._panel(screen, bar_x, bar_y, bar_w, bar_h)
        seg_n = 10
        ratio = self.player.hp / max(1, self.player.max_hp)
        filled = int(seg_n * ratio)
        pad = 10
        inner = pygame.Rect(bar_x + pad, bar_y + pad, bar_w - 2 * pad, bar_h - 2 * pad)
        pygame.draw.rect(screen, (0x3B, 0x1A, 0x16), inner, border_radius=6)
        # 红条分段：高度给下方护盾蓝条留一行（4px），不再与蓝条重叠
        seg_h = inner.h - 7
        seg_w = (inner.w - (seg_n - 1) * 3) / seg_n
        for i in range(seg_n):
            x = inner.x + i * (seg_w + 3)
            if i < filled:
                pygame.draw.rect(screen, (0xD3, 0x2A, 0x2A), (x, inner.y, seg_w, seg_h), border_radius=4)
            else:
                pygame.draw.rect(screen, (0x6E, 0x14, 0x14), (x, inner.y, seg_w, seg_h), border_radius=4)
        hp_text = gfx.font(20, True).render(f"{int(self.player.hp)}/{self.player.max_hp}", True, settings.UI_TEXT)
        screen.blit(hp_text, (bar_x + bar_w - hp_text.get_width() - 12, bar_y + 18))
        # 护盾格：蓝条（红条下方独立一行，随护盾量填充）
        if self.player.shield > 0:
            sc = self.balance['shield']
            ratio = min(1.0, self.player.shield / (sc['max_cells'] * sc['cell_value']))
            sy = inner.y + inner.h - 4
            pygame.draw.rect(screen, (0x1A, 0x2A, 0x40), (inner.x, sy, inner.w, 3), border_radius=2)
            pygame.draw.rect(screen, (0x4A, 0xA8, 0xFF),
                             (inner.x, sy, max(1, int(inner.w * ratio)), 3), border_radius=2)

        # ---- 左上：三行（同为 18px · UI_TEXT 色）----
        # 经验行：Lvx 与 0/x 只隔 2 个字符的宽度
        lv = gfx.font(18).render(f"Lv{self.level}", True, settings.UI_TEXT)
        screen.blit(lv, (bar_x, bar_y + bar_h + 6))
        xp = gfx.font(18).render(f"{self.xp}/{self.xp_next}", True, settings.UI_TEXT)
        screen.blit(xp, (bar_x + lv.get_width() + 22, bar_y + bar_h + 6))
        # 祭点行（经验行与背包行中间）
        offer = gfx.font(18).render(f"本局祭点 +{self.run_offering}", True, settings.UI_TEXT)
        screen.blit(offer, (bar_x, bar_y + bar_h + 30))
        # v4 钥匙槽：紧贴祭点行文本右侧（图标+名称紧凑排列；无图标时程序化占位）
        kx = bar_x + offer.get_width() + 20
        key_cols = (('key_left', '银钥', (0xC0, 0xC8, 0xD4)),
                    ('key_right', '金钥', (0xE9, 0xC4, 0x6A)))
        for kid, col, colr in key_cols:
            if not self._has_key(kid):
                continue
            ic = gfx.load_icon_safe(self.items_data[kid]['icon'], 20)
            if ic is not None:
                screen.blit(ic, (kx, bar_y + bar_h + 31))
            else:
                pygame.draw.circle(screen, colr, (kx + 10, bar_y + bar_h + 41), 9, 2)
            t = gfx.font(13, True).render(col, True, settings.UI_TEXT)
            screen.blit(t, (kx + 24, bar_y + bar_h + 34))
            kx += 24 + t.get_width() + 12
        # v4 完整钥匙（合成后显示，紧随其后）
        if self._has_key('key_full'):
            ic = gfx.load_icon_safe(self.items_data['key_full']['icon'], 22)
            if ic is not None:
                screen.blit(ic, (kx, bar_y + bar_h + 30))
            else:
                pygame.draw.circle(screen, (0xF4, 0xE0, 0xA0), (kx + 11, bar_y + bar_h + 41), 10, 2)
            t = gfx.font(13, True).render("完整", True, settings.UI_TEXT)
            screen.blit(t, (kx + 26, bar_y + bar_h + 34))
            kx += 26 + t.get_width() + 16  # 与装备耐久留 16px 空隙
        # 装备耐久指示（与钥匙同行；避免压在书包提示文字上）
        ex = kx
        for iid in ('sweater', 'scalpel'):
            s = self.backpack.active_slot(iid)
            if s is None:
                continue
            ic = gfx.load_icon_safe(self.items_data[iid]['icon'], 18)
            if ic is not None:
                screen.blit(ic, (ex, bar_y + bar_h + 31))
            dtxt = gfx.font(14, True).render(f"{s['dur']}/{s['dur_max']}", True,
                                             (0x4A, 0xC4, 0x58) if s['dur'] > s['dur_max'] * 0.34
                                             else (0xC8, 0x5A, 0x3A))
            screen.blit(dtxt, (ex + 22, bar_y + bar_h + 34))
            ex += 22 + dtxt.get_width() + 8  # 多件装备之间 8px 空隙
        # 背包行（装备耐久已上移到钥匙行，这里仅显示背包图标 + 总数 + 提示）
        draw_bag_hud(screen, bar_x + 2, bar_y + bar_h + 54, self.backpack)
        buff = ""
        if self.equipment.boost_timer > 0:
            buff += f"预防{self.equipment.boost_timer:.0f}s "
        if self.equipment.pain_timer > 0:
            buff += f"止痛{self.equipment.pain_timer:.0f}s "
        if self.equipment.soup_regen_timer > 0:
            buff += f"暖心{self.equipment.soup_regen_timer:.0f}s"
        buff_y = bar_y + bar_h + 82
        if buff:
            b = gfx.font(18).render(buff, True, (0x7F, 0xD8, 0xC4))
            screen.blit(b, (bar_x, buff_y))
        if self._rage_tier > 0:
            ratio = self.player.hp / max(1, self.player.max_hp)
            bonus = rage_bonus(ratio, self.balance['rage'])
            label = {1: '狂暴Ⅰ', 2: '狂暴Ⅱ', 3: '狂暴Ⅲ', 4: '狂暴Ⅳ'}[self._rage_tier]
            rt = gfx.font(18, True).render(f"{label} 攻×{1 + bonus:.2f}", True, (0xFF, 0x7A, 0x5A))
            screen.blit(rt, (bar_x, buff_y + (24 if buff else 0)))

        # ---- 顶部中间：层数进度面板 ----
        layer_names = {1: '肝脏·表面', 2: '肝脏·深层', 3: '肿瘤核心'}
        layer_name = layer_names.get(self.current_layer, '')
        prog = pygame.Rect(settings.WIDTH // 2 - 170, 16, 340, 60)
        self._panel(screen, prog.x, prog.y, prog.w, prog.h)
        name_t = gfx.font(20, True).render(layer_name, True, settings.UI_TEXT)
        screen.blit(name_t, name_t.get_rect(center=(prog.centerx, prog.y + 18)))
        cnt_t = gfx.font(18).render(f"{self.room.index + 1}/{len(self.room.rooms)}", True, (0x9C, 0x96, 0x88))
        screen.blit(cnt_t, cnt_t.get_rect(midright=(prog.right - 14, prog.y + 18)))
        dot_y = prog.y + 42
        n_rooms = len(self.room.rooms)
        for i in range(n_rooms):
            x = prog.x + 24 + i * ((prog.w - 48) / max(1, n_rooms - 1))
            done = i <= self.room.index
            pygame.draw.circle(screen, (0xC9, 0xA2, 0x27) if done else (0x5C, 0x5C, 0x5C),
                               (int(x), dot_y), 6)
            pygame.draw.circle(screen, (0, 0, 0), (int(x), dot_y), 6, 1)

        # ---- 底部：卡牌栏 + 右下积分面板 ----
        self.cardbar.draw(screen)
        sw, sh = 152, 56
        sx0 = settings.WIDTH - sw - 20
        sy0 = settings.HEIGHT - sh - 16
        self._panel(screen, sx0, sy0, sw, sh)
        coin = gfx.load('coin_score.png', (24, 24), subdir='ui/icons')
        screen.blit(coin, (sx0 + 10, sy0 + (sh - 24) // 2))
        sc_l = gfx.font(15).render("积分", True, (0x9C, 0x96, 0x88))
        screen.blit(sc_l, (sx0 + 42, sy0 + sh // 2 - sc_l.get_height() // 2))
        # 数字居中（左右都能容纳多位数增长）
        num_zone = pygame.Rect(sx0 + 42, sy0, sw - 50, sh)
        sc_n = gfx.font(24, True).render(str(self.score), True, (0xE9, 0xC4, 0x6A))
        screen.blit(sc_n, sc_n.get_rect(center=num_zone.center))

        # ---- 右下（积分栏左侧）：残留癌细胞计数面板（等高、布局同积分栏）----
        cw, ch = 148, 56
        c_y = settings.HEIGHT - ch - 16
        cx0 = sx0 - 24 - cw                      # 积分栏左侧，间距与原边距相当
        self._panel(screen, cx0, c_y, cw, ch)
        icon = gfx.load('enemy_cancer_48.png', (24, 24))   # 与积分图标同尺寸
        screen.blit(icon, (cx0 + 10, c_y + (ch - 24) // 2))
        # 两行文本（行间水平居中，位于图标右侧）：残留 / 癌细胞
        l1 = gfx.font(13).render("残留", True, (0x9C, 0x96, 0x88))
        l2 = gfx.font(13).render("癌细胞", True, (0x9C, 0x96, 0x88))
        txt_axis = cx0 + 10 + 24 + 8 + max(l1.get_width(), l2.get_width()) / 2
        screen.blit(l1, l1.get_rect(midtop=(txt_axis, c_y + 10)))
        screen.blit(l2, l2.get_rect(midtop=(txt_axis, c_y + 28)))
        # 数字：文字右侧，字号与积分相同、颜色保持红
        num_zone = pygame.Rect(cx0 + cw - 56, c_y, 48, ch)
        num_t = gfx.font(24, True).render(str(len(self.enemies)), True, (0xD3, 0x2A, 0x2A))
        screen.blit(num_t, num_t.get_rect(center=num_zone.center))
        # v4 BOSS 战后提示：「回去看看」钩子（仅一次）
        if getattr(self, '_post_boss_hint', False) and not self.archive.in_archive:
            hint = gfx.font(14).render("似乎有什么在等你回去……", True, (0xC9, 0xA2, 0x27))
            screen.blit(hint, hint.get_rect(midtop=(cx0 + cw // 2, c_y + ch + 6)))

        # ---- BOSS 血条 ----
        self._draw_boss_bar(screen)
