using UnityEngine;
using System.Collections.Generic;

public class LevelManager : MonoBehaviour
{
    public enum GameRunState { NotStarted, Running, Ended }

    public const int MaxDifficultyLevel = 5; // 确保最高是 5

    [Header("Platform Settings")]
    public GameObject[] platformPrefabs; 
    public int platformCount = 6;      
    public float verticalGap = 10f;    

    [Header("Calibration Settings (10秒静息期)")]
    [Tooltip("拖入你做好的实心、带 Box Collider 的校准平台预制体")]
    public GameObject calibrationPlatformPrefab; 
    public float calibrationDuration = 10f; 
    private bool isCalibrating = true;      
    private float calibrationTimer = 0f;

    [Header("References")]
    public Transform player;

    [Header("Progression Settings")]
    [Tooltip("达到多少层后直接胜利并结束游戏")]
    public int maxLayersToWin = 25;
    public int currentLevel = 1;
    private int platformsPassed = 0;

    [Header("Calibration Collection")]
    public bool enableCalibrationMode = true;
    [SerializeField] private int defaultSessionLayers = 25;
    [SerializeField, Tooltip("0 = Auto, 1-5 = fixed difficulty")]
    private int defaultCalibrationDifficulty = 0;

    private static bool calibrationSelectionInitialized;
    private static int nextSessionLayers = 25;
    private static int nextSelectedDifficulty;
    private const string SessionLayersPreferenceKey = "EndlessFalling.SessionLayers";
    private const string DifficultyPreferenceKey = "EndlessFalling.Difficulty";
    private bool calibrationMode;
    private int selectedSessionLayers = 25;
    private int selectedDifficulty;

    [Header("Difficulty Tuning")]
    public float[] scaleByDifficulty = { 1.2f, 1.0f, 0.85f, 0.7f, 0.6f };
    public float[] deathRadiusByLevel = { 10.3f, 8.6f, 7.3f, 6.0f, 5.2f };

    [Header("Difficulty Authority")]
    [Tooltip("When enabled, only backend realtime packets may command difficulty.")]
    public bool useBackendDifficulty = true;

    [Header("AI Dynamic Difficulty (DDA)")]
    [Tooltip("Local fallback only. Ignored while useBackendDifficulty is enabled.")]
    public bool enableDDA = false;
    public int[] baselinePlan = { 1, 1, 2, 2, 3, 3, 4, 4, 4, 5, 5, 5 }; 
    public float toleranceMargin = 0.15f; 

    private enum DDAState { Baseline, Adaptive }
    private DDAState ddaState = DDAState.Baseline;
    private List<float> completionTimes = new List<float>(); 
    private float timeOnCurrentPlatform = 0f; 
    public float baselineAverageTime = 0f; 

    private List<GameObject> activePlatforms = new List<GameObject>();
    private readonly Dictionary<int, int> platformDifficultyByInstance = new Dictionary<int, int>();
    private readonly Dictionary<int, int> platformGeometryGenerationByInstance = new Dictionary<int, int>();
    private GameObject calibrationPlatformInstance;
    private Transform cachedHolePlatform;
    private Vector3 cachedHolePlatformScale;
    private Vector3 cachedHoleCenter;
    private float cachedHoleRadius = float.NaN;
    private float nextSpawnY = 0f;
    private float lastHoleAngle = 0f;
    private bool stageCompleted = false;
    private GameRunState runState = GameRunState.NotStarted;
    private string runId = string.Empty;
    private double runStartBackendTimestamp = double.NaN;
    private string sessionOutcome = string.Empty;
    private double sessionEndBackendTimestamp = double.NaN;
    private int commandedDifficulty = 1;

