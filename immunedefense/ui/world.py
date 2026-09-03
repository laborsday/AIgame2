"""ui/world.py：世界层渲染（A3.3，自 Gameplay 外迁）——背景/墙体、通道门与出口、
房内商店台、层际标题布幡、过渡黑幕。

A4 分层硬约束：本模块只读 Gameplay 状态并绘制，不改任何游戏状态字段；
持有宿主 Gameplay 引用（gp），渲染缓存（墙影/管口旋转图/标题布幡）随对象保留。
"""
import random

import pygame

import gfx
import settings


class WorldRenderer:
    """战斗世界渲染器：Gameplay.render 只调它的 4 个公开入口。"""

    def __init__(self, gp):
        self.gp = gp
        self._wall_shadow_surf = None     # 墙带内缘柔影缓存
        self._portal_img_cache = {}       # (side, open, 墙变体) → 旋转后管口图
        self._title_banner_cache = {}     # 标题布幡缓存（按文本）

    # ---------- 公开入口 ----------

    def draw_background(self, world):
        """地板 + 组织切面墙（按层 × 房型选变体）。档案室走 ArchiveRoom.draw_world。"""
        gp = self.gp
        if gp.archive.in_archive:
            gp.archive.draw_world(world)
            return
        if gp.current_kind == 'start':
            # 初始房：正常健康肝细胞地板（与战斗层病变/癌变形成明暗对照）
            bg = gfx.load('bg_cell_floor_start.png', (settings.WIDTH, settings.HEIGHT))
            world.blit(bg, (0, 0))
            # 地板玩法说明（以撒地下室式蚀刻画，gen_start_floor.py 生成）
            world.blit(gfx.load('start_floor_markings.png'), (0, 0))
        else:
            layer_files = {
                1: 'bg_cell_floor_upgraded.png',
                2: 'bg_cell_floor_layer2.png',
                3: 'bg_cell_floor_layer3.png',
            }
            bg_path = layer_files.get(gp.current_layer, 'bg_cell_floor_upgraded.png')
            bg = gfx.load(bg_path, (settings.WIDTH, settings.HEIGHT))
            world.blit(bg, (0, 0))
        # 组织切面墙（按层 × 房型选变体；左右条带只覆盖中部，角落由上下条带负责）
        v = self._wall_variant()
        W, H = settings.WIDTH, settings.HEIGHT
        world.blit(gfx.load(f'wall_{v}_left.png'), (0, gp.WALL_T))
        world.blit(gfx.load(f'wall_{v}_right.png'), (W - gp.WALL_T, gp.WALL_T))
        world.blit(gfx.load(f'wall_{v}_top.png'), (0, 0))
        world.blit(gfx.load(f'wall_{v}_bottom.png'), (0, H - gp.WALL_T))
        # 墙角：两墙面 45° 斜切拼接（画框式 miter，预生成 corner 贴图，覆盖条带端部）
        for corner, pos in (("tl", (0, 0)), ("tr", (W - gp.WALL_T, 0)),
                            ("bl", (0, H - gp.WALL_T)),
                            ("br", (W - gp.WALL_T, H - gp.WALL_T))):
            world.blit(gfx.load(f'wall_{v}_corner_{corner}.png'), pos)
        world.blit(self._wall_shadow(), (0, 0))

    def draw_exit(self, world):
        """通道：前进门户（清房后开）+ 返回口（始终开放）+ 档案室侧门（四态）+ 告别之门。"""
        gp = self.gp
        self._draw_portal(world, gp.exit_side, gp.exit_open, True)
        if gp.back_side:
            self._draw_portal(world, gp.back_side, True, False)
        # v4 §5.3 档案室门：live（清房开放）/ visited（上锁）/ opened（敞开）
        if not gp.archive.in_archive and gp._archive_host == gp.room.index:
            st = gp._archive_state
            if st == 'live':   # [演示临时] 不清房也显示侧门（演示后改回 and gp.room_cleared）
                gp.archive.draw_portal(world, 'free')
            elif st == 'visited':
                gp.archive.draw_portal(world, 'locked')
            elif st == 'opened':
                gp.archive.draw_portal(world, 'open')
        # v4 §5.4 BOSS 战后：告别之门（金色漩涡覆盖前进门户，清房后常驻）
        if gp.current_kind == 'boss' and gp.room_cleared:
            self._draw_final_portal(world)

    def _draw_final_portal(self, world):
        """告别之门：金色漩涡 + 浮尘 + 提示（走进 = 结算，与返回口并存）。"""
        gp = self.gp
        W, H = settings.WIDTH, settings.HEIGHT
        cx, cy = W // 2, H - 30
        try:
            img = gfx.load('portal_final.png', (96, 60), subdir='ui/icons')
        except Exception:
            img = None
        if img is not None:
            world.blit(img, img.get_rect(midbottom=(cx, H)))
        else:
            # 兜底：程序化金色漩涡（同心椭圆渐亮）
            for rx, ry, a in ((46, 26, 40), (36, 20, 60),
                              (26, 14, 90), (16, 9, 130), (7, 4, 190)):
                pyg = pygame.Surface((rx * 2 + 2, ry * 2 + 2), pygame.SRCALPHA)
                pygame.draw.ellipse(pyg, (0xF4, 0xE0, 0xA0, a), pyg.get_rect(), 3)
                world.blit(pyg, pyg.get_rect(center=(cx, cy)))
        t = gfx.font(15, True).render("……该回去了。", True, (0xC9, 0xA2, 0x27))
        world.blit(t, t.get_rect(center=(cx, cy - 58)))

    def draw_shop_stand(self, world):
        """房内商店台：本房刷台子时画在房间角落，清房后亮金色、靠近提示按 E。"""
        gp = self.gp
        if not gp.shop_here:
            return
        x, y = gp.shop_spot
        img = gfx.load('shop_stand_open.png',   # [演示临时] 不清房也亮台子（演示后改回按 room_cleared 切换）
                       (96, 96), subdir='ui/icons')
        world.blit(img, img.get_rect(center=(x, y - 42)))
        if True:   # [演示临时] 靠近就提示（演示后改回 gp.room_cleared）
            near = (gp.player.x - x) ** 2 + (gp.player.y - y) ** 2 < 80 ** 2
            label = '按 E 打开商店' if near else '商店'
            t = gfx.font(14, True).render(label, True, (0xC9, 0xA2, 0x27))
        else:
            t = gfx.font(14).render('清房后开放', True, (0x9C, 0x96, 0x88))
        world.blit(t, t.get_rect(center=(x, y - 92)))

    def draw_transition(self, screen):
        """过渡：层际标题布幡 或 淡出/淡入黑幕。"""
        gp = self.gp
        if gp.transition_phase == 'title':
            self._draw_layer_title(screen)
            return
        if gp.transition_phase == 'out':
            a = int(255 * (1 - gp.transition_t / 0.45))
        else:
            a = int(255 * (gp.transition_t / 0.4))
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, max(0, min(255, a))))
        screen.blit(veil, (0, 0))

    # ---------- 内部绘制 ----------

    def _wall_variant(self):
        """按（层 × 房型）选墙 / 门变体（视觉交接 walls_spec.md）。"""
        kind, layer = self.gp.current_kind, self.gp.current_layer
        if kind == 'start':
            return 'start'                     # 初始房：正常健康肝组织
        if kind == 'boss':
            return 'boss_l3'                   # 癌变血肉
        if kind == 'elite':
            return 'elite_l%d' % min(max(layer, 2), 3)   # 炎症 / 癌变组织
        return 'normal_l%d' % min(layer, 2)    # 表层 / 深层组织

    def _wall_shadow(self):
        """墙带内缘的柔和投影（缓存表面，静态）。"""
        s = self._wall_shadow_surf
        if s is None:
            gp = self.gp
            w, h = settings.WIDTH, settings.HEIGHT
            s = pygame.Surface((w, h), pygame.SRCALPHA)
            steps, step_h = 5, 3
            for i in range(steps):
                a = max(0, int(66 * (1 - i / steps)))
                off = gp.WALL_T + i * step_h
                pygame.draw.rect(s, (0, 0, 0, a), (0, off, w, step_h))
                pygame.draw.rect(s, (0, 0, 0, a), (0, h - gp.WALL_T - (i + 1) * step_h, w, step_h))
                pygame.draw.rect(s, (0, 0, 0, a), (off, 0, step_h, h))
                pygame.draw.rect(s, (0, 0, 0, a), (w - gp.WALL_T - (i + 1) * step_h, 0, step_h, h))
            self._wall_shadow_surf = s
        return s

    def _portal_image(self, side, open_):
        """通道管口 = 血管道 45° 斜剖面（椭圆开口 + 隧道纵深），随墙变体配色。

        - 同层平级（左/右）与层际（上/下）同一剖面语言，旋转到对应墙位
        - 基础朝向：隧道向右（右墙）；旋转映射 right=0 / left=180 / down=-90 / up=90
        - 旋转结果缓存（每帧不重复分配）
        """
        v = self._wall_variant()
        key = (side, open_, v)
        img = self._portal_img_cache.get(key)
        if img is None:
            suffix = '' if open_ else '_closed'
            base = gfx.load(f'door_oblique_{v}{suffix}.png', (126, 73))   # 缩小 30%
            rot = {'right': 0, 'left': 180, 'down': -90, 'up': 90}[side]
            img = pygame.transform.rotate(base, rot) if rot else base
            self._portal_img_cache[key] = img
        return img

    def _draw_portal(self, world, side, open_, is_forward):
        gp = self.gp
        img = self._portal_image(side, open_)
        W, H = settings.WIDTH, settings.HEIGHT
        if side == 'down':
            rect = img.get_rect(midbottom=(W // 2, H))
        elif side == 'up':
            rect = img.get_rect(midtop=(W // 2, 0))
        elif side == 'right':
            rect = img.get_rect(midright=(W, H // 2))
        elif gp.archive.in_archive and side == 'left':
            # 档案室出口：竖式木门（非管道剖面；镜像翻转朝向房间）
            wood = gfx.load('door_wood_archive.png', (76, 122))
            wood = pygame.transform.flip(wood, True, False)
            world.blit(wood, wood.get_rect(midleft=(gp.ARCHIVE_RECT[0] - 34, H // 2)))
            return
        else:
            rect = img.get_rect(midleft=(0, H // 2))
        world.blit(img, rect)
        if is_forward and not open_:
            cx, cy = gp._portal_center(side)
            ox, oy = {'right': (-84, 0), 'left': (84, 0),
                      'down': (0, -78), 'up': (0, 72)}[side]
            t = gfx.font(16).render("清空房间后开启", True, (0x9C, 0x96, 0x88))
            world.blit(t, t.get_rect(center=(cx + ox, cy + oy)))

    def _make_title_banner(self, text):
        """以撒式标题布幡：横挂深色条幅 + 撕裂边缘 + 墨渍 + 白字黑描边。"""
        if text in self._title_banner_cache:
            return self._title_banner_cache[text]
        w, h = 880, 100
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        rng = random.Random(hash(text) & 0xFFFF)
        # 主体轮廓：顶/底锯齿 + 左右撕裂端
        base = (0x1E, 0x14, 0x0C)
        dark = (0x12, 0x0C, 0x06)
        top, bottom = [], []
        steps = 22
        for i in range(steps + 1):
            x = 14 + (w - 28) * i / steps
            top.append((x, 16 + rng.randint(-5, 5)))
            bottom.append((w - 14 - (w - 28) * i / steps, h - 18 + rng.randint(-5, 5)))
        pts = (top + [(w - 4, h - 30), (w - 18, h - 8), (w - 8, h - 46)]
               + bottom + [(8, h - 52), (16, h - 10), (4, h - 34)])
        pygame.draw.polygon(s, base, pts)
        # 内部渐暗（中段更暗，布幅褶皱感）
        for k in range(3):
            pygame.draw.line(s, (0x16, 0x0F, 0x08, 60),
                             (30, 26 + k * 22), (w - 30, 26 + k * 22), 3)
        # 墨渍斑点（小幅随机，深色）
        for _ in range(9):
            sx = rng.randint(30, w - 30)
            sy = rng.randint(24, h - 26)
            r = rng.randint(4, 12)
            pygame.draw.circle(s, dark + (70,), (sx, sy), r)
            pygame.draw.circle(s, dark + (50,), (sx + rng.randint(-8, 8), sy + rng.randint(-7, 7)),
                               max(2, r // 2))
        # 两端撕裂翻角
        for ex, ey, flip in ((4, 30, 1), (w - 4, 60, -1)):
            pygame.draw.polygon(s, dark + (180,),
                                [(ex, ey), (ex + 16 * flip, ey - 6), (ex + 6 * flip, ey + 14)])
        # 白字黑描边（以撒式：粗白体）
        f = gfx.font(46, True)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (2, 2), (-2, -2)):
            sh = f.render(text, True, (0x0A, 0x06, 0x02))
            s.blit(sh, (w // 2 - sh.get_width() // 2 + dx, h // 2 - sh.get_height() // 2 + dy))
        t = f.render(text, True, (0xF2, 0xEA, 0xDC))
        s.blit(t, t.get_rect(center=(w // 2, h // 2)))
        self._title_banner_cache[text] = s
        return s

    def _draw_layer_title(self, screen):
        """层际标题（以撒式布幡·无整页黑幕）：布幡切在房间正中央，淡入→淡出，游戏静止。"""
        gp = self.gp
        p = 1.0 - gp.transition_t / gp.TITLE_SECONDS    # 0 → 1
        a = min(1.0, p / 0.15, max(0.0, (1.0 - p) / 0.22))  # 淡入快、淡出慢
        a = max(0.0, a)
        title = '档案室' if gp.archive.in_archive \
            else gp.LAYER_TITLES.get(gp.current_layer, '')
        if not title:
            return
        banner = self._make_title_banner(title)
        banner.set_alpha(int(255 * a))
        screen.blit(banner, banner.get_rect(center=(settings.WIDTH // 2,
                                                    settings.HEIGHT // 2 - 40)))
        if p > 0.35:
            hint = gfx.font(18).render("点击继续", True, (0x9C, 0x96, 0x88))
            hint.set_alpha(int(200 * a))
            screen.blit(hint, hint.get_rect(center=(settings.WIDTH // 2,
                                                    settings.HEIGHT // 2 + 48)))
