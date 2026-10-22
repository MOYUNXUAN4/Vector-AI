using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Sends the current Endless Falling game state to the local UDP telemetry listener.
/// </summary>
public class UDPManager : MonoBehaviour
{
    public static UDPManager Instance { get; private set; }
    public UnityGameTelemetry LastTelemetry { get; private set; }

    [Header("UDP Telemetry")]
    public string pythonIP = "127.0.0.1";
    public int sendPort = 5005;

    [Header("Performance")]
    [Tooltip("Game-state packets sent per second.")]
    [Min(1f)] public float sendRate = 60f;

    [Header("References")]
    public EndlessPlayerController player;
    public LevelManager levelManager;

    [Header("Response Experiment")]
    public string responseExperimentId = "response_experiment";
    public string responseCondition = "two_level";
    public string trialScenario = "normal";
    public bool trialValid = true;

    [Header("Geometry Diagnostics (local JSONL; not sent over UDP)")]
    public bool enableGeometryDiagnostics = true;
    [Min(0.25f)] public float geometryDiagnosticSampleInterval = 0.5f;
    [Range(16, 256)] public int geometryBoundaryScanSamples = 64;
    [Range(4, 16)] public int geometryBoundaryRefinementSteps = 8;

    [Header("High-Frequency Lightweight Diagnostics (local JSONL only)")]
    [Tooltip("Short functional acceptance only. Records lightweight local samples; does not change gameplay or UDP payloads.")]
    public bool enableHighFrequencyLightDiagnostics = false;
    [Min(0.01f)] public float highFrequencyLightSampleInterval = 0.05f;

    [Tooltip("Additional world-space allowance around the target hole for suppressing ATTENTION. Telemetry only.")]
    [Min(0f)] public float holeApproachSafetyMargin = 0.35f;
    [Tooltip("Additional world-space distance required to leave the hole approach range after entering it. Telemetry only.")]
    [Min(0f)] public float holeApproachExitHysteresis = 0.15f;

    [Header("Event / Fixed Full Geometry Diagnostics (local only)")]
    [Tooltip("Records immediate event metadata and, when allowed, a complete local geometry snapshot. Does not affect gameplay or UDP.")]
    public bool enableEventDrivenFullGeometryDiagnostics = false;

    [Tooltip("Runs complete local geometry queries at a fixed cadence for short diagnostic control runs.")]
    public bool enableFixedCadenceFullGeometryDiagnostics = false;
    [Min(0.01f)] public float eventDrivenFullGeometryMinInterval = 0.10f;
    [Min(0.05f)] public float fixedFullGeometrySampleInterval = 0.25f;
    [Min(0.01f)] public float fullGeometryBudgetMilliseconds = 1.0f;

    private float nextFixedFullGeometryTime;
    private float lastTriggeredFullGeometryQueryTime = float.NaN;
    private long fullGeometryEventId;

    private float nextSendTime;
    private float sendInterval;
    private float nextErrorLogTime;
    private long sequence;
    private bool finalTelemetrySent;
    private bool isReady;
    private Vector2 previousBallPosition;
    private float previousBallTime = float.NaN;
    private Vector2 previousCopPosition;
    private float previousCopTime = float.NaN;
    private UdpClient udpSender;
    private IPEndPoint telemetryEndPoint;
    private readonly Queue<float> predictionSampleTimes = new Queue<float>();
    private readonly Queue<float> predictionRadialVelocities = new Queue<float>();
    private int previousPredictionPlatformInstanceId = int.MinValue;
    private int previousPredictionPassedCount = int.MinValue;
    private bool holeApproachLatched;
    private string responseTrialId = string.Empty;
    private bool responseTrialInitialized;
    private string activeResponseExperimentId = string.Empty;
    private string activeResponseCondition = string.Empty;
    private string activeTrialScenario = string.Empty;
    private string activeRunId = string.Empty;
    private bool activeTrialValid;
    private int attentionEpisodeId;
    private bool attentionEpisodeActive;
    private float attentionEpisodeEnterTime = float.NaN;
    private float attentionEpisodeExitTime = float.NaN;
    private float attentionEpisodeStartTime = float.NaN;
    private float attentionEpisodeEndTime = float.NaN;
    private double attentionEpisodeEnterBackendTimestamp = double.NaN;
    private double attentionEpisodeExitBackendTimestamp = double.NaN;
    private double attentionEpisodeStartBackendTimestamp = double.NaN;
    private double attentionEpisodeEndBackendTimestamp = double.NaN;
    private EndlessFallingGeometryDiagnostics geometryDiagnostics;
    private bool geometryDiagnosticsErrorLogged;
    private string lastSerializedTelemetry = string.Empty;
    private long lastSerializedSequence;
    private float nextLightDiagnosticTime;
    private float lastLightDiagnosticTime = float.NaN;
    private long lastLightDiagnosticUdpSequence;
    private bool lastUdpSendCallCompleted;
    private int previousFullSupportPlatformId = int.MinValue;
    private bool previousFullWarningState;
    private bool previousFullAttentionState;
    private bool fullDiagnosticStateInitialized;

    [Serializable]
    public class UnityGameTelemetry
    {
        // Backward-compatible fields from the original Endless Falling UDP payload.
        public string command;
        public float time;
        public float copX;
        public float copZ;
        public float targetX;
        public float targetZ;
        public int passedCount;

        // Added game-state telemetry fields. No Wii sensor fields are included.
        public string type;
        public string source;
        public long sequence;
        public double timestamp;
        public int platformLevel;
        public float distanceToHole;
        public float platformTilt;
        public int difficulty;
        public bool fallEvent;
        public string fallReason;

