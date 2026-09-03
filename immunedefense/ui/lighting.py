"""ui/lighting.py：手术灯光照渲染（美术优化批次 · 灯光）。

效果：
- 手术灯：每间房从天花板打下一盏灯，照亮地图中央约 39% 面积（半径 340），
  中心 50% 半径内全亮（平顶聚光），外围平滑渐暗；圆外四周沉入黑暗。
  亮区叠加暖黄光晕（明显提亮，非仅透出原色），同一房间每次进入光照位置一致。
- 主角光环：主角（白细胞指挥）指挥范围（guide_radius=200）内自带暖黄光源，
  跟随玩家移动，暗房探索时操作区域始终可见。

设计：
- 遮罩（SRCALPHA）：暗色 fill + 径向渐变「黑色 alpha」光斑用 BLEND_RGBA_SUB 只减
  遮罩 alpha（RGB 保持 0，不破坏世界颜色），中心 alpha=0 全透、边缘 alpha=dark。
- 暖光光晕：暖色渐变（SRCALPHA 正常混合）叠加在世界之上、遮罩之下，亮区真正变亮。
- 静态手术灯遮罩/光晕按 (cx, cy, dark) 缓存（≤12 房）；玩家光环每帧把 halo patch
  SUB 进遮罩副本（copy 一次全屏，局部擦暗）+ 叠加暖黄光晕（跟随玩家）。

A4 分层硬约束：本模块只读房间状态并绘制，不改任何游戏状态字段。
"""
import math
import random

import pygame


