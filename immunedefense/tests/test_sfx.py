"""程序化音效引擎测试：每个 Patch 可渲染、非静音、可复现、wav 写出合法、
音频总线音效名与音效表一致（防「名字存在却失声」回归）。"""
import os

from core import sfx


def test_all_names_render_nonempty():
    """全部音效可渲染，且峰值强度足够（非近零/非空白）。"""
    for name in sfx.names():
        buf = sfx.render(name, rate=22050)
        assert len(buf) > 200, f"{name}: 样本数不足 {len(buf)}"
        peak = max(abs(min(buf)), abs(max(buf)))
        assert peak > 2000, f"{name}: 峰值过低 {peak}（疑似静音）"


def test_render_deterministic():
    """噪声种子固定 → 同一音效两次渲染逐样本一致。"""
    for name in ('heartbeat', 'alarm', 'purge', 'door_open'):
        assert sfx.render(name, 22050) == sfx.render(name, 22050)


def test_unknown_name_renders_empty():
    assert len(sfx.render('not_a_sound')) == 0


def test_render_all_writes_wavs(tmp_path):
    files = sfx.render_all(str(tmp_path), rate=22050)
    assert len(files) == len(sfx.names())
    for f in files:
        assert os.path.exists(f)
        assert os.path.getsize(f) > 100
        with open(f, 'rb') as fh:
            head = fh.read(12)
        assert head[:4] == b'RIFF' and head[8:12] == b'WAVE'


def test_audio_names_cover_sfx_table():
    """音频总线注册名 == sfx 音效表名（无静默名字、无孤儿补丁）。"""
    from core.audio import SOUND_NAMES
    assert set(SOUND_NAMES) == set(sfx.names())


def test_all_patches_have_valid_voices():
    """每个 Patch 至少一个 Voice，且字段合法（dur/gain 为正）。"""
    for name, voices in sfx.SFX.items():
        assert voices, f"{name}: 空 Patch"
        for v in voices:
            assert v.get('dur', 0) > 0, f"{name}: dur 非法"
            assert v.get('gain', 0) > 0, f"{name}: gain 非法"
            assert v.get('wave', 'sine') in ('sine', 'square', 'saw', 'tri',
                                             'noise'), f"{name}: wave 非法"
