// FrameStallAutoCapture.cs — 独立只读诊断工具（Editor-only，不入构建）
// 来源：parallel_20261019/profiler_capture_review/auto_capture_v2.cs.txt（V2 审查通过后包装安装）
// 目的：在 RunState=Running 期间自动捕获一个 >400ms 的完整长帧（含 2 个后续完成帧），
//       先证明 Editor Profiler 缓冲区有有效帧（buffer proven），再等待游戏内触发；
//       自动停录并保存，避免被退出 Play / 拖动窗口等边界操作污染。
//
// 使用步骤（见 workspace 报告）：
//   1. Unity 菜单 Tools > Frame Stall Capture > Install Monitor（Edit Mode 下点击）
//   2. Console 出现 "[FrameStallCapture] armed_waiting_for_start; editor_buffer_valid_frames=N"（N>0）
//      ——这一步就是"缓冲区有有效帧"的证明，N 持续增长更好
//   3. 正常开始游戏（进入 Running 后监控自动生效，启动前 2s 的慢帧忽略）
//   4. 命中 >400ms 完成帧 + 2 个后续帧后自动停录保存到
//      fyp_Backend/parallel_20261019/profiler_capture_review/auto_v2/*.data + *.json
//   5. 180s 未命中 / 退出 Play / run 结束 / 场景变化 → 以 boundary 标签保存或标记失败，不冒充有效候选
//
// 移除方式：直接删除本文件（不改场景、不改任何现有脚本）。
// 该工具不修改玩法、模型、阈值、协议或现有诊断配置；仅在 Editor 进程内启用 Profiler 并保存快照。
using System;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEditorInternal;
using UnityEngine;
using UnityEngine.Profiling;

public static class FrameStallAutoCapture
{
    const string SentinelKey = "Codex.ProfilerCaptureReview.AutoCapture.Cancel.20261019";
    const string StatusKey = "Codex.ProfilerCaptureReview.AutoCapture.Status.20261019";

