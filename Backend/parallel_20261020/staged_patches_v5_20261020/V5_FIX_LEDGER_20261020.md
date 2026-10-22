# V5 修复账本（2026-10-20）

输入：`parallel_20261020/staged_v4_review/REPORT.md` 及其 `reproduce_remaining.py`。
处置范围：**只修离线工具与补丁安全边界**。Unity 代码、模型、阈值、协议、正常游戏构建全部未动，
未上板，未应用补丁。

生产文件复核（本文件写作时实测）：

| 文件 | SHA-256 前 16 位 | mtime |
|---|---|---|
| `Assets/BackEnd/UDPManager.cs` | `096C5FFA591E8B5D` | 2026-10-08 16:01 |
| `Assets/Endness Falling/Scripts/UIManager.cs` | `03C9765ED598D19F` | 2026-10-16 16:32 |

---

## 一、六条反例：v4 → v5 逐条对照

用同一份 `reproduce_remaining.py`，只把包路径与文件名换成 v5（不改任何断言）后重跑：

| 反例 | v4 输出 | v5 输出 | 判定 |
|---|---|---|---|
| 板子状态字段全部缺失 | `OK`，同时 `flag_columns_present` 全 False | `UNKNOWN_EVIDENCE` | 缺失证据不再等于通过 |
| 时间戳倒退 | `OK`，`duration = -0.98` | `NO_ELIGIBLE_WINDOW`，`duration = None` | 负时长不再可能产生 |
| 双时钟缓慢漂移 239 ms | `global_offset_sufficient = True` | `False`（spread 239.0，jumps 0） | 漂移不再被阶跃检测漏掉 |
| CSV 与诊断终局冲突 | `TERMINAL_OUTCOME_VALIDATED`，`outcome_match=False` | `TERMINAL_OUTCOME_CONTRADICTED` | 冲突可推翻 VALIDATED |
| 同层平台实例/版本变化 | 合并为 `1` 组 | `2` 组 | 身份键补全 |
| 时间/序号反转 | 合并为 `1` 组 | `2` 组 | 顺序违规即切分 |

真实数据不回归（同一脚本）：

```
real_161529  receive_step False  spike_ms 204.239  dual_jumps 6  jump_sum_ms 948.8
P02_descriptive_groups 90
```

说明：v5 把 `cumulative_drift_ms` 改名为 `cumulative_jump_ms`（它求和的是离散跳变，不是缓慢漂移），
因此旧脚本最后两行会 `KeyError`。这是有意的键名修正，数值不变（6 次 / 948.8 ms）。

---

## 二、Patch 5（Wii 预检）：把“没证据”和“证据合格”分开

| v4 行为 | 位置 | v5 行为 |
|---|---|---|
| `valid/loaded/centered` 缺失时 `True if v is None else v` | `load_wii` | 缺失记 `None`，整份文件判 `UNKNOWN_EVIDENCE`（exit 6） |
| age 缺失不拦 | `audit` | age 必须存在、有限、`0 ≤ age ≤ --max-age-s` |
| 空 generation / instance 字符串构成常量集合 | `len(set(...)) > 1` | 二者必须非空，空值直接不合格 |
| `gap_ok` 接受 `b - a <= 0` | `gap_ok` | 必须 `0 < dt <= --max-gap`；重复时间戳与倒退都算屏障 |
| 缺 weight/CoP 的行被丢弃后再索引 | `load_wii` | 行保留在原索引，标记不合格，窗口跨不过去 |
| `ineligible_rows` 按“每个标志”计数（一行可计 2–3 次） | `audit` | 改为按行计数 |

真实数据上的变化（只是计数口径变正，结论不变）：

| 会话 | v4 `ineligible_rows` | v5 | 判定 |
|---|---|---|---|
| P01 10:56（真人 87 kg） | 278 | 139 行 | `OK`，窗口 samples 0–49 / csv 行 2–94 |
| P02 10:19 | 952 | 476 行 | `OK`，窗口 75–124 / csv 146–242 |
| P02 10:22 | 132 | 66 行 | `OK`，窗口 70–119 / csv 141–236 |
| P01 16:15（空板 0.10 kg） | 15638 | 7819 行 | `INSUFFICIENT_LOAD`（exit 2） |

