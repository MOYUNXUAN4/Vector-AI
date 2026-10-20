using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using NUnit.Framework;
using UnityEngine;

public class UdpFrontendReceiverWarningTests
{
    private const string RunId = "run-current";
    private const int Layer = 1;
    private const string ModelId = "test-model";

    private GameObject receiverObject;
    private GameObject levelObject;
    private GameObject udpObject;
    private Component receiver;
    private Component levelManager;
    private Component udpManager;
    private Type receiverType;
    private Type packetType;
    private Type geometryPacketType;
    private Type proximityPacketType;
    private Type udpManagerType;
    private MethodInfo handleWarning;
    private MethodInfo handleRealtimeWarnings;
    private MethodInfo handleGeometryWarning;
    private MethodInfo handleProximityWarning;
    private MethodInfo resetWarningForRun;
    private MethodInfo layerTransition;
    private FieldInfo sequenceFloor;
    private FieldInfo geometryWatermark;
    private FieldInfo proximityWatermark;
    private object savedUdpManager;
    private object savedReceiverInstance;
    private readonly List<string> geometryDiagnosticLogs = new List<string>();
    private long nextWarningUpdateSequence;

    [TestCase("{\"warning\":{\"value\":1}}", true, "1")]
    [TestCase("{\"warning\":{\"value\":1,\"value\":2}}", false, "2")]
    [TestCase("{\"warning\":{\"val\\u0075e\":1}}", false, "")]
    [TestCase("{\"warning\":{\"value\":[1,{\"x\":2}]}}", true, "[1,{\"x\":2}]")]
    [TestCase("{\"warning\":{\"value\":[1,{\"x\":2]}}}", false, "")]
    public void RawJsonFieldRangeComparisonPreservesOutcomes(string json, bool expected, string expectedValue)
    {
        object[] arguments = { json, "warning", "value", null };
        bool actual = (bool)InvokeStatic(receiverType, "TryGetRawJsonFieldValue", arguments);
        Assert.That(actual, Is.EqualTo(expected));
        Assert.That(arguments[3], Is.EqualTo(expectedValue));
    }

    [TestCase("{\"warning\":{\"warning_update_sequence\":1}}", true, 1L)]
    [TestCase("{\"warning\":{\"warning_update_sequence\":1,\"warning_update_sequence\":2}}", false, 0L)]
    [TestCase("{\"warning\":{\"warning_update_\\u0073equence\":1}}", false, 0L)]
    [TestCase("{\"warning\":{\"warning_update_sequence\":01}}", false, 0L)]
    [TestCase("{\"warning\":{\"warning_update_sequence\":1.0}}", false, 0L)]
    [TestCase("{\"warning\":{\"warning_update_sequence\":1e}}", false, 0L)]
    [TestCase("{\"warning\":{\"warning_update_sequence\":9223372036854775807}}", true, long.MaxValue)]
    [TestCase("{\"warning\":{\"warning_update_sequence\":9223372036854775808}}", false, 0L)]
    [TestCase("{\"warning\":{\"warning_update_sequence\":1,\"extra\":[1,{\"x\":2]}}}", false, 0L)]
    [TestCase("{\"warning\":{\"warning_update_sequence\":\u20031\u2003}}", true, 1L)]
    public void WarningSequenceRangeParsingPreservesStrictOutcomes(string json, bool expected, long expectedSequence)
    {
        object[] arguments = { json, "warning", 0L };
        bool actual = (bool)InvokeStatic(receiverType, "TryGetPositiveWarningUpdateSequenceForObject", arguments);
        Assert.That(actual, Is.EqualTo(expected));
        Assert.That(arguments[2], Is.EqualTo(expectedSequence));
    }

    [TestCase("1   ,", true, 4)]
    [TestCase("\u20031\u2003,", true, 3)]
    [TestCase("true  }", true, 6)]
    [TestCase("1.  ,", false, 4)]
    public void PrimitiveRangeParsingPreservesUntrimmedCursor(string json, bool expected, int expectedCursor)
    {
        object[] arguments = { json, 0 };
        Assert.That((bool)InvokeStatic(receiverType, "TrySkipJsonValue", arguments), Is.EqualTo(expected));
        Assert.That(arguments[1], Is.EqualTo(expectedCursor));
    }

    [SetUp]
    public void SetUp()
    {
        receiverType = FindProjectType("UdpFrontendReceiver");
        Type levelManagerType = FindProjectType("LevelManager");
        packetType = receiverType.GetNestedType("ModelWarningPacket", BindingFlags.Public);
        geometryPacketType = receiverType.GetNestedType("GeometryWarningPacket", BindingFlags.Public | BindingFlags.NonPublic);
        proximityPacketType = receiverType.GetNestedType("ProximityWarningPacket", BindingFlags.Public | BindingFlags.NonPublic);
        handleRealtimeWarnings = GetMethod(receiverType, "HandleRealtimeExperimentalWarnings");
        handleGeometryWarning = GetMethod(receiverType, "HandleExperimentalGeometryWarning");
        handleProximityWarning = GetMethod(receiverType, "HandleExperimentalProximityWarning");
        udpManagerType = FindProjectType("UDPManager");
        savedUdpManager = GetStaticProperty(udpManagerType, "Instance");
        savedReceiverInstance = GetStaticProperty(receiverType, "Instance");
        SetStaticProperty(udpManagerType, "Instance", null);

        receiverObject = new GameObject("WarningReceiverRegressionTest");
        receiver = receiverObject.AddComponent(receiverType);
        SetStaticProperty(receiverType, "Instance", receiver);
        SetPrivateField(receiver, "enableExperimentalModelWarning", true);
        SetPrivateField(receiver, "enableExperimentalGeometryWarning", true);
        SetPrivateField(receiver, "enableExperimentalProximityWarning", true);

        levelObject = new GameObject("WarningLevelRegressionTest");
        levelManager = levelObject.AddComponent(levelManagerType);
        Type runStateType = levelManagerType.GetNestedType("GameRunState");
        SetPrivateField(levelManager, "runState", Enum.Parse(runStateType, "Running"));
        SetPrivateField(levelManager, "runId", RunId);
        SetPrivateField(levelManager, "platformsPassed", 0);
        SetPrivateField(receiver, "levelManager", levelManager);

        handleWarning = GetMethod(receiverType, "HandleExperimentalModelWarning");
        resetWarningForRun = GetMethod(receiverType, "ResetExperimentalWarningForRun");
        layerTransition = GetMethod(receiverType, "HandleExperimentalLayerTransition");
        sequenceFloor = receiverType.GetField("layerInputSequenceFloor", BindingFlags.Instance | BindingFlags.NonPublic);
        geometryWatermark = receiverType.GetField("highestExperimentalGeometryWarningUpdateSequence", BindingFlags.Instance | BindingFlags.NonPublic);
        proximityWatermark = receiverType.GetField("highestExperimentalProximityWarningUpdateSequence", BindingFlags.Instance | BindingFlags.NonPublic);
        Assert.That(sequenceFloor, Is.Not.Null);
        Assert.That(geometryWatermark, Is.Not.Null);
        Assert.That(proximityWatermark, Is.Not.Null);
        nextWarningUpdateSequence = 0;
        Invoke(resetWarningForRun, receiver, RunId);
        sequenceFloor.SetValue(receiver, -1L);
        SetPrivateField(receiver, "hasLayerInputSequenceFloor", false);

        udpObject = new GameObject("WarningTelemetryRegressionTest");
        udpManager = udpObject.AddComponent(udpManagerType);
        SetStaticProperty(udpManagerType, "Instance", udpManager);
        SetGeometryTelemetryContext(RunId, Layer, 123, "platform-123-g1");
        Invoke(GetMethod(receiverType, "SynchronizeExperimentalProximityTelemetryContext"), receiver);
    }

    [TearDown]
    public void TearDown()
    {
        Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        if (receiverObject != null) UnityEngine.Object.DestroyImmediate(receiverObject);
        if (levelObject != null) UnityEngine.Object.DestroyImmediate(levelObject);
        if (udpObject != null) UnityEngine.Object.DestroyImmediate(udpObject);
        SetStaticProperty(udpManagerType, "Instance", savedUdpManager);
        SetStaticProperty(receiverType, "Instance", savedReceiverInstance);
    }

    [Test]
    public void WarningExtractionScopeCachesOnlyForTheSameRawStringReference()
    {
        const string payload = "{\"model_warning\":{\"value\":1}}";
        object scope = CreateExtractionScope(payload);
        try
        {
            object[] first = { payload, "model_warning", null };
            object[] second = { payload, "model_warning", null };
            Assert.That((bool)InvokeStatic(receiverType, "TryExtractJsonObject", first), Is.True);
            Assert.That((bool)InvokeStatic(receiverType, "TryExtractJsonObject", second), Is.True);
            Assert.That(second[2], Is.SameAs(first[2]));

            string equalButDistinctPayload = new string(payload.ToCharArray());
            object[] mismatch = { equalButDistinctPayload, "model_warning", null };
            Assert.That((bool)InvokeStatic(receiverType, "TryExtractJsonObject", mismatch), Is.True);
            Assert.That(mismatch[2], Is.Not.SameAs(first[2]));
        }
        finally { ((IDisposable)scope).Dispose(); }
    }

    [Test]
    public void WarningExtractionScopeCachesFailuresAndLeavesEmptyOutput()
    {
        const string payload = "{\"model_warning\":null}";
        object scope = CreateExtractionScope(payload);
        try
        {
            object[] first = { payload, "model_warning", null };
            object[] second = { payload, "model_warning", null };
            Assert.That((bool)InvokeStatic(receiverType, "TryExtractJsonObject", first), Is.False);
            Assert.That(first[2], Is.EqualTo(string.Empty));
            Assert.That((bool)InvokeStatic(receiverType, "TryExtractJsonObject", second), Is.False);
            Assert.That(second[2], Is.EqualTo(string.Empty));
            Assert.That(GetScopeField(scope, "modelResolved"), Is.True);
            Assert.That(GetScopeField(scope, "modelSucceeded"), Is.False);
        }
        finally { ((IDisposable)scope).Dispose(); }
    }

    [Test]
    public void WarningExtractionScopesRestoreNestedContextAndClearAfterException()
    {
        const string outerPayload = "{\"geometry_warning\":{\"value\":1}}";
        const string innerPayload = "{\"proximity_warning\":{\"value\":2}}";
        FieldInfo currentScope = receiverType.GetField("currentWarningJsonExtractionScope",
            BindingFlags.Static | BindingFlags.NonPublic);
        object outer = CreateExtractionScope(outerPayload);
        try
        {
            object inner = CreateExtractionScope(innerPayload);
            Assert.That(currentScope.GetValue(null), Is.SameAs(inner));
            ((IDisposable)inner).Dispose();
            Assert.That(currentScope.GetValue(null), Is.SameAs(outer));

            try { throw new InvalidOperationException("scope unwind"); }
            catch (InvalidOperationException) { ((IDisposable)outer).Dispose(); }
            Assert.That(currentScope.GetValue(null), Is.Null);
            Assert.That(GetScopeField(outer, "source"), Is.Null);
        }
        finally { ((IDisposable)outer).Dispose(); }
    }

    [Test]
    public void WarningExtractionScopeIsThreadLocal()
    {
        object scope = CreateExtractionScope("{\"model_warning\":{}}");
        FieldInfo currentScope = receiverType.GetField("currentWarningJsonExtractionScope",
            BindingFlags.Static | BindingFlags.NonPublic);
        object childThreadScope = scope;
        try
        {
            Thread worker = new Thread(() => childThreadScope = currentScope.GetValue(null));
            worker.Start();
            worker.Join();
            Assert.That(currentScope.GetValue(null), Is.SameAs(scope));
            Assert.That(childThreadScope, Is.Null);
        }
        finally { ((IDisposable)scope).Dispose(); }
    }

    private object CreateExtractionScope(string rawJson)
    {
        Type scopeType = receiverType.GetNestedType("WarningJsonExtractionScope", BindingFlags.NonPublic);
        Assert.That(scopeType, Is.Not.Null, "Missing packet extraction scope");
        return Activator.CreateInstance(scopeType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            null, new object[] { rawJson }, null);
    }

    [Test]
    public void DisposedIntermediateExtractionScopeDoesNotHideLiveAncestor()
    {
        FieldInfo current = receiverType.GetField("currentWarningJsonExtractionScope", BindingFlags.Static | BindingFlags.NonPublic);
        object outer = CreateExtractionScope("outer");
        object middle = CreateExtractionScope("middle");
        object inner = CreateExtractionScope("inner");
        try
        {
            ((IDisposable)middle).Dispose();
            Assert.That(current.GetValue(null), Is.SameAs(inner));
            Assert.That(GetScopeField(middle, "source"), Is.Null);
            ((IDisposable)inner).Dispose();
            Assert.That(current.GetValue(null), Is.SameAs(outer));
        }
        finally
        {
            ((IDisposable)inner).Dispose();
            ((IDisposable)middle).Dispose();
            ((IDisposable)outer).Dispose();
        }
        Assert.That(current.GetValue(null), Is.Null);
    }

