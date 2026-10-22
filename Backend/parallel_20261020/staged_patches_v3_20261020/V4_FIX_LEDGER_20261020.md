# v3 → v4 修复账本与复核（2026-10-20）

对照对象：`parallel_20261020/staged_v2_review/REPORT.md`
性质：只改离线工具与打包安全机制。**Unity 源码、正常游戏构建、模型与阈值全部未动。**

生产文件核对（复核前后一致，未被任何脚本触碰）：

| 文件 | SHA-256 | mtime |
|---|---|---|
| `Assets/BackEnd/UDPManager.cs` | `096c5ffa…35a90` | 2026-10-08 16:01 |
| `Assets/Endness Falling/Scripts/UIManager.cs` | `03c9765e…b488` | 2026-10-19 16:32 |

---

## 一、你列出的 6 项，逐条复现结论

| # | 你的发现 | 复现 | 处置 |
|---|---|:---:|---|
| 1 | 备份/回滚可复用旧备份、强制覆盖丢代码 | **成立** | 已改为收据绑定 + 篡改拒回滚 + 可选归档 |
| 2 | Patch1 实际 +120/+480，且不保证退出后发送 | **成立** | 已改 `{0.12, 0.24}`，文档写明协程边界 |
| 3 | Patch2 用 32 位整数哈希当身份 | **成立** | 已改 `VectorStyleKey` 强类型值键 |
| 4 | Patch3 默认排除完成局 | **成立，且更严重** | 已改为默认全含，排除必须显式并逐条报告 |
| 5 | Patch4 测的是接收延迟；100 ms 阶跃漏检 | **成立** | 已重写检测；另发现它会在真实数据上误报 |
| 6 | Patch5／闭环审计有效性不足、推测写成原因 | **成立** | 已补真实列名、逐样本校验、中性标签 |

`reproduce.py` 的四条断言我原样跑过，输出与你的报告一致（跨 run 合并为 1、显式 CLEAR 仍为 1、100 ms 阶跃 `step_detected=false`、Wii 无证据仍 `OK`）。

---

## 二、你的报告没提到、但同样致命的三处

### 2.1 Patch5 读错了列名，所谓"标志校验"从未执行

v3 读 `control_valid` / `board_loaded` / `center_applied`，CSV 里实际叫 `wii_control_valid` / `wii_board_loaded` / `wii_center_applied`。三次 `r.get()` 全部返回 `None`，于是：

```python
valid.append(_truthy(c_val) if c_val is not None else True)   # 永远 True
```

实测 `session_20261020_101929`：v3 报告的 `loaded=True` 是 **5685/5685**，而 CSV 里 `wii_board_loaded=False` 有 **476 行**。也就是说 v3 宣称的"逐样本有效载荷校验"是空转。

v4 读真实列名并记录"哪些标志列真的存在"，同时加 `wii_control_age_seconds` 和 `wii_center_generation` / `wii_controller_instance_id` 一致性检查。同一会话现在报告 `ineligible_rows: {"flag_false": 476}`，窗口从 0 移到 75。

### 2.2 Patch4 修好漏检后，会在真实数据上误报

v3 加了流内检测之后，`session_20261019_161529` 变成 `STEP_DETECTED 139 ms`——但那是已知的 ~500 ms 长帧造成的**瞬时爆发**，不是时延阶跃（该会话七段中位数极差只有 0.317 ms）。同一个会话在 v2 里是 `NO_STEP`。

原因：v3 比较相邻 25 样本中位数，长帧期间 ~30 个高延迟包足以推动中位数 139 ms。

v4 要求阶跃**持续**：四个连续块 `left2 | left | right | later`，只有当两侧各自稳定（`|left-left2|` 与 `|right-later|` 都 ≤ 5 ms）且左右不同，才计为阶跃。burst 的上升沿 `right` 抬高而 `later` 回落，下降沿 `left` 抬高而 `left2` 正常，两边都过不了稳定性检查。

结果：`161529` 回到 `NO_STEP`，同时把 204 ms 的瞬时尖峰单独作为描述量报出。

### 2.3 真正的时钟阶跃在 `source − geometry`，而且每次长帧跳一次

v3 把 `source_ts − geom_ts` 的中位数当"偏移"打印，得到 1 792 397 728 s —— 那是 Unix 历元与相对时钟原点的距离，不是对齐误差。但把这条差值的**变化**画出来，得到的是阶梯：

