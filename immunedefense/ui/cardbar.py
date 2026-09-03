"""细胞卡牌栏：底部 4 个白细胞图标 + 数量角标（0 灰 / ≥1 红），点击召唤。

角标规则来自 visual_specs/color_spec.md：badge_zero #5C5C5C / badge_one #C92A2A。
"""
import pygame

import gfx
from entities.wbc import WBC_ORDER, load_cells


class CardBar:
    ICON_SIZE = 48
    SLOT_W = 64
    MARGIN_BOTTOM = 16
    MARGIN_LEFT = 16     # 卡牌栏贴左下角，给底部中央出口（门）让位

    def __init__(self, player, on_summon):
        self.player = player
        self.on_summon = on_summon  # (wbc_type) -> bool 是否召唤成功
        self.font = pygame.font.SysFont("consolas", 15, bold=True)
        self._rects = []

    def layout(self, screen_w, screen_h):
        x0 = self.MARGIN_LEFT
        y = screen_h - self.ICON_SIZE - self.MARGIN_BOTTOM
        self._rects = [pygame.Rect(x0 + i * self.SLOT_W, y, self.SLOT_W, self.ICON_SIZE)
                       for i in range(len(WBC_ORDER))]

    def handle_click(self, pos):
        """点击卡牌槽 → 召唤；返回是否命中卡牌栏。"""
        for rect, wbc_type in zip(self._rects, WBC_ORDER):
            if rect.collidepoint(pos):
                self.on_summon(wbc_type)
                return True
        return False

    def draw(self, screen):
        for i, (rect, wbc_type) in enumerate(zip(self._rects, WBC_ORDER)):
            count = self.player.cards.get(wbc_type, 0)
            img = gfx.load(load_cells()[wbc_type]['sprite'], (self.ICON_SIZE, self.ICON_SIZE))
            screen.blit(img, (rect.x + (self.SLOT_W - self.ICON_SIZE) // 2, rect.y))

            # 数量角标：图标右上角，0 灰 / ≥1 红
            cx, cy = rect.right - 12, rect.top + 12
            if count >= 1:
                fill, outline, text_color = (0xC9, 0x2A, 0x2A), (0x5E, 0x0F, 0x0F), (0xFF, 0xFF, 0xFF)
            else:
                fill, outline, text_color = (0x5C, 0x5C, 0x5C), (0x2E, 0x2E, 0x2E), (0xDC, 0xDC, 0xDC)
            pygame.draw.circle(screen, fill, (cx, cy), 9)
            pygame.draw.circle(screen, outline, (cx, cy), 9, 1)
            txt = self.font.render(str(count), True, text_color)
            screen.blit(txt, txt.get_rect(center=(cx, cy)))

            # 快捷键角标：1/2/3/4（召唤）
            key = gfx.font(13, True).render(str(i + 1), True, (0x9C, 0x96, 0x88))
            screen.blit(key, key.get_rect(bottomright=(rect.right - 3, rect.bottom - 2)))
