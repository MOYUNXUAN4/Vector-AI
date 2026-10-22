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

# Import local database manager (ensure db_manager.py is in the same directory)
from db_manager import load_or_create_user, save_user_data

# ==========================================
# Network Communication & Basic Configuration
# ==========================================
LISTEN_IP = "127.0.0.1"
LISTEN_PORT_FROM_UNITY = 5007 
TARGET_PORT_TO_UNITY = 5008 

# AI Report Generation API Configuration (DeepSeek LLM)
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# ==========================================
# Core AI Variables (Q-Learning & DDA)
# ==========================================
CALIBRATION_TIME_SEC = 10.0      # Duration for initial baseline calibration
DIFFICULTY_COOLDOWN_SEC = 8.0    # Minimum 8s time between advanced difficulty adjustments
session_start_time = 0.0         
last_difficulty_change_time = 0.0

# [OPTIMIZATION]: Reduced batch size to 30 for faster DDA responsiveness
EVALUATION_BATCH_SIZE = 30  
current_difficulty = 1 
epoch_squared_errors = []  
last_eval_count = 0        
session_history_log = []

current_user_profile = None
current_nickname = "Guest"

# Dynamic thresholds based on calibration
LOW_THRESHOLD = 1.0   
HIGH_THRESHOLD = 3.0  
is_calibrated = False       
calibration_errors = []     
current_rmse = 0.0  

# [Core Mod Variables]: Tracking clinical fatigue and mastery persistence
mastery_layers = 0
consecutive_struggles = 0

state_history = []  
# Window size minimized to 2 to prevent state transition latency
STATE_WINDOW_SIZE = 2

# Initial Q-Table Matrix (State x Action)
# States: S0 (Struggle), S1 (Flow), S2 (Mastery)
# Actions: -1 (Decrease), 0 (Maintain), +1 (Increase)
q_table = np.array([
    [ 10.0, -5.0, -10.0],  # Row 0 -> State S0: Struggle
    [-5.0,  10.0, -5.0 ],  # Row 1 -> State S1: Flow
    [-10.0, -5.0,  10.0]   # Row 2 -> State S2: Mastery
])

# Reinforcement Learning Hyperparameters
alpha = 0.1       # Learning rate
gamma = 0.9       # Discount factor
epsilon = 0.15    # Exploration rate

last_state_idx = None
last_action_idx = None
ai_chat_history = []

def fetch_ai_response_async(command, payload_data, sock_tx):
    """
    Asynchronous thread to handle LLM API requests without blocking the UDP telemetry loop.
    """
    global ai_chat_history, current_user_profile, current_nickname, q_table
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

    if command == "generate_report":
        print("\n[INFO] [LLM Service] Initiating clinical analysis report generation...")
        rmse = payload_data.get("rmse", 0.0)
        distance = payload_data.get("passed_layers", 0)
        history_log = payload_data.get("history", [])

        previous_rmse = None
        if current_user_profile is not None:
            previous_rmse = current_user_profile.get("last_runningball_rmse", None)
            
            # Update user profile with latest session data
            current_user_profile["total_sessions"] += 1
            current_user_profile["q_table"] = q_table.tolist() 
            if distance > current_user_profile.get("runningball_high_score", 0):
                current_user_profile["runningball_high_score"] = distance
            current_user_profile["last_runningball_rmse"] = rmse
            
            # Persist data to local storage
            save_user_data(current_nickname, current_user_profile)

        # Format session telemetry for the LLM prompt
        history_str = "\n".join([f"Distance {item['layer']}m: RMSE {item['rmse']:.2f} | AI Difficulty {item['difficulty']} | State: {item['state']}" for item in history_log[-15:]])
        if not history_str: history_str = "No specific data recorded."

        past_comparison_text = f"- PREVIOUS Session Average RMSE: {previous_rmse:.2f} mm" if previous_rmse is not None else "- PREVIOUS Session: N/A (This is their first session)."
        
        system_prompt = f"""You are the VectorAI Virtual Coach...
[Patient's Session Telemetry]
- Final Average Tracking Error (RMSE): {rmse:.2f} mm.
{past_comparison_text}
- Distance Covered Before Falling: {distance} meters.
[Continuous Performance Log]
{history_str}
[Interaction Rules]
1. IMPORTANT: You MUST communicate primarily in ENGLISH.
2. Begin EXACTLY like this: "Hello [ {current_nickname} ], I am VectorAI."
3. Compare "Current RMSE" with "PREVIOUS RMSE".
4. Give ONE posture adjustment tip.
5. NO MARKDOWN."""
        
        ai_chat_history = [{"role": "system", "content": system_prompt}]
        ai_chat_history.append({"role": "user", "content": "I fell off the track. Please generate my clinical report."})

    elif command == "chat":
        ai_chat_history.append({"role": "user", "content": payload_data.get("message", "")})

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json={"model": "deepseek-chat", "messages": ai_chat_history}, timeout=20)
        if response.status_code == 200:
            ai_reply = response.json()["choices"][0]["message"]["content"].replace("**", "").replace("*", "").strip()
            sock_tx.sendto(json.dumps({"type": "ai_report", "content": ai_reply}).encode('utf-8'), (LISTEN_IP, TARGET_PORT_TO_UNITY))
    except Exception as e:
        print(f"[ERROR] LLM: {e}")