新增 `window_start_csv_line` / `window_end_csv_line`：窗口可以直接在原始 CSV 里打开核对。

---

## 三、Patch 4（时延剖面）：充分性改成预声明规则

v4 的 `single_global_offset_sufficient = (len(jumps) == 0)` 是“没看到 >50 ms 的单点跳变，所以一个常数偏移够用”，
缓慢漂移与多次小跳变都能绕过。v5 改为：

```
sufficient    coverage ≥ 0.90 且 paired ≥ 200 且 无离散跳变
              且 detrended spread ≤ 20 ms 且 |gradual drift| ≤ 20 ms
insufficient 以上任一条被违反
unknown      coverage 或样本数不足，无法判断
```

20 ms 取一个标称 50 Hz 采样间隔：只有两钟相对变化小于一个采样间隔，才允许声称“单一偏移足够”。
规则以模块常量固定（`GLOBAL_OFFSET_MAX_SPREAD_MS` 等），不随文件调参。

其它：
- 新增 `detrended_gradual_drift_ms`（首末十分位中位数差），让慢漂移可见，不再只依赖跳变检测；
- `single_global_offset_sufficient` 保留键名但改为三态 `True / False / None`，未知时不是 `True`；
- 每个跳变带 `csv_line`（1 基物理行号，表头为第 1 行），不再只给过滤后数组下标。

复跑：`--self-test` 9 项全过；真实 16:15 仍为 `NO_STEP`、spike 204.239 ms、6 次跳变合计 948.8 ms、
`global_offset_verdict = insufficient`。

---

## 四、闭环审计（v5）：诊断冲突可以推翻 VALIDATED

| 项 | v4 | v5 |
|---|---|---|
| 终态判定来源 | 任意行的 outcome + 任意行的 ended | **必须同一行**（终末行）同时具备 |
| outcome 语义 | 任意非空即通过 | 必须属于源码可产出的四种：`completed` / `calibration_completed` / `edge_exit` / `user_exit` |
| 多 run | 未处理 | `MIXED_RUN`（归属不明，不算通过） |
| 诊断冲突 | 只附加 `outcome_match` | `TERMINAL_OUTCOME_CONTRADICTED`，exit 7 |
| 证据状态 | 无 | `corroborated` / `partial` / `unavailable` / `contradicted` 四态 |

冲突定义（任一即推翻）：
1. CSV outcome ≠ 诊断终局 outcome；
2. 诊断冻结序号 < 已落盘最大序号（顺序不可能）；
3. 诊断报告终局发送调用失败。

`partial` 是独立状态：outcome 一致，但终局快照序号领先最后落盘行 —— 属于“终局那一行本身没落盘”，
不是矛盾，也不隐藏。

真实数据结果不变，且证据等级明确：

```
P01: 22 校验通过（全部 corroborated）+ 5 未通过
     151034 缺 255 包 / 161733 缺 244 包 / 092857 缺 76 包 → BOTH_STREAMS_CEASE_TOGETHER
     151734、095225 → UNITY_CEASES_BEFORE_WII
P02: 4/4 TERMINAL_OUTCOME_VALIDATED，全部 corroborated，unpersisted span 0
```

---

## 五、Patch 3（事件聚类）：身份键、顺序、参数透传

| 项 | v4 | v5 |
|---|---|---|
| 身份键 | run_id + 通道 + `platform_level` + `layer_id` | 追加 `geometry_platform_instance_id` + `geometry_version_id` |
| 时间倒退 | 直接 append（合并） | 切分 |
| 序号倒退 | 未处理 | 切分 |
| `--seq-tolerance` | 解析了但没传给 `episodes_for_session` | 全链路透传，并成为“序号不连续”的唯一定义 |
| 多 run 文件 | outcome/fall 按整份文件赋值 | `MIXED_RUN`，outcome/fall **不归属** |
| 通道名来源 | 未区分 | `channel_is_fallback` 标记；由状态字段重建的名字不当作独立告警系统的证据 |