    public GameRunState RunState => runState;
    public string RunStateTelemetry => runState == GameRunState.Running ? "running" : runState == GameRunState.Ended ? "ended" : "not_started";
    public string RunId => runId;
    public double RunStartBackendTimestamp => runStartBackendTimestamp;
    public string SessionOutcome => sessionOutcome;
    public double SessionEndBackendTimestamp => sessionEndBackendTimestamp;
    public bool IsRunRunning => runState == GameRunState.Running;
    public int CommandedDifficulty => commandedDifficulty;
    public int ActivePlatformDifficulty => GetActivePlatformDifficulty();
    public bool CalibrationMode => calibrationMode;
    public bool IsCalibrationStage => isCalibrating;
    public int SelectedSessionLayers => selectedSessionLayers;
    public int SelectedDifficulty => selectedDifficulty;
    public string SelectedDifficultyLabel => selectedDifficulty == 0 ? "Auto" : selectedDifficulty.ToString();
    public int EffectiveSessionLayers => calibrationMode ? selectedSessionLayers : maxLayersToWin;
    public bool IsFixedCalibrationDifficulty => calibrationMode && selectedDifficulty > 0;

    void Awake()
    {
        InitializeCalibrationSelection();
        calibrationMode = enableCalibrationMode;
        selectedSessionLayers = calibrationMode ? nextSessionLayers : maxLayersToWin;
        selectedDifficulty = calibrationMode ? nextSelectedDifficulty : 0;
    }

    private void InitializeCalibrationSelection()
    {
        if (calibrationSelectionInitialized) return;

        int defaultLayers = NormalizeSessionLayers(defaultSessionLayers);
        int defaultDifficulty = Mathf.Clamp(defaultCalibrationDifficulty, 0, MaxDifficultyLevel);
        nextSessionLayers = NormalizeSessionLayers(
            PlayerPrefs.GetInt(SessionLayersPreferenceKey, defaultLayers));
        nextSelectedDifficulty = Mathf.Clamp(
            PlayerPrefs.GetInt(DifficultyPreferenceKey, defaultDifficulty), 0, MaxDifficultyLevel);
        calibrationSelectionInitialized = true;
    }

    private static int NormalizeSessionLayers(int layers)
    {
        int[] choices = { 1, 3, 5, 10, 25 };
        int best = choices[0];
        int bestDistance = Mathf.Abs(layers - best);
        for (int i = 1; i < choices.Length; i++)
        {
            int distance = Mathf.Abs(layers - choices[i]);
            if (distance < bestDistance)
            {
                best = choices[i];
                bestDistance = distance;
            }
        }
        return best;
    }

    private static void SaveCalibrationSelection()
    {
        PlayerPrefs.SetInt(SessionLayersPreferenceKey, nextSessionLayers);
        PlayerPrefs.SetInt(DifficultyPreferenceKey, nextSelectedDifficulty);
        PlayerPrefs.Save();
    }

    public void SetNextCalibrationSelection(int sessionLayers, int difficulty)
    {
        if (!calibrationMode || IsRunRunning) return;
        nextSessionLayers = NormalizeSessionLayers(sessionLayers);
        nextSelectedDifficulty = Mathf.Clamp(difficulty, 0, MaxDifficultyLevel);
        SaveCalibrationSelection();
    }

    public int NextSessionLayers => nextSessionLayers;
    public int NextSelectedDifficulty => nextSelectedDifficulty;

    void Start()
    {
        EnsureVisualTheme();

        if (!IsFixedCalibrationDifficulty && !useBackendDifficulty && enableDDA && baselinePlan.Length > 0)
        {
            currentLevel = baselinePlan[0];
        }

        if (calibrationPlatformPrefab != null)
        {
            GameObject calibPlatform = Instantiate(calibrationPlatformPrefab, new Vector3(0, nextSpawnY, 0), Quaternion.identity);
            calibrationPlatformInstance = calibPlatform;
            activePlatforms.Add(calibPlatform);
            platformDifficultyByInstance[calibPlatform.GetInstanceID()] = currentLevel;
            platformGeometryGenerationByInstance[calibPlatform.GetInstanceID()] = 1;
            nextSpawnY -= verticalGap;
        }
    }

