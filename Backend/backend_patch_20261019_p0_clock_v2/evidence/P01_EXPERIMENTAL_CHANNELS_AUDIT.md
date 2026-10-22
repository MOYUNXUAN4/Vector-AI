# P01 真实实验预警通道审计报告 (Purple TTE & Orange LightGBM)

**审计日期**：2026-10-19  
**数据范围**：受试者 P01 全部 10 局会话（`telemetry_logs/P01`）  
**评估约束**：原始数据 0 修改（`sources_unchanged: True`），不改动模型/阈值/玩法，只读分析。

---

## 1. 核心纠正确认

对此前测试脚本及统计口径的 6 处重大偏差进行彻底纠正与核实：

1. **预警通道**：`raw.csv` 中的 `visible_warning_state` 和 `warning_source` 确系 Unity 原生黄色注意力规则（`unity_attention_rule`）与红色几何规则（`unity_edge_geometry`）。真正的实验通道为：
   - **紫色 TTE 几何邻近预警**：记录于 `proximity_shadow.jsonl`（414 条 active 记录，与 CSV sequence 100% 吻合）及 Unity 客户端 `[ExperimentalProximityWarning]`；
   - **橙色 LightGBM 模型预警**：记录于 Unity 客户端 `[ExperimentalModelWarning]`（42 条 active 记录）。
2. **提前量口径**：从首次 onset 全面更正为**最后一次合格 onset（last qualifying onset）**。
3. **时钟映射**：从“映射单个时间点”更正为**区间映射（`map_interval(t_warn, t_anchor)`）**。凡跨越 0.5s 长帧缺口或时钟阶跃跳变的区间，严格判定为 `n_a_ambiguous`。
4. **工具边界消除**：消除结局行触碰段末导致的 `near_segment_boundary` 误报；终局行仅作为锚点，不作为受检事件计入分母。
5. **结局锚点去重**：每局唯一终局锚点共 10 个（5 个通关、4 个坠出、1 个电池松动退出），消除同一帧 fall 与 outcome 重复计数。
6. **双时钟毫秒级提前量与哈希核验**：对全部 10 局 `raw.csv` 及 shadow 日志完成 SHA-256 校验，确认 100% 原始未动；提供 Unity 时钟与 Unix 墙钟双时钟毫秒计算。

---

## 2. 实验通道审计结果汇总

### 通道一：紫色 TTE 几何邻近预警 (`ExperimentalProximityWarning`)

| 会话 (Session) | 终局性质 (Anchor) | 最后 Onset ($t_{\text{warn}}$) | 终局锚点 ($t_{\text{anchor}}$) | Unity 提前量 | Epoch 提前量 | 区间判定 | 判定原因 / 保护机制 |
|---|---|---:|---:|---:|---:|---|---|
| 10:56:32 | calibration_completed | 25.075 s | 39.800 s | 14.725 s | 14.886 s | **N/A** | `interval_crosses_gap, step` (跨越L1长帧缺口) |
| **10:56:56** | **edge_exit (坠出)** | **53.467 s** | **54.742 s** | **1.275 s** | **1.279 s** | **available** | 时钟平稳连续，提前量 $\ge 0.4\text{ s}$ |
| **10:57:12** | **edge_exit (坠出)** | **70.003 s** | **71.536 s** | **1.533 s** | **1.688 s** | **N/A** | `interval_crosses_gap, step` (跨越0.494s缺口+板子卸载) |
| 10:57:34 | user_exit (电池松动) | – | 85.181 s | – | – | **排除** | 用户确认电池松动异常退出，不入正常分母 |
| **10:59:12** | **edge_exit (坠出)** | – | 8.277 s | – | – | **系统限制** | 局长仅 4.4s，处于模型冷启动 warmup 期 |
| 10:59:22 | calibration_completed | 34.016 s | 36.217 s | 2.201 s | 2.202 s | **available** | 缺口发生在靠前时段，终局靠边段干净可用 |
| 10:59:51 | calibration_completed | 56.417 s | 64.588 s | 8.171 s | 8.163 s | **available** | 缺口发生在靠前时段，终局靠边段干净可用 |
| 11:00:23 | calibration_completed | 96.069 s | 96.395 s | 0.326 s | 0.325 s | **available** | 时钟连续干净，但提前量 0.326s < 0.4s 门槛 |
| **11:00:55** | **edge_exit (坠出)** | **104.562 s** | **105.766 s** | **1.205 s** | **1.206 s** | **available** | 时钟平稳连续，提前量 $\ge 0.4\text{ s}$ |
| 11:01:07 | calibration_completed | 130.355 s | 133.836 s | 3.482 s | 3.483 s | **available** | 缺口发生在靠前时段，终局靠边段干净可用 |

