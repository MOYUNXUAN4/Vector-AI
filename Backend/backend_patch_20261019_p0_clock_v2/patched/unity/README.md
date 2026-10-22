# FrameClockProbe — 500 ms stall investigation

## 为什么需要它

现有诊断里的 `frame_delta_time_ms` 来自 `Time.deltaTime`，被 Unity 的
`Time.maximumDeltaTime`（默认 **0.3333 s**）截断。今天 5 个 run 的该字段最大值
全部是 **333.3333 ms**，而 CSV 的 epoch 时间戳显示真实缺口是 **485–515 ms**。
也就是说：当前量具**看不到**长帧的真实长度。

这个探针每帧记录墙钟差，`wall_ms - delta_ms` 就是被截断隐藏的那部分。

## 安装

1. 把 `FrameClockProbe.cs` 复制到 Unity 工程的任意 `Assets/` 子目录（例如
   `Assets/Endness Falling/Scripts/`）。
2. 不需要改场景、不需要挂组件：`[RuntimeInitializeOnLoadMethod]` 会在第一个场景
   加载后自动创建一个 `DontDestroyOnLoad` 对象。

## 输出

```
%USERPROFILE%\AppData\LocalLow\<company>\<product>\FrameClockProbe\frames_<UTC时间>.jsonl
```

每行：

```json
{"frame":1234,"realtime_s":82.551,"unity_time":82.218,"delta_ms":333.333,
 "wall_ms":500.412,"clamped_ms":167.079,"gc_bytes":12345678,"stall":true}
```

- `wall_ms`：两帧之间的真实墙钟差；
- `delta_ms`：Unity 报告的 `Time.deltaTime`（被截断）；
- `clamped_ms`：被 `maximumDeltaTime` 隐藏的毫秒数；
- 只记录 `wall_ms >= 50`、`clamped_ms >= 20` 或每 120 帧一次心跳，文件很小；
- 单次 `wall_ms >= 400` 会立即 flush，避免进程被杀时丢证据。

## 怎么读

1. 找 `wall_ms >= 400` 的行，记下 `realtime_s` / `unity_time` / `frame`。
2. 同一行的 `delta_ms` 若仍是 333.3，说明确实是长帧而不是两帧合并上报。
3. 往前看 5–10 行的 `gc_bytes`：若在长帧前突增，优先怀疑 GC。
4. 若 `gc_bytes` 平稳、`clamped_ms` 大，则阻塞在别处（场景/资源加载、渲染、
   同步 I/O），需要 Profiler 标记继续定位。

## 注意

- 这是**诊断**，不改玩法、不改物理、不改任何现有脚本；调查结束后删除即可。
- 它只在 Editor/Development Build 里有意义；正式构建也可以保留，开销约为每帧
  两次 `Time` 读取 + 每秒一行写入。
- 不要用它替代 `frame_delta_time_ms` 的现有记录；两者并存才能看出截断。
