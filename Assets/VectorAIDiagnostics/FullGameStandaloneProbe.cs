#if VECTORAI_FULLGAME_PROBE && !UNITY_EDITOR
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime;
using System.Text;
using System.Collections;
using UnityEngine;
using UnityEngine.Profiling;
using Unity.Profiling;

/// <summary>Observe the real Endless Falling scene under a dedicated synthetic-peer diagnostic build.</summary>
internal sealed class FullGameStandaloneProbe : MonoBehaviour
{
    const string SyntheticHost = "127.0.0.1";
    const int SyntheticPort = 16005;
    const int ReceiverPort = 16006;
    const int TargetFps = 60;
    const double RequestedRunSeconds = 180d;
    const int MaxRecordedLongFrames = 4096;
    static FullGameStandaloneProbe instance;
    readonly LongFrameEvent[] longFrames = new LongFrameEvent[MaxRecordedLongFrames];
    int longFrameCount;
    int totalLongFrameEvents;
    string outputDir, error;
    UIManager ui;
    UDPManager udp;
    UdpFrontendReceiver receiver;
    LevelManager level;
    EndlessPlayerController player;
    FieldInfo uiBackendEndPoint;
    FieldInfo modelWatermark, geometryWatermark, proximityWatermark;
    FieldInfo receiverSocket, receiverThread, udpSender;
    long lastFrameTick;
    long maxFrameIntervalTicks;
    long startedTick;
    int frameCount, fixedUpdateCount, ownOnGuiCount;
    int modelActiveFrames, geometryActiveFrames, proximityActiveFrames;
    int modelTransitions, geometryTransitions, proximityTransitions;
    bool lastModel, lastGeometry, lastProximity;
    bool failed, finished, started;
    long startModelWatermark, startGeometryWatermark, startProximityWatermark;
    int startRealtimeCount;
    string runId;
    string[] diagnosticFilesAtStart;
    long startTelemetrySequence;
    int priorFrameGen0, priorFrameGen1, priorFrameGen2;
    double nonCalibrationRunningSeconds;
    float startTimeScale;
    string startedUtc;
    int gc0Start, gc1Start, gc2Start;
    long usedMemoryStart, monoHeapStart;
    ProfilerRecorder uiOnGuiRecorder;
    bool uiOnGuiRecorderAvailable;
    int uiOnGuiRecordedFrames;
    long uiOnGuiLastValue;

