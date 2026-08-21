# Context-IR 目标与职责边界

## 1. 产品定义

Context-IR 是多素材视频生成任务的结构化编译层。它接收基本明确的用户意图和素材，理解素材中的实体、属性、事件与关系，明确每个素材的使用方法，建立可验证的继承、替换、隔离和连续性约束，最终输出符合 MiniMax-H3 官方规范的提示词与请求。

Context-IR 的核心不是代替上游交互 Agent 完成开放式创意策划，而是把已经基本明确的任务可靠地编译成生成模型可以执行、审计和追踪的规范。

## 2. 核心目标

1. 理解图片与视频素材里有什么。
2. 明确每个素材以及素材内部属性如何参与生成。
3. 将用户要求转换成结构化、可验证的约束。
4. 在授权范围内进行保守且可追踪的补全。
5. 输出符合 H3 官方格式的 prompt 和 generation request。

## 3. 职责范围

### 3.1 素材理解

图片分析应提供：

- 可复用实体及其数量、位置、形状、颜色、材质和纹样；
- 主体、背景、陈列方式和拍摄属性的区分；
- 实体之间的空间或附着关系；
- 字段级证据来源、置信度和不确定性。

视频分析应提供：

- 跨镜头人物、商品、服装、配饰、道具和场景实体；
- 动作、手势、状态变化和时间段；
- 镜头结构、景别、运镜、转场和节奏；
- 跨镜头实体关系和连续性证据。

感知结果只描述素材事实，不自行决定用户想继承或替换什么。

### 3.2 素材使用规划

IR 必须为每个 conditioned asset 建立明确用途，包括：

- `preserve`：必须保持；
- `replace`：必须替换；
- `transfer`：只迁移指定属性；
- `may_change`：允许改变，但默认不强制改变；
- `exclude`：禁止继承或出现。

每条用途必须说明目标、作用范围、优先级、继承属性和排除属性。一个素材可以承担多个独立用途，例如参考视频同时提供人物身份、动作和镜头结构，但背景仅为 `may_change`。

### 3.3 约束编译

IR 应把语义要求展开为生成约束。例如“让人物佩戴商品甲片，人物和动作不改”应落实为：

- 保留人物身份、脸、头发、体型和手部外形；
- 保留身体动作、手势、动作时序和镜头内位置；
- 用商品甲片替换原甲片；
- 商品甲片附着于对应甲床并随手指运动；
- 每根手指的设计跨镜头保持一致；
- 禁止漂浮、错位、互换、变形和原甲片残留；
- 禁止把商品图的背景、陈列布局和拍摄光线带入视频。

### 3.4 H3 输出

编译产物包括：

- `media_analysis.json`：provider-neutral 素材证据；
- `context_ir.json`：结构化中间表示；
- `h3_prompt.txt`：H3 官方格式提示词；
- `h3_prompt_audit.json`：确定性审计；
- `h3_request.json`：H3 请求参数；
- 原始推理响应和运行日志，用于追踪与复现。

## 4. 与上游交互 Agent 的边界

上游 Agent 负责：

- 与用户交互和追问；
- 消除会改变创作结果的重大歧义；
- 确认最终目标和素材大致用途；
- 决定人物、动作、商品、场景和风格的保留或替换范围；
- 标记未解决问题与决策来源。

Context-IR 负责：

- 理解素材证据；
- 将上游决策映射到素材中的具体实体、属性和时间段；
- 建立 bindings、isolation rules、timeline 和 continuity；
- 完成必要的技术性与保守语义补全；
- 检测矛盾、悬空引用和越权扩展；
- 渲染并审计 H3 prompt。

## 5. 统一输入原则

Context-IR 不区分 resolved、partial 或 direct 模式，统一按照以下优先级处理：

1. 用户自然语言中的明确要求；
2. 上游提供的结构化 `directives`；
3. 产品级默认规则；
4. 素材证据支持的保守推断；
5. 必要的技术补全。

明确要求和 directives 不得被 IR 改写、弱化或覆盖。用户没有指定的内容采用最小变化原则进行合理补全，并记录在 `intent.assumptions`。只有要求相互冲突，或者不存在安全的保守解释时，才停止编译并请求澄清。

旧版仅包含 `user_request` 的自然语言请求继续有效；旧版 `resolved_request.v1` 会自动迁移到统一协议。

## 6. 标准输入契约

```json
{
  "schema_version": "context_request.v1",
  "user_request": "用户原始请求",
  "task": {
    "type": "ref2va",
    "duration_seconds": 15,
    "aspect_ratio": "9:16",
    "generate_audio": true
  },
  "assets": [],
  "resolved_request": "可选的上游执行摘要",
  "directives": [
    {
      "directive_id": "d_product_replace",
      "asset_id": "image_1",
      "target": "video_1.performer.fingernails",
      "operation": "replace",
      "scope": ["shape", "color", "pattern", "decoration", "material"],
      "priority": "hard",
      "provenance": "explicit_user"
    }
  ],
  "completion_policy": {
    "technical": true,
    "conservative_semantic": true,
    "creative": false
  }
}
```

`directives` 是可选的。上游能够提供结构化决策时使用；没有 directives 时，IR 直接从用户原话解析明确要求并对遗漏项做保守补全。

`provenance` 使用：`explicit_user`、`confirmed_by_upstream`、`product_default` 或 `ir_completion`。上游决策必须保留来源，IR 新增内容只能标记为 `ir_completion`。

## 7. 补全策略

默认允许：

- 格式、时长、时间线和模型协议补全；
- 将明确要求展开为属性级约束；
- 建立附着、方向、遮挡和跨镜头一致性规则；
- 在 `may_change` 未指定替代方案时保留参考内容；
- 无法从素材确定每指分配时选择一次合理分配并固定。

默认禁止：

- 发明新剧情、人物、场景、商品或卖点；
- 擅自决定是否继承参考人物；
- 把“可以改变”解释为“必须重做”；
- 添加未经请求的品牌、文案、口播或事实性声明；
- 用 IR 推断覆盖用户明确要求或上游 hard directive。

## 8. 成功标准

一次编译只有同时满足以下条件才算成功：

- 所有 conditioned assets 都有明确 relationship 和 usage；
- 所有 hard directives 都被 Context-IR binding 或 constraint 覆盖；
- 所有绑定都有隔离规则；
- 所有事实性素材描述都可追溯到感知证据；
- 时间线连续并与目标时长一致；
- 主要创作目标在必要镜头中可见且可执行；
- 未越过 completion policy；
- H3 prompt 通过确定性格式和引用审计。
