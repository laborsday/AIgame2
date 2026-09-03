"""敌方弹幕投射物：纯运动学，撞玩家或障碍即消。"""
import pygame


class EnemyProjectile:
    def __init__(self, x, y, vx, vy, damage=6, lifetime=5.0, owner=None):
        self.x = float(x)
        self.y = float(y)
        self.vx = vx
        self.vy = vy
        self.damage = damage
        self.lifetime = lifetime
        self.radius = 6
        self.owner = owner
        self.alive = True

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.lifetime -= dt
        if self.lifetime <= 0:
            self.alive = False

    def draw(self, screen):
        pygame.draw.circle(screen, (0xD8, 0x5C, 0x50),
                           (int(self.x), int(self.y)), self.radius)
        pygame.draw.circle(screen, (0xFF, 0x8A, 0x6A),
                           (int(self.x), int(self.y)), self.radius - 2)
