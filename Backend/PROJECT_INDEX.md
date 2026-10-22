# Backend Project Index

Reviewed against current source: **2026-10-19**. This guide maps current entry points; historical experiment folders do not imply deployment approval.

## Workspace and services

- Backend: C:/Users/QIYUXUAN/Desktop/fyp_Backend (3)/fyp_Backend
- Unity project: C:/Users/QIYUXUAN/Desktop/Endless-Driver-Tutorial - EP9/Endless-Driver-Tutorial - EP9
- Wii sender: C:/Users/QIYUXUAN/Desktop/WiiBalanceWalker_x86
- Wii deployment entry: Start_WiiBalanceWalker_Verified.cmd in that Wii directory; deployment_manifest.json pins the seven EXE/PDB/config/DLL files. See DEPLOYMENT_README.md there. Matching symbols were reconciled on 2026-10-19; existing root EXE/config/DLLs were preserved, and old output was archived.
- master_server.py starts four daemon-thread services receiving on 127.0.0.1.

| Service | Implementation | Receive / reply UDP port | Unity counterpart, relative to Unity project |
| --- | --- | --- | --- |
| Login/register | login_server.py, db_manager.py | 6000 / sender address | Assets/Login/LoginCinematicRuntime.cs |
| Endless Falling | UDPRecevier.py | 5005 / 5006 | Assets/BackEnd/UDPManager.cs; Assets/Endness Falling/Scripts/UdpFrontendReceiver.cs and UIManager.cs |
| Running Ball / Path Following | runningball_ai.py | 5007 / 5008 | Assets/RunningBall/Scripts/PathNetworkManager.cs and RunningBallNetwork.cs |
| Car Dodging | car_backend.py | 5009 / 5010 | Assets/Endness Driving/Scripts/AI/UDPCarNetworkManager.cs |

The existing RMSE, calibration, Q-learning difficulty and report/chat paths are separate from experimental warnings.

## Startup entry points

| Entry point | Role |
| --- | --- |
| [Start_Pilot_10P_Experimental.cmd](Start_Pilot_10P_Experimental.cmd) | Pilot entry: pins Python, explicitly enables model/calibration compatibility, TTE shadow and proximity replies, runs preflight, then calls the experiment launcher. |
| [Start_Master_With_Model.cmd](Start_Master_With_Model.cmd) | Starts master with the configured Python 3.14 executable; respects inherited warning environment overrides. |
| [Start_Master_With_Proximity_Shadow.cmd](Start_Master_With_Proximity_Shadow.cmd) | Sets PROXIMITY_SHADOW_ENABLED=1. It does not clear inherited PROXIMITY_REPLY_ENABLED; check the environment before assuming shadow-only operation. |
| [Start_Master_With_Proximity_Experiment.cmd](Start_Master_With_Proximity_Experiment.cmd) | Enables shadow and independent proximity_warning replies. Unity's display switch must also be enabled. |
| [master_server.py](master_server.py) | Direct entry: model/calibration compatibility default ON unless explicitly overridden. The standalone receiver retains separate default-OFF bridge behavior. |

Run only one backend. [Preflight](parallel_20261016/pilot_readiness/tools/preflight.py) uses preflight_lock.json beside it and writes receipts under parallel_20261016/pilot_readiness/preflight_receipts/.

**The master “All 4 ... online” banner is unconditional after thread startup: it is not proof of service readiness or model loading.** Check service-specific output, the model-loaded message and actual session creation after Unity Start. Preflight is not runtime or performance acceptance.

## Current experimental warning paths

| Channel | Implementation and meaning |
| --- | --- |
| Orange model | parallel_20261011/realtime_integration/bridge.py loads the pinned artifact through parallel_20261010/backend/. Model test1009-strong-deployment-refit-20261011: TEST1009, **24 features**, threshold **0.65**, **0.75-second horizon**, **two-point confirmation**. Predicts final-fall risk. |
| Red geometry | parallel_20261011/realtime_integration/geometry_danger.py; separate current-geometry danger rule, not a model probability. |
| TTE shadow | parallel_20261014/proximity_shadow_backend_luna/proximity_shadow.py; deterministic proximity rule, recorded in telemetry_logs/proximity_shadow.jsonl. |
| Purple proximity reply | parallel_20261015/proximity_reply_luna/proximity_reply.py; independent proximity_warning with context, sequencing and expiry behavior. |

