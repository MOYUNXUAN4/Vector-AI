# 核查来源与准确路径

以下相对路径以 `C:/Users/QIYUXUAN/Desktop/fyp_Backend (3)/fyp_Backend` 为根：

## 模型

- `telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/主审结论.md`：最新主审结果、评价修正、未通过完整目标。
- `telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/PROTOCOL.md`：单因素范围与因果/校准约束。
- `telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/runner/run_cop_single_factor.py`：最新 corrected runner。
- `telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/baseline_fixed/`：当前基准 config、selected_thresholds、OOF 输出；不是部署包。
- `telemetry_logs/DEV_MATCHED_A/analysis_20261009/数据增量受控实验主审结论.md`：加入数据未升级。
- `telemetry_logs/TEST1009/training_20261009/matched_early_signal_20261009/主审结论与采集安排.md`：已有匹配信号工作，不重新泛采。
- `telemetry_logs/TEST1009/training_20261009/episode70_audit_20261009/主审结论.md`：70 个报警的证据限制。
- `telemetry_logs/1009TEST/acceptance_20261009/主审结论与下一步.md`：7 条功能测试；不是训练数据。

## 后端（本次只读核查）

- `UDPRecevier.py`：5005 接收、5006 回包；实时输入/难度路径尚无模型输出。
- `udp_packet_reader.py`：大包接收及解析日志；不要回退已修复的接收长度。
- `timesync_logger.py`：字段落盘支持不等于每个实时 packet 都具有有效字段。
- `telemetry_logs/independent_TEST1006_20261006/freeze/frozen_model.joblib`：历史开发 freeze，仅作来源参考，不加载为最新模型。

## Unity（不同根）

根：`C:/Users/QIYUXUAN/Desktop/Endless-Driver-Tutorial - EP9/Endless-Driver-Tutorial - EP9`

- `Assets/BackEnd/UDPManager.cs`：5005 发包、Unity 自有 attention/黄色 telemetry。
- `Assets/Endness Falling/Scripts/UdpFrontendReceiver.cs`：5006 接收，仅处理 realtime/ai_report；当前无模型提示。
- `Assets/Endness Falling/Scripts/UIManager.cs`：现有 telemetry HUD。

本次核查日期 2026-10-10；跨会话接手时重新确认文件状态。报告中没有补全旧日志无法证明的物理接触真值。
