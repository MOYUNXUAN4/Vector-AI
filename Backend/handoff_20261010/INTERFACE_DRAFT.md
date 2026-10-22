# 实时预警接口草案 v0（尚未实施）

## 已有链路

后端 `UDPRecevier.py` 监听 127.0.0.1:5005，向 Unity 127.0.0.1:5006 返回 `type=realtime` 包，含 x/y、difficulty、rmse 等。Unity 的 `UdpFrontendReceiver.cs` 用它控制输入和同步难度；当前无后端模型预警字段。

Unity 接收器只有一个 `pendingJsonData` 槽，后到包会覆盖前包。因此不能直接频繁往同一端口加独立 warning 包，可能影响输入。推荐在现有 realtime 包中**附加**预警对象，保持原包节奏和全部旧字段语义不变；该方案仍须实现前核对和主代理确认。

## 拟议嵌套对象

```json
{
  "type": "realtime",
  "x": 0.0,
  "y": 0.0,
  "difficulty": 1,
  "rmse": 0.0,
  "model_warning": {
    "schema_version": 1,
    "experimental": true,
    "enabled": false,
    "model_id": "mock-v0",
    "run_id": "current-run",
    "platform_instance_id": 123,
    "layer": 1,
    "input_sequence": 42,
    "input_source_timestamp": 0.0,
    "prediction_sequence": 1,
    "state": "UNKNOWN",
    "valid": false,
    "probability_valid": false,
    "strong_probability": 0.0,
    "feature_age_seconds": 0.0,
    "reason": "not_ready"
  }
}
```

这是形状示例，时间/身份数字是占位，不是真实记录。state 候选：UNKNOWN/SAFE/ATTENTION/STRONG。当前最终坠出模型与危险 attention 的概率、标签和评价不可互换；attention 若未单独冻结，则保持禁用，不拿 strong 的低阈值冒充已验证 attention。

## 安全与时序要求

- 模型默认关闭；缺模型、历史不足、字段缺失、COP 过期、身份失配输出 UNKNOWN，不表示 SAFE，不补旧几何当新真值。
- 包缺少 model_warning 时保持全部旧控制行为，模型显示关闭。
- Unity 仅显示与当前 running run/platform/layer 对应的有效结果，忽略旧 run/乱序包；超时清模型提示，原黄色继续工作。
- 在 Unity 接收时记录本地单调时钟用于断流超时；不能直接相减两台设备的非同步时钟。关联原 input sequence/source timestamp 以计算可解释延迟。
- Restart、换层、终端、calibration 时清窗口/计数/提示；不得把前一个平台的窗口接到新平台。
- 各 geometry version/fingerprint/generation 按自身语义关联，不要求不同体系字符串相等。
- 现有 Wii fallback 没有新鲜度检查；模型必须独立检查其真实 source/receive 时间，不借改变输入控制来修此事。
- 严格 JSON，不发 NaN；概率无效时用有效性标记，不让占位 0 被当作低风险。
- 显示可加独立蓝色 attention、实验强报警标记，但不覆盖原黄色、死亡、输入或难度权威。

## 实现前需固定

源时间单位、具体窗口重采样策略、COP 最大年龄、推理 cadence、显示超时、状态机和模型 artifact ID。这些由离线因果构造/模型门禁决定，不能由各 agent 分别猜。可先用 mock 走通身份、丢包和 Restart 测试。

CPU 模型耗时、特征耗时、包传输/显示延迟分别统计；“加载成功”不等于完整链路验收。