复跑：P02 仍为 90 组（identity 在会话内稳定，所以数量不变）；P01 为 87 组。
`sequence_gaps` 改名 `sequence_discontinuities`，与 tolerance 语义一致。

---

## 六、补丁安全机制（apply/revert）

v4 的三个缺口与处置：

| 缺口 | v5 处置 |
|---|---|
| 收据未严格绑定目标路径 | 收据 `target` 与当前目标必须归一化后相等；**且在一次 apply 之前就检查已有收据**，一个收据目录只对应一个目标（exit 8） |
| 已有备份未在 apply 前验证 | 备份存在时必须先哈希等于当前目标，否则在任何改动之前中止（exit 6） |
| 先替换目标、后写收据 | 改为 `patch_receipt.pending.json`（替换**前**写）→ 替换 → 校验 → `patch_receipt.json`（提交）。中途失败留下可恢复的 pending 状态 |
| 替换后哈希不符 | 用已验证备份回滚并复验，失败则保留 pending 并 exit 9 |

`-TargetOverride` 不再能绕过身份：revert 时若 override 与收据目标不一致，直接拒绝（exit 8）。

生命周期回归 `tests/test_ps_lifecycle.ps1`：**54 项全过**（每个补丁 27 项），全部在 `%TEMP%` 的
一次性副本上运行：

```
T1 apply 提交收据、哈希一致          T6 pending-only 被下一次 apply 提交
T2 二次 apply 幂等且不改文件          T7 改过文件后 revert 拒绝；-SaveCurrentFirst 归档后恢复
T3 同内容他处文件被拒（exit 8）       T8 pending-only 可正常 revert
T4 已有备份损坏则中止（exit 6）       T9 revert 的 -TargetOverride 必须等于收据目标（exit 8）
T5 收据目录不可写则中止（exit 7）
```

其中 **T3 一开始是失败的**：v4 的检查只在“文件已含补丁标记”时才比对路径，因此对一个未打补丁的
同内容文件会直接打补丁并覆盖收据，把前一个目标变成孤儿。v5 把路径检查提到标记判断之前，才通过。

诚实的边界：`Move-Item -Force` 不保证所有失败路径上的原子性，v5 不声称原子替换，
pending 收据存在的原因正是它不原子。

---

## 七、测试

```
tests/test_v5_suite.py          38 项，全过
tests/test_ps_lifecycle.ps1     54 项，全过
patch_4 ... --self-test          9 项，全过
```

测试用例与反例一一对应，回退任一修复都会让对应用例失败。

---

## 八、仍未验证（不要写进论文，也不要当作已验收）

1. **C# 没有编译过。** 两个 apply 只做锚点唯一性、哈希收据、文件级替换与回滚，Unity 侧一行都没跑。
2. **Patch 2 的“像素一致”仍是断言。** 没有截图 diff；`19.4 KB/frame` 来自 15:51 的捕获，
   接收器 21:16 改过，分配排名需重测。
3. **Patch 1 的重传是协程序列**，场景卸载/进程退出后不会继续发；不修复 4.2 s 级接收黑障。
4. **Patch 5 仍是描述性**：有载重且静止的窗口，不等于标定流程真的执行过。
5. **`partial` 与 `unavailable` 都不是通过**，只是“未发现矛盾”。任何引用闭环结论的地方必须带上
   证据等级；P02 四局是 `corroborated`，可以直接引用。

## 九、两条口径（保留）

- **90 个分组不是 90 次模型报警**：它按 (run, 通道, 层级, 平台实例, 版本) 切分、按时间与序号连续性
  合并，既不是橙/紫被试可见告警日志，也不能当误报率分母。
- **P01 的 09:28:57（缺 76 包）与 09:52:25（缺 50 包）是更早的运行**，与随后 10:04/10:06 及 P02 的
  版本和时段不同，不能据此说后续仍有同样故障；P02 四局终局完整且与诊断一致。
