"""敌人系统：数值由 data/enemies.json 按类名驱动；类字段保留为 seed 快照。

- 小怪 Cancer：睡眠/唤醒、睡眠态分裂、仇恨系统（嘲讽巨噬 > 反击仇恨 > 玩家）
- 变异 Variant：伪装成宿主细胞，T 细胞标记后才能被集火（标定）
- 精英/ BOSS：不分裂（已成熟），各有特殊机制；狂暴精英与 BOSS 有弹幕
"""
import json
import math
import os
import random

import pygame

import gfx
import paths

from .entity import Entity
from .enemy_projectile import EnemyProjectile

ENEMIES_JSON = os.path.join(paths.data_dir(), "enemies.json")

_ENEMIES = None


def load_enemies(path=None):
    global _ENEMIES
    if _ENEMIES is None or path is not None:
        with open(path or ENEMIES_JSON, encoding="utf-8") as f:
            _ENEMIES = json.load(f)
    return _ENEMIES


class Cancer(Entity):
    # ---- 类字段：seed 数值快照（默认值）；实例实际值从 data/enemies.json 读取 ----
    CAN_SPLIT = True
    SPRITE = 'enemy_cancer_48.png'
    SCORE = 10
    SIZE = 40
    RADIUS = 12
    HP = 20
    ATK = 5
    SPEED = 100
    AWAKE_RADIUS = 140
    SPLIT_INTERVAL = 12.0
    SIZE_SCALE = 1.05        # 视觉放大（v3 观感）：普通/变异 +5%（只改贴图尺寸，碰撞半径不变）

    # hardcoded by design: 攻击间隔/仇恨记忆/分裂偏移/标记时长为全局行为节奏，Schema 未逐类定义
    ATK_INTERVAL = 1.0
    AGGRO_MEMORY = 3.0
    SPLIT_OFFSET = 30.0
    MARK_DURATION = 3.0

    def __init__(self, x, y):
        d = load_enemies()[type(self).__name__]
        super().__init__(x, y, radius=d['radius'], faction='enemy', hp=d['hp'])
        self.atk = d['atk']
        self.base_atk = self.atk   # 分层分裂用：子体攻击 = 基础攻击 + 层数加成
        self.speed = d['speed']
        self.score = d['score']
        self.size = int(round(d['size'] * self.SIZE_SCALE))
        self.sprite = d['sprite']
        self.can_split = d.get('can_split', False)
        self.split_interval = d.get('split_interval', self.SPLIT_INTERVAL)
        self.awake_radius = d.get('awake_radius', self.AWAKE_RADIUS)
        self.barrage = d.get('barrage')
        self.awake = False
        self.target = None
        self._attack_cd = 0.0
        self._aggro_wbc = None
        self._aggro_timer = 0.0
        self.split_timer = self.split_interval
        self._split_ready = False
        self.marked = False
        self._mark_timer = 0.0
        self._barrage_timer = (self.barrage or {}).get('interval', 3.0)
        self._barrage_ready = False
        self.atk_interval = self.ATK_INTERVAL    # 攻击间隔（狂暴精英低血时缩短）
        self.split_tier = 0                      # 分层分裂：0=根层
        self.max_split_tier = d.get('split_tiers', 3)
        self.offspring_hp_scale = d.get('offspring_hp_scale', 0.5)
        self.offspring_atk_bonus_per_tier = d.get('offspring_atk_bonus_per_tier', 0)

    # ---------- 唤醒 / 仇恨 / 标记 ----------

    def try_wake(self, player):
        if not self.awake and self.dist_to(player) <= self.awake_radius:
            self.awake = True

    def mark(self):
        """T 细胞标记：揭穿伪装 + 免疫风暴增伤标记。"""
        self.marked = True
        self._mark_timer = self.MARK_DURATION

    def pick_target(self, allies, player):
        macros = [a for a in allies if a.wbc_type == 'macrophage' and a.alive]
        if macros:
            return min(macros, key=self.dist_to)
        if self._aggro_wbc is not None and self._aggro_wbc.alive and self._aggro_timer > 0:
            return self._aggro_wbc
        return player

    def on_hit_by(self, wbc):
        self.awake = True
        self._aggro_wbc = wbc
        self._aggro_timer = self.AGGRO_MEMORY

    # ---------- 移动 / 攻击 ----------

    def chase(self, target):
        dx = target.x - self.x
        dy = target.y - self.y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= self.radius + target.radius:
            self.vx = self.vy = 0.0
        elif dist > 0:
            self.vx = dx / dist * self.speed
            self.vy = dy / dist * self.speed
        else:
            self.vx = self.vy = 0.0

    def try_attack_target(self, target):
        if self._attack_cd > 0:
            return
        if self.dist_to(target) <= self.radius + target.radius + 2:
            # 减伤顺序（v3 §2.6）：敌攻 → −护甲（针织衣，耗耐久）→ ×止痛药 → 盾 → 血
            dmg = self.atk
            armor = getattr(target, 'armor', 0)
            if armor > 0:
                dmg = max(0.0, dmg - armor)
                cb = getattr(target, 'on_hit_cb', None)
                if cb is not None:
                    cb()
            dmg *= getattr(target, 'dmg_mult', 1.0)
            if hasattr(target, 'try_contact_damage'):
                target.try_contact_damage(dmg)
            else:
                target.take_damage(dmg)
            self._attack_cd = self.ATK_INTERVAL

    # ---------- 分裂 ----------

    def take_split(self):
        if self._split_ready:
            self._split_ready = False
            return True
        return False

    def spawn_offspring(self):
        ang = random.uniform(0, math.tau)
        baby = type(self)(self.x + math.cos(ang) * self.SPLIT_OFFSET,
                          self.y + math.sin(ang) * self.SPLIT_OFFSET)
        # 分层分裂：子体更弱但可再分裂（封顶层除外），攻击随层数递增
        baby.split_tier = self.split_tier + 1
        baby.can_split = baby.split_tier < self.max_split_tier
        baby.max_hp = max(1, int(self.max_hp * self.offspring_hp_scale))
        baby.hp = baby.max_hp
        baby.atk = self.base_atk + self.offspring_atk_bonus_per_tier * baby.split_tier
        return baby

    # ---------- 弹幕 ----------

    def _barrage_interval(self):
        """当前弹幕发射间隔（秒）。BossCore 三阶段会加长以降低密度。"""
        return self.barrage['interval']

    def take_barrage(self, player):
        """返回本次弹幕的投射物列表（未到时机返回空）。支持直线/扇形 pattern。"""
        if not self.barrage or not self._barrage_ready:
            return []
        self._barrage_ready = False
        b = self.barrage
        a = math.atan2(player.y - self.y, player.x - self.x)
        if b.get('pattern') == 'fan':
            n = b.get('count', 5)
            spread = b.get('spread', 0.18)
            return [EnemyProjectile(self.x, self.y,
                                    math.cos(a + (i - (n - 1) / 2) * spread) * b['speed'],
                                    math.sin(a + (i - (n - 1) / 2) * spread) * b['speed'],
                                    b['damage'], owner=self)
                    for i in range(n)]
        return [EnemyProjectile(self.x, self.y, math.cos(a) * b['speed'],
                                math.sin(a) * b['speed'], b['damage'], owner=self)]

    # ---------- 帧更新 ----------

    def update(self, dt):
        super().update(dt)
        self._attack_cd = max(0.0, self._attack_cd - dt)
        if self._aggro_timer > 0:
            self._aggro_timer = max(0.0, self._aggro_timer - dt)
            if self._aggro_timer <= 0:
                self._aggro_wbc = None
        if self._mark_timer > 0:
            self._mark_timer = max(0.0, self._mark_timer - dt)
            if self._mark_timer <= 0:
                self.marked = False
        if self.can_split and not self.awake:
            self.split_timer -= dt
            if self.split_timer <= 0:
                self.split_timer = self.split_interval
                self._split_ready = True
        if self.barrage and self.awake:
            self._barrage_timer -= dt
            if self._barrage_timer <= 0:
                self._barrage_timer = self._barrage_interval()
                self._barrage_ready = True

    def draw(self, screen):
        # 程序化动画（美术优化批次 · 精灵图）：
        # 蠕动（微颤 + 呼吸缩放 + 方向摇晃）+ 分裂前兆 / 精英 BOSS 专属提示
        expand, flash = 1.0, None
        if self._split_ready and self.can_split:
            # 分裂前兆：白色膨胀闪帧（睡眠态增殖即将发生）
            expand = 1.0 + 0.12 * math.sin(self._t * 12.0)
            flash = (255, 255, 255)
        elif isinstance(self, BossCore):
            # BOSS：呼吸膨胀 + 二阶段起泛红（狂暴警示）
            expand = 1.0 + math.sin(self._t * 1.6 + self._phase) * 0.06
            flash = (255, 70, 45) if self.phase >= 2 else None
        elif isinstance(self, EliteShield):
            # 护盾精英：护盾存在时淡蓝呼吸闪烁
            flash = (0x8A, 0xD0, 0xFF) if (self.shield > 0
                                           and math.sin(self._t * 6.0) > 0) else None
        elif isinstance(self, EliteSummoner):
            # 召唤精英：蓄力膨胀 + 召唤就绪紫闪
            expand = 1.0 + 0.05 * math.sin(self._t * 2.0 + self._phase)
            flash = (0xE8, 0x5A, 0xE8) if self._summon_ready else None
        elif isinstance(self, EliteRage):
            # 狂暴精英：低血狂化红闪
            en = getattr(self, 'enrage', None)
            if en and self.hp / max(1, self.max_hp) <= en['threshold']:
                flash = (255, 45, 45) if math.sin(self._t * 8.0) > 0 else None
        self._blit_animated(screen, self.sprite, self.size, expand, flash)

    def _blit_animated(self, screen, sprite, size, expand=1.0, flash=None):
        """通用程序化动画：蠕动（位置微颤 + 呼吸缩放 + 摇晃）+ 可选膨胀/闪光环。"""
        t = self._t
        jx = math.sin(t * 4.0 + self._phase) * 2.0
        jy = math.cos(t * 3.1 + self._phase * 1.3) * 1.5
        breathe = 1.0 + math.sin(t * 5.0 + self._phase) * 0.03
        if self.awake:
            ang = math.sin(t * 6.0 + self._phase) * 6.0      # 苏醒：急促蠕动摇晃
        else:
            ang = math.sin(t * 2.0 + self._phase) * 4.0      # 睡眠：缓慢晃动
        img = gfx.load(sprite, (size, size))
        w = max(4, int(size * breathe * expand))
        h = max(4, int(size * breathe * expand))
        if w != size or h != size or abs(ang) >= 1.0:
            img = pygame.transform.smoothscale(img, (w, h))
            if abs(ang) >= 1.0:
                img = pygame.transform.rotate(img, ang)
        cx, cy = int(self.x + jx), int(self.y + jy)
        screen.blit(img, img.get_rect(center=(cx, cy)))
        if flash is not None:
            r = max(8, int(size * 0.35))
            pygame.draw.circle(screen, flash, (cx, cy), r, 3)


