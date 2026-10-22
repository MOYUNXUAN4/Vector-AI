# V8 修复账本 — 诊断序号类型边界（2026-10-20）

输入：`parallel_20261020/staged_v7_review/REPORT.md` + `check_diagnostic_sequence.py`
范围：只修 `session_closure_audit` 对**诊断侧** `sequence` 的使用，以及单会话异常隔离。
边界：不应用 Unity 补丁、不重新上板、不改生产 `.cs`、不改原始遥测与诊断日志。

## 1. 反例复现（先跑，再改）

用复核方给的脚本原样指向 v7 包：

```
$ python staged_v7_review/check_diagnostic_sequence.py
10    -> TERMINAL_OUTCOME_VALIDATED corroborated
None  -> TERMINAL_OUTCOME_VALIDATED partial
'10'  -> TypeError unsupported operand type(s) for -: 'str' and 'int'
'bad' -> TypeError unsupported operand type(s) for -: 'str' and 'int'
10.5  -> TERMINAL_OUTCOME_VALIDATED partial
```

与报告完全一致。两处成因：

1. `index_diagnostics` 把 JSON 里的 `sequence` **原样**放进索引，从不看类型；
2. `audit_session` 先算 `term_seq - terminal_seq`（v7 第 311–312 行），到第 347 行才用
   `isinstance(term_seq, int)` 判“能否算 corroborated”。减法在类型检查之前，字符串直接抛
   `TypeError`，整个多会话循环一起死。

另有两处同源问题一并处理：

3. Python 里 `bool` 是 `int` 的子类，`True` 会通过 `isinstance(term_seq, int)`，被当作序号 1；
4. 非字符串的 `session_outcome` 会走“与 CSV 不一致”分支，被误判 `CONTRADICTED`。

## 2. 修复

| # | 位置 | v7 | v8 |
|---|---|---|---|
| F1 | `parse_diag_sequence`（新增） | 无 | 只接受 JSON 整数。`None`→`missing`；`bool`→`boolean`；`str`→`string`；小数→`fractional`；整数值浮点→`float_typed`；`NaN/Inf`→`non_finite`；数组/对象→`not_integer`。**不转换**：`"10"` 不会变成 10 |
| F2 | `index_diagnostics` | `e["terminal_seq"] = rec.get("sequence")` | 建索引时即调 F1；同时记录 `terminal_seq_type`（JSON 类型名）与 `terminal_records`（同一 run 的冻结记录条数） |
| F3 | `audit_session` 减法 | `if term_seq is not None and terminal_seq is not None:` | 同条件，但 `term_seq` 已是 F1 的输出，只可能是 `int` 或 `None`；缺陷值不参与任何算术 |
| F4 | `audit_session` 冲突判定 | `if isinstance(term_seq, int) and term_seq < terminal_seq` | 保留，且 outcome 比较前加 `isinstance(..., str)`，非字符串不再制造假冲突 |
| F5 | `audit_session` 证据强度 | `elif not isinstance(term_seq, int): partial` | 非空字符串 outcome + 整数序号才可能 `corroborated`；缺陷时 `partial` 并在 `evidence_reason` 里写明缺陷名与 JSON 类型 |
| F6 | `audit_session` 时间戳 | `isinstance(term_ts,(int,float))` 即做减法 | 再加 `not isinstance(bool)` 与 `math.isfinite`，非有限值不再产生 `tail_silence_s` |
| F7 | `main` | `results = [audit_session(s, diag_index) for s in sessions]` | 逐会话 `try/except`：异常记 `AUDIT_ERROR` + `audit_error`（异常类型与消息），继续审计其余会话，退出码仍 7 |
| F8 | 输出 | 无 | 新增 `diag_terminal_sequence_defect` / `_json_type` / `_malformed` 字段，以及 “N session(s) have a malformed diagnostic terminal sequence” 汇总段 |

## 3. 复跑：反例翻转

`tests/check_boundaries_v8.py` 第三段跑的是同一矩阵，但**经过真实 JSONL 索引器**（复核方的
脚本手工构造 dict，绕过了 `index_diagnostics`，因此看不到类型来源）：