    [Serializable] sealed class LongFrameEvent
    {
        public double elapsed_seconds;
        public double interval_ms;
        public int gen0_delta_since_prior_frame;
        public int gen1_delta_since_prior_frame;
        public int gen2_delta_since_prior_frame;
        public long used_managed_bytes_at_observation;
    }
    [Serializable] sealed class RunSnapshot
    {
        public string state;
        public string run_id;
        public string outcome;
        public int current_layer;
        public int selected_layers;
        public int selected_difficulty;
        public int commanded_difficulty;
        public bool calibration_mode;
        public bool calibration_stage;
        public bool backend_difficulty_enabled;
        public bool dda_enabled;
        public float input_sensitivity;
        public int platforms_passed;
        public int realtime_packet_count;
        public long model_watermark;
        public long geometry_watermark;
        public long proximity_watermark;
        public bool model_active;
        public bool geometry_active;
        public bool proximity_active;
    }
    [Serializable] sealed class ProbeReport
    {
        public string probe = "VectorAI Full Game Standalone Probe";
        public string unity_version;
        public string mode = "full_game_real_scene_synthetic_peer";
        public bool synthetic_run = true;
        public bool synthetic_peer_required = true;
        public string incoming_packet_source = "External synthetic UDP peer; probe does not inject incoming packets.";
        public bool participant_data = false;
        public string output_directory;
        public string run_id;
        public string start_utc;
        public string end_utc;
        public string diagnostics_persistent_directory;
        public string completion = "incomplete";
        public bool failed;
        public string error;
        public double requested_running_seconds;
        public double actual_running_seconds;
        public double non_calibration_running_seconds;
        public double ended_elapsed_seconds;
        public float target_frame_rate;
        public int v_sync_count;
        public bool run_in_background;
        public string gc_mode;
        public bool incremental_gc;
        public string dotnet_gc_latency_mode;
        public long used_managed_bytes_start;
        public long used_managed_bytes_end;
        public long mono_heap_bytes_start;
        public long mono_heap_bytes_end;
        public int gen0_delta;
        public int gen1_delta;
        public int gen2_delta;
        public int frame_count;
        public int fixed_update_count;
        public int runner_on_gui_count;
        public string ui_ongui_profiler_recorder_status;
        public int ui_ongui_profiler_recorded_frames;
        public long ui_ongui_profiler_last_value;
        public double max_frame_interval_ms;
        public LongFrameEvent[] frame_gaps_over_100ms;
        public int omitted_long_frame_events;
        public int model_active_frames;
        public int geometry_active_frames;
        public int proximity_active_frames;
        public int model_active_transitions;
        public int geometry_active_transitions;
        public int proximity_active_transitions;
        public int receiver_realtime_packets_start;
        public int receiver_realtime_packets_end;
        public long last_telemetry_sequence_start;
        public long last_telemetry_sequence_end;
        public double run_start_backend_timestamp;
        public long model_watermark_start;
        public long model_watermark_end;
        public long geometry_watermark_start;
        public long geometry_watermark_end;
        public long proximity_watermark_start;
        public long proximity_watermark_end;
        public bool receiver_socket_null_end;
        public bool receiver_thread_null_end;
        public bool telemetry_sender_null_end;
        public bool ui_manager_found_and_enabled;
        public string redirected_backend_endpoint;
        public string redirected_receiver_endpoint;
        public string redirected_telemetry_endpoint;
        public float telemetry_send_rate_hz;
        public float geometry_diagnostic_sample_interval;
        public int geometry_boundary_scan_samples;
        public int geometry_boundary_refinement_steps;
        public bool geometry_diagnostics_enabled;
        public bool model_warning_enabled;
        public bool geometry_warning_enabled;
        public bool proximity_warning_enabled;
        public bool verbose_observation_logs;
        public bool show_edge_warning_debug_hud;
        public bool show_top_title;
        public Vector2 hud_group_anchor;
        public Vector2 hud_card_size;
        public float hud_card_vertical_gap;
        public float configured_calibration_duration;
        public float time_scale_at_start;
        public float time_scale_at_end;
        public float maximum_delta_time;
        public Vector3 gravity;
        public bool high_frequency_light_diagnostics_enabled;
        public float high_frequency_light_interval;
        public bool event_driven_full_geometry_enabled;
        public bool fixed_cadence_full_geometry_enabled;
        public float fixed_full_geometry_interval;
        public float event_full_geometry_min_interval;
        public float full_geometry_budget_ms;
        public RunSnapshot start;
        public RunSnapshot end;
        public string[] diagnostic_files_before;
        public string[] diagnostic_files_after;
        public string limitation = "A run that ends before 180 unscaled running seconds is reported incomplete; the probe does not restart or alter gameplay.";
    }

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Bootstrap()
    {
        if (instance != null) return;
        var go = new GameObject("[VectorAI Full Game Probe]");
        DontDestroyOnLoad(go);
        instance = go.AddComponent<FullGameStandaloneProbe>();
        try { instance.PrepareBeforeSceneStart(); }
        catch (Exception ex)
        {
            instance.error = ex.GetBaseException().ToString(); instance.failed = true;
            instance.DisableSceneNetworkStarts();
            instance.WriteFailureAndQuit();
            instance.enabled = false;
        }
    }

    void PrepareBeforeSceneStart()
    {
        Application.targetFrameRate = TargetFps;
        QualitySettings.vSyncCount = 0;
        Application.runInBackground = true;
        string[] args = Environment.GetCommandLineArgs();
        outputDir = ReadArg(args, "--fullgame-probe-output");
        if (string.IsNullOrWhiteSpace(outputDir) || !Path.IsPathRooted(outputDir))
        {
            error = "--fullgame-probe-output must name a unique absolute directory.";
            outputDir = Path.Combine(Application.persistentDataPath, "FullGameProbeFailure_" + Guid.NewGuid().ToString("N"));
            throw new ArgumentException(error);
        }
        if (Directory.Exists(outputDir) && Directory.GetFileSystemEntries(outputDir).Length != 0)
        {
            outputDir = Path.Combine(Application.persistentDataPath, "FullGameProbeFailure_" + Guid.NewGuid().ToString("N"));
            throw new IOException("Output directory must be new or empty; refusing to overwrite prior evidence.");
        }
        Directory.CreateDirectory(outputDir);
        BindSceneObjectsAndRedirectEndpoints();
    }

