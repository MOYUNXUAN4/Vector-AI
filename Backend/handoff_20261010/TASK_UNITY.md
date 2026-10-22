# 给 Unity agent 的任务（先核查，不立即改）

实际项目根：`C:/Users/QIYUXUAN/Desktop/Endless-Driver-Tutorial - EP9/Endless-Driver-Tutorial - EP9`。

先读 START_HERE.md 与 INTERFACE_DRAFT.md。只读确认 `Assets/Endness Falling/Scripts/UdpFrontendReceiver.cs` 与 `UIManager.cs` 的接收/显示调用链、场景引用与当前旧黄色。返回最小接入方案，主代理确认接口后才写代码。不要又做几何诊断重构。

允许的未来范围：在现有 realtime packet 增加嵌套 model_warning 接收，独立默认关闭的实验显示；必要时增加一个小组件。优先不改场景、不改 UDPManager。禁止修改输入、COP 控制、灵敏度、难度、Rigidbody、平台、死亡/换层 predicate、原黄色阈值。

重点：现有接收器一个 pendingJsonData 槽，独立 warning 包可能覆盖输入包。不能另开同一监听端口或改变输入发送节奏；按确认接口附加字段。Unity API 只在主线程执行。

模拟验收：无新字段保持旧行为；禁用显示；UNKNOWN 不冒充安全；旧 run/乱序/平台失配包忽略；断流清实验提示；Restart/换层/结束清状态；原黄色始终保留。编译成功不等于 Play Mode 实测完成。

代码需要独立 worktree，保留当前用户改动，别从远端旧版本不加核对地接入。若无法包含当前诊断修改，先报告隔离方式，禁止 reset/clean。写代码前给文件范围，最终给真实测试日志与未验证项。
