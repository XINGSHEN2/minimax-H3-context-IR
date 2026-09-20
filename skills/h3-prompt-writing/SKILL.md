---
name: h3-prompt-writing
description: 为 T2VA、I2VA、FL2VA、L2VA 和 Ref2VA 编写 MiniMax H3 视频生成提示词。用于把多模态请求改写成 H3 提示词结构、编写 integrated_multimodal_description、overall_soundscape 和 non_diegetic_music、对齐关键帧，以及为图片、视频和音频定义参考标签。
compatibility: 可移植到任何能够读取本地文件的 Agent；无需外部 API、MiniMax Hub 工具或专有运行时。agents/openai.yaml 只提供可选的 ChatGPT/Codex 界面元数据，不限制本 Skill 只能供 OpenAI Agent 使用。
---

# H3 提示词编写

## 工作流程

1. 判断输入模式：T2VA、I2VA、FL2VA、L2VA 或全参考 Ref2VA。
2. 阅读 `references/shared-zh-en.txt`，应用所有模式共用的镜头、运镜、对白、可见文字和音频规则。
3. 对于基础文本／关键帧模式，阅读 `references/base-zh-en.txt`，遵循其中的最终提示词结构。
4. 对于全参考模式，阅读 `references/ref2va-zh-en.txt`，遵循其中的六板块改写格式。
5. 保持所选指南规定的字段名称、板块顺序、标签和时间格式完全一致。

## 基础模式

- T2VA：根据文本构建完整视听时间线。
- I2VA：从给定首帧出发，向后连续发展。
- FL2VA：描述从首帧到尾帧的连续路径。
- L2VA：推断合理的前置状态，并最终收敛到给定尾帧。

按照 `references/base-zh-en.txt` 的顺序输出 `integrated_multimodal_description`、`overall_soundscape` 和 `non_diegetic_music`。

## 全参考模式

Ref2VA 改写按以下顺序使用：`subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`。所有板块中的参考标签必须保持一致。

阅读 `references/ref2va-zh-en.txt`，获取标签规则、保留度分析和完整示例。

## 输出规则

- 改写板块使用英文；对白、歌词和画面中可见文字保留原始语言。
- 每个镜头写明构图、主体、环境、动作、摄影机、声音，以及参考内容出现的准确位置。
- 避免使用剧情摘要代替可执行描述，避免未定义的参考标签，以及与目标时长不一致的时间标记。
