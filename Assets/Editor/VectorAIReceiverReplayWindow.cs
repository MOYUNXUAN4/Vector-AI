using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEngine;
using UnityEngine.Profiling;

/// <summary>Boardless, socket-free editor replay for the realtime receiver path.</summary>
public sealed class VectorAIReceiverReplayWindow : EditorWindow
{
    const int RateHz = 50;
    const string RunId = "vectorai-boardless-replay";
    const int SyntheticPlatformId = -123;
    const string SyntheticGeometryId = "-123-g1";
    static readonly BindingFlags InstanceFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    static readonly BindingFlags StaticFlags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

    int durationSeconds = 60;
    bool running;
    string status = "就绪 / Ready";
    string outputPath;
    UdpFrontendReceiver receiver;
    LevelManager level;
    UDPManager udp;
    GameObject root;
    FieldInfo pendingJson, pendingAt, countField, sumField, rmseField;
    FieldInfo receiverSocketField, receiverThreadField, udpSenderField, lastTelemetryField;
    MethodInfo updateMethod;
    FieldInfo runStateField, runIdField, passedField;
    object previousReceiverInstance, previousUdpInstance;
    object[] packets;
    double started, nextPacketAt;
    int nextPacket, scheduled, accepted, countAtStart, missedTicks, maxGapMs, gapsOver100Ms, silencePackets, updateInvocations;
    long maxUpdateTicks;
    int gc0Start, gc1Start, gc2Start;
    bool gcAvailable;
    bool receiverStaticCaptured, udpStaticCaptured;
    string receiverHash, toolHash, payloadTraceHash;
    FieldInfo modelWatermark, geometryWatermark, proximityWatermark;
    long priorModelWatermark, priorGeometryWatermark, priorProximityWatermark;
    bool timeoutObserved, modelSeenActive, geometrySeenActive, proximitySeenActive, silenceArmed;
    double silenceStarted;

    [MenuItem("Tools/VectorAI/Boardless Receiver Replay")]
    static void Open() => GetWindow<VectorAIReceiverReplayWindow>("Receiver Replay");

    void OnEnable() { EditorApplication.update += EditorTick; EditorApplication.playModeStateChanged += OnPlayModeChanged; AssemblyReloadEvents.beforeAssemblyReload += Cancel; EditorApplication.quitting += Cancel; }
    void OnDisable() { Cancel(); EditorApplication.update -= EditorTick; EditorApplication.playModeStateChanged -= OnPlayModeChanged; AssemblyReloadEvents.beforeAssemblyReload -= Cancel; EditorApplication.quitting -= Cancel; }
    void OnPlayModeChanged(PlayModeStateChange state)
    { if (state == PlayModeStateChange.ExitingEditMode && running) Finish(true, "play mode transition requested; replay stopped before scene activation"); }

    void OnGUI()
    {
        EditorGUILayout.LabelField("Boardless Receiver Replay / 无板卡接收器回放", EditorStyles.boldLabel);
        EditorGUILayout.HelpBox("仅调用接收器 Update，不开 UDP、不启动后端、不改写或保存场景。拒绝 Play、编译中及场景内已有接收器/管理器。编辑器负载会影响调度间隔。\nUses prebuilt packets and invokes receiver Update only. Current candidate only; source SHA-256 enables later comparisons. Receiver allocations require a separate manual Profiler recording.", MessageType.Info);
        using (new EditorGUI.DisabledScope(running)) durationSeconds = EditorGUILayout.IntPopup("Duration", durationSeconds, new[] { "60 s smoke", "180 s replay" }, new[] { 60, 180 });
        EditorGUILayout.LabelField("Status", status);
        if (!string.IsNullOrEmpty(outputPath)) EditorGUILayout.SelectableLabel(outputPath, GUILayout.Height(36));
        using (new EditorGUI.DisabledScope(running)) if (GUILayout.Button("Start / 开始", GUILayout.Height(30))) StartRun();
        if (running && GUILayout.Button("Cancel / 取消")) Cancel();
    }

