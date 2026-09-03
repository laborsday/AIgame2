"""v5：本地库数据层测试（dblocal.systems，注入隔离库路径）。"""
import os

import pytest

from systems import dblocal
from systems import meta as meta_mod


def test_db_path_resolution(tmp_path):
    """json 惯例路径 → 同名 .db（避免把 JSON 当 SQLite）。"""
    p = os.path.join(str(tmp_path), "a.json")
    assert dblocal.resolve_db_path(p) == os.path.join(str(tmp_path), "a.db")
    p2 = os.path.join(str(tmp_path), "b.db")
    assert dblocal.resolve_db_path(p2) == p2


def test_state_meta_roundtrip(tmp_path):
    dbp = dblocal.resolve_db_path(os.path.join(str(tmp_path), "m.json"))
    dblocal.init_db(dbp)
    meta = {"offering": 42, "achievements": ["reliquary"]}
    dblocal.save_state_meta(meta, dbp)
    assert dblocal.load_state_meta(dbp) == meta
    # upsert 覆盖
    dblocal.save_state_meta({"offering": 7}, dbp)
    assert dblocal.load_state_meta(dbp) == {"offering": 7}


def test_runs_offering_achievements(tmp_path):
    dbp = dblocal.resolve_db_path(os.path.join(str(tmp_path), "x.json"))
    dblocal.init_db(dbp)
    rid = dblocal.insert_run({"score": 100, "layers": 2, "wbc_deaths": 5,
                              "residual": 0.42, "ending": "NE",
                              "key_left_found": True, "archive_left_read": False}, dbp)
    assert rid == 1
    assert len(dblocal.runs_rows(10, dbp)) == 1
    assert dblocal.insert_offering(40, "memory_frag", 40, dbp)
    assert dblocal.insert_offering(-200, "buy_key", -160, dbp)
    rows = dblocal.offering_log_rows(10, dbp)
    assert rows[0]["delta"] == -200 and rows[0]["reason"] == "buy_key"
    assert dblocal.unlock_achievement("reliquary", dbp) is True
    assert dblocal.unlock_achievement("reliquary", dbp) is False   # 主键幂等
    assert dblocal.achievement_unlocked("reliquary", dbp)
    assert "reliquary" in dblocal.unlocked_aids(dbp)


def test_stats(tmp_path):
    dbp = dblocal.resolve_db_path(os.path.join(str(tmp_path), "s.json"))
    dblocal.init_db(dbp)
    dblocal.insert_run({"score": 1, "layers": 3, "wbc_deaths": 2, "residual": 0.1,
                        "ending": "TE2", "key_left_found": False,
                        "archive_left_read": True}, dbp)
    dblocal.insert_run({"score": 2, "layers": 1, "wbc_deaths": 9, "residual": None,
                        "ending": "died", "key_left_found": False,
                        "archive_left_read": False}, dbp)
    dblocal.insert_offering(30, "settle", 30, dbp)
    s = dblocal.stats(dbp)
    assert s["total_runs"] == 2 and s["win_runs"] == 1
    assert s["ending_dist"].get("died") == 1
    assert s["offering_total"] == 30 and s["offering_now"] == 30


def test_db_ready(tmp_path):
    dbp = dblocal.resolve_db_path(os.path.join(str(tmp_path), "r.json"))
    assert not dblocal.db_ready(dbp)      # 未建库
    dblocal.init_db(dbp)
    assert dblocal.db_ready(dbp)


def test_meta_migrate_legacy_json(tmp_path, monkeypatch):
    """v4 旧 meta.json 首启迁移：导入库 + .migrated 标记 + 二次 load 走库。"""
    legacy = os.path.join(str(tmp_path), "meta.json")
    flag = legacy + ".migrated"
    monkeypatch.setattr(meta_mod, "META_PATH", legacy)
    monkeypatch.setattr(meta_mod, "MIGRATED_FLAG", flag)
    with open(legacy, "w", encoding="utf-8") as f:
        f.write('{"offering": 666, "next_buffs": ["atk"], "perfect_ne_count": 2}')
    dbp = os.path.join(str(tmp_path), "t.json")
    m = meta_mod.load_meta(dbp)
    assert m["offering"] == 666 and m["next_buffs"] == ["atk"]
    assert m["perfect_ne_count"] == 2
    assert os.path.exists(flag)
    # 二次读取走库（且值为完整默认补齐后的形态）
    m2 = meta_mod.load_meta(dbp)
    assert m2["offering"] == 666
    assert m2["learned_memories"] == []
    assert m2["memories"]["neutrophil"] == {"deaths": 0, "kills": 0}