class Variant(Cancer):
    """变异细胞：伪装成宿主细胞，T 细胞标记后才能被集火。"""
    SPRITE = 'enemy_variant_96.png'
    SCORE = 15
    SPRITE_REVEALED = 'enemy_cancer_48.png'
    HP = 30
    ATK = 6
    SPEED = 110

    def __init__(self, x, y):
        d = load_enemies()['Variant']
        super().__init__(x, y)
        self.disguised = d.get('disguised', True)
        self.sprite_revealed = d.get('sprite_revealed', self.SPRITE_REVEALED)
        # 分级伪装：1=宿主细胞 / 2=拾取物(红细胞) / 3=己方白细胞（反间，T 标记识破）
        self.disguise_tier = d.get('disguise_tier', 1)

    def mark(self):
        """T 细胞标记：揭穿伪装 + 增伤标记。"""
        super().mark()
        self.disguised = False

    def try_wake(self, player):
        super().try_wake(player)
        if self.awake and self.disguise_tier >= 2:
            self.disguised = False  # 伪装拾取物：玩家靠近即现形突袭

    def draw(self, screen):
        if self.disguised and self.disguise_tier == 2:
            # 伪装成红细胞拾取物：红圆 + 金色提示环（保持静止，防露馅）
            pygame.draw.circle(screen, (0xD8, 0x3A, 0x3A),
                               (int(self.x), int(self.y)), self.radius + 4)
            pygame.draw.circle(screen, (0xC9, 0xA2, 0x27),
                               (int(self.x), int(self.y)), self.radius + 7, 1)
            return
        if self.disguised and self.disguise_tier == 3:
            sprite = 'wbc_neutrophil_48.png'  # 伪装成己方中性粒细胞（反间）
        else:
            sprite = self.sprite if self.disguised else self.sprite_revealed
        self._blit_animated(screen, sprite, self.size)


