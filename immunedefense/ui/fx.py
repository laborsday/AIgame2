"""ui/fx.py：战斗特效渲染（对象池 + 一次性 surface，避免每帧分配）。

设计遵循算法化特效理念：粒子行为由「种子随机 + 帧率无关阻力衰减」涌现，
冲击波/白闪/全屏红闪均预渲染 surface 复用，标记环呼吸脉动由时间函数驱动。

A4 分层硬约束：本模块含 pygame 渲染，故从 systems/ 迁至 ui/（systems/ 只留纯逻辑）。
"""
import math
import random

import pygame


class ParticlePool:
    """碎屑粒子对象池：固定容量循环复用，避免频繁分配与 GC。"""

    def __init__(self, capacity=96):
        self._pool = [
            {'alive': False, 'x': 0.0, 'y': 0.0, 'vx': 0.0, 'vy': 0.0,
             't': 0.0, 'life': 0.5, 'size': 3, 'color': (255, 255, 255)}
            for _ in range(capacity)
        ]
        self._cursor = 0

    def burst(self, x, y, vx, vy, life, size, color):
        p = self._pool[self._cursor]
        self._cursor = (self._cursor + 1) % len(self._pool)
        p['alive'] = True
        p['x'], p['y'] = x, y
        p['vx'], p['vy'] = vx, vy
        p['t'] = 0.0
        p['life'] = life
        p['size'] = size
        p['color'] = color

    def update(self, dt):
        drag = 0.9 ** (dt * 60)  # 帧率无关阻力衰减
        for p in self._pool:
            if not p['alive']:
                continue
            p['t'] += dt
            if p['t'] >= p['life']:
                p['alive'] = False
                continue
            p['x'] += p['vx'] * dt
            p['y'] += p['vy'] * dt
            p['vx'] *= drag
            p['vy'] *= drag

    def draw(self, screen):
        for p in self._pool:
            if not p['alive']:
                continue
            k = 1.0 - p['t'] / p['life']  # 1 → 0
            s = max(1, int(p['size'] * k))
            pygame.draw.circle(screen, p['color'], (int(p['x']), int(p['y'])), s)


class Shockwave:
    """冲击波：环形扩散，半径随时间线性扩张，线宽衰减。"""

    def __init__(self, x, y, max_radius, color=(255, 255, 255), duration=0.35):
        self.x = float(x)
        self.y = float(y)
        self.max_radius = max_radius
        self.color = color
        self.duration = duration
        self._t = 0.0
        self.alive = True

    def update(self, dt):
        self._t += dt
        if self._t >= self.duration:
            self.alive = False

    def draw(self, screen):
        k = self._t / self.duration
        if k >= 1.0:
            return
        r = max(2, int(self.max_radius * k))
        width = max(1, int(4 * (1 - k)))
        pygame.draw.circle(screen, self.color, (int(self.x), int(self.y)), r, width)


class HitFlash:
    """命中白闪：目标位置短暂高亮圆，预渲染 surface 复用（set_alpha 不分配）。"""

    def __init__(self, x, y, radius, color=(255, 255, 255), duration=0.12):
        self.x = float(x)
        self.y = float(y)
        self.radius = radius
        self.color = color
        self.duration = duration
        self._t = 0.0
        self.alive = True
        s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, color + (200,), (radius, radius), radius)
        self._surface = s

    def update(self, dt):
        self._t += dt
        if self._t >= self.duration:
            self.alive = False

    def draw(self, screen):
        alpha = int(200 * (1 - self._t / self.duration))
        if alpha <= 0:
            return
        self._surface.set_alpha(alpha)
        screen.blit(self._surface, (int(self.x - self.radius),
                                    int(self.y - self.radius)))


class ScreenFlash:
    """全屏红闪：狂暴档3 爆发时低频压场。surface 按屏幕尺寸懒创建并缓存。"""

    def __init__(self, color=(255, 40, 40), duration=0.25):
        self.color = color
        self.duration = duration
        self._t = 0.0
        self.alive = True
        self._surface = None
        self._surface_size = None

    def update(self, dt):
        self._t += dt
        if self._t >= self.duration:
            self.alive = False

    def draw(self, screen):
        alpha = int(110 * (1 - self._t / self.duration))
        if alpha <= 0:
            return
        size = screen.get_size()
        if self._surface is None or self._surface_size != size:
            s = pygame.Surface(size, pygame.SRCALPHA)
            s.fill(self.color + (255,))
            self._surface = s
            self._surface_size = size
        self._surface.set_alpha(alpha)
        screen.blit(self._surface, (0, 0))


def draw_mark_ring(screen, x, y, radius, t):
    """marked 敌人可见标记环：呼吸脉动的金色圆环 + 四角准星。"""
    pulse = 1.0 + 0.15 * math.sin(t * 6.0)
    r = int((radius + 6) * pulse)
    cx, cy = int(x), int(y)
    pygame.draw.circle(screen, (0xFF, 0xD0, 0x4A), (cx, cy), r, 2)
    s = r + 4
    for sx in (-1, 1):
        for sy in (-1, 1):
            x2, y2 = cx + sx * s, cy + sy * s
            pygame.draw.line(screen, (0xFF, 0xE8, 0xA0), (x2 - 4, y2), (x2 + 4, y2), 2)
            pygame.draw.line(screen, (0xFF, 0xE8, 0xA0), (x2, y2 - 4), (x2, y2 + 4), 2)


class FxManager:
    """战斗特效管理器：冲击波/白闪/粒子/全屏红闪 聚合，标记环时间源。"""

    def __init__(self, particle_capacity=96):
        self.shockwaves = []
        self.hit_flashes = []
        self.screen_flashes = []
        self.particles = ParticlePool(particle_capacity)
        self._t = 0.0

    def update(self, dt):
        self._t += dt
        for s in self.shockwaves:
            s.update(dt)
        self.shockwaves = [s for s in self.shockwaves if s.alive]
        for f in self.hit_flashes:
            f.update(dt)
        self.hit_flashes = [f for f in self.hit_flashes if f.alive]
        for f in self.screen_flashes:
            f.update(dt)
        self.screen_flashes = [f for f in self.screen_flashes if f.alive]
        self.particles.update(dt)

    def time(self):
        return self._t

    def spawn_shockwave(self, x, y, max_radius, color=(255, 255, 255)):
        self.shockwaves.append(Shockwave(x, y, max_radius, color))

    def spawn_flash(self, x, y, radius, color=(255, 255, 255)):
        self.hit_flashes.append(HitFlash(x, y, radius, color))

    def spawn_red_flash(self):
        self.screen_flashes.append(ScreenFlash())

    def burst_particles(self, x, y, color, count=10, speed=170,
                        size_range=(2, 4), life_range=(0.3, 0.6), rng=None):
        """爆发碎屑粒子：种子随机方向 + 速度区间，受控混沌。"""
        rng = rng or random
        for _ in range(count):
            a = rng.uniform(0, math.tau)
            v = rng.uniform(speed * 0.4, speed)
            self.particles.burst(
                x, y,
                math.cos(a) * v, math.sin(a) * v,
                rng.uniform(*life_range),
                rng.randint(*size_range),
                color)

    def draw_world(self, screen):
        for s in self.shockwaves:
            s.draw(screen)
        for f in self.hit_flashes:
            f.draw(screen)
        self.particles.draw(screen)

    def draw_screen(self, screen):
        for f in self.screen_flashes:
            f.draw(screen)
