using UnityEngine;
using UnityEngine.SceneManagement;
using System.Collections;
using System.Collections.Generic;

[RequireComponent(typeof(Rigidbody))]
public class EndlessPlayerController : MonoBehaviour
{
    [Header("核心控制参数 (WASD 键盘平滑适配)")]
    [Tooltip("输入灵敏度/速度：调小它，小球的移动速度就会变慢")]
    [Range(0.1f, 3.0f)]
    public float inputSensitivity = 0.5f; 

    [Header("WBB 传感器数据监测 (不影响移动)")]
    [Tooltip("此变量用于存放来自 Python 的重心数据，仅供数据记录或 AI 分析")]
    public Vector2 externalWbbData = Vector2.zero; 
    public int filterSize = 15; 
    public float deadzone = 0.05f; 

    [Header("输入反转设置")]
    public bool invertX = true;
    public bool invertY = false;

    [Header("物理弹簧手感")]
    public float maxReach = 12f; 
    public float springForce = 2f;

    private Queue<Vector3> inputHistory = new Queue<Vector3>();

    private Rigidbody rb;
    private Transform cam;
    private LevelManager levelManager;
    private Transform cachedBoundsPlatform;
    private Collider[] cachedPlatformColliders;
    
    private bool isDead;
    private bool hasWon;
    private int warningEpisodeId;
    private int warningEnterCount;
    private int warningExitCount;
    private float lastSupportContactFixedTime = float.NaN;
    private int supportContactPlatformId = int.MinValue;
    private bool layerTransitionBlocked;
    private bool edgeWarningState;
    private bool edgeContactState;
    private float edgeWarningTime = float.NaN;
    private float edgeWarningEndTime = float.NaN;
    private float edgeContactTime = float.NaN;
    private float supportLostTime = float.NaN;
    private float fallEventTime = float.NaN;
    private double edgeWarningBackendTimestamp = double.NaN;
    private double edgeWarningEndBackendTimestamp = double.NaN;
    private double edgeContactBackendTimestamp = double.NaN;
    private double supportLostBackendTimestamp = double.NaN;
    private double fallEventBackendTimestamp = double.NaN;
    private string fallDirection = string.Empty;
    private Transform telemetryPlatform;
    private bool externalCopReceived;

    // Local geometry diagnostics only. These values observe existing predicates and
    // are not consumed by movement, support-loss, death, or layer progression.
    private float diagnosticRadialDistance = float.NaN;
    private float diagnosticPlayerRadius = float.NaN;
    private float diagnosticSupportBoundaryRadius = float.NaN;
    private bool diagnosticInsideHoleOpening;
    private bool diagnosticBeyondOuterEdge;
    private bool diagnosticCrossedSupportBoundary;
    private float diagnosticWarningRadialDistance = float.NaN;
    private float diagnosticWarningPredicateRadius = float.NaN;
    private bool diagnosticWarningNearEdge;
    private bool diagnosticWarningStateBeforeTransition;
    private float diagnosticWarningTransitionTime = float.NaN;
    private double diagnosticWarningTransitionBackendTimestamp = double.NaN;
    private float diagnosticEdgeContactRadialDistance = float.NaN;
    private float diagnosticEdgeContactPredicateRadius = float.NaN;
    private bool diagnosticEdgeContactPredicateResult;
    private float diagnosticEdgeContactTransitionTime = float.NaN;
    private double diagnosticEdgeContactTransitionBackendTimestamp = double.NaN;

    // 【核心架构接口】供 UDPManager/UdpFrontendReceiver 调用。
    // 作用：只把 Python 算好的数据存起来供后续模块提取，绝对不干扰物理层的 WASD 逻辑。
    public void SetExternalWbbData(float x, float y)
    {
        externalWbbData = new Vector2(x, y);
        externalCopReceived = true;
    }

    void Start()
    {
        inputSensitivity = GameSensitivitySettings.GetFalling();
        rb = GetComponent<Rigidbody>();
        if (Camera.main != null) cam = Camera.main.transform;
        rb.interpolation = RigidbodyInterpolation.Interpolate;
        levelManager = FindObjectOfType<LevelManager>();
    }

    void Update()
    {
        RefreshEdgeAndFallState();
    }