class EliteRage(Cancer):
    """狂暴精英：高速高攻 + 扇形弹幕，低血狂化（攻击频率/移速提升）。"""
    CAN_SPLIT = False
    SPRITE = 'enemy_elite_rage_96.png'
    SCORE = 50
    SIZE = 56
    RADIUS = 22
    HP = 60
    ATK = 10
    SPEED = 140
    SIZE_SCALE = 1.10        # 精英 +10%

    def __init__(self, x, y):
        d = load_enemies()[type(self).__name__]   # 子类（EliteFragment）读自己的节点
        super().__init__(x, y)
        self.enrage = d.get('enrage')
        self.base_speed = d['speed']

    def update(self, dt):
        super().update(dt)
        if self.enrage and self.awake:
            ratio = self.hp / max(1, self.max_hp)
            enraged = ratio <= self.enrage['threshold']
            self.atk_interval = (self.ATK_INTERVAL / self.enrage['atk_speed_mult']
                                 if enraged else self.ATK_INTERVAL)
            self.speed = self.base_speed * (self.enrage['speed_mult'] if enraged else 1.0)


class EliteFragment(EliteRage):
    """BOSS 分裂时召唤的「精英残片」：小型化狂暴精英（v2 §5.4）。

    数值独立定义于 enemies.json → EliteFragment（hp/atk/size 均低于 EliteRage，
    弹幕更稀疏）。视觉走变异细胞贴图（enemy_variant_96.png，比精英怪贴图更贴合
    「BOSS 分出的小块」观感——避免被误认为普通精英怪，2016-08-30 用户反馈修正）。
    静止时分层分裂（同 Variant：睡眠态增殖，唤醒后停止，split_tier 封顶）。
    """
    SPRITE = 'enemy_variant_96.png'
    SIZE_SCALE = 0.95        # 残片比变异体更小一档（继承 EliteRage 的 1.10 会显得像满编精英）


