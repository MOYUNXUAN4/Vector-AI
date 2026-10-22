# V6 修复账本（2026-10-20）

对象：`parallel_20261020/staged_v5_review/REPORT.md` 的三条边界 A/B/C。
只改离线工具与补丁安全机制。**未应用任何 Unity 补丁，未重新上板，未跑模型实验，未采新数据。**

生产文件复核（本轮结束时测得）：

| 文件 | SHA-256 前 24 位 | mtime |
|---|---|---|
| `UDPManager.cs` | `096C5FFA591E8B5D98B24F51` | 2026-10-08 16:01:09 |
| `UIManager.cs` | `03C9765ED598D19F6721F851` | 2026-10-19 16:32:21 |

`Assets/` 下 `.bak` / `.tmp.*` 残留：0 个。

---

## A. Wii 连续性：改用声明源时钟 + 控制序号

**反例（复核方 `check_boundaries.py`，原样指向 v6）**

| 夹具 | v5 输出 | v6 输出 |
|---|---|---|
| 源时钟 1020 ms 缺口、接收 1 ms 匀速 | `OK`，`window_duration_s=0.049` | `NO_ELIGIBLE_WINDOW`，`window_duration_s=None` |
| 全部 `backend_timestamp=inf` | `OK`，`window_duration_s=NaN` | `UNKNOWN_EVIDENCE`，`window_duration_s=None` |

**改法**

1. 表头一次性选定时钟，优先级 `wii_control_timestamp`（板端采样，ISO-8601）→
   `source_timestamp`（记录侧 ISO）→ `backend_timestamp`（接收，**非源时钟**）。
   选定结果写入 `time_column` / `time_domain` / `clock_is_source`，窗口输出同样带 `time_domain`。
   不再逐行切换列，缺该列的行一律 `no_timestamp`，不回落。
2. 解析 ISO-8601（含 7 位小数、`Z`、`+00:00`）。真实 P02 行：
   `wii_control_timestamp=02:19:29.1086780Z` 与 `backend_timestamp=...769.130726` 相差约 21 ms，
   说明这两个域确实不同；`source_timestamp` 与接收时刻中位差仅 0.57 ms，所以它不是独立源时钟，
   只是被排在第二顺位。
3. 连续性只看源时钟上的 distinct 采样：同一控制样本被记到多行是常态（P01 16:15 局
   5685 行 wii 只有 2867 个 distinct 采样），重复折叠后必须 `0 < dt ≤ --max-gap`。
4. `wii_control_sequence` 列为必填，distinct 采样之间必须非递减且步长 ≤ `--max-seq-gap`（默认 1）。
   接收时间再平滑，序号跳号就说明板端样本丢了 —— 这正是接收时钟看不见的那类缺口。
5. 所有时间 / 年龄 / 载重 / CoP 数值必须 `math.isfinite`。任一非有限值 → `UNKNOWN_EVIDENCE`
   （`evidence.nonfinite_count` 记录条数），JSON 用 `allow_nan=False`，不再序列化 `NaN`。
6. CLI 阈值做 `isfinite` + 区间校验，`--window`、`--max-seq-gap` 有上下界。
7. 接收时延降级为描述统计：`window_receive_duration_s`、`receive_max_dt_ms`，并带
   `receive_note` 说明它不是连续性证据。

**真实数据复跑**

- `P01/session_20261019_105632_058608`：`OK`，`time_domain=board_control`，
  源时钟窗口 0.77 s / 26 个 distinct 采样 / 最大步长 35.7 ms，序号 25494→25519（最大步长 1），
  接收跨度 0.76 s（描述性）。与 v5 的 `OK` 一致，但现在有源域证据。
- `P01/session_20261019_161529_760840`：`INSUFFICIENT_LOAD`（板子空载，7819 行全 `flag_false`），
  与 v5 一致。
- 全库 wii 源时钟 `max dt` 实测：`wii_control_timestamp` 53.5 ms、`source_timestamp` 32.1 ms、
  `backend_timestamp` 114.9 ms —— 默认 `--max-gap 0.15` 对三者都不误杀。

---

## B. 终局证据：只有冻结终局才算 corroborated

**反例**

| 夹具 | v5 输出 | v6 输出 |
|---|---|---|
| 诊断只有 `files` + `last_sample_ts` | `VALIDATED / corroborated` | `VALIDATED / unavailable` |
| 手上字典含 `terminal_outcome` + `terminal_seq`（未过 `index_diagnostics`） | `VALIDATED / corroborated` | `VALIDATED / unavailable` |

