"""装备/道具结算系统（A3.1，自 Gameplay 外迁）：消耗品使用、书包动作、护甲耐久、
手术刀环绕命中、三 buff 倒计时。纯逻辑——零 pygame 依赖（A4 分层硬约束）。

持有宿主 Gameplay 引用（gp）读写游戏状态；每帧由 Gameplay 只调 update(dt)。
手术刀的绘制在 ui/scalpel.py（只读渲染，本模块不碰）。
"""
import math


class Equipment:
    """装备与消耗品状态机：使用/穿脱/耐久/buff 计时，随 Gameplay 每局重置。"""

    def __init__(self, gp):
        self.gp = gp
        self.scalpel_angle = 0.0          # 手术刀：环绕角（rad）
        self._scalpel_cd = {}             # (刀序, 敌人id) → 命中冷却（0.5s）
        self.soup_regen_timer = 0.0       # 妈妈的炖汤·暖心
        self.soup_regen_per_sec = 0.0
        self._soup_float_acc = 0.0
        self.boost_timer = 0.0            # 预防针
        self.pain_timer = 0.0             # 止痛药

    # ---------- 消耗品 / 书包 ----------

    def use_item(self, item_id):
        """使用一件道具（消耗品）。返回是否真正生效（生效后调用方扣 1 个）。"""
        gp = self.gp
        entry = gp.items_data[item_id]
        eff = entry.get('effect')
        if eff is None:
            return False
        t = eff['type']
        if t == 'firefly_place':
            # v6：由 handle_bag_action 拦截进入放置模式（这里兜底：不消耗）
            return False
        px, py = gp.player.x, gp.player.y
        if t == 'heal':
            if gp.player.hp >= gp.player.max_hp:
                gp._add_floater(px, py - 44, "生命值已满", (0x9C, 0x96, 0x88))
                return False
            amt = eff['amount']
            gp.player.hp = min(gp.player.max_hp, gp.player.hp + amt)
            gp._add_floater(px, py - 24, f"+{int(amt)}", (0xE8, 0x6A, 0x6A))
        elif t == 'heal_regen':
            if gp.player.hp >= gp.player.max_hp:
                gp._add_floater(px, py - 44, "生命值已满", (0x9C, 0x96, 0x88))
                return False
            gp.player.hp = min(gp.player.max_hp,
                               gp.player.hp + eff['amount'])
            self.soup_regen_timer = float(eff['regen_duration'])
            self.soup_regen_per_sec = float(eff['regen_per_sec'])
            self._soup_float_acc = 0.0
            gp._add_floater(px, py - 24, f"+{int(eff['amount'])}", (0xD8, 0xA6, 0x5C))
            gp._add_floater(px, py - 52, "暖心…", (0xE9, 0xC4, 0x6A))
        elif t == 'atk_buff':
            self.boost_timer = float(eff['duration'])
            for w in gp.allies:
                w.atk_mult = eff['atk_mult']
        elif t == 'dmg_reduce':
            self.pain_timer = float(eff['duration'])
            gp.player.dmg_mult = eff['dmg_mult']
        elif t == 'score':
            amt = eff['amount']
            gp.score += amt
            gp._add_floater(px, py - 24, f"爸妈的支援 +{amt}", (0xE9, 0xC4, 0x6A))
        gp.audio.play('heal' if t in ('heal', 'heal_regen') else 'pickup')
        return True

    def handle_bag_action(self, action):
        """书包面板动作：('use', idx, qty) / ('wear'|'takeoff'|'discard', idx) / ('close',) / ('qty+'|'qty-',)。"""
        gp = self.gp
        kind = action[0]
        if kind == 'use':
            _, idx, qty = action
            if not (0 <= idx < len(gp.backpack.slots)):
                return
            item_id = gp.backpack.slots[idx]['id']
            if item_id == 'firefly':
                # v6 萤火虫：不即时消耗——进入「点地图放置」模式，落地才 use_one
                gp._begin_firefly_place()
                gp.bag_panel.close_popup()
                return
            if gp.items_data.get(item_id, {}).get('kind') == 'key':
                return   # v4：钥匙不可使用（只能合成/开门）
            for _ in range(qty):
                if not self.use_item(item_id):
                    break
                gp.backpack.use_one(item_id)
            gp.bag_panel.close_popup()
        elif kind in ('wear', 'takeoff'):
            _, idx = action
            if not (0 <= idx < len(gp.backpack.slots)):
                return
            item_id = gp.backpack.slots[idx]['id']
            if kind == 'wear':
                # 同类装备只保留一件激活（穿新衣旧衣自动回背包）
                for s in gp.backpack.slots:
                    if s['id'] == item_id and s is not gp.backpack.slots[idx]:
                        s['active'] = False
                gp.backpack.set_active(item_id, True)
            else:
                gp.backpack.set_active(item_id, False)
            gp.audio.play('click')
            self.on_equip_changed()
        elif kind == 'discard':
            _, idx = action
            item_id = gp.backpack.slots[idx]['id'] if 0 <= idx < len(gp.backpack.slots) else ''
            if gp.items_data.get(item_id, {}).get('kind') == 'key':
                gp.bag_panel.close_popup()   # v4：钥匙不可丢弃（防止手滑丢真结局线）
                return
            gp.backpack.discard(idx, 1)
            gp.bag_panel.close_popup()
            gp.audio.play('click')
        elif kind == 'close':
            gp.bag_panel.close_popup()
        elif kind == 'swap':
            _, i, j = action
            gp.backpack.swap(i, j)
            gp.bag_panel.close_popup()
            gp.audio.play('click')
            self.on_equip_changed()   # 交换可能改变固定格/装备格身份，但激活态不变——纯保险

    # ---------- 装备穿脱 / 护甲耐久 ----------

    def on_equip_changed(self):
        """装备穿脱回调：同步护甲值（手术刀在 update 中按激活态生效）。"""
        gp = self.gp
        slot = gp.backpack.active_slot('sweater')
        gp.player.armor = gp.items_data['sweater']['armor'] if slot else 0

    def on_armor_hit(self):
        """针织衣被直接攻击命中：扣 1 耐久；破损 → 护甲失效 + 文案。"""
        gp = self.gp
        rem, broke = gp.backpack.damage_equip('sweater', 1)
        if broke:
            gp.player.armor = 0
            gp._add_floater(gp.player.x, gp.player.y - 56,
                            "奶奶的针织衣破了…", (0xC8, 0x5A, 0x64))
            gp.audio.play('hit')

    # ---------- 每帧更新 ----------

    def update(self, dt):
        """每帧：手术刀环绕命中 + 三 buff 倒计时（Gameplay 只调这一个入口）。"""
        self._update_scalpel(dt)
        gp = self.gp
        # 预防针到期：全体白细胞攻击倍率回落
        if self.boost_timer > 0:
            self.boost_timer = max(0.0, self.boost_timer - dt)
            if self.boost_timer == 0:
                for w in gp.allies:
                    w.atk_mult = 1.0
        # 止痛药到期：受伤减伤回落
        if self.pain_timer > 0:
            self.pain_timer = max(0.0, self.pain_timer - dt)
            if self.pain_timer == 0:
                gp.player.dmg_mult = 1.0
        # 妈妈的炖汤·暖心：每秒回复（每 1s 飘一次 +N）
        if self.soup_regen_timer > 0:
            self.soup_regen_timer = max(0.0, self.soup_regen_timer - dt)
            if gp.player.hp < gp.player.max_hp:
                gp.player.hp = min(gp.player.max_hp,
                                   gp.player.hp + self.soup_regen_per_sec * dt)
                self._soup_float_acc += dt
                if self._soup_float_acc >= 1.0:
                    self._soup_float_acc -= 1.0
                    gp._add_floater(gp.player.x, gp.player.y - 24,
                                    f"+{int(self.soup_regen_per_sec)}",
                                    (0xD8, 0xA6, 0x5C))

    def _update_scalpel(self, dt):
        """手术刀：3 把刀绕主角旋转；敌人接触受伤害，同目标每刀 0.5s 结算一次。"""
        gp = self.gp
        slot = gp.backpack.active_slot('scalpel')
        if slot is None:
            self._scalpel_cd.clear()
            return
        entry = gp.items_data['scalpel']
        self.scalpel_angle = (self.scalpel_angle + entry['orbit_speed'] * dt) % math.tau
        for k in list(self._scalpel_cd):
            self._scalpel_cd[k] -= dt
            if self._scalpel_cd[k] <= 0:
                del self._scalpel_cd[k]
        r, n = entry['orbit_radius'], entry['blades']
        for i in range(n):
            ang = self.scalpel_angle + math.tau * i / n
            bx = gp.player.x + math.cos(ang) * r
            by = gp.player.y + math.sin(ang) * r
            for c in gp.enemies:
                if (not c.alive or getattr(c, 'disguised', False)):
                    continue
                if (c.x - bx) ** 2 + (c.y - by) ** 2 <= (c.radius + 14) ** 2:
                    k = (i, id(c))
                    if k in self._scalpel_cd:
                        continue
                    self._scalpel_cd[k] = entry['hit_cooldown']
                    c.take_damage(entry['damage'])
                    gp.fx.spawn_flash(c.x, c.y, 20, (0xD8, 0xE0, 0xE8))
                    gp._add_floater(c.x, c.y - 18, entry['damage'], (0xD8, 0xE0, 0xE8))
                    rem, broke = gp.backpack.damage_equip('scalpel', 1)
                    if broke:
                        gp._add_floater(gp.player.x, gp.player.y - 56,
                                        "手术刀折断了…", (0x9C, 0xA8, 0xB8))
                        gp.audio.play('hit')
                        return   # 刀已折断，本帧收工
