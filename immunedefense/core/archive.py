"""档案室「阳光书房（右半）· 暮色书房（左半）」（v3 §4 + v4 §5）。

从 Gameplay 拆出的独立房间功能对象（修正清单 A1）。设计取舍：`ArchiveRoom` 不继承
`Scene`、不占 `SceneManager` 栈，而是持有宿主 `Gameplay` 引用（`gp`）的操作对象——
档案室必须复用 Gameplay 的 HUD / 书包 / 获得横幅 / 关卡过渡机制。

v4 变化（v4祭点层.md §5）：
- 侧门离开后**不再永久封闭**：状态机 none/live/visited/opened（Gameplay 侧 `_archive_state`）
- `visited` 态门上锁；持「完整的钥匙」按 E → 消耗开门 → 进入**左半区**（side='left'）
- 左半区：暮色书房（纸片墙 + 旧书桌 + 相框），读纸 → story（archive_left）→ 出口开启
- 左半区出口 = 通关结算（te2 分支由 roomflow/ending 处理，本房间只置 `left_read`）
"""
import math
import os
import random

import pygame

import gfx
import paths
import settings
from entities.pickup import Pickup


class ArchiveRoom:
    """档案室状态与交互：进入/离开（快照回传）、家具互动、四选一拿取、
    手术刀双击隐藏项、家具碰撞、世界与侧门绘制、阳光/纸屑动画。"""

    def __init__(self, gp):
        self.gp = gp
        self.in_archive = False
        self.side = 'right'          # 'right' 阳光书房（免费一次）/ 'left' 暮色书房（钥匙）
        self.taken = None            # 已拿道具 id（拿一件，其余封存）
        self.item = None             # 本房随机到的那一件（soup/money/sweater/scalpel）
        self.wardrobe_open = False   # 医药费藏在衣柜：先开柜才能拿
        self.lamp_on = False         # 书桌台灯（可选互动）
        self.left_read = False       # 左半区：纸是否已读（读毕开出口）
        self._dbl_click_t = -1e9     # 双击主角检测（手术刀）
        self._dbl_click_n = 0
        self._stored_allies = []     # 细胞带不进记忆——寄存在宿主房
        self.dust = []               # 阳光尘埃 / 纸屑（缓飘粒子）

    # ---------- 进入 / 离开 ----------

    def enter(self):
        """进入右半（阳光书房）：记忆世界只有主角，白细胞留在外面（离开原样回归）。"""
        gp = self.gp
        gp._archive_used = True
        self._common_enter('right')
        self.item = gp.rng.choice(('soup', 'money', 'sweater', 'scalpel'))
        self._spawn_dust_dust_light()   # 阳光尘埃（金色缓浮）

    def enter_left(self):
        """进入左半（暮色书房）：需要完整钥匙（Gameplay 已消耗并置 opened 态）。"""
        gp = self.gp
        gp._archive_used = True
        self._common_enter('left')
        self.item = None
        self.left_read = False
        self._spawn_dust_dust_light(paper=True)

    def _common_enter(self, side):
        gp = self.gp
        self.side = side
        self.in_archive = True
        self.taken = None
        self.wardrobe_open = False
        self.lamp_on = False
        self._dbl_click_t = -1e9
        self._dbl_click_n = 0
        self._stored_allies = list(gp.allies)
        gp.allies = []
        gp.current_kind = 'archive'
        gp.enemies = []
        gp.projectiles = []
        gp.enemy_projectiles = []
        gp.poison_zones = []
        gp.pickups = []
        gp.room_obstacles = []
        gp.fireflies = []              # v6：档案室无萤火虫（宿主房的留在快照里）
        gp.shop_here = False
        gp.room_cleared = True
        gp.exit_open = False           # 出口请先完成本半区内容（右半：出去随时可走）
        gp.exit_kind = 'door'
        gp.exit_side = 'left'          # 返回宿主房的门（左墙）
        gp.back_side = None
        gp.floaters = []
        gp._place_player_at_entry('left')
        gp._title_banner_pending = False
        if side == 'right':
            gp.exit_open = True        # 阳光书房：拿完即走（原规则）

    def _spawn_dust_dust_light(self, paper=False):
        gp = self.gp
        if paper:
            self.dust = [[gp.rng.uniform(620, 1080), gp.rng.uniform(200, 600),
                          gp.rng.uniform(1.0, 2.2), gp.rng.uniform(-7, -13),
                          gp.rng.uniform(0, 6.28), True] for _ in range(12)]
        else:
            self.dust = [[gp.rng.uniform(600, 1080), gp.rng.uniform(200, 600),
                          gp.rng.uniform(1.0, 2.2), gp.rng.uniform(-9, -4),
                          gp.rng.uniform(0, 6.28), False] for _ in range(10)]

    def leave(self):
        """离开档案室：门状态机转移（右半→visited 上锁 / 左半→opened 敞开）；
        白细胞原封不动回到身边，回到宿主房（快照还原）。"""
        gp = self.gp
        self.in_archive = False
        was_left = (self.side == 'left')
        gp._archive_state = 'opened' if was_left else 'visited'
        gp.allies = list(self._stored_allies)   # 细胞原样回归
        state = gp.room_cache.get(gp.room.index)
        if state is not None:
            gp.roomflow.restore(state)
        else:
            gp.current_layer, gp.current_kind, gp.enemies, free_wbc = gp.room.spawn_room()
            gp.room_obstacles = gp.roomflow.build_obstacles()
            gp.pickups = gp._make_pickups(free_wbc)
            gp.fireflies = gp._spawn_fireflies()
            gp.room_cleared = False
            gp.shop_here = gp.room.roll_shop()
            gp.shop_spot = gp._shop_spot_pos()
            gp.roomflow.compute_exit_sides()
        # 从档案室回到宿主房：出现在侧门旁
        px, py = gp._archive_portal_center()
        gp.player.x, gp.player.y = px - 95, py
        for i, w in enumerate(gp.allies):
            sx, sy = gp.guide.formation_slot(i, len(gp.allies))
            w.x, w.y = gp.player.x + sx, gp.player.y + sy

    # ---------- 互动 ----------

    def _near_spot(self, spot):
        px, py = spot['pos']
        # v4 修正（2026-08-30）：互动半径 125——家具碰撞把玩家推出到离家具最近点
        # ≈ 玩家半径处；旧阈值 95 在床/衣柜（pos 在矩形内）永恒不可达
        return (self.gp.player.x - px) ** 2 + (self.gp.player.y - py) ** 2 < 125 ** 2

    def interact(self):
        """按 E：靠近家具互动（礼物拿取 / 开衣柜 / 开台灯 / 翻动被角 / 读纸）。"""
        gp = self.gp
        if self.side == 'left':
            self._interact_left()
            return
        spots = {s['item']: s for s in gp.ARCHIVE_SPOTS}
        if self._near_spot(spots['soup']):                    # 书桌
            if self.item == 'soup' and self.taken is None:
                self.take_item('soup')
            else:
                self.lamp_on = not self.lamp_on
                gp._add_floater(gp.player.x, gp.player.y - 44,
                                "台灯亮了" if self.lamp_on else "台灯熄了",
                                (0xE9, 0xC4, 0x6A) if self.lamp_on else (0x9C, 0x96, 0x88))
                gp.audio.play('click')
            return
        if self._near_spot(spots['money']):                   # 衣柜
            if not self.wardrobe_open:
                self.wardrobe_open = True
                gp._add_floater(gp.player.x, gp.player.y - 44,
                                "衣柜的门开了…", (0xC9, 0xA2, 0x27))
                gp.audio.play('chime')
            elif self.item == 'money' and self.taken is None:
                self.take_item('money')
            else:
                gp._add_floater(gp.player.x, gp.player.y - 44,
                                "衣柜里空空的…", (0x9C, 0x96, 0x88))
            return
        if self._near_spot(spots['sweater']):                 # 床
            if self.item == 'sweater' and self.taken is None:
                self.take_item('sweater')
            else:
                gp._add_floater(gp.player.x, gp.player.y - 44,
                                "被子叠得整整齐齐…", (0x9C, 0x96, 0x88))
            return

    def _interact_left(self):
        """左半区：旧书桌上的纸（按 E 阅读 → 获得横幅 archive_left → 出口开启）。"""
        gp = self.gp
        spot = next(s for s in gp.ARCHIVE_LEFT_SPOTS if s['item'] == 'paper')
        if self._near_spot(spot):
            if self.left_read:
                gp._add_floater(gp.player.x, gp.player.y - 44,
                                "纸上的字，你已经记住了。", (0x9C, 0x96, 0x88))
                return
            self.left_read = True
            gp.archive_left_read = True
            gp.exit_open = True    # 读毕：出口门开启（出门 = 通关结算，te2）
            self.start_story('archive_left')
            return
        gp._add_floater(gp.player.x, gp.player.y - 44,
                        "暮色里，只有这一页纸在等你。", (0x9C, 0x96, 0x88))

    def take_item(self, item_id):
        """拿取家人礼物：进书包 + 获得横幅（本房间只出现这一件）。"""
        gp = self.gp
        self.taken = item_id
        gp.backpack.add(item_id, gp.items_data[item_id])
        gp.pickups = [p for p in gp.pickups if p.kind != 'scalpel']
        self.start_story(item_id)

    def check_double_click(self, pos):
        """手术刀是隐藏项：本房随机到手术刀时，双击主角 3 次刀从体内掉出。"""
        gp = self.gp
        if not self.in_archive or self.side != 'right':
            return
        if self.taken is not None:
            return
        if self.item != 'scalpel' or gp.backpack.count('scalpel'):
            return
        px, py = gp.player.x, gp.player.y
        if (pos[0] - px) ** 2 + (pos[1] - py) ** 2 > (gp.player.radius + 22) ** 2:
            return
        now = pygame.time.get_ticks()
        if now - self._dbl_click_t <= 350:      # 双击完成
            self._dbl_click_n += 1
            self._dbl_click_t = -1e9
            if self._dbl_click_n == 1:
                gp._add_floater(px, py - 74, "体内传来异物的感觉…", (0x9C, 0x96, 0x88))
            elif self._dbl_click_n == 2:
                gp._add_floater(px, py - 74, "好像有什么东西…", (0x9C, 0x96, 0x88))
            else:
                gp._add_floater(px, py - 74, "手术刀掉了出来！", (0xC9, 0xA2, 0x27))
                gp.pickups.append(Pickup(px + 36, py, 'scalpel'))
                gp.audio.play('chime')
        else:
            self._dbl_click_t = now

    def start_story(self, item_id):
        """获得横幅（以撒式）：道具名 + 副题 + 逐字剧情小字（进 Gameplay 状态机）。"""
        gp = self.gp
        gp.story = {'id': item_id, 'data': gp.story_data[item_id],
                    'chars': 0, 'acc': 0.0,
                    'speed': gp.story_data.get('type_speed', 25)}
        gp.state = 'story'
        gp.audio.play('chime')

    # ---------- 每帧更新 / 碰撞 ----------

    def sync_collision(self):
        """玩家与家具的圆-矩形推出（左右两半各自列表）。"""
        p = self.gp.player
        furniture = (self.gp.ARCHIVE_LEFT_FURNITURE if self.side == 'left'
                     else self.gp.ARCHIVE_FURNITURE)
        for f in furniture:
            nx = max(f.x, min(p.x, f.x + f.w))
            ny = max(f.y, min(p.y, f.y + f.h))
            dx, dy = p.x - nx, p.y - ny
            d2 = dx * dx + dy * dy
            if d2 < p.radius ** 2 and d2 > 0:
                d = d2 ** 0.5
                push = (p.radius - d)
                p.x += dx / d * push
                p.y += dy / d * push

    def update(self, dt):
        """粒子：阳光尘埃（金色缓浮）/ 纸屑（暮色斜落），循环。"""
        gp = self.gp
        for d in self.dust:
            paper = d[5]
            if paper:
                d[0] += d[3] * 0.35
                d[1] += abs(d[3]) * 0.8
                d[4] += dt * 3.0
            else:
                d[0] += d[3] * 0.5
                d[1] += abs(d[3]) * 0.55
                d[4] += dt * 2.0
            if d[1] > gp.ARCHIVE_RECT[3] - 10:
                d[1] = gp.ARCHIVE_RECT[1] + 20
                d[0] = gp.rng.uniform(620, 1080)

    # ---------- 绘制 ----------

    def draw_world(self, world):
        """档案室：右半 = 阳光书房；左半 = 暮色书房（纸片墙 + 旧书桌 + 相框）。"""
        gp = self.gp
        if self.side == 'left':
            self._draw_left(world)
            return
        world.blit(gfx.load('bg_bedroom_1280.png'), (0, 0))
        # 家具（大比例，以撒式）
        world.blit(gfx.load('fg_bed_300.png'), (250, 330))
        world.blit(gfx.load('fg_wardrobe_190.png'), (880, 320))
        world.blit(gfx.load('fg_desk_320.png'), (490, 120))
        # 书桌台灯亮起（暖光晕）
        if self.lamp_on:
            glow = pygame.Surface((240, 240), pygame.SRCALPHA)
            pygame.draw.circle(glow, (0xFF, 0xE9, 0xA0, 34), (120, 120), 110)
            pygame.draw.circle(glow, (0xFF, 0xE9, 0xA0, 26), (120, 120), 74)
            world.blit(glow, (650 - 120, 160 - 120))
        # 衣柜：未开=关着门（闭门缝）；打开=露出暗柜与（随机到钱时）金环
        if self.wardrobe_open:
            wr = pygame.Surface((120, 150), pygame.SRCALPHA)
            pygame.draw.rect(wr, (0x2A, 0x1E, 0x10), (8, 18, 104, 128))
            world.blit(wr, (910, 356))
        # 本房随机到的那件礼物（未拿时显示在对应家具位；手术刀为隐藏项不显示；
        # 医药费要等衣柜打开才露出来）
        if self.taken is None and self.item != 'scalpel':
            spot = next(s for s in gp.ARCHIVE_SPOTS if s['item'] == self.item)
            if spot['item'] == 'money' and not self.wardrobe_open:
                label = gfx.font(14).render(spot['label'], True, (0x9C, 0x96, 0x88))
                world.blit(label, label.get_rect(center=spot['pos']))
            else:
                entry = gp.items_data[spot['item']]
                icon = gfx.load_icon_safe(entry['icon'], 44)
                cx, cy = spot['pos']
                # 椭圆投影：放在家具面/床上的视觉锚定
                shadow = pygame.Surface((40, 12), pygame.SRCALPHA)
                pygame.draw.ellipse(shadow, (0, 0, 0, 70), shadow.get_rect())
                world.blit(shadow, shadow.get_rect(center=(cx, cy + 20)))
                ring = pygame.Surface((66, 66), pygame.SRCALPHA)
                pygame.draw.circle(ring, (0xC9, 0xA2, 0x27, 40), (33, 33), 30)
                pygame.draw.circle(ring, (0xC9, 0xA2, 0x27, 150), (33, 33), 30, 2)
                world.blit(ring, (cx - 33, cy - 33))
                if icon is not None:
                    world.blit(icon, icon.get_rect(center=(cx, cy)))
                near = ((gp.player.x - cx) ** 2 + (gp.player.y - cy) ** 2) < 125 ** 2
                label = gfx.font(14, True).render("按 E 拿取" if near else spot['label'],
                                                  True, (0xC9, 0xA2, 0x27) if near
                                                  else (0x9C, 0x96, 0x88))
                world.blit(label, label.get_rect(center=(cx, cy - 40)))
        # 阳光尘埃：光带中缓慢漂浮的微小光点（近乎不可见，点缀氛围）
        for dx_, dy_, r, vy, ph, _paper in self.dust:
            flicker = 0.5 + 0.5 * math.sin(ph)
            pygame.draw.circle(world, (0xFF, 0xE9, 0xA0, int(8 + 18 * flicker)),
                               (int(dx_), int(dy_)), int(r))

    def _draw_left(self, world):
        """左半区（暮色书房）：灰蓝纸片墙 + 旧书桌 + 台灯光晕 + 相框 + 纸。"""
        gp = self.gp
        _asset = lambda name: os.path.exists(os.path.join(paths.assets_dir(), name))
        bg = gfx.load('bg_archive_left.png', (settings.WIDTH, settings.HEIGHT)) \
            if _asset('bg_archive_left.png') else None
        if bg is not None:
            world.blit(bg, (0, 0))
        else:
            # 兜底：暮色旧书房（程序化：暗墙 + 地板 + 泛黄纸片）
            world.fill((0x1E, 0x1A, 0x1E))
            base = pygame.Surface((settings.WIDTH, settings.HEIGHT))
            base.fill((0x24, 0x20, 0x26))
            for px in range(80, settings.WIDTH - 80, 48):
                pygame.draw.line(base, (0x2C, 0x28, 0x2E), (px, 110), (px, 590), 1)
            for py in range(120, 590, 48):
                pygame.draw.line(base, (0x2C, 0x28, 0x2E), (80, py), (1200, py), 1)
            world.blit(base, (0, 0))
            rnd = random.Random(20260830)
            for _ in range(26):
                px = rnd.randint(120, 1160)
                py = rnd.randint(130, 460)
                w = rnd.randint(34, 70)
                h = rnd.randint(40, 84)
                paper = pygame.Surface((w, h), pygame.SRCALPHA)
                paper.fill((0xD8, 0xD4, 0xC0, 60))
                pygame.draw.rect(paper, (0xE4, 0xDE, 0xC8, 130), paper.get_rect(), 2)
                paper.set_alpha(int(80 + rnd.randint(-20, 20)))
                world.blit(paper, (px, py))
        world.blit(gfx.load('fg_archiveshelf_180.png'), (150, 300)) \
            if _asset('fg_archiveshelf_180.png') else None
        desk = gfx.load('fg_old_desk_320.png') \
            if _asset('fg_old_desk_320.png') else None
        if desk is not None:
            world.blit(desk, (480, 130))
        # 台灯光晕（唯一光源，恒亮）
        glow = pygame.Surface((260, 260), pygame.SRCALPHA)
        pygame.draw.circle(glow, (0xF4, 0xE0, 0xA0, 40), (130, 130), 120)
        pygame.draw.circle(glow, (0xF4, 0xE0, 0xA0, 26), (130, 130), 78)
        world.blit(glow, (660 - 130, 170 - 130))
        # 旧相框（背对玩家）
        frame = gfx.load_icon_safe('fg_photo_frame_64.png', 56)
        if frame is not None:
            world.blit(frame, frame.get_rect(center=(660, 300)))
        else:
            pf = pygame.Surface((56, 68), pygame.SRCALPHA)
            pygame.draw.rect(pf, (0x6A, 0x54, 0x30), pf.get_rect(), 2)
            pygame.draw.rect(pf, (0x3A, 0x2E, 0x1A), pf.get_rect().inflate(-10, -10))
            world.blit(pf, pf.get_rect(center=(660, 300)))
        # 纸（未读时：金环 + 按 E 提示；读毕：整平）
        spot = next(s for s in gp.ARCHIVE_LEFT_SPOTS if s['item'] == 'paper')
        cx, cy = spot['pos']
        if not self.left_read:
            ring = pygame.Surface((70, 70), pygame.SRCALPHA)
            pygame.draw.circle(ring, (0xC9, 0xA2, 0x27, 60), (35, 35), 32)
            pygame.draw.circle(ring, (0xC9, 0xA2, 0x27, 170), (35, 35), 32, 2)
            world.blit(ring, (cx - 35, cy - 35))
            paper = gfx.load_icon_safe('fg_paper_64.png', 44)
            if paper is not None:
                world.blit(paper, paper.get_rect(center=(cx, cy)))
            else:
                pg = pygame.Surface((40, 50), pygame.SRCALPHA)
                pygame.draw.rect(pg, (0xE8, 0xE0, 0xCC), pg.get_rect(), 1)
                pygame.draw.rect(pg, (0xE8, 0xE0, 0xCC), pg.get_rect().inflate(-8, -8))
                world.blit(pg, pg.get_rect(center=(cx, cy)))
            near = ((gp.player.x - cx) ** 2 + (gp.player.y - cy) ** 2) < 125 ** 2
            label = gfx.font(14, True).render("按 E 阅读" if near else "一张纸",
                                              True, (0xC9, 0xA2, 0x27) if near
                                              else (0x9C, 0x96, 0x88))
            world.blit(label, label.get_rect(center=(cx, cy - 42)))
        # 纸屑缓落（灰白纸屑，比阳光尘埃明显）
        for dx_, dy_, r, vy, ph, paper in self.dust:
            if not paper:
                continue
            flicker = 0.5 + 0.5 * math.sin(ph)
            grey = int(60 + 70 * flicker)
            pygame.draw.rect(world, (grey, grey, grey + 10),
                             (int(dx_), int(dy_), max(2, int(r)), max(2, int(r))))
        # 出口提示（读毕才开门）
        if self.left_read and gp.exit_open:
            t = gfx.font(16, True).render("够了。该回去了。", True, (0xC9, 0xA2, 0x27))
            world.blit(t, t.get_rect(center=(settings.WIDTH // 2,
                                             gp.ARCHIVE_RECT[1] + 26)))

    def draw_portal(self, world, state='free'):
        """宿主房右侧墙上口：档案室侧门（free 木门 / locked 上锁 / open 敞开）。"""
        gp = self.gp
        img = gfx.load('door_wood_archive.png', (76, 122))
        W = settings.WIDTH
        world.blit(img, img.get_rect(midright=(W + 4, 150)))
        if state == 'locked':
            lock = gfx.load_icon_safe('lock_32.png', 26)
            if lock is not None:
                world.blit(lock, lock.get_rect(center=(W - 46, 150)))
        elif state == 'open':
            # 敞开：门内透出暮色微光
            hole = pygame.Surface((20, 60), pygame.SRCALPHA)
            hole.fill((0x2A, 0x22, 0x30, 180))
            world.blit(hole, hole.get_rect(midright=(W + 4, 150)))
        near = ((gp.player.x - (W - 74)) ** 2 + (gp.player.y - 150) ** 2) < 90 ** 2
        label = gfx.font(15, True).render(
            "档案室" if state != 'locked' else "档案室（上锁）", True, (0xC9, 0xA2, 0x27))
        world.blit(label, label.get_rect(center=(W - 74, 100)))
        if state == 'locked' and near:
            t = gfx.font(13).render("按 E 查看", True, (0xC9, 0xA2, 0x27))
            world.blit(t, t.get_rect(center=(W - 74, 126)))
