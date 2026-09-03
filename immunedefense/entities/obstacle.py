"""房间障碍 v2：坏死堆 + 血管网络（多段拼接路径 / 拱桥可钻 / 形状即碰撞）。

形状 = 碰撞（不再是矩形）：
  - dead_cells ：沿长轴 3 圆的椭圆化圆簇（贴合坏死堆贴图的团块形状）
  - vessel 地面管：沿平滑路径采样成胶囊圆串，整条管碰撞
  - vessel 拱桥(raised)：管身按正弦拱起——拱起处 lift ≥ radius+16 则该段无碰撞
    （实体可从管下钻过），两端贴地处碰撞；地面画投影阴影提示"可钻"

vessel 数据格式（rooms.json）：
  {"type":"vessel","path":[{"x":..,"y":..},..2~5点],
   "radius":13~15,"raised":true,"sag":30~40}     # sag=拱高，sag ≥ radius+16 才有可钻段
"""
import math
import os
import random

import pygame

import gfx
import paths

VESSEL_DARK = (0x3A, 0x12, 0x18)   # 轮廓
VESSEL_BODY = (0x5A, 0x1E, 0x28)   # 管体
VESSEL_MID = (0x8A, 0x3A, 0x3E)    # 受光面
VESSEL_HI = (0xA9, 0x4A, 0x4A)     # 高光
SHADOW = (0x12, 0x0B, 0x09)        # 地面投影（可钻提示）

PASS_UNDER_LIFT = 16   # 拱起高度门槛：lift 超过 radius+该值 → 可钻


