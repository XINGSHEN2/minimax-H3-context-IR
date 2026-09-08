# 静态素材与目标动作权限的边界

真实原因位于 Case3 旧正式 IR：completion_authority.story_continuation=true，但 production_policies.motion.allow_new_events=false，并以“Still images cannot supply motion, so the protagonist's stillness is the conservative baseline”禁止 Shot1 和 Shot2 人物动作。素材不可提供已观察动作，是事实来源限制，不是目标动作禁令。

已在 backend/agent.py 同一静态素材规则处澄清：动作由用户及补全权限决定；指定静止只保持其对应镜头范围；授权续展允许同一主体的小动作或信息揭示，标记为补全而非观察事实。没有更改用户请求，没有强制走进门、转脸或固定镜数。

89 项相关测试通过，仅证明指令契约和相关回归。

固定输入实验已启动：

- Case：1.1 品牌大片与影视内容/case3-ref2va
- 输入基线：output/local_ir_260907_01
- 新输出：output/local_ir_260907_02_continuation_replay
- 运行句柄：86016
- 意图解析与 Qwen 分析复用，运行类型为 controlled_internal_stage_replay。

写此记录时正在规划，未完成。后续查询该原句柄，不重复提交。评估需确认超广角、小背影下方偏右、黑暗门心、湿地倒影、慢推、精确标题与字体、模糊渐清晰、硬切等开场约束仍完整；后续新信息要服务原氛围与紧凑节奏，而非添加无关剧情。

## 草稿阶段的反证

已收到 context_ir_draft.json：只规划一个 0–15 秒镜头，标题约 9.5 秒才出现、10.2 秒变清晰，末尾写 then cut hard。motion.allow_new_events=true 但只生成头发衣料微动。没有真正的续展，也没有解决紧凑节奏，相比旧版两镜不应算进步。

最终写作尚在运行；不能拿新增规则和单元测试来证明此目标已解决。后续须区分“用户允许补全”与“规划真的给补全留了时间”，以及片尾 hard cut 是否只是不可见的出口。当前不要重跑同一任务。

更新：该任务已正常结束，408.834 秒。最终 Prompt 仍为单镜 15 秒，9.5 秒标题开始出现，10.2 秒变清晰。该版本不作为续展质量提升的证据，原句柄 86016 已关闭。

## 简化规划对照（不切换正式 API）

由于追加规则未解决此案例，新增实验模块 backend/compact_planner.py，通过 replay_visual_planning.py --compact-planner 只替换该进程的规划指令。仍使用同一 DeepSeek、相同输入、相同 IR schema、编译和最终写作；无新增审核。正式 API 不引用该模块。

新实验：Case3/output/local_ir_260907_03_compact_planner_experiment；输入仍为 local_ir_260907_01 的已解析需求与分析；句柄 99039；写此更新时正在规划。实验 manifest 标明 compact_experimental 并记录额外模块哈希。语法检查通过，尚无生成质量结论。

## 并行的另一项独立实验

Case4 在后续代码版本增加了局部不确定性规则：不确定哪一面有组件，不等于组件形状不确定；视觉材质限定应在主体、绑定与约束中一致。51 项相关测试通过。

运行句柄 44253；Case4 的 output/local_ir_260907_05_local_uncertainty_replay；固定输入基线 output/local_ir_260907_04_joint_focus。它在本记录更新时仍运行。Case3 启动较早，未加载这一处修改。两个实验均保存各自代码/输入哈希。