        // Unity-side geometry, motion, edge and event telemetry. Distances are world units;
        // velocities are world units per second; times are Unity Time.time seconds.
        public double backend_timestamp;
        public float platform_center_x;
        public float platform_center_z;
        public float platform_radius;
        public float platform_scale;
        public int geometry_platform_instance_id;
        public string geometry_version_id;
        public float geometry_source_timestamp;
        public bool geometry_query_valid;
        public bool geometry_ownership_valid;
        public int geometry_active_platform_instance_id;
        public string geometry_active_version_id;
        public float platform_root_lossy_scale_x;
        public float platform_root_lossy_scale_y;
        public float platform_root_lossy_scale_z;
        public float platform_collider_lossy_scale_x;
        public float platform_collider_lossy_scale_y;
        public float platform_collider_lossy_scale_z;
        public string platform_radius_source;
        public int platform_difficulty;
        public float ball_pos_x;
        public float ball_pos_z;
        public float ball_velocity_x;
        public float ball_velocity_z;
        public float ball_radial_distance;
        public float ball_radial_velocity;
        public float nearest_edge_direction_x;
        public float nearest_edge_direction_z;
        public float target_edge_direction_x;
        public float target_edge_direction_z;
        public float target_edge_distance;
        public float target_edge_radial_velocity;
        public float directional_edge_distance;
        public float directional_edge_point_x;
        public float directional_edge_point_z;
        public bool directional_edge_valid;
        public float ball_radius;
        public float edge_warning_margin;
        public float edge_warning_radius;
        public float edge_warning_distance_threshold;
        public float ball_position_velocity_x;
        public float ball_position_velocity_z;
        public float cop_velocity_x;
        public float cop_velocity_z;
        public float cop_speed;
        public string fall_direction;
        public bool edge_warning_state;
        public bool edge_contact_state;
        public float edge_contact_time;
        public float support_lost_time;
        public float fall_event_time;
        public double edge_warning_backend_timestamp;
        public double edge_contact_backend_timestamp;
        public double support_lost_backend_timestamp;
        public double fall_event_backend_timestamp;
        public int active_platform_id;
        public string support_contact_state;
        public bool ball_below_support_height;
        public float support_height;
        public bool layer_transition_blocked;
        public int warning_episode_id;
        public int warning_enter_count;
        public int warning_exit_count;
        public float edge_warning_time;
        public string run_id;
        public double run_start_backend_timestamp;
        public string run_state;
        public string session_outcome;
        public double session_end_backend_timestamp;
        public int commanded_difficulty;
        public int active_platform_difficulty;
        public int passed_count;
        public bool fall_event;
        public string fall_reason;
        public bool calibration_mode;
        public int selected_session_layers;
        public string selected_difficulty;
        public bool attention_state;
        public string prediction_state;
        public float target_hole_distance;
        public float target_hole_radius;
        public float target_hole_approach_velocity;
        public bool moving_toward_target_hole;
        public string hole_approach_state;
        public string response_experiment_id;
        public string response_condition;
        public string trial_scenario;
        public bool trial_valid;
        public string response_trial_id;
        public int response_layer_id;
        public string warning_source;
        public string warning_type;
        public bool warning_active;
        public string visible_warning_state;
        public float warning_episode_start_time;
        public double warning_episode_start_backend_timestamp;
        public float warning_episode_end_time;
        public double warning_episode_end_backend_timestamp;
        public int attention_episode_id;
        public float attention_episode_enter_time;
        public float attention_episode_exit_time;
        public float attention_episode_start_time;
        public float attention_episode_end_time;
        public double attention_episode_enter_backend_timestamp;
        public double attention_episode_exit_backend_timestamp;
        public double attention_episode_start_backend_timestamp;
        public double attention_episode_end_backend_timestamp;
    }

    public static double GetBackendUnixTimestamp()
    {
        return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
    }

    private void Awake()
    {
        // Take ownership before any Start/Update callback can expose the previous
        // scene instance or its terminal telemetry after Restart.
        Instance = this;
        LastTelemetry = null;
        NormalizeResponseExperimentSettings();
    }

    private void NormalizeResponseExperimentSettings()
    {
        if (string.IsNullOrEmpty(responseExperimentId)) responseExperimentId = "response_experiment";
        if (string.IsNullOrEmpty(responseCondition)) responseCondition = "two_level";
        if (responseCondition != "two_level") responseCondition = "two_level";
        if (trialScenario != "normal" && trialScenario != "recovery" && trialScenario != "forced_exit")
        {
            trialScenario = "normal";
        }
    }

    private void Start()
    {
        sendInterval = 1f / Mathf.Max(1f, sendRate);

        if (player == null) player = FindObjectOfType<EndlessPlayerController>();
        if (levelManager == null) levelManager = FindObjectOfType<LevelManager>();
        if (player == null || levelManager == null)
        {
            Debug.LogError("[GameTelemetry] Disabled: missing EndlessPlayerController or LevelManager reference.");
            enabled = false;
            return;
        }

        try
        {
            telemetryEndPoint = new IPEndPoint(IPAddress.Parse(pythonIP), sendPort);
            udpSender = new UdpClient();
            udpSender.Client.Blocking = false;
            isReady = true;
            Debug.Log($"[GameTelemetry] Sending to {pythonIP}:{sendPort} at {sendRate:0.#} Hz.");
            if (enableGeometryDiagnostics)
            {
                try
                {
                    geometryDiagnostics = new EndlessFallingGeometryDiagnostics(
                        geometryDiagnosticSampleInterval,
                        geometryBoundaryScanSamples,
                        geometryBoundaryRefinementSteps);
                    geometryDiagnostics.ConfigureFullGeometryEventScheduling(
                        eventDrivenFullGeometryMinInterval, fullGeometryBudgetMilliseconds);
                    Debug.Log($"[GameTelemetry] Geometry diagnostics: schema={EndlessFallingGeometryDiagnostics.SchemaVersion}, " +
                              $"samples={geometryDiagnostics.SampleLogPath}, geometry={geometryDiagnostics.GeometryLogPath}, " +
                              $"interval={Mathf.Max(0.25f, geometryDiagnosticSampleInterval):0.###}s.");
                }
                catch (Exception exception)
                {
                    Debug.LogWarning($"[GameTelemetry] Geometry diagnostics disabled: {exception.Message}");
                    geometryDiagnostics = null;
                }
            }
        }
        catch (Exception exception)
        {
            Debug.LogError($"[GameTelemetry] Disabled: could not initialize UDP sender: {exception.Message}");
            enabled = false;
        }
    }

