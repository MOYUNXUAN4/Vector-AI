# V7 修复账本（2026-10-20）

输入：`parallel_20261020/staged_v6_review/REPORT.md` 两条窄边界。
范围：只改离线工具与补丁安全机制。Unity 源码、场景、模型、阈值、游戏构建、板端数据一律未动。

---

## 边界 D：终局身份被继承

### 反例（复核方 `staged_v6_review/check_terminal_identity.py`，原样运行）

```
$ python staged_v6_review/check_terminal_identity.py
{'verdict': 'TERMINAL_OUTCOME_VALIDATED', 'terminal_evidence': 'corroborated',
 'run_id': 'r1', 'last_seq': 10, 'unpersisted_sequence_span': 0}
Actual final CSV row has blank run_id and sequence; values above were inherited from preceding running row.
```

CSV：行 A `run_id=r1, sequence=10, run_state=running`（无 outcome）；末行 B `run_id` 空、
`sequence` 空、`run_state=ended`、`outcome=edge_exit`。诊断里 r1 有真实的
`terminal_snapshot_frozen`（seq=10, edge_exit, send completed）。

v6 的两处继承：

- `last_seq` 对**任一**可解析行更新，末行空值不会清掉它（`session_closure_audit_v6.py:133-138`）；
- `run_id` 取“文件里最后一个非空 ID”，与末行是否自带无关（`:139-151`）。

于是 `corroborated` 判定把 B 行的 outcome 挂到了 A 行的身份上——**没有任何一行同时既被标识
又是终局**，却输出了“同 run 已持久化终局”的结论。`--require-corroboration` 也拦不住，因为
返回的证据本身就是 `corroborated`。

顺带查出的两个同类缺陷（复核报告未列，但同属“序号当作值而不是身份”）：

```
$ python -c "print(int(float('10.7')))"      -> 10        # 分数序号被静默截断
$ python -c "print(int(float('inf')))"       -> OverflowError: cannot convert float infinity to integer
```

`inf` 不是被拒绝，而是**未捕获异常**——整轮审计在第一个坏行上崩掉，退出码 1，前面的会话
结果全部丢失。

### 修复（`tools/session_closure_audit_v7.py`）

- 新增 `parse_sequence()`：`re.fullmatch(r"[+-]?[0-9]+")`（ASCII 数字，不用 `\d`，因为
  `\d` 与 `int()` 都接受非 ASCII 十进制数字），不经 `float()`。返回 `(value, defect)`，
  defect ∈ {`missing`, `not_integer`}。
- 身份只从终局行取：`terminal_row_run_id`、`terminal_row_sequence`；
  `out["run_id"]` 直接等于终局行的 `run_id`，**继承路径已删除**。
- 新增终局判定 `TERMINAL_ROW_IDENTITY_UNRESOLVED`，位置在 `run_state=ended` 与
  `outcome ∈ KNOWN_OUTCOMES` 之后、矛盾检查之前；带 `identity_defect`：
  `run_id_missing` / `sequence_missing` / `sequence_not_integer` /
  `run_id_and_sequence_missing`，证据记 `unavailable`。
- `unpersisted_sequence_span` 改用 `terminal_row_sequence`；身份未定时不计算（不再出现
  从上一行借来的 `span=0`）。
- `last_seq` 保留，但语义收窄为“全文件最后一个可解析序号”，仅作展示；无法解析的序号进
  `bad_sequences`（最多 10 条），不再截断、也不再崩。
- CLI 输出列由 `last_seq` 改为 `term_seq`（终局行自己的序号），`TERMINAL_ROW_IDENTITY_UNRESOLVED`
  进入排序表；`--out` 的 `json.dump` 加 `allow_nan=False`。

### 复跑（同一临时目录、同一夹具，仅换包路径）