class LightRenderer:
    """手术灯暗遮罩 + 暖光光晕；主角指挥范围自带暖黄光源。"""

    def __init__(self, width, height, light_radius=None):
        self.w, self.h = width, height
        self.cx, self.cy = width // 2, height // 2
        self.light_radius = light_radius or 340     # 光斑半径：照亮地图约 39% 面积
        self._center_radius = width // 4            # 圆心取样范围（保持中央区域）
        self._patch = None            # 手术灯「黑色 alpha」光斑（擦暗用，预渲染一次）
        self._glow = None             # 手术灯暖黄光晕（提亮用，预渲染一次）
        self._halo_base = None        # 玩家光环基片（96×96）
        self._halos = {}              # radius → 擦暗光斑（黑色 alpha）
        self._halo_glows = {}         # radius → 暖黄光晕
        self._cache = {}              # (cx, cy, dark) → 遮罩 surface
        self._mask = None
        self._last_key = None
        self._lcx = self.lcy = None   # 当前圆心（draw 时对齐光晕）

    # ---------- 光源圆心（房间种子稳定） ----------

    def room_center(self, room_index):
        """在「地图中央、半径 = 地图宽 1/4」的圆内取均匀随机点。

        以房间 index 为随机种子，同一房间每次进入光照位置一致（不随重开/返回变化）。
        """
        rng = random.Random(f"surgery-light:{room_index}")
        a = rng.uniform(0, math.tau)
        r = self._center_radius * math.sqrt(rng.random())   # 均匀圆内分布
        return (self.cx + math.cos(a) * r, self.cy + math.sin(a) * r)

    # ---------- 预渲染贴片 ----------

    def _light_patch(self):
        """手术灯擦暗光斑：中心 50% 半径 alpha=255（遮罩全透明），外缘平滑衰减到 0。

        黑色 alpha 渐变，BLEND_RGBA_SUB 时只减遮罩 alpha，不破坏世界颜色。
        """
        if self._patch is None:
            S = 192
            s = pygame.Surface((S, S), pygame.SRCALPHA)
            c = S / 2.0
            R = S / 2.0
            for y in range(S):
                for x in range(S):
                    r = math.hypot(x - c, y - c)
                    if r > R:
                        continue
                    t = r / R
                    if t < 0.5:
                        a = 255                      # 中心平顶：全擦除暗色
                    else:
                        a = int(255 * (1.0 - (t - 0.5) / 0.5) ** 1.6)
                    s.set_at((x, y), (0, 0, 0, a))
            self._patch = pygame.transform.smoothscale(
                s, (self.light_radius * 2, self.light_radius * 2))
        return self._patch

    def _glow_patch(self):
        """手术灯暖黄光晕：中心 alpha=120 平缓衰减，叠加在遮罩之下使亮区真正变亮。"""
        if self._glow is None:
            S = 192
            s = pygame.Surface((S, S), pygame.SRCALPHA)
            c = S / 2.0
            R = S / 2.0
            for y in range(S):
                for x in range(S):
                    r = math.hypot(x - c, y - c)
                    if r > R:
                        continue
                    t = r / R
                    a = int(120 * (1.0 - t) ** 1.4)
                    s.set_at((x, y), (255, 216, 150, a))
            self._glow = pygame.transform.smoothscale(
                s, (self.light_radius * 2, self.light_radius * 2))
        return self._glow

    def _halo(self, radius):
        """玩家光环擦暗光斑：柔和渐亮（1-t^2），按半径缓存。"""
        patch = self._halos.get(radius)
        if patch is not None:
            return patch
        if self._halo_base is None:
            S = 96
            s = pygame.Surface((S, S), pygame.SRCALPHA)
            c = S / 2.0
            R = S / 2.0
            for y in range(S):
                for x in range(S):
                    r = math.hypot(x - c, y - c)
                    if r > R:
                        continue
                    t = r / R
                    a = int(240 * (1.0 - t * t))
                    s.set_at((x, y), (0, 0, 0, a))
            self._halo_base = s
        patch = pygame.transform.smoothscale(
            self._halo_base, (radius * 2, radius * 2))
        if len(self._halos) < 4:
            self._halos[radius] = patch
        return patch

    def _halo_glow(self, radius):
        """玩家光环暖黄光晕（与地图手术灯同色系，但亮度弱 30%）：中心 alpha=84 平缓衰减。

        颜色从淡青 (200,235,255) 改为暖黄 (255,216,150)：淡青叠加在角色身上会把
        黑色头发/深色衣物偏成灰蓝，像蒙了层冷雾；暖黄与手术灯一致，角色置身暖光
        中更自然，深色部分只轻微泛暖而不发灰。
        手术灯中心 alpha=120，玩家光环取 70%（=84），避免光环提亮盖过地图灯光。
        """
        glow = self._halo_glows.get(radius)
        if glow is not None:
            return glow
        S = 96
        s = pygame.Surface((S, S), pygame.SRCALPHA)
        c = S / 2.0
        R = S / 2.0
        for y in range(S):
            for x in range(S):
                r = math.hypot(x - c, y - c)
                if r > R:
                    continue
                t = r / R
                a = int(84 * (1.0 - t * t))
                s.set_at((x, y), (255, 216, 150, a))
        glow = pygame.transform.smoothscale(s, (radius * 2, radius * 2))
        if len(self._halo_glows) < 4:
            self._halo_glows[radius] = glow
        return glow

    def _build_mask(self, cx, cy, dark_alpha):
        mask = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        mask.fill((0, 0, 0, dark_alpha))
        patch = self._light_patch()
        mask.blit(patch, (cx - patch.get_width() // 2,
                          cy - patch.get_height() // 2),
                  special_flags=pygame.BLEND_RGBA_SUB)
        return mask

    # ---------- 同步 / 绘制 ----------

    def sync(self, room_index, dark_alpha=225):
        """按房间同步当前遮罩（index 或亮度变化才重建；缓存 ≤12 张防异常增长）。"""
        cx, cy = self.room_center(room_index)
        key = (int(cx), int(cy), int(dark_alpha))
        if key == self._last_key:
            return
        if key not in self._cache:
            if len(self._cache) >= 12:
                self._cache.clear()
            self._cache[key] = self._build_mask(*key)
        self._mask = self._cache[key]
        self._lcx, self._lcy = cx, cy
        self._last_key = key

    def draw(self, surface, halo=None, halos=None):
        """把光照叠加在世界内容之上（UI 层不受影响）。

        halo=(x, y, radius) 兼容：单个暖黄光环（跟随玩家）。
        halos=[(x, y, radius), ...] 可选：多个光源（主角 + 萤火虫等），
        与单 halo 等效叠加——光晕逐源提亮，遮罩副本逐源擦亮。
        """
        if self._mask is None:
            return
        sources = []
        if halo is not None:
            sources.append(halo)
        if halos:
            sources.extend(halos)
        # 1) 手术灯暖黄光晕：亮区真正变亮
        glow = self._glow_patch()
        surface.blit(glow, (self._lcx - glow.get_width() // 2,
                            self._lcy - glow.get_height() // 2))
        final = self._mask
        if sources:
            final = self._mask.copy()
            for x, y, rad in sources:
                # 2a) 各光源暖黄光晕（叠加提亮）
                surface.blit(self._halo_glow(rad), (x - rad, y - rad))
                # 2b) 遮罩副本中擦出各光源亮区（仅改副本，缓存不受影响）
                final.blit(self._halo(rad), (x - rad, y - rad),
                           special_flags=pygame.BLEND_RGBA_SUB)
        # 3) 暗遮罩压暗四周
        surface.blit(final, (0, 0))