    private void Update()
    {
        if (!isReady || finalTelemetrySent || levelManager == null || !levelManager.IsRunRunning) return;

        if (enableHighFrequencyLightDiagnostics && !levelManager.IsCalibrationStage)
        {
            RecordLightweightDiagnosticSample();
        }

        if (enableFixedCadenceFullGeometryDiagnostics && !levelManager.IsCalibrationStage &&
            Time.time >= nextFixedFullGeometryTime)
        {
            nextFixedFullGeometryTime = Time.time + Mathf.Max(0.05f, fixedFullGeometrySampleInterval);
            RecordFullGeometryDiagnostic("fixed_cadence", "fixed_cadence", Time.time);
        }

        if (enableEventDrivenFullGeometryDiagnostics && geometryDiagnostics != null &&
            !levelManager.IsCalibrationStage && player != null)
        {
            Transform deferredPlatform = levelManager.GetCurrentPlatformTransform();
            Vector3 deferredCentre = player.transform.position;
            Vector3 deferredPlatformCentre = deferredPlatform != null ? deferredPlatform.position : Vector3.zero;
            Vector2 deferredOffset = new Vector2(deferredCentre.x - deferredPlatformCentre.x, deferredCentre.z - deferredPlatformCentre.z);
            float deferredRadial = deferredOffset.magnitude;
            geometryDiagnostics.ProcessDeferredFullGeometryEvents(
                deferredPlatform, levelManager.GetCurrentLayer(), player.GetComponent<Collider>(), deferredCentre,
                player.DiagnosticWarningPredicateRadius + player.GetTelemetryBallRadius(),
                "deferred_event_directional_observation", deferredPlatformCentre,
                deferredRadial > 0.0001f ? deferredOffset / deferredRadial : Vector2.right,
                deferredRadial, player.DiagnosticWarningPredicateRadius - deferredRadial,
                player.GetTelemetryBallRadius(), player, GetBackendUnixTimestamp(), levelManager.RunId, string.Empty);
        }

        if (Time.unscaledTime < nextSendTime) return;

        SendTelemetry(false, string.Empty);

        // Preserve the 60 Hz phase when frames are fast enough, but skip every missed
        // interval after a slow frame instead of sending catch-up packets.
        nextSendTime += sendInterval;
        if (nextSendTime <= Time.unscaledTime)
        {
            float missedIntervals = Mathf.Floor((Time.unscaledTime - nextSendTime) / sendInterval) + 1f;
            nextSendTime += missedIntervals * sendInterval;
        }
    }

    /// <summary>
    /// Sends the terminal edge-exit packet synchronously and exactly once.
    /// LevelManager must already be in Ended state so the packet contains the final run metadata.
    /// </summary>
    public static void ReportFallEvent(string reason)
    {
        if (Instance == null) return;
        Instance.SendFinalTelemetry(true, reason);
    }

    public static void ReportRunEnded()
    {
        if (Instance == null) return;
        Instance.SendFinalTelemetry(false, string.Empty);
    }

    public static void RecordRestartAborted()
    {
        if (Instance == null || Instance.geometryDiagnostics == null) return;
        string runId = Instance.levelManager != null ? Instance.levelManager.RunId : string.Empty;
        Instance.geometryDiagnostics.RecordLifecycleEvent(
            "restart_aborted", runId,
            Instance.levelManager != null ? Instance.levelManager.RunStateTelemetry : "unknown",
            Instance.levelManager != null ? Instance.levelManager.SessionOutcome : string.Empty,
            Instance.sequence, "active_run_restart_request_no_terminal_outcome");
    }

    public static void RecordNewRunCreated(string runId)
    {
        if (Instance == null || Instance.geometryDiagnostics == null) return;
        Instance.geometryDiagnostics.SetRunContext(runId);
        Instance.geometryDiagnostics.RecordLifecycleEvent(
            "new_run_created", runId, "running", string.Empty,
            Instance.sequence, "new_guid_run_started");
    }

    public static void RecordRestartRequested(string runId, string detail)
    {
        if (Instance == null || Instance.geometryDiagnostics == null) return;
        Instance.geometryDiagnostics.RecordLifecycleEvent(
            "restart_requested", runId, "ended", string.Empty,
            Instance.sequence, detail);
    }

    private void SendFinalTelemetry(bool fallEvent, string fallReason)
    {
        if (!isReady || levelManager == null || levelManager.RunState != LevelManager.GameRunState.Ended)
        {
            return;
        }
        if (finalTelemetrySent)
        {
            geometryDiagnostics?.RecordLifecycleEvent(
                "terminal_send_duplicate_blocked", levelManager.RunId,
                levelManager.RunStateTelemetry, levelManager.SessionOutcome,
                sequence, "final_telemetry_already_sent", true, lastSerializedTelemetry);
            return;
        }

        finalTelemetrySent = true;
        geometryDiagnostics?.SetTerminalRunContext(levelManager.RunId, levelManager.SessionOutcome, sequence + 1);
        geometryDiagnostics?.RecordLifecycleEvent(
            "terminal_snapshot_frozen", levelManager.RunId,
            levelManager.RunStateTelemetry, levelManager.SessionOutcome,
            sequence + 1, fallEvent ? "edge_exit_terminal_snapshot" : "normal_completion_terminal_snapshot");
        if (enableEventDrivenFullGeometryDiagnostics && player != null)
        {
            RecordFullGeometryDiagnostic("event", "terminal_snapshot_frozen", Time.time);
        }
        SendTelemetry(fallEvent, fallReason);
        geometryDiagnostics?.RecordLifecycleEvent(
            lastUdpSendCallCompleted ? "terminal_udp_send_call_completed" : "terminal_udp_send_call_failed",
            levelManager.RunId, levelManager.RunStateTelemetry, levelManager.SessionOutcome,
            lastSerializedSequence,
            lastUdpSendCallCompleted ? "UdpClient.Send_returned" : "UdpClient.Send_did_not_complete",
            false, lastSerializedTelemetry);
        geometryDiagnostics?.Flush();
    }

    private void RecordLightweightDiagnosticSample()
    {
        if (geometryDiagnostics == null || LastTelemetry == null || player == null || levelManager == null) return;
        float now = Time.time;
        if (now < nextLightDiagnosticTime) return;
        float targetInterval = Mathf.Max(0.01f, highFrequencyLightSampleInterval);
        nextLightDiagnosticTime = now + targetInterval;
        try
        {
            geometryDiagnostics.TryRecordLightweightSample(
                LastTelemetry,
                levelManager.GetCurrentPlatformTransform(),
                player,
                now,
                targetInterval,
                lastLightDiagnosticTime,
                lastLightDiagnosticUdpSequence);
            lastLightDiagnosticTime = now;
            lastLightDiagnosticUdpSequence = LastTelemetry.sequence;
        }
        catch (Exception exception)
        {
            if (Time.unscaledTime >= nextErrorLogTime)
            {
                Debug.LogWarning($"[GameTelemetry] Lightweight diagnostics skipped: {exception.Message}");
                nextErrorLogTime = Time.unscaledTime + 5f;
            }
        }
    }

