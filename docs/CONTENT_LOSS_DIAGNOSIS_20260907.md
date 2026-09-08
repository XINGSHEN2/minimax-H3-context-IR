# 内容缺失定位：先修规划，不增加审核调用

本轮仅评视觉 Prompt。官方原始 Prompt 为参照，不重新生成官方结果。以下结论来自已完成正式流程输出，不是视频效果结论，也不是“达到官方 80%”的证明。

## Case4：不是 Qwen 没看见，也不是最终渲染删掉

核对版本：`feishu_case4_formal_goal_coverage_20260907`，Case 归档 `output/local_ir_260907_02`。

用户明确说“卖衣服和包”，并要求两者自然融入人物行动。

| 检查层 | 实际证据 | 结论 |
| --- | --- | --- |
| input.json 中 image_3 / entity_1 | components.closure = metallic clasp with circular and vertical bar elements | 圆形和竖条均被识别 |
| 相同实体的 material.surface_type | textured leather-like | 证据是皮革状视觉表面，不是确定材质 |
| `_compact_entity` 压缩 | 搭扣是第 7 个有效属性，材质第 4 个；预算为 16 | 这两条没有被预算截断；扩大预算不能解决本例 |
| context_ir_draft.json | centered metallic clasp and bar detail；textured embossed black leather finish | 草稿已丢圆形，并把视觉近似硬化为材质事实 |
| h3_prompt.txt | 同样使用 metallic clasp and bar / embossed black leather | 最终写作沿用上游缺陷，不是缺失的起点 |
| h3_prompt.txt summary | The creative focus is the handbag | 在用户要求衣服和包的基础上，额外建立了包优先的层级；正文仍写衣服，不能说完全遗漏 |

现有 build_prompt 已经要求保留区别性组件与不确定性。再追加同义规则不是有证据的解决方法。后续应减少规划阶段重复表达同一外观的负担，并验证实体描述是否真正成为各阶段共用的事实来源。不能让最终编辑在锁定 IR 之外偷偷补语义。

## Case3：缺少续展，而非缺少更多切镜

核对版本：`feishu_case3_formal_content_20260907`，Case 归档 `output/local_ir_260907_01`。

用户指定超广角、下方偏右小背影、黑暗门心、湿地倒影、慢推、精确标题与模糊到清晰、最后硬切；同时允许补充未写完整的部分。

本地全部保留上述主要视觉要求，但 8–15 秒是静止中远景背影，与开场相比主要只改变景别。人物外观更可读是有效信息，却不足以自动支撑“节奏紧凑”的七秒停留。不能简单套用每镜时长上限，也不能强加更多镜头。

原始官方第二镜改为侧面近景、重心变化和迈步，人物表演推进更强；但其 summary 写 glowing darkness，与黑暗门心存在潜在冲突，且更完整地继承图1环境。不能整段照搬官方。

Qwen 的 coat 属性写 double-breasted front with buttons (not clearly visible)，本地主体直接写 double-breasted。这里只能证明限定语没有保留，不能据此断言真实衣服一定不是双排扣。

## 下一次实验应检验什么

1. 固定同一份素材分析，以隔离规划变化；这轮没有理由重跑 Qwen。
2. 在 IR 规划阶段解决主体事实和缺失续展，不添加后置独立语义审核或格式重试。
3. Case4 检查圆形＋竖条、皮革状表面、服装和包的共同目标，以及原有取包→目光交流→持包离开是否仍完整。
4. Case3 检查指定开场不被改动，后续有适量新信息，而非强制新增剧情；不把看不清的服装细节升级为事实。
5. 同时回归另一类成功案例，避免为这两个案例定制全局规则。每次结果写到对应 Case 下的新 local_ir 版本目录。

这份记录是离线质量定位，不是新增生产审核层。当前证据支持“部分内容损失发生在 IR 草稿阶段”，不支持“Qwen 能力不够”“所有问题由截断造成”或“已稳定达到目标”。
