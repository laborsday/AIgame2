"""祭坛 · 记忆之匣（v4 祭点层 §2）：主菜单 / 死亡结算 / 通关结算三入口的独立场景。

- 双 tab：记忆（buff 类 13 项，分档位 + 里程碑解锁）/ 实物（道具类：左半钥匙）
- 记忆购买 → next_run_buffs（下一局生效并清空）；实物购买 → pending_physical（下一局开局入包）
- 覆盖在 Gameplay 之上（push）时 to_back=True：关闭即弹出回原面板；
  从结局 switch 进入（to_back=False）：关闭回主菜单。
"""
import json
import os

import pygame

import gfx
import paths
import settings
from core.scene import Scene
from systems.meta import load_meta, save_meta
from entities.wbc import load_cells

SHOP_PATH = os.path.join(paths.data_dir(), "offering_shop.json")

GOLD = (0xC9, 0xA2, 0x27)
GOLD_HI = (0xFF, 0xE9, 0xA0)
BRONZE = (0x7A, 0x6A, 0x4F)
DIM = (0x9C, 0x96, 0x88)
BG = (0x12, 0x0F, 0x0C)

GROUP_NAMES = {'neutrophil': '中性粒细胞', 'macrophage': '巨噬细胞',
               't_cell': 'T细胞', 'nk': 'NK细胞'}
GROUP_ORDER = ['neutrophil', 'macrophage', 't_cell', 'nk']


def _wrap(text, per_line):
    """按字符数断行；避免把 ASCII 块（NK / +3s 等）拦腰切断，回退到最近空白。"""
    lines = []
    while text:
        if len(text) <= per_line:
            lines.append(text)
            break
        cut = per_line
        if text[cut - 1].isascii() and text[cut].isascii():
            while cut > 1 and text[cut - 1].isascii() and not text[cut - 1].isspace():
                cut -= 1
        lines.append(text[:cut].rstrip())
        text = text[cut:]
    return lines


def _load_icon(name, size):
    try:
        return gfx.load(name, (size, size), subdir='ui/icons')
    except Exception:
        return None


