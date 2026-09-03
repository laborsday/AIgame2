"""免疫防线 v5：本地 SQLite 数据层（单机档案库）。

数据落点：%APPDATA%\\Immunedefense\\immunedefense.db（写权限安全；打包分发不含任何玩家数据）。
表：app_state（单机单档 meta 快照）/ runs（战绩）/ achievements（成就）/ offering_log（祭点流水）。

只读查询供档案管理面板（server/）与游戏端 systems/dbwrite.py 共用：
- 本模块保持纯标准库（sqlite3），供两端引用，无 pygame/游戏依赖。
- 单一数据源：游戏本体与同进程 Flask 面板线程均 import 本模块。
"""
import os
import sqlite3

DATA_DIR_ENV = "V5_DATA_DIR"
DB_NAME = "immunedefense.db"

# 受限环境（打包只读目录 / 沙箱）回退位：游戏目录下 data/userdata（.gitignore）
_FALLBACK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "data", "userdata")


def _try_makedirs(p):
    try:
        os.makedirs(p, exist_ok=True)
        return True
    except OSError:
        return False


def data_dir():
    """用户数据目录（三级回退，全部失败也没关系——由调用方容错）：
    1) 环境变量 V5_DATA_DIR（测试/部署注入）
    2) %LOCALAPPDATA%\\Immunedefense（Windows 标准本机数据位）
    3) 游戏目录 data/userdata（开发/受限环境）
    """
    env = os.environ.get(DATA_DIR_ENV)
    if env and _try_makedirs(env):
        return env
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") \
        or os.path.expanduser("~")
    p = os.path.join(base, "Immunedefense")
    if _try_makedirs(p):
        return p
    if _try_makedirs(_FALLBACK_DIR):
        return _FALLBACK_DIR
    return _FALLBACK_DIR      # 最后仍返回（写失败由上层 sqlite 报错兜底，不静默换库）


def default_db_path():
    return os.path.join(data_dir(), DB_NAME)


def resolve_db_path(path=None):
    """统一库路径解析。

    - path 为 None：默认库（环境变量 V5_DB_PATH 可覆盖；仍允许 V5_DATA_DIR 先解析）
    - path 给定：用于测试注入。旧惯例传 *.json 路径 -> 同目录同名 .db（避免把 JSON 当 SQLite）
    - 返回绝对路径字符串；目录不存在时创建。
    """
    if path is None:
        p = os.environ.get("V5_DB_PATH")
        if p:
            return _ensure_dir(p)
        return default_db_path()
    if path.lower().endswith(".json"):
        path = os.path.splitext(path)[0] + ".db"
    return _ensure_dir(path)


def _ensure_dir(p):
    d = os.path.dirname(os.path.abspath(p))
    os.makedirs(d, exist_ok=True)
    return os.path.abspath(p)


# ---------- 建表（幂等） ----------

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=3000;

