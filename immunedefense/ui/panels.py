"""局间面板：三选一奖励 + 积分商店。"""
import pygame

import gfx
import settings
from entities.wbc import WBC_NAMES, load_cells

# 面板配色（color_spec）
PANEL_BG = (0x12, 0x0F, 0x0C)
GOLD = (0xC9, 0xA2, 0x27)
BRONZE = (0x7A, 0x6A, 0x4F)
GOLD_HI = (0xFF, 0xE9, 0xA0)


def _wrap(text, per_line):
    return [text[i:i + per_line] for i in range(0, len(text), per_line)]


def _veil(screen, alpha=190):
    veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
    veil.fill((0, 0, 0, alpha))
    screen.blit(veil, (0, 0))


def _draw_glow_border(screen, rect, color, radius=14):
    """卡片外圈柔光（悬停选中特效）。"""
    glow = pygame.Surface((rect.w + 20, rect.h + 20), pygame.SRCALPHA)
    pygame.draw.rect(glow, color + (46,), (10, 10, rect.w, rect.h), border_radius=radius + 3)
    pygame.draw.rect(glow, color + (110,), (10, 10, rect.w, rect.h), 3, border_radius=radius + 3)
    screen.blit(glow, (rect.x - 10, rect.y - 10))


def _draw_stat_glyph(screen, cx, cy, stat):
    """属性强化小图标（程序化 glyph）。"""
    if stat == 'radius':
        pygame.draw.circle(screen, (0x7F, 0xD8, 0xC4), (cx, cy), 20, 3)
        pygame.draw.circle(screen, (0x7F, 0xD8, 0xC4), (cx, cy), 5)
    elif stat == 'cap':
        pygame.draw.circle(screen, (0xC9, 0xA2, 0x27), (cx, cy), 22, 3)
        pygame.draw.line(screen, (0xC9, 0xA2, 0x27), (cx - 12, cy), (cx + 12, cy), 3)
        pygame.draw.line(screen, (0xC9, 0xA2, 0x27), (cx, cy - 12), (cx, cy + 12), 3)
    elif stat == 'speed':
        pygame.draw.polygon(screen, (0xE8, 0xE4, 0xD8),
                            [(cx - 18, cy - 2), (cx + 8, cy - 2), (cx + 8, cy - 12),
                             (cx + 22, cy + 6), (cx + 8, cy + 24), (cx + 8, cy + 14),
                             (cx - 18, cy + 14)])
    elif stat == 'maxhp':
        for dx in (-9, 9):
            pygame.draw.circle(screen, (0xD3, 0x2A, 0x2A), (cx + dx, cy - 7), 12)
        pygame.draw.polygon(screen, (0xD3, 0x2A, 0x2A),
                            [(cx - 19, cy - 2), (cx + 19, cy - 2), (cx, cy + 22)])


def _opt_icon_name(opt):
    """选项的图标名（用于统一绘制）。返回 (kind, 参数)。

    两种数据形态：奖励 'stat'+stat 键；进化直接用 kind 作为属性名（cap/maxhp/speed/radius）；
    道具奖励的 kind 即 v3 道具 id（vaccine/pain，见 data/items.json）。
    """
    k = opt.get('kind', 'stat')
    if k in ('card', 'wbc'):
        return ('card', opt.get('wbc_type'))
    if k in ('vaccine', 'pain'):
        return ('drug', k)
    return ('stat', opt.get('stat') or k)


def _opt_desc(opt):
    k = opt.get('kind')
    if k == 'card':
        return '获得 2 张对应细胞卡'
    if k == 'wbc':
        return '本局进化：攻击 +2'
    if k in ('vaccine', 'pain'):
        return '获得 1 个，存进书包（按住 Q 打开使用）'
    s = opt.get('stat') or k
    return {'radius': '引导范围更大', 'cap': '场上白细胞上限 +1',
            'speed': '移动速度更快', 'maxhp': '最大血量 +15 并回满'}.get(s, '')


