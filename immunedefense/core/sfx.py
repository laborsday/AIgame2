"""程序化音效引擎（纯计算，零 pygame 依赖）。

一套极小的「音效 DSL」：每个音效 = 若干 Voice（振荡器 + 包络 + 低通 + 延迟）叠加合成
16-bit 单声道样本。核心音频总线（core/audio.py）缺外部文件时用它实时合成回退，
gen_sfx.py 用同一份定义批量导出 wav 资产——一套定义，两条出路。

Voice 字段：
- wave: 'sine'|'square'|'saw'|'tri'|'noise'
- f0   : 起始频率（Hz）；f1 可选：按指数滑音到 f1
- dur  : 时长（秒）；at : 起始延迟（秒）
- gain : 音量 0..1；att : 起音（秒）；dec : 衰减速率（指数，1/秒）
- sus  : 衰减后保持电平 0..1（默认 0）；rel : 尾音线性收尾（秒，防爆音）
- lp   : 一阶低通截止频率（Hz），0 = 不滤波（方波/锯齿/噪声建议带上）
"""
import math
import random
from array import array

RATE = 44100          # 资产渲染采样率（wav 导出）
_MIXER_RATE = 22050   # 运行时合成回退采样率（与 pygame.mixer 对齐，见 core/audio.py）

_WAVES = {
    'sine': lambda ph: math.sin(2 * math.pi * (ph % 1.0)),
    'square': lambda ph: 1.0 if (ph % 1.0) < 0.5 else -1.0,
    'saw': lambda ph: 2.0 * (ph % 1.0) - 1.0,
    'tri': lambda ph: 2.0 * abs(2.0 * (ph % 1.0) - 1.0) - 1.0,
}


def _env(t, att, dec, sus, dur, rel):
    """分段包络：线性起音 → 指数衰减至 sus →（可选）rel 线性收尾。"""
    if rel > 0 and t > dur - rel:
        return max(0.0, (dur - t) / rel)
    a = min(1.0, t / att) if att > 0 else 1.0
    e = sus + (1.0 - sus) * math.exp(-dec * max(0.0, t - att))
    return a * e


def _render_voice(voice, rate, rng):
    """按 Voice 定义渲染一段 float 样本列表（含延迟前导零）。"""
    dur = float(voice.get('dur', 0.2))
    at = float(voice.get('at', 0.0))
    n = int(rate * (at + dur)) + 2
    out = [0.0] * n
    wave = voice.get('wave', 'sine')
    f0 = float(voice.get('f0', 440.0))
    f1 = float(voice.get('f1', f0))
    gain = float(voice.get('gain', 0.5))
    att = float(voice.get('att', 0.002))
    dec = float(voice.get('dec', 30.0))
    sus = float(voice.get('sus', 0.0))
    rel = float(voice.get('rel', 0.004))
    lp = float(voice.get('lp', 0.0))
    start = int(rate * at)
    n_dur = int(rate * dur)
    ph = 0.0
    lp_y = 0.0
    lp_a = 1.0 - math.exp(-2.0 * math.pi * lp / rate) if lp > 0 else 0.0
    for i in range(n_dur):
        t = i / rate
        fade = max(0.0, min(1.0, i / max(1.0, int(rate * 0.001))))  # 1ms 防爆音
        # 频率：f0 → f1 指数滑音
        f = f0 * (f1 / f0) ** (t / dur) if f1 >= 0 else f0
        ph += f / rate
        if wave == 'noise':
            x = rng.uniform(-1.0, 1.0)
        else:
            x = _WAVES[wave](ph)
        if lp_a:
            lp_y += lp_a * (x - lp_y)
            x = lp_y
        out[start + i] = gain * fade * x * _env(t, att, dec, sus, dur, rel)
    return out


def _render_patch(voices, rate, seed=0):
    """叠加全部 Voice；削峰保护（仅峰值 >0.96 时整体缩放到 0.96，不抹平音效相对响度）。"""
    rng = random.Random(seed)
    total = 0
    parts = []
    for v in voices:
        buf = _render_voice(v, rate, rng)
        parts.append(buf)
        total = max(total, len(buf))
    mix = [0.0] * total
    for buf in parts:
        for i, x in enumerate(buf):
            mix[i] += x
    peak = max((abs(x) for x in mix), default=0.0)
    if peak > 0.96:
        scale = 0.96 / peak
        mix = [x * scale for x in mix]
    return mix


def render(name, rate=RATE):
    """渲染命名音效 → int16 单声道 array('h')；未知音效名返回空。"""
    voices = SFX.get(name)
    if not voices:
        return array('h')
    mix = _render_patch(voices, rate)
    return array('h', (int(max(-32767, min(32767, x * 32767))) for x in mix))


def names():
    """全部可用音效名（与 core/audio.SOUND_NAMES 一致）。"""
    return list(SFX.keys())


