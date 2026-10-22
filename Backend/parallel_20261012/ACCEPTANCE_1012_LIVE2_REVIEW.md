# 1012TEST 新增3条：报警中Restart实测

只读审计，不重训、不调阈值、不修改Unity或后端。Luna负责CSV与Editor.log重复提取；主代理独立匹配本地JSONL的生命周期/终端证据，并检查实际日志单行及撤销原因。

| session ID | 结果 | ACTIVE连续片段 | 撤销原因 |
|---|---|---:|---|
| session_20261012_103349_663622 | 第3层edge_exit | 2 | 两段backend_unknown，前一RECEIVED原因nonpositive_clearance |
| session_20261012_103420_415741 | 运行中Restart | 2 | 第一段backend_safe/raw_off；第二段restart |
| session_20261012_103433_164318 | 三层完成calibration_completed | 4 | 均backend_safe/raw_off |

合计8段，51次ACTIVE日志更新。更新次数不能当独立报警次数。

103349的两段本地ACTIVE→REVOKED约0.386秒与0.0285秒；103420约0.183与1.823秒；103433约0.133、0.113、0.139、0.185秒。时长是接收器单调计时，不是录屏逐帧可见时间或事件提前量。

## 本轮新通过项

103420第二段持续报警中明确REVOKED/restart，随后有新的run。JSONL同run记录restart_aborted、detail=active_run_restart_request_no_terminal_outcome、sequence=694；CSV因此保留末态running和空outcome。不是结束包丢失，也不能标为正常/坠出。

旧run ID 9cfbf4a61f564ee089b9a40d51060e24，新run ID b7d24afc4d534cb6ba846eed7aadc70f。旧提示在Restart先撤销，新run随后独立接收和触发自己的报警。正常顺序重启未观察到旧提示残留；没有刻意注入延迟旧包，因此不宣称完成所有乱序故障实测。

两个真正终端run的Unity本地terminal packet seq与CSV最后Unity seq一致：103349=1566、outcome=edge_exit、layer=3；103433=1506、outcome=calibration_completed、terminal层计数4。结束包真实落盘，普通换层before/after各两组。

## 撤警解释

103349是净空非正导致UNKNOWN，不表示恢复；103420和103433的SAFE撤警对应raw_off，即概率不再满足报警条件。附近日志可以有joint_recovery SAFE，但不是这些ACTIVE片段的即时撤销原因，因此不能把本轮SAFE退出统称为真实回正撤警。若要评价恢复，需要对齐球持续向内/净空回升的运动片段。

## 未通过/尚无证据项

匹配这3个run的日志没有REVOKED/prediction_age_exceeded_0_3s。因此不能认为完成了停止后端后的断流超时验收。游戏Restart和后端停机不是同一种事件。

下一项仅补一次：真实横幅显示时停止master后端（后端终端Ctrl+C，不是Unity Restart），检查过期撤警。若在停止前已SAFE退出，或游戏结束先清理提示，则记录实际原因，不冒充超时分支通过。重启后端后开启新的Unity run，不在原run直接恢复计数。

不需要重做整批或继续用功能样本调参。模型仍为实验版，完成run也有报警，性能/玩家反应研究与功能验收分开。

## 原始证据

accept1012_live2_luna/summary.json按run_id关联每条ExperimentalModelWarning原始单行，合并连续ACTIVE更新并保留REVOKED与前一RECEIVED原因。3CSV读取前后SHA相同，主代理审计期间只读；Editor.log仍可能自然追加，摘要记录所用快照。原始所有15条1012TEST session保留，不改标签。