    void StartRun()
    {
        if (EditorApplication.isPlaying || EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling)
        { status = "拒绝：Play 或编译中 / Refused: Play or compiling"; Repaint(); return; }
        if (UnityEngine.Object.FindAnyObjectByType<UdpFrontendReceiver>(FindObjectsInactive.Include) != null || UnityEngine.Object.FindAnyObjectByType<LevelManager>(FindObjectsInactive.Include) != null || UnityEngine.Object.FindAnyObjectByType<UDPManager>(FindObjectsInactive.Include) != null ||
            UdpFrontendReceiver.Instance != null || UDPManager.Instance != null)
        { status = "拒绝：场景对象或单例已存在 / Refused: receiver or manager exists"; Repaint(); return; }
        try
        {
            CacheReflection();
            string source = AssetDatabase.GetAssetPath(MonoScript.FromScriptableObject(this));
            toolHash = File.Exists(source) ? HashFile(source) : "unavailable";
            string receiverSource = "Assets/Endness Falling/Scripts/UdpFrontendReceiver.cs";
            receiverHash = File.Exists(receiverSource) ? HashFile(receiverSource) : "unavailable";
            BuildPackets();
            payloadTraceHash = PayloadTraceHash();
            root = new GameObject("[VectorAI Receiver Replay]") { hideFlags = HideFlags.HideAndDontSave };
            root.SetActive(false);
            level = root.AddComponent<LevelManager>(); level.enabled = false;
            receiver = root.AddComponent<UdpFrontendReceiver>(); receiver.enabled = false;
            udp = root.AddComponent<UDPManager>(); udp.enabled = false;
            SetBacking(typeof(UdpFrontendReceiver), "<Instance>k__BackingField", receiver, out previousReceiverInstance);
            receiverStaticCaptured = true;
            SetBacking(typeof(UDPManager), "<Instance>k__BackingField", udp, out previousUdpInstance);
            udpStaticCaptured = true;
            SetField(runStateField, level, Enum.Parse(runStateField.FieldType, "Running")); SetField(runIdField, level, RunId); SetField(passedField, level, 0);
            SetField(pendingJson, receiver, null); SetField(pendingAt, receiver, 0d);
            receiver.levelManager = level; receiver.targetPlayer = null;
            object telemetry = Activator.CreateInstance(typeof(UDPManager.UnityGameTelemetry));
            SetPublic(telemetry, "run_id", RunId); SetPublic(telemetry, "platformLevel", 1);
            SetPublic(telemetry, "geometry_platform_instance_id", SyntheticPlatformId); SetPublic(telemetry, "geometry_version_id", SyntheticGeometryId);
            lastTelemetryField.SetValue(udp, telemetry);
            receiver.enableExperimentalModelWarning = true; receiver.enableExperimentalGeometryWarning = true; receiver.enableExperimentalProximityWarning = true;
            SetField(countField, receiver, 0); SetField(sumField, receiver, 0f); SetField(rmseField, receiver, 0f);
            AssertSocketsClosed();
            running = true; started = StopwatchSeconds(); nextPacketAt = started; nextPacket = scheduled = missedTicks = accepted = silencePackets = 0;
            countAtStart = (int)countField.GetValue(receiver); maxUpdateTicks = 0; maxGapMs = gapsOver100Ms = 0; updateInvocations = 0; lastTick = 0d;
            timeoutObserved = modelSeenActive = geometrySeenActive = proximitySeenActive = silenceArmed = false; silenceStarted = 0d;
            gcAvailable = TryGcCounts(out gc0Start, out gc1Start, out gc2Start);
            priorModelWatermark = (long)modelWatermark.GetValue(receiver);
            priorGeometryWatermark = (long)geometryWatermark.GetValue(receiver);
            priorProximityWatermark = (long)proximityWatermark.GetValue(receiver);
            status = "运行中 / Running"; Repaint();
        }
        catch (Exception ex) { Cleanup(); status = "启动失败 / Start failed: " + ex.GetBaseException().Message; Repaint(); }
    }

