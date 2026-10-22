import socket
import json
import math
import numpy as np
import random
import os
import sys
import requests
import threading
import traceback
import select
import time
from udp_packet_reader import recv_json_packet, log_processing_error
from datetime import datetime

# Import local database manager
from db_manager import load_or_create_user, save_user_data
from timesync_logger import TimeSynchronizedLogger

LISTEN_IP = "127.0.0.1"
LISTEN_PORT_FROM_UNITY = 5005
TARGET_PORT_TO_UNITY = 5006

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

ai_chat_history = []
EVALUATION_BATCH_SIZE = 1
# The Q-table remains the policy source.  This guard prevents a stale table
# from holding a consistently successful player at level 1 indefinitely.
MIN_STABLE_LAYERS_TO_INCREASE = 2
current_difficulty = 1
epoch_squared_errors = []
last_eval_count = 0
session_history_log = []

current_user_profile = None
current_nickname = "Guest"

LOW_THRESHOLD = 2.0
HIGH_THRESHOLD = 3.2
is_calibrated = False
calibration_errors = []
current_rmse = 0.0

stable_layers = 0
consecutive_struggles = 0

# Sliding window to smooth state fluctuations
state_history = []
STATE_WINDOW_SIZE = 5

# Ignore COP/ratio calculations while the board is effectively unloaded.
# A 0.5 kg cutoff amplified sensor noise during light contact.
MIN_COP_WEIGHT_KG = 5.0

q_table = np.array([
    [10.0, -5.0, -10.0],
    [-5.0, 10.0, -5.0],
    [-10.0, -5.0, 10.0]
])

alpha = 0.1
gamma = 0.9
epsilon = 0.15

last_state_idx = None
last_action_idx = None

# Latest raw Wii Balance Board load-sensor sample from WiiBalanceWalker.
latest_wii_balance = {
    "tl": 0.0, "tr": 0.0, "bl": 0.0, "br": 0.0,
    "weight": 0.0, "timestamp": 0.0,
}
last_wii_log_time = 0.0
last_game_log_time = 0.0


