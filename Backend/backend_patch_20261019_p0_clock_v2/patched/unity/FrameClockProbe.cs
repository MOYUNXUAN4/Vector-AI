// FrameClockProbe — wall-clock frame timing for the 500 ms stall investigation.
//
// Unity clamps Time.deltaTime to Time.maximumDeltaTime (0.3333 s by default),
// so the existing diagnostics cannot show a 485-505 ms stall: every long frame
// reads back as 333.3333 ms.  This probe records the *wall clock* delta between
// frames next to Time.deltaTime, which exposes the clamped remainder directly.
//
// It needs no scene changes: the static initializer creates a hidden
// DontDestroyOnLoad object after the first scene loads.
//
// Log: %USERPROFILE%\AppData\LocalLow\<company>\<product>\FrameClockProbe\frames_*.jsonl
// Each line:
//   {"frame":123,"realtime_s":12.345,"unity_time":10.200,"delta_ms":16.7,
//    "wall_ms":16.7,"clamped_ms":0.0,"gc_bytes":12345678,"stall":false}
//
// `wall_ms - delta_ms` is the time Unity hid because of the clamp.  A 500 ms
// stall appears as wall_ms ~= 500 and delta_ms ~= 333.3 on the same frame.

using System;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;

public sealed class FrameClockProbe : MonoBehaviour
{
    private const int HeartbeatFrames = 120;   // ~2 s at 60 Hz
    private const double StallThresholdMs = 50.0;
    private const double ClampThresholdMs = 20.0;
    private const int FlushEveryLines = 60;

    private StreamWriter writer;
    private double lastRealtime;
    private long lines;
    private long stalls;
    private string logPath;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Bootstrap()
    {
        if (UnityEngine.Object.FindFirstObjectByType<FrameClockProbe>() != null) return;
        var host = new GameObject("FrameClockProbe");
        UnityEngine.Object.DontDestroyOnLoad(host);
        host.AddComponent<FrameClockProbe>();
    }

    private void Awake()
    {
        try
        {
            string directory = Path.Combine(Application.persistentDataPath, "FrameClockProbe");
            Directory.CreateDirectory(directory);
            logPath = Path.Combine(directory,
                "frames_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture) + ".jsonl");
            writer = new StreamWriter(logPath, false, new UTF8Encoding(false)) { AutoFlush = false };
            lastRealtime = Time.realtimeSinceStartupAsDouble;
            writer.WriteLine("{\"record\":\"header\",\"unity\":\"" + Application.unityVersion +
                             "\",\"platform\":\"" + Application.platform +
                             "\",\"maximum_delta_time_s\":" + Num(Time.maximumDeltaTime) + "}");
            writer.Flush();
        }
        catch (Exception error)
        {
            Debug.LogWarning("[FrameClockProbe] disabled: " + error.GetType().Name);
            enabled = false;
        }
    }

    private void Update()
    {
        if (writer == null) return;
        double now = Time.realtimeSinceStartupAsDouble;
        double wallMs = (now - lastRealtime) * 1000.0;
        double deltaMs = Time.deltaTime * 1000.0;
        double clampedMs = wallMs - deltaMs;
        lastRealtime = now;
        bool stall = wallMs >= StallThresholdMs;
        if (stall) stalls++;

        if (stall || clampedMs >= ClampThresholdMs || Time.frameCount % HeartbeatFrames == 0)
        {
            Write(now, deltaMs, wallMs, clampedMs, stall);
        }
    }

    private void Write(double realtime, double deltaMs, double wallMs, double clampedMs, bool stall)
    {
        try
        {
            long gc = GC.GetTotalMemory(false);
            writer.Write("{\"frame\":" + Time.frameCount);
            writer.Write(",\"realtime_s\":" + Num(realtime));
            writer.Write(",\"unity_time\":" + Num(Time.timeAsDouble));
            writer.Write(",\"delta_ms\":" + Num(deltaMs));
            writer.Write(",\"wall_ms\":" + Num(wallMs));
            writer.Write(",\"clamped_ms\":" + Num(clampedMs));
            writer.Write(",\"gc_bytes\":" + gc);
            writer.Write(",\"stall\":" + (stall ? "true" : "false"));
            writer.WriteLine("}");
            lines++;
            // Persist a large stall immediately: the process may be killed
            // before the next scheduled flush.
            if (wallMs >= 400.0 || lines % FlushEveryLines == 0)
            {
                writer.Flush();
            }
        }
        catch (Exception)
        {
            enabled = false;
        }
    }

    private static string Num(double value)
    {
        if (double.IsNaN(value) || double.IsInfinity(value)) return "null";
        return value.ToString("0.###", CultureInfo.InvariantCulture);
    }

    private void OnApplicationQuit() { Close(); }
    private void OnDisable() { Close(); }
    private void OnDestroy() { Close(); }

    private void Close()
    {
        if (writer == null) return;
        try
        {
            writer.WriteLine("{\"record\":\"summary\",\"frames\":" + Time.frameCount +
                             ",\"stalls\":" + stalls + "}");
            writer.Flush();
            writer.Dispose();
        }
        catch (Exception) { }
        finally
        {
            writer = null;
            Debug.Log("[FrameClockProbe] log: " + logPath + " (stalls: " + stalls + ")");
        }
    }
}