    void CacheReflection()
    {
        Type rt = typeof(UdpFrontendReceiver), lt = typeof(LevelManager);
        pendingJson = Need(rt, "pendingJsonData"); pendingAt = Need(rt, "pendingReceiveMonotonicSeconds"); countField = Need(rt, "backendCountX"); sumField = Need(rt, "backendSumX"); rmseField = Need(rt, "backendRealRMSE");
        updateMethod = rt.GetMethod("Update", InstanceFlags) ?? throw new MissingMethodException("Update");
        runStateField = Need(lt, "runState"); runIdField = Need(lt, "runId"); passedField = Need(lt, "platformsPassed");
        modelWatermark = Need(rt, "highestExperimentalWarningUpdateSequence");
        geometryWatermark = Need(rt, "highestExperimentalGeometryWarningUpdateSequence");
        proximityWatermark = Need(rt, "highestExperimentalProximityWarningUpdateSequence");
        receiverSocketField = Need(rt, "udpClient"); receiverThreadField = Need(rt, "receiveThread"); udpSenderField = Need(typeof(UDPManager), "udpSender");
        lastTelemetryField = typeof(UDPManager).GetField("<LastTelemetry>k__BackingField", StaticFlags | BindingFlags.Instance) ?? throw new MissingFieldException("LastTelemetry backing field");
    }
    static void SetPublic(object target, string field, object value) => target.GetType().GetField(field, BindingFlags.Instance | BindingFlags.Public).SetValue(target, value);
    void AssertSocketsClosed()
    {
        if ((receiver != null && (receiverSocketField.GetValue(receiver) != null || receiverThreadField.GetValue(receiver) != null)) ||
            (udp != null && udpSenderField.GetValue(udp) != null))
            throw new InvalidOperationException("Network initialization detected; replay aborted.");
    }
    static FieldInfo Need(Type t, string name) => t.GetField(name, InstanceFlags) ?? throw new MissingFieldException(t.FullName, name);

    void BuildPackets()
    {
        int n = durationSeconds * RateHz;
        packets = new object[n];
        for (int i = 0; i < n; i++)
        {
            double t = (double)i / RateHz; double phase = t % 30d; long seq = i + 1;
            bool silence = phase >= 29.4d;
            if (silence) { packets[i] = null; continue; }
            bool hazard = phase < 10d || phase >= 20d;
            string state = hazard ? "STRONG" : "SAFE";
            string geometryState = hazard ? "CRITICAL" : "CLEAR";
            string proximityState = hazard ? "APPROACH" : "CLEAR";
            float prob = state == "STRONG" ? .91f : .08f;
            string stamp = (1_800_000_000d + t).ToString("0.000", CultureInfo.InvariantCulture);
            long predictionSeq = 1 + i / 5; // Model inference is 10 Hz; replies remain 50 Hz.
            packets[i] = "{\"type\":\"realtime\",\"x\":0.25,\"y\":-0.1,\"difficulty\":0,\"rmse\":0.125,\"model_warning\":{\"schema_version\":1,\"experimental\":true,\"enabled\":true,\"model_id\":\"replay-model\",\"run_id\":\"" + RunId + "\",\"layer\":1,\"state\":\"" + state + "\",\"valid\":true,\"probability_valid\":true,\"strong_probability\":" + prob.ToString(CultureInfo.InvariantCulture) + ",\"prediction_sequence\":" + predictionSeq + ",\"warning_update_sequence\":" + seq + ",\"input_sequence\":" + seq + ",\"input_source_timestamp\":" + stamp + ",\"feature_age_seconds\":0.01,\"reason\":\"synthetic_replay\"},\"geometry_warning\":{\"schema_version\":1,\"experimental\":true,\"enabled\":true,\"source\":\"geometry_rule\",\"policy_id\":\"outer_clearance_nonpositive_v1\",\"run_id\":\"" + RunId + "\",\"layer\":1,\"platform_instance_id\":-123,\"geometry_version_id\":\"-123-g1\",\"input_sequence\":" + seq + ",\"input_source_timestamp\":" + stamp + ",\"warning_update_sequence\":" + seq + ",\"clearance\":" + (geometryState == "CLEAR" ? "0.5" : "-0.1") + ",\"clearance_valid\":true,\"state\":\"" + geometryState + "\",\"valid\":true,\"reason\":\"synthetic_geometry_rule\",\"sample_age_seconds\":0.01,\"query_age_seconds\":0.01,\"geometry_age_seconds\":0.02},\"proximity_warning\":{\"schema_version\":1,\"experimental\":true,\"enabled\":true,\"source\":\"tte_proximity_rule_v1\",\"policy_id\":\"tte_proximity_h075_confirm2_v1\",\"run_id\":\"" + RunId + "\",\"layer\":1,\"platform_instance_id\":-123,\"geometry_version_id\":\"-123-g1\",\"input_sequence\":" + seq + ",\"input_source_timestamp\":" + stamp + ",\"warning_update_sequence\":" + seq + ",\"state\":\"" + proximityState + "\",\"active\":" + (proximityState == "APPROACH" ? "true" : "false") + ",\"valid\":true,\"sample_age_seconds\":0.01,\"query_age_seconds\":0.01,\"geometry_age_seconds\":0.02,\"q\":" + (proximityState == "APPROACH" ? "0.25" : "0") + ",\"q_valid\":" + (proximityState == "APPROACH" ? "true" : "false") + ",\"outward_velocity\":" + (proximityState == "APPROACH" ? "0.4" : "0") + ",\"horizon_seconds\":0.75,\"reason\":\"synthetic_tte_rule\"}}";
        }
    }