---

### 通道二：橙色 LightGBM 模型预警 (`ExperimentalModelWarning`)

| 会话 (Session) | 终局性质 (Anchor) | 最后 Onset ($t_{\text{warn}}$) | 终局锚点 ($t_{\text{anchor}}$) | Unity 提前量 | Epoch 提前量 | 区间判定 | 判定原因 / 保护机制 |
|---|---|---:|---:|---:|---:|---|---|
| 10:56:32 | calibration_completed | 25.075 s | 39.800 s | 14.725 s | 14.886 s | **N/A** | `interval_crosses_gap, step` (跨越L1长帧缺口) |
| **10:56:56** | **edge_exit (坠出)** | **53.822 s** | **54.742 s** | **0.920 s** | **0.925 s** | **available** | 时钟平稳连续，提前量 $\ge 0.4\text{ s}$ |
| **10:57:12** | **edge_exit (坠出)** | **70.351 s** | **71.536 s** | **1.185 s** | **1.340 s** | **N/A** | `interval_crosses_gap, step` (跨越0.494s缺口+板子卸载) |
| 10:57:34 | user_exit (电池松动) | – | 85.181 s | – | – | **排除** | 用户确认电池松动异常退出，不入正常分母 |
| **10:59:12** | **edge_exit (坠出)** | – | 8.277 s | – | – | **系统限制** | 局长仅 4.4s，处于模型冷启动 warmup 期 |
| 10:59:22 | calibration_completed | 34.344 s | 36.217 s | 1.873 s | 1.874 s | **available** | 缺口发生在靠前时段，终局靠边段干净可用 |
| 10:59:51 | calibration_completed | 56.829 s | 64.588 s | 7.758 s | 7.750 s | **available** | 缺口发生在靠前时段，终局靠边段干净可用 |
| 11:00:23 | calibration_completed | 83.446 s | 96.395 s | 12.949 s | 12.949 s | **available** | L1 预警在过关后撤销，终局前无新预警 |
| **11:00:55** | **edge_exit (坠出)** | **104.859 s** | **105.766 s** | **0.907 s** | **0.908 s** | **available** | 时钟平稳连续，提前量 $\ge 0.4\text{ s}$ |
| 11:01:07 | calibration_completed | – | 133.836 s | – | – | **无预警** | 本局模型未激活 STRONG 预警 |

---

### 对照基线：原黄色注意力规则 (`unity_attention_rule` / visible_warning_state)

| 会话 (Session) | 终局性质 (Anchor) | 最后 Onset ($t_{\text{warn}}$) | 终局锚点 ($t_{\text{anchor}}$) | Unity 提前量 | 区间判定 | 判定原因 |
|---|---|---:|---:|---:|---|---|
| 10:56:32 | calibration_completed | 36.435 s | 39.800 s | 3.365 s | **available** | 段内连续干净 |
| 10:56:56 | edge_exit (坠出) | 52.682 s | 54.742 s | 2.060 s | **available** | 段内连续干净 |
| 10:57:12 | edge_exit (坠出) | 70.057 s | 71.536 s | 1.479 s | **N/A** | 跨越 0.494s 长帧缺口及阶跃 |
| 10:57:34 | user_exit (电池松动) | – | 85.181 s | – | **无预警** | – |
| 10:59:12 | edge_exit (坠出) | 5.753 s | 8.277 s | 2.524 s | **available** | 几何规则无 warmup 限制，直接触发 |
| 10:59:22 | calibration_completed | 32.917 s | 36.217 s | 3.300 s | **available** | 段内连续干净 |
| 10:59:51 | calibration_completed | 61.016 s | 64.588 s | 3.572 s | **available** | 段内连续干净 |
| 11:00:23 | calibration_completed | 94.564 s | 96.395 s | 1.831 s | **available** | 段内连续干净 |
| 11:00:55 | edge_exit (坠出) | 104.828 s | 105.766 s | 0.939 s | **available** | 段内连续干净 |
| 11:01:07 | calibration_completed | 131.767 s | 133.836 s | 2.069 s | **available** | 段内连续干净 |

*(注：基线数据与用户复核表 100% 吻合：7/8 可用，1 N/A，1 无预警)*

