"""Settings -- TASK.md 9.

Keys are validated *per path*, not globally: running with ``--provider offline`` must
work on a machine with no ``.env`` at all, since that is what makes CI and a clean-clone
demo possible. So every credential is optional here, and the code that needs one calls
``require()`` at the point of use.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Credentials -- all optional; required only on the paths that use them.
    serpapi_key: str | None = None
    imgbb_key: str | None = None
    private_key: str | None = None
    contract_address: str | None = None

    # Chain
    rpc_url_amoy: str = "https://rpc-amoy.polygon.technology"
    rpc_url_local: str = "http://127.0.0.1:8545"

    # Pipeline tunables
    match_threshold: float = 0.45
    max_candidates: int = 15

    # Paths. Kept off the env by default so the layout matches TASK.md 4.
    data_dir: Path = REPO_ROOT / "data"
    out_dir: Path = REPO_ROOT / "out"

    @property
    def consent_dir(self) -> Path:
        return self.data_dir / "consent"

    @property
    def enrolled_dir(self) -> Path:
        return self.data_dir / "enrolled"

    def require(self, field: str, why: str) -> str:
        """Fetch a credential or fail with a message naming the env var and the reason."""
        value = getattr(self, field, None)
        if not value:
            raise ConfigError(
                f"{field.upper()} is not set, but is required to {why}. "
                f"Add it to .env (see .env.example)."
            )
        return str(value)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """Override the active settings. Used by tests to redirect data_dir to a tmp path."""
    global _settings
    _settings = settings
