"""祭点（谐音"绩点"，象征队友祭天法力无边）：跨局累计的 meta 档案。

v4（v4祭点层.md）：meta 扩展为完整档案——
- offering          ：累计祭点
- next_buffs        ：已买、仅下一局生效的记忆类 buff
- memories          ：分型牺牲史（neutrophil/macrophage/t_cell/nk 的 deaths/kills）
- learned_memories  ：买过的记忆（Ⅱ 档解锁判定）
- boss_beaten_count ：击败 BOSS 次数（Ⅱ 档里程碑）
- pending_physical  ：实物类已兑换、待注入下一局开局背包的物品列表
- fixed_slot        ：背包固定格（留念格）跨局保留的道具
- perfect_ne_count  ：完美局次数（TE 与成就门槛）
- te2_seen          ：TE2（档案室左半线）是否已播过
- achievements      ：成就解锁列表

v5（v5数据库系统.md）：**存储底层迁移至本地 SQLite**（systems/dblocal.py）——
- 函数签名与字段结构**完全不变**（全部调用点零改动）
- 旧 data/meta.json 首启自动迁移入库（写 .migrated 标记，不删原档）
- path 参数语义：测试注入独立档（*.json 路径 → 同名 .db）
"""
import json
import os

import paths
from systems.dblocal import (load_state_meta, save_state_meta,
                             resolve_db_path, init_db)

META_PATH = os.path.join(paths.data_dir(), "meta.json")
MIGRATED_FLAG = META_PATH + ".migrated"

MEMORY_TYPES = ('neutrophil', 'macrophage', 't_cell', 'nk')


def _blank_memories():
    return {t: {"deaths": 0, "kills": 0} for t in MEMORY_TYPES}


def _normalize(data):
    """任意来源 dict -> 完整字段默认值兜底（兼容 v4 json 与库中旧/新数据）。"""
    if not isinstance(data, dict):
        data = {}
    memories = _blank_memories()
    for t, v in (data.get("memories") or {}).items():
        if t in memories and isinstance(v, dict):
            memories[t] = {"deaths": int(v.get("deaths", 0)),
                           "kills": int(v.get("kills", 0))}
    fs = data.get("fixed_slot")
    return {
        "offering": int(data.get("offering", 0)),
        "next_buffs": list(data.get("next_buffs", [])),
        "memories": memories,
        "learned_memories": list(data.get("learned_memories", [])),
        "boss_beaten_count": int(data.get("boss_beaten_count", 0)),
        "pending_physical": list(data.get("pending_physical", [])),
        "fixed_slot": dict(fs) if isinstance(fs, dict) else None,
        "perfect_ne_count": int(data.get("perfect_ne_count", 0)),
        "te2_seen": bool(data.get("te2_seen", False)),
        "achievements": list(data.get("achievements", [])),
    }


def _migrate_json_once(db_path):
    """v4 旧档迁移：库无档 且 data/meta.json 存在 -> 导入并落库 + 写 .migrated 标记。

    返回迁移得到的 dict（无档则 None）。该函数只由 load_meta 调用。
    """
    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            legacy = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if os.path.exists(MIGRATED_FLAG):
        return None            # 已迁移过（标记在）；库才是真相
    cur = load_state_meta(db_path)
    if cur is not None:
        return None            # 库已初始化，不需要迁移
    meta = _normalize(legacy)
    save_state_meta(meta, db_path)
    try:
        with open(MIGRATED_FLAG, "w", encoding="utf-8") as f:
            f.write("migrated to sqlite\n")
    except OSError:
        pass
    return meta


def load_meta(path=None):
    """读取完整档案（库优先；旧 json 首启迁移；全无则默认字段）。"""
    db = resolve_db_path(path)
    init_db(db)                       # 幂等建表（未存在则建）
    migrated = _migrate_json_once(db)
    if migrated is not None:
        return migrated
    cur = load_state_meta(db)
    if cur is None:
        return _normalize({})
    return _normalize(cur)


def save_meta(offering=None, next_buffs=None, path=None, *,
              perfect_ne_count=None, memories=None, learned_memories=None,
              boss_beaten_count=None, pending_physical=None, fixed_slot=None,
              te2_seen=None, achievements=None):
    """合并且写回本地库。不传的字段保持当前值（向后兼容）。"""
    cur = load_meta(path)
    if offering is None:
        offering = cur["offering"]
    if next_buffs is None:
        next_buffs = cur["next_buffs"]
    if perfect_ne_count is None:
        perfect_ne_count = cur["perfect_ne_count"]
    if memories is None:
        memories = cur["memories"]
    if learned_memories is None:
        learned_memories = cur["learned_memories"]
    if boss_beaten_count is None:
        boss_beaten_count = cur["boss_beaten_count"]
    if pending_physical is None:
        pending_physical = cur["pending_physical"]
    if fixed_slot is None:
        fixed_slot = cur["fixed_slot"]
    if te2_seen is None:
        te2_seen = cur["te2_seen"]
    if achievements is None:
        achievements = cur["achievements"]
    save_state_meta(_normalize({
        "offering": offering,
        "next_buffs": next_buffs,
        "memories": memories,
        "learned_memories": learned_memories,
        "boss_beaten_count": boss_beaten_count,
        "pending_physical": pending_physical,
        "fixed_slot": fixed_slot,
        "perfect_ne_count": perfect_ne_count,
        "te2_seen": te2_seen,
        "achievements": achievements,
    }), resolve_db_path(path))
