"""书包 UI：7 格面板（格 0 = 留念格）+ 使用/穿戴确认弹窗 + 拖拽排序 + HUD 书包指示。

交互定稿（v3道具层.md §1 + v4祭点层.md §6）：
- 按住 Q 打开（面板暂停战斗）；松开关闭
- 点击道具格 → 弹窗：图标/名称/说明 + （消耗品：用量 −/+ 与「使用」；装备：「穿戴/收起」；
  钥匙：仅查看——不可使用/丢弃）
- 弹窗内「丢弃」丢 1 个；「取消」关闭；满格拾取提示由 Gameplay 飘字
- 拖拽排序：按住左键拖到另一格松手 = 交换（点击不拖动松手 = 打开弹窗）
- 固定格（格 0）：左上角锁形图标（重开不掉落）
"""
import pygame

import gfx
import settings
from ui.panels import _veil, _draw_glow_border, PANEL_BG, GOLD, BRONZE, GOLD_HI

SLOT_W, SLOT_H = 152, 176
GAP = 16
COLS = 4

DIM = (0x9C, 0x96, 0x88)


def _load_icon(name, size):
    try:
        return gfx.load(name, (size, size), subdir='ui/icons')
    except Exception:
        return None


def _fallback_icon(surface, center, size, color):
    """图标缺失时的程序化占位（圆形 + 高光）。"""
    r = size // 2
    pygame.draw.circle(surface, color, center, r)
    pygame.draw.circle(surface, (0x1A, 0x16, 0x12), center, r, 2)
    pygame.draw.circle(surface, (0xFF, 0xFF, 0xFF), (center[0] - r // 3, center[1] - r // 3), 3)


# 道具主题色（图标缺失兜底 / 耐久条等）
ITEM_COLORS = {
    'rbc': (0xC8, 0x2A, 0x2A),
    'vaccine': (0x4A, 0xD8, 0xC4),
    'pain': (0xE8, 0x6A, 0x6A),
    'money': (0xE8, 0xB0, 0xC8),
    'soup': (0xD8, 0xA6, 0x5C),
    'sweater': (0xC8, 0x5A, 0x64),
    'scalpel': (0xD8, 0xE0, 0xE8),
    'key_left': (0xC0, 0xC8, 0xD4),
    'key_right': (0xE9, 0xC4, 0x6A),
    'key_full': (0xF4, 0xE0, 0xA0),
    'firefly': (0xE8, 0xD8, 0x5C),
}


class BackpackPanel:
    """书包面板：7 格（4×2，格 0 = 留念格）+ 道具弹窗 + 拖拽排序。"""

    def __init__(self):
        self._slot_rects = []
        self._panel_rect = None
        self.popup = None      # {'index': i, 'qty': n} | None
        self._popup_rects = {}  # {name: pygame.Rect}
        self._popup_rect = None
        self.drag_from = None  # 拖拽起点格（mousedown 记录，mouseup 结算）

    def layout(self, screen_w, screen_h):
        total_w = SLOT_W * COLS + GAP * (COLS - 1)
        x0 = (screen_w - total_w) // 2
        y0 = 128
        self._slot_rects = [pygame.Rect(x0 + (i % COLS) * (SLOT_W + GAP),
                                        y0 + (i // COLS) * (SLOT_H + GAP),
                                        SLOT_W, SLOT_H) for i in range(7)]
        pad = 26
        rows = 2
        self._panel_rect = pygame.Rect(x0 - pad, y0 - 62,
                                       total_w + pad * 2 + 8,
                                       SLOT_H * rows + GAP + 62 + 40)

    # ---------- 弹窗 ----------

    def open_popup(self, index):
        self.popup = {'index': index, 'qty': 1}

    def close_popup(self):
        self.popup = None

    # ---------- 点击（按下 / 松开） ----------

    def handle_click(self, pos, backpack):
        """MOUSEBUTTONDOWN：弹窗优先；否则记录拖拽起点。"""
        if self.popup is not None:
            if self._popup_rect is None or not self._popup_rect.collidepoint(pos):
                self.close_popup()
                return ('close',)
            idx = self.popup['index']
            slot = backpack.slots[idx] if 0 <= idx < len(backpack.slots) else None
            if slot is None:
                return None
            for name, rect in self._popup_rects.items():
                if rect.collidepoint(pos):
                    if name == 'use':
                        return ('use', idx, self.popup['qty'])
                    if name == 'discard':
                        return ('discard', idx)
                    if name == 'wear':
                        return ('wear', idx)
                    if name == 'takeoff':
                        return ('takeoff', idx)
                    if name == 'close':
                        return ('close',)
                    if name == 'qty+':
                        self.popup['qty'] = min(6, self.popup['qty'] + 1)
                        return ('qty+',)
                    if name == 'qty-':
                        self.popup['qty'] = max(1, self.popup['qty'] - 1)
                        return ('qty-',)
            return None
        for i, rect in enumerate(self._slot_rects):
            if rect.collidepoint(pos):
                self.drag_from = i if i < len(backpack.slots) else None
                return ('slot', i)
        self.drag_from = None
        return None

    def handle_release(self, pos, backpack):
        """MOUSEBUTTONUP：拖拽到别的格 = 交换；原地松开 = 打开弹窗。"""
        if self.popup is not None or self.drag_from is None:
            self.drag_from = None
            return None
        i = self.drag_from
        self.drag_from = None
        for j, rect in enumerate(self._slot_rects):
            if rect.collidepoint(pos):
                if j != i and i < len(backpack.slots) and j < len(backpack.slots):
                    return ('swap', i, j)
                if i < len(backpack.slots):
                    self.open_popup(i)
                    return ('slot', i)
                return None
        return None

    # ---------- 绘制 ----------

    def _draw_empty_slot(self, screen, rect, fixed=False):
        pygame.draw.rect(screen, (0x0C, 0x0A, 0x08), rect, border_radius=12)
        pygame.draw.rect(screen, (0x3A, 0x34, 0x2A), rect, 2, border_radius=12)
        pygame.draw.rect(screen, (0x22, 0x1E, 0x18), rect.inflate(-10, -10),
                         1, border_radius=9)
        if fixed:
            self._draw_fixed_frame(screen, rect)

    def _draw_fixed_frame(self, screen, rect):
        """留念格：左上角锁形图标（无虚线框、无说明文字）。"""
        gold = (0xC9, 0xA2, 0x27)
        # 锁形图标（左上）
        lx, ly = rect.left + 18, rect.top + 16
        pygame.draw.circle(screen, gold, (lx, ly - 3), 5, 2)
        pygame.draw.rect(screen, gold, (lx - 6, ly - 2, 12, 9), 2, border_radius=2)

    def draw(self, screen, backpack, items_data, blocked=None):
        blocked = blocked or {}
        if self._panel_rect is not None:
            _veil(screen, 150)
        p = self._panel_rect
        if p is not None:
            pygame.draw.rect(screen, PANEL_BG, p, border_radius=16)
            pygame.draw.rect(screen, GOLD, p, 3, border_radius=16)
            pygame.draw.rect(screen, (0x2A, 0x24, 0x1C), p.inflate(-10, -10),
                             1, border_radius=12)
        title = gfx.font(30, True).render("我的书包", True, settings.UI_TEXT)
        screen.blit(title, title.get_rect(center=(settings.WIDTH // 2, p.y + 22)))

        mouse = pygame.mouse.get_pos()
        for i, rect in enumerate(self._slot_rects):
            if i >= len(backpack.slots):
                self._draw_empty_slot(screen, rect, fixed=(i == 0))
                continue
            slot = backpack.slots[i]
            entry = items_data[slot['id']]
            self._draw_slot(screen, rect, slot, entry,
                            hover=rect.collidepoint(mouse),
                            blocked=blocked.get(slot['id']),
                            fixed=(i == 0))
            if i == 0:
                self._draw_fixed_frame(screen, rect)

        if self.popup is not None:
            self._draw_popup(screen, backpack, items_data, blocked)

    def _draw_slot(self, screen, rect, slot, entry, hover, blocked=None, fixed=False):
        if hover:
            _draw_glow_border(screen, rect, GOLD)
        active = slot.get('active', False)
        pygame.draw.rect(screen, PANEL_BG, rect, border_radius=12)
        border = GOLD if (hover or active or fixed) else BRONZE
        pygame.draw.rect(screen, border, rect, 3 if hover else 2, border_radius=12)
        pygame.draw.rect(screen, (0x3A, 0x32, 0x20) if hover else (0x2A, 0x24, 0x1C),
                         rect.inflate(-8, -8), 1, border_radius=10)
        # 图标
        icon = _load_icon(entry['icon'], 58)
        cx, cy = rect.centerx, rect.y + 52
        if icon is not None:
            screen.blit(icon, icon.get_rect(center=(cx, cy)))
        else:
            _fallback_icon(screen, (cx, cy), 46, ITEM_COLORS.get(slot['id'], (0x88, 0x88, 0x88)))
        # 名称
        name = gfx.font(15, True).render(entry['name'], True, settings.UI_TEXT)
        screen.blit(name, name.get_rect(center=(cx, rect.y + 108)))
        kind = entry.get('kind')
        # 数量角标（消耗品）
        if kind == 'consumable':
            bx, by = rect.right - 16, rect.top + 16
            pygame.draw.circle(screen, (0xC9, 0x2A, 0x2A), (bx, by), 10)
            pygame.draw.circle(screen, (0x5E, 0x0F, 0x0F), (bx, by), 10, 1)
            num = gfx.font(14, True).render(str(slot['count']), True, (0xFF, 0xFF, 0xFF))
            screen.blit(num, num.get_rect(center=(bx, by)))
        elif kind == 'equip':
            if slot.get('dur_max'):
                bar = pygame.Rect(rect.x + 14, rect.bottom - 26, rect.w - 28, 8)
                pygame.draw.rect(screen, (0x1A, 0x2A, 0x20), bar, border_radius=4)
                ratio = slot['dur'] / max(1, slot['dur_max'])
                pygame.draw.rect(screen, (0x4A, 0xC4, 0x58) if ratio > 0.34 else (0xC8, 0x5A, 0x3A),
                                 (bar.x, bar.y, max(2, int(bar.w * ratio)), bar.h),
                                 border_radius=4)
            label = "穿戴中" if active else "已收起"
            lc = GOLD if active else DIM
            t = gfx.font(13, True).render(label, True, lc)
            screen.blit(t, t.get_rect(center=(cx, rect.bottom - 45)))
        elif kind == 'key':
            # v4 钥匙：半钥/完整标识
            half = entry.get('key_half')
            tag = '左半' if half == 'left' else ('右半' if half == 'right' else '完整')
            t = gfx.font(13, True).render(tag, True, GOLD)
            screen.blit(t, t.get_rect(center=(cx, rect.bottom - 40)))

    def _draw_popup(self, screen, backpack, items_data, blocked=None):
        blocked = blocked or {}
        idx = self.popup['index']
        slot = backpack.slots[idx] if 0 <= idx < len(backpack.slots) else None
        if slot is None:
            self.close_popup()
            return
        entry = items_data[slot['id']]
        w, h = 400, 264
        x = (settings.WIDTH - w) // 2
        y = (settings.HEIGHT - h) // 2 - 20
        self._popup_rect = pygame.Rect(x, y, w, h)
        pw = self._popup_rect
        pygame.draw.rect(screen, PANEL_BG, pw, border_radius=14)
        pygame.draw.rect(screen, GOLD, pw, 3, border_radius=14)
        pygame.draw.rect(screen, (0x2A, 0x24, 0x1C), pw.inflate(-10, -10), 1, border_radius=11)
        self._popup_rects = {}

        # 图标 + 名称 + 说明
        icon = _load_icon(entry['icon'], 52)
        ix, iy = x + 44, y + 48
        if icon is not None:
            screen.blit(icon, icon.get_rect(center=(ix, iy)))
        else:
            _fallback_icon(screen, (ix, iy), 40, ITEM_COLORS.get(slot['id'], (0x88, 0x88, 0x88)))
        name = gfx.font(22, True).render(entry['name'], True, settings.UI_TEXT)
        screen.blit(name, (x + 84, y + 22))
        lines = _wrap(entry['desc'], 18)
        for k, line in enumerate(lines[:3]):
            dl = gfx.font(15).render(line, True, DIM)
            screen.blit(dl, (x + 84, y + 58 + k * 22))

        kind = entry.get('kind')
        if kind == 'key':
            # v4 钥匙：仅查看（不可使用/丢弃）
            cancel = pygame.Rect(x + 30, y + h - 62, 108, 40)
            self._popup_rects['close'] = cancel
            self._draw_button(screen, cancel, "取消", BRONZE)
            note = gfx.font(15).render("不可丢弃 · 不可使用（合成与开锁专用）",
                                       True, (0xC9, 0xA2, 0x27))
            screen.blit(note, (x + 150, y + h - 49))
            return
        is_consumable = kind != 'equip'

        if is_consumable:
            # 用量选择
            qx = x + 84
            qy = y + 132
            ql = gfx.font(15).render("用量", True, DIM)
            screen.blit(ql, (qx, qy + 2))
            bw = 34
            minus_rect = pygame.Rect(qx + 46, qy - 6, bw, 30)
            num_rect = pygame.Rect(qx + 46 + bw + 8, qy - 6, bw, 30)
            plus_rect = pygame.Rect(qx + 46 + bw + 8 + bw + 8, qy - 6, bw, 30)
            for label, name_, r in (("−", 'qty-', minus_rect), ("+", 'qty+', plus_rect)):
                self._popup_rects[name_] = r
                pygame.draw.rect(screen, (0x2A, 0x24, 0x1C), r, border_radius=6)
                pygame.draw.rect(screen, BRONZE, r, 2, border_radius=6)
                btxt = gfx.font(18, True).render(label, True, settings.UI_TEXT)
                screen.blit(btxt, btxt.get_rect(center=r.center))
            qn = gfx.font(18, True).render(str(self.popup['qty']), True, GOLD_HI)
            screen.blit(qn, qn.get_rect(center=num_rect.center))

            # 使用（满血/不可用时隐藏，显示原因）
            use_rect = pygame.Rect(x + 30, y + h - 62, 108, 40)
            cancel_rect = pygame.Rect(x + 150, y + h - 62, 108, 40)
            drop_rect = pygame.Rect(x + 270, y + h - 62, 100, 40)
            reason = blocked.get(slot['id'])
            if reason:
                rtxt = gfx.font(15).render(reason, True, (0xD3, 0x8A, 0x2A))
                screen.blit(rtxt, rtxt.get_rect(center=(use_rect.centerx, use_rect.centery)))
            else:
                self._popup_rects['use'] = use_rect
                self._draw_button(screen, use_rect, "使用", GOLD)
            self._popup_rects['close'] = cancel_rect
            self._draw_button(screen, cancel_rect, "取消", BRONZE)
            self._popup_rects['discard'] = drop_rect
            self._draw_button(screen, drop_rect, "丢弃", (0x8A, 0x4A, 0x3A))
        else:
            active = slot.get('active', False)
            if active:
                mine = pygame.Rect(x + 30, y + h - 62, 108, 40)
                self._popup_rects['takeoff'] = mine
                self._draw_button(screen, mine, "收起", GOLD)
            else:
                mine = pygame.Rect(x + 30, y + h - 62, 108, 40)
                self._popup_rects['wear'] = mine
                self._draw_button(screen, mine, "穿戴", GOLD)
            cancel = pygame.Rect(x + 150, y + h - 62, 108, 40)
            self._popup_rects['close'] = cancel
            self._draw_button(screen, cancel, "取消", BRONZE)
            drop = pygame.Rect(x + 270, y + h - 62, 100, 40)
            self._popup_rects['discard'] = drop
            self._draw_button(screen, drop, "丢弃", (0x8A, 0x4A, 0x3A))

    def _draw_button(self, screen, rect, text, color):
        pygame.draw.rect(screen, PANEL_BG, rect, border_radius=8)
        pygame.draw.rect(screen, color, rect, 2, border_radius=8)
        t = gfx.font(17, True).render(text, True, settings.UI_TEXT)
        screen.blit(t, t.get_rect(center=rect.center))


def _wrap(text, per_line):
    return [text[i:i + per_line] for i in range(0, len(text), per_line)]


# ---------- HUD 书包指示 ----------

def draw_bag_hud(screen, x, y, backpack):
    """左上：书包图标 + 总数 + 提示（与经验/祭点行同字体同色）。"""
    icon = _load_icon('backpack_32.png', 22)
    if icon is None:
        icon = pygame.Surface((22, 22), pygame.SRCALPHA)
        pygame.draw.rect(icon, (0x8A, 0x5A, 0x2E), (2, 6, 18, 14), border_radius=3)
        pygame.draw.rect(icon, (0x6E, 0x46, 0x22), (2, 6, 18, 5), border_radius=3)
        pygame.draw.arc(icon, (0x6E, 0x46, 0x22), (6, 0, 16, 12), 0, 180, 2)
        pygame.draw.rect(icon, (0x8A, 0x5A, 0x2E), (2, 6, 18, 14), 2, border_radius=3)
    screen.blit(icon, (x, y))
    n = backpack.total_count()
    cnt = gfx.font(18).render(f"×{n}", True, settings.UI_TEXT)
    screen.blit(cnt, (x + 26, y + 1))
    tip = gfx.font(18).render("按住 Q 打开书包", True, settings.UI_TEXT)
    screen.blit(tip, (x + 62, y + 1))
