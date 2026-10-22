# staged_patches_v6_20261020 — 三条 v5 边界关闭包

针对 `parallel_20261020/staged_v5_review/REPORT.md` 中列出的三条边界（A Wii 连续性、
B 终局证据、C 收据提交失败），只改离线工具与补丁安全机制。**生产代码零改动**：Unity 两个
目标文件哈希与 mtime 均未变，本包不应用任何 Unity 补丁，也不需要重新上板。

- `UDPManager.cs` `096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90`
- `UIManager.cs`  `03C9765ED598D19F6721F851F9CF378808ED0056AAB7FAC905CCD9B9D240B488`

上一轮复核接受的结论照原样保留：v4 六条反例的修复、38 项 Python + 54 项 PowerShell 的基座、
P01 22 局 / P02 4 局的闭合、16:15 那次 948.8 ms 的阶梯、以及 90 个描述性分组不构成报警数。
本包只增不减这些结论。

## 本轮改了什么

| 边界 | v5 行为 | v6 行为 |
|---|---|---|
| A 源连续性 | 优先用 `backend_timestamp`（接收时刻），只能解析数字；源时钟 1020 ms 缺口 + 接收 1 ms 间隔仍判 `OK`；`inf` 时间戳判 `OK` 且 `window_duration_s=NaN` | 从表头一次性选定声明时钟（`wii_control_timestamp` → `source_timestamp` → 仅接收）。只有接收时钟时判 `SOURCE_CLOCK_UNAVAILABLE`，永不 `OK`。解析 ISO-8601，重复采样折叠，distinct 采样必须 `0 < dt ≤ --max-gap`；`wii_control_sequence` 必填且必须非递减、步长 ≤ `--max-seq-gap`（缺口/反转即屏障）。任何非有限数值 → `UNKNOWN_EVIDENCE`，JSON 用 `allow_nan=False` |
| B 终局证据 | 只要有诊断条目就落到 `corroborated` | `corroborated` 必须来自同 `run_id` 的 `terminal_snapshot_frozen` 记录，且 outcome 与 CSV 一致、sequence 为整数且不晚于最后持久化行。仅有 `new_run_created` / `restart_requested` 等记账记录 → `unavailable` 并标 `diag_terminal_absent`。`diag_send_state` 区分 completed / failed / unknown，unknown 既不当失败也不当证据 |
| C 收据提交 | 直接 `WriteAllText` 写 committed 再删 pending；写失败仍 `exit 0`；截断的 committed 优先级高于有效 pending | 提交走 `patch_receipt.json.tmp`：写入→读回→校验 target 绑定与哈希往返→`Move-Item`→再读回校验，全部通过才删 pending。任一步失败保留 pending 并 `exit 12`。committed 不可解析时先隔离为 `patch_receipt.corrupt_<stamp>.json`，再从有效 pending 恢复；两者都不可用时 `exit 11` |

## 目录

```
staged_patches_v6_20261020/
├── README.md                                  本文件
├── V6_FIX_LEDGER_20261020.md                  逐条修复账本（反例→修复→复跑输出）
├── patch_1_terminal_delivery/
│   ├── apply.ps1                              目标绑定 + 先验备份 + 受校验的收据提交
│   └── revert.ps1                             收据损坏时回落到 pending
├── patch_2_uimanager_style_cache/
│   ├── apply.ps1                              同上；补丁体与 v4/v5 相同
│   └── revert.ps1
├── patch_3_warning_episodes/
│   └── cluster_warning_episodes_v5.py         本轮未改，与 v5 包逐字节相同
├── patch_4_clock_profile/
│   └── receive_latency_profile_v5.py          本轮未改，与 v5 包逐字节相同
├── patch_5_wii_preflight/
│   └── wii_cop_preflight_v6.py                声明源时钟 + 序号连续性 + 有限性
├── tools/
│   └── session_closure_audit_v6.py            冻结终局才算 corroborated
└── tests/
    ├── test_v6_suite.py                       66 项 Python 对抗性回归
    ├── test_ps_lifecycle.ps1                  98 项 PowerShell 生命周期回归（一次性副本）
    └── check_boundaries_v6.py                 复核方 check_boundaries.py 的 v6 镜像（仅改两处路径）
```

patch 3 / patch 4 的两个工具**故意保留 `_v5.py` 文件名**，这样它们的内容哈希可与 v5 包直接比对，
不会产生“只是改名”的伪差异：