def start_backend():
    """
    Main loop for the UDP backend. Handles telemetry parsing, RMSE calculation, 
    and Q-Learning Dynamic Difficulty Adjustment (DDA) with Asymmetric Scaling.
    """
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

    print(f"==================================================")
    print(f" [SYSTEM] VectorAI Path Following Engine Initialized")
    print(f"==================================================\n")
    
    while True:
        try:
            data, addr = sock_rx.recvfrom(4096)
            input_json = json.loads(data.decode('utf-8'))
            command = input_json.get("command", None)

            # Handle Session Initialization
            if command == "start_session":
                current_nickname = input_json.get("nickname", "Guest")
                current_user_profile = load_or_create_user(current_nickname)
                
                temp_q = np.array(current_user_profile.get("q_table", []))
                q_table = temp_q if temp_q.shape == (3, 3) else np.array([[ 10.0, -5.0, -10.0], [-5.0,  10.0, -5.0], [-10.0, -5.0,  10.0]])
                
                session_start_time = time.time()
                last_difficulty_change_time = session_start_time
                continue

            # Handle Asynchronous LLM Requests
            if command in ["generate_report", "chat"]:
                threading.Thread(
                    target=fetch_ai_response_async, 
                    args=(command, {"rmse": current_rmse, "passed_layers": input_json.get("passedCount", 0), "message": input_json.get("message", ""), "history": list(session_history_log)}, sock_tx)
                ).start()
                continue 

            # Parse Continuous Biomechanical Telemetry
            actual_x, target_x = input_json.get("copX", 0.0), input_json.get("targetX", 0.0)
            path_width, passed_count = input_json.get("pathWidth", 10.0), input_json.get("passedCount", 0) 
            current_time = time.time()

            # Handle Game Restarts or Anomalous Distances
            if passed_count == 0 or (last_eval_count - passed_count > 10):
                last_eval_count = passed_count
                epoch_squared_errors.clear()
                current_difficulty = 1  
                is_calibrated = False
                calibration_errors.clear()
                mastery_layers, consecutive_struggles = 0, 0
                session_history_log.clear()
                state_history.clear()
                session_start_time, last_difficulty_change_time = current_time, current_time
                print(f"\n[INFO] Initiating {CALIBRATION_TIME_SEC}s calibration...")
            elif passed_count < last_eval_count:
                continue

            # Compute Spatial Tolerance
            offset = abs(actual_x - target_x)
            effective_error = 0.0 if offset <= path_width * 0.05 else offset - (path_width * 0.05)
            frame_error = effective_error ** 2 
            elapsed_time_since_start = current_time - session_start_time

            # Phase 1: Dynamic Baseline Calibration
            if elapsed_time_since_start < CALIBRATION_TIME_SEC: 
                if not is_calibrated: 
                    calibration_errors.append(frame_error)
                sock_tx.sendto(json.dumps({"type": "realtime", "difficulty": 1, "rmse": 0.0}).encode('utf-8'), (LISTEN_IP, TARGET_PORT_TO_UNITY))
                continue 

            elif elapsed_time_since_start >= CALIBRATION_TIME_SEC and not is_calibrated:
                raw_baseline = math.sqrt(sum(calibration_errors) / max(1, len(calibration_errors)))
                baseline_rmse = min(raw_baseline, 1.5) 
                LOW_THRESHOLD = baseline_rmse + 0.5  
                HIGH_THRESHOLD = baseline_rmse + 2.0 
                is_calibrated = True
                epoch_squared_errors.clear()
                last_eval_count = passed_count 
                print(f"[INFO] Capped Baseline: {baseline_rmse:.2f}. LOW: {LOW_THRESHOLD:.2f}, HIGH: {HIGH_THRESHOLD:.2f}")

            # Phase 2: Q-Learning & Continuous Evaluation
            epoch_squared_errors.append(frame_error)

            if passed_count - last_eval_count >= EVALUATION_BATCH_SIZE:
                last_eval_count = passed_count
                frames_taken = len(epoch_squared_errors)
                
                if frames_taken > 0:
                    try:
                        # Calculate Batch RMSE
                        group_rmse = math.sqrt(sum(epoch_squared_errors) / frames_taken)
                        current_rmse = group_rmse  
                        
                        # Determine Raw State
                        if group_rmse < LOW_THRESHOLD: base_state = 2     
                        elif group_rmse > HIGH_THRESHOLD: base_state = 0  
                        else: base_state = 1                              
                        
                        state_history.append(base_state)
                        if len(state_history) > STATE_WINDOW_SIZE: 
                            state_history.pop(0)
                        
                        averaged_state_idx = int(round(sum(state_history) / len(state_history)))
                        
                        # Emergency fallback evaluation
                        if group_rmse > 4.0:
                            averaged_state_idx = 0
                            state_history = [0] * STATE_WINDOW_SIZE
                        
                        # Elastic Mastery Tracking
                        if averaged_state_idx == 2:
                            mastery_layers += 1
                            consecutive_struggles = 0
                        elif averaged_state_idx == 0:
                            consecutive_struggles += 1
                            mastery_layers = 0
                        else: 
                            consecutive_struggles = 0
                            mastery_layers = max(0, mastery_layers - 1)

                        states_name = ["S0:Struggle", "S1:Flow", "S2:Mastery"]
                        print(f"[EVAL] Distance: {passed_count}m | RMSE: {group_rmse:.2f} -> State: {states_name[averaged_state_idx]} | Struggles: {consecutive_struggles}")

                        session_history_log.append({"layer": passed_count, "rmse": current_rmse, "difficulty": current_difficulty, "state": states_name[averaged_state_idx]})

                        # Update Q-Table
                        if last_state_idx is not None and last_action_idx is not None:
                            if averaged_state_idx == 1: reward = 10.0   
                            elif averaged_state_idx == 0: reward = -10.0  
                            elif averaged_state_idx == 2: reward = 5.0 if last_action_idx == 2 else -5.0
                            
                            old_q = q_table[last_state_idx, last_action_idx]
                            q_table[last_state_idx, last_action_idx] = old_q + alpha * (reward + gamma * np.max(q_table[averaged_state_idx]) - old_q)

                        # Action Selection
                        if random.uniform(0, 1) < epsilon: action_idx = random.randint(0, 2)
                        else: action_idx = int(np.argmax(q_table[averaged_state_idx])) 
                        
                        action_value = action_idx - 1 
                        
                        # ==========================================
                        # [CLINICAL DDA LOGIC: Path Following Optimization]
                        # ==========================================
                        
                        # 1. Fast-track Upgrades for Level 1 and 2
                        required_mastery = 1 if current_difficulty < 3 else 3
                        
                        # 2. Asymmetric Downgrade Resistance: Hard to fall from Level 3+
                        if current_difficulty >= 3:
                            struggle_tolerance = 5
                            emergency_rmse = 4.0
                        else:
                            struggle_tolerance = 3
                            emergency_rmse = 3.5
                            
                        # [CLINICAL UPDATE]: Level 3 -> Level 2 Downgrade Cooldown Lock
                        is_emergency = group_rmse > emergency_rmse
                        is_struggling = consecutive_struggles >= struggle_tolerance
                        
                        if is_emergency or is_struggling:
                            # Interception Logic: Prevent downgrades from Level 3 if within the 8s cooldown (unless emergency)
                            if current_difficulty == 3 and not is_emergency and (current_time - last_difficulty_change_time < DIFFICULTY_COOLDOWN_SEC):
                                action_value = 0
                                print(f"[RESTRICTION] Holding at Level 3. Struggle detected, but {DIFFICULTY_COOLDOWN_SEC}s cooldown is active.")
                            else:
                                action_value = -1  
                                consecutive_struggles = 0 
                                mastery_layers = 0
                                print("[ACTION] Protecting patient stability, forcing difficulty reduction!")
                                
                        elif action_value == 1: 
                            if averaged_state_idx != 2:
                                action_value = 0 
                                print("[RESTRICTION] Agent proposes upgrade, but patient is not in Mastery. Vetoed.")
                            elif mastery_layers < required_mastery: 
                                action_value = 0 
                                print(f"[RESTRICTION] Holding in Mastery ({mastery_layers}/{required_mastery}) for Level {current_difficulty} progression.")
                        
                        # 3. Hard Floor Mechanism: Level 2 can NEVER drop to Level 1 once attained
                        lower_bound = 2 if current_difficulty >= 2 else 1
                        new_diff = max(lower_bound, min(5, current_difficulty + action_value))
                        
                        if action_value == -1 and new_diff == current_difficulty:
                            print(f"[RESTRICTION] Downgrade blocked: Minimum therapeutic difficulty floor (Level {lower_bound}) reached.")
                        
                        if new_diff != current_difficulty:
                            is_upgrade = new_diff > current_difficulty
                            requires_cooldown = is_upgrade and new_diff >= 3
                            
                            # Apply new settings and reset cooldown timestamp
                            if is_emergency or not requires_cooldown or (current_time - last_difficulty_change_time >= DIFFICULTY_COOLDOWN_SEC):
                                current_difficulty = new_diff
                                last_difficulty_change_time = current_time
                                print(f"[ACTION] Path Following Difficulty SUCCESSFULLY adjusted to Level {current_difficulty}")
                                if is_upgrade:
                                    mastery_layers = 0 
                            else:
                                print(f"[ACTION] Blocked: AI proposes Level {new_diff}, but {DIFFICULTY_COOLDOWN_SEC}s Cooldown is currently active.")
                        
                        last_state_idx, last_action_idx = averaged_state_idx, action_idx
                        
                    except Exception as eval_err: 
                        traceback.print_exc()
                    finally:
                        epoch_squared_errors.clear()
                        if epsilon > 0.05: epsilon *= 0.99  

            sock_tx.sendto(json.dumps({"type": "realtime", "difficulty": int(current_difficulty), "rmse": float(current_rmse)}).encode('utf-8'), (LISTEN_IP, TARGET_PORT_TO_UNITY))
            
        except Exception as e: 
            pass 

if __name__ == "__main__":
    start_backend()