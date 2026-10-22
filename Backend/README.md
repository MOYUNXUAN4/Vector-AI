# Vector AI Backend & ML Engine
### *Real-Time UDP Telemetry Ingestion, Wii Balance Board Processing & AI Predictive Fall Intervention*

[![Python](https://img.shields.io/badge/Python-3.10%20--%203.14-blue?logo=python)](https://www.python.org/)
[![Machine Learning](https://img.shields.io/badge/ML-LightGBM%20%7C%20RandomForest%20%7C%20GRU-orange)]()
[![Protocol](https://img.shields.io/badge/Networking-High--Frequency%20UDP%20%40%20110Hz-brightgreen)]()
[![Platform](https://img.shields.io/badge/Platform-Windows%20x64-lightgrey)]()

---

## 📌 Overview

The **Vector AI Backend** is the high-performance Python server and machine learning intelligence layer for the Vector AI closed-loop balance rehabilitation system. 

It acts as the central coordinator between the **Nintendo Wii Balance Board** physical sensor hardware and the **Unity 6 game engine client**, executing high-frequency signal processing, Center of Pressure (CoP) calibration, single-clock telemetry persistence, and real-time fall risk forecasting with sub-4 millisecond inference latencies.

```
+-----------------------------------------------------------------------------------------+
|                                    Vector AI Architecture                               |
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|  [ Wii Balance Board ]                                          [ Unity 6 Client ]      |
|    Load Cells (TL, TR, BL, BR)                                    Physics & Visuals     |
|          |                                                               |              |
|          | Bluetooth HID                                                 | UDP 110 Hz   |
|          v                                                               v              |
|  +-----------------------------------------------------------------------------------+  |
|  |                            Vector AI Backend (Python)                             |  |
|  |                                                                                   |  |
|  |   1. UDP Ingest & Demux (UDPRecevier.py)                                          |  |
|  |      - Ingests Wii load streams & Unity kinematics simultaneously                 |  |
|  |      - Dynamic socket buffering and zero-allocation frame parsing                 |  |
|  |                                                                                   |  |
|  |   2. Biomechanical Signal Processing & Calibration                               |  |
|  |      - 4-corner sensor calibration & zero-drift tare auto-adjustment              |  |
|  |      - CoP coordinates computation: CoP_X, CoP_Z, radial speed, stability index   |  |
|  |                                                                                   |  |
|  |   3. Predictive Fall Prevention Pipeline                                          |  |
|  |      - Time-to-Edge (TTE) kinematic projection                                    |  |
|  |      - LightGBM & GRU sequential models for impending edge-loss detection         |  |
|  |      - Delivers proactive warning cues: ATTENTION / PROXIMITY / CRITICAL (<4ms)   |  |
|  |                                                                                   |  |
|  |   4. High-Precision Timesync & Telemetry Logger (timesync_logger.py)              |  |
|  |      - Single-provenance clock logging to prevent cross-domain skew               |  |
|  |      - Real-time audit metrics & session outcome validation                       |  |
|  +-----------------------------------------+-----------------------------------------+  |
|                                            |                                            |
|                                            v (UDP Port 5005)                            |
|                          Proactive Biofeedback Cues Delivered                           |
+-----------------------------------------------------------------------------------------+
```

---

## ⚡ Key Modules & Capabilities

### 1. Ultra-Low-Latency UDP Engine (`UDPRecevier.py`)
- **Dual-Stream Demuxing**: Concurrently receives and syncs data streams from the Unity simulation client (kinematics, platform level, ball speed) and Wii Balance Board controller.
- **Microsecond Ingest Performance**: Achieves a median receive latency of **~3.5 ms** and peak latency under **21 ms** on local loopback, with zero persistent latency level jumps (`NO_STEP`).
- **Resilient Buffer Management**: Socket buffer configuration (`SO_RCVBUF`) designed to prevent OS-level UDP datagram dropouts during heavy disk flush intervals.

### 2. Machine Learning Predictive Pipeline
- **LightGBM Early Fall Classifier (`optimize_tte_lgbm.py`)**: Gradient boosted decision tree trained on high-dimensional temporal features (CoP velocity, acceleration, radial distance, and directional edge margin).
- **GRU Deep Temporal Modeling (`train_gru_offline.py`)**: Recurrent neural network capturing non-linear dynamic postural sway trajectories across sliding temporal windows.
- **Proactive Early Warning Lead Time**: Issues predictive alerts ~0.25s to 0.75s prior to physical edge departure, granting participants an actionable cognitive window to initiate postural corrections.

### 3. Rigorous Telemetry & Session Closure Verification
The repository includes the audited **v8 Scientific Quality Verification Toolkit** (`parallel_20261020/staged_patches_v8_20261020/tools/`):
- **`session_closure_audit_v8.py`**: Ensures graceful session completion, zero sequence packet drops (`unpersisted=0`), and cross-validates terminal game outcomes (`calibration_completed` vs `edge_exit`).
- **`wii_cop_preflight_v4.py`**: Performs pre-run participant load checks, stationary stance validation, and zero-drift centering verification.
- **`receive_latency_profile_v4.py`**: Profiles backend UDP ingestion latency using 4-block stability step detection, isolating network transients from systemic clock level shifts.
- **`cluster_warning_episodes_v4.py`**: Disaggregates warning episodes across local geometric rules, model predictions, and edge states.

---

## 📂 Codebase Structure

```
├── UDPRecevier.py                      # Core UDP socket server, real-time packet demux & ML dispatcher
├── timesync_logger.py                  # High-precision synchronized telemetry persistence logger
├── master_server.py                    # Master service orchestration & startup lifecycle manager
├── runningball_ai.py                   # Real-time inference wrapper for live game biofeedback
├── udp_packet_reader.py                # Telemetry packet parsing & struct unpacking utilities
├── telemetry_preprocess.py             # Feature engineering & sliding-window data normalization
├── baseline_time_rule.py               # Geometric Time-to-Edge (TTE) baseline rule evaluation
├── directional_risk_baseline.py        # Directional CoP perturbation & margin estimation
├── calibrate_gru_threshold.py          # Decision threshold calibration under Precision-First criteria
├── train_gru_offline.py                # Offline GRU neural network training & cross-validation
├── compare_tree_models.py              # Comparative evaluation: LightGBM vs Random Forest
├── optimize_tte_lgbm.py                # Hyperparameter optimization for LightGBM TTE classifier
├── run_time_to_edge_validation.py      # Batch validation pipeline for edge warning horizons
├── parallel_20261020/
│   ├── staged_patches_v8_20261020/     # Audited v8 offline quality & telemetry audit toolkit
│   │   ├── tools/                      # Closure audit, Wii preflight, and latency profiling tools
│   │   ├── tests/                      # Automated regression test suite (30/30 checks passed)
│   │   └── README.md                   # Toolkit specification & execution guide
│   └── p03_deepcheck_20261020/         # Participant P03 full-cohort telemetry audit report
├── Start_Master_With_Model.cmd         # One-click startup script with model inference enabled
├── Start_Master_Shadow_Only_Latency_Test.cmd # Low-overhead telemetry-only benchmarking launcher
├── requirements-telemetry.txt          # Python runtime dependencies
└── DATA_COLLECTION_PROTOCOL.md         # Clinical experimental protocol & participant guidelines
```

---

## 🚀 Quickstart & Setup

### Requirements
- **Python**: Python 3.10, 3.11, 3.12, 3.13, or 3.14 (64-bit)
- **OS**: Windows 10 / 11 (64-bit)

### Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/MOYUNXUAN4/Vector-AI.git
   cd Vector-AI/Backend
   ```

2. **Create Virtual Environment & Install Dependencies**:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements-telemetry.txt
   ```

3. **Verify Toolkit & Regression Tests**:
   ```bash
   python parallel_20261020/staged_patches_v8_20261020/tests/test_v4_suite.py
   ```
   *Expected output: `ALL V4 REGRESSION CHECKS PASSED`*

### Running the Live Backend Server
Launch the master server with real-time model inference:
```bash
python master_server.py
# Or run using the provided Windows script:
.\Start_Master_With_Model.cmd
```
The server will bind to:
- **`127.0.0.1:5005`**: Bidirectional communication with the Unity game client.
- **`127.0.0.1:5006`**: Ingest channel for Bluetooth Wii Balance Board bridge.

---

## 📊 Telemetry Benchmarks & Quality Standards

Audited against 15 consecutive sessions from participant **P03**:
- **Packet Integrity**: 100% sequence continuity across all sessions; 0 missing packets, 0 sequence reversals.
- **Ingestion Latency**: Median 3.5 ms, 95th percentile < 4.7 ms, zero persistent clock level jumps.
- **Session Closure Validation**: 15/15 sessions validated with complete packet persistence (`unpersisted=0`).
- **Sensor Pre-flight**: Zero-drift CoP centering verified with load stability standard deviation < 0.02 cm.

---

## 👨‍💻 Research & Authors

- **Author & Principal Investigator**: QI YUXUAN (QI YUXAUN)
- **Academic Context**: Final Year Project (FYP) - Closed-Loop Biofeedback Neurorehabilitation Architecture
- **Repository**: [https://github.com/MOYUNXUAN4/Vector-AI](https://github.com/MOYUNXUAN4/Vector-AI)
