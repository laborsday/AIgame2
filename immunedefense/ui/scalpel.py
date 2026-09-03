"""手术刀环绕刀刃绘制（A3.1，自 Gameplay 外迁）：只读渲染，不改任何游戏状态（A4 分层硬约束）。"""
import math

import pygame

import gfx


def draw_scalpel(world, player_x, player_y, angle, blades, orbit_radius, icon):
    """3 把刀绕主角旋转（刃口顺切线）；全部数据由调用方（Gameplay 接线层）传入。"""
    img = gfx.load(icon, (26, 26), subdir='ui/icons')
    for i in range(blades):
        ang = angle + math.tau * i / blades
        bx = int(player_x + math.cos(ang) * orbit_radius)
        by = int(player_y + math.sin(ang) * orbit_radius)
        blade = pygame.transform.rotate(img, -math.degrees(ang))
        world.blit(blade, blade.get_rect(center=(bx, by)))
