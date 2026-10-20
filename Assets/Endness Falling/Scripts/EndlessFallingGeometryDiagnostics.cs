using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;
#endif

/// <summary>
/// Local-only Endless Falling geometry diagnostics. These records are deliberately
/// separate from the legacy UDP payload until its scalar schema is agreed with the backend.
/// </summary>
public sealed class EndlessFallingGeometryDiagnostics : IDisposable
{
    public const string SchemaVersion = "endless_falling_geometry_diag_v1";
    public const string BoundaryMethod = "active_collider_vertical_ray_radial_scan_binary_refine";
    public const string SupportMethod = "active_collider_vertical_raycast_9_point_footprint_approx";

    [Serializable]
    public sealed class ColliderGeometry
    {
        public int collider_instance_id;
        public string collider_name;
        public string collider_hierarchy_path;
        public string collider_type;
        public bool enabled;
        public bool active_in_hierarchy;
        public bool is_trigger;
        public bool contributes_to_query;
        public int game_object_layer;
        public Vector3 local_position;
        public Vector3 world_position;
        public Vector3 local_euler_angles;
        public Vector3 world_euler_angles;
        public Vector3 local_scale;
        public Vector3 lossy_scale;
        public Vector3 bounds_min;
        public Vector3 bounds_max;
        public string mesh_collider_identity;
        public string mesh_filter_identity;
        public string mesh_asset_path;
        public string mesh_asset_guid;
        public int mesh_instance_id;
        public int mesh_vertex_count;
        public int mesh_triangle_index_count;
    }

    [Serializable]
    public sealed class DiagnosticLifecycleRecord
    {
        public string schema_version;
        public string record_type;
        public string lifecycle_event;
        public string run_id;
        public string run_state;
        public string session_outcome;
        public float unity_time;
        public double backend_timestamp;
        public long sequence;
        public bool duplicate_event;
        public string detail;
        public string payload_json;
    }

    [Serializable]
    public sealed class GeometryChangeRecord
    {
        public string schema_version;
        public string geometry_version_id;
        public string run_id;
        public string change_reason;
        public float unity_time;
        public string platform_asset_identity;
        public string platform_asset_path;
        public string platform_asset_guid;
        public int platform_instance_id;
        public string platform_name;
        public int layer_at_observation;
        public Vector3 platform_position;
        public Vector3 platform_euler_angles;
        public Vector3 platform_local_scale;
        public Vector3 platform_lossy_scale;
        public bool has_target_hole;
        public bool root_platform_data_present;
        public bool hole_center_present;
        public int platform_data_instance_id;
        public int hole_center_instance_id;
        public string hole_center_name;
        public Vector3 hole_center_world_position;
        public float authored_hole_radius;
        public string authored_hole_radius_units;
        public Vector3 hole_radius_scale_inputs;
        public float computed_world_hole_radius;
        public float computed_world_hole_radius_candidate;
        public bool hole_geometry_valid;
        public string hole_geometry_source;
        public bool hole_center_probe_clear;
        public int hole_ring_probe_hits;
        public int hole_ring_probe_count;
        public string outer_bound_search_extent_method;
        public float collider_aabb_radial_search_extent;
        public ColliderGeometry[] colliders;
    }

    [Serializable]
    public sealed class TerminalEventSnapshot
    {
        public bool valid;
        public string event_name;
        public string run_id;
        public string event_outcome;
        public long event_sequence;
        public string geometry_version_id;
        public float event_time;
        public double event_backend_timestamp;
        public int event_platform_instance_id;
        public int event_layer;
        public int last_support_platform_instance_id;
        public float last_support_fixed_time;
        public int transition_old_support_platform_instance_id;
        public float transition_old_support_fixed_time;
        public int transition_from_layer;
        public int transition_to_layer;
        public int transition_from_platform_instance_id;
        public int transition_to_platform_instance_id;
        public string event_platform_asset_identity;
        public string event_platform_asset_path;
        public string event_platform_asset_guid;
        public Vector3 event_ball_centre;
        public int event_ball_collider_instance_id;
        public float event_radial_distance;
        public float event_legacy_radius_estimate;
        public float event_legacy_directional_distance;
        public float event_player_radius;
        public float event_support_boundary_radius;
        public bool event_inside_hole_opening;
        public bool event_beyond_outer_edge_predicate;
        public bool event_crossed_support_boundary_predicate;
        public bool event_terminal_fall_predicate_committed;
    }

    [Serializable]
    public sealed class LightweightDiagnosticSample
    {
        public string schema_version;
        public string record_type;
        public long diagnostic_sequence;
        public long associated_udp_sequence;
        public string udp_sequence_association;
        public string run_id;
        public float unity_time;
        public double source_timestamp;
        public double backend_timestamp;
        public float target_interval_seconds;
        public float actual_interval_seconds;
        public float previous_write_cost_ms;
        public float lightweight_capture_cost_ms;
        public string skip_reason;
        public bool geometry_cache_valid;
        public int geometry_cache_platform_instance_id;
        public string geometry_cache_version_id;
        public float geometry_cache_age_seconds;
        public string geometry_cache_state;
        public int platform_level;
        public int active_platform_instance_id;
        public string geometry_version_id;
        public int ordinary_geometry_platform_instance_id;
        public string ordinary_geometry_version_id;
        public float ordinary_geometry_source_timestamp;
        public bool ordinary_geometry_query_valid;
        public bool ordinary_geometry_ownership_valid;
        public int ordinary_geometry_active_platform_instance_id;
        public string ordinary_geometry_active_version_id;
        public int recent_support_platform_instance_id;
        public float recent_support_fixed_time;
        public string recent_support_evidence;
        public Vector3 ball_centre;
        public float ball_radius;
        public float directional_edge_distance;
        public bool directional_edge_valid;
        public float target_hole_distance;
        public float target_hole_radius;
        public bool hole_geometry_valid;
        public float hole_boundary_signed_distance;
        public bool footprint_support_query_valid;
        public int footprint_support_hit_count;
        public string transition_event;
        public bool calibration_excluded;
        public float source_geometry_sample_time;
    }

    [Serializable]
    public sealed class DiagnosticSample
    {
        public string schema_version;
        public long sample_sequence;
        public float unity_time;
        public double backend_timestamp;
        public int platform_level;
        public int active_platform_instance_id;
        public string platform_asset_identity;
        public string platform_asset_path;
        public string platform_asset_guid;
        public string run_id;
        public string geometry_version_id;
        public Vector3 platform_centre;

        public Vector3 ball_centre;
        public int ball_collider_instance_id;
        public string ball_collider_name;
        public string ball_collider_type;
        public bool ball_collider_enabled;
        public bool ball_collider_is_trigger;
        public Vector3 ball_collider_local_scale;
        public Vector3 ball_collider_lossy_scale;
        public Vector3 ball_collider_bounds_min;
        public Vector3 ball_collider_bounds_max;
        public Vector3 ball_collider_bounds_extents;
        public float ball_world_radius_estimate;
        public string ball_shape_parameters;

        public float legacy_radius_estimate;
        public string legacy_radius_source;
        public float legacy_radial_distance;
        public Vector2 normalized_radial_direction;
        public float legacy_directional_distance;

        public bool has_target_hole;
        public bool root_platform_data_present;
        public bool hole_center_present;
        public int platform_data_instance_id;
        public int hole_center_instance_id;
        public Vector3 hole_center_world_position;
        public float authored_hole_radius;
        public string authored_hole_radius_units;
        public Vector3 hole_radius_scale_inputs;
        public float computed_world_hole_radius;
        public float computed_world_hole_radius_candidate;
        public bool hole_geometry_valid;
        public string hole_geometry_source;

        public string boundary_query_method;
        public bool actual_boundary_query_valid;
        public string actual_boundary_query_invalid_reason;
        public int actual_boundary_hit_collider_instance_id;
        public string actual_boundary_hit_collider_name;
        public Vector3 actual_boundary_point;
        public float actual_boundary_radius;
        public float actual_boundary_signed_distance_from_ball_centre;
        public float ball_surface_clearance_to_outer_edge;
        public float hole_boundary_signed_distance_from_ball_centre;
        public float actual_boundary_signed_error_vs_legacy;
        public float boundary_query_cost_ms;
        public int boundary_query_ray_count;

        public string support_query_method;
        public string footprint_support_result;
        public bool footprint_support_query_valid;
        public int footprint_support_hit_count;
        public int footprint_support_sample_count;
        public int footprint_support_hit_collider_instance_id;
        public string footprint_support_hit_collider_name;
        public Vector3 footprint_support_contact_point;
        public float footprint_support_surface_height;
        public Vector3 footprint_support_normal;
        public float support_query_cost_ms;
        public int support_query_ray_count;
        public float diagnostic_metadata_cost_ms;
        public float diagnostic_total_cost_ms;
        public float diagnostic_query_cost_ms;
        public float diagnostic_write_cost_ms;
        public float diagnostic_identity_extra_query_ms;
        public float diagnostic_fingerprint_stage_ms;
        public float diagnostic_hole_geometry_stage_ms;
        public float frame_delta_time_ms;
        public float frame_unscaled_delta_time_ms;
        public float frame_smooth_delta_time_ms;
        public string generic_support_contact_state;
        public int generic_support_contact_platform_id;
        public float generic_support_last_contact_fixed_time;
        public bool generic_ball_below_support_height;
        public float generic_support_height;
        public float support_lost_predicate_radial_distance;
        public float support_lost_predicate_boundary_radius;
        public bool support_lost_predicate_inside_hole_opening;
        public bool support_lost_predicate_result;

        public float warning_predicate_radial_distance;
        public float warning_predicate_radius;
        public bool warning_predicate_near_edge;
        public bool warning_state_before_transition;
        public bool warning_state_after_transition;
        public float warning_transition_unity_time;
        public double warning_transition_backend_timestamp;
        public float edge_contact_predicate_radial_distance;
        public float edge_contact_predicate_radius;
        public bool edge_contact_predicate_result;
        public float edge_contact_transition_unity_time;
        public double edge_contact_transition_backend_timestamp;
        public bool support_lost_transition;
        public float support_lost_transition_unity_time;
        public double support_lost_transition_backend_timestamp;
        public bool fall_predicate_committed;
        public float fall_transition_unity_time;
        public double fall_transition_backend_timestamp;
        public bool fall_predicate_inside_hole_opening;
        public bool fall_predicate_beyond_outer_edge;
        public bool fall_predicate_crossed_support_boundary;

        public bool event_snapshot_valid;
        public string event_geometry_version_id;
        public int event_platform_instance_id;
        public int event_layer;
        public string event_platform_asset_identity;
        public Vector3 event_ball_centre;
        public float event_time;
        public double event_backend_timestamp;
    }

    public struct BoundaryQueryResult
    {
        public bool valid;
        public string invalidReason;
        public int hitColliderId;
        public string hitColliderName;
        public Vector3 boundaryPoint;
        public float boundaryRadius;
        public float signedDistanceFromCentre;
        public int rayCount;
        public float queryCostMilliseconds;
    }

    public struct FootprintSupportResult
    {
        public bool valid;
        public bool hasSupport;
        public int hitCount;
        public int sampleCount;
        public int hitColliderId;
        public string hitColliderName;
        public Vector3 contactPoint;
        public float surfaceHeight;
        public Vector3 normal;
        public int rayCount;
        public float queryCostMilliseconds;
    }