    void Update()
    {
        if (!IsRunRunning || stageCompleted) return;
        if (player == null || activePlatforms.Count == 0) return;
        
        if (isCalibrating)
        {
            calibrationTimer += Time.deltaTime;
            if (calibrationTimer >= calibrationDuration)
            {
                EndCalibrationStage();
            }
            return; 
        }

        timeOnCurrentPlatform += Time.deltaTime;

        // ==========================================
        // 【核心修复区域】：每一帧强制让 UI 同步最新的层数和难度！
        // ==========================================
        if (UIManager.Instance != null)
        {
            UIManager.Instance.UpdateHUD(GetCurrentLayer(), currentLevel, 0);
        }
        // ==========================================

        if (activePlatforms[0] != null && player.position.y < activePlatforms[0].transform.position.y - (verticalGap * 0.5f))
        {
            RecyclePlatform();
        }
    }

    void EndCalibrationStage()
    {
        if (!IsRunRunning) return;
        isCalibrating = false;
        GameObject calibPlatform = activePlatforms[0];
        activePlatforms.RemoveAt(0);
        platformDifficultyByInstance.Remove(calibPlatform.GetInstanceID());
        calibrationPlatformInstance = null;

        Destroy(calibPlatform);
        SpawnPlatform(false);
    }

    void RecyclePlatform()
    {
        if (!IsRunRunning || stageCompleted) return;

        EndlessPlayerController playerController = player != null
            ? player.GetComponent<EndlessPlayerController>()
            : FindObjectOfType<EndlessPlayerController>();
        if (playerController == null) return;

        // Re-evaluate the edge at the exact layer-recycle boundary. This is an
        // authoritative guard: a platform transition may never rescue a ball that
        // has already crossed the current platform edge between physics frames.
        playerController.RefreshEdgeAndFallState();
        if (!IsRunRunning || stageCompleted || !playerController.CanAdvanceLayer)
        {
            playerController.SetLayerTransitionBlocked(true);
            return;
        }

        if (playerController.IsOutsideCurrentPlatformEdge())
        {
            playerController.CommitEdgeExit("Fell off platform edge before layer transition");
            return;
        }

        if (!IsFixedCalibrationDifficulty && !useBackendDifficulty && enableDDA && baselinePlan.Length > 0)
        {
            ProcessDDALogic(timeOnCurrentPlatform);
        }
        timeOnCurrentPlatform = 0f; 

        platformsPassed++; 
        UdpFrontendReceiver.NotifyLayerTransition();
        
        // 检测是否达到最大层数
        if (platformsPassed >= EffectiveSessionLayers)
        {
            stageCompleted = true;
            EndlessPlayerController ctrl = FindObjectOfType<EndlessPlayerController>();
            // 触发胜利状态！
            if(ctrl != null) ctrl.TriggerWin();
            return;
        }

        GameObject recycledPlatform = activePlatforms[0];
        GameObject nextPlatform = activePlatforms.Count > 1 ? activePlatforms[1] : null;
        int fromLayer = GetCurrentLayer() - 1;
        int fromPlatformId = recycledPlatform != null ? recycledPlatform.GetInstanceID() : -1;
        int toLayer = GetCurrentLayer();
        int toPlatformId = nextPlatform != null ? nextPlatform.GetInstanceID() : fromPlatformId;
        UDPManager.RecordLayerTransition(
            "before",
            RunId,
            fromLayer,
            toLayer,
            fromPlatformId,
            toPlatformId,
            playerController.DiagnosticSupportContactPlatformId,
            playerController.DiagnosticLastSupportContactFixedTime,
            playerController.DiagnosticInsideHoleOpening,
            playerController.DiagnosticBeyondOuterEdge,
            playerController.DiagnosticCrossedSupportBoundary,
            "recycle_platform_after_can_advance_check",
            recycledPlatform != null ? recycledPlatform.transform : null,
            fromLayer);

        activePlatforms.RemoveAt(0);
        platformDifficultyByInstance.Remove(recycledPlatform.GetInstanceID());
        AdvancePlatformGeometryGeneration(recycledPlatform);
        recycledPlatform.transform.position = new Vector3(0, nextSpawnY, 0);
        recycledPlatform.transform.rotation = platformPrefabs[0].transform.rotation;

        ApplyDifficultyToPlatform(recycledPlatform);

        activePlatforms.Add(recycledPlatform);
        playerController.ResetForLayerTransition(nextPlatform != null ? nextPlatform.transform : recycledPlatform.transform);
        UDPManager.RecordLayerTransition(
            "after",
            RunId,
            fromLayer,
            toLayer,
            fromPlatformId,
            toPlatformId,
            playerController.DiagnosticSupportContactPlatformId,
            playerController.DiagnosticLastSupportContactFixedTime,
            playerController.DiagnosticInsideHoleOpening,
            playerController.DiagnosticBeyondOuterEdge,
            playerController.DiagnosticCrossedSupportBoundary,
            "recycle_platform_completed",
            nextPlatform != null ? nextPlatform.transform : recycledPlatform.transform,
            toLayer);
        nextSpawnY -= verticalGap;
    }