    IEnumerator Start()
    {
        // Let every scene Start run first (including the real component socket initialization and pause setup).
        yield return null;
        yield return null;
        try
        {
            try
            {
                uiOnGuiRecorder = ProfilerRecorder.StartNew(ProfilerCategory.Scripts, "VectorAI.UI.OnGUI.Total", 1);
                uiOnGuiRecorderAvailable = uiOnGuiRecorder.Valid;
            }
            catch { uiOnGuiRecorderAvailable = false; }
            if (ui == null || !ui.enabled || level == null || receiver == null || udp == null || player == null)
                throw new InvalidOperationException("Required scene identity became unavailable before run start.");
            if (receiverSocket.GetValue(receiver) == null || receiverThread.GetValue(receiver) == null || udpSender.GetValue(udp) == null)
                throw new InvalidOperationException("Receiver or telemetry sender did not initialize; refusing to measure a partial scene.");
            MethodInfo startRun = typeof(UIManager).GetMethod("StartConfiguredRun", BindingFlags.Instance | BindingFlags.NonPublic);
            if (startRun == null) throw new MissingMethodException("UIManager.StartConfiguredRun");
            startRun.Invoke(ui, new object[] { level });
            if (!level.IsRunRunning || string.IsNullOrWhiteSpace(level.RunId))
                throw new InvalidOperationException("Normal configured run entry point did not start a valid run.");
            runId = level.RunId;
            SnapshotStartAndWriteManifest();
            startedTick = Stopwatch.GetTimestamp();
            lastFrameTick = startedTick;
            started = true;
        }
        catch (Exception ex) { error = ex.GetBaseException().ToString(); failed = true; WriteFailureAndQuit(); }
    }

    void BindSceneObjectsAndRedirectEndpoints()
    {
        ui = Unique<UIManager>("UIManager"); udp = Unique<UDPManager>("UDPManager");
        receiver = Unique<UdpFrontendReceiver>("UdpFrontendReceiver"); level = Unique<LevelManager>("LevelManager");
        player = Unique<EndlessPlayerController>("EndlessPlayerController");
        if (!ui.enabled || !udp.enabled || !receiver.enabled || !level.enabled || !player.enabled)
            throw new InvalidOperationException("Required scene component is disabled.");
        if (ui.backendPort != 5005 || udp.sendPort != 5005 || receiver.listenPort != 5006 || receiver.targetPythonPort != 5005)
            throw new InvalidOperationException("Unexpected authored endpoints; refusing to redirect an unrecognized scene setup.");
        ui.backendIP = SyntheticHost; ui.backendPort = SyntheticPort;
        uiBackendEndPoint = Need(typeof(UIManager), "backendEndPoint");
        uiBackendEndPoint.SetValue(ui, new IPEndPoint(IPAddress.Parse(SyntheticHost), SyntheticPort));
        udp.pythonIP = SyntheticHost; udp.sendPort = SyntheticPort;
        receiver.listenPort = ReceiverPort; receiver.targetPythonPort = SyntheticPort;
        receiverSocket = Need(typeof(UdpFrontendReceiver), "udpClient");
        receiverThread = Need(typeof(UdpFrontendReceiver), "receiveThread");
        udpSender = Need(typeof(UDPManager), "udpSender");
        if (receiverSocket.GetValue(receiver) != null || receiverThread.GetValue(receiver) != null || udpSender.GetValue(udp) != null)
            throw new InvalidOperationException("A network component initialized before the probe redirected endpoints.");
        modelWatermark = Need(typeof(UdpFrontendReceiver), "highestExperimentalWarningUpdateSequence");
        geometryWatermark = Need(typeof(UdpFrontendReceiver), "highestExperimentalGeometryWarningUpdateSequence");
        proximityWatermark = Need(typeof(UdpFrontendReceiver), "highestExperimentalProximityWarningUpdateSequence");
    }

