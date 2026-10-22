$ErrorActionPreference = 'Stop'
$backend = 'C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend'
$project = 'C:\Users\QIYUXUAN\Desktop\Endless-Driver-Tutorial - EP9\Endless-Driver-Tutorial - EP9'
$out = Join-Path $backend 'parallel_20261020/collection_freeze_primary'
$game = 'C:\Users\QIYUXUAN\Desktop\VectorAI_Normal_Game\6F1E9B5F-1F20-4BB7-BCB4-6E8B23795054'
$annotations = Get-Content -LiteralPath (Join-Path $out 'session_annotations.json') -Raw | ConvertFrom-Json
$target = $annotations.future_collection_target
$lockPath = Join-Path $backend 'parallel_20261016/pilot_readiness/tools/preflight_lock.json'
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$backendChecks = @($lock.sha256.PSObject.Properties | ForEach-Object {
    $path = Join-Path $backend $_.Name
    $observed = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    [pscustomobject]@{ Path = $_.Name; ExpectedSHA256 = $_.Value; ObservedSHA256 = $observed; Match = $observed -eq $_.Value }
})
$manifestPath = $game + '_sha256_manifest.json'
$gameManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$playerChecks = @($gameManifest.files.PSObject.Properties | ForEach-Object {
    $path = Join-Path $game $_.Name
    $observed = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    [pscustomobject]@{ Path = $_.Name; ExpectedSHA256 = $_.Value; ObservedSHA256 = $observed; Match = $observed -eq $_.Value }
})
$dll = Join-Path $game 'VectorAI_Data/Managed/Assembly-CSharp.dll'
[void][Reflection.Assembly]::LoadFrom('C:/Program Files/Unity/Hub/Editor/6000.3.9f1/Editor/Data/Managed/Unity.Cecil.dll')
$assembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly($dll)
try {
    $level = $assembly.MainModule.Types | Where-Object Name -eq 'LevelManager'
    $method = $level.Methods | Where-Object Name -eq 'NormalizeSessionLayers'
    $tokens = @($method.Body.Instructions | Where-Object { $_.OpCode.Code.ToString() -eq 'Ldtoken' })
    if ($tokens.Count -ne 1) { throw 'Cannot uniquely identify layer-normalization constant array.' }
    $bytes = $tokens[0].Operand.Resolve().InitialValue
    if (-not $bytes.Length -or $bytes.Length % 4 -ne 0) { throw 'Invalid layer choice array bytes.' }
    $choices = @(for ($i=0; $i -lt $bytes.Length; $i+=4) { [BitConverter]::ToInt32($bytes, $i) })
    $ui = $assembly.MainModule.Types | Where-Object Name -eq 'UIManager'
    $binaryHasUnifiedUIField = @($ui.Fields | Where-Object Name -eq 'enableUnifiedRiskPresentation').Count -ne 0
} finally { $assembly.Dispose() }
$buildReceiptPath = $game + '_build_receipt.json'
$buildReceipt = Get-Content -LiteralPath $buildReceiptPath -Raw | ConvertFrom-Json
$scenePath = 'Assets/Endness Driving/Scenes/Stage/EndlessFalling.unity'
$scene = Get-Content -LiteralPath (Join-Path $project $scenePath) -Raw
$sceneHash = (Get-FileHash -LiteralPath (Join-Path $project $scenePath) -Algorithm SHA256).Hash.ToLowerInvariant()
$fields = @('enableExperimentalModelWarning','enableExperimentalGeometryWarning','enableExperimentalProximityWarning',
    'sendRate','enableGeometryDiagnostics','geometryDiagnosticSampleInterval','enableHighFrequencyLightDiagnostics',
    'highFrequencyLightSampleInterval','enableEventDrivenFullGeometryDiagnostics','enableFixedCadenceFullGeometryDiagnostics',
    'eventDrivenFullGeometryMinInterval','fixedFullGeometrySampleInterval','fullGeometryBudgetMilliseconds')