    /// <summary>
    /// Re-evaluates the existing platform geometry before normal layer progression.
    /// It observes state only and does not change Rigidbody or input behavior.
    /// </summary>
    public void RefreshEdgeAndFallState()
    {
        if (isDead || hasWon || levelManager == null || !levelManager.IsRunRunning) return;

        Transform currentPlatform = levelManager.GetCurrentPlatformTransform();
        if (currentPlatform != telemetryPlatform) ResetPlatformTelemetryState(currentPlatform);

        if (currentPlatform != null)
        {
            Vector2 offsetFromPlatform = new Vector2(
                transform.position.x - currentPlatform.position.x,
                transform.position.z - currentPlatform.position.z);
            GetPlatformBounds(currentPlatform, out float boundsOuterRadius, out float platformTop);
            float outerRadius = boundsOuterRadius;
            Vector2 warningDirection = offsetFromPlatform.sqrMagnitude > 0.0001f ? offsetFromPlatform.normalized : Vector2.right;
            bool actualBoundaryValid = levelManager.GetDirectionalPlatformOuterRadius(
                warningDirection, out float queriedOuterRadius, out _, out _);
            if (actualBoundaryValid && queriedOuterRadius > 0f)
            {
                outerRadius = queriedOuterRadius;
            }
            UpdateEdgeTelemetry(offsetFromPlatform, outerRadius, platformTop);

            Collider playerCollider = GetComponent<Collider>();
            float playerRadius = playerCollider != null
                ? Mathf.Max(playerCollider.bounds.extents.x, playerCollider.bounds.extents.z)
                : 0.5f;
            float radialDistance = offsetFromPlatform.magnitude;
            bool outsideOuterEdge = IsOutsidePlatformEdge(
                currentPlatform, transform.position, playerRadius, outerRadius);
            diagnosticRadialDistance = radialDistance;
            diagnosticPlayerRadius = playerRadius;
            diagnosticSupportBoundaryRadius = Mathf.Max(0f, outerRadius - playerRadius);
            diagnosticInsideHoleOpening = IsInsideCurrentHole(transform.position, playerRadius);
            diagnosticBeyondOuterEdge = outsideOuterEdge;
            diagnosticCrossedSupportBoundary = outsideOuterEdge;
            if (outsideOuterEdge)
            {
                TriggerDeath("Fell off platform outer edge at: " + transform.position);
            }
        }

        if (UIManager.Instance != null)
            UIManager.Instance.UpdateHUD(levelManager.GetCurrentLayer(), levelManager.currentLevel, 0);
    }

    private void ResetPlatformTelemetryState(Transform platform)
    {
        CloseEdgeWarningEpisode();
        telemetryPlatform = platform;
        edgeWarningState = false;
        edgeContactState = false;
        edgeWarningTime = float.NaN;
        edgeWarningEndTime = float.NaN;
        edgeContactTime = float.NaN;
        supportLostTime = float.NaN;
        fallEventTime = float.NaN;
        edgeWarningBackendTimestamp = double.NaN;
        edgeWarningEndBackendTimestamp = double.NaN;
        edgeContactBackendTimestamp = double.NaN;
        supportLostBackendTimestamp = double.NaN;
        fallEventBackendTimestamp = double.NaN;
        fallDirection = string.Empty;
        lastSupportContactFixedTime = float.NaN;
        supportContactPlatformId = int.MinValue;
        diagnosticRadialDistance = float.NaN;
        diagnosticPlayerRadius = float.NaN;
        diagnosticSupportBoundaryRadius = float.NaN;
        diagnosticInsideHoleOpening = false;
        diagnosticBeyondOuterEdge = false;
        diagnosticCrossedSupportBoundary = false;
        diagnosticWarningRadialDistance = float.NaN;
        diagnosticWarningPredicateRadius = float.NaN;
        diagnosticWarningNearEdge = false;
        diagnosticWarningStateBeforeTransition = false;
        diagnosticWarningTransitionTime = float.NaN;
        diagnosticWarningTransitionBackendTimestamp = double.NaN;
        diagnosticEdgeContactRadialDistance = float.NaN;
        diagnosticEdgeContactPredicateRadius = float.NaN;
        diagnosticEdgeContactPredicateResult = false;
        diagnosticEdgeContactTransitionTime = float.NaN;
        diagnosticEdgeContactTransitionBackendTimestamp = double.NaN;
    }

