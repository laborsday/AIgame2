"""Game 主类：初始化、主循环、场景调度（策划书 4.4）。"""
import os

import pygame

import settings
from .audio import AudioBus
from .configs import get_config


class Game:
    def __init__(self):
        pygame.init()
        try:
            pygame.key.stop_text_input()  # 防止中文输入法吞掉 WASD
        except AttributeError:
            pass
        pygame.display.set_caption("免疫防线")
        self.screen = pygame.display.set_mode((settings.WIDTH, settings.HEIGHT))
        self._ime_off()                   # v3：进入游戏自动纯英文，无需手动切输入法
        self.clock = pygame.time.Clock()
        self.running = True
        self.seed = None   # 开局种子（主菜单生成，传给 Gameplay）
        self.scenes = None  # 由 main 注入 SceneManager 和初始场景
        # 音频总线：菜单/祭坛/战斗共享（音效开关即时生效，见 core/menu.py）
        self.audio = AudioBus()
        self.audio.set_enabled(get_config()["sound_on"])

    @staticmethod
    def _ime_off():
        """Windows：剥夺本窗口的 IME 上下文（中文输入法不接管键盘）。"""
        if os.name != 'nt':
            return
        try:
            import ctypes
            hwnd = pygame.display.get_wm_info().get('window')
            if hwnd:
                ctypes.windll.imm32.ImmAssociateContext(hwnd, None)
        except Exception:
            pass  # 非标准环境：忽略，保持原输入法行为

    def run(self):
        while self.running:
            dt = self.clock.tick(settings.FPS) / 1000.0
            events = pygame.event.get()
            for e in events:
                if e.type == pygame.QUIT:
                    self.running = False
                elif hasattr(pygame, 'WINDOWFOCUSGAINED') and e.type == pygame.WINDOWFOCUSGAINED:
                    self._ime_off()   # 切回游戏窗口时再次关闭 IME

            scene = self.scenes.current()
            if scene is None:
                break
            scene.handle_events(events)
            scene.update(dt)
            scene.render(self.screen)
            pygame.display.flip()

        pygame.quit()
