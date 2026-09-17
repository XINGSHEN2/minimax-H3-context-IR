# v20 脚本

- `smoke_test.sh`：语法检查和全部自动测试，不调用真实模型。
- `web_smoke_test.sh`：本地临时 Web 服务的静态页面和健康接口检查。
- `verify_context_ir_services.py [env文件]`：读取与 v20 相同配置，只检查 TCP 连通性及密钥是否存在，不发送素材或模型请求。
- `build_examples_showcase.py`：维护现有案例对比页面，独立于编译流程。
- `run_ab_suite.py`：使用当前 CLI 进行案例 A/B 编译，复用详细版的素材分析；运行会调用模型并更新指定案例目录。
- `run_local_ir_h3_480.py`：显式生成已有 Prompt 的 H3 视频，含部署环境专用文件暂存逻辑；不是 Prompt 编译的隐式步骤。

历史旧 IR／导演实验脚本已移除，旧结果和 Git 历史保留。通常使用根目录 agent.py 或公开 API 运行新案例。