    [Test]
    public void RealtimeExtractionScopeUnwindsWhenReceiverLoggingThrows()
    {
        string raw = JsonFor(Packet("STRONG", true, 1, 1, 1, Layer, RunId, 1));
        ILogHandler originalHandler = Debug.unityLogger.logHandler;
        bool originalEnabled = Debug.unityLogger.logEnabled;
        Exception failure = null;
        try
        {
            Debug.unityLogger.logHandler = new ExtractionScopeThrowingLogHandler();
            Debug.unityLogger.logEnabled = true;
            handleRealtimeWarnings.Invoke(receiver, new object[] { raw, StopwatchSeconds() });
        }
        catch (Exception ex) { failure = ex; }
        finally
        {
            Debug.unityLogger.logHandler = originalHandler;
            Debug.unityLogger.logEnabled = originalEnabled;
        }
        Assert.That(failure, Is.Not.Null);
        Assert.That(failure.GetBaseException().Message, Is.EqualTo("scope-test-log-failure"));
        FieldInfo current = receiverType.GetField("currentWarningJsonExtractionScope", BindingFlags.Static | BindingFlags.NonPublic);
        Assert.That(current.GetValue(null), Is.Null);
    }

    private sealed class ExtractionScopeThrowingLogHandler : ILogHandler
    {
        public void LogFormat(LogType logType, UnityEngine.Object context, string format, params object[] args)
        { throw new InvalidOperationException("scope-test-log-failure"); }
        public void LogException(Exception exception, UnityEngine.Object context)
        { throw new InvalidOperationException("scope-test-log-failure"); }
    }