def render_all(out_dir, rate=RATE):
    """把全部音效写成 {name}.wav 到 out_dir，返回写入的文件路径列表。"""
    import os
    import wave
    written = []
    for name in names():
        path = os.path.join(out_dir, name + '.wav')
        samples = render(name, rate)
        if not samples:
            continue
        with wave.open(path, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(samples.tobytes())
        written.append(path)
    return written


# ============================================================
# 音效表：① 手术室/监护仪（心跳/警报）② 战斗（命中/爆发/狂暴档位/毒/阶段）
# ③ 流程（门/拾取/宝箱/升级/商店/胜利）④ UI（点击/回血）
# 所有音效确定性可复现（噪声随机种子固定）。
# ============================================================
SFX = {
    # ---------- UI ----------
    'click': [                                   # 按钮/开关：短促软嗒
        dict(wave='sine', f0=1600, f1=900, dur=0.045, gain=0.20, att=0.001,
             dec=70, lp=0),
        dict(wave='noise', dur=0.022, gain=0.07, att=0.001, dec=120, lp=2600),
    ],
    # ---------- 拾取 / 回血 / 获得 ----------
    'pickup': [                                  # 拾取：清脆双泛音「叮」
        dict(wave='sine', f0=1150, f1=1150, dur=0.10, gain=0.28, att=0.002, dec=24),
        dict(wave='sine', f0=1725, f1=1725, dur=0.07, gain=0.14, att=0.002,
             dec=34, at=0.005),
    ],
    'heal': [                                    # 回血：温暖上行
        dict(wave='sine', f0=620, f1=880, dur=0.22, gain=0.20, att=0.006, dec=10),
        dict(wave='sine', f0=1240, f1=1760, dur=0.14, gain=0.09, att=0.004,
             dec=16, at=0.02),
    ],
    'chest': [                                   # 开宝箱：木盖 + 金币双响
        dict(wave='saw', f0=170, f1=250, dur=0.09, gain=0.13, att=0.002,
             dec=26, lp=1600),
        dict(wave='noise', dur=0.07, gain=0.13, att=0.001, dec=40, lp=1300),
        dict(wave='sine', f0=1568, dur=0.15, gain=0.18, att=0.001, dec=18, at=0.11),
        dict(wave='sine', f0=2093, dur=0.13, gain=0.11, att=0.001, dec=24, at=0.15),
    ],
    'chime': [                                   # 获得横幅/钥匙：三音钟铃
        dict(wave='sine', f0=660, dur=0.55, gain=0.24, att=0.002, dec=8),
        dict(wave='sine', f0=990, dur=0.50, gain=0.13, att=0.002, dec=9, at=0.008),
        dict(wave='sine', f0=1320, dur=0.40, gain=0.09, att=0.002, dec=12, at=0.016),
    ],
    'shop_buy': [                                # 祭坛交易：祭祀铃 + 后随泛音
        dict(wave='sine', f0=880, dur=0.50, gain=0.26, att=0.002, dec=8),
        dict(wave='sine', f0=1174, dur=0.48, gain=0.17, att=0.002, dec=9, at=0.14),
        dict(wave='sine', f0=1760, dur=0.34, gain=0.08, att=0.002, dec=14, at=0.14),
    ],
    'levelup': [                                 # 升级：上扬琶音 C5-E5-G5-C6
        dict(wave='sine', f0=523, dur=0.10, gain=0.20, att=0.002, dec=22),
        dict(wave='sine', f0=659, dur=0.10, gain=0.18, att=0.002, dec=24, at=0.09),
        dict(wave='sine', f0=784, dur=0.10, gain=0.16, att=0.002, dec=26, at=0.18),
        dict(wave='sine', f0=1046, dur=0.42, gain=0.16, att=0.002, dec=10, at=0.27),
        dict(wave='sine', f0=2093, dur=0.26, gain=0.05, att=0.002, dec=20, at=0.27),
    ],
    'victory': [                                 # 通关：柔和主和弦铺开
        dict(wave='sine', f0=261.6, dur=1.15, gain=0.15, att=0.06, dec=3.4),
        dict(wave='sine', f0=392.0, dur=1.15, gain=0.11, att=0.06, dec=3.4),
        dict(wave='sine', f0=523.2, dur=1.25, gain=0.13, att=0.05, dec=3.0),
        dict(wave='sine', f0=659.2, dur=1.10, gain=0.09, att=0.06, dec=3.4),
        dict(wave='sine', f0=1046.5, dur=0.72, gain=0.07, att=0.03, dec=5, at=0.06),
        dict(wave='sine', f0=1318.5, dur=0.5, gain=0.04, att=0.03, dec=8, at=0.16),
    ],
    # ---------- 手术室 / 监护 ----------
    'heartbeat': [                               # 心跳：低频「砰-咚」
        dict(wave='sine', f0=52, f1=44, dur=0.16, gain=0.55, att=0.004, dec=26),
        dict(wave='sine', f0=38, f1=32, dur=0.12, gain=0.34, att=0.004, dec=30,
             at=0.10),
    ],
    'alarm': [                                   # 监护仪警报：双短哔
        dict(wave='square', f0=660, dur=0.13, gain=0.16, att=0.002, dec=12,
             lp=2400),
        dict(wave='square', f0=660, dur=0.13, gain=0.16, att=0.002, dec=12,
             lp=2400, at=0.24),
    ],
    # ---------- 战斗 ----------
    'hit': [                                     # 攻击命中：短促打击
        dict(wave='square', f0=160, f1=95, dur=0.07, gain=0.32, att=0.001, dec=55,
             lp=2200),
        dict(wave='noise', dur=0.045, gain=0.20, att=0.001, dec=70, lp=1800),
    ],
    'hurt': [                                    # 玩家受伤：音调下滑的闷响
        dict(wave='saw', f0=260, f1=110, dur=0.22, gain=0.24, att=0.003, dec=16,
             lp=1400),
        dict(wave='noise', dur=0.06, gain=0.11, att=0.001, dec=42, lp=1100,
             at=0.01),
    ],
    'burst': [                                   # NK 重爆/震爆：下沉低频 + 爆裂
        dict(wave='noise', dur=0.18, gain=0.28, att=0.001, dec=18, lp=2600),
        dict(wave='sine', f0=75, f1=42, dur=0.28, gain=0.38, att=0.002, dec=11),
        dict(wave='saw', f0=140, f1=60, dur=0.16, gain=0.15, att=0.001, dec=22,
             lp=1600),
    ],
    'purge': [                                   # NK 标定爆发：能量上扬 + 爆裂
        dict(wave='saw', f0=260, f1=720, dur=0.16, gain=0.20, att=0.002, dec=24,
             lp=5200),
        dict(wave='noise', dur=0.14, gain=0.18, att=0.001, dec=28, lp=3200),
        dict(wave='sine', f0=90, f1=55, dur=0.22, gain=0.24, att=0.002, dec=14),
    ],
    'synergy': [                                 # 免疫风暴命中标记：快速双音闪
        dict(wave='sine', f0=1318, dur=0.11, gain=0.20, att=0.001, dec=28),
        dict(wave='sine', f0=1975, dur=0.13, gain=0.13, att=0.001, dec=24, at=0.02),
    ],
    'poison': [                                  # 酸液毒区：滋滋 + 下潜鸣音
        dict(wave='noise', dur=0.10, gain=0.19, att=0.001, dec=42, lp=1500),
        dict(wave='sine', f0=1500, f1=350, dur=0.13, gain=0.13, att=0.001,
             dec=30, lp=2800),
    ],
    'rage1': [                                   # 狂暴档位 1：低吼、渐重
        dict(wave='saw', f0=120, f1=100, dur=0.20, gain=0.20, att=0.003, dec=18,
             lp=900),
    ],
    'rage2': [
        dict(wave='saw', f0=160, f1=130, dur=0.22, gain=0.24, att=0.003, dec=16,
             lp=1100),
        dict(wave='noise', dur=0.05, gain=0.09, att=0.001, dec=46, lp=1000),
    ],
    'rage3': [
        dict(wave='square', f0=210, f1=170, dur=0.24, gain=0.26, att=0.003,
             dec=14, lp=1300),
        dict(wave='noise', dur=0.07, gain=0.11, att=0.001, dec=40, lp=1400),
    ],
    'rage4': [
        dict(wave='square', f0=280, f1=230, dur=0.26, gain=0.30, att=0.003,
             dec=12, lp=1500),
        dict(wave='noise', dur=0.09, gain=0.13, att=0.001, dec=36, lp=1800),
        dict(wave='sine', f0=65, f1=90, dur=0.24, gain=0.16, att=0.003, dec=13),
    ],
    'phase': [                                   # BOSS 阶段切换：深钟下坠
        dict(wave='sine', f0=320, f1=95, dur=0.55, gain=0.28, att=0.002, dec=6),
        dict(wave='sine', f0=480, f1=190, dur=0.48, gain=0.09, att=0.002, dec=8),
        dict(wave='noise', dur=0.08, gain=0.08, att=0.001, dec=32, lp=900),
    ],
    # ---------- 门 ----------
    'door_open': [                               # 门开：封膜撕裂 + 上滑
        dict(wave='noise', dur=0.36, gain=0.17, att=0.004, dec=7, lp=1000),
        dict(wave='sine', f0=90, f1=170, dur=0.30, gain=0.13, att=0.004, dec=9),
        dict(wave='noise', dur=0.16, gain=0.07, att=0.003, dec=22, lp=2600,
             at=0.05),
    ],
    'door_close': [                              # 门关：低沉闷响
        dict(wave='sine', f0=85, f1=48, dur=0.22, gain=0.28, att=0.002, dec=14),
        dict(wave='noise', dur=0.05, gain=0.15, att=0.001, dec=52, lp=700),
    ],
}
