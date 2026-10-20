using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditorInternal;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>Explicit build entry point for the existing full-game diagnostic scene only.</summary>
public static class VectorAIFullGameProbeBuild
{
    const string ScenePath = "Assets/Endness Driving/Scenes/Stage/EndlessFalling.unity";
    static bool queued;

    [MenuItem("Tools/VectorAI/Full Game Probe/Build Windows Player")]
    public static void ScheduleBuild()
    {
        if (queued) { Debug.LogWarning("Full-game probe build is already queued or running."); return; }
        string reason = BuildGuardFailure();
        if (reason != null) { Debug.LogError("Full-game probe build refused: " + reason); return; }
        queued = true;
        EditorApplication.delayCall += BuildNow;
    }

    static string BuildGuardFailure()
    {
        if (EditorApplication.isPlayingOrWillChangePlaymode) return "Play mode is active or starting.";
        if (EditorApplication.isCompiling) return "Unity is compiling scripts.";
        if (ProfilerDriver.enabled) return "Profiler capture is active.";
        for (int i = 0; i < SceneManager.sceneCount; i++)
            if (SceneManager.GetSceneAt(i).isDirty) return "A loaded scene has unsaved changes.";
        if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.StandaloneWindows64) return "Active build target is not Windows 64-bit.";
        if (PlayerSettings.GetScriptingBackend(NamedBuildTarget.Standalone) != ScriptingImplementation.Mono2x)
            return "Current standalone scripting backend is not Mono; project settings will not be changed.";
        if (!File.Exists(ScenePath)) return "Required existing diagnostic scene is missing: " + ScenePath;
        return null;
    }

    static void BuildNow()
    {
        queued = false;
        string reason = BuildGuardFailure();
        if (reason != null) { Debug.LogError("Full-game probe build refused after queue: " + reason); return; }
        string id = DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff") + "_" + Guid.NewGuid().ToString("N");
        string projectDir = Directory.GetParent(Application.dataPath).FullName;
        string outputParent = Path.GetFullPath(Path.Combine(projectDir, "..", "VectorAIStandaloneDiagnostics"));
        string outputDir = Path.Combine(outputParent, "fullgame_" + id);
        string receiptPath = Path.Combine(outputParent, "fullgame_" + id + "_build_receipt.json");
        string result = "Failed";
        string error = null;
        try
        {
            Directory.CreateDirectory(outputParent);
            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = Path.Combine(outputDir, "EndlessFallingFullGameProbe.exe"),
                target = BuildTarget.StandaloneWindows64,
                targetGroup = BuildTargetGroup.Standalone,
                options = BuildOptions.Development,
                extraScriptingDefines = new[] { "VECTORAI_FULLGAME_PROBE" }
            };
            BuildReport build = BuildPipeline.BuildPlayer(options);
            if (build == null) throw new InvalidOperationException("Unity returned no build report; inspect Editor.log for the original build error.");
            result = build.summary.result.ToString();
            if (build.summary.result != BuildResult.Succeeded)
                error = "Build result " + result + "; errors=" + build.summary.totalErrors;
        }
        catch (Exception ex) { error = ex.GetBaseException().ToString(); }
        finally
        {
            string json = "{\n" +
                "  \"result\":\"" + Escape(result) + "\",\n" +
                "  \"error\":" + (error == null ? "null" : "\"" + Escape(error) + "\"") + ",\n" +
                "  \"unity_version\":\"" + Escape(Application.unityVersion) + "\",\n" +
                "  \"scene_path\":\"" + Escape(ScenePath) + "\",\n" +
                "  \"scene_sha256\":\"" + HashFile(ScenePath) + "\",\n" +
                "  \"runtime_probe_sha256\":\"" + HashFile("Assets/VectorAIDiagnostics/FullGameStandaloneProbe.cs") + "\",\n" +
                "  \"receiver_probe_harness_sha256\":\"" + HashFile("Assets/VectorAIDiagnostics/StandaloneReceiverProbe.cs") + "\",\n" +
                "  \"receiver_probe_build_helper_sha256\":\"" + HashFile("Assets/Editor/VectorAIStandaloneProbeBuild.cs") + "\",\n" +
                "  \"receiver_source_sha256\":\"" + HashFile("Assets/Endness Falling/Scripts/UdpFrontendReceiver.cs") + "\",\n" +
                "  \"telemetry_manager_source_sha256\":\"" + HashFile("Assets/BackEnd/UDPManager.cs") + "\",\n" +
                "  \"ui_manager_source_sha256\":\"" + HashFile("Assets/Endness Falling/Scripts/UIManager.cs") + "\",\n" +
                "  \"level_manager_source_sha256\":\"" + HashFile("Assets/Endness Falling/Scripts/LevelManager.cs") + "\",\n" +
                "  \"runtime_define\":\"VECTORAI_FULLGAME_PROBE\",\n" +
                "  \"target\":\"Windows64 Mono Development\",\n" +
                "  \"build_scene_count\":1,\n" +
                "  \"build_scene_only\":true,\n" +
                "  \"output_directory\":\"" + Escape(outputDir) + "\",\n" +
                "  \"build_helper_sha256\":\"" + HashFile("Assets/Editor/VectorAIFullGameProbeBuild.cs") + "\"\n" +
                "}";
            try { File.WriteAllText(receiptPath, json, new UTF8Encoding(false)); }
            catch (Exception ex) { Debug.LogError("Full-game probe receipt write failed: " + ex.GetBaseException().Message); }
            Debug.Log("Full-game standalone probe build " + result + ". Receipt: " + receiptPath + (error == null ? "" : " | " + error));
        }
    }

    static string HashFile(string path)
    {
        if (!File.Exists(path)) return "unavailable";
        using (var sha = SHA256.Create()) using (var stream = File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }
    static string Escape(string value) => (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
}