    private readonly string geometryLogPath;
    private readonly string sampleLogPath;
    private readonly float sampleInterval;
    private readonly int boundaryScanSamples;
    private readonly int boundaryRefinementSteps;
    private readonly StreamWriter geometryWriter;
    private readonly StreamWriter sampleWriter;
    private string lastGeometryFingerprint = string.Empty;
    private string geometryVersionId = string.Empty;
    private int geometryVersion;
    private long lightweightDiagnosticSequence;
    private long sampleSequence;
    private float lastGeometrySampleTime = float.NaN;
    private int lastGeometryPlatformInstanceId = int.MinValue;
    private string lastGeometryVersionId = string.Empty;
    private bool geometryCacheValid;
    private string geometryCacheState = "not_sampled";
    private float lastLightweightWriteCostMs = float.NaN;
    private float lastFullGeometryQueryCostMs = float.NaN;
    private float lastFullGeometryWriteCostMs = float.NaN;
    private int lightweightSamplesSinceFlush;
    private float nextSampleTime;
    private long fullGeometryEventId;
    private TerminalEventSnapshot terminalSnapshot;
    private string currentRunId = string.Empty;
    private bool transitionEvidenceValid;
    private int transitionFromLayer = -1;
    private int transitionToLayer = -1;
    private int transitionFromPlatformInstanceId = -1;
    private int transitionToPlatformInstanceId = -1;
    private int transitionLastSupportPlatformInstanceId = int.MinValue;
    private float transitionLastSupportFixedTime = float.NaN;
    private bool disposed;
    private DiagnosticSample lastFullDiagnosticSample;
    private float pendingIdentityQueryCostMilliseconds = float.NaN;
    private int ordinaryGeometryPlatformInstanceId;
    private int ordinaryGeometryActivePlatformInstanceId;
    private string ordinaryGeometryVersionId = string.Empty;
    private string ordinaryGeometryActiveVersionId = string.Empty;
    private float ordinaryGeometrySourceTimestamp = float.NaN;
    private bool ordinaryGeometryQueryValid;
    private bool ordinaryGeometryOwnershipValid;
    private float ordinaryGeometryAssociationQueryTime = float.NaN;

    public string GeometryLogPath => geometryLogPath;
    public string SampleLogPath => sampleLogPath;
    public string CurrentGeometryVersionForPlatform(int platformId)
    {
        return lastGeometryPlatformInstanceId == platformId ? lastGeometryVersionId : string.Empty;
    }

    public void SetOrdinaryGeometryAssociation(
        int platformInstanceId, int activePlatformInstanceId,
        string versionId, string activeVersionId, float sourceTimestamp,
        bool queryValid, bool ownershipValid, float queryTime)
    {
        ordinaryGeometryPlatformInstanceId = platformInstanceId;
        ordinaryGeometryActivePlatformInstanceId = activePlatformInstanceId;
        ordinaryGeometryVersionId = versionId ?? string.Empty;
        ordinaryGeometryActiveVersionId = activeVersionId ?? string.Empty;
        ordinaryGeometrySourceTimestamp = sourceTimestamp;
        ordinaryGeometryQueryValid = queryValid;
        ordinaryGeometryOwnershipValid = ownershipValid;
        ordinaryGeometryAssociationQueryTime = queryTime;
    }

    public void SetIdentityExtraQueryCost(float milliseconds)
    {
        pendingIdentityQueryCostMilliseconds = milliseconds;
    }


