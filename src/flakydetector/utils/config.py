"""Application configuration with pydantic-settings for type-safe env loading."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GitHubSettings(BaseSettings):
    """GitHub API configuration."""

    model_config = SettingsConfigDict(env_prefix="GITHUB_")

    token: SecretStr = Field(
        default=SecretStr("local_dev_dummy_token"),
        description="GitHub Personal Access Token"
    )


class ClassifierSettings(BaseSettings):
    """ML classifier configuration."""

    model_config = SettingsConfigDict(env_prefix="CLASSIFIER_")

    backend: Literal["catboost", "llm", "ensemble"] = Field(
        default="ensemble",
        description="Classification backend",
    )
    catboost_iterations: int = Field(default=1000, ge=10, le=10000)
    catboost_depth: int = Field(default=8, ge=1, le=16)
    catboost_learning_rate: float = Field(default=0.05, ge=0.001, le=1.0)
    flaky_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Probability threshold for flaky classification",
    )


class LLMDettings(BaseSettings):
    """LLM integration settings."""

    model_config = SettingsConfigDict(env_prefix="LLM_")

    provider: Literal["openai", "anthropic", "local"] = Field(default="openai")
    model_name: str = Field(default="gpt-4o")
    api_key: SecretStr | None = Field(default=None)
    max_tokens: int = Field(default=4096, ge=1, le=128000)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)


class DashboardSettings(BaseSettings):
    """Dashboard/API server settings."""

    model_config = SettingsConfigDict(env_prefix="DASHBOARD_")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(default=["http://localhost:3000"])
    debug: bool = Field(default=False)


class AnalysisSettings(BaseSettings):
    """Code analysis settings."""

    model_config = SettingsConfigDict(env_prefix="ANALYSIS_")

    max_file_size_bytes: int = Field(default=1_000_000, ge=1024)
    max_complexity: int = Field(default=50, ge=1)
    timeout_seconds: float = Field(default=60.0, ge=1.0)
    detect_async_patterns: bool = Field(default=True)
    detect_timing_patterns: bool = Field(default=True)
    detect_state_patterns: bool = Field(default=True)
    detect_network_patterns: bool = Field(default=True)


class Settings(BaseSettings):
    """Main application settings aggregating all subsystems."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Paths
    project_root: Path = Field(default=Path(__file__).parent.parent.parent)
    data_dir: Path = Field(default=Path("./data"))
    models_dir: Path = Field(default=Path("./data/models"))
    logs_dir: Path = Field(default=Path("./data/logs"))

    # Subsystems
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    classifier: ClassifierSettings = Field(default_factory=ClassifierSettings)
    llm: LLMDettings = Field(default_factory=LLMDettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
    )

    @field_validator("data_dir", "models_dir", "logs_dir", mode="after")
    @classmethod
    def ensure_directories_exist(cls, path: Path) -> Path:
        """Create directories if they don't exist."""
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance (singleton pattern)."""
    return Settings()  # type: ignore[call-arg]