"""core/ending.py：结局与故事演出（A3.4，自 Gameplay 外迁）——NE 单页/死亡闪回/TE 占位/
获得横幅/心跳红脉冲的绘制，以及结局推进与回主菜单的流程。

持有宿主 Gameplay 引用（gp）：绘制只读 gp 状态；advance/finish_te 通过
SceneManager.switch 回主菜单（惰性导入 menu 避免循环依赖）。
"""
import pygame

import gfx
import settings

# NE 单页演出文案（《开头与结局设计.md》§2.2，一页播完，点击回菜单）
ENDING_STAGES = [
    "主病灶已切除。",
    "但深处仍有残留细胞，微微闪烁。",
    "你睁开眼，窗外是清晨的光。",
    "心电监护仪稳定地响着。",
    "复查时间：三个月后。",
]

# TE 真结局文案（TE.txt 终稿）：主角苏醒后的内心独白，逐字显现（同开场独白）
TE_PARAGRAPHS = [
    "我睁开眼睛，已经没有了手术室刺眼的白光，也没有了之前恐惧凝成实质的黑暗，取而代之的，是父母和奶奶疲惫但关切的目光。",
    "我的心暖暖的，仿佛暂时忘却了麻药退去后的疼痛。",
    "我回忆起之前，癌细胞的复制，肿瘤的可怕已经不让我恐惧，取而代之的是被体内白细胞们冲锋陷阵、悍不畏死的感动。",
    "我的身体，我的家人，还有屏幕前的你，我们的努力最终在三个月后的复查体现出来。",
    "肿瘤没有转移，原病灶完全被清除。",
    "我，在这场生死战役中，活下来了。",
]

TE_CHAR_TIME = 0.04      # 每字显现间隔（秒）
TE_PAUSE_TIME = 0.7      # 段间呼吸停顿（秒）
TE_FONT_SIZE = 22        # 正文字号
TE_LINE_H = 38           # 行距
TE_STANZA_GAP = 22       # 段间额外间距
TE_MAX_WIDTH = 1180      # 换行宽度（像素）
TE_TEXT_COLOR = (0xE8, 0xE4, 0xD8)
TE_TITLE_COLOR = (0xE9, 0xC4, 0x6A)


def _wrap_te(font):
    """TE 文案按宽度自动换行，返回 [[line, ...], ...]（每段一个 stanza）。"""
    out = []
    for para in TE_PARAGRAPHS:
        lines, cur = [], ""
        for ch in para:
            if cur and font.size(cur + ch)[0] > TE_MAX_WIDTH:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        out.append(lines)
    return out