def fetch_ai_response_async(command, payload_data, sock_tx):
    global ai_chat_history, current_user_profile, current_nickname, q_table

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    if command == "generate_report":
        print("\n[INFO] [LLM Service] Initiating clinical analysis report generation...")
        rmse = payload_data.get("rmse", 0.0)
        bal_left = payload_data.get("bal_left", 50.0)
        bal_right = 100.0 - bal_left
        passed_layers = payload_data.get("passed_layers", 0)
        difficulty = payload_data.get("difficulty", 1)
        history_log = payload_data.get("history", [])

        previous_rmse = None
        if current_user_profile is not None:
            previous_rmse = current_user_profile.get("last_rmse", None)
            current_user_profile["total_sessions"] += 1
            current_user_profile["q_table"] = q_table.tolist()

            if passed_layers > current_user_profile.get("high_score", 0):
                current_user_profile["high_score"] = passed_layers

            current_user_profile["last_rmse"] = rmse
            save_user_data(current_nickname, current_user_profile)
            print(
                f"[SUCCESS] [Database] Saved latest session memory and "
                f"RMSE ({rmse:.2f}) for user: {current_nickname}."
            )

        recent_history = history_log[-30:] if len(history_log) > 30 else history_log
        history_str = "\n".join([
            f"Layer {item['layer']}: RMSE {item['rmse']:.2f}mm | "
            f"AI Set Difficulty to Level {item['difficulty']} | "
            f"State: {item['state']}"
            for item in recent_history
        ])

        if not history_str:
            history_str = "No specific layer data recorded."

        if previous_rmse is not None:
            past_comparison_text = (
                f"- PREVIOUS Session Average RMSE: {previous_rmse:.2f} mm"
            )
        else:
            past_comparison_text = (
                "- PREVIOUS Session: N/A (This is their first session)."
            )

        system_prompt = f"""You are the VectorAI Virtual Coach, an elite clinical rehabilitation physician.
The patient just finished a biofeedback postural training session.

[Final Summary Telemetry]
- Current Session Average RMSE: {rmse:.2f} mm (<2.0 is excellent, >3.2 implies struggle)
{past_comparison_text}
- Weight Symmetry: Left {bal_left:.1f}% / Right {bal_right:.1f}%
- Highest Layer Reached: {passed_layers}

[Continuous Layer-by-Layer Performance Log]
{history_str}

[Interaction Rules]
1. IMPORTANT: You MUST communicate primarily in ENGLISH by default.
2. Begin your very first response EXACTLY like this: "Hello [ {current_nickname} ], I am VectorAI."
3. After the greeting, PROACTIVELY compare their "Current Session Average RMSE" with their "PREVIOUS Session Average RMSE" (if available). Tell them explicitly if they improved or declined and by how much.
4. ABSOLUTELY NO MARKDOWN (Do not use ** or *). Keep text plain for the Unity UI.
5. Keep responses concise and supportive."""

        ai_chat_history = [{"role": "system", "content": system_prompt}]

        first_request = """Session ended. Please generate my clinical report using this exact format:
Sentence 1: Greet me and proactively compare my current RMSE with my previous session's RMSE to highlight my progress.
Sentence 2-3: Analyze my continuous performance trend based on the layers.
Sentence 4: Provide ONE specific, actionable physical adjustment for my posture or balance."""

        ai_chat_history.append({"role": "user", "content": first_request})

    elif command == "chat":
        user_msg = payload_data.get("message", "")
        print(f"\n[INFO] [LLM Service] Patient query received: {user_msg}")
        ai_chat_history.append({"role": "user", "content": user_msg})

    api_payload = {
        "model": "deepseek-chat",
        "messages": ai_chat_history,
        "stream": False
    }

    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json=api_payload,
            timeout=20
        )

        if response.status_code == 200:
            ai_reply = response.json()["choices"][0]["message"]["content"]
            ai_reply = ai_reply.replace("**", "").replace("*", "").strip()

            print(f"[SUCCESS] [LLM Service] Response generated: {ai_reply[:40]}...")

            ai_chat_history.append({"role": "assistant", "content": ai_reply})

            report_packet = {"type": "ai_report", "content": ai_reply}
            sock_tx.sendto(
                json.dumps(report_packet).encode("utf-8"),
                (LISTEN_IP, TARGET_PORT_TO_UNITY)
            )
        else:
            print(
                f"[ERROR] [LLM Service] API Request Failed: "
                f"{response.status_code} - {response.text}"
            )

    except Exception as e:
        print(f"[ERROR] [LLM Service] Connection Exception: {e}")


def attach_proximity_warning(realtime_packet, proximity_reply=None):
    """Default-off optional rule field; legacy reply fields remain independent."""
    if proximity_reply is None:
        return realtime_packet
    try:
        attached = proximity_reply.attach_realtime(realtime_packet)
        if isinstance(attached, dict):
            return attached
    except Exception:
        pass
    # A broken optional adapter must not interrupt ordinary telemetry. The
    # client must expire any previous proximity lease when this field is absent.
    fallback = dict(realtime_packet)
    fallback.pop("proximity_warning", None)
    return fallback


