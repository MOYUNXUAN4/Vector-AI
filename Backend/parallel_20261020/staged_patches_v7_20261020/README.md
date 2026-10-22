# staged_patches_v7_20261020 — 两条 v6 窄边界关闭包

针对 `parallel_20261020/staged_v6_review/REPORT.md` 中列出的两条窄边界（D 终局身份继承、
E 恢复 pending 前未验回滚备份），只改离线工具与补丁安全机制。**生产代码零改动**：Unity 两个
目标文件哈希与 mtime 均未变，本包不应用任何 Unity 补丁，也不需要重新上板。

- `UDPManager.cs` `096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90`
- `UIManager.cs`  `03C9765ED598D19F6721F851F9CF378808ED0056AAB7FAC905CCD9B9D240B488`

上一轮复核接受的结论照原样保留：v5 三条边界的修复、v4 六条反例的修复、P01 22 局 / P02 4 局的
闭合、16:15 那次 948.8 ms 的阶梯、以及 90 个描述性分组不构成报警数。本包只增不减这些结论。

## 本轮改了什么

| 边界 | v6 行为 | v7 行为 |
|---|---|---|
| D 终局身份 | 末行 `run_state=ended` + outcome 但 `run_id` 与 `sequence` 都为空时，身份从上一行 `running` 继承：`run_id=r1`、`last_seq=10`，配合 r1 的冻结终局记录判 `corroborated`。另：`int(float(seq))` 把 `10.7` 截成 10，`inf` 抛未捕获 `OverflowError` 直接终止整轮审计 | 身份只从**终局行本身**取：该行必须自带非空 `run_id` 与严格整数 `sequence`（`[+-]?[0-9]+`，仅 ASCII）。缺失/分数/非有限 → `TERMINAL_ROW_IDENTITY_UNRESOLVED` + `identity_defect`（`run_id_missing` / `sequence_missing` / `sequence_not_integer` / `run_id_and_sequence_missing`），证据记 `unavailable`。`out["run_id"]` 不再继承；`last_seq` 只作“全文件最后可解析序号”的展示项，与诊断比较只用 `terminal_row_sequence`；无法解析的序号进 `bad_sequences`，不再截断也不再崩 |
| E 回滚证据 | 恢复分支只校验 `target` 绑定与 `intended_post_hash == 当前哈希`，就把 pending 提升为 committed 收据。`backup_file` 缺失、不可读或与 `pre_patch_hash` 不符时照样提交，产出一份**承诺了做不到的回滚**的收据 | 提升前整条回滚记录端到端验证：`pre_patch_hash`/`intended_post_hash` 必须是 64 位十六进制且 post 与当前文件一致；`backup_file` 必须存在、可读、且字节哈希等于 `pre_patch_hash`。任一不满足 → `exit 13`，pending 原样保留（字节不变），**不写** committed 收据，并逐条打印缺陷。成功时收据记录 `backup_verified=true` 与 `backup_sha256`。revert 的 pending-only 分支同样先验再动目标 |

## 目录

```
staged_patches_v7_20261020/
├── README.md                                  本文件
├── V7_FIX_LEDGER_20261020.md                  逐条修复账本（反例→修复→复跑输出）
├── patch_1_terminal_delivery/
│   ├── apply.ps1                              恢复前验回滚记录（备份存在 + 哈希等于 pre）
│   └── revert.ps1                             pending-only 先验回滚记录再还原
├── patch_2_uimanager_style_cache/
│   ├── apply.ps1                              同上；补丁体与 v4/v5/v6 相同
│   └── revert.ps1
├── patch_3_warning_episodes/
│   └── cluster_warning_episodes_v5.py         本轮未改，逐字节同 v5/v6
├── patch_4_clock_profile/
│   └── receive_latency_profile_v5.py          本轮未改，逐字节同 v5/v6
├── patch_5_wii_preflight/
│   └── wii_cop_preflight_v6.py                本轮未改，逐字节同 v6
├── tools/
│   └── session_closure_audit_v7.py            终局行自带身份才算 corroborated
└── tests/
    ├── test_v7_suite.py                       85 项 Python 对抗性回归
    ├── test_ps_lifecycle.ps1                  134 项 PowerShell 生命周期回归（一次性副本）
    └── check_boundaries_v7.py                 复核方两项夹具 + v5 四个夹具的 v7 镜像
```

patch 3 / 4 / 5 的三个工具**故意保留原文件名**，内容哈希可与 v6 包直接比对，不会产生
“只是改名”的伪差异：

```
af2f76a56fc586451b4b6668273b8c97d65abdb2b38538b620a5532dcc3e790c  wii_cop_preflight_v6.py
c40c65282b9be04d295199680511a024ef6339da3ac15025c61f08841ce2c9cf  receive_latency_profile_v5.py
5249d0c533cb25302bf18e65939f4b42c6e0976d44668c59a0dd7f95ea7444da  cluster_warning_episodes_v5.py
```

