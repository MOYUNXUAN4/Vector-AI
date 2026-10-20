using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Unity.Profiling;

public class UdpFrontendReceiver : MonoBehaviour
{
    private static readonly ProfilerMarker RawFieldMarker = new ProfilerMarker("VectorAI.Receiver.RawField");
    private static readonly ProfilerMarker ExtractObjectMarker = new ProfilerMarker("VectorAI.Receiver.ExtractObject");
    private static readonly ProfilerMarker SkipValueMarker = new ProfilerMarker("VectorAI.Receiver.SkipValue");
    private static readonly ProfilerMarker SequenceMarker = new ProfilerMarker("VectorAI.Receiver.Sequence");
    private static readonly ProfilerMarker ExtensionsMarker = new ProfilerMarker("VectorAI.Receiver.Extensions");
    private static readonly ProfilerMarker DeserializeBaseMarker = new ProfilerMarker("VectorAI.Receiver.DeserializeBase");
    private static readonly ProfilerMarker DeserializeRealtimeMarker = new ProfilerMarker("VectorAI.Receiver.DeserializeRealtime");
    private static readonly ProfilerMarker DeserializeModelMarker = new ProfilerMarker("VectorAI.Receiver.DeserializeModel");
    private static readonly ProfilerMarker DeserializeGeometryMarker = new ProfilerMarker("VectorAI.Receiver.DeserializeGeometry");
    private static readonly ProfilerMarker DeserializeProximityMarker = new ProfilerMarker("VectorAI.Receiver.DeserializeProximity");
    [System.ThreadStatic] private static WarningJsonExtractionScope currentWarningJsonExtractionScope;

    private sealed class WarningJsonExtractionScope : System.IDisposable
    {
        private WarningJsonExtractionScope previousScope;
        private string source;
        private string modelWarningJson;
        private string geometryWarningJson;
        private string proximityWarningJson;
        private bool modelResolved;
        private bool geometryResolved;
        private bool proximityResolved;
        private bool modelSucceeded;
        private bool geometrySucceeded;
        private bool proximitySucceeded;
        private bool disposed;

        public WarningJsonExtractionScope(string rawJson)
        {
            source = rawJson;
            previousScope = currentWarningJsonExtractionScope;
            currentWarningJsonExtractionScope = this;
        }

        public bool TryGet(string rawJson, string fieldName, out bool handled, out string objectJson)
        {
            handled = false;
            objectJson = string.Empty;
            if (disposed || !object.ReferenceEquals(source, rawJson)) return false;

            if (string.Equals(fieldName, "model_warning", System.StringComparison.Ordinal))
            {
                handled = true;
                return Resolve(rawJson, fieldName, ref modelResolved, ref modelSucceeded, ref modelWarningJson, out objectJson);
            }
            if (string.Equals(fieldName, "geometry_warning", System.StringComparison.Ordinal))
            {
                handled = true;
                return Resolve(rawJson, fieldName, ref geometryResolved, ref geometrySucceeded, ref geometryWarningJson, out objectJson);
            }
            if (string.Equals(fieldName, "proximity_warning", System.StringComparison.Ordinal))
            {
                handled = true;
                return Resolve(rawJson, fieldName, ref proximityResolved, ref proximitySucceeded, ref proximityWarningJson, out objectJson);
            }
            return false;
        }

        private static bool Resolve(string rawJson, string fieldName, ref bool resolved, ref bool succeeded,
            ref string cachedJson, out string objectJson)
        {
            if (!resolved)
            {
                succeeded = TryExtractJsonObjectUncached(rawJson, fieldName, out cachedJson);
                resolved = true;
            }
            objectJson = succeeded ? cachedJson : string.Empty;
            return succeeded;
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            if (object.ReferenceEquals(currentWarningJsonExtractionScope, this))
            {
                WarningJsonExtractionScope restore = previousScope;
                while (restore != null && restore.disposed) restore = restore.previousScope;
                currentWarningJsonExtractionScope = restore;
                previousScope = null;
            }
            source = null;
            modelWarningJson = null;
            geometryWarningJson = null;
            proximityWarningJson = null;
        }
    }

    public static UdpFrontendReceiver Instance { get; private set; }

    [Header("Experimental Model Warning (display only)")]
    [Tooltip("Displays validated backend LightGBM STRONG warnings separately from the existing yellow warning.")]
    public bool enableExperimentalModelWarning = false;

    [Header("Experimental Geometry Warning (display only)")]
    [Tooltip("Displays the independent backend outer-clearance geometry rule separately from AI and the existing yellow warning.")]
    public bool enableExperimentalGeometryWarning = true;

    [Header("Experimental Proximity Warning (display only)")]
    [Tooltip("Displays the independent deterministic TTE proximity rule without changing movement or gameplay predicates.")]
    public bool enableExperimentalProximityWarning = false;

    [Header("Diagnostics & Logging")]
    [Tooltip("When false, suppresses per-prediction high-frequency RECEIVED logs to eliminate console allocations and I/O stalls.")]
    [SerializeField] private bool verboseObservationLogs = false;

    private const double ExperimentalModelWarningMaxAgeSeconds = 0.3d;
    private const double ExperimentalGeometryWarningMaxAgeSeconds = 0.3d;
    private const double ExperimentalProximityWarningMaxAgeSeconds = 0.3d;
    private const double ExperimentalProximityWarningHorizonSeconds = 0.75d;
    private const double ExperimentalProximityAgeToleranceSeconds = 1e-9d;
    private const string ExperimentalProximitySource = "tte_proximity_rule_v1";
    private const string ExperimentalProximityPolicyId = "tte_proximity_h075_confirm2_v1";
    private bool experimentalModelWarningActive;
    private string activeExperimentalModelId = string.Empty;
    private string activeExperimentalRunId = string.Empty;
    private string activeExperimentalReason = string.Empty;
    private float activeExperimentalStrongProbability;
    private long activeExperimentalPredictionSequence = -1;
    private double activeExperimentalReceiveMonotonicSeconds;
    private float activeExperimentalFeatureAgeSeconds;
    private string trackedExperimentalRunId = string.Empty;
    private string lastObservedExperimentalRunId = string.Empty;
    private int trackedExperimentalLayer = -1;
    private long highestExperimentalPredictionSequence = -1;
    private bool hasExperimentalPredictionSequence;
    private long highestExperimentalInputSequence = -1;
    private bool hasExperimentalInputSequence;
    private double highestExperimentalInputSourceTimestamp = double.NegativeInfinity;
    private bool hasExperimentalInputSourceTimestamp;
    private long highestRevokedExperimentalPredictionSequence = -1;
    private long highestExperimentalWarningUpdateSequence = -1;
    private bool hasExperimentalWarningUpdateSequence;
    private bool experimentalGeometryWarningActive;
    private string activeExperimentalGeometryRunId = string.Empty;
    private string activeExperimentalGeometryReason = string.Empty;
    private float activeExperimentalGeometryClearance;
    private int activeExperimentalGeometryPlatformInstanceId;
    private int activeExperimentalGeometryLayer = -1;
    private string activeExperimentalGeometryVersionId = string.Empty;
    private long activeExperimentalGeometryInputSequence = -1;
    private double activeExperimentalGeometryReceiveMonotonicSeconds;
    private double activeExperimentalGeometryAgeAtReceiveSeconds;
    private int trackedExperimentalGeometryPlatformInstanceId;
    private string trackedExperimentalGeometryVersionId = string.Empty;
    private long highestExperimentalGeometryWarningUpdateSequence = -1;
    private bool hasExperimentalGeometryWarningUpdateSequence;
    private long highestExperimentalGeometryInputSequence = -1;
    private bool hasExperimentalGeometryInputSequence;
    private double highestExperimentalGeometryInputSourceTimestamp = double.NegativeInfinity;
    private bool hasExperimentalGeometryInputSourceTimestamp;
    private double highestExperimentalGeometryQueryAgeSeconds;
    private double highestExperimentalGeometrySampleAgeSeconds;
    private double highestExperimentalGeometryAgeSeconds;
    private long highestRevokedExperimentalGeometryInputSequence = -1;
    private int observedExperimentalGeometryPlatformInstanceId;
    private string observedExperimentalGeometryVersionId = string.Empty;
    private bool hasObservedExperimentalGeometryContext;
    private string lastGeometryValidationDiagnosticSignature = string.Empty;
    private string lastGeometryValidationDiagnosticContext = string.Empty;
    private int geometryValidationDiagnosticSuppressedCount;
    private int geometryValidationDiagnosticReportedSuppressedCount;
    private long layerInputSequenceFloor = -1;
    private bool hasLayerInputSequenceFloor;
    private long layerPredictionSequenceFloor = -1;
    private string lastObservedExperimentalState = string.Empty;

    private bool experimentalProximityWarningActive;
    private string activeExperimentalProximityRunId = string.Empty;
    private string activeExperimentalProximityReason = string.Empty;
    private string activeExperimentalProximityState = string.Empty;
    private int activeExperimentalProximityLayer = -1;
    private int activeExperimentalProximityPlatformInstanceId;
    private string activeExperimentalProximityVersionId = string.Empty;
    private long activeExperimentalProximityInputSequence = -1;
    private double activeExperimentalProximityInputSourceTimestamp;
    private long activeExperimentalProximityWarningUpdateSequence = -1;
    private double activeExperimentalProximityQ;
    private double activeExperimentalProximityOutwardVelocity;
    private double activeExperimentalProximityHorizonSeconds;
    private double activeExperimentalProximityReceiveMonotonicSeconds;
    private double activeExperimentalProximityAgeAtReceiveSeconds;
    private long highestExperimentalProximityWarningUpdateSequence = -1;
    private bool hasExperimentalProximityWarningUpdateSequence;
    private long highestExperimentalProximityInputSequence = -1;
    private bool hasExperimentalProximityInputSequence;
    private double highestExperimentalProximityInputSourceTimestamp = double.NegativeInfinity;
    private bool hasExperimentalProximityInputSourceTimestamp;
    private double highestExperimentalProximityQueryAgeSeconds;
    private double highestExperimentalProximitySampleAgeSeconds;
    private double highestExperimentalProximityAgeSeconds;
    private long highestRevokedExperimentalProximityInputSequence = -1;
    private int observedExperimentalProximityPlatformInstanceId;
    private string observedExperimentalProximityVersionId = string.Empty;
    private bool hasObservedExperimentalProximityContext;

    [System.Serializable]
    public class ModelWarningPacket
    {
        public int schema_version;
        public bool experimental;
        public bool enabled;
        public string model_id;
        public string run_id;
        public int layer;
        public string state;
        public bool valid;
        public bool probability_valid;
        public float strong_probability;
        public long prediction_sequence;
        public long warning_update_sequence;
        public long input_sequence;
        public double input_source_timestamp;
        public float feature_age_seconds;
        public string reason;
    }

    [Header("网络配置")]
    public int listenPort = 5006;           // Unity 监听 Python 发来数据的端口
    public int targetPythonPort = 5005;     // 👈 【核心修改】Python 服务器的端口 (Infinite Fall 填 5005, Path Following 填 5007)
    
    [Header("游戏组件绑定")]
    public EndlessPlayerController targetPlayer; 
    public LevelManager levelManager; 

    private UdpClient udpClient;
    private Thread receiveThread;
    private bool startSessionSent;
    
    private readonly object dataLock = new object();
    private string pendingJsonData = null;
    private double pendingReceiveMonotonicSeconds;

    // ==========================================
    // 【核心】：供报告面板读取的后端真实数据
    // ==========================================
    public float backendRealRMSE = 0f;
    public float backendSumX = 0f;
    public int backendCountX = 0;

    // --- 数据包结构定义 ---
    
    // 基础包：用来判断是哪种类型的数据
    [System.Serializable]
    public class BasePacket
    {
        public string type;
    }

    [System.Serializable]
    public class CoPPacket
    {
        public string type;
        public float x;
        public float y;
        public int difficulty;
        public float rmse;
    }

    [System.Serializable]
    private class RealtimeDataPacket
    {
        public string type;
        public float x;
        public float y;
        public int difficulty;
        public float rmse;
    }

    [System.Serializable]
    public class GeometryWarningPacket
    {
        public int schema_version;
        public bool experimental;
        public bool enabled;
        public string source;
        public string policy_id;
        public string run_id;
        public int layer;
        public int platform_instance_id;
        public string geometry_version_id;
        public long input_sequence;
        public double input_source_timestamp;
        public long warning_update_sequence;
        public float clearance;
        public bool clearance_valid;
        public string state;
        public bool valid;
        public string reason;
        public double sample_age_seconds;
        public double query_age_seconds;
        public double geometry_age_seconds;
    }

    [System.Serializable]
    public class ProximityWarningPacket
    {
        public int schema_version;
        public bool experimental;
        public bool enabled;
        public string source;
        public string policy_id;
        public string run_id;
        public int layer;
        public int platform_instance_id;
        public string geometry_version_id;
        public long input_sequence;
        public double input_source_timestamp;
        public long warning_update_sequence;
        public string state;
        public bool active;
        public bool valid;
        public double sample_age_seconds;
        public double query_age_seconds;
        public double geometry_age_seconds;
        public double q;
        public bool q_valid;
        public double outward_velocity;
        public double horizon_seconds;
        public string reason;
    }

    [System.Serializable]
    private class ModelWarningIdentityPacket
    {
        public string run_id;
    }

    [System.Serializable]
    private class GeometryWarningIdentityPacket
    {
        public string run_id;
    }


    [System.Serializable]
    private class StartSessionPacket
    {
        public string command;
        public string nickname;
        public string run_id;
        public bool calibration_mode;
        public int selected_session_layers;
        public string selected_difficulty;
        public int commanded_difficulty;
    }

    // AI 聊天/报告数据包
    [System.Serializable]
    public class AIReplyPacket
    {
        public string type;
        public string content;
    }

    void Awake()
    {
        Instance = this;
    }

    void Start()
    {
        if (levelManager == null) levelManager = FindFirstObjectByType<LevelManager>();

        try 
        {
            // 1. 建立 UDP 客户端并开始监听后端发来的数据
            IPEndPoint localEndPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), listenPort);
            udpClient = new UdpClient(localEndPoint);
            
