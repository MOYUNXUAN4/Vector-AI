import socket
import json
import os
from db_manager import load_or_create_user, get_user_filepath, save_user_data

# According to the decoupled architecture, configure UDP IP and Port
UDP_IP = "127.0.0.1"
UDP_PORT = 6000 

def start_server():
    # Initialize UDP Socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    
    print(f"==================================================")
    print(f" [SYSTEM] VectorAI Authentication Server Initialized")
    print(f" [INFO] Listening for client requests on UDP port {UDP_PORT}...")
    print(f"==================================================\n")

    while True:
        try:
            # 1. Receive data payload from Unity client
            data, addr = sock.recvfrom(4096)
        except Exception as e:
            print(f"[ERROR] [Auth Service] Socket receive error: {e}")
            continue

        response = {"status": "error", "message": "An unknown error occurred during authentication."}

        try:
            # 2. Decode and parse JSON payload safely
            message = data.decode('utf-8')
            print(f"[INFO] [Auth Service] Request received from client {addr}: {message}")

            request = json.loads(message)
            req_type = request.get("type")
            nickname = request.get("nickname")

            if not nickname or not isinstance(nickname, str) or not nickname.strip():
                response = {"status": "error", "message": "Username is required and cannot be empty."}
                print(f"[WARNING] [Auth Service] Rejected request from {addr}: Missing or invalid nickname.")

            # 3. Process Registration Logic
            elif req_type == "REGISTER":
                nickname = nickname.strip()
                if os.path.exists(get_user_filepath(nickname)):
                    response = {"status": "error", "message": "Username already exists. Please login directly."}
                    print(f"[WARNING] [Auth Service] Registration rejected: Conflict for username '{nickname}'.")
                else:
                    user_data = load_or_create_user(nickname) # Initialize new user profile
                    # Serialize additional demographic/anthropometric data
                    user_data["age_group"] = request.get("age_group", "65+")
                    user_data["height"] = request.get("height", "")
                    user_data["weight"] = request.get("weight", "")
                    save_user_data(nickname, user_data) # Commit to local DB
                    
                    response = {"status": "success", "type": "REGISTER_SUCCESS", "nickname": nickname}
                    print(f"[SUCCESS] [Database] New patient profile registered and allocated for: '{nickname}'.")

            # 4. Process Login Logic
            elif req_type == "LOGIN":
                nickname = nickname.strip()
                if not os.path.exists(get_user_filepath(nickname)):
                    response = {"status": "error", "message": "User not found. Please register a new account."}
                    print(f"[WARNING] [Auth Service] Login denied: Profile '{nickname}' not found in database.")
                else:
                    user_data = load_or_create_user(nickname) # Retrieve existing profile
                    response = {"status": "success", "type": "LOGIN_SUCCESS", "nickname": nickname, "high_score": user_data.get("high_score", 0)}
                    print(f"[SUCCESS] [Auth Service] Session authenticated for returning patient: '{nickname}'.")

            else:
                response = {"status": "error", "message": f"Unsupported request type '{req_type}'."}
                print(f"[WARNING] [Auth Service] Unknown request type: {req_type}")

        except UnicodeDecodeError as e:
            response = {"status": "error", "message": "Malformed packet encoding (must be UTF-8)."}
            print(f"[ERROR] [Auth Service] UTF-8 decode error from {addr}: {e}")
        except json.JSONDecodeError as e:
            response = {"status": "error", "message": "Malformed JSON payload."}
            print(f"[ERROR] [Auth Service] JSON decode error from {addr}: {e}")
        except Exception as e:
            response = {"status": "error", "message": f"Server processing error: {e}"}
            print(f"[ERROR] [Auth Service] Processing exception: {e}\n")

        # 5. Always dispatch response packet back to Unity client so client does not hang
        try:
            sock.sendto(json.dumps(response).encode('utf-8'), addr)
            print(f"[INFO] [Auth Service] Response dispatched to client {addr}: {response}\n")
        except Exception as send_err:
            print(f"[ERROR] [Auth Service] Failed to dispatch response to {addr}: {send_err}\n")

if __name__ == "__main__":
    start_server()