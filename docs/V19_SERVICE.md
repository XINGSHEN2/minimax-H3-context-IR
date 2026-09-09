# 正式服务 v19 切换

`run_agent` 的素材生成路径在意图解析、素材理解后调用 `single_call_service.finish_single_call`，不再执行旧草稿、语义修复和最终导演。

- 正常生成阶段一次 LLM 请求；结构错误落盘并报错，不隐式追加请求。
- 新素材仍有前置意图解析请求。`media_analysis` 配合 `intent_resolved=true` 可跳过该阶段。
- HTTP 响应字段保持，但 `context_ir` 产物的 schema 改为 `h3_compilation.light.v1`，内含 `content_plan`，不是旧 canonical IR。消费者应按 schema 区分。
- `input_type=context_ir` 仍只用于已有 canonical IR 的兼容优化路径，不适用于轻量记录。
- H3 请求由输入 task/assets 构建，不从模型文字推断素材地址、时长。关键帧任务要求显式 frame_index。
- 图片和视频理解使用 9012 的 Qwen3.8-27B；API 端口保持 38080。
- 运行状态 `/api/health` 显示 `prompt_compiler` 和调用次数语义。

回滚：切换前代码提交为 e684573（后续服务器实际部署还应以部署记录为准）。可将本次服务切换提交 revert 后重启；环境文件备份保存在服务器备份目录，不上传 Git。
