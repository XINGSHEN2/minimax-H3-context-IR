# H3 v20 Prompt compiler

当前分支只保留 v20 生产流程：用户需求 → 意图解析 → 素材理解或复用 → 单次联合编译 content_plan 与 H3 Prompt → 格式校验 → 保存产物。

## 入口

- CLI：`python3 agent.py request.json --output-dir outputs/my-run`。输出目录必须不存在。
- 复用素材分析：追加 `--perception-from /absolute/path/media_analysis.json`。
- 输入校验：`python3 agent.py --validate-only request.json`。
- Web/API：`python3 -m backend.api --host 127.0.0.1 --port 38080`。
- Docker 包装入口：`bash deploy/run.sh ...`、`bash deploy/web.sh`，读取本机 `deploy/context_ir.env`。现有镜像仅作为 Python 运行环境，不再调用 Codex SDK。

运行前将配置模板复制到 `deploy/context_ir.env` 并填写密钥；直接运行 Python 时需向进程导出配置，Python 入口不会自动读取 env 文件。不要提交本机密钥。

## 代码结构

| 模块 | 职责 |
|---|---|
| backend/agent.py | v20 流程编排、模型配置、官方 Skills 注入 |
| backend/intent_resolver.py | 解析需求、素材角色和分析计划 |
| backend/perception.py | 素材理解、远程 Qwen 上传、证据规范化和缓存 |
| backend/evidence.py | 把需求和素材证据整理为写作输入 |
| backend/prompt_instructions.py | 联合写作指令 |
| backend/compiler.py | v20 规则、单次联合编译、格式校验及产物保存 |
| backend/contracts.py | 输入契约和 H3 请求序列化 |
| backend/llm_runtime.py | Direct Chat Completions 模型适配 |
| backend/capabilities.py | 三种输入方式与独立视频提交能力 |
| backend/api.py、frontend/ | HTTP 接口与工作台 |

旧 canonical IR 编译器、确定性 Prompt 渲染器、独立导演优化器、Codex 执行路径及历史实验入口已移除。`context_ir.json` 仍沿用案例文件名，但内容是 `h3_compilation.light.v1`。旧 `input_type=context_ir` 不再支持。

## 配置与验证

图片／视频理解使用 Qwen3.8-27B，素材先上传至 asset 服务。推理模型可通过现有环境变量切换上海／宁夏 DeepSeek 或 GLM；模型可用性由网关决定。详见 [当前流程](docs/CURRENT_CONTEXT_IR_WORKFLOW.md)。

核心 Direct Chat 路径使用 Python 标准库；素材处理根据输入需要系统 curl、ffmpeg/ffprobe，以及可选的 Pillow、imageio-ffmpeg 或特定感知适配器依赖。Python 推荐 3.10–3.12（Web 上传目前使用 cgi）。

安装测试依赖后运行：

```bash
python3 -m pip install -r requirements-dev.txt
bash scripts/smoke_test.sh
```

测试使用模拟模型和素材服务，不消耗真实推理或生成视频。格式校验通过不等于语义质量已被验证。

[API](docs/API.md) · [案例输出约定](docs/CASE_OUTPUT_CONVENTION.md) · [脚本](scripts/README.md)
