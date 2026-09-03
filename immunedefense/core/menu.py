"""主菜单场景：直接显示 flash-vision-exp 的新版整图，并用 bg_anim 帧做背景动画。

- 整图自带「开始游戏 / 退出」按钮，代码保留热区（方案 A）。
- 右下角新增代码绘制的「设置」按钮 → 设置弹层（含「跳过开场剧情」开关，落盘 config.json）。
- 右上角心电图：整图烘焙版有"曲线突出屏幕"且过简，改为代码重绘（机身+屏幕+网格+
  发光扫描波形+心率数字），覆盖原烘焙绘制。
"""
import math
import random

import pygame

import gfx
import settings
from .scene import Scene
from .configs import (load_config, set_skip_intro, set_sound_on, set_light_mode)

# 背景动画帧：full（=bg_anim_0）+ 两张偏移帧，按时间循环切换
ANIM_FRAMES = ['ui_main_menu_full.png', 'ui_main_menu_bg_anim_1.png', 'ui_main_menu_bg_anim_2.png']
ANIM_INTERVAL = 2.0  # 秒，放缓避免"来回闪"

# 代码重绘的心电监护仪（覆盖整图烘焙版；机身加高以盖住旧版突出屏幕的曲线尖端）
ECG_BODY = pygame.Rect(916, 42, 304, 180)
ECG_SCREEN = pygame.Rect(941, 74, 252, 104)
ECG_TRACE = (0x7F, 0xD8, 0xC4)   # 与 color_spec ui_guide 同青绿


