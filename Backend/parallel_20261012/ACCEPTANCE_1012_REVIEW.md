# 1012TEST：主代理验收核查

结论：这批可保留为功能测试。原始遥测、换层和Restart链路有真实证据，但独立AI提示的现场显示、撤警、断流尚未获证实。不能把离线重放当成真实HUD验收，也不据此挑阈值或报告正式F1。

## 数据结果

全部为难度3、选定三层、calibration_mode=true（当前已审计兼容模式）。8个run各有独立GUID，共9,958行Unity遥测；原始8份CSV的SHA256经主代理复核未变。

| 完整session ID | 日志确认结果 | 固定模型离线STRONG片段数 |
|---|---|---:|
| session_20261012_094803_454375 | 三层完成，calibration_completed | 2 |
| session_20261012_094829_452155 | 三层完成，calibration_completed | 1 |
| session_20261012_094848_416014 | 三层完成，calibration_completed | 4 |
| session_20261012_094923_638395 | 三层完成，calibration_completed | 8 |
| session_20261012_095007_690150 | 第一层edge_exit | 1 |
| session_20261012_095019_846147 | 第一层edge_exit | 0 |
| session_20261012_095041_552734 | 运行中Restart，JSONL有restart_aborted | 0 |
| session_20261012_095057_878988 | 三层完成，calibration_completed | 0 |

095041的CSV末态running、无终端outcome，与JSONL active_run_restart_request_no_terminal_outcome一致，不当作通关、坠出或丢失结束包。7个真正结束run的JSONL terminal_udp_send_call_completed payload序号/outcome均与CSV最后Unity行匹配，证明这7个结束包已在后端原始日志中落盘。正常通关终端平台层号4是三层完成后的计数，不是额外玩了第4层。

8个CSV的Unity序号/源时间均无重复或倒序，序号从1到N连续。普通geometry query/ownership有效标志均为true，active平台与版本身份错配0；这说明身份字段一致，不等于连续物理边界精度已全面验证。

两段源时间空隙超过0.1秒：094848在第3层序号1668→1669为0.619秒；094923在第2层1932→1933为0.663秒。均running且序号连续，不能直接归因于UDP丢包。当前guard会清历史并重新准备；没有插值或补造样本。

## 现场AI提示证据缺口

- 本批CSV不含model_warning、模型概率或warning_update_sequence；attention_state、prediction_state和edge_warning_state不能冒充LightGBM提示日志。
- 当前Unity Editor.log有这8个run的start_session/诊断启动记录，但没有ExperimentalModelWarning接收/显示记录。
- 当前正式场景Assets/Endness Driving/Scenes/Stage/EndlessFalling.unity第882行保存enableExperimentalModelWarning: 0；代码默认也为false。恢复场景文件另有开启值，但不是正式场景配置。
- 用户反馈不确定看到的是哪一种提示。因此不能确认本批测试时运行实例已开启实验显示，也不能从保存配置反推出测试期间一定关闭。
- 这批材料也不能证明模型是否由当时master成功加载；启动终端日志未提供。不能以当前离线加载成功替代当时加载记录。

## 离线重放，非现场观测

GPT-6 Luna只读提取与重放，主代理独立核查CSV/JSONL并再次重放两个坠出run。模型保持锁定SHA、阈值0.65、两点确认及既定恢复策略，没有训练、调阈值或修改Unity。

8个run的counterfactual重放：7,543行accepted、6,810行valid、234个收到STRONG状态的采样点，合并为16个片段。234不是234次独立报警。回复排序序号在一次桥实例中从1到9,958单调递增。原数据哈希未变。

095007会产生1个强报警片段，首次源时间1791769816.255，最后STRONG源时间1791769816.420；在1791769816.455因nonpositive_clearance退出。CSV fall_event_backend_timestamp为1791769816.795，两时间字段相差0.540秒。这个值只相对游戏fall事件，不是经完整几何锚点验证的提前量，也不是现场HUD提前量。095019没有强报警。5个完成run里4个出现离线强报警，不能因此称为成功干预；这批尚未证明AI显示或玩家因它回正。

## 下一步最小补测

先让Unity agent只核查正式场景唯一接收器，把实验开关在Edit Mode开启并保存，验证UI Restart重载后仍开启；不要调整输入/灵敏度/黄色规则/模型。主代理负责后端，Unity agent不用后端权限。

确认master启动终端明确有experimental model loaded，同时Unity日志出现ExperimentalModelWarning RECEIVED。然后只补2–3次定向短测：真实STRONG显示、触发后的撤销/回正、STRONG显示时停止后端后的过期清理。普通Restart/换层原始链路已有证据，但AI提示在这些路径的真实清理仍应观察。后端重启必须开启新Unity run。

保留原始CSV、Unity Editor.log与模型加载终端信息；无需重做整批8条或泛泛增加训练数据。当前批次保留为功能测试，不加入开发调参或冻结模型性能主表。

资料：accept1012_csv_luna/summary.json为CSV原始核查；accept1012_replay_luna/summary.json为离线重放；accept1012_primary.py为主代理CSV/本地JSONL对照。脚本只读源数据。
