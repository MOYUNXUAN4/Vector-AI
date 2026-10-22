# SOURCES.md 只读核查报告（2026-10-10 20:46）

核查人：WorkBuddy agent（只读，未修改任何运行代码、数据或模型）

## 1. 路径存在性

后端根 `C:/Users/QIYUXUAN/Desktop/fyp_Backend (3)/fyp_Backend`，以下全部存在：

- telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/主审结论.md ✓
- telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/PROTOCOL.md ✓
- telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/runner/run_cop_single_factor.py ✓
- telemetry_logs/TEST1009/training_20261009/cop_single_factor_20261009/baseline_fixed/ ✓（含 config.json、selected_thresholds.json、inner/outer_oof_predictions.csv、metrics.json、summary.json 等，mtime 2026-10-09 15:44）
- telemetry_logs/DEV_MATCHED_A/analysis_20261009/数据增量受控实验主审结论.md ✓
- telemetry_logs/TEST1009/training_20261009/matched_early_signal_20261009/主审结论与采集安排.md ✓
- telemetry_logs/TEST1009/training_20261009/episode70_audit_20261009/主审结论.md ✓
- telemetry_logs/1009TEST/acceptance_20261009/主审结论与下一步.md ✓
- UDPRecevier.py / udp_packet_reader.py / timesync_logger.py ✓
- telemetry_logs/independent_TEST1006_20261006/freeze/frozen_model.joblib ✓（历史 freeze，2026-10-06）

Unity 根 `C:/Users/QIYUXUAN/Desktop/Endless-Driver-Tutorial - EP9/Endless-Driver-Tutorial - EP9`：

- Assets/BackEnd/UDPManager.cs ✓
- Assets/Endness Falling/Scripts/UdpFrontendReceiver.cs ✓
- Assets/Endness Falling/Scripts/UIManager.cs ✓

## 2. 状态一致性（文档 vs 实际文件）

| 声明 | 核查结果 |
|---|---|
| UDPRecevier 监听 5005 / 回发 5006 | ✓（源码 18-19 行） |
| baseline_fixed 强报警 Recall 10/10 | ✓ metrics.json strong_lgb_cohort_TEST1009: hits=10/10 |
| 保守几何 ≥0.4s 覆盖 6/10 | ✓ guaranteed_early_sessions=6/10 |
| 完成组报警率 16/20、平均 1.302 秒 | ✓ completed_alarm_count=16/20，1.3020 s |
| F1 55.6% | ✓ 由 TP10/FP16 复算 precision=38.46%、F1=55.56% |
| TTE：F1 57.1%、覆盖 0/10、报警率 15/20（75%）、0.5655 秒 | ✓ 与主审结论.md 一致 |
| 主审结论：COP 速度候选无实质改善（1.302→1.29875 s），不升级 | ✓ 一致 |
| Unity 接收器单一 pendingJsonData 槽 | ✓（出现 5 处） |
| Unity 仅处理 realtime/ai_report，无 model_warning | ✓ 无 model_warning 字样 |
| UDPManager 发往 5005、自有 attention telemetry | ✓（sendPort=5005，attention 字段存在） |
| parallel_20261012/ 尚未创建 | ✓ 不存在（符合交接包"尚未开始"状态） |
| OOF 输出存在但无最终部署 refit/export | ✓ baseline_fixed 只有 OOF 与 selected_thresholds，无部署包 |

## 3. 待复核项（不影响接手，但需主代理知悉）

1. `frozen_model.joblib`（2026-10-06）确认为历史开发 freeze；已核实最新基准是 baseline_fixed，与 SOURCES.md 警告一致，不得加载旧 joblib。
2. baseline_fixed/metrics.json 中 attention 口径的 guaranteed_04_risk_coverage=14/22，与主审结论"评价修正后 14/22"一致；旧 helper 的 10/22 差异已在独立审计中，本核查未发现矛盾。
3. START_HERE.md 表格的 TTE 报警率写作 15/20，主审结论写作 75%——同值不同表述，非矛盾。
4. 本报告为文件级核查；未重放 OOF 预测或复核 16 项合成检查（主审称主代理已另行复算）。

## 4. 结论

交接包描述的路径、基准数字与链路现状**全部与磁盘实际状态一致**，可以据此进入三条任务线的第一阶段。