    private static object GetScopeField(object scope, string name)
    {
        FieldInfo field = scope.GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic);
        Assert.That(field, Is.Not.Null, "Missing scope field " + name);
        return field.GetValue(scope);
    }

    [Test]
    public void GeometryCriticalActivatesIndependentlyWhenModelWarningIsUnknown()
    {
        DispatchCombined("UNKNOWN", false, 10, 100, 10.0, "CRITICAL", 100, 1.1, 0.04, 0.08, 0.12);
        AssertActive(false, "Model UNKNOWN remains an independent model-channel revoke.");
        AssertGeometryActive(true, "Fresh geometric CRITICAL remains active despite model UNKNOWN.");
        AssertGeometryWatermark(1);
        AssertWatermark(1);
    }

    [Test]
    public void GeometryClearDoesNotRevokeSeparateModelStrong()
    {
        DispatchCombined("STRONG", true, 11, 101, 10.1, "CLEAR", 101, 1.2, 0.01, 0.01, 0.02);
        AssertActive(true, "Model STRONG remains active when the independent geometry channel is CLEAR.");
        AssertGeometryActive(false);
    }

    [TestCase("CLEAR")]
    [TestCase("UNKNOWN")]
    public void GeometryClearAndUnknownRevokeOnlyGeometry(string state)
    {
        DispatchGeometry("CRITICAL", 20, 2.0, -0.02, 0.01, 0.01, 0.02);
        AssertGeometryActive(true);
        DispatchCombined("STRONG", true, 21, 201, 20.1, state, 21, 2.1, 0.01, 0.02, 0.03, updateSequence: 2);
        AssertGeometryActive(false);
        AssertActive(true, "Geometry state changes must not clear an independently valid model STRONG.");
    }

    [Test]
    public void GeometryDisconnectLeaseExpiresAtTotalAgeOverPointThreeSeconds()
    {
        DispatchGeometry("CRITICAL", 30, 3.0, -0.02, 0.04, 0.03, 0.08);
        AssertGeometryActive(true);
        SetPrivateField(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() /
            (double)System.Diagnostics.Stopwatch.Frequency - 0.23d);
        Invoke(GetMethod(receiverType, "ExpireExperimentalGeometryWarningIfNeeded"), receiver);
        AssertGeometryActive(false, "Received geometry age plus elapsed monotonic time exceeds 0.3 seconds.");
    }

    [Test]
    public void BothChannelsAcceptSameUpdateSequenceAndDuplicateOrReorderedPacketsAreIgnored()
    {
        DispatchCombined("STRONG", true, 40, 400, 4.0, "CRITICAL", 400, 4.1, 0.01, 0.01, 0.02);
        AssertActive(true);
        AssertGeometryActive(true, "Same reply sequence is valid independently in both warning channels.");
        DispatchCombined("UNKNOWN", false, 40, 400, 4.0, "UNKNOWN", 400, 4.1, 0.01, 0.02, 0.03);
        AssertActive(true, "Duplicate update sequence is ignored in model channel.");
        AssertGeometryActive(true, "Duplicate update sequence is ignored in geometry channel.");
        DispatchCombined("UNKNOWN", false, 40, 400, 4.0, "CLEAR", 401, 4.2, 0.01, 0.01, 0.02);
        AssertActive(true, "Reordered older model update cannot revoke.");
        AssertGeometryActive(true, "Reordered older geometry update cannot revoke.");
        AssertWatermark(1);
        AssertGeometryWatermark(1);
    }

    [Test]
    public void IncreasingReplySequenceCannotRenewIdenticalStaleInputSample()
    {
        DispatchGeometry("CRITICAL", 50, 5.0, -0.01, 0.01, 0.01, 0.02);
        AssertGeometryActive(true);
        SetPrivateField(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() /
            (double)System.Diagnostics.Stopwatch.Frequency - 0.15d);
        DispatchGeometry("CRITICAL", 50, 5.0, -0.01, 0.01, 0.01, 0.02, updateSequence: 2);
        AssertGeometryActive(true);
        Assert.That(GetPrivateField<double>(receiver, "activeExperimentalGeometryAgeAtReceiveSeconds"),
            Is.GreaterThanOrEqualTo(0.15d), "Repeated sample lease must carry elapsed age forward.");
        SetPrivateField(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() /
            (double)System.Diagnostics.Stopwatch.Frequency - 0.31d);
        Invoke(GetMethod(receiverType, "ExpireExperimentalGeometryWarningIfNeeded"), receiver);
        AssertGeometryActive(false, "A new reply sequence cannot renew the identical stale sample.");
        DispatchGeometry("CRITICAL", 50, 5.0, -0.01, 0.01, 0.01, 0.02, updateSequence: 3);
        AssertGeometryActive(false, "Expired/revoked input identity cannot reactivate with another reply sequence.");
    }

    [Test]
    public void GeometryOldRunAndLayerCannotActivateOrClearCurrentLease()
    {
        DispatchGeometry("CRITICAL", 60, 6.0, -0.01, 0.01, 0.01, 0.02);
        AssertGeometryActive(true);
        DispatchGeometry("UNKNOWN", 61, 6.1, 0.0, 0.01, 0.01, 0.02,
            runId: "old-run", updateSequence: 99);
        AssertGeometryActive(true, "Old run must not clear the active lease.");
        AssertGeometryWatermark(1);
        SetPrivateField(levelManager, "platformsPassed", 1);
        Invoke(layerTransition, receiver);
        AssertGeometryActive(false, "Unity layer transition clears prior-context geometry.");
        SetGeometryTelemetryContext(RunId, 2, 123, "platform-123-g1");
        DispatchGeometry("CRITICAL", 62, 6.2, -0.01, 0.01, 0.01, 0.02,
            layer: 1, updateSequence: 2);
        AssertGeometryActive(false, "Old layer cannot activate.");
        AssertGeometryWatermark(2, "Old layer still advances geometry run watermark.");
        DispatchGeometry("CRITICAL", 63, 6.3, -0.01, 0.01, 0.01, 0.02,
            layer: 2, updateSequence: 1);
        AssertGeometryActive(false, "Older sequence remains blocked after layer transition.");
        DispatchGeometry("CRITICAL", 64, 6.4, -0.01, 0.01, 0.01, 0.02,
            layer: 2, updateSequence: 3);
        AssertGeometryActive(true, "Fresh current-layer reply at a greater watermark can activate.");
    }

    [Test]
    public void GeometryMalformedSequenceAndAgeFailClosedWithoutBreakingRealtimeValues()
    {
        DispatchGeometry("CRITICAL", 70, 7.0, -0.01, 0.01, 0.01, 0.02);
        AssertGeometryActive(true);
        var invalidAgeOverrides = new Dictionary<string, string>
        {
            ["geometry_age_seconds"] = "-0.01"
        };
        object malformedSequence = GeometryPacket("CRITICAL", 71, 7.1, -0.01, 0.01, 0.01, 0.02, 2, Layer, RunId);
        Invoke(handleGeometryWarning, receiver,
            JsonForCombined(null, malformedSequence, geometrySequenceRaw: "2.5"), malformedSequence, 7.1);
        AssertGeometryActive(false, "Invalid geometry sequence fails closed for the identified run.");
        AssertGeometryWatermark(1, "Invalid geometry sequence does not advance its watermark.");

        object invalidAgeWarning = GeometryPacket("CRITICAL", 72, 7.2, -0.01, 0.01, 0.01, 0.02, 2, Layer, RunId);
        string invalidAgeJson = JsonForCombined(null, invalidAgeWarning,
            geometryOverrides: invalidAgeOverrides)
            .Replace("\"x\":0", "\"x\":3.5")
            .Replace("\"y\":0", "\"y\":-2.25")
            .Replace("\"rmse\":0", "\"rmse\":0.5");
        SetPrivateField(receiver, "pendingJsonData", invalidAgeJson);
        SetPrivateField(receiver, "pendingReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
        Invoke(GetMethod(receiverType, "Update"), receiver);
        AssertGeometryActive(false, "Negative geometry age fails closed.");
        Assert.That(GetPrivateField<int>(receiver, "backendCountX"), Is.EqualTo(1));
        Assert.That(GetPrivateField<float>(receiver, "backendSumX"), Is.EqualTo(3.5f));
        Assert.That(GetPrivateField<float>(receiver, "backendRealRMSE"), Is.EqualTo(0.5f));
        AssertGeometryWatermark(2);
    }

    [Test]
    public void ValidGeometryCriticalStillActivatesWithoutFailureDiagnostic()
    {
        object warning = GeometryPacket("CRITICAL", 85, 8.5, -0.01, 0.01, 0.01, 0.02);
        string raw = JsonForCombined(null, warning);
        MethodInfo validator = receiverType.GetMethod("IsValidCriticalGeometryWarning",
            BindingFlags.Static | BindingFlags.NonPublic);
        Assert.That(validator, Is.Not.Null);
        bool originalValidationResult = (bool)validator.Invoke(null, new[] { warning, raw });
        Assert.That(originalValidationResult, Is.True);

        geometryDiagnosticLogs.Clear();
        Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        Application.logMessageReceived += CaptureGeometryDiagnosticLog;
        try
        {
            Invoke(handleGeometryWarning, receiver, raw, warning,
                System.Diagnostics.Stopwatch.GetTimestamp() /
                (double)System.Diagnostics.Stopwatch.Frequency);
        }
        finally
        {
            Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        }

        AssertGeometryActive(true, "A valid CRITICAL warning must retain its prior activation behavior.");
        Assert.That(geometryDiagnosticLogs.Any(message =>
            message.Contains("[ExperimentalGeometryWarningValidation] rejected ")), Is.False,
            "Successful validation must not emit failure diagnostics.");
        bool validationAfterDiagnostic = (bool)validator.Invoke(null, new[] { warning, raw });
        Assert.That(validationAfterDiagnostic, Is.EqualTo(originalValidationResult));
    }

    [TestCase("sample_age_seconds")]
    [TestCase("query_age_seconds")]
    [TestCase("geometry_age_seconds")]
    public void GeometryCriticalUsesStrictRawAgeWhenJsonUtilityDoubleDiffersByOneUlp(string ageField)
    {
        const string realRawAge = "0.183438060";
        const string legacyAge = "0.18343805999999999";
        object warning = GeometryPacket("CRITICAL", 89, 8.9, -0.01,
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture),
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture),
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture));
        var ageOverrides = new Dictionary<string, string>
        {
            ["sample_age_seconds"] = legacyAge,
            ["query_age_seconds"] = legacyAge,
            ["geometry_age_seconds"] = legacyAge
        };
        ageOverrides[ageField] = realRawAge;
        string raw = JsonForCombined(null, warning, geometryOverrides: ageOverrides);
        int geometryKeyIndex = raw.IndexOf("\"geometry_warning\":", StringComparison.Ordinal);
        Assert.That(geometryKeyIndex, Is.GreaterThanOrEqualTo(0));
        int geometryObjectStart = raw.IndexOf('{', geometryKeyIndex + "\"geometry_warning\":".Length);
        int geometryObjectEnd = raw.LastIndexOf('}');
        string warningObjectJson = raw.Substring(geometryObjectStart, geometryObjectEnd - geometryObjectStart);
        Type packetTypeForJson = receiverType.GetNestedType("GeometryWarningPacket",
            BindingFlags.Public | BindingFlags.NonPublic);
        object jsonUtilityPacket = JsonUtility.FromJson(warningObjectJson, packetTypeForJson);
        double jsonUtilityAge = (double)packetTypeForJson.GetField(ageField).GetValue(jsonUtilityPacket);
        MethodInfo rawParser = receiverType.GetMethod("TryGetFiniteJsonNumber", BindingFlags.Static | BindingFlags.NonPublic);
        var expectedRawAges = new Dictionary<string, double>();
        foreach (string field in new[] { "sample_age_seconds", "query_age_seconds", "geometry_age_seconds" })
        {
            object[] fieldParseArgs = { raw, "geometry_warning", field, 0d };
            Assert.That((bool)rawParser.Invoke(null, fieldParseArgs), Is.True);
            expectedRawAges[field] = (double)fieldParseArgs[3];
        }
        Assert.That(BitConverter.DoubleToInt64Bits(jsonUtilityAge),
            Is.Not.EqualTo(BitConverter.DoubleToInt64Bits(expectedRawAges[ageField])),
            "Fixture must retain the observed one-ULP parser difference.");

        MethodInfo validator = receiverType.GetMethod("IsValidCriticalGeometryWarning",
            BindingFlags.Static | BindingFlags.NonPublic);
        Assert.That((bool)validator.Invoke(null, new[] { warning, raw }), Is.True,
            "Raw JSON age, not JsonUtility's adjacent double, determines the age validity.");
        Invoke(handleGeometryWarning, receiver, raw, warning,
            System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);

        AssertGeometryActive(true, "One-ULP JsonUtility precision difference must not reject a valid age.");
        foreach (string field in new[] { "sample_age_seconds", "query_age_seconds", "geometry_age_seconds" })
        {
            double normalizedAge = (double)packetTypeForJson.GetField(field).GetValue(warning);
            Assert.That(normalizedAge, Is.EqualTo(expectedRawAges[field]),
                "Validated packet ages must be normalized to each field's strict raw JSON parse.");
        }
        Assert.That(GetPrivateField<double>(receiver, "highestExperimentalGeometrySampleAgeSeconds"), Is.EqualTo(expectedRawAges["sample_age_seconds"]));
        Assert.That(GetPrivateField<double>(receiver, "highestExperimentalGeometryQueryAgeSeconds"), Is.EqualTo(expectedRawAges["query_age_seconds"]));
        Assert.That(GetPrivateField<double>(receiver, "highestExperimentalGeometryAgeSeconds"), Is.EqualTo(expectedRawAges["geometry_age_seconds"]));
        Assert.That(GetPrivateField<double>(receiver, "activeExperimentalGeometryAgeAtReceiveSeconds"), Is.EqualTo(expectedRawAges["geometry_age_seconds"]));
    }

    [Test]
    public void GeometryAgeExactlyAtPointThreeSecondsIsAccepted()
    {
        var boundaryOverrides = new Dictionary<string, string>
        {
            ["sample_age_seconds"] = "0.3",
            ["query_age_seconds"] = "0.3",
            ["geometry_age_seconds"] = "0.3"
        };
        object warning = GeometryPacket("CRITICAL", 90, 9.0, -0.01, 0.3, 0.3, 0.3);
        string raw = JsonForCombined(null, warning, geometryOverrides: boundaryOverrides);
        double receive = System.Diagnostics.Stopwatch.GetTimestamp() /
                         (double)System.Diagnostics.Stopwatch.Frequency;
        Invoke(handleGeometryWarning, receiver, raw, warning, receive);
        AssertGeometryActive(true, "An initial geometry age exactly equal to 0.3 seconds remains valid.");
        Assert.That(GetPrivateField<double>(receiver, "activeExperimentalGeometryAgeAtReceiveSeconds"), Is.EqualTo(0.3d));
    }

    [Test]
    public void GeometryLeaseRemainsActiveBelowAndExpiresAbovePointThreeSeconds()
    {
        var ageOverrides = new Dictionary<string, string>
        {
            ["sample_age_seconds"] = "0.1",
            ["query_age_seconds"] = "0.1",
            ["geometry_age_seconds"] = "0.1"
        };
        object warning = GeometryPacket("CRITICAL", 92, 9.2, -0.01, 0.1, 0.1, 0.1);
        string raw = JsonForCombined(null, warning, geometryOverrides: ageOverrides);
        double receive = System.Diagnostics.Stopwatch.GetTimestamp() /
                         (double)System.Diagnostics.Stopwatch.Frequency;
        Invoke(handleGeometryWarning, receiver, raw, warning, receive);
        AssertGeometryActive(true);

        double now = System.Diagnostics.Stopwatch.GetTimestamp() /
                     (double)System.Diagnostics.Stopwatch.Frequency;
        SetPrivateField(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds", now - 0.199d);
        Invoke(GetMethod(receiverType, "ExpireExperimentalGeometryWarningIfNeeded"), receiver);
        AssertGeometryActive(true, "A total geometry age below 0.3 seconds remains active.");

        now = System.Diagnostics.Stopwatch.GetTimestamp() /
              (double)System.Diagnostics.Stopwatch.Frequency;
        SetPrivateField(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds", now - 0.201d);
        Invoke(GetMethod(receiverType, "ExpireExperimentalGeometryWarningIfNeeded"), receiver);
        AssertGeometryActive(false, "Monotonic elapsed time that takes total age beyond 0.3 seconds revokes.");
    }

    [Test]
    public void RealPrecisionGeometrySampleDoesNotRenewLeaseOnRepeatedReplyAndExpiresDuringSilence()
    {
        const string realRawAge = "0.183438060";
        const string legacyAge = "0.18343805999999999";
        object firstWarning = GeometryPacket("CRITICAL", 91, 9.1, -0.01,
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture),
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture),
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture),
            warningUpdateSequence: 1);
        var ageOverrides = new Dictionary<string, string>
        {
            ["sample_age_seconds"] = realRawAge,
            ["query_age_seconds"] = realRawAge,
            ["geometry_age_seconds"] = realRawAge
        };
        string firstRaw = JsonForCombined(null, firstWarning, geometryOverrides: ageOverrides);
        Invoke(handleGeometryWarning, receiver, firstRaw, firstWarning,
            System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
        AssertGeometryActive(true);
        double strictAge = GetPrivateField<double>(receiver, "activeExperimentalGeometryAgeAtReceiveSeconds");
        Assert.That(strictAge, Is.EqualTo(double.Parse(realRawAge,
            System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture)));

        object repeatedWarning = GeometryPacket("CRITICAL", 91, 9.1, -0.01,
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture),
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture),
            double.Parse(legacyAge, System.Globalization.CultureInfo.InvariantCulture),
            warningUpdateSequence: 2);
        string repeatedRaw = JsonForCombined(null, repeatedWarning, geometryOverrides: ageOverrides);
        double duplicateReceiveMonotonic = System.Diagnostics.Stopwatch.GetTimestamp() /
                                          (double)System.Diagnostics.Stopwatch.Frequency;
        SetPrivateField(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds",
            duplicateReceiveMonotonic - 0.05d);
        Invoke(handleGeometryWarning, receiver, repeatedRaw, repeatedWarning, duplicateReceiveMonotonic);
        AssertGeometryActive(true);
        Assert.That(GetPrivateField<double>(receiver, "activeExperimentalGeometryAgeAtReceiveSeconds"),
            Is.GreaterThanOrEqualTo(strictAge + 0.05d),
            "A repeated input sample carries forward elapsed monotonic age using the normalized age.");
        Assert.That(GetPrivateField<double>(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds"),
            Is.EqualTo(duplicateReceiveMonotonic).Within(0.01d),
            "Repeated-reply bookkeeping must start from the current monotonic instant after carrying elapsed age forward.");

        SetPrivateField(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency - 0.2d);
        Invoke(GetMethod(receiverType, "ExpireExperimentalGeometryWarningIfNeeded"), receiver);
        AssertGeometryActive(false, "A repeated reply must not extend the same input sample beyond 0.3 seconds.");
    }

    [Test]
    public void GeometryCriticalMissingFieldDiagnosticPreservesRejection()
    {
        object warning = GeometryPacket("CRITICAL", 81, 8.1, -0.01, 0.01, 0.01, 0.02);
        string raw = JsonForCombined(null, warning).Replace("\"query_age_seconds\":0.01,", string.Empty);
        Assert.That(raw, Does.Not.Contain("\"query_age_seconds\":"));
        AssertCriticalRejectionDiagnostic(raw, warning, "required_field_missing", "query_age_seconds",
            "\"present\":false,\"raw_json\":null,\"raw_json_is_valid_json_value\":null,\"deserialized\":0.01");
    }

    [Test]
    public void GeometryCriticalInvalidNumberDiagnosticPreservesRejection()
    {
        object warning = GeometryPacket("CRITICAL", 82, 8.2, -0.01, 0.01, 0.01, 0.02);
        string raw = JsonForCombined(null, warning,
            geometryOverrides: new Dictionary<string, string> { ["geometry_age_seconds"] = "\"NaN\"" });
        AssertCriticalRejectionDiagnostic(raw, warning, "geometry_age_seconds.finite_json_number",
            "geometry_age_seconds", "\"present\":true,\"raw_json\":\"NaN\",\"raw_json_is_valid_json_value\":true,\"deserialized\":0.02");
    }

    [Test]
    public void GeometryCriticalNumericMismatchDiagnosticPreservesRejection()
    {
        object warning = GeometryPacket("CRITICAL", 83, 8.3, -0.01, 0.01, 0.01, 0.02);
        string raw = JsonForCombined(null, warning,
            geometryOverrides: new Dictionary<string, string> { ["input_source_timestamp"] = "8.31" });
        AssertCriticalRejectionDiagnostic(raw, warning, "input_source_timestamp.matches_deserialized",
            "input_source_timestamp", "\"present\":true,\"raw_json\":8.31,\"raw_json_is_valid_json_value\":true,\"deserialized\":8.3");
    }

    [Test]
    public void DistinctGeometryFailureFieldsEachKeepTheirOwnDiagnosticEvidence()
    {
        object warning = GeometryPacket("CRITICAL", 86, 8.6, -0.01, 0.01, 0.01, 0.02);
        MethodInfo validator = receiverType.GetMethod("IsValidCriticalGeometryWarning",
            BindingFlags.Static | BindingFlags.NonPublic);
        string missingFieldRaw = JsonForCombined(null, warning)
            .Replace("\"query_age_seconds\":0.01,", string.Empty);
        object secondWarning = GeometryPacket("CRITICAL", 86, 8.6, -0.01, 0.01, 0.01, 0.02,
            warningUpdateSequence: 2);
        string mismatchRaw = JsonForCombined(null, secondWarning,
            geometryOverrides: new Dictionary<string, string> { ["input_source_timestamp"] = "8.61" });
        Assert.That((bool)validator.Invoke(null, new[] { warning, missingFieldRaw }), Is.False);
        Assert.That((bool)validator.Invoke(null, new[] { secondWarning, mismatchRaw }), Is.False);

        geometryDiagnosticLogs.Clear();
        Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        Application.logMessageReceived += CaptureGeometryDiagnosticLog;
        try
        {
            Invoke(handleGeometryWarning, receiver, missingFieldRaw, warning,
                System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
            Invoke(handleGeometryWarning, receiver, mismatchRaw, secondWarning,
                System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
        }
        finally
        {
            Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        }

        Assert.That(geometryDiagnosticLogs.Count(message =>
            message.Contains("[ExperimentalGeometryWarningValidation] rejected ")), Is.EqualTo(2),
            "Distinct failing fields must not be merged into the same suppression key.");
        Assert.That(geometryDiagnosticLogs.Any(message => message.Contains("required_field_missing")), Is.True);
        Assert.That(geometryDiagnosticLogs.Any(message => message.Contains("input_source_timestamp.matches_deserialized")), Is.True);
        Assert.That(GetPrivateField<bool>(receiver, "experimentalGeometryWarningActive"), Is.False);
    }

    [Test]
    public void IdenticalGeometryFailureIsSuppressedAfterFirstFullEvidenceAndCounted()
    {
        object firstWarning = GeometryPacket("CRITICAL", 87, 8.7, -0.01, 0.01, 0.01, 0.02,
            warningUpdateSequence: 1);
        object repeatedWarning = GeometryPacket("CRITICAL", 88, 8.8, -0.01, 0.01, 0.01, 0.02,
            warningUpdateSequence: 2);
        string firstRaw = JsonForCombined(null, firstWarning)
            .Replace("\"query_age_seconds\":0.01,", string.Empty);
        string repeatedRaw = JsonForCombined(null, repeatedWarning)
            .Replace("\"query_age_seconds\":0.01,", string.Empty);

        geometryDiagnosticLogs.Clear();
        Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        Application.logMessageReceived += CaptureGeometryDiagnosticLog;
        try
        {
            Invoke(handleGeometryWarning, receiver, firstRaw, firstWarning,
                System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
            Invoke(handleGeometryWarning, receiver, repeatedRaw, repeatedWarning,
                System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
            Invoke(GetMethod(receiverType, "FlushGeometryValidationSuppressionSummary"), receiver);
        }
        finally
        {
            Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        }

        Assert.That(geometryDiagnosticLogs.Count(message =>
            message.Contains("[ExperimentalGeometryWarningValidation] rejected ")), Is.EqualTo(1),
            "The first matching failure must retain its complete diagnostic while repeats are rate-limited.");
        string firstDiagnostic = geometryDiagnosticLogs.First(message =>
            message.Contains("[ExperimentalGeometryWarningValidation] rejected "));
        Assert.That(firstDiagnostic, Does.Contain("\"input_sequence\""));
        Assert.That(firstDiagnostic, Does.Contain("\"geometry_warning_raw\""));
        Assert.That(geometryDiagnosticLogs.Any(message =>
            message.Contains("repeated_failure_suppressed") && message.Contains("suppressed_repeated_count=1")), Is.True,
            "The suppression summary must report the number of identical failures omitted.");
    }

    [Test]
    public void GeometryCriticalAgeOverLeaseDiagnosticPreservesRejection()
    {
        object warning = GeometryPacket("CRITICAL", 84, 8.4, -0.01, 0.01, 0.01, 0.31);
        string raw = JsonForCombined(null, warning);
        AssertCriticalRejectionDiagnostic(raw, warning, "geometry_age_seconds.max_0_3_seconds",
            "geometry_age_seconds", "\"present\":true,\"raw_json\":0.31,\"raw_json_is_valid_json_value\":true,\"deserialized\":0.31");
    }

    private void AssertCriticalRejectionDiagnostic(string raw, object warning,
        string expectedFailureName, string expectedField, string expectedFieldEvidence)
    {
        MethodInfo validator = receiverType.GetMethod("IsValidCriticalGeometryWarning",
            BindingFlags.Static | BindingFlags.NonPublic);
        Assert.That(validator, Is.Not.Null, "Existing CRITICAL validator must remain available.");
        bool originalValidationResult = (bool)validator.Invoke(null, new[] { warning, raw });
        Assert.That(originalValidationResult, Is.False, "The pre-existing validation rule should reject this fixture.");

        geometryDiagnosticLogs.Clear();
        Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        Application.logMessageReceived += CaptureGeometryDiagnosticLog;
        try
        {
            Invoke(handleGeometryWarning, receiver, raw, warning,
                System.Diagnostics.Stopwatch.GetTimestamp() /
                (double)System.Diagnostics.Stopwatch.Frequency);
        }
        finally
        {
            Application.logMessageReceived -= CaptureGeometryDiagnosticLog;
        }

        AssertGeometryActive(false, "Diagnostic collection must not turn an invalid CRITICAL packet valid.");
        string diagnostic = geometryDiagnosticLogs.FirstOrDefault(message =>
            message.Contains("[ExperimentalGeometryWarningValidation] rejected "));
        Assert.That(diagnostic, Is.Not.Null, "Invalid CRITICAL packet should emit a diagnostic warning.");
        Assert.That(diagnostic, Does.Contain("\"name\":\"" + expectedFailureName + "\""));
        Assert.That(diagnostic, Does.Contain(expectedFieldEvidence));
        Assert.That(diagnostic, Does.Contain("\"local_receive_monotonic_seconds\":"));
        Assert.That(diagnostic, Does.Contain("\"geometry_warning_raw\":"));
        Assert.That(diagnostic, Does.Contain("\"run_id\":"));
        Assert.That(diagnostic, Does.Contain("\"layer\":"));
        Assert.That(diagnostic, Does.Contain("\"platform_instance_id\":"));
        Assert.That(diagnostic, Does.Contain("\"geometry_version_id\":"));
        Assert.That(diagnostic, Does.Contain("\"input_sequence\":"));
        Assert.That(diagnostic, Does.Contain("\"warning_update_sequence\":"));
        Assert.That(diagnostic, Does.Not.Contain("\"type\":\"realtime\""),
            "Diagnostic must include only geometry_warning, not the full realtime packet.");
        Assert.That(diagnostic, Does.Contain("\"field\":\"" + expectedField + "\""));

        bool validationAfterDiagnostic = (bool)validator.Invoke(null, new[] { warning, raw });
        Assert.That(validationAfterDiagnostic, Is.EqualTo(originalValidationResult),
            "Adding side-channel diagnostics must not alter the existing validator result.");
    }

    private void CaptureGeometryDiagnosticLog(string condition, string stackTrace, LogType type)
    {
        if (type == LogType.Warning) geometryDiagnosticLogs.Add(condition);
    }

    [TestCase("sample_age_seconds", "-0.01")]
    [TestCase("query_age_seconds", "-0.01")]
    [TestCase("geometry_age_seconds", "-0.01")]
    [TestCase("sample_age_seconds", "string")]
    [TestCase("query_age_seconds", "string")]
    [TestCase("geometry_age_seconds", "string")]
    [TestCase("sample_age_seconds", "NaN")]
    [TestCase("query_age_seconds", "NaN")]
    [TestCase("geometry_age_seconds", "NaN")]
    [TestCase("sample_age_seconds", "Infinity")]
    [TestCase("query_age_seconds", "Infinity")]
    [TestCase("geometry_age_seconds", "Infinity")]
    [TestCase("sample_age_seconds", "1e309")]
    [TestCase("query_age_seconds", "1e309")]
    [TestCase("geometry_age_seconds", "1e309")]
    public void InvalidGeometryAgeCannotActivate(string ageField, string age)
    {
        object warning = GeometryPacket("CRITICAL", 80, 8.0, -0.01, 0.01, 0.01, 0.02, 1, Layer, RunId);
        string rawAge = age == "string" || age == "NaN" || age == "Infinity"
            ? JsonString(age == "string" ? "0.02" : age) : age;
        string raw = JsonForCombined(null, warning,
            geometryOverrides: new Dictionary<string, string> { [ageField] = rawAge });
        Invoke(handleGeometryWarning, receiver, raw, warning, 8.0);
        AssertGeometryActive(false, "Invalid " + ageField + " must fail closed: " + age);
    }

    [Test]
    public void CurrentRunUnknownIdentityCannotActivate()
    {
        SetGeometryTelemetryContext(RunId, Layer, 0, string.Empty);
        DispatchGeometry("CRITICAL", 0, 9.1, -0.01, 0.01, 0.01, 0.02,
            updateSequence: 1, platformId: 0, geometryVersionId: string.Empty);
        AssertGeometryActive(false, "Neutral layer/platform/input identities cannot activate a geometric warning.");
        AssertGeometryWatermark(1);
    }

    [Test]
    public void NegativeWarningUpdateSequenceRemainsInvalidForGeometryWarning()
    {
        object warning = GeometryPacket("CRITICAL", 44, 4.4, -0.01, 0.01, 0.01, 0.02, 1, Layer, RunId);
        Invoke(handleGeometryWarning, receiver,
            JsonForCombined(null, warning, geometrySequenceRaw: "-1"), warning, 4.4);
        AssertGeometryActive(false, "Geometry warning_update_sequence must remain a positive integer.");
        AssertGeometryWatermark(-1, "Invalid negative warning_update_sequence must not advance the watermark.");
    }

    [Test]
    public void NegativePlatformIdSynchronizesAndActivatesCriticalGeometryWarning()
    {
        SetGeometryTelemetryContext(RunId, Layer, -234, "-234-g1");
        Assert.That(GetPrivateField<int>(receiver, "observedExperimentalGeometryPlatformInstanceId"), Is.EqualTo(-234));
        DispatchGeometry("CRITICAL", 45, 4.5, -0.01, 0.01, 0.01, 0.02,
            platformId: -234, geometryVersionId: "-234-g1");
        AssertGeometryActive(true, "A valid negative Unity instance ID must activate geometry warning.");
        Assert.That(GetProperty<int>(receiver, "ExperimentalGeometryPlatformInstanceId"), Is.EqualTo(-234));
    }

    [Test]
    public void NegativePlatformIdClearRevokesGeometryWarning()
    {
        SetGeometryTelemetryContext(RunId, Layer, -234, "-234-g1");
        DispatchGeometry("CRITICAL", 46, 4.6, -0.01, 0.01, 0.01, 0.02,
            platformId: -234, geometryVersionId: "-234-g1");
        AssertGeometryActive(true);
        DispatchGeometry("CLEAR", 47, 4.7, 0.01, 0.01, 0.01, 0.02,
            updateSequence: 2, platformId: -234, geometryVersionId: "-234-g1");
        AssertGeometryActive(false, "A matching negative platform identity may revoke with CLEAR.");
    }

    [Test]
    public void OldPlatformOrVersionCannotActivateOrClearNegativePlatformWarning()
    {
        SetGeometryTelemetryContext(RunId, Layer, -234, "-234-g1");
        DispatchGeometry("CRITICAL", 48, 4.8, -0.01, 0.01, 0.01, 0.02,
            updateSequence: 1, platformId: -567, geometryVersionId: "-567-g1");
        AssertGeometryActive(false, "A CRITICAL from an old platform cannot activate.");
        DispatchGeometry("CRITICAL", 49, 4.9, -0.01, 0.01, 0.01, 0.02,
            updateSequence: 2, platformId: -234, geometryVersionId: "-234-g2");
        AssertGeometryActive(false, "A version mismatch cannot activate.");
        DispatchGeometry("CRITICAL", 50, 5.0, -0.01, 0.01, 0.01, 0.02,
            updateSequence: 3, platformId: -234, geometryVersionId: "-234-g1");
        AssertGeometryActive(true);
        DispatchGeometry("CLEAR", 51, 5.1, 0.01, 0.01, 0.01, 0.02,
            updateSequence: 4, platformId: -567, geometryVersionId: "-567-g1");
        AssertGeometryActive(true, "A CLEAR from an old platform cannot revoke the current warning.");
        DispatchGeometry("CLEAR", 52, 5.2, 0.01, 0.01, 0.01, 0.02,
            updateSequence: 5, platformId: -234, geometryVersionId: "-234-g2");
        AssertGeometryActive(true, "A version mismatch cannot revoke the current warning.");
    }

    [Test]
    public void NegativePlatformIdWarningStillExpiresByTotalGeometryAge()
    {
        SetGeometryTelemetryContext(RunId, Layer, -234, "-234-g1");
        DispatchGeometry("CRITICAL", 52, 5.2, -0.01, 0.04, 0.03, 0.08,
            platformId: -234, geometryVersionId: "-234-g1");
        AssertGeometryActive(true);
        SetPrivateField(receiver, "activeExperimentalGeometryReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() /
            (double)System.Diagnostics.Stopwatch.Frequency - 0.23d);
        Invoke(GetMethod(receiverType, "ExpireExperimentalGeometryWarningIfNeeded"), receiver);
        AssertGeometryActive(false, "Negative platform identity does not bypass the 0.3-second total-age lease.");
    }

    [Test]
    public void GeometryWarningRequiresAvailableCurrentPlatformTelemetryIdentity()
    {
        SetTelemetry(null);
        DispatchGeometry("CRITICAL", 53, 5.3, -0.01, 0.01, 0.01, 0.02);
        AssertGeometryActive(false, "A missing telemetry identity cannot satisfy strict current-platform matching.");
    }

    [Test]
    public void SynchronizingNewNegativePlatformContextRevokesOldGeometryWarning()
    {
        SetGeometryTelemetryContext(RunId, Layer, -234, "-234-g1");
        DispatchGeometry("CRITICAL", 54, 5.4, -0.01, 0.01, 0.01, 0.02,
            platformId: -234, geometryVersionId: "-234-g1");
        AssertGeometryActive(true);
        SetGeometryTelemetryContext(RunId, Layer, -567, "-567-g1");
        AssertGeometryActive(false, "Synchronizing a new negative platform identity clears the prior context.");
    }

    [Test]
    public void NewRunResetsGeometryWatermarkAndClearsOldDisplay()
    {
        DispatchGeometry("CRITICAL", 100, 10.0, -0.01, 0.01, 0.01, 0.02, updateSequence: 10);
        AssertGeometryActive(true);
        Invoke(resetWarningForRun, receiver, "run-next");
        SetPrivateField(levelManager, "runId", "run-next");
        SetGeometryTelemetryContext("run-next", Layer, 123, "platform-123-g1");
        AssertGeometryActive(false);
        AssertGeometryWatermark(-1);
        DispatchGeometry("CRITICAL", 1, 1.0, -0.01, 0.01, 0.01, 0.02,
            runId: "run-next", updateSequence: 1);
        AssertGeometryActive(true);
    }

    [Test]
    public void OrdinaryRealtimeStillAppliesWhenGeometryObjectIsMalformedOrMissing()
    {
        string missing = "{\"type\":\"realtime\",\"x\":2.5,\"y\":-1.25,\"difficulty\":1,\"rmse\":0.75}";
        SetPrivateField(receiver, "pendingJsonData", missing);
        SetPrivateField(receiver, "pendingReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
        Invoke(GetMethod(receiverType, "Update"), receiver);
        Assert.That(GetPrivateField<int>(receiver, "backendCountX"), Is.EqualTo(1));
        Assert.That(GetPrivateField<float>(receiver, "backendSumX"), Is.EqualTo(2.5f));
        Assert.That(GetPrivateField<float>(receiver, "backendRealRMSE"), Is.EqualTo(0.75f));
    }

    [Test]
    public void WarningUpdateSequenceOrdersRevocationAndBlocksSamePredictionRevival()
    {
        Dispatch("STRONG", true, 5, 100, 5.0, 1.0, warningUpdateSequence: 10);
        AssertActive(true);
        Dispatch("UNKNOWN", false, 5, 100, 5.0, 1.05, warningUpdateSequence: 11);
        AssertActive(false, "Newer UNKNOWN revokes despite unchanged prediction/source identity.");
        Dispatch("STRONG", true, 5, 100, 5.0, 1.06, warningUpdateSequence: 10);
        AssertActive(false, "Late lower-sequence STRONG is ignored.");
        Dispatch("STRONG", true, 5, 101, 5.05, 1.10, warningUpdateSequence: 12);
        AssertActive(false, "Newer reply carrying revoked prediction cannot reignite it.");
        Dispatch("STRONG", true, 6, 102, 5.10, 1.15, warningUpdateSequence: 13);
        AssertActive(true, "A genuinely newer prediction may activate.");
        Assert.That(GetProperty<long>(receiver, "ExperimentalModelPredictionSequence"), Is.EqualTo(6));
        AssertWatermark(13);
    }

    [Test]
    public void DuplicateReplyIsIgnoredAndNewSequenceForSamePredictionDoesNotRenew()
    {
        Dispatch("STRONG", true, 20, 200, 8.0, 2.0, warningUpdateSequence: 10);
        AssertActive(true);
        Dispatch("UNKNOWN", false, 20, 200, 8.0, 2.05, warningUpdateSequence: 10);
        AssertActive(true, "Duplicate sequence cannot change the prompt.");
        AssertWatermark(10);
        Dispatch("STRONG", true, 20, 201, 8.05, 2.10, warningUpdateSequence: 11);
        AssertActive(true);
        Assert.That(GetPrivateField<double>(receiver, "activeExperimentalReceiveMonotonicSeconds"),
            Is.EqualTo(2.0).Within(1e-9), "New reply sequence cannot renew the same prediction.");
    }

    [Test]
    public void NewerSafeStatusRevokesCurrentPredictionImmediately()
    {
        Dispatch("STRONG", true, 25, 250, 8.5, 2.5, warningUpdateSequence: 15);
        AssertActive(true);
        Dispatch("SAFE", false, 25, 250, 8.5, 2.5, warningUpdateSequence: 16);
        AssertActive(false, "A newer SAFE status revokes despite reusing the last successful sample identity.");
        AssertWatermark(16);
        Dispatch("STRONG", true, 25, 250, 8.5, 2.5, warningUpdateSequence: 17);
        AssertActive(false, "A newer reply carrying the SAFE-revoked prediction cannot revive it.");
    }

    [Test]
    public void OldRunIsInertAndLayerTransitionPreservesWatermark()
    {
        Dispatch("STRONG", true, 30, 300, 10.0, 3.0, warningUpdateSequence: 10);
        AssertActive(true);
        Dispatch("UNKNOWN", false, 30, 301, 10.05, 3.05,
            runId: "run-old", warningUpdateSequence: 99);
        AssertActive(true, "Prior run cannot affect current prompt or watermark.");
        AssertWatermark(10);
        SetPrivateField(levelManager, "platformsPassed", 1);
        Invoke(layerTransition, receiver);
        sequenceFloor.SetValue(receiver, 300L);
        SetPrivateField(receiver, "hasLayerInputSequenceFloor", true);
        AssertActive(false);
        AssertWatermark(10, "Layer transition retains run-wide reply sequence.");
        Dispatch("UNKNOWN", false, 30, 301, 10.05, 3.10,
            warningUpdateSequence: 11, layer: 1);
        AssertActive(false, "Previous-layer reply cannot affect current prompt.");
        AssertWatermark(11, "Ordered previous-layer reply still advances watermark.");
        Dispatch("STRONG", true, 31, 301, 10.10, 3.15,
            warningUpdateSequence: 10, layer: 2);
        AssertActive(false, "Older sequence remains ignored after transition.");
        Dispatch("STRONG", true, 31, 301, 10.10, 3.20,
            warningUpdateSequence: 12, layer: 2);
        AssertActive(true, "A fresh reply in the new layer can activate.");
    }

    [Test]
    public void NewRunResetsWarningReplyWatermark()
    {
        Dispatch("STRONG", true, 40, 400, 12.0, 4.0, warningUpdateSequence: 50);
        AssertActive(true);
        Invoke(resetWarningForRun, receiver, "run-next");
        SetPrivateField(levelManager, "runId", "run-next");
        SetPrivateField(receiver, "layerInputSequenceFloor", -1L);
        SetPrivateField(receiver, "hasLayerInputSequenceFloor", false);
        AssertWatermark(-1);
        Dispatch("STRONG", true, 1, 1, 1.0, 4.1,
            runId: "run-next", warningUpdateSequence: 1);
        AssertActive(true, "First observed sequence is accepted after starting a new run.");
    }

    [Test]
    public void LayerZeroFaultRevokesAndCannotActivate()
    {
        Dispatch("STRONG", true, 50, 500, 15.0, 5.0, warningUpdateSequence: 20);
        AssertActive(true);
        Dispatch("UNKNOWN", false, 50, 500, 15.0, 5.05,
            warningUpdateSequence: 21, layer: 0);
        AssertActive(false, "Current-run layer=0 fault status revokes immediately.");
        Dispatch("STRONG", true, 51, 501, 15.1, 5.10,
            warningUpdateSequence: 22, layer: 0);
        AssertActive(false, "Layer zero is never eligible to activate.");
        AssertWatermark(22);
    }

    [TestCase("missing")]
    [TestCase("zero")]
    [TestCase("fraction")]
    [TestCase("negative")]
    [TestCase("string")]
    [TestCase("overflow")]
    [TestCase("leading_zero")]
    public void MissingOrInvalidWarningUpdateSequenceFailsClosed(string invalid)
    {
        Dispatch("STRONG", true, 60, 600, 16.0, 6.0, warningUpdateSequence: 30);
        AssertActive(true);
        object warning = Packet("UNKNOWN", false, 60, 600, 16.0, Layer,
            warningUpdateSequence: 31);
        string raw = JsonFor(warning,
            omit: invalid == "missing" ? "warning_update_sequence" : null,
            updateSequenceRaw: invalid == "missing" ? null :
                invalid == "zero" ? "0" :
                invalid == "fraction" ? "31.5" :
                invalid == "negative" ? "-1" :
                invalid == "string" ? "\"31\"" :
                invalid == "overflow" ? "9223372036854775808" : "031");
        Invoke(handleWarning, receiver, raw, warning, 6.05);
        AssertActive(false, "Invalid sequence fails closed for experimental prompt.");
        AssertWatermark(30, "Invalid sequence cannot advance the trusted watermark.");
    }

    [Test]
    public void MissingWarningObjectCannotRevokeWithoutRunIdentity()
    {
        Dispatch("STRONG", true, 70, 700, 17.0, 7.0, warningUpdateSequence: 40);
        AssertActive(true);
        Invoke(handleWarning, receiver, "{\"type\":\"realtime\"}", null, 7.05);
        AssertActive(true, "Without a run identity, this packet cannot be attributed to the current run.");
        AssertWatermark(40);
    }

    [Test]
    public void RealtimeValuesStillApplyWhenCurrentRunWarningSequenceIsInvalid()
    {
        Dispatch("STRONG", true, 90, 900, 19.0, 9.0, warningUpdateSequence: 60);
        AssertActive(true);

        object warning = Packet("UNKNOWN", false, 90, 900, 19.0, Layer,
            warningUpdateSequence: 61);
        string raw = JsonFor(warning, omit: "warning_update_sequence")
            .Replace("\"x\":0", "\"x\":2.5")
            .Replace("\"y\":0", "\"y\":-1.25")
            .Replace("\"rmse\":0", "\"rmse\":0.75");
        SetPrivateField(receiver, "activeExperimentalReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() /
            (double)System.Diagnostics.Stopwatch.Frequency - 0.05d);
        SetPrivateField(receiver, "pendingJsonData", raw);
        SetPrivateField(receiver, "pendingReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
        Invoke(GetMethod(receiverType, "Update"), receiver);

        Assert.That(GetPrivateField<int>(receiver, "backendCountX"), Is.EqualTo(1));
        Assert.That(GetPrivateField<float>(receiver, "backendSumX"), Is.EqualTo(2.5f));
        Assert.That(GetPrivateField<float>(receiver, "backendRealRMSE"), Is.EqualTo(0.75f));
        AssertActive(false, "Invalid experimental metadata revokes only the experimental prompt.");
    }

    [Test]
    public void TotalSilenceExpiresWarningByMonotonicLease()
    {
        Dispatch("STRONG", true, 80, 800, 18.0, 8.0, warningUpdateSequence: 50);
        AssertActive(true);
        SetPrivateField(receiver, "activeExperimentalReceiveMonotonicSeconds",
            System.Diagnostics.Stopwatch.GetTimestamp() /
            (double)System.Diagnostics.Stopwatch.Frequency - 0.31d);
        Invoke(GetMethod(receiverType, "ExpireExperimentalModelWarningIfNeeded"), receiver);
        AssertActive(false, "The 0.3-second lease expires without any new UDP reply.");

        Dispatch("STRONG", true, 80, 801, 18.05, 8.40, warningUpdateSequence: 51);
        AssertActive(false, "A later reply cannot revive the prediction whose monotonic lease expired.");
    }

    [Test]
    public void ProximityApproachAcceptsNegativePlatformIdAndUsesIndependentWatermark()
    {
        SetProximityTelemetryContext(RunId, Layer, -234, "platform--234-g1");
        DispatchProximity("APPROACH", 1, 12.5, -234, "platform--234-g1");

        AssertProximityActive(true);
        Assert.That(GetProperty<int>(receiver, "ExperimentalProximityPlatformInstanceId"), Is.EqualTo(-234));
        Assert.That(GetProperty<long>(receiver, "ExperimentalProximityInputSequence"), Is.EqualTo(1));
        AssertProximityWatermark(1);
        AssertGeometryWatermark(-1, "Proximity ordering is isolated from geometry ordering.");
        AssertWatermark(-1, "Proximity ordering is isolated from model ordering.");
    }

    [TestCase("CLEAR")]
    [TestCase("UNKNOWN")]
    public void MatchingProximityClearAndUnknownRevokeOnlyProximity(string state)
    {
        DispatchProximity("APPROACH", 10, 10.0);
        AssertProximityActive(true);

        DispatchProximity(state, 11, 10.1, updateSequence: 2);
        AssertProximityActive(false);
        Assert.That(GetPrivateField<long>(receiver, "highestRevokedExperimentalProximityInputSequence"), Is.EqualTo(11));
        AssertActive(false, "Proximity status must not activate the model warning.");
        AssertGeometryActive(false, "Proximity status must not activate geometry warning.");
        AssertProximityWatermark(2);
    }

    [Test]
    public void ProximityOldRunLayerAndPlatformCannotRevokeCurrentWarning()
    {
        DispatchProximity("APPROACH", 20, 20.0);
        AssertProximityActive(true);

        DispatchProximity("CLEAR", 21, 20.1, runId: "run-old", updateSequence: 2);
        AssertProximityActive(true, "An old run cannot revoke the current proximity warning.");

        SetPrivateField(levelManager, "platformsPassed", 1);
        Invoke(layerTransition, receiver);
        AssertProximityActive(false, "The actual Unity layer transition clears the previous layer lease.");
        SetProximityTelemetryContext(RunId, 2, 123, "platform-123-g1");
        DispatchProximity("APPROACH", 22, 22.0, layer: 1, updateSequence: 2);
        AssertProximityActive(false, "An old-layer approach cannot activate.");
        DispatchProximity("APPROACH", 23, 23.0, layer: 2, updateSequence: 1);
        AssertProximityActive(false, "Layer transitions do not reset the run-wide update watermark.");
        DispatchProximity("APPROACH", 24, 24.0, layer: 2, updateSequence: 3);
        AssertProximityActive(true, "A newer current-layer approach is accepted.");
    }

    [Test]
    public void ProximityAgeSumAcceptsToleranceAndRejectsMismatchBeyondTolerance()
    {
        var withinTolerance = new Dictionary<string, string>
        {
            ["sample_age_seconds"] = "0.1",
            ["query_age_seconds"] = "0.2",
            ["geometry_age_seconds"] = "0.3"
        };
        object accepted = ProximityPacket("APPROACH", 27, 27.0, 1,
            sampleAge: 0.1, queryAge: 0.2, geometryAge: 0.3);
        Invoke(handleProximityWarning, receiver, JsonForProximity(accepted, overrides: withinTolerance), accepted,
            StopwatchSeconds() + 1d);
        AssertProximityActive(true, "Floating-point representation at the sum boundary remains within tolerance.");

        var mismatch = new Dictionary<string, string>
        {
            ["sample_age_seconds"] = "0.1",
            ["query_age_seconds"] = "0.2",
            ["geometry_age_seconds"] = "0.299999998"
        };
        object rejected = ProximityPacket("APPROACH", 28, 28.0, 2,
            sampleAge: 0.1, queryAge: 0.2, geometryAge: 0.299999998);
        Invoke(handleProximityWarning, receiver, JsonForProximity(rejected, overrides: mismatch), rejected,
            StopwatchSeconds());
        AssertProximityActive(false, "Age sum discrepancy above the allowed tolerance must fail closed.");
    }

    [Test]
    public void ProximityExactLeaseBoundaryIsAcceptedAtReceiveInstant()
    {
        object warning = ProximityPacket("APPROACH", 26, 26.0, 1,
            sampleAge: 0.1, queryAge: 0.2, geometryAge: 0.3);
        Invoke(handleProximityWarning, receiver, JsonForProximity(warning), warning,
            StopwatchSeconds() + 1d);
        AssertProximityActive(true, "An input whose total age is exactly 0.3 seconds is valid at its receive instant.");
        Assert.That(GetPrivateField<double>(receiver, "activeExperimentalProximityAgeAtReceiveSeconds"), Is.EqualTo(0.3d));
    }

    [Test]
    public void ProximityTelemetryPlatformSwitchImmediatelyRevokesActiveWarning()
    {
        DispatchProximity("APPROACH", 25, 25.0);
        AssertProximityActive(true);

        SetProximityTelemetryContext(RunId, Layer, -567, "platform--567-g2");
        AssertProximityActive(false, "A synchronized telemetry platform/version change revokes the prior context.");
        Assert.That(GetPrivateField<long>(receiver, "highestRevokedExperimentalProximityInputSequence"), Is.EqualTo(25));
    }

    [Test]
    public void ProximityMismatchedPlatformOrVersionCannotActivateOrClear()
    {
        DispatchProximity("APPROACH", 30, 30.0, platformId: -321, geometryVersionId: "old-platform");
        AssertProximityActive(false, "A stale platform identity cannot activate.");

        DispatchProximity("APPROACH", 31, 31.0, updateSequence: 2);
        AssertProximityActive(true);
        DispatchProximity("CLEAR", 32, 32.0, platformId: 456, geometryVersionId: "platform-456-g1", updateSequence: 3);
        AssertProximityActive(true, "A CLEAR from a different platform cannot revoke.");
        DispatchProximity("UNKNOWN", 33, 33.0, geometryVersionId: "platform-123-g2", updateSequence: 4);
        AssertProximityActive(true, "A version mismatch cannot revoke.");
    }

    [Test]
    public void ProximityPositiveTinyQAndEquivalentExactHorizonAreAccepted()
    {
        var overrides = new Dictionary<string, string>
        {
            ["q"] = "1e-300",
            ["outward_velocity"] = "-999",
            ["horizon_seconds"] = "7.5e-1"
        };
        DispatchProximity("APPROACH", 29, 29.0, updateSequence: 1, overrides: overrides);
        AssertProximityActive(true, "The client accepts backend APPROACH with any finite outward velocity and q > 0; it does not recompute a trigger threshold.");
        Assert.That(GetProperty<double>(receiver, "ExperimentalProximityQ"), Is.EqualTo(1e-300));
        Assert.That(GetProperty<double>(receiver, "ExperimentalProximityHorizonSeconds"), Is.EqualTo(0.75d));
    }

    [Test]
    public void ProximityRejectsFreshnessThatExpiresBeforeMainThreadProcessing()
    {
        object warning = ProximityPacket("APPROACH", 59, 59.0, 1,
            sampleAge: 0.02, queryAge: 0.03, geometryAge: 0.05);
        string raw = JsonForProximity(warning);
        Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds() - 0.251d);
        AssertProximityActive(false, "Elapsed local monotonic time is included in the 0.3-second lease.");
    }

    [Test]
    public void ProximityWarningUpdateAndInputSequencesAcceptPositiveInt64Maximum()
    {
        const long maximum = long.MaxValue;
        object warning = ProximityPacket("APPROACH", maximum, 60.0, maximum);
        string raw = JsonForProximity(warning,
            updateSequenceRaw: maximum.ToString(System.Globalization.CultureInfo.InvariantCulture));
        Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds());

        AssertProximityActive(true);
        AssertProximityWatermark(maximum);
        Assert.That(GetProperty<long>(receiver, "ExperimentalProximityInputSequence"), Is.EqualTo(maximum));
    }

    [TestCase("source", "\"other_source\"")]
    [TestCase("policy_id", "\"other_policy\"")]
    [TestCase("schema_version", "2")]
    [TestCase("experimental", "false")]
    [TestCase("enabled", "false")]
    public void ProximityProtocolMismatchInStatusCannotClearCurrentWarning(string field, string value)
    {
        DispatchProximity("APPROACH", 58, 58.0, updateSequence: 1);
        AssertProximityActive(true);
        object warning = ProximityPacket("CLEAR", 59, 59.0, 2);
        string raw = JsonForProximity(warning,
            updateSequenceRaw: "2", overrides: new Dictionary<string, string> { [field] = value });
        Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds());
        AssertProximityActive(true, "A status from a non-matching protocol envelope is not a valid revoke.");
    }

    [Test]
    public void ProximityMalformedApproachRawFlagDoesNotRevokeCurrentWarning()
    {
        DispatchProximity("APPROACH", 57, 57.0, updateSequence: 1);
        AssertProximityActive(true);
        object warning = ProximityPacket("APPROACH", 58, 58.0, 2);
        string raw = JsonForProximity(warning,
            updateSequenceRaw: "2", overrides: new Dictionary<string, string> { ["q_valid"] = "\"true\"" });
        Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds());
        AssertProximityActive(true, "Malformed APPROACH is ignored and the independent lease remains authoritative.");
    }

    [Test]
    public void ProximityUnsupportedStateCannotRevokeCurrentWarning()
    {
        DispatchProximity("APPROACH", 37, 37.0, updateSequence: 1);
        AssertProximityActive(true);
        object warning = ProximityPacket("SAFE", 38, 38.0, 2);
        string raw = JsonForProximity(warning, updateSequenceRaw: "2");
        Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds());
        AssertProximityActive(true, "Only documented CLEAR and UNKNOWN statuses revoke.");
        AssertProximityWatermark(1, "Unrecognized state cannot advance the trusted sequence.");
    }

    [Test]
    public void ProximityDuplicateAndReorderedRepliesDoNotChangeLease()
    {
        DispatchProximity("APPROACH", 40, 40.0, updateSequence: 10);
        AssertProximityActive(true);
        DispatchProximity("CLEAR", 41, 41.0, updateSequence: 10);
        AssertProximityActive(true, "A duplicate warning update is ignored.");
        DispatchProximity("CLEAR", 42, 42.0, updateSequence: 9);
        AssertProximityActive(true, "A reordered warning update is ignored.");
        AssertProximityWatermark(10);
    }

    [Test]
    public void RepeatedProximityInputCannotRenewLeaseOrReigniteAfterRevocation()
    {
        DispatchProximity("APPROACH", 50, 50.0, sampleAge: 0.04, queryAge: 0.03,
            geometryAge: 0.07, updateSequence: 1);
        AssertProximityActive(true);
        double before = GetPrivateField<double>(receiver, "activeExperimentalProximityAgeAtReceiveSeconds");
        double now = StopwatchSeconds();
        SetPrivateField(receiver, "activeExperimentalProximityReceiveMonotonicSeconds", now - 0.05d);
        DispatchProximity("APPROACH", 50, 50.0, sampleAge: 0.07, queryAge: 0.05,
            geometryAge: 0.12, updateSequence: 2);
        AssertProximityActive(true);
        Assert.That(GetPrivateField<double>(receiver, "activeExperimentalProximityAgeAtReceiveSeconds"),
            Is.GreaterThanOrEqualTo(before + 0.05d), "Elapsed age must be carried forward for repeated samples.");

        SetPrivateField(receiver, "activeExperimentalProximityReceiveMonotonicSeconds", StopwatchSeconds() - 0.20d);
        Invoke(GetMethod(receiverType, "ExpireExperimentalProximityWarningIfNeeded"), receiver);
        AssertProximityActive(false, "Total monotonic age above 0.3 seconds expires during silence.");
        DispatchProximity("APPROACH", 50, 50.0, sampleAge: 0.12, queryAge: 0.08,
            geometryAge: 0.20, updateSequence: 3);
        AssertProximityActive(false, "An expired input identity cannot be reactivated by a later reply.");
    }

    [TestCase("sample_age_seconds", "-0.01")]
    [TestCase("query_age_seconds", "-0.01")]
    [TestCase("geometry_age_seconds", "-0.01")]
    [TestCase("geometry_age_seconds", "0.31")]
    [TestCase("q", "0")]
    [TestCase("q", "-0.1")]
    [TestCase("outward_velocity", "\"NaN\"")]
    [TestCase("horizon_seconds", "0.7500000001")]
    [TestCase("input_sequence", "1.5")]
    [TestCase("input_sequence", "-1")]
    [TestCase("input_sequence", "9223372036854775808")]
    [TestCase("input_source_timestamp", "0")]
    [TestCase("input_source_timestamp", "1e309")]
    public void InvalidProximityNumericFieldsFailClosed(string field, string rawValue)
    {
        DispatchProximity("APPROACH", 60, 60.0, updateSequence: 1);
        AssertProximityActive(true);
        var overrides = new Dictionary<string, string> { [field] = rawValue };
        DispatchProximity("APPROACH", 61, 61.0, updateSequence: 2, overrides: overrides);
        AssertProximityActive(false, "Invalid " + field + " must fail closed.");
        SetPrivateField(receiver, "highestExperimentalProximityWarningUpdateSequence", -1L);
        SetPrivateField(receiver, "hasExperimentalProximityWarningUpdateSequence", false);
    }

    [TestCase("zero")]
    [TestCase("fraction")]
    [TestCase("negative")]
    [TestCase("string")]
    [TestCase("overflow")]
    [TestCase("duplicate")]
    public void InvalidProximityWarningSequenceFailsClosed(string invalid)
    {
        DispatchProximity("APPROACH", 70, 70.0, updateSequence: 10);
        AssertProximityActive(true);
        string rawSequence = invalid == "zero" ? "0" :
            invalid == "fraction" ? "11.5" :
            invalid == "negative" ? "-11" :
            invalid == "string" ? "\"11\"" :
            invalid == "overflow" ? "9223372036854775808" : "11";
        string raw = JsonForProximity(ProximityPacket("CLEAR", 71, 71.0, 11),
            updateSequenceRaw: rawSequence, duplicateUpdateSequence: invalid == "duplicate");
        object warning = ProximityPacket("CLEAR", 71, 71.0, 11);
        Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds());
        AssertProximityActive(false, "Invalid or duplicate update sequence must fail closed for current identity.");
        AssertProximityWatermark(10, "Invalid update sequence must not advance the trusted watermark.");
    }

    [Test]
    public void MissingProximityUpdateSequenceFailsClosedForCurrentIdentity()
    {
        DispatchProximity("APPROACH", 70, 70.0, updateSequence: 10);
        AssertProximityActive(true);
        object warning = ProximityPacket("CLEAR", 71, 71.0, 11);
        string raw = JsonForProximity(warning, omitUpdateSequence: true);
        Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds());
        AssertProximityActive(false);
        AssertProximityWatermark(10);
    }

    [Test]
    public void ProximityRequiresExactProtocolAndBooleanFlagsForApproach()
    {
        long nextInput = 80;
        long nextUpdate = 1;
        foreach (var test in new[]
        {
            ("source", JsonString("other_source")),
            ("policy_id", JsonString("other_policy")),
            ("schema_version", "2"),
            ("active", "false"),
            ("valid", "false"),
            ("q_valid", "false")
        })
        {
            object warning = ProximityPacket("APPROACH", nextInput, 80.0 + nextInput, nextUpdate);
            string raw = JsonForProximity(warning,
                updateSequenceRaw: nextUpdate.ToString(System.Globalization.CultureInfo.InvariantCulture),
                overrides: new Dictionary<string, string> { [test.Item1] = test.Item2 });
            Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds());
            AssertProximityActive(false, "Invalid protocol field " + test.Item1 + " must not activate.");
            SetPrivateField(receiver, "highestExperimentalProximityWarningUpdateSequence", -1L);
            SetPrivateField(receiver, "hasExperimentalProximityWarningUpdateSequence", false);
            nextInput++;
            nextUpdate++;
        }
    }

    [Test]
    public void ProximityNewRunResetsItsIndependentWatermarkAndRevokedInputBarrier()
    {
        DispatchProximity("APPROACH", 75, 75.0, updateSequence: 100);
        AssertProximityActive(true);
        Invoke(resetWarningForRun, receiver, "run-next");
        SetPrivateField(levelManager, "runId", "run-next");
        SetGeometryTelemetryContext("run-next", Layer, 123, "platform-123-g1");
        Invoke(GetMethod(receiverType, "SynchronizeExperimentalProximityTelemetryContext"), receiver);
        AssertProximityActive(false);
        AssertProximityWatermark(-1);
        Assert.That(GetPrivateField<long>(receiver, "highestRevokedExperimentalProximityInputSequence"), Is.EqualTo(-1));

        DispatchProximity("APPROACH", 1, 1.0, runId: "run-next", updateSequence: 1);
        AssertProximityActive(true, "A new run starts a separate proximity ordering and input stream.");
    }

    [Test]
    public void ProximityDisableAndRunEndClearOnlyItsIndependentState()
    {
        DispatchProximity("APPROACH", 90, 90.0);
        AssertProximityActive(true);
        SetPrivateField(receiver, "enableExperimentalProximityWarning", false);
        Invoke(GetMethod(receiverType, "ExpireExperimentalProximityWarningIfNeeded"), receiver);
        AssertProximityActive(false, "Disabling the feature immediately clears the display.");
        DispatchProximity("APPROACH", 91, 91.0, updateSequence: 2);
        AssertProximityActive(false, "Disabled proximity input cannot activate the display.");
        AssertProximityWatermark(1, "Disabled input is ignored without advancing its independent watermark.");

        SetPrivateField(receiver, "enableExperimentalProximityWarning", true);
        DispatchProximity("APPROACH", 91, 91.0, updateSequence: 2);
        AssertProximityActive(true);
        Type receiverPublicType = receiverType;
        MethodInfo notifyRunEnded = receiverPublicType.GetMethod("NotifyRunEnded", BindingFlags.Static | BindingFlags.Public);
        Invoke(notifyRunEnded, null, "test_run_end");
        AssertProximityActive(false, "Run end clears proximity immediately.");
    }

    [Test]
    public void ProximityRealtimeAndOtherWarningChannelsRemainIndependent()
    {
        object model = Packet("STRONG", true, 1, 100, 100.0, Layer, RunId, 1);
        object geometry = GeometryPacket("CRITICAL", 101, 101.0, -0.02, 0.01, 0.01, 0.02,
            1, Layer, RunId);
        object proximity = ProximityPacket("APPROACH", 102, 102.0, 1);
        string raw = JsonForCombined(model, geometry) + string.Empty;
        raw = raw.Substring(0, raw.Length - 1) + ",\"proximity_warning\":" + JsonForProximityObject(proximity) + "}";
        SetPrivateField(receiver, "pendingJsonData", raw.Replace("\"x\":0", "\"x\":2.5")
            .Replace("\"y\":0", "\"y\":-1.25").Replace("\"rmse\":0", "\"rmse\":0.75"));
        SetPrivateField(receiver, "pendingReceiveMonotonicSeconds", StopwatchSeconds());
        Invoke(GetMethod(receiverType, "Update"), receiver);
        AssertActive(true);
        AssertGeometryActive(true);
        AssertProximityActive(true);
        Assert.That(GetPrivateField<int>(receiver, "backendCountX"), Is.EqualTo(1));
        Assert.That(GetPrivateField<float>(receiver, "backendSumX"), Is.EqualTo(2.5f));
        Assert.That(GetPrivateField<float>(receiver, "backendRealRMSE"), Is.EqualTo(0.75f));
        AssertWatermark(1);
        AssertGeometryWatermark(1);
        AssertProximityWatermark(1);
    }

    private void AssertProximityActive(bool expected, string message = null)
    {
        Assert.That(GetProperty<bool>(receiver, "ExperimentalProximityWarningActive"), Is.EqualTo(expected),
            (message ?? string.Empty) + " watermark=" + GetPrivateField<long>(receiver,
                "highestExperimentalProximityWarningUpdateSequence") + ", input=" +
            GetPrivateField<long>(receiver, "activeExperimentalProximityInputSequence") + ", age=" +
            GetPrivateField<double>(receiver, "activeExperimentalProximityAgeAtReceiveSeconds"));
    }

    private void AssertProximityWatermark(long expected, string message = null)
    {
        Assert.That(GetPrivateField<long>(receiver, "highestExperimentalProximityWarningUpdateSequence"),
            Is.EqualTo(expected), message);
    }

    private void AssertActive(bool expected, string message = null)
    {
        Assert.That(GetProperty<bool>(receiver, "ExperimentalModelWarningActive"), Is.EqualTo(expected), message);
    }

    private void AssertGeometryActive(bool expected, string message = null)
    {
        bool actual = GetProperty<bool>(receiver, "ExperimentalGeometryWarningActive");
        Assert.That(actual, Is.EqualTo(expected), (message ?? string.Empty) +
            " internal=" + GetPrivateField<bool>(receiver, "experimentalGeometryWarningActive") +
            ", watermark=" + GetPrivateField<long>(receiver, "highestExperimentalGeometryWarningUpdateSequence") +
            ", latestInput=" + GetPrivateField<long>(receiver, "highestExperimentalGeometryInputSequence") +
            ", reason=" + GetPrivateField<string>(receiver, "activeExperimentalGeometryReason") +
            ", age=" + GetPrivateField<double>(receiver, "activeExperimentalGeometryAgeAtReceiveSeconds"));
    }

    private void AssertWatermark(long expected, string message = null)
    {
        Assert.That(GetPrivateField<long>(receiver, "highestExperimentalWarningUpdateSequence"),
            Is.EqualTo(expected), message);
    }

    private void AssertGeometryWatermark(long expected, string message = null)
    {
        Assert.That(GetPrivateField<long>(receiver, "highestExperimentalGeometryWarningUpdateSequence"),
            Is.EqualTo(expected), message);
    }

    private void DispatchCombined(string modelState, bool modelValid, long predictionSequence,
        long modelInputSequence, double modelInputTimestamp, string geometryState,
        long geometryInputSequence, double geometryInputTimestamp, double sampleAge,
        double queryAge, double geometryAge, long updateSequence = 1)
    {
        object model = Packet(modelState, modelValid, predictionSequence, modelInputSequence,
            modelInputTimestamp, Layer, RunId, updateSequence);
        object geometry = GeometryPacket(geometryState, geometryInputSequence, geometryInputTimestamp,
            geometryState == "CRITICAL" ? -0.02f : 0.1f, sampleAge, queryAge, geometryAge,
            updateSequence, Layer, RunId);
        string raw = JsonForCombined(model, geometry);
        Invoke(handleRealtimeWarnings, receiver, raw,
            System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
    }

    private void SetProximityTelemetryContext(string runId, int layer, int platformId, string versionId)
    {
        SetGeometryTelemetryContext(runId, layer, platformId, versionId);
        Invoke(GetMethod(receiverType, "SynchronizeExperimentalProximityTelemetryContext"), receiver);
    }

    private void SetGeometryTelemetryContext(string runId, int layer, int platformId, string versionId)
    {
        object telemetry = Activator.CreateInstance(udpManagerType.GetNestedType("UnityGameTelemetry"));
        SetPublicField(telemetry, "run_id", runId);
        SetPublicField(telemetry, "platformLevel", layer);
        SetPublicField(telemetry, "geometry_platform_instance_id", platformId);
        SetPublicField(telemetry, "geometry_version_id", versionId);
        SetTelemetry(telemetry);
        Invoke(GetMethod(receiverType, "SynchronizeExperimentalGeometryTelemetryContext"), receiver);
    }

    private void SetTelemetry(object telemetry)
    {
        PropertyInfo property = udpManagerType.GetProperty("LastTelemetry",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        Assert.That(property, Is.Not.Null);
        MethodInfo setter = property.GetSetMethod(true);
        Assert.That(setter, Is.Not.Null);
        setter.Invoke(udpManager, new[] { telemetry });
    }

    private void DispatchProximity(string state, long inputSequence, double inputTimestamp,
        int platformId = 123, string geometryVersionId = "platform-123-g1",
        string runId = RunId, int layer = Layer, long updateSequence = 1,
        double sampleAge = 0.01, double queryAge = 0.01, double geometryAge = 0.02,
        Dictionary<string, string> overrides = null)
    {
        object warning = ProximityPacket(state, inputSequence, inputTimestamp, updateSequence,
            platformId, geometryVersionId, runId, layer, sampleAge, queryAge, geometryAge);
        string raw = JsonForProximity(warning, updateSequenceRaw: null, overrides: overrides);
        Invoke(handleProximityWarning, receiver, raw, warning, StopwatchSeconds());
    }

    private object ProximityPacket(string state, long inputSequence, double inputTimestamp,
        long updateSequence = 1, int platformId = 123,
        string geometryVersionId = "platform-123-g1", string runId = RunId, int layer = Layer,
        double sampleAge = 0.01, double queryAge = 0.01, double geometryAge = 0.02)
    {
        object warning = Activator.CreateInstance(proximityPacketType);
        SetPublicField(warning, "schema_version", 1);
        SetPublicField(warning, "experimental", true);
        SetPublicField(warning, "enabled", true);
        SetPublicField(warning, "source", "tte_proximity_rule_v1");
        SetPublicField(warning, "policy_id", "tte_proximity_h075_confirm2_v1");
        SetPublicField(warning, "run_id", runId);
        SetPublicField(warning, "layer", layer);
        SetPublicField(warning, "platform_instance_id", platformId);
        SetPublicField(warning, "geometry_version_id", geometryVersionId);
        SetPublicField(warning, "input_sequence", inputSequence);
        SetPublicField(warning, "input_source_timestamp", inputTimestamp);
        SetPublicField(warning, "warning_update_sequence", updateSequence);
        SetPublicField(warning, "state", state);
        SetPublicField(warning, "active", state == "APPROACH");
        SetPublicField(warning, "valid", state != "UNKNOWN");
        SetPublicField(warning, "sample_age_seconds", sampleAge);
        SetPublicField(warning, "query_age_seconds", queryAge);
        SetPublicField(warning, "geometry_age_seconds", geometryAge);
        SetPublicField(warning, "q", state == "APPROACH" ? 0.25d : 0d);
        SetPublicField(warning, "q_valid", state == "APPROACH");
        SetPublicField(warning, "outward_velocity", state == "APPROACH" ? 0.4d : 0d);
        SetPublicField(warning, "horizon_seconds", 0.75d);
        SetPublicField(warning, "reason", "synthetic_tte_rule");
        return warning;
    }

    private string JsonForProximity(object warning, bool omitUpdateSequence = false,
        string updateSequenceRaw = null, bool duplicateUpdateSequence = false,
        Dictionary<string, string> overrides = null)
    {
        string proximityJson = JsonForProximityObject(warning, omitUpdateSequence,
            updateSequenceRaw, duplicateUpdateSequence, overrides);
        return "{\"type\":\"realtime\",\"x\":0,\"y\":0,\"difficulty\":1,\"rmse\":0,\"proximity_warning\":" + proximityJson + "}";
    }

    private string JsonForProximityObject(object warning, bool omitUpdateSequence = false,
        string updateSequenceRaw = null, bool duplicateUpdateSequence = false,
        Dictionary<string, string> overrides = null)
    {
        string[] names = { "schema_version", "experimental", "enabled", "source", "policy_id", "run_id", "layer",
            "platform_instance_id", "geometry_version_id", "input_sequence", "input_source_timestamp",
            "warning_update_sequence", "state", "active", "valid", "sample_age_seconds", "query_age_seconds",
            "geometry_age_seconds", "q", "q_valid", "outward_velocity", "horizon_seconds", "reason" };
        var fields = new List<string>();
        foreach (string name in names)
        {
            if (name == "warning_update_sequence" && omitUpdateSequence) continue;
            object value = GetField(warning, name);
            string serialized = value is string stringValue ? JsonString(stringValue) :
                value is bool boolValue ? (boolValue ? "true" : "false") : Number(value);
            if (name == "warning_update_sequence" && updateSequenceRaw != null) serialized = updateSequenceRaw;
            if (overrides != null && overrides.TryGetValue(name, out string replacement)) serialized = replacement;
            fields.Add(JsonString(name) + ":" + serialized);
            if (name == "warning_update_sequence" && duplicateUpdateSequence)
                fields.Add("\"warning_update_sequence\":" + serialized);
        }
        return "{" + string.Join(",", fields) + "}";
    }

    private static double StopwatchSeconds()
    {
        return System.Diagnostics.Stopwatch.GetTimestamp() /
               (double)System.Diagnostics.Stopwatch.Frequency;
    }

    private void DispatchGeometry(string state, long inputSequence, double inputTimestamp,
        double clearance, double sampleAge, double queryAge, double geometryAge,
        string runId = RunId, int layer = Layer, long updateSequence = 1,
        int platformId = 123, string geometryVersionId = "platform-123-g1")
    {
        object warning = GeometryPacket(state, inputSequence, inputTimestamp,
            clearance, sampleAge, queryAge, geometryAge, updateSequence, layer, runId,
            platformId, geometryVersionId);
        Invoke(handleGeometryWarning, receiver, JsonForCombined(null, warning), warning,
            System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency);
    }

    private void Dispatch(string state, bool valid, long predictionSequence, long inputSequence,
        double inputTimestamp, double receiveTime, string runId = RunId, int layer = Layer,
        long warningUpdateSequence = -1)
    {
        if (warningUpdateSequence <= 0) warningUpdateSequence = ++nextWarningUpdateSequence;
        else nextWarningUpdateSequence = System.Math.Max(nextWarningUpdateSequence, warningUpdateSequence);
        object warning = Packet(state, valid, predictionSequence, inputSequence, inputTimestamp,
            layer, runId, warningUpdateSequence);
        Invoke(handleWarning, receiver, JsonFor(warning), warning, receiveTime);
    }

    private object Packet(string state, bool valid, long predictionSequence,
        long inputSequence, double inputTimestamp, int layer, string runId = RunId,
        long warningUpdateSequence = 1)
    {
        object warning = Activator.CreateInstance(packetType);
        SetPublicField(warning, "schema_version", 1);
        SetPublicField(warning, "experimental", true);
        SetPublicField(warning, "enabled", true);
        SetPublicField(warning, "model_id", ModelId);
        SetPublicField(warning, "run_id", runId);
        SetPublicField(warning, "layer", layer);
        SetPublicField(warning, "state", state);
        SetPublicField(warning, "valid", valid);
        SetPublicField(warning, "probability_valid", valid);
        SetPublicField(warning, "strong_probability", valid ? 0.95f : 0.0f);
        SetPublicField(warning, "prediction_sequence", predictionSequence);
        SetPublicField(warning, "warning_update_sequence", warningUpdateSequence);
        SetPublicField(warning, "input_sequence", inputSequence);
        SetPublicField(warning, "input_source_timestamp", inputTimestamp);
        SetPublicField(warning, "feature_age_seconds", 0.0f);
        SetPublicField(warning, "reason", valid ? "confirmed" : "unknown");
        return warning;
    }

    private object GeometryPacket(string state, long inputSequence, double inputTimestamp,
        double clearance, double sampleAge, double queryAge, double geometryAge,
        long warningUpdateSequence = 1, int layer = Layer, string runId = RunId,
        int platformId = 123, string geometryVersionId = "platform-123-g1")
    {
        object warning = (object)Activator.CreateInstance(geometryPacketType);
        SetPublicField(warning, "schema_version", 1);
        SetPublicField(warning, "experimental", true);
        SetPublicField(warning, "enabled", true);
        SetPublicField(warning, "source", "geometry_rule");
        SetPublicField(warning, "policy_id", "outer_clearance_nonpositive_v1");
        SetPublicField(warning, "run_id", runId);
        SetPublicField(warning, "layer", layer);
        SetPublicField(warning, "platform_instance_id", platformId);
        SetPublicField(warning, "geometry_version_id", geometryVersionId);
        SetPublicField(warning, "input_sequence", inputSequence);
        SetPublicField(warning, "input_source_timestamp", inputTimestamp);
        SetPublicField(warning, "warning_update_sequence", warningUpdateSequence);
        SetPublicField(warning, "clearance", (float)clearance);
        SetPublicField(warning, "clearance_valid", true);
        SetPublicField(warning, "state", state);
        SetPublicField(warning, "valid", true);
        SetPublicField(warning, "reason", "synthetic_geometry_rule");
        SetPublicField(warning, "sample_age_seconds", sampleAge);
        SetPublicField(warning, "query_age_seconds", queryAge);
        SetPublicField(warning, "geometry_age_seconds", geometryAge);
        return warning;
    }

    private string JsonForCombined(object model, object geometry,
        string geometrySequenceRaw = null, Dictionary<string, string> geometryOverrides = null)
    {
        var fields = new List<string>();
        if (model != null)
        {
            Add(fields, "model_warning", JsonForModelObject(model), null);
        }
        if (geometry != null)
        {
            Add(fields, "geometry_warning", JsonForGeometryObject(geometry, geometrySequenceRaw, geometryOverrides), null);
        }
        return "{\"type\":\"realtime\",\"x\":0,\"y\":0,\"difficulty\":1,\"rmse\":0," +
               string.Join(",", fields) + "}";
    }

    private string JsonFor(object warning, string omit = null, string updateSequenceRaw = null)
    {
        string modelJson = JsonForModelObject(warning, omit, updateSequenceRaw);
        return "{\"type\":\"realtime\",\"x\":0,\"y\":0,\"difficulty\":1,\"rmse\":0,\"model_warning\":" + modelJson + "}";
    }

    private string JsonForModelObject(object warning, string omit = null, string updateSequenceRaw = null)
    {
        var fields = new List<string>();
        Add(fields, "schema_version", GetField(warning, "schema_version").ToString(), omit);
        Add(fields, "experimental", BoolJson(GetField(warning, "experimental")), omit);
        Add(fields, "enabled", BoolJson(GetField(warning, "enabled")), omit);
        Add(fields, "model_id", JsonString((string)GetField(warning, "model_id")), omit);
        Add(fields, "run_id", JsonString((string)GetField(warning, "run_id")), omit);
        Add(fields, "layer", GetField(warning, "layer").ToString(), omit);
        Add(fields, "state", JsonString((string)GetField(warning, "state")), omit);
        Add(fields, "valid", BoolJson(GetField(warning, "valid")), omit);
        Add(fields, "probability_valid", BoolJson(GetField(warning, "probability_valid")), omit);
        Add(fields, "strong_probability", ((float)GetField(warning, "strong_probability")).ToString(System.Globalization.CultureInfo.InvariantCulture), omit);
        Add(fields, "prediction_sequence", GetField(warning, "prediction_sequence").ToString(), omit);
        Add(fields, "warning_update_sequence", updateSequenceRaw ?? GetField(warning, "warning_update_sequence").ToString(), omit);
        Add(fields, "input_sequence", GetField(warning, "input_sequence").ToString(), omit);
        Add(fields, "input_source_timestamp", ((double)GetField(warning, "input_source_timestamp")).ToString(System.Globalization.CultureInfo.InvariantCulture), omit);
        Add(fields, "feature_age_seconds", ((float)GetField(warning, "feature_age_seconds")).ToString(System.Globalization.CultureInfo.InvariantCulture), omit);
        Add(fields, "reason", JsonString((string)GetField(warning, "reason")), omit);
        return "{" + string.Join(",", fields) + "}";
    }

    private string JsonForGeometryObject(object warning, string updateSequenceRaw = null,
        Dictionary<string, string> overrides = null)
    {
        var fields = new List<string>();
        AddGeometry(fields, warning, "schema_version", GetField(warning, "schema_version").ToString(), overrides);
        AddGeometry(fields, warning, "experimental", BoolJson(GetField(warning, "experimental")), overrides);
        AddGeometry(fields, warning, "enabled", BoolJson(GetField(warning, "enabled")), overrides);
        AddGeometry(fields, warning, "source", JsonString((string)GetField(warning, "source")), overrides);
        AddGeometry(fields, warning, "policy_id", JsonString((string)GetField(warning, "policy_id")), overrides);
        AddGeometry(fields, warning, "run_id", JsonString((string)GetField(warning, "run_id")), overrides);
        AddGeometry(fields, warning, "layer", GetField(warning, "layer").ToString(), overrides);
        AddGeometry(fields, warning, "platform_instance_id", GetField(warning, "platform_instance_id").ToString(), overrides);
        AddGeometry(fields, warning, "geometry_version_id", JsonString((string)GetField(warning, "geometry_version_id")), overrides);
        AddGeometry(fields, warning, "input_sequence", GetField(warning, "input_sequence").ToString(), overrides);
        AddGeometry(fields, warning, "input_source_timestamp", Number(GetField(warning, "input_source_timestamp")), overrides);
        AddGeometry(fields, warning, "warning_update_sequence", updateSequenceRaw ?? GetField(warning, "warning_update_sequence").ToString(), overrides);
        AddGeometry(fields, warning, "clearance", Number((float)GetField(warning, "clearance")), overrides);
        AddGeometry(fields, warning, "clearance_valid", BoolJson(GetField(warning, "clearance_valid")), overrides);
        AddGeometry(fields, warning, "state", JsonString((string)GetField(warning, "state")), overrides);
        AddGeometry(fields, warning, "valid", BoolJson(GetField(warning, "valid")), overrides);
        AddGeometry(fields, warning, "reason", JsonString((string)GetField(warning, "reason")), overrides);
        AddGeometry(fields, warning, "sample_age_seconds", Number(GetField(warning, "sample_age_seconds")), overrides);
        AddGeometry(fields, warning, "query_age_seconds", Number(GetField(warning, "query_age_seconds")), overrides);
        AddGeometry(fields, warning, "geometry_age_seconds", Number(GetField(warning, "geometry_age_seconds")), overrides);
        return "{" + string.Join(",", fields) + "}";
    }

    private static string Number(object value)
    {
        return Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
    }

    private static void AddGeometry(List<string> fields, object warning, string name, string value,
        Dictionary<string, string> overrides)
    {
        if (overrides != null && overrides.TryGetValue(name, out string replacement)) value = replacement;
        fields.Add(JsonString(name) + ":" + value);
    }

    private static Type FindProjectType(string name)
    {
        Type result = AppDomain.CurrentDomain.GetAssemblies()
            .Select(assembly => assembly.GetType(name, false))
            .FirstOrDefault(type => type != null);
        Assert.That(result, Is.Not.Null, "Could not find project type " + name);
        return result;
    }

    private static object GetField(object target, string name)
    {
        FieldInfo field = target.GetType().GetField(name, BindingFlags.Instance | BindingFlags.Public);
        Assert.That(field, Is.Not.Null, "Missing public field " + name);
        return field.GetValue(target);
    }

    private static void SetPublicField(object target, string name, object value)
    {
        FieldInfo field = target.GetType().GetField(name, BindingFlags.Instance | BindingFlags.Public);
        Assert.That(field, Is.Not.Null, "Missing public field " + name);
        field.SetValue(target, value);
    }

    private static void Add(List<string> fields, string name, string value, string omit)
    {
        if (!string.Equals(name, omit, StringComparison.Ordinal))
            fields.Add(JsonString(name) + ":" + value);
    }

    private static string BoolJson(object value)
    {
        return (bool)value ? "true" : "false";
    }

    private static string JsonString(string value)
    {
        return "\"" + (value ?? string.Empty).Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }

    private static MethodInfo GetMethod(Type type, string name)
    {
        return type.GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic);
    }

    private static void Invoke(MethodInfo method, object target, params object[] arguments)
    {
        Assert.That(method, Is.Not.Null, "Missing reflected member");
        method.Invoke(target, arguments);
    }

    private static object InvokeStatic(Type type, string name, object[] arguments)
    {
        MethodInfo method = type.GetMethod(name, BindingFlags.Static | BindingFlags.NonPublic);
        Assert.That(method, Is.Not.Null, "Missing reflected member " + name);
        return method.Invoke(null, arguments);
    }

    private static object GetStaticProperty(Type type, string name)
    {
        PropertyInfo property = type.GetProperty(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        Assert.That(property, Is.Not.Null, "Missing static property " + name);
        return property.GetValue(null);
    }

    private static void SetStaticProperty(Type type, string name, object value)
    {
        PropertyInfo property = type.GetProperty(name, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        Assert.That(property, Is.Not.Null, "Missing static property " + name);
        MethodInfo setter = property.GetSetMethod(true);
        Assert.That(setter, Is.Not.Null, "Missing setter for static property " + name);
        setter.Invoke(null, new[] { value });
    }

    private static void SetPrivateField(object target, string name, object value)
    {
        FieldInfo field = target.GetType().GetField(name,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        Assert.That(field, Is.Not.Null, "Missing reflected field " + name);
        field.SetValue(target, value);
    }

    private static T GetPrivateField<T>(object target, string name)
    {
        FieldInfo field = target.GetType().GetField(name,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        Assert.That(field, Is.Not.Null, "Missing reflected field " + name);
        return (T)field.GetValue(target);
    }

    private static T GetProperty<T>(object target, string name)
    {
        PropertyInfo property = target.GetType().GetProperty(name,
            BindingFlags.Instance | BindingFlags.Public);
        Assert.That(property, Is.Not.Null, "Missing property " + name);
        return (T)property.GetValue(target);
    }
}
