"""图鉴：遭遇敌人解锁条目，未遇见的显示为锁定「？？？」。

敌人条目键 = 类名小写（Cancer→cancer, Variant→variant, EliteRage→eliterage ...）。
"""
import pygame

import gfx
import settings


BESTIARY = [
    {'key': 'cancer', 'name': '癌细胞', 'sprite': 'enemy_cancer_48.png',
     'desc': '普通小怪。睡眠态每 12 秒分裂一次，攻击态不分裂。'},
    {'key': 'variant', 'name': '变异细胞', 'sprite': 'enemy_variant_96.png',
     'desc': '伪装成宿主细胞。T 细胞标记前无法被标定集火。'},
    {'key': 'eliterage', 'name': '狂暴精英', 'sprite': 'enemy_elite_rage_96.png',
     'desc': '高速高攻，冲脸型精英。'},
    {'key': 'eliteshield', 'name': '护盾精英', 'sprite': 'enemy_elite_shield_96.png',
     'desc': '带护盾，需先破盾再掉血。'},
    {'key': 'elitesummoner', 'name': '召唤精英', 'sprite': 'enemy_elite_summoner_96.png',
     'desc': '醒着时每隔 8 秒召唤一只小怪。'},
    {'key': 'bosscore', 'name': '癌变核心', 'sprite': 'enemy_boss_144.png',
     'desc': 'BOSS。400 血，战斗中每 6 秒分裂出一只变异体。'},
]


class BestiaryPanel:
    CARD_W, CARD_H = 170, 150
    GAP = 20
    COLS = 3

    def __init__(self):
        self.selected = None
        self._card_rects = []

    def layout(self, screen_w, screen_h):
        total_w = self.COLS * self.CARD_W + (self.COLS - 1) * self.GAP
        rows = (len(BESTIARY) + self.COLS - 1) // self.COLS
        total_h = rows * self.CARD_H + (rows - 1) * self.GAP
        x0 = (screen_w - total_w) // 2
        y0 = (screen_h - total_h) // 2 - 40
        self._card_rects = []
        for i in range(len(BESTIARY)):
            r, c = divmod(i, self.COLS)
            self._card_rects.append(pygame.Rect(
                x0 + c * (self.CARD_W + self.GAP),
                y0 + r * (self.CARD_H + self.GAP),
                self.CARD_W, self.CARD_H))

    def handle_click(self, pos, discovered):
        for rect, entry in zip(self._card_rects, BESTIARY):
            if rect.collidepoint(pos):
                if entry['key'] in discovered:
                    self.selected = entry['key']
                return True
        return False

    def draw(self, screen, discovered):
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 180))
        screen.blit(veil, (0, 0))

        title = gfx.font(40, True).render("敌人图鉴 · Tab 关闭", True, settings.UI_TEXT)
        screen.blit(title, title.get_rect(center=(settings.WIDTH // 2, 52)))

        for rect, entry in zip(self._card_rects, BESTIARY):
            self._draw_card(screen, rect, entry, entry['key'] in discovered)

        if self.selected is not None:
            entry = next(e for e in BESTIARY if e['key'] == self.selected)
            self._draw_detail(screen, entry)

    def _draw_card(self, screen, rect, entry, known):
        pygame.draw.rect(screen, (0x12, 0x0F, 0x0C), rect, border_radius=12)
        border = (0xC9, 0xA2, 0x27) if known else (0x5C, 0x5C, 0x5C)
        pygame.draw.rect(screen, border, rect, 2, border_radius=12)
        if known:
            img = gfx.load(entry['sprite'], (72, 72))
            screen.blit(img, img.get_rect(center=(rect.centerx, rect.y + 52)))
            name = gfx.font(20, True).render(entry['name'], True, settings.UI_TEXT)
            screen.blit(name, name.get_rect(center=(rect.centerx, rect.bottom - 22)))
        else:
            q = gfx.font(30, True).render("？？？", True, (0x9C, 0x96, 0x88))
            screen.blit(q, q.get_rect(center=rect.center))
            lock = gfx.font(16).render("未发现", True, (0x9C, 0x96, 0x88))
            screen.blit(lock, lock.get_rect(center=(rect.centerx, rect.bottom - 22)))

    def _draw_detail(self, screen, entry):
        panel = pygame.Rect(settings.WIDTH // 2 - 340, settings.HEIGHT - 130, 680, 110)
        pygame.draw.rect(screen, (0x12, 0x0F, 0x0C), panel, border_radius=10)
        pygame.draw.rect(screen, (0x7A, 0x6A, 0x4F), panel, 2, border_radius=10)
        name = gfx.font(22, True).render(entry['name'], True, (0xC9, 0xA2, 0x27))
        screen.blit(name, (panel.x + 16, panel.y + 12))
        y = panel.y + 48
        for line in _wrap(entry['desc'], 32):
            txt = gfx.font(18).render(line, True, settings.UI_TEXT)
            screen.blit(txt, (panel.x + 16, y))
            y += 26


def _wrap(text, per_line=32):
    return [text[i:i + per_line] for i in range(0, len(text), per_line)]
