# 给后端 agent 的任务

先读 START_HERE.md 与 INTERFACE_DRAFT.md。核心目标是在线/离线特征一致及可测试的预警链路，不自行决定模型参数。

第一阶段：只在新目录 `parallel_20261012/backend/` 实现独立纯函数组件与测试；不改 UDPRecevier.py、timesync_logger.py 或运行服务。后端不是 Git 仓库，不能假设 worktree 可用。主循环最小集成需主代理另行审核。

交付：有界、按 run/platform/layer 分段的历史缓冲；与指定 offline runner 相同的因果特征/预处理适配器；可插拔 mock predictor；状态重置/有效性处理；提议的附加 model_warning 对象。协议未固定处使用显式配置或待复核，不猜时间单位、COP 映射或阈值。模型未冻结，不加载历史 joblib 充当最新版本。

验收测试：未来包不可进入过去特征；旧 run/跨平台历史拒绝；Wii stale/缺失/几何无效输出 UNKNOWN；Restart、终端、calibration 重置；乱序/重复序列明确处理；JSON 无 NaN；旧 realtime 字段语义不变。完整 feature parity 测试必须与训练构造逐行对照，缺证据不能声称通过。

当前普通控制使用 latest Wii fallback，不带新鲜度检查。模型独立拒绝过期值，不改输入控制。所有重采样必须因果，不能复制离线含未来插值的构造到实时推理。

返回：新文件列表、执行命令/测试数、未完成 parity 项、主循环后续最小 diff 提案。不要启动监听器、装载生产模型、修改 CSV schema、改标签或开启提示。
