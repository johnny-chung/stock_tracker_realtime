from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from dotenv import load_dotenv
import yaml
import os


def _load_live_tracker_db_name() -> str | None:
    """Try to read `mongo.db` from live_tracker/config.yaml if present.

    This allows the realtime service to pick up the same DB name used by
    the `live_tracker` app when no `MONGO_DB_NAME` env var is provided.
    """
    cfg_path = Path(__file__).resolve().parents[1] / ".." / "live_tracker" / "config.yaml"
    # normalize path: project_root/realtime_service/../live_tracker/config.yaml
    cfg_path = cfg_path.resolve()
    if not cfg_path.exists():
        return None
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        mongo = raw.get("mongo", {})
        db = mongo.get("db")
        return str(db) if db else None
    except Exception:
        return None


class Settings(BaseSettings):
    # Mongo connection (read from env or .env). For Atlas use mongodb+srv URI.
    MONGO_URI: str | None = None
    # DB name: prefer explicit env var, else try to read live_tracker config.yaml, else fallback
    MONGO_DB_NAME: str | None = None
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    # Optional Redis URL for pub/sub (e.g. redis://localhost:6379)
    REDIS_URL: str | None = None
    # Channel name used for notifications
    REDIS_CHANNEL: str = "realtime_notifications"

    # Use the pydantic-settings v2 configuration helper to set env file
    model_config = SettingsConfigDict(env_file=".env")


# Load environment variables from the live_tracker .env too (if present)
lt_env = Path(__file__).resolve().parents[1] / ".." / "live_tracker" / ".env"
lt_env = lt_env.resolve()
if lt_env.exists():
    # don't override existing env vars — load but keep existing values
    load_dotenv(lt_env, override=False)

settings = Settings()

# If MONGO_DB_NAME not provided, try to get it from live_tracker config.yaml
if not settings.MONGO_DB_NAME:
    db_name = _load_live_tracker_db_name()
    if db_name:
        # mutate settings object attribute (BaseSettings is frozen after creation but supports env override)
        os.environ.setdefault("MONGO_DB_NAME", db_name)
        settings = Settings()