class EndingDirector:
    """结局/死亡/横幅演出：Gameplay.render 的对应分支只调 draw_*。"""

    def __init__(self, gp):
        self.gp = gp
        # TE 逐字演出：换行布局/总时长懒计算（首次 draw/typing 时，pygame.font 已就绪）
        self._te_stanzas = None
        self._te_total = None
        self._te_surfs = {}

    # ---------- TE 逐字进度 ----------

    def _ensure_te_layout(self):
        """懒计算 TE 换行后的段落 + 总时长（避免构造期依赖 pygame.font）。"""
        if self._te_stanzas is None:
            self._te_stanzas = _wrap_te(gfx.font(TE_FONT_SIZE))
            self._te_total = self._te_typing_time()

    def _te_typing_time(self):
        """TE 逐字播放总时长（含段间停顿）。"""
        t = 0.0
        for i, stanza in enumerate(self._te_stanzas):
            if i > 0:
                t += TE_PAUSE_TIME
            for line in stanza:
                t += len(line) * TE_CHAR_TIME
        return t

    def te_typing_time(self):
        """TE 逐字播放总时长（供 Gameplay 驱动打字机）。"""
        self._ensure_te_layout()
        return self._te_total

    def te_shown_chars(self):
        """当前已显现的累计字数（打字机进度，含段间停顿）。"""
        self._ensure_te_layout()
        t = self.gp.te_timer
        shown = 0
        for i, stanza in enumerate(self._te_stanzas):
            if i > 0:
                t -= TE_PAUSE_TIME
                if t < 0:
                    return shown
            for line in stanza:
                n = len(line)
                k = min(n, int(t / TE_CHAR_TIME))
                shown += k
                t -= n * TE_CHAR_TIME
                if k < n:
                    return shown
        return shown

    # ---------- 流程 ----------

    def advance(self):
        """NE 单页演出：点击一次即结束（或进入 TE 追加）。"""
        gp = self.gp
        gp.ending_stage += 1
        if gp.ending_stage >= 1:
            if gp._te_pending and not gp._te_shown:
                gp._te_shown = True
                gp.te_timer = 0.0            # 打字机从 0 递增
                gp._te_finished = False
                gp._set_scene('te')          # NE 之后追加 TE 逐字演出
                return
            self._go_finish()

    def _go_finish(self):
        """结尾看完：切到祭坛（可兑换/回主菜单）。"""
        from .altar import AltarScene
        self.gp.game.scenes.switch(AltarScene(self.gp.game, to_back=False))

    def finish_te(self):
        """TE 演出结束（计时归零或点击）：若有 TE2 线 → 续播；否则结算收尾。"""
        gp = self.gp
        if getattr(gp, '_te2_pending', False) and not gp._te2_shown:
            gp._te2_shown = True
            gp.te2_timer = 5.0
            gp._set_scene('te2')
            return
        self._go_finish()

    def finish_te2(self):
        """TE2 演出结束（计时归零或点击）：结算收尾（切祭坛）。"""
        self._go_finish()

    # ---------- 绘制 ----------

    def draw_story(self, screen):
        """获得横幅（v3 §5.1）：图标淡入 + 道具名 + 副题 + 逐字剧情小字。"""
        gp = self.gp
        story = gp.story
        if story is None:
            return
        data = story['data']
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 205))
        screen.blit(veil, (0, 0))
        cx = settings.WIDTH // 2
        item = gp.items_data.get(story['id'])          # v5：成就横幅无道具条目（icon=None）
        icon = gfx.load_icon_safe(item['icon'], 92) if item else None
        if icon is not None:
            screen.blit(icon, icon.get_rect(center=(cx, 210)))
        title = gfx.font(44, True).render(data['title'], True, settings.UI_TEXT)
        screen.blit(title, title.get_rect(center=(cx, 330)))
        sub = gfx.font(20).render(data['subtitle'], True, (0xC9, 0xA2, 0x27))
        screen.blit(sub, sub.get_rect(center=(cx, 380)))
        # 剧情小字：单行显示（按文本长度自适应字号，强迫症友好）
        text = data['text']
        shown = text[:story['chars']]
        fs = min(24, max(15, int(1210 / max(1, len(text)))))
        t = gfx.font(fs).render(shown, True, (0xE8, 0xE4, 0xD8))
        screen.blit(t, t.get_rect(center=(cx, 440)))
        completed = story['chars'] >= len(text)
        hint = gfx.font(16).render("点击继续" if completed else "点击跳过 · 空格补全",
                                   True, (0x9C, 0x96, 0x88))
        screen.blit(hint, hint.get_rect(center=(cx, settings.HEIGHT - 84)))

    def draw_death_flash(self, screen):
        """死亡闪回：手术室警报 + 监护仪画面。"""
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0x5A, 0x12, 0x08, 210))
        screen.blit(veil, (0, 0))
        t1 = gfx.font(44, True).render("手术室警报", True, (0xFF, 0x4A, 0x4A))
        screen.blit(t1, t1.get_rect(center=(settings.WIDTH // 2, settings.HEIGHT // 2 - 30)))
        t2 = gfx.font(26).render("监护仪 ——————", True, settings.UI_TEXT)
        screen.blit(t2, t2.get_rect(center=(settings.WIDTH // 2, settings.HEIGHT // 2 + 20)))

    def draw_ending(self, screen):
        """NE 单页演出（《开头与结局设计.md》§2.2 文案，一页播完，点击回菜单）。"""
        gp = self.gp
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 215))
        screen.blit(veil, (0, 0))
        cx = settings.WIDTH // 2
        # 主标题
        t = gfx.font(46, True).render(ENDING_STAGES[0], True, settings.UI_TEXT)
        screen.blit(t, t.get_rect(center=(cx, 178)))
        # 残留（红，动态）
        r = gfx.font(22, True).render(f"残留癌细胞：{gp.ending_residual:.2f}%", True, (0xFF, 0x4A, 0x4A))
        screen.blit(r, r.get_rect(center=(cx, 246)))
        # 正文三行
        for i, line in enumerate(ENDING_STAGES[1:-1]):
            t = gfx.font(26).render(line, True, settings.UI_TEXT)
            screen.blit(t, t.get_rect(center=(cx, 330 + i * 56)))
        # 收尾（金）
        t = gfx.font(30, True).render(ENDING_STAGES[-1], True, (0xC9, 0xA2, 0x27))
        screen.blit(t, t.get_rect(center=(cx, 520)))
        hint = gfx.font(20).render("点击返回 · ESC 退出", True, (0x9C, 0x96, 0x88))
        screen.blit(hint, hint.get_rect(center=(cx, settings.HEIGHT - 60)))

    def draw_true_ending(self, screen):
        """TE 真结局演出：标题 + 正文逐字显现（打字机，同开场独白）。"""
        self._ensure_te_layout()
        gp = self.gp
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 235))
        screen.blit(veil, (0, 0))
        cx = settings.WIDTH // 2
        # 标题
        title = gfx.font(40, True).render("真结局", True, TE_TITLE_COLOR)
        screen.blit(title, title.get_rect(center=(cx, 64)))
        # 正文逐字显现（居中排版，段间留白）
        total_lines = sum(len(s) for s in self._te_stanzas)
        total_h = total_lines * TE_LINE_H + (len(self._te_stanzas) - 1) * TE_STANZA_GAP
        y = max(120, (settings.HEIGHT - total_h) // 2 + 20)
        remaining = self.te_shown_chars()
        f = gfx.font(TE_FONT_SIZE)
        for stanza in self._te_stanzas:
            for line in stanza:
                if remaining <= 0:
                    y += TE_LINE_H
                    continue
                k = min(len(line), remaining)
                remaining -= k
                surf = self._te_surfs.get(line)
                if surf is None:
                    surf = f.render(line, True, TE_TEXT_COLOR)
                    self._te_surfs[line] = surf
                w = max(1, f.size(line[:k])[0])
                rect = surf.get_rect(center=(cx, y + TE_LINE_H // 2))
                screen.blit(surf, rect, pygame.Rect(0, 0, w, surf.get_height()))
                y += TE_LINE_H
            y += TE_STANZA_GAP
        # 提示
        hint_text = "点击继续 · ESC 跳过" if gp._te_finished else "点击补全 · ESC 跳过"
        hint = gfx.font(16).render(hint_text, True, (0x6A, 0x64, 0x58))
        screen.blit(hint, hint.get_rect(center=(cx, settings.HEIGHT - 48)))

    def draw_true_ending2(self, screen):
        """TE2 真结局占位演出（v4 §5.6：档案室左半线，内容待剧情系统）。

        与 TE 互相独立；触发 = 本局打开过档案室左半区。
        """
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 230))
        screen.blit(veil, (0, 0))
        t1 = gfx.font(44, True).render("真结局·另一侧", True, (0xC9, 0xA2, 0x27))
        screen.blit(t1, t1.get_rect(center=(settings.WIDTH // 2, settings.HEIGHT // 2 - 40)))
        t2 = gfx.font(24).render("（档案室左半的剧情文案待策划撰写——占位演出）",
                                 True, settings.UI_TEXT)
        screen.blit(t2, t2.get_rect(center=(settings.WIDTH // 2, settings.HEIGHT // 2 + 20)))
        hint = gfx.font(18).render("点击返回", True, (0x9C, 0x96, 0x88))
        screen.blit(hint, hint.get_rect(center=(settings.WIDTH // 2, settings.HEIGHT - 60)))

    def draw_pulse(self, screen):
        """心跳视觉：低血时屏幕边缘红脉冲更明显。"""
        gp = self.gp
        if gp._pulse <= 0.01:
            return
        ratio = gp.player.hp / max(1, gp.player.max_hp)
        intensity = int(90 * gp._pulse * (1.2 - ratio))
        if intensity <= 0:
            return
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        w, h = settings.WIDTH, settings.HEIGHT
        pygame.draw.rect(veil, (0xD3, 0x2A, 0x2A, intensity), (0, 0, w, 8))
        pygame.draw.rect(veil, (0xD3, 0x2A, 0x2A, intensity), (0, h - 8, w, 8))
        pygame.draw.rect(veil, (0xD3, 0x2A, 0x2A, intensity), (0, 0, 8, h))
        pygame.draw.rect(veil, (0xD3, 0x2A, 0x2A, intensity), (w - 8, 0, 8, h))
        screen.blit(veil, (0, 0))