class EliteShield(Cancer):
    """护盾精英：先破盾再掉血。"""
    CAN_SPLIT = False
    SPRITE = 'enemy_elite_shield_96.png'
    SCORE = 50
    SIZE = 56
    RADIUS = 22
    HP = 50
    ATK = 8
    SPEED = 110
    SHIELD = 30
    SIZE_SCALE = 1.10        # 精英 +10%

    def __init__(self, x, y):
        d = load_enemies()['EliteShield']
        super().__init__(x, y)
        self.max_shield = d.get('shield', self.SHIELD)
        self.shield = self.max_shield
        self.shield_regen_interval = d.get('shield_regen_interval', 8.0)
        self.shield_break_radius = d.get('shield_break_radius', 120)
        self.shield_break_damage = d.get('shield_break_damage', 8)
        self.shield_timer = self.shield_regen_interval
        self._shield_broke = False

    def take_damage(self, dmg):
        if self.shield > 0:
            self.shield -= dmg
            if self.shield <= 0:
                overflow = -self.shield
                self.shield = 0
                self._shield_broke = True  # 破盾瞬间：Gameplay 结算范围震爆
                self.hp -= overflow
                if self.hp <= 0:
                    self.hp = 0
                    self.alive = False
            return
        super().take_damage(dmg)

    def update(self, dt):
        super().update(dt)
        if self.shield < self.max_shield:
            self.shield_timer -= dt
            if self.shield_timer <= 0:
                self.shield = self.max_shield  # 周期再生
                self.shield_timer = self.shield_regen_interval


