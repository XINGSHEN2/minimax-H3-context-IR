# 脚本导航

业务调用优先使用 [API](../docs/API.md)，测试使用 `python3 -m pytest -q`。本目录不是全部都适用于 v20 的批处理入口。

## 按用途查找

- 页面维护：`build_examples_showcase.py`。可能改写已发布数据，执行前检查版本和参数。
- 服务检查：`verify_context_ir_services.py`、`*smoke_test.sh`。部分历史测试依赖旧模型网关或会发起请求，先阅读脚本。
- 复现与计时：`recompile_output.py`、`cold_timing_benchmark.py`、`run_ab_suite.py`。
- 历史专项：`retest_*`、`diagnose_*`、`replay_*`、`resume_*`、`run_dsv4f_case1_7.py` 等，可能带固定 Case 路径和旧接口，不作为当前推荐入口。
- 视频提交：`run_local_ir_h3_480.py`，会产生真实生成任务，勿用于只想检查 Prompt 的场景。

暂不移动历史脚本，避免脚本的仓库根目录计算、固定路径及外部调用失效。新增临时实验应放到本地忽略目录 `scratch/`；确需维护的工具补充用途、参数、是否调用付费模型或提交视频。
