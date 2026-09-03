"""免疫防线 · 档案管理面板（v5，只读本地页面）。

同进程线程内运行（main.py 启动），浏览器 http://127.0.0.1:8765；
数据只读（用户数据目录 SQLite），无登录——仅本机回环访问，安全定位为「游戏配套数据终端」。
"""
import os
import threading

from flask import Flask, render_template

from systems import dblocal
from systems.achievements import load_achievements

DEFAULT_PORT = 8765
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def create_app(db_path=None):
    app = Flask(__name__, template_folder=_TEMPLATE_DIR, static_folder=_STATIC_DIR)
    app.config["JSON_AS_ASCII"] = False
    db_path_ref = {"path": db_path}      # 工厂捕获：测试可注入独立库

    @app.get("/")
    def dashboard():
        s = dblocal.stats(db_path_ref["path"])
        defs = load_achievements()
        unlocked = set(dblocal.unlocked_aids(db_path_ref["path"]))
        for a in defs:
            a["unlocked"] = a["aid"] in unlocked
        return render_template("dashboard.html", stats=s, defs=defs)

    @app.get("/runs")
    def runs():
        return render_template("runs.html",
                               rows=dblocal.runs_rows(100, db_path_ref["path"]))

    @app.get("/achievements")
    def achievements():
        defs = load_achievements()
        unlocked = set(dblocal.unlocked_aids(db_path_ref["path"]))
        for a in defs:
            a["unlocked"] = a["aid"] in unlocked
        return render_template("achievements.html", defs=defs)

    @app.get("/offering")
    def offering():
        return render_template("offering.html",
                               rows=dblocal.offering_log_rows(200, db_path_ref["path"]))

    @app.get("/healthz")
    def healthz():
        return {"ok": True}
    return app


def serve_panel(port=None):
    """daemon 线程入口（游戏启动调用）；失败仅打日志（由调用方 catch）。"""
    port = port or int(os.environ.get("V5_PANEL_PORT", DEFAULT_PORT))
    app = create_app()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


def start_panel_thread(port=None):
    """启动面板线程；返回 (thread, ok)。端口被占等多重失败不抛给游戏主流程。"""
    try:
        t = threading.Thread(target=serve_panel, kwargs={"port": port}, daemon=True)
        t.start()
        return t, True
    except Exception as e:
        print(f"[panel] start failed: {e}")
        return None, False