    private void SendTelemetry(bool fallEvent, string fallReason)
    {
        if (!isReady) return;

        try
        {
            lastUdpSendCallCompleted = false;
            bool hasTargetHole = levelManager.TryGetCurrentHoleTelemetryGeometry(
                out Vector3 holePosition, out float targetHoleRadius);
            if (!hasTargetHole) holePosition = Vector3.one * float.NaN;
            Transform currentPlatform = levelManager.GetCurrentPlatformTransform();
            // Signed X rotation: positive means the platform's local +Z edge slopes down;
            // negative means that edge slopes up. This is the platform's front/back tilt.
            float platformTilt = currentPlatform != null
                ? Mathf.DeltaAngle(0f, currentPlatform.eulerAngles.x)
                : 0f;

            int passedCount = levelManager.GetPassedCount();
            EnsureResponseTrialContext();
            Vector3 ballPosition = player.transform.position;
            Vector3 ballVelocity = player.GetTelemetryVelocity();
            float unityTime = Time.time;
            double backendTimestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            float ballPositionVelocityX = float.NaN;
            float ballPositionVelocityZ = float.NaN;
            if (!float.IsNaN(previousBallTime) && unityTime > previousBallTime)
            {
                float dt = unityTime - previousBallTime;
                ballPositionVelocityX = (ballPosition.x - previousBallPosition.x) / dt;
                ballPositionVelocityZ = (ballPosition.z - previousBallPosition.y) / dt;
            }
            previousBallPosition = new Vector2(ballPosition.x, ballPosition.z);
            previousBallTime = unityTime;

            float copX = player.HasExternalCop ? player.ExternalCop.x : float.NaN;
            float copZ = player.HasExternalCop ? player.ExternalCop.y : float.NaN;
            float copVelocityX = float.NaN;
            float copVelocityZ = float.NaN;
            if (!float.IsNaN(previousCopTime) && unityTime > previousCopTime && !float.IsNaN(copX) && !float.IsNaN(copZ))
            {
                float dt = unityTime - previousCopTime;
                copVelocityX = (copX - previousCopPosition.x) / dt;
                copVelocityZ = (copZ - previousCopPosition.y) / dt;
            }
            if (!float.IsNaN(copX) && !float.IsNaN(copZ))
            {
                previousCopPosition = new Vector2(copX, copZ);
                previousCopTime = unityTime;
            }

            Vector3 platformCenter = currentPlatform != null ? currentPlatform.position : Vector3.zero;
            float platformRadius = float.NaN;
            float platformScale = float.NaN;
            Vector3 colliderScale = Vector3.one * float.NaN;
            string radiusSource = string.Empty;
            Vector3 edgePoint = Vector3.one * float.NaN;
            Vector2 radialOffset = currentPlatform != null
                ? new Vector2(ballPosition.x - platformCenter.x, ballPosition.z - platformCenter.z)
                : Vector2.zero;
            float radialDistance = currentPlatform != null ? radialOffset.magnitude : float.NaN;
            Vector2 edgeDirection = radialDistance > 0.0001f ? radialOffset.normalized : Vector2.right;
            bool geometryOwnershipValid = false;
            int geometryPlatformInstanceId = 0;
            string geometryVersionId = string.Empty;
            float geometrySourceTimestamp = float.NaN;
            int activeGeometryPlatformInstanceId = 0;
            string activeGeometryVersionId = string.Empty;
            bool geometryQueryValid;
            int queriedActiveGeometryPlatformInstanceId;
            string queriedActiveGeometryVersionId;
            bool hasGeometry = levelManager.GetCurrentPlatformTelemetryGeometryIdentity(
                ballPosition,
                out geometryPlatformInstanceId, out geometryVersionId, out geometrySourceTimestamp,
                out geometryQueryValid, out geometryOwnershipValid,
                out platformCenter, out platformRadius, out platformScale, out _,
                out colliderScale, out radiusSource, out edgePoint,
                out queriedActiveGeometryPlatformInstanceId, out queriedActiveGeometryVersionId);
            activeGeometryPlatformInstanceId = queriedActiveGeometryPlatformInstanceId;
            activeGeometryVersionId = queriedActiveGeometryVersionId;
            geometryDiagnostics?.SetOrdinaryGeometryAssociation(
                geometryPlatformInstanceId, activeGeometryPlatformInstanceId,
                geometryVersionId, activeGeometryVersionId,
                geometrySourceTimestamp, geometryQueryValid, geometryOwnershipValid, unityTime);
            int platformInstanceId = geometryPlatformInstanceId;
            bool predictionContextChanged = platformInstanceId != previousPredictionPlatformInstanceId ||
                                            passedCount != previousPredictionPassedCount;
            if (predictionContextChanged)
            {
                predictionSampleTimes.Clear();
                predictionRadialVelocities.Clear();
                holeApproachLatched = false;
                previousPredictionPlatformInstanceId = platformInstanceId;
                previousPredictionPassedCount = passedCount;
            }
            if (!geometryOwnershipValid)
            {
                geometryPlatformInstanceId = 0;
                geometryVersionId = string.Empty;
                geometrySourceTimestamp = float.NaN;
            }
            bool geometryBelongsToPacketPlatform = geometryOwnershipValid &&
                platformInstanceId == activeGeometryPlatformInstanceId &&
                string.Equals(geometryVersionId, activeGeometryVersionId, StringComparison.Ordinal);
            hasGeometry = hasGeometry && geometryQueryValid && geometryBelongsToPacketPlatform;
            Vector2 outwardDirection = radialDistance > 0.0001f ? radialOffset / radialDistance : Vector2.zero;
            float radialVelocity = hasGeometry
                ? Vector2.Dot(new Vector2(ballVelocity.x, ballVelocity.z), outwardDirection)
                : float.NaN;
            float targetEdgeDistance = hasGeometry ? platformRadius - radialDistance : float.NaN;
            float targetEdgeRadialVelocity = hasGeometry ? radialVelocity : float.NaN;
            float warningDistanceThreshold = player.GetTelemetryBallRadius() * 2f;
            bool edgeContact = hasGeometry && targetEdgeDistance <= 0f;
            bool edgeWarning = hasGeometry && (player.EdgeWarningState || targetEdgeDistance <= warningDistanceThreshold);
            bool ballBelowSupportHeight = player.IsBelowCurrentSupportHeight(out float supportHeight);

            Vector2 holeOffset = hasTargetHole
                ? new Vector2(holePosition.x - ballPosition.x, holePosition.z - ballPosition.z)
                : Vector2.zero;
            float targetHoleDistance = hasTargetHole ? holeOffset.magnitude : float.NaN;
            Vector2 holeDirection = targetHoleDistance > 0.0001f ? holeOffset / targetHoleDistance : Vector2.zero;
            float targetHoleApproachVelocity = hasTargetHole
                ? Vector2.Dot(new Vector2(ballVelocity.x, ballVelocity.z), holeDirection)
                : float.NaN;
            float ballRadius = player.GetTelemetryBallRadius();
            float holeApproachRadius = hasTargetHole && !float.IsNaN(ballRadius)
                ? targetHoleRadius + ballRadius + holeApproachSafetyMargin
                : float.NaN;
            float holeApproachExitRadius = !float.IsNaN(holeApproachRadius)
                ? holeApproachRadius + holeApproachExitHysteresis
                : float.NaN;
            bool inHoleApproachRange = hasTargetHole && !float.IsNaN(holeApproachRadius) &&
                                       targetHoleDistance <= (holeApproachLatched ? holeApproachExitRadius : holeApproachRadius);
            if (!hasTargetHole || float.IsNaN(targetHoleDistance)) holeApproachLatched = false;
            else if (inHoleApproachRange) holeApproachLatched = true;
            else if (!float.IsNaN(holeApproachExitRadius) && targetHoleDistance > holeApproachExitRadius) holeApproachLatched = false;
            bool movingTowardTargetHole = holeApproachLatched && targetHoleApproachVelocity > 0f;
            bool atHole = hasTargetHole && !float.IsNaN(ballRadius) &&
                          targetHoleDistance <= targetHoleRadius + ballRadius;
            string holeApproachState = !hasTargetHole || float.IsNaN(targetHoleDistance) ||
                                       float.IsNaN(targetHoleRadius) || float.IsNaN(targetHoleApproachVelocity)
                ? "GEOMETRY_UNKNOWN"
                : atHole ? "AT_HOLE"
                : movingTowardTargetHole ? "APPROACHING_HOLE"
                : targetHoleApproachVelocity < 0f ? "MOVING_AWAY_FROM_HOLE"
                : "NONE";
            bool suppressAttentionForHole = movingTowardTargetHole || atHole;

            bool attentionState = UpdateAttentionState(
                hasGeometry, targetEdgeDistance, warningDistanceThreshold,
                targetEdgeRadialVelocity, edgeWarning, edgeContact,
                suppressAttentionForHole, predictionContextChanged, unityTime);
            bool normalCompletion = levelManager.RunState == LevelManager.GameRunState.Ended &&
                                    levelManager.SessionOutcome == "calibration_completed";
            bool terminalFall = levelManager.RunState == LevelManager.GameRunState.Ended &&
                                levelManager.SessionOutcome == "edge_exit";
            if (normalCompletion || terminalFall) attentionState = false;
            string predictionState = !hasGeometry ? "GEOMETRY UNKNOWN"
                : terminalFall ? "FALL"
                : edgeContact ? "EDGE CONTACT"
                : edgeWarning ? "EDGE WARNING"
                : attentionState ? "ATTENTION"
                : "SAFE";
            if (normalCompletion) predictionState = "SAFE";
            UpdateAttentionEpisode(attentionState, unityTime, backendTimestamp, predictionContextChanged);
            bool attentionChanged = fullDiagnosticStateInitialized && attentionState != previousFullAttentionState;
            bool warningChanged = fullDiagnosticStateInitialized && player.EdgeWarningState != previousFullWarningState;
            bool supportChanged = fullDiagnosticStateInitialized && player.DiagnosticSupportContactPlatformId != previousFullSupportPlatformId;
            previousFullAttentionState = attentionState;
            previousFullWarningState = player.EdgeWarningState;
            previousFullSupportPlatformId = player.DiagnosticSupportContactPlatformId;
            fullDiagnosticStateInitialized = true;
            if (enableEventDrivenFullGeometryDiagnostics)
            {
                if (attentionChanged) RecordFullGeometryDiagnostic("event", attentionState ? "attention_enter" : "attention_exit", unityTime);
                if (warningChanged) RecordFullGeometryDiagnostic("event", player.EdgeWarningState ? "edge_warning_enter" : "edge_warning_exit", unityTime);
                if (supportChanged) RecordFullGeometryDiagnostic("event", "support_changed", unityTime);
            }
            string visibleWarningState = terminalFall ? "FALL"
                : edgeContact ? "EDGE_CONTACT"
                : edgeWarning ? "EDGE_WARNING"
                : attentionState ? "ATTENTION"
                : "SAFE";
            string warningType = visibleWarningState == "ATTENTION" ? "ATTENTION"
                : visibleWarningState == "EDGE_WARNING" ? "STRONG"
                : visibleWarningState == "EDGE_CONTACT" ? "EDGE_CONTACT"
                : visibleWarningState == "FALL" ? "FALL" : string.Empty;
            string warningSource = visibleWarningState == "ATTENTION" ? "unity_attention_rule"
                : visibleWarningState == "EDGE_WARNING" ? "unity_edge_geometry" : string.Empty;
            bool warningActive = visibleWarningState == "ATTENTION" || visibleWarningState == "EDGE_WARNING";

            int geometryPlatformIdForPacket = geometryPlatformInstanceId;
            bool geometryOwnershipValidForPacket = geometryOwnershipValid;
            if (!geometryOwnershipValidForPacket)
            {
                geometryPlatformIdForPacket = 0;
                geometryVersionId = string.Empty;
            }
            UnityGameTelemetry data = new UnityGameTelemetry
            {
                // Original protocol fields retain their original source and meaning.
                command = "realtime",
                time = unityTime,
                copX = copX,
                copZ = copZ,
                targetX = holePosition.x,
                targetZ = holePosition.z,
                passedCount = passedCount,

                // New fields are appended to the same JSON packet.
                type = "unity_game",
                source = "unity",
                sequence = ++sequence,
                timestamp = backendTimestamp,
                platformLevel = levelManager.GetCurrentLayer(),
                distanceToHole = hasTargetHole
                    ? new Vector2(ballPosition.x - holePosition.x, ballPosition.z - holePosition.z).magnitude
                    : float.NaN,
                platformTilt = platformTilt,
                difficulty = levelManager.currentLevel,
                fallEvent = fallEvent,
                fallReason = fallEvent ? fallReason : string.Empty,

                backend_timestamp = backendTimestamp,
                platform_center_x = hasGeometry ? platformCenter.x : float.NaN,
                platform_center_z = hasGeometry ? platformCenter.z : float.NaN,
                platform_radius = platformRadius,
                platform_scale = platformScale,
                geometry_platform_instance_id = geometryPlatformIdForPacket,
                geometry_version_id = geometryVersionId,
                geometry_source_timestamp = geometrySourceTimestamp,
                geometry_query_valid = geometryQueryValid,
                geometry_ownership_valid = geometryOwnershipValidForPacket,
                geometry_active_platform_instance_id = activeGeometryPlatformInstanceId,
                geometry_active_version_id = activeGeometryVersionId,
                platform_root_lossy_scale_x = hasGeometry ? currentPlatform.lossyScale.x : float.NaN,
                platform_root_lossy_scale_y = hasGeometry ? currentPlatform.lossyScale.y : float.NaN,
                platform_root_lossy_scale_z = hasGeometry ? currentPlatform.lossyScale.z : float.NaN,
                platform_collider_lossy_scale_x = hasGeometry ? colliderScale.x : float.NaN,
                platform_collider_lossy_scale_y = hasGeometry ? colliderScale.y : float.NaN,
                platform_collider_lossy_scale_z = hasGeometry ? colliderScale.z : float.NaN,
                platform_radius_source = hasGeometry ? radiusSource : string.Empty,
                platform_difficulty = levelManager.currentLevel,
                ball_pos_x = ballPosition.x,
                ball_pos_z = ballPosition.z,
                ball_velocity_x = ballVelocity.x,
                ball_velocity_z = ballVelocity.z,
                ball_radial_distance = radialDistance,
                ball_radial_velocity = radialVelocity,
                nearest_edge_direction_x = hasGeometry ? outwardDirection.x : float.NaN,
                nearest_edge_direction_z = hasGeometry ? outwardDirection.y : float.NaN,
                target_edge_direction_x = hasGeometry ? outwardDirection.x : float.NaN,
                target_edge_direction_z = hasGeometry ? outwardDirection.y : float.NaN,
                target_edge_distance = targetEdgeDistance,
                target_edge_radial_velocity = targetEdgeRadialVelocity,
                directional_edge_distance = hasGeometry ? platformRadius - radialDistance : float.NaN,
                directional_edge_point_x = hasGeometry ? edgePoint.x : float.NaN,
                directional_edge_point_z = hasGeometry ? edgePoint.z : float.NaN,
                directional_edge_valid = hasGeometry,
                ball_radius = ballRadius,
                edge_warning_margin = ballRadius * 2f,
                edge_warning_radius = hasGeometry ? platformRadius - ballRadius * 2f : float.NaN,
                edge_warning_distance_threshold = warningDistanceThreshold,
                ball_position_velocity_x = ballPositionVelocityX,
                ball_position_velocity_z = ballPositionVelocityZ,
                cop_velocity_x = copVelocityX,
                cop_velocity_z = copVelocityZ,
                cop_speed = (!float.IsNaN(copVelocityX) && !float.IsNaN(copVelocityZ))
                    ? Mathf.Sqrt(copVelocityX * copVelocityX + copVelocityZ * copVelocityZ)
                    : float.NaN,
                fall_direction = player.FallDirection,
                edge_warning_state = player.EdgeWarningState,
                edge_contact_state = player.EdgeContactState,
                edge_warning_time = player.EdgeWarningTime,
                edge_contact_time = player.EdgeContactTime,
                support_lost_time = player.SupportLostTime,
                fall_event_time = fallEvent ? player.FallEventTime : float.NaN,
                edge_warning_backend_timestamp = player.EdgeWarningBackendTimestamp,
                edge_contact_backend_timestamp = player.EdgeContactBackendTimestamp,
                support_lost_backend_timestamp = player.SupportLostBackendTimestamp,
                fall_event_backend_timestamp = fallEvent ? player.FallEventBackendTimestamp : double.NaN,
                active_platform_id = platformInstanceId,
                support_contact_state = player.SupportContactState,
                ball_below_support_height = ballBelowSupportHeight,
                support_height = supportHeight,
                layer_transition_blocked = player.LayerTransitionBlocked,
                warning_episode_id = player.WarningEpisodeId,
                warning_enter_count = player.WarningEnterCount,
                warning_exit_count = player.WarningExitCount,
                run_id = levelManager.RunId,
                run_start_backend_timestamp = levelManager.RunStartBackendTimestamp,
                run_state = levelManager.RunStateTelemetry,
                session_outcome = levelManager.SessionOutcome,
                session_end_backend_timestamp = levelManager.SessionEndBackendTimestamp,
                commanded_difficulty = levelManager.CommandedDifficulty,
                active_platform_difficulty = levelManager.ActivePlatformDifficulty,
                passed_count = passedCount,
                fall_event = fallEvent,
                fall_reason = fallEvent ? fallReason : string.Empty,
                calibration_mode = levelManager.CalibrationMode,
                selected_session_layers = levelManager.SelectedSessionLayers,
                selected_difficulty = levelManager.SelectedDifficultyLabel,
                attention_state = attentionState,
                prediction_state = predictionState,
                target_hole_distance = targetHoleDistance,
                target_hole_radius = hasTargetHole ? targetHoleRadius : float.NaN,
                target_hole_approach_velocity = targetHoleApproachVelocity,
                moving_toward_target_hole = movingTowardTargetHole,
                hole_approach_state = holeApproachState,
                response_experiment_id = activeResponseExperimentId,
                response_condition = activeResponseCondition,
                trial_scenario = activeTrialScenario,
                trial_valid = activeTrialValid,
                response_trial_id = responseTrialId,
                response_layer_id = levelManager.GetCurrentLayer(),
                warning_source = warningSource,
                warning_type = warningType,
                warning_active = warningActive,
                visible_warning_state = visibleWarningState,
                warning_episode_start_time = player.EdgeWarningTime,
                warning_episode_start_backend_timestamp = player.EdgeWarningBackendTimestamp,
                warning_episode_end_time = player.EdgeWarningEndTime,
                warning_episode_end_backend_timestamp = player.EdgeWarningEndBackendTimestamp,
                attention_episode_id = attentionEpisodeId,
                attention_episode_enter_time = attentionEpisodeEnterTime,
                attention_episode_exit_time = attentionEpisodeExitTime,
                attention_episode_start_time = attentionEpisodeStartTime,
                attention_episode_end_time = attentionEpisodeEndTime,
                attention_episode_enter_backend_timestamp = attentionEpisodeEnterBackendTimestamp,
                attention_episode_exit_backend_timestamp = attentionEpisodeExitBackendTimestamp,
                attention_episode_start_backend_timestamp = attentionEpisodeStartBackendTimestamp,
                attention_episode_end_backend_timestamp = attentionEpisodeEndBackendTimestamp
            };

            LastTelemetry = data;
            RecordGeometryDiagnosticSample(
                currentPlatform,
                platformCenter,
                radialOffset,
                radialDistance,
                hasGeometry ? platformRadius - radialDistance : float.NaN,
                platformRadius,
                radiusSource,
                ballPosition,
                ballRadius,
                ballVelocity,
                fallEvent,
                backendTimestamp);
            string jsonString = JsonUtility.ToJson(data);
            lastSerializedTelemetry = jsonString;
            lastSerializedSequence = data.sequence;
            byte[] bytes = Encoding.UTF8.GetBytes(jsonString);
            udpSender.Send(bytes, bytes.Length, telemetryEndPoint);
            lastUdpSendCallCompleted = true;
        }
        catch (Exception exception)
        {
            if (Time.unscaledTime >= nextErrorLogTime)
            {
                Debug.LogWarning($"[GameTelemetry] UDP send failed: {exception.Message}");
                nextErrorLogTime = Time.unscaledTime + 5f;
            }
        }
    }