```
diag_sequence 10     -> TERMINAL_OUTCOME_VALIDATED  corroborated  defect=None         span=0
diag_sequence None   -> TERMINAL_OUTCOME_VALIDATED  partial       defect=missing      span=None
diag_sequence '10'   -> TERMINAL_OUTCOME_VALIDATED  partial       defect=string       span=None
diag_sequence 'bad'  -> TERMINAL_OUTCOME_VALIDATED  partial       defect=string       span=None
diag_sequence 10.5   -> TERMINAL_OUTCOME_VALIDATED  partial       defect=fractional   span=None
diag_sequence 10.0   -> TERMINAL_OUTCOME_VALIDATED  partial       defect=float_typed  span=None
diag_sequence True   -> TERMINAL_OUTCOME_VALIDATED  partial       defect=boolean      span=None
diag_sequence nan    -> TERMINAL_OUTCOME_VALIDATED  partial       defect=non_finite   span=None
```

零 `RAISED`。第 1、2 段的 v5/v6 夹具标签与 v7 完全一致（`NO_ELIGIBLE_WINDOW` /
`UNKNOWN_EVIDENCE` / `UNAVAILABLE`×2 / 五个 `TERMINAL_ROW_IDENTITY_UNRESOLVED` / 一个
`corroborated`），没有回退。

## 4. 测试

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python tests/test_v8_suite.py` | 111 项，111 passed，0 failed（v7 的 85 项全保留 + F 新增 26 项） | 0 |
| `powershell -File tests/test_ps_lifecycle.ps1` | 138 项，138 passed，0 failed（v7 的 134 项 + T16/T17/T18 各补一条 pending 字节不变断言，P1/P2 各一遍） | 0 |
| `python patch_4_clock_profile/receive_latency_profile_v5.py --self-test` | 10 项通过（工具未改） | 0 |
| `python tests/check_boundaries_v8.py` | 17 行，见上 | 0 |

F 的 26 项覆盖：九种非整数值各自 `partial` + 明确缺陷名；九种值都不产生 span；字符串缺陷在
`evidence_reason` 里被点名且写明“not coerced”；`null` 是 `missing`；JSON 整数仍
`corroborated` 且 `span=0`；非字符串 outcome 是 `partial` 而非冲突；非有限诊断时间戳不产生
尾部静默；以及一次真实的多会话运行——一个会话的 `raw.csv` 含超过 `csv` 131072 字节上限的
字段，`subprocess` 跑 `--root`，得到 `rc=7`、`{'TERMINAL_OUTCOME_VALIDATED': 1,
'AUDIT_ERROR': 1}`，`AUDIT_ERROR` 记录 `Error: field larger than field limit (131072)`，
另一个会话照常 `corroborated`。

## 5. 真实数据未变

- 诊断索引：690 个 run，668 条 `terminal_snapshot_frozen`，`sequence` 的 JSON 类型
  **668/668 为 integer**，缺陷计数为 0，同一 run 多条冻结记录为 0。也就是说，F 的收紧对
  现有数据零影响——与复核报告“这是畸形输入，不是现有日志缺陷”的判断一致。
- P01：22 局 `validated`，全部 `corroborated`；5 局未闭合
  （`BOTH_STREAMS_CEASE_TOGETHER` 3、`UNITY_CEASES_BEFORE_WII` 2），与 v5–v7 相同。
- P02：4/4 `validated`，4/4 `corroborated`，`send=completed`，`unpersist=0`。
- P02 预警分组仍为 90（描述性分组，不是报警数）。

## 6. 生产状态

```
096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90  UDPManager.cs  mtime 2026-10-08 16:01:09
03C9765ED598D19F6721F851F9CF378808ED0056AAB7FAC905CCD9B9D240B488  UIManager.cs   mtime 2026-10-19 16:32:21
Assets 下 *.bak / *.tmp.*: 0
```

四个 apply/revert 脚本与 v7 包逐字节相同（D、E 已验收，本轮不重开）；`wii_cop_preflight_v6.py`、
`receive_latency_profile_v5.py`、`cluster_warning_episodes_v5.py` 同样逐字节未变。

## 7. 仍然不能声称的

- 未编译 C#，未做 Patch 2 截图 diff，未重测 `19.4 KB/frame`。
- 未做 Editor 同条件 180 s 对照，长帧根因仍未定案。
- F 只覆盖“诊断 `sequence` 类型错误”这一类畸形输入；`json.loads` 失败的行仍按原策略跳过，
  不产生会话级记录。不能据此声称对任意畸形 JSON 都健壮。
- `AUDIT_ERROR` 依赖逐会话 `try/except`，它保证“其余会话继续”，不保证“异常会话的部分
  结果可用”——该会话除异常类型外没有别的结论。
- 90 分组不是报警数；P01 的两局早停不能推断 P02；v8 在拿到独立复核前只作人工复核用的
  描述性分析，不作无人值守验收门槛。
