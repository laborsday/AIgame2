"""碰撞检测：空间网格 broad-phase + 圆形/矩形精确判定。"""


def circles_overlap(a, b, pad=0.0):
    dx = a.x - b.x
    dy = a.y - b.y
    r = a.radius + b.radius + pad
    return dx * dx + dy * dy <= r * r


class SpatialGrid:
    """空间网格 broad-phase：先投桶再精确判定，把 O(n²) 降到近 O(n)。

    cell 取当前实体最大直径 + 边距，保证任意重叠实体必在同桶或相邻桶。
    """

    def __init__(self, cell=48):
        self.cell = cell
        self.buckets = {}

    def _key(self, x, y):
        return (int(x // self.cell), int(y // self.cell))

    def _fit_cell(self, entities):
        cell = 24
        for e in entities:
            cell = max(cell, int(e.radius * 2 + 4))
        return cell

    def _insert_all(self, entities):
        self.buckets = {}
        self.cell = self._fit_cell(entities)
        for e in entities:
            k = self._key(e.x, e.y)
            self.buckets.setdefault(k, []).append(e)

    def unique_pairs(self, entities):
        """列表内去重候选对（用于 resolve_overlaps）。"""
        self._insert_all(entities)
        seen = set()
        for e in entities:
            kx, ky = self._key(e.x, e.y)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other in self.buckets.get((kx + dx, ky + dy), ()):
                        if other is e:
                            continue
                        a, b = (e, other) if id(e) < id(other) else (other, e)
                        key = (id(a), id(b))
                        if key in seen:
                            continue
                        seen.add(key)
                        yield a, b

    def cross_pairs(self, a_list, b_list):
        """跨列表候选对（用于 contact_pairs）。"""
        self.buckets = {}
        self.cell = self._fit_cell(a_list + b_list)
        for b in b_list:
            k = self._key(b.x, b.y)
            self.buckets.setdefault(k, []).append(b)
        for a in a_list:
            kx, ky = self._key(a.x, a.y)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for b in self.buckets.get((kx + dx, ky + dy), ()):
                        yield a, b


def contact_pairs(allies, enemies):
    """返回接触中的 (ally, enemy) 对（空间网格 broad-phase + 精确判定）。"""
    grid = SpatialGrid()
    return [(a, e) for a, e in grid.cross_pairs(allies, enemies)
            if circles_overlap(a, e)]


def _push_apart(a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    r = a.radius + b.radius
    dist_sq = dx * dx + dy * dy
    if dist_sq >= r * r:
        return
    if dist_sq < 0.0001:
        dx, dy = 0.01, 0.01
        dist = (dx * dx + dy * dy) ** 0.5
    else:
        dist = dist_sq ** 0.5
    overlap = r - dist
    nx, ny = dx / dist, dy / dist
    a.x -= nx * overlap / 2
    a.y -= ny * overlap / 2
    b.x += nx * overlap / 2
    b.y += ny * overlap / 2


def resolve_overlaps(entities, iterations=2):
    """把列表内互相重叠的实体推开（空间网格 broad-phase，各退一半）。"""
    grid = SpatialGrid()
    for _ in range(iterations):
        pairs = list(grid.unique_pairs(entities))
        for a, b in pairs:
            _push_apart(a, b)


def resolve_rect_collisions(entities, obstacles, iterations=2):
    """把圆形实体从障碍矩形中推出（房间障碍碰撞，矩形版/兼容旧格式）。"""
    for _ in range(iterations):
        for e in entities:
            for ob in obstacles:
                rect = ob.rect
                nx = max(rect.left, min(e.x, rect.right))
                ny = max(rect.top, min(e.y, rect.bottom))
                dx = e.x - nx
                dy = e.y - ny
                dist_sq = dx * dx + dy * dy
                if dist_sq >= e.radius * e.radius:
                    continue
                if dist_sq < 0.0001:
                    left = e.x - rect.left
                    right = rect.right - e.x
                    top = e.y - rect.top
                    bottom = rect.bottom - e.y
                    m = min(left, right, top, bottom)
                    if m == left:
                        e.x = rect.left - e.radius
                    elif m == right:
                        e.x = rect.right + e.radius
                    elif m == top:
                        e.y = rect.top - e.radius
                    else:
                        e.y = rect.bottom + e.radius
                else:
                    dist = dist_sq ** 0.5
                    push = e.radius - dist
                    e.x += dx / dist * push
                    e.y += dy / dist * push


def resolve_obstacle_collisions(entities, obstacles, iterations=2):
    """把圆形实体从障碍「形状」中推出（v2：贴合形状的圆簇/胶囊碰撞）。

    障碍形状由 Obstacle.resolve_circle 逐实心圆推出；拱桥血管在拱起段无碰撞，
    实体可从管下钻过。
    """
    for _ in range(iterations):
        for e in entities:
            for ob in obstacles:
                ob.resolve_circle(e)
