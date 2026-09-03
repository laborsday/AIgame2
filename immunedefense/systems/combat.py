"""v2 战斗结算纯函数（从 gameplay.py 拆分的第一步）：残血狂暴倍率 / 档位判定。

所有数值来自 data/balance.json 的 rage 节点，代码不写死。
"""


def rage_bonus(hp_ratio, config):
    """按当前血量比例返回狂暴攻击加成（0.0~0.35），档位间线性插值。

    config['tiers'] 形如 [{'hp_ratio': 0.60, 'bonus': 0.00}, ...]，按 hp_ratio 降序。
    血量高于基准档（默认 60%）无加成；低于最低档后封顶。
    """
    tiers = config['tiers']
    if hp_ratio >= tiers[0]['hp_ratio']:
        return tiers[0]['bonus']
    for i in range(len(tiers) - 1):
        hi, lo = tiers[i], tiers[i + 1]
        if lo['hp_ratio'] <= hp_ratio <= hi['hp_ratio']:
            span = max(1e-6, hi['hp_ratio'] - lo['hp_ratio'])
            t = (hi['hp_ratio'] - hp_ratio) / span
            return hi['bonus'] + (lo['bonus'] - hi['bonus']) * t
    return tiers[-1]['bonus']


def rage_tier(hp_ratio, config):
    """返回狂暴档位：0=无加成，1:≤50%，2:≤30%，3:≤20%（与 tiers 下标对齐）。

    从最低档倒序判定，保证低血量命中更深的档位（如 30% 血应返回档2 而非档1）。
    """
    tiers = config['tiers']
    for i in range(len(tiers) - 1, 0, -1):
        if hp_ratio <= tiers[i]['hp_ratio']:
            return i
    return 0


def aura_bonus_map(enemies):
    """召唤精英加攻光环：返回 {id(e): bonus}（唤醒状态下范围内敌人攻击+）。

    多个光环重叠时取最高加成。数值来自 enemies.json 的 aura_radius/aura_atk_bonus。
    """
    bonus = {}
    for c in enemies:
        if not (getattr(c, 'aura_radius', 0) > 0 and c.alive and c.awake):
            continue
        for e in enemies:
            if e is not c and e.dist_to(c) <= c.aura_radius + e.radius:
                bonus[id(e)] = max(bonus.get(id(e), 0), c.aura_atk_bonus)
    return bonus


def shield_break_hits(enemies, targets):
    """护盾精英破盾震爆：返回 [(elite, target, dmg, (nx, ny))] 命中事件。

    击退方向为指向目标的单位向量，由调用方应用（本函数只做结算判定）。
    """
    hits = []
    for c in enemies:
        if not getattr(c, '_shield_broke', False):
            continue
        c._shield_broke = False
        for w in targets:
            if w.alive and c.dist_to(w) <= c.shield_break_radius + w.radius:
                dx, dy = w.x - c.x, w.y - c.y
                d = (dx * dx + dy * dy) ** 0.5 or 1.0
                hits.append((c, w, c.shield_break_damage, (dx / d, dy / d)))
    return hits


def resolve_zone_damage(zones, entities, dt):
    """场地毒区结算：对范围内实体持续伤害，返回存活毒区列表。"""
    alive = []
    for z in zones:
        z.update(dt, entities)
        if z.alive:
            alive.append(z)
    return alive
