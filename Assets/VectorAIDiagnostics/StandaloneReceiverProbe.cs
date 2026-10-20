#if VECTORAI_STANDALONE_PROBE && !UNITY_EDITOR
using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.Profiling;

/// <summary>Standalone, socket-free receiver diagnostic. Compiled only for its dedicated player.</summary>
internal sealed class StandaloneReceiverProbe : MonoBehaviour
{
    const int RateHz = 50;
    const int SyntheticPlatformId = -123;
    const string RunId = "vectorai-boardless-replay";
    static readonly BindingFlags InstanceFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    static readonly BindingFlags StaticFlags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
    static StandaloneReceiverProbe runner;
    UdpFrontendReceiver receiver;
    LevelManager level;
    UDPManager udp;
    GameObject fixture;
    MethodInfo updateMethod;
    Action updateAction;
    FieldInfo pendingJson, pendingAt, countField, receiverSocket, receiverThread, udpSender;
    FieldInfo runState, runId, passed, telemetryBacking;
    FieldInfo modelWatermark, geometryWatermark, proximityWatermark;
    object[] packets;
    string mode, outputDir, error;
    string payloadHash;
    int duration, nextPacket, scheduled, silenceTicks, misses, accepted, frameGaps, frameCount;
    int gc0Start, gc1Start, gc2Start;
    long[] gapTicks;
    int gapCount;
    long maxFrameTicks, maxReceiverTicks, maxIntervalTicks;
    long initialModelWatermark, initialGeometryWatermark, initialProximityWatermark;
    bool modelActive, geometryActive, proximityActive, timeoutObserved, failed;
    double started, nextPacketAt, silenceAt;
    bool silenceWasActive;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Bootstrap()
    {
        if (runner != null) return;
        var go = new GameObject("[VectorAI Standalone Probe]");
        DontDestroyOnLoad(go);
        runner = go.AddComponent<StandaloneReceiverProbe>();
    }

    void Start()
    {
        try { Initialize(); }
        catch (Exception ex) { failed = true; error = ex.GetBaseException().ToString(); Finish(); }
    }

    void Initialize()
    {
        string[] args = Environment.GetCommandLineArgs();
        mode = Arg(args, "--probe-mode") ?? "receiver";
        outputDir = Arg(args, "--probe-output");
        if (mode != "idle" && mode != "receiver") throw new ArgumentException("--probe-mode must be idle or receiver");
        if (string.IsNullOrWhiteSpace(outputDir) || !Path.IsPathRooted(outputDir))
        { outputDir = Path.Combine(Application.persistentDataPath, "VectorAIProbeFailure_" + Guid.NewGuid().ToString("N")); throw new ArgumentException("--probe-output must be an absolute unique directory; failure report fallback selected."); }
        duration = mode == "idle" ? 90 : 180;
        Application.targetFrameRate = 60;
        QualitySettings.vSyncCount = 0;
        Application.runInBackground = true;
        if (mode == "idle") { StartClock(); return; }

        Type rt = typeof(UdpFrontendReceiver), lt = typeof(LevelManager), ut = typeof(UDPManager);
        pendingJson = Need(rt, "pendingJsonData"); pendingAt = Need(rt, "pendingReceiveMonotonicSeconds");
        countField = Need(rt, "backendCountX"); receiverSocket = Need(rt, "udpClient"); receiverThread = Need(rt, "receiveThread"); udpSender = Need(ut, "udpSender");
        runState = Need(lt, "runState"); runId = Need(lt, "runId"); passed = Need(lt, "platformsPassed");
        updateMethod = rt.GetMethod("Update", InstanceFlags) ?? throw new MissingMethodException("UdpFrontendReceiver.Update");
        modelWatermark = Need(rt, "highestExperimentalWarningUpdateSequence");
        geometryWatermark = Need(rt, "highestExperimentalGeometryWarningUpdateSequence");
        proximityWatermark = Need(rt, "highestExperimentalProximityWarningUpdateSequence");
        telemetryBacking = ut.GetField("<LastTelemetry>k__BackingField", StaticFlags | BindingFlags.Instance) ?? throw new MissingFieldException("UDPManager.LastTelemetry backing field");

        BuildPackets();
        fixture = new GameObject("[VectorAI Standalone Probe Fixture]"); fixture.SetActive(false);
        level = fixture.AddComponent<LevelManager>(); level.enabled = false;
        receiver = fixture.AddComponent<UdpFrontendReceiver>(); receiver.enabled = false;
        udp = fixture.AddComponent<UDPManager>(); udp.enabled = false;
        updateAction = (Action)Delegate.CreateDelegate(typeof(Action), receiver, updateMethod);
        SetBacking(rt, "<Instance>k__BackingField", receiver);
        SetBacking(ut, "<Instance>k__BackingField", udp);
        Set(runState, level, Enum.Parse(runState.FieldType, "Running")); Set(runId, level, RunId); Set(passed, level, 0);
        Set(pendingJson, receiver, null); Set(pendingAt, receiver, 0d);
        receiver.levelManager = level; receiver.targetPlayer = null;
        object telemetry = Activator.CreateInstance(typeof(UDPManager.UnityGameTelemetry));
        SetPublic(telemetry, "run_id", RunId); SetPublic(telemetry, "platformLevel", 1);
        SetPublic(telemetry, "geometry_platform_instance_id", SyntheticPlatformId); SetPublic(telemetry, "geometry_version_id", "-123-g1");
        telemetryBacking.SetValue(udp, telemetry);
        receiver.enableExperimentalModelWarning = true; receiver.enableExperimentalGeometryWarning = true; receiver.enableExperimentalProximityWarning = true;
        if (receiverSocket.GetValue(receiver) != null || receiverThread.GetValue(receiver) != null || udpSender.GetValue(udp) != null)
            throw new InvalidOperationException("Network initialization detected; aborting.");
        accepted = 0;
        initialModelWatermark = (long)modelWatermark.GetValue(receiver);
        initialGeometryWatermark = (long)geometryWatermark.GetValue(receiver);
        initialProximityWatermark = (long)proximityWatermark.GetValue(receiver);
        gc0Start = GC.CollectionCount(0); gc1Start = GC.CollectionCount(1); gc2Start = GC.CollectionCount(2);
        heapStart = GC.GetTotalMemory(false);
        StartClock();
    }

