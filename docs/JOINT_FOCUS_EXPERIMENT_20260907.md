# 联合目标规划实验

## 已修改

服务器 backend/agent.py 的 build_prompt 两条指令：移除“唯一主要结果主体”和“剩余细节给主要主体”的要求，改为单个 primary_subject_id 仅作为注册表锚点；叙事或商业主次继续由用户意图及 subject_priority 决定。稳定外观只在主体定义形成，绑定描述控制维度，镜头描述可见性和变化。

不新增字段、LLM 调用、审核、Qwen 重分析或服务重启。官方结果不重新生成。仅 fresh runner 使用新代码，不能据此声明常驻 HTTP 进程已更新。

## 验证

51 项相关测试通过，仅证明指令契约和相关代码回归，不证明生成质量。

两项正式接口实验已启动，复用原有分析以隔离规划变量：

- Case4：output/local_ir_260907_04_joint_focus；本地等待句柄 30445。
- Case5：output/local_ir_260907_02_joint_focus_regression；本地等待句柄 85653。

案例根目录：/home/mx/shenxing/minimax-H3-data/minimax-H3-feishu-cases/1.商用级多场景生成/1.1 品牌大片与影视内容/，对应 case4-ref2va、case5-ref2va。

两项均已完成，原等待句柄已正常退出，不需要再次提交。

## 完成结果

| 案例 | 意图解析 | IR规划 | 最终写作 | 总计 |
| --- | ---: | ---: | ---: | ---: |
| Case4 | 181.997s | 358.087s | 173.304s | 713.547s |
| Case5 | 234.862s | 294.368s | 122.951s | 652.370s |

素材分析为复用，本轮不代表包含全新 Qwen 分析的端到端耗时。

Case4：summary 不再把包指定为唯一重点，服装与包均融入动作；裙长、袖长、发型仍保留，末尾卡片也没有继续加胶片颗粒。但搭扣退化为 metallic closure，圆形＋竖条仍丢失；leather-like 仍成为 leather。连续三个 slow small-amplitude push-in 也说明镜头多样性未改善。只能说联合目标表述得到一次正向样本，不能说整体质量全面提高。

Case5：单个人物与图2身份来源保留，服装、火场、反光、白闪、扫描线等核心视觉元素完整。但是可选加入图1的 BROADCAST INTERRUPTION / V / 27 文本，虽然来自 OCR 且标记可选，并非凭空编造，却超过用户明确授予的氛围/质感范围。旧版不引入这些文字更保守。这是来源使用范围的退步，不能被 passed=true 掩盖。

## 随后发现并修复的代码矛盾

backend/context_ir.py 的草稿 renderer 原来无条件把 primary_subject_id 写成唯一 primary creative focus，即使 semantic_plan.subject_priority=co_equal。审核又会报该表述冲突。

现已改成：真实注册的多个 co_equal subject 标签共享 creative focus；其他模式保留原单重点行为。新增实际渲染/审核回归测试，联合相关测试共 133 项通过。

上述两项模型实验启动早于 renderer 修复，未加载这一处新代码，不作为其在线验证。下一次应复用原 IR 离线检查确定性渲染变化，不必为验证这处代码再跑 Qwen/完整 LLM 链。

后续真实输入离线验证已完成：读取 `feishu_action_formal_content_20260907/context_ir.json`，该文件原本声明男女两人为 co_equal。新 renderer 输出 `<Subject 1>, <Subject 2> share the creative focus`，保留递盘、右手甩泡沫、受惊反击和互相闪躲的原始 objective；输入 IR 深比较完全不变，Prompt contract audit 无问题。此验证不调用模型、不生成视频、不覆盖原 Prompt。脚本为 `check_real_joint_render.py`。

这证明确定性渲染尊重真实共同重点 IR，但不能证明 LLM 每次都正确决定共同重点。后者仍需语义输出评估。

## 人工内容检查

Case4：衣服和包不被锚点字段强行分出主次；圆形＋竖条、皮革状表面、服装袖长与轮廓仍保留；取包、目光交流、持包离开完整；不能以增加电商特写违反自然融入要求。

Case5：人物来源仍只来自授权人物图，氛围图不污染身份；原有服装、火焰与故障视觉效果不减少，且不增加未经要求的文字或车辆。它用于检查联合目标修改是否错误地把真正的单主体广告变成多主体。

不设置程序关键词门槛或自动重试。Case3 的后半段推进暂未修改，本轮不把它计为解决。
