import threading
import time
import sys
import os

# Import core server modules
import login_server
import UDPRecevier
import runningball_ai
import car_backend 

def _master_warning_bridge():
    integration_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "parallel_20261011", "realtime_integration"
    )
    if integration_dir not in sys.path:
        sys.path.insert(0, integration_dir)
    from bridge import RealtimeWarningBridge, env_enabled

    def enabled_by_default(name):
        value = os.getenv(name)
        return True if value is None else env_enabled(name)

    return RealtimeWarningBridge(
        enabled=enabled_by_default("FALLING_WARNING_MODEL_ENABLED"),
        allow_calibration_gameplay=enabled_by_default(
            "FALLING_WARNING_ALLOW_CALIBRATION_GAMEPLAY"))
def run_login_server():
    try:
        login_server.start_server()
    except Exception as e:
        print(f"[ERROR] [Master Control] Login Server encountered a fatal error: {e}")

def run_falling_server():
    try:
        warning_bridge = _master_warning_bridge()
        try:
            result = warning_bridge.preload()
            if result.get("loaded"):
                print(f"[EXPERIMENTAL] Falling warning model loaded: {result.get('model_id')}")
            elif not result.get("enabled"):
                print(f"[EXPERIMENTAL] Falling warning model disabled: {result.get('reason')}")
            else:
                print(f"[EXPERIMENTAL] Falling warning model unavailable: {result.get('reason')}")
        except Exception as preload_error:
            warning_bridge.enabled = False
            print(f"[EXPERIMENTAL] Falling warning model unavailable: preload_failed:{type(preload_error).__name__}")
        UDPRecevier.start_backend(warning_bridge=warning_bridge)
    except Exception as e:
        print(f"[ERROR] [Master Control] Infinite Fall Server encountered a fatal error: {e}")

def run_runningball_server():
    try:
        runningball_ai.start_backend()
    except Exception as e:
        print(f"[ERROR] [Master Control] Path Following Server encountered a fatal error: {e}")

def run_car_dodging_server():
    try:
        car_backend.start_backend()
    except Exception as e:
        print(f"[ERROR] [Master Control] Car Dodging Server encountered a fatal error: {e}")

if __name__ == "__main__":
    print("==================================================")
    print(" [SYSTEM] Initializing VectorAI Microservice Master Control Engine...")
    print(" [INFO] 1. Login & Database Bus (Port: 6000)")
    print(" [INFO] 2. Infinite Fall Neurofeedback Calculation Engine (Ports: 5005/5006)")
    print(" [INFO] 3. Path Following Dynamic Balance Calculation Engine (Ports: 5007/5008)")
    print(" [INFO] 4. Car Dodging Adaptive Driving Engine (Ports: 5009/5010)") # 【新增】
    print("==================================================\n")

    # Create four independent background daemon threads
    thread_login = threading.Thread(target=run_login_server, daemon=True)
    thread_falling = threading.Thread(target=run_falling_server, daemon=True)
    thread_runningball = threading.Thread(target=run_runningball_server, daemon=True)
    thread_car = threading.Thread(target=run_car_dodging_server, daemon=True) # 【新增】

    # Staggered startup to prevent console log overlapping (错峰启动)
    thread_login.start()
    time.sleep(0.5)
    
    thread_falling.start()
    time.sleep(0.5)
    
    thread_runningball.start()
    time.sleep(0.5)

    thread_car.start() # 【新增】
    time.sleep(0.5)

    print("\n[SUCCESS] All 4 core microservices are successfully online.")
    print("[SYSTEM] System is now in standby listening mode...")
    print("[NOTICE] To terminate gracefully, close this window or press Ctrl+C.\n")

    # Infinite loop to keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SYSTEM] Termination signal received. VectorAI is safely disconnecting all services...")
        sys.exit(0)
