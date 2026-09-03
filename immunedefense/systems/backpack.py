"""书包（背包）核心：7 格 · 格 0 = 固定格（留念格）· 消耗品每格上限 6 · 装备每格 1 件。

规则定稿（v3道具层.md §1 + v4祭点层.md §6）：
- 7 格固定；格 0 = 固定格（重开不掉落，可放任意道具）；普通格 6 格
- 消耗品同种一格堆叠（上限 6，六六大顺）；装备不可堆叠（每格 1 件）
- 钥匙（kind='key'）：全局唯一（左半/右半/完整各至多 1 把），不可堆叠
- 满格 add 失败（调用方提示「书包已满！」并保留地面道具）
- 装备实例带 dur（当前耐久）/ dur_max（最大耐久）/ active（穿戴 / 使用中）
- 每局重置（重开新局新建 Backpack），固定格由 meta.fixed_slot 注入
"""
from typing import Optional

STACK_MAX_CONSUMABLE = 6


class Backpack:
    CAPACITY = 7          # v4：6 → 7（格 0 = 固定格）
    FIXED_INDEX = 0
    KEY_IDS = ('key_left', 'key_right', 'key_full')

    def __init__(self, capacity: Optional[int] = None,
                 stack_max: Optional[int] = None):
        self.capacity = capacity if capacity is not None else self.CAPACITY
        self.stack_max = stack_max if stack_max is not None else STACK_MAX_CONSUMABLE
        # 格子：{'id': str, 'count': int, 'dur': Optional[int],
        #        'dur_max': Optional[int], 'active': bool}
        self.slots = []

    # ---------- 查询 ----------

    @property
    def fixed_slot(self):
        return self.slots[0] if len(self.slots) > self.FIXED_INDEX else None

    def is_full(self) -> bool:
        return len(self.slots) >= self.capacity

    def find(self, item_id: str) -> Optional[int]:
        for i, s in enumerate(self.slots):
            if s['id'] == item_id:
                return i
        return None

    def count(self, item_id: str) -> int:
        i = self.find(item_id)
        return self.slots[i]['count'] if i is not None else 0

    def total_count(self) -> int:
        return sum(s['count'] for s in self.slots)

    def active_slot(self, item_id: Optional[str] = None):
        """返回当前激活的装备格（可选限定 id）。"""
        for s in self.slots:
            if s['active'] and (item_id is None or s['id'] == item_id):
                return s
        return None

    def has_key(self, item_id: str) -> bool:
        """钥匙类唯一性：包内是否已有该钥匙（含固定格）。"""
        return item_id in self.KEY_IDS and self.find(item_id) is not None

    # ---------- 增删 ----------

    def add(self, item_id: str, entry: dict, count: int = 1) -> bool:
        """放入道具。成功返回 True；满格 / 堆叠超上限 / 钥匙重复返回 False（不部分放入）。"""
        kind = entry.get('kind', 'consumable')
        if kind == 'key':
            # 钥匙：全局唯一一件（左半/右半/完整各 1）；不堆叠
            if self.has_key(item_id) or self.is_full():
                return False
            self.slots.append({'id': item_id, 'count': 1,
                               'dur': None, 'dur_max': None, 'active': False})
            return True
        if kind == 'equip':
            # 装备：每格 1 件；同名可持有多件（各占一格，一穿一备）
            if self.is_full():
                return False
            dur_max = entry.get('durability')
            self.slots.append({'id': item_id, 'count': 1,
                               'dur': dur_max, 'dur_max': dur_max, 'active': False})
            return True
        cap = min(self.stack_max, int(entry.get('stack_max', self.stack_max)))
        i = self.find(item_id)
        if i is not None:
            s = self.slots[i]
            if s['count'] >= cap:
                return False
            s['count'] = min(cap, s['count'] + count)
            return True
        if self.is_full():
            return False
        self.slots.append({'id': item_id, 'count': min(cap, count),
                           'dur': None, 'dur_max': None, 'active': False})
        return True

    def insert_slot(self, index: int, item_id: str, entry: dict) -> bool:
        """强制占位插入（钥匙合成品落格等场景）；index 处已有格则顺延。"""
        if self.is_full():
            return False
        dur_max = entry.get('durability')
        self.slots.insert(min(index, len(self.slots)),
                          {'id': item_id, 'count': 1,
                           'dur': dur_max, 'dur_max': dur_max, 'active': False})
        return True

    def use_one(self, item_id: str) -> bool:
        """消耗 1 个（消耗品）。返回是否成功；归零自动移除格子。"""
        i = self.find(item_id)
        if i is None:
            return False
        s = self.slots[i]
        s['count'] -= 1
        if s['count'] <= 0:
            self.slots.pop(i)
        return True

    def discard(self, index: int, n: int = 1) -> bool:
        """丢弃格子里 n 个；归零移除格子。钥匙类由调用方（UI/Equipment）拦截。"""
        if not (0 <= index < len(self.slots)):
            return False
        s = self.slots[index]
        s['count'] -= n
        if s['count'] <= 0:
            self.slots.pop(index)
        return True

    def remove_slot(self, index: int) -> bool:
        if not (0 <= index < len(self.slots)):
            return False
        self.slots.pop(index)
        return True

    def swap(self, i: int, j: int) -> bool:
        """交换两格位置（背包排序/固定格拖入拖出）。"""
        if not (0 <= i < len(self.slots) and 0 <= j < len(self.slots)):
            return False
        self.slots[i], self.slots[j] = self.slots[j], self.slots[i]
        return True

    # ---------- 固定格（meta 注入 / 导出） ----------

    def restore_fixed(self, meta_slot) -> bool:
        """从 meta.fixed_slot 恢复固定格（重开/开局注入；激活态重置）。"""
        if not isinstance(meta_slot, dict) or not meta_slot.get('id'):
            return False
        self.slots.insert(self.FIXED_INDEX, {
            'id': meta_slot['id'], 'count': int(meta_slot.get('count', 1)),
            'dur': meta_slot.get('dur'), 'dur_max': meta_slot.get('dur_max'),
            'active': False})
        return True

    def export_fixed(self):
        """导出固定格 → meta.fixed_slot（空则 None）。"""
        s = self.fixed_slot
        if s is None:
            return None
        return {'id': s['id'], 'count': s['count'],
                'dur': s['dur'], 'dur_max': s['dur_max']}

    # ---------- 装备 ----------

    def set_active(self, item_id: str, active: bool) -> bool:
        i = self.find(item_id)
        if i is None:
            return False
        self.slots[i]['active'] = active
        return True

    def damage_equip(self, item_id: str, n: int = 1):
        """扣装备耐久。返回 (剩余耐久, 是否报废)；非装备返回 (None, False)。"""
        i = self.find(item_id)
        if i is None:
            return None, False
        s = self.slots[i]
        if s['dur'] is None:
            return None, False
        s['dur'] = max(0, s['dur'] - n)
        if s['dur'] == 0:
            self.slots.pop(i)
            return 0, True
        return s['dur'], False