    void ProcessDDALogic(float timeTaken)
    {
        if (!IsRunRunning || useBackendDifficulty || !enableDDA) return;

        if (ddaState == DDAState.Baseline)
        {
            completionTimes.Add(timeTaken);
            int nextIndex = platformsPassed + 1;

            if (nextIndex < baselinePlan.Length)
            {
                int nextLevel = baselinePlan[nextIndex];
                SetLocalDifficulty(nextLevel);
            }
            else
            {
                CalculateBaseline();
                ddaState = DDAState.Adaptive;
                SetLocalDifficulty(3); 
            }
        }
        else if (ddaState == DDAState.Adaptive)
        {
            float lowerBound = baselineAverageTime * (1f - toleranceMargin);
            float upperBound = baselineAverageTime * (1f + toleranceMargin);

            int nextLevel = currentLevel;

            if (timeTaken < lowerBound)
            {
                nextLevel++; 
            }
            else if (timeTaken > upperBound)
            {
                nextLevel--; 
            }

            // 确保难度在 1 到 5 之间
            nextLevel = Mathf.Clamp(nextLevel, 1, MaxDifficultyLevel);
            
            if (nextLevel != currentLevel)
            {
                SetLocalDifficulty(nextLevel);
            }
        }
    }

    void CalculateBaseline()
    {
        if (completionTimes.Count == 0) return;

        completionTimes.Sort();
        if (completionTimes.Count > 4)
        {
            completionTimes.RemoveAt(0); 
            completionTimes.RemoveAt(completionTimes.Count - 1); 
        }
        
        float sum = 0;
        foreach (float t in completionTimes) sum += t;
        baselineAverageTime = sum / completionTimes.Count;
    }

    public void SetDifficultyFromAI(int aiLevel)
    {
        if (!IsRunRunning || !useBackendDifficulty || IsFixedCalibrationDifficulty) return;
        SetCommandedDifficulty(aiLevel);
    }

    private void SetLocalDifficulty(int level)
    {
        if (!IsRunRunning || useBackendDifficulty || !enableDDA || IsFixedCalibrationDifficulty) return;
        SetCommandedDifficulty(level);
    }

    private void SetCommandedDifficulty(int level)
    {
        commandedDifficulty = Mathf.Clamp(level, 1, MaxDifficultyLevel);
        currentLevel = commandedDifficulty;

        // Never rescale the active platform under the player. Future platforms may
        // adopt the latest backend command immediately in Auto mode.
        for (int i = 1; i < activePlatforms.Count; i++)
        {
            GameObject platform = activePlatforms[i];
            if (platform == null) continue;

            // The solid no-hole platform is a dedicated rest/calibration surface with
            // its own authored dimensions. It participates in difficulty telemetry but
            // must never use the normal gameplay platform scale table.
            if (platform != calibrationPlatformInstance)
            {
                int idx = Mathf.Clamp(commandedDifficulty - 1, 0, scaleByDifficulty.Length - 1);
                float scale = scaleByDifficulty[idx];
                platform.transform.localScale = new Vector3(scale, scale, scale);
            }
            platformDifficultyByInstance[platform.GetInstanceID()] = commandedDifficulty;
        }
    }

    void SpawnPlatform(bool isInitialSpawn)
    {
        int randomIndex = Random.Range(0, platformPrefabs.Length);
        GameObject newPlatform = Instantiate(platformPrefabs[randomIndex], new Vector3(0, nextSpawnY, 0), platformPrefabs[randomIndex].transform.rotation);
        
        ApplyDifficultyToPlatform(newPlatform);
        platformGeometryGenerationByInstance.TryGetValue(newPlatform.GetInstanceID(), out int generation);
        platformGeometryGenerationByInstance[newPlatform.GetInstanceID()] = Mathf.Max(1, generation);
        activePlatforms.Add(newPlatform);
        nextSpawnY -= verticalGap;
    }

