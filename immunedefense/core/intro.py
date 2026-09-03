"""开场演出：主角内心独白字幕（《开头与结局设计.md》§1.2 终稿）。

画面：纯黑底 + 白色居中字幕，整段独白**排版在同一页**；
播放：逐字显现（打字机效果），空行 = 段间呼吸停顿；全部显现后停留数秒 → 渐黑收尾
→ 进入游戏首房（Gameplay）。
交互：点击/空格 = 补全打字，再点 = 直接进入游戏；ESC = 整段跳过。
bg 字段预留：后续即梦出「望向手术灯」画面后可换成背景图（本次仅黑底字幕）。
"""
import pygame

import gfx
import settings
from .scene import Scene

# 独白终稿（已逐句确认）——空行 = 段落呼吸停顿
MONOLOGUE = [
    "他们说，只是肝上长了个东西。",
    "切除就行。",
    "可没人告诉我，麻醉上来之前，",
    "人会这么怕。",
    "",
    "我也说不清在怕什么——",
    "怕这一针推下去，",
    "就再也醒不过来。",
    "",
    "……要是能醒，",
    "我得好好活一次。",
    "",
    "（意识沉下去）",
    "这里……是哪里？",
]

CHAR_TIME = 0.05     # 每个字显现间隔（秒）
PAUSE_TIME = 0.55    # 空行（段间）呼吸停顿（秒）
HOLD_END = 2.4       # 全部显现后的停留（秒）
FADE_TIME = 1.2      # 渐黑收尾（秒）

FONT_SIZE = 28       # 单页排版字号（13 行可一页放下）
LINE_H = 42          # 行距
STANZA_GAP = 14      # 段间额外间距
TEXT_COLOR = (0xE8, 0xE4, 0xD8)


def _typing_time():
    """逐字播放总时长（含段间停顿）。"""
    t = 0.0
    for line in MONOLOGUE:
        t += len(line) * CHAR_TIME
        if line == "":
            t += PAUSE_TIME
    return t


def _stanzas():
    """按空行切段，返回 [[str, ...], ...]。"""
    out, cur = [], []
    for line in MONOLOGUE:
        if line == "":
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(line)
    if cur:
        out.append(cur)
    return out


class IntroScene(Scene):
    MONOLOGUE = MONOLOGUE   # 类属性引用（便于测试访问）

    def __init__(self, game, seed=None, bg=None):
        super().__init__(game)
        self.seed = seed
        self.bg = bg            # 预留：背景图路径（None = 纯黑）
        self.timer = 0.0        # 打字进度计时
        self.finished = False   # 全部文字已显现
        self.hold = 0.0         # 全部显现后的停留计时
        self.fade = 0.0         # 渐黑收尾计时
        self.done = False       # 收尾完毕，可切场景
        self._surfs = {}        # 每行整行渲染缓存（逐字显现用裁剪）
        self._veil = pygame.Surface((settings.WIDTH, settings.HEIGHT))
        self._veil.fill((0, 0, 0))

    # ---------- 输入 ----------

    def handle_events(self, events):
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self._advance()
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    self._finish()          # ESC 整段跳过
                else:
                    self._advance()         # 空格/任意键推进

    def _advance(self):
        """点击/空格：打字中 → 立即补全；已补全 → 直接进入游戏。"""
        if self.done:
            return
        if not self.finished:
            self.timer = _typing_time()
            self.finished = True
            return
        self._finish()

    def _finish(self):
        if self.done:
            return
        self.done = True
        from .gameplay import Gameplay  # 惰性导入避免循环依赖
        if self.seed is not None:
            self.game.seed = self.seed
        self.game.scenes.switch(Gameplay(self.game, seed=self.game.seed))

    # ---------- 更新 ----------

    def update(self, dt):
        if self.done:
            return
        if not self.finished:
            self.timer += dt
            if self.timer >= _typing_time():
                self.timer = _typing_time()
                self.finished = True
            return
        # 全部显现：停留 → 渐黑 → 切场景
        if self.hold < HOLD_END:
            self.hold = min(HOLD_END, self.hold + dt)
            if self.hold < HOLD_END:
                return
        self.fade += dt
        if self.fade >= FADE_TIME:
            self._finish()

    # ---------- 渲染 ----------

    def _shown_chars(self):
        """当前已显现的累计字数（打字机进度：逐字 + 段间停顿）。"""
        t = self.timer
        shown = 0
        for line in MONOLOGUE:
            if line == "":
                t -= PAUSE_TIME
                if t < 0:
                    return shown
                continue
            n = len(line)
            k = min(n, int(t / CHAR_TIME))
            shown += k
            t -= n * CHAR_TIME
            if k < n:
                break
        return shown

    def render(self, screen):
        screen.fill((0, 0, 0))
        # 单页排版：整段居中，段间留白
        stanzas = _stanzas()
        total_h = sum(len(s) * LINE_H for s in stanzas) + STANZA_GAP * (len(stanzas) - 1)
        y = (settings.HEIGHT - total_h) // 2
        remaining = self._shown_chars()
        f = gfx.font(FONT_SIZE)
        for stanza in stanzas:
            for line in stanza:
                if remaining <= 0:
                    y += LINE_H
                    continue
                k = min(len(line), remaining)
                remaining -= k
                surf = self._surfs.get(line)
                if surf is None:
                    surf = f.render(line, True, TEXT_COLOR)
                    self._surfs[line] = surf
                w = max(1, f.size(line[:k])[0])
                rect = surf.get_rect(center=(settings.WIDTH // 2, y + LINE_H // 2))
                screen.blit(surf, rect, pygame.Rect(0, 0, w, surf.get_height()))
                y += LINE_H
            y += STANZA_GAP

        # 渐黑收尾（文字渐隐）
        if self.finished and self.hold >= HOLD_END:
            a = int(255 * min(1.0, self.fade / FADE_TIME))
            if a > 0:
                self._veil.set_alpha(a)
                screen.blit(self._veil, (0, 0))

        hint = gfx.font(16).render(
            "点击继续 · ESC 跳过" if self.finished else "点击补全 · ESC 跳过",
            True, (0x6A, 0x64, 0x58))
        screen.blit(hint, hint.get_rect(center=(settings.WIDTH // 2, settings.HEIGHT - 48)))