def _catmull_rom(points, samples=10):
    """Catmull-Rom 样条插值（平滑多段路径）。"""
    if len(points) < 2:
        return [tuple(p) for p in points]
    pts = [(float(x), float(y)) for x, y in points]
    pts = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for t in range(samples):
            t /= samples
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
                       (2 * p0[0] - 4 * p1[0] + 2 * p2[0]) * t2 +
                       (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
                       (2 * p0[1] - 4 * p1[1] + 2 * p2[1]) * t2 +
                       (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(pts[-1])
    return out


def _sample_vessel(spec):
    """路径 → 等距采样点（含拱起 lift）。返回 (pts, passable_zone)。"""
    path = [(float(p['x']), float(p['y'])) for p in spec.get('path', [])]
    radius = float(spec.get('radius', 13))
    raised = bool(spec.get('raised', False))
    sag = float(spec.get('sag', 0))
    smooth = _catmull_rom(path, samples=8)
    # 弧长等距采样（每 5px 一点）
    pts = []
    acc = 0.0
    seg = [smooth[0]]
    for i in range(1, len(smooth)):
        x0, y0 = seg[-1]
        x1, y1 = smooth[i]
        d = math.hypot(x1 - x0, y1 - y0)
        while acc + d >= 5.0:
            t = (5.0 - acc) / max(1e-6, d)
            nx, ny = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            seg[-1] = (nx, ny)
            pts.append(seg[-1])
            seg.append((nx, ny))
            x0, y0 = seg[-1]
            d = math.hypot(x1 - x0, y1 - y0)
            acc = 0.0
        acc += d
    if seg and (seg[-1] not in pts):
        pts.append(seg[-1])
    if not pts and smooth:
        pts = smooth
    total = max(1.0, len(pts))
    out = []
    for i, (x, y) in enumerate(pts):
        lift = sag * math.sin(math.pi * (i / total)) if raised else 0.0
        out.append((x, y, lift))
    return out, radius, raised


class Obstacle:
    def __init__(self, spec):
        self.type = spec.get('type', 'dead_cells')
        if self.type == 'vessel':
            self.raw = spec
            self._tube, self.radius, self.raised = _sample_vessel(spec)
            self.sag = float(spec.get('sag', 0))
            # 碰撞实心圆：地面管全管；拱桥只在「贴地段」实心
            self._solids = []
            for (x, y, lift) in self._tube:
                if lift < self.radius + PASS_UNDER_LIFT:
                    self._solids.append((x, y, self.radius))
            # 兜底：至少两端实心（若路径极短全是可钻段）
            if not self._solids:
                self._solids = [(self._tube[0][0], self._tube[0][1], self.radius)]
            self.x = min(p[0] for p in self._tube)
            self.y = min(p[1] for p in self._tube)
            self.w = max(p[0] for p in self._tube) - self.x
            self.h = max(p[1] for p in self._tube) - self.y
            self.rect = pygame.Rect(int(self.x - self.radius), int(self.y - self.radius),
                                    int(self.w + 2 * self.radius),
                                    int(self.h + 2 * self.radius))  # 兼容旧 API
            self.sprite = None
        else:  # dead_cells 坏死堆
            self.x = spec['x']
            self.y = spec['y']
            self.w = spec['w']
            self.h = spec['h']
            self.rect = pygame.Rect(self.x, self.y, self.w, self.h)
            self._solids = self._pile_solids()
            self.sprite = self._pick_sprite()
            self.raised = False

    # ---------- 形状 ----------
    def _pile_solids(self):
        """坏死堆：沿长轴 3 圆的椭圆化圆簇（贴合团块贴图）。"""
        cx, cy = self.x + self.w / 2, self.y + self.h / 2
        rx, ry = self.w / 2, self.h / 2
        rmin = min(rx, ry)
        major = max(rx, ry)
        off = max(0.0, major - rmin)
        return [(cx - off * 0.55, cy, rmin * 0.9),
                (cx, cy, rmin),
                (cx + off * 0.55, cy, rmin * 0.9)]

    def _pick_sprite(self):
        sprites = _get_dead_cells_sprites()
        if not sprites:
            return None
        return random.Random((int(self.x * 31 + self.y * 17)) & 0xFFFFFF).choice(sprites)

    def collide_circle(self, cx, cy, r):
        """圆与障碍是否重叠（贴合形状；恰好接触不算重叠）。"""
        for (sx, sy, sr) in self._solids:
            dx, dy = cx - sx, cy - sy
            rr = r + sr
            if dx * dx + dy * dy < rr * rr:
                return True
        return False

    def blocks_point(self, px, py):
        """点是否被障碍阻挡（弹幕用）。"""
        for (sx, sy, sr) in self._solids:
            dx, dy = px - sx, py - sy
            if dx * dx + dy * dy < sr * sr:
                return True
        return False

    def overlaps_rect(self, rect):
        """矩形是否与障碍重叠（商店台落点用）。"""
        for (sx, sy, sr) in self._solids:
            nx = max(rect.left, min(sx, rect.right))
            ny = max(rect.top, min(sy, rect.bottom))
            if (sx - nx) ** 2 + (sy - ny) ** 2 <= sr * sr:
                return True
        return False

    def perch_points(self):
        """萤火虫停留候选点：障碍物顶部（坏死堆顶面 / 管顶）。

        - dead_cells ：堆顶中轴取 3 点（贴图团块顶部弧线）
        - vessel     ：沿管身取 3 点（含拱起处，取管顶上方）
        """
        pts = []
        if self.type == 'vessel':
            step = max(1, len(self._tube) // 3)
            for i in (0, step, min(2 * step, len(self._tube) - 1)):
                tx, ty, lift = self._tube[i]
                pts.append((tx, ty - lift - self.radius - 8))
        else:
            for fx in (0.3, 0.5, 0.7):
                pts.append((self.x + self.w * fx,
                            self.y + self.h * (0.30 - 0.14 * abs(fx - 0.5) * 2)))
        return pts

    def resolve_circle(self, e):
        """把圆形实体 e 从障碍各实心圆中推出。"""
        for (sx, sy, sr) in self._solids:
            dx = e.x - sx
            dy = e.y - sy
            r = e.radius + sr
            dist_sq = dx * dx + dy * dy
            if dist_sq >= r * r:
                continue
            if dist_sq < 0.0001:
                dx, dy = 0.01, 0.01
                dist = 0.0141
            else:
                dist = dist_sq ** 0.5
            push = r - dist
            e.x += dx / dist * push
            e.y += dy / dist * push

    # ---------- 渲染 ----------
    def draw(self, screen):
        """完整绘制（兼容旧调用）；游戏内分层用 draw_under / draw_over。"""
        self.draw_under(screen)
        self.draw_over(screen)

    def draw_under(self, screen):
        """地面层：坏死堆 / 地面血管 / 拱桥的投影与墩座（在实体之下绘制）。"""
        if self.type == 'vessel':
            self._draw_vessel_shadow(screen)
            if not self.raised:
                self._draw_vessel_tube(screen)
        elif self.sprite is not None:
            scaled = pygame.transform.smoothscale(self.sprite, (self.w, self.h))
            screen.blit(scaled, (self.x, self.y))
        else:
            self._draw_dead_cells(screen)

    def draw_over(self, screen):
        """架空层：拱桥管身画在实体之上（钻过时被管身遮住，读作"在桥下"）。"""
        if self.type == 'vessel' and self.raised:
            self._draw_vessel_tube(screen)

    def _draw_vessel_shadow(self, screen):
        """拱桥：地面投影（可钻提示）+ 落端墩座。"""
        if not self.raised:
            return
        r = int(self.radius)
        for (x, y, lift) in self._tube:
            if lift > self.radius * 0.7:
                pygame.draw.ellipse(screen, SHADOW,
                                    (x - r, y + r * 0.5, r * 2, r))
        for idx in (0, len(self._tube) - 1):
            x, y, _ = self._tube[idx]
            pygame.draw.ellipse(screen, SHADOW,
                                (x - r * 1.3, y + r * 0.15, r * 2.6, r * 0.8))
            pygame.draw.ellipse(screen, VESSEL_BODY,
                                (x - r * 1.05, y - r * 0.28, r * 2.1, r * 0.7))

    def _draw_vessel_tube(self, screen):
        """管身：轮廓 → 体 → 受光面 → 高光（按拱起 lift 上移）；无分节环。"""
        r = int(self.radius)
        for (x, y, lift) in self._tube:
            cy = y - lift
            pygame.draw.circle(screen, VESSEL_DARK, (int(x), int(cy)), r + 2)
        for (x, y, lift) in self._tube:
            cy = y - lift
            pygame.draw.circle(screen, VESSEL_BODY, (int(x), int(cy)), r)
        for (x, y, lift) in self._tube:
            cy = y - lift
            pygame.draw.circle(screen, VESSEL_MID,
                               (int(x), int(cy) - int(r * 0.30)), int(r * 0.62))
        for (x, y, lift) in self._tube:
            cy = y - lift
            pygame.draw.circle(screen, VESSEL_HI,
                               (int(x) - int(r * 0.20), int(cy) - int(r * 0.38)),
                               int(r * 0.30))

    def _draw_dead_cells(self, screen):
        """兜底：程序化坏死堆（与原实现一致）。"""
        rng = random.Random((int(self.rect.x * 31 + self.rect.y * 17)) & 0xFFFFFF)
        r = self.rect
        pygame.draw.ellipse(screen, (0x14, 0x1A, 0x10),
                            (r.x - 4, r.bottom - 10, r.w + 8, 18))
        pile = [
            (0.50, 0.30, 0.50, 0.55),
            (0.20, 0.58, 0.36, 0.55),
            (0.80, 0.56, 0.38, 0.52),
            (0.48, 0.42, 0.42, 0.50),
        ]
        for i, (cx, cy, cw, ch) in enumerate(pile):
            col = [(0x4C, 0x4F, 0x2F), (0x58, 0x5C, 0x34),
                   (0x48, 0x4C, 0x2C), (0x52, 0x56, 0x30)][i % 4]
            px = r.x + cx * r.w - cw * r.w / 2
            py = r.y + cy * r.h - ch * r.h / 2
            pygame.draw.ellipse(screen, col, (px, py, cw * r.w, ch * r.h))
        n = max(4, r.w // 20)
        for _ in range(n):
            gx = r.x + rng.uniform(0.12, 0.88) * r.w
            gy = r.y + rng.uniform(0.30, 0.88) * r.h
            pygame.draw.circle(screen, (0x2E, 0x33, 0x20), (int(gx), int(gy)), 5)
            pygame.draw.circle(screen, (0x76, 0x7B, 0x48), (int(gx) - 1, int(gy) - 2), 3)
            pygame.draw.circle(screen, (0x39, 0x3E, 0x26), (int(gx) + 6, int(gy) + 3), 3)


# ---------- 贴图缓存（坏死堆） ----------
_DEAD_CELLS_SPRITES = None


def _load_sprites(prefix):
    assets_dir = paths.assets_dir()
    sprites = []
    for f in sorted(os.listdir(assets_dir)):
        if f.startswith(prefix + '_') and f.endswith('.png'):
            try:
                surf = pygame.image.load(os.path.join(assets_dir, f)).convert_alpha()
                sprites.append(surf)
            except Exception:
                pass
    return sprites


def _get_dead_cells_sprites():
    global _DEAD_CELLS_SPRITES
    if _DEAD_CELLS_SPRITES is None:
        _DEAD_CELLS_SPRITES = _load_sprites('dead_cells')
    return _DEAD_CELLS_SPRITES
