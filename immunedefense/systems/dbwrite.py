"""本地库写入辅助（v5）：战绩 / 祭点流水 / 成就。

设计：**异常兜底**——库损坏/不可写时仅打日志，绝不炸游戏（离线可玩性 > 统计完整性）。
所有函数返回 None/False 表示写入失败，调用方无需感知。
"""
from systems import dblocal


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:            # sqlite3.Error / OSError / json 等
        print(f"[db] write skipped: {fn.__name__} -> {e}")
        return None


def record_run(run: dict):
    """一局战绩（runs 表）。run: score/layers/wbc_deaths/residual/ending/key_left_found/archive_left_read。"""
    return _safe(dblocal.insert_run, run)


def record_offering(delta: int, reason: str, offering_after: int):
    """祭点流水（delta 正=获取 负=消费）。"""
    return _safe(dblocal.insert_offering, delta, reason, offering_after)


def unlock_achievement(aid: str) -> bool:
    """成就入库（幂等）。返回是否本次新解锁；库异常返回 False。"""
    return bool(_safe(dblocal.unlock_achievement, aid))


def achievement_unlocked(aid: str) -> bool:
    """成就是否已解锁（库异常按未解锁处理）。"""
    return bool(_safe(dblocal.achievement_unlocked, aid))
