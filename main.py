"""
Run the trading bot from the repository root.

Adds `bot_app/` and `PocketOptionAPI/` to `sys.path`, then starts the async main.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bot_app"))
sys.path.insert(0, str(ROOT / "PocketOptionAPI"))

from app_main import main  # noqa: E402


if __name__ == "__main__":
    asyncio.run(main())