$sceneFields = [ordered]@{}
foreach ($field in $fields) {
    $match = [regex]::Match($scene, '(?m)^\s*' + [regex]::Escape($field) + ':\s*([^\r\n]+)')
    $sceneFields[$field] = if ($match.Success) { $match.Groups[1].Value.Trim() } else { $null }
}
$registry = @()
foreach ($path in @('Software\Unity\UnityEditor\QI YUXUAN\VectorAI', 'Software\QI YUXUAN\VectorAI')) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($path)
    if ($null -eq $key) { continue }
    try {
        foreach ($name in $key.GetValueNames()) {
            if ($name -match '^Sensitivity.Falling_') {
                $raw = $key.GetValue($name)
                $decoded = if ($raw -is [long]) { [BitConverter]::Int64BitsToDouble($raw) } else { $null }
                $registry += [pscustomobject]@{ Location = $path; ValueName = $name;
                    StoredBits = $raw.ToString(); DecodedDouble = $decoded;
                    Interpretation = 'Read-only persisted setting observation, NOT a historical or live-run measurement.' }
            }
        }
    } finally { $key.Close() }
}
$model = Get-Content -LiteralPath (Join-Path $backend 'parallel_20261011/deployment_refit/output/artifact/manifest.json') -Raw | ConvertFrom-Json
$blockers = @('operator_runtime_configuration_receipt_not_completed')
if ($choices -notcontains [int]$target.session_layers) { $blockers += 'requested_layer_count_not_supported_by_current_player_binary' }
if (@($backendChecks | Where-Object {-not $_.Match}).Count) { $blockers += 'backend_locked_hash_mismatch' }
if (@($playerChecks | Where-Object {-not $_.Match}).Count) { $blockers += 'player_manifest_hash_mismatch' }
$result = [ordered]@{
    Schema = 1; VersionTargetID = 'PILOT055_D3_L5_OLD_UI_COMPAT5_R1_20261020';
    Status = 'STATIC_PINNED_RUNTIME_CHECK_PENDING'; StaticInspectionOnly = $true;
    RuntimeVerified = $false; CollectionReleaseApproved = $false;
    Target = $target; Blockers = $blockers;
    GameExecutable = (Join-Path $game 'VectorAI.exe'); BackendLauncher = (Join-Path $backend 'Start_Pilot_10P_Experimental.cmd');
    BuildID = $buildReceipt.build_id; BuildFlags = $buildReceipt.build_flags;
    SupportedLayersFromBinary = $choices; LayerRequestSilentlyMapsTo = ($choices | Sort-Object {[Math]::Abs($_ - [int]$target.session_layers)} | Select-Object -First 1);
    BinaryContainsUnifiedUIField = $binaryHasUnifiedUIField;
    PlayerHashChecks = $playerChecks; BackendHashChecks = $backendChecks;
    Model = @{ID=$model.model_id; Features=$model.features.Count; Threshold=$model.threshold;
        HorizonSeconds=$model.prediction_horizon_seconds; ConfirmationPoints=$model.confirmation_points;
        DeploymentDescription='Existing LightGBM plus independent TTE rule, NOT a fused deployed predictor'};
    SourceSceneMatchesBuildReceipt = $sceneHash -eq $buildReceipt.source_hashes_pre_build.$scenePath;
    SavedSceneFields = $sceneFields; SavedSceneFieldsAreNotLiveRuntimeVerification = $true;
    SensitivityRegistryObservations = $registry;
    RegistryOrSceneSettingsWritten = $false; ModelOrLauncherChanged = $false;
    InputHashes = @{
        Annotations = (Get-FileHash -LiteralPath (Join-Path $out 'session_annotations.json') -Algorithm SHA256).Hash;
        BackendLock = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash;
        PlayerManifest = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash;
        PlayerBuildReceipt = (Get-FileHash -LiteralPath $buildReceiptPath -Algorithm SHA256).Hash
    }
}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $out 'COLLECTION_SPEC_DRAFT.json') -Encoding utf8
[pscustomobject]@{Status=$result.Status;BackendHashesMatched=@($backendChecks | Where-Object Match).Count;
    PlayerHashesMatched=@($playerChecks | Where-Object Match).Count;SupportedLayers=$choices;
    RequestedLayers=$target.session_layers;Blockers=$blockers;OldUIBinary=(-not $binaryHasUnifiedUIField)} | ConvertTo-Json -Depth 4
