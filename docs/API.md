# Context-IR 对外 API 使用文档

本文档是 MiniMax-H3 Context-IR 项目的统一对外接口说明。普通业务调用方优先使用稳定业务接口；图片、视频和音频理解接口仅供其他 Agent、Skill 或素材系统按需复用。

## 1. 服务地址与协议

示例地址：

```text
http://10.100.4.2:38080
```

除文件上传页面外，本项目接口统一使用：

```http
Content-Type: application/json
```

成功响应：

```json
{
  "ok": true,
  "result": {}
}
```

失败响应：

```json
{
  "ok": false,
  "error": "错误说明"
}
```

常用状态码：

| 状态码 | 含义 |
|---|---|
| `200` | 请求成功 |
| `400` | JSON、字段或输入结构不合法 |
| `404` | 接口不存在 |
| `413` | 请求为空或超过服务限制 |
| `500` | 模型、网络或内部执行失败 |

## 2. 接口总览

### 稳定业务接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/h3/prompt` | 生成 Context-IR、H3 Prompt、审计和 H3 Request |
| `POST` | `/api/h3/videos` | 提交 H3 视频任务，并可选等待结果 |
| `POST` | `/api/context-ir/generate` | 组合 Prompt 编译与可选视频生成 |

### 可选通用理解接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/understand/image` | 图片实体、属性、关系和证据提取 |
| `POST` | `/api/understand/video` | 视频事件、动作、镜头和实际时间线提取 |
| `POST` | `/api/understand/audio` | 音频证据提取；需要配置音频感知模型 |

### 服务状态与能力发现

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/health` | 检查 IR、VLM 和 LLM 服务状态 |
| `GET` | `/api/capabilities` | 查询当前公开接口和 Prompt 输入类型 |

`media_evidence_normalize` 是内部数据适配步骤，不作为 HTTP 接口单独开放。

## 3. 健康检查

```bash
curl http://10.100.4.2:38080/api/health
```

示例响应：

```json
{
  "ok": true,
  "services": {
    "ready": true,
    "vlm": {
      "ready": true,
      "model": "Qwen3-VL-32B-Instruct"
    },
    "llm": {
      "ready": true,
      "model": "deepseek-v4-flash"
    }
  }
}
```

只有 `services.ready=true` 才表示完整 Prompt 流程可用。

## 4. 能力发现

```bash
curl http://10.100.4.2:38080/api/capabilities
```

响应会分别列出：

- `business_api`：稳定业务接口；
- `optional_general_api`：可选通用理解接口；
- `internal`：仅供服务内部使用的能力；
- `h3_prompt_input_types`：当前支持的 Prompt 输入起点。

## 5. 生成 H3 Prompt

```text
POST /api/h3/prompt
```

该接口是普通用户的推荐入口，支持四种输入成熟度：

| `input_type` | 调用方已有内容 | 是否调用 VLM | 执行范围 |
|---|---|---|---|
| `assets` | 原始图片、视频或音频 | 是 | 素材理解到 H3 Request |
| `asset_descriptions` | 人工或外部系统的素材描述 | 否 | 描述标准化到 H3 Request |
| `media_analysis` | 标准 `media_analysis.v2` | 否 | IR 编译到 H3 Request |
| `context_ir` | 已有合法 Context-IR | 否 | Prompt 渲染、审计和请求构建 |

### 5.1 使用自然语言素材描述

如果用户已经分析完素材，只想把自然语言需求和素材描述转换成 H3 Prompt，使用 `asset_descriptions`：

```bash
curl -X POST \
  http://10.100.4.2:38080/api/h3/prompt \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "asset_descriptions",
    "source": {
      "user_request": "参考视频动作和镜头节奏，用图片中的甲片替换原商品。第一镜保持裸手，第二镜开始佩戴甲片，后续保持同一套甲片。",
      "task": {
        "type": "ref2va",
        "duration_seconds": 15,
        "aspect_ratio": "9:16",
        "generate_audio": true,
        "style": "premium commercial, photorealistic"
      }
    },
    "asset_descriptions": [
      {
        "asset_id": "image_1",
        "media_type": "image",
        "uri": "/shared/assets/nails.png",
        "description": "一套蓝紫色和橙红色穿戴甲，包含星星、钥匙和银河旋涡装饰。图片只控制甲片外观，不继承包装背景。"
      },
      {
        "asset_id": "video_1",
        "media_type": "video",
        "uri": "/shared/assets/reference.mp4",
        "description": "15秒竖屏展示视频。人物先展示裸手，约4秒切换为佩戴甲片，随后双手靠近脸部展示，最后为手部近景。只参考动作、运镜和剪辑节奏。"
      }
    ]
  }'
