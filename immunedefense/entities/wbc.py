"""白细胞：4 种类型，标定差异化响应（方案 D，GDD 3.2）。数值由 data/cells.json 驱动；
免疫风暴标记倍率（单一来源）在 data/balance.json → rage.immune_storm_mult。"""
import json
import math
import os

import gfx
import paths
import pygame

from .entity import Entity
from .projectile import Projectile

CELLS_JSON = os.path.join(paths.data_dir(), "cells.json")
BALANCE_JSON = os.path.join(paths.data_dir(), "balance.json")

WBC_ORDER = ['neutrophil', 'macrophage', 't_cell', 'nk']
# hardcoded by design: 中文显示名属 UI 文本，不进数值 JSON
WBC_NAMES = {'neutrophil': '中性粒细胞', 'macrophage': '巨噬细胞',
             't_cell': 'T细胞', 'nk': 'NK细胞'}

_CELLS = None
_BALANCE = None


def load_cells(path=None):
    global _CELLS
    if _CELLS is None or path is not None:
        with open(path or CELLS_JSON, encoding="utf-8") as f:
            _CELLS = json.load(f)
    return _CELLS


def load_balance(path=None):
    global _BALANCE
    if _BALANCE is None or path is not None:
        with open(path or BALANCE_JSON, encoding="utf-8") as f:
            _BALANCE = json.load(f)
    return _BALANCE