class EliteSummoner(Cancer):
    """召唤精英：醒着时周期性召唤小怪。"""
    CAN_SPLIT = False
    SPRITE = 'enemy_elite_summoner_96.png'
    SCORE = 50
    SIZE = 56
    RADIUS = 22
    HP = 50
    ATK = 6
    SPEED = 100
    SUMMON_INTERVAL = 8.0
    SIZE_SCALE = 1.10        # 精英 +10%

    def __init__(self, x, y):
        d = load_enemies()['EliteSummoner']
        super().__init__(x, y)
        self.summon_timer = d.get('summon_interval', self.SUMMON_INTERVAL)
        self._summon_ready = False
        self.aura_radius = d.get('aura_radius', 0)    # 加攻光环：范围内敌人攻击+
        self.aura_atk_bonus = d.get('aura_atk_bonus', 0)

    def take_summon(self):
        if self._summon_ready:
            self._summon_ready = False
            return True
        return False

    def update(self, dt):
        super().update(dt)
        if self.awake:
            self.summon_timer -= dt
            if self.summon_timer <= 0:
                self.summon_timer = self.SUMMON_INTERVAL
                self._summon_ready = True


class BossCore(Cancer):
    """癌变核心：高血量，战斗中分裂变异体 + 扇形/环形/螺旋弹幕。"""
    CAN_SPLIT = False
    SPRITE = 'enemy_boss_144.png'
    SCORE = 200
    SIZE = 88
    RADIUS = 40
    HP = 400
    ATK = 10
    SPEED = 60
    BOSS_SPLIT_INTERVAL = 6.0
    SIZE_SCALE = 1.30        # BOSS +30%

    def __init__(self, x, y):
        d = load_enemies()['BossCore']
        super().__init__(x, y)
        self.boss_split_timer = d.get('boss_split_interval', self.BOSS_SPLIT_INTERVAL)
        # 阶段分裂间隔（v2 §5.4：6s→4s→3s），JSON 单一来源，代码不再硬编码倍率
        self.boss_split_intervals = d.get('boss_split_intervals', {})
        self._boss_split_ready = False
        self._spiral_i = 0
        self.phase = 1                # 阶段：1 普通 / 2 狂暴(≤66%) / 3 究极(≤33%)
        self.phase_changed = False
        self.poison_cfg = d.get('poison')
        self.poison_timer = 0.0
        self._poison_ready = False

    def take_boss_split(self):
        if self._boss_split_ready:
            self._boss_split_ready = False
            return True
        return False

    def _barrage_interval(self):
        """三阶段螺旋弹幕密度下调：发射间隔 +3s（2.5s → 5.5s）。"""
        base = self.barrage['interval']
        return base + 3.0 if self.phase >= 3 else base

    def take_barrage(self, player):
        if not self.barrage or not self._barrage_ready:
            return []
        self._barrage_ready = False
        b = self.barrage
        if self.phase >= 3:
            pattern = 'spiral'          # 三阶段：螺旋压制
        elif self.phase >= 2:
            pattern = 'ring'            # 二阶段：环形封锁
        else:
            pattern = 'fan'             # 一阶段：扇形（v2 §5.4 阶段设计：扇→环→螺旋）
        return self._make_barrage(pattern, player.x, player.y, b['speed'], b['damage'])

    def _make_barrage(self, pattern, tx, ty, speed, damage):
        n = 12
        base = math.atan2(ty - self.y, tx - self.x)
        projs = []
        if pattern == 'fan':
            for i in range(n):
                a = base + (i - (n - 1) / 2) * 0.14
                projs.append(EnemyProjectile(self.x, self.y, math.cos(a) * speed,
                                             math.sin(a) * speed, damage, owner=self))
        elif pattern == 'ring':
            for i in range(n):
                a = math.tau * i / n
                projs.append(EnemyProjectile(self.x, self.y, math.cos(a) * speed,
                                             math.sin(a) * speed, damage, owner=self))
        else:  # spiral —— 阿基米德螺旋：4 条臂沿 r=r0+r_step*k 预分布，缓慢径向外扩
            arms = 4
            per_arm = 15
            self._spiral_i += 1
            rot = self._spiral_i * 0.35                       # 每轮整体旋转约 20°
            r0 = 48                                           # 起始半径（>BOSS 半径 40）
            r_step = 14                                       # 沿臂半径步长（臂末 ≈ 244px，更紧凑）
            d_theta = 0.10                                    # 沿臂角度步长（臂占 14*dθ ≈ 80°）
            radial = 50                                       # 径向扩散速度（让螺旋缓慢外扩）
            for arm in range(arms):
                arm_base = rot + arm * (math.tau / arms)
                for k in range(per_arm):
                    theta = arm_base + k * d_theta
                    r = r0 + r_step * k
                    px = self.x + r * math.cos(theta)         # 子弹沿螺旋线预分布（不从中心）
                    py = self.y + r * math.sin(theta)
                    projs.append(EnemyProjectile(
                        px, py, math.cos(theta) * radial, math.sin(theta) * radial,
                        damage, owner=self, lifetime=8.0))    # 8s 持续，螺旋稳定停留
        return projs

    def take_poison_ready(self):
        if self._poison_ready:
            self._poison_ready = False
            return True
        return False

    def update(self, dt):
        super().update(dt)
        if not self.awake:
            return
        # 阶段推进（66% / 33% 血线）
        ratio = self.hp / max(1, self.max_hp)
        new_phase = 3 if ratio <= 0.33 else 2 if ratio <= 0.66 else 1
        if new_phase > self.phase:
            self.phase = new_phase
            self.phase_changed = True
        # 分裂间隔按阶段查表（v2 §5.4：6s→4s→3s）
        interval = self.boss_split_intervals.get(str(self.phase), self.BOSS_SPLIT_INTERVAL)
        self.boss_split_timer -= dt
        if self.boss_split_timer <= 0:
            self.boss_split_timer = interval
            self._boss_split_ready = True
        # 三阶段：周期性生成场地毒区
        if self.poison_cfg and self.phase >= 3:
            self.poison_timer -= dt
            if self.poison_timer <= 0:
                self.poison_timer = self.poison_cfg.get('interval', 5.0)
                self._poison_ready = True


