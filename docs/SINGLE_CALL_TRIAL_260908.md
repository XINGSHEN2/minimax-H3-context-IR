# 09 批次：素材证据后的单次编译试验

## 冻结基线

服务器：aigc；项目：`/home/mx/shenxing/minimax-H3-context-IR`。

冻结目录：`outputs/frozen_260908_before_singlecall`。

`source.tar.gz` 保存当前工作区源码（包括未提交的修改），`manifest.json` 保存 98 个文件的 SHA-256。归档已逐文件校验。此快照不包括密钥、环境文件、素材、结果或安装依赖，不是完整运行环境备份。归档 SHA-256：`ca23168e65e7c602d1384cbea081e05679a3caee74bd05d385c67aaefcbdc0a8`。

现有服务不重启、不切换公开 API、不覆盖 08 批次、不重新生成官方结果。

## 本轮仅替换哪部分

旧：LLM 草稿 → 程序语义编译 → LLM 最终写作。

新：用户需求 + 已解析意图 + Qwen 证据 + 两份 H3 Skills → 一次 LLM → 轻量 content_plan + 最终 H3 Prompt。

基础检查只核对响应可用性、真实素材引用和计划时间。轻微格式问题只记录警告；硬错误允许再调用一次修复。没有新增独立审核阶段，基础检查不保证语义正确。

`backend/single_call_compiler.py` 是新实验入口，复用 `backend/compact_writer.py` 和现有模型适配器。它使用 `h3_compilation.light.v1`，不冒充旧版完整 Context-IR。

## 对照条件

- 1.1 五个案例和 2.2 四个案例。
- 同一案例复用 08 批次的原始需求、意图解析和 Qwen 分析；不重新感知。
- 与 08 相同的 DeepSeek 官方 `deepseek-v4-flash`、high 推理设置。
- 1.1 目标均 15 秒；2.2 目标分别为 14.9、9.474、5、5.875 秒，不统一拉到 15 秒。
- 不向模型提供旧版 Prompt 或官方 Prompt。
- 新结果放在各 Case 的 `output/local_ir_260908_09_singlecall/`。
- 本轮只生成 Prompt，不提交视频任务，不自动发布网页。

## 核验文件

`h3_prompt.txt`：新版最终 Prompt。

`content_plan.json`：素材绑定、保持项和镜头状态记录。

`evidence_input.json`：实际提供给模型的输入；沿用正式编译器的证据压缩方法，原始分析按基线路径和哈希追踪。

`comparison_metadata.json`：基线、模型、源码和输入哈希、实际调用次数、耗时、长度和状态。

`h3_prompt_audit.json`：基础检查结果，不是语义评分。

`h3_request.json`：仅基础检查通过时输出，沿用原请求的素材和目标；未提交。

总进度：项目 `outputs/local_ir_260908_09_singlecall_summary.json`。

## 如何判断

先核对用户指定内容是否完整、素材来源是否正确、运镜和转场是否执行得清楚、状态有无回退或重复、声音是否一致。对照旧版和官方时，不把更短或基础检查通过当作更好。最终视频效果仍需用户确认 Prompt 后单独生成。

记录耗时仅为“已有素材证据之后的编译耗时”，不含意图解析、Qwen 或 H3 视频生成。

## 后续规则修订：singlecall.rules.v2

09 批次全部完成后，新增四项同次编译规则：按观众获得的新信息组织镜头；稳定属性集中定义、只删除重复而非关键细节；不确定文字和属性保持不确定，不擅自合并人物或把未知歌声改成无词吟唱；在返回前核对立即反应、道具持握、位置互换、动作完成状态与声音结束点。

只修改 singlecall 专用规则，未改公共 compact_writer、官方 Skills 或正式 API。新增 audience_gain/cut_reason 是轻量规划提示，不是新的程序拒绝条件；不设固定镜头数或字数上限，不增加独立审核调用。

09 版实验模块原文件另存于冻结目录的 `single_call_compiler_09.py`，SHA-256 为 `42b3a50dc62264cff4119df99867b4f4e35cce07bf2b758a8377a0706e2c360e`。旧 09 案例保持不变。批量脚本下一次执行默认输出到 `output/local_ir_260908_10_singlecall_editorial`，并记录 compiler_revision；本次规则修改未启动 10 批次。

9 项无模型调用测试通过，覆盖正常单次调用、修复上限、无效引用、时间、规则注入、用户约束保留、多镜不拒绝及新增备注不成为校验门槛。它们不是 LLM 语义或视频质量评测。