class WBC(Entity):
    # hardcoded by design: 爆发半径兜底值，实际由 cells.json 的 burst_radius 覆盖到实例
    BURST_RADIUS = 80

    def __init__(self, x, y, wbc_type):
        stats = load_cells()[wbc_type]
        super().__init__(x, y, radius=stats['radius'], faction='ally', hp=stats['hp'])
        self.wbc_type = wbc_type
        self.atk = stats['atk']
        self.speed = stats['speed']
        self.attack_range = stats.get('range', 0)  # 0 = 近战
        self.attack_interval = 1.0 / stats.get('atk_speed', 0.5)
        self.burst_cd = stats.get('burst_cd', 0.0)
        self.burst_radius = stats.get('burst_radius', self.BURST_RADIUS)
        # 单一来源：免疫风暴标记倍率统一走 balance.json（v2 §4.3 mark_multiplier 2.0）
        self.mark_multiplier = load_balance()['rage']['immune_storm_mult']
        self.sprite = stats['sprite']
        self.burst_cd_left = 0.0
        self._attack_cd = 0.0
        self.atk_mult = 1.0   # 攻击倍率（预防针临时提升）
        self.rage_bonus = 0.0  # 残血狂暴攻击加成（0~0.35），由 Gameplay 每帧同步
        self.rage_tier = 0     # 狂暴档位 0-3（T 穿透 / NK 爆发技分级）
        self.kills = 0        # 本局击杀数（死亡时换算成祭点）
        self.dmg_mult = stats.get('dmg_mult', 1.0)  # 坦克减伤（巨噬 0.5）

    # ---------- 行为 ----------

    def seek(self, tx, ty, stop_dist=4.0):
        """朝 (tx, ty) 移动，到达附近即停。"""
        dx = tx - self.x
        dy = ty - self.y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > stop_dist:
            self.vx = dx / dist * self.speed
            self.vy = dy / dist * self.speed
        else:
            self.vx = self.vy = 0.0

    def respond_to_target(self, player, target, projectiles):
        """对标定的差异化响应（GDD 3.2，方案 D）。"""
        if self.wbc_type == 'neutrophil':
            self.seek(target.x, target.y)
            if self.dist_to(target) <= self.radius + target.radius:
                self.vx = self.vy = 0.0
        elif self.wbc_type == 'macrophage':
            self.seek((player.x + target.x) / 2, (player.y + target.y) / 2)
        elif self.wbc_type == 't_cell':
            dist = self.dist_to(target)
            if dist > self.attack_range * 0.75:
                self.seek(target.x, target.y)
            else:
                self.vx = self.vy = 0.0
            self._shoot(target, projectiles)
        elif self.wbc_type == 'nk':
            self.seek(target.x, target.y)

    def auto_mark(self, enemies, projectiles):
        """T 细胞自动识别并射击伪装中的变异细胞（无需标定，GDD 4.2）。"""
        if self.wbc_type != 't_cell':
            return
        for e in enemies:
            if getattr(e, 'disguised', False) and e.alive:
                self._shoot(e, projectiles)
                return

    def _shoot(self, target, projectiles):
        if not hasattr(target, 'hp'):
            return  # 地面标定不射击，只移动
        if self._attack_cd > 0:
            return
        if self.dist_to(target) <= self.attack_range:
            # 口径与其他单位一致（v2 §4.2）：远程也吃狂暴攻击加成；
            # 档 2+ 爆发技：穿透射击（v2 §4.4，balance.json rage.burst_skills.t_cell.tier2）
            pierce = 1 if self.rage_tier >= 2 else 0
            projectiles.append(Projectile(self.x, self.y, target.x, target.y,
                                          self.atk * self.atk_mult * (1 + self.rage_bonus),
                                          owner=self, pierce=pierce))
            self._attack_cd = self.attack_interval

    def trigger_burst(self):
        """NK：标定瞬间的爆发（伤害由 Gameplay 对范围内敌人结算）。"""
        self.burst_cd_left = self.burst_cd

    def try_attack(self, target):
        """近战接触攻击，按攻速节流；命中后敌人记仇。返回命中伤害（0=未命中）。"""
        if self._attack_cd > 0:
            return 0
        if self.dist_to(target) <= self.radius + target.radius + 2:
            dmg = self.atk * self.atk_mult * (1 + self.rage_bonus)
            target.take_damage(dmg)
            if not target.alive:
                self.kills += 1
            if hasattr(target, 'on_hit_by'):
                target.on_hit_by(self)
            self._attack_cd = self.attack_interval
            return dmg
        return 0

    def update(self, dt):
        super().update(dt)
        self._attack_cd = max(0.0, self._attack_cd - dt)
        self.burst_cd_left = max(0.0, self.burst_cd_left - dt)

    def draw(self, screen):
        # 程序化动画（美术优化批次 · 精灵图）：漂浮游动 + 呼吸缩放 + 攻击前倾
        # 漂浮：Y 轴正弦浮动（幅度 3px，相位错开避免同屏同步）
        bob = math.sin(self._t * 2.2 + self._phase) * 3.0
        # 呼吸：缩放 ±4%
        breathe = 1.0 + math.sin(self._t * 3.1 + self._phase * 1.7) * 0.04
        # 攻击前倾：近战/远程出手瞬间向移动方向倾斜，随攻击冷却衰减复位
        tilt = 0.0
        if self._attack_cd > 0 and self.attack_interval > 0:
            ratio = self._attack_cd / self.attack_interval   # 1→0 衰减
            tilt = 12.0 * ratio
        if abs(self.vx) > 1 or abs(self.vy) > 1:
            angle = tilt if self.vx >= 0 else -tilt
        else:
            angle = 0.0
        img = gfx.load(self.sprite, (42, 42))   # 白细胞 +5% 视觉（碰撞半径不变）
        w = max(4, int(42 * breathe))
        h = max(4, int(42 * breathe))
        if w != 42 or h != 42 or abs(angle) >= 1.0:
            img = pygame.transform.smoothscale(img, (w, h))
            if abs(angle) >= 1.0:
                img = pygame.transform.rotate(img, angle)
        cy = int(self.y + bob)
        screen.blit(img, img.get_rect(center=(int(self.x), cy)))
        if self.rage_bonus > 0.0:
            # 残血狂暴：泛红光提示（档位越高圈越大）
            r = self.radius + 5 + int(self.rage_bonus * 10)
            pygame.draw.circle(screen, (0xFF, 0x3A, 0x3A),
                               (int(self.x), cy), r, 2)