```
5249d0c533cb25302bf18e65939f4b42c6e0976d44668c59a0dd7f95ea7444da  cluster_warning_episodes_v5.py
c40c65282b9be04d295199680511a024ef6339da3ac15025c61f08841ce2c9cf  receive_latency_profile_v5.py
```

## 运行

```bash
python patch_5_wii_preflight/wii_cop_preflight_v6.py --csv <raw.csv>
python patch_4_clock_profile/receive_latency_profile_v5.py --csv <raw.csv>
python patch_3_warning_episodes/cluster_warning_episodes_v5.py --csv <dir 或 raw.csv>
python tools/session_closure_audit_v6.py --root telemetry_logs/P02 --diag-dir "<诊断目录>"
python tools/session_closure_audit_v6.py --root telemetry_logs/P02 --diag-dir "<诊断目录>" --require-corroboration

# 回归
python tests/test_v6_suite.py
powershell -ExecutionPolicy Bypass -File tests/test_ps_lifecycle.ps1
python tests/check_boundaries_v6.py          # 复核方四个边界夹具的 v6 输出
```

managed Python 3.13 无 numpy；三个工具都不依赖 numpy。
`test_ps_lifecycle.ps1` 只在 `%TEMP%` 的一次性副本上运行，从不写生产文件。

## 退出码

| 工具 | 0 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|
| wii v6 | OK | INSUFFICIENT_LOAD | SKEWED | LOADED_NOT_STATIONARY | NO_ELIGIBLE_WINDOW | UNKNOWN_EVIDENCE | | SOURCE_CLOCK_UNAVAILABLE | | |
| latency v5 | NO_STEP | | STEP_DETECTED | DOMAIN_ERROR | | SELF_TEST_FAILED | | | | |
| closure v6 | 全部闭合 | | | | | | 存在未闭合 | `--require-corroboration` 下有证据不足 | | |
| apply v6 | 成功/幂等 | | | | 状态不可验证 | 备份哈希不符 | 收据目录不可写 | 目标路径不符 | 收据不可读且无可恢复 | 已改文件但收据未提交 |
| revert v6 | 成功 | | | | | | | 目标路径不符 | 收据不可读且无可恢复 | 无法隔离损坏收据 |

`exit 12` 的语义是**恢复待办**，不是成功：目标文件已被替换且已验证，但 committed 收据没写成，
pending 仍保留。再跑一次同一脚本即可提交；在此之前不要把它当作已应用。

## 明确未验证（不要当已验收）

1. **C# 未编译**。两个 apply 脚本只做锚点唯一性、哈希收据与文件级替换；Unity 编译、运行时
   行为、`VectorStyleKey` 的等价性都没有被验证过。
2. **Patch 2 的“像素一致”仍是断言**，没有截图 diff，也没有重测分配量；`19.4 KB/frame` 需要在
   接收器 21:16 改动后重测。
3. **Patch 1 的重传时序是协程序列**（+120 ms、+360 ms 名义值），场景卸载或进程退出后不会
   继续发送；它不修复 4.2 s 级的接收黑障。
4. **Patch 5 仍是描述性检查**。`wii_control_timestamp` 连续只说明板端采样没断，不等于协议
   标定流程真的执行过；`wii_cop_preflight_v6.py` 不会因此给出“标定有效”的结论。
5. **收据失败路径是文件系统级注入**（把 `patch_receipt.json.tmp` 预先建成目录，使临时写入
   必然失败），不是真实的磁盘写满或 ACL 事故回放。注入点与真实失败点相同（都在 committed
   收据写入这一侧），但“磁盘满时 NTFS 的具体错误码”没有被覆盖。

## 三条必须保留的口径

- **90 个分组不是 90 次模型报警。** 它是按 (run, 通道, 层级, 平台实例, 版本) 切分并按时间/
  序号连续性合并后的描述性计数，既不是橙/紫两色被试可见告警日志，也不是误报率分母。
- **P01 的 09:28:57（缺 76 包）与 09:52:25（缺 50 包）是此前已记录的早期运行**，不能据此推断
  后续 P02 仍有同样的终局故障。P02 四局终局完整、诊断交叉核对一致（`corroborated`）。
- **本轮没有新增模型实验，也没有新采板数据。** 三条边界都是工具缺陷，不需要用更多数据来“证明”。