第二行需要说明：v6 的 corroborated 只认 `index_diagnostics` 产出的 `terminal_present`，
而该标志只由 `lifecycle_event == "terminal_snapshot_frozen"` 置位。复核夹具是手工构造的字典，
不经过索引器，所以按“无冻结终局”处理。真实 JSONL 走索引器时，
`terminal_snapshot_frozen` 一定同时带来 outcome 与 sequence（实测 668 条记录全部如此），
v6 套件用真实 JSONL 写的 `closure: frozen terminal corroborates` 覆盖了这条正向路径。

**改法**

1. `index_diagnostics` 增加 `terminal_present`（仅 `terminal_snapshot_frozen` 置位）、
   `events` 集合；记账类记录（`new_run_created`、`restart_requested`、`layer_transition_*`）
   只证明“有过生命周期记录”，不再参与证据强度。
2. 证据判定顺序：
   - 无诊断条目 → `unavailable`（`evidence_reason: 无诊断记录`）
   - 有条目但无冻结终局 → `unavailable` + `diag_terminal_absent: true`
   - 冻结终局缺 outcome 或 sequence，或 sequence 晚于最后持久化行 → `partial`
   - 同 run、outcome 一致、整数 sequence 不晚于最后持久化行 → `corroborated`
3. `diag_send_state` ∈ {`completed`, `failed`, `unknown`}。`unknown` 不当作失败（不制造冲突），
   也不当作证据（不提升等级）。`failed` 仍然直接推翻 VALIDATED。
4. 新增 `--require-corroboration`：`unavailable` / `partial` 时 `exit 8`，供需要硬门槛的场合；
   默认仍是描述性输出，并在汇总里单列“证据弱于 corroborated”的局。
5. 冲突判定（outcome 不符、sequence 落后、send 失败）不再依赖 `terminal_present` 之外的条件，
   仍然是 `TERMINAL_OUTCOME_CONTRADICTED`，且 `--only-problems` 不隐藏。

**真实数据复跑（不变）**

- P01：22 局 `VALIDATED`，**全部 corroborated**；5 局未闭合（
  `151034` / `161733` / `20261020_092857` 双流同时停止；`151734` / `20261020_095225` Unity 先停）。
- P02：4/4 `VALIDATED`，4/4 corroborated。

即 v6 的加严没有把任何一局从 corroborated 降级 —— 因为那 26 局本来就都带真实冻结终局。
这也说明 v5 的 `corroborated` 在真实数据上碰巧正确，缺陷只在“诊断无终局”的边界上。

---

## C. 收据提交：先验证再删 pending

**反例（代码路径，非磁盘事故回放）**

v5 `apply.ps1`：`WriteAllText(committed)` → `Remove-Item(pending)` 在同一 `try` 里，且
`$ErrorActionPreference = "Continue"`。写失败时异常被捕获、打印 `Write-Warning`，然后 `exit 0`。
更糟的一条：截断的 committed 在后续 apply/revert 里优先于有效 pending 被读取，
于是“自动恢复”被自己写坏的文件挡住。

**改法**

1. `Commit-Receipt`：`ConvertTo-Json` → 写 `patch_receipt.json.tmp` → 读回 →
   校验 `target` 绑定与 `post_patch_hash` 往返 → `Move-Item -Force` → **再读回**校验
   → 全部通过才返回 `$true`。
2. 任一环节失败：返回 `$false`，**不删 pending**，`exit 12`（恢复待办）。已在文件里明确写
   “不要当作已应用”。
3. 读收据统一走 `Try-ReadJson`（失败返回 `$null`，不抛）。committed 不可解析时：
   - 有有效 pending → 隔离成 `patch_receipt.corrupt_<stamp>.json`，继续按 pending 恢复；
   - 无有效 pending → `exit 11`（收据不可读且无可恢复），不再对 `$null` 取属性。
4. revert 同构：committed 损坏时回落到 pending；两者都不可用 `exit 11`。
5. `patch_receipt.json` / `patch_receipt.pending.json` 若是目录，直接 `exit 11`。

**故障注入（全部在 `%TEMP%` 一次性副本上）**

注入手法：把 `patch_receipt.json.tmp` 预先建成目录，临时写入必然失败。选它是因为实测
`Move-Item -Force` 会覆盖只读目标、只读属性也不阻止重命名 —— 只读收据根本走不到失败分支。

