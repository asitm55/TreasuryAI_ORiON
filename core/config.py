"""Environment-backed settings for TreasuryAI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    model: str
    scenario: str
    audit_dir: str
    log_level: str

    def require_api_key(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and set it."
            )
        return self.anthropic_api_key

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("TREASURYAI_MODEL", "claude-sonnet-5"),
            scenario=os.environ.get("TREASURYAI_SCENARIO", "base_case"),
            audit_dir=os.environ.get("TREASURYAI_AUDIT_DIR", "./audit"),
            log_level=os.environ.get("TREASURYAI_LOG_LEVEL", "INFO"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
