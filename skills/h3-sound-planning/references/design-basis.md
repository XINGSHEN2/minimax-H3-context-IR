# 设计依据

本文件用于维护和评估 `h3-sound-planning`，不属于普通生成所需上下文。

## 官方 IR 样本

对 `/home/xingshen/minimax-H3-data/minimax-H3-feishu-cases` 中 57 个官方 IR 的两个音频板块进行统计：

- 57/57 填写 `overall_soundscape`；
- 21/57 将 `non_diegetic_music` 设为 `N/A`；
- 47/57 建立环境或场所底层；
- 40/57 把声音与动作、切点或视觉变化建立关系；
- 36/57 使用清晰瞬态；
- 26/57 描述动态弧；
- 26/57 说明混音主次；
- 14/57 明确描述远近、回声或混响等空间关系。

因此优先级应是可见因果、时间同步和听觉主次，其次才是空间修饰。官方案例还显示：未明确要求音乐时仍需判断其功能；存在对白、真实环境、参考原声或足够强的动作声时，`N/A` 是正常结果。

## 开源资料取舍

- [MiniMax-H3-Prompt-AgentSkill](https://github.com/benjiyaya/Minimax-H3-Prompt-AgentSkill)：采用环境、物理动作、画外配乐、剧情内音乐与对白的基础边界；未采用固定镜头数量、每镜单动作和每镜必须运镜等会改变本项目视觉规划的规则。
- [Sound Design (Murch Method)](https://github.com/roohe/agentic-super-skills/blob/master/skills_library/sound-design-film/SKILL.md)：采用主要听觉重心、关键叙事声优先、音乐为主声部让位、普通时刻控制可辨识层数等原则；未采用面向后期制作的响度、设备和插件流程。
- [seedance2-skill](https://github.com/dexhunter/seedance2-skill)：采用参考音频必须分配明确用途、音乐节拍只在用户要求或证据支持时驱动画面关系的原则；未采用其模型专属的素材数量、时长和输出语法。

这些资料只提供可迁移的决策原则。H3 字段、参考标签、视觉锁定和输出契约仍以本仓库的 H3 Skills 与测试为准。