CREATE TABLE IF NOT EXISTS app_state (
  id         INTEGER PRIMARY KEY CHECK (id = 1),
  meta       TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  score      INTEGER NOT NULL,
  layers     INTEGER NOT NULL,
  wbc_deaths INTEGER NOT NULL,
  residual   REAL,
  ending     TEXT NOT NULL,
  key_left_found     INTEGER NOT NULL DEFAULT 0,
  archive_left_read  INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS achievements (
  aid         TEXT PRIMARY KEY,
  unlocked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offering_log (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  delta          INTEGER NOT NULL,
  reason         TEXT NOT NULL,
  offering_after INTEGER NOT NULL,
  created_at     TEXT NOT NULL
);
"""


def init_db(path=None):
    """建库建表（幂等）；返回库路径。"""
    p = resolve_db_path(path)
    with sqlite3.connect(p) as conn:
        conn.executescript(DDL)
    return p


def connect(path=None):
    """业务连接：WAL + busy_timeout + Row factory。由调用方负责 close（with 语句）。"""
    conn = sqlite3.connect(resolve_db_path(path), timeout=3.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def db_ready(path=None) -> bool:
    """面板/游戏启动自检：库可打开且表齐全。"""
    try:
        with connect(path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('app_state','runs','achievements','offering_log')").fetchall()
            return len(rows) == 4
    except sqlite3.Error:
        return False


# ---------- 单机单档 meta 快照 ----------

def load_state_meta(path=None):
    """读 app_state.meta（JSON 字符串 -> dict）；无档返回 None。"""
    with connect(path) as conn:
        row = conn.execute("SELECT meta FROM app_state WHERE id = 1").fetchone()
    if row is None:
        return None
    import json
    return json.loads(row["meta"])


def save_state_meta(meta: dict, path=None, now=None):
    """写 app_state.meta（upsert id=1）。"""
    import json
    if now is None:
        from datetime import datetime
        now = datetime.now().isoformat()
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO app_state (id, meta, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET meta = excluded.meta, "
            "updated_at = excluded.updated_at",
            (json.dumps(meta, ensure_ascii=False), now))


# ---------- runs / achievements / offering_log（供 systems/dbwrite.py 复用） ----------

def insert_run(run: dict, path=None, now=None):
    """写入一局战绩。字段：score/layers/wbc_deaths/residual/ending/key_left_found/archive_left_read。"""
    if now is None:
        from datetime import datetime
        now = datetime.now().isoformat()
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO runs (score, layers, wbc_deaths, residual, ending, "
            "key_left_found, archive_left_read, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (int(run["score"]), int(run["layers"]), int(run["wbc_deaths"]),
             (float(run["residual"]) if run.get("residual") is not None else None),
             str(run["ending"]),
             1 if run.get("key_left_found") else 0,
             1 if run.get("archive_left_read") else 0,
             now))
        return cur.lastrowid


def unlock_achievement(aid: str, path=None, now=None) -> bool:
    """成就解锁（aid 主键幂等）。返回是否本次新解锁。"""
    if now is None:
        from datetime import datetime
        now = datetime.now().isoformat()
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO achievements (aid, unlocked_at) VALUES (?, ?)",
            (aid, now))
        return cur.rowcount > 0


def achievement_unlocked(aid: str, path=None) -> bool:
    with connect(path) as conn:
        return conn.execute("SELECT 1 FROM achievements WHERE aid = ?", (aid,)).fetchone() is not None


def unlocked_aids(path=None) -> set:
    with connect(path) as conn:
        return {r["aid"] for r in conn.execute("SELECT aid FROM achievements")}


def insert_offering(delta: int, reason: str, offering_after: int, path=None, now=None) -> int:
    """祭点流水。delta 正=获取 负=消费。"""
    if now is None:
        from datetime import datetime
        now = datetime.now().isoformat()
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO offering_log (delta, reason, offering_after, created_at) "
            "VALUES (?,?,?,?)",
            (int(delta), str(reason), int(offering_after), now))
        return cur.lastrowid


def offering_log_rows(limit=200, path=None):
    with connect(path) as conn:
        return conn.execute(
            "SELECT delta, reason, offering_after, created_at FROM offering_log "
            "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()


def runs_rows(limit=100, path=None):
    with connect(path) as conn:
        return conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()


def stats(path=None) -> dict:
    """面板仪表盘聚合（一次查询集）。"""
    with connect(path) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        wins = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE ending IN ('NE','TE','TE2')").fetchone()["n"]
        today = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE date(created_at) = date('now','localtime')"
        ).fetchone()["n"]
        ending_dist = {r["ending"]: r["n"] for r in conn.execute(
            "SELECT ending, COUNT(*) AS n FROM runs GROUP BY ending")}
        offering_total = conn.execute(
            "SELECT COALESCE(SUM(delta),0) AS s FROM offering_log").fetchone()["s"]
        offering_now = conn.execute(
            "SELECT offering_after FROM offering_log ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "total_runs": total,
            "win_runs": wins,
            "today_runs": today,
            "ending_dist": ending_dist,
            "offering_total": offering_total,
            "offering_now": (offering_now["offering_after"] if offering_now else None),
            "achievements": [r["aid"] for r in conn.execute(
                "SELECT aid FROM achievements ORDER BY unlocked_at")],
        }
