"""程序化音效批量导出：把 core/sfx.py 的 24 个音效 Patch 渲染成 wav 资产。

- 输出：assets/audio/{name}.wav（44100Hz 16-bit 单声道），与打包 spec 的 assets
  目录收集规则一致，EXE 自动带上。
- 运行时兜底不受影响：core/audio.py 缺文件时用同一份 Patch 定义实时合成，音色一致。
用法：python gen_sfx.py            # 全部生成
      python gen_sfx.py --list     # 只列出音效名
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import sfx  # noqa: E402


def main():
    if '--list' in sys.argv:
        for i, name in enumerate(sfx.names(), 1):
            print(f"{i:2d}. {name}")
        return
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'assets', 'audio')
    os.makedirs(out_dir, exist_ok=True)
    files = sfx.render_all(out_dir)
    print(f"生成 {len(files)} 个音效 → {out_dir}")


if __name__ == '__main__':
    main()
