# 1012TEST 新增4条：真实AI提示闭环

判定：真实模型强报警回复进入Unity、接收器接受显示状态并撤销已有证据。用户也目视看到了独立横幅，支持至少一次真实视觉显示；不能将这次目视归到每个run。仍不是性能验收通过，也不是断流等所有场景已通过。

## 精确归属

| session ID | run ID | 终端结果 | Unity ACTIVE片段数 |
|---|---|---|---:|
| session_20261012_101911_080981 | baf20b87408d4ef7b9195e3f55a1c7d7 | calibration_completed | 4 |
| session_20261012_101940_356172 | 923614ec5f6e4626b91779bb6c7c51d9 | calibration_completed | 0 |
| session_20261012_102000_453011 | 48febfab66de4e2b9ff75d49ae99835c | edge_exit，第1层 | 1 |
| session_20261012_102014_820513 | 0a8d375d04a44075a614d7ea1b3e7a23 | edge_exit，第1层 | 1 |

全部为难度3、选定三层。4个run共4,046行Unity输入，seq从1到N连续；geometry query/ownership有效且身份错配0。主代理以本地JSONL和CSV独立匹配4份终端包的sequence/outcome：1552/1018/507/969，对应终端均已落盘。三个前run有结束后restart_requested，新run身份独立；没有在所匹配日志中观察到旧run ACTIVE进入新run。未刻意注入迟到包或在报警中Restart，不能将普通顺序运行升级为完整故障验收。

## 真实显示状态和撤销

以Editor.log中的单行[ExperimentalModelWarning]按run_id精确关联。RECEIVED原始状态在revoke_reason字段；ACTIVE更新不是新的片段，首次ACTIVE至REVOKED合并为一个片段。

- 101911：4个片段，分别约0.456、0.433、0.185、0.302秒，均因backend_safe退出。
- 101940：只有SAFE/UNKNOWN接收，没有ACTIVE。
- 102000：1个片段约0.064秒，随后backend_safe退出。
- 102014：1个片段约0.274秒，随后backend_unknown退出。

合计6个片段、29次ACTIVE日志更新。上述时长是接收器本地单调时钟的ACTIVE→REVOKED时长，不是录像逐帧可见时间或坠出提前量。SAFE退出也不能直接证明玩家已完成物理恢复，必须结合具体轨迹。

最后run的重要回归证据：prediction_sequence=173先为STRONG/confirmed，随后保持173收到UNKNOWN/nonpositive_clearance，接收器REVOKED/backend_unknown。这证明同预测序号撤警已在真实链路生效。UNKNOWN收到时间2321.761242、撤销时间2321.766522，差约5.28ms，只是该次本地接收至撤销处理差，不是端到端延迟。

nonpositive_clearance表示模型当前几何净空不满足有效预测条件，不表示风险消失或成功回正。该提示退出时仍应保留原游戏危险判断和原黄色规则。模型不自动控制球。

正式场景enableExperimentalModelWarning现保存为1，与上一批保存为0及无实验日志不同。本轮用户已目视见独立横幅，日志也有真实RECEIVED STRONG、ACTIVE、REVOKED，因此不再仅是离线重放/合成测试。

## 仍需做什么

1. 一次强报警显示期间停止后端的实测，确认过期自动撤警；若停止前已SAFE撤警则不算这项通过。重启后端后必须新建Unity run。
2. 一次明确靠边后回正的轨迹/日志对照，确认撤警时已出现真实恢复，而非只是风险分数下降。可结合已有101911轨迹优先审查，不必泛泛补采。
3. 模型后续评价必须保留最终坠出误报口径。本轮完成run也有强报警，不能改称成功干预来提高F1。
4. 当前有约64ms的短报警片段，后续应评估闪烁/有效可见性；本次不增加最短保持时间，不借保持制造提前量改善。

GPT-6 Luna做重复提取，主代理核对Editor.log强报警/撤警单行、同seq173回归、场景开关、CSV/JSONL终端归属与4CSV哈希。数据只读；未改Unity、后端、模型或阈值。

来源：accept1012_live_luna/summary.json（含稳定Editor.log快照SHA及4CSV快照）；原始12个1012TEST session均保留，前8条和后4条验收证据分开，不混算。
