"""ui/sprites.py：精灵图动画系统（美术优化批次 · 精灵图）。

支持「sprite sheet + JSON 元数据」驱动的方向/状态动画：

- `SpriteSheet`：按 (row, col) 切帧并缓存（水平镜像、目标尺寸缩放一并缓存）。
- `SpriteAnimator`：dt 驱动帧计时，方向（down/up/left/right）+ 状态（idle/walk）状态机。
- 素材缺失时 `image()` 返回 None，调用方回退单帧贴图——游戏任意时刻可运行。

素材约定（AI 生成后放入 `assets/sprites/`，代码零改动）：

    {name}.png   sprite sheet：行 = 方向、列 = 帧（每帧等宽等高）
    {name}.json  元数据：
    {
      "sheet": "player.png", "frame_w": 96, "frame_h": 96, "fps": 8,
      "rows": {"down": 0, "up": 1, "side": 2},
      "states": {"idle": [0], "walk": [1, 2, 3, 4]},
      "dir": {"down": ["down", false], "up": ["up", false],
              "left": ["side", true], "right": ["side", false]}
    }
    dir 键 = 方向名 → [行名, 是否水平镜像]（左右可共用 side 行镜像，省素材量）。

A4 分层：渲染住 ui/（systems/ 保持纯逻辑）。
"""
import json
import os

import pygame

import gfx
import paths


def _norm(frames):
    return frames if isinstance(frames, list) else [frames]


class SpriteSheet:
    """sprite sheet 切帧：按 (row, col) 取子图并缓存（镜像/缩放一并缓存）。"""

    def __init__(self, path, frame_w, frame_h):
        self._img = pygame.image.load(path).convert_alpha()
        self.fw, self.fh = frame_w, frame_h
        self._cache = {}

    def frame(self, row, col, flip_x=False, size=None):
        key = (row, col, flip_x, size)
        s = self._cache.get(key)
        if s is None:
            rect = pygame.Rect(col * self.fw, row * self.fh, self.fw, self.fh)
            s = self._img.subsurface(rect).copy()
            if flip_x:
                s = pygame.transform.flip(s, True, False)
            if size:
                s = pygame.transform.smoothscale(s, size)
            self._cache[key] = s
        return s


class SpriteAnimator:
    """方向 + 状态动画器：dt 驱动帧计时；缺配置时 image() 返回 None（调用方回退）。"""

    def __init__(self, sheet, meta, size=None):
        self.sheet = sheet
        self.meta = meta
        self.size = size
        self.fps = meta.get('fps', 8)
        self.rows = meta.get('rows', {})                # 行名 → 行号
        self.states = {k: _norm(v) for k, v in meta.get('states', {}).items()}
        self.dir_cfg = meta.get('dir', {})              # 方向名 → [行名, flip_x]
        self.direction = 'down'
        self.state = 'idle'
        self._t = 0.0
        self._idx = 0

    def set_direction(self, d):
        if d in self.dir_cfg:
            self.direction = d

    def set_state(self, s):
        if s != self.state and s in self.states:
            self.state = s
            self._t = 0.0
            self._idx = 0

    def update(self, dt):
        frames = self.states.get(self.state, [0])
        if len(frames) <= 1:
            return
        self._t += dt
        interval = 1.0 / max(1, self.fps)
        while self._t >= interval:
            self._t -= interval
            self._idx = (self._idx + 1) % len(frames)

    def image(self):
        """返回当前帧 Surface；无方向配置/缺帧时返回 None。"""
        cfg = self.dir_cfg.get(self.direction)
        if not cfg or self.sheet is None:
            return None
        row_name, flip_x = cfg
        row = self.rows.get(row_name)
        if row is None:
            return None
        frames = self.states.get(self.state) or [0]
        col = frames[min(self._idx, len(frames) - 1)]
        return self.sheet.frame(row, col, flip_x=flip_x, size=self.size)


def load_animator(name, size=None):
    """按 assets/sprites/{name}.json 元数据加载动画器；素材缺失返回 None（回退单帧）。"""
    try:
        base = os.path.join(paths.assets_dir(), 'sprites')
        with open(os.path.join(base, f'{name}.json'), encoding='utf-8') as f:
            meta = json.load(f)
        sheet = SpriteSheet(os.path.join(base, meta['sheet']),
                            meta['frame_w'], meta['frame_h'])
        return SpriteAnimator(sheet, meta, size=size)
    except Exception:
        return None
