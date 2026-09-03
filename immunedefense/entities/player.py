"""玩家：大学生意识体。脆皮、跑得快、无攻击。持有标定目标与细胞卡牌。"""
import pygame

import gfx

from ui.sprites import load_animator   # 精灵图动画（美术优化批次；缺素材回退单帧）
from .entity import Entity


class Player(Entity):
    SPEED = 240
    CONTACT_HURT_CD = 0.5  # 被接触伤害后的短暂无敌
    TARGET_TIMEOUT = 3.0   # 标定超时（GDD 2.2）

    def __init__(self, x, y):
        super().__init__(x, y, radius=14, faction='player', hp=40)
        self._hurt_cd = 0.0
        self.shield = 0         # 护盾格：优先抵消伤害（红细胞体系扩展）
        self.speed = self.SPEED
        self.dmg_mult = 1.0     # 受伤倍率（止痛药临时降低）
        self.armor = 0          # 护甲（奶奶的针织衣：直接攻击 −armor，每次被击耗 1 耐久）
        self.on_hit_cb = None   # 直接攻击命中回调（Gameplay 挂接：扣护甲耐久/破损提示）
        self.on_life_guard = None  # v5 成就「战友的徽章」锁血回调（hp≤0 时询问能否保住）
        self.guide_radius = 200   # 引导范围：核心属性（GDD 8.2）
        self.wbc_cap = 4          # 白细胞上限（GDD 8.2）
        self.target = None        # 标定目标（实体或 GroundTarget）
        self.target_timer = 0.0
        # 起始卡牌：真正从零开始（初始房 4 个随机游离细胞是唯一的卡牌来源）
        self.cards = {}
        # 精灵图动画（walk/idle + 4 方向）；素材未到位时 None → draw 回退单帧贴图
        self._anim = load_animator('player', size=(47, 81))

    def set_target(self, target):
        self.target = target
        self.target_timer = self.TARGET_TIMEOUT

    def clear_target(self):
        self.target = None

    def handle_input(self, keys):
        dx = dy = 0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += 1

        if dx or dy:  # 归一化：斜向不加速
            length = (dx * dx + dy * dy) ** 0.5
            dx /= length
            dy /= length

        self.vx = dx * self.speed
        self.vy = dy * self.speed

    def take_damage(self, dmg):
        """护盾格优先抵消伤害，溢出部分才扣血。"""
        if self.shield > 0:
            self.shield -= dmg
            if self.shield < 0:
                dmg = -self.shield
                self.shield = 0.0
            else:
                dmg = 0.0
        if dmg > 0:
            super().take_damage(dmg)
            # v5 成就锁血（最后一道防线：减伤/盾全部结算后）
            if not self.alive and self.on_life_guard is not None:
                if self.on_life_guard():
                    self.hp = 1.0
                    self.alive = True

    def try_contact_damage(self, amount):
        """接触伤害 + 冷却，避免每帧掉血秒死。"""
        if self._hurt_cd > 0:
            return
        self.take_damage(amount)
        self._hurt_cd = self.CONTACT_HURT_CD

    def update(self, dt):
        super().update(dt)
        self._hurt_cd = max(0.0, self._hurt_cd - dt)
        if self.target is not None:
            self.target_timer -= dt
            if self.target_timer <= 0 or not self.target.alive:
                self.target = None
        self._sync_anim(dt)

    def _sync_anim(self, dt):
        """按速度向量同步动画方向/状态并推进帧（俯视角 4 方向，侧向镜像复用）。"""
        anim = self._anim
        if anim is None:
            return
        if abs(self.vx) >= abs(self.vy) and self.vx != 0:
            anim.set_direction('right' if self.vx > 0 else 'left')
        elif self.vy != 0:
            anim.set_direction('down' if self.vy > 0 else 'up')
        moving = self.vx != 0 or self.vy != 0
        anim.set_state('walk' if moving else 'idle')
        anim.update(dt)

    def draw(self, screen):
        cx, cy = int(self.x), int(self.y)
        # 地面柔光：深底上突出白色/蓝条纹角色（可读性）
        glow = pygame.Surface((120, 120), pygame.SRCALPHA)
        pygame.draw.circle(glow, (0x9F, 0xE5, 0xDA, 66), (60, 60), 40)
        pygame.draw.circle(glow, (0xDD, 0xEA, 0xE6, 22), (60, 60), 50)
        screen.blit(glow, (cx - 60, cy - 54))
        # 角色形象：精灵图动画优先；素材缺失回退单帧贴图
        img = self._anim.image() if self._anim is not None else None
        if img is None:
            try:
                # 主角原画 v2（红眼 Q 版，宽高比 0.582）——保形缩放
                img = gfx.load("player_char.png", (47, 81))
            except Exception:
                img = gfx.load("player_avatar_96.png", (56, 56))
        screen.blit(img, img.get_rect(center=(cx, cy)))
