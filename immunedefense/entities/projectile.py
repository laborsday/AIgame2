"""T 细胞投射物：直线飞行，命中敌人造成伤害（无贴图，用我方色系占位）。"""
import pygame

import settings


class Projectile:
    SPEED = 320

    def __init__(self, x, y, tx, ty, damage, owner=None, pierce=0):
        self.x = float(x)
        self.y = float(y)
        self.damage = damage
        self.owner = owner  # 发射它的白细胞（用于仇恨结算）
        self.radius = 4
        self.pierce = pierce      # 可继续穿透命中的敌人数量（0=命中即消散）
        self._hit = set()         # 已命中的敌人（穿透弹不重复结算）
        dx = tx - x
        dy = ty - y
        dist = (dx * dx + dy * dy) ** 0.5 or 1.0
        self.vx = dx / dist * self.SPEED
        self.vy = dy / dist * self.SPEED
        self.life = 2.0
        self.alive = True

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        if self.life <= 0:
            self.alive = False

    def draw(self, screen):
        pygame.draw.circle(screen, settings.WBC_GLOW,
                           (int(self.x), int(self.y)), self.radius + 2, 1)
        pygame.draw.circle(screen, settings.WBC_NUC,
                           (int(self.x), int(self.y)), self.radius)
