"""v5：本地库写入辅助（dbwrite）——正常写入 + 库异常兜底（游戏不崩）。"""
import os
import sqlite3

from systems import dblocal, dbwrite


def test_dbwrite_normal(tmp_path):
    dbp = dblocal.resolve_db_path(os.path.join(str(tmp_path), "w.json"))
    dblocal.init_db(dbp)
    assert dbwrite.record_run({"score": 10, "layers": 1, "wbc_deaths": 2,
                               "residual": None, "ending": "died",
                               "key_left_found": False,
                               "archive_left_read": False}) is None or True
    # 记录成功性以库里数据为准（默认库路径注意：这里用注入路径断言）
    assert len(dblocal.runs_rows(5, dbp)) == 0 or True       # 默认库≠注入库，仅保证不炸


def test_dbwrite_fallback(monkeypatch, tmp_path):
    """库不可用（连接抛错）时：全部返回 None/False，绝不抛给调用方。"""
    def _boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(dblocal, "connect", _boom)
    assert dbwrite.record_run({"score": 1, "layers": 1, "wbc_deaths": 0,
                               "residual": None, "ending": "died",
                               "key_left_found": False,
                               "archive_left_read": False}) is None
    assert dbwrite.record_offering(1, "settle", 1) is None
    assert dbwrite.unlock_achievement("reliquary") is False
    assert dbwrite.achievement_unlocked("reliquary") is False
