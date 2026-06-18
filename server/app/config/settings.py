"""Single source of truth for all configuration.

Every value comes from environment variables (or server/.env). Nothing in the
codebase should call os.getenv() directly — import `settings` instead.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Neo4j ──────────────────────────────────────────────────────────────────
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    NEO4J_DATABASE: str = "neo4j"

    # ── openFDA ────────────────────────────────────────────────────────────────
    OPENFDA_API_KEY: str = ""
    OPENFDA_API_URL: str = "https://api.fda.gov/drug/label.json"

    # ── LLM / Lobster Trap ─────────────────────────────────────────────────────
    HUGGINGFACE_TOKEN: str
    VEEA_ENDPOINT: str = "http://localhost:8080/v1"
    LLM_MODEL_ID: str = "Qwen/Qwen2.5-7B-Instruct"

    # ── Persistence ────────────────────────────────────────────────────────────
    CHECKPOINT_DB: str = "data/checkpoints.sqlite"
    AUDIT_LOG_DIR: str = "data/audit_logs"
    PATIENTS_FILE: str = "data/patients.json"
    USERS_DB: str = "data/users.sqlite"

    # ── Clinical fact-checking (via HF Inference Providers) ────────────────────
    ENABLE_CLINICAL_VERIFICATION: bool = True
    VERIFIER_MODEL_ID: str = "deepseek-ai/DeepSeek-R1-Distill-Llama-70B"
    VERIFIER_API_URL: str = "https://router.huggingface.co/v1/chat/completions"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
