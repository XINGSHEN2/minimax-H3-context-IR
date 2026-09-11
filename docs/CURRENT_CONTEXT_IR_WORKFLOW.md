# v20 当前流程

1. `run_agent` 规范化和校验 `context_request.v1`。
2. `resolve_intent` 调用推理模型解析用户需求、素材引用、directives 和 perception_plan。原始 user_request 保持最高优先级。调用方提供已解析需求并显式设置 intent_resolved 时可跳过此调用。
3. `ensure_perception` 使用 Qwen 分析素材，或复用调用方／文件提供的 media_analysis.v2。调用方描述会标记为未独立验证的证据。
4. `build_writer_evidence` 整理证据；`prepare_writer_evidence` 仅移除观察置信分数，不删除用户约束。
5. `compile_prompt` 拼接 v20 RULES 与 `build_compact_writing_prompt`；`invoke_reasoning_json` 注入 AGENTS.md、h3-prompt-writing、base-en.txt、ref-en.txt、h3-shot-planning。
6. `DirectChatRuntime.invoke_json` 发送 `/chat/completions`。模型联合输出 content_plan、h3_prompt、uncertainties。没有独立导演或语义修复阶段。
7. `transport_issues` 检查结果字段、素材编号、镜头时间连续性及目标时长；官方章节缺失只提示警告。程序不验证语义完整性。
8. 保存轻量 IR、原样 Prompt、H3 请求和诊断文件。视频生成由单独能力显式触发。

正常路径包含一次意图调用及一次编译调用，另有素材理解调用。复用分析不会自动跳过意图解析。底层 Direct Chat 仍保留网关不支持 response_format 时的兼容重发，以及 JSON 语法修复调用；因此 llm_calls=1 表示编译器调用次数，并非所有情况下的 HTTP 请求总数。输出截断会报错，不拼接缺失内容。

## 当前服务

- 素材上传：`QWEN_ASSET_UPLOAD_BASE_URL=http://10.0.96.114:30100`，multipart POST `/v1/assets`。
- 图片／视频：`QWEN_IMAGE_UNDERSTAND_BASE_URL`、`QWEN_VIDEO_UNDERSTAND_BASE_URL` 指向 `http://10.6.157.43:9012`，模型 `Qwen3.8-27B`。
- 视频默认 fps=2、max_frames=256。图片使用 image_url，视频使用 video_url，URL 来自 asset 服务。
- 推理网关：`CONTEXT_IR_LLM_CHAT_BASE_URL=https://llm-gw.kai.metax-tech.com/v1`；`CONTEXT_IR_LLM_PROVIDER=deepseek_litellm` 使用 `LITELLM_API_KEY`、`DEEPSEEK_LITELLM_MODEL`，例如 sha/deepseek-v4-flash 或 inc/deepseek-v4-flash。
- GLM：选择 `CONTEXT_IR_LLM_PROVIDER=glm`，使用 `OPENAI_API_KEY`、`GLM_MODEL`，同一 Chat base URL 可继续使用。
- `CONTEXT_IR_LLM_MAX_TOKENS` 控制输出上限，上下文窗口不等于输出长度上限。

## 产物

`input.json`、`resolved_input.json`、`intent_resolution.json`、`perception_plan.json`、`media_analysis.json`、`evidence_input.json`、`compiler_instructions.txt`、`writer_1.log`、`compilation_result.json`、`content_plan.json`、`context_ir.json`、`h3_prompt.txt`、`h3_request.json`、`h3_prompt_audit.json`、`result_status.json`、`stage_timings.json`。

`context_ir.json` schema 为 h3_compilation.light.v1，包含 task、assets、content_plan、uncertainties、perception。失败时保留诊断文件，不产生有效的 H3 提交请求；不要把不完整目录当作完成结果。
