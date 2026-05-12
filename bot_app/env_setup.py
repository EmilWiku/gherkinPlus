"""Load `.env` into `os.environ` and helpers for required secrets."""
from __future__ import annotations

import os
from pathlib import Path

# Repository root (parent of `bot_app/`)
_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv_early() -> None:
    """Parse a simple key=value `.env` at repo root (no python-dotenv required)."""
    path = _REPO_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ[key] = value


def require_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(
            f"Missing required environment variable {name}. Copy .env.example to .env and fill values."
        )
    return v


def get_pocket_option_ssid() -> str:
    raw = os.environ.get("POCKET_OPTION_SSID", "").strip()
    if raw:
        return raw
    path = os.environ.get("POCKET_OPTION_SSID_FILE", "").strip()
    if path:
        p = Path(path).expanduser()
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "Set POCKET_OPTION_SSID or POCKET_OPTION_SSID_FILE. See .env.example."
    )
