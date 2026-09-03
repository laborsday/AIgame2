"""房间系统：加载房间模板池（data/rooms.json）+ 8 房递进 + 出口。

8 房递进（GDD 5.2，初始教学房 + 7 间战斗房）：每间房从模板池按类型随机抽一个布局；
出口 kind（door 门 / vessel_hole 血管洞口）由游戏按层边界决定。
"""
import json
import os

import paths
from systems.rng import RunRNG
from entities.cancer import (Cancer, Variant, EliteRage, EliteShield,
                             EliteSummoner, BossCore)
from entities.wbc import WBC_ORDER

ROOMS_JSON = os.path.join(paths.data_dir(), "rooms.json")

# 8 房递进：(层, 类型, 敌人类型列表)
# 初始房 = 以撒地下室式教学房：无怪、出口常开、地板印玩法说明（gen_start_floor.py）
SEQUENCE = [
    (1, 'start', []),
    (1, 'normal', [Cancer, Cancer, Cancer]),
    (1, 'normal', [Cancer, Cancer, Variant]),
    (2, 'normal', [Cancer, Variant, Cancer]),
    (2, 'normal', [EliteRage, Cancer, Cancer]),
    (2, 'elite', [EliteShield, EliteSummoner]),        # 第 2 层小 boss
    (3, 'elite', [EliteRage, EliteSummoner]),
    (3, 'boss', [BossCore]),
]

SHOP_PROB = {1: 0.30, 2: 0.50, 3: 0.70}
FREE_WBC_PROB = {1: 0.60, 2: 0.40, 3: 0.25}
WBC_WEIGHTS = {
    1: {'neutrophil': 0.6, 't_cell': 0.2, 'macrophage': 0.2, 'nk': 0.0},
    2: {'neutrophil': 0.3, 't_cell': 0.3, 'macrophage': 0.3, 'nk': 0.1},
    3: {'neutrophil': 0.2, 't_cell': 0.25, 'macrophage': 0.25, 'nk': 0.3},
}


def load_room_defs(path=None):
    p = path or ROOMS_JSON
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class RoomManager:
    def __init__(self, screen_w, screen_h, defs=None, rng=None):
        self.w = screen_w
        self.h = screen_h
        self.defs = defs if defs is not None else load_room_defs()
        self.rng = rng or RunRNG()
        self.sequences = SEQUENCE
        self.rooms = SEQUENCE        # 兼容：HUD len(self.room.rooms)
        self.index = 0
        # 每间房从模板池按类型随机抽一个布局
        pool = {'normal': [], 'elite': [], 'boss': [], 'start': []}
        for d in self.defs.get('rooms', []):
            if d.get('type') in pool:
                pool[d['type']].append(d)
        self.templates = []
        for layer, kind, _wave in self.sequences:
            choices = pool[kind]
            self.templates.append(self.rng.choice(choices) if choices
                                  else {'obstacles': [], 'exits': []})
        self.current_tpl = self.templates[0] if self.templates else {'obstacles': [], 'exits': []}

    @property
    def done(self):
        return self.index >= len(self.sequences)

    @property
    def layer(self):
        return self.sequences[self.index][0] if not self.done else 3

    def spawn_room(self):
        layer, kind, wave = self.sequences[self.index]
        tpl = self.templates[self.index]
        self.current_tpl = tpl
        zone = tpl.get('spawn_zones') or [{'x': 100, 'y': 100, 'w': 1080, 'h': 520}]
        z = zone[0]
        enemies = []
        for cls in wave:
            e = cls(self.rng.randint(z['x'], min(z['x'] + z['w'], self.w - 60)),
                    self.rng.randint(z['y'], min(z['y'] + z['h'], self.h - 60)))
            # 分级伪装随层递进（v2 §5.2）：层2 伪装红细胞/宝箱，层3 伪装己方白细胞
            if isinstance(e, Variant):
                e.disguise_tier = min(3, max(1, layer))
            enemies.append(e)
        free_wbc = []
        if self.index == 0:
            # 初始房：随机刷新 4 个游离白细胞，四品类等概率（可重复，非一各一）
            free_wbc = [self.rng.choice(WBC_ORDER) for _ in range(4)]
        elif self.rng.random() < FREE_WBC_PROB[layer]:
            free_wbc = [self._rand_wbc(layer) for _ in range(self.rng.randint(1, 2))]
        return layer, kind, enemies, free_wbc

    def advance(self):
        self.index += 1

    def back(self):
        """返回上一房（v3：已清房可返回）。"""
        self.index = max(0, self.index - 1)

    def roll_shop(self):
        """判定本房是否生成房内商店台（以撒式）。

        每房独立判定，无全局「只开一家」限制：
        - BOSS 前房（倒数第 2 间）强制刷新，保证进 BOSS 前有补给；
        - 其余房按层概率 SHOP_PROB 随机。
        """
        if self.index >= len(self.sequences) - 2:  # BOSS 前房必刷
            return True
        return self.rng.random() < SHOP_PROB[self.layer]

    def next_layer(self):
        if self.index + 1 < len(self.sequences):
            return self.sequences[self.index + 1][0]
        return 3

    def _rand_wbc(self, layer):
        types = list(WBC_WEIGHTS[layer].keys())
        weights = list(WBC_WEIGHTS[layer].values())
        return self.rng.choices(types, weights=weights)[0]
