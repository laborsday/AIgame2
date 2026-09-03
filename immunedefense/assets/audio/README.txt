音频素材目录（wav / ogg 均可）
================================

当前状态（2026-09-01 音效系统升级）
----------------------------------
- 23 个程序化音效已由 gen_sfx.py 批量导出为 wav（唯一音色定义源：core/sfx.py），
  运行时优先加载本目录文件；文件缺失时 core/audio.py 用同一份 Patch 定义
  实时合成回退——音色一致，永不静默。
- 配音仍是外部文件方案：assets/audio/voice/{key}.wav|.ogg，独立通道互斥播放。

音效名（assets/audio/{name}.wav|.ogg；缺文件即回退合成）：
  heartbeat hit hurt burst purge synergy poison alarm
  rage1 rage2 rage3 rage4 phase
  pickup heal chest chime shop_buy levelup victory
  click door_open door_close

重新生成：cd immunedefense && python gen_sfx.py    （全部重导出 44100Hz wav）
          python gen_sfx.py --list                 （查看音效名）
替换外部素材：同名 wav/ogg 直接覆盖即可（外部文件优先加载）。

配音键名（放入 voice/ 子目录）：
  opening ending_win ending_lose

素材来源建议（替换/补充用）：
- 免费音效：Freesound.org（CC0）搜索对应关键词后导出 wav/ogg。
- 配音：AI 语音合成（沉稳带疲惫的青年男声，大学生意识体的声音），文案见
  visual_specs/sprite_sheet_prompts.md §4.2。
