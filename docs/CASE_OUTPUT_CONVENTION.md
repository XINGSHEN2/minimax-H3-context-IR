# Case结果组织约定

用户要求：以后每次不同版本的本地IR提示词直接写入对应素材Case下，不再另建脱离Case的实验输出集合。

```text
caseN-ref2va/
  assets/
  output/
    raw/                         # 保留已有原始对照
    official_ir/                 # 唯一官方结果，只读复用
    local_ir_260907_01/           # 每次生成新版本，禁止覆盖
      h3_prompt.txt
      context_ir.json
      media_analysis.json
      h3_request.json
      stage_timings.json
      result_manifest.json
      h3_outputs/                # 可选；只放使用本版Prompt生成的视频
```

- 使用日期加序号区分同日版本；不把较晚Prompt覆盖进已生成视频的版本目录。
- 从Prompt到视频全过程沿用同一版本目录；仅生成Prompt时不制造空视频或伪造完成状态。
- result_manifest记录实际Prompt来源/哈希、代码版本或文件哈希、模型、是否复用分析、任务ID与状态。
- 官方Prompt及视频只引用原始output/official_ir，不生成official_ir_新版本，也不重复调用官方。
- 服务通用API仍接受调用方指定output_dir；本项目Case测试调用方必须明确传入对应Case版本路径。
- 不把厨房动作迁移样本标成飞书1.1的Case2；编号必须按真实Case路径区分。
- 旧版本保留，除非用户明确批准清理。各阶段文件可放版本目录的logs/或diagnostics/，不散落仓库根目录。

## 本轮重复官方结果已清理

aigc-2的三份重复官方运行目录和两份official_ir_260907归档已移出Case目录，原有official_ir共40个文件哈希未变。
可恢复目录：`/mnt/customer-fs/shenxing/minimax-H3-data/.trash/duplicate-official-260907`。
本地四个重复官方视频/联系表也移至本审阅目录的`.trash/duplicate-official-260907`。
