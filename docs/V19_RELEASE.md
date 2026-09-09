# v19 内容优先编译版

本版将已测试的 v19 实验规则合入 `backend/single_call_compiler.py`，版本标识为 `singlecall.v19.content_first`。

## 主要变化

- 单次 LLM 响应内先形成 `developments`（内容变化及结果），再通过 `development_ids` 分配镜头。
- 不限定镜头数量；保留用户指定镜头、关键帧顺序、参考节奏和合理扩写。
- 短黑场、闪光、运动模糊通常作为镜头边界；连续标题动效不因每个效果机械拆镜。
- 没有新增第二轮导演调用。现有接口和兼容路径继续保留，本次不重启服务或改变调用方模式。

## 实验范围与复现

Feishu 1.1 Case1–5 的结果位于各自 `output/local_ir_260909_19_content_first_qwen38/`。
使用已有 v17 Qwen3.8-27B 素材分析，未重新感知；DeepSeek 官方 `deepseek-v4-flash` 单次编译，不输入旧 Prompt。
每个结果目录包含 `evidence_input.json`、`compiler_rules_used.txt`、`writer_instructions_used.txt`、`system_instructions_used.json`、`experiment.json` 和耗时记录，可追溯当次完整输入。合入规则与实验快照按去除首尾空白后核对。
H3 视频为 768p、20 步、15 秒、16:9，实际帧对齐时长略有增加。

## 展示与已知限制

GitHub Pages 的 1.1 本地栏使用 v19 视频和对应 Prompt；Raw、官方、2.2、原始 A/B Test 不变。官方结果不重复生成。
v19 不是全方面优于旧版的质量保证。商品证据错误仍可能传入最终 Prompt；镜头数不能直接代表视频重复程度。Case2 的标题分镜不能仅凭文本判定实际视频重复。
部署的图片和视频理解服务选择 Qwen3.8-27B；机器地址及密钥保留在不提交的环境文件中。
