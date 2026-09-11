# v20 案例输出约定

每个案例保留原始需求和素材，在 `output/<版本目录>/` 下保存独立运行结果，不覆盖旧版本。

- `context_ir.json`：h3_compilation.light.v1 轻量生产记录。
- `content_plan.json`：模型联合生成的内容计划。
- `h3_prompt.txt`：同次调用生成的完整提示词。
- `h3_request.json`：可显式提交给 H3 的请求，不代表已经生成视频。
- `media_analysis.json`、`evidence_input.json`：素材分析及实际写作证据。
- `h3_prompt_audit.json`、`result_status.json`、`stage_timings.json`：格式检查、状态和耗时。

只有运行成功且 h3_prompt_audit.passed=true 才作为可审阅版本。semantic_quality_verified=false，仍需人工比较用户需求、素材及官方 IR。失败目录保留日志供排查，不当作完成版本。历史生成结果、对比页面和本地 work 实验数据不随代码清理删除。
