# v20 API

## 编译提示词

`POST /api/h3/prompt`：

```json
{
  "input_type": "assets",
  "source": {
    "schema_version": "context_request.v1",
    "user_request": "生成一支五秒产品展示短片",
    "task": {"type": "ref2va", "duration_seconds": 5, "aspect_ratio": "16:9"},
    "assets": [{"asset_id": "image_1", "media_type": "image", "uri": "/shared/product.png"}]
  }
}
```

input_type 必须显式选择：

| 类型 | 额外字段 | 素材理解 |
|---|---|---|
| assets | source.assets | 调用感知服务 |
| asset_descriptions | asset_descriptions 数组，每项 asset_id、description；省略 source.assets 时还须 media_type、uri | 规范化调用方描述 |
| media_analysis | media_analysis.v2 对象，asset_id 与 source.assets 完全匹配 | 复用分析 |

后两种类型可传 `intent_resolved: true`，同时 source.resolved_request 必须非空，否则仍执行意图解析。三种输入都调用同一个 v20 编译器。旧 context_ir 输入已移除。

HTTP 成功响应为 {ok: true, result: ...}；result 的 schema_version=h3_prompt_generate.v1，包含 media_analysis、context_ir（h3_compilation.light.v1）、h3_prompt、h3_prompt_audit、h3_request、stage_timings 和带来源／哈希的 artifacts。ready_for_review 代表格式通过，semantic_quality_verified 恒为 false。

## 组合与视频

- `POST /api/context-ir/generate`：组合能力，默认仅编译。只有显式 generate_video=true 才提交视频；wait_for_video 控制等待。
- `POST /api/h3/videos`：提交 H3 请求或包含 h3_request 的编译结果；视频服务独立于提示词生成。
- 可选理解接口：`POST /api/understand/image`、`/video`、`/audio`。音频不受支持时明确记录证据限制。
- `GET /api/health`、`GET /api/capabilities`：服务与能力信息。
- Web 工作台继续使用 `/api/jobs` 异步任务接口、上传及产物下载接口。

任务支持 t2va、ref2va、i2va、l2va、fl2va。关键帧任务需要显式 image asset.frame_index：首帧 0、尾帧 -1；不会从模型生成的文字推断关键帧位置。
