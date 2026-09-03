"""拾取物：游离白细胞（得卡）、宝箱（掉消耗品道具）、红细胞/止痛药/预防针（进书包）
与护盾道具。

贴图来自 assets/ui/icons/（gen_shop_icons.py 程序化生成）；缺图回退程序化绘制。
"""
import pygame

import gfx
from entities.wbc import load_cells

# v3 掉落池/档案室拾取物：kind → (图标名, 兜底圆色)
ITEM_ICONS = {
    'rbc': ('rbc_48.png', (0xC8, 0x2A, 0x2A)),
    'pain': ('drug_pain_32.png', (0xE8, 0x6A, 0x6A)),
    'vaccine': ('vaccine_32.png', (0x4A, 0xD8, 0xC4)),
    'scalpel': ('scalpel_48.png', (0xD8, 0xE0, 0xE8)),
    'key_left': ('key_left_48.png', (0xC0, 0xC8, 0xD4)),
    'key_right': ('key_right_48.png', (0xE9, 0xC4, 0x6A)),
    'key_full': ('key_full_48.png', (0xF4, 0xE0, 0xA0)),
}


def _icon(name, size):
    """加载图标，失败返回 None（调用方回退程序化绘制）。"""
    try:
        return gfx.load(name, (size, size), subdir='ui/icons')
    except Exception:
        return None


class Pickup:
    """走上去即拾取。kind: 'wbc' | 'chest' | 'rbc'·'pain'·'vaccine'（进书包） | 'shield'。"""
    RADIUS = 14

    def __init__(self, x, y, kind, wbc_type=None):
        self.x = float(x)
        self.y = float(y)
        self.radius = self.RADIUS
        self.kind = kind
        self.wbc_type = wbc_type
        self.collected = False

    def dist_to(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5

    def draw(self, screen):
        if self.kind == 'wbc':
            img = gfx.load(load_cells()[self.wbc_type]['sprite'], (32, 32))
            screen.blit(img, img.get_rect(center=(int(self.x), int(self.y))))
            pygame.draw.circle(screen, (0xC9, 0xA2, 0x27),
                               (int(self.x), int(self.y)), self.radius + 7, 1)
        elif self.kind == 'chest':
            img = _icon('chest_48.png', 44)
            if img is not None:
                screen.blit(img, img.get_rect(center=(int(self.x), int(self.y))))
                return
            pygame.draw.rect(screen, (0x7A, 0x6A, 0x4F),
                             (self.x - 15, self.y - 11, 30, 22), border_radius=4)
            pygame.draw.rect(screen, (0xC9, 0xA2, 0x27),
                             (self.x - 15, self.y - 11, 30, 22), 2, border_radius=4)
            pygame.draw.line(screen, (0xC9, 0xA2, 0x27),
                             (self.x, self.y - 11), (self.x, self.y + 11), 2)
        elif self.kind in ITEM_ICONS:
            icon, color = ITEM_ICONS[self.kind]
            img = _icon(icon, 40)
            if img is not None:
                screen.blit(img, img.get_rect(center=(int(self.x), int(self.y))))
                return
            pygame.draw.circle(screen, color, (int(self.x), int(self.y)), self.radius + 2)
            pygame.draw.circle(screen, (0xFF, 0xFF, 0xFF),
                               (int(self.x) - 3, int(self.y) - 3), 4)
        else:  # 'shield' 护盾道具：蓝色盾环
            img = _icon('shield_pickup_48.png', 40)
            if img is not None:
                screen.blit(img, img.get_rect(center=(int(self.x), int(self.y))))
                return
            pygame.draw.circle(screen, (0x3A, 0x8A, 0xE8),
                               (int(self.x), int(self.y)), self.radius + 2, 2)
            pygame.draw.circle(screen, (0x7A, 0xC4, 0xFF),
                               (int(self.x), int(self.y)), self.radius - 2)
