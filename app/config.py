from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
# The published snapshot is immutable; only caches/indexes/logs use runtime storage.
IS_VERCEL = os.environ.get("VERCEL") == "1"
RUNTIME_DIR = Path(os.environ.get(
    "CONTEXTLENS_RUNTIME_DIR",
    str(Path(tempfile.gettempdir()) / "contextlens") if IS_VERCEL else str(DATA_DIR),
))
RAW_DIR = RUNTIME_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = RUNTIME_DIR / "index"
LOG_DIR = RUNTIME_DIR / "logs"
DB_PATH = INDEX_DIR / "contextlens_demo.sqlite"


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    use_live_api: bool
    deepseek_api_key: str | None
    use_deepseek: bool
    deepseek_model: str
    project_root: Path = PROJECT_ROOT
    db_path: Path = DB_PATH


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def ensure_dirs() -> None:
    for path in (RAW_DIR, INDEX_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    _load_dotenv()
    ensure_dirs()
    use_live = os.environ.get(
        "CONTEXTLENS_USE_LIVE_API",
        os.environ.get("STABLETRADE_USE_LIVE_API", "0"),
    ).strip().lower()
    use_deepseek = os.environ.get(
        "CONTEXTLENS_USE_DEEPSEEK",
        os.environ.get("STABLETRADE_USE_DEEPSEEK", "1"),
    ).strip().lower()
    return Settings(
        api_key=os.environ.get("SHLIB_API_KEY") or None,
        use_live_api=use_live in {"1", "true", "yes", "y"},
        deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY") or None,
        use_deepseek=use_deepseek in {"1", "true", "yes", "y"},
        deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
    )
