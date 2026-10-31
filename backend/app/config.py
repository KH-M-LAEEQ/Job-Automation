from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://applypilot:applypilot@localhost:5450/applypilot"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    # Session cookie. Set COOKIE_SECURE=true whenever the site is served over HTTPS.
    cookie_secure: bool = False
    # Run the scheduler in this process. The API container sets this to false and a
    # separate worker process (python -m app.worker) runs background work instead.
    run_scheduler: bool = True
    max_upload_mb: int = 10
    resume_encryption_key: str = ""

    nvidia_api_key: str = ""
    ai_timeout_seconds: int = 60
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    job_extraction_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    resume_parsing_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    match_scoring_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    generation_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"

    file_storage_dir: str = "./storage/resumes"
    cors_origins: str = "http://localhost:3010"

    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    crawl_interval_hours: int = 1
    scoring_batch_size: int = 8
    enrichment_batch_size: int = 8
    discovery_max_jobs: int = 120
    discovery_run_timeout_minutes: int = 45
    discovery_retry_hours: int = 6
    portfolio_refresh_hours: int = 24
    # Concurrent users served at once; one user's slow work never blocks another's.
    search_workers: int = 3
    backlog_workers: int = 3
    # A backlog pass yields its user lock after this long so that user's searches can start.
    backlog_pass_seconds: int = 120
    # Real-browser page checks are slow (tens of seconds); cap them per user per pass.
    rendered_fetches_per_pass: int = 3
    # Web searches per user per pass to find the employer's copy of an aggregator posting.
    original_lookups_per_pass: int = 2

    tavily_api_key: str = ""

    # Fernet key used to encrypt the SMTP password on a connected EmailAccount at rest.
    # Generate with: python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
    # Required (no default) - a missing/changed key must fail startup loudly rather than
    # silently produce undecryptable stored passwords.
    email_encryption_key: str
    followup_interval_hours: int = 6

    def assert_secure(self) -> None:
        """Refuse to run the API or worker with a guessable signing secret."""
        weak = {"", "dev-secret-change-me", "change-me-to-a-long-random-string", "changeme", "secret"}
        if self.jwt_secret in weak or len(self.jwt_secret) < 32 or "change-me" in self.jwt_secret:
            raise RuntimeError(
                "JWT_SECRET is missing or a placeholder. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if not self.resume_encryption_key:
            raise RuntimeError("RESUME_ENCRYPTION_KEY is required to store CV files encrypted")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
