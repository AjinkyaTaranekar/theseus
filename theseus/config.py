"""Settings from environment variables and `.env`; the table in docs/spec/07-github-and-deploy.md."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting Theseus reads. Secrets are SecretStr, so they never print."""

    # A blank value, as in a fresh copy of .env.example, means "use the default".
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    theseus_mode: Literal["replay", "record", "live"] = "replay"

    llm_model: str = "openai/zai-org/GLM-5.3"
    llm_fast_model: str = "openai/zai-org/GLM-5.3-Flash"
    llm_api_base: str = "https://api.inference.crusoecloud.com/v1"
    llm_api_key: SecretStr | None = None

    typesafe_api_key: SecretStr | None = None
    jev_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"

    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_username: str = ""
    falkordb_password: SecretStr | None = None
    falkordb_tls: bool = False

    github_app_id: str | None = None
    github_app_private_key_path: Path | None = None
    github_webhook_secret: SecretStr | None = None

    theseus_token: SecretStr | None = None
    theseus_repos: str = ""
    theseus_world_root: str = "demo-infra"
    # The advisory feed the posture run checks main's workflows against: one JSON file per advisory.
    theseus_advisories: str = "advisories"
    domain: str = ""

    @property
    def repos(self) -> list[str]:
        """THESEUS_REPOS as a list: the repos the backend will act on."""
        return [r.strip() for r in self.theseus_repos.split(",") if r.strip()]


def get_settings() -> Settings:
    """Settings for this process, read from the environment and `.env`."""
    return Settings()
