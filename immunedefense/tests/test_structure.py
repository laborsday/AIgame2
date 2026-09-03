"""结构守护测试（A4 分层硬约束编码进套件）：防止「systems/ 含渲染」复活。

守则来源（修正清单 A4）：
- systems/ 下文件禁止 import pygame，也禁止直接 screen.blit（渲染一律住 ui/）；
- 这两个条款缺一不可：导入封装好的 gfx 也可能持有渲染操作（如曾经的
  systems/floater.py 只 import gfx 却调 screen.blit，被 import 条款漏检）。
"""
import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _py_files(subdir):
    path = os.path.join(PROJECT_ROOT, subdir)
    return [os.path.join(path, f) for f in sorted(os.listdir(path))
            if f.endswith('.py') and f != '__init__.py']


@pytest.mark.parametrize('p', _py_files('systems'))
def test_systems_no_pygame_no_blit(p):
    """systems/ 纯逻辑硬约束：源码中不得出现 pygame 导入或 screen.blit。"""
    src = open(p, encoding='utf-8').read()
    assert 'import pygame' not in src, \
        f"{os.path.basename(p)}: systems/ 禁 import pygame（渲染住 ui/）"
    assert 'screen.blit' not in src, \
        f"{os.path.basename(p)}: systems/ 禁直接 blit（渲染住 ui/）"
