# staged_patches_v5_20261020 — 离线工具与补丁安全边界修复包

针对 `parallel_20261020/staged_v4_review/REPORT.md` 中列出的 5 类剩余问题，以及 v4 遗留的
两处口径问题。**生产代码零改动**：Unity 两个目标文件哈希与 mtime 均未变，本包不应用任何
Unity 补丁，也不需要重新上板。

- `UDPManager.cs` `096C5FFA591E8B5D98B24F51BA4902D8E4C38699C36301589D7B512C3EB35A90`
- `UIManager.cs`  `03C9765ED598D19F6721F851F9CF378808ED0056AAB7FAC905CCD9B9D240B488`

## 目录

```
staged_patches_v5_20261020/
├── README.md                                  本文件
├── V5_FIX_LEDGER_20261020.md                  逐条修复账本（反例→修复→复跑结果）
├── patch_1_terminal_delivery/
│   ├── apply.ps1                              目标绑定 + pending/commit 收据
│   └── revert.ps1                             目标绑定 + 备份先验哈希
├── patch_2_uimanager_style_cache/
│   ├── apply.ps1                              同上；补丁体与 v4 相同
│   └── revert.ps1
├── patch_3_warning_episodes/
│   └── cluster_warning_episodes_v5.py         平台/版本身份 + 顺序反转切分 + 透传 seq-tolerance
├── patch_4_clock_profile/
│   └── receive_latency_profile_v5.py          全局偏移充分性改为预声明规则，默认 UNKNOWN
├── patch_5_wii_preflight/
│   └── wii_cop_preflight_v5.py                缺失证据 → UNKNOWN_EVIDENCE，时间必须单调递增
├── tools/
│   └── session_closure_audit_v5.py            诊断冲突可推翻 VALIDATED；证据四态
└── tests/
    ├── test_v5_suite.py                       38 项 Python 对抗性回归
    └── test_ps_lifecycle.ps1                  54 项 PowerShell 生命周期回归（一次性副本）
```

## 运行

```bash
# 三个离线工具直接跑，无需安装
python patch_5_wii_preflight/wii_cop_preflight_v5.py --csv <raw.csv>
python patch_4_clock_profile/receive_latency_profile_v5.py --csv <raw.csv>
python patch_3_warning_episodes/cluster_warning_episodes_v5.py --csv <dir 或 raw.csv>
python tools/session_closure_audit_v5.py --root telemetry_logs/P02 --diag-dir "<诊断目录>"

# 回归
python tests/test_v5_suite.py
powershell -ExecutionPolicy Bypass -File tests/test_ps_lifecycle.ps1
```

环境说明：managed Python 3.13 无 numpy；v5 三个工具**不依赖 numpy**，用任一解释器均可。
`test_ps_lifecycle.ps1` 只在 `%TEMP%` 的一次性副本上运行，从不写生产文件。

## 退出码

| 工具 | 0 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| wii v5 | OK | INSUFFICIENT_LOAD | SKEWED | LOADED_NOT_STATIONARY | NO_ELIGIBLE_WINDOW | UNKNOWN_EVIDENCE | | | |
| latency v5 | NO_STEP | | STEP_DETECTED | DOMAIN_ERROR | | SELF_TEST_FAILED | | | |
| closure v5 | 全部闭合 | | | | | | 存在未闭合 | | |
| apply v5 | 成功/幂等 | | | | 状态不可验证 | 备份哈希不符 | 收据写失败 | 目标路径不符 | 替换后状态未知 |

## 明确未验证（不要当已验收）

1. **C# 未编译**。两个 apply 脚本只做锚点唯一性、哈希收据与文件级替换；Unity 编译、运行时
   行为、`VectorStyleKey` 的等价性都没有被验证过。
2. **Patch 2 的“像素一致”仍是断言**，没有截图 diff，也没有重新测分配量。
   `19.4 KB/frame` 来自 15:51 那次捕获，接收器在 21:16 改过，分配排名需要重测。
3. **Patch 1 的重传时序是协程序列**（+120 ms、+360 ms 名义值），场景卸载或进程退出后不会
   继续发送；它不修复 4.2 s 级的接收黑障。
4. **Patch 5 仍是描述性检查**。一个“有载重且静止”的窗口不等于协议标定流程真的执行过。

## 两条必须保留的口径

- **90 个分组不是 90 次模型报警。** 它是按 (run, 通道, 层级, 平台实例, 版本) 切分并按时间/
  序号连续性合并后的描述性计数，既不是橙/紫两色被试可见告警日志，也不是误报率分母。
- **P01 的 09:28:57（缺 76 包）与 09:52:25（缺 50 包）是此前已记录的早期运行**，不能据此推断
  后续 P02 仍有同样的终局故障。P02 四局终局完整、诊断交叉核对一致（evidence=corroborated）。
