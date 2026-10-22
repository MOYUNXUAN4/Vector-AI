# P0 时钟阶跃与离线对齐独立补丁包 (v2)

**更新时间**：2026-10-19  
**补丁属性**：独立、只读、零侵入（Non-invasive Standalone Patch）  
**作用目标**：解决 Unity 引擎 485–505 ms 长帧卡顿遭遇 `Time.maximumDeltaTime` (333.3 ms) 截断后产生的 **+0.15s ~ +0.50s 时钟阶跃（Step Jump）** 及对离线提前量评估的系统性污染。

---

## 1. 为什么需要这个补丁？

在长帧发生时，Unity 的 `Time.time` 以为只过了 0.333 秒，而真实墙钟（DateTimeOffset / Epoch）已经过了 0.5 秒，导致：
1. **时钟阶跃**：两者 Offset（墙钟 - 游戏时钟）在卡顿点瞬间跳动 0.16 秒以上；
2. **评估被污染**：原离线分析脚本（如 `prepare.py`）采用“整局单一中位数 Offset”对齐时序，导致阶跃点之后的所有事件时间戳发生 0.15~0.5 秒的系统性平移，彻底破坏了对 0.4 秒提前量的评判；
3. **盲窗放大**：0.5 秒缺口触发了后端的 0.1 秒熔断，重置并进入 0.5 秒预热期（Warmup），累计产生 1.0 秒无预测盲窗（超出 0.75 秒预测视界）。

---

## 2. 补丁目录结构

```
backend_patch_20261019_p0_clock_v2/
├── patched/
│   ├── tools/
│   │   ├── clock_alignment.py       # 核心算法库：分段连续 Offset 估计、阶跃/缺口/漂移检测、双时钟映射
│   │   └── clock_offset_audit.py    # 命令行工具：raw.csv 审计、时钟跳变诊断、事件表重定时
│   ├── tests/
│   │   └── test_clock_alignment.py  # 14 项完整单元回归测试（覆盖全部边界条件）
│   └── unity/
│       ├── FrameClockProbe.cs       # 可选 Unity 探针：每帧记录真实墙钟与 deltaTime，暴露被截断的毫秒与 GC
│       └── README.md                # 探针使用说明（零场景改动，放置即可）
├── evidence/
│   ├── clock_offset_report.md       # 今天 10 个 Session 的完整时钟偏移审计报告
│   ├── clock_offset_report.json     # 10 个 Session 审计明细 JSON
│   ├── demo_events.csv              # 测试事件输入样例
│   └── demo_events_remapped.csv     # 修复后的事件输出样例（带 N/A 标注）
├── verify_p0_v2.py                  # Python 一键验证脚本
├── verify_patch.cmd                 # Windows 双击运行验证脚本
├── audit_session.cmd                # 拖拽 raw.csv 一键审计脚本
├── REVIEW_P0_V2.md                  # 详细技术审阅与漏洞修复备忘
├── SHA256SUMS.json                  # 文件哈希校验单
└── PATCH_README.md                  # 本说明文档
```

---

## 3. 核心功能与使用方法

### 3.1 一键运行补丁自检与验证
双击 `verify_patch.cmd` 或在终端运行：
```powershell
python verify_p0_v2.py --csv "..\telemetry_logs\P01\session_20261019_105632_058608\raw.csv"
```
> **通过指标**：14 项单测全部 `OK`，P01 会话输出 `STEPPED range=0.162s drift=0.019s steps=1 gaps=1`，且无任何源文件被修改。

---

### 3.2 审计任意受试者会话（排查是否有阶跃/缺口）
你可以直接把任意 `raw.csv` 拖拽到 `audit_session.cmd` 上，或执行命令：
```powershell
python patched\tools\clock_offset_audit.py "..\telemetry_logs\<受试者>\<Session>\raw.csv"
```
终端会明确输出：
- `CLEAN`：时钟干净，无阶跃、无缺口；
- `STEPPED`：发现时钟阶跃，并定位具体的物理 CSV 行号与 Unity 发生时间；
- `GAPPED` / `DRIFTED`：识别出单纯的数据缺口或段内漂移。

---

### 3.3 对离线事件表重定时（将盲窗标为 N/A）
```powershell
python patched\tools\clock_offset_audit.py <raw.csv> --events events.csv --events-out fixed.csv --warmup-seconds 0.5
```
输出的 `fixed.csv` 会增加以下关键列：
- `mapped_epoch` / `mapped_unity`：分段对齐后的精确时间戳；
- `segment_index`：所属连续稳定段序号；
- `ambiguous`：布尔值（是否跨越盲窗或受阶跃影响）；
- `coverage_status`：
  - `lead_available`：处于稳定段，提前量 100% 真实可靠；
  - `n_a_ambiguous`：落入缺口或 0.5s 预热期内，**保留在全量覆盖分母中，但不强算提前量**。

---

### 3.4 可选：安装 Unity 探针排查 500ms 根因
如果你需要在 Unity 运行时进一步捕捉这 500ms 是发生在 GC 还是平台生成：
1. 将 `patched/unity/FrameClockProbe.cs` 复制进 Unity 工程的任意 `Assets/` 目录下；
2. **无需挂载任何场景对象**（代码包含 `RuntimeInitializeOnLoadMethod` 自动装载）；
3. 运行后日志自动输出至：  
   `%USERPROFILE%\AppData\LocalLow\<公司>\<产品>\FrameClockProbe\frames_*.jsonl`  
   记录了每帧的 `wall_ms`、`delta_ms`、`clamped_ms`（被 Unity 隐藏的时间）和 `gc_bytes`。
4. 调查完毕后直接从 Unity 工程中删除该脚本即可，零残留。

---

## 4. 诚信与学术规范

1. **零文件破坏**：不改写原数据库或 CSV，所有测试前后源码 Hash 保持一致；
2. **拒绝粉饰指标**：绝不通过删除不确定事件来人为拉高模型准确率；
3. **独立分轨**：分析工具与生产代码解耦，确保 D7 评审与历史对照实验的可追溯性。