    void EditorTick()
    {
        if (!running) return;
        try
        {
            double now = StopwatchSeconds();
            if (nextPacket < packets.Length && now >= nextPacketAt)
            {
                double late = now - nextPacketAt;
                int skipped = Math.Min((int)(late * RateHz), packets.Length - nextPacket - 1);
                if (skipped > 0)
                {
                    for (int i = 0; i < skipped; i++) if (packets[nextPacket + i] != null) missedTicks++;
                    nextPacket += skipped; nextPacketAt += skipped / (double)RateHz;
                }
                object packet = packets[nextPacket];
                if (packet == null)
                {
                    silencePackets++;
                    if (silenceStarted == 0d)
                    {
                        silenceStarted = now;
                        silenceArmed = receiver.ExperimentalModelWarningActive && receiver.ExperimentalGeometryWarningActive && receiver.ExperimentalProximityWarningActive;
                    }
                }
                else
                {
                    silenceStarted = 0d; silenceArmed = false;
                    SetField(pendingJson, receiver, packet); SetField(pendingAt, receiver, now); scheduled++;
                }
                nextPacket++; nextPacketAt += 1d / RateHz;
            }
            if (EditorApplication.isCompiling || EditorApplication.isPlayingOrWillChangePlaymode || root == null || receiver == null || level == null || udp == null)
                throw new InvalidOperationException("Editor replay context ended; aborting safely.");
            double gap = now - lastTick; if (lastTick > 0) { maxGapMs = Math.Max(maxGapMs, (int)(gap * 1000)); if (gap > .1) gapsOver100Ms++; } lastTick = now;
            long before = Stopwatch.GetTimestamp();
            Profiler.BeginSample("VectorAI.Replay.ReceiverUpdate");
            try { updateMethod.Invoke(receiver, null); }
            finally { Profiler.EndSample(); }
            long cost = Stopwatch.GetTimestamp() - before; updateInvocations++;
            AssertSocketsClosed();
            modelSeenActive |= receiver.ExperimentalModelWarningActive;
            geometrySeenActive |= receiver.ExperimentalGeometryWarningActive;
            proximitySeenActive |= receiver.ExperimentalProximityWarningActive;
            if (silenceArmed && silenceStarted > 0d && now - silenceStarted >= 0.3d && !receiver.ExperimentalModelWarningActive && !receiver.ExperimentalGeometryWarningActive && !receiver.ExperimentalProximityWarningActive) timeoutObserved = true;
            if (cost > maxUpdateTicks) maxUpdateTicks = cost;
            accepted = (int)countField.GetValue(receiver) - countAtStart;
            if (now - started >= durationSeconds || nextPacket >= packets.Length) Finish(false);
        }
        catch (Exception ex) { Finish(true, ex.GetBaseException().ToString()); }
    }
    double lastTick;

