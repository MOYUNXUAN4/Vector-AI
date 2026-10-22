# Vector AI: Closed-Loop Balance Training & Fall Risk Biofeedback System
### *Full-Stack Neurorehabilitation & Fall Prevention System Powered by Unity 6, Wii Balance Board, and AI Predictive Edge Warning*

[![Unity](https://img.shields.io/badge/Unity-6000.3.9f1%20LTS-black?logo=unity)](https://unity.com/)
[![Python](https://img.shields.io/badge/Python-3.10%20--%203.14-blue?logo=python)](https://www.python.org/)
[![Machine Learning](https://img.shields.io/badge/ML-LightGBM%20%7C%20RandomForest%20%7C%20GRU-orange)]()
[![Render Pipeline](https://img.shields.io/badge/Pipeline-URP%20(Universal%20RP)-blue)]()
[![Platform](https://img.shields.io/badge/Platform-Windows%20x64%20(Standalone)-lightgrey)]()
[![License](https://img.shields.io/badge/License-Academic%20Research-green)]()

---

## 📌 Executive Summary

**Vector AI** is an advanced closed-loop biofeedback rehabilitation and gaming system designed for real-time balance impairment intervention, postural stability training, and fall risk mitigation. 

By integrating a **Nintendo Wii Balance Board (WBB)** with a custom **Unity 6 physics simulation engine** and an ultra-low-latency **Python machine learning backend (LightGBM/GRU/TTE)**, Vector AI tracks participant Center of Pressure (CoP) at 110 Hz, simulates continuous postural destabilization across dynamically dropping platforms, and delivers proactive, multi-tier biofeedback cues (Visual, Kinematic, and Spatial) before a loss of balance or edge fall occurs.

This repository is organized as a unified full-stack monorepo containing both the **Unity 6 client** and the **Python AI backend & verification engine**.

```
+-----------------------------------------------------------------------------------------+
|                                    Vector AI Architecture                               |
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|       +-----------------------------------------------------------+                     |
|       |                 Nintendo Wii Balance Board                |                     |
|       |       4-Corner Load Sensors (TL, TR, BL, BR) @ 110 Hz     |                     |
|       +-----------------------------+-----------------------------+                     |
|                                     | Bluetooth HID                                     |
|                                     v                                                   |
|       +-----------------------------------------------------------+                     |
|       |             Python Real-Time Server Engine (Backend/)     |                     |
|       |   - CoP Normalization & Zero-Drift Auto Calibration       |                     |
|       |   - High-Frequency Timesync Logger (Single-Clock Trace)   |                     |
|       |   - LightGBM & Time-to-Edge (TTE) Predictors (<4ms)       |                     |
|       +-------------------+-------------------+-------------------+                     |
|                           |                   ^                                         |
|             UDP Port 5005 | Telemetry         | UDP Port 5006                           |
|             Inference Cues| (Kinematics, CoP) | Status & Control                        |
|                           v                   |                                         |
|       +---------------------------------------+-------------------+                     |
|       |                 Unity 6 Client (Assets/)                  |                     |
|       |   - Dynamic Endless Falling Gameplay Physics              |                     |
|       |   - Proactive Multi-Channel Biofeedback Banners           |                     |
|       |   - Real-Time L/R Balance Distribution & Radar Analytics  |                     |
|       |   - Standalone 60 FPS Low-Jitter Simulation Loop          |                     |
|       +-----------------------------------------------------------+                     |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
```

---

## 📁 Repository Structure

```
.
├── Assets/                             # Unity 6 Client Source Code
│   ├── BackEnd/
│   │   └── UDPManager.cs               # High-frequency UDP client, packet serialization & telemetry
│   ├── Editor/
│   │   ├── FrameStallAutoCapture.cs    # Profiler instrumentation for frame-drop diagnostics
│   │   ├── VectorAINormalGameBuild.cs  # Automated Standalone Windows 64 build pipeline
│   │   └── VectorAIReceiverReplayWindow.cs # Offline telemetry packet replayer
│   ├── Endness Driving/Scripts/UI/
│   │   ├── FypHubSensitivityMenu.cs    # In-game sensitivity configuration overlay
│   │   └── GameSensitivitySettings.cs  # Sensitivity persistence interface
│   ├── Endness Falling/
│   │   ├── Scenes/Stage/
│   │   │   ├── EndlessFalling.unity    # Main falling balance experimental scene
│   │   │   ├── FypHub.unity            # Central management lobby scene
│   │   │   └── Stage.unity             # Baseline balance testing environment
│   │   ├── Scripts/
│   │   │   ├── EndlessPlayerController.cs  # Sphere physics, CoP-to-torque mapping & sensitivity
│   │   │   ├── LevelManager.cs         # Endless platform procedural generation & difficulty ladder
│   │   │   ├── UIManager.cs            # Low-allocation immediate-mode GUI, HUD & Clinical Report
│   │   │   └── UdpFrontendReceiver.cs  # Ring-buffered UDP receiver with zero-allocation JSON parser
│   │   └── Tests/Editor/
│   │       ├── UdpFrontendReceiverWarningTests.cs  # Unit tests for UDP deserializer & warning lifecycle
│   │       └── UnifiedRiskPresentationTests.cs     # Unit tests for multi-channel risk arbitrator
│   └── Settings/Build Profiles/        # Standalone Windows x64 build profiles
│
├── Backend/                            # Python Real-Time Server & Machine Learning Engine
│   ├── UDPRecevier.py                  # Core UDP socket server, packet demux & ML dispatcher
│   ├── timesync_logger.py              # High-precision synchronized telemetry persistence logger
│   ├── master_server.py                # Master service orchestration & startup lifecycle manager
│   ├── runningball_ai.py               # Real-time inference wrapper for live game biofeedback
│   ├── udp_packet_reader.py            # Telemetry packet parsing & struct unpacking utilities
│   ├── telemetry_preprocess.py         # Feature engineering & sliding-window data normalization
│   ├── baseline_time_rule.py           # Geometric Time-to-Edge (TTE) baseline rule evaluation
│   ├── directional_risk_baseline.py    # Directional CoP perturbation & margin estimation
│   ├── calibrate_gru_threshold.py      # Decision threshold calibration under Precision-First criteria
│   ├── train_gru_offline.py            # Offline GRU neural network training & cross-validation
│   ├── compare_tree_models.py          # Comparative evaluation: LightGBM vs Random Forest
│   ├── optimize_tte_lgbm.py            # Hyperparameter optimization for LightGBM TTE classifier
│   ├── run_time_to_edge_validation.py  # Batch validation pipeline for edge warning horizons
│   ├── parallel_20261020/
│   │   └── staged_patches_v8_20261020/ # Audited v8 offline quality & telemetry audit toolkit
│   │       ├── tools/                  # Closure audit, Wii preflight, and latency profiling tools
│   │       ├── tests/                  # Automated regression test suite (30/30 checks passed)
│   │       └── README.md               # Toolkit specification & execution guide
│   ├── Start_Master_With_Model.cmd     # One-click startup script with model inference enabled
│   ├── requirements-telemetry.txt      # Python runtime dependencies
│   └── DATA_COLLECTION_PROTOCOL.md     # Clinical experimental protocol & participant guidelines
│
├── Packages/                           # Unity Package Manager manifest & package locks
├── ProjectSettings/                    # Unity project settings & physics configurations
├── README.md                           # Monorepo documentation
└── RECOVERY_BASELINE_20261020.md       # Audit baseline & configuration recovery receipt
```

---

## 🎮 Core Gameplay & Rehabilitation Modules

### 1. Endless Falling Balance Mode (`EndlessFalling.unity`)
- **Dynamic Platform Tilting**: Platforms dynamically adjust tilt angle and rotation in response to real-time player CoP shifts and progressive difficulty tiers.
- **Physical Boundary Awareness**: Players must steer the descending sphere to remain centered while falling through platform apertures, counteracting intentional perturbations.
- **Progressive Difficulty Scaling**: 5 difficulty levels with dynamic scaling of platform radius, tilt velocity, obstacle placement, and fall margin.

### 2. Clinical Calibration Stage (`CalibrationPlatform`)
- **Automated Tare & Load Pre-flight**: Verifies board contact, detects baseline participant weight, and enforces stationary tare periods before session launch.
- **Zero-Drift CoP Alignment**: Compensates for initial postural asymmetry, establishing reliable origin coordinates ($X=0, Z=0$).

### 3. FYP Central Hub (`FypHub.unity`)
- **Participant Profile Management**: Manages experimental cohorts (P01, P02, P03) and session metadata.
- **Sensitivity Configuration**: Interactive settings menu (`FypHubSensitivityMenu.cs`) allowing fine-grained calibration of input sensitivity (`0.10f` to `3.00f`, default `0.55f`) with synchronized registry persistence.

---

## ⚡ Real-Time Biofeedback & Warning HUD System

Vector AI features a multi-tiered biofeedback warning framework (`UIManager.cs`) designed to alert participants before edge-fall events:

```
[ SAFE / BALANCED ] ---> [ ATTENTION (Yellow) ] ---> [ PROXIMITY TTE (Purple) ] ---> [ CRITICAL EDGE (Red) ]
       Normal Play         Center Deviation > 2.5cm        Time-to-Edge < 0.75s            Margin < 0.20m
```

| Warning Layer | Visual Presentation | Trigger Mechanism | Latency / Horizon |
|---|---|---|---|
| **Attention Cue** | Top Subtle Yellow Banner | Local kinematic rule: CoP radius deviates from safe boundary. | Instantaneous (<1 frame) |
| **TTE Proximity Cue** | Glowing Purple Banner | AI Backend prediction: Time-to-Edge trajectory forecast. | ~0.25s - 0.75s lead time |
| **Critical Danger Cue** | High-Contrast Red Banner | Backend CRITICAL packet + Local platform geometry boundary. | Hard physical threshold (<0.20m) |
| **Real-Time Balance Bar** | Dynamic Cyan/White HUD | Continuous bilateral weight distribution ($L\% \leftrightarrow R\%$). | Per-frame (60 Hz) |
| **Clinical Session Report** | Radar Chart & Post-Run View | 6-axis stability radar, RMSE error trajectory, and CoP trajectory plot. | Session End |

---

## 🚀 Quickstart & Setup Guide

### 1. Python Backend Setup
```bash
# Navigate to the backend directory
cd Backend

# Create a virtual environment & activate
python -m venv venv
.\venv\Scripts\activate

# Install telemetry & machine learning dependencies
pip install -r requirements-telemetry.txt

# Run automated regression tests to verify environment
python parallel_20261020/staged_patches_v8_20261020/tests/test_v8_suite.py

# Launch the real-time server with ML models
python master_server.py
# Or double-click: Start_Master_With_Model.cmd
```

### 2. Unity Client Setup
1. **Launch Unity Hub** $\rightarrow$ Click **Add** $\rightarrow$ Select this project repository root folder.
2. Ensure editor version is set to **Unity 6 LTS (6000.3.9f1)**.
3. Open `Assets/Endness Falling/Scenes/Stage/EndlessFalling.unity`.
4. In the Inspector, verify `backendIP = 127.0.0.1` and `backendPort = 5005`.
5. Enter Play Mode or build the Standalone Player:
   - Go to **File** $\rightarrow$ **Build Profiles** $\rightarrow$ Select **VectorAi** $\rightarrow$ Click **Build and Run**.

---

## 📊 Telemetry Benchmarks & Quality Standards

Rigorous telemetry audits comparing runtime environments demonstrate that the **Standalone Windows x64 Player** build achieves near-zero jitter:

| Metric | Unity Editor (Play Mode) | Standalone Player (Production) | Clinical Impact |
|---|---|---|---|
| **Frame Rate** | ~53 FPS (Unstable) | **60 FPS Fixed** (VSync) | Smooth biofeedback rendering |
| **Max Frame Stall** | ~473 ms (Periodic GC/Profiler) | **40.6 ms** (Stall-free) | Eliminates visual interruption |
| **UDP Ingest Latency** | 3.5 ms - 21.0 ms | **3.5 ms median (NO_STEP)** | Sub-10ms closed-loop response |
| **Dual-Clock Stability** | ~950 ms accumulated drift | **0 discrete jumps, 7-20ms spread** | Prevents timestamp misalignment |

---

## 🧪 Automated Testing & Scientific Audit

### Unity Test Suite
- Open Unity Editor: **Window** $\rightarrow$ **General** $\rightarrow$ **Test Runner**.
- Run `EndlessFalling.WarningReceiver.Tests` (Validates ring-buffer packet ingestion, timestamp monotonicity, and warning clear semantics).

### Backend Offline Quality Toolkit (v8)
The repository includes a scientific quality assurance pipeline in `Backend/parallel_20261020/staged_patches_v8_20261020/tools/`:
- **Session Closure Audit (`session_closure_audit_v8.py`)**: 100% verified packet persistence across all sessions (`unpersisted=0`).
- **Wii CoP Pre-flight (`wii_cop_preflight_v6.py`)**: Automatic load, center-applied, and control-valid check.
- **Latency & Step Profiler (`receive_latency_profile_v5.py`)**: Dual-clock staircase tracking and 4-block stability verification.

---

## 👨‍💻 Research & Authors

- **Author & Principal Investigator**: QI YUXUAN (QI YUXAUN)
- **Academic Context**: Final Year Project (FYP) - Biofeedback & Machine Learning Driven Neurorehabilitation System
- **Repository**: [https://github.com/MOYUNXUAN4/Vector-AI](https://github.com/MOYUNXUAN4/Vector-AI)
