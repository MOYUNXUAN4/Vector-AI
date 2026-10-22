# P0 时钟补丁包 v2 — 2026-10-19

**状态：待审阅。主目录、prepare.py、Unity 工程均未修改。**

> v1（`backend_patch_20261019_p0_clock`）已作废，请勿用于 P01 复核；保留它只为审计轨迹。本包修掉 v1 的 5 个实质漏洞。

## 1. 你指出的 5 条，逐条对应

| # | v1 的问题 | v2 的修法 | 回归测试 |
|---|---|---|---|
| 1 | 有缺口但 offset 不跳时不切段，缺口内部仍标"无歧义" | 缺口是独立的不确定区间；点/区间落入即 `in_gap` 且 `ambiguous=true`，映射值为空 | `test_gap_without_offset_step_is_not_clean`、`test_inside_gap_is_ambiguous` |
| 2 | 段内缓慢漂移未校验，累积 0.1 s 仍判 CLEAN | 每段计算 `max-min`、p05/p95；超过 `drift=0.02` 标 `drifting`，会话判 `DRIFTED`，映射带 `drifting_segment` | `test_slow_drift_is_not_clean`、`test_drifting_segment_mapping_is_ambiguous` |
| 3 | epoch 输入转换后写进 `mapped_epoch` 的其实是 Unity 时间 | 输出 `mapped_epoch` 与 `mapped_unity` 两列：epoch 输入保持 epoch，Unity 输入保持 Unity | `test_epoch_input_keeps_epoch_output`、`test_unity_input_keeps_unity_output` |
| 4 | 过滤后重编号、丢失 run 身份 | 每条样本保留**物理 CSV 行号**和 `run_id`；混 run 直接报错；CLI 按 run 分组报告 | `test_physical_line_and_run_are_kept`、`test_mixed_runs_are_rejected`、`test_group_by_run_keeps_identity` |
| 5 | 只映射时间点，没有区间检查 | 新增 `map_interval` 与事件 `unity_end`：跨阶跃、跨缺口、跨瞬态段、会话 offset 超差都标 `ambiguous` | `test_interval_crossing_step_is_ambiguous`、`test_interval_crossing_gap_is_ambiguous` |

另外按你的要求新增：**N/A 事件仍进入覆盖统计**——输出 `coverage_status = lead_available / n_a_ambiguous`，CLI 打印 N/A 数量。

## 2. 语义变化（需要知道）

| 项 | v1 | v2 |
|---|---|---|
| `offset_span` | 段中位数之间的差 | 所有样本 offset 的 `max-min`（保守） |
| 判定 | CLEAN / STEPPED / NO_GEOMETRY | CLEAN / GAPPED / DRIFTED / STEPPED / NO_GEOMETRY |
| 段内映射 | 段中位数 | 段内相邻样本**线性插值**；跨缺口不插值，取近侧 |
| 缺口 | 只记录 | 记录 epoch/unity 双区间；落入即 N/A |
| 事件输出 | 单点 | 支持 `unity_end` 区间；输出双时钟 + 原因 + 覆盖状态 |

判定优先级：有阶跃 → `STEPPED`；否则有漂移 → `DRIFTED`；否则有缺口 → `GAPPED`；否则 `CLEAN`。组件数量单独输出（`components`），不会因为一个强信号掩盖其他问题。

## 3. P01 复核（按身份 / 连续段 / 不确定区间）

```
run_id 31870bd7101e45a29d78d179f82e06f0
verdict STEPPED
offset range 0.162 s   max segment drift 0.019 s
step: +0.161 s at CSV line 1965, unity 35.541
gap : 0.510 s (epoch), unity 35.192..35.541, after CSV line 1932
segments: [4..1932] offset 1792378572.552754
          [1965..2494] offset 1792378572.708868
```

**不确定区间**（含后端 0.5 s warmup）：`unity 35.192 .. 36.041`。
落在这个区间的事件：
- `mapped_epoch` 为空；
- `coverage_status = n_a_ambiguous`；
- **仍保留在覆盖统计里**，不删除、不算漏检。