---

## 3. 4 次真实坠出事件深度对比 (关键安全性能)

在研究协议中最核心的坠出预警评估中，4 次真实坠出的表现如下：

1. **10:56:56 坠出局**：
   - 时钟质量：整局极度干净，offset 全程跨度仅 0.004 秒，无任何长帧缺口。
   - **黄色 Attention**：提前 **2.060 s** 预警；
   - **紫色 TTE Proximity**：提前 **1.275 s** 预警（远大于 0.4s 门槛）；
   - **橙色 LightGBM**：提前 **0.920 s** 预警（远大于 0.4s 门槛）；
   - 结论：**三大通道全部给出了有效、充裕的提前量，成功命中**。

2. **10:57:12 坠出局**：
   - 时钟与设备：靠边过程中遭遇 Unity 494 ms 长帧阻塞，Unity 时钟与墙钟产生 +0.155 s 阶跃跳变，且板子在终局前发生卸载/去中心化。
   - 警告区间 $[70.00, 71.54]$ 跨越了该缺口与时钟跳变点。
   - 结论：**时钟与输入双重失效，提前量被污染。严格标为 N/A（时序不确定），保留在分母中，不作为模型漏检，也不作为有效命中**。

3. **10:59:12 坠出局**：
   - 时钟质量：时钟本身平稳（跨度 0.014 s）。
   - 局况：该局极短（仅 4.404 秒），属于刚开局的冷启动/校准期，尚未满足模型 0.5s 因果历史要求（shadow 状态全部为 `unsupported_or_calibration_phase`）。
   - 结论：**单独报告为系统覆盖范围限制（System Coverage Limitation）。不强行归因于预测器漏检，但保留在覆盖范围分母中**。

4. **11:00:55 坠出局**：
   - 时钟质量：整局极度干净，offset 全程跨度仅 0.004 秒，无任何长帧缺口。
   - **黄色 Attention**：提前 **0.939 s** 预警；
   - **紫色 TTE Proximity**：提前 **1.205 s** 预警（远大于 0.4s 门槛）；
   - **橙色 LightGBM**：提前 **0.907 s** 预警（远大于 0.4s 门槛）；
   - 结论：**三大通道全部给出了有效、充裕的提前量，成功命中**。

---

## 4. 数据完整性校验哈希 (SHA-256)

所有 10 份原始 `raw.csv` 文件的 SHA-256 哈希值与初检记录完全一致，无一字节篡改：

| Session | File Size (Bytes) | SHA-256 Hash |
|---|---:|---|
| session_20261019_105632_058608 | 2,217,833 | `bea008eedc3ae1253b48faec2cf07532e1679ed043effd96c95d7220914caff6` |
| session_20261019_105656_285619 | 1,371,533 | `7ed67cbdfbb5f4c72988ec4fb5ac63d2391c7488d41f0230a8efa8deb6eb1946` |
| session_20261019_105712_007803 | 1,661,002 | `667478e03cbd24f195cf79a900c8dc6f43e55f5f6e18383147eb76d11c43f1ec` |
| session_20261019_105734_310716 | 2,014,102 | `1f9d817c1fef1b9f5810ff6d0c7aebc3e5e5a489decd5f383c295b4bc4446831` |
| session_20261019_105912_781089 | 615,187 | `38efd5a00f53123ea4bfb2959462b3a27dcbd4aa3312b87e9f59af6c7e9906b7` |
| session_20261019_105922_291656 | 2,732,645 | `c3d3a4de42a203dddedb8161d78cef57d2e7eeba3f284a9738642c75685d51f0` |
| session_20261019_105951_117357 | 2,949,867 | `5c578a374e2e6ed009d9d78c12ea1efa6dfba69b14eda4c23769110888a19733` |
| session_20261019_110023_567130 | 3,088,389 | `0dbfadd2f3ec35a4d3344f04d79e018e5a2c78ff603c528813400d2479739967` |
| session_20261019_110055_533132 | 902,719 | `673fe9180470728821dcb9c670ee2ee1fd17202c1bc45f578ba159d27fd35bed` |
| session_20261019_110107_096491 | 6,215,841 | `24c0c99de265c123f4e8ccfe946ea556c3b1e3d9c5a4990fdb615009c01c9426` |
| `proximity_shadow.jsonl` | 65,239,295 | `ee36945eedf921f08bc79e658fe84f0fb9fba3fe61be0ee39f04aa0f0985552d` |