class MainMenu(Scene):
    def __init__(self, game):
        super().__init__(game)
        # 热区 = 整图按钮完整外框（古铜外圈 + 金线内框，实测 279×59）
        self.start_rect = pygame.Rect(501, 419, 279, 59)
        self.quit_rect = pygame.Rect(501, 487, 279, 59)
        # 「设置」按钮：退出正下方（按钮间隙 9px），同宽同高同列左对齐
        self.settings_rect = pygame.Rect(501, 555, 279, 59)
        # v4 祭坛入口：设置下方（同宽同高同列）
        self.altar_rect = pygame.Rect(501, 623, 279, 59)
        self.show_settings = False
        _cfg = load_config()
        self._skip_intro = _cfg["skip_intro"]
        self._sound_on = _cfg["sound_on"]
        self._light_mode = _cfg["light_mode"]
        # 设置弹层热区（非显示时不生效）：标题下三行 = 模式设置 / 音效开关 / 跳过剧情
        self._panel = pygame.Rect(settings.WIDTH // 2 - 280, 170, 560, 360)
        self._mode_label_rect = pygame.Rect(self._panel.x + 44, self._panel.y + 82, 100, 24)
        self._mode_normal = pygame.Rect(self._panel.x + 190, self._panel.y + 78, 150, 38)
        self._mode_dim = pygame.Rect(self._mode_normal.right + 12, self._mode_normal.y, 150, 38)
        self._chk_sound = pygame.Rect(self._panel.x + 44, self._panel.y + 132, 24, 24)
        self._chk_rect = pygame.Rect(self._panel.x + 44, self._panel.y + 186, 24, 24)
        self._settings_leave = pygame.Rect(self._panel.centerx - 70, self._panel.bottom - 64, 140, 40)
        self._anim_idx = 0
        self._anim_timer = 0.0
        self._ecg_t = 0.0          # 心电图动画时间
        self._ecg_glow = None      # 描线发光层（推迟到首次 render 创建）
        # v5：档案管理面板地址小字（可点击打开浏览器）
        self.panel_rect = pygame.Rect(24, settings.HEIGHT - 40, 300, 26)

    def _click(self):
        """UI 点击音（共享总线；无音频环境时静默）。"""
        a = getattr(self.game, 'audio', None)
        if a:
            a.play('click')

    def handle_events(self, events):
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if self.show_settings:
                    if self._chk_sound.collidepoint(e.pos):
                        self._sound_on = set_sound_on(not self._sound_on)
                        a = getattr(self.game, 'audio', None)
                        if a:
                            a.set_enabled(self._sound_on)   # 开关即时生效
                        self._click()
                    elif self._mode_normal.collidepoint(e.pos):
                        self._light_mode = set_light_mode('normal')
                        self._click()
                    elif self._mode_dim.collidepoint(e.pos):
                        self._light_mode = set_light_mode('dim')
                        self._click()
                    elif self._chk_rect.collidepoint(e.pos):
                        self._skip_intro = set_skip_intro(not self._skip_intro)
                        self._click()
                    elif self._settings_leave.collidepoint(e.pos):
                        self.show_settings = False
                        self._click()
                    continue  # 设置弹层打开时，屏蔽底层按钮
                if self.settings_rect.collidepoint(e.pos):
                    self.show_settings = True
                    self._click()
                    continue
                if self.altar_rect.collidepoint(e.pos):
                    from .altar import AltarScene  # v4：祭坛（记忆/实物兑换）
                    self._click()
                    self.game.scenes.push(AltarScene(self.game))
                    continue
                if self.panel_rect.collidepoint(e.pos):
                    import webbrowser  # v5：打开本地档案管理面板
                    self._click()
                    webbrowser.open("http://127.0.0.1:8765")
                    continue
                if self.start_rect.collidepoint(e.pos):
                    from .gameplay import Gameplay  # 惰性导入避免循环依赖
                    # 开局种子：SystemRandom 生成，存入 Game 再传给 Gameplay
                    self._click()
                    self.game.seed = random.SystemRandom().randint(0, 2 ** 31 - 1)
                    if self._skip_intro:
                        self.game.scenes.switch(Gameplay(self.game, seed=self.game.seed))
                    else:
                        from .intro import IntroScene
                        self.game.scenes.switch(IntroScene(self.game, seed=self.game.seed))
                elif self.quit_rect.collidepoint(e.pos):
                    self._click()
                    self.game.running = False

    def update(self, dt):
        self._anim_timer += dt
        self._ecg_t += dt
        if self._anim_timer >= ANIM_INTERVAL:
            self._anim_timer -= ANIM_INTERVAL
            self._anim_idx = (self._anim_idx + 1) % len(ANIM_FRAMES)

    def render(self, screen):
        # 整图已内置标题/标语/按钮，直接铺满即可（不叠加代码文字）
        bg = gfx.load_ui(ANIM_FRAMES[self._anim_idx], (settings.WIDTH, settings.HEIGHT))
        screen.blit(bg, (0, 0))
        self._draw_ecg(screen)
        if self.show_settings:
            self._draw_settings(screen)
        else:
            self._draw_settings_button(screen)
            self._draw_altar_button(screen)
            self._draw_panel_hint(screen)

    def _draw_panel_hint(self, screen):
        """v5：底部左角档案管理地址（灰字，hover 变亮，点击打开浏览器）。"""
        mouse = pygame.mouse.get_pos()
        hover = self.panel_rect.collidepoint(mouse)
        t = gfx.font(14, hover).render("档案管理：http://127.0.0.1:8765",
                                       True, (0x9C, 0x96, 0x88) if not hover
                                       else (0xE9, 0xC4, 0x6A))
        screen.blit(t, (self.panel_rect.x, self.panel_rect.y + 4))

    def _draw_altar_button(self, screen):
        """祭坛按钮：与设置按钮同款底图，青金配色文字。"""
        img = gfx.load_ui('ui_settings_button.png')
        screen.blit(img, self.altar_rect.topleft)
        t = gfx.font(24, True).render("祭坛", True, (0xE9, 0xC4, 0x6A))
        screen.blit(t, t.get_rect(center=self.altar_rect.center))

    # ---------- 心电图（代码重绘 + 扫描动画）----------

    @staticmethod
    def _ecg_value(ph):
        """一段心跳波形（P-QRS-T），ph ∈ [0,1) 周期；返回相对波高（+上 -下）。"""
        def g(c, w):
            return math.exp(-((ph - c) ** 2) / (2 * w * w))
        return (0.10 * g(0.18, 0.035)      # P 波
                - 0.16 * g(0.44, 0.020)    # Q 小凹
                + 1.00 * g(0.50, 0.020)    # R 尖峰
                - 0.30 * g(0.57, 0.018)    # S 凹
                + 0.22 * g(0.73, 0.055))   # T 波

    def _draw_ecg(self, screen):
        body, scr = ECG_BODY, ECG_SCREEN
        t = self._ecg_t
        scr_layer = pygame.Surface((scr.w, scr.h), pygame.SRCALPHA)  # 每帧小尺寸，开销可忽略
        # 机身（深蓝壳 + 高光描边 + 圆角）
        pygame.draw.rect(screen, (0x10, 0x19, 0x21), body, border_radius=14)
        pygame.draw.rect(screen, (0x2E, 0x44, 0x52), body, 2, border_radius=14)
        pygame.draw.rect(screen, (0x3A, 0x56, 0x64), body.inflate(-8, -8), 1, border_radius=10)
        # 屏幕（近黑底 + 圆角）
        pygame.draw.rect(screen, (0x05, 0x0E, 0x14), scr, border_radius=6)
        pygame.draw.rect(screen, (0x0F, 0x22, 0x2C), scr, 1, border_radius=6)
        # 点阵网格（心电纸质感）
        for gx in range(scr.x + 6, scr.right, 14):
            for gy in range(scr.y + 6, scr.bottom, 14):
                pygame.draw.circle(screen, (0x11, 0x28, 0x30), (gx, gy), 1)
        # 波形：滚动扫描（波形恒定振幅，R 尖峰预留边距，不突屏）
        baseline = scr.y + scr.h * 0.60
        amp = scr.h * 0.44
        pts = []
        for px in range(scr.x, scr.right + 1, 3):
            ph = ((px - scr.x) / scr.w + t * 0.22) % 1.0
            pts.append((px - scr.x, baseline - scr.y - self._ecg_value(ph) * amp))
        for width, color in ((7, (0x36, 0x7C, 0x84, 30)),
                             (3, (0x7F, 0xD8, 0xC4, 120)),
                             (1, (0xBF, 0xF2, 0xE4, 255))):
            pygame.draw.lines(scr_layer, color, False, pts, width)
        # 扫描亮线（跟随波形相位）
        sweep = int(((t * 0.22) % 1.0) * scr.w)
        pygame.draw.line(scr_layer, (0x7F, 0xD8, 0xC4, 90), (sweep, 0), (sweep, scr.h), 1)
        screen.blit(scr_layer, scr.topleft)
        # 心率读数（呼吸式微变）
        hr = 72 + int(5 * math.sin(t * 0.9))
        hrt = gfx.font(28, True).render(str(hr), True, (0xAA, 0xE8, 0xD0))
        screen.blit(hrt, (scr.right - 50, scr.y + 12))
        bpm = gfx.font(11).render('BPM', True, (0x4A, 0x7A, 0x72))
        screen.blit(bpm, (scr.right - 50, scr.y + 44))
        # 底部铭牌条 + 电源 LED（呼吸闪）
        bar = pygame.Rect(body.x + 12, body.bottom - 24, body.w - 24, 15)
        pygame.draw.rect(screen, (0x0C, 0x14, 0x1A), bar, border_radius=4)
        pygame.draw.rect(screen, (0x1E, 0x30, 0x3A), bar, 1, border_radius=4)
        led = (0x3A, 0xE0, 0xA0) if int(t * 1.6) % 2 == 0 else (0x1A, 0x6A, 0x4A)
        pygame.draw.circle(screen, led, (body.x + 24, body.bottom - 16), 3)
        br = gfx.font(11).render('VITAL MONITOR', True, (0x3A, 0x54, 0x5E))
        screen.blit(br, (body.x + 36, body.bottom - 22))

    def _draw_settings_button(self, screen):
        """与整图上的 开始游戏/退出 按钮完全一致：使用精确裁剪的按钮底图 + 同色文字。"""
        img = gfx.load_ui('ui_settings_button.png')   # 273x53，自整图按金边实测坐标裁取
        screen.blit(img, self.settings_rect.topleft)
        t = gfx.font(24, True).render("设置", True, settings.UI_TEXT)  # 与「退出」同色
        screen.blit(t, t.get_rect(center=self.settings_rect.center))

    def _draw_check(self, screen, rect, checked):
        """金框勾选框：unchecked = 空框，checked = 金色对勾。"""
        pygame.draw.rect(screen, (0x1A, 0x16, 0x12), rect, border_radius=4)
        pygame.draw.rect(screen, (0x7A, 0x6A, 0x4F), rect, 2, border_radius=4)
        if checked:
            pygame.draw.line(screen, (0xC9, 0xA2, 0x27),
                             (rect.x + 5, rect.centery),
                             (rect.centerx, rect.bottom - 6), 3)
            pygame.draw.line(screen, (0xC9, 0xA2, 0x27),
                             (rect.centerx, rect.bottom - 6),
                             (rect.right - 5, rect.y + 4), 3)

    def _draw_mode_button(self, screen, rect, label, selected):
        """模式按钮：选中 = 金边金字 + 亮底，未选中 = 暗边灰字。"""
        pygame.draw.rect(screen, (0x2A, 0x24, 0x16) if selected else (0x1A, 0x16, 0x12),
                         rect, border_radius=8)
        pygame.draw.rect(screen, (0xC9, 0xA2, 0x27) if selected else (0x7A, 0x6A, 0x4F),
                         rect, 2, border_radius=8)
        color = settings.UI_TEXT if selected else (0x9C, 0x96, 0x88)
        t = gfx.font(20, selected).render(label, True, color)
        screen.blit(t, t.get_rect(center=rect.center))

    def _draw_settings(self, screen):
        veil = pygame.Surface((settings.WIDTH, settings.HEIGHT), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 190))
        screen.blit(veil, (0, 0))
        p = self._panel
        pygame.draw.rect(screen, (0x12, 0x0F, 0x0C), p, border_radius=12)
        pygame.draw.rect(screen, (0xC9, 0xA2, 0x27), p, 2, border_radius=12)
        title = gfx.font(30, True).render("设置", True, settings.UI_TEXT)
        screen.blit(title, title.get_rect(center=(p.centerx, p.y + 34)))
        # 行1：模式设置（正常 = 去除灯光渲染；昏暗 = 黑暗 + 灯光）
        l = gfx.font(22).render("模式设置", True, settings.UI_TEXT)
        screen.blit(l, (self._mode_label_rect.x, self._mode_label_rect.y + 2))
        self._draw_mode_button(screen, self._mode_normal, "正常模式",
                               self._light_mode == 'normal')
        self._draw_mode_button(screen, self._mode_dim, "昏暗模式",
                               self._light_mode == 'dim')
        # 行2：音效开关
        self._draw_check(screen, self._chk_sound, self._sound_on)
        label = gfx.font(22).render("音效开关", True, settings.UI_TEXT)
        screen.blit(label, (self._chk_sound.right + 14, self._chk_sound.y - 2))
        # 行3：跳过开场剧情
        self._draw_check(screen, self._chk_rect, self._skip_intro)
        label = gfx.font(22).render("跳过开场剧情（答辩演示）", True, settings.UI_TEXT)
        screen.blit(label, (self._chk_rect.right + 14, self._chk_rect.y - 2))
        # 离开按钮
        r = self._settings_leave
        pygame.draw.rect(screen, (0x12, 0x0F, 0x0C), r, border_radius=8)
        pygame.draw.rect(screen, (0xC9, 0xA2, 0x27), r, 2, border_radius=8)
        t = gfx.font(20, True).render("离开", True, settings.UI_TEXT)
        screen.blit(t, t.get_rect(center=r.center))