class PoisonZone:
    """场地毒区：持续伤害区域（BOSS 三阶段生成），对范围内敌人与主角造成伤害。

    视觉：预渲染的酸性池底（径向渐变 + 污渍 + 溅点），逐帧叠加冒泡 + 边缘脉冲。
    """

    def __init__(self, x, y, radius, duration, dps):
        self.x = float(x)
        self.y = float(y)
        self.radius = radius
        self.duration = duration
        self.dps = dps
        self.alive = True
        self._timer = duration
        self._tick = 0.0
        self._t = 0.0              # 动画时间
        self._surface = None       # 预渲染池底
        self._fx_layer = None      # 每帧气泡/脉冲层

    def dist_to(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5

    def update(self, dt, entities):
        self._timer -= dt
        self._t += dt
        if self._timer <= 0:
            self.alive = False
            return
        self._tick -= dt
        if self._tick > 0:
            return
        self._tick = 0.5  # 每 0.5s 结算一次
        for e in entities:
            if getattr(e, 'alive', True) and e.dist_to(self) <= self.radius + e.radius:
                e.take_damage(self.dps * 0.5)

    # ---- 预渲染：酸性池底（径向渐变 + 污渍 + 溅点）----

    def _render_base(self, pad=8):
        R = self.radius
        S = R * 2 + pad * 2
        s = pygame.Surface((S, S), pygame.SRCALPHA)
        cx, cy = S // 2, S // 2
        # 径向渐变：外缘暗绿 → 中心亮酸绿（逐圈）
        rings = 22
        for i in range(rings, 0, -1):
            t = i / rings
            r = R * t
            # 颜色插值：外 (0x2A, 0x7A, 0x1E) → 内 (0x8A, 0xE0, 0x4A)
            col = (int(0x2A + (0x8A - 0x2A) * (1 - t)),
                   int(0x7A + (0xE0 - 0x7A) * (1 - t)),
                   int(0x1E + (0x4A - 0x1E) * (1 - t)))
            alpha = 110 + int(60 * (1 - t))
            pygame.draw.circle(s, col + (alpha,), (cx, cy), int(r))
        # 污渍：暗色斑块（病态组织感）
        import random as _rng
        r = _rng.Random((int(self.x * 7) + int(self.y * 13)) & 0xFFFFFF)
        for _ in range(6):
            ang = r.uniform(0, math.tau)
            d = r.uniform(0.2, 0.85) * R
            px, py = cx + math.cos(ang) * d, cy + math.sin(ang) * d
            pr = r.uniform(0.08, 0.20) * R
            pygame.draw.circle(s, (0x1E, 0x5A, 0x16, 55), (int(px), int(py)), int(pr))
        # 高光泡泡斑
        for _ in range(9):
            ang = r.uniform(0, math.tau)
            d = r.uniform(0.1, 0.8) * R
            px, py = cx + math.cos(ang) * d, cy + math.sin(ang) * d
            pr = r.uniform(2, 5)
            pygame.draw.circle(s, (0xC9, 0xF6, 0x9A, 120), (int(px), int(py)), int(pr))
        # 边缘：暗环 + 内亮环（腐蚀感）
        pygame.draw.circle(s, (0x14, 0x3C, 0x0E, 230), (cx, cy), R + 3, 4)
        pygame.draw.circle(s, (0x9A, 0xE0, 0x4A, 160), (cx, cy), R, 2)
        return s

    def draw(self, screen):
        if self._surface is None:
            self._surface = self._render_base()
            self._fx_layer = pygame.Surface(self._surface.get_size(), pygame.SRCALPHA)
        cx, cy = int(self.x), int(self.y)
        pad = 8
        screen.blit(self._surface, (cx - self._surface.get_width() // 2,
                                    cy - self._surface.get_height() // 2))
        # ---- 每帧：冒泡 + 边缘脉冲 ----
        self._fx_layer.fill((0, 0, 0, 0))
        f = pygame.draw
        t = self._t
        R = self.radius
        for i in range(4):
            ph = t * 1.6 + i * 1.9
            bx = cx + math.sin(ph * 1.7 + i * 2.3) * R * 0.45
            by = cy + math.cos(ph * 1.3 + i * 1.1) * R * 0.45
            br = 2.5 + (i % 2) * 2.0
            a = 90 + int(70 * math.sin(ph * 2.2))
            f.circle(self._fx_layer, (0xB8, 0xF0, 0x86, max(20, a)),
                     (int(bx), int(by)), int(br))
            f.circle(self._fx_layer, (0x7A, 0xD0, 0x3A, 190),
                     (int(bx), int(by)), int(br), 1)
        # 边缘脉冲环（呼吸感）
        pulse = math.sin(t * 2.6)
        if pulse > 0:
            f.circle(self._fx_layer, (0x9A, 0xE0, 0x4A, int(70 + 80 * pulse)),
                     (cx, cy), R + 4, 3)
        screen.blit(self._fx_layer, (cx - self._surface.get_width() // 2,
                                     cy - self._surface.get_height() // 2))