    public EndlessFallingGeometryDiagnostics(float intervalSeconds, int scanSamples, int refinementSteps)
    {
        sampleInterval = Mathf.Max(0.25f, intervalSeconds);
        boundaryScanSamples = Mathf.Clamp(scanSamples, 16, 256);
        boundaryRefinementSteps = Mathf.Clamp(refinementSteps, 4, 16);
        string folder = Path.Combine(Application.persistentDataPath, "EndlessFallingDiagnostics");
        Directory.CreateDirectory(folder);
        string session = DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture) + "_" + Guid.NewGuid().ToString("N").Substring(0, 8);
        geometryLogPath = Path.Combine(folder, "geometry_" + session + ".jsonl");
        sampleLogPath = Path.Combine(folder, "samples_" + session + ".jsonl");
        geometryWriter = new StreamWriter(geometryLogPath, false, new UTF8Encoding(false)) { AutoFlush = false };
        sampleWriter = new StreamWriter(sampleLogPath, false, new UTF8Encoding(false)) { AutoFlush = false };
    }

    public void SetRunContext(string runId)
    {
        string nextRunId = runId ?? string.Empty;
        if (!string.Equals(currentRunId, nextRunId, StringComparison.Ordinal))
        {
            transitionEvidenceValid = false;
            transitionFromLayer = -1;
            transitionToLayer = -1;
            transitionFromPlatformInstanceId = -1;
            transitionToPlatformInstanceId = -1;
            transitionLastSupportPlatformInstanceId = int.MinValue;
            transitionLastSupportFixedTime = float.NaN;
            lastFullGeometryQueryCostMs = float.NaN;
            lastFullGeometryWriteCostMs = float.NaN;
        }
        currentRunId = nextRunId;
    }

    public void InvalidateGeometryCache(int activePlatformInstanceId)
    {
        lastGeometrySampleTime = float.NaN;
        lastGeometryPlatformInstanceId = int.MinValue;
        lastGeometryVersionId = string.Empty;
        geometryVersionId = string.Empty;
        geometryCacheValid = false;
        geometryCacheState = "invalidated_platform_changed";
    }

    public void Flush()
    {
        if (disposed) return;
        geometryWriter?.Flush();
        sampleWriter?.Flush();
    }

    public void SetTerminalRunContext(string runId, string outcome, long sequence)
    {
        if (terminalSnapshot == null) return;
        terminalSnapshot.run_id = runId ?? string.Empty;
        terminalSnapshot.event_outcome = outcome ?? string.Empty;
        terminalSnapshot.event_sequence = sequence;
    }

    public void RecordLayerTransition(
        string phase,
        string runId,
        string runState,
        string sessionOutcome,
        long sequence,
        int fromLayer,
        int toLayer,
        int fromPlatformId,
        int toPlatformId,
        int lastSupportPlatformId,
        float lastSupportFixedTime,
        bool insideHole,
        bool beyondOuterEdge,
        bool crossedSupportBoundary,
        string reason)
    {
        if (disposed) return;
        if (phase == "before")
        {
            transitionEvidenceValid = true;
            transitionFromLayer = fromLayer;
            transitionToLayer = toLayer;
            transitionFromPlatformInstanceId = fromPlatformId;
            transitionToPlatformInstanceId = toPlatformId;
            transitionLastSupportPlatformInstanceId = lastSupportPlatformId;
            transitionLastSupportFixedTime = lastSupportFixedTime;
        }

        RecordLifecycleEvent(
            phase == "before" ? "layer_transition_before" : "layer_transition_after",
            runId, runState, sessionOutcome, sequence,
            $"from_layer={fromLayer};to_layer={toLayer};from_platform={fromPlatformId};to_platform={toPlatformId};last_support_platform={lastSupportPlatformId};last_support_fixed_time={lastSupportFixedTime:R};inside_hole={insideHole};beyond_outer_edge={beyondOuterEdge};crossed_support_boundary={crossedSupportBoundary};reason={reason}");
    }

    public void RecordLifecycleEvent(
        string lifecycleEvent,
        string runId,
        string runState,
        string sessionOutcome,
        long sequence,
        string detail,
        bool duplicateEvent = false,
        string payloadJson = "")
    {
        if (disposed) return;
        sampleWriter.WriteLine(JsonUtility.ToJson(new DiagnosticLifecycleRecord
        {
            schema_version = SchemaVersion,
            record_type = "lifecycle",
            lifecycle_event = lifecycleEvent,
            run_id = runId ?? string.Empty,
            run_state = runState ?? string.Empty,
            session_outcome = sessionOutcome ?? string.Empty,
            unity_time = Time.time,
            backend_timestamp = UDPManager.GetBackendUnixTimestamp(),
            sequence = sequence,
            duplicate_event = duplicateEvent,
            detail = detail ?? string.Empty,
            payload_json = payloadJson ?? string.Empty
        }));
    }

    public void TryRecordLightweightSample(
        UDPManager.UnityGameTelemetry telemetry,
        Transform platform,
        EndlessPlayerController player,
        float unityTime,
        float targetInterval,
        float previousSampleTime,
        long associatedUdpSequence)
    {
        if (disposed || telemetry == null || platform == null) return;
        long started = Stopwatch.GetTimestamp();
        float actualInterval = float.IsNaN(previousSampleTime) ? float.NaN : unityTime - previousSampleTime;
        string supportEvidence = player != null && player.DiagnosticSupportContactPlatformId != int.MinValue
            ? "collision_stay_latest_known"
            : "unknown";
        string transitionEvent = transitionEvidenceValid ? "recent_transition_evidence_available" : "none_known";
        bool geometryCacheValid = lastGeometryPlatformInstanceId == platform.gameObject.GetInstanceID() &&
                                  !float.IsNaN(lastGeometrySampleTime) &&
                                  !string.IsNullOrEmpty(geometryVersionId);
        LightweightDiagnosticSample sample = new LightweightDiagnosticSample
        {
            schema_version = SchemaVersion,
            record_type = "lightweight_sample",
            diagnostic_sequence = ++lightweightDiagnosticSequence,
            associated_udp_sequence = associatedUdpSequence,
            udp_sequence_association = associatedUdpSequence > 0 ? "latest_udp_state_not_one_to_one" : "none",
            run_id = currentRunId,
            unity_time = unityTime,
            source_timestamp = telemetry.time,
            backend_timestamp = telemetry.backend_timestamp,
            target_interval_seconds = targetInterval,
            actual_interval_seconds = actualInterval,
            previous_write_cost_ms = lastLightweightWriteCostMs,
            lightweight_capture_cost_ms = ElapsedMilliseconds(started),
            skip_reason = float.IsNaN(actualInterval) ? "first_sample" : actualInterval > targetInterval * 1.5f ? "late_frame_or_udp_schedule" : "none",
            platform_level = telemetry.platformLevel,
            active_platform_instance_id = platform.gameObject.GetInstanceID(),
            geometry_version_id = geometryCacheValid ? lastGeometryVersionId : string.Empty,
            ordinary_geometry_platform_instance_id = telemetry.run_id == currentRunId ? telemetry.geometry_platform_instance_id : 0,
            ordinary_geometry_version_id = telemetry.run_id == currentRunId ? telemetry.geometry_version_id : string.Empty,
            ordinary_geometry_source_timestamp = telemetry.run_id == currentRunId ? telemetry.geometry_source_timestamp : float.NaN,
            ordinary_geometry_query_valid = telemetry.run_id == currentRunId && telemetry.geometry_query_valid,
            ordinary_geometry_ownership_valid = telemetry.run_id == currentRunId && telemetry.geometry_ownership_valid,
            ordinary_geometry_active_platform_instance_id = telemetry.run_id == currentRunId ? telemetry.geometry_active_platform_instance_id : 0,
            ordinary_geometry_active_version_id = telemetry.run_id == currentRunId ? telemetry.geometry_active_version_id : string.Empty,
            geometry_cache_valid = geometryCacheValid,
            geometry_cache_platform_instance_id = lastGeometryPlatformInstanceId,
            geometry_cache_version_id = lastGeometryVersionId,
            geometry_cache_age_seconds = geometryCacheValid ? unityTime - lastGeometrySampleTime : float.NaN,
            geometry_cache_state = geometryCacheState,
            recent_support_platform_instance_id = player != null ? player.DiagnosticSupportContactPlatformId : int.MinValue,
            recent_support_fixed_time = player != null ? player.DiagnosticLastSupportContactFixedTime : float.NaN,
            recent_support_evidence = supportEvidence,
            ball_centre = player.transform.position,
            ball_radius = telemetry.ball_radius,
            directional_edge_distance = geometryCacheValid ? telemetry.directional_edge_distance : float.NaN,
            directional_edge_valid = geometryCacheValid && telemetry.directional_edge_valid,
            target_hole_distance = geometryCacheValid ? telemetry.target_hole_distance : float.NaN,
            target_hole_radius = geometryCacheValid ? telemetry.target_hole_radius : float.NaN,
            hole_geometry_valid = geometryCacheValid && !float.IsNaN(telemetry.target_hole_radius),
            hole_boundary_signed_distance = geometryCacheValid ? telemetry.target_hole_distance - telemetry.target_hole_radius : float.NaN,
            source_geometry_sample_time = geometryCacheValid ? lastGeometrySampleTime : float.NaN,
            footprint_support_query_valid = false,
            footprint_support_hit_count = -1,
            transition_event = transitionEvidenceValid ? "recent_transition_evidence_available" : "none_known",
            calibration_excluded = false,
        };
        string json = JsonUtility.ToJson(sample);
        long writeStarted = Stopwatch.GetTimestamp();
        sampleWriter.WriteLine(json);
        lastLightweightWriteCostMs = ElapsedMilliseconds(writeStarted);
        lightweightSamplesSinceFlush++;
        if (lightweightSamplesSinceFlush >= 20)
        {
            long flushStarted = Stopwatch.GetTimestamp();
            sampleWriter.Flush();
            lastLightweightWriteCostMs += ElapsedMilliseconds(flushStarted);
            lightweightSamplesSinceFlush = 0;
        }
    }
    [Serializable]
    public sealed class FullGeometryDiagnosticEvent
    {
        public string schema_version;
        public string record_type;
        public long event_id;
        public string sampling_mode;
        public string trigger_type;
        public float trigger_unity_time;
        public double trigger_backend_timestamp;
        public float query_start_unity_time;
        public float query_end_unity_time;
        public float query_delay_seconds;
        public float query_cost_ms;
        public float diagnostic_boundary_stage_ms;
        public float diagnostic_support_stage_ms;
        public float diagnostic_hole_geometry_stage_ms;
        public float diagnostic_fingerprint_stage_ms;
        public float diagnostic_identity_extra_query_ms;
        public float diagnostic_metadata_stage_ms;
        public float diagnostic_full_query_total_ms;
        public float diagnostic_write_total_ms;
        public float frame_delta_time_ms;
        public float frame_unscaled_delta_time_ms;
        public float frame_smooth_delta_time_ms;
        public float write_cost_ms;
        public float budget_ms;
        public bool budget_exceeded;
        public bool query_completed;
        public bool result_valid;
        public string status;
        public string skip_reason;
        public string run_id;
        public int platform_level;
        public int active_platform_instance_id;
        public string geometry_version_id;
        public string diagnostic_fingerprint_version_id;
        public float diagnostic_fingerprint_query_time;
        public int ordinary_geometry_platform_instance_id;
        public int ordinary_geometry_active_platform_instance_id;
        public string ordinary_geometry_version_id;
        public string ordinary_geometry_active_version_id;
        public float ordinary_geometry_source_timestamp;
        public bool ordinary_geometry_query_valid;
        public bool ordinary_geometry_ownership_valid;
        public string version_association;
        public float version_association_query_time;
        public Vector3 ball_centre;
        public float ball_radius;
        public float directional_edge_distance;
        public bool directional_edge_valid;
        public float target_hole_distance;
        public float target_hole_radius;
        public bool hole_geometry_valid;
        public float hole_boundary_signed_distance;
        public string footprint_support_result;
        public bool footprint_support_query_valid;
        public int footprint_support_hit_count;
        public int support_platform_instance_id;
        public float support_fixed_time;
        public string event_detail;
    }

    public void RecordFullGeometryEventMetadata(
        long eventId,
        string samplingMode,
        string triggerType,
        float triggerUnityTime,
        double triggerBackendTimestamp,
        string runId,
        int platformLevel,
        int platformId,
        string geometryVersionId,
        string detail)
    {
        if (disposed) return;
        long writeStarted = Stopwatch.GetTimestamp();
        sampleWriter.WriteLine(JsonUtility.ToJson(new FullGeometryDiagnosticEvent
        {
            schema_version = SchemaVersion,
            record_type = "full_geometry_event_metadata",
            event_id = eventId,
            sampling_mode = samplingMode ?? string.Empty,
            trigger_type = triggerType ?? string.Empty,
            trigger_unity_time = triggerUnityTime,
            trigger_backend_timestamp = triggerBackendTimestamp,
            query_start_unity_time = float.NaN,
            query_end_unity_time = float.NaN,
            query_delay_seconds = float.NaN,
            query_cost_ms = float.NaN,
            write_cost_ms = ElapsedMilliseconds(writeStarted),
            budget_ms = float.NaN,
            budget_exceeded = false,
            query_completed = false,
            result_valid = false,
            status = "event_metadata_recorded",
            skip_reason = string.Empty,
            run_id = runId ?? string.Empty,
            platform_level = platformLevel,
            active_platform_instance_id = platformId,
            geometry_version_id = geometryVersionId ?? string.Empty,
            diagnostic_fingerprint_version_id = string.Empty,
            diagnostic_fingerprint_query_time = float.NaN,
            ordinary_geometry_platform_instance_id = 0,
            ordinary_geometry_active_platform_instance_id = 0,
            ordinary_geometry_version_id = string.Empty,
            ordinary_geometry_active_version_id = string.Empty,
            ordinary_geometry_source_timestamp = float.NaN,
            ordinary_geometry_query_valid = false,
            ordinary_geometry_ownership_valid = false,
            version_association = "unknown",
            version_association_query_time = float.NaN,
            event_detail = detail ?? string.Empty
        }));
        sampleWriter.Flush();
    }

    public long NextFullGeometryEventId()
    {
        return ++fullGeometryEventId;
    }

    private sealed class DeferredFullGeometryEvent
    {
        public long eventId;
        public string samplingMode;
        public string triggerType;
        public float triggerUnityTime;
        public double triggerBackendTimestamp;
        public string runId;
        public int platformLevel;
        public int platformId;
        public string geometryVersionId;
        public string detail;
    }

    private readonly Queue<DeferredFullGeometryEvent> deferredFullGeometryEvents = new Queue<DeferredFullGeometryEvent>();
    private float nextFullGeometryQueryTime;
    private float deferredFullGeometryMinInterval = 0.10f;
    private float fullGeometryBudgetMilliseconds = 1f;

    public void ConfigureFullGeometryEventScheduling(float minInterval, float budgetMilliseconds)
    {
        deferredFullGeometryMinInterval = Mathf.Max(0.01f, minInterval);
        fullGeometryBudgetMilliseconds = Mathf.Max(0.01f, budgetMilliseconds);
    }

    public bool EnqueueDeferredFullGeometryEvent(
        long eventId, string samplingMode, string triggerType, float triggerUnityTime,
        double triggerBackendTimestamp, string runId, int platformLevel, int platformId,
        string geometryVersionId, string detail)
    {
        deferredFullGeometryEvents.Enqueue(new DeferredFullGeometryEvent
        {
            eventId = eventId,
            samplingMode = samplingMode,
            triggerType = triggerType,
            triggerUnityTime = triggerUnityTime,
            triggerBackendTimestamp = triggerBackendTimestamp,
            runId = runId,
            platformLevel = platformLevel,
            platformId = platformId,
            geometryVersionId = geometryVersionId,
            detail = detail
        });
        return true;
    }

    public void ProcessDeferredFullGeometryEvents(
        Transform platform, int platformLevel, Collider ballCollider, Vector3 ballCentre,
        float legacyRadiusEstimate, string legacyRadiusSource, Vector3 platformCentre,
        Vector2 normalizedRadialDirection, float radialDistance, float legacyDirectionalDistance,
        float ballRadius, EndlessPlayerController player, double backendTimestamp, string runId,
        string currentGeometryVersionId)
    {
        if (disposed || deferredFullGeometryEvents.Count == 0 || Time.time < nextFullGeometryQueryTime) return;
        DeferredFullGeometryEvent item = deferredFullGeometryEvents.Peek();
        int currentPlatformId = platform != null ? platform.gameObject.GetInstanceID() : -1;
        if (!string.Equals(item.runId, runId, StringComparison.Ordinal) || item.platformId != currentPlatformId ||
            (!string.IsNullOrEmpty(item.geometryVersionId) && item.geometryVersionId != currentGeometryVersionId))
        {
            deferredFullGeometryEvents.Dequeue();
            RecordFullGeometryEventDeferred(item.eventId, item.samplingMode, item.triggerType,
                item.triggerUnityTime, item.triggerBackendTimestamp, item.runId, item.platformLevel,
                item.platformId, item.geometryVersionId, "deferred_event_platform_or_version_changed");
            return;
        }

        deferredFullGeometryEvents.Dequeue();
        nextFullGeometryQueryTime = Time.time + deferredFullGeometryMinInterval;
        TryRecordFullGeometrySnapshot(item.samplingMode, item.triggerType, item.eventId,
            item.triggerUnityTime, item.triggerBackendTimestamp, platform, platformLevel,
            ballCollider, ballCentre, legacyRadiusEstimate, legacyRadiusSource, platformCentre,
            normalizedRadialDirection, radialDistance, legacyDirectionalDistance, ballRadius,
            player, backendTimestamp, runId, fullGeometryBudgetMilliseconds,
            "deferred_from_event_id;" + (item.detail ?? string.Empty));
    }

    public void RecordFullGeometryEventDeferred(
        long eventId,
        string samplingMode,
        string triggerType,
        float triggerUnityTime,
        double triggerBackendTimestamp,
        string runId,
        int platformLevel,
        int platformId,
        string geometryVersionId,
        string reason)
    {
        if (disposed) return;
        long writeStarted = Stopwatch.GetTimestamp();
        sampleWriter.WriteLine(JsonUtility.ToJson(new FullGeometryDiagnosticEvent
        {
            schema_version = SchemaVersion,
            record_type = "full_geometry_snapshot",
            event_id = eventId,
            sampling_mode = samplingMode ?? string.Empty,
            trigger_type = triggerType ?? string.Empty,
            trigger_unity_time = triggerUnityTime,
            trigger_backend_timestamp = triggerBackendTimestamp,
            query_start_unity_time = float.NaN,
            query_end_unity_time = float.NaN,
            query_delay_seconds = float.NaN,
            query_cost_ms = float.NaN,
            write_cost_ms = ElapsedMilliseconds(writeStarted),
            budget_ms = float.NaN,
            budget_exceeded = false,
            query_completed = false,
            result_valid = false,
            status = "skipped",
            skip_reason = reason ?? "deferred",
            run_id = runId ?? string.Empty,
            platform_level = platformLevel,
            active_platform_instance_id = platformId,
            geometry_version_id = geometryVersionId ?? string.Empty,
            ordinary_geometry_version_id = ordinaryGeometryVersionId,
            ordinary_geometry_active_version_id = ordinaryGeometryActiveVersionId,
            ordinary_geometry_source_timestamp = ordinaryGeometrySourceTimestamp,
            ordinary_geometry_query_valid = ordinaryGeometryQueryValid,
            ordinary_geometry_ownership_valid = ordinaryGeometryOwnershipValid,
            version_association = "unknown",
            version_association_query_time = ordinaryGeometryAssociationQueryTime,
            event_detail = "event_metadata_preserved"
        }));
        sampleWriter.Flush();
    }

    public bool TryRecordFullGeometrySnapshot(
        string samplingMode,
        string triggerType,
        long eventId,
        float triggerUnityTime,
        double triggerBackendTimestamp,
        Transform platform,
        int platformLevel,
        Collider ballCollider,
        Vector3 ballCentre,
        float legacyRadiusEstimate,
        string legacyRadiusSource,
        Vector3 platformCentre,
        Vector2 normalizedRadialDirection,
        float radialDistance,
        float legacyDirectionalDistance,
        float ballRadius,
        EndlessPlayerController player,
        double backendTimestamp,
        string runId,
        float budgetMilliseconds,
        string detail)
    {
        if (disposed || platform == null)
        {
            RecordFullGeometryEventMetadata(eventId, samplingMode, triggerType, triggerUnityTime, triggerBackendTimestamp,
                runId, platformLevel, platform != null ? platform.gameObject.GetInstanceID() : -1, string.Empty,
                string.IsNullOrEmpty(detail) ? "query_not_started_platform_missing" : detail);
            RecordFullGeometryEventDeferred(eventId, samplingMode, triggerType, triggerUnityTime,
                triggerBackendTimestamp, runId, platformLevel, -1, string.Empty, "platform_missing_query_not_started");
            return false;
        }

        float queryStartUnity = Time.time;
        long queryStarted = Stopwatch.GetTimestamp();
        bool completed = false;
        bool valid = false;
        string reason = string.Empty;
        DiagnosticSample querySample = null;
        try
        {
            completed = TryRecordSample(
                platform, platformLevel, ballCollider, ballCentre, legacyRadiusEstimate, legacyRadiusSource,
                platformCentre, normalizedRadialDirection, radialDistance, legacyDirectionalDistance, ballRadius,
                player, backendTimestamp, runId, true);
            querySample = lastFullDiagnosticSample;
            valid = completed && geometryCacheValid && lastGeometryPlatformInstanceId == platform.gameObject.GetInstanceID() &&
                    !string.IsNullOrEmpty(lastGeometryVersionId) && querySample != null;
            if (!completed) reason = "query_not_completed";
            else if (!valid) reason = "query_result_invalid";
        }
        catch (Exception exception)
        {
            reason = "query_exception:" + exception.GetType().Name;
        }

        float queryCost = ElapsedMilliseconds(queryStarted);
        lastFullGeometryQueryCostMs = queryCost;
        float queryEndUnity = Time.time;
        bool hasHoleGeometry = valid && querySample.hole_geometry_valid;
        float targetHoleDistance = hasHoleGeometry
            ? querySample.hole_boundary_signed_distance_from_ball_centre + querySample.computed_world_hole_radius
            : float.NaN;
        float holeWorldRadius = hasHoleGeometry ? querySample.computed_world_hole_radius : float.NaN;
        float fullDirectionalEdgeDistance = valid && querySample.actual_boundary_query_valid
            ? querySample.actual_boundary_signed_distance_from_ball_centre
            : float.NaN;
        bool fullDirectionalEdgeValid = valid && querySample.actual_boundary_query_valid;
        FullGeometryDiagnosticEvent record = new FullGeometryDiagnosticEvent
        {
            schema_version = SchemaVersion,
            record_type = "full_geometry_snapshot",
            event_id = eventId,
            sampling_mode = samplingMode ?? string.Empty,
            trigger_type = triggerType ?? string.Empty,
            trigger_unity_time = triggerUnityTime,
            trigger_backend_timestamp = triggerBackendTimestamp,
            query_start_unity_time = queryStartUnity,
            query_end_unity_time = queryEndUnity,
            query_delay_seconds = queryStartUnity - triggerUnityTime,
            query_cost_ms = queryCost,
            diagnostic_boundary_stage_ms = querySample != null ? querySample.boundary_query_cost_ms : float.NaN,
            diagnostic_support_stage_ms = querySample != null ? querySample.support_query_cost_ms : float.NaN,
            diagnostic_hole_geometry_stage_ms = querySample != null ? querySample.diagnostic_hole_geometry_stage_ms : float.NaN,
            diagnostic_fingerprint_stage_ms = querySample != null ? querySample.diagnostic_fingerprint_stage_ms : float.NaN,
            diagnostic_identity_extra_query_ms = querySample != null ? querySample.diagnostic_identity_extra_query_ms : float.NaN,
            diagnostic_metadata_stage_ms = querySample != null ? querySample.diagnostic_metadata_cost_ms : float.NaN,
            diagnostic_full_query_total_ms = querySample != null ? querySample.diagnostic_total_cost_ms : float.NaN,
            diagnostic_write_total_ms = querySample != null ? lastFullGeometryWriteCostMs : float.NaN,
            frame_delta_time_ms = querySample != null ? querySample.frame_delta_time_ms : float.NaN,
            frame_unscaled_delta_time_ms = querySample != null ? querySample.frame_unscaled_delta_time_ms : float.NaN,
            frame_smooth_delta_time_ms = querySample != null ? querySample.frame_smooth_delta_time_ms : float.NaN,
            budget_ms = budgetMilliseconds,
            budget_exceeded = completed && queryCost > budgetMilliseconds,
            query_completed = completed,
            result_valid = valid,
            write_cost_ms = float.NaN,
            status = valid ? "completed" : "skipped",
            skip_reason = valid ? string.Empty : reason,
            run_id = runId ?? string.Empty,
            platform_level = platformLevel,
            active_platform_instance_id = platform.gameObject.GetInstanceID(),
            geometry_version_id = valid ? lastGeometryVersionId : string.Empty,
            diagnostic_fingerprint_version_id = valid ? lastGeometryVersionId : string.Empty,
            diagnostic_fingerprint_query_time = valid ? queryStartUnity : float.NaN,
            ordinary_geometry_platform_instance_id = ordinaryGeometryAssociationQueryTime >= 0f &&
                Mathf.Abs(ordinaryGeometryAssociationQueryTime - queryStartUnity) <= 0.001f &&
                ordinaryGeometryQueryValid && ordinaryGeometryOwnershipValid &&
                ordinaryGeometryPlatformInstanceId == platform.gameObject.GetInstanceID()
                ? ordinaryGeometryPlatformInstanceId : 0,
            ordinary_geometry_active_platform_instance_id = ordinaryGeometryAssociationQueryTime >= 0f &&
                Mathf.Abs(ordinaryGeometryAssociationQueryTime - queryStartUnity) <= 0.001f &&
                ordinaryGeometryPlatformInstanceId == platform.gameObject.GetInstanceID()
                ? ordinaryGeometryActivePlatformInstanceId : 0,
            ordinary_geometry_version_id = ordinaryGeometryAssociationQueryTime >= 0f &&
                Mathf.Abs(ordinaryGeometryAssociationQueryTime - queryStartUnity) <= 0.001f &&
                ordinaryGeometryQueryValid && ordinaryGeometryOwnershipValid &&
                ordinaryGeometryPlatformInstanceId == platform.gameObject.GetInstanceID()
                ? ordinaryGeometryVersionId : string.Empty,
            ordinary_geometry_active_version_id = ordinaryGeometryAssociationQueryTime >= 0f &&
                Mathf.Abs(ordinaryGeometryAssociationQueryTime - queryStartUnity) <= 0.001f &&
                ordinaryGeometryQueryValid && ordinaryGeometryOwnershipValid &&
                ordinaryGeometryPlatformInstanceId == platform.gameObject.GetInstanceID()
                ? ordinaryGeometryActiveVersionId : string.Empty,
            ordinary_geometry_source_timestamp = ordinaryGeometryAssociationQueryTime >= 0f &&
                Mathf.Abs(ordinaryGeometryAssociationQueryTime - queryStartUnity) <= 0.001f &&
                ordinaryGeometryQueryValid && ordinaryGeometryOwnershipValid &&
                ordinaryGeometryPlatformInstanceId == platform.gameObject.GetInstanceID()
                ? ordinaryGeometrySourceTimestamp : float.NaN,
            ordinary_geometry_query_valid = ordinaryGeometryAssociationQueryTime >= 0f &&
                Mathf.Abs(ordinaryGeometryAssociationQueryTime - queryStartUnity) <= 0.001f &&
                ordinaryGeometryPlatformInstanceId == platform.gameObject.GetInstanceID() && ordinaryGeometryQueryValid,
            ordinary_geometry_ownership_valid = ordinaryGeometryAssociationQueryTime >= 0f &&
                Mathf.Abs(ordinaryGeometryAssociationQueryTime - queryStartUnity) <= 0.001f &&
                ordinaryGeometryPlatformInstanceId == platform.gameObject.GetInstanceID() && ordinaryGeometryOwnershipValid,
            version_association = ordinaryGeometryAssociationQueryTime >= 0f &&
                                  Mathf.Abs(ordinaryGeometryAssociationQueryTime - queryStartUnity) <= 0.001f &&
                                  ordinaryGeometryQueryValid && ordinaryGeometryOwnershipValid &&
                                  ordinaryGeometryPlatformInstanceId == platform.gameObject.GetInstanceID()
                ? "same_platform_instance_independent_versions"
                : "unknown",
            version_association_query_time = ordinaryGeometryAssociationQueryTime,
            ball_centre = ballCentre,
            ball_radius = ballRadius,
            directional_edge_distance = fullDirectionalEdgeDistance,
            directional_edge_valid = fullDirectionalEdgeValid,
            target_hole_distance = targetHoleDistance,
            target_hole_radius = holeWorldRadius,
            hole_geometry_valid = hasHoleGeometry,
            hole_boundary_signed_distance = hasHoleGeometry ? querySample.hole_boundary_signed_distance_from_ball_centre : float.NaN,
            footprint_support_result = valid ? querySample.footprint_support_result : "unknown",
            footprint_support_query_valid = valid && querySample.footprint_support_query_valid,
            footprint_support_hit_count = valid ? querySample.footprint_support_hit_count : -1,
            support_platform_instance_id = valid ? querySample.generic_support_contact_platform_id : int.MinValue,
            support_fixed_time = valid ? querySample.generic_support_last_contact_fixed_time : float.NaN,
            event_detail = detail ?? string.Empty
        };
        record.query_completed = completed;
        record.result_valid = valid && querySample != null && querySample.actual_boundary_query_valid &&
                              querySample.hole_geometry_valid && querySample.footprint_support_query_valid;
        if (!completed)
        {
            record.status = "skipped";
            if (string.IsNullOrEmpty(record.skip_reason)) record.skip_reason = reason;
        }
        else if (!record.result_valid)
        {
            record.status = "skipped";
            record.skip_reason = "required_geometry_or_support_invalid";
        }
        else
        {
            record.status = "completed";
            record.skip_reason = string.Empty;
            record.footprint_support_result = querySample.footprint_support_result;
            record.footprint_support_query_valid = querySample.footprint_support_query_valid;
            record.footprint_support_hit_count = querySample.footprint_support_hit_count;
        }
        long fullSnapshotWriteStarted = Stopwatch.GetTimestamp();
        sampleWriter.WriteLine(JsonUtility.ToJson(record));
        sampleWriter.Flush();
        float snapshotWriteCostMs = ElapsedMilliseconds(fullSnapshotWriteStarted);
        WriteFullGeometryWriteCost(eventId, samplingMode, triggerType, triggerUnityTime, runId, snapshotWriteCostMs);
        return valid;
    }
    private void WriteFullGeometryWriteCost(long eventId, string samplingMode, string triggerType, float triggerUnityTime, string runId, float writeCostMs)
    {
        long writeStarted = Stopwatch.GetTimestamp();
        sampleWriter.WriteLine(JsonUtility.ToJson(new FullGeometryDiagnosticEvent
        {
            schema_version = SchemaVersion,
            record_type = "full_geometry_write_cost",
            event_id = eventId,
            sampling_mode = samplingMode ?? string.Empty,
            trigger_type = triggerType ?? string.Empty,
            trigger_unity_time = triggerUnityTime,
            query_cost_ms = float.NaN,
            diagnostic_write_total_ms = writeCostMs,
            write_cost_ms = writeCostMs,
            query_completed = true,
            result_valid = true,
            status = "write_cost_recorded",
            run_id = runId ?? string.Empty
        }));
        sampleWriter.Flush();
    }

    public bool TryRecordSample(
        Transform platform,
        int platformLevel,
        Collider ballCollider,
        Vector3 ballCentre,
        float legacyRadiusEstimate,
        string legacyRadiusSource,
        Vector3 legacyPlatformCentre,
        Vector2 normalizedRadialDirection,
        float legacyRadialDistance,
        float legacyDirectionalDistance,
        float ballWorldRadiusEstimate,
        EndlessPlayerController player,
        double backendTimestamp,
        string runId,
        bool force)
    {


        if (disposed || platform == null) return false;
        float now = Time.time;
        if (!force && now < nextSampleTime) return false;
        nextSampleTime = now + sampleInterval;
        string assetIdentity;
        string assetPath;
        string assetGuid;
        GetAssetIdentity(platform.gameObject, out assetIdentity, out assetPath, out assetGuid);
        long fingerprintStarted = Stopwatch.GetTimestamp();
        string fingerprint = BuildGeometryFingerprint(platform);
        float fingerprintCostMs = ElapsedMilliseconds(fingerprintStarted);
        bool geometryChanged = fingerprint != lastGeometryFingerprint;
        if (geometryChanged)
        {
            geometryVersion++;
            geometryVersionId = platform.gameObject.GetInstanceID() + "-g" + geometryVersion.ToString(CultureInfo.InvariantCulture);
            lastGeometryFingerprint = fingerprint;
            GeometryChangeRecord detail = BuildGeometryChangeRecord(
                platform, platformLevel, assetIdentity, assetPath, assetGuid, fingerprint);
            geometryWriter.WriteLine(JsonUtility.ToJson(detail));
            geometryWriter.Flush();
        }
        if (terminalSnapshot != null) terminalSnapshot.geometry_version_id = geometryVersionId;

        long holeGeometryStarted = Stopwatch.GetTimestamp();
        PlatformData data = platform.GetComponent<PlatformData>();
        Transform holeCentre = data != null ? data.holeCenter : null;
        bool hasTargetHole = data != null && holeCentre != null;
        float authoredHoleRadius = data != null ? data.holeRadius : float.NaN;
        Vector3 holeScaleInputs = platform.lossyScale;
        float holeRadiusCandidate = data != null && IsFinite(authoredHoleRadius)
            ? authoredHoleRadius * Mathf.Max(Mathf.Abs(holeScaleInputs.x), Mathf.Abs(holeScaleInputs.z))
            : float.NaN;
        bool holeGeometryValid = HasIndependentlyPlausibleHoleGeometry(platform, data, holeRadiusCandidate, out string holeGeometrySource);
        float computedWorldHoleRadius = holeGeometryValid ? holeRadiusCandidate : float.NaN;
        float holeGeometryCostMs = ElapsedMilliseconds(holeGeometryStarted);

        long boundaryStarted = Stopwatch.GetTimestamp();
        BoundaryQueryResult boundary = QueryOuterBoundary(
            platform, legacyPlatformCentre, normalizedRadialDirection, legacyRadialDistance,
            boundaryScanSamples, boundaryRefinementSteps);
        boundary.queryCostMilliseconds = ElapsedMilliseconds(boundaryStarted);
        float signedError = boundary.valid && IsFinite(legacyDirectionalDistance)
            ? boundary.signedDistanceFromCentre - legacyDirectionalDistance
            : float.NaN;

        long supportStarted = Stopwatch.GetTimestamp();
        FootprintSupportResult support = QueryFootprintSupport(
            platform, ballCollider, ballCentre, ballWorldRadiusEstimate);
        support.queryCostMilliseconds = ElapsedMilliseconds(supportStarted);

        long metadataStarted = Stopwatch.GetTimestamp();
        ColliderGeometry ballGeometry = DescribeBallCollider(ballCollider);
        float warningTransitionTime = player != null ? player.DiagnosticWarningTransitionTime : float.NaN;
        double warningTransitionBackend = player != null ? player.DiagnosticWarningTransitionBackendTimestamp : double.NaN;
        float contactTransitionTime = player != null ? player.DiagnosticEdgeContactTransitionTime : float.NaN;
        double contactTransitionBackend = player != null ? player.DiagnosticEdgeContactTransitionBackendTimestamp : double.NaN;
        float supportLostTime = player != null ? player.SupportLostTime : float.NaN;
        double supportLostBackend = player != null ? player.SupportLostBackendTimestamp : double.NaN;
        float fallTime = player != null ? player.FallEventTime : float.NaN;
        double fallBackend = player != null ? player.FallEventBackendTimestamp : double.NaN;
        float metadataCost = ElapsedMilliseconds(metadataStarted);
        float totalQueryCost = ElapsedMilliseconds(fingerprintStarted);
        lastFullGeometryQueryCostMs = totalQueryCost;
        float genericSupportHeight = float.NaN;
        bool genericBallBelowSupportHeight = player != null && player.IsBelowCurrentSupportHeight(out genericSupportHeight);

        geometryCacheValid = true;
        geometryCacheState = "valid_full_geometry_sample";
        lastGeometrySampleTime = now;
        lastGeometryPlatformInstanceId = platform.gameObject.GetInstanceID();
        lastGeometryVersionId = geometryVersionId;
        DiagnosticSample sample = new DiagnosticSample
        {
            schema_version = SchemaVersion,
            sample_sequence = ++sampleSequence,
            unity_time = now,
            backend_timestamp = backendTimestamp,
            platform_level = platformLevel,
            active_platform_instance_id = platform.gameObject.GetInstanceID(),
            platform_asset_identity = assetIdentity,
            platform_asset_path = assetPath,
            platform_asset_guid = assetGuid,
            run_id = runId ?? string.Empty,
            geometry_version_id = geometryVersionId,
            platform_centre = legacyPlatformCentre,
            ball_centre = ballCentre,
            ball_collider_instance_id = ballGeometry.collider_instance_id,
            ball_collider_name = ballGeometry.collider_name,
            ball_collider_type = ballGeometry.collider_type,
            ball_collider_enabled = ballGeometry.enabled,
            ball_collider_is_trigger = ballGeometry.is_trigger,
            ball_collider_local_scale = ballGeometry.local_scale,
            ball_collider_lossy_scale = ballGeometry.lossy_scale,
            ball_collider_bounds_min = ballGeometry.bounds_min,
            ball_collider_bounds_max = ballGeometry.bounds_max,
            ball_collider_bounds_extents = (ballGeometry.bounds_max - ballGeometry.bounds_min) * 0.5f,
            ball_world_radius_estimate = ballWorldRadiusEstimate,
            ball_shape_parameters = GetBallShapeParameters(ballCollider),
            legacy_radius_estimate = legacyRadiusEstimate,
            legacy_radius_source = legacyRadiusSource,
            legacy_radial_distance = legacyRadialDistance,
            normalized_radial_direction = normalizedRadialDirection,
            legacy_directional_distance = legacyDirectionalDistance,
            has_target_hole = hasTargetHole,
            root_platform_data_present = data != null,
            hole_center_present = holeCentre != null,
            platform_data_instance_id = data != null ? data.GetInstanceID() : 0,
            hole_center_instance_id = holeCentre != null ? holeCentre.GetInstanceID() : 0,
            hole_center_world_position = holeCentre != null ? holeCentre.position : Vector3.one * float.NaN,
            authored_hole_radius = authoredHoleRadius,
            authored_hole_radius_units = data != null ? "platform_local_scale_units (PlatformData Tooltip)" : "unknown",
            hole_radius_scale_inputs = holeScaleInputs,
            computed_world_hole_radius = computedWorldHoleRadius,
            computed_world_hole_radius_candidate = holeRadiusCandidate,
            hole_geometry_valid = holeGeometryValid,
            hole_geometry_source = holeGeometrySource,
            boundary_query_method = BoundaryMethod,
            actual_boundary_query_valid = boundary.valid,
            actual_boundary_query_invalid_reason = boundary.invalidReason,
            actual_boundary_hit_collider_instance_id = boundary.hitColliderId,
            actual_boundary_hit_collider_name = boundary.hitColliderName,
            actual_boundary_point = boundary.valid ? boundary.boundaryPoint : Vector3.one * float.NaN,
            actual_boundary_radius = boundary.valid ? boundary.boundaryRadius : float.NaN,
            actual_boundary_signed_distance_from_ball_centre = boundary.valid ? boundary.signedDistanceFromCentre : float.NaN,
            ball_surface_clearance_to_outer_edge = boundary.valid && IsFinite(ballWorldRadiusEstimate)
                ? boundary.boundaryRadius - legacyRadialDistance - ballWorldRadiusEstimate : float.NaN,
            hole_boundary_signed_distance_from_ball_centre = holeGeometryValid && holeCentre != null
                ? new Vector2(ballCentre.x - holeCentre.position.x, ballCentre.z - holeCentre.position.z).magnitude - computedWorldHoleRadius
                : float.NaN,
            actual_boundary_signed_error_vs_legacy = signedError,
            boundary_query_cost_ms = boundary.queryCostMilliseconds,
            boundary_query_ray_count = boundary.rayCount,
            support_query_method = SupportMethod,
            footprint_support_result = !support.valid ? "unknown" : support.hasSupport ? "yes" : "no",
            footprint_support_query_valid = support.valid,
            footprint_support_hit_count = support.hitCount,
            footprint_support_sample_count = support.sampleCount,
            footprint_support_hit_collider_instance_id = support.hitColliderId,
            footprint_support_hit_collider_name = support.hitColliderName,
            footprint_support_contact_point = support.valid && support.hasSupport ? support.contactPoint : Vector3.one * float.NaN,
            footprint_support_surface_height = support.valid && support.hasSupport ? support.surfaceHeight : float.NaN,
            footprint_support_normal = support.valid && support.hasSupport ? support.normal : Vector3.one * float.NaN,
            support_query_cost_ms = support.queryCostMilliseconds,
            support_query_ray_count = support.rayCount,
            diagnostic_metadata_cost_ms = metadataCost,
            diagnostic_total_cost_ms = totalQueryCost,
            diagnostic_query_cost_ms = totalQueryCost,
            diagnostic_write_cost_ms = lastFullGeometryWriteCostMs,
            diagnostic_identity_extra_query_ms = pendingIdentityQueryCostMilliseconds,
            diagnostic_fingerprint_stage_ms = fingerprintCostMs,
            diagnostic_hole_geometry_stage_ms = holeGeometryCostMs,
            frame_delta_time_ms = Time.deltaTime * 1000f,
            frame_unscaled_delta_time_ms = Time.unscaledDeltaTime * 1000f,
            frame_smooth_delta_time_ms = Time.smoothDeltaTime * 1000f,
            generic_support_contact_state = player != null ? player.SupportContactState : "UNKNOWN",
            generic_support_contact_platform_id = player != null ? player.DiagnosticSupportContactPlatformId : 0,
            generic_support_last_contact_fixed_time = player != null ? player.DiagnosticLastSupportContactFixedTime : float.NaN,
            generic_ball_below_support_height = genericBallBelowSupportHeight,
            generic_support_height = genericSupportHeight,
            support_lost_predicate_radial_distance = player != null ? player.DiagnosticRadialDistance : float.NaN,
            support_lost_predicate_boundary_radius = player != null ? player.DiagnosticSupportBoundaryRadius : float.NaN,
            support_lost_predicate_inside_hole_opening = player != null && player.DiagnosticInsideHoleOpening,
            support_lost_predicate_result = player != null && (player.DiagnosticBeyondOuterEdge || player.DiagnosticCrossedSupportBoundary),
            warning_predicate_radial_distance = player != null ? player.DiagnosticWarningRadialDistance : float.NaN,
            warning_predicate_radius = player != null ? player.DiagnosticWarningPredicateRadius : float.NaN,
            warning_predicate_near_edge = player != null && player.DiagnosticWarningNearEdge,
            warning_state_before_transition = player != null && player.DiagnosticWarningStateBeforeTransition,
            warning_state_after_transition = player != null && player.EdgeWarningState,
            warning_transition_unity_time = warningTransitionTime,
            warning_transition_backend_timestamp = warningTransitionBackend,
            edge_contact_predicate_radial_distance = player != null ? player.DiagnosticEdgeContactRadialDistance : float.NaN,
            edge_contact_predicate_radius = player != null ? player.DiagnosticEdgeContactPredicateRadius : float.NaN,
            edge_contact_predicate_result = player != null && player.DiagnosticEdgeContactPredicateResult,
            edge_contact_transition_unity_time = contactTransitionTime,
            edge_contact_transition_backend_timestamp = contactTransitionBackend,
            support_lost_transition = !float.IsNaN(supportLostTime),
            support_lost_transition_unity_time = supportLostTime,
            support_lost_transition_backend_timestamp = supportLostBackend,
            fall_predicate_committed = !float.IsNaN(fallTime),
            fall_transition_unity_time = fallTime,
            fall_transition_backend_timestamp = fallBackend,
            fall_predicate_inside_hole_opening = player != null && player.DiagnosticInsideHoleOpening,
            fall_predicate_beyond_outer_edge = player != null && player.DiagnosticBeyondOuterEdge,
            fall_predicate_crossed_support_boundary = player != null && player.DiagnosticCrossedSupportBoundary,
            event_snapshot_valid = terminalSnapshot != null && terminalSnapshot.valid,
            event_geometry_version_id = terminalSnapshot != null ? terminalSnapshot.geometry_version_id : string.Empty,
            event_platform_instance_id = terminalSnapshot != null ? terminalSnapshot.event_platform_instance_id : -1,
            event_layer = terminalSnapshot != null ? terminalSnapshot.event_layer : -1,
            event_platform_asset_identity = terminalSnapshot != null ? terminalSnapshot.event_platform_asset_identity : string.Empty,
            event_ball_centre = terminalSnapshot != null ? terminalSnapshot.event_ball_centre : Vector3.one * float.NaN,
            event_time = terminalSnapshot != null ? terminalSnapshot.event_time : float.NaN,
            event_backend_timestamp = terminalSnapshot != null ? terminalSnapshot.event_backend_timestamp : double.NaN
        };

        // These measurements cover collider metadata lookup plus direct collider ray queries;
        // file I/O is intentionally not represented as query/frame cost.
        sample.boundary_query_cost_ms += metadataCost * 0f;
        lastFullDiagnosticSample = sample;
        pendingIdentityQueryCostMilliseconds = float.NaN;
        long fullSampleWriteStarted = Stopwatch.GetTimestamp();
        sampleWriter.WriteLine(JsonUtility.ToJson(sample));
        sampleWriter.Flush();
        lastFullGeometryWriteCostMs = ElapsedMilliseconds(fullSampleWriteStarted);
        WriteFullGeometryWriteCost(sample.sample_sequence, "periodic_full", "periodic_full", now, runId, lastFullGeometryWriteCostMs);
        if (terminalSnapshot != null && terminalSnapshot.valid && force)
        {
            sampleWriter.WriteLine(JsonUtility.ToJson(terminalSnapshot));
            terminalSnapshot = null;
        }
        return true;
    }

    public void CaptureTerminalEvent(
        string eventName,
        Transform platform,
        int eventLayer,
        EndlessPlayerController player,
        Collider ballCollider,
        Vector3 ballCentre,
        float legacyRadiusEstimate,
        float legacyDirectionalDistance)
    {
        if (disposed) return;
        string assetIdentity;
        string assetPath;
        string assetGuid;
        GetAssetIdentity(platform != null ? platform.gameObject : null, out assetIdentity, out assetPath, out assetGuid);
        terminalSnapshot = new TerminalEventSnapshot
        {
            valid = platform != null,
            event_name = eventName,
            run_id = currentRunId,
            geometry_version_id = geometryVersionId,
            event_time = Time.time,
            event_backend_timestamp = UDPManager.GetBackendUnixTimestamp(),
            event_platform_instance_id = platform != null ? platform.gameObject.GetInstanceID() : -1,
            event_layer = eventLayer,
            last_support_platform_instance_id = player != null ? player.DiagnosticSupportContactPlatformId : int.MinValue,
            last_support_fixed_time = player != null ? player.DiagnosticLastSupportContactFixedTime : float.NaN,
            transition_old_support_platform_instance_id = transitionEvidenceValid ? transitionLastSupportPlatformInstanceId : int.MinValue,
            transition_old_support_fixed_time = transitionEvidenceValid ? transitionLastSupportFixedTime : float.NaN,
            transition_from_layer = transitionEvidenceValid ? transitionFromLayer : -1,
            transition_to_layer = transitionEvidenceValid ? transitionToLayer : -1,
            transition_from_platform_instance_id = transitionEvidenceValid ? transitionFromPlatformInstanceId : -1,
            transition_to_platform_instance_id = transitionEvidenceValid ? transitionToPlatformInstanceId : -1,
            event_platform_asset_identity = assetIdentity,
            event_platform_asset_path = assetPath,
            event_platform_asset_guid = assetGuid,
            event_ball_centre = ballCentre,
            event_ball_collider_instance_id = ballCollider != null ? ballCollider.GetInstanceID() : 0,
            event_radial_distance = player != null ? player.DiagnosticRadialDistance : float.NaN,
            event_legacy_radius_estimate = legacyRadiusEstimate,
            event_legacy_directional_distance = legacyDirectionalDistance,
            event_player_radius = player != null ? player.DiagnosticPlayerRadius : float.NaN,
            event_support_boundary_radius = player != null ? player.DiagnosticSupportBoundaryRadius : float.NaN,
            event_inside_hole_opening = player != null && player.DiagnosticInsideHoleOpening,
            event_beyond_outer_edge_predicate = player != null && player.DiagnosticBeyondOuterEdge,
            event_crossed_support_boundary_predicate = player != null && player.DiagnosticCrossedSupportBoundary,
            event_terminal_fall_predicate_committed = true
        };
    }

    public static BoundaryQueryResult QueryOuterBoundary(
        Transform platform,
        Vector3 platformCentre,
        Vector2 radialDirection,
        float ballRadialDistance,
        int scanSamples = 64,
        int refinementSteps = 8)
    {
        long started = Stopwatch.GetTimestamp();
        BoundaryQueryResult result = new BoundaryQueryResult
        {
            valid = false,
            invalidReason = "unknown",
            hitColliderId = 0,
            hitColliderName = string.Empty,
            boundaryPoint = Vector3.one * float.NaN,
            boundaryRadius = float.NaN,
            signedDistanceFromCentre = float.NaN,
            rayCount = 0
        };
        if (platform == null)
        {
            result.invalidReason = "platform_missing";
            result.queryCostMilliseconds = ElapsedMilliseconds(started);
            return result;
        }

        Vector2 direction = radialDirection.sqrMagnitude > 0.000001f ? radialDirection.normalized : Vector2.right;
        Collider[] colliders = platform.GetComponentsInChildren<Collider>(true);
        List<Collider> eligible = GetEligibleColliders(colliders);
        if (eligible.Count == 0)
        {
            result.invalidReason = "no_enabled_nontrigger_active_platform_colliders";
            result.queryCostMilliseconds = ElapsedMilliseconds(started);
            return result;
        }

        float minY = float.PositiveInfinity;
        float maxY = float.NegativeInfinity;
        float searchExtent = 0f;
        foreach (Collider collider in eligible)
        {
            Bounds bounds = collider.bounds;
            minY = Mathf.Min(minY, bounds.min.y);
            maxY = Mathf.Max(maxY, bounds.max.y);
            float rx = Mathf.Abs(bounds.center.x - platformCentre.x) + bounds.extents.x;
            float rz = Mathf.Abs(bounds.center.z - platformCentre.z) + bounds.extents.z;
            searchExtent = Mathf.Max(searchExtent, Mathf.Sqrt(rx * rx + rz * rz));
        }
        if (!IsFinite(searchExtent) || searchExtent <= 0f || !IsFinite(minY) || !IsFinite(maxY))
        {
            result.invalidReason = "collider_bounds_unknown";
            result.queryCostMilliseconds = ElapsedMilliseconds(started);
            return result;
        }

        float verticalStart = maxY + Mathf.Max(0.25f, (maxY - minY) * 0.1f);
        float verticalDistance = Mathf.Max(0.5f, maxY - minY + Mathf.Max(0.5f, (maxY - minY) * 0.2f));
        float outsideRadius = searchExtent + Mathf.Max(0.1f, searchExtent / Mathf.Max(16, scanSamples));
        float lastOutsideRadius = outsideRadius;
        float firstInsideRadius = float.NaN;
        RaycastHit firstInsideHit = default;
        int steps = Mathf.Clamp(scanSamples, 16, 256);

        for (int i = 0; i <= steps; i++)
        {
            float radius = searchExtent * (1f - (float)i / steps);
            if (TryVerticalHit(eligible, platformCentre, direction, radius, verticalStart, verticalDistance, out RaycastHit hit))
            {
                result.rayCount++;
                firstInsideRadius = radius;
                firstInsideHit = hit;
                break;
            }
            result.rayCount++;
            lastOutsideRadius = radius;
        }

        if (float.IsNaN(firstInsideRadius))
        {
            result.invalidReason = "no_collider_hit_along_radial_vertical_probe";
            result.queryCostMilliseconds = ElapsedMilliseconds(started);
            return result;
        }

        float insideRadius = firstInsideRadius;
        float outside = Mathf.Max(insideRadius, lastOutsideRadius);
        if (outside - insideRadius <= 0.00001f) outside = insideRadius + searchExtent / steps;
        RaycastHit boundaryHit = firstInsideHit;
        int refinements = Mathf.Clamp(refinementSteps, 4, 16);
        for (int i = 0; i < refinements; i++)
        {
            float mid = (insideRadius + outside) * 0.5f;
            if (TryVerticalHit(eligible, platformCentre, direction, mid, verticalStart, verticalDistance, out RaycastHit hit))
            {
                result.rayCount++;
                insideRadius = mid;
                boundaryHit = hit;
            }
            else
            {
                result.rayCount++;
                outside = mid;
            }
        }

        float estimatedBoundaryRadius = (insideRadius + outside) * 0.5f;
        result.valid = boundaryHit.collider != null;
        result.invalidReason = result.valid ? string.Empty : "refinement_hit_missing";
        result.hitColliderId = result.valid ? boundaryHit.collider.GetInstanceID() : 0;
        result.hitColliderName = result.valid ? boundaryHit.collider.name : string.Empty;
        result.boundaryRadius = result.valid ? estimatedBoundaryRadius : float.NaN;
        result.boundaryPoint = result.valid
            ? new Vector3(platformCentre.x + direction.x * estimatedBoundaryRadius, boundaryHit.point.y,
                platformCentre.z + direction.y * estimatedBoundaryRadius)
            : Vector3.one * float.NaN;
        result.signedDistanceFromCentre = result.valid ? estimatedBoundaryRadius - ballRadialDistance : float.NaN;
        result.queryCostMilliseconds = ElapsedMilliseconds(started);
        return result;
    }

    public static FootprintSupportResult QueryFootprintSupport(
        Transform platform,
        Collider ballCollider,
        Vector3 ballCentre,
        float ballWorldRadius)
    {
        long started = Stopwatch.GetTimestamp();
        FootprintSupportResult result = new FootprintSupportResult
        {
            valid = false,
            hasSupport = false,
            hitCount = 0,
            sampleCount = 9,
            hitColliderId = 0,
            hitColliderName = string.Empty,
            contactPoint = Vector3.one * float.NaN,
            surfaceHeight = float.NaN,
            normal = Vector3.one * float.NaN,
            rayCount = 0
        };
        if (platform == null || ballCollider == null || !IsFinite(ballWorldRadius) || ballWorldRadius <= 0f)
        {
            result.queryCostMilliseconds = ElapsedMilliseconds(started);
            return result;
        }

        List<Collider> eligible = GetEligibleColliders(platform.GetComponentsInChildren<Collider>(true));
        if (eligible.Count == 0)
        {
            result.queryCostMilliseconds = ElapsedMilliseconds(started);
            return result;
        }

        float minY = float.PositiveInfinity;
        float maxY = float.NegativeInfinity;
        foreach (Collider collider in eligible)
        {
            minY = Mathf.Min(minY, collider.bounds.min.y);
            maxY = Mathf.Max(maxY, collider.bounds.max.y);
        }
        if (!IsFinite(minY) || !IsFinite(maxY))
        {
            result.queryCostMilliseconds = ElapsedMilliseconds(started);
            return result;
        }

        result.valid = true;
        float rayStartY = Mathf.Max(ballCentre.y + ballWorldRadius + 0.05f, maxY + 0.1f);
        float rayDistance = Mathf.Max(0.5f, rayStartY - minY + 0.25f);
        const float footprintScale = 0.8f;
        Vector2[] offsets =
        {
            Vector2.zero,
            new Vector2(1f, 0f), new Vector2(-1f, 0f),
            new Vector2(0f, 1f), new Vector2(0f, -1f),
            new Vector2(0.70710678f, 0.70710678f), new Vector2(-0.70710678f, 0.70710678f),
            new Vector2(0.70710678f, -0.70710678f), new Vector2(-0.70710678f, -0.70710678f)
        };
        float highestHitY = float.NegativeInfinity;
        for (int sampleIndex = 0; sampleIndex < offsets.Length; sampleIndex++)
        {
            Vector2 offset = offsets[sampleIndex] * (ballWorldRadius * footprintScale);
            Vector3 origin = new Vector3(ballCentre.x + offset.x, rayStartY, ballCentre.z + offset.y);
            Ray ray = new Ray(origin, Vector3.down);
            foreach (Collider collider in eligible)
            {
                result.rayCount++;
                if (!collider.Raycast(ray, out RaycastHit hit, rayDistance)) continue;
                result.hitCount++;
                if (hit.point.y > highestHitY)
                {
                    highestHitY = hit.point.y;
                    result.hitColliderId = hit.collider.GetInstanceID();
                    result.hitColliderName = hit.collider.name;
                    result.contactPoint = hit.point;
                    result.surfaceHeight = hit.point.y;
                    result.normal = hit.normal;
                }
            }
        }
        result.hasSupport = result.hitCount > 0;
        result.queryCostMilliseconds = ElapsedMilliseconds(started);
        return result;
    }

    private GeometryChangeRecord BuildGeometryChangeRecord(
        Transform platform,
        int platformLevel,
        string assetIdentity,
        string assetPath,
        string assetGuid,
        string fingerprint)
    {
        PlatformData data = platform.GetComponent<PlatformData>();
        Transform holeCentre = data != null ? data.holeCenter : null;
        bool hasTargetHole = data != null && holeCentre != null;
        float authored = data != null ? data.holeRadius : float.NaN;
        Vector3 scale = platform.lossyScale;
        float candidate = data != null && IsFinite(authored)
            ? authored * Mathf.Max(Mathf.Abs(scale.x), Mathf.Abs(scale.z))
            : float.NaN;
        bool valid = HasIndependentlyPlausibleHoleGeometry(platform, data, candidate, out string source);
        Collider[] colliders = platform.GetComponentsInChildren<Collider>(true);
        ColliderGeometry[] descriptions = new ColliderGeometry[colliders.Length];
        for (int i = 0; i < colliders.Length; i++) descriptions[i] = DescribeCollider(colliders[i], platform);
        return new GeometryChangeRecord
        {
            schema_version = SchemaVersion,
            run_id = currentRunId,
            geometry_version_id = geometryVersionId,
            change_reason = geometryVersion == 1 ? "platform_first_observed" : "platform_transform_or_collider_fingerprint_changed",
            unity_time = Time.time,
            platform_asset_identity = assetIdentity,
            platform_asset_path = assetPath,
            platform_asset_guid = assetGuid,
            platform_instance_id = platform.gameObject.GetInstanceID(),
            platform_name = platform.name,
            layer_at_observation = platformLevel,
            platform_position = platform.position,
            platform_euler_angles = platform.eulerAngles,
            platform_local_scale = platform.localScale,
            platform_lossy_scale = platform.lossyScale,
            has_target_hole = hasTargetHole,
            root_platform_data_present = data != null,
            hole_center_present = holeCentre != null,
            platform_data_instance_id = data != null ? data.GetInstanceID() : 0,
            hole_center_instance_id = holeCentre != null ? holeCentre.GetInstanceID() : 0,
            hole_center_name = holeCentre != null ? GetHierarchyPath(holeCentre) : string.Empty,
            hole_center_world_position = holeCentre != null ? holeCentre.position : Vector3.one * float.NaN,
            authored_hole_radius = authored,
            authored_hole_radius_units = data != null ? "platform_local_scale_units (PlatformData Tooltip)" : "unknown",
            hole_radius_scale_inputs = scale,
            computed_world_hole_radius = valid ? candidate : float.NaN,
            computed_world_hole_radius_candidate = candidate,
            hole_geometry_valid = valid,
            hole_geometry_source = source,
            hole_center_probe_clear = hasTargetHole ? !AnyPlatformHitAtHolePoint(platform, holeCentre.position, out _) : false,
            hole_ring_probe_hits = hasTargetHole && valid ? CountHoleRingProbeHits(platform, holeCentre.position, candidate) : 0,
            hole_ring_probe_count = hasTargetHole && valid ? 4 : 0,
            outer_bound_search_extent_method = "conservative_union_collider_aabb_corner_radius_only_for_search_bracket",
            collider_aabb_radial_search_extent = GetConservativeAabbRadialExtent(platform),
            colliders = descriptions
        };
    }

    private static bool HasIndependentlyPlausibleHoleGeometry(
        Transform platform,
        PlatformData data,
        float candidate,
        out string source)
    {
        source = "unknown";
        if (platform == null || data == null)
        {
            source = "invalid_missing_root_platform_data";
            return false;
        }
        if (data.holeCenter == null)
        {
            source = "invalid_missing_hole_center";
            return false;
        }
        if (!IsFinite(data.holeRadius) || data.holeRadius <= 0f || !IsFinite(candidate) || candidate <= 0f)
        {
            source = "invalid_authored_radius_or_scale";
            return false;
        }

        float extent = GetConservativeAabbRadialExtent(platform);
        if (!IsFinite(extent) || candidate >= extent)
        {
            source = "rejected_radius_outside_conservative_collider_bounds";
            return false;
        }

        bool centreClear = !AnyPlatformHitAtHolePoint(platform, data.holeCenter.position, out _);
        int ringHits = CountHoleRingProbeHits(platform, data.holeCenter.position, candidate);
        if (!centreClear || ringHits < 2)
        {
            source = "platform_data_candidate_not_confirmed_by_vertical_collider_probes";
            return false;
        }
        source = "platform_data_authored_local_radius_scaled_by_root_max_abs_xz_and_centre_ring_probed";
        return true;
    }

    private static int CountHoleRingProbeHits(Transform platform, Vector3 centre, float radius)
    {
        int hits = 0;
        Vector2[] directions = { Vector2.right, Vector2.left, Vector2.up, Vector2.down };
        for (int i = 0; i < directions.Length; i++)
        {
            Vector3 position = centre + new Vector3(directions[i].x * radius * 1.15f, 0f, directions[i].y * radius * 1.15f);
            if (AnyPlatformHitAtHolePoint(platform, position, out _)) hits++;
        }
        return hits;
    }

    private static bool AnyPlatformHitAtHolePoint(Transform platform, Vector3 position, out RaycastHit bestHit)
    {
        bestHit = default;
        if (platform == null) return false;
        List<Collider> eligible = GetEligibleColliders(platform.GetComponentsInChildren<Collider>(true));
        if (eligible.Count == 0) return false;
        float minY = float.PositiveInfinity;
        float maxY = float.NegativeInfinity;
        foreach (Collider collider in eligible)
        {
            minY = Mathf.Min(minY, collider.bounds.min.y);
            maxY = Mathf.Max(maxY, collider.bounds.max.y);
        }
        if (!IsFinite(minY) || !IsFinite(maxY)) return false;
        Ray ray = new Ray(new Vector3(position.x, maxY + 0.2f, position.z), Vector3.down);
        float distance = maxY - minY + 0.4f;
        bool found = false;
        float highest = float.NegativeInfinity;
        foreach (Collider collider in eligible)
        {
            if (!collider.Raycast(ray, out RaycastHit hit, distance)) continue;
            if (hit.point.y <= highest) continue;
            highest = hit.point.y;
            bestHit = hit;
            found = true;
        }
        return found;
    }

    private static float GetConservativeAabbRadialExtent(Transform platform)
    {
        if (platform == null) return float.NaN;
        List<Collider> eligible = GetEligibleColliders(platform.GetComponentsInChildren<Collider>(true));
        float extent = 0f;
        foreach (Collider collider in eligible)
        {
            Bounds bounds = collider.bounds;
            float rx = Mathf.Abs(bounds.center.x - platform.position.x) + bounds.extents.x;
            float rz = Mathf.Abs(bounds.center.z - platform.position.z) + bounds.extents.z;
            extent = Mathf.Max(extent, Mathf.Sqrt(rx * rx + rz * rz));
        }
        return extent > 0f ? extent : float.NaN;
    }

    private static bool TryVerticalHit(
        List<Collider> colliders,
        Vector3 centre,
        Vector2 direction,
        float radius,
        float rayStartY,
        float maxDistance,
        out RaycastHit bestHit)
    {
        bestHit = default;
        Vector3 origin = new Vector3(centre.x + direction.x * radius, rayStartY, centre.z + direction.y * radius);
        Ray ray = new Ray(origin, Vector3.down);
        bool found = false;
        float highest = float.NegativeInfinity;
        foreach (Collider collider in colliders)
        {
            if (!collider.Raycast(ray, out RaycastHit hit, maxDistance)) continue;
            if (hit.point.y <= highest) continue;
            highest = hit.point.y;
            bestHit = hit;
            found = true;
        }
        return found;
    }

    private static List<Collider> GetEligibleColliders(Collider[] colliders)
    {
        List<Collider> eligible = new List<Collider>(colliders != null ? colliders.Length : 0);
        if (colliders == null) return eligible;
        for (int i = 0; i < colliders.Length; i++)
        {
            Collider collider = colliders[i];
            if (collider == null || !collider.enabled || !collider.gameObject.activeInHierarchy || collider.isTrigger) continue;
            eligible.Add(collider);
        }
        return eligible;
    }

    private static ColliderGeometry DescribeBallCollider(Collider collider)
    {
        if (collider == null)
        {
            return new ColliderGeometry
            {
                collider_instance_id = 0,
                collider_name = string.Empty,
                collider_type = "unknown",
                local_scale = Vector3.one * float.NaN,
                lossy_scale = Vector3.one * float.NaN,
                bounds_min = Vector3.one * float.NaN,
                bounds_max = Vector3.one * float.NaN
            };
        }
        return DescribeCollider(collider, collider.transform.root);
    }

    private static ColliderGeometry DescribeCollider(Collider collider, Transform root)
    {
        if (collider == null) return new ColliderGeometry();
        MeshCollider meshCollider = collider as MeshCollider;
        MeshFilter filter = collider.GetComponent<MeshFilter>();
        Mesh mesh = meshCollider != null && meshCollider.sharedMesh != null
            ? meshCollider.sharedMesh
            : filter != null ? filter.sharedMesh : null;
        string meshPath = string.Empty;
        string meshGuid = string.Empty;
#if UNITY_EDITOR
        if (mesh != null)
        {
            meshPath = AssetDatabase.GetAssetPath(mesh);
            if (!string.IsNullOrEmpty(meshPath)) meshGuid = AssetDatabase.AssetPathToGUID(meshPath);
        }
#endif
        Bounds bounds = collider.bounds;
        Transform t = collider.transform;
        return new ColliderGeometry
        {
            collider_instance_id = collider.GetInstanceID(),
            collider_name = collider.name,
            collider_hierarchy_path = GetHierarchyPath(t),
            collider_type = collider.GetType().Name,
            enabled = collider.enabled,
            active_in_hierarchy = collider.gameObject.activeInHierarchy,
            is_trigger = collider.isTrigger,
            contributes_to_query = collider.enabled && collider.gameObject.activeInHierarchy && !collider.isTrigger,
            game_object_layer = collider.gameObject.layer,
            local_position = t.localPosition,
            world_position = t.position,
            local_euler_angles = t.localEulerAngles,
            world_euler_angles = t.eulerAngles,
            local_scale = t.localScale,
            lossy_scale = t.lossyScale,
            bounds_min = bounds.min,
            bounds_max = bounds.max,
            mesh_collider_identity = meshCollider != null
                ? (mesh != null ? mesh.name + "#" + mesh.GetInstanceID().ToString(CultureInfo.InvariantCulture) : "null")
                : string.Empty,
            mesh_filter_identity = filter != null && filter.sharedMesh != null
                ? filter.sharedMesh.name + "#" + filter.sharedMesh.GetInstanceID().ToString(CultureInfo.InvariantCulture)
                : string.Empty,
            mesh_asset_path = meshPath,
            mesh_asset_guid = meshGuid,
            mesh_instance_id = mesh != null ? mesh.GetInstanceID() : 0,
            mesh_vertex_count = mesh != null ? mesh.vertexCount : 0,
            mesh_triangle_index_count = mesh != null && mesh.isReadable ? mesh.triangles.Length : 0
        };
    }

    private static string GetBallShapeParameters(Collider collider)
    {
        if (collider == null) return "unknown";
        SphereCollider sphere = collider as SphereCollider;
        if (sphere != null) return "radius=" + sphere.radius.ToString("R", CultureInfo.InvariantCulture) + ";center=" + VectorString(sphere.center);
        BoxCollider box = collider as BoxCollider;
        if (box != null) return "size=" + VectorString(box.size) + ";center=" + VectorString(box.center);
        CapsuleCollider capsule = collider as CapsuleCollider;
        if (capsule != null) return "radius=" + capsule.radius.ToString("R", CultureInfo.InvariantCulture) + ";height=" + capsule.height.ToString("R", CultureInfo.InvariantCulture) + ";direction=" + capsule.direction + ";center=" + VectorString(capsule.center);
        CharacterController character = collider as CharacterController;
        if (character != null) return "radius=" + character.radius.ToString("R", CultureInfo.InvariantCulture) + ";height=" + character.height.ToString("R", CultureInfo.InvariantCulture) + ";center=" + VectorString(character.center);
        MeshCollider mesh = collider as MeshCollider;
        if (mesh != null) return "convex=" + mesh.convex + ";mesh=" + (mesh.sharedMesh != null ? mesh.sharedMesh.name : "null");
        return collider.GetType().Name;
    }

    private static string BuildGeometryFingerprint(Transform platform)
    {
        StringBuilder builder = new StringBuilder(1024);
        AppendVector(builder, platform.position);
        AppendVector(builder, platform.eulerAngles);
        AppendVector(builder, platform.localScale);
        PlatformData data = platform.GetComponent<PlatformData>();
        builder.Append(data != null ? data.GetInstanceID() : 0).Append('|');
        if (data != null)
        {
            builder.Append(data.holeRadius.ToString("R", CultureInfo.InvariantCulture)).Append('|');
            builder.Append(data.holeCenter != null ? data.holeCenter.GetInstanceID() : 0).Append('|');
            if (data.holeCenter != null)
            {
                AppendVector(builder, data.holeCenter.position);
                AppendVector(builder, data.holeCenter.lossyScale);
            }
        }
        Collider[] colliders = platform.GetComponentsInChildren<Collider>(true);
        builder.Append(colliders.Length).Append('|');
        foreach (Collider collider in colliders)
        {
            if (collider == null) { builder.Append("null|"); continue; }
            builder.Append(collider.GetInstanceID()).Append('|')
                .Append(collider.enabled).Append('|')
                .Append(collider.gameObject.activeInHierarchy).Append('|')
                .Append(collider.isTrigger).Append('|');
            AppendVector(builder, collider.transform.position);
            AppendVector(builder, collider.transform.eulerAngles);
            AppendVector(builder, collider.transform.lossyScale);
            Bounds bounds = collider.bounds;
            AppendVector(builder, bounds.min);
            AppendVector(builder, bounds.max);
            MeshCollider meshCollider = collider as MeshCollider;
            if (meshCollider != null) builder.Append(meshCollider.sharedMesh != null ? meshCollider.sharedMesh.GetInstanceID() : 0).Append('|');
        }
        return Hash128.Compute(builder.ToString()).ToString();
    }

    private static void GetAssetIdentity(GameObject instance, out string identity, out string path, out string guid)
    {
        identity = "unknown";
        path = string.Empty;
        guid = string.Empty;
        if (instance == null) return;
#if UNITY_EDITOR
        GameObject source = PrefabUtility.GetCorrespondingObjectFromSource(instance);
        if (source == null) source = instance;
        path = AssetDatabase.GetAssetPath(source);
        if (!string.IsNullOrEmpty(path))
        {
            guid = AssetDatabase.AssetPathToGUID(path);
            identity = path + (string.IsNullOrEmpty(guid) ? string.Empty : "#" + guid);
            return;
        }
#endif
        if (instance.scene.IsValid() && !string.IsNullOrEmpty(instance.scene.path))
        {
            identity = "scene-object:" + instance.scene.path + "/" + GetHierarchyPath(instance.transform);
        }
        else
        {
            identity = "runtime-object:" + instance.name + "#" + instance.GetInstanceID().ToString(CultureInfo.InvariantCulture) + ";asset=unknown";
        }
    }

    private static string GetHierarchyPath(Transform transform)
    {
        if (transform == null) return string.Empty;
        string path = transform.name;
        Transform parent = transform.parent;
        while (parent != null)
        {
            path = parent.name + "/" + path;
            parent = parent.parent;
        }
        return path;
    }

    private static void AppendVector(StringBuilder builder, Vector3 vector)
    {
        builder.Append(vector.x.ToString("R", CultureInfo.InvariantCulture)).Append(',')
            .Append(vector.y.ToString("R", CultureInfo.InvariantCulture)).Append(',')
            .Append(vector.z.ToString("R", CultureInfo.InvariantCulture)).Append('|');
    }

    private static string VectorString(Vector3 vector)
    {
        return vector.x.ToString("R", CultureInfo.InvariantCulture) + "," +
               vector.y.ToString("R", CultureInfo.InvariantCulture) + "," +
               vector.z.ToString("R", CultureInfo.InvariantCulture);
    }

    private static float ElapsedMilliseconds(long startTicks)
    {
        return (float)((Stopwatch.GetTimestamp() - startTicks) * 1000.0 / Stopwatch.Frequency);
    }

    private static bool IsFinite(float value)
    {
        return !float.IsNaN(value) && !float.IsInfinity(value);
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        geometryWriter?.Flush();
        geometryWriter?.Dispose();
        sampleWriter?.Flush();
        sampleWriter?.Dispose();
    }
}