    public static void RecordLayerTransition(
        string phase,
        string runId,
        int fromLayer,
        int toLayer,
        int fromPlatformId,
        int toPlatformId,
        int lastSupportPlatformId,
        float lastSupportFixedTime,
        bool insideHole,
        bool beyondOuterEdge,
        bool crossedSupportBoundary,
        string reason,
        Transform explicitPlatform = null,
        int explicitLayer = -1)
    {
        if (Instance == null || Instance.geometryDiagnostics == null) return;
            Instance.geometryDiagnostics.RecordLayerTransition(
                phase,
                runId,
                Instance.levelManager != null ? Instance.levelManager.RunStateTelemetry : "unknown",
                Instance.levelManager != null ? Instance.levelManager.SessionOutcome : string.Empty,
                Instance.sequence,
                fromLayer,
                toLayer,
                fromPlatformId,
                toPlatformId,
                lastSupportPlatformId,
                lastSupportFixedTime,
                insideHole,
                beyondOuterEdge,
                crossedSupportBoundary,
                reason);
            if (Instance.enableEventDrivenFullGeometryDiagnostics)
            {
                Instance.RecordFullGeometryDiagnostic("event", phase == "before" ? "layer_transition_before" : "layer_transition_after", Time.time,
                    explicitPlatform, explicitLayer);
            }
    }

