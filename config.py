import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Radio Configuration
RADIO_IP: str = os.getenv("RADIO_IP", "192.168.68.71")
RADIO_PIN: str = os.getenv("RADIO_PIN", "1234")
RADIO_PORT: int = int(os.getenv("RADIO_PORT", "80"))

# Calendar Configuration
CALENDAR_URL: str = os.getenv("CALENDAR_URL", "")
CALENDAR_KEYWORD: str = os.getenv("CALENDAR_KEYWORD", "").strip()  # Optional filter like "[Radio]"
SYNC_INTERVAL_MINUTES: int = int(os.getenv("SYNC_INTERVAL_MINUTES", "15"))
LOOKAHEAD_HOURS: int = int(os.getenv("LOOKAHEAD_HOURS", "48"))

# Default Radio Settings
DEFAULT_SOURCE: str = os.getenv("DEFAULT_SOURCE", "DAB")
DEFAULT_VOLUME: int = int(os.getenv("DEFAULT_VOLUME", "12"))

# Environment & Server Settings
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production").lower()
RELOAD: bool = os.getenv("RELOAD", "false" if ENVIRONMENT == "production" else "true").lower() == "true"
SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))