            receiveThread = new Thread(new ThreadStart(ReceiveDataLoop));
            receiveThread.IsBackground = true;
            receiveThread.Start();
        }
        catch (System.Exception e) { Debug.LogError($"接收器启动失败: {e.Message}"); }
    }

    public void SendStartSession()
    {
        if (udpClient == null || startSessionSent || levelManager == null || !levelManager.IsRunRunning) return;
        startSessionSent = true;

        string playerName = PlayerPrefs.GetString("CurrentPlayer", "Guest");
        string runId = levelManager != null ? levelManager.RunId : string.Empty;
        StartSessionPacket packet = new StartSessionPacket
        {
            command = "start_session",
            nickname = playerName,
            run_id = runId,
            calibration_mode = levelManager != null && levelManager.CalibrationMode,
            selected_session_layers = levelManager != null ? levelManager.SelectedSessionLayers : 25,
            selected_difficulty = levelManager != null ? levelManager.SelectedDifficultyLabel : "Auto",
            commanded_difficulty = levelManager != null ? levelManager.CommandedDifficulty : 1
        };
        byte[] sendBytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(packet));
        IPEndPoint pythonServer = new IPEndPoint(IPAddress.Parse("127.0.0.1"), targetPythonPort);
        udpClient.Send(sendBytes, sendBytes.Length, pythonServer);
        Debug.Log($"[UDP] Sent start_session to {targetPythonPort}, player={playerName}, run_id={runId}");
    }

    void Update()
    {
        SynchronizeExperimentalWarningContext();
        SynchronizeExperimentalGeometryTelemetryContext();
        SynchronizeExperimentalProximityTelemetryContext();
        ExpireExperimentalModelWarningIfNeeded();
        ExpireExperimentalGeometryWarningIfNeeded();
        ExpireExperimentalProximityWarningIfNeeded();
        string jsonToParse = null;
        double jsonReceiveMonotonicSeconds = 0d;

        lock (dataLock)
        {
            if (!string.IsNullOrEmpty(pendingJsonData))
            {
                jsonToParse = pendingJsonData;
                jsonReceiveMonotonicSeconds = pendingReceiveMonotonicSeconds;
                pendingJsonData = null;
                pendingReceiveMonotonicSeconds = 0d;
            }
        }

        if (jsonToParse == null) return;

        bool isRealtimePacket = false;
        try
        {
            BasePacket basePacket;
            using (DeserializeBaseMarker.Auto())
                basePacket = JsonUtility.FromJson<BasePacket>(jsonToParse);
            isRealtimePacket = basePacket != null &&
                (basePacket.type == "realtime" || string.IsNullOrEmpty(basePacket.type));

            if (basePacket != null && basePacket.type == "ai_report")
            {
                AIReplyPacket aiPacket = JsonUtility.FromJson<AIReplyPacket>(jsonToParse);
                if (UIManager.Instance != null) UIManager.Instance.ReceiveAIResponse(aiPacket.content);
            }
            else if (isRealtimePacket)
            {
                RealtimeDataPacket latestData;
                using (DeserializeRealtimeMarker.Auto())
                    latestData = JsonUtility.FromJson<RealtimeDataPacket>(jsonToParse);
                if (latestData == null) throw new System.FormatException("Realtime reply was empty.");

                backendRealRMSE = latestData.rmse;
                backendSumX += latestData.x;
                backendCountX++;

                if (targetPlayer != null) targetPlayer.SetExternalWbbData(latestData.x, latestData.y);
                if (levelManager != null && latestData.difficulty > 0)
                    levelManager.SetDifficultyFromAI(latestData.difficulty);

                HandleRealtimeExperimentalWarnings(jsonToParse, jsonReceiveMonotonicSeconds);
            }
        }
        catch (System.Exception e)
        {
            // With no trustworthy model-warning/run identity this datagram cannot
            // be allowed to revoke a current-run prompt. Its independent lease will
            // still expire under total silence.
            Debug.LogWarning($"JSON 解析失败，可能收到残缺包: {e.Message} \n原数据: {jsonToParse}");
        }
    }

    public static void NotifyRunStarted(string runId)
    {
        if (Instance != null) Instance.ResetExperimentalWarningForRun(runId);
    }

    public static void NotifyRunEnded(string reason)
    {
        if (Instance != null)
        {
            Instance.ClearExperimentalModelWarning(reason ?? "run_ended");
            Instance.ClearExperimentalGeometryWarning(reason ?? "run_ended");
            Instance.ClearExperimentalProximityWarning(reason ?? "run_ended");
            Instance.observedExperimentalGeometryPlatformInstanceId = 0;
            Instance.observedExperimentalGeometryVersionId = string.Empty;
            Instance.hasObservedExperimentalGeometryContext = false;
        }
    }

    public static void NotifyLayerTransition()
    {
        if (Instance != null) Instance.HandleExperimentalLayerTransition();
    }

    public bool ExperimentalModelWarningActive =>
        enableExperimentalModelWarning && experimentalModelWarningActive;
    public string ExperimentalModelId => activeExperimentalModelId;
    public string ExperimentalModelRunId => activeExperimentalRunId;
    public string ExperimentalModelReason => activeExperimentalReason;
    public float ExperimentalModelStrongProbability => activeExperimentalStrongProbability;
    public long ExperimentalModelPredictionSequence => activeExperimentalPredictionSequence;
    public bool ExperimentalGeometryWarningActive =>
        enableExperimentalGeometryWarning && experimentalGeometryWarningActive;
    public float ExperimentalGeometryClearance => activeExperimentalGeometryClearance;
    public string ExperimentalGeometryRunId => activeExperimentalGeometryRunId;
    public string ExperimentalGeometryReason => activeExperimentalGeometryReason;
    public int ExperimentalGeometryPlatformInstanceId => activeExperimentalGeometryPlatformInstanceId;
    public string ExperimentalGeometryVersionId => activeExperimentalGeometryVersionId;
    public bool ExperimentalProximityWarningActive =>
        enableExperimentalProximityWarning && experimentalProximityWarningActive;
    public string ExperimentalProximityState => activeExperimentalProximityState;
    public string ExperimentalProximityRunId => activeExperimentalProximityRunId;
    public string ExperimentalProximityReason => activeExperimentalProximityReason;
    public int ExperimentalProximityLayer => activeExperimentalProximityLayer;
    public int ExperimentalProximityPlatformInstanceId => activeExperimentalProximityPlatformInstanceId;
    public string ExperimentalProximityVersionId => activeExperimentalProximityVersionId;
    public long ExperimentalProximityInputSequence => activeExperimentalProximityInputSequence;
    public long ExperimentalProximityWarningUpdateSequence => activeExperimentalProximityWarningUpdateSequence;
    public double ExperimentalProximityQ => activeExperimentalProximityQ;
    public double ExperimentalProximityOutwardVelocity => activeExperimentalProximityOutwardVelocity;
    public double ExperimentalProximityHorizonSeconds => activeExperimentalProximityHorizonSeconds;
    public double ExperimentalProximityAgeAtReceiveSeconds => activeExperimentalProximityAgeAtReceiveSeconds;

    private void SynchronizeExperimentalWarningContext()
    {
        if (levelManager == null) levelManager = FindFirstObjectByType<LevelManager>();
        if (levelManager == null || !levelManager.IsRunRunning || string.IsNullOrEmpty(levelManager.RunId))
        {
            if (!string.IsNullOrEmpty(trackedExperimentalRunId))
            {
                ClearExperimentalModelWarning("run_not_running");
                ClearExperimentalGeometryWarning("run_not_running");
                ClearExperimentalProximityWarning("run_not_running");
                observedExperimentalGeometryPlatformInstanceId = 0;
                observedExperimentalGeometryVersionId = string.Empty;
                hasObservedExperimentalGeometryContext = false;
                observedExperimentalProximityPlatformInstanceId = 0;
                observedExperimentalProximityVersionId = string.Empty;
                hasObservedExperimentalProximityContext = false;
            }
            return;
        }

        string runId = levelManager.RunId;
        int layer = levelManager.GetCurrentLayer();
        if (!string.Equals(trackedExperimentalRunId, runId, System.StringComparison.Ordinal))
        {
            ResetExperimentalWarningForRun(runId);
            trackedExperimentalLayer = layer;
            return;
        }

        if (trackedExperimentalLayer != layer)
        {
            HandleExperimentalLayerTransition();
            lastObservedExperimentalState = string.Empty;
            lastObservedExperimentalRunId = trackedExperimentalRunId;
        }
    }

    private void ResetExperimentalWarningForRun(string runId)
    {
        string nextRunId = runId ?? string.Empty;
        if (!string.IsNullOrEmpty(nextRunId) &&
            string.Equals(trackedExperimentalRunId, nextRunId, System.StringComparison.Ordinal))
        {
            return;
        }

        ClearExperimentalModelWarning("run_started");
        ClearExperimentalGeometryWarning("run_started");
        ClearExperimentalProximityWarning("run_started");
        observedExperimentalGeometryPlatformInstanceId = 0;
        observedExperimentalGeometryVersionId = string.Empty;
        hasObservedExperimentalGeometryContext = false;
        observedExperimentalProximityPlatformInstanceId = 0;
        observedExperimentalProximityVersionId = string.Empty;
        hasObservedExperimentalProximityContext = false;
        trackedExperimentalRunId = nextRunId;
        trackedExperimentalLayer = levelManager != null ? levelManager.GetCurrentLayer() : -1;
        lastObservedExperimentalRunId = trackedExperimentalRunId;
        ResetExperimentalSequenceTracking();
        SetLayerInputSequenceFloor();
    }

    private void ResetExperimentalSequenceTracking()
    {
        highestExperimentalPredictionSequence = -1;
        hasExperimentalPredictionSequence = false;
        highestExperimentalInputSequence = -1;
        hasExperimentalInputSequence = false;
        highestExperimentalInputSourceTimestamp = double.NegativeInfinity;
        hasExperimentalInputSourceTimestamp = false;
        highestRevokedExperimentalPredictionSequence = -1;
        highestExperimentalWarningUpdateSequence = -1;
        hasExperimentalWarningUpdateSequence = false;
        highestExperimentalGeometryWarningUpdateSequence = -1;
        hasExperimentalGeometryWarningUpdateSequence = false;
        highestExperimentalGeometryInputSequence = -1;
        hasExperimentalGeometryInputSequence = false;
        highestExperimentalGeometryInputSourceTimestamp = double.NegativeInfinity;
        hasExperimentalGeometryInputSourceTimestamp = false;
        highestExperimentalGeometryQueryAgeSeconds = 0d;
        highestExperimentalGeometrySampleAgeSeconds = 0d;
        highestExperimentalGeometryAgeSeconds = 0d;
        highestRevokedExperimentalGeometryInputSequence = -1;
        trackedExperimentalGeometryPlatformInstanceId = 0;
        trackedExperimentalGeometryVersionId = string.Empty;
        highestExperimentalProximityWarningUpdateSequence = -1;
        hasExperimentalProximityWarningUpdateSequence = false;
        highestExperimentalProximityInputSequence = -1;
        hasExperimentalProximityInputSequence = false;
        highestExperimentalProximityInputSourceTimestamp = double.NegativeInfinity;
        hasExperimentalProximityInputSourceTimestamp = false;
        highestExperimentalProximityQueryAgeSeconds = 0d;
        highestExperimentalProximitySampleAgeSeconds = 0d;
        highestExperimentalProximityAgeSeconds = 0d;
        highestRevokedExperimentalProximityInputSequence = -1;
        observedExperimentalProximityPlatformInstanceId = 0;
        observedExperimentalProximityVersionId = string.Empty;
        hasObservedExperimentalProximityContext = false;
        observedExperimentalGeometryPlatformInstanceId = 0;
        observedExperimentalGeometryVersionId = string.Empty;
        hasObservedExperimentalGeometryContext = false;
        layerInputSequenceFloor = -1;
        hasLayerInputSequenceFloor = false;
        layerPredictionSequenceFloor = -1;
    }

    private void HandleExperimentalLayerTransition()
    {
        trackedExperimentalLayer = levelManager != null ? levelManager.GetCurrentLayer() : -1;
        layerPredictionSequenceFloor = hasExperimentalPredictionSequence
            ? highestExperimentalPredictionSequence : -1;
        SetLayerInputSequenceFloor();
        ClearExperimentalModelWarning("layer_transition");
        ClearExperimentalGeometryWarning("layer_transition");
        ClearExperimentalProximityWarning("layer_transition");
        observedExperimentalGeometryPlatformInstanceId = 0;
        observedExperimentalGeometryVersionId = string.Empty;
        hasObservedExperimentalGeometryContext = false;
        observedExperimentalProximityPlatformInstanceId = 0;
        observedExperimentalProximityVersionId = string.Empty;
        hasObservedExperimentalProximityContext = false;
        trackedExperimentalGeometryPlatformInstanceId = 0;
        trackedExperimentalGeometryVersionId = string.Empty;
    }

    private void SetLayerInputSequenceFloor()
    {
        UDPManager.UnityGameTelemetry telemetry = UDPManager.Instance != null
            ? UDPManager.Instance.LastTelemetry : null;
        long telemetrySequence = telemetry != null ? telemetry.sequence : -1;
        hasLayerInputSequenceFloor = telemetrySequence >= 0 || hasExperimentalInputSequence;
        layerInputSequenceFloor = hasExperimentalInputSequence && highestExperimentalInputSequence > telemetrySequence
            ? highestExperimentalInputSequence : telemetrySequence;
    }

    private void HandleRealtimeExperimentalWarnings(string rawJson, double receiveMonotonicSeconds)
    {
        using (ExtensionsMarker.Auto())
        using (new WarningJsonExtractionScope(rawJson))
        {
        ModelWarningPacket modelWarning = null;
        if (TryExtractJsonObject(rawJson, "model_warning", out string modelWarningJson))
        {
            try
            {
                using (DeserializeModelMarker.Auto())
                    modelWarning = JsonUtility.FromJson<ModelWarningPacket>(modelWarningJson);
            }
            catch (System.Exception)
            {
                // A malformed experimental extension must not block ordinary realtime data.
            }
        }
        HandleExperimentalModelWarning(rawJson, modelWarning, receiveMonotonicSeconds);

        GeometryWarningPacket geometryWarning = null;
        if (TryExtractJsonObject(rawJson, "geometry_warning", out string geometryWarningJson))
        {
            try
            {
                using (DeserializeGeometryMarker.Auto())
                    geometryWarning = JsonUtility.FromJson<GeometryWarningPacket>(geometryWarningJson);
            }
            catch (System.Exception)
            {
                // Geometry validation is independent of model-warning and realtime parsing.
            }
        }
        HandleExperimentalGeometryWarning(rawJson, geometryWarning, receiveMonotonicSeconds);

        ProximityWarningPacket proximityWarning = null;
        if (TryExtractJsonObject(rawJson, "proximity_warning", out string proximityWarningJson))
        {
            try
            {
                using (DeserializeProximityMarker.Auto())
                    proximityWarning = JsonUtility.FromJson<ProximityWarningPacket>(proximityWarningJson);
            }
            catch (System.Exception)
            {
                // A malformed proximity extension must not block ordinary realtime,
                // model-warning, or geometry-warning handling.
            }
        }
        HandleExperimentalProximityWarning(rawJson, proximityWarning, receiveMonotonicSeconds);
        }
    }

    private void SynchronizeExperimentalGeometryTelemetryContext()
    {
        UDPManager manager = UDPManager.Instance;
        UDPManager.UnityGameTelemetry telemetry = manager != null ? manager.LastTelemetry : null;
        if (telemetry == null || levelManager == null ||
            !string.Equals(telemetry.run_id, levelManager.RunId, System.StringComparison.Ordinal)) return;

        if (telemetry.platformLevel != levelManager.GetCurrentLayer())
        {
            ClearExperimentalGeometryWarning("geometry_layer_context_changed");
            observedExperimentalGeometryPlatformInstanceId = 0;
            observedExperimentalGeometryVersionId = string.Empty;
            hasObservedExperimentalGeometryContext = false;
            return;
        }

        int platformId = telemetry.geometry_platform_instance_id;
        string versionId = telemetry.geometry_version_id ?? string.Empty;
        if (!hasObservedExperimentalGeometryContext && platformId != 0 && !string.IsNullOrWhiteSpace(versionId))
        {
            observedExperimentalGeometryPlatformInstanceId = platformId;
            observedExperimentalGeometryVersionId = versionId;
            hasObservedExperimentalGeometryContext = true;
        }

        if (platformId == 0 || string.IsNullOrWhiteSpace(versionId))
        {
            platformId = 0;
            versionId = string.Empty;
        }

        if (hasObservedExperimentalGeometryContext &&
            (platformId != observedExperimentalGeometryPlatformInstanceId ||
             !string.Equals(versionId, observedExperimentalGeometryVersionId, System.StringComparison.Ordinal)))
        {
            ClearExperimentalGeometryWarning("geometry_context_changed");
        }
        observedExperimentalGeometryPlatformInstanceId = platformId;
        observedExperimentalGeometryVersionId = versionId;
        hasObservedExperimentalGeometryContext = true;
    }

    private bool HasMatchingGeometryWarningIdentity(string rawJson, GeometryWarningPacket warning)
    {
        if (warning == null || warning.platform_instance_id == 0 ||
            string.IsNullOrWhiteSpace(warning.geometry_version_id) ||
            !TryGetJsonSignedInteger(rawJson, "geometry_warning", "platform_instance_id", out long platformId) ||
            platformId != warning.platform_instance_id ||
            !TryGetRawJsonFieldValue(rawJson, "geometry_warning", "geometry_version_id", out string rawVersion) ||
            rawVersion.Length < 2 || rawVersion[0] != '"' || rawVersion[rawVersion.Length - 1] != '"' ||
            rawVersion.IndexOf('\\', 1, rawVersion.Length - 2) >= 0) return false;

        string rawVersionId = rawVersion.Substring(1, rawVersion.Length - 2);
        return string.Equals(rawVersionId, warning.geometry_version_id, System.StringComparison.Ordinal);
    }

    private bool MatchesCurrentExperimentalGeometryContext(string rawJson, string runId, int layer)
    {
        UDPManager manager = UDPManager.Instance;
        UDPManager.UnityGameTelemetry telemetry = manager != null ? manager.LastTelemetry : null;
        if (telemetry == null || levelManager == null ||
            !string.Equals(telemetry.run_id, runId, System.StringComparison.Ordinal) ||
            !string.Equals(runId, levelManager.RunId, System.StringComparison.Ordinal) ||
            !TryGetGeometryWarningRunId(rawJson, out string packetRunId) ||
            !string.Equals(packetRunId, runId, System.StringComparison.Ordinal) ||
            !TryGetJsonSignedInteger(rawJson, "geometry_warning", "layer", out long packetLayer) ||
            packetLayer <= 0 || packetLayer != layer || layer != levelManager.GetCurrentLayer() ||
            telemetry.platformLevel != layer || telemetry.geometry_platform_instance_id == 0 ||
            string.IsNullOrWhiteSpace(telemetry.geometry_version_id) ||
            !TryGetJsonSignedInteger(rawJson, "geometry_warning", "platform_instance_id", out long platformId) ||
            platformId != telemetry.geometry_platform_instance_id ||
            !TryGetRawJsonFieldValue(rawJson, "geometry_warning", "geometry_version_id", out string rawVersion) ||
            rawVersion.Length < 2 || rawVersion[0] != '"' || rawVersion[rawVersion.Length - 1] != '"' ||
            rawVersion.IndexOf('\\', 1, rawVersion.Length - 2) >= 0) return false;

        return string.Equals(rawVersion.Substring(1, rawVersion.Length - 2),
            telemetry.geometry_version_id, System.StringComparison.Ordinal);
    }

    private bool MatchesCurrentExperimentalGeometryContext(GeometryWarningPacket warning)
    {
        UDPManager manager = UDPManager.Instance;
        UDPManager.UnityGameTelemetry telemetry = manager != null ? manager.LastTelemetry : null;
        if (telemetry == null || levelManager == null) return false;
        if (!string.Equals(telemetry.run_id, levelManager.RunId, System.StringComparison.Ordinal) ||
            telemetry.platformLevel != levelManager.GetCurrentLayer()) return false;

        return telemetry.geometry_platform_instance_id != 0 &&
               !string.IsNullOrWhiteSpace(telemetry.geometry_version_id) &&
               warning.platform_instance_id == telemetry.geometry_platform_instance_id &&
               string.Equals(warning.geometry_version_id, telemetry.geometry_version_id,
                   System.StringComparison.Ordinal);
    }

    private void HandleExperimentalGeometryWarning(
        string rawJson, GeometryWarningPacket warning, double receiveMonotonicSeconds)
    {
        if (!enableExperimentalGeometryWarning) return;
        if (levelManager == null || !levelManager.IsRunRunning || string.IsNullOrEmpty(levelManager.RunId))
            return;

        if (warning == null)
        {
            if (TryGetGeometryWarningRunId(rawJson, out string malformedRunId) &&
                string.Equals(malformedRunId, levelManager.RunId, System.StringComparison.Ordinal))
            {
                if (experimentalGeometryWarningActive &&
                    !MatchesCurrentExperimentalGeometryContext(rawJson, malformedRunId, levelManager.GetCurrentLayer()))
                    return;
                RevokeExperimentalGeometryInputSequence(-1);
                ClearExperimentalGeometryWarning("geometry_warning_malformed_or_missing");
            }
            return;
        }

        if (!string.Equals(warning.run_id, levelManager.RunId, System.StringComparison.Ordinal)) return;

        int currentLayer = levelManager.GetCurrentLayer();
        if (warning.layer <= 0) return;

        if (!TryGetPositiveWarningUpdateSequenceForObject(rawJson, "geometry_warning", out long parsedSequence) ||
            warning.warning_update_sequence != parsedSequence)
        {
            if (warning.layer == currentLayer)
            {
                if (experimentalGeometryWarningActive &&
                    (!MatchesCurrentExperimentalGeometryContext(warning) ||
                     !HasMatchingGeometryWarningIdentity(rawJson, warning))) return;
                if (string.Equals(warning.state, "CRITICAL", System.StringComparison.Ordinal))
                {
                    var sequenceFailures = new System.Collections.Generic.List<GeometryValidationDiagnosticCheck>();
                    if (!TryGetPositiveWarningUpdateSequenceForObject(rawJson, "geometry_warning", out long diagnosticSequence))
                        AddGeometryValidationDiagnosticCheck(sequenceFailures,
                            "warning_update_sequence.positive_integer", "present, unique JSON integer > 0", "warning_update_sequence");
                    else if (warning.warning_update_sequence != diagnosticSequence)
                        AddGeometryValidationDiagnosticCheck(sequenceFailures,
                            "warning_update_sequence.matches_deserialized", "raw sequence equals deserialized sequence", "warning_update_sequence");
                    LogGeometryWarningValidationFailure(rawJson, warning, receiveMonotonicSeconds, sequenceFailures);
                }
                RevokeExperimentalGeometryInputSequence(warning.input_sequence);
                ClearExperimentalGeometryWarning("geometry_warning_sequence_missing_or_invalid");
            }
            return;
        }
        if (hasExperimentalGeometryWarningUpdateSequence &&
            parsedSequence <= highestExperimentalGeometryWarningUpdateSequence)
        {
            return;
        }
        highestExperimentalGeometryWarningUpdateSequence = parsedSequence;
        hasExperimentalGeometryWarningUpdateSequence = true;

        // Old-layer packets advance only the run-wide ordering watermark; they
        // cannot activate or revoke the current layer's geometry display.
        if (warning.layer != currentLayer) return;

        bool contextMatches = MatchesCurrentExperimentalGeometryContext(warning);
        if (!contextMatches || !HasMatchingGeometryWarningIdentity(rawJson, warning)) return;

        string state = warning.state ?? string.Empty;
        if (state != "CRITICAL")
        {
            if (state == "CLEAR" || state == "UNKNOWN")
            {
                if (experimentalGeometryWarningActive &&
                    (warning.platform_instance_id != activeExperimentalGeometryPlatformInstanceId ||
                     !string.Equals(warning.geometry_version_id, activeExperimentalGeometryVersionId,
                         System.StringComparison.Ordinal))) return;
                RevokeExperimentalGeometryInputSequence(warning.input_sequence);
                ClearExperimentalGeometryWarning(state == "CLEAR" ? "geometry_clear" : "geometry_unknown");
            }
            else
            {
                if (experimentalGeometryWarningActive &&
                    (!MatchesCurrentExperimentalGeometryContext(warning) ||
                     !HasMatchingGeometryWarningIdentity(rawJson, warning))) return;
                RevokeExperimentalGeometryInputSequence(warning.input_sequence);
                ClearExperimentalGeometryWarning("geometry_warning_state_invalid");
            }
            return;
        }

        if (!HasRequiredGeometryWarningFields(rawJson))
        {
            LogGeometryWarningValidationFailure(rawJson, warning, receiveMonotonicSeconds,
                CollectMissingGeometryWarningFieldFailures(rawJson));
            RevokeExperimentalGeometryInputSequence(warning.input_sequence);
            ClearExperimentalGeometryWarning("geometry_warning_fields_missing");
            return;
        }
        if (!TryValidateCriticalGeometryWarning(warning, rawJson,
                out double normalizedSampleAge, out double normalizedQueryAge, out double normalizedGeometryAge))
        {
            LogGeometryWarningValidationFailure(rawJson, warning, receiveMonotonicSeconds,
                CollectCriticalGeometryWarningFailures(warning, rawJson));
            RevokeExperimentalGeometryInputSequence(warning.input_sequence);
            ClearExperimentalGeometryWarning("geometry_warning_invalid_or_incomplete_critical");
            return;
        }

        // From here through repeat detection and lease accounting, use only the
        // strict raw-JSON values that passed validation.
        warning.sample_age_seconds = normalizedSampleAge;
        warning.query_age_seconds = normalizedQueryAge;
        warning.geometry_age_seconds = normalizedGeometryAge;

        if ((hasExperimentalGeometryInputSequence && warning.input_sequence < highestExperimentalGeometryInputSequence) ||
            (hasExperimentalGeometryInputSourceTimestamp &&
             warning.input_source_timestamp < highestExperimentalGeometryInputSourceTimestamp))
        {
            return;
        }

        bool sameInputSequence = hasExperimentalGeometryInputSequence &&
                                 warning.input_sequence == highestExperimentalGeometryInputSequence;
        bool sameInputTimestamp = hasExperimentalGeometryInputSourceTimestamp &&
                                  warning.input_source_timestamp == highestExperimentalGeometryInputSourceTimestamp;
        if (sameInputSequence != sameInputTimestamp)
        {
            RevokeExperimentalGeometryInputSequence(warning.input_sequence);
            ClearExperimentalGeometryWarning("geometry_repeated_sample_identity_inconsistent");
            return;
        }

        bool repeatedSample = sameInputSequence && sameInputTimestamp;
        if (repeatedSample &&
            (warning.query_age_seconds + 1e-9d < highestExperimentalGeometryQueryAgeSeconds ||
             warning.sample_age_seconds + 1e-9d < highestExperimentalGeometrySampleAgeSeconds ||
             warning.geometry_age_seconds + 1e-9d < highestExperimentalGeometryAgeSeconds))
        {
            RevokeExperimentalGeometryInputSequence(warning.input_sequence);
            ClearExperimentalGeometryWarning("geometry_repeated_sample_freshness_regressed");
            return;
        }

        if (warning.input_sequence <= highestRevokedExperimentalGeometryInputSequence)
        {
            return;
        }

        if (!repeatedSample)
        {
            highestExperimentalGeometryInputSequence = warning.input_sequence;
            hasExperimentalGeometryInputSequence = true;
            highestExperimentalGeometryInputSourceTimestamp = warning.input_source_timestamp;
            hasExperimentalGeometryInputSourceTimestamp = true;
            highestExperimentalGeometryQueryAgeSeconds = warning.query_age_seconds;
            highestExperimentalGeometrySampleAgeSeconds = warning.sample_age_seconds;
            highestExperimentalGeometryAgeSeconds = warning.geometry_age_seconds;
        }
        else
        {
            highestExperimentalGeometryQueryAgeSeconds = warning.query_age_seconds;
            highestExperimentalGeometrySampleAgeSeconds = warning.sample_age_seconds;
            highestExperimentalGeometryAgeSeconds = warning.geometry_age_seconds;
        }

        if (warning.geometry_age_seconds > ExperimentalGeometryWarningMaxAgeSeconds)
        {
            RevokeExperimentalGeometryInputSequence(warning.input_sequence);
            ClearExperimentalGeometryWarning("geometry_sample_already_expired");
            return;
        }

        double currentTotalAge = activeExperimentalGeometryAgeAtReceiveSeconds +
            (GetMonotonicSeconds() - activeExperimentalGeometryReceiveMonotonicSeconds);
        if (experimentalGeometryWarningActive &&
            currentTotalAge > ExperimentalGeometryWarningMaxAgeSeconds)
        {
            RevokeExperimentalGeometryInputSequence(activeExperimentalGeometryInputSequence);
            ClearExperimentalGeometryWarning("geometry_age_exceeded_0_3s");
            return;
        }
        if (experimentalGeometryWarningActive && repeatedSample)
        {
            activeExperimentalGeometryAgeAtReceiveSeconds = System.Math.Max(
                currentTotalAge, warning.geometry_age_seconds);
            activeExperimentalGeometryReceiveMonotonicSeconds = GetMonotonicSeconds();
            activeExperimentalGeometryClearance = warning.clearance;
            activeExperimentalGeometryReason = warning.reason ?? string.Empty;
            return;
        }

        bool activatingGeometryWarning = !experimentalGeometryWarningActive;
        experimentalGeometryWarningActive = true;
        activeExperimentalGeometryRunId = warning.run_id;
        activeExperimentalGeometryReason = warning.reason ?? string.Empty;
        activeExperimentalGeometryClearance = warning.clearance;
        activeExperimentalGeometryPlatformInstanceId = warning.platform_instance_id;
        activeExperimentalGeometryLayer = warning.layer;
        activeExperimentalGeometryVersionId = warning.geometry_version_id;
        activeExperimentalGeometryInputSequence = warning.input_sequence;
        activeExperimentalGeometryAgeAtReceiveSeconds = warning.geometry_age_seconds;
        activeExperimentalGeometryReceiveMonotonicSeconds = receiveMonotonicSeconds;
        if (activatingGeometryWarning)
        {
            Debug.Log($"[ExperimentalGeometryWarning] active run={activeExperimentalGeometryRunId} " +
                      $"layer={activeExperimentalGeometryLayer} platform={activeExperimentalGeometryPlatformInstanceId} " +
                      $"input_sequence={activeExperimentalGeometryInputSequence} reason={activeExperimentalGeometryReason}");
        }
    }

    private void SynchronizeExperimentalProximityTelemetryContext()
    {
        if (!enableExperimentalProximityWarning)
        {
            ClearExperimentalProximityWarning("feature_disabled");
            observedExperimentalProximityPlatformInstanceId = 0;
            observedExperimentalProximityVersionId = string.Empty;
            hasObservedExperimentalProximityContext = false;
            return;
        }

        UDPManager manager = UDPManager.Instance;
        UDPManager.UnityGameTelemetry telemetry = manager != null ? manager.LastTelemetry : null;
        if (telemetry == null || levelManager == null ||
            !levelManager.IsRunRunning ||
            !string.Equals(telemetry.run_id, levelManager.RunId, System.StringComparison.Ordinal)) return;
        if (telemetry.platformLevel != levelManager.GetCurrentLayer()) return;

        int platformId = telemetry.geometry_platform_instance_id;
        string versionId = telemetry.geometry_version_id ?? string.Empty;
        bool hasIdentity = platformId != 0 && !string.IsNullOrWhiteSpace(versionId);
        int normalizedPlatformId = hasIdentity ? platformId : 0;
        string normalizedVersionId = hasIdentity ? versionId : string.Empty;

        if (hasObservedExperimentalProximityContext &&
            (normalizedPlatformId != observedExperimentalProximityPlatformInstanceId ||
             !string.Equals(normalizedVersionId, observedExperimentalProximityVersionId,
                 System.StringComparison.Ordinal)))
        {
            ClearExperimentalProximityWarning("proximity_context_changed");
        }

        observedExperimentalProximityPlatformInstanceId = normalizedPlatformId;
        observedExperimentalProximityVersionId = normalizedVersionId;
        hasObservedExperimentalProximityContext = true;
    }

    private bool IsCurrentExperimentalProximityProtocolEnvelope(
        string rawJson, ProximityWarningPacket warning, string state)
    {
        if (warning == null || (state != "APPROACH" && state != "CLEAR" && state != "UNKNOWN") ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "state", out string rawState) ||
            !string.Equals(rawState, state, System.StringComparison.Ordinal) ||
            !string.Equals(warning.state, state, System.StringComparison.Ordinal) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "source", out string source) ||
            !string.Equals(source, ExperimentalProximitySource, System.StringComparison.Ordinal) ||
            !string.Equals(warning.source, source, System.StringComparison.Ordinal) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "policy_id", out string policyId) ||
            !string.Equals(policyId, ExperimentalProximityPolicyId, System.StringComparison.Ordinal) ||
            !string.Equals(warning.policy_id, policyId, System.StringComparison.Ordinal) ||
            !TryGetJsonSignedInteger(rawJson, "proximity_warning", "schema_version", out long schemaVersion) ||
            schemaVersion != 1 || warning.schema_version != schemaVersion ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "experimental", out bool experimental) ||
            experimental != warning.experimental ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "enabled", out bool enabled) ||
            enabled != warning.enabled ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "active", out bool active) ||
            active != warning.active ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "valid", out bool valid) ||
            valid != warning.valid ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "q_valid", out bool qValid) ||
            qValid != warning.q_valid ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "run_id", out string runId) ||
            !string.Equals(runId, warning.run_id, System.StringComparison.Ordinal) ||
            !TryGetJsonSignedInteger(rawJson, "proximity_warning", "layer", out long layer) ||
            layer < int.MinValue || layer > int.MaxValue || warning.layer != (int)layer ||
            !TryGetProximityPlatformId(rawJson, out int platformId) ||
            warning.platform_instance_id != platformId ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "geometry_version_id", out string versionId) ||
            !string.Equals(versionId, warning.geometry_version_id, System.StringComparison.Ordinal) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "reason", out string reason) ||
            !string.Equals(reason, warning.reason ?? string.Empty, System.StringComparison.Ordinal)) return false;

        return true;
    }

    private bool IsCurrentExperimentalProximityContext(string rawJson)
    {
        if (levelManager == null || !levelManager.IsRunRunning || string.IsNullOrEmpty(levelManager.RunId) ||
            !TryGetWarningRunId(rawJson, "proximity_warning", out string packetRunId) ||
            !string.Equals(packetRunId, levelManager.RunId, System.StringComparison.Ordinal) ||
            !TryGetJsonSignedInteger(rawJson, "proximity_warning", "layer", out long packetLayer) ||
            !TryGetProximityPlatformId(rawJson, out int packetPlatformId) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning",
                "geometry_version_id", out string packetVersionId)) return false;

        UDPManager manager = UDPManager.Instance;
        UDPManager.UnityGameTelemetry telemetry = manager != null ? manager.LastTelemetry : null;
        int currentLayer = levelManager.GetCurrentLayer();
        if (telemetry == null || !levelManager.IsRunRunning ||
            !string.Equals(telemetry.run_id, levelManager.RunId, System.StringComparison.Ordinal) ||
            telemetry.platformLevel != currentLayer) return false;

        return packetLayer == currentLayer &&
               telemetry.platformLevel == currentLayer &&
               string.Equals(telemetry.run_id, levelManager.RunId, System.StringComparison.Ordinal) &&
               telemetry.geometry_platform_instance_id != 0 &&
               !string.IsNullOrWhiteSpace(telemetry.geometry_version_id) &&
               packetPlatformId == telemetry.geometry_platform_instance_id &&
               string.Equals(packetVersionId, telemetry.geometry_version_id,
                   System.StringComparison.Ordinal);
    }

    private static bool TryGetProximityPlatformId(string rawJson, out int platformId)
    {
        platformId = 0;
        if (!TryGetJsonSignedInteger(rawJson, "proximity_warning", "platform_instance_id",
                out long parsedPlatformId) ||
            parsedPlatformId < int.MinValue || parsedPlatformId > int.MaxValue)
            return false;
        platformId = (int)parsedPlatformId;
        return true;
    }

    private static bool TryGetRawJsonStringWithoutEscapes(
        string rawJson, string objectName, string fieldName, out string value)
    {
        value = string.Empty;
        if (!TryGetRawJsonFieldValue(rawJson, objectName, fieldName, out string rawValue) ||
            rawValue.Length < 2 || rawValue[0] != '"' ||
            rawValue[rawValue.Length - 1] != '"') return false;
        int contentLength = rawValue.Length - 2;
        if (rawValue.IndexOf('\\', 1, contentLength) >= 0) return false;
        value = rawValue.Substring(1, contentLength);
        return true;
    }

    private static bool TryGetRawJsonBoolean(
        string rawJson, string objectName, string fieldName, out bool value)
    {
        value = false;
        if (!TryGetRawJsonFieldValue(rawJson, objectName, fieldName, out string rawValue)) return false;
        if (rawValue == "true") { value = true; return true; }
        if (rawValue == "false") return true;
        return false;
    }

    private static bool TryGetProximityInputIdentity(
        string rawJson, out long inputSequence, out double inputTimestamp)
    {
        inputSequence = -1;
        inputTimestamp = 0d;
        return TryGetJsonSignedInteger(rawJson, "proximity_warning", "input_sequence",
                   out inputSequence) && inputSequence > 0 &&
               TryGetFiniteJsonNumber(rawJson, "proximity_warning", "input_source_timestamp",
                   out inputTimestamp) && inputTimestamp > 0d;
    }

    private static bool TryValidateExperimentalProximityWarning(
        string rawJson, ProximityWarningPacket warning,
        out long warningUpdateSequence, out long inputSequence, out double inputTimestamp,
        out double sampleAge, out double queryAge, out double geometryAge,
        out double q, out double outwardVelocity, out double horizonSeconds,
        out string state, out string runId, out int layer, out int platformId,
        out string geometryVersionId)
    {
        warningUpdateSequence = -1;
        inputSequence = -1;
        inputTimestamp = 0d;
        sampleAge = 0d;
        queryAge = 0d;
        geometryAge = 0d;
        q = 0d;
        outwardVelocity = 0d;
        horizonSeconds = 0d;
        state = string.Empty;
        runId = string.Empty;
        layer = 0;
        platformId = 0;
        geometryVersionId = string.Empty;
        bool reasonIsString = TryGetRawJsonStringWithoutEscapes(rawJson,
            "proximity_warning", "reason", out string reason);
        if (warning == null || !reasonIsString ||
            !string.Equals(reason, warning.reason ?? string.Empty, System.StringComparison.Ordinal) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "state", out state) ||
            (state != "APPROACH" && state != "CLEAR" && state != "UNKNOWN") ||
            !string.Equals(state, warning.state, System.StringComparison.Ordinal) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "run_id", out runId) ||
            string.IsNullOrEmpty(runId) || !string.Equals(runId, warning.run_id, System.StringComparison.Ordinal) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "source", out string source) ||
            source != ExperimentalProximitySource ||
            !string.Equals(source, warning.source, System.StringComparison.Ordinal) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "policy_id", out string policyId) ||
            policyId != ExperimentalProximityPolicyId ||
            !string.Equals(policyId, warning.policy_id, System.StringComparison.Ordinal) ||
            !TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "geometry_version_id", out geometryVersionId) ||
            !string.Equals(geometryVersionId, warning.geometry_version_id, System.StringComparison.Ordinal) ||
            !ContainsJsonField(TryExtractJsonObject(rawJson, "proximity_warning", out string warningJson)
                ? warningJson : string.Empty, "reason")) return false;

        if (!TryGetJsonSignedInteger(rawJson, "proximity_warning", "schema_version", out long schemaVersion) ||
            schemaVersion != 1 || warning.schema_version != schemaVersion ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "experimental", out bool experimental) ||
            experimental != warning.experimental ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "enabled", out bool enabled) ||
            enabled != warning.enabled ||
            !TryGetJsonSignedInteger(rawJson, "proximity_warning", "layer", out long parsedLayer) ||
            parsedLayer < int.MinValue || parsedLayer > int.MaxValue ||
            warning.layer != (int)parsedLayer ||
            !TryGetProximityPlatformId(rawJson, out platformId) ||
            warning.platform_instance_id != platformId ||
            !TryGetJsonSignedInteger(rawJson, "proximity_warning", "input_sequence", out inputSequence) ||
            inputSequence <= 0 || warning.input_sequence != inputSequence ||
            !TryGetFiniteJsonNumber(rawJson, "proximity_warning", "input_source_timestamp", out inputTimestamp) ||
            inputTimestamp <= 0d ||
            !TryGetPositiveWarningUpdateSequenceForObject(rawJson, "proximity_warning",
                out warningUpdateSequence) ||
            warning.warning_update_sequence != warningUpdateSequence ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "active", out bool active) ||
            active != warning.active ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "valid", out bool valid) ||
            valid != warning.valid ||
            !TryGetRawJsonBoolean(rawJson, "proximity_warning", "q_valid", out bool qValid) ||
            qValid != warning.q_valid ||
            !TryGetFiniteJsonNumber(rawJson, "proximity_warning", "sample_age_seconds", out sampleAge) ||
            sampleAge < 0d ||
            !TryGetFiniteJsonNumber(rawJson, "proximity_warning", "query_age_seconds", out queryAge) ||
            queryAge < 0d ||
            !TryGetFiniteJsonNumber(rawJson, "proximity_warning", "geometry_age_seconds", out geometryAge) ||
            geometryAge < 0d || geometryAge > ExperimentalProximityWarningMaxAgeSeconds ||
            System.Math.Abs((sampleAge + queryAge) - geometryAge) >
                ExperimentalProximityAgeToleranceSeconds ||
            !TryGetFiniteJsonNumber(rawJson, "proximity_warning", "q", out q) ||
            !TryGetFiniteJsonNumber(rawJson, "proximity_warning", "outward_velocity", out outwardVelocity) ||
            !TryGetFiniteJsonNumber(rawJson, "proximity_warning", "horizon_seconds", out horizonSeconds))
            return false;

        layer = (int)parsedLayer;
        if (layer <= 0 || platformId == 0 || string.IsNullOrWhiteSpace(geometryVersionId))
            return false;

        if (state == "APPROACH" &&
            (!warning.experimental || !warning.enabled || !warning.active || !warning.valid ||
             !warning.q_valid || !active || !valid || !qValid || q <= 0d ||
             !IsFinite(q) || !IsFinite(outwardVelocity) ||
             horizonSeconds != ExperimentalProximityWarningHorizonSeconds)) return false;

        return true;
    }

    private bool IsCurrentOrNewerExperimentalProximityInput(
        long inputSequence, double inputTimestamp)
    {
        if (!experimentalProximityWarningActive) return true;
        if (inputSequence < activeExperimentalProximityInputSequence) return false;
        return inputSequence != activeExperimentalProximityInputSequence ||
               inputTimestamp >= activeExperimentalProximityInputSourceTimestamp;
    }

    private void HandleExperimentalProximityWarning(
        string rawJson, ProximityWarningPacket warning, double receiveMonotonicSeconds)
    {
        if (!enableExperimentalProximityWarning) return;
        if (levelManager == null || !levelManager.IsRunRunning ||
            string.IsNullOrEmpty(levelManager.RunId))
        {
            ClearExperimentalProximityWarning("run_not_running");
            return;
        }
        if (!TryGetWarningRunId(rawJson, "proximity_warning", out string rawRunId) ||
            !string.Equals(rawRunId, levelManager.RunId, System.StringComparison.Ordinal)) return;
        if (!TryGetRawJsonStringWithoutEscapes(rawJson, "proximity_warning", "state",
                out string rawState))
        {
            if (IsCurrentExperimentalProximityContext(rawJson))
            {
                RevokeExperimentalProximityInputSequence(-1);
                ClearExperimentalProximityWarning("proximity_state_missing_or_invalid");
            }
            return;
        }

        if (!IsCurrentExperimentalProximityProtocolEnvelope(rawJson, warning, rawState)) return;

        bool parsedSequence = TryGetPositiveWarningUpdateSequenceForObject(
            rawJson, "proximity_warning", out long parsedUpdateSequence);
        if (!parsedSequence || warning.warning_update_sequence != parsedUpdateSequence)
        {
            if (IsCurrentExperimentalProximityContext(rawJson))
            {
                RevokeExperimentalProximityInputSequence(-1);
                ClearExperimentalProximityWarning("warning_update_sequence_invalid");
            }
            return;
        }
        if (hasExperimentalProximityWarningUpdateSequence &&
            parsedUpdateSequence <= highestExperimentalProximityWarningUpdateSequence) return;
        highestExperimentalProximityWarningUpdateSequence = parsedUpdateSequence;
        hasExperimentalProximityWarningUpdateSequence = true;

        if (rawState != "APPROACH")
        {
            if ((rawState == "CLEAR" || rawState == "UNKNOWN") &&
                IsCurrentExperimentalProximityContext(rawJson))
            {
                if (TryGetProximityInputIdentity(rawJson, out long statusInputSequence, out _))
                    RevokeExperimentalProximityInputSequence(statusInputSequence);
                else
                    RevokeExperimentalProximityInputSequence(-1);
                ClearExperimentalProximityWarning(rawState == "CLEAR" ? "backend_clear" : "backend_unknown");
            }
            return;
        }

        if (!TryValidateExperimentalProximityWarning(rawJson, warning,
                out long warningUpdateSequence, out long inputSequence,
                out double inputTimestamp, out double sampleAge, out double queryAge,
                out double geometryAge, out double q, out double outwardVelocity,
                out double horizonSeconds, out string state, out string runId,
                out int layer, out int platformId, out string geometryVersionId))
        {
            if (IsCurrentExperimentalProximityContext(rawJson))
            {
                RevokeExperimentalProximityInputSequence(
                    TryGetProximityInputIdentity(rawJson, out long invalidInput, out _) ? invalidInput : -1);
                ClearExperimentalProximityWarning("proximity_warning_invalid_or_incomplete");
            }
            return;
        }

        if (!IsCurrentExperimentalProximityContext(rawJson)) return;
        warning.input_source_timestamp = inputTimestamp;
        warning.sample_age_seconds = sampleAge;
        warning.query_age_seconds = queryAge;
        warning.geometry_age_seconds = geometryAge;
        warning.q = q;
        warning.outward_velocity = outwardVelocity;
        warning.horizon_seconds = horizonSeconds;

        if (layer != levelManager.GetCurrentLayer()) return;
        if ((hasExperimentalProximityInputSequence && inputSequence < highestExperimentalProximityInputSequence) ||
            (hasExperimentalProximityInputSourceTimestamp &&
             inputTimestamp < highestExperimentalProximityInputSourceTimestamp)) return;

        bool sameInputSequence = hasExperimentalProximityInputSequence &&
                                 inputSequence == highestExperimentalProximityInputSequence;
        bool sameInputTimestamp = hasExperimentalProximityInputSourceTimestamp &&
                                  inputTimestamp == highestExperimentalProximityInputSourceTimestamp;
        if (sameInputSequence != sameInputTimestamp)
        {
            RevokeExperimentalProximityInputSequence(inputSequence);
            ClearExperimentalProximityWarning("proximity_repeated_sample_identity_inconsistent");
            return;
        }

        bool repeatedSample = sameInputSequence && sameInputTimestamp;
        if (repeatedSample &&
            (queryAge + ExperimentalProximityAgeToleranceSeconds < highestExperimentalProximityQueryAgeSeconds ||
             sampleAge + ExperimentalProximityAgeToleranceSeconds < highestExperimentalProximitySampleAgeSeconds ||
             geometryAge + ExperimentalProximityAgeToleranceSeconds < highestExperimentalProximityAgeSeconds))
        {
            RevokeExperimentalProximityInputSequence(inputSequence);
            ClearExperimentalProximityWarning("proximity_repeated_sample_freshness_regressed");
            return;
        }
        if (inputSequence <= highestRevokedExperimentalProximityInputSequence) return;

        if (!repeatedSample)
        {
            highestExperimentalProximityInputSequence = inputSequence;
            hasExperimentalProximityInputSequence = true;
            highestExperimentalProximityInputSourceTimestamp = inputTimestamp;
            hasExperimentalProximityInputSourceTimestamp = true;
            highestExperimentalProximityQueryAgeSeconds = queryAge;
            highestExperimentalProximitySampleAgeSeconds = sampleAge;
            highestExperimentalProximityAgeSeconds = geometryAge;
        }
        else
        {
            highestExperimentalProximityQueryAgeSeconds = queryAge;
            highestExperimentalProximitySampleAgeSeconds = sampleAge;
            highestExperimentalProximityAgeSeconds = geometryAge;
        }

        double localNow = GetMonotonicSeconds();
        double currentTotalAge = activeExperimentalProximityAgeAtReceiveSeconds +
            (localNow - activeExperimentalProximityReceiveMonotonicSeconds);
        double incomingTotalAge = geometryAge + System.Math.Max(0d, localNow - receiveMonotonicSeconds);
        if (incomingTotalAge > ExperimentalProximityWarningMaxAgeSeconds)
        {
            RevokeExperimentalProximityInputSequence(inputSequence);
            ClearExperimentalProximityWarning("proximity_age_exceeded_0_3s_at_receive");
            return;
        }
        if (experimentalProximityWarningActive &&
            currentTotalAge > ExperimentalProximityWarningMaxAgeSeconds)
        {
            RevokeExperimentalProximityInputSequence(activeExperimentalProximityInputSequence);
            ClearExperimentalProximityWarning("proximity_age_exceeded_0_3s");
            return;
        }
        if (experimentalProximityWarningActive && repeatedSample)
        {
            activeExperimentalProximityAgeAtReceiveSeconds = System.Math.Max(currentTotalAge, incomingTotalAge);
            activeExperimentalProximityReceiveMonotonicSeconds = localNow;
            activeExperimentalProximityQ = q;
            activeExperimentalProximityOutwardVelocity = outwardVelocity;
            activeExperimentalProximityHorizonSeconds = horizonSeconds;
            activeExperimentalProximityReason = warning.reason ?? string.Empty;
            return;
        }

        bool activating = !experimentalProximityWarningActive;
        experimentalProximityWarningActive = true;
        activeExperimentalProximityRunId = runId;
        activeExperimentalProximityReason = warning.reason ?? string.Empty;
        activeExperimentalProximityState = state;
        activeExperimentalProximityLayer = layer;
        activeExperimentalProximityPlatformInstanceId = platformId;
        activeExperimentalProximityVersionId = geometryVersionId;
        activeExperimentalProximityInputSequence = inputSequence;
        activeExperimentalProximityInputSourceTimestamp = inputTimestamp;
        activeExperimentalProximityWarningUpdateSequence = warningUpdateSequence;
        activeExperimentalProximityQ = q;
        activeExperimentalProximityOutwardVelocity = outwardVelocity;
        activeExperimentalProximityHorizonSeconds = horizonSeconds;
        activeExperimentalProximityAgeAtReceiveSeconds = incomingTotalAge;
        activeExperimentalProximityReceiveMonotonicSeconds = localNow;
        if (activating)
        {
            LogExperimentalProximityWarning("ACTIVE", state, warning.reason,
                "proximity_approach_accepted", runId, layer, platformId, geometryVersionId,
                inputSequence, warningUpdateSequence, receiveMonotonicSeconds);
        }
    }

    private void RevokeExperimentalProximityInputSequence(long inputSequence)
    {
        long revokedSequence = inputSequence >= 0
            ? inputSequence
            : (experimentalProximityWarningActive
                ? activeExperimentalProximityInputSequence
                : highestExperimentalProximityInputSequence);
        if (revokedSequence >= 0)
            highestRevokedExperimentalProximityInputSequence =
                System.Math.Max(highestRevokedExperimentalProximityInputSequence, revokedSequence);
    }

    private void ExpireExperimentalProximityWarningIfNeeded()
    {
        if (!enableExperimentalProximityWarning)
        {
            ClearExperimentalProximityWarning("feature_disabled");
            observedExperimentalProximityPlatformInstanceId = 0;
            observedExperimentalProximityVersionId = string.Empty;
            hasObservedExperimentalProximityContext = false;
            return;
        }
        if (!experimentalProximityWarningActive) return;
        double totalAge = activeExperimentalProximityAgeAtReceiveSeconds +
                          (GetMonotonicSeconds() - activeExperimentalProximityReceiveMonotonicSeconds);
        if (totalAge > ExperimentalProximityWarningMaxAgeSeconds)
        {
            RevokeExperimentalProximityInputSequence(activeExperimentalProximityInputSequence);
            ClearExperimentalProximityWarning("proximity_age_exceeded_0_3s");
        }
    }

    private void ClearExperimentalProximityWarning(string revokeReason)
    {
        if (!experimentalProximityWarningActive) return;
        RevokeExperimentalProximityInputSequence(activeExperimentalProximityInputSequence);
        double now = GetMonotonicSeconds();
        LogExperimentalProximityWarning("REVOKED", activeExperimentalProximityState,
            activeExperimentalProximityReason, revokeReason, activeExperimentalProximityRunId,
            activeExperimentalProximityLayer, activeExperimentalProximityPlatformInstanceId,
            activeExperimentalProximityVersionId, activeExperimentalProximityInputSequence,
            activeExperimentalProximityWarningUpdateSequence, now);
        experimentalProximityWarningActive = false;
        activeExperimentalProximityRunId = string.Empty;
        activeExperimentalProximityReason = string.Empty;
        activeExperimentalProximityState = string.Empty;
        activeExperimentalProximityLayer = -1;
        activeExperimentalProximityPlatformInstanceId = 0;
        activeExperimentalProximityVersionId = string.Empty;
        activeExperimentalProximityInputSequence = -1;
        activeExperimentalProximityInputSourceTimestamp = 0d;
        activeExperimentalProximityWarningUpdateSequence = -1;
        activeExperimentalProximityQ = 0d;
        activeExperimentalProximityOutwardVelocity = 0d;
        activeExperimentalProximityHorizonSeconds = 0d;
        activeExperimentalProximityReceiveMonotonicSeconds = 0d;
        activeExperimentalProximityAgeAtReceiveSeconds = 0d;
    }

    private static void LogExperimentalProximityWarning(
        string state, string backendState, string reason, string revokeReason,
        string runId, int layer, int platformId, string versionId,
        long inputSequence, long warningUpdateSequence, double localMonotonicSeconds)
    {
        Debug.Log($"[ExperimentalProximityWarning] state={state} local_monotonic_s={localMonotonicSeconds:F6} " +
                  $"run_id={runId} layer={layer} platform={platformId} version={versionId} " +
                  $"input_sequence={inputSequence} warning_update_sequence={warningUpdateSequence} " +
                  $"backend_state={backendState} reason={reason} revoke_reason={revokeReason}");
    }

    private sealed class GeometryValidationDiagnosticCheck
    {
        public string name;
        public string condition;
        public string[] fields;
    }

    private static void AddGeometryValidationDiagnosticCheck(
        System.Collections.Generic.List<GeometryValidationDiagnosticCheck> failures,
        string name, string condition, params string[] fields)
    {
        failures.Add(new GeometryValidationDiagnosticCheck
        {
            name = name,
            condition = condition,
            fields = fields
        });
    }

    private static System.Collections.Generic.List<GeometryValidationDiagnosticCheck>
        CollectMissingGeometryWarningFieldFailures(string rawJson)
    {
        var failures = new System.Collections.Generic.List<GeometryValidationDiagnosticCheck>();
        string warningJson = TryExtractJsonObject(rawJson, "geometry_warning", out string extracted)
            ? extracted : string.Empty;
        string[] requiredFields =
        {
            "schema_version", "experimental", "enabled", "source", "policy_id", "run_id", "layer",
            "platform_instance_id", "geometry_version_id", "input_sequence", "input_source_timestamp",
            "warning_update_sequence", "clearance", "clearance_valid", "state", "valid", "reason",
            "sample_age_seconds", "query_age_seconds", "geometry_age_seconds"
        };
        for (int i = 0; i < requiredFields.Length; i++)
        {
            if (!ContainsJsonField(warningJson, requiredFields[i]))
                AddGeometryValidationDiagnosticCheck(failures, "required_field_missing",
                    "field is required by the existing geometry-warning protocol", requiredFields[i]);
        }
        if (!TryGetPositiveWarningUpdateSequenceForObject(rawJson, "geometry_warning", out _))
            AddGeometryValidationDiagnosticCheck(failures, "warning_update_sequence.positive_integer",
                "present, unique JSON integer > 0", "warning_update_sequence");
        return failures;
    }

    // This collector intentionally mirrors the existing validator only for diagnosis.
    // Its results never participate in acceptance, revocation, or lease decisions.
    private static System.Collections.Generic.List<GeometryValidationDiagnosticCheck>
        CollectCriticalGeometryWarningFailures(GeometryWarningPacket warning, string rawJson)
    {
        var failures = new System.Collections.Generic.List<GeometryValidationDiagnosticCheck>();
        if (warning.schema_version != 1)
            AddGeometryValidationDiagnosticCheck(failures, "schema_version.equals_1", "== 1", "schema_version");
        if (!warning.experimental)
            AddGeometryValidationDiagnosticCheck(failures, "experimental.true", "== true", "experimental");
        if (!warning.enabled)
            AddGeometryValidationDiagnosticCheck(failures, "enabled.true", "== true", "enabled");
        if (!string.Equals(warning.source, "geometry_rule", System.StringComparison.Ordinal))
            AddGeometryValidationDiagnosticCheck(failures, "source.equals_geometry_rule", "== geometry_rule", "source");
        if (!string.Equals(warning.policy_id, "outer_clearance_nonpositive_v1", System.StringComparison.Ordinal))
            AddGeometryValidationDiagnosticCheck(failures, "policy_id.equals_outer_clearance_nonpositive_v1",
                "== outer_clearance_nonpositive_v1", "policy_id");

        bool layerRawValid = TryGetJsonSignedInteger(rawJson, "geometry_warning", "layer", out long layer);
        if (warning.layer <= 0)
            AddGeometryValidationDiagnosticCheck(failures, "layer.positive_deserialized", "> 0", "layer");
        if (!layerRawValid)
            AddGeometryValidationDiagnosticCheck(failures, "layer.signed_json_integer", "signed JSON integer", "layer");
        else if (layer != warning.layer)
            AddGeometryValidationDiagnosticCheck(failures, "layer.matches_deserialized", "raw integer equals deserialized value", "layer");

        bool platformRawValid = TryGetJsonSignedInteger(rawJson, "geometry_warning", "platform_instance_id", out long platformId);
        if (warning.platform_instance_id == 0)
            AddGeometryValidationDiagnosticCheck(failures, "platform_instance_id.nonzero", "!= 0", "platform_instance_id");
        if (!platformRawValid)
            AddGeometryValidationDiagnosticCheck(failures, "platform_instance_id.signed_json_integer", "signed JSON integer", "platform_instance_id");
        else if (platformId != warning.platform_instance_id)
            AddGeometryValidationDiagnosticCheck(failures, "platform_instance_id.matches_deserialized", "raw integer equals deserialized value", "platform_instance_id");

        if (string.IsNullOrWhiteSpace(warning.geometry_version_id))
            AddGeometryValidationDiagnosticCheck(failures, "geometry_version_id.nonblank", "not null, empty, or whitespace", "geometry_version_id");

        bool inputSequenceRawValid = TryGetJsonSignedInteger(rawJson, "geometry_warning", "input_sequence", out long inputSequence);
        if (warning.input_sequence <= 0)
            AddGeometryValidationDiagnosticCheck(failures, "input_sequence.positive_deserialized", "> 0", "input_sequence");
        if (!inputSequenceRawValid)
            AddGeometryValidationDiagnosticCheck(failures, "input_sequence.signed_json_integer", "signed JSON integer", "input_sequence");
        else if (inputSequence != warning.input_sequence)
            AddGeometryValidationDiagnosticCheck(failures, "input_sequence.matches_deserialized", "raw integer equals deserialized value", "input_sequence");

        if (!IsFinite(warning.input_source_timestamp))
            AddGeometryValidationDiagnosticCheck(failures, "input_source_timestamp.finite_deserialized", "finite deserialized number", "input_source_timestamp");
        bool inputTimestampRawValid = TryGetFiniteJsonNumber(rawJson, "geometry_warning", "input_source_timestamp", out double inputTimestamp);
        if (!inputTimestampRawValid)
            AddGeometryValidationDiagnosticCheck(failures, "input_source_timestamp.finite_json_number", "finite JSON number", "input_source_timestamp");
        else if (inputTimestamp != warning.input_source_timestamp)
            AddGeometryValidationDiagnosticCheck(failures, "input_source_timestamp.matches_deserialized", "raw number equals deserialized value", "input_source_timestamp");

        if (warning.warning_update_sequence <= 0)
            AddGeometryValidationDiagnosticCheck(failures, "warning_update_sequence.positive_deserialized", "> 0", "warning_update_sequence");
        if (!warning.valid)
            AddGeometryValidationDiagnosticCheck(failures, "valid.true", "== true", "valid");
        if (!warning.clearance_valid)
            AddGeometryValidationDiagnosticCheck(failures, "clearance_valid.true", "== true", "clearance_valid");
        if (!IsFinite(warning.clearance))
            AddGeometryValidationDiagnosticCheck(failures, "clearance.finite_deserialized", "finite deserialized number", "clearance");
        bool clearanceRawValid = TryGetFiniteJsonNumber(rawJson, "geometry_warning", "clearance", out double clearance);
        if (!clearanceRawValid)
            AddGeometryValidationDiagnosticCheck(failures, "clearance.finite_json_number", "finite JSON number", "clearance");
        else if ((double)(float)clearance != (double)warning.clearance)
            AddGeometryValidationDiagnosticCheck(failures, "clearance.matches_float_deserialized", "(float)raw number equals deserialized clearance", "clearance");
        if (warning.clearance > 0f)
            AddGeometryValidationDiagnosticCheck(failures, "clearance.nonpositive", "<= 0", "clearance");

        CollectGeometryAgeFailures(failures, rawJson, "sample_age_seconds", false);
        CollectGeometryAgeFailures(failures, rawJson, "query_age_seconds", false);
        CollectGeometryAgeFailures(failures, rawJson, "geometry_age_seconds", true);
        return failures;
    }

    private static void CollectGeometryAgeFailures(
        System.Collections.Generic.List<GeometryValidationDiagnosticCheck> failures,
        string rawJson, string fieldName, bool enforceMaximumAge)
    {
        bool rawValid = TryGetFiniteJsonNumber(rawJson, "geometry_warning", fieldName, out double rawValue);
        if (!rawValid)
        {
            AddGeometryValidationDiagnosticCheck(failures, fieldName + ".finite_json_number",
                "finite JSON number", fieldName);
            return;
        }
        if (rawValue < 0d)
            AddGeometryValidationDiagnosticCheck(failures, fieldName + ".nonnegative_json_number",
                ">= 0", fieldName);
        if (enforceMaximumAge && rawValue > ExperimentalGeometryWarningMaxAgeSeconds)
            AddGeometryValidationDiagnosticCheck(failures, fieldName + ".max_0_3_seconds",
                "<= 0.3 seconds", fieldName);
    }

    private static string GetGeometryDiagnosticFieldEvidence(
        string warningJson, GeometryWarningPacket warning, string fieldName)
    {
        bool present = ContainsJsonField(warningJson, fieldName);
        bool hasUniqueRawValue = TryGetDiagnosticRawGeometryFieldValue(warningJson, fieldName, out string rawValue);
        System.Reflection.FieldInfo field = typeof(GeometryWarningPacket).GetField(fieldName);
        object deserialized = field != null && warning != null ? field.GetValue(warning) : null;
        var builder = new System.Text.StringBuilder();
        builder.Append("{\"present\":").Append(present ? "true" : "false").Append(",\"raw_json\":");
        bool rawTokenIsValidJson = hasUniqueRawValue && IsValidDiagnosticJsonValue(rawValue);
        if (hasUniqueRawValue && rawTokenIsValidJson) builder.Append(rawValue);
        else if (hasUniqueRawValue) AppendJsonString(builder, rawValue);
        else if (present) AppendJsonString(builder, "unavailable_or_ambiguous");
        else builder.Append("null");
        builder.Append(",\"raw_json_is_valid_json_value\":");
        if (hasUniqueRawValue) builder.Append(rawTokenIsValidJson ? "true" : "false");
        else builder.Append("null");
        builder.Append(",\"deserialized\":");
        AppendDiagnosticValue(builder, deserialized);
        builder.Append('}');
        return builder.ToString();
    }

    private static bool IsValidDiagnosticJsonValue(string rawValue)
    {
        int cursor = 0;
        if (!TrySkipJsonValue(rawValue, ref cursor)) return false;
        SkipJsonWhitespace(rawValue, ref cursor);
        return cursor == rawValue.Length;
    }

    private static bool TryGetDiagnosticRawGeometryFieldValue(string warningJson,
        string fieldName, out string rawValue)
    {
        rawValue = string.Empty;
        if (string.IsNullOrEmpty(warningJson)) return false;
        if (TryGetRawJsonFieldValue("{\"geometry_warning\":" + warningJson + "}",
                "geometry_warning", fieldName, out rawValue)) return true;

        int cursor = 0;
        SkipJsonWhitespace(warningJson, ref cursor);
        if (cursor >= warningJson.Length || warningJson[cursor++] != '{') return false;
        int matches = 0;
        while (cursor < warningJson.Length)
        {
            SkipJsonWhitespace(warningJson, ref cursor);
            if (cursor < warningJson.Length && warningJson[cursor] == '}')
            {
                cursor++;
                break;
            }
            if (cursor >= warningJson.Length || warningJson[cursor++] != '\"') return false;
            int keyStart = cursor;
            bool escaped = false;
            while (cursor < warningJson.Length)
            {
                char c = warningJson[cursor++];
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '\"') break;
            }
            if (cursor > warningJson.Length || warningJson[cursor - 1] != '\"') return false;
            string key = warningJson.Substring(keyStart, cursor - keyStart - 1);
            SkipJsonWhitespace(warningJson, ref cursor);
            if (cursor >= warningJson.Length || warningJson[cursor++] != ':') return false;
            SkipJsonWhitespace(warningJson, ref cursor);
            int valueStart = cursor;
            if (cursor < warningJson.Length && warningJson[cursor] == '\"')
            {
                cursor++;
                escaped = false;
                bool closed = false;
                while (cursor < warningJson.Length)
                {
                    char c = warningJson[cursor++];
                    if (escaped) escaped = false;
                    else if (c == '\\') escaped = true;
                    else if (c == '\"') { closed = true; break; }
                }
                if (!closed) return false;
            }
            else if (cursor < warningJson.Length &&
                     (warningJson[cursor] == '{' || warningJson[cursor] == '['))
            {
                if (!TrySkipJsonValue(warningJson, ref cursor)) return false;
            }
            else
            {
                while (cursor < warningJson.Length && warningJson[cursor] != ',' && warningJson[cursor] != '}')
                    cursor++;
                while (cursor > valueStart && char.IsWhiteSpace(warningJson[cursor - 1])) cursor--;
                if (cursor == valueStart) return false;
            }

            if (string.Equals(key, fieldName, System.StringComparison.Ordinal))
            {
                matches++;
                rawValue = warningJson.Substring(valueStart, cursor - valueStart).Trim();
            }
            SkipJsonWhitespace(warningJson, ref cursor);
            if (cursor >= warningJson.Length) return false;
            if (warningJson[cursor] == ',') { cursor++; continue; }
            if (warningJson[cursor] == '}') { cursor++; break; }
            return false;
        }
        SkipJsonWhitespace(warningJson, ref cursor);
        return cursor == warningJson.Length && matches == 1;
    }

    private void LogGeometryWarningValidationFailure(string rawJson, GeometryWarningPacket warning,
        double receiveMonotonicSeconds, System.Collections.Generic.List<GeometryValidationDiagnosticCheck> failures)
    {
        try
        {
            string warningJson = TryExtractJsonObject(rawJson, "geometry_warning", out string extracted)
                ? extracted : string.Empty;
            if (failures == null || failures.Count == 0)
                AddGeometryValidationDiagnosticCheck(failures ?? (failures = new System.Collections.Generic.List<GeometryValidationDiagnosticCheck>()),
                    "critical_validation_failed_unclassified", "existing CRITICAL validation returned false");

            string signature = BuildGeometryValidationDiagnosticSignature(warning, failures);
            string context = BuildGeometryValidationDiagnosticContext(warning);
            if (string.Equals(signature, lastGeometryValidationDiagnosticSignature, System.StringComparison.Ordinal))
            {
                geometryValidationDiagnosticSuppressedCount++;
                if (geometryValidationDiagnosticSuppressedCount % 100 == 0)
                    EmitGeometryValidationSuppressionSummary();
                return;
            }

            FlushGeometryValidationSuppressionSummary();
            lastGeometryValidationDiagnosticSignature = signature;
            lastGeometryValidationDiagnosticContext = context;
            geometryValidationDiagnosticSuppressedCount = 0;
            geometryValidationDiagnosticReportedSuppressedCount = 0;
            Debug.LogWarning(BuildGeometryValidationDiagnosticJson(
                warningJson, warning, receiveMonotonicSeconds, failures));
        }
        catch (System.Exception exception)
        {
            // Diagnostics are best-effort and must never change the existing validation decision.
            Debug.LogWarning("[ExperimentalGeometryWarningValidation] diagnostic_error=" + exception.GetType().Name);
        }
    }

    private static string BuildGeometryValidationDiagnosticSignature(
        GeometryWarningPacket warning, System.Collections.Generic.List<GeometryValidationDiagnosticCheck> failures)
    {
        var builder = new System.Text.StringBuilder();
        builder.Append(warning != null ? warning.run_id : string.Empty).Append('|')
            .Append(warning != null ? warning.layer : 0).Append('|')
            .Append(warning != null ? warning.platform_instance_id : 0).Append('|')
            .Append(warning != null ? warning.geometry_version_id : string.Empty);
        for (int i = 0; i < failures.Count; i++)
        {
            builder.Append('|').Append(failures[i].name).Append(':').Append(failures[i].condition);
            if (failures[i].fields == null) continue;
            for (int j = 0; j < failures[i].fields.Length; j++) builder.Append(':').Append(failures[i].fields[j]);
        }
        return builder.ToString();
    }

    private static string BuildGeometryValidationDiagnosticContext(GeometryWarningPacket warning)
    {
        if (warning == null) return "run_id=<unavailable> layer=<unavailable> platform_instance_id=<unavailable>";
        return "run_id=" + (warning.run_id ?? string.Empty) + " layer=" + warning.layer +
               " platform_instance_id=" + warning.platform_instance_id +
               " geometry_version_id=" + (warning.geometry_version_id ?? string.Empty);
    }

    private static string BuildGeometryValidationDiagnosticJson(string warningJson,
        GeometryWarningPacket warning, double receiveMonotonicSeconds,
        System.Collections.Generic.List<GeometryValidationDiagnosticCheck> failures)
    {
        var builder = new System.Text.StringBuilder();
        builder.Append("[ExperimentalGeometryWarningValidation] rejected {\"local_receive_monotonic_seconds\":")
            .Append(receiveMonotonicSeconds.ToString("R", System.Globalization.CultureInfo.InvariantCulture))
            .Append(",\"run_id\":").Append(GetGeometryDiagnosticFieldEvidence(warningJson, warning, "run_id"))
            .Append(",\"layer\":").Append(GetGeometryDiagnosticFieldEvidence(warningJson, warning, "layer"))
            .Append(",\"platform_instance_id\":").Append(GetGeometryDiagnosticFieldEvidence(warningJson, warning, "platform_instance_id"))
            .Append(",\"geometry_version_id\":").Append(GetGeometryDiagnosticFieldEvidence(warningJson, warning, "geometry_version_id"))
            .Append(",\"input_sequence\":").Append(GetGeometryDiagnosticFieldEvidence(warningJson, warning, "input_sequence"))
            .Append(",\"warning_update_sequence\":").Append(GetGeometryDiagnosticFieldEvidence(warningJson, warning, "warning_update_sequence"))
            .Append(",\"failed_checks\":[");
        for (int i = 0; i < failures.Count; i++)
        {
            if (i > 0) builder.Append(',');
            builder.Append("{\"name\":");
            AppendJsonString(builder, failures[i].name);
            builder.Append(",\"condition\":");
            AppendJsonString(builder, failures[i].condition);
            builder.Append(",\"fields\":[");
            for (int j = 0; failures[i].fields != null && j < failures[i].fields.Length; j++)
            {
                if (j > 0) builder.Append(',');
                AppendJsonString(builder, failures[i].fields[j]);
            }
            builder.Append("],\"field_evidence\":[");
            for (int j = 0; failures[i].fields != null && j < failures[i].fields.Length; j++)
            {
                if (j > 0) builder.Append(',');
                builder.Append("{\"field\":");
                AppendJsonString(builder, failures[i].fields[j]);
                builder.Append(",\"evidence\":").Append(GetGeometryDiagnosticFieldEvidence(
                    warningJson, warning, failures[i].fields[j])).Append('}');
            }
            builder.Append("]}");
        }
        builder.Append("],\"geometry_warning_raw\":");
        if (!string.IsNullOrEmpty(warningJson)) AppendJsonString(builder, warningJson);
        else builder.Append("null");
        builder.Append('}');
        return builder.ToString();
    }

    private void EmitGeometryValidationSuppressionSummary()
    {
        int newlySuppressed = geometryValidationDiagnosticSuppressedCount -
                              geometryValidationDiagnosticReportedSuppressedCount;
        if (newlySuppressed <= 0) return;
        Debug.LogWarning("[ExperimentalGeometryWarningValidation] repeated_failure_suppressed " +
                         lastGeometryValidationDiagnosticContext +
                         " failure_signature=" + lastGeometryValidationDiagnosticSignature +
                         " suppressed_repeated_count=" + geometryValidationDiagnosticSuppressedCount +
                         " newly_suppressed_count=" + newlySuppressed);
        geometryValidationDiagnosticReportedSuppressedCount = geometryValidationDiagnosticSuppressedCount;
    }

    private void FlushGeometryValidationSuppressionSummary()
    {
        EmitGeometryValidationSuppressionSummary();
        lastGeometryValidationDiagnosticSignature = string.Empty;
        lastGeometryValidationDiagnosticContext = string.Empty;
        geometryValidationDiagnosticSuppressedCount = 0;
        geometryValidationDiagnosticReportedSuppressedCount = 0;
    }

    private static void AppendDiagnosticValue(System.Text.StringBuilder builder, object value)
    {
        if (value == null) { builder.Append("null"); return; }
        if (value is string text) { AppendJsonString(builder, text); return; }
        if (value is bool boolean) { builder.Append(boolean ? "true" : "false"); return; }
        if (value is float floatValue)
        {
            if (IsFinite(floatValue)) builder.Append(floatValue.ToString("R", System.Globalization.CultureInfo.InvariantCulture));
            else AppendJsonString(builder, floatValue.ToString(System.Globalization.CultureInfo.InvariantCulture));
            return;
        }
        if (value is double doubleValue)
        {
            if (IsFinite(doubleValue)) builder.Append(doubleValue.ToString("R", System.Globalization.CultureInfo.InvariantCulture));
            else AppendJsonString(builder, doubleValue.ToString(System.Globalization.CultureInfo.InvariantCulture));
            return;
        }
        builder.Append(System.Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture));
    }

    private static void AppendJsonString(System.Text.StringBuilder builder, string value)
    {
        builder.Append('"');
        if (value != null)
        {
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                switch (c)
                {
                    case '"': builder.Append("\\\""); break;
                    case '\\': builder.Append("\\\\"); break;
                    case '\b': builder.Append("\\b"); break;
                    case '\f': builder.Append("\\f"); break;
                    case '\n': builder.Append("\\n"); break;
                    case '\r': builder.Append("\\r"); break;
                    case '\t': builder.Append("\\t"); break;
                    default:
                        if (c < 0x20) builder.Append("\\u").Append(((int)c).ToString("x4"));
                        else builder.Append(c);
                        break;
                }
            }
        }
        builder.Append('"');
    }

    private static bool IsValidCriticalGeometryWarning(GeometryWarningPacket warning, string rawJson)
    {
        return TryValidateCriticalGeometryWarning(warning, rawJson,
            out _, out _, out _);
    }

    private static bool TryValidateCriticalGeometryWarning(GeometryWarningPacket warning, string rawJson,
        out double sampleAge, out double queryAge, out double geometryAge)
    {
        sampleAge = 0d;
        queryAge = 0d;
        geometryAge = 0d;
        bool rawAgesValid =
            TryGetFiniteJsonNumber(rawJson, "geometry_warning", "sample_age_seconds", out sampleAge) &&
            sampleAge >= 0d &&
            TryGetFiniteJsonNumber(rawJson, "geometry_warning", "query_age_seconds", out queryAge) &&
            queryAge >= 0d &&
            TryGetFiniteJsonNumber(rawJson, "geometry_warning", "geometry_age_seconds", out geometryAge) &&
            geometryAge >= 0d && geometryAge <= ExperimentalGeometryWarningMaxAgeSeconds;

        return warning.schema_version == 1 && warning.experimental && warning.enabled &&
               string.Equals(warning.source, "geometry_rule", System.StringComparison.Ordinal) &&
               string.Equals(warning.policy_id, "outer_clearance_nonpositive_v1", System.StringComparison.Ordinal) &&
               warning.layer > 0 && TryGetJsonSignedInteger(rawJson, "geometry_warning", "layer", out long layer) && layer == warning.layer &&
               warning.platform_instance_id != 0 && TryGetJsonSignedInteger(rawJson, "geometry_warning", "platform_instance_id", out long platformId) && platformId == warning.platform_instance_id &&
               !string.IsNullOrWhiteSpace(warning.geometry_version_id) &&
               warning.input_sequence > 0 && TryGetJsonSignedInteger(rawJson, "geometry_warning", "input_sequence", out long inputSequence) && inputSequence == warning.input_sequence &&
               IsFinite(warning.input_source_timestamp) &&
               TryGetFiniteJsonNumber(rawJson, "geometry_warning", "input_source_timestamp", out double inputTimestamp) && inputTimestamp == warning.input_source_timestamp &&
               warning.warning_update_sequence > 0 &&
               warning.valid && warning.clearance_valid && IsFinite(warning.clearance) &&
               TryGetFiniteJsonNumber(rawJson, "geometry_warning", "clearance", out double clearance) &&
               (double)(float)clearance == (double)warning.clearance &&
               warning.clearance <= 0f &&
               rawAgesValid;
    }

    private static bool TryGetJsonSignedInteger(
        string rawJson, string objectName, string fieldName, out long value)
    {
        value = 0;
        if (!TryGetRawJsonFieldValue(rawJson, objectName, fieldName, out string rawValue) ||
            rawValue.Length == 0) return false;

        int digitStart = rawValue[0] == '-' ? 1 : 0;
        if (digitStart == rawValue.Length ||
            (rawValue.Length - digitStart > 1 && rawValue[digitStart] == '0')) return false;
        for (int i = digitStart; i < rawValue.Length; i++)
        {
            if (rawValue[i] < '0' || rawValue[i] > '9') return false;
        }
        return long.TryParse(rawValue, System.Globalization.NumberStyles.AllowLeadingSign,
            System.Globalization.CultureInfo.InvariantCulture, out value);
    }

    private static bool TryGetFiniteJsonNumber(
        string rawJson, string objectName, string fieldName, out double value)
    {
        value = 0d;
        if (!TryGetRawJsonFieldValue(rawJson, objectName, fieldName, out string rawValue) ||
            !IsJsonNumber(rawValue) ||
            !double.TryParse(rawValue, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out value)) return false;
        return IsFinite(value);
    }

    private static bool TryGetRawJsonFieldValue(
        string rawJson, string objectName, string fieldName, out string rawValue)
    {
        using (RawFieldMarker.Auto())
        {
        rawValue = string.Empty;
        if (!TryExtractJsonObject(rawJson, objectName, out string objectJson)) return false;
        int cursor = 0;
        SkipJsonWhitespace(objectJson, ref cursor);
        if (cursor >= objectJson.Length || objectJson[cursor++] != '{') return false;
        int matches = 0;
        while (cursor < objectJson.Length)
        {
            SkipJsonWhitespace(objectJson, ref cursor);
            if (cursor < objectJson.Length && objectJson[cursor] == '}')
            {
                cursor++;
                break;
            }
            if (cursor >= objectJson.Length || objectJson[cursor++] != '"') return false;
            int keyStart = cursor;
            bool escaped = false;
            while (cursor < objectJson.Length)
            {
                char c = objectJson[cursor++];
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"') break;
            }
            if (cursor > objectJson.Length || objectJson[cursor - 1] != '"') return false;
            int keyLength = cursor - keyStart - 1;
            SkipJsonWhitespace(objectJson, ref cursor);
            if (cursor >= objectJson.Length || objectJson[cursor++] != ':') return false;
            SkipJsonWhitespace(objectJson, ref cursor);
            int valueStart = cursor;
            if (!TrySkipJsonValue(objectJson, ref cursor)) return false;
            if (fieldName != null && keyLength == fieldName.Length &&
                string.CompareOrdinal(objectJson, keyStart, fieldName, 0, keyLength) == 0)
            {
                matches++;
                rawValue = objectJson.Substring(valueStart, cursor - valueStart).Trim();
            }
            SkipJsonWhitespace(objectJson, ref cursor);
            if (cursor >= objectJson.Length) return false;
            if (objectJson[cursor] == ',') { cursor++; continue; }
            if (objectJson[cursor] == '}') { cursor++; break; }
            return false;
        }
        SkipJsonWhitespace(objectJson, ref cursor);
        return cursor == objectJson.Length && matches == 1;
        }
    }

    private static bool HasRequiredGeometryWarningFields(string rawJson)
    {
        if (!TryExtractJsonObject(rawJson, "geometry_warning", out string warningJson) ||
            !TryGetPositiveWarningUpdateSequenceForObject(rawJson, "geometry_warning", out _)) return false;
        string[] requiredFields =
        {
            "schema_version", "experimental", "enabled", "source", "policy_id", "run_id", "layer",
            "platform_instance_id", "geometry_version_id", "input_sequence", "input_source_timestamp",
            "warning_update_sequence", "clearance", "clearance_valid", "state", "valid", "reason",
            "sample_age_seconds", "query_age_seconds", "geometry_age_seconds"
        };
        for (int i = 0; i < requiredFields.Length; i++)
        {
            if (!ContainsJsonField(warningJson, requiredFields[i])) return false;
        }
        return true;
    }

    private void RevokeExperimentalGeometryInputSequence(long inputSequence)
    {
        long revokedSequence = inputSequence >= 0
            ? inputSequence
            : (experimentalGeometryWarningActive ? activeExperimentalGeometryInputSequence : highestExperimentalGeometryInputSequence);
        if (revokedSequence >= 0)
        {
            highestRevokedExperimentalGeometryInputSequence = System.Math.Max(
                highestRevokedExperimentalGeometryInputSequence, revokedSequence);
        }
    }

    private void ExpireExperimentalGeometryWarningIfNeeded()
    {
        if (!experimentalGeometryWarningActive) return;
        double totalAge = activeExperimentalGeometryAgeAtReceiveSeconds +
                          (GetMonotonicSeconds() - activeExperimentalGeometryReceiveMonotonicSeconds);
        if (!enableExperimentalGeometryWarning)
        {
            ClearExperimentalGeometryWarning("feature_disabled");
        }
        else if (totalAge > ExperimentalGeometryWarningMaxAgeSeconds)
        {
            RevokeExperimentalGeometryInputSequence(activeExperimentalGeometryInputSequence);
            ClearExperimentalGeometryWarning("geometry_age_exceeded_0_3s");
        }
    }

    private void ClearExperimentalGeometryWarning(string reason)
    {
        if (!experimentalGeometryWarningActive) return;
        Debug.Log($"[ExperimentalGeometryWarning] revoked run={activeExperimentalGeometryRunId} " +
                  $"layer={activeExperimentalGeometryLayer} platform={activeExperimentalGeometryPlatformInstanceId} " +
                  $"input_sequence={activeExperimentalGeometryInputSequence} reason={reason ?? "unspecified"}");
        experimentalGeometryWarningActive = false;
        activeExperimentalGeometryRunId = string.Empty;
        activeExperimentalGeometryReason = string.Empty;
        activeExperimentalGeometryClearance = 0f;
        activeExperimentalGeometryPlatformInstanceId = 0;
        activeExperimentalGeometryLayer = -1;
        activeExperimentalGeometryVersionId = string.Empty;
        activeExperimentalGeometryInputSequence = -1;
        activeExperimentalGeometryReceiveMonotonicSeconds = 0d;
        activeExperimentalGeometryAgeAtReceiveSeconds = 0d;
    }

    private static bool TryGetGeometryWarningRunId(string rawJson, out string runId)
    {
        return TryGetWarningRunId(rawJson, "geometry_warning", out runId);
    }

    private static bool TryGetModelWarningRunId(string rawJson, out string runId)
    {
        return TryGetWarningRunId(rawJson, "model_warning", out runId);
    }

    private static bool TryGetWarningRunId(string rawJson, string warningName, out string runId)
    {
        runId = string.Empty;
        if (!TryGetRawJsonFieldValue(rawJson, warningName, "run_id", out string rawRunId) ||
            rawRunId.Length < 2 || rawRunId[0] != '"' || rawRunId[rawRunId.Length - 1] != '"') return false;
        int idLength = rawRunId.Length - 2;
        if (idLength <= 0 || rawRunId.IndexOf('\\', 1, idLength) >= 0) return false;
        runId = rawRunId.Substring(1, idLength);
        return true;
    }

    private void HandleExperimentalModelWarning(
        string rawJson, ModelWarningPacket warning, double receiveMonotonicSeconds)
    {
        if (!enableExperimentalModelWarning)
        {
            ClearExperimentalModelWarning("feature_disabled");
            return;
        }
        if (levelManager == null || !levelManager.IsRunRunning || string.IsNullOrEmpty(levelManager.RunId))
        {
            ClearExperimentalModelWarning("run_not_running");
            return;
        }

        if (warning == null)
        {
            // An absent warning object cannot carry run ownership, so ignore it and
            // rely on the independent expiration. A malformed object is checked by
            // its raw run_id before it can revoke the active prompt.
            if (TryGetModelWarningRunId(rawJson, out string malformedRunId))
            {
                if (!string.Equals(malformedRunId, levelManager.RunId, System.StringComparison.Ordinal))
                    return;
                RevokeExperimentalPredictionSequence(-1);
                ClearExperimentalModelWarning("model_warning_malformed_or_missing");
            }
            return;
        }

        // Establish ownership before any malformed status can affect this run.
        if (!string.Equals(warning.run_id, levelManager.RunId, System.StringComparison.Ordinal))
        {
            return;
        }
        RecordExperimentalWarningObservation(warning.state, warning.model_id,
            warning.prediction_sequence, warning.reason, warning.run_id, receiveMonotonicSeconds);

        // This field is the sole ordering authority for warning replies. Require a
        // syntactically valid positive JSON integer as well as the deserialized long.
        if (!TryGetPositiveWarningUpdateSequence(rawJson, out long parsedUpdateSequence) ||
            warning.warning_update_sequence != parsedUpdateSequence)
        {
            RevokeExperimentalPredictionSequence(warning.prediction_sequence);
            ClearExperimentalModelWarning("warning_update_sequence_missing_or_invalid");
            return;
        }
        if (hasExperimentalWarningUpdateSequence &&
            parsedUpdateSequence <= highestExperimentalWarningUpdateSequence)
        {
            return;
        }
        highestExperimentalWarningUpdateSequence = parsedUpdateSequence;
        hasExperimentalWarningUpdateSequence = true;

        // Layer zero explicitly represents an unknown-layer fault reply. It is
        // ordered for this run and must revoke, never activate, a warning.
        if (warning.layer <= 0)
        {
            RevokeExperimentalPredictionSequence(warning.prediction_sequence);
            ClearExperimentalModelWarning("warning_layer_unknown_or_invalid");
            return;
        }
        // Ordered packets from a previous layer are inert, but still advance the
        // run-wide reply watermark above so older UDP datagrams cannot be replayed.
        if (warning.layer != levelManager.GetCurrentLayer())
        {
            return;
        }

        bool isStrongState = string.Equals(warning.state, "STRONG", System.StringComparison.Ordinal);
        bool hasCompleteWarning = HasRequiredModelWarningFields(rawJson);
        bool validStrongPrediction = isStrongState && hasCompleteWarning &&
            warning.experimental && warning.enabled && warning.valid && warning.probability_valid &&
            IsFinite(warning.strong_probability) && warning.strong_probability >= 0f && warning.strong_probability <= 1f &&
            IsFinite(warning.feature_age_seconds) && warning.feature_age_seconds >= 0f &&
            warning.input_sequence >= 0 && IsFinite(warning.input_source_timestamp) &&
            !string.IsNullOrWhiteSpace(warning.model_id) && warning.prediction_sequence >= 0 &&
            warning.feature_age_seconds <= ExperimentalModelWarningMaxAgeSeconds;

        if (!validStrongPrediction)
        {
            // A newer current-run UNKNOWN/SAFE/invalid reply revokes immediately;
            // its source identity may intentionally be the last known sample.
            RevokeExperimentalPredictionSequence(warning.prediction_sequence);
            ClearExperimentalModelWarning(
                string.Equals(warning.state, "SAFE", System.StringComparison.Ordinal) ? "backend_safe" :
                string.Equals(warning.state, "UNKNOWN", System.StringComparison.Ordinal) ? "backend_unknown" :
                !hasCompleteWarning ? "model_warning_fields_missing" :
                warning.feature_age_seconds > ExperimentalModelWarningMaxAgeSeconds ? "prediction_already_expired" :
                "invalid_or_incomplete_strong_prediction");
            return;
        }

        // Retain the previous layer/input safeguards for STRONG activation only.
        // Status revocations above are ordered by warning_update_sequence and must
        // not be discarded because they reuse or carry older input identities.
        if ((hasLayerInputSequenceFloor && warning.input_sequence <= layerInputSequenceFloor) ||
            warning.prediction_sequence <= layerPredictionSequenceFloor ||
            (hasExperimentalInputSequence && warning.input_sequence < highestExperimentalInputSequence) ||
            (hasExperimentalInputSourceTimestamp &&
             warning.input_source_timestamp < highestExperimentalInputSourceTimestamp) ||
            (hasExperimentalPredictionSequence &&
             warning.prediction_sequence < highestExperimentalPredictionSequence))
        {
            return;
        }

        long previouslyHighestPredictionSequence = highestExperimentalPredictionSequence;
        if (!hasExperimentalInputSequence || warning.input_sequence > highestExperimentalInputSequence)
        {
            highestExperimentalInputSequence = warning.input_sequence;
            hasExperimentalInputSequence = true;
        }
        if (!hasExperimentalInputSourceTimestamp ||
            warning.input_source_timestamp > highestExperimentalInputSourceTimestamp)
        {
            highestExperimentalInputSourceTimestamp = warning.input_source_timestamp;
            hasExperimentalInputSourceTimestamp = true;
        }
        if (!hasExperimentalPredictionSequence ||
            warning.prediction_sequence > highestExperimentalPredictionSequence)
        {
            highestExperimentalPredictionSequence = warning.prediction_sequence;
            hasExperimentalPredictionSequence = true;
        }

        // A newer reply carrying the same inference is neither a lease renewal nor
        // permission to revive an inference already revoked or expired.
        if (warning.prediction_sequence <= highestRevokedExperimentalPredictionSequence ||
            (previouslyHighestPredictionSequence >= 0 &&
             warning.prediction_sequence <= previouslyHighestPredictionSequence))
        {
            return;
        }

        experimentalModelWarningActive = true;
        activeExperimentalModelId = warning.model_id;
        activeExperimentalRunId = warning.run_id;
        activeExperimentalReason = warning.reason ?? string.Empty;
        activeExperimentalStrongProbability = warning.strong_probability;
        activeExperimentalPredictionSequence = warning.prediction_sequence;
        activeExperimentalReceiveMonotonicSeconds = receiveMonotonicSeconds;
        activeExperimentalFeatureAgeSeconds = warning.feature_age_seconds;
        LogExperimentalModelWarning("ACTIVE", "strong_prediction_accepted", warning.reason,
            warning.run_id, warning.prediction_sequence, receiveMonotonicSeconds);
    }

    private void RevokeExperimentalPredictionSequence(long predictionSequence)
    {
        long revokedSequence = predictionSequence >= 0
            ? predictionSequence
            : (experimentalModelWarningActive
                ? activeExperimentalPredictionSequence
                : highestExperimentalPredictionSequence);
        if (revokedSequence >= 0)
        {
            highestRevokedExperimentalPredictionSequence = System.Math.Max(
                highestRevokedExperimentalPredictionSequence, revokedSequence);
        }
    }

    private static bool TryGetPositiveWarningUpdateSequence(string rawJson, out long sequence)
    {
        return TryGetPositiveWarningUpdateSequenceForObject(rawJson, "model_warning", out sequence);
    }

    private static bool TryGetPositiveWarningUpdateSequenceForObject(
        string rawJson, string objectName, out long sequence)
    {
        using (SequenceMarker.Auto())
        {
        sequence = 0;
        if (!TryExtractJsonObject(rawJson, objectName, out string warningJson)) return false;

        int cursor = 0;
        SkipJsonWhitespace(warningJson, ref cursor);
        if (cursor >= warningJson.Length || warningJson[cursor++] != '{') return false;

        int matchCount = 0;
        string rawSequence = null;
        while (cursor < warningJson.Length)
        {
            SkipJsonWhitespace(warningJson, ref cursor);
            if (cursor < warningJson.Length && warningJson[cursor] == '}')
            {
                cursor++;
                break;
            }

            if (cursor >= warningJson.Length || warningJson[cursor] != '"') return false;
            int keyStart = cursor++;
            bool escaped = false;
            bool keyClosed = false;
            while (cursor < warningJson.Length)
            {
                char c = warningJson[cursor++];
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"')
                {
                    keyClosed = true;
                    break;
                }
            }
            if (!keyClosed) return false;
            int keyLength = cursor - keyStart;

            SkipJsonWhitespace(warningJson, ref cursor);
            if (cursor >= warningJson.Length || warningJson[cursor++] != ':') return false;
            SkipJsonWhitespace(warningJson, ref cursor);
            int valueStart = cursor;
            if (!TrySkipJsonValue(warningJson, ref cursor)) return false;

            const string sequenceKeyToken = "\"warning_update_sequence\"";
            if (keyLength == sequenceKeyToken.Length &&
                string.CompareOrdinal(warningJson, keyStart, sequenceKeyToken, 0, keyLength) == 0)
            {
                matchCount++;
                rawSequence = warningJson.Substring(valueStart, cursor - valueStart).Trim();
            }

            SkipJsonWhitespace(warningJson, ref cursor);
            if (cursor >= warningJson.Length) return false;
            if (warningJson[cursor] == ',')
            {
                cursor++;
                continue;
            }
            if (warningJson[cursor] == '}')
            {
                cursor++;
                break;
            }
            return false;
        }

        SkipJsonWhitespace(warningJson, ref cursor);
        if (cursor != warningJson.Length || matchCount != 1 || string.IsNullOrEmpty(rawSequence)) return false;
        if (rawSequence.Length > 1 && rawSequence[0] == '0') return false;
        for (int i = 0; i < rawSequence.Length; i++)
        {
            if (rawSequence[i] < '0' || rawSequence[i] > '9') return false;
        }

        return long.TryParse(rawSequence, System.Globalization.NumberStyles.None,
                   System.Globalization.CultureInfo.InvariantCulture, out sequence) && sequence > 0;
        }
    }

    private static bool TrySkipJsonValue(string json, ref int cursor)
    {
        using (SkipValueMarker.Auto())
        {
        if (cursor >= json.Length) return false;
        char first = json[cursor];
        if (first == '"')
        {
            cursor++;
            bool escaped = false;
            while (cursor < json.Length)
            {
                char c = json[cursor++];
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"') return true;
            }
            return false;
        }

        if (first == '{' || first == '[')
        {
            var closing = new System.Collections.Generic.Stack<char>();
            closing.Push(first == '{' ? '}' : ']');
            cursor++;
            bool inString = false;
            bool escaped = false;
            while (cursor < json.Length && closing.Count > 0)
            {
                char c = json[cursor++];
                if (inString)
                {
                    if (escaped) escaped = false;
                    else if (c == '\\') escaped = true;
                    else if (c == '"') inString = false;
                    continue;
                }

                if (c == '"') inString = true;
                else if (c == '{') closing.Push('}');
                else if (c == '[') closing.Push(']');
                else if (c == '}' || c == ']')
                {
                    if (closing.Count == 0 || closing.Pop() != c) return false;
                }
            }
            return closing.Count == 0 && !inString;
        }

        int primitiveStart = cursor;
        while (cursor < json.Length && json[cursor] != ',' && json[cursor] != '}' && json[cursor] != ']')
            cursor++;
        int primitiveEnd = cursor;
        TrimJsonWhitespaceRange(json, ref primitiveStart, ref primitiveEnd);
        int primitiveLength = primitiveEnd - primitiveStart;
        if (primitiveLength == 0) return false;
        return IsJsonLiteral(json, primitiveStart, primitiveLength, "true") ||
               IsJsonLiteral(json, primitiveStart, primitiveLength, "false") ||
               IsJsonLiteral(json, primitiveStart, primitiveLength, "null") ||
               IsJsonNumber(json, primitiveStart, primitiveLength);
        }
    }

    private static bool IsJsonNumber(string value)
    {
        return IsJsonNumber(value, 0, value.Length);
    }

    private static bool IsJsonNumber(string value, int start, int length)
    {
        int index = start;
        int end = start + length;
        if (index < end && value[index] == '-') index++;
        if (index >= end) return false;
        if (value[index] == '0') index++;
        else
        {
            if (value[index] < '1' || value[index] > '9') return false;
            while (index < end && value[index] >= '0' && value[index] <= '9') index++;
        }
        if (index < end && value[index] == '.')
        {
            index++;
            int fractionStart = index;
            while (index < end && value[index] >= '0' && value[index] <= '9') index++;
            if (index == fractionStart) return false;
        }
        if (index < end && (value[index] == 'e' || value[index] == 'E'))
        {
            index++;
            if (index < end && (value[index] == '+' || value[index] == '-')) index++;
            int exponentStart = index;
            while (index < end && value[index] >= '0' && value[index] <= '9') index++;
            if (index == exponentStart) return false;
        }
        return index == end;
    }

    private static bool IsJsonLiteral(string json, int start, int length, string literal)
    {
        return length == literal.Length && string.CompareOrdinal(json, start, literal, 0, length) == 0;
    }

    private static void TrimJsonWhitespaceRange(string json, ref int start, ref int end)
    {
        while (start < end && char.IsWhiteSpace(json[start])) start++;
        while (end > start && char.IsWhiteSpace(json[end - 1])) end--;
    }

    private static void SkipJsonWhitespace(string json, ref int cursor)
    {
        while (cursor < json.Length && char.IsWhiteSpace(json[cursor])) cursor++;
    }

    private static bool HasRequiredModelWarningFields(string rawJson)
    {
        if (!TryExtractJsonObject(rawJson, "model_warning", out string warningJson)) return false;
        if (!TryGetPositiveWarningUpdateSequence(rawJson, out _)) return false;
        string[] requiredFields =
        {
            "schema_version", "experimental", "enabled", "model_id", "run_id", "layer", "state", "valid",
            "probability_valid", "strong_probability", "prediction_sequence", "warning_update_sequence",
            "input_sequence", "input_source_timestamp", "feature_age_seconds", "reason"
        };
        for (int i = 0; i < requiredFields.Length; i++)
        {
            if (!ContainsJsonField(warningJson, requiredFields[i])) return false;
        }
        return true;
    }

    private static bool TryExtractJsonObject(string json, string fieldName, out string objectJson)
    {
        using (ExtractObjectMarker.Auto())
        {
        objectJson = string.Empty;
        WarningJsonExtractionScope scope = currentWarningJsonExtractionScope;
        objectJson = string.Empty;
        bool handled = false;
        bool succeeded = scope != null && scope.TryGet(json, fieldName, out handled, out objectJson);
        if (handled) return succeeded;
        return TryExtractJsonObjectUncached(json, fieldName, out objectJson);
        }
    }

    private static bool TryExtractJsonObjectUncached(string json, string fieldName, out string objectJson)
    {
        objectJson = string.Empty;
        if (string.IsNullOrEmpty(json)) return false;
        string key = "\"" + fieldName + "\"";
        int keyIndex = json.IndexOf(key, System.StringComparison.Ordinal);
        if (keyIndex < 0) return false;
        int colonIndex = json.IndexOf(':', keyIndex + key.Length);
        if (colonIndex < 0) return false;
        int start = colonIndex + 1;
        while (start < json.Length && char.IsWhiteSpace(json[start])) start++;
        if (start >= json.Length || json[start] != '{') return false;

        bool inString = false;
        bool escaped = false;
        int depth = 0;
        for (int i = start; i < json.Length; i++)
        {
            char c = json[i];
            if (inString)
            {
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"') inString = false;
                continue;
            }
            if (c == '"') inString = true;
            else if (c == '{') depth++;
            else if (c == '}' && --depth == 0)
            {
                objectJson = json.Substring(start, i - start + 1);
                return true;
            }
        }
        return false;
    }

    private static bool ContainsJsonField(string jsonObject, string fieldName)
    {
        string key = "\"" + fieldName + "\"";
        int index = jsonObject.IndexOf(key, System.StringComparison.Ordinal);
        if (index < 0) return false;
        int colon = jsonObject.IndexOf(':', index + key.Length);
        if (colon < 0) return false;
        for (int i = index + key.Length; i < colon; i++)
        {
            if (!char.IsWhiteSpace(jsonObject[i])) return false;
        }
        return true;
    }

    private void ExpireExperimentalModelWarningIfNeeded()
    {
        if (!experimentalModelWarningActive) return;
        double age = activeExperimentalFeatureAgeSeconds +
                    (GetMonotonicSeconds() - activeExperimentalReceiveMonotonicSeconds);
        if (!enableExperimentalModelWarning) ClearExperimentalModelWarning("feature_disabled");
        else if (age > ExperimentalModelWarningMaxAgeSeconds)
            ClearExperimentalModelWarning("prediction_age_exceeded_0_3s");
    }

    private void ClearExperimentalModelWarning(string revokeReason)
    {
        if (!experimentalModelWarningActive) return;
        double revokeMonotonicSeconds = GetMonotonicSeconds();
        LogExperimentalModelWarning("REVOKED", revokeReason, activeExperimentalReason,
            activeExperimentalRunId, activeExperimentalPredictionSequence, revokeMonotonicSeconds);
        experimentalModelWarningActive = false;
        activeExperimentalModelId = string.Empty;
        activeExperimentalRunId = string.Empty;
        activeExperimentalReason = string.Empty;
        activeExperimentalStrongProbability = 0f;
        activeExperimentalPredictionSequence = -1;
        activeExperimentalReceiveMonotonicSeconds = 0d;
        activeExperimentalFeatureAgeSeconds = 0f;
    }

    private void RecordExperimentalWarningObservation(
        string state, string modelId, long predictionSequence, string reason, string runId, double receiveTime)
    {
        string signature = string.Concat(runId ?? string.Empty, "|", modelId ?? string.Empty, "|",
            predictionSequence.ToString(), "|", state ?? string.Empty, "|", reason ?? string.Empty);
        if (string.Equals(signature, lastObservedExperimentalState, System.StringComparison.Ordinal)) return;
        lastObservedExperimentalState = signature;
        lastObservedExperimentalRunId = runId ?? string.Empty;
        if (verboseObservationLogs)
        {
            LogExperimentalModelWarning("RECEIVED", state ?? string.Empty, reason ?? string.Empty,
                runId ?? string.Empty, predictionSequence, receiveTime);
        }
    }

    private void LogExperimentalModelWarning(
        string state, string revokeReason, string backendReason, string runId,
        long predictionSequence, double localMonotonicSeconds)
    {
        Debug.Log($"[ExperimentalModelWarning] state={state} local_monotonic_s={localMonotonicSeconds:F6} " +
                  $"run_id={runId} prediction_sequence={predictionSequence} reason={backendReason} " +
                  $"revoke_reason={revokeReason}");
    }

    private static double GetMonotonicSeconds()
    {
        return System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency;
    }

    private static bool IsFinite(float value)
    {
        return !float.IsNaN(value) && !float.IsInfinity(value);
    }

    private static bool IsFinite(double value)
    {
        return !double.IsNaN(value) && !double.IsInfinity(value);
    }

    private void OnApplicationQuit()
    {
        ClearExperimentalModelWarning("application_quit");
        ClearExperimentalGeometryWarning("application_quit");
        ClearExperimentalProximityWarning("application_quit");
    }

    private void OnDisable()
    {
        FlushGeometryValidationSuppressionSummary();
        ClearExperimentalModelWarning("receiver_disabled");
        ClearExperimentalGeometryWarning("receiver_disabled");
        ClearExperimentalProximityWarning("receiver_disabled");
    }

    private void ReceiveDataLoop()
    {
        IPEndPoint remoteEndPoint = new IPEndPoint(IPAddress.Any, 0);
        while (true)
        {
            try
            {
                byte[] data = udpClient.Receive(ref remoteEndPoint);
                string rawJson = Encoding.UTF8.GetString(data);

                lock (dataLock)
                {
                    pendingJsonData = rawJson;
                    pendingReceiveMonotonicSeconds = GetMonotonicSeconds();
                }
            }
            catch (System.Exception)
            {
                // UDP 线程关闭时可能会报异常，直接忽略
            }
        }
    }

    private void OnDestroy()
    {
        FlushGeometryValidationSuppressionSummary();
        ClearExperimentalModelWarning("receiver_destroyed");
        ClearExperimentalGeometryWarning("receiver_destroyed");
        ClearExperimentalProximityWarning("receiver_destroyed");
        if (Instance == this) Instance = null;
        if (receiveThread != null && receiveThread.IsAlive) receiveThread.Abort();
        if (udpClient != null) { udpClient.Close(); udpClient = null; }
    }
}
