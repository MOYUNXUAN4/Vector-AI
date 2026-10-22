import socket
import json
import math
import numpy as np
import random
import threading
import requests
import traceback
import time
import os

# Import local database manager
from db_manager import load_or_create_user, save_user_data

# ==========================================
# Exclusive Configuration: Car Dodging Module
# ==========================================
LISTEN_IP = "127.0.0.1"
LISTEN_PORT_FROM_UNITY = 5009
TARGET_PORT_TO_UNITY = 5010

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# ==========================================
# Core AI Variables (Q-Learning & DDA)
# ==========================================
CALIBRATION_TIME_SEC = 10.0
DIFFICULTY_COOLDOWN_SEC = 8.0
session_start_time = 0.0
last_difficulty_change_time = 0.0

EVALUATION_BATCH_SIZE = 50
current_difficulty = 1
epoch_squared_errors = []
last_eval_count = 0
session_history_log = []

current_user_profile = None
current_nickname = "Guest"

LOW_THRESHOLD = 1.0
HIGH_THRESHOLD = 3.0
is_calibrated = False
calibration_errors = []
current_rmse = 0.0

mastery_layers = 0
consecutive_struggles = 0
state_history = []

# Minimized window size for immediate state transition.
STATE_WINDOW_SIZE = 1

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
ai_chat_history = []


def fetch_ai_response_async(command, payload_data, sock_tx):
    global ai_chat_history, current_user_profile, current_nickname, q_table

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    # Always use this helper for Unity replies.
    # Unity receives ai_report and releases its isAITyping state.
    def send_ai_reply(content):
        packet = {
            "type": "ai_report",
            "content": content
        }

        sock_tx.sendto(
            json.dumps(packet).encode("utf-8"),
            (LISTEN_IP, TARGET_PORT_TO_UNITY)
        )

    if command == "generate_report":
        print("\n[INFO] [LLM Service] Initiating CAR DODGING clinical analysis report...")

        rmse = payload_data.get("rmse", 0.0)
        distance = payload_data.get("passed_layers", 0)
        history_log = payload_data.get("history", [])

        previous_rmse = None

        if current_user_profile is not None:
            previous_rmse = current_user_profile.get("last_car_rmse", None)
            current_user_profile["total_sessions"] += 1
            current_user_profile["car_q_table"] = q_table.tolist()

            if distance > current_user_profile.get("car_high_score", 0):
                current_user_profile["car_high_score"] = distance

            current_user_profile["last_car_rmse"] = rmse
            save_user_data(current_nickname, current_user_profile)

        history_str = "\n".join([
            f"Time Tick {item['layer']}: "
            f"Jitter-RMSE {item['rmse']:.2f} | "
            f"AI Difficulty {item['difficulty']} | "
            f"State: {item['state']}"
            for item in history_log[-15:]
        ])

        if not history_str:
            history_str = "No specific data recorded."

        past_comparison_text = (
            f"- PREVIOUS Session Average Jitter: {previous_rmse:.2f}"
            if previous_rmse is not None
            else "- PREVIOUS Session: N/A (First session)."
        )

        system_prompt = f"""You are the VectorAI Virtual Coach, an elite clinical rehabilitation physician.
[Project Background]
The patient stands on a Nintendo Wii Balance Board to control a virtual car dodging oncoming traffic. The game tests their dynamic weight-shifting speed and postural stability under cognitive load.

[Patient's Session Telemetry]
- Final Average Postural Jitter (RMSE): {rmse:.2f} (Lower is better, meaning they stayed stable while dodging).
{past_comparison_text}
- Survival Score (Time/Distance): {distance}.

[Continuous Performance Log]
{history_str}

[Interaction Rules]
1. IMPORTANT: You MUST communicate primarily in ENGLISH.
2. Begin EXACTLY like this: "Hello [ {current_nickname} ], I am VectorAI."
3. Compare their "Current Jitter" with their "PREVIOUS Jitter".
4. Give ONE posture or weight-distribution tip specifically for maintaining balance while making quick lateral movements (like dodging).
5. NO MARKDOWN."""

        ai_chat_history = [{"role": "system", "content": system_prompt}]
        ai_chat_history.append({
            "role": "user",
            "content": "I crashed. Please generate my clinical report."
        })

    elif command == "chat":
        user_message = payload_data.get("message", "").strip()

        print(f"[INFO] [LLM Service] Chat message received: {user_message}")

        if not user_message:
            send_ai_reply("Please type a message before sending.")
            return

        # Handles chat safely even if a report was not requested first.
        if not ai_chat_history:
            ai_chat_history = [{
                "role": "system",
                "content": (
                    "You are VectorAI, a supportive rehabilitation coach. "
                    "Answer briefly in English and do not use Markdown."
                )
            }]

        ai_chat_history.append({
            "role": "user",
            "content": user_message
        })

    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json={
                "model": "deepseek-chat",
                "messages": ai_chat_history
            },
            timeout=20
        )

        if response.status_code == 200:
            ai_reply = response.json()["choices"][0]["message"]["content"]
            ai_reply = ai_reply.replace("**", "").replace("*", "").strip()

            ai_chat_history.append({
                "role": "assistant",
                "content": ai_reply
            })

            print("[SUCCESS] [LLM Service] AI response sent to Unity.")
            send_ai_reply(ai_reply)

        else:
            print(
                f"[ERROR] [LLM Service] API Request Failed: "
                f"{response.status_code} - {response.text}"
            )

            send_ai_reply(
                "I could not generate a response right now. "
                "Please check the AI connection and try again."
            )

    except requests.Timeout:
        print("[ERROR] [LLM Service] Request timed out.")

        send_ai_reply(
            "The AI service took too long to respond. Please try again."
        )

    except Exception as e:
        print(f"[ERROR] [LLM Service] Connection Exception: {e}")

        send_ai_reply(
            "The AI service is temporarily unavailable. Please try again."
        )


