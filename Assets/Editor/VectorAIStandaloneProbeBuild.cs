using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEditorInternal;
using UnityEngine.Profiling;

/// <summary>Explicitly invoked helper for the isolated Windows standalone receiver probe.</summary>
public static class VectorAIStandaloneProbeBuild
{
    // Unity rejects Player output inside its internal Library directory.
    const string OutputRoot = "../VectorAIStandaloneDiagnostics";
    static bool busy;

    [MenuItem("Tools/VectorAI/Standalone Probe/Build Windows Player")]
    public static void ScheduleBuild()
    {
        if (busy) { Debug.LogWarning("Standalone probe build is already queued or running."); return; }
        if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling || ProfilerDriver.enabled)
        { Debug.LogError("Refusing standalone probe build during Play, compilation, or active Profiler capture."); return; }
        for (int i = 0; i < SceneManager.sceneCount; i++)
            if (SceneManager.GetSceneAt(i).isDirty) { Debug.LogError("Refusing to replace a dirty loaded scene for probe build."); return; }
        busy = true;
        EditorApplication.delayCall += BuildNow;
    }

    static void BuildNow()
    {
        string buildId = DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff") + "_" + Guid.NewGuid().ToString("N");
        string receipt = Path.Combine(OutputRoot, "build_receipt_" + buildId + ".json");
        string tempAssetPath = "Assets/VectorAIDiagnostics/TempStandaloneProbe_" + buildId + ".unity";
        string playerPath = Path.Combine(OutputRoot, buildId, "VectorAIStandaloneProbe.exe");
        string result = "failed";
        string failure = null;
        bool sceneReplaced = false;
        SceneSetup[] setup = EditorSceneManager.GetSceneManagerSetup();
        try
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling || ProfilerDriver.enabled)
                throw new InvalidOperationException("Build context changed while queued; refusing to build.");
            for (int i = 0; i < SceneManager.sceneCount; i++)
                if (SceneManager.GetSceneAt(i).isDirty) throw new InvalidOperationException("A loaded scene became dirty while queued.");
            Directory.CreateDirectory(OutputRoot);
            if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.StandaloneWindows64)
                throw new InvalidOperationException("Select Windows 64-bit as the active build target before invoking this helper.");
            BuildTargetGroup group = BuildTargetGroup.Standalone;
            BuildTarget namedTarget = BuildTarget.StandaloneWindows64;
            NamedBuildTarget named = NamedBuildTarget.Standalone;
            if (PlayerSettings.GetScriptingBackend(named) != ScriptingImplementation.Mono2x)
                throw new InvalidOperationException("The current standalone scripting backend is not Mono. Refusing to change project settings.");

            sceneReplaced = true;
            Scene empty = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            if (!EditorSceneManager.SaveScene(empty, tempAssetPath)) throw new IOException("Could not create temporary empty diagnostic scene.");
            var options = new BuildPlayerOptions
            {
                scenes = new[] { tempAssetPath },
                locationPathName = Path.GetFullPath(playerPath),
                target = namedTarget,
                targetGroup = group,
                options = BuildOptions.Development,
                extraScriptingDefines = new[] { "VECTORAI_STANDALONE_PROBE" }
            };
            BuildReport report = BuildPipeline.BuildPlayer(options);
            if (report == null) throw new InvalidOperationException("Unity returned no build report; inspect Editor.log for the original build error.");
            result = report.summary.result.ToString();
            if (report.summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException("Player build result: " + result + " (" + report.summary.totalErrors + " errors)");
        }
        catch (Exception ex) { failure = ex.GetBaseException().ToString(); }
        finally
        {
            try { if (sceneReplaced) EditorSceneManager.RestoreSceneManagerSetup(setup); }
            catch (Exception ex) { failure = (failure ?? "") + " Scene restore failure: " + ex.GetBaseException().Message; result = "failed"; }
            try { AssetDatabase.DeleteAsset(tempAssetPath); AssetDatabase.Refresh(); }
            catch (Exception ex) { failure = (failure ?? "") + " Temporary scene cleanup failure: " + ex.GetBaseException().Message; result = "failed"; }
            try
            {
                string json = "{\n" +
                    "  \"result\":\"" + Escape(result) + "\",\n" +
                    "  \"unity_version\":\"" + Escape(Application.unityVersion) + "\",\n" +
                    "  \"player_path\":\"" + Escape(Path.GetFullPath(playerPath)) + "\",\n" +
                    "  \"scene\":\"temporary empty diagnostic scene only\",\n" +
                    "  \"target\":\"Windows64 Mono Development\",\n" +
                    "  \"extra_define\":\"VECTORAI_STANDALONE_PROBE\",\n" +
                    "  \"runtime_source_sha256\":\"" + HashFile("Assets/VectorAIDiagnostics/StandaloneReceiverProbe.cs") + "\",\n" +
                    "  \"build_helper_sha256\":\"" + HashFile("Assets/Editor/VectorAIStandaloneProbeBuild.cs") + "\",\n" +
                    "  \"receiver_source_sha256\":\"" + HashFile("Assets/Endness Falling/Scripts/UdpFrontendReceiver.cs") + "\",\n" +
                    "  \"replay_fixture_source_sha256\":\"" + HashFile("Assets/Editor/VectorAIReceiverReplayWindow.cs") + "\",\n" +
                    "  \"frame_cap\":60,\n  \"vsync\":0,\n  \"run_in_background\":true,\n" +
                    "  \"error\":" + (failure == null ? "null" : "\"" + Escape(failure) + "\"") + "\n}";
                File.WriteAllText(receipt, json, new UTF8Encoding(false));
            }
            catch (Exception ex) { Debug.LogError("Could not write standalone probe build receipt: " + ex.GetBaseException().Message); }
            busy = false;
            Debug.Log("Standalone probe build finished: " + result + (failure == null ? "" : " — " + failure));
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
