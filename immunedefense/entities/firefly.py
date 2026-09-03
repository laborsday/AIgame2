"""萤火虫（昏暗模式专属道具，v6）。

玩法定稿：
- 仅「昏暗模式」下，每间战斗房 50% 概率刷新 1 只，停在随机障碍物顶部；
- 主角进入 CAPTURE_RANGE 起算 6 秒捕捉窗口（离开范围重置）；超时未捕捉
   → 飞往另一处障碍物（弧线飞行动画）；
- 点击命中的萤火虫（且在窗口内）→ 弹确认式捕捉弹窗，确认进背包；
- 使用道具 → 点击地图一处 → 萤火虫从主角处飞过去，永久照亮（placed，
  不再可捕捉、不会熄灭）；照亮半径与主角光环一致（FIREFLY_HALO_RADIUS）。

A4 分层：entities/ 允许 pygame（渲染归实体）；systems/ 保持纯逻辑。
"""
import math
import random

import pygame

import gfx

# 数值
FIREFLY_HALO_RADIUS = 200   # 照亮半径：与主角默认光环（guide_radius）相当
CAPTURE_RANGE = 160         # 主角进入此距离 → 开始 6s 捕捉窗口
CAPTURE_TIMEOUT = 6.0       # 窗口时长（秒），超时未捕捉 → 飞走
CLICK_RADIUS = 42           # 点击命中半径
FLIGHT_SPEED = 240.0        # 飞行速度（px/s）

# 颜色
BODY = (0xE8, 0xD8, 0x5C)   # 发光腹部（暖黄）
HEAD = (0x9A, 0x8A, 0x3A)   # 头胸
WING = (0xF0, 0xF2, 0xDC)   # 薄翅
CORE = (0xFF, 0xF6, 0xB8)   # 光核
RING = (0xFF, 0xE9, 0xA0)   # 倒计时环

_GLOW = None   # 光晕贴片（模块级缓存）


def _glow_patch():
    """萤火虫光晕：暖黄径向渐变（中心亮、边缘 0），96px 缓存。"""
    global _GLOW
    if _GLOW is None:
        S = 96
        s = pygame.Surface((S, S), pygame.SRCALPHA)
        c = S / 2.0
        for y in range(S):
            for x in range(S):
                r = math.hypot(x - c, y - c)
                if r > c:
                    continue
                t = r / c
                a = int(110 * (1.0 - t) ** 1.7)
                s.set_at((x, y), (0xE8, 0xD8, 0x5C, a))
        _GLOW = s
    return _GLOW


class Firefly:
    """萤火虫。state: 'perch' 停留障碍物 / 'fly' 飞行 / 'placed' 已放置（永久）。"""

    def __init__(self, perch):
        self.x, self.y = float(perch[0]), float(perch[1])
        self.state = 'perch'
        self.placed = False
        self.timer = CAPTURE_TIMEOUT   # 进入捕捉窗口后倒计时；离开范围重置
        self.in_range = False
        self._phase = random.uniform(0, math.tau)   # 动画相位（错开）
        self._t = 0.0
        self._hover = 0.0
        self._fly = None                # {'from': (x, y), 'to': (x, y), 'dur': s, 't': 0..1}

    # ---------- 逻辑 ----------

    def dist_to(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5

    def start_flight(self, x, y):
        """起飞：从当前位置弧线飞往 (x, y)。placed 飞行动画同样走这里。"""
        d = math.hypot(x - self.x, y - self.y)
        self._fly = {'from': (self.x, self.y), 'to': (x, y),
                     'dur': max(0.5, d / FLIGHT_SPEED), 't': 0.0}
        self.state = 'fly'
        self.timer = CAPTURE_TIMEOUT   # 落地后重新给满窗口

    def update(self, dt, player, obstacles):
        """perch：按玩家距离跑 6s 窗口；超时 → 飞往另一处障碍物。"""
        self._t += dt
        if self.state == 'fly':
            f = self._fly
            f['t'] += dt / f['dur']
            k = min(1.0, f['t'])
            x0, y0 = f['from']
            x1, y1 = f['to']
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2 - 46   # 弧线：中点抬升
            u = 1.0 - k
            self.x = u * u * x0 + 2 * u * k * cx + k * k * x1
            self.y = u * u * y0 + 2 * u * k * cy + k * k * y1
            if f['t'] >= 1.0:
                self.x, self.y = x1, y1
                self._fly = None
                self.state = 'perch'
            return
        # perch / placed：轻微悬浮
        self._hover = math.sin(self._t * 3.0 + self._phase) * 3.0
        if self.placed:
            return
        if self.dist_to(player) <= CAPTURE_RANGE:
            self.in_range = True
            self.timer -= dt
            if self.timer <= 0:
                self.timer = CAPTURE_TIMEOUT
                self.in_range = False
                nxt = self._next_perch(obstacles)
                if nxt is not None:
                    self.start_flight(*nxt)
        else:
            self.in_range = False
            self.timer = CAPTURE_TIMEOUT   # 离开范围：撤销本次窗口

    def _next_perch(self, obstacles):
        """挑选另一处停留点（与原处相距 ≥ 60px，避免原地打转）；无候选返回 None。"""
        pts = []
        for ob in obstacles:
            for p in ob.perch_points():
                if (p[0] - self.x) ** 2 + (p[1] - self.y) ** 2 >= 60 * 60:
                    pts.append(p)
        return random.choice(pts) if pts else None

    # ---------- 渲染 ----------

    def draw(self, screen):
        flap = math.sin(self._t * (42.0 if self.state == 'fly' else 9.0))
        bob = self._hover if self.state != 'fly' else 0.0
        x, y = int(self.x), int(self.y + bob)

        # 光晕（脉动）
        pulse = 1.0 + 0.18 * math.sin(self._t * 4.0 + self._phase)
        gs = int(56 * pulse)
        glow = pygame.transform.smoothscale(_glow_patch(), (gs, gs))
        screen.blit(glow, glow.get_rect(center=(x, y)))

        # 薄翅（蝴蝶式扇动）
        off = 6 + 2 * flap
        pygame.draw.ellipse(screen, WING, (x - off - 4, y - 13 - flap, 8, 10))
        pygame.draw.ellipse(screen, WING, (x + off - 4, y - 13 - flap, 8, 10))
        # 头胸 + 发光腹部
        pygame.draw.ellipse(screen, HEAD, (x - 3, y - 6, 7, 7))
        pygame.draw.ellipse(screen, BODY, (x - 5, y - 1, 10, 10))
        pygame.draw.circle(screen, CORE, (x, y + 4), 3)
        pygame.draw.circle(screen, (0xFF, 0xFF, 0xD8), (x - 1, y), 1)

        # 捕捉窗口：倒计时环 + 「点击捕捉」提示
        if self.state == 'perch' and not self.placed and self.in_range:
            frac = max(0.0, self.timer / CAPTURE_TIMEOUT)
            pygame.draw.arc(screen, RING,
                            (x - 18, y - 18, 36, 36),
                            -math.pi / 2, -math.pi / 2 + math.tau * frac, 3)
            hint = gfx.font(13, True).render("点击捕捉", True, RING)
            screen.blit(hint, hint.get_rect(center=(x, y - 34)))
            sec = gfx.font(14, True).render(f"{self.timer:.1f}", True, RING)
            screen.blit(sec, sec.get_rect(center=(x, y - 50)))