```
row 1124   +171.7 ms   source gap 511.0 ms   ← 长帧
row 2135   +148.3 ms   source gap 487.0 ms   ← 长帧
row 3145   +164.2 ms   source gap 503.0 ms   ← 长帧
row 4167   +150.7 ms   source gap 484.0 ms   ← 长帧
row 5173   +139.2 ms   source gap 488.0 ms   ← 长帧
row 6177   +174.7 ms   source gap 508.0 ms   ← 长帧
累计 948.8 ms / 90 秒
```

每一次长帧，`geometry_source_timestamp` 相对 `source_timestamp` 永久后退 139–175 ms，六次累计 949 ms。

对照 `session_20261020_102222`（无长帧）：**0 次跳变，去趋势极差 21.1 ms**。

这条比 v1 当年猜的"长帧导致时钟阶跃"更精确：**阶跃不在 `backend − source`（那里七段只差 0.317 ms），而在 `source − geometry`**。任何把几何时钟与遥测时钟混用的提前量计算，误差会随时间累积到接近 1 秒。

v4 把它做成可检查项：`discrete_jumps`、`cumulative_drift_ms`、`single_global_offset_sufficient=false`。

---

## 三、Patch3 的通道切分不是潜在问题，已经影响 P02

v3 只按时间间隔 / run / platform 切分。加上通道后：

| 数据集 | v3 | v4 | 差异 |
|---|---:|---:|---|
| P02（4 局） | 82 | **90** | 8 个事件此前被并进别的通道 |
| P01（27 局） | — | 87 | 62 attention / 15 edge geometry / 10 edge_warning_state |

P02 的 8 个被合并事件里，7 个是 `unity_edge_geometry`、1 个是 `edge_warning_state`。

另外，CSV 里确实有 `warning_episode_id`，但它不能当事件身份：`session_20261020_102222` 中该字段在几十次 attention 开关期间一直停在 `0`，同一个 id 还同时覆盖 `ATTENTION` 和 `STRONG` 两类行。v4 只把它记录成 `unity_episode_ids` 供交叉核对，不用作切分键。

---

## 四、安全机制：沙箱实测通过

四个脚本 PowerShell 语法解析均无错误。在**临时副本**上跑完整生命周期：

| 步骤 | 期望 | 实测 |
|---|---|---|
| 首次 apply（哈希匹配基线） | 写入 + 建收据 | exit 0，post hash `D149…` |
| 再次 apply | 校验收据而非子串 | exit 0，"receipt hash matches" |
| 手工改一行后 revert | 拒绝 | exit 1，"Refusing to restore" |
| revert `-SaveCurrentFirst` | 先归档再恢复 | exit 0，归档 `…edited_…C6F4…bak`，目标回到 `096c…` |
| 生产文件 | 未被触碰 | `096c5ffa…` / `03c9765e…`，mtime 未变 |

---

## 五、仍未验证的部分（不要当成已验收）

1. **没有编译过**。C# 改动只做了锚点唯一性、写后子串校验和哈希收据，没有经过 Unity 编译。收据里也写的是结构校验，不是编译通过。
2. **Patch2 的"像素一致"没有做截图 diff**。代码层面五处污染点已处理、缓存键有界（`UiAlpha` 是 `const 0.85f`，不会逐帧换色），但渲染一致性仍需 A/B 截图。
3. **分配量没有重测**。`19.4 KB/frame` 来自 15:51 那份捕获；接收器在 21:16 改过，当前分配排名需要重测才能决定优先级。
4. **Patch1 仍然是 DEFERRED**。P02 四局终局全部落盘，没有证据支持现在引入重传。

---

## 六、复跑命令

```powershell
$py = "C:\Users\QIYUXUAN\AppData\Local\Microsoft\WindowsApps\python.exe"
$v3 = "C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\parallel_20261020\staged_patches_v3_20261020"

& $py "$v3\tests\test_v4_suite.py"                                  # 30 项回归
& $py "$v3\patch_3_warning_episodes\cluster_warning_episodes_v4.py" --csv ..\..\telemetry_logs\P02
& $py "$v3\patch_4_clock_profile\receive_latency_profile_v4.py" --self-test
& $py "$v3\patch_4_clock_profile\receive_latency_profile_v4.py" --csv ..\..\telemetry_logs\P01\session_20261019_161529_760840\raw.csv
& $py "$v3\patch_5_wii_preflight\wii_cop_preflight_v4.py" --csv ..\..\telemetry_logs\P02\session_20261020_101929_120829\raw.csv
& $py "$v3\tools\session_closure_audit_v4.py" --root ..\..\telemetry_logs\P01 --diag-dir "$env:LOCALAPPDATA..\..\LocalLow\QI YUXUAN\VectorAI\EndlessFallingDiagnostics"
```

`session_closure_audit_v4.py` 在存在未闭环会话时返回 7。这是有意的门槛，不是错误。
