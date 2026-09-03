"""实体基类：位置、速度、血量、阵营、距离。"""
import random


class Entity:
    def __init__(self, x, y, radius, faction, hp):
        self.x = float(x)
        self.y = float(y)
        self.radius = radius
        self.faction = faction  # 'player' | 'ally' | 'enemy'
        self.hp = hp
        self.max_hp = hp
        self.vx = 0.0
        self.vy = 0.0
        self.alive = True
        self._t = 0.0        # 动画时间源（帧率无关，子类动画以此驱动）
        self._phase = random.random() * 6.2832   # 动画相位错开（同屏实体动作不同步）

    def update(self, dt):
        """按当前速度位移（子类先设置 vx/vy 再调用）。"""
        self._t += dt
        self.x += self.vx * dt
        self.y += self.vy * dt

    def take_damage(self, dmg):
        self.hp -= dmg
        if self.hp <= 0:
            self.hp = 0
            self.alive = False

    def dist_to(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return (dx * dx + dy * dy) ** 0.5

    def draw(self, screen):
        raise NotImplementedError