class RewardPanel:
    """清房后三选一 / 升级进化三选一（参考视觉稿：图标大卡 + 悬停高亮 + 按键提示）。"""
    CARD_W, CARD_H = 300, 236
    GAP = 36

    def __init__(self):
        self.options = []
        self._rects = []
        self.title = "选择你的强化"

    def layout(self, screen_w, screen_h):
        total = self.CARD_W * 3 + self.GAP * 2
        x0 = (screen_w - total) // 2
        y = 214
        self._rects = [pygame.Rect(x0 + i * (self.CARD_W + self.GAP), y,
                                   self.CARD_W, self.CARD_H) for i in range(3)]

    def set_options(self, options):
        self.options = options

    def handle_click(self, pos):
        for rect, opt in zip(self._rects, self.options):
            if rect.collidepoint(pos):
                return opt
        return None

    def draw(self, screen):
        _veil(screen, 200)
        title = gfx.font(38, True).render(self.title, True, settings.UI_TEXT)
        screen.blit(title, title.get_rect(center=(settings.WIDTH // 2, 108)))
        mouse = pygame.mouse.get_pos()
        for i, (rect, opt) in enumerate(zip(self._rects, self.options)):
            hover = rect.collidepoint(mouse)
            self._draw_card(screen, rect, opt, hover)
            hint = gfx.font(18).render(f"按 {i + 1}", True,
                                       GOLD if hover else (0x9C, 0x96, 0x88))
            screen.blit(hint, hint.get_rect(center=(rect.centerx, rect.bottom + 26)))
        tip = gfx.font(18).render("点击选择 · 按 1/2/3 快捷选择", True, (0x9C, 0x96, 0x88))
        screen.blit(tip, tip.get_rect(center=(settings.WIDTH // 2, settings.HEIGHT - 64)))

    def _draw_card(self, screen, rect, opt, hover):
        if hover:
            _draw_glow_border(screen, rect, GOLD)
        pygame.draw.rect(screen, PANEL_BG, rect, border_radius=14)
        pygame.draw.rect(screen, GOLD if hover else BRONZE, rect,
                         3 if hover else 2, border_radius=14)
        pygame.draw.rect(screen, (0x2A, 0x24, 0x1C) if not hover else (0x3A, 0x32, 0x20),
                         rect.inflate(-8, -8), 1, border_radius=11)
        # 图标
        kind, param = _opt_icon_name(opt)
        cx, cy = rect.centerx, rect.y + 62
        if kind == 'card':
            img = gfx.load(load_cells()[param]['sprite'], (84, 84))
            screen.blit(img, img.get_rect(center=(cx, cy)))
        elif kind == 'drug':
            # 图标名沿用 items.json 的 icon 字段（数据唯一来源）
            from core.gameplay import load_items
            icon_name = load_items().get(param, {}).get('icon', 'vaccine_32.png')
            img = gfx.load(icon_name, (52, 52), subdir='ui/icons')
            screen.blit(img, img.get_rect(center=(cx, cy)))
        else:
            _draw_stat_glyph(screen, cx, cy, param)
        # 名称 + 说明
        name = gfx.font(22, True).render(opt.get('label', ''), True, settings.UI_TEXT)
        screen.blit(name, name.get_rect(center=(rect.centerx, rect.y + 140)))
        desc = _opt_desc(opt)
        if desc:
            d = gfx.font(15).render(desc, True, (0x9C, 0x96, 0x88))
            screen.blit(d, d.get_rect(center=(rect.centerx, rect.y + 172)))


class ShopPanel:
    """积分商店：买细胞卡（参考视觉稿：卡内图标+名称+说明+数量角标，价格签独立在卡下方）。"""
    ITEM_W, ITEM_H = 172, 196
    GAP = 22

    def __init__(self, prices):
        self.order = ['neutrophil', 'macrophage', 't_cell', 'nk']
        self.prices = prices   # 唯一价格源：balance.json → economy.shop_prices（由 Gameplay 传入）
        self._item_rects = []
        self._tag_rects = []
        self._leave_rect = None

    def layout(self, screen_w, screen_h):
        total = self.ITEM_W * 4 + self.GAP * 3
        x0 = (screen_w - total) // 2
        y = 235
        self._item_rects = [pygame.Rect(x0 + i * (self.ITEM_W + self.GAP), y,
                                        self.ITEM_W, self.ITEM_H) for i in range(4)]
        # 价格签：卡片正下方（点击同为购买）
        self._tag_rects = [pygame.Rect(r.centerx - 42, r.bottom + 6, 84, 30)
                           for r in self._item_rects]
        self._leave_rect = pygame.Rect(screen_w // 2 - 80, screen_h - 86, 160, 44)

    def handle_click(self, pos):
        if self._leave_rect.collidepoint(pos):
            return 'leave'
        for rect in self._item_rects:
            if rect.collidepoint(pos):
                return f'buy:{self.order[self._item_rects.index(rect)]}'
        for rect in self._tag_rects:
            if rect.collidepoint(pos):
                return f'buy:{self.order[self._tag_rects.index(rect)]}'
        return None

    def draw(self, screen, score, cards=None):
        _veil(screen, 200)
        # 标题：「积分商店」+ 金币 + 「N 分」（三段独立排版，整体不下坠）
        t1 = gfx.font(36, True).render("积分商店", True, GOLD)
        t2 = gfx.font(36, True).render(f"{score} 分", True, GOLD_HI)
        coin = gfx.load('coin_score.png', (30, 30), subdir='ui/icons')
        total_w = t1.get_width() + 14 + 30 + 14 + t2.get_width()
        x0 = (settings.WIDTH - total_w) // 2
        screen.blit(t1, (x0, 150 - t1.get_height() // 2))
        screen.blit(coin, coin.get_rect(midleft=(x0 + t1.get_width() + 14, 150)))
        screen.blit(t2, (x0 + t1.get_width() + 14 + 30 + 14, 150 - t2.get_height() // 2))
        mouse = pygame.mouse.get_pos()
        for i, (rect, rect2, wtype) in enumerate(zip(self._item_rects, self._tag_rects,
                                                     self.order)):
            afford = score >= self.prices[wtype]
            hover = rect.collidepoint(mouse) or rect2.collidepoint(mouse)
            count = (cards or {}).get(wtype, 0)
            self._draw_card(screen, rect, rect2, wtype, count, afford, hover)
        pygame.draw.rect(screen, PANEL_BG, self._leave_rect, border_radius=8)
        pygame.draw.rect(screen, GOLD, self._leave_rect, 2, border_radius=8)
        lv = gfx.font(22, True).render("离开", True, settings.UI_TEXT)
        screen.blit(lv, lv.get_rect(center=self._leave_rect.center))

    def _draw_card(self, screen, rect, tag_rect, wtype, count, afford, hover):
        if hover:
            _draw_glow_border(screen, rect, GOLD)
        pygame.draw.rect(screen, PANEL_BG, rect, border_radius=12)
        pygame.draw.rect(screen, GOLD if hover else (BRONZE if afford else (0x4A, 0x44, 0x3A)),
                         rect, 3 if hover else 2, border_radius=12)
        pygame.draw.rect(screen, (0x3A, 0x32, 0x20) if hover else (0x2A, 0x24, 0x1C),
                         rect.inflate(-8, -8), 1, border_radius=10)
        # 大图标（沿用原版细胞图标）
        img = gfx.load(load_cells()[wtype]['sprite'], (78, 78))
        screen.blit(img, img.get_rect(center=(rect.centerx, rect.y + 58)))
        # 名称 + 说明
        name = gfx.font(20, True).render(f"{WBC_NAMES[wtype]}卡", True, settings.UI_TEXT)
        screen.blit(name, name.get_rect(center=(rect.centerx, rect.y + 132)))
        desc = gfx.font(14).render("召唤一只白细胞", True, (0x9C, 0x96, 0x88))
        screen.blit(desc, desc.get_rect(center=(rect.centerx, rect.y + 158)))
        # 数量角标（右上，0 灰 / ≥1 红）
        cx, cy = rect.right - 16, rect.top + 16
        if count >= 1:
            fill, outline, tc = (0xC9, 0x2A, 0x2A), (0x5E, 0x0F, 0x0F), (0xFF, 0xFF, 0xFF)
        else:
            fill, outline, tc = (0x5C, 0x5C, 0x5C), (0x2E, 0x2E, 0x2E), (0xDC, 0xDC, 0xDC)
        pygame.draw.circle(screen, fill, (cx, cy), 10)
        pygame.draw.circle(screen, outline, (cx, cy), 10, 1)
        num = gfx.font(14, True).render(str(count), True, tc)
        screen.blit(num, num.get_rect(center=(cx, cy)))
        # 价格签（卡下方独立）
        tag = gfx.load('price_tag_afford.png' if afford else 'price_tag_poor.png',
                       (84, 30), subdir='ui/icons')
        screen.blit(tag, tag.get_rect(center=tag_rect.center))
        price = gfx.font(16, True).render(f"{self.prices[wtype]} 分", True,
                                          GOLD if afford else (0x9C, 0x96, 0x88))
        screen.blit(price, price.get_rect(center=(tag_rect.centerx - 2, tag_rect.centery)))


class DeathPanel:
    """死亡结算：本局数据 + 「前往祭坛」（记忆/实物兑换）+ 重开。"""
    def __init__(self):
        self._restart_rect = None
        self._altar_rect = None

    def layout(self, screen_w, screen_h):
        # 整组内容（标题→按钮）居中收拢：按钮不再贴屏幕底
        self._altar_rect = pygame.Rect(screen_w // 2 - 320, 470, 200, 50)
        self._restart_rect = pygame.Rect(screen_w // 2 + 120, 470, 200, 50)

    def handle_click(self, pos):
        if self._altar_rect.collidepoint(pos):
            return 'altar'
        if self._restart_rect.collidepoint(pos):
            return 'restart'
        return None

    def draw(self, screen, score, level, offering, run_offering=0):
        _veil(screen, 220)                                 # 加深背景，弱化透出的游戏画面
        cx = settings.WIDTH // 2
        # 整组数据向屏幕中央收拢（紧凑布局，标题→按钮一体居中）
        # 标题
        t = gfx.font(44, True).render("你倒下了", True, settings.UI_HP)
        screen.blit(t, t.get_rect(center=(cx, 178)))
        # 金色装饰线（标题与数据分隔）
        pygame.draw.line(screen, (0xC9, 0xA2, 0x27), (cx - 70, 220), (cx + 70, 220), 1)
        # 得分 / 等级
        s = gfx.font(22).render(f"得分 {score} · 等级 {level}", True, settings.UI_TEXT)
        screen.blit(s, s.get_rect(center=(cx, 250)))
        # 祭点（视觉焦点：加大字号 + 金色）
        o = gfx.font(40, True).render(f"祭点 {offering}", True, (0xE9, 0xC4, 0x6A))
        screen.blit(o, o.get_rect(center=(cx, 312)))
        if run_offering:
            ro = gfx.font(18).render(f"本局新增 +{run_offering}（牺牲的记忆）",
                                     True, (0x9C, 0x96, 0x88))
            screen.blit(ro, ro.get_rect(center=(cx, 356)))
        # 故事结语（与前后紧凑衔接）
        sub = gfx.font(20).render("—— 记忆会留下来 ——", True, (0x6A, 0x64, 0x58))
        screen.blit(sub, sub.get_rect(center=(cx, 406)))
        # 按钮（紧贴内容组下方，居中对称）
        for rect, label, key in ((self._altar_rect, "前往祭坛", 'altar'),
                                 (self._restart_rect, "重开", 'restart')):
            pygame.draw.rect(screen, (0x12, 0x0F, 0x0C), rect, border_radius=8)
            pygame.draw.rect(screen, (0xC9, 0xA2, 0x27), rect, 2, border_radius=8)
            rb = gfx.font(22, True).render(label, True, settings.UI_TEXT)
            screen.blit(rb, rb.get_rect(center=rect.center))


class CapturePanel:
    """萤火虫捕捉确认弹窗：图标 + 名称 + 说明 + [捕捉] / [取消]。

    确认式（用户定稿）：点击萤火虫弹出，确认才进背包；取消则关闭，
    倒计时继续（6s 窗口只随战斗推进，弹窗打开时暂停战斗，即暂停计时）。
    定稿 v6.1：弹窗内不再显示「倒计时 X.Xs」文字（压缩为名称下方的空间）。
    """

    W, H = 400, 240

    def __init__(self):
        self._panel = None
        self._capture_rect = None
        self._cancel_rect = None

    def layout(self, screen_w, screen_h):
        x = (screen_w - self.W) // 2
        y = (screen_h - self.H) // 2 - 24
        self._panel = pygame.Rect(x, y, self.W, self.H)
        self._capture_rect = pygame.Rect(x + 36, y + self.H - 66, 130, 42)
        self._cancel_rect = pygame.Rect(x + 36 + 140, y + self.H - 66, 130, 42)

    def handle_click(self, pos):
        if self._capture_rect is not None and self._capture_rect.collidepoint(pos):
            return 'capture'
        if self._cancel_rect is not None and self._cancel_rect.collidepoint(pos):
            return 'cancel'
        return None

    def draw(self, screen, entry):
        _veil(screen, 150)
        p = self._panel
        pygame.draw.rect(screen, PANEL_BG, p, border_radius=14)
        pygame.draw.rect(screen, GOLD, p, 3, border_radius=14)
        pygame.draw.rect(screen, (0x2A, 0x24, 0x1C), p.inflate(-10, -10),
                         1, border_radius=11)
        # 图标 + 名称
        icon = gfx.load_icon_safe(entry['icon'], 56)
        ix, iy = p.x + 48, p.y + 48
        if icon is not None:
            screen.blit(icon, icon.get_rect(center=(ix, iy)))
        else:
            pygame.draw.circle(screen, (0xE8, 0xD8, 0x5C), (ix, iy), 24)
        name = gfx.font(24, True).render(entry['name'], True, settings.UI_TEXT)
        screen.blit(name, (p.x + 92, p.y + 24))
        # 说明（两行）
        for k, line in enumerate(_wrap(entry['desc'], 18)[:2]):
            dl = gfx.font(15).render(line, True, (0x9C, 0x96, 0x88))
            screen.blit(dl, (p.x + 92, p.y + 62 + k * 22))
        # 按钮
        for rect, label, color in ((self._capture_rect, "捕捉", GOLD),
                                   (self._cancel_rect, "取消", BRONZE)):
            pygame.draw.rect(screen, PANEL_BG, rect, border_radius=8)
            pygame.draw.rect(screen, color, rect, 2, border_radius=8)
            bt = gfx.font(19, True).render(label, True, settings.UI_TEXT)
            screen.blit(bt, bt.get_rect(center=rect.center))
