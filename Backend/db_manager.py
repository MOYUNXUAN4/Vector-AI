import os
import json
import datetime

# Store all user data in the database folder beside this file.
# This remains stable even if Python is launched from another directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")

# Ensure the database directory exists; create if it does not.
os.makedirs(DB_DIR, exist_ok=True)


def get_user_filepath(nickname):
    """Returns the stable file path for a user's JSON profile."""
    return os.path.join(DB_DIR, f"{nickname}.json")


def create_default_profile(nickname):
    """Initializes a default health profile for a newly registered user."""
    default_profile = {
        "nickname": nickname,
        "age_group": "65+",
        "total_sessions": 0,
        "high_score": 0,
        "runningball_high_score": 0,
        "last_login": str(datetime.date.today()),
        "q_table": [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0]
        ]
    }

    filepath = get_user_filepath(nickname)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(default_profile, f, indent=4, ensure_ascii=False)

    print(
        f"[SUCCESS] [Database] Local profile generated and allocated "
        f"for new user: [{nickname}]."
    )
    return default_profile


def load_or_create_user(nickname):
    """Loads an existing profile or creates a new profile."""
    filepath = get_user_filepath(nickname)

    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            user_data = json.load(f)

        user_data["last_login"] = str(datetime.date.today())
        save_user_data(nickname, user_data)

        print(
            f"[INFO] [Database] Returning user [{nickname}] "
            f"authenticated. Historical telemetry and Q-Table loaded."
        )
        return user_data

    return create_default_profile(nickname)


def save_user_data(nickname, user_data):
    """Persists user data, scores, sessions, and Q-Table."""
    filepath = get_user_filepath(nickname)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(user_data, f, indent=4, ensure_ascii=False)

    print(
        f"[INFO] [Database] Telemetry and memory data persistently "
        f"updated for user: [{nickname}]."
    )