```
$ python staged_patches_v7_20261020/tests/check_boundaries_v7.py
source_gap_1020ms_receive_continuous NO_ELIGIBLE_WINDOW reported_duration None
nonfinite_timestamp UNKNOWN_EVIDENCE reported_duration None
new_run_lifecycle_only TERMINAL_OUTCOME_VALIDATED unavailable send_completed None
incomplete_terminal TERMINAL_OUTCOME_VALIDATED unavailable send_completed None
terminal_identity_inherited       TERMINAL_ROW_IDENTITY_UNRESOLVED evidence=unavailable run_id='' term_seq=None defect=run_id_and_sequence_missing span=None
terminal_identity_blank_run_id    TERMINAL_ROW_IDENTITY_UNRESOLVED evidence=unavailable run_id='' term_seq=11 defect=run_id_missing span=None
terminal_identity_blank_sequence  TERMINAL_ROW_IDENTITY_UNRESOLVED evidence=unavailable run_id='r1' term_seq=None defect=sequence_missing span=None
terminal_identity_fractional_seq  TERMINAL_ROW_IDENTITY_UNRESOLVED evidence=unavailable run_id='r1' term_seq=None defect=sequence_not_integer span=None
terminal_identity_healthy         TERMINAL_OUTCOME_VALIDATED evidence=corroborated run_id='r1' term_seq=10 defect=None span=0
```

前四行是 v5 复核的四个夹具，标签与 v6 完全一致（未回退）。后五行是本轮新增：复核反例、
两个独立变体（只缺 run_id / 只缺 sequence）、分数序号，以及“身份齐全仍然 corroborated”的
正向对照。

真实数据不受影响（终局行本来就自带身份）：

```
P01: summary {"BOTH_STREAMS_CEASE_TOGETHER": 3, "TERMINAL_OUTCOME_VALIDATED": 22, "UNITY_CEASES_BEFORE_WII": 2}
     evidence for validated sessions: {"corroborated": 22}
P02: summary {"TERMINAL_OUTCOME_VALIDATED": 4}
     evidence for validated sessions: {"corroborated": 4}
     --require-corroboration --only-problems -> rc=0
```

逐局核对过 26 个会话的末行：全部 26 行的 `run_id` 与 `sequence` 都与前一行一致且非空
（例如 P02 `session_20261020_101929_120829` 末行 `rid=358796c3…, seq=4851, ended,
calibration_completed`），所以 D 的收紧没有改变任何既有结论。

---

## 边界 E：恢复 pending 前未验回滚备份

### 静态路径（复核报告 `REPORT.md` 第二段）

v6 的恢复分支（P1 apply 原 `:221-237`、P2 apply 原 `:206-222`）只做两件事：`target` 绑定、
`intended_post_hash == 当前哈希`。满足即把 pending 提升为 committed 收据，但
`pre_patch_hash` 与 `backup_file` 从未被验证。

后果不是“源码被破坏”（revert 之后仍会在改目标之前拒绝），而是**丢失“一定可回滚”这一保证**：
一份 `backup_file` 为空/不存在/内容不符的收据被写成 committed，此后任何 revert 都会在
“备份缺失”处失败，而此时 pre 字节已不存在于任何地方。

### 修复（P1/P2 的 apply 与 revert 四个脚本）

新增 `Test-RollbackRecord($rec, $expectedPostHash, $postField)`，逐项返回问题清单：

| 检查 | 不通过时的消息 |
|---|---|
| `pre_patch_hash` 非空 | `pre_patch_hash is missing` |
| `pre_patch_hash` 为 64 位十六进制 | `pre_patch_hash is not a 64-hex SHA-256 value` |
| post 哈希非空 / 64 位 / 等于当前文件 | `post-patch hash is missing` / `... is not a 64-hex ...` / `... does not match the current target` |
| `backup_file` 非空且是文件 | `backup_file is missing` / `backup_file does not exist: <path>` |
| 备份字节哈希等于 `pre_patch_hash` | `backup_file hashes to <h>, not the recorded pre-patch state <pre>` |

- apply 的恢复分支：任一项不通过 → `exit 13`，pending **不删除、不改写**（测试用文件哈希比
  对“字节不变”），不写 committed 收据，并把全部缺陷打进错误消息。
- apply 的正常提交与恢复提交都写入 `backup_verified = true`、`backup_sha256 = <pre 哈希>`。
- revert 的 pending-only 分支：先用同一函数验证（此时还不知道当前文件哈希，故传空
  `expectedPostHash` 跳过该项），不通过 → `exit 13` 且不动目标。这一条覆盖了复核提到的
  `:79-108` / `:74-104` 两个回落分支。

### 故障注入（`tests/test_ps_lifecycle.ps1` T15–T18，对 P1/P2 各跑一遍）

