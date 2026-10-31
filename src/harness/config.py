"""Configuration for the harness, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# src/harness/config.py -> repo root is three levels up (harness -> src -> root).
REPO_ROOT = Path(__file__).resolve().parents[2]

DEEPSEEK_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


@dataclass
class Config:
    lean_project_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("LEAN_PROJECT_DIR", REPO_ROOT / "infinite_nat"))
    )
    api_key: str = ""
    base_url: str = DEEPSEEK_API_BASE
    model: str = DEFAULT_MODEL
    temperature: float = 0.0
    max_iter: int = 8
    direct_tries: int = 2
    imports: str = "import Mathlib.Tactic"
    timeout: float = 60.0
    llm_retries: int = 3
    llm_backoff: float = 5.0

    @classmethod
    def from_env(cls) -> "Config":
        api_key = (
            os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        return cls(
            lean_project_dir=Path(
                os.environ.get("LEAN_PROJECT_DIR", REPO_ROOT / "infinite_nat")
            ),
            api_key=api_key,
            base_url=(
                os.environ.get("DEEPSEEK_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or DEEPSEEK_API_BASE
            ),
            model=(
                os.environ.get("DEEPSEEK_MODEL")
                or os.environ.get("OPENAI_MODEL")
                or DEFAULT_MODEL
            ),
            temperature=float(os.environ.get("LEAN_TEMP", "0.0")),
            max_iter=int(os.environ.get("LEAN_MAX_ITER", "8")),
            direct_tries=int(os.environ.get("LEAN_DIRECT_TRIES", "2")),
            imports=os.environ.get("LEAN_IMPORT", "import Mathlib.Tactic"),
            timeout=float(os.environ.get("LEAN_TIMEOUT", "60")),
            llm_retries=int(os.environ.get("LEAN_LLM_RETRIES", "3")),
            llm_backoff=float(os.environ.get("LEAN_LLM_BACKOFF", "5")),
        )