## 运行

```bash
python patch_5_wii_preflight/wii_cop_preflight_v6.py --csv <raw.csv>
python patch_4_clock_profile/receive_latency_profile_v5.py --csv <raw.csv>
python patch_3_warning_episodes/cluster_warning_episodes_v5.py --csv <dir 或 raw.csv>
python tools/session_closure_audit_v7.py --root telemetry_logs/P02 --diag-dir "<诊断目录>"
python tools/session_closure_audit_v7.py --root telemetry_logs/P02 --diag-dir "<诊断目录>" --require-corroboration

# 回归
python tests/test_v7_suite.py
powershell -ExecutionPolicy Bypass -File tests/test_ps_lifecycle.ps1
python tests/check_boundaries_v7.py          # 六类夹具的 v7 输出
```

managed Python 3.13 无 numpy；三个工具都不依赖 numpy。
`test_ps_lifecycle.ps1` 只在 `%TEMP%/v7_ps_lifecycle_*` 的一次性副本上运行，从不写生产文件。

## 退出码

| 工具 | 0 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| wii v6 | OK | INSUFFICIENT_LOAD | SKEWED | LOADED_NOT_STATIONARY | NO_ELIGIBLE_WINDOW | UNKNOWN_EVIDENCE | | SOURCE_CLOCK_UNAVAILABLE | | | |
| latency v5 | NO_STEP | | STEP_DETECTED | DOMAIN_ERROR | | SELF_TEST_FAILED | | | | | |
| closure v7 | 全部闭合 | | | | | | 存在未闭合（含 `TERMINAL_ROW_IDENTITY_UNRESOLVED`） | `--require-corroboration` 下有证据不足 | | | |
| apply v7 | 成功/幂等 | | | | 状态不可验证 | 备份哈希不符 | 收据目录不可写 | 目标路径不符 | 收据不可读且无可恢复 | 已改文件但收据未提交 | 回滚记录验不过，拒绝提升 pending |
| revert v7 | 成功 | | | | | | | 目标路径不符 | 收据不可读且无可恢复 | 无法隔离损坏收据 | 回滚记录验不过，拒绝还原 |

`exit 12` 的语义是**恢复待办**，不是成功：目标文件已被替换且已验证，但 committed 收据没写成，
pending 仍保留。`exit 13` 的语义是**拒绝提升**：目标已打补丁但回滚点不可验证，pending 原样保留，
必须先人工修复备份或补回 pre 文件。

## 明确未验证（不要当已验收）

1. **C# 未编译**。两个 apply 脚本只做锚点唯一性、哈希收据与文件级替换；Unity 编译、运行时
   行为、`VectorStyleKey` 的等价性都没有被验证过。
2. **Patch 2 的“像素一致”仍是断言**，没有截图 diff，也没有重测分配量；`19.4 KB/frame` 需要在
   接收器 21:16 改动后重测。
3. **Patch 1 的重传时序是协程序列**（+120 ms、+360 ms 名义值），场景卸载或进程退出后不会
   继续发送；它不修复 4.2 s 级的接收黑障。
4. **Patch 5 仍是描述性检查**。`wii_control_timestamp` 连续只说明板端采样没断，不等于协议
   标定流程真的执行过；`wii_cop_preflight_v6.py` 不会因此给出“标定有效”的结论。
5. **收据失败与备份损坏都是文件系统级注入**（把 `patch_receipt.json.tmp` 预建为目录；
   删掉备份文件；向 `.bak` 追加字节）。注入点与真实失败点相同，但“磁盘满时 NTFS 的具体
   错误码”没有被覆盖，也不是真实磁盘事故回放。
6. **回滚点验证只覆盖“收据声明的备份是否可用”**，不覆盖“收据声明的那份 pre 内容是否真的
   是当时的目标内容”——后者只能由收据自身的哈希链保证，工具无法独立复核。

## 三条必须保留的口径

- **90 个分组不是 90 次模型报警。** 它是按 (run, 通道, 层级, 平台实例, 版本) 切分并按时间/
  序号连续性合并后的描述性计数，既不是橙/紫两色被试可见告警日志，也不是误报率分母。
- **P01 的 09:28:57（缺 76 包）与 09:52:25（缺 50 包）是此前已记录的早期运行**，不能据此推断
  后续 P02 仍有同样的终局故障。P02 四局终局完整、诊断交叉核对一致（`corroborated`）。
- **本轮没有新增模型实验，也没有新采板数据。** 两条边界都是工具缺陷，不需要用更多数据来“证明”。
