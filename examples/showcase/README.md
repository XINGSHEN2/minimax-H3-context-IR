# Context-IR 视频对比展示

GitHub Pages 当前展示 Feishu 1.1、2.2、3.1、3.2 和 3.4 案例。每个案例并排展示 Raw、本地 IR 和官方 IR 视频。

案例配置保存在 `cases.json`，素材和生成结果保存在 `data/`。更新页面时，请同步检查配置中的所有文件路径；不要运行旧的 A/B Test 构建脚本覆盖当前清单。

本地预览可从仓库根目录运行：

```bash
python3 -m http.server 38081
```

然后访问 `http://<服务器地址>:38081/examples/showcase/`。向 `main` 推送 `examples/showcase/` 下的改动会触发 GitHub Pages 工作流。