    [MenuItem("Tools/Frame Stall Capture/Install Monitor")]
    public static void Install()
    {
        if (AppDomain.CurrentDomain.GetData(SentinelKey) != null)
        {
            Debug.LogWarning("[FrameStallCapture] Monitor already installed; use Force Cancel first.");
            return;
        }

        PropertyInfo driverEnabledProperty = typeof(ProfilerDriver).GetProperty("enabled", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        if (driverEnabledProperty == null || !driverEnabledProperty.CanRead || !driverEnabledProperty.CanWrite || driverEnabledProperty.PropertyType != typeof(bool))
            throw new MissingMemberException("ProfilerDriver.enabled bool property is unavailable");
        bool priorUnityEnabled = Profiler.enabled, priorDriverEnabled = (bool)driverEnabledProperty.GetValue(null, null), priorEditor = ProfilerDriver.profileEditor;
        if (priorUnityEnabled || priorDriverEnabled)
        {
            Debug.LogWarning("[FrameStallCapture] Profiler recording already enabled; stop it manually before installing.");
            return;
        }

        double installedAt = EditorApplication.timeSinceStartup, runStartedAt = -1, nextSearchAt = 0, recordingStartedAt = -1;
        int managerId = 0, lastScannedFrame = -1, triggerFrame = -1, validFrameCount = 0, slowFrameCount = 0, completedAfterTrigger = 0;
        string runId = "", scenePath = "";
        double triggerMs = 0;
        LevelManager manager = null;
        bool finished = false, recordingStarted = false, bufferProven = false;
        string directory = @"C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\parallel_20261019\profiler_capture_review\auto_v2";
        EditorApplication.CallbackFunction tick = null;
        Action cancel = null;
        Action<PlayModeStateChange> playChanged = null;
        Func<string, string> quote = s => "\"" + (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n").Replace("\t", "\\t") + "\"";
        Action restore = () =>
        {
            if (recordingStarted)
            {
                try { driverEnabledProperty.SetValue(null, priorDriverEnabled, null); } catch { }
                try { ProfilerDriver.profileEditor = priorEditor; } catch { }
                try { Profiler.enabled = priorUnityEnabled; } catch { }
            }
        };
        cancel = () =>
        {
            if (finished) return;
            finished = true;
            if (tick != null) EditorApplication.update -= tick;
            if (playChanged != null) EditorApplication.playModeStateChanged -= playChanged;
            restore();
            AppDomain.CurrentDomain.SetData(SentinelKey, null);
        };
        Action<string, bool> save = (label, validCandidate) =>
        {
            if (finished) return;
            string dataPath = null;
            try
            {
                if (!recordingStarted || validFrameCount == 0) { AppDomain.CurrentDomain.SetData(StatusKey, "no_valid_frames: " + label); return; }
                int saveLast = ProfilerDriver.lastFrameIndex;
                driverEnabledProperty.SetValue(null, false, null);
                Profiler.enabled = false;
                int savedValidFrameCount = validFrameCount;
                int savedSlowFrameCount = slowFrameCount;
                int savedCompletedAfterTrigger = completedAfterTrigger;
                int savedTriggerFrame = triggerFrame;
                Directory.CreateDirectory(directory);
                string id = "Auto_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff") + "_" + Guid.NewGuid().ToString("N");
                dataPath = Path.Combine(directory, id + ".data");
                string metaPath = Path.Combine(directory, id + ".json");
                if (File.Exists(dataPath) || File.Exists(metaPath)) throw new IOException("Refusing overwrite");
                if (!ProfilerDriver.SaveProfile(dataPath)) throw new IOException("SaveProfile returned false");
                FileInfo dataInfo = new FileInfo(dataPath);
                if (!dataInfo.Exists || dataInfo.Length <= 4) throw new IOException("Saved profile is empty or only a four-byte header; retained for failure audit");
                string metadata = "{\n" + string.Join(",\n", new string[]{
                    "\"status\":" + quote(label),
                    "\"midgame_candidate_not_root_cause_certification\":" + (validCandidate ? "true" : "false"),
                    "\"run_id\":" + quote(runId), "\"scene_path\":" + quote(scenePath),
                    "\"manager_id\":" + managerId, "\"trigger_native_frame\":" + savedTriggerFrame,
                    "\"trigger_ms\":" + triggerMs.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
                    "\"capture_first_native_frame\":" + ProfilerDriver.firstFrameIndex, "\"capture_last_native_frame\":" + saveLast,
                    "\"observed_valid_raw_frame_count\":" + savedValidFrameCount, "\"observed_slow_raw_frame_count_over_400ms\":" + savedSlowFrameCount,
                    "\"completed_frames_after_trigger\":" + savedCompletedAfterTrigger, "\"data_file_bytes\":" + dataInfo.Length,
                    "\"threshold_ms\":400", "\"following_completed_frames_required\":2", "\"run_startup_ignore_seconds\":2",
                    "\"save_utc\":" + quote(DateTime.UtcNow.ToString("O")), "\"data_file\":" + quote(dataPath),
                    "\"manual_window_pause_disambiguated\":false"
                }) + "\n}";
                File.WriteAllText(metaPath, metadata);
                AppDomain.CurrentDomain.SetData(StatusKey, "saved: " + dataPath + "; classification=" + label);
                Debug.Log("[FrameStallCapture] Saved " + label + ": " + dataPath);
            }
            catch (Exception e)
            {
                AppDomain.CurrentDomain.SetData(StatusKey, "save_error: " + e.GetType().Name + ": " + e.Message);
            }
            finally { cancel(); }
        };
        tick = () =>
        {
            if (finished) return;
            try
            {
                double now = EditorApplication.timeSinceStartup;
                if (now - installedAt > 180) { save(validFrameCount == 0 ? "no_valid_frames_timeout" : "timeout_boundary", false); return; }
                // 注：Edit Mode 等待阶段不做 play 边界判断（V2 原版此处会在 Edit Mode 安装时立即误判
                // "play_exit_boundary" 并取消，导致永远无法武装）；Play 退出由 playChanged 回调处理。
                if (manager == null && now >= nextSearchAt) { manager = UnityEngine.Object.FindFirstObjectByType<LevelManager>(); nextSearchAt = now + 0.5; }
                if (!recordingStarted)
                {
                    ProfilerDriver.ClearAllFrames();
                    ProfilerDriver.profileEditor = true;
                    driverEnabledProperty.SetValue(null, true, null);
                    Profiler.enabled = true;
                    recordingStarted = true;
                    recordingStartedAt = now;
                    AppDomain.CurrentDomain.SetData(StatusKey, "verifying_editor_profiler_buffer");
                }
                int completed = ProfilerDriver.lastFrameIndex - 1;
                int first = Math.Max(lastScannedFrame + 1, ProfilerDriver.firstFrameIndex);
                for (int f = first; f <= completed; f++)
                {
                    lastScannedFrame = f;
                    using (var raw = ProfilerDriver.GetRawFrameDataView(f, 0))
                    {
                        if (raw.valid && raw.sampleCount > 0)
                        {
                            validFrameCount++;
                            if (raw.frameTimeMs > 400) { slowFrameCount++; if (triggerFrame < 0 && runStartedAt >= 0 && now - runStartedAt >= 2) { triggerFrame = f; triggerMs = raw.frameTimeMs; } }
                            if (triggerFrame >= 0 && f > triggerFrame) completedAfterTrigger++;
                        }
                    }
                }
                if (!bufferProven && now - recordingStartedAt > 10 && validFrameCount == 0)
                {
                    AppDomain.CurrentDomain.SetData(StatusKey, "no_valid_frames: editor capture failed within 10s; monitor removed");
                    Debug.LogError("[FrameStallCapture] Editor profiler buffer produced no valid frames in 10s — capture NOT armed. Do not trust any .data produced this way.");
                    cancel(); return;
                }
                if (!bufferProven)
                {
                    if (now - installedAt >= 2 && validFrameCount > 0 && completed >= ProfilerDriver.firstFrameIndex)
                    {
                        bufferProven = true;
                        AppDomain.CurrentDomain.SetData(StatusKey, "armed_waiting_for_start; editor_buffer_valid_frames=" + validFrameCount);
                        Debug.Log("[FrameStallCapture] armed_waiting_for_start; editor_buffer_valid_frames=" + validFrameCount + " (buffer PROVEN — you may start Play now)");
                    }
                    else return;
                }
                if (manager == null) return;
                if (!manager.IsRunRunning) { if (runStartedAt >= 0) save("run_end_boundary", false); return; }
                if (runStartedAt < 0)
                {
                    runStartedAt = now; managerId = manager.GetInstanceID(); runId = manager.RunId ?? "";
                    scenePath = UnityEngine.SceneManagement.SceneManager.GetActiveScene().path;
                    AppDomain.CurrentDomain.SetData(StatusKey, "monitoring_run=" + runId);
                    Debug.Log("[FrameStallCapture] monitoring_run=" + runId + " — waiting for a >400ms completed frame (startup 2s ignored)");
                }
                if (manager.GetInstanceID() != managerId || manager.RunId != runId || UnityEngine.SceneManagement.SceneManager.GetActiveScene().path != scenePath) { save("context_changed_boundary", false); return; }
                if (triggerFrame >= 0 && completedAfterTrigger >= 2) save("midgame_slow_frame_candidate", true);
            }
            catch (Exception e) { AppDomain.CurrentDomain.SetData(StatusKey, "monitor_error: " + e.GetType().Name + ": " + e.Message); Debug.LogException(e); cancel(); }
        };
        playChanged = state => { if (state == PlayModeStateChange.ExitingPlayMode || state == PlayModeStateChange.EnteredEditMode) save("play_exit_boundary", false); };
        AppDomain.CurrentDomain.SetData(SentinelKey, cancel);
        AppDomain.CurrentDomain.SetData(StatusKey, "installed_waiting_for_editor_buffer");
        EditorApplication.update += tick;
        EditorApplication.playModeStateChanged += playChanged;
        Debug.Log("[FrameStallCapture] Temporary monitor installed; verifies Editor Profiler buffer before waiting for Start; one >400ms completed frame plus two following completed frames; lifetime 180s.");
    }

    [MenuItem("Tools/Frame Stall Capture/Force Cancel")]
    public static void ForceCancel()
    {
        var c = AppDomain.CurrentDomain.GetData(SentinelKey) as Action;
        if (c != null) { c(); Debug.Log("[FrameStallCapture] Monitor cancelled."); }
        else Debug.Log("[FrameStallCapture] No monitor installed.");
    }

    [MenuItem("Tools/Frame Stall Capture/Show Status")]
    public static void ShowStatus()
    {
        Debug.Log("[FrameStallCapture] status = " + (AppDomain.CurrentDomain.GetData(StatusKey) ?? "(none)"));
    }
}
