# staged_patches_v8_20261020 — 诊断序号类型边界关闭包

针对 `parallel_20261020/staged_v7_review/REPORT.md` 的 follow-up：**诊断侧的 `sequence` 从未
做过类型校验**，字符串值会让整轮批量审计抛未捕获 `TypeError`，`10.5` / `None` 被静默容忍。
只改离线工具与测试，**生产代码零改动**：Unity 两个目标文件哈希与 mtime 均未变，本包不应用
任何 Unity 补丁，也不需要重新上板。

- `UDPManager.cs` `096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90`
- `UIManager.cs`  `03C9765ED598D19F6721F851F9CF378808ED0056AAB7FAC905CCD9B9D240B488`

上一轮复核接受的 D（终局行身份）与 E（回滚证据）结论照原样保留：`test_ps_lifecycle.ps1`
本轮 138/138 通过，四个 apply/revert 脚本与 v7 包**逐字节相同**（哈希见下），本轮没有重开
D/E，只补了 T16–T18 的 pending 字节不变断言——复核报告指出原先只有 T15 独立断言了这一点。

## 本轮改了什么

| 边界 | v7 行为 | v8 行为 |
|---|---|---|
| F 诊断序号 | `index_diagnostics` 原样拷贝 JSON 的 `sequence`；`audit_session` 在类型检查之前就做 `term_seq - terminal_seq`。字符串 `"10"` / `"bad"` → 未捕获 `TypeError`，整轮批量审计中断；`10.5`、`None` 只落 `partial`；`True` 会被当成整数 1 | 解析提前到**建索引时**，且类型严格：只接受 JSON 整数。`bool`（Python 里是 `int` 子类）、字符串、小数、整数值浮点 `10.0`、`NaN/Infinity`、数组/对象分别是 `boolean` / `string` / `fractional` / `float_typed` / `non_finite` / `not_integer` 缺陷，**一律不转换**，`"10"` 永远不会变成 10。缺陷名与 JSON 类型按会话输出，证据记 `partial`，永不 `corroborated` |
| F 单会话崩溃 | 一个会话解析失败就终止整轮，其余会话无输出 | `main` 逐会话 `try/except`：抛异常的会话记 `AUDIT_ERROR`（含异常类型与消息）并继续审计其余会话，退出码仍是 7。`AUDIT_ERROR` 是问题判定，不是静默跳过 |
| F 相邻字段 | 诊断的 `session_outcome` 非字符串时会被当成“与 CSV 不一致”→ 误判 `CONTRADICTED`；`backend_timestamp` 为 `NaN/Inf` 时会算出非有限 `tail_silence_s` | outcome 必须先是非空字符串才参与比较，否则记 `partial` 且 `outcome_match=None`；时间戳必须是有限数（排除 bool）才做尾部静默减法 |

## 目录

```
staged_patches_v8_20261020/
├── README.md                                  本文件
├── V8_FIX_LEDGER_20261020.md                  逐条修复账本（反例→修复→复跑输出）
├── patch_1_terminal_delivery/
│   ├── apply.ps1                              与 v7 逐字节相同（D/E 已验收，不再改）
│   └── revert.ps1                             同上
├── patch_2_uimanager_style_cache/
│   ├── apply.ps1                              同上；补丁体与 v4/v5/v6/v7 相同
│   └── revert.ps1                             同上
├── patch_3_warning_episodes/
│   └── cluster_warning_episodes_v5.py         本轮未改，逐字节同 v5–v7
├── patch_4_clock_profile/
│   └── receive_latency_profile_v5.py          本轮未改，逐字节同 v5–v7
├── patch_5_wii_preflight/
│   └── wii_cop_preflight_v6.py                本轮未改，逐字节同 v6/v7
├── tools/
│   └── session_closure_audit_v8.py            诊断序号先验类型，单会话错误隔离
└── tests/
    ├── test_v8_suite.py                       111 项 Python 对抗性回归
    ├── test_ps_lifecycle.ps1                  138 项 PowerShell 生命周期回归（一次性副本）
    └── check_boundaries_v8.py                 三段夹具：v5 四项 / v6 五项 / v7 八项
```

patch 3 / 4 / 5 的三个工具与两个补丁脚本**故意保留原文件名、逐字节不变**，可与 v7 包直接比对，
不会产生“只是改名”的伪差异：

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
python tools/session_closure_audit_v8.py --root telemetry_logs/P02 --diag-dir "<诊断目录>"
python tools/session_closure_audit_v8.py --root telemetry_logs/P02 --diag-dir "<诊断目录>" --require-corroboration

# 回归
python tests/test_v8_suite.py
powershell -ExecutionPolicy Bypass -File tests/test_ps_lifecycle.ps1
python tests/check_boundaries_v8.py          # 三段夹具的 v8 输出
```

managed Python 3.13 无 numpy；三个工具都不依赖 numpy。
`test_ps_lifecycle.ps1` 只在 `%TEMP%/v8_ps_lifecycle_*` 的一次性副本上运行，从不写生产文件。

## 退出码

| 工具 | 0 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| wii v6 | OK | INSUFFICIENT_LOAD | SKEWED | LOADED_NOT_STATIONARY | NO_ELIGIBLE_WINDOW | UNKNOWN_EVIDENCE | | SOURCE_CLOCK_UNAVAILABLE | | | |
| latency v5 | NO_STEP | | STEP_DETECTED | DOMAIN_ERROR | | SELF_TEST_FAILED | | | | | |
| closure v8 | 全部闭合 | | | | | | 存在未闭合（含 `TERMINAL_ROW_IDENTITY_UNRESOLVED`、`AUDIT_ERROR`） | `--require-corroboration` 下有证据不足 | | | |
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
7. **F 的隔离测试用的是真实解析失败**（单字段超过 `csv` 的 131072 字节上限），不是人为
   monkeypatch；但它只证明“该会话记 `AUDIT_ERROR`、其余会话继续”，不等于“任意恶意 JSON
   都能被完整解释”。`json.loads` 失败的行仍按原有策略跳过，不产生会话级记录。

## 三条必须保留的口径

- **90 个分组不是 90 次模型报警。** 它是按 (run, 通道, 层级, 平台实例, 版本) 切分并按时间/
  序号连续性合并后的描述性计数，既不是橙/紫两色被试可见告警日志，也不是误报率分母。
- **P01 的 09:28:57 与 09:52:25 是此前已记录的早期运行**，不能据此推断后续 P02 仍有同样的
  终局故障。P02 四局终局完整、诊断交叉核对一致（`corroborated`）。
- **本轮没有新增模型实验，也没有新采板数据。** 这条 follow-up 是工具缺陷，不需要用更多数据
  来“证明”。v8 在拿到独立复核前仍只作**人工复核用的描述性分析**，不作为无人值守验收门槛。
