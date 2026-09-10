# 当前 Context-IR 工作流（v20）

本文取代旧两阶段工作流说明。编译器版本：`singlecall.v20.reference_inheritance`。

## 执行阶段

1. 校验输入模式和素材清单。自然语言素材描述先在内部标准化；已有分析可复用。
2. 按输入条件进行前置意图解析，明确用户要求和感知重点。
3. 新素材调用图片／视频理解；当前验证模型 Qwen3.8-27B。视频按配置解码，视觉服务不分析音轨。复用分析不等于重新验证素材。
4. 将原始需求、解析结果、素材证据和 Skills 送入单次编译，联合产出 `content_plan` 与 `h3_prompt`。绑定、动作、镜头、时间和声音在该响应内协调。
5. 程序执行传输契约检查，保存产物，并根据实际输入构建 H3 Request。通过检查不代表语义或视频质量已验证。
6. 仅在调用方要求时提交视频。

## 代码入口

- `backend/agent.py`：意图、感知与编译编排。
- `backend/single_call_service.py`：单次编译产物保存与请求构建。
- `backend/single_call_compiler.py`：v20 规则、证据准备、传输检查。
- `backend/compact_writer.py`：联合写作提示词。
- `backend/llm_runtime.py`：模型请求与 JSON 处理。

单次是正常编译阶段的设计，不是全流程网络调用上限。前置意图解析另计；底层 JSON 修复或网络重试可能增加请求。`prompt_llm_calls=1` 不应作为实际 HTTP 请求计数使用。

## v20 的素材继承

区分必需保留、可选继承、明确排除。主要角色不等于排他白名单；未指定场景时可继承适合动作的主体参考背景。用户明确的替换、禁止、仅身份或仅风格范围仍优先。模型需记录排除理由，但理由本身仍可能不正确，应通过案例检查验证。

## 主要产物

| 文件 | 意义 |
|---|---|
| `intent_resolution.json` | 适用时保存的意图与感知计划 |
| `media_analysis.json` | 新分析或复用的标准素材证据 |
| `evidence_input.json` | 提交编译的证据 |
| `compiler_instructions.txt` | 编译指令，可能包含用户资料，不应无条件公开 |
| `content_plan.json` | 内容、继承与分镜计划 |
| `context_ir.json` | `h3_compilation.light.v1` 轻量记录，不是旧 canonical IR |
| `h3_prompt.txt` | 最终 H3 Prompt |
| `h3_prompt_audit.json` | 契约检查；不代表审美或事实正确 |
| `h3_request.json` | 基于真实素材与任务参数的请求 |
| `stage_timings.json` | 阶段计时 |

失败时产物可能不完整。旧 `input_type=context_ir` 兼容路径仍不同于本页流程；不要把轻量记录回传为 canonical IR。

## 已知限制

- OCR、实体和视频事件仍可能误识别。
- 被识别的信息可能在后续继承决策中丢失。
- 音频素材编号、复用范围、旁白和音乐设计仍需核验；不能从图片或视觉分析推断听到了原音。
- 本次文档更新不改变运行服务。以 `/api/health` 为准区分仓库 v20 与实际部署。
