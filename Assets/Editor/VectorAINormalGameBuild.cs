using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditorInternal;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>Explicit build entry point for the authored, normal standalone game.</summary>
public static class VectorAINormalGameBuild
{
    const string RequiredLogIn = "Assets/Endness Driving/Scenes/Stage/LogIn.unity";
    const string RequiredHub = "Assets/Endness Driving/Scenes/Stage/FypHub.unity";
    const string RequiredFalling = "Assets/Endness Driving/Scenes/Stage/EndlessFalling.unity";
    const string ProbeStandaloneDefine = "VECTORAI_STANDALONE_PROBE";
    const string ProbeFullGameDefine = "VECTORAI_FULLGAME_PROBE";
    static bool queued;

    static readonly string[] SourcePaths =
    {
        "Assets/Endness Falling/Scripts/UdpFrontendReceiver.cs",
        "Assets/Endness Falling/Scripts/UIManager.cs",
        "Assets/BackEnd/UDPManager.cs",
        "Assets/Endness Falling/Scripts/LevelManager.cs",
        "Assets/Endness Falling/Scripts/EndlessPlayerController.cs",
        "Assets/Endness Driving/Scripts/UI/GameSensitivitySettings.cs",
        "Assets/VectorAIDiagnostics/FullGameStandaloneProbe.cs",
        "Assets/VectorAIDiagnostics/StandaloneReceiverProbe.cs"
    };

    [MenuItem("Tools/VectorAI/Normal Game/Build Windows Player")]
    public static void ScheduleBuild()
    {
        if (queued) { Debug.LogWarning("Normal game build is already queued or running."); return; }
        string reason = BuildGuardFailure(out _);
        if (reason != null) { Debug.LogError("Normal game build refused: " + reason); return; }
        queued = true;
        EditorApplication.delayCall += BuildNow;
    }

    static string BuildGuardFailure(out List<string> scenes)
    {
        scenes = null;
        if (EditorApplication.isPlayingOrWillChangePlaymode) return "Play mode is active or starting.";
        if (EditorApplication.isCompiling) return "Unity is compiling scripts.";
        if (ProfilerDriver.enabled) return "Profiler capture is active.";
        for (int i = 0; i < SceneManager.sceneCount; i++)
            if (SceneManager.GetSceneAt(i).isDirty) return "A loaded scene has unsaved changes.";
        if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.StandaloneWindows64)
            return "Active build target is not Windows 64-bit; project settings will not be changed.";
        if (PlayerSettings.GetScriptingBackend(NamedBuildTarget.Standalone) != ScriptingImplementation.Mono2x)
            return "Current standalone scripting backend is not Mono; project settings will not be changed.";
        string defineError = FindProbeDefine();
        if (defineError != null) return defineError;

