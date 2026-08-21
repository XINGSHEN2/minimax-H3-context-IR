# MiniMax-H3 Context-IR Agent

面向 MiniMax-H3 多素材视频生成的 Context-IR 编译 Agent。用户只需提交自然语言需求和图片、视频等参考素材，系统会解析素材用途与继承边界，完成定向视觉理解、跨素材关系推理、确定性指令绑定、时间线编排和官方格式 Prompt 渲染，最终输出可验证、可追踪的 Context-IR、H3 Prompt 与服务请求。

当前推理 LLM 可在 DeepSeek 和 GLM 之间切换；视觉感知默认使用本地部署的 Qwen3-VL-32B。模型负责理解和推理，关键用户指令由程序级编译与校验锁定，避免只依赖语言模型“记住”约束。

完整设计与字段说明见 [当前 Context-IR 工作流](docs/CURRENT_CONTEXT_IR_WORKFLOW.md)。

## 项目结构

```text
backend/     Python Agent、感知适配器、Context-IR 编译器与 Web API
frontend/    独立浏览器界面
assets/      按案例组织的上传与请求素材
skills/      MiniMax-H3 官方 Skills
deploy/      容器启动脚本与本地环境配置模板
outputs/     生成的 Context-IR、H3 Prompt、审计与请求文件
```

根目录下的 `agent.py`、`context_ir.py` 和 `perception.py` 作为向后兼容入口保留；当前实际实现位于 `backend/`。

## 整体架构

```mermaid
flowchart TD
    A["用户自然语言需求<br/>图片、视频、音频及素材标签"] --> B["Intent Resolver<br/>DeepSeek / GLM"]
    B --> C["Locked Directives<br/>Perception Plan"]
    C --> D["Qwen3-VL-32B<br/>定向图片与视频分析"]
    D --> E["media_analysis.v2<br/>客观素材证据"]
    A --> F["Context-IR Semantic Agent<br/>DeepSeek / GLM"]
    C --> F
    E --> F
    G["MiniMax-H3 官方 Skills"] --> F
    F --> H["Context-IR Candidate"]
    H --> I["Directive Binding Compiler"]
    I --> J["规范化与严格校验"]
    J --> K["H3 官方格式 Prompt Renderer"]
    K --> L["Prompt Auditor"]
    L --> M["Context-IR JSON<br/>H3 Prompt<br/>H3 Request JSON"]
```

各层职责：

- **Intent Resolver**：先理解用户明确指定的素材用途、替换关系、保持项、禁止项和镜头要求，并生成 VLM 应重点观察的问题。
- **Qwen3-VL 感知层**：只提取图片与视频中的客观证据，不负责决定最终创意；视频默认按 2 FPS 解码并保留实际时间语义。
- **Semantic Agent**：结合用户原始需求、锁定指令和素材证据，推理资产角色、引用隔离、状态变化、连续性与时间线。
- **Directive Binding Compiler**：把用户已明确指定的要求编译为程序级强绑定，防止后续模型输出偏离重点。
- **Renderer 与 Auditor**：生成 MiniMax-H3 官方三段式或六段式 Prompt，并检查引用、主体、时间线、商品重点与禁止项。

视觉分析标准输出为 `media_analysis.v2`。传入已有 perception 缓存时可以跳过 VLM，便于重复调试 IR；测试 VLM 准确性时应禁用缓存重新分析。音频目前会保留在素材清单中，但 Qwen 视觉层不分析音轨，后续可接入独立音频感知模型。

## 运行方法

将每个请求的素材放在 `assets/case_NNN/` 下，并分别使用 `images`、`videos` 和 `audio` 子目录。可以从 `assets/case_001/request.json` 开始；素材路径应使用 `/home/mx/shenxing/minimax-H3-context-IR/assets/...` 形式的绝对路径，确保宿主机与容器内解析结果一致。

参考 `examples/request.example.json` 准备输入 JSON，然后运行：

```bash
cd /home/mx/shenxing/minimax-H3-context-IR
bash deploy/run.sh examples/request.example.json
```

运行仓库自带的案例模板：

```bash
bash deploy/run.sh assets/case_001/request.json
```

用户不需要手写完整 Context-IR。最小请求只需自然语言和素材清单，例如：

```json
{
  "user_request": "参考视频的运镜和展示结构，为图片中的商品制作一条15秒竖屏广告，商品外观不要改变。",
  "task": {
    "type": "ref2va",
    "duration_seconds": 15,
    "aspect_ratio": "9:16",
    "generate_audio": true,
    "style": "premium commercial, photorealistic"
  },
  "assets": [
    {
      "asset_id": "image_1",
      "media_type": "image",
      "uri": "/absolute/path/product.png",
      "label": "图片1 - 商品外观"
    },
    {
      "asset_id": "video_1",
      "media_type": "video",
      "uri": "/absolute/path/reference.mp4",
      "label": "视频1 - 仅参考运镜和展示结构"
    }
  ]
}
```

如果用户提供了更详细的分镜、素材继承范围或状态切换要求，系统会把这些内容视为高优先级指令；只对未指定但生成所必需的部分进行保守补全。

## Web 操作界面

在项目目录中启动独立前端与素材上传 API：

```bash
bash deploy/web.sh
```

然后打开 `http://<aigc-host>:38080`。界面支持自然语言需求和拖放素材，会自动为图片、视频和音频编号，记录每份素材的预期用途，创建新的 `assets/case_NNN`，并运行同一套 Codex Agent 流程。生成文件保存在 `outputs/` 下，可在 Context-IR、H3 Prompt 和审计标签页中查看。