    void StartClock()
    {
        gapTicks = new long[Math.Max(1, duration * 2)];
        started = Seconds(); nextPacketAt = started;
        gc0Start = GC.CollectionCount(0); gc1Start = GC.CollectionCount(1); gc2Start = GC.CollectionCount(2);
        heapStart = GC.GetTotalMemory(false);
    }

    void Update()
    {
        if (started == 0) return;
        try
        {
            long frameStart = Stopwatch.GetTimestamp();
            double now = Seconds();
            long gap = frameStart - lastFrameTick;
            if (lastFrameTick != 0)
            {
                if (gap > maxIntervalTicks) maxIntervalTicks = gap;
                if (gap > Stopwatch.Frequency / 10) { if (gapCount < gapTicks.Length) gapTicks[gapCount++] = gap; frameGaps++; }
            }
            frameCount++;
            lastFrameTick = frameStart;
            if (mode == "receiver")
            {
                if (nextPacket < packets.Length && now >= nextPacketAt)
                {
                    double late = now - nextPacketAt;
                    int skipped = Math.Min((int)(late * RateHz), packets.Length - nextPacket - 1);
                    if (skipped > 0) { for (int i=0;i<skipped;i++) if (packets[nextPacket+i] != null) misses++; nextPacket += skipped; nextPacketAt += skipped / (double)RateHz; }
                    object packet = packets[nextPacket++];
                    if (packet == null)
                    {
                        silenceTicks++;
                        if (silenceAt == 0) { silenceAt = now; silenceWasActive = receiver.ExperimentalModelWarningActive && receiver.ExperimentalGeometryWarningActive && receiver.ExperimentalProximityWarningActive; }
                    }
                    else { silenceAt = 0; silenceWasActive = false; Set(pendingJson, receiver, packet); Set(pendingAt, receiver, now); scheduled++; }
                    nextPacketAt += 1d / RateHz;
                }
                long before = Stopwatch.GetTimestamp(); updateAction(); long cost = Stopwatch.GetTimestamp()-before;
                if (cost > maxReceiverTicks) maxReceiverTicks = cost;
                if (receiverSocket.GetValue(receiver) != null || receiverThread.GetValue(receiver) != null || udpSender.GetValue(udp) != null) throw new InvalidOperationException("Socket/thread became non-null; aborting.");
                modelActive |= receiver.ExperimentalModelWarningActive; geometryActive |= receiver.ExperimentalGeometryWarningActive; proximityActive |= receiver.ExperimentalProximityWarningActive;
                if (silenceWasActive && silenceAt != 0 && now-silenceAt >= .3 && !receiver.ExperimentalModelWarningActive && !receiver.ExperimentalGeometryWarningActive && !receiver.ExperimentalProximityWarningActive) timeoutObserved = true;
                accepted = (int)countField.GetValue(receiver);
            }
            long frameCost = Stopwatch.GetTimestamp()-frameStart; if (frameCost > maxFrameTicks) maxFrameTicks=frameCost;
            if (now-started >= duration || (mode == "receiver" && nextPacket >= packets.Length)) Finish();
        }
        catch (Exception ex) { failed = true; error = ex.GetBaseException().ToString(); Finish(); }
    }
    long lastFrameTick;