class AltarScene(Scene):
    """祭坛：记忆（buff 类）/ 实物（道具类）兑换。"""

    def __init__(self, game, to_back=True):
        super().__init__(game)
        with open(SHOP_PATH, encoding="utf-8") as f:
            shop = json.load(f)
        self.entries = shop['entries']
        self.physical = shop['physical']
        self.to_back = to_back
        self.meta = load_meta(None)
        self.tab = 'memory'            # memory | physical
        self.confirm = None            # {'kind':'memory'|'physical', 'key':...} | None
        self.msg = None                # 购买结果提示
        self._msg_t = 0.0
        self._memory_rects = {}        # key → pygame.Rect
        self._tab_rects = {}
        self._close_rect = None
        self._menu_rect = None
        self._confirm_rects = {}
        self._confirm_rect = None
        self._layout()

    def _click(self):
        """UI 点击音（共享总线；无音频环境时静默）。"""
        a = getattr(self.game, 'audio', None)
        if a:
            a.play('click')

    # ---------- 状态 ----------

    def _unlocked(self, item):
        u = item.get('unlock')
        if isinstance(u, dict) and u.get('milestone') == 'boss_beaten_1':
            if self.meta['boss_beaten_count'] < 1:
                return False
        for req in item.get('requires', []):
            # v4 修订：Ⅱ 档不能跳级——必须本局先记住 Ⅰ 档（同在 next_buffs 才允许买 Ⅱ）
            if req not in self.meta['next_buffs']:
                return False
        return True

    def _held_key_left(self):
        fs = self.meta['fixed_slot']
        return (isinstance(fs, dict) and fs.get('id') in ('key_left', 'key_right', 'key_full')
                or 'key_left' in self.meta['pending_physical'])

    # ---------- 布局 ----------

    def _layout(self):
        """记忆卡统一网格（5 列 × 3 行，面板内不溢出、上下留白均衡）：
        行 1 = 通用 ×5；行 2 = 类型 Ⅰ 档 ×4；行 3 = 类型 Ⅱ 档 ×4——
        各列按细胞类型上下对齐（Ⅰ 在上 Ⅱ 在下），第 5 列留白。
        """
        W = settings.WIDTH
        self._panel_rect = pygame.Rect(120, 76, W - 240, 588)   # 76..664
        self._tab_rects = {
            'memory': pygame.Rect(W // 2 - 170, 172, 160, 44),
            'physical': pygame.Rect(W // 2 + 10, 172, 160, 44),
        }
        self._memory_rects = {}
        x0, y0 = 162, 236
        cw, ch, gap, row_gap = 180, 96, 14, 12
        general = [e for e in self.entries if e['group'] == 'general']
        tiers = {tier: sorted((e for e in self.entries
                               if e['group'] in GROUP_ORDER and e['tier'] == tier),
                              key=lambda e: GROUP_ORDER.index(e['group']))
                 for tier in (1, 2)}
        for i, e in enumerate(general):                     # 行 0：通用 ×5
            self._memory_rects[e['key']] = pygame.Rect(
                x0 + i * (cw + gap), y0, cw, ch)
        for row, tier in ((1, 1), (2, 2)):                  # 行 1/2：类型 Ⅰ/Ⅱ 各占 1~4 列
            ry = y0 + row * (ch + row_gap)
            for c, e in enumerate(tiers[tier]):
                self._memory_rects[e['key']] = pygame.Rect(
                    x0 + c * (cw + gap), ry, cw, ch)
        self._close_rect = pygame.Rect(W // 2 - 90, 563, 180, 44)
        if not self.to_back:
            self._menu_rect = pygame.Rect(W // 2 - 90, 563, 180, 44)

    # ---------- 事件 ----------

    def handle_events(self, events):
        for e in events:
            if e.type != pygame.MOUSEBUTTONDOWN or e.button != 1:
                continue
            pos = e.pos
            if self.confirm is not None:
                if self._confirm_rect is not None and self._confirm_rect.collidepoint(pos):
                    for name, rect in self._confirm_rects.items():
                        if rect.collidepoint(pos):
                            if name == 'ok':
                                self._click()
                                self._do_buy()
                            self.confirm = None
                            return
                self.confirm = None
                self._click()
                continue
            for name, rect in self._tab_rects.items():
                if rect.collidepoint(pos):
                    self.tab = name
                    self._click()
                    return
            if self._close_rect.collidepoint(pos):
                self._click()
                if self.to_back:
                    self.game.scenes.pop()
                else:
                    from core.menu import MainMenu
                    self.game.scenes.switch(MainMenu(self.game))
                return
            if self._menu_rect is not None and self._menu_rect.collidepoint(pos):
                self._click()
                from core.menu import MainMenu
                self.game.scenes.switch(MainMenu(self.game))
                return
            if self.tab == 'memory':
                for key, rect in self._memory_rects.items():
                    if rect.collidepoint(pos):
                        self.confirm = {'kind': 'memory', 'key': key}
                        self._click()
                        return
            else:
                for key, rect in self._physical_rects().items():
                    if rect.collidepoint(pos):
                        if not self._held_key_left():
                            self.confirm = {'kind': 'physical', 'key': key}
                            self._click()
                        return

    def _physical_rects(self):
        W = settings.WIDTH
        return {'key_left': pygame.Rect(W // 2 - 160, 256, 320, 272)}

    def _do_buy(self):
        c = self.confirm
        if c['kind'] == 'memory':
            item = next(e for e in self.entries if e['key'] == c['key'])
            if not self._unlocked(item):
                self._flash("尚未解锁")
                return
            if item['key'] in self.meta['next_buffs']:
                self._flash("已记住（下一局生效）")
                return
            if self.meta['offering'] < item['cost']:
                self._flash("祭点不足")
                return
            self.meta['offering'] -= item['cost']
            self.meta['next_buffs'].append(item['key'])
            if item['key'] not in self.meta['learned_memories']:
                self.meta['learned_memories'].append(item['key'])
            self._flash("记忆已烧进下一局")
            _cost = item['cost']
            _reason = "buy_memory:" + c['key']
        else:
            if self._held_key_left():
                return
            if len(self.meta['pending_physical']) >= 6:
                self._flash("背包已满，无法再选择道具")
                return
            entry = self.physical[c['key']]
            if self.meta['offering'] < entry['cost']:
                self._flash("祭点不足")
                return
            self.meta['offering'] -= entry['cost']
            self.meta['pending_physical'].append(c['key'])
            self._flash("已兑换：下一局开局放入背包")
            _cost = entry['cost']
            _reason = "buy_key"
        save_meta(self.meta['offering'], self.meta['next_buffs'], None,
                  memories=self.meta['memories'],
                  learned_memories=self.meta['learned_memories'],
                  boss_beaten_count=self.meta['boss_beaten_count'],
                  pending_physical=self.meta['pending_physical'],
                  fixed_slot=self.meta['fixed_slot'],
                  perfect_ne_count=self.meta['perfect_ne_count'],
                  te2_seen=self.meta['te2_seen'],
                  achievements=self.meta['achievements'])
        # v5：祭点消费流水（购买成功后才记录）
        from systems import dbwrite
        dbwrite.record_offering(-_cost, _reason, self.meta['offering'])
        a = getattr(self.game, 'audio', None)
        if a:
            a.play('shop_buy')   # 祭祀铃：兑换成功

    def _flash(self, msg):
        self.msg = msg
        self._msg_t = 2.2

    def update(self, dt):
        if self.msg is not None:
            self._msg_t -= dt
            if self._msg_t <= 0:
                self.msg = None

    # ---------- 绘制 ----------

    def render(self, screen):
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0x08, 0x06, 0x04, 235))
        screen.blit(veil, (0, 0))
        p = self._panel_rect
        pygame.draw.rect(screen, BG, p, border_radius=18)
        pygame.draw.rect(screen, GOLD, p, 3, border_radius=18)
        pygame.draw.rect(screen, (0x2A, 0x24, 0x1C), p.inflate(-10, -10), 1, border_radius=13)
        # 标题 + 余额
        title = gfx.font(40, True).render("祭坛 · 记忆之匣", True, settings.UI_TEXT)
        screen.blit(title, title.get_rect(center=(settings.WIDTH // 2, p.y + 36)))
        offer = gfx.font(26, True).render(f"祭点 {self.meta['offering']}", True, GOLD_HI)
        screen.blit(offer, offer.get_rect(midright=(p.right - 40, p.y + 36)))
        # Tab
        for name, rect in self._tab_rects.items():
            sel = (self.tab == name)
            pygame.draw.rect(screen, (0x1E, 0x18, 0x10) if sel else (0x0C, 0x0A, 0x08),
                             rect, border_radius=10)
            pygame.draw.rect(screen, GOLD if sel else BRONZE, rect, 2, border_radius=10)
            t = gfx.font(22, True).render("记忆" if name == 'memory' else "实物",
                                          True, settings.UI_TEXT)
            screen.blit(t, t.get_rect(center=rect.center))
        if self.tab == 'memory':
            self._draw_memory(screen)
        else:
            self._draw_physical(screen)
        # 底部按钮
        pygame.draw.rect(screen, BG, self._close_rect, border_radius=10)
        pygame.draw.rect(screen, GOLD, self._close_rect, 2, border_radius=10)
        t = gfx.font(22, True).render("离开" if not self.to_back else "返回", True,
                                      settings.UI_TEXT)
        screen.blit(t, t.get_rect(center=self._close_rect.center))
        if self._menu_rect is not None:
            pygame.draw.rect(screen, BG, self._menu_rect, border_radius=10)
            pygame.draw.rect(screen, BRONZE, self._menu_rect, 2, border_radius=10)
            t = gfx.font(22, True).render("回主菜单", True, settings.UI_TEXT)
            screen.blit(t, t.get_rect(center=self._menu_rect.center))
        if self.msg is not None:
            m = gfx.font(20, True).render(self.msg, True, GOLD_HI)
            screen.blit(m, m.get_rect(center=(settings.WIDTH // 2, p.bottom - 30)))
        if self.confirm is not None:
            self._draw_confirm(screen)

    def _draw_memory(self, screen):
        mouse = pygame.mouse.get_pos()
        for key, rect in self._memory_rects.items():
            item = next(e for e in self.entries if e['key'] == key)
            unlocked = self._unlocked(item)
            bought = item['key'] in self.meta['next_buffs']
            afford = self.meta['offering'] >= item['cost']
            hover = rect.collidepoint(mouse)
            ok = unlocked and afford and not bought
            pygame.draw.rect(screen, BG, rect, border_radius=10)
            pygame.draw.rect(screen, GOLD if (hover and ok) else BRONZE, rect, 2,
                             border_radius=10)
            # 图标：类型记忆用细胞立绘；通用用小圆珠（左上角紧凑尺寸，让出文本宽度）
            ic_x, ic_y = rect.x + 20, rect.y + 24
            if item['group'] in GROUP_NAMES:
                img = gfx.load(load_cells()[item['group']]['sprite'], (34, 34))
                screen.blit(img, img.get_rect(center=(ic_x, ic_y)))
            else:
                pygame.draw.circle(screen, (0x7F, 0xD8, 0xC4), (ic_x, ic_y), 11)
                pygame.draw.circle(screen, (0xFF, 0xFF, 0xFF), (ic_x - 4, ic_y - 4), 4)
            # 名称 + 效果（卡片压缩布局，两行效果文本）
            tier_tag = 'Ⅰ' if item['tier'] == 1 else ('Ⅱ' if item['tier'] == 2 else '')
            nm = f"{item['name']}·{tier_tag}" if tier_tag else item['name']
            name = gfx.font(17, True).render(nm,
                                             True, settings.UI_TEXT if unlocked else DIM)
            screen.blit(name, (rect.x + 34, rect.y + 11))
            lines = _wrap(item['effect'], 11)
            for k, line in enumerate(lines[:2]):
                dl = gfx.font(12).render(line, True, DIM)
                screen.blit(dl, (rect.x + 34, rect.y + 38 + k * 16))
            # 状态行（简洁：已记住 / 价格 / 解锁条件）
            if bought:
                st = gfx.font(14, True).render("已记住", True, (0x4A, 0xC4, 0x58))
            elif unlocked:
                st = gfx.font(14, True).render(
                    f"{item['cost']} 祭点", True, GOLD_HI if afford else DIM)
            else:
                u = item.get('unlock')
                if isinstance(u, dict) and u.get('milestone') == 'boss_beaten_1' \
                        and self.meta['boss_beaten_count'] < 1:
                    st = gfx.font(13).render("击败 BOSS 解锁", True, DIM)
                else:
                    st = gfx.font(13).render("先买 Ⅰ 档", True, DIM)
            screen.blit(st, (rect.x + 34, rect.y + rect.h - 26))

    def _draw_physical(self, screen):
        mouse = pygame.mouse.get_pos()
        for key, rect in self._physical_rects().items():
            entry = self.physical[key]
            held = self._held_key_left()
            afford = self.meta['offering'] >= entry['cost']
            hover = rect.collidepoint(mouse)
            ok = afford and not held
            pygame.draw.rect(screen, BG, rect, border_radius=14)
            pygame.draw.rect(screen, GOLD if (hover and ok) else BRONZE, rect, 3,
                             border_radius=14)
            icon = _load_icon('key_left_48.png', 110)
            cx = rect.centerx
            if icon is not None:
                screen.blit(icon, icon.get_rect(center=(cx, rect.y + 80)))
            else:
                pygame.draw.circle(screen, (0xC0, 0xC8, 0xD4), (cx, rect.y + 80), 44, 3)
                pygame.draw.circle(screen, (0xC0, 0xC8, 0xD4), (cx, rect.y + 80), 7)
            name = gfx.font(26, True).render(entry['name'], True, settings.UI_TEXT)
            screen.blit(name, name.get_rect(center=(cx, rect.y + 152)))
            for k, line in enumerate(_wrap(entry['desc'], 15)[:2]):
                dl = gfx.font(15).render(line, True, DIM)
                screen.blit(dl, dl.get_rect(center=(cx, rect.y + 186 + k * 22)))
            st = gfx.font(20, True).render(
                "已持有" if held else f"{entry['cost']} 祭点", True,
                (0x4A, 0xC4, 0x58) if held else (GOLD_HI if afford else DIM))
            screen.blit(st, st.get_rect(center=(cx, rect.y + 236)))

    def _draw_confirm(self, screen):
        w, h = 460, 260
        x = (settings.WIDTH - w) // 2
        y = (settings.HEIGHT - h) // 2 - 20
        self._confirm_rect = pygame.Rect(x, y, w, h)
        self._confirm_rects = {}
        pygame.draw.rect(screen, BG, self._confirm_rect, border_radius=14)
        pygame.draw.rect(screen, GOLD, self._confirm_rect, 3, border_radius=14)
        c = self.confirm
        if c['kind'] == 'memory':
            item = next(e for e in self.entries if e['key'] == c['key'])
            title = item['name']
            lines = [item['effect'], f"价格：{item['cost']} 祭点",
                     "（下一局开局生效，用一次即淡忘）"]
        else:
            entry = self.physical[c['key']]
            title = entry['name']
            lines = [entry['desc'], f"价格：{entry['cost']} 祭点",
                     "（下一局开局放入背包）"]
        t = gfx.font(30, True).render(title, True, settings.UI_TEXT)
        screen.blit(t, t.get_rect(center=(settings.WIDTH // 2, y + 46)))
        for k, line in enumerate(lines):
            dl = gfx.font(18).render(line, True, DIM)
            screen.blit(dl, dl.get_rect(center=(settings.WIDTH // 2, y + 100 + k * 32)))
        ok = pygame.Rect(x + 90, y + h - 64, 130, 44)
        no = pygame.Rect(x + 240, y + h - 64, 130, 44)
        self._confirm_rects['ok'] = ok
        self._confirm_rects['cancel'] = no
        for r, label, col in ((ok, "兑换", GOLD), (no, "取消", BRONZE)):
            pygame.draw.rect(screen, BG, r, border_radius=8)
            pygame.draw.rect(screen, col, r, 2, border_radius=8)
            bt = gfx.font(20, True).render(label, True, settings.UI_TEXT)
            screen.blit(bt, bt.get_rect(center=r.center))