| 用例 | 注入 | 断言 |
|---|---|---|
| T15 | pending 的 `backup_file` 指向不存在的路径 | `exit 13`；无 committed 收据；pending 字节不变；目标仍是打补丁状态；错误里出现 `does_not_exist.bak` |
| T16 | 向 `.bak` 追加 `// tampered`（`IsReadOnly` 先解除） | `exit 13`；无 committed 收据；pending 保留；错误里出现 `not the recorded pre-patch state`；把备份按 pre 内容修复后**同一状态**再跑 → `exit 0`，收据含 `backup_verified=true` 且 `backup_sha256==pre` |
| T17 | 同上，但走 revert 的 pending-only 分支 | `exit 13`；目标未被修改（仍是 patched 哈希）；错误里出现 `cannot serve as a rollback record` |
| T18 | pending 完全缺 `pre_patch_hash` | `exit 13`；无 committed 收据；错误里出现 `pre_patch_hash is missing` |

T16 的第二段是关键的“可恢复性”断言：拒绝之后不是死局，补齐回滚点就能正常提交。

---

## 复跑汇总

| 项 | 结果 | 退出码 |
|---|---|---|
| `python tests/test_v7_suite.py` | 85 项，85 passed，0 failed（wii 27 / closure 42（含 D 的 19 项）/ p4 10 / episodes 6，另内置时延自检 10 项） | 0 |
| `powershell -File tests/test_ps_lifecycle.ps1` | 134 项，134 passed，0 failed（P1 67 / P2 67） | 0 |
| `receive_latency_profile_v5.py --self-test` | 10 项通过 | 0 |
| `session_closure_audit_v7.py --root telemetry_logs/P02 --require-corroboration` | 4/4 corroborated | 0 |
| `check_boundaries_v7.py` | 9 行输出见上 | 0 |

未改工具与 v6 包逐字节相同（避免“只是改名”的伪差异）：

```
af2f76a56fc586451b4b6668273b8c97d65abdb2b38538b620a5532dcc3e790c  wii_cop_preflight_v6.py
c40c65282b9be04d295199680511a024ef6339da3ac15025c61f08841ce2c9cf  receive_latency_profile_v5.py
5249d0c533cb25302bf18e65939f4b42c6e0976d44668c59a0dd7f95ea7444da  cluster_warning_episodes_v5.py
```

生产文件校验（测试前后各一次，均一致）：

```
096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90  UDPManager.cs   mtime 2026-10-08 16:01
03C9765ED598D19F6721F851F9CF378808ED0056AAB7FAC905CCD9B9D240B488  UIManager.cs    mtime 2026-10-19 16:32
Assets 下 .bak / .tmp.* 数量：0
```

---

## 仍然不能声称的

1. **C# 未编译**，Patch 1 / Patch 2 的运行时行为、`VectorStyleKey` 等价性、Pixel 一致性都未验证。
2. **D 只保证“终局行自己带身份”**，不保证那份身份对应的确实是同一局——跨 run 的情形由
   `MIXED_RUN` 兜住，但“两份文件拼出来的同一 run”不在工具能力范围内。
3. **E 只保证“收据声明的备份可用”**，不保证收据声明的 pre 内容就是当时的目标内容；这依赖
   收据自身哈希链，工具无法独立复核。
4. **两次故障注入都是文件系统级**（预建 tmp 目录、删/改 `.bak`），不是真实磁盘满或 ACL 事故
   的回放；NTFS 在磁盘满时的具体错误码未被覆盖。
5. **Patch 5 仍是描述性检查**，板端时钟连续 ≠ 标定流程执行过。
6. **本轮无新增模型实验、无新采板数据**；两条边界都是工具缺陷，不需要更多数据来证明。

## 三条口径（不变）

- 90 个分组不是 90 次模型报警，只是按 (run, 通道, 层级, 平台实例, 版本) 切分的描述性计数。
- P01 的 09:28:57 / 09:52:25 是此前记录的历史运行，不能据此推断 P02 仍有同样故障；P02 四局
  终局完整且 `corroborated`。
- v7 在拿到独立复核前仍只作**人工复核用的描述性分析**，不构成无人值守验收门槛，也不构成
  可安全部署的证书。
