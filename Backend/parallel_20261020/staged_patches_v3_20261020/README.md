# v3 补丁与诊断工具包（2026-10-20 11:00）

> **当前版本是 v4，不是本文件下面描述的 v3。**
> 独立复核发现 v3 仍有 5 处实质缺陷（Patch5 读错列名导致标志校验空转、Patch4 在真实数据上把长帧误报成时延阶跃、Patch3 跨通道合并了 P02 的 8 个事件、闭环审计未校验 `run_state`、apply 的"已应用"判断只看子串），已全部修复。
> 请以这些文件为准：
>
> - `patch_3_warning_episodes/cluster_warning_episodes_v4.py`
> - `patch_4_clock_profile/receive_latency_profile_v4.py`
> - `patch_5_wii_preflight/wii_cop_preflight_v4.py`
> - `tools/session_closure_audit_v4.py`
> - `tests/test_v4_suite.py`（30 项回归）
> - `V4_FIX_LEDGER_20261020.md`（逐条复现与对照数据）
>
> 下面 v3 的说明保留作为历史记录，不再代表工具行为。

本包针对 `staged_v2_review/REPORT.md` 中指出的所有 P1 / P2 级问题进行全面修复，**生产代码（Unity 源码、正常游戏构建、模型权重与阈值）保持完全未改动**。

---

## 一、修复清单（v2 缺陷 vs v3 修正）

| 模块 | v2 缺陷 (被 REPORT.md 查实) | v3 修复措施 | 验证状态 |
|---|---|---|:---:|
| **备份与回滚** | 无哈希绑定的单文件覆盖；二次执行覆盖备份；篡改后回滚存在丢代码风险 | 强制校验基准 SHA-256；生成预哈希绑定的不可变备份；落盘加密收据 `patch_receipt.json`；若目标被二次篡改则**严格拒绝回滚**；临时文件原子替换 | 沙箱测试通过，篡改拦截已验证 |
| **Patch 1: 终局发送** | 实际重传时间为 +120ms / +480ms；MonoBehaviour 协程在场景/进程析构时无法存活；P02 无补丁已 100% 成功 | 明确标记为 **DEFERRED (暂缓/仅作为可选加固)**；修正增量延迟为 `{0.12f, 0.24f}` (累计 +120ms / +360ms)；文档注明协程生命周期局限 | 脚本沙箱测试通过，默认不合入 |
| **Patch 2: GUIStyle 缓存** | 使用 32 位整型哈希作键，存在哈希碰撞返回错误样式风险 | 改用 `VectorStyleKey` 结构体，实现 `IEquatable<VectorStyleKey>` 与全字段强类型值相等性比对；哈希碰撞风险归零 | 语法与沙箱注入测试通过，无碰撞隐患 |
| **Patch 3: 预警聚类** | 默认排除 `calibration_completed`，导致 P02 3 局正常完成局被全部丢弃；跨 Run、跨层或显式 CLEAR 时发生错误粘连 | 彻底取消对完成局的默认排除；P02 实跑 4 局（82 个事件）全量保留；显式 CLEAR (`warning_active=false`) 与跨 Run 严格切分；短事件全量导出保留 | `test_v3_suite.py` 验证通过 |
| **Patch 4: 时钟/延迟剖面** | 仅按 >0.4s 源缺口分段，无法发现连续流内部的时延阶跃（注入 100ms 阶跃报 0ms）；误将接收时延当双时钟对齐 | 改名 `receive_latency_profile_v3.py`，明确边界为网络/接收时延；增加流内滑动窗口阶跃检测，实测 100ms 阶跃 100% 捕获；双时钟偏移独立分离 | 100ms 阶跃捕获实测通过 |
| **Patch 5: Wii 零位质检** | 仅查窗口均值，未查逐样本有效载荷；无法区分未站立、晃动、偏移 | 严格要求逐样本载重 $\ge 20\text{ kg}$ 且连续无空洞；细化为 4 档状态：`INSUFFICIENT_LOAD`, `LOADED_NOT_STATIONARY`, `SKEWED`, `OK` | 4 档状态测试全部通过 |
| **闭环审计** | 将时间戳推论写为确定原因（如 RECEIVER_BLACKOUT）；将未落盘序号差夸大为网络发包证明 | 采用中立描述标签（如 `SIMULTANEOUS_CESSATION_WITHOUT_OUTCOME`）；区分本地 `send_completed` 与落盘序号差 `unpersisted_sequence_span` | P01/P02 全量审计通过 |

---

## 二、目录结构

```
staged_patches_v3_20261020/
├── patch_1_terminal_delivery/
│   ├── apply.ps1          (带哈希收据与原子替换，状态: DEFERRED)
│   └── revert.ps1         (带篡改拦截)
├── patch_2_uimanager_style_cache/
│   ├── apply.ps1          (采用 VectorStyleKey 强类型键，带哈希收据)
│   └── revert.ps1         (带篡改拦截)
├── patch_3_warning_episodes/
│   └── cluster_warning_episodes_v3.py (全量包含完成局，支持显式 CLEAR 切分)
├── patch_4_clock_profile/
│   └── receive_latency_profile_v3.py  (支持流内时延阶跃捕获，明确接收时延范围)
├── patch_5_wii_preflight/
│   └── wii_cop_preflight_v3.py        (逐样本持续受载与 4 档状态质检)
├── tools/
│   └── session_closure_audit_v3.py    (中立分类标签与诊断交叉核验)
├── tests/
│   └── test_v3_suite.py               (全量单元与回归测试套件)
├── reproduce_v3_comparison.py         (针对 staged_v2_review/reproduce.py 的对照脚本)
└── README.md
```

---

## 三、快速验证指令

```powershell
$py = "C:\Users\QIYUXUAN\AppData\Local\Microsoft\WindowsApps\python.exe"

# 1. 运行回归测试套件
& $py tests\test_v3_suite.py

# 2. 运行 v2 与 v3 对比测试
& $py reproduce_v3_comparison.py

# 3. 运行 P02 全量预警聚类（验证 4 局全保留，不漏完成局）
& $py patch_3_warning_episodes\cluster_warning_episodes_v3.py --csv "..\..\telemetry_logs\P02"

# 4. 运行闭环审计
& $py tools\session_closure_audit_v3.py --root "..\..\telemetry_logs\P02"
```

---

## 四、安全使用规范

1. **Unity 生产代码先保持未动**：目前 P02 standalone 表现良好且无需补丁支持，不要急于合入 Unity 补丁；
2. **Patch 2 评估前置**：在未来决定是否合入 Patch 2 之前，必须先在目标环境进行 A/B 截图像素比对与 Unity 内存分配测量；
3. **Patch 1 暂缓**：现有日志显示终局帧落盘完整，暂不需要引入额外的协程重发机制。