区间之外但要看清：E2（unity 36.0）在 warmup 内 → N/A；E1（30.0）可用。

## 4. 实测（10:55–11:01 的 10 个 run）

| Session | Verdict | Offset range | Drift | Steps | Gaps |
|---|---|---:|---:|---:|---:|
| P01 10:56:32 | STEPPED | 0.162 | 0.019 | 1 | 1 |
| 10:56:56 | CLEAN | 0.004 | 0.004 | 0 | 0 |
| 10:57:12 | STEPPED | 0.157 | 0.005 | 1 | 1 |
| 10:57:34 | STEPPED | 0.128 | 0.007 | 2 | 1 |
| 10:59:12 | CLEAN | 0.014 | 0.014 | 0 | 0 |
| 10:59:22 | STEPPED | 0.484 | 0.005 | 2 | 1 |
| 10:59:51 | STEPPED | 0.160 | 0.005 | 1 | 1 |
| 11:00:23 | STEPPED | 0.502 | 0.005 | 2 | 1 |
| 11:00:55 | CLEAN | 0.004 | 0.004 | 0 | 0 |
| 11:01:07 | STEPPED | 0.167 | 0.004 | 1 | 1 |

**7 STEPPED / 3 CLEAN**，与 v1 的结论一致；但行号现在是物理 CSV 行，run 身份保留。`drift` 列是 v2 新增的段内漂移：本批最大 0.019 s，未触发 0.02 阈值。

## 5. 用法

```powershell
# 单 run 审计（多个 run 会自动分组）
python tools\clock_offset_audit.py "telemetry_logs\P01\session_20261019_105632_058608\raw.csv"

# 只审计指定 run
python tools\clock_offset_audit.py <raw.csv> --run-id 31870bd7101e45a29d78d179f82e06f0

# 事件重定时，并把 gap+warmup 标成 N/A
python tools\clock_offset_audit.py <raw.csv> --events events.csv --events-out fixed.csv --warmup-seconds 0.5
```

`events.csv`：`event_id` 必填；`unity_time` 或 `epoch_time` 二选一；可选 `unity_end` 做区间检查。

输出列：`mapped_epoch, mapped_unity, segment_index, ambiguous, reasons, coverage_status`。

## 6. 验证

```
14 regression tests: OK   （5 条发现各有 2–3 个用例）
P01 10:56:32: STEPPED range=0.162s drift=0.019s steps=1 gaps=1
demo events: 1 lead_available / 3 n_a_ambiguous（全部保留）
```

`python verify_p0_v2.py --csv <raw.csv>` 可复跑。

## 7. 边界与未做

- **没有改 `prepare.py`**：按你的要求，旧结果/冻结脚本不动；接入方式见第 8 节。
- **没有装 Unity 探针**：`patched/unity/FrameClockProbe.cs` 已附上，但未复制进 Unity 工程；装不装由你决定。
- **没有改运行代码/模型/阈值/玩法**。
- `map_interval` 目前只接受 Unity 时间区间；epoch 区间只做点映射。
- 段内插值假设 offset 线性变化；若出现非线性漂移，需要滚动窗口。
- 物理行号依赖 CSV 单行记录；带换行的字段会偏移（本数据无此情况）。
- 长帧本身的根因仍未定位；本包只保证"不确定的地方标出来、不被算进提前量"。

## 8. 接进现有分析（不替换 prepare.py）

在 `prepare.py` 之外新增一个后处理：读 `features.csv` / `event_anchors.csv`，用
`clock_alignment` 按段重算 `qtime`，把 `ambiguous` 的事件写成 N/A 列，保留原文件。
建议字段：`event_id, run_id, unity_time, unity_end, mapped_epoch, ambiguous, reasons, coverage_status`。

这样旧结果可复算而不被覆盖，P01 的 N/A 事件也仍进入覆盖统计。
