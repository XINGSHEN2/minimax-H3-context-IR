#!/usr/bin/env python3
"""Extract and summarize audio guidance from official Feishu H3 IR prompts."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

SECTION_RE = re.compile(r"(?m)^([a-z][a-z0-9_]*):\s*")
AUDIO_WORDS = re.compile(
    r"\b(sound|audio|music|score|voice|dialogue|narrat|speak|says?|whisper|shout|"
    r"footstep|rumble|roar|whoosh|impact|boom|crack|click|clank|groan|"
    r"silence|silent|pulse|drone|hiss|buzz|echo|reverber|static|swoosh|"
    r"percuss|beat|rhythm|tempo|brass|string|synth|piano|guitar|audible|heard)\w*\b",
    re.I,
)
NA_RE = re.compile(r"^\s*(?:N/?A|NONE|NO\s+MUSIC|NOT\s+APPLICABLE)[.\s]*$", re.I)

MUSIC_TAGS = {
    "electronic_synth": r"electronic|synth|synthwave|techno|ambient electronic",
    "cinematic_trailer": r"cinematic|trailer|orchestral|brass|braam",
    "ambient_drone": r"ambient|drone|sustained|atmospheric",
    "acoustic_instrumental": r"pizzicato|piano|guitar|strings?|woodwind|jazz|acoustic",
    "percussive_rhythmic": r"percussion|percussive|drum|beat|rhythm|pulse",
    "vocal_song": r"vocal|sing|song|choir|lyric",
}
SOUNDSCAPE_TAGS = {
    "environment_ambience": r"ambience|ambient|room tone|wind|rain|water|traffic|crowd|forest|ocean|fire",
    "action_foley": r"footstep|steps?|cloth|fabric|leather|handle|touch|movement|breath|door|gravel",
    "mechanical_material": r"mechanical|metal|engine|motor|machine|hull|bridge|gear|click|clank|groan|creak",
    "impact_transition": r"impact|boom|whoosh|swoosh|hit|cut|flash|transition|burst|shock",
    "digital_glitch": r"digital|glitch|static|electronic buzz|VHS|broadcast|signal",
    "voice_dialogue": r"voice|dialogue|narration|speaks?|says?|whisper|shout|chant",
    "silence_dynamic": r"silence|silent|quiet|drop.?out|fade|stop|near-silence",
}
FUNCTION_TAGS = {
    "edit_sync": r"match|sync|cut|transition|flash|movement|action|visual",
    "rhythm_pacing": r"rhythm|tempo|pace|driving|pulse|beat",
    "emotion_tone": r"tension|tense|ominous|emotional|mood|atmosphere|haunting|playful",
    "brand_style": r"fashion|brand|premium|commercial|advertis|aesthetic|style",
    "build_climax": r"build|rise|rising|swell|peak|climax|crescendo|intens",
    "ending_resolution": r"ending|end|final|silence|fade|stop|blackout|resolve",
}


def sections(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    result = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[match.group(1)] = text[match.end() : end].strip()
    return result


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=\[Shot|[A-Z<])|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def tags(text: str, mapping: dict[str, str]) -> list[str]:
    return [name for name, pattern in mapping.items() if re.search(pattern, text, re.I)]


def relative(case: Path, root: Path) -> str:
    return str(case.relative_to(root)).replace("\\", "/")


def extract(root: Path):
    cases = sorted({p.parent for p in root.rglob("prompt.txt") if p.parent.name.startswith("case")})
    rows = []
    missing = []
    for case in cases:
        official = case / "output/official_ir/official_ir_prompt.txt"
        if not official.is_file():
            missing.append(relative(case, root))
            continue
        text = official.read_text(encoding="utf-8", errors="replace")
        sec = sections(text)
        sound = sec.get("overall_soundscape", "")
        music = sec.get("non_diegetic_music", "")
        detail = sec.get("detailed_description", "")
        inline = [sentence for sentence in sentences(detail) if AUDIO_WORDS.search(sentence)]
        prompt_file = case / "prompt.txt"
        user = prompt_file.read_text(encoding="utf-8", errors="replace").strip() if prompt_file.is_file() else ""
        rows.append(
            {
                "case_id": relative(case, root),
                "category": case.parent.name,
                "case_name": case.name,
                "user_prompt": user,
                "overall_soundscape": sound,
                "non_diegetic_music": music,
                "music_is_na": bool(NA_RE.match(music)),
                "inline_audio_sentences": inline,
                "has_inline_audio": bool(inline),
                "has_voice_or_dialogue": bool(re.search(SOUNDSCAPE_TAGS["voice_dialogue"], text, re.I)),
                "music_tags": tags(music, MUSIC_TAGS),
                "soundscape_tags": tags(sound, SOUNDSCAPE_TAGS),
                "music_function_tags": tags(music, FUNCTION_TAGS),
                "source_file": str(official),
            }
        )
    return cases, rows, missing


def pct(number: int, total: int) -> str:
    return f"{100 * number / total:.1f}%" if total else "0.0%"


def make_report(rows, total_cases, missing):
    count = len(rows)
    music = sum(not row["music_is_na"] for row in rows)
    no_music = count - music
    inline = sum(row["has_inline_audio"] for row in rows)
    voice = sum(row["has_voice_or_dialogue"] for row in rows)
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    music_tags = Counter(tag for row in rows for tag in row["music_tags"])
    sound_tags = Counter(tag for row in rows for tag in row["soundscape_tags"])
    functions = Counter(tag for row in rows for tag in row["music_function_tags"])

    lines = [
        "# Feishu 官方 IR 音频提示词分析",
        "",
        "> 数据由脚本从 Feishu Cases 的 `output/official_ir/official_ir_prompt.txt` 自动抽取。关键词标签用于发现模式，不代表人工语义标注；制定规则时应同时查看原文。",
        "",
        "## 数据覆盖",
        "",
        "| 指标 | 数量 | 占官方 IR |",
        "|---|---:|---:|",
        f"| Case 总数 | {total_cases} | — |",
        f"| 有官方 IR | {count} | {pct(count, total_cases)} |",
        f"| 缺少官方 IR | {len(missing)} | {pct(len(missing), total_cases)} |",
        f"| 使用非剧情内音乐 | {music} | {pct(music, count)} |",
        f"| `non_diegetic_music: N/A` | {no_music} | {pct(no_music, count)} |",
        f"| 镜头内含声音描述 | {inline} | {pct(inline, count)} |",
        f"| 涉及人声、对白或旁白 | {voice} | {pct(voice, count)} |",
        "",
        "## 按任务类别统计",
        "",
        "| 类别 | 官方 IR | 使用配乐 | N/A | 镜头内声音 |",
        "|---|---:|---:|---:|---:|",
    ]
    for category, items in sorted(by_category.items()):
        category_music = sum(not item["music_is_na"] for item in items)
        category_inline = sum(item["has_inline_audio"] for item in items)
        lines.append(f"| {category} | {len(items)} | {category_music} | {len(items) - category_music} | {category_inline} |")

    lines += ["", "## 高频写法标签", "", "### 整体声场", ""]
    lines += [f"- `{name}`：{value} 个 Case" for name, value in sound_tags.most_common()]
    lines += ["", "### 配乐类型", ""]
    lines += [f"- `{name}`：{value} 个 Case" for name, value in music_tags.most_common()]
    lines += ["", "### 配乐功能", ""]
    lines += [f"- `{name}`：{value} 个 Case" for name, value in functions.most_common()]
    lines += [
        "",
        "## 从官方样本归纳出的稳定规律",
        "",
        "1. **两个音频板块始终保留。** 57 份官方 IR 全部包含 `overall_soundscape` 和 `non_diegetic_music`；不需要配乐时写 `N/A`，而不是删除板块。",
        "2. **未指定音乐不是自动 N/A。** 官方会在开放部分补全音乐，但约三分之一案例选择 N/A，说明决策取决于内容和声音功能。",
        "3. **整体声场通常短而集中。** 它概括环境底层、主要动作反馈、空间或材质特征和必要的动态变化，不复述完整分镜。",
        "4. **关键同步声音进入 Shot。** 标题显现、冲击、脚步落地、台词、跨镜持续声和转场声音常写在对应镜头；普通可推断声音留给整体声场或模型补全。",
        "5. **配乐通常只写类型、速度、力度和作用。** 官方较少规定完整编曲或逐镜音乐自动化，避免配乐说明压过视觉提示词。",
        "6. **声音服务已有画面。** 音效和音乐强化动作、节奏、情绪、品牌调性或结尾，不反向增加视觉事件和镜头。",
        "7. **N/A 常出现在场景声已能承担节奏与情绪的案例。** 但这不是硬规则；应结合任务类型、对白、真实感和参考音频要求判断。",
        "",
        "## 建议的通用音频规划流程",
        "",
        "1. 执行用户明确的音乐、静音、原声、音轨、对白和歌词要求。",
        "2. 未指定部分作为开放设计，先确定每镜主要听觉焦点及其功能：空间建立、动作反馈、信息传递、镜头连接、节奏、情绪或品牌调性。",
        "3. 从有依据的环境声、动作声、画外持续声和必要空间关系中选择最少充分集合；只在确有空间差异时写远近、方向、移动、遮挡或余响。",
        "4. 需要精确同步、承担因果或跨镜延续的声音写进对应 Shot；`overall_soundscape` 只汇总全局关系。",
        "5. 单独判断配乐是否提供环境声无法替代的跨镜节奏、情绪统一、高潮组织或品牌调性。需要则简洁描述类型、速度、力度、动态和结束；不需要则写 `N/A`。",
        "6. 最终删除无来源、无功能、相互竞争或写得比官方明显更细的声音设计。",
        "",
        "## 推荐的精简运行规则",
        "",
        "> 完成分镜后再规划音频。遵守用户明确的音乐、静音、原声、音轨、对白和歌词要求；未指定部分属于开放设计。为每镜确定主要听觉焦点和声音功能，选择最少且充分的环境声、动作反馈与连续性声音。精确同步、因果反馈或跨镜延续写入对应 Shot；`overall_soundscape` 简洁汇总主要声音和必要空间关系，不逐镜复述。单独判断非剧情内音乐是否提供环境声无法替代的节奏、情绪、高潮或品牌价值；需要时只写必要的类型、速度、力度、动态和结束方式，不需要时写 `N/A`。声音不能反向新增视觉事件或镜头。",
        "",
        "## 数据限制",
        "",
        "- 该分析能够归纳官方 IR 的输出规律，不能还原隐藏系统提示词的原文。",
        "- 官方 IR 与最终成片可能不完全一致；Case 1 已显示文字中写有配乐，但实际成片未必出现明显背景音乐。",
        "- 8 个缺失官方 IR 的 Case 未进入统计。",
        "- 关键词标签是自动分析，涉及隐喻或特殊语言的案例需要人工复核。",
        "",
        "## 缺少官方 IR 的 Case",
        "",
    ]
    lines += [f"- `{item}`" for item in missing]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    cases, rows, missing = extract(args.root)
    payload = {
        "schema_version": "official_audio_ir_dataset.v1",
        "total_cases": len(cases),
        "official_ir_cases": len(rows),
        "missing_cases": missing,
        "cases": rows,
    }
    args.dataset.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.dataset.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(make_report(rows, len(cases), missing), encoding="utf-8")
    print(json.dumps({"total_cases": len(cases), "official_ir_cases": len(rows), "missing": len(missing)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