        scenes = new List<string>();
        foreach (EditorBuildSettingsScene scene in EditorBuildSettings.scenes)
        {
            if (scene == null || !scene.enabled) continue;
            if (!File.Exists(scene.path)) return "Enabled build scene file is missing: " + scene.path;
            scenes.Add(scene.path);
        }
        if (!scenes.Contains(RequiredLogIn)) return "Required enabled scene is missing from EditorBuildSettings: " + RequiredLogIn;
        if (!scenes.Contains(RequiredHub)) return "Required enabled scene is missing from EditorBuildSettings: " + RequiredHub;
        if (!scenes.Contains(RequiredFalling)) return "Required enabled scene is missing from EditorBuildSettings: " + RequiredFalling;
        if (scenes[0] != RequiredLogIn) return "The authored first enabled scene is not LogIn; refusing to silently change entry order.";
        foreach (string path in SourcePaths)
            if (!File.Exists(path)) return "Required source for build receipt is missing: " + path;
        if (!File.Exists("ProjectSettings/EditorBuildSettings.asset") || !File.Exists("ProjectSettings/ProjectSettings.asset"))
            return "Required project settings file is missing.";
        return null;
    }

    static string FindProbeDefine()
    {
        try
        {
            string current = PlayerSettings.GetScriptingDefineSymbols(NamedBuildTarget.Standalone) ?? "";
            foreach (string symbol in current.Split(';'))
                if (symbol.Trim() == ProbeStandaloneDefine || symbol.Trim() == ProbeFullGameDefine)
                    return "Standalone contains a diagnostic-only symbol: " + symbol.Trim();
        }
        catch (Exception ex) { return "Cannot verify standalone scripting defines: " + ex.GetBaseException().Message; }
        var targets = new List<NamedBuildTarget> { NamedBuildTarget.Standalone };
        foreach (BuildTargetGroup group in Enum.GetValues(typeof(BuildTargetGroup)))
        {
            if (group == BuildTargetGroup.Unknown) continue;
            try { targets.Add(NamedBuildTarget.FromBuildTargetGroup(group)); }
            catch { /* Some obsolete or unsupported groups cannot be queried. */ }
        }
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (NamedBuildTarget target in targets)
        {
            string name = target.TargetName;
            if (!seen.Add(name)) continue;
            try
            {
                string defines = PlayerSettings.GetScriptingDefineSymbols(target) ?? "";
                foreach (string symbol in defines.Split(';'))
                    if (symbol.Trim() == ProbeStandaloneDefine || symbol.Trim() == ProbeFullGameDefine)
                        return "Project scripting defines contain diagnostic-only symbol " + symbol.Trim() + " for target group " + name + ".";
            }
            catch { /* Unsupported target groups have no queryable scripting defines. */ }
        }
        return null;
    }

    static void BuildNow()
    {
        string buildId = Guid.NewGuid().ToString("D").ToUpperInvariant();
        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        string parent = Path.GetFullPath(Path.Combine(desktop, "VectorAI_Normal_Game"));
        string outputDir = Path.Combine(parent, buildId);
        string receiptPath = Path.Combine(parent, buildId + "_build_receipt.json");
        string manifestPath = Path.Combine(parent, buildId + "_sha256_manifest.json");
        string playerPath = Path.Combine(outputDir, "VectorAI.exe");
        string result = "NotStarted";
        string failure = null;
        BuildSummary summary = default(BuildSummary);
        List<string> scenes = null;
        Dictionary<string, string> preHashes = new Dictionary<string, string>();
        Dictionary<string, string> postHashes = new Dictionary<string, string>();
        Dictionary<string, string> defines = ReadAllDefines();
        bool sourceDrift = false;
        string verification = "verification_pending";
        var artifactHashes = new Dictionary<string, string>();

        try
        {
            string reason = BuildGuardFailure(out scenes);
            if (reason != null) throw new InvalidOperationException("Build context changed while queued; refusing to build. " + reason);
            if (Directory.Exists(outputDir) || File.Exists(receiptPath) || File.Exists(manifestPath))
                throw new IOException("The unique build destination unexpectedly already exists; refusing to overwrite it: " + outputDir);
            foreach (string path in InputPaths(scenes)) preHashes[path] = HashFile(path);

            Directory.CreateDirectory(outputDir);
            var options = new BuildPlayerOptions
            {
                scenes = scenes.ToArray(),
                locationPathName = playerPath,
                target = BuildTarget.StandaloneWindows64,
                targetGroup = BuildTargetGroup.Standalone,
                options = BuildOptions.Development,
                extraScriptingDefines = new string[0]
            };
            BuildReport report = BuildPipeline.BuildPlayer(options);
            if (report == null) throw new InvalidOperationException("Unity returned no BuildReport; inspect Editor.log for the build error.");
            summary = report.summary;
            result = summary.result.ToString();
            if (summary.result != BuildResult.Succeeded)
                failure = "Unity build result was " + result + "; errors=" + summary.totalErrors + ", warnings=" + summary.totalWarnings + ".";
            WriteReadme(outputDir);

            string dataDir = Path.Combine(outputDir, "VectorAI_Data");
            string[] critical =
            {
                playerPath,
                Path.Combine(outputDir, "UnityPlayer.dll"),
                Path.Combine(dataDir, "Managed", "Assembly-CSharp.dll"),
                Path.Combine(dataDir, "globalgamemanagers"),
                Path.Combine(dataDir, "boot.config")
            };
            foreach (string file in critical)
            {
                string relative = file.Substring(outputDir.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                artifactHashes[relative.Replace('\\', '/')] = File.Exists(file) ? HashAbsoluteFile(file) : "missing";
            }
            if (summary.result == BuildResult.Succeeded && artifactHashes.ContainsValue("missing"))
            {
                result = "Failed_MissingArtifact";
                failure = "A required runtime file is missing from the successful Unity build; inspect the manifest.";
            }
            if (summary.result == BuildResult.Succeeded)
            {
                verification = VerifyCompiledAssembly(Path.Combine(dataDir, "Managed", "Assembly-CSharp.dll"));
                if (verification.StartsWith("failed:", StringComparison.Ordinal))
                {
                    result = "Failed_CompiledAssemblyVerification";
                    failure = verification;
                }
            }
        }
        catch (Exception ex)
        {
            if (result == "NotStarted") result = "Failed";
            failure = ex.GetBaseException().ToString();
        }
        finally
        {
            foreach (string path in InputPaths(scenes)) postHashes[path] = HashFile(path);
            foreach (KeyValuePair<string, string> pair in preHashes)
                if (!postHashes.ContainsKey(pair.Key) || pair.Value != postHashes[pair.Key]) sourceDrift = true;
            if (sourceDrift)
            {
                result = "Failed_SourceDrift";
                failure = (failure == null ? "" : failure + " ") + "One or more captured source or settings hashes changed during the build; this result must not be treated as a successful build.";
            }

            try
            {
                if (Directory.Exists(outputDir)) WriteReadme(outputDir);
                WriteManifest(manifestPath, artifactHashes);
                WriteReceipt(receiptPath, result, failure, buildId, playerPath, scenes, preHashes, postHashes,
                    defines, summary, sourceDrift, verification, manifestPath);
            }
            catch (Exception ex) { Debug.LogError("Normal game build receipt/manifest write failed: " + ex.GetBaseException().Message); }
            queued = false;
            Debug.Log("Normal game build finished: " + result + (failure == null ? "" : " — " + failure) + " | receipt: " + receiptPath);
        }
    }

    static IEnumerable<string> InputPaths(List<string> scenes)
    {
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "ProjectSettings/ProjectSettings.asset", "ProjectSettings/EditorBuildSettings.asset",
            "Assets/Editor/VectorAINormalGameBuild.cs"
        };
        foreach (string path in SourcePaths) paths.Add(path);
        if (scenes != null) foreach (string scene in scenes) paths.Add(scene);
        return paths;
    }

    static Dictionary<string, string> ReadAllDefines()
    {
        var values = new Dictionary<string, string>();
        var targets = new List<NamedBuildTarget> { NamedBuildTarget.Standalone };
        foreach (BuildTargetGroup group in Enum.GetValues(typeof(BuildTargetGroup)))
        {
            if (group == BuildTargetGroup.Unknown) continue;
            try { targets.Add(NamedBuildTarget.FromBuildTargetGroup(group)); } catch { }
        }
        foreach (NamedBuildTarget target in targets)
        {
            string name = target.TargetName;
            if (values.ContainsKey(name)) continue;
            try { values[name] = PlayerSettings.GetScriptingDefineSymbols(target) ?? ""; } catch { }
        }
        return values;
    }

    static string VerifyCompiledAssembly(string assemblyPath)
    {
        if (!File.Exists(assemblyPath)) return "verification_pending: compiled Assembly-CSharp.dll was not found.";
        try
        {
            Assembly cecil = null;
            foreach (Assembly loaded in AppDomain.CurrentDomain.GetAssemblies())
                if (loaded.GetType("Mono.Cecil.AssemblyDefinition", false) != null) { cecil = loaded; break; }
            if (cecil == null)
            {
                string bundled = Path.Combine(EditorApplication.applicationContentsPath, "Managed", "Unity.Cecil.dll");
                if (File.Exists(bundled)) cecil = Assembly.LoadFrom(bundled);
            }
            if (cecil == null) return "verification_pending: Mono.Cecil is unavailable in the editor domain.";
            Type assemblyDefinitionType = cecil.GetType("Mono.Cecil.AssemblyDefinition", false);
            MethodInfo readAssembly = assemblyDefinitionType == null ? null : assemblyDefinitionType.GetMethod("ReadAssembly", new[] { typeof(string) });
            if (readAssembly == null) return "verification_pending: Mono.Cecil AssemblyDefinition.ReadAssembly(string) is unavailable.";
            object definition = readAssembly.Invoke(null, new object[] { assemblyPath });
            try
            {
                object mainModule = definition.GetType().GetProperty("MainModule").GetValue(definition, null);
                object typeCollection = mainModule.GetType().GetProperty("Types").GetValue(mainModule, null);
                var typeNames = new HashSet<string>(StringComparer.Ordinal);
                foreach (object type in (System.Collections.IEnumerable)typeCollection) CollectTypeNames(type, typeNames);
                string[] forbidden = { "FullGameStandaloneProbe", "StandaloneReceiverProbe" };
                foreach (string name in forbidden)
                    if (typeNames.Contains(name)) return "failed: forbidden diagnostic type is present in compiled Assembly-CSharp: " + name;
                if (!typeNames.Contains("UdpFrontendReceiver")) return "failed: UdpFrontendReceiver type is absent from compiled Assembly-CSharp.";
                if (!typeNames.Contains("UIManager")) return "failed: UIManager type is absent from compiled Assembly-CSharp.";
                return "passed: Mono.Cecil inspected Assembly-CSharp.dll; forbidden probe types absent and normal receiver/UI types present.";
            }
            finally
            {
                IDisposable disposable = definition as IDisposable;
                if (disposable != null) disposable.Dispose();
            }
        }
        catch (Exception ex) { return "verification_pending: compiled assembly inspection failed: " + ex.GetBaseException().Message; }
    }

    static void CollectTypeNames(object typeDefinition, HashSet<string> names)
    {
        Type type = typeDefinition.GetType();
        string name = Convert.ToString(type.GetProperty("Name").GetValue(typeDefinition, null));
        names.Add(name);
        object nested = type.GetProperty("NestedTypes").GetValue(typeDefinition, null);
        foreach (object child in (System.Collections.IEnumerable)nested) CollectTypeNames(child, names);
    }

    static void WriteReadme(string outputDir)
    {
        const string readme = "VectorAI normal game build\r\n\r\n" +
            "This is the normal independent game build. Use LogIn, then FypHub, then select a game from the hub.\r\n" +
            "Start the backend separately with Start_Pilot_10P_Experimental.cmd. Keep this entire build folder together.\r\n" +
            "For the falling game, set sensitivity to 0.55 in the actual app and select difficulty 3 and session length 3 layers. The app reads its saved PlayerPrefs; this build does not force a sensitivity value.\r\n" +
            "Normal UDP defaults remain ports 5005 and 5006. This build adds no timers, synthetic UDP input, or port redirection.\r\n" +
            "This Development build supports current retesting and observability. It is not a final performance-certified release.\r\n";
        File.WriteAllText(Path.Combine(outputDir, "README.txt"), readme, new UTF8Encoding(false));
    }

    static void WriteManifest(string path, Dictionary<string, string> hashes)
    {
        var builder = new StringBuilder("{\n  \"files\": {\n");
        int i = 0;
        foreach (KeyValuePair<string, string> entry in hashes)
        {
            if (i++ > 0) builder.Append(",\n");
            builder.Append("    \"").Append(Escape(entry.Key)).Append("\": \"").Append(Escape(entry.Value)).Append("\"");
        }
        builder.Append("\n  }\n}\n");
        File.WriteAllText(path, builder.ToString(), new UTF8Encoding(false));
    }

    static void WriteReceipt(string path, string result, string failure, string buildId, string playerPath,
        List<string> scenes, Dictionary<string, string> before, Dictionary<string, string> after,
        Dictionary<string, string> defines, BuildSummary summary, bool drift, string verification, string manifest)
    {
        var json = new StringBuilder("{\n");
        Append(json, "result", Q(result), true);
        Append(json, "error", failure == null ? "null" : Q(failure));
        Append(json, "build_id", Q(buildId));
        Append(json, "unity_version", Q(Application.unityVersion));
        Append(json, "target", Q("StandaloneWindows64 / Windows x86_64 / Mono"));
        Append(json, "build_flags", Q("Development; no AutoRunPlayer; no ConnectWithProfiler; no DeepProfilingSupport"));
        Append(json, "extra_scripting_defines", "[]");
        Append(json, "player_path", Q(Path.GetFullPath(playerPath)));
        Append(json, "enabled_scenes_authored_order", StringArray(scenes));
        Append(json, "source_hashes_pre_build", StringMap(before));
        Append(json, "source_hashes_post_build", StringMap(after));
        Append(json, "source_or_settings_drift", drift ? "true" : "false");
        Append(json, "project_scripting_defines_by_group", StringMap(defines));
        Append(json, "verification", Q(verification));
        Append(json, "manifest_path", Q(Path.GetFullPath(manifest)));
        Append(json, "error_count", summary.totalErrors.ToString());
        Append(json, "warning_count", summary.totalWarnings.ToString());
        Append(json, "total_size_bytes", summary.totalSize.ToString());
        Append(json, "build_duration_seconds", summary.totalTime.TotalSeconds.ToString("F3", System.Globalization.CultureInfo.InvariantCulture), false);
        json.Append("}\n");
        File.WriteAllText(path, json.ToString(), new UTF8Encoding(false));
    }

    static void Append(StringBuilder json, string key, string value, bool first = false)
    {
        if (!first) json.Append(",\n");
        json.Append("  \"").Append(Escape(key)).Append("\": ").Append(value);
    }
    static string StringArray(List<string> values)
    {
        var b = new StringBuilder("[");
        if (values != null) for (int i = 0; i < values.Count; i++) { if (i > 0) b.Append(", "); b.Append(Q(values[i])); }
        return b.Append(']').ToString();
    }
    static string StringMap(Dictionary<string, string> values)
    {
        var b = new StringBuilder("{"); int i = 0;
        foreach (KeyValuePair<string, string> pair in values) { if (i++ > 0) b.Append(", "); b.Append(Q(pair.Key)).Append(": ").Append(Q(pair.Value)); }
        return b.Append('}').ToString();
    }
    static string Q(string value) => "\"" + Escape(value) + "\"";
    static string Escape(string value) => (value ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
    static string HashFile(string path) => File.Exists(path) ? HashAbsoluteFile(Path.GetFullPath(path)) : "missing";
    static string HashAbsoluteFile(string path)
    {
        using (SHA256 sha = SHA256.Create()) using (FileStream stream = File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }
}
