from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Blacklist Monitor"
    secret_key: str = "CHANGE-ME-IN-PRODUCTION-please-set-SECRET_KEY-env-var"
    fernet_key: str = "dhrrsFeU8r6_YYYuNYhkZbQCgt89wJ4r9t7Pkhki_DM="  # dev-only default, override in prod (see .env.example)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8

    database_url: str = "sqlite:///./blacklist_monitor.db"

    # First-boot admin account. If admin_password is empty, a random one is
    # generated and logged once at startup (see app/seed.py).
    admin_email: str = "admin@seudominio.com"
    admin_password: str = ""

    # DNS resolution
    # Comma-separated list of resolver IPs. Empty = use system resolver.
    # PRODUCTION NOTE: Spamhaus/SORBS block queries from public resolvers (8.8.8.8, 1.1.1.1)
    # and high-volume shared resolvers. Point this at a dedicated local Unbound instance
    # with no forwarding to public resolvers (see PLANEJAMENTO doc, section 2.3).
    dns_resolvers: str = ""
    dns_timeout_seconds: float = 5.0
    spamhaus_dqs_key: str = ""

    # Scheduler
    default_check_interval_minutes: int = 60
    listed_ip_recheck_minutes: int = 15
    ping_cache_minutes: int = 30
    ping_timeout_seconds: float = 2.0
    ping_attempts: int = 2

    # Safety cap for CIDR expansion (in number of addresses). /22 IPv4 = 1024.
    max_cidr_expansion: int = 1024

    # Notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from: str = "blacklist-monitor@localhost"
    pushover_app_token: str = ""

    cors_origins: str = "*"

    # Observability
    # log_level: "nada" (desliga), "erro", "info" (padrão) ou "log" (debug/verboso).
    log_level: str = "info"
    log_file_path: str = "/var/log/blacklistmonitor.log"
    timezone: str = "UTC"

    # UI language. One of: pt-BR, en, es, fr, de.
    language: str = "pt-BR"


@lru_cache
def get_settings() -> Settings:
    return Settings()