```

内部自动执行：

```text
asset_descriptions
→ 素材证据标准化
→ media_analysis.v2
→ 绑定、隔离、时间线和连续性编译
→ Context-IR
→ H3 Prompt 渲染与审计
→ H3 Request
```

描述会标记为调用方提供，不会被伪装成 VLM 独立确认的事实。

如果 `source.assets` 已经包含路径，`asset_descriptions` 可以只提交 `asset_id` 和 `description`。两处 `asset_id` 集合必须完全一致。

### 5.2 从原始素材开始

```json
{
  "input_type": "assets",
  "source": {
    "user_request": "参考视频的运镜，为图片中的商品制作15秒广告。",
    "task": {
      "type": "ref2va",
      "duration_seconds": 15,
      "aspect_ratio": "9:16",
      "generate_audio": true
    },
    "assets": [
      {
        "asset_id": "image_1",
        "media_type": "image",
        "uri": "/shared/assets/product.png"
      },
      {
        "asset_id": "video_1",
        "media_type": "video",
        "uri": "/shared/assets/reference.mp4"
      }
    ]
  }
}
```

该模式会调用当前配置的图片、视频或音频理解能力。

### 5.3 复用标准素材分析

```json
{
  "input_type": "media_analysis",
  "source": {
    "user_request": "保持商品外观不变，生成15秒高级广告。",
    "task": {
      "type": "ref2va",
      "duration_seconds": 15,
      "aspect_ratio": "9:16",
      "generate_audio": true
    },
    "assets": [
      {
        "asset_id": "image_1",
        "media_type": "image",
        "uri": "/shared/assets/product.png"
      }
    ]
  },
  "media_analysis": {
    "schema_version": "media_analysis.v2",
    "provider": {
      "name": "upstream",
      "model": "custom",
      "options": {}
    },
    "assets": [
      {
        "asset_id": "image_1",
        "summary": "透明玻璃香水瓶，黑色斜切瓶盖。",
        "evidence": [],
        "regions": [],
        "entities": [],
        "relations": [],
        "events": [],
        "technical": {},
        "transcript": "",
        "uncertainties": [],
        "evidence_coverage": [],
        "supplemental_attempts": []
      }
    ],
    "missing_asset_ids": []
  }
}
```

### 5.4 复用已有 Context-IR

```json
{
  "input_type": "context_ir",
  "context_ir": {
    "schema_version": "context_ir.v2"
  },
  "prompt_file": "/shared/prompts/result.txt",
  "output_path": "/shared/h3-outputs"
}
```

调用方必须提供完整且通过当前 Schema 校验的 Context-IR。该模式不调用 VLM 和语义 LLM。

### 5.5 Prompt 生成返回值

```json
{
  "ok": true,
  "result": {
    "schema_version": "h3_prompt_generate.v1",
    "input_type": "asset_descriptions",
    "sources": {
      "media_analysis": "normalized_from_caller_descriptions",
      "context_ir": "generated"
    },
    "media_analysis": {},
    "context_ir": {},
    "h3_prompt": "...",
    "h3_prompt_audit": {},
    "h3_request": {},
    "stage_timings": {},
    "artifacts": {}
  }
}
```

关键字段：

- `media_analysis`：标准化素材证据；
- `context_ir`：素材绑定、隔离、时间线和连续性；
- `h3_prompt`：最终 MiniMax-H3 Prompt；
- `h3_prompt_audit`：Prompt 结构与约束审计；
- `h3_request`：可提交给 H3 的请求；
- `stage_timings`：各阶段耗时；
- `artifacts`：产物来源及 SHA-256。

## 6. 提交 H3 视频任务

```text
POST /api/h3/videos
```

可以直接提交 `h3_request`：

```json
{
  "task": "ref2va",
  "prompt_file": "/shared/prompts/result.txt",
  "conditions": [
    {
      "type": "image",
      "uri": "/shared/assets/product.png",
      "role": "reference"
    }
  ],
  "target": {
    "short_edge": 768,
    "aspect_ratio": "9:16",
    "duration_seconds": 15
  },
  "num_inference_steps": 20,
  "output_mode": "decoded_files",
  "output_path": "/shared/h3-outputs",
  "wait": false
}
```

也可以把 `/api/h3/prompt` 的完整 `result` 作为请求体传入。`wait=false` 只返回提交结果；`wait=true` 会等待 H3 任务完成。

## 7. 完整组合工作流

```text
POST /api/context-ir/generate
```

请求体沿用 `/api/h3/prompt` 的四种输入结构，并增加：

```json
{
  "generate_video": false,
  "wait_for_video": false
}
```

- `generate_video=false`：只编译 Prompt，不提交视频；
- `generate_video=true`：编译成功后提交 H3；
- `wait_for_video=true`：等待视频任务结束并返回结果。

响应结构：

```json
{
  "ok": true,
  "result": {
    "schema_version": "context_ir_capabilities.v1",
    "workflow": "context_ir_generate",
    "compile": {},
    "video_generation": null
  }
}
```

## 8. 图片理解

```text
POST /api/understand/image
```

```json
{
  "asset": {
    "asset_id": "image_1",
    "media_type": "image",
    "uri": "/shared/assets/product.png"
  },
  "analysis_directive": {
    "focus": ["product geometry", "material", "visible text"]
  }
}
```

`analysis_directive` 可省略。该接口只理解素材，不生成 H3 Prompt。

## 9. 视频理解

```text
POST /api/understand/video
```

```json
{
  "asset": {
    "asset_id": "video_1",
    "media_type": "video",
    "uri": "/shared/assets/reference.mp4"
  },
  "analysis_directive": {
    "focus": ["actual-time events", "body motion", "camera", "editing"]
  }
}
```

输出包括事件、实际秒数、动作、镜头、剪辑结构和不确定性，不生成 H3 Prompt。

## 10. 音频理解

```text
POST /api/understand/audio
```

```json
{
  "asset": {
    "asset_id": "audio_1",
    "media_type": "audio",
    "uri": "/shared/assets/reference.wav"
  },
  "analysis_directive": {
    "focus": ["speech", "music", "beat", "sound events"]
  }
}
```

当前默认 Qwen3-VL 是视觉模型。未配置音频感知适配器时，服务必须明确返回不支持状态，不会让视觉模型声称听过音频。

## 11. 素材路径与安全要求

- `uri` 必须是 IR 服务能够访问的服务器绝对路径；
- Windows 客户端的 `C:\\...` 路径不能直接被 aigc 容器读取；
- 推荐使用宿主机与容器共享的 `/shared/...` 或项目素材目录；
- `asset_id` 在单次请求内必须唯一；
- `source.assets` 与上游分析或描述中的素材 ID 必须完全对齐；
- API Key 只保存在服务端环境文件中，不应放入请求 JSON；
- Prompt 编译默认不会提交昂贵的视频生成任务。

## 12. 推荐调用方式

```text
用户只有原始素材
→ POST /api/h3/prompt，input_type=assets

用户已经分析完素材
→ POST /api/h3/prompt，input_type=asset_descriptions

上游系统已有标准分析
→ POST /api/h3/prompt，input_type=media_analysis

需要重新渲染已有 IR
→ POST /api/h3/prompt，input_type=context_ir

Prompt 审核通过后生成视频
→ POST /api/h3/videos

需要一站式编译并生成
→ POST /api/context-ir/generate
```