    public static void CaptureDiagnosticTerminalEvent(
        string eventName,
        Transform platform,
        int eventLayer,
        EndlessPlayerController player,
        Collider ballCollider,
        Vector3 ballCentre,
        float legacyRadiusEstimate,
        float legacyDirectionalDistance)
    {
        if (Instance == null || Instance.geometryDiagnostics == null) return;
        try
        {
            Instance.geometryDiagnostics.SetRunContext(Instance.levelManager != null ? Instance.levelManager.RunId : string.Empty);
            Instance.geometryDiagnostics.CaptureTerminalEvent(
                eventName,
                platform,
                eventLayer,
                player,
                ballCollider,
                ballCentre,
                legacyRadiusEstimate,
                legacyDirectionalDistance);
        }
        catch (Exception exception)
        {
            Instance.LogGeometryDiagnosticsWarning(exception);
        }
    }

    private void RecordGeometryDiagnosticSample(
        Transform platform,
        Vector3 platformCentre,
        Vector2 radialOffset,
        float radialDistance,
        float directionalEdgeDistance,
        float legacyRadius,
        string legacyRadiusSource,
        Vector3 ballPosition,
        float ballRadius,
        Vector3 ballVelocity,
        bool terminalPacket,
        double backendTimestamp)
    {
        if (geometryDiagnostics == null || platform == null || levelManager == null) return;
        geometryDiagnostics.SetRunContext(levelManager.RunId);
        try
        {
            Vector2 normalizedDirection = radialDistance > 0.0001f ? radialOffset / radialDistance : Vector2.right;
            geometryDiagnostics.TryRecordSample(
                platform,
                levelManager.GetCurrentLayer(),
                player != null ? player.GetComponent<Collider>() : null,
                ballPosition,
                legacyRadius,
                legacyRadiusSource,
                platformCentre,
                normalizedDirection,
                radialDistance,
                directionalEdgeDistance,
                ballRadius,
                player,
                backendTimestamp,
                levelManager != null ? levelManager.RunId : string.Empty,
                terminalPacket);
        }
        catch (Exception exception)
        {
            LogGeometryDiagnosticsWarning(exception);
        }
    }