    void ApplyDifficultyToPlatform(GameObject platform)
    {
        int idx = Mathf.Clamp(currentLevel - 1, 0, Mathf.Min(scaleByDifficulty.Length, deathRadiusByLevel.Length) - 1);
        float currentScale = scaleByDifficulty[idx];
        platform.transform.localScale = new Vector3(currentScale, currentScale, currentScale);

        float newAngle = GetSmartHoleAngle(idx + 1);
        platform.transform.Rotate(Vector3.up, newAngle, Space.World);
        lastHoleAngle = newAngle;
        platformDifficultyByInstance[platform.GetInstanceID()] = currentLevel;
        platformGeometryGenerationByInstance.TryGetValue(platform.GetInstanceID(), out int generation);
        platformGeometryGenerationByInstance[platform.GetInstanceID()] = Mathf.Max(1, generation);
    }

    private void AdvancePlatformGeometryGeneration(GameObject platform)
    {
        if (platform == null) return;
        int id = platform.GetInstanceID();
        platformGeometryGenerationByInstance.TryGetValue(id, out int generation);
        platformGeometryGenerationByInstance[id] = Mathf.Max(1, generation + 1);
    }

    float GetSmartHoleAngle(int level)
    {
        float offset = 0f;
        float sign = Random.value > 0.5f ? 1f : -1f; 

        switch (level)
        {
            case 1: offset = 180f; break; 
            case 2: offset = Random.Range(150f, 180f); break; 
            case 3: offset = Random.Range(120f, 180f); break; 
            case 4: offset = Random.Range(100f, 180f); break;
            case 5: offset = Random.Range(90f, 180f); break;  
        }
        return lastHoleAngle + (offset * sign);
    }

    public float GetCurrentDeathRadius()
    {
        int idx = Mathf.Clamp(currentLevel - 1, 0, deathRadiusByLevel.Length - 1);
        return deathRadiusByLevel[idx];
    }
    
    public bool BeginConfiguredRun()
    {
        if (runState != GameRunState.NotStarted) return false;

        calibrationMode = enableCalibrationMode;
        selectedSessionLayers = calibrationMode ? nextSessionLayers : maxLayersToWin;
        selectedDifficulty = calibrationMode ? nextSelectedDifficulty : 0;
        if (calibrationMode)
        {
            SaveCalibrationSelection();
        }
        if (IsFixedCalibrationDifficulty)
        {
            currentLevel = selectedDifficulty;
        }
        else if (!useBackendDifficulty && enableDDA && baselinePlan.Length > 0)
        {
            currentLevel = baselinePlan[0];
        }

        commandedDifficulty = Mathf.Clamp(currentLevel, 1, MaxDifficultyLevel);
        if (calibrationPlatformInstance != null)
        {
            platformDifficultyByInstance[calibrationPlatformInstance.GetInstanceID()] = commandedDifficulty;
        }
        for (int i = activePlatforms.Count; i < platformCount; i++)
        {
            SpawnPlatform(true);
        }

        BeginNewRun();
        return IsRunRunning;
    }

    private void BeginNewRun()
    {
        if (runState != GameRunState.NotStarted) return;

        runId = System.Guid.NewGuid().ToString("N");
        runStartBackendTimestamp = UDPManager.GetBackendUnixTimestamp();
        sessionOutcome = string.Empty;
        sessionEndBackendTimestamp = double.NaN;
        platformsPassed = 0;
        stageCompleted = false;
        commandedDifficulty = IsFixedCalibrationDifficulty
            ? selectedDifficulty
            : Mathf.Clamp(currentLevel, 1, MaxDifficultyLevel);
        currentLevel = commandedDifficulty;
        runState = GameRunState.Running;
        UdpFrontendReceiver.NotifyRunStarted(runId);
        UDPManager.RecordNewRunCreated(runId);

        EndlessPlayerController playerController = player != null
            ? player.GetComponent<EndlessPlayerController>()
            : FindObjectOfType<EndlessPlayerController>();
        if (playerController != null)
        {
            playerController.ResetRunTelemetryState();
        }
    }

