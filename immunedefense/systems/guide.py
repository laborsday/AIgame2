"""引导系统：标定 + 身位双轨（方案 D，GDD 2.2）。"""
import math


class GroundTarget:
    """标定在地面上的点（移动/集火点）。"""
    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.radius = 1
        self.alive = True


class GuideSystem:
    FORMATION_RADIUS = 45.0  # 阵型圈半径

    def formation_slot(self, index, count):
        """阵型槽位：第 index 个白细胞绕玩家的位置偏移。"""
        if count <= 1:
            return (-self.FORMATION_RADIUS, 0.0)
        angle = math.tau * index / count
        return (math.cos(angle) * self.FORMATION_RADIUS,
                math.sin(angle) * self.FORMATION_RADIUS)

    def update_wbc(self, player, wbc, slot, projectiles):
        """单帧更新：有标定且在引导范围内 → 差异化响应；否则回归身位。"""
        target = player.target
        if target is not None and wbc.dist_to(player) <= player.guide_radius:
            wbc.respond_to_target(player, target, projectiles)
        else:
            wbc.seek(player.x + slot[0], player.y + slot[1])
