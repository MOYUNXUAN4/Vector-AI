using System;
using System.Collections;
using System.Linq;
using System.Reflection;
using NUnit.Framework;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public class UnifiedRiskPresentationTests
{
    private static Type ProjectType(string name) => AppDomain.CurrentDomain.GetAssemblies()
        .Select(a => a.GetType(name, false)).First(t => t != null);
    private static readonly BindingFlags InstanceFlags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    private static FieldInfo Field(object obj, string name) => obj.GetType().GetField(name, InstanceFlags);
    private static void Set(object obj, string name, object value) => Field(obj, name).SetValue(obj, value);
    private static object Get(object obj, string name) => Field(obj, name).GetValue(obj);
    private static object Call(object obj, string name, params object[] args) => obj.GetType().GetMethod(name, InstanceFlags).Invoke(obj, args);
    private static int Mask(object state) => Convert.ToInt32(Get(state, "sources"));

    public static IEnumerable SourceCombinations
    {
        get
        {
            for (int context = 0; context < 2; context++)
                for (int mask = 0; mask < 16; mask++)
                    yield return new TestCaseData(context != 0, mask).SetName("UnifiedSources_Context" + context + "_Mask" + mask);
        }
    }

    [TestCaseSource(nameof(SourceCombinations))]
    public void AllSourcesAreIndependentAndNoSourceSurvivesInactiveContext(bool context, int mask)
    {
        Type ui = ProjectType("UIManager");
        MethodInfo build = ui.GetMethod("BuildUnifiedRiskPresentationState", BindingFlags.Static | BindingFlags.NonPublic);
        object state = build.Invoke(null, new object[] { context, (mask & 1) != 0, (mask & 2) != 0, (mask & 4) != 0, (mask & 8) != 0 });
        int expected = context ? mask : 0;
        Assert.That(Mask(state), Is.EqualTo(expected));
        Assert.That((bool)Get(state, "modelActive"), Is.EqualTo((expected & 1) != 0));
        Assert.That((bool)Get(state, "geometryActive"), Is.EqualTo((expected & 2) != 0));
        Assert.That((bool)Get(state, "proximityActive"), Is.EqualTo((expected & 4) != 0));
        Assert.That((bool)Get(state, "localEdgeActive"), Is.EqualTo((expected & 8) != 0));
    }

    private Scene preview;
    private Component uiManager, levelManager, player, receiver;
    private object savedUiInstance, savedReceiverInstance;
    private FieldInfo uiInstance;
    private PropertyInfo receiverInstance;

    [SetUp]
    public void SetUp()
    {
        preview = EditorSceneManager.NewPreviewScene();
        Type uiType = ProjectType("UIManager");
        Type receiverType = ProjectType("UdpFrontendReceiver");
        uiInstance = uiType.GetField("Instance", BindingFlags.Public | BindingFlags.Static);
        receiverInstance = receiverType.GetProperty("Instance", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
        savedUiInstance = uiInstance.GetValue(null);
        savedReceiverInstance = receiverInstance.GetValue(null);
        uiManager = Create("UIManager", false);
        levelManager = Create("LevelManager", true);
        player = Create("EndlessPlayerController", true);
        receiver = Create("UdpFrontendReceiver", false);
        receiverInstance.SetValue(null, receiver);
        Set(levelManager, "runId", "unified-ui-test-run");
        FieldInfo run = Field(levelManager, "runState");
        run.SetValue(levelManager, Enum.Parse(run.FieldType, "Running"));
        Set(levelManager, "player", player.transform);
        Set(player, "levelManager", levelManager);
        Set(uiManager, "unifiedRiskLevelManager", levelManager);
        Set(player, "edgeWarningState", false);
    }

    private Component Create(string typeName, bool active)
    {
        var obj = new GameObject("UnifiedRiskTest_" + typeName) { hideFlags = HideFlags.HideAndDontSave };
        obj.SetActive(false);
        SceneManager.MoveGameObjectToScene(obj, preview);
        Component result = obj.AddComponent(ProjectType(typeName));
        obj.SetActive(active);
        return result;
    }

    [TearDown]
    public void TearDown()
    {
        // Keep lifecycle notifications isolated from any real scene receiver.
        receiverInstance?.SetValue(null, null);
        uiInstance?.SetValue(null, null);
        if (preview.IsValid()) EditorSceneManager.ClosePreviewScene(preview);
        receiverInstance?.SetValue(null, savedReceiverInstance);
        uiInstance?.SetValue(null, savedUiInstance);
    }

    private object Capture() => Call(uiManager, "CaptureUnifiedRiskPresentationState");

    [Test]
    public void NewOptionIsSerializedAndDefaultOff()
    {
        FieldInfo field = Field(uiManager, "enableUnifiedRiskPresentation");
        Assert.That(field.GetCustomAttribute<SerializeField>(), Is.Not.Null);
        Assert.That((bool)field.GetValue(uiManager), Is.False);
    }

    [Test]
    public void LocalEdgeWorksWithoutReceiverOrDebugHud()
    {
        receiverInstance.SetValue(null, null);
        Set(uiManager, "showEdgeWarningDebugHud", false);
        Set(player, "edgeWarningState", true);
        Assert.That(Mask(Capture()), Is.EqualTo(8));
    }

    [Test]
    public void MissingBoundPlayerDoesNotBorrowAnotherPlayer()
    {
        Set(player, "edgeWarningState", true);
        Assert.That(Mask(Capture()), Is.EqualTo(8));
        Set(levelManager, "player", null);
        Assert.That(Mask(Capture()), Is.Zero);
    }

    [Test]
    public void ChangedBoundPlayerDoesNotKeepOldEdgeFlag()
    {
        Set(player, "edgeWarningState", true);
        Assert.That(Mask(Capture()), Is.EqualTo(8));
        Component replacement = Create("EndlessPlayerController", true);
        Set(levelManager, "player", replacement.transform);
        Assert.That(Mask(Capture()), Is.Zero);
    }

    [Test]
    public void DisabledLocalPlayerDoesNotSupplyAnActiveSource()
    {
        Set(player, "edgeWarningState", true);
        ((Behaviour)player).enabled = false;
        Assert.That(Mask(Capture()), Is.Zero);
    }

    [TestCase("isPaused")]
    [TestCase("isReportVisible")]
    [TestCase("isGameOverVisible")]
    public void ModalStateSuppressesUnifiedOnly(string field)
    {
        Set(player, "edgeWarningState", true);
        Set(uiManager, field, true);
        Assert.That(Mask(Capture()), Is.Zero);
        Assert.That((bool)Get(player, "edgeWarningState"), Is.True);
    }

    [Test]
    public void EndedRunDoesNotDisplayRisk()
    {
        Set(player, "edgeWarningState", true);
        FieldInfo run = Field(levelManager, "runState");
        run.SetValue(levelManager, Enum.Parse(run.FieldType, "Ended"));
        Assert.That(Mask(Capture()), Is.Zero);
    }

    [Test]
    public void ReceiverFeatureGatesAreNotBypassed()
    {
        Set(receiver, "experimentalModelWarningActive", true);
        Set(receiver, "experimentalGeometryWarningActive", true);
        Set(receiver, "experimentalProximityWarningActive", true);
        Set(receiver, "enableExperimentalModelWarning", false);
        Set(receiver, "enableExperimentalGeometryWarning", false);
        Set(receiver, "enableExperimentalProximityWarning", false);
        Assert.That(Mask(Capture()), Is.Zero);
    }

    [Test]
    public void ModelRevocationCannotLeaveProbabilityInLocalOnlySnapshot()
    {
        Set(receiver, "enableExperimentalModelWarning", true);
        Set(receiver, "experimentalModelWarningActive", true);
        Set(receiver, "activeExperimentalStrongProbability", .81f);
        Set(player, "edgeWarningState", true);
        object before = Capture();
        Assert.That(Mask(before), Is.EqualTo(9));
        Assert.That((float)Get(before, "modelProbability"), Is.EqualTo(.81f));
        Set(receiver, "experimentalModelWarningActive", false);
        object after = Capture();
        Assert.That(Mask(after), Is.EqualTo(8));
        Assert.That((float)Get(after, "modelProbability"), Is.Zero);
    }

    [Test]
    public void SourceRelayIsStatelessAndNoSourceMeansEmptyImmediately()
    {
        Set(receiver, "enableExperimentalProximityWarning", true);
        Set(receiver, "experimentalProximityWarningActive", true);
        Set(receiver, "activeExperimentalProximityState", "STRONG");
        Assert.That(Mask(Capture()), Is.EqualTo(4));
        Set(receiver, "experimentalProximityWarningActive", false);
        Set(player, "edgeWarningState", true);
        Assert.That(Mask(Capture()), Is.EqualTo(8));
        Set(player, "edgeWarningState", false);
        Assert.That(Mask(Capture()), Is.Zero);
    }

    [Test]
    public void ExistingLayerResetClearsLocalSource()
    {
        Set(player, "edgeWarningState", true);
        Assert.That(Mask(Capture()), Is.EqualTo(8));
        Call(player, "ResetForLayerTransition", new object[] { null });
        Assert.That(Mask(Capture()), Is.Zero);
    }

    [Test]
    public void FirstNullProximityTextCreatesLabelAndStableTextReusesContent()
    {
        MethodInfo build = uiManager.GetType().GetMethod("BuildUnifiedRiskPresentationState", BindingFlags.Static | BindingFlags.NonPublic);
        object state = build.Invoke(null, new object[] { true, false, false, true, false });
        Call(uiManager, "CacheUnifiedRiskSourceLabels", state);
        object first = Get(uiManager, "cachedUnifiedProximityContent");
        Assert.That(first, Is.Not.Null);
        Call(uiManager, "CacheUnifiedRiskSourceLabels", state);
        Assert.That(Get(uiManager, "cachedUnifiedProximityContent"), Is.SameAs(first));
    }

    [TestCase("modelProbability", "cachedUnifiedModelContent", .805f, .8049f, "F2", 1)]
    [TestCase("geometryClearance", "cachedUnifiedGeometryContent", -.0005f, -.00049f, "F3", 2)]
    public void CacheDoesNotRetainTextAcrossDifferentFormattedValuesWithSameRoundedIntegerKey(
        string valueField, string contentField, float firstValue, float secondValue, string format, int mask)
    {
        MethodInfo build = uiManager.GetType().GetMethod("BuildUnifiedRiskPresentationState", BindingFlags.Static | BindingFlags.NonPublic);
        object state = build.Invoke(null, new object[] { true, (mask & 1) != 0, (mask & 2) != 0, false, false });
        Set(state, valueField, firstValue);
        Call(uiManager, "CacheUnifiedRiskSourceLabels", state);
        Assert.That(((GUIContent)Get(uiManager, contentField)).text, Does.Contain(firstValue.ToString(format)));
        Set(state, valueField, secondValue);
        Call(uiManager, "CacheUnifiedRiskSourceLabels", state);
        Assert.That(((GUIContent)Get(uiManager, contentField)).text, Does.Contain(secondValue.ToString(format)));
    }
}
