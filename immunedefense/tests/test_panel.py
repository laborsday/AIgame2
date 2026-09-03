"""v5：档案管理面板（Flask test_client 只读五页）。"""
import os

from server.app import create_app
from systems import dblocal


def _seed(dbp):
    dblocal.init_db(dbp)
    dblocal.insert_run({"score": 432, "layers": 3, "wbc_deaths": 5,
                        "residual": 0.05, "ending": "NE",
                        "key_left_found": True, "archive_left_read": True}, dbp)
    dblocal.insert_run({"score": 60, "layers": 1, "wbc_deaths": 17,
                        "residual": None, "ending": "died",
                        "key_left_found": False, "archive_left_read": False}, dbp)
    dblocal.insert_offering(30, "settle", 30, dbp)
    dblocal.unlock_achievement("reliquary", dbp)


def test_panel_pages(tmp_path):
    dbp = os.path.join(str(tmp_path), "panel.json")      # 注入独立库
    _seed(dbp)
    app = create_app(db_path=dbp)
    c = app.test_client()
    assert c.get("/healthz").json == {"ok": True}
    r = c.get("/")
    assert r.status_code == 200 and "总对局" in r.get_data(as_text=True)
    assert "2" in r.get_data(as_text=True)
    r = c.get("/runs")
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "NE" in body and "died" in body
    r = c.get("/achievements")
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "战友的徽章" in body and "已解锁" in body
    r = c.get("/offering")
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and "settle" in body and "+30" in body


def test_panel_empty_db(tmp_path):
    """空库页面不崩（模板 else 分支）。"""
    dbp = os.path.join(str(tmp_path), "empty.json")
    dblocal.init_db(dbp)
    app = create_app(db_path=dbp)
    c = app.test_client()
    for p in ("/", "/runs", "/achievements", "/offering"):
        assert c.get(p).status_code == 200