    public string GetCompletionOutcome()
    {
        return calibrationMode && selectedSessionLayers < 25
            ? "calibration_completed"
            : "completed";
    }

    public bool MarkRunEnded(string outcome)
    {
        if (runState != GameRunState.Running) return false;

        runState = GameRunState.Ended;
        UdpFrontendReceiver.NotifyRunEnded("run_ended:" + (outcome ?? string.Empty));
        stageCompleted = true;
        sessionOutcome = outcome;
        EndlessPlayerController playerController = player != null
            ? player.GetComponent<EndlessPlayerController>()
            : FindObjectOfType<EndlessPlayerController>();
        if (playerController != null)
        {
            playerController.OnRunEnded(outcome == "edge_exit");
        }
        sessionEndBackendTimestamp = UDPManager.GetBackendUnixTimestamp();
        return true;
    }

    private int GetActivePlatformDifficulty()
    {
        Transform platform = GetCurrentPlatformTransform();
        if (platform != null && platformDifficultyByInstance.TryGetValue(platform.gameObject.GetInstanceID(), out int difficulty))
        {
            return difficulty;
        }
        return commandedDifficulty;
    }

    public int GetPassedCount() { return platformsPassed; }
    
    public int GetCurrentLayer() { return platformsPassed + 1; }

    public float GetCurrentPlatformScale()
    {
        int idx = Mathf.Clamp(currentLevel - 1, 0, scaleByDifficulty.Length - 1);
        return scaleByDifficulty[idx];
    }

    public Vector3 GetCurrentHolePosition()
    {
        return TryGetCurrentHoleTelemetryGeometry(out Vector3 center, out _)
            ? center
            : Vector3.one * float.NaN;
    }

    /// <summary>
    /// Returns the target hole centre and its actual world-space inner-edge radius.
    /// This is telemetry-only geometry and does not participate in gameplay collision.
    /// </summary>
    public bool TryGetCurrentHoleTelemetryGeometry(out Vector3 center, out float radius)
    {
        center = Vector3.zero;
        radius = float.NaN;
        Transform platform = GetCurrentPlatformTransform();
        if (platform == null) return false;

        PlatformData data = platform.GetComponent<PlatformData>();
        if (data == null || data.holeCenter == null) return false;

        Vector3 platformScale = platform.lossyScale;
        if (cachedHolePlatform != platform || cachedHolePlatformScale != platformScale)
        {
            cachedHolePlatform = platform;
            cachedHolePlatformScale = platformScale;
            cachedHoleCenter = data.holeCenter.position;
            bool useMeshFallback = data.holeRadius <= 0f;
            cachedHoleRadius = useMeshFallback
                ? float.PositiveInfinity
                : data.holeRadius * Mathf.Max(Mathf.Abs(platform.lossyScale.x), Mathf.Abs(platform.lossyScale.z));

            // The authored calibration prefab uses a large primitive root scale while its
            // PlatformData radius is already expressed in world units. Reject any scaled
            // hole radius that would exceed the platform itself and use the authored value.
            if (!useMeshFallback && GetPlatformTelemetryGeometry(
                    platform, Vector2.right, out _, out float platformRadius, out _, out _, out _, out _, out _) &&
                cachedHoleRadius >= platformRadius)
            {
                cachedHoleRadius = data.holeRadius;
            }

            if (useMeshFallback)
            {
                MeshFilter[] filters = platform.GetComponentsInChildren<MeshFilter>();
                foreach (MeshFilter filter in filters)
                {
                    Mesh mesh = filter.sharedMesh;
                    if (mesh == null || !mesh.isReadable) continue;
                    Vector3[] vertices = mesh.vertices;
                    for (int i = 0; i < vertices.Length; i++)
                    {
                        Vector3 worldVertex = filter.transform.TransformPoint(vertices[i]);
                        float horizontalDistance = new Vector2(
                            worldVertex.x - cachedHoleCenter.x,
                            worldVertex.z - cachedHoleCenter.z).magnitude;
                        if (horizontalDistance > 0.0001f)
                        {
                            cachedHoleRadius = Mathf.Min(cachedHoleRadius, horizontalDistance);
                        }
                    }
                }
            }

            if (float.IsInfinity(cachedHoleRadius)) cachedHoleRadius = float.NaN;
        }
        else
        {
            cachedHoleCenter = data.holeCenter.position;
        }

        center = cachedHoleCenter;
        radius = cachedHoleRadius;
        return !float.IsNaN(radius) && radius > 0f;
    }

