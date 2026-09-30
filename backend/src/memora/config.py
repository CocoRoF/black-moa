"""Bootstrap settings — env only. Everything else lives in ``system_settings`` (DB)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORA_", env_file=".env", extra="ignore")

    public_url: str = "http://localhost:3000"
    secret_key: str = Field(default="dev-secret-change-me-dev-secret-change-me")
    encryption_key: str = Field(default="")  # primary Fernet key; derived from secret_key when empty
    encryption_key_previous: str = Field(default="")  # comma-separated decrypt-only Fernet keys during rotation
    bootstrap_token: str = Field(default="")  # required for the first admin when public_url is https
    # Seeded administrator. Present on every install so a fresh deployment has a
    # working console login; the console keeps warning until the password changes.
    default_admin_enabled: bool = True
    default_admin_email: str = "admin@geny.com"
    default_admin_password: str = "admin123"
    default_admin_name: str = "관리자"
    database_url: str = "postgresql+asyncpg://memora:memora@localhost:5432/memora"
    # The connection pool, owned by core.database.manager. Sized for one process: the API
    # and the worker each get their own, so Postgres sees roughly twice these numbers.
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_s: float = 10.0
    # A connection open for hours is the one a proxy or firewall drops without telling
    # anyone, so they are retired long before that.
    db_pool_recycle_s: int = 1800
    db_connect_timeout_s: float = 10.0
    # A brief outage — a restart, a failover — should make requests slow, not failed.
    db_connect_attempts: int = 4
    # Nothing may hold a connection forever: a query that runs this long is a bug holding a
    # slot that everything else is queuing for, and it fails instead.
    db_statement_timeout_s: float = 120.0
    db_idle_tx_timeout_s: float = 300.0
    db_health_interval_s: float = 15.0
    db_failures_before_reset: int = 3
    data_dir: Path = Path("/data")
    # Object storage. Empty endpoint keeps uploads on local disk, which is correct for one
    # machine and wrong the moment there are two: a pod serving a file another pod wrote to
    # its own filesystem is a 404 nobody can reproduce.
    s3_endpoint: str = ""
    s3_bucket: str = "memora"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    claude_home: Path = Path("/root/.claude")
    claude_binary: str = "claude"
    internal_api_url: str = "http://127.0.0.1:8000"
    log_level: str = "INFO"
    debug: bool = False
    timezone: str = "Asia/Seoul"
    worker_id: str = Field(default_factory=lambda: os.environ.get("HOSTNAME", "worker"))
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    visitor_token_days: int = 90
    # Jobs this worker runs at once. Most are waiting on something — a model, a website,
    # an SMTP server — so this sits above the core count; the per-kind, per-class and
    # reserved-slot rules in ``worker.__main__`` are what stop one sort of work taking all
    # of them.
    worker_concurrency: int = 8
    # A live conversation holds a CLI process, so this is a memory budget rather than a
    # policy. At roughly 150MB resident per session, 300 was an order of magnitude more
    # than this host can hold; the container's own memory limit would be hit long first,
    # which is an OOM kill instead of a clean "busy". Idle eviction keeps the real number
    # far below it.
    runtime_max_sessions: int = 40
    # A conversation holds a CLI process and a pooled account for its whole life, so an
    # idle one is a cost with nothing on the other side. Ten minutes: long enough that
    # coming back to a chat is still warm, short enough to give the account back.
    runtime_idle_minutes: int = 10
    cli_prewarm: bool = False
    fake_llm: bool = False

    # User-controlled outbound URLs are restricted to these ports. Add ports
    # explicitly (for example "80,443,8443") instead of allowing arbitrary
    # internal service ports.
    outbound_allowed_ports: str = "80,443"

    # Untrusted document parsers execute in a child process with these ceilings.
    parser_timeout_seconds: int = 20
    parser_memory_mb: int = 512
    parser_max_output_bytes: int = 8 * 1024 * 1024

    @property
    def vault_root(self) -> Path:
        return self.data_dir / "vaults"

    @property
    def upload_root(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cache_root(self) -> Path:
        return self.data_dir / "cache"


@lru_cache
def get_settings() -> Settings:
    return Settings()