    public void ResetRunTelemetryState()
    {
        isDead = false;
        hasWon = false;
        layerTransitionBlocked = false;
        warningEpisodeId = 0;
        warningEnterCount = 0;
        warningExitCount = 0;
        ResetPlatformTelemetryState(levelManager != null ? levelManager.GetCurrentPlatformTransform() : null);
    }

    public void ResetForLayerTransition(Transform nextPlatform)
    {
        layerTransitionBlocked = false;
        ResetPlatformTelemetryState(nextPlatform);
    }

    // ==========================================
    // 核心修复区域：彻底隔离 vJoy 幽灵输入
    // ==========================================
    private float GetSmoothX()
    {
        // 完全抛弃 GetAxis，只读取物理键盘按键
        float x = 0f;
        if (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow)) x += 1f;
        if (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow)) x -= 1f;
        
        return invertX ? -x : x;
    }

    private float GetSmoothY()
    {
        // 同样只读取物理键盘按键
        float y = 0f;
        if (Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow)) y += 1f;
        if (Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow)) y -= 1f;
        
        return invertY ? -y : y;
    }
    // ==========================================

    void FixedUpdate()
    {
        if (isDead || hasWon) return;
        RefreshEdgeAndFallState();
        if (isDead || hasWon) return;

        // 1. 获取纯净的键盘输入
        float smoothX = GetSmoothX(); 
        float smoothY = GetSmoothY();
        
        // 2. 计算缩放输入
        Vector3 scaledInput = new Vector3(smoothX, 0, smoothY) * inputSensitivity;

        // 3. 移动平均滤波 (处理键盘操作的平滑感)
        inputHistory.Enqueue(scaledInput);
        if (inputHistory.Count > filterSize)
        {
            inputHistory.Dequeue();
        }

        Vector3 smoothedInput = Vector3.zero;
        foreach (Vector3 input in inputHistory)
        {
            smoothedInput += input;
        }
        
        if (inputHistory.Count > 0)
        {
            smoothedInput /= inputHistory.Count;
        }

        if (smoothedInput.magnitude < deadzone)
        {
            smoothedInput = Vector3.zero;
        }

        // 4. 输入直接控制水平速度，不再把球弹簧式拽回世界原点。
        // 松开输入时保持当前惯性，由物理接触自然决定球是否滚出平台。
        Vector3 horizontalVelocity = new Vector3(rb.linearVelocity.x, 0f, rb.linearVelocity.z);
        if (smoothedInput != Vector3.zero)
        {
            // Keep the old centre-position speed scale (input * reach * spring),
            // but make it independent of the ball's distance from world origin.
            horizontalVelocity = smoothedInput * maxReach * springForce;
        }

        rb.linearVelocity = new Vector3(horizontalVelocity.x, rb.linearVelocity.y, horizontalVelocity.z);
    }

    private void UpdateEdgeTelemetry(Vector2 offsetFromPlatform, float outerRadius, float platformTop)
    {
        if (outerRadius <= 0f) return;

        Collider playerCollider = GetComponent<Collider>();
        float playerRadius = playerCollider != null
            ? Mathf.Max(playerCollider.bounds.extents.x, playerCollider.bounds.extents.z)
            : 0.5f;
        float warningRadius = Mathf.Max(0f, outerRadius - playerRadius * 2f);
        float radialDistance = offsetFromPlatform.magnitude;
        bool nearEdge = radialDistance >= warningRadius;
        bool wasWarning = edgeWarningState;
        diagnosticWarningRadialDistance = radialDistance;
        diagnosticWarningPredicateRadius = warningRadius;
        diagnosticWarningNearEdge = nearEdge;
        diagnosticWarningStateBeforeTransition = wasWarning;
        if (nearEdge && !wasWarning)
        {
            edgeWarningState = true;
            warningEpisodeId++;
            warningEnterCount++;
            edgeWarningTime = Time.time;
            edgeWarningEndTime = float.NaN;
            edgeWarningBackendTimestamp = UDPManager.GetBackendUnixTimestamp();
            edgeWarningEndBackendTimestamp = double.NaN;
            diagnosticWarningTransitionTime = edgeWarningTime;
            diagnosticWarningTransitionBackendTimestamp = edgeWarningBackendTimestamp;
        }
        else if (!nearEdge && wasWarning)
        {
            CloseEdgeWarningEpisode();
            diagnosticWarningTransitionTime = edgeWarningEndTime;
            diagnosticWarningTransitionBackendTimestamp = edgeWarningEndBackendTimestamp;
        }

        bool touchingOrCrossingEdge = radialDistance >= Mathf.Max(0f, outerRadius - playerRadius);
        bool wasEdgeContact = edgeContactState;
        diagnosticEdgeContactRadialDistance = radialDistance;
        diagnosticEdgeContactPredicateRadius = Mathf.Max(0f, outerRadius - playerRadius);
        diagnosticEdgeContactPredicateResult = touchingOrCrossingEdge;
        if (touchingOrCrossingEdge != wasEdgeContact)
        {
            diagnosticEdgeContactTransitionTime = Time.time;
            diagnosticEdgeContactTransitionBackendTimestamp = UDPManager.GetBackendUnixTimestamp();
        }
        edgeContactState = touchingOrCrossingEdge;
        if (touchingOrCrossingEdge && float.IsNaN(edgeContactTime))
        {
            edgeContactTime = Time.time;
            edgeContactBackendTimestamp = UDPManager.GetBackendUnixTimestamp();
        }

        // Edge contact is telemetry only. Support loss is recorded when the
        // unchanged physical fall predicate commits TriggerDeath.
    }

    private void CloseEdgeWarningEpisode()
    {
        if (!edgeWarningState) return;
        edgeWarningState = false;
        warningExitCount++;
        edgeWarningEndTime = Time.time;
        edgeWarningEndBackendTimestamp = UDPManager.GetBackendUnixTimestamp();
    }

    private void MarkSupportLost()
    {
        if (float.IsNaN(supportLostTime))
        {
            supportLostTime = Time.time;
            supportLostBackendTimestamp = UDPManager.GetBackendUnixTimestamp();
        }
    }

    private void GetPlatformBounds(Transform platform, out float outerRadius, out float platformTop)
    {
        outerRadius = 0f;
        platformTop = platform.position.y;
        if (cachedBoundsPlatform != platform || cachedPlatformColliders == null)
        {
            cachedBoundsPlatform = platform;
            cachedPlatformColliders = platform.GetComponentsInChildren<Collider>();
        }

        Vector3 center = platform.position;
        foreach (Collider platformCollider in cachedPlatformColliders)
        {
            if (!platformCollider.enabled || platformCollider.isTrigger || platformCollider.bounds.size.sqrMagnitude <= 0f)
            {
                continue;
            }

            Bounds bounds = platformCollider.bounds;
            float radiusX = Mathf.Abs(bounds.center.x - center.x) + bounds.extents.x;
            float radiusZ = Mathf.Abs(bounds.center.z - center.z) + bounds.extents.z;
            outerRadius = Mathf.Max(outerRadius, Mathf.Min(radiusX, radiusZ));
            platformTop = Mathf.Max(platformTop, bounds.max.y);
        }
    }

    void TriggerDeath(string logMessage)
    {
        if (isDead || hasWon || levelManager == null || !levelManager.IsRunRunning) return;
        Transform eventPlatform = levelManager.GetCurrentPlatformTransform();
            int eventLayer = levelManager.GetCurrentLayer();
            Collider eventBallCollider = GetComponent<Collider>();
            Vector3 eventBallCentre = transform.position;
            float eventLegacyRadius = diagnosticSupportBoundaryRadius + diagnosticPlayerRadius;
            float eventLegacyDirectionalDistance = eventLegacyRadius - diagnosticRadialDistance;
        UDPManager.CaptureDiagnosticTerminalEvent(
            "edge_exit_predicate_commit",
            eventPlatform,
            eventLayer,
            this,
            eventBallCollider,
            eventBallCentre,
            eventLegacyRadius,
            eventLegacyDirectionalDistance);
        isDead = true;
        layerTransitionBlocked = true;
        edgeContactState = true;
        MarkSupportLost();
        fallEventTime = Time.time;
        fallEventBackendTimestamp = UDPManager.GetBackendUnixTimestamp();
        Vector3 horizontalVelocity = rb != null ? new Vector3(rb.linearVelocity.x, 0f, rb.linearVelocity.z) : Vector3.zero;
        Vector2 radialOffset = levelManager != null && levelManager.GetCurrentPlatformTransform() != null
            ? new Vector2(transform.position.x - levelManager.GetCurrentPlatformTransform().position.x,
                transform.position.z - levelManager.GetCurrentPlatformTransform().position.z)
            : Vector2.zero;
        Vector2 radialDirection = radialOffset.sqrMagnitude > 0.0001f ? radialOffset.normalized : Vector2.zero;
        float radialVelocity = Vector2.Dot(new Vector2(horizontalVelocity.x, horizontalVelocity.z), radialDirection);
        fallDirection = radialVelocity > 0.05f ? "outward" : radialVelocity < -0.05f ? "inward" : "stationary";
        Debug.LogWarning(logMessage);
        if (levelManager != null && levelManager.MarkRunEnded("edge_exit"))
        {
            UDPManager.ReportFallEvent("fell_off_platform");
        }
        
        if (cam != null)
        {
            CameraController camScript = cam.GetComponent<CameraController>();
            if (camScript != null) camScript.target = null;
        }

        rb.useGravity = true;
        StartCoroutine(GameOverSequence());
    }

    IEnumerator GameOverSequence()
    {
        yield return new WaitForSeconds(1f);

        if (UIManager.Instance != null && levelManager != null)
        {
            Time.timeScale = 0f;
            UIManager.Instance.ShowGameOver(levelManager.GetPassedCount(), levelManager.currentLevel);
        }
    }

    public Vector3 GetTelemetryVelocity()
    {
        return rb != null ? rb.linearVelocity : Vector3.zero;
    }

    public float GetTelemetryBallRadius()
    {
        Collider playerCollider = GetComponent<Collider>();
        return playerCollider != null
            ? Mathf.Max(playerCollider.bounds.extents.x, playerCollider.bounds.extents.z)
            : float.NaN;
    }

    public bool EdgeWarningState => edgeWarningState;
    public bool EdgeContactState => edgeContactState;
    public bool IsDead => isDead;
    public bool HasWon => hasWon;
    public int WarningEpisodeId => warningEpisodeId;
    public int WarningEnterCount => warningEnterCount;
    public int WarningExitCount => warningExitCount;
    public float EdgeWarningTime => edgeWarningTime;
    public float EdgeWarningEndTime => edgeWarningEndTime;
    public float EdgeContactTime => edgeContactTime;
    public float SupportLostTime => supportLostTime;
    public float FallEventTime => fallEventTime;
    public double EdgeWarningBackendTimestamp => edgeWarningBackendTimestamp;
    public double EdgeWarningEndBackendTimestamp => edgeWarningEndBackendTimestamp;
    public double EdgeContactBackendTimestamp => edgeContactBackendTimestamp;
    public double SupportLostBackendTimestamp => supportLostBackendTimestamp;
    public double FallEventBackendTimestamp => fallEventBackendTimestamp;
    public string FallDirection => fallDirection;
    public float DiagnosticRadialDistance => diagnosticRadialDistance;
    public float DiagnosticPlayerRadius => diagnosticPlayerRadius;
    public float DiagnosticSupportBoundaryRadius => diagnosticSupportBoundaryRadius;
    public bool DiagnosticInsideHoleOpening => diagnosticInsideHoleOpening;
    public bool DiagnosticBeyondOuterEdge => diagnosticBeyondOuterEdge;
    public bool DiagnosticCrossedSupportBoundary => diagnosticCrossedSupportBoundary;
    public float DiagnosticWarningRadialDistance => diagnosticWarningRadialDistance;
    public float DiagnosticWarningPredicateRadius => diagnosticWarningPredicateRadius;
    public bool DiagnosticWarningNearEdge => diagnosticWarningNearEdge;
    public bool DiagnosticWarningStateBeforeTransition => diagnosticWarningStateBeforeTransition;
    public float DiagnosticWarningTransitionTime => diagnosticWarningTransitionTime;
    public double DiagnosticWarningTransitionBackendTimestamp => diagnosticWarningTransitionBackendTimestamp;
    public float DiagnosticEdgeContactRadialDistance => diagnosticEdgeContactRadialDistance;
    public float DiagnosticEdgeContactPredicateRadius => diagnosticEdgeContactPredicateRadius;
    public bool DiagnosticEdgeContactPredicateResult => diagnosticEdgeContactPredicateResult;
    public float DiagnosticEdgeContactTransitionTime => diagnosticEdgeContactTransitionTime;
    public double DiagnosticEdgeContactTransitionBackendTimestamp => diagnosticEdgeContactTransitionBackendTimestamp;
    public int DiagnosticSupportContactPlatformId => supportContactPlatformId;
    public float DiagnosticLastSupportContactFixedTime => lastSupportContactFixedTime;
    public bool HasExternalCop => externalCopReceived;
    public string SupportContactState
    {
        get
        {
            if (!float.IsNaN(supportLostTime)) return "SUPPORT_LOST";
            Transform platform = levelManager != null ? levelManager.GetCurrentPlatformTransform() : null;
            if (platform == null) return "UNKNOWN";
            int platformId = platform.gameObject.GetInstanceID();
            return supportContactPlatformId == platformId && !float.IsNaN(lastSupportContactFixedTime) &&
                   Time.fixedTime - lastSupportContactFixedTime <= Mathf.Max(Time.fixedDeltaTime * 2.5f, 0.05f)
                ? "CONTACT"
                : "NO_CONTACT";
        }
    }

    private void OnCollisionStay(Collision collision)
    {
        Transform platform = levelManager != null ? levelManager.GetCurrentPlatformTransform() : null;
        if (platform == null || (collision.transform != platform && !collision.transform.IsChildOf(platform)) ||
            transform.position.y < platform.position.y) return;
        supportContactPlatformId = platform.gameObject.GetInstanceID();
        lastSupportContactFixedTime = Time.fixedTime;
    }

    public bool IsBelowCurrentSupportHeight(out float supportHeight)
    {
        supportHeight = float.NaN;
        Transform platform = levelManager != null ? levelManager.GetCurrentPlatformTransform() : null;
        if (platform == null) return false;
        Collider[] colliders = platform.GetComponentsInChildren<Collider>();
        float top = platform.position.y;
        bool found = false;
        foreach (Collider platformCollider in colliders)
        {
            if (!platformCollider.enabled || platformCollider.isTrigger || platformCollider.bounds.size.sqrMagnitude <= 0f) continue;
            top = Mathf.Max(top, platformCollider.bounds.max.y);
            found = true;
        }
        if (!found) return false;
        supportHeight = top;
        return transform.position.y < top;
    }

    private bool IsOutsidePlatformEdge(
        Transform platform,
        Vector3 worldPosition,
        float playerRadius,
        float knownOuterRadius = 0f)
    {
        if (platform == null) return false;

        Vector2 offset = new Vector2(worldPosition.x - platform.position.x, worldPosition.z - platform.position.z);
        float radialDistance = offset.magnitude;
        float outerRadius = knownOuterRadius;
        if (levelManager != null)
        {
            Vector2 direction = radialDistance > 0.0001f ? offset / radialDistance : Vector2.right;
            if (levelManager.GetDirectionalPlatformOuterRadius(direction, out float queriedRadius, out _, out _) &&
                queriedRadius > 0f)
            {
                outerRadius = queriedRadius;
            }
        }

        // Missing support alone is insufficient: the aperture is also an intentional
        // support-free region. Only consider edge exit near the measured outer boundary.
        if (outerRadius <= 0f || radialDistance < outerRadius - playerRadius) return false;
        if (HasPlatformSurfaceUnderPoint(platform, worldPosition, playerRadius)) return false;
        if (IsWithinCurrentHoleOpening(worldPosition, playerRadius)) return false;
        return true;
    }

    private bool IsWithinCurrentHoleOpening(Vector3 worldPosition, float playerRadius)
    {
        if (levelManager == null ||
            !levelManager.TryGetCurrentHoleTelemetryGeometry(out Vector3 holeCentre, out float holeRadius) ||
            holeRadius <= 0f)
        {
            return false;
        }

        float holeDistance = new Vector2(worldPosition.x - holeCentre.x, worldPosition.z - holeCentre.z).magnitude;
        return holeDistance <= holeRadius + playerRadius;
    }

    private bool IsInsideCurrentHole(Vector3 worldPosition, float playerRadius)
    {
        if (levelManager == null ||
            !levelManager.TryGetCurrentHoleTelemetryGeometry(out Vector3 holeCentre, out float holeRadius) ||
            holeRadius <= playerRadius)
        {
            return false;
        }

        float holeDistance = new Vector2(worldPosition.x - holeCentre.x, worldPosition.z - holeCentre.z).magnitude;
        return holeDistance <= holeRadius - playerRadius;
    }

    private static bool HasPlatformSurfaceUnderPoint(Transform platform, Vector3 worldPosition, float playerRadius)
    {
        Collider[] colliders = platform.GetComponentsInChildren<Collider>(true);
        float minY = float.PositiveInfinity;
        float maxY = float.NegativeInfinity;
        for (int i = 0; i < colliders.Length; i++)
        {
            Collider collider = colliders[i];
            if (collider == null || !collider.enabled || !collider.gameObject.activeInHierarchy ||
                collider.isTrigger || collider.bounds.size.sqrMagnitude <= 0f)
            {
                continue;
            }

            minY = Mathf.Min(minY, collider.bounds.min.y);
            maxY = Mathf.Max(maxY, collider.bounds.max.y);
        }

        if (float.IsInfinity(minY) || float.IsInfinity(maxY)) return false;
        Ray ray = new Ray(new Vector3(worldPosition.x, maxY + 0.25f, worldPosition.z), Vector3.down);
        Vector2 offset = new Vector2(worldPosition.x - platform.position.x, worldPosition.z - platform.position.z);
        float distance = offset.magnitude;
        Vector2 direction = distance > 0.0001f ? offset / distance : Vector2.right;
        float rayDistance = maxY - minY + 0.5f;
        for (int i = 0; i < colliders.Length; i++)
        {
            Collider collider = colliders[i];
            if (collider == null || !collider.enabled || !collider.gameObject.activeInHierarchy || collider.isTrigger)
                continue;

            if (collider.Raycast(ray, out _, rayDistance)) return true;
            // Raycast checks the centre point; also check just inside the ball's
            // outer footprint so a sphere that still overlaps a rim does not exit.
            if (distance > 0.0001f && playerRadius > 0f)
            {
                Vector3 inset = new Vector3(-direction.x * playerRadius * 0.9f, 0f,
                    -direction.y * playerRadius * 0.9f);
                Ray footprintRay = new Ray(new Vector3(worldPosition.x + inset.x, maxY + 0.25f,
                    worldPosition.z + inset.z), Vector3.down);
                if (collider.Raycast(footprintRay, out _, rayDistance)) return true;
            }
        }
        return false;
    }

    public bool IsOutsideCurrentPlatformEdge()
    {
        if (levelManager == null || isDead || hasWon) return false;
        Transform platform = levelManager.GetCurrentPlatformTransform();
        if (platform == null) return false;

        Collider playerCollider = GetComponent<Collider>();
        float playerRadius = playerCollider != null
            ? Mathf.Max(playerCollider.bounds.extents.x, playerCollider.bounds.extents.z)
            : 0.5f;
        GetPlatformBounds(platform, out float outerRadius, out _);
        return IsOutsidePlatformEdge(platform, transform.position, playerRadius, outerRadius);
    }

    public void CommitEdgeExit(string reason)
    {
        if (!isDead && !hasWon) TriggerDeath(reason);
    }

    public bool CanAdvanceLayer => !isDead && !hasWon && !layerTransitionBlocked && float.IsNaN(supportLostTime);
    public bool LayerTransitionBlocked => layerTransitionBlocked;
    public void SetLayerTransitionBlocked(bool value) => layerTransitionBlocked = value;

    public void ClearWarningForNormalCompletion()
    {
        CloseEdgeWarningEpisode();
        edgeContactState = false;
    }

    public void OnRunEnded(bool realFall)
    {
        CloseEdgeWarningEpisode();
        if (realFall)
        {
            layerTransitionBlocked = true;
        }
        edgeContactState = realFall;
    }

    public Vector2 ExternalCop => externalWbbData;

    public void TriggerWin()
    {
        if (hasWon || isDead || levelManager == null || !levelManager.IsRunRunning) return;
        hasWon = true;
        ClearWarningForNormalCompletion();
        if (levelManager != null && levelManager.MarkRunEnded(levelManager.GetCompletionOutcome()))
        {
            UDPManager.ReportRunEnded();
        }
        rb.linearVelocity = Vector3.zero;
        Time.timeScale = 0f;
        if (UIManager.Instance != null && levelManager != null)
        {
            int displayDifficulty = Mathf.Clamp(levelManager.currentLevel, 1, 5);
            UIManager.Instance.ShowGameOver(levelManager.GetPassedCount(), displayDifficulty, true);
        }
    }
}