    public bool GetDirectionalPlatformOuterRadius(Vector2 edgeDirection, out float radius, out Vector3 edgePoint, out string source)
    {
        return GetDirectionalPlatformOuterRadius(GetCurrentPlatformTransform(), edgeDirection, out radius, out edgePoint, out source);
    }

    private static bool GetDirectionalPlatformOuterRadius(
        Transform platform, Vector2 edgeDirection, out float radius, out Vector3 edgePoint, out string source)
    {
        radius = float.NaN;
        edgePoint = Vector3.one * float.NaN;
        source = string.Empty;
        if (platform == null) return false;
        Vector2 direction = edgeDirection.sqrMagnitude > 0.000001f ? edgeDirection.normalized : Vector2.right;
        EndlessFallingGeometryDiagnostics.BoundaryQueryResult query = EndlessFallingGeometryDiagnostics.QueryOuterBoundary(
            platform, platform.position, direction, 0f, 64, 8);
        if (!query.valid) return false;
        radius = query.boundaryRadius;
        edgePoint = query.boundaryPoint;
        source = "active_collider_vertical_ray_radial_scan_binary_refine";
        return true;
    }

    public bool GetCurrentPlatformTelemetryGeometryIdentity(
        Vector3 worldPosition,
        out int platformInstanceId,
        out string geometryVersionId,
        out float geometrySourceTimestamp,
        out bool queryValid,
        out bool ownershipValid,
        out Vector3 center,
        out float radius,
        out float worldScale,
        out float top,
        out Vector3 colliderWorldScale,
        out string radiusSource,
        out Vector3 directionalEdgePoint,
        out int activePlatformInstanceId,
        out string activeGeometryVersionId)
    {
        platformInstanceId = 0;
        geometryVersionId = string.Empty;
        geometrySourceTimestamp = float.NaN;
        queryValid = false;
        ownershipValid = false;
        center = Vector3.zero;
        radius = float.NaN;
        worldScale = float.NaN;
        top = float.NaN;
        colliderWorldScale = Vector3.one * float.NaN;
        radiusSource = string.Empty;
        directionalEdgePoint = Vector3.one * float.NaN;
        activePlatformInstanceId = 0;
        activeGeometryVersionId = string.Empty;

        Transform queriedPlatform = GetCurrentPlatformTransform();
        platformInstanceId = queriedPlatform != null ? queriedPlatform.gameObject.GetInstanceID() : 0;
        platformGeometryGenerationByInstance.TryGetValue(platformInstanceId, out int generationBefore);
        geometryVersionId = platformInstanceId != 0 && generationBefore > 0
            ? platformInstanceId + "-g" + generationBefore
            : string.Empty;
        if (queriedPlatform == null) return false;

        center = queriedPlatform.position;
        Vector2 offset = new Vector2(worldPosition.x - center.x, worldPosition.z - center.z);
        Vector2 edgeDirection = offset.sqrMagnitude > 0.000001f ? offset.normalized : Vector2.right;
        geometrySourceTimestamp = Time.time;
        queryValid = GetPlatformTelemetryGeometry(
            queriedPlatform, edgeDirection, out center, out radius, out worldScale, out top,
            out colliderWorldScale, out radiusSource, out directionalEdgePoint);

        Transform platformAfterQuery = GetCurrentPlatformTransform();
        activePlatformInstanceId = platformAfterQuery != null ? platformAfterQuery.gameObject.GetInstanceID() : 0;
        platformGeometryGenerationByInstance.TryGetValue(activePlatformInstanceId, out int generationAfter);
        activeGeometryVersionId = activePlatformInstanceId != 0 && generationAfter > 0
            ? activePlatformInstanceId + "-g" + generationAfter
            : string.Empty;
        ownershipValid = queryValid && generationBefore > 0 &&
                         platformAfterQuery == queriedPlatform && activePlatformInstanceId == platformInstanceId &&
                         generationAfter == generationBefore;
        return queryValid && ownershipValid;
    }