    private void RecordFullGeometryDiagnostic(string samplingMode, string triggerType, float triggerUnityTime,
        Transform explicitPlatform = null, int explicitLayer = -1)
    {
        if (geometryDiagnostics == null || levelManager == null || player == null) return;
        Transform platform = explicitPlatform != null ? explicitPlatform : levelManager.GetCurrentPlatformTransform();
        int snapshotLayer = explicitLayer >= 0 ? explicitLayer : levelManager.GetCurrentLayer();
        Vector3 centre = player.transform.position;
        int ordinaryPlatformId = 0;
        int ordinaryActivePlatformId = 0;
        string ordinaryVersionId = string.Empty;
        string ordinaryActiveVersionId = string.Empty;
        float ordinarySourceTimestamp = float.NaN;
        bool ordinaryQueryValid = false;
        bool ordinaryOwnershipValid = false;
        bool ordinaryBelongsToSnapshotPlatform = false;
        float identityStarted = Time.realtimeSinceStartup;
        if (platform != null && levelManager.GetCurrentPlatformTransform() == platform)
        {
            levelManager.GetCurrentPlatformTelemetryGeometryIdentity(
                centre,
                out ordinaryPlatformId, out ordinaryVersionId, out ordinarySourceTimestamp,
                out ordinaryQueryValid, out ordinaryOwnershipValid,
                out _, out _, out _, out _, out _, out _, out _,
                out ordinaryActivePlatformId, out ordinaryActiveVersionId);
            ordinaryBelongsToSnapshotPlatform = ordinaryPlatformId == platform.gameObject.GetInstanceID() &&
                                                ordinaryActivePlatformId == ordinaryPlatformId;
        }
        geometryDiagnostics.SetIdentityExtraQueryCost((Time.realtimeSinceStartup - identityStarted) * 1000f);
        geometryDiagnostics.SetOrdinaryGeometryAssociation(
            ordinaryBelongsToSnapshotPlatform ? ordinaryPlatformId : 0,
            ordinaryBelongsToSnapshotPlatform ? ordinaryActivePlatformId : 0,
            ordinaryBelongsToSnapshotPlatform ? ordinaryVersionId : string.Empty,
            ordinaryBelongsToSnapshotPlatform ? ordinaryActiveVersionId : string.Empty,
            ordinarySourceTimestamp, ordinaryQueryValid,
            ordinaryOwnershipValid && ordinaryBelongsToSnapshotPlatform,
            ordinarySourceTimestamp);
        long eventId = geometryDiagnostics.NextFullGeometryEventId();
        double triggerBackend = GetBackendUnixTimestamp();
        int platformId = platform != null ? platform.gameObject.GetInstanceID() : -1;
        geometryDiagnostics.RecordFullGeometryEventMetadata(eventId, samplingMode, triggerType,
            triggerUnityTime, triggerBackend, levelManager.RunId, snapshotLayer,
            platformId, "unknown", "snapshot_versions_are_written_after_live_queries");
        if (platform == null) return;
        if (samplingMode == "event" && triggerType != "layer_transition_before" &&
            triggerType != "layer_transition_after" && triggerType != "terminal_snapshot_frozen" &&
            !float.IsNaN(lastTriggeredFullGeometryQueryTime) &&
            triggerUnityTime - lastTriggeredFullGeometryQueryTime < Mathf.Max(0.01f, eventDrivenFullGeometryMinInterval))
        {
            geometryDiagnostics.EnqueueDeferredFullGeometryEvent(eventId, samplingMode, triggerType,
                triggerUnityTime, triggerBackend, levelManager.RunId, levelManager.GetCurrentLayer(),
                platformId, "unknown", "event_cooldown_before_snapshot_query");
            return;
        }
        lastTriggeredFullGeometryQueryTime = triggerUnityTime;
        Vector3 platformCentre = platform.position;
        Vector2 offset = new Vector2(centre.x - platformCentre.x, centre.z - platformCentre.z);
        float radial = offset.magnitude;
        float edgeDistance = player.DiagnosticWarningPredicateRadius - radial;
        geometryDiagnostics.TryRecordFullGeometrySnapshot(samplingMode, triggerType, eventId,
            triggerUnityTime, triggerBackend, platform, snapshotLayer,
            player.GetComponent<Collider>(), centre,
            player.DiagnosticWarningPredicateRadius + player.GetTelemetryBallRadius(),
            "event_full_geometry_directional_observation", platformCentre,
            radial > 0.0001f ? offset / radial : Vector2.right, radial, edgeDistance,
            player.GetTelemetryBallRadius(), player, GetBackendUnixTimestamp(), levelManager.RunId,
            fullGeometryBudgetMilliseconds, "triggered_from_udp_telemetry_state");
    }

