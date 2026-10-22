# VectorAI: Closed-Loop Balance Training & Fall Risk Biofeedback System
### *Real-Time Neurorehabilitation & Fall Prevention System Powered by Unity 6, Wii Balance Board, and AI Predictive Edge Warning*

[![Unity](https://img.shields.io/badge/Unity-6000.3.9f1%20LTS-black?logo=unity)](https://unity.com/)
[![Render Pipeline](https://img.shields.io/badge/Pipeline-URP%20(Universal%20RP)-blue)]()
[![Platform](https://img.shields.io/badge/Platform-Windows%20x64%20(Standalone)-lightgrey)]()
[![License](https://img.shields.io/badge/License-Academic%20Research-green)]()

---

## 📌 Executive Summary

**VectorAI** is an advanced closed-loop biofeedback rehabilitation and gaming system designed for real-time balance impairment intervention, postural stability training, and fall risk mitigation. 

By integrating a **Nintendo Wii Balance Board (WBB)** with a custom **Unity 6 physics simulation engine** and an ultra-low-latency **Python machine learning backend (LightGBM/GRU/TTE)**, VectorAI tracks participant Center of Pressure (CoP) at 110 Hz, simulates continuous postural destabilization across dynamically dropping platforms, and delivers proactive, multi-tier biofeedback cues (Visual, Kinematic, and Spatial) before a loss of balance or edge fall occurs.

```
       +-----------------------------------------------------------+
       |                 Nintendo Wii Balance Board                |
       |       4-Corner Load Sensors (TL, TR, BL, BR) @ 110 Hz     |
       +-----------------------------+-----------------------------+
                                     | Bluetooth HID
                                     v
       +-----------------------------------------------------------+
       |               Python Real-Time Server Engine              |
       |   - CoP Normalization & Zero-Drift Auto Calibration       |
       |   - High-Frequency Timesync Logger (Single-Clock Trace)   |
       |   - LightGBM & Time-to-Edge (TTE) Predictors (<4ms)       |
       +-------------------+-------------------+-------------------+
                           |                   ^
             UDP Port 5005 | Telemetry         | UDP Port 5006
             Inference Cues| (Kinematics, CoP) | Status & Control
                           v                   |
       +---------------------------------------+-------------------+
       |                 Unity 6 Client (VectorAI)                 |
       |   - Dynamic Endless Falling Gameplay Physics              |
       |   - Proactive Multi-Channel Biofeedback Banners           |
       |   - Real-Time L/R Balance Distribution & Radar Analytics  |
       |   - Standalone 60 FPS Low-Jitter Simulation Loop          |
       +-----------------------------------------------------------+
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

VectorAI features a multi-tiered biofeedback warning framework (`UIManager.cs`) designed to alert participants before edge-fall events:

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

## 🏗 Architecture & Codebase Map

```
Assets/
├── BackEnd/
│   └── UDPManager.cs                  # High-frequency UDP client, packet serialization & telemetry
├── Editor/
│   ├── FrameStallAutoCapture.cs       # Profiler instrumentation for frame-drop and stall diagnostics
│   ├── VectorAINormalGameBuild.cs     # Automated Standalone Windows 64 build pipeline
│   └── VectorAIReceiverReplayWindow.cs# Offline telemetry packet replayer and diagnostic viewer
├── Endness Driving/
│   └── Scripts/UI/
│       ├── FypHubSensitivityMenu.cs   # In-game sensitivity configuration overlay
│       └── GameSensitivitySettings.cs # Sensitivity persistence interface
├── Endness Falling/
│   ├── Scenes/Stage/
│   │   ├── EndlessFalling.unity       # Main falling balance experimental scene
│   │   ├── FypHub.unity               # Central management lobby scene
│   │   └── Stage.unity                # Baseline balance testing environment
│   ├── Scripts/
│   │   ├── CameraController.cs        # Smooth target-tracking dynamic camera
│   │   ├── EndlessFallingGeometryDiagnostics.cs # Real-time platform geometry & edge query engine
│   │   ├── EndlessPlayerController.cs # Sphere physics, CoP-to-torque mapping & sensitivity scaling
│   │   ├── LevelManager.cs            # Endless platform procedural generation & difficulty ladder
│   │   ├── UIManager.cs               # Low-allocation immediate-mode GUI, HUD & Clinical Report
│   │   └── UdpFrontendReceiver.cs     # Ring-buffered UDP receiver with zero-allocation JSON parser
│   └── Tests/Editor/
│       ├── UdpFrontendReceiverWarningTests.cs  # Unit tests for UDP deserializer & warning lifecycle
│       └── UnifiedRiskPresentationTests.cs     # Unit tests for multi-channel risk arbitrator
└── Settings/
    └── Build Profiles/VectorAi.asset  # Standalone Windows x64 build profile
```

---

## 🚀 Getting Started

### Prerequisites
- **Unity Version**: Unity 6 LTS (`6000.3.9f1` or later recommended)
- **Target Platform**: Windows 10 / 11 (64-bit)
- **Input Hardware**:
  - Nintendo Wii Balance Board (connected via Bluetooth) **OR**
  - Standard Keyboard / Joystick (Fall-back testing mode: `W/A/S/D` or Arrow Keys)

### Setup & Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/MOYUNXUAN4/Endless-Driver-Tutorial---EP9.git
   cd Endless-Driver-Tutorial---EP9
   ```
2. **Open in Unity Hub**:
   - Launch Unity Hub $\rightarrow$ Select **Add project from disk** $\rightarrow$ Choose this directory.
   - Ensure the editor version is set to **Unity 6000.3.9f1**.
3. **Open the Core Scene**:
   - Navigate to `Assets/Endness Falling/Scenes/Stage/EndlessFalling.unity` in the Project panel.
4. **Configure Network Endpoint**:
   - In the Hierarchy, select `UIManager` or `UDPManager`.
   - Ensure `Backend IP` is set to `127.0.0.1` and `Backend Port` is set to `5005` (matching the Python backend).

---

## 📊 Performance & Runtime Benchmarks

Rigorous telemetry audits comparing runtime environments demonstrate that the **Standalone Windows x64 Player** build achieves near-zero jitter:

| Metric | Unity Editor (Play Mode) | Standalone Player (Production) | Clinical Impact |
|---|---|---|---|
| **Frame Rate** | ~53 FPS (Unstable) | **60 FPS Fixed** (VSync) | Smooth biofeedback rendering |
| **Max Frame Stall** | ~473 ms (Periodic GC/Profiler) | **40.6 ms** (Stall-free) | Eliminates visual interruption |
| **UDP Ingest Latency** | 3.5 ms - 21.0 ms | **3.5 ms median (NO_STEP)** | Sub-10ms closed-loop response |
| **Dual-Clock Stability** | ~950 ms accumulated drift | **0 discrete jumps, 7-20ms spread** | Prevents timestamp misalignment |

> **Recommendation**: Always run clinical participant data collection sessions using the **Standalone Player build** (`Builds/VectorAI.exe`) rather than the Editor Play Mode.

---

## 🧪 Automated Testing

The project includes automated Editor-mode unit test suites:
- Open Unity Editor: **Window** $\rightarrow$ **General** $\rightarrow$ **Test Runner**.
- Run `EndlessFalling.WarningReceiver.Tests`:
  - `UdpFrontendReceiverWarningTests`: Validates ring-buffer packet ingestion, timestamp monotonicity, and warning clear semantics.
  - `UnifiedRiskPresentationTests`: Validates priority resolution between local geometric rules and external model predictions.

---

## 👨‍💻 Research & Authors

- **Primary Investigator / Developer**: QI YUXUAN / MOYUNXUAN
- **Academic Context**: Final Year Project (FYP) - Biofeedback & Machine Learning Driven Neurorehabilitation System
- **Repository**: [https://github.com/MOYUNXUAN4/Endless-Driver-Tutorial---EP9](https://github.com/MOYUNXUAN4/Endless-Driver-Tutorial---EP9)
