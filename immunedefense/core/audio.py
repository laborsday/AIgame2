"""音频总线：外部音频文件优先（assets/audio/），缺失回退 core/sfx 程序化合成；mixer 失败静默降级。

- 音效：`assets/audio/{name}.wav|.ogg` 存在则加载；否则用 core/sfx.py 的音效表实时合成
  （gen_sfx.py 批量导出的 wav 与运行时合成共用同一份 Patch 定义，音色一致）。
- 配音：`assets/audio/voice/{key}.wav|.ogg`，经 `AudioBus.voice(key)` 在独立通道播放
  （互斥：新配音打断上一段），文件缺失时静默。
- 节流：`play(name, throttle=0.0)`——高频事件（连续命中/毒区）给最小间隔防刷屏。
"""
import os
import time

import pygame

import paths
from core import sfx

RATE = 22050   # mixer 采样率；44100Hz 的 wav 由 pygame 加载时自动转换

try:
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=RATE, size=-16, channels=1, buffer=512)
    _MIXER_OK = pygame.mixer.get_init() is not None
except Exception:
    _MIXER_OK = False

if _MIXER_OK:
    try:
        pygame.mixer.set_num_channels(24)   # 战斗音效并发多，留足发声通道
    except Exception:
        pass


def _load_sound(name):
    """从 assets/audio/{name}.wav|.ogg 加载外部音效；文件缺失/损坏返回 None。"""
    if not _MIXER_OK:
        return None
    base = os.path.join(paths.assets_dir(), 'audio')
    for ext in ('.wav', '.ogg'):
        p = os.path.join(base, name + ext)
        if os.path.isfile(p):
            try:
                return pygame.mixer.Sound(p)
            except Exception:
                return None
    return None


def _synth_sound(name, rate=RATE):
    """用 core/sfx 音效表合成；mixer 不可用时返回 None。"""
    if not _MIXER_OK:
        return None
    try:
        buf = sfx.render(name, rate)
        if not buf:
            return None
        return pygame.mixer.Sound(buffer=buf.tobytes())
    except Exception:
        return None


# 全部音效名（顺序即 sfx.SFX 定义顺序；gen_sfx.py 与测试以此为准）
SOUND_NAMES = tuple(sfx.names())


class AudioBus:
    def __init__(self):
        self.enabled = True                        # 音效总开关（设置 → config.sound_on）
        # 外部音频文件优先，缺失回退 sfx 合成音（保持 play() 接口不变）
        self._sounds = {}
        for name in SOUND_NAMES:
            self._sounds[name] = _load_sound(name) or _synth_sound(name)
        self._last = {}                            # 节流计时 {name: 上次播放时刻}
        self._heart_cd = 0.0
        self._voices = {}                          # 配音缓存 {key: Sound}
        try:
            self._voice_chan = pygame.mixer.Channel(1)   # 独立配音通道（互斥）
        except Exception:
            self._voice_chan = None

    def set_enabled(self, value):
        """主开关关闭时立即静音（停止所有通道）。"""
        self.enabled = bool(value)
        if not self.enabled:
            try:
                pygame.mixer.stop()
            except Exception:
                pass

    def play(self, name, throttle=0.0):
        """播放音效；throttle>0 时同名音效最短间隔（秒），高频事件防刷屏。"""
        if not self.enabled:
            return
        if throttle > 0:
            now = time.monotonic()
            if now - self._last.get(name, -1e9) < throttle:
                return
            self._last[name] = now
        s = self._sounds.get(name)
        if s:
            s.play()

    def voice(self, key):
        """播放配音 assets/audio/voice/{key}.wav|.ogg；文件缺失静默。新配音打断上一段。"""
        if not self.enabled or not _MIXER_OK:
            return
        s = self._voices.get(key)
        if s is None:
            s = self._load_voice(key)
            if s is None:
                return
            self._voices[key] = s
        if self._voice_chan is not None:
            self._voice_chan.stop()
            self._voice_chan.play(s)
        else:
            s.play()

    @staticmethod
    def _load_voice(key):
        base = os.path.join(paths.assets_dir(), 'audio', 'voice')
        for ext in ('.wav', '.ogg'):
            p = os.path.join(base, key + ext)
            if os.path.isfile(p):
                try:
                    return pygame.mixer.Sound(p)
                except Exception:
                    return None
        return None

    def heartbeat(self, ratio, dt):
        """按血量区间播放心跳（低血更快）。"""
        self._heart_cd -= dt
        if self._heart_cd > 0:
            return
        self._heart_cd = 0.45 + 0.75 * ratio
        self.play('heartbeat')