    public static void RecordFullGeometryEvent(string triggerType, float triggerUnityTime)
    {
        if (Instance == null || !Instance.enableEventDrivenFullGeometryDiagnostics) return;
        Instance.RecordFullGeometryDiagnostic("event", triggerType, triggerUnityTime);
    }

    private void LogGeometryDiagnosticsWarning(Exception exception)
    {
        if (geometryDiagnosticsErrorLogged) return;
        geometryDiagnosticsErrorLogged = true;
        Debug.LogWarning($"[GameTelemetry] Geometry diagnostics sample failed: {exception.Message}");
    }

    private bool UpdateAttentionState(
        bool hasGeometry,
        float edgeDistance,
        float warningThreshold,
        float radialVelocity,
        bool edgeWarning,
        bool edgeContact,
        bool suppressAttentionForHole,
        bool predictionContextChanged,
        float sampleTime)
    {
        if (predictionContextChanged || !hasGeometry || float.IsNaN(radialVelocity))
        {
            predictionSampleTimes.Clear();
            predictionRadialVelocities.Clear();
            return false;
        }

        predictionSampleTimes.Enqueue(sampleTime);
        predictionRadialVelocities.Enqueue(radialVelocity);
        while (predictionSampleTimes.Count > 0 && sampleTime - predictionSampleTimes.Peek() > 0.5f)
        {
            predictionSampleTimes.Dequeue();
            predictionRadialVelocities.Dequeue();
        }

        if (edgeContact || edgeWarning || suppressAttentionForHole || edgeDistance <= warningThreshold || radialVelocity <= 0f || predictionRadialVelocities.Count < 5)
        {
            return false;
        }

        int outwardSamples = 0;
        int inwardSamples = 0;
        foreach (float velocity in predictionRadialVelocities)
        {
            if (velocity > 0.05f) outwardSamples++;
            else if (velocity < -0.05f) inwardSamples++;
        }

        int sampleCount = predictionRadialVelocities.Count;
        return outwardSamples > sampleCount * 0.6f && inwardSamples <= sampleCount * 0.1f;
    }

    private void EnsureResponseTrialContext()
    {
        string runId = levelManager != null ? levelManager.RunId : string.Empty;
        if (responseTrialInitialized && activeRunId == runId) return;

        responseTrialId = Guid.NewGuid().ToString("N");
        activeResponseExperimentId = responseExperimentId;
        activeResponseCondition = responseCondition;
        activeTrialScenario = trialScenario;
        activeTrialValid = trialValid;
        activeRunId = runId;
        responseTrialInitialized = true;
        attentionEpisodeId = 0;
        attentionEpisodeActive = false;
        attentionEpisodeEnterTime = float.NaN;
        attentionEpisodeExitTime = float.NaN;
        attentionEpisodeStartTime = float.NaN;
        attentionEpisodeEndTime = float.NaN;
        attentionEpisodeEnterBackendTimestamp = double.NaN;
        attentionEpisodeExitBackendTimestamp = double.NaN;
        attentionEpisodeStartBackendTimestamp = double.NaN;
        attentionEpisodeEndBackendTimestamp = double.NaN;
    }

    private void UpdateAttentionEpisode(bool active, float unityTime, double backendTimestamp, bool contextChanged)
    {
        if (contextChanged && attentionEpisodeActive) ExitAttentionEpisode(unityTime, backendTimestamp);
        if (active && !attentionEpisodeActive)
        {
            attentionEpisodeActive = true;
            attentionEpisodeId++;
            attentionEpisodeEnterTime = unityTime;
            attentionEpisodeStartTime = unityTime;
            attentionEpisodeExitTime = float.NaN;
            attentionEpisodeEndTime = float.NaN;
            attentionEpisodeEnterBackendTimestamp = backendTimestamp;
            attentionEpisodeStartBackendTimestamp = backendTimestamp;
            attentionEpisodeExitBackendTimestamp = double.NaN;
            attentionEpisodeEndBackendTimestamp = double.NaN;
        }
        else if (!active && attentionEpisodeActive)
        {
            ExitAttentionEpisode(unityTime, backendTimestamp);
        }
    }

    private void ExitAttentionEpisode(float unityTime, double backendTimestamp)
    {
        attentionEpisodeActive = false;
        attentionEpisodeExitTime = unityTime;
        attentionEpisodeEndTime = unityTime;
        attentionEpisodeExitBackendTimestamp = backendTimestamp;
        attentionEpisodeEndBackendTimestamp = backendTimestamp;
    }

    private void OnDestroy()
    {
        geometryDiagnostics?.Flush();
        geometryDiagnostics?.Dispose();
        geometryDiagnostics = null;
        if (Instance == this) Instance = null;
        if (udpSender != null)
        {
            udpSender.Close();
            udpSender = null;
        }
    }
}