def start_backend():
    global current_difficulty, last_eval_count, epoch_squared_errors
    global last_state_idx, last_action_idx, q_table
    global is_calibrated, calibration_errors, LOW_THRESHOLD, HIGH_THRESHOLD
    global mastery_layers, consecutive_struggles, current_rmse, epsilon
    global session_history_log, state_history
    global current_user_profile, current_nickname
    global session_start_time, last_difficulty_change_time

    sock_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_rx.bind((LISTEN_IP, LISTEN_PORT_FROM_UNITY))

    sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print("==================================================")
    print(" [SYSTEM] VectorAI CAR DODGING Backend Initialized")
    print("==================================================\n")

    while True:
        try:
            data, addr = sock_rx.recvfrom(4096)
            input_json = json.loads(data.decode("utf-8"))
            command = input_json.get("command", None)

            if command == "start_session":
                current_nickname = input_json.get("nickname", "Guest")
                current_user_profile = load_or_create_user(current_nickname)

                temp_q = np.array(
                    current_user_profile.get("car_q_table", [])
                )

                q_table = (
                    temp_q
                    if temp_q.shape == (3, 3)
                    else np.array([
                        [10.0, -5.0, -10.0],
                        [-5.0, 10.0, -5.0],
                        [-10.0, -5.0, 10.0]
                    ])
                )

                session_start_time = time.time()
                last_difficulty_change_time = session_start_time

                print(
                    f"\n[INFO] [Session] Car Dodging Started. "
                    f"Player: [{current_nickname}]"
                )
                continue

            if command in ["generate_report", "chat"]:
                payload_data = {
                    "rmse": current_rmse,
                    "passed_layers": input_json.get("passedCount", 0),
                    "message": input_json.get("message", ""),
                    "history": list(session_history_log)
                }

                threading.Thread(
                    target=fetch_ai_response_async,
                    args=(command, payload_data, sock_tx),
                    daemon=True
                ).start()

                continue

            actual_x = input_json.get("copX", 0.0)
            target_x = input_json.get("targetX", 0.0)
            passed_count = input_json.get("passedCount", 0)
            current_time = time.time()

            if passed_count == 0 or (last_eval_count - passed_count > 10):
                last_eval_count = passed_count
                epoch_squared_errors.clear()
                current_difficulty = 1
                is_calibrated = False
                calibration_errors.clear()
                mastery_layers = 0
                consecutive_struggles = 0
                session_history_log.clear()
                state_history.clear()

                session_start_time = current_time
                last_difficulty_change_time = current_time

                print(
                    f"\n[INFO] Initiating {CALIBRATION_TIME_SEC}s "
                    f"Driving Stability Calibration..."
                )

            elif passed_count < last_eval_count:
                continue

            offset = abs(actual_x - target_x)
            frame_error = offset ** 2
            elapsed_time_since_start = current_time - session_start_time

            if elapsed_time_since_start < CALIBRATION_TIME_SEC:
                if not is_calibrated:
                    calibration_errors.append(frame_error)

                sock_tx.sendto(
                    json.dumps({
                        "type": "realtime",
                        "difficulty": 1,
                        "rmse": 0.0
                    }).encode("utf-8"),
                    (LISTEN_IP, TARGET_PORT_TO_UNITY)
                )

                continue

            elif not is_calibrated:
                raw_baseline = math.sqrt(
                    sum(calibration_errors) / max(1, len(calibration_errors))
                )

                baseline_rmse = raw_baseline
                LOW_THRESHOLD = baseline_rmse * 1.2
                HIGH_THRESHOLD = baseline_rmse * 2.0

                is_calibrated = True
                epoch_squared_errors.clear()
                last_eval_count = passed_count

                print(
                    f"[INFO] Calibration Complete. "
                    f"Baseline Jitter: {baseline_rmse:.2f}. "
                    f"LOW: {LOW_THRESHOLD:.2f}, "
                    f"HIGH: {HIGH_THRESHOLD:.2f}"
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
                        is_emergency = False

                        if (
                            group_rmse > (HIGH_THRESHOLD * 2.5) or
                            group_rmse > 8.0
                        ):
                            is_emergency = True
                            averaged_state_idx = 0
                            state_history = [0] * STATE_WINDOW_SIZE
                            consecutive_struggles += 1

                            print(
                                f"[EMERGENCY] Loss of control detected! "
                                f"Extreme Jitter ({group_rmse:.2f})!"
                            )

                        else:
                            if group_rmse < LOW_THRESHOLD:
                                base_state = 2
                            elif group_rmse > HIGH_THRESHOLD:
                                base_state = 0
                            else:
                                base_state = 1

                            state_history.append(base_state)

                            if len(state_history) > STATE_WINDOW_SIZE:
                                state_history.pop(0)

                            averaged_state_idx = int(
                                round(
                                    sum(state_history) /
                                    len(state_history)
                                )
                            )

                        if not is_emergency:
                            if averaged_state_idx == 2:
                                mastery_layers += 1
                                consecutive_struggles = 0

                            elif averaged_state_idx == 0:
                                consecutive_struggles += 1
                                mastery_layers = 0

                            else:
                                consecutive_struggles = 0
                                mastery_layers = max(
                                    0,
                                    mastery_layers - 1
                                )

                        states_name = [
                            "S0:Struggle",
                            "S1:Flow",
                            "S2:Mastery"
                        ]

                        print(
                            f"[EVAL] Time-Score: {passed_count} | "
                            f"Jitter-RMSE: {group_rmse:.2f} -> "
                            f"State: {states_name[averaged_state_idx]}"
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
                            if averaged_state_idx == 1:
                                reward = 10.0
                            elif averaged_state_idx == 0:
                                reward = -10.0
                            else:
                                reward = (
                                    5.0
                                    if last_action_idx == 2
                                    else -5.0
                                )

                            old_q = q_table[
                                last_state_idx,
                                last_action_idx
                            ]

                            q_table[
                                last_state_idx,
                                last_action_idx
                            ] = old_q + alpha * (
                                reward +
                                gamma * np.max(
                                    q_table[averaged_state_idx]
                                ) -
                                old_q
                            )

                        if random.uniform(0, 1) < epsilon:
                            action_idx = random.randint(0, 2)
                        else:
                            action_idx = int(
                                np.argmax(q_table[averaged_state_idx])
                            )

                        action_value = action_idx - 1

                        required_mastery = (
                            1 if current_difficulty < 3 else 3
                        )

                        if current_difficulty >= 3:
                            struggle_tolerance = 5
                        else:
                            struggle_tolerance = 3

                        if (
                            is_emergency or
                            consecutive_struggles >= struggle_tolerance
                        ):
                            action_value = -1
                            consecutive_struggles = 0
                            mastery_layers = 0

                            print(
                                "[ACTION] Protecting player safety, "
                                "forcing speed reduction!"
                            )

                        elif action_value == 1:
                            if averaged_state_idx != 2:
                                action_value = 0

                                print(
                                    "[RESTRICTION] Agent wants to speed up, "
                                    "but player is not in Mastery. Vetoed."
                                )

                            elif mastery_layers < required_mastery:
                                action_value = 0

                                print(
                                    f"[RESTRICTION] Holding in Mastery "
                                    f"({mastery_layers}/{required_mastery}) "
                                    f"before speed up to Level "
                                    f"{current_difficulty + 1}."
                                )

                        lower_bound = (
                            2 if current_difficulty >= 2 else 1
                        )

                        new_diff = max(
                            lower_bound,
                            min(5, current_difficulty + action_value)
                        )

                        if (
                            action_value == -1 and
                            new_diff == current_difficulty
                        ):
                            print(
                                f"[RESTRICTION] Downgrade blocked: "
                                f"Minimum difficulty floor "
                                f"(Level {lower_bound}) reached."
                            )

                        if new_diff != current_difficulty:
                            is_upgrade = new_diff > current_difficulty

                            requires_cooldown = (
                                is_upgrade and new_diff >= 3
                            )

                            if (
                                is_emergency or
                                not requires_cooldown or
                                current_time -
                                last_difficulty_change_time
                                >= DIFFICULTY_COOLDOWN_SEC
                            ):
                                current_difficulty = new_diff
                                last_difficulty_change_time = current_time

                                print(
                                    f"[ACTION] Car Difficulty "
                                    f"SUCCESSFULLY adjusted to "
                                    f"Level {current_difficulty}"
                                )

                            else:
                                print(
                                    f"[ACTION] Blocked: AI wants "
                                    f"Level {new_diff}, but 8s cooldown "
                                    f"is active."
                                )

                        last_state_idx = averaged_state_idx
                        last_action_idx = action_idx

                    except Exception:
                        traceback.print_exc()

                    finally:
                        epoch_squared_errors.clear()

                        if epsilon > 0.05:
                            epsilon *= 0.99

            sock_tx.sendto(
                json.dumps({
                    "type": "realtime",
                    "difficulty": int(current_difficulty),
                    "rmse": float(current_rmse)
                }).encode("utf-8"),
                (LISTEN_IP, TARGET_PORT_TO_UNITY)
            )

        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    start_backend()