| 用例 | 断言 |
|---|---|
| T10 首次提交失败 | `exit 12`（不是 0）；目标已被替换；无 committed；pending 保留且仍绑定已改文件；解除阻塞后重跑 `exit 0`、committed 出现、pending 清除 |
| T11 恢复提交失败 | `exit 12`；committed 仍缺；pending 仍在；目标仍是已改状态；解除阻塞后 `exit 0` |
| T12 committed 截断 + 有效 pending | `exit 0`；committed 重新可读且绑定一致；损坏件被隔离为 `patch_receipt.corrupt_*.json` |
| T13 revert 遇 committed 截断 | `exit 0`，从 pending 恢复，回到 pre-patch 哈希 |
| T14 committed 截断且无 pending | apply `exit 11`、revert `exit 11`，目标未被触碰 |

---

## 复跑结果

| 项目 | 结果 |
|---|---|
| `tests/test_v6_suite.py` | **66 / 66 通过**，exit 0 |
| `tests/test_ps_lifecycle.ps1 -KeepWorkDir` | **98 / 98 通过**（P1/P2 各 49），exit 0 |
| `receive_latency_profile_v5.py --self-test` | 10 项通过（工具未改） |
| `tests/check_boundaries_v6.py` | 四个夹具全部翻转（见 A、B 两表） |
| P01 闭环 | 22 validated，全部 corroborated；5 未闭合 |
| P02 闭环 | 4/4 validated，4/4 corroborated |
| P02 描述性分组 | 仍为 90（未被本包改动） |
| 生产文件 | 哈希与 mtime 未变，无 `.bak` / `.tmp.*` 残留 |

基座对比：v5 的 38 项 Python 与 54 项 PowerShell 全部保留在 v6 套件里（wii 夹具已补上
`wii_control_timestamp` 与 `wii_control_sequence`，因为 v6 不接受只凭接收时钟的证据）。
v6 的 66 项构成为：Wii 27、闭环 23、时延 10、预警分组 6；PowerShell 由 54 增至 98（新增 T10–T14）。

---

## 本包文件哈希（SHA-256，复核用）

```
AF2F76A56FC586451B4B6668273B8C97D65ABDB2B38538B620A5532DCC3E790C  patch_5_wii_preflight/wii_cop_preflight_v6.py
D9D13AAF6B7274EAF499CCDF98C701DD56B16153EB4BDD52DED899965550D5B5  tools/session_closure_audit_v6.py
5E18F5FD926EDA9FD1C17E21F3268353FDF1520C5CE9A093DC99DFDFBE6823D2  patch_1_terminal_delivery/apply.ps1
B64BD3671D3CE6DE70735BA6B01F3C3A4A8FD2ADB3D292641FE5A25E109F2264  patch_1_terminal_delivery/revert.ps1
B5A079D68F1B5FCDDF8A723273584E8D998E361E23B6AE4CD01377A6CFF2DB99  patch_2_uimanager_style_cache/apply.ps1
2BB70C5BD09A445FD1944E054411B7157B7800D1247DA1C43B9DD7AE23C798D3  patch_2_uimanager_style_cache/revert.ps1
3670D33338BC69FB777C6DE89B4BFF913329A22CA33D4E89EBF5B7CC2204F2EB  tests/test_v6_suite.py
590CDEEA1E11290F54182236894D53D5C72BD894876D0179662654912635ECEB  tests/test_ps_lifecycle.ps1
B216F5153456AA3AD1E2C342996CFE1966E04A20008D56218F2E215DE11E52EC  tests/check_boundaries_v6.py
5249D0C533CB25302BF18E65939F4B42C6E0976D44668C59A0DD7F95EA7444DA  patch_3_warning_episodes/cluster_warning_episodes_v5.py
C40C65282B9BE04D295199680511A024EF6339DA3AC15025C61F08841CE2C9CF  patch_4_clock_profile/receive_latency_profile_v5.py
```

---

## 仍然不能声称的

1. **不是无人值守验收门槛。** v6 让三条边界不可再被这些夹具穿过，但没有第三方独立复核；
   在有复核结论前，它仍是“供人工复核使用的描述性分析”，不是自动放行闸门。
2. **C# 未编译，Unity 补丁继续不应用。** Patch 1 / Patch 2 的 apply 脚本只做锚点唯一性、
   哈希收据与文件级替换；“像素一致”“分配减少”仍是断言，没有编译、截图 diff 或分配重测。
3. **Patch 5 仍是描述性。** 板端时钟连续 ≠ 协议标定执行过。要声称标定有效，需要协议层证据
   （标定阶段标记或人工记录），本包不提供。
4. **收据失败注入不是磁盘事故回放。** 注入点与真实失败点同在 committed 收据写入侧，
   但 NTFS 在磁盘满 / ACL 拒绝时的具体错误码与部分写行为没有被覆盖。
