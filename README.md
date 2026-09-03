# 《免疫防线》 Immunity Defense

2D 俯视角动作肉鸽（Action Roguelite）· Python + Pygame。

一名确诊肝癌的大学生，在手术麻醉的梦境中，以「纳米意识」潜入自己体内，指挥白细胞对抗癌细胞……梦境里的胜负，决定现实里他能否醒来。

- **完整玩法说明**（操作 / 系统 / 打包 / 测试）：见 [`immunedefense/README.md`](immunedefense/README.md)
- 设计文档（策划书 / GDD / v2-v5 升级说明 / 视觉规格）与课程交付物不收录于本仓库。

## 仓库结构

```
immunedefense/  游戏主体：核心玩法 / 实体 / 系统 / UI / 测试，含运行所需的全部资源与数值配置
server/         随游戏启动的本地「档案管理」面板（Flask，只读；可选，不装也能玩）
packaging/      PyInstaller 打包脚本（build.ps1 + immunedefense.spec）
```

## 运行

```bash
pip install pygame-ce        # 或 pygame（本项目用 pygame-ce 2.5.8 验证）
pip install flask            # 可选：本地档案管理面板（默认随游戏启动；不装也能玩）
cd immunedefense
python main.py
```

启动后浏览器打开 **http://127.0.0.1:8765** 查看档案管理面板（或在主菜单左下角点击地址小字）。
数据（存档 / 战绩 / 成就 / 祭点流水）保存在本机 `%LOCALAPPDATA%\Immunedefense\immunedefense.db`，不进版本库。

## 测试

```bash
pip install -r immunedefense/requirements-dev.txt   # pytest、flask（仅首次）
python -m pytest immunedefense/tests -q             # 109 个用例
```

## 打包

```powershell
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# 产物：packaging\免疫防线-v5-win64.zip（onedir，自动校验不含玩家存档/数据库）
```