    void Finish(bool failed, string error = null)
    {
        if (!running) return;
        double duration = StopwatchSeconds() - started;
        accepted = receiver != null ? (int)countField.GetValue(receiver) - countAtStart : accepted;
        int g0, g1, g2; bool gcNow = TryGcCounts(out g0, out g1, out g2);
        long finalModel = receiver != null ? (long)modelWatermark.GetValue(receiver) : priorModelWatermark;
        long finalGeometry = receiver != null ? (long)geometryWatermark.GetValue(receiver) : priorGeometryWatermark;
        long finalProximity = receiver != null ? (long)proximityWatermark.GetValue(receiver) : priorProximityWatermark;
        bool noNetwork = receiver != null && udp != null && receiverSocketField.GetValue(receiver) == null && receiverThreadField.GetValue(receiver) == null && udpSenderField.GetValue(udp) == null;
        bool watermarkProgress = finalModel > priorModelWatermark && finalGeometry > priorGeometryWatermark && finalProximity > priorProximityWatermark;
        bool replayValid = accepted > 0 && modelSeenActive && geometrySeenActive && proximitySeenActive && watermarkProgress && timeoutObserved && noNetwork;
        string json = "{\n" +
            "  \"tool\":\"VectorAI Boardless Receiver Replay\",\n  \"unity_version\":" + Q(Application.unityVersion) + ",\n  \"receiver_source_sha256\":" + Q(receiverHash) + ",\n  \"tool_source_sha256\":" + Q(toolHash) + ",\n  \"payload_trace_sha256\":" + Q(payloadTraceHash) + ",\n" +
            "  \"requested_seconds\":" + durationSeconds + ",\n  \"actual_seconds\":" + duration.ToString("0.000", CultureInfo.InvariantCulture) + ",\n  \"rate_hz\":" + RateHz + ",\n" +
            "  \"scheduled_packets\":" + scheduled + ",\n  \"accepted_realtime_packets\":" + accepted + ",\n  \"accepted_path_valid\":" + (replayValid ? "true" : "false") + ",\n  \"channels_seen_active\":{\"model\":" + modelSeenActive.ToString().ToLowerInvariant() + ",\"geometry\":" + geometrySeenActive.ToString().ToLowerInvariant() + ",\"proximity\":" + proximitySeenActive.ToString().ToLowerInvariant() + "},\n  \"warning_update_watermark_advanced\":{\"model\":" + (finalModel > priorModelWatermark).ToString().ToLowerInvariant() + ",\"geometry\":" + (finalGeometry > priorGeometryWatermark).ToString().ToLowerInvariant() + ",\"proximity\":" + (finalProximity > priorProximityWatermark).ToString().ToLowerInvariant() + "},\n  \"silence_timeout_cleared_all\":" + timeoutObserved.ToString().ToLowerInvariant() + ",\n  \"schedule_misses\":" + missedTicks + ",\n  \"intentional_silence_ticks\":" + silencePackets + ",\n  \"faults_smoke\":\"not_run\",\n" +
            "  \"editor_update_invocations\":" + updateInvocations + ",\n" +
            "  \"max_update_ms\":" + (maxUpdateTicks * 1000d / Stopwatch.Frequency).ToString("0.000", CultureInfo.InvariantCulture) + ",\n  \"max_editor_tick_gap_ms\":" + maxGapMs + ",\n  \"tick_gaps_over_100ms\":" + gapsOver100Ms + ",\n" +
            "  \"gc_collection_counts\":" + (gcAvailable && gcNow ? "{\"gen0_delta\":" + (g0-gc0Start) + ",\"gen1_delta\":" + (g1-gc1Start) + ",\"gen2_delta\":" + (g2-gc2Start) + "}" : "null") + ",\n  \"gc_counts_scope\":\"editor process-wide, not receiver-specific\",\n  \"gc_counts_status\":" + Q(gcAvailable && gcNow ? "available" : "unknown_or_unsupported") + ",\n" +
            "  \"warning_active_at_end\":" + (receiver != null && receiver.ExperimentalModelWarningActive ? "true" : "false") + ",\n  \"failed\":" + (failed ? "true" : "false") + (error == null ? "" : ",\n  \"error\":" + Q(error)) + "\n}";
        try { string dir = Path.Combine("Library", "VectorAIReceiverReplay"); Directory.CreateDirectory(dir); outputPath = Path.Combine(dir, "replay_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff") + ".json"); File.WriteAllText(outputPath, json, new UTF8Encoding(false)); }
        catch (Exception ex) { error = "report write: " + ex.Message; failed = true; }
        Cleanup(); status = failed ? "结束但有错误 / Finished with error: " + error : (replayValid ? "完成 / Complete" : "回放完成但验收未通过 / Replay finished, acceptance incomplete"); Repaint();
    }

    void Cancel() { if (!running && root == null) return; if (running) { Finish(true, "cancelled"); status = "已取消并保存部分报告 / Cancelled; partial report saved"; } else Cleanup(); Repaint(); }
    void Cleanup()
    {
        running = false;
        if (receiver != null && pendingJson != null) { SetField(pendingJson, receiver, null); SetField(pendingAt, receiver, 0d); }
        try { AssertSocketsClosed(); } catch (Exception e) { UnityEngine.Debug.LogError("[VectorAI Replay] " + e.Message); }
        UdpFrontendReceiver receiverToRestore = receiver;
        UDPManager udpToRestore = udp;
        if (root != null) DestroyImmediate(root);
        if (receiverStaticCaptured && receiverBacking != null)
        { object current = receiverBacking.GetValue(null); if (current == null || ReferenceEquals(current, receiverToRestore)) receiverBacking.SetValue(null, previousReceiverInstance); }
        if (udpStaticCaptured && udpBacking != null)
        { object current = udpBacking.GetValue(null); if (current == null || ReferenceEquals(current, udpToRestore)) udpBacking.SetValue(null, previousUdpInstance); }
        receiverStaticCaptured = udpStaticCaptured = false;
        receiver = null; level = null; udp = null; root = null;
    }

    static void SetBacking(Type type, string name, object value, out object old)
    { FieldInfo f = type.GetField(name, StaticFlags) ?? throw new MissingFieldException(type.FullName, name); old = f.GetValue(null); f.SetValue(null, value); if (type == typeof(UdpFrontendReceiver)) receiverBacking = f; else udpBacking = f; }
    static FieldInfo receiverBacking, udpBacking;
    static void SetField(FieldInfo field, object target, object value) => field.SetValue(target, value);
    static double StopwatchSeconds() => Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
    string PayloadTraceHash()
    {
        using (var sha = SHA256.Create())
        {
            var bytes = new StringBuilder(packets == null ? 0 : packets.Length * 1024);
            if (packets != null) foreach (object packet in packets) bytes.Append(packet == null ? "<SILENCE>" : (string)packet).Append('\n');
            return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(bytes.ToString()))).Replace("-", "").ToLowerInvariant();
        }
    }
    static bool TryGcCounts(out int a, out int b, out int c) { a = b = c = 0; try { a = GC.CollectionCount(0); b = GC.CollectionCount(1); c = GC.CollectionCount(2); return true; } catch { return false; } }
    static string HashFile(string path) { using (var sha = SHA256.Create()) using (var stream = File.OpenRead(path)) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant(); }
    static string Q(string value) => "\"" + (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n") + "\"";
}
