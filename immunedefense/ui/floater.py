"""ui/floater.py：伤害飘字渲染（A4 分层后自 systems/ 迁入）——FloatText 纯展示：
浮升位移 + 生命周期 + 绘制到屏幕。systems/ 禁 pygame/blit，渲染一律住 ui/。"""
import gfx


class FloatText:
    """伤害/提示飘字：上浮 + 存活期，绘制到调用方传入的 screen。"""

    def __init__(self, x, y, text, color, life=0.8):
        self.x, self.y = float(x), float(y)
        self.text = text
        self.color = color
        self.life = life
        self.alive = True

    def update(self, dt):
        self.y -= 42 * dt
        self.life -= dt
        if self.life <= 0:
            self.alive = False

    def draw(self, screen):
        img = gfx.font(20, True).render(self.text, True, self.color)
        screen.blit(img, img.get_rect(center=(int(self.x), int(self.y))))