def start_backend(warning_bridge=None):
    global current_difficulty, last_eval_count, epoch_squared_errors
    global last_state_idx, last_action_idx, q_table
    global is_calibrated, calibration_errors, LOW_THRESHOLD, HIGH_THRESHOLD
    global stable_layers, consecutive_struggles, current_rmse, epsilon
    global session_history_log
    global current_user_profile, current_nickname
    global latest_wii_balance, last_wii_log_time, last_game_log_time

    integration_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "parallel_20261011", "realtime_integration"
    )
    if integration_dir not in sys.path:
        sys.path.insert(0, integration_dir)
    from bridge import bridge_from_environment
    if warning_bridge is None:
        warning_bridge = bridge_from_environment()

    # Original shadow remains local-only. An independent reply adapter requires
    # its own explicit opt-in and never replaces model/geometry warning fields.
    proximity_shadow = None
    proximity_reply = None
    if os.getenv("PROXIMITY_SHADOW_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            shadow_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "parallel_20261014", "proximity_shadow_backend_luna")
            if shadow_dir not in sys.path:
                sys.path.insert(0, shadow_dir)
            if os.getenv("PROXIMITY_REPLY_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
                reply_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "parallel_20261015", "proximity_reply_luna")
                if reply_dir not in sys.path:
                    sys.path.insert(0, reply_dir)
                from proximity_reply import ReplyProximityShadow
                proximity_shadow = ReplyProximityShadow()
                proximity_reply = proximity_shadow
                print("[EXPERIMENTAL] Independent proximity_warning replies enabled; deterministic TTE rule, no probability.")
            else:
                from proximity_shadow import ProximityShadow
                proximity_shadow = ProximityShadow()
                print("[SHADOW] TTE proximity rule enabled; local log only.")
        except Exception as shadow_error:
            print(f"[SHADOW] TTE proximity rule unavailable: {type(shadow_error).__name__}")

    # A training log is opened only after Unity identifies the authenticated
    # user with start_session.  Hardware packets received before that point
    # are intentionally not mixed into a user's training history.
    logger = None

    sock_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_rx.bind((LISTEN_IP, LISTEN_PORT_FROM_UNITY))

    sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print("==================================================")
    print(" [SYSTEM] VectorAI Core Engine Initialized [Infinite Fall - Port 5005]")
    print("==================================================\n")

    try:
        while True:
            if proximity_shadow is not None:
                try:
                    proximity_shadow.tick()
                except Exception:
                    pass
                ready, _, _ = select.select([sock_rx], [], [], 0.05)
                if not ready:
                    continue
            received = recv_json_packet(sock_rx)
            receive_monotonic = time.monotonic() if proximity_shadow is not None else None
            if received is None:
                continue
            try:
                input_json = received.payload
                command = input_json.get("command", None)

                # Direct WiiBalanceWalker telemetry. This packet is emitted
                # from its Balance Board refresh loop and bypasses Unity/vJoy.
                if input_json.get("type") == "wii_balance":
                    latest_wii_balance = {
                        "tl": float(input_json.get("tl", 0.0)),
                        "tr": float(input_json.get("tr", 0.0)),
                        "bl": float(input_json.get("bl", 0.0)),
                        "br": float(input_json.get("br", 0.0)),
                        "weight": float(input_json.get("weight", 0.0)),
                        "offset_tl": float(input_json.get("offset_tl", 0.0)),
                        "offset_tr": float(input_json.get("offset_tr", 0.0)),
                        "offset_bl": float(input_json.get("offset_bl", 0.0)),
                        "offset_br": float(input_json.get("offset_br", 0.0)),
                        "ratio_tl": float(input_json.get("ratio_tl", 0.0)),
                        "ratio_tr": float(input_json.get("ratio_tr", 0.0)),
                        "ratio_bl": float(input_json.get("ratio_bl", 0.0)),
                        "ratio_br": float(input_json.get("ratio_br", 0.0)),
                        "timestamp": datetime.now().timestamp(),
                    }
                    # Sanitize tare-adjusted values before storage/logging.
                    # Negative readings are sensor noise and NaN ratios occur
                    # when the board is unloaded.
                    for key in ("offset_tl", "offset_tr", "offset_bl", "offset_br"):
                        latest_wii_balance[key] = max(0.0, latest_wii_balance[key])
                    latest_wii_balance["weight"] = max(0.0, latest_wii_balance["weight"])
                    offset_sum = sum(latest_wii_balance[key] for key in ("offset_tl", "offset_tr", "offset_bl", "offset_br"))
                    if offset_sum <= MIN_COP_WEIGHT_KG:
                        for key in ("ratio_tl", "ratio_tr", "ratio_bl", "ratio_br"):
                            latest_wii_balance[key] = 0.0
                    else:
                        for key in ("ratio_tl", "ratio_tr", "ratio_bl", "ratio_br"):
                            if not math.isfinite(latest_wii_balance[key]):
                                latest_wii_balance[key] = 0.0
                    # COP from tare-adjusted corner loads. Clamp each corner
                    # to zero so sensor noise while unweighted cannot invert
                    # the denominator or create a false centre of pressure.
                    offset_tl = max(0.0, latest_wii_balance["offset_tl"])
                    offset_tr = max(0.0, latest_wii_balance["offset_tr"])
                    offset_bl = max(0.0, latest_wii_balance["offset_bl"])
                    offset_br = max(0.0, latest_wii_balance["offset_br"])
                    offset_total = offset_tl + offset_tr + offset_bl + offset_br
                    if offset_total > MIN_COP_WEIGHT_KG:
                        latest_wii_balance["cop_x"] = ((offset_tr + offset_br) - (offset_tl + offset_bl)) / offset_total
                        latest_wii_balance["cop_z"] = ((offset_tl + offset_tr) - (offset_bl + offset_br)) / offset_total
                    else:
                        latest_wii_balance["cop_x"] = 0.0
                        latest_wii_balance["cop_z"] = 0.0
                    clean_payload = dict(input_json)
                    clean_payload.update(latest_wii_balance)
                    if logger is not None:
                        logger.record(
                            "wii",
                            dict(clean_payload, cop_x=latest_wii_balance["cop_x"], cop_z=latest_wii_balance["cop_z"]),
                            source_timestamp=input_json.get("timestamp"),
                            sequence=input_json.get("sequence"),
                        )
                    now = datetime.now().timestamp()
                    if now - last_wii_log_time >= 1.0:
                        print("[WII] TL={:.2f} TR={:.2f} BL={:.2f} BR={:.2f} kg | Total={:.2f} kg".format(
                            latest_wii_balance["tl"], latest_wii_balance["tr"],
                            latest_wii_balance["bl"], latest_wii_balance["br"],
                            latest_wii_balance.get("weight", 0.0)))
                        last_wii_log_time = now
                    continue

                # Accept WiiBalanceWalker samples carried in the same realtime
                # packet as the existing CoP telemetry. This keeps the UDP
                # protocol backwards-compatible for older Unity clients.
                if input_json.get("hasWiiBalanceSensors") or all(k in input_json for k in ("tl", "tr", "bl", "br")):
                    latest_wii_balance.update({
                        "tl": float(input_json.get("tl", 0.0)),
                        "tr": float(input_json.get("tr", 0.0)),
                        "bl": float(input_json.get("bl", 0.0)),
                        "br": float(input_json.get("br", 0.0)),
                        "timestamp": datetime.now().timestamp(),
                    })

                if command == "start_session":
                    warning_bridge.start_session(input_json.get("run_id"))
                    if proximity_shadow is not None:
                        try:
                            proximity_shadow.start_session(input_json.get("run_id"))
                        except Exception:
                            pass
                    current_nickname = input_json.get("nickname", "Guest")
                    print(
                        f"\n[INFO] [Session] Game Started. "
                        f"Player Identified as: [{current_nickname}]"
                    )

                    current_user_profile = load_or_create_user(current_nickname)

                    # A session must begin from a known controller state.
                    # Do not carry a prior user's layer counter, calibration
                    # samples, or command difficulty into the next session.
                    current_difficulty = 1
                    last_eval_count = 0
                    epoch_squared_errors.clear()
                    last_state_idx = None
                    last_action_idx = None
                    is_calibrated = False
                    calibration_errors.clear()
                    stable_layers = 0
                    consecutive_struggles = 0
                    current_rmse = 0.0
                    epsilon = 0.15
                    session_history_log.clear()
                    state_history.clear()

                    # Close any previous session log and start a fresh file in
                    # telemetry_logs/<username>/ for this training session.
                    if logger is not None:
                        logger.close()
                    logger = TimeSynchronizedLogger(username=current_nickname)
                    print(f"[LOGGER] Session CSV: {logger.path}")

                    temp_q = np.array(current_user_profile.get("q_table", []))
                    if temp_q.shape == (3, 3):
                        q_table = temp_q
                        print(
                            "[INFO] [Memory Engine] Q-Table successfully "
                            "loaded for patient."
                        )
                    else:
                        print(
                            "[WARNING] [Memory Engine] Invalid matrix dimension "
                            "detected. Re-initializing default 3x3 Q-Table."
                        )

                        q_table = np.array([
                            [10.0, -5.0, -10.0],
                            [-5.0, 10.0, -5.0],
                            [-10.0, -5.0, 10.0]
                        ])

                    continue

                if command in ["generate_report", "chat"]:
                    passed_layers = input_json.get("passedCount", last_eval_count)
                    avg_x = input_json.get("avgX", 0.0)
                    bal_left = max(0.0, min(100.0, 50.0 - (avg_x * 10.0)))

                    payload_data = {
                        "rmse": current_rmse,
                        "bal_left": bal_left,
                        "passed_layers": passed_layers,
                        "difficulty": current_difficulty,
                        "message": input_json.get("message", ""),
                        "history": list(session_history_log)
                    }

                    threading.Thread(
                        target=fetch_ai_response_async,
                        args=(command, payload_data, sock_tx)
                    ).start()

                    continue

                # Keep the legacy RMSE/difficulty protocol while accepting
                # the newer unity_game telemetry packet. If a new Unity
                # packet does not include legacy COP fields, use the latest
                # directly received Wii COP as the measured balance position.
                is_unity_game = input_json.get("type") == "unity_game"
                if is_unity_game:
                    # Feed the independent warning runtime before the legacy
                    # passedCount==0 calibration path can reply and continue.
                    warning_bridge.ingest_unity_packet(input_json)
                    if proximity_shadow is not None:
                        try:
                            proximity_shadow.ingest(input_json, receive_time=receive_monotonic)
                        except Exception as shadow_error:
                            print(f"[SHADOW] TTE scorer error: {type(shadow_error).__name__}")
                actual_x = input_json.get("copX")
                actual_z = input_json.get("copZ")
                if actual_x is None:
                    actual_x = input_json.get(
                        "cop_x",
                        latest_wii_balance.get("cop_x", 0.0) if is_unity_game else 0.0,
                    )
                if actual_z is None:
                    actual_z = input_json.get(
                        "cop_z",
                        latest_wii_balance.get("cop_z", 0.0) if is_unity_game else 0.0,
                    )
                target_x = input_json.get("targetX", 0.0)
                target_z = input_json.get("targetZ", 0.0)
                passed_count = input_json.get("passedCount")
                if passed_count is None:
                    # platformLevel is 1-based; legacy passedCount is 0-based.
                    platform_level = input_json.get("platformLevel")
                    passed_count = (
                        max(0, int(platform_level) - 1)
                        if platform_level is not None else 0
                    )

                if logger is not None:
                    logger.record(
                        "unity" if is_unity_game else "game",
                        input_json,
                        source_timestamp=input_json.get("timestamp"),
                        sequence=input_json.get("sequence"),
                    )

                if is_unity_game:
                    now = datetime.now().timestamp()
                    if now - last_game_log_time >= 1.0:
                        print(
                            "[GAME] Level={} Distance={:.2f} Tilt={:.2f} "
                            "Difficulty={} Fall={}".format(
                                input_json.get("platformLevel", "?"),
                                float(input_json.get("distanceToHole", 0.0)),
                                float(input_json.get("platformTilt", 0.0)),
                                input_json.get("difficulty", current_difficulty),
                                input_json.get("fallEvent", False),
                            )
                        )
                        last_game_log_time = now

                if passed_count < last_eval_count:
                    last_eval_count = passed_count
                    epoch_squared_errors.clear()
                    current_difficulty = 1
                    last_state_idx = None
                    last_action_idx = None
                    is_calibrated = False
                    calibration_errors.clear()
                    stable_layers = 0
                    consecutive_struggles = 0
                    current_rmse = 0.0
                    epsilon = 0.15
                    session_history_log.clear()
                    state_history.clear()

                    print(
                        "\n[INFO] [Calibration] New session detected. "
                        "Re-initiating resting baseline calibration..."
                    )

                frame_error = (
                    (actual_x - target_x) ** 2 +
                    (actual_z - target_z) ** 2
                )

                if passed_count == 0:
                    if not is_calibrated:
                        calibration_errors.append(frame_error)

                    cop_packet = {
                        "type": "realtime",
                        "x": actual_x,
                        "y": actual_z,
                        # Backend Q-agent is the sole difficulty authority,
                        # including calibration.  The initial value is level 1
                        # because start_session explicitly resets it above.
                        "difficulty": int(current_difficulty),
                        "rmse": 0.0,
                        "tl": latest_wii_balance["tl"],
                        "tr": latest_wii_balance["tr"],
                        "bl": latest_wii_balance["bl"],
                        "br": latest_wii_balance["br"],
                        "weight": latest_wii_balance.get("weight", 0.0),
                        "offset_tl": latest_wii_balance.get("offset_tl", 0.0),
                        "offset_tr": latest_wii_balance.get("offset_tr", 0.0),
                        "offset_bl": latest_wii_balance.get("offset_bl", 0.0),
                        "offset_br": latest_wii_balance.get("offset_br", 0.0),
                        "ratio_tl": latest_wii_balance.get("ratio_tl", 0.0),
                        "ratio_tr": latest_wii_balance.get("ratio_tr", 0.0),
                        "ratio_bl": latest_wii_balance.get("ratio_bl", 0.0),
                        "ratio_br": latest_wii_balance.get("ratio_br", 0.0)
                    }

                    sock_tx.sendto(
                        json.dumps(attach_proximity_warning(warning_bridge.attach(cop_packet), proximity_reply)).encode("utf-8"),
                        (LISTEN_IP, TARGET_PORT_TO_UNITY)
                    )
                    continue

                elif passed_count > 0 and not is_calibrated:
                    baseline_rmse = math.sqrt(
                        sum(calibration_errors) / max(1, len(calibration_errors))
                    )

                    LOW_THRESHOLD = baseline_rmse + 2.0
                    HIGH_THRESHOLD = baseline_rmse + 5.0
                    is_calibrated = True
                    epoch_squared_errors.clear()

                    print(
                        f"[INFO] [Calibration] Baseline established. "
                        f"Thresholds updated: Low [{LOW_THRESHOLD:.2f}] "
                        f"High [{HIGH_THRESHOLD:.2f}]"
                    )

                epoch_squared_errors.append(frame_error)

                if passed_count - last_eval_count >= EVALUATION_BATCH_SIZE:
                    last_eval_count = passed_count

                    frames_taken = len(epoch_squared_errors)
                    if frames_taken > 0:
                        try:
                            group_rmse = math.sqrt(
                                sum(epoch_squared_errors) / frames_taken
                            )

                            current_rmse = group_rmse
                            time_spent = frames_taken / 126.0

                            if group_rmse < LOW_THRESHOLD:
                                base_state = 2
                            elif group_rmse > HIGH_THRESHOLD:
                                base_state = 0
                            else:
                                base_state = 1

                            current_state_idx = base_state
                            reason = "Normal"

                            if time_spent > 2.5:
                                current_state_idx = 0
                                reason = "Timeout(>2.5s)"
                            elif base_state == 2 and time_spent < 0.4:
                                current_state_idx = 1
                                reason = "Quick Fall (<0.4s)"
                            elif base_state == 1 and time_spent < 1.5:
                                current_state_idx = 2
                                reason = "Stable & Fast"

                            state_history.append(current_state_idx)
                            if len(state_history) > STATE_WINDOW_SIZE:
                                state_history.pop(0)

                            averaged_state_idx = int(
                                round(sum(state_history) / len(state_history))
                            )

                            if averaged_state_idx == 0:
                                consecutive_struggles += 1
                                stable_layers = 0
                            else:
                                consecutive_struggles = 0
                                stable_layers += 1

                            states_name = [
                                "S0:Struggle",
                                "S1:Flow",
                                "S2:Mastery"
                            ]

                            print(
                                f"[EVAL] Layer: {passed_count} | "
                                f"Time: {time_spent:.1f}s | "
                                f"RMSE: {group_rmse:.1f} -> "
                                f"State: {states_name[averaged_state_idx]} "
                                f"[{reason}]"
                            )

                            session_history_log.append({
                                "layer": passed_count,
                                "rmse": current_rmse,
                                "difficulty": current_difficulty,
                                "state": states_name[averaged_state_idx]
                            })

                            if (
                                last_state_idx is not None and
                                last_action_idx is not None
                            ):
                                # Neutral reward for combinations that were
                                # not covered by the original rules.
                                reward = 0.0

                                if averaged_state_idx == 1:
                                    reward = 10.0
                                elif current_state_idx == 0:
                                    reward = -10.0
                                elif current_state_idx == 2:
                                    if last_action_idx == 2:
                                        reward = 5.0
                                    else:
                                        reward = -5.0

                                old_q = q_table[
                                    last_state_idx,
                                    last_action_idx
                                ]

                                max_future_q = np.max(
                                    q_table[current_state_idx]
                                )

                                q_table[
                                    last_state_idx,
                                    last_action_idx
                                ] = old_q + alpha * (
                                    reward + gamma * max_future_q - old_q
                                )

                            if random.uniform(0, 1) < epsilon:
                                action_idx = random.randint(0, 2)
                            else:
                                action_idx = int(
                                    np.argmax(q_table[current_state_idx])
                                )

                            action_value = action_idx - 1

                            if (
                                time_spent >= 2.5 or
                                consecutive_struggles >= 2
                            ):
                                action_value = -1
                                consecutive_struggles = 0

                                print(
                                    "[SYSTEM] [Fatigue Protection] Triggered! "
                                    "Forcing difficulty reduction."
                                )

                            elif action_value == 1 and stable_layers < 2:
                                action_value = 0

                            elif (
                                averaged_state_idx == 2
                                and action_value == 0
                                and stable_layers >= MIN_STABLE_LAYERS_TO_INCREASE
                            ):
                                # A learned table can become overly
                                # conservative after noisy historical reward.
                                # Keep Q-learning for ordinary decisions, but
                                # require measured progression after repeated
                                # stable success.
                                action_value = 1
                                print(
                                    "[ACTION] Progression guard: "
                                    f"{stable_layers} stable layers; increasing difficulty."
                                )

                            new_diff = max(
                                1,
                                min(5, current_difficulty + action_value)
                            )

                            if new_diff > current_difficulty:
                                stable_layers = 0

                            if new_diff != current_difficulty:
                                current_difficulty = new_diff

                                print(
                                    f"[ACTION] Q-Agent Policy: Difficulty "
                                    f"adjusted to Level {current_difficulty}"
                                )

                            last_state_idx = averaged_state_idx
                            last_action_idx = action_idx

                        except Exception as eval_err:
                            print(
                                f"[ERROR] [Evaluation Module] "
                                f"Internal Exception: {eval_err}"
                            )
                            traceback.print_exc()

                        finally:
                            epoch_squared_errors.clear()

                            if epsilon > 0.05:
                                epsilon *= 0.99

                cop_packet = {
                    "type": "realtime",
                    "x": actual_x,
                    "y": actual_z,
                    "difficulty": int(current_difficulty),
                    "rmse": float(current_rmse),
                    "tl": latest_wii_balance["tl"],
                    "tr": latest_wii_balance["tr"],
                    "bl": latest_wii_balance["bl"],
                    "br": latest_wii_balance["br"],
                    "weight": latest_wii_balance.get("weight", 0.0),
                    "offset_tl": latest_wii_balance.get("offset_tl", 0.0),
                    "offset_tr": latest_wii_balance.get("offset_tr", 0.0),
                    "offset_bl": latest_wii_balance.get("offset_bl", 0.0),
                    "offset_br": latest_wii_balance.get("offset_br", 0.0),
                    "ratio_tl": latest_wii_balance.get("ratio_tl", 0.0),
                    "ratio_tr": latest_wii_balance.get("ratio_tr", 0.0),
                    "ratio_bl": latest_wii_balance.get("ratio_bl", 0.0),
                    "ratio_br": latest_wii_balance.get("ratio_br", 0.0)
                }

                sock_tx.sendto(
                    json.dumps(attach_proximity_warning(warning_bridge.attach(cop_packet), proximity_reply)).encode("utf-8"),
                    (LISTEN_IP, TARGET_PORT_TO_UNITY)
                )

            except Exception as exc:
                log_processing_error(
                    input_json, received.byte_count, received.peer, exc
                )
                traceback.print_exc()

    except KeyboardInterrupt:
        print("\n[SYSTEM] Backend termination sequence initiated.")

    finally:
        if logger is not None:
            print(f"[LOGGER] CSV saved: {logger.path}")
            print(f"[LOGGER] Sampling summary: {logger.summary()}")
            logger.close()
        sock_rx.close()
        sock_tx.close()


if __name__ == "__main__":
    start_backend()
