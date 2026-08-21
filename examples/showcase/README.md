# Context-IR 视频对比展示

页面把每个案例的 `Raw / 本地 IR / 官方 IR` 三种结果并排展示，支持“模糊需求 / 详细需求”切换和同步播放。

从仓库根目录更新案例：

```bash
python3 scripts/build_examples_showcase.py /home/mx/shenxing/context-ir-ab-tests-20260820 examples/showcase
```

构建器只收集用户 Prompt、H3 Prompt、Context-IR、请求参数和最终 MP4。尚未生成的视频会显示为“缺失”，生成完成后再次构建即可补齐。

启动浏览：

```bash
python3 -m http.server 38081
```

访问 `http://<服务器地址>:38081/examples/showcase/`。若推送展示视频到 GitHub，建议使用 Git LFS 管理 `examples/showcase/data/**/*.mp4`。
