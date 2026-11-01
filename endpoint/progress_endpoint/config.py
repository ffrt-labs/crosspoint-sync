import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path("/data/progress.db")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    api_key: str
    db_path: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        api_key = env.get("PROGRESS_API_KEY", "").strip()
        if not api_key:
            raise ConfigError("PROGRESS_API_KEY is empty: refusing to start without a key")
        return cls(api_key=api_key, db_path=DB_PATH)
