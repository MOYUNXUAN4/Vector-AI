# 靠边时AI横幅消失：原因核查

只读诊断，没有修改模型、报警状态机、Unity或后端生产代码。

## 最新run的真实记录

session_20261012_104434_821214，run_id=567a765f63824eaa88db0381beebb44f。Editor.log有5个连续ACTIVE片段：前4次REVOKED/backend_safe，紧邻的RECEIVED均为SAFE/raw_off；第5次REVOKED/prediction_age_exceeded_0_3s。

因此最新这条中，前4次消失由当前分数退出规则造成，不是已有证据表明球已完成恢复，也不是非正净空导致。CSV已收到的1826个Unity样本中净空<=0计数为0，源序号连续且无>0.1秒几何采样空隙；不要将其他run的nonpositive_clearance原因套到这条。

最后有效ACTIVE本地时间3796.561678，过期撤销3796.854994，间隔0.293316秒。计时年龄包含接收时feature_age_seconds，所以并非要求恰好收到后0.300秒。用户已报告主动关闭后端，结合真实超时撤销支持一次停止后端后过期清理的实测；没有记录精确关闭时刻，不报告端到端停止延迟。

CSV停止时最后Unity仍running，无terminal结果。主代理本地JSONL另确认终端edge_exit、sequence1887、layer1，在source backend timestamp1791773106.411附近，Unity Send正常返回；该终端在本次后端CSV中没有落盘。后端已被主动停止，这是故障测试边界，不当作未知通关或新的UDP长度缺陷，不把该run加入训练/正式性能比较。

## 两种普通撤销机制

1. 分数撤销：alarm_policy.StrongAlarmPolicy在每次新评估用p>=0.65构造raw。confirmed要求连续两个满足阈值；一旦不满足，若没有恢复标志，也会令active=false、state=SAFE、reason=raw_off。这里SAFE只意味着模型当前未报警，不保证物理安全。
2. 预测域边界：warning_runtime首先计算directional_edge_distance-ball_radius。如果有限净空<=0，直接UNKNOWN/nonpositive_clearance并重置policy；model_artifact也拒绝对非正净空进行模型推理。UdpFrontendReceiver对新的UNKNOWN立即撤销AI显示，UIManager在active=false时不画横幅。

第二机制在先前session_20261012_103349_663622已实测：seq295与306的STRONG之后，以相同prediction_sequence收到UNKNOWN/nonpositive_clearance并撤销。其CSV有72个净空<=0样本和真正edge_exit。边缘风险和模型输入域失效被同一个“横幅消失”视觉效果表现，因此用户观察到危险更近却没提示是有证据的交互缺陷。

## 下一步建议，尚未实施

优先区分三种语义：模型提前风险、当前几何危险、数据不可用。

- 当输入/平台归属/采样年龄仍有效且几何净空有限<=0时，用独立、明确标记的几何危险提示承接，而不是伪造模型概率或宣称又一次模型命中。模型可以停止预测，但不能把确定的风险条件表现为安全。判断的是球体净空侵入，不保证必然坠出。
- 真正断流、时间过期、平台归属错误或几何查询无效，仍必须撤销失效AI状态。不能为保持显示而使用旧几何值伪造危险真值；可明确提示“AI不可用”。
- 对合法分数上下波动，另做单因素退出策略离线比较，检查实际向内运动/净空恢复、闪烁、完成组负担和漏检，不直接加无限保持或只降阈值。入口阈值、权重、特征和预测范围先不改。
- 模型指标与几何提示指标分开，几何接力不计入“改进的模型F1”；延长显示不算更早触发。

需一次明确的协议/前端显示适配后才能接入新语义；本轮没有授权后擅自更改玩法或旧黄色规则。先处理危险时消失与短闪烁，再开展其他玩家试采，不继续泛泛增加功能run。

证据：disappear_audit_luna/summary.json，原CSV与Editor.log的读取快照/哈希；主代理核对源码、日志single-line原因及本地JSONL终端。单调时间和CSV epoch没有直接互减，不编造现场几何提前量。
