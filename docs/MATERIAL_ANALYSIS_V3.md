# 素材分析 v3

## 流程
用户原始需求和素材 ID → 后端校验 → 图片一起交给 Qwen 3.8；每个视频及其音轨、每个独立音频交给 Omni Instruct → 校验和合并 → media_analysis.v3 → 现有提示词编写阶段。

素材分析前不调用 DeepSeek。后续提示词编写仍用已配置的文本模型。

## 提示词在哪里
- `backend/perception_prompts.py`：共同要求、图片要求、视频和音频要求、重试要求。
- `backend/perception.py` 的 `response_shape`：JSON 字段示例及 COMPACT_FORMAT 数组字段说明。模型返回短数组，后端 expand_compact 展开成完整 v3 对象。运行时附加用户原话、素材清单和 ffprobe 实测时长。
- 每次调用的完整提示词保存在任务目录 `perception/request_XX/request_N.json`。原始回答在 `response_N.json`。

## 返回字段
- `assets`：每份输入素材一项，ID 与输入一致。
- `visual`：主体、外观、关系、事件、可见文字。
- `audio`：音轨来源、逐句对白、音乐和其他声音。
- `audio_visual_links`：一个声音片段与一个视觉事件的关联。
- `cross_asset_relations`：共同分析的图片之间的关系；不自动判断图片人物是否出现在视频中。
- `uncertainties`：具体不确定的内容。

每个实体、事件和声音片段的 ID 都加素材 ID 前缀，避免混淆。
视频音轨标为 `视频ID:audio`，source_asset_id 指向原视频，不额外生成上传文件。
独立音频和视频音轨按 reference_registry 分配 Audio 编号；后续 bindings 可使用真实输入素材 ID 或已登记的内嵌音轨 ID。编译器会核对原视频、音轨来源和有声音轨状态；H3 请求仍只提交原始输入文件。

## 时间与失败处理
- time_range 使用源素材秒数。合法范围内仍只是 model_estimate，不保证准确对齐。
- 未知时间为 null；越界或非法时间也变成 null，保留 rejected_time_range 和 timing_warning，不裁成一个看似正确的时间。
- JSON 或引用错误最多重试一次。仍失败则停止本次分析，不把缺失素材当作成功。
- 仅修复字段名前重复引号这一格式问题，记录 format_repair 文件；不改模型观察值。
- v3 暂不使用缓存，避免修改提示词后仍读取旧结果。

## 当前服务限制
图片一次最多 8 张，超出直接说明错误，不悄悄拆组。Omni 每份音视频最多 30 秒，调用前测量时长并确认是否存在音轨。
默认图片地址 http://10.42.1.1:9012，Omni 地址 http://10.42.1.1:9013。
用 QWEN_IMAGE_UNDERSTAND_BASE_URL、QWEN_IMAGE_MODEL、QWEN_OMNI_BASE_URL、QWEN_OMNI_MODEL 覆盖；请求 perception_provider.options 可覆盖相应 image_base_url/image_model/omni_base_url/omni_model。
旧 video_base_url、单图分析开关和 v2 缓存不参与 v3 路由。

## 兼容与边界
显式传入的旧 media_analysis.v2 仍可复用；它不代表做过声音分析。media_analysis.v3 可通过 media_analysis 输入或 --perception-from 复用。
没有修改生成模型、部署服务或自动提交视频生成任务。