    void DisableSceneNetworkStarts()
    {
        foreach (UdpFrontendReceiver component in UnityEngine.Object.FindObjectsByType<UdpFrontendReceiver>(FindObjectsInactive.Include, FindObjectsSortMode.None)) component.enabled = false;
        foreach (UDPManager component in UnityEngine.Object.FindObjectsByType<UDPManager>(FindObjectsInactive.Include, FindObjectsSortMode.None)) component.enabled = false;
        foreach (UIManager component in UnityEngine.Object.FindObjectsByType<UIManager>(FindObjectsInactive.Include, FindObjectsSortMode.None)) component.enabled = false;
    }

    static T Unique<T>(string label) where T : UnityEngine.Object
    {
        T[] found = UnityEngine.Object.FindObjectsByType<T>(FindObjectsInactive.Include, FindObjectsSortMode.None);
        if (found.Length != 1 || found[0] == null) throw new InvalidOperationException("Expected exactly one " + label + "; found " + found.Length + ".");
        return found[0];
    }
    static FieldInfo Need(Type type, string name) => type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) ?? throw new MissingFieldException(type.FullName, name);

    void SnapshotStartAndWriteManifest()
    {
        gc0Start = GC.CollectionCount(0); gc1Start = GC.CollectionCount(1); gc2Start = GC.CollectionCount(2);
        usedMemoryStart = GC.GetTotalMemory(false); monoHeapStart = Profiler.GetMonoHeapSizeLong();
        startTimeScale = Time.timeScale;
        startRealtimeCount = receiver.backendCountX;
        startModelWatermark = (long)modelWatermark.GetValue(receiver);
        startGeometryWatermark = (long)geometryWatermark.GetValue(receiver);
        startProximityWatermark = (long)proximityWatermark.GetValue(receiver);
        lastModel = receiver.ExperimentalModelWarningActive; lastGeometry = receiver.ExperimentalGeometryWarningActive; lastProximity = receiver.ExperimentalProximityWarningActive;
        diagnosticFilesAtStart = DiagnosticFiles();
        startTelemetrySequence = ReadTelemetrySequence();
        priorFrameGen0 = GC.CollectionCount(0); priorFrameGen1 = GC.CollectionCount(1); priorFrameGen2 = GC.CollectionCount(2);
        startedUtc = DateTime.UtcNow.ToString("o");
        ProbeReport report = CreateReport("run_started");
        report.start = Snapshot();
        File.WriteAllText(Path.Combine(outputDir, "manifest.json"), JsonUtility.ToJson(report, true), new UTF8Encoding(false));
    }

    void Update()
    {
        if (!started || finished) return;
        if (uiOnGuiRecorderAvailable)
        {
            uiOnGuiLastValue = uiOnGuiRecorder.LastValue;
            if (uiOnGuiLastValue > 0) uiOnGuiRecordedFrames++;
        }
        long tick = Stopwatch.GetTimestamp();
        long gap = tick - lastFrameTick; lastFrameTick = tick; frameCount++;
        if (gap > maxFrameIntervalTicks) maxFrameIntervalTicks = gap;
        if (gap > Stopwatch.Frequency / 10)
        {
            totalLongFrameEvents++;
            if (longFrameCount < longFrames.Length)
                longFrames[longFrameCount++] = new LongFrameEvent
                {
                    elapsed_seconds = (tick - startedTick) / (double)Stopwatch.Frequency,
                    interval_ms = gap * 1000d / Stopwatch.Frequency,
                    gen0_delta_since_prior_frame = GC.CollectionCount(0) - priorFrameGen0,
                    gen1_delta_since_prior_frame = GC.CollectionCount(1) - priorFrameGen1,
                    gen2_delta_since_prior_frame = GC.CollectionCount(2) - priorFrameGen2,
                    used_managed_bytes_at_observation = GC.GetTotalMemory(false)
                };
        }
        priorFrameGen0 = GC.CollectionCount(0); priorFrameGen1 = GC.CollectionCount(1); priorFrameGen2 = GC.CollectionCount(2);
        bool model = receiver != null && receiver.ExperimentalModelWarningActive;
        bool geometry = receiver != null && receiver.ExperimentalGeometryWarningActive;
        bool proximity = receiver != null && receiver.ExperimentalProximityWarningActive;
        if (model) modelActiveFrames++; if (geometry) geometryActiveFrames++; if (proximity) proximityActiveFrames++;
        if (model != lastModel) modelTransitions++; if (geometry != lastGeometry) geometryTransitions++; if (proximity != lastProximity) proximityTransitions++;
        lastModel = model; lastGeometry = geometry; lastProximity = proximity;
        if (level.IsRunRunning && !level.IsCalibrationStage) nonCalibrationRunningSeconds += gap / (double)Stopwatch.Frequency;
        double elapsed = (tick - startedTick) / (double)Stopwatch.Frequency;
        if (!level.IsRunRunning) { error = "Real gameplay run ended before requested observation duration."; failed = true; Finish("ended_early", elapsed); return; }
        if (elapsed >= RequestedRunSeconds) Finish("complete", elapsed);
    }

    void FixedUpdate() { if (started && !finished) fixedUpdateCount++; }
    void OnGUI() { if (started && !finished && Event.current.type == EventType.Repaint) ownOnGuiCount++; }

    void Finish(string completion, double elapsed)
    {
        if (finished) return; finished = true;
        int endGen0 = GC.CollectionCount(0), endGen1 = GC.CollectionCount(1), endGen2 = GC.CollectionCount(2);
        long endUsedManagedBytes = GC.GetTotalMemory(false), endMonoHeapBytes = Profiler.GetMonoHeapSizeLong();
        ProbeReport report = CreateReport(completion);
        report.actual_running_seconds = elapsed;
        report.non_calibration_running_seconds = nonCalibrationRunningSeconds;
        report.ended_elapsed_seconds = elapsed;
        report.end = Snapshot();
        report.diagnostic_files_after = DiagnosticFiles();
        report.frame_gaps_over_100ms = new LongFrameEvent[longFrameCount];
        Array.Copy(longFrames, report.frame_gaps_over_100ms, longFrameCount);
        report.frame_count = frameCount; report.fixed_update_count = fixedUpdateCount; report.runner_on_gui_count = ownOnGuiCount;
        report.max_frame_interval_ms = maxFrameIntervalTicks * 1000d / Stopwatch.Frequency;
        report.ui_ongui_profiler_recorder_status = uiOnGuiRecorderAvailable ? "available" : "unknown_unavailable_or_marker_missing";
        report.ui_ongui_profiler_recorded_frames = uiOnGuiRecordedFrames;
        report.ui_ongui_profiler_last_value = uiOnGuiLastValue;
        report.omitted_long_frame_events = Math.Max(0, totalLongFrameEvents - longFrameCount);
        report.model_active_frames = modelActiveFrames; report.geometry_active_frames = geometryActiveFrames; report.proximity_active_frames = proximityActiveFrames;
        report.model_active_transitions = modelTransitions; report.geometry_active_transitions = geometryTransitions; report.proximity_active_transitions = proximityTransitions;
        report.receiver_realtime_packets_start = startRealtimeCount; report.receiver_realtime_packets_end = receiver != null ? receiver.backendCountX : -1;
        report.last_telemetry_sequence_start = startTelemetrySequence; report.last_telemetry_sequence_end = ReadTelemetrySequence();
        report.run_start_backend_timestamp = level != null ? level.RunStartBackendTimestamp : double.NaN;
        report.model_watermark_start = startModelWatermark; report.geometry_watermark_start = startGeometryWatermark; report.proximity_watermark_start = startProximityWatermark;
        report.model_watermark_end = ReadLong(modelWatermark, receiver); report.geometry_watermark_end = ReadLong(geometryWatermark, receiver); report.proximity_watermark_end = ReadLong(proximityWatermark, receiver);
        report.receiver_socket_null_end = receiver != null && receiverSocket.GetValue(receiver) == null;
        report.receiver_thread_null_end = receiver != null && receiverThread.GetValue(receiver) == null;
        report.telemetry_sender_null_end = udp != null && udpSender.GetValue(udp) == null;
        report.gen0_delta = endGen0 - gc0Start; report.gen1_delta = endGen1 - gc1Start; report.gen2_delta = endGen2 - gc2Start;
        report.used_managed_bytes_end = endUsedManagedBytes; report.mono_heap_bytes_end = endMonoHeapBytes;
        report.completion = completion; report.error = error;
        report.failed = failed;
        report.end_utc = DateTime.UtcNow.ToString("o");
        if (report.receiver_socket_null_end || report.receiver_thread_null_end || report.telemetry_sender_null_end)
        { failed = true; report.error = error = "Expected live scene sockets were null at the end of observation."; }
        report.failed = failed;
        report.time_scale_at_end = Time.timeScale;
        if (uiOnGuiRecorderAvailable) uiOnGuiRecorder.Dispose();
        try { File.WriteAllText(Path.Combine(outputDir, "summary.json"), JsonUtility.ToJson(report, true), new UTF8Encoding(false)); }
        catch (Exception ex) { failed = true; UnityEngine.Debug.LogError("Full game probe summary write failed: " + ex.GetBaseException().Message); }
        Application.Quit(failed ? 2 : 0);
    }

    ProbeReport CreateReport(string completion)
    {
        return new ProbeReport
        {
            unity_version = Application.unityVersion, output_directory = outputDir, run_id = runId, completion = completion,
            start_utc = startedUtc ?? "",
            diagnostics_persistent_directory = Path.Combine(Application.persistentDataPath, "EndlessFallingDiagnostics"),
            run_start_backend_timestamp = level != null ? level.RunStartBackendTimestamp : double.NaN,
            error = error, failed = failed, requested_running_seconds = RequestedRunSeconds, target_frame_rate = Application.targetFrameRate,
            v_sync_count = QualitySettings.vSyncCount, run_in_background = Application.runInBackground,
            gc_mode = UnityEngine.Scripting.GarbageCollector.GCMode.ToString(), incremental_gc = UnityEngine.Scripting.GarbageCollector.isIncremental,
            dotnet_gc_latency_mode = GCSettingsMode(), used_managed_bytes_start = usedMemoryStart, mono_heap_bytes_start = monoHeapStart,
            ui_manager_found_and_enabled = ui != null && ui.enabled,
            redirected_backend_endpoint = SyntheticHost + ":" + SyntheticPort,
            redirected_receiver_endpoint = SyntheticHost + ":" + ReceiverPort,
            redirected_telemetry_endpoint = SyntheticHost + ":" + SyntheticPort,
            telemetry_send_rate_hz = udp != null ? udp.sendRate : 0f,
            geometry_diagnostic_sample_interval = udp != null ? udp.geometryDiagnosticSampleInterval : 0f,
            geometry_boundary_scan_samples = udp != null ? udp.geometryBoundaryScanSamples : 0,
            geometry_boundary_refinement_steps = udp != null ? udp.geometryBoundaryRefinementSteps : 0,
            geometry_diagnostics_enabled = udp != null && udp.enableGeometryDiagnostics,
            model_warning_enabled = receiver != null && receiver.enableExperimentalModelWarning,
            geometry_warning_enabled = receiver != null && receiver.enableExperimentalGeometryWarning,
            proximity_warning_enabled = receiver != null && receiver.enableExperimentalProximityWarning,
            verbose_observation_logs = receiver != null && (bool)Need(typeof(UdpFrontendReceiver), "verboseObservationLogs").GetValue(receiver),
            show_edge_warning_debug_hud = ui != null && ui.showEdgeWarningDebugHud,
            show_top_title = ui != null && (bool)Need(typeof(UIManager), "showTopTitle").GetValue(ui),
            hud_group_anchor = ui != null ? (Vector2)Need(typeof(UIManager), "hudGroupAnchor").GetValue(ui) : Vector2.zero,
            hud_card_size = ui != null ? (Vector2)Need(typeof(UIManager), "hudCardSize").GetValue(ui) : Vector2.zero,
            hud_card_vertical_gap = ui != null ? (float)Need(typeof(UIManager), "hudCardVerticalGap").GetValue(ui) : 0f,
            configured_calibration_duration = level != null ? level.calibrationDuration : 0f,
            time_scale_at_start = startTimeScale, maximum_delta_time = Time.maximumDeltaTime, gravity = Physics.gravity,
            high_frequency_light_diagnostics_enabled = udp != null && udp.enableHighFrequencyLightDiagnostics,
            high_frequency_light_interval = udp != null ? udp.highFrequencyLightSampleInterval : 0f,
            event_driven_full_geometry_enabled = udp != null && udp.enableEventDrivenFullGeometryDiagnostics,
            fixed_cadence_full_geometry_enabled = udp != null && udp.enableFixedCadenceFullGeometryDiagnostics,
            fixed_full_geometry_interval = udp != null ? udp.fixedFullGeometrySampleInterval : 0f,
            event_full_geometry_min_interval = udp != null ? udp.eventDrivenFullGeometryMinInterval : 0f,
            full_geometry_budget_ms = udp != null ? udp.fullGeometryBudgetMilliseconds : 0f,
            diagnostic_files_before = diagnosticFilesAtStart
        };
    }

    RunSnapshot Snapshot()
    {
        return new RunSnapshot
        {
            state = level != null ? level.RunState.ToString() : "missing", run_id = level != null ? level.RunId : "",
            outcome = level != null ? level.SessionOutcome : "", current_layer = level != null ? level.GetCurrentLayer() : -1,
            selected_layers = level != null ? level.SelectedSessionLayers : -1, selected_difficulty = level != null ? level.SelectedDifficulty : -1,
            commanded_difficulty = level != null ? level.CommandedDifficulty : -1, calibration_mode = level != null && level.CalibrationMode,
            calibration_stage = level != null && level.IsCalibrationStage, backend_difficulty_enabled = level != null && level.useBackendDifficulty,
            dda_enabled = level != null && level.enableDDA, input_sensitivity = player != null ? player.inputSensitivity : -1f,
            platforms_passed = level != null ? level.GetPassedCount() : -1, realtime_packet_count = receiver != null ? receiver.backendCountX : -1,
            model_watermark = ReadLong(modelWatermark, receiver), geometry_watermark = ReadLong(geometryWatermark, receiver), proximity_watermark = ReadLong(proximityWatermark, receiver),
            model_active = receiver != null && receiver.ExperimentalModelWarningActive,
            geometry_active = receiver != null && receiver.ExperimentalGeometryWarningActive,
            proximity_active = receiver != null && receiver.ExperimentalProximityWarningActive
        };
    }

    string[] DiagnosticFiles()
    {
        string folder = Path.Combine(Application.persistentDataPath, "EndlessFallingDiagnostics");
        if (!Directory.Exists(folder)) return Array.Empty<string>();
        string[] files = Directory.GetFiles(folder, "*.jsonl", SearchOption.TopDirectoryOnly);
        for (int i = 0; i < files.Length; i++) files[i] = Path.GetFileName(files[i]);
        return files;
    }
    static long ReadLong(FieldInfo field, object target) => field != null && target != null ? (long)field.GetValue(target) : -1L;
    long ReadTelemetrySequence() => udp != null && udp.LastTelemetry != null ? udp.LastTelemetry.sequence : -1L;
    static string ReadArg(string[] args, string key) { for (int i = 0; i + 1 < args.Length; i++) if (args[i] == key) return args[i + 1]; return null; }
    static string GCSettingsMode() { try { return GCSettings.LatencyMode.ToString(); } catch { return "unknown"; } }

    void WriteFailureAndQuit()
    {
        if (uiOnGuiRecorderAvailable) { uiOnGuiRecorder.Dispose(); uiOnGuiRecorderAvailable = false; }
        try
        {
            Directory.CreateDirectory(outputDir);
            ProbeReport report = CreateReport("failed_before_run"); report.error = error; report.frame_gaps_over_100ms = Array.Empty<LongFrameEvent>();
            File.WriteAllText(Path.Combine(outputDir, "failure.json"), JsonUtility.ToJson(report, true), new UTF8Encoding(false));
        }
        catch (Exception ex) { UnityEngine.Debug.LogError("Full game probe failure report could not be written: " + ex.GetBaseException().Message); }
        Application.Quit(2);
    }
}
#endif
