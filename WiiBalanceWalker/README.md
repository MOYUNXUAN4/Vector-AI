# Vector AI: WiiBalanceWalker (Direct UDP Biofeedback Fork)
### *Customized High-Frequency Biomechanical Telemetry Bridge for Nintendo Wii Balance Board*

[![License: MS-PL](https://img.shields.io/badge/License-MS--PL-blue.svg)](https://opensource.org/licenses/MS-PL)
[![Language](https://img.shields.io/badge/Language-C%23%20%7C%20.NET%20Framework-brightgreen)]()
[![Telemetry](https://img.shields.io/badge/Telemetry-Direct%20UDP%20%40%20100Hz-orange)]()
[![Platform](https://img.shields.io/badge/Platform-Windows%20x86%20%2F%20x64-lightgrey)]()

---

## 📌 Acknowledgments & Original Credits

This module is built upon the open-source **WiiBalanceWalker** project. We gratefully acknowledge and credit the original developers:

- **Shachar Liberman (lshachar)**: Author of **WiiBalanceWalker v0.5** and maintainer of the customized [WiimoteLib](https://github.com/lshachar/WiimoteLib) with 64-bit vJoy and permanent Bluetooth PIN pairing support.
- **Richard Perry (GreyCube.com)**: Original creator of **WiiBalanceWalker v0.1 - v0.4**, released under the **Microsoft Public License (MS-PL)**.
- **Shaul Eizikovich**: Creator of the [vJoy Virtual Joystick driver](http://vjoystick.sourceforge.net/).
- **32feet.NET**: Personal Area Networking for .NET (Bluetooth library).

*All original code retains its open-source license (MS-PL). All custom extensions, modifications, and protocol designs developed for Vector AI are detailed below.*

---

## 🛠 What is the Vector AI Fork? (Our Key Modifications)

Standard WiiBalanceWalker was designed solely as an accessibility tool to map balance board shifts into simulated keystrokes (WASD/Arrow keys) or virtual joystick axis inputs. While functional for casual gaming, it completely lacked the ability to export raw sensor readings, timestamps, or continuous load distributions required for clinical rehabilitation and machine learning.

For the **Vector AI** project, **MOYUNXUAN** fundamentally redesigned and extended the software into a scientific-grade biomechanical data bridge:

### 1. Direct High-Frequency UDP Streaming (`100 Hz / 10 ms`)
- **Independent Telemetry Thread**: Implemented a dedicated high-precision `System.Threading.Timer` running at 10 ms (~100 Hz) that reads the latest Bluetooth HID balance board snapshot independently from the 20 ms WinForms UI render loop.
- **Direct Socket Ingestion**: Bypasses vJoy and Windows keyboard drivers, transmitting UDP JSON datagrams directly to the Vector AI Python backend (`127.0.0.1:5005`).

### 2. Full 4-Corner Raw Load Cell Telemetry
- Transmits raw physical weight readings in kilograms from all four independent load sensors:
  - Top-Left (`tl`), Top-Right (`tr`), Bottom-Left (`bl`), Bottom-Right (`br`).
- Transmits per-sensor zero-calibration offsets (`offset_*`) and real-time bilateral weight distribution percentages (`ratio_*`).
- Enables the Python backend to compute accurate Center of Pressure (CoP $X$ and $Z$), sway velocity, and postural perturbation indicators in real time.

### 3. Decoupled Control & Sensor Schema (`wii_control_v1`)
- Separates physical force sensor readings from issued game control signals:
  - Carries independent monotonic `sequence`, UTC ISO-8601 `timestamp`, and `control_age` metrics.
  - Guarantees that sensor data is never confounded with discrete threshold crossings or stale button states.

### 4. Robust Windows Process Guard (`Check_WiiInstance.ps1`)
- Resolves a notorious Windows Bluetooth stack issue where terminated processes linger in the system process table with 0 threads and 0 handles, permanently blocking subsequent startups.
- Implemented a dual-snapshot heuristic (250 ms apart) to cleanly detect phantom process entries while strictly guarding against duplicate active hardware connections.

### 5. Deployment Integrity Manifest & Symbol Alignment
- Introduced `deployment_manifest.json` with SHA-256 integrity verification across the executable, configuration, DLLs, and matching CodeView/PDB symbols (`725ee573-4908-4e80-b2c6-5530a0d3e433`).
- Created `Start_WiiBalanceWalker_Verified.cmd` for one-click verified startup.

---

## 📡 UDP Telemetry Packet Format

Each packet sent to `127.0.0.1:5005` follows this structured schema:

```json
{
  "type": "wii_balance",
  "timestamp": "2026-10-22T02:15:00.1234567Z",
  "sequence": 14205,
  "tl": 14.25,
  "tr": 13.80,
  "bl": 16.10,
  "br": 15.65,
  "weight": 59.80,
  "offset_tl": 14.10,
  "offset_tr": 13.70,
  "offset_bl": 15.90,
  "offset_br": 15.50,
  "ratio_tl": 23.83,
  "ratio_tr": 23.08,
  "ratio_bl": 26.92,
  "ratio_br": 26.17,
  "wii_control_v1": {
    "control_sequence": 7102,
    "control_timestamp": "2026-10-22T02:15:00.1150000Z",
    "control_age_seconds": 0.008,
    "control_valid": true,
    "actions_enabled": true
  }
}
```

---

## 🚀 Quickstart & Verified Launch

### Recommended: Verified One-Click Launch
Double-click `Start_WiiBalanceWalker_Verified.cmd` in this directory. It will:
1. Validate file hashes against `deployment_manifest.json`.
2. Verify process table cleanliness via `Check_WiiInstance.ps1`.
3. Launch `WiiBalanceWalker.exe` with direct UDP telemetry enabled.

### Connecting the Wii Balance Board
1. Turn on PC Bluetooth.
2. Press the red **SYNC** button inside the battery compartment of the Wii Balance Board.
3. In WiiBalanceWalker, click **Bluetooth Search** $\rightarrow$ **Connect**.
4. The status bar will confirm connection and begin streaming telemetry at ~100 Hz.

---

## 👨‍💻 Research Attribution

- **Custom Telemetry Protocol & Direct UDP Modifications**: MOYUNXUAN
- **Contact Email**: [moyunxuan0@gmail.com](mailto:moyunxuan0@gmail.com)
- **Academic Context**: Final Year Project (FYP) - Vector AI Balance Rehabilitation System
- **Original Base Project**: Shachar Liberman (v0.5) / Richard Perry (v0.4, GreyCube.com)