    // The first active platform is the platform currently being played.
    public Transform GetCurrentPlatformTransform()
    {
        return activePlatforms.Count > 0 && activePlatforms[0] != null
            ? activePlatforms[0].transform
            : null;
    }

    /// <summary>
    /// Returns world-space geometry from the active platform colliders. This is telemetry
    /// metadata only; it does not participate in gameplay decisions.
    /// </summary>
    private bool GetPlatformTelemetryGeometry(
        Transform platform,
        Vector2 edgeDirection,
        out Vector3 center,
        out float radius,
        out float worldScale,
        out float top,
        out Vector3 colliderWorldScale,
        out string radiusSource,
        out Vector3 directionalEdgePoint)
    {
        center = Vector3.zero;
        radius = float.NaN;
        worldScale = float.NaN;
        top = float.NaN;
        colliderWorldScale = Vector3.one * float.NaN;
        radiusSource = string.Empty;
        directionalEdgePoint = Vector3.one * float.NaN;
        if (platform == null) return false;

        center = platform.position;
        worldScale = platform.lossyScale.x;
        top = platform.position.y;
        float maxRadius = 0f;
        Collider radiusCollider = null;
        Collider[] colliders = platform.GetComponentsInChildren<Collider>();

        foreach (Collider platformCollider in colliders)
        {
            if (!platformCollider.enabled || platformCollider.isTrigger || platformCollider.bounds.size.sqrMagnitude <= 0f)
            {
                continue;
            }

            Bounds bounds = platformCollider.bounds;
            float radiusX = Mathf.Abs(bounds.center.x - center.x) + bounds.extents.x;
            float radiusZ = Mathf.Abs(bounds.center.z - center.z) + bounds.extents.z;
            float candidateRadius = Mathf.Min(radiusX, radiusZ);
            if (candidateRadius > maxRadius)
            {
                maxRadius = candidateRadius;
                radiusCollider = platformCollider;
            }
            top = Mathf.Max(top, bounds.max.y);
        }

        Vector2 direction = edgeDirection.sqrMagnitude > 0.0001f ? edgeDirection.normalized : Vector2.zero;
        if (direction.sqrMagnitude > 0.0001f)
        {
            if (GetDirectionalPlatformOuterRadius(platform, direction, out float directionalRadius, out Vector3 queriedPoint, out string queriedSource))
            {
                radius = directionalRadius;
                directionalEdgePoint = queriedPoint;
                radiusSource = queriedSource;
                return true;
            }

            radius = float.NaN;
            directionalEdgePoint = Vector3.one * float.NaN;
            radiusSource = "unknown_directional_query_failed";
            return false;
        }

        radius = maxRadius > 0f ? maxRadius : float.NaN;
        if (radiusCollider != null)
        {
            colliderWorldScale = radiusCollider.transform.lossyScale;
            radiusSource = radiusCollider.GetType().Name + ":" + radiusCollider.name;
            if (radiusSource.Length == 0) radiusSource = "bounds_fallback";
        }

        Vector2 edgeDirection2 = edgeDirection.sqrMagnitude > 0.0001f ? edgeDirection.normalized : Vector2.zero;
        directionalEdgePoint = center + new Vector3(edgeDirection2.x * radius, 0f, edgeDirection2.y * radius);
        return !float.IsNaN(radius);
    }

    private void OnApplicationQuit()
    {
        if (MarkRunEnded("user_exit"))
        {
            UDPManager.ReportRunEnded();
        }
    }

    void EnsureVisualTheme()
    {
        EndlessVisualTheme theme = FindObjectOfType<EndlessVisualTheme>();
        if (theme != null) return;
        GameObject go = new GameObject("EndlessVisualTheme");
        go.AddComponent<EndlessVisualTheme>();
    }
}