import os
from typing import Dict, Any

def update_env_file(updates: Dict[str, str], env_path: str = ".env"):
    """
    Update or create a .env file with the given key-value pairs.
    """
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    current_keys = {}
    for i, line in enumerate(lines):
        if "=" in line and not line.strip().startswith("#"):
            key = line.split("=")[0].strip()
            current_keys[key] = i

    for key, value in updates.items():
        if key in current_keys:
            lines[current_keys[key]] = f"{key}={value}\n"
        else:
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

def get_config_summary() -> Dict[str, str]:
    """
    Get a summary of current configuration.
    """
    return {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "Not Set"),
        "DB_PATH": os.getenv("DB_PATH", "data/lograg.db"),
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO")
    }