The deployed system uses **LightGBM plus a separate TTE rule**, not a deployed fused predictor. Offline 26/27-feature and LSTM candidates are not this 24-feature runtime. See [LSTM comparison](parallel_20261017/lstm_primary/REPORT.md).

The artifact manifest is parallel_20261011/deployment_refit/output/artifact/manifest.json. Bridge ownership comes from explicit start_session run IDs; telemetry alone does not authorize a run. A backend restart requires a fresh Unity run. Run/platform/version identity, update sequences and client expiry remain part of validity. The current build is experimental; synthetic tests or a visible banner do not establish performance acceptance.

## Logging and timing

[timesync_logger.py](timesync_logger.py) writes source-relative:

    telemetry_logs/<sanitized username>/session_YYYYMMDD_HHMMSS_microseconds/raw.csv

UDPRecevier.py creates the logger after start_session; pre-session hardware packets do not become a user's session rows. New sessions close the previous logger. Confirm the actual “[LOGGER] Session CSV:” path after Start. Preserve practice, operator-check, interrupted and restarted runs with their roles registered.

Rows retain Wii/Unity source timestamps and sequences, backend log-entry timestamps, lifecycle/outcome fields, available geometry identity and wii_control_v1 evidence. The CSV backend timestamp is not a dedicated socket-arrival timestamp. Sender control requests do not prove Unity-applied input, and send timestamps are not hardware sample timestamps. Unity, Unix and local monotonic clocks need an established mapping before subtraction. Ordinary generation and diagnostic fingerprint are distinct identity systems.

The shadow JSONL is shared across runs: join exact run/context, not folder names or nearest wall-clock times. Unity local diagnostic JSONL is outside the backend log tree unless explicitly copied and registered.

### Historical preprocessing

[telemetry_preprocess.py](telemetry_preprocess.py) preserves raw files and produces aligned rows, windows and quality reports. Its default 60 Hz alignment uses **linear interpolation** and nearest-sample metadata, followed by a backward Unity join. Interpolation can use future Wii observations, so this historical utility is **not an approved causal real-time feature pipeline**. Its 1-second window, 0.25-second stride and 2-second label horizon are not the deployed model contract.

## Pilot and evaluation

- [10-minute plan](parallel_20261016/pilot_readiness/PLAN_10_MIN.md).
- [Operator card](parallel_20261017/pilot_collection_pack/forms/OPERATOR_CARD.md) and [registration](parallel_20261017/pilot_collection_pack/forms/REGISTRATION.md).
- [Evaluation protocol](parallel_20261017/pilot_collection_pack/EVALUATION_PROTOCOL.md): final-fall, proximity entry, display burden and evidence gaps have distinct denominators. Planned 0.55 sensitivity and difficulty 3 / three layers require actual configuration receipts.
- [Offline quality checker](parallel_20261016/pilot_quality/README.md), implemented in check_pilot.py beside that README: explicit participant/run/session manifests; no automatic training approval or silent trial exclusions.
- [Operator smoke review](parallel_20261019/operator_smoke_review/REPORT.md), including actual test scope and limitations.
- [Original binary/document audit](parallel_20261019/binary_document_audit/CHECK.md).

## Profiles, credentials and dependencies

db_manager.py stores per-user profiles in source-relative database/. Profiles and telemetry may contain personal information; they are not deployment dependencies.

All three game services currently read **DEEPSEEK_API_KEY** from the environment for DeepSeek report/chat calls. See [SECRETS_SETUP.md](SECRETS_SETUP.md). The former claim that the current files hardcode the key is obsolete. Historical key revocation and absence of credentials from every historical copy have not been established. Local warning inference is separate from remote chat/report generation.

- Core service third-party imports include numpy and requests.
- Enabled local model inference requires matching runtime modules, its pinned native artifact, numpy and lightgbm.
- Offline preprocessing needs pandas/numpy; experiments additionally use scikit-learn, lightgbm and, for neural models, torch. [requirements-telemetry.txt](requirements-telemetry.txt) lists telemetry/experiment lower bounds, not a fully pinned deployment environment or the complete core-service requirements.
- Pilot launchers pin C:/Users/QIYUXUAN/AppData/Local/Python/pythoncore-3.14-64/python.exe; another interpreter's packages do not establish its readiness.
- Keep compatibility names UDPRecevier.py and databse/test_db.py until references are deliberately migrated. Runtime profile storage is database/, not databse/.
- Preserve UTF-8. The 2026-10-19 audit did not reproduce a blanket mojibake defect in the three core game services; diagnose specific file/line evidence before conversion.
