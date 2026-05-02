"""
harness/config.py — single source of truth for all paths and tunables.

Every module imports from here instead of computing os.path.dirname(__file__)
individually. DATA_DIR is the only path that needs changing to relocate all
runtime state.
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"

# Load .env into os.environ so bare os.environ.get() calls (e.g. S2_API_KEY) work
# alongside pydantic-settings.  dotenv is already installed as a pydantic-settings dep.
_env_file = ROOT / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)
    except ImportError:
        pass  # python-dotenv not installed; pydantic-settings still reads it for Settings

# Runtime data — all written here, all gitignored
RUNS_FILE                 = DATA_DIR / "runs.jsonl"
SESSIONS_FILE             = DATA_DIR / "sessions.jsonl"
PLANS_FILE                = DATA_DIR / "plans.jsonl"
ARTIFACTS_FILE            = DATA_DIR / "artifacts.jsonl"
MEMORY_DB                 = DATA_DIR / "memory.db"
SEARCH_CACHE_DB           = DATA_DIR / "search_cache.db"
SEMANTIC_SCHOLAR_CACHE_DB = DATA_DIR / "semantic_scholar_cache.db"
TRACES_DIR                = DATA_DIR / "traces"
LIT_REVIEWS_DIR           = DATA_DIR / "lit_reviews"
CHROMA_DIR                = DATA_DIR / "chroma_memory"
EMAIL_DRAFTS_DIR          = DATA_DIR / "email_drafts"
SCREENSHOTS_DIR           = DATA_DIR / "screenshots"
TRANSCRIPTS_DIR           = DATA_DIR / "transcripts"
MCP_LOG                   = DATA_DIR / "mcp_tasks.jsonl"

# Legacy data from harness-engineering (sibling repo) — read-only historical source
LEGACY_ROOT          = ROOT.parent / "harness-engineering"
LEGACY_RUNS_FILE     = LEGACY_ROOT / "runs.jsonl"
LEGACY_SESSIONS_FILE = LEGACY_ROOT / "sessions.jsonl"
LEGACY_PLANS_FILE    = LEGACY_ROOT / "plans.jsonl"
LEGACY_ARTIFACTS_FILE= LEGACY_ROOT / "artifacts.jsonl"
LEGACY_MCP_LOG       = LEGACY_ROOT / "data" / "mcp_tasks.jsonl"
LEGACY_CURATION_LOG  = LEGACY_ROOT / "data" / "curation_log.jsonl"

# whisper.cpp
WHISPER_CPP_DIR   = ROOT / "whisper.cpp"
WHISPER_CPP_CLI   = Path(os.environ.get(
    "WHISPER_CPP_CLI",
    str(WHISPER_CPP_DIR / "build" / "bin" / "Release" / "whisper-cli.exe"),
))
WHISPER_CPP_MODEL = Path(os.environ.get(
    "WHISPER_CPP_MODEL",
    str(WHISPER_CPP_DIR / "models" / "ggml-base.en.bin"),
))

# Source assets
SKILLS_DIR    = ROOT / "harness" / "skills"
TEMPLATES_DIR = SKILLS_DIR / "templates"
PLUGINS_DIR   = ROOT / "plugins"
MODELS_DIR    = ROOT / "models"
EVAL_OUTPUT   = ROOT / "eval-output"
SCRIPTS_DIR   = ROOT / "scripts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # Ollama
    ollama_host: str = "http://localhost:11434"

    # Models
    producer_model: str   = "pi-qwen3.6"
    evaluator_model: str  = "Qwen3-Coder:30b"
    vision_model: str     = "llama3.2-vision"
    embed_model: str      = "nomic-embed-text"

    # Thresholds
    pass_threshold: float = 8.0
    wiggum_max_rounds: int = 3
    subtask_max_workers: int = 4

    # Feature flags
    research_cache: bool  = True
    wiggum_panel: bool    = False

    # API keys
    semantic_scholar_api_key: str = ""

    # Server
    port: int  = 7860
    host: str  = "0.0.0.0"


settings = Settings()


def ensure_dirs() -> None:
    """Create all runtime directories if they don't exist."""
    for d in (DATA_DIR, TRACES_DIR, LIT_REVIEWS_DIR, CHROMA_DIR, EMAIL_DRAFTS_DIR, SCREENSHOTS_DIR, TRANSCRIPTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
