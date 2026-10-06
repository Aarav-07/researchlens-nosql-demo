"""Configuration. Env-driven only - no business logic here."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_prefix="RL_",
        extra="ignore",
    )

    # --- app ---
    app_name: str = "ResearchLens API"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- storage (MongoDB) ---
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "researchlens"
    mongodb_timeout_ms: int = 5000
    # auto | atlas | local  -- atlas unlocks $search / $vectorSearch aggregation stages
    search_backend: str = "auto"

    # --- sources ---
    arxiv_base_url: str = "http://export.arxiv.org/api/query"
    openalex_base_url: str = "https://api.openalex.org/works"
    # OpenAlex asks for a contact email to enter the polite pool.
    openalex_mailto: str = ""
    http_timeout_seconds: float = 30.0
    user_agent: str = "ResearchLens/0.2 (+https://github.com/researchlens)"

    # --- embeddings ---
    # auto | sentence_transformers | hashing
    embedding_backend: str = "auto"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim_fallback: int = 384
    embedding_batch_size: int = 32

    # --- search / ranking ---
    default_page_size: int = 20
    max_page_size: int = 100
    hybrid_semantic_weight: float = 0.7
    hybrid_keyword_weight: float = 0.3
    recency_half_life_days: float = 1095.0  # ~3 years
    recency_weight: float = 0.06
    citation_weight: float = 0.04
    vector_candidate_pool: int = 400  # oversample before re-ranking
    # Absolute cosine floor for a result to be shown at all. Vector search
    # always returns the nearest K, so without this an off-topic query returns a
    # full page of unrelated papers.
    search_min_similarity: float = 0.28

    # --- live coverage (fetch from the internet at search time) ---
    live_search_enabled: bool = True
    live_min_results: int = 8          # fewer good local matches than this = thin
    live_min_top_score: float = 0.45   # best local cosine below this = thin
    # A hit only counts toward coverage if it is this close. Papers scraping
    # past the display floor are not evidence that the topic is covered.
    live_good_similarity: float = 0.52
    live_limit_per_source: int = 25
    live_cooldown_hours: float = 12.0  # same query is not re-fetched sooner

    # --- recommendations ---
    rec_candidate_pool: int = 150
    rec_group_size: int = 6
    rec_recent_months: int = 30
    rec_foundational_min_citations: int = 50
    # Similarity floors per group. Foundational is the drift-prone one: a highly
    # cited paper from a neighbouring field will out-cite everything in topic,
    # so it needs a stricter floor than the rest.
    rec_min_similarity: float = 0.30
    rec_foundational_min_similarity: float = 0.42
    rec_adjacent_min_similarity: float = 0.38

    # --- pdf proxy ---
    pdf_max_bytes: int = 40 * 1024 * 1024
    pdf_timeout_seconds: float = 45.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