该界面参考了 MIT 许可项目 `ComfyUI-MiniMaxH3-Prompt-Writer` 的交互方式，但属于独立实现，不依赖 ComfyUI，也没有复制其运行时集成。

默认情况下，结果会写入 `outputs/` 下按时间戳命名的目录；也可以通过 `--output-dir` 指定输出位置。规范化后的视觉证据保存在 `media_analysis.json` 中；模型推理文本和 Base64 图片载荷不会写入输出目录。
主要产物包括：

```text
intent_resolution.json   用户指令锁定与定向感知计划
media_analysis.json      Qwen 客观素材分析（media_analysis.v2）
context_ir.json          规范化并通过校验的 Context-IR
h3_prompt.txt            可直接提交给 H3 的官方格式 Prompt
h3_prompt_audit.json     Prompt 审计结果、错误与警告
h3_request.json          MiniMax-H3 服务请求
```

每次成功运行都会生成 `h3_prompt_audit.json`。基础任务（`T2VA/I2VA/FL2VA/L2VA`）使用官方三段式结构，`Ref2VA` 使用官方六段式结构。H3 引用标签根据最终条件顺序确定性生成。

仅检查 Codex 运行环境和 GLM 网关，不执行 Agent 推理：

```bash
bash deploy/run.sh --preflight-only
```

需要指定官方风格 Skill 时：

```bash
bash deploy/run.sh request.json --style-skill minimalist-product-ad-generator
```

不调用 GLM，仅校验已有 Context-IR：

```bash
bash deploy/run.sh --validate-only outputs/<run>/context_ir.json
```

## 运行配置

视觉感知默认使用本地部署的 Qwen3-VL-32B FIFO 服务：

- `CONTEXT_IR_VLM_PROVIDER`：默认值 `local-qwen3-vl-32b`
- `YIWU_VLM_BASE_URL`：默认值 `http://127.0.0.1:9012`
- `YIWU_VLM_MODEL`：默认值 `Qwen3-VL-32B-Instruct`
- `CONTEXT_IR_VIDEO_FPS`：默认值 `2`
- `CONTEXT_IR_VIDEO_MAX_FRAMES`：默认值 `256`
- `CONTEXT_IR_VLM_TIMEOUT_SECONDS`：默认值 `1800`

与 `yiwu_codex` 启动方式一致，运行参数可以保存在本地环境文件中。将 `deploy/context_ir.env.example` 复制为 `deploy/context_ir.env`，在其中填写密钥，并确保该文件不进入版本控制。系统中已经导出的环境变量优先于文件内配置。

本地图片和视频的绝对路径会直接提交给服务。服务将输入复制到 FIFO 任务目录，并使用 Qwen 原生视频工具按时间顺序解码帧；当前不分析音轨。原有 `gitee-qwen3-vl` 联系表适配器仍可作为显式指定的备用感知提供方。

Codex Agent 通过 Responses API 支持切换推理模型。在 `deploy/context_ir.env` 中设置 `CONTEXT_IR_LLM_PROVIDER=deepseek` 或 `CONTEXT_IR_LLM_PROVIDER=glm`。

GLM 配置：

- `GLM_MODEL`：默认值 `GLM-5.2`
- `GLM_PROVIDER_ID`：默认值 `glm`
- `GLM_RESPONSES_BASE_URL`：默认值 `http://127.0.0.1:38041/v1`
- `GLM_HTTP_HOST`：默认值 `litellm-poc.pgw.metax-tech.com`
- `OPENAI_API_KEY`：必填，LiteLLM Bearer Key
- 传输 API：`responses`

DeepSeek 配置：

- `DEEPSEEK_MODEL`：默认值 `deepseek-v4-flash`
- `DEEPSEEK_PROVIDER_ID`：默认值 `deepseek`
- `DEEPSEEK_RESPONSES_BASE_URL`：默认值 `https://api.deepseek.com`
- `DEEPSEEK_API_KEY`：必填，DeepSeek 官方 API Key
- 传输 API：`responses`

DeepSeek 官方 Responses 端点可以直接与 Codex 配合使用，不经过 GLM 的 LiteLLM 隧道。切换推理模型不会影响 Qwen 感知阶段和确定性的 Context-IR 校验流程。

真实 LiteLLM 密钥只应保存在已忽略的 `deploy/context_ir.env` 文件中。由于 `aigc` 无法解析 LiteLLM 内网域名，需要由 Windows 通过 SSH 反向隧道提供网络访问：

```powershell
Start-Process ssh -ArgumentList @(
  "-N", "-T",
  "-o", "ExitOnForwardFailure=yes",
  "-o", "ServerAliveInterval=30",
  "-o", "ServerAliveCountMax=3",
  "-R", "38041:litellm-poc.pgw.metax-tech.com:80",
  "aigc"
) -WindowStyle Hidden
```

Codex 通过 `127.0.0.1:38041` 调用隧道时，`GLM_HTTP_HOST` 用于保留原始虚拟主机路由。

Docker **容器**名称为 `minimax_h3_context_ir`。默认情况下，启动脚本只复用现有 **镜像** `yiwu_codex:latest` 作为 Codex SDK 运行环境；容器与镜像是两个不同概念。可以通过 `CONTEXT_IR_IMAGE` 覆盖镜像，例如：

```bash
CONTEXT_IR_IMAGE=minimax-h3-context-ir:latest bash deploy/run.sh request.json
```

挂载后的项目保持独立，不依赖 `/home/mx/shenxing/yiwu_codex`。

只有选择 GLM 时才需要外部 LiteLLM Responses 网关；本项目的启动脚本不会启动或管理该网关。