    void BuildPackets()
    {
        packets = new object[duration * RateHz];
        for (int i=0;i<packets.Length;i++)
        {
            double t=(double)i/RateHz, phase=t%30d; long seq=i+1; if(phase>=29.4d){packets[i]=null;continue;}
            bool hazard=phase<10||phase>=20; string state=hazard?"STRONG":"SAFE", gs=hazard?"CRITICAL":"CLEAR", ps=hazard?"APPROACH":"CLEAR";
            float prob=hazard?.91f:.08f; string stamp=(1800000000d+t).ToString("0.000",CultureInfo.InvariantCulture); long pseq=1+i/5;
            packets[i]="{\"type\":\"realtime\",\"x\":0.25,\"y\":-0.1,\"difficulty\":0,\"rmse\":0.125,\"model_warning\":{\"schema_version\":1,\"experimental\":true,\"enabled\":true,\"model_id\":\"replay-model\",\"run_id\":\""+RunId+"\",\"layer\":1,\"state\":\""+state+"\",\"valid\":true,\"probability_valid\":true,\"strong_probability\":"+prob.ToString(CultureInfo.InvariantCulture)+",\"prediction_sequence\":"+pseq+",\"warning_update_sequence\":"+seq+",\"input_sequence\":"+seq+",\"input_source_timestamp\":"+stamp+",\"feature_age_seconds\":0.01,\"reason\":\"synthetic_replay\"},\"geometry_warning\":{\"schema_version\":1,\"experimental\":true,\"enabled\":true,\"source\":\"geometry_rule\",\"policy_id\":\"outer_clearance_nonpositive_v1\",\"run_id\":\""+RunId+"\",\"layer\":1,\"platform_instance_id\":-123,\"geometry_version_id\":\"-123-g1\",\"input_sequence\":"+seq+",\"input_source_timestamp\":"+stamp+",\"warning_update_sequence\":"+seq+",\"clearance\":"+(hazard?"-0.1":"0.5")+",\"clearance_valid\":true,\"state\":\""+gs+"\",\"valid\":true,\"reason\":\"synthetic_geometry_rule\",\"sample_age_seconds\":0.01,\"query_age_seconds\":0.01,\"geometry_age_seconds\":0.02},\"proximity_warning\":{\"schema_version\":1,\"experimental\":true,\"enabled\":true,\"source\":\"tte_proximity_rule_v1\",\"policy_id\":\"tte_proximity_h075_confirm2_v1\",\"run_id\":\""+RunId+"\",\"layer\":1,\"platform_instance_id\":-123,\"geometry_version_id\":\"-123-g1\",\"input_sequence\":"+seq+",\"input_source_timestamp\":"+stamp+",\"warning_update_sequence\":"+seq+",\"state\":\""+ps+"\",\"active\":"+(hazard?"true":"false")+",\"valid\":true,\"sample_age_seconds\":0.01,\"query_age_seconds\":0.01,\"geometry_age_seconds\":0.02,\"q\":"+(hazard?"0.25":"0")+",\"q_valid\":"+(hazard?"true":"false")+",\"outward_velocity\":"+(hazard?"0.4":"0")+",\"horizon_seconds\":0.75,\"reason\":\"synthetic_tte_rule\"}}";
        }
        using (var sha=SHA256.Create())
        {
            var trace=new StringBuilder(packets.Length*1024);
            foreach(object packet in packets) trace.Append(packet==null?"<SILENCE>":(string)packet).Append('\n');
            payloadHash=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(trace.ToString()))).Replace("-","").ToLowerInvariant();
        }
    }

    void Finish()
    {
        if (finished) return; finished=true;
        string report="";
        try
        {
            Directory.CreateDirectory(outputDir);
            bool socketsNull = receiver == null || (receiverSocket.GetValue(receiver)==null && receiverThread.GetValue(receiver)==null && udpSender.GetValue(udp)==null);
            string gaps="["; for(int i=0;i<gapCount;i++){if(i>0)gaps+=",";gaps+=(gapTicks[i]*1000d/Stopwatch.Frequency).ToString("0.000",CultureInfo.InvariantCulture);} gaps+="]";
            report="{\n  \"mode\":"+Q(mode)+",\n  \"unity_version\":"+Q(Application.unityVersion)+",\n  \"requested_seconds\":"+duration+",\n  \"actual_seconds\":"+(started==0?0:Seconds()-started).ToString("0.000",CultureInfo.InvariantCulture)+",\n  \"frame_gaps_over_100ms\":"+gaps+",\n  \"frame_gap_count\":"+frameGaps+",\n  \"max_frame_ms\":"+(maxFrameTicks*1000d/Stopwatch.Frequency).ToString("0.000",CultureInfo.InvariantCulture)+",\n  \"max_receiver_update_ms\":"+(maxReceiverTicks*1000d/Stopwatch.Frequency).ToString("0.000",CultureInfo.InvariantCulture)+",\n  \"receiver_active_seen\":{\"model\":"+modelActive.ToString().ToLowerInvariant()+",\"geometry\":"+geometryActive.ToString().ToLowerInvariant()+",\"proximity\":"+proximityActive.ToString().ToLowerInvariant()+"},\n  \"silence_timeout_cleared_all\":"+timeoutObserved.ToString().ToLowerInvariant()+",\n  \"warning_watermark_advanced\":{\"model\":"+(receiver!=null&&(long)modelWatermark.GetValue(receiver)>initialModelWatermark).ToString().ToLowerInvariant()+",\"geometry\":"+(receiver!=null&&(long)geometryWatermark.GetValue(receiver)>initialGeometryWatermark).ToString().ToLowerInvariant()+",\"proximity\":"+(receiver!=null&&(long)proximityWatermark.GetValue(receiver)>initialProximityWatermark).ToString().ToLowerInvariant()+"},\n  \"scheduled_packets\":"+scheduled+",\n  \"accepted_realtime_packets\":"+accepted+",\n  \"intentional_silence_ticks\":"+silenceTicks+",\n  \"schedule_misses\":"+misses+",\n  \"network_fields_null\":"+socketsNull.ToString().ToLowerInvariant()+",\n  \"gc_mode\":"+Q(GCSettingsMode())+",\n  \"used_managed_bytes_start\":"+heapStart+",\n  \"used_managed_bytes_end\":"+GC.GetTotalMemory(false)+",\n  \"gc_collection_count_delta\":{\"gen0\":"+(GC.CollectionCount(0)-gc0Start)+",\"gen1\":"+(GC.CollectionCount(1)-gc1Start)+",\"gen2\":"+(GC.CollectionCount(2)-gc2Start)+"},\n  \"synthetic_fixture\":true,\n  \"failed\":"+failed.ToString().ToLowerInvariant()+(error==null?"":",\n  \"error\":"+Q(error))+"\n}";
            report = report.Replace("\"max_frame_ms\"", "\"max_probe_update_ms\"")
                .Replace("\"gc_mode\"", "\"dotnet_gc_latency_mode\"")
                .Replace("  \"synthetic_fixture\":true,", "  \"frame_count\":"+frameCount+",\n  \"target_fps\":60,\n  \"packet_rate_hz\":50,\n  \"max_frame_interval_ms\":"+(maxIntervalTicks*1000d/Stopwatch.Frequency).ToString("0.000",CultureInfo.InvariantCulture)+",\n  \"payload_trace_sha256\":"+Q(payloadHash)+",\n  \"unity_gc_mode\":"+Q(UnityEngine.Scripting.GarbageCollector.GCMode.ToString())+",\n  \"incremental_gc_enabled\":"+UnityEngine.Scripting.GarbageCollector.isIncremental.ToString().ToLowerInvariant()+",\n  \"mono_heap_bytes_end\":"+Profiler.GetMonoHeapSizeLong()+",\n  \"synthetic_fixture\":true,");
            File.WriteAllText(Path.Combine(outputDir,"probe_"+DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff")+"_"+Guid.NewGuid().ToString("N")+".json"),report,new UTF8Encoding(false));
        }
        catch(Exception ex){failed=true;UnityEngine.Debug.LogError("Probe report failure: "+ex.GetBaseException().Message);}
        if(fixture!=null) Destroy(fixture);
        Application.Quit(failed?2:0);
    }
    bool finished; long heapStart;
    static string Arg(string[] a,string key){for(int i=0;i<a.Length-1;i++)if(a[i]==key)return a[i+1];return null;}
    static FieldInfo Need(Type t,string n)=>t.GetField(n,InstanceFlags)??throw new MissingFieldException(t.FullName,n);
    static void Set(FieldInfo f,object o,object v)=>f.SetValue(o,v);
    static void SetPublic(object o,string n,object v)=>o.GetType().GetField(n,BindingFlags.Instance|BindingFlags.Public).SetValue(o,v);
    static void SetBacking(Type t,string n,object value){FieldInfo f=t.GetField(n,StaticFlags)??throw new MissingFieldException(t.FullName,n);f.SetValue(null,value);}
    static double Seconds()=>Stopwatch.GetTimestamp()/(double)Stopwatch.Frequency;
    static string Q(string s)=>"\""+(s??"").Replace("\\","\\\\").Replace("\"","\\\"").Replace("\r","\\r").Replace("\n","\\n")+"\"";
    static string GCSettingsMode(){try{return GCSettings.LatencyMode.ToString();}catch{return "unknown";}}
}
#